const jwt = require('jsonwebtoken');
const User = require('../models/User');
const Admin = require('../models/Admin');

/**
 * Protect routes – verifies the JWT in the Authorization header.
 * Usage: router.get('/me', protect, authController.getMe)
 */
const protect = async (req, res, next) => {
  try {
    let token;

    // Support both  Authorization: Bearer <token>  and  cookie token
    if (
      req.headers.authorization &&
      req.headers.authorization.startsWith('Bearer ')
    ) {
      token = req.headers.authorization.split(' ')[1];
    }

    if (!token) {
      return res.status(401).json({
        success: false,
        message: 'Access denied. No token provided.',
      });
    }

    // Verify token
    const decoded = jwt.verify(token, process.env.JWT_SECRET);

    // Attach account to request (exclude password)
   if (decoded.accountType === 'admin' || decoded.accountType === 'superadmin') {
      req.user = await Admin.findById(decoded.id).select('-password');
    } else if (decoded.accountType === 'user') {
      req.user = await User.findById(decoded.id).select('-password');
    } else {
      // Backward compatibility for tokens generated before accountType was added.
      req.user = await User.findById(decoded.id).select('-password');
      if (!req.user) {
        req.user = await Admin.findById(decoded.id).select('-password');
      }
    }

    if (!req.user) {
      return res.status(401).json({
        success: false,
        message: 'User belonging to this token no longer exists.',
      });
    }

    if (!req.user.isActive) {
      return res.status(403).json({
        success: false,
        message: 'Your account has been deactivated.',
      });
    }

    next();
  } catch (err) {
    return res.status(401).json({
      success: false,
      message: 'Invalid or expired token.',
    });
  }
};

/**
 * Role-based authorisation.
 * Usage: router.delete('/user/:id', protect, restrictTo('admin'), ...)
 */
const restrictTo = (...roles) => {
  return (req, res, next) => {
    if (!roles.includes(req.user.role)) {
      return res.status(403).json({
        success: false,
        message: `Access denied. Required roles: ${roles.join(', ')}.`,
      });
    }
    next();
  };
};

module.exports = { protect, restrictTo };
