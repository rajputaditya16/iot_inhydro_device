const { validationResult } = require('express-validator');
const jwt = require('jsonwebtoken');
const User = require('../models/User');
const Admin = require('../models/Admin');

// ── Helper: sign JWT ─────────────────────────────────────────────────────────
const signToken = (id, accountType) =>
  jwt.sign({ id, accountType }, process.env.JWT_SECRET, {
    expiresIn: process.env.JWT_EXPIRES_IN || '7d',
  });

// ── Helper: send token response ──────────────────────────────────────────────
const sendTokenResponse = (user, statusCode, res, accountType) => {
  const token = signToken(user._id, accountType);

  // Remove password from output
  user.password = undefined;

  return res.status(statusCode).json({
    success: true,
    token,
    accountType,
    user: {
      id: user._id,
      name: user.name,
      email: user.email,
      role: user.role,
      isActive: user.isActive,
      createdAt: user.createdAt,
      accountType,
    },
  });
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   POST /api/auth/register
// @desc    Register a new user
// @access  Public
// ─────────────────────────────────────────────────────────────────────────────
exports.register = async (req, res) => {
  // 1. Validate inputs
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    return res.status(422).json({
      success: false,
      message: 'Validation failed',
      errors: errors.array(),
    });
  }

  const { name, email, password, role } = req.body;

  try {
    // 2. Check if user already exists
    const existingUser = await User.findOne({ email: email.toLowerCase() });
    if (existingUser) {
      return res.status(409).json({
        success: false,
        message: 'An account with this email already exists.',
      });
    }

    // 3. Create user (password is hashed automatically by the pre-save hook)
    const safeRole = role === 'operator' ? 'operator' : 'viewer';

    const user = await User.create({
      name,
      email,
      password,
      role: safeRole,
    });

    sendTokenResponse(user, 201, res, 'user');
  } catch (err) {
    console.error('[Register Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error during registration.' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   POST /api/auth/login
// @desc    Login user & return JWT
// @access  Public
// ─────────────────────────────────────────────────────────────────────────────
exports.login = async (req, res) => {
  // 1. Validate inputs
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    return res.status(422).json({
      success: false,
      message: 'Validation failed',
      errors: errors.array(),
    });
  }

  const { email, password } = req.body;

  try {
    const normalizedEmail = email.toLowerCase();

    // 2. Find account (admins are stored in dedicated collection)
    let accountType = 'admin';
    let user = await Admin.findOne({ email: normalizedEmail }).select('+password');
    
   if (user && user.role === 'superadmin') {
      accountType = 'superadmin';
    } else if (!user) {
      accountType = 'user';
      user = await User.findOne({ email: normalizedEmail }).select('+password');
    }

    if (!user) {
      return res.status(401).json({
        success: false,
        message: 'Invalid email or password.',
      });
    }

    // 3. Check account status
    if (!user.isActive) {
      return res.status(403).json({
        success: false,
        message: 'Your account has been deactivated. Contact an administrator.',
      });
    }

    // 4. Verify password
    const isMatch = await user.comparePassword(password);
    if (!isMatch) {
      return res.status(401).json({
        success: false,
        message: 'Invalid email or password.',
      });
    }

    // 5. Update last login timestamp
    user.lastLogin = new Date();
    await user.save({ validateBeforeSave: false });

    sendTokenResponse(user, 200, res, accountType);
  } catch (err) {
    console.error('[Login Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error during login.' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   GET /api/auth/me
// @desc    Get currently authenticated user
// @access  Private
// ─────────────────────────────────────────────────────────────────────────────
exports.getMe = async (req, res) => {
  try {
    const user = req.user;
    if (!user) {
      return res.status(404).json({ success: false, message: 'User not found.' });
    }
    res.status(200).json({
      success: true,
      user: {
        id: user._id,
        name: user.name,
        email: user.email,
        role: user.role,
        isActive: user.isActive,
        lastLogin: user.lastLogin,
        createdAt: user.createdAt,
      },
    });
  } catch (err) {
    console.error('[GetMe Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error.' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   POST /api/auth/forgot-password
// @desc    Send OTP to user email
// @access  Public
// ─────────────────────────────────────────────────────────────────────────────
const sendEmail = require('../utils/sendEmail');

exports.forgotPassword = async (req, res) => {
  const { email } = req.body;
  if (!email) return res.status(400).json({ success: false, message: 'Please provide an email' });

  try {
    const normalizedEmail = email.toLowerCase();
    
    // Check Admin first, then User
    let user = await Admin.findOne({ email: normalizedEmail });
    if (!user) user = await User.findOne({ email: normalizedEmail });

    if (!user) {
      // Don't leak whether the email exists or not to prevent user enumeration
      return res.status(200).json({ success: true, message: 'If registered, an OTP is sent.' });
    }

    // Generate 6-digit OTP
    const otp = Math.floor(100000 + Math.random() * 900000).toString();
    const expiresIn = new Date(Date.now() + 10 * 60 * 1000); // 10 minutes

    user.resetPasswordOtp = otp;
    user.resetPasswordExpires = expiresIn;
    await user.save({ validateBeforeSave: false });

    // Send email
    const message = `
      <div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
        <h2 style="color: #60bf71;">Password Reset Request</h2>
        <p>Hello ${user.name},</p>
        <p>You requested a password reset. Your OTP is:</p>
        <h3 style="background: #f4f4f4; padding: 10px; display: inline-block; border-radius: 5px; color: #333; letter-spacing: 2px;">${otp}</h3>
        <p>This OTP is valid for 10 minutes. If you did not request this, please ignore this email.</p>
        <p>Thank you,<br>INHYDRO Smart Soil Team</p>
      </div>
    `;

    try {
      await sendEmail({
        to: user.email,
        subject: 'Password Reset OTP - INHYDRO Smart Soil',
        html: message,
      });

      res.status(200).json({ success: true, message: 'OTP sent to email' });
    } catch (err) {
      user.resetPasswordOtp = undefined;
      user.resetPasswordExpires = undefined;
      await user.save({ validateBeforeSave: false });
      
      console.error('[Email Error]', err);
      res.status(500).json({ success: false, message: 'Email could not be sent' });
    }
  } catch (err) {
    console.error('[Forgot Password Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   POST /api/auth/verify-otp
// @desc    Verify OTP
// @access  Public
// ─────────────────────────────────────────────────────────────────────────────
exports.verifyOtp = async (req, res) => {
  const { email, otp } = req.body;
  if (!email || !otp) return res.status(400).json({ success: false, message: 'Please provide email and OTP' });

  try {
    const normalizedEmail = email.toLowerCase();
    let user = await Admin.findOne({ email: normalizedEmail });
    if (!user) user = await User.findOne({ email: normalizedEmail });

    if (!user) {
      return res.status(400).json({ success: false, message: 'Invalid OTP or email' });
    }

    if (user.resetPasswordOtp !== otp || user.resetPasswordExpires < Date.now()) {
      return res.status(400).json({ success: false, message: 'Invalid or expired OTP' });
    }

    res.status(200).json({ success: true, message: 'OTP verified successfully' });
  } catch (err) {
    console.error('[Verify OTP Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   POST /api/auth/reset-password
// @desc    Reset password using valid OTP
// @access  Public
// ─────────────────────────────────────────────────────────────────────────────
exports.resetPassword = async (req, res) => {
  const { email, otp, password } = req.body;
  
  if (!email || !otp || !password) {
    return res.status(400).json({ success: false, message: 'Please provide email, OTP, and new password' });
  }

  try {
    const normalizedEmail = email.toLowerCase();
    let user = await Admin.findOne({ email: normalizedEmail });
    if (!user) user = await User.findOne({ email: normalizedEmail });

    if (!user) {
      return res.status(400).json({ success: false, message: 'Invalid OTP or email' });
    }

    if (user.resetPasswordOtp !== otp || user.resetPasswordExpires < Date.now()) {
      return res.status(400).json({ success: false, message: 'Invalid or expired OTP' });
    }

    // Set new password
    user.password = password;
    user.resetPasswordOtp = undefined;
    user.resetPasswordExpires = undefined;
    
    await user.save();

    res.status(200).json({ success: true, message: 'Password updated successfully. You can now log in.' });
  } catch (err) {
    console.error('[Reset Password Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   PUT /api/auth/update-profile
// @desc    Update currently authenticated user's profile/password
// @access  Private
// ─────────────────────────────────────────────────────────────────────────────
exports.updateProfile = async (req, res) => {
  try {
    const { name, email, password, currentPassword } = req.body;
    
    // Find user or admin by id depending on the collection
    const id = req.user._id;
    let user = await Admin.findById(id).select('+password');
    let accountType = 'admin';
    
    if (user && user.role === 'superadmin') {
      accountType = 'superadmin';
    } else if (!user) {
      user = await User.findById(id).select('+password');
      accountType = 'user';
    }
    
    if (!user) {
      return res.status(404).json({ success: false, message: 'User not found' });
    }

    // Require current password for security verification
    if (!currentPassword) {
      return res.status(400).json({ success: false, message: 'Current password is required to save changes' });
    }

    const isMatch = await user.comparePassword(currentPassword);
    if (!isMatch) {
      return res.status(401).json({ success: false, message: 'Incorrect current password' });
    }

    // Update profile info
    if (name) user.name = name;
    if (email) {
      const normalizedEmail = email.toLowerCase();
      
      // Check if email is already taken by another account
      const emailExistsAdmin = await Admin.findOne({ email: normalizedEmail, _id: { $ne: id } });
      const emailExistsUser = await User.findOne({ email: normalizedEmail, _id: { $ne: id } });
      
      if (emailExistsAdmin || emailExistsUser) {
        return res.status(400).json({ success: false, message: 'Email is already in use by another account' });
      }
      user.email = normalizedEmail;
    }

    // Update password if provided
    if (password) {
      if (password.length < 6) {
        return res.status(400).json({ success: false, message: 'New password must be at least 6 characters' });
      }
      user.password = password;
    }

    await user.save();

    // Remove password from response
    user.password = undefined;

    res.status(200).json({
      success: true,
      user: {
        id: user._id,
        name: user.name,
        email: user.email,
        role: user.role,
        isActive: user.isActive,
        createdAt: user.createdAt,
        accountType
      }
    });
  } catch (err) {
    console.error('[Update Profile Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error updating profile' });
  }
};
