const { validationResult } = require('express-validator');
const User = require('../models/User');
const Device = require('../models/Device');

// ─────────────────────────────────────────────────────────────────────────────
// @route   GET /api/users
// @desc    Get all users (with optional search & populated devices)
// @access  Private (Admin only)
// ─────────────────────────────────────────────────────────────────────────────
exports.getUsers = async (req, res) => {
  try {
    const { search } = req.query;
    let filter = {};

    if (req.user && req.user.role === 'admin') {
      filter.createdBy = req.user._id;
    }

    if (search) {
      const regex = new RegExp(search, 'i');
      const searchFilter = {
        $or: [{ name: regex }, { email: regex }, { role: regex }],
      };
      if (req.user && req.user.role === 'admin') {
        filter = {
          $and: [
            { createdBy: req.user._id },
            searchFilter
          ]
        };
      } else {
        filter = searchFilter;
      }
    }

    const users = await User.find(filter)
      .populate('assignedDevices', 'name location status')
      .populate('createdBy', 'name role')
      .sort({ createdAt: -1 })
      .select('-password');

    // Map users to include a `status` field derived from `isActive`
    const mapped = users.map((u) => {
      const obj = u.toObject();
      obj.status = obj.isActive ? 'active' : 'inactive';
      return obj;
    });

    res.status(200).json({ success: true, count: mapped.length, data: mapped });
  } catch (err) {
    console.error('[GetUsers Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error fetching users.' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   GET /api/users/:id
// @desc    Get single user by ID
// @access  Private (Admin only)
// ─────────────────────────────────────────────────────────────────────────────
exports.getUser = async (req, res) => {
  try {
    const query = { _id: req.params.id };
    if (req.user && req.user.role === 'admin') {
      query.createdBy = req.user._id;
    }

    const user = await User.findOne(query)
      .populate('assignedDevices', 'name location status')
      .select('-password');

    if (!user) {
      return res.status(404).json({ success: false, message: 'User not found.' });
    }

    const obj = user.toObject();
    obj.status = obj.isActive ? 'active' : 'inactive';

    res.status(200).json({ success: true, data: obj });
  } catch (err) {
    console.error('[GetUser Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error.' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   POST /api/users
// @desc    Admin creates a new user
// @access  Private (Admin only)
// ─────────────────────────────────────────────────────────────────────────────
exports.createUser = async (req, res) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    return res.status(422).json({
      success: false,
      message: 'Validation failed',
      errors: errors.array(),
    });
  }

  const { name, email, password, role, assignedLocations, assignedDevices } = req.body;

  try {
    // Enforce user creation limit for admins
    if (req.user && req.user.role === 'admin') {
      const userCount = await User.countDocuments({ createdBy: req.user._id });
      const maxAllowed = req.user.maxUsersAllowed !== undefined ? req.user.maxUsersAllowed : 1;
      if (userCount >= maxAllowed) {
        return res.status(403).json({
          success: false,
          message: `User limit reached. You are only allowed to create up to ${maxAllowed} user(s). Please contact the Super Admin for permission to create more.`,
        });
      }
    }

    // Check duplicate email
    const existing = await User.findOne({ email: email.toLowerCase() });
    if (existing) {
      return res.status(409).json({ success: false, message: 'A user with this email already exists.' });
    }

    const safeRole = ['admin', 'operator', 'viewer'].includes(role) ? role : 'viewer';

    const user = await User.create({
      name,
      email,
      password,
      role: safeRole,
      assignedLocations: assignedLocations || [],
      assignedDevices: assignedDevices || [],
      createdBy: req.user._id,
    });

    user.password = undefined;

    const obj = user.toObject();
    obj.status = obj.isActive ? 'active' : 'inactive';

    res.status(201).json({ success: true, data: obj });
  } catch (err) {
    console.error('[CreateUser Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error creating user.' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   PUT /api/users/:id
// @desc    Admin updates a user
// @access  Private (Admin only)
// ─────────────────────────────────────────────────────────────────────────────
exports.updateUser = async (req, res) => {
  try {
    const { name, email, role, isActive, assignedLocations, assignedDevices } = req.body;

    const query = { _id: req.params.id };
    if (req.user && req.user.role === 'admin') {
      query.createdBy = req.user._id;
    }

    const updateData = {};
    if (name !== undefined) updateData.name = name;
    if (email !== undefined) updateData.email = email.toLowerCase();
    if (role !== undefined && ['admin', 'operator', 'viewer'].includes(role)) updateData.role = role;
    if (isActive !== undefined) updateData.isActive = isActive;
    if (assignedLocations !== undefined) updateData.assignedLocations = assignedLocations;
    if (assignedDevices !== undefined) updateData.assignedDevices = assignedDevices;

    const user = await User.findOneAndUpdate(query, updateData, {
      returnDocument: 'after',
      runValidators: true,
    })
      .populate('assignedDevices', 'name location status')
      .select('-password');

    if (!user) {
      return res.status(404).json({ success: false, message: 'User not found.' });
    }

    const obj = user.toObject();
    obj.status = obj.isActive ? 'active' : 'inactive';

    res.status(200).json({ success: true, data: obj });
  } catch (err) {
    console.error('[UpdateUser Error]', err.message);
    if (err.code === 11000) {
      return res.status(409).json({ success: false, message: 'Email already in use.' });
    }
    res.status(500).json({ success: false, message: 'Server error updating user.' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   DELETE /api/users/:id
// @desc    Admin deletes a user
// @access  Private (Admin only)
// ─────────────────────────────────────────────────────────────────────────────
exports.deleteUser = async (req, res) => {
  try {
    const query = { _id: req.params.id };
    if (req.user && req.user.role === 'admin') {
      query.createdBy = req.user._id;
    }
    const user = await User.findOneAndDelete(query);
    if (!user) {
      return res.status(404).json({ success: false, message: 'User not found.' });
    }
    res.status(200).json({ success: true, message: 'User deleted successfully.' });
  } catch (err) {
    console.error('[DeleteUser Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error deleting user.' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   PUT /api/users/:id/assign
// @desc    Assign locations & devices to a user
// @access  Private (Admin only)
// ─────────────────────────────────────────────────────────────────────────────
exports.assignToUser = async (req, res) => {
  try {
    const { assignedLocations, assignedDevices } = req.body;

    const query = { _id: req.params.id };
    if (req.user && req.user.role === 'admin') {
      query.createdBy = req.user._id;
    }

    const updateData = {};
    if (assignedLocations !== undefined) updateData.assignedLocations = assignedLocations;
    if (assignedDevices !== undefined) updateData.assignedDevices = assignedDevices;

    const user = await User.findOneAndUpdate(query, updateData, {
      returnDocument: 'after',
      runValidators: true,
    })
      .populate('assignedDevices', 'name location status')
      .select('-password');

    if (!user) {
      return res.status(404).json({ success: false, message: 'User not found.' });
    }

    const obj = user.toObject();
    obj.status = obj.isActive ? 'active' : 'inactive';

    res.status(200).json({ success: true, data: obj });
  } catch (err) {
    console.error('[AssignToUser Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error assigning to user.' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   PUT /api/users/:id/toggle-status
// @desc    Toggle user active/inactive status
// @access  Private (Admin only)
// ─────────────────────────────────────────────────────────────────────────────
exports.toggleUserStatus = async (req, res) => {
  try {
    const query = { _id: req.params.id };
    if (req.user && req.user.role === 'admin') {
      query.createdBy = req.user._id;
    }
    const user = await User.findOne(query);
    if (!user) {
      return res.status(404).json({ success: false, message: 'User not found.' });
    }

    user.isActive = !user.isActive;
    await user.save({ validateBeforeSave: false });

    const obj = user.toObject();
    obj.status = obj.isActive ? 'active' : 'inactive';
    obj.password = undefined;

    res.status(200).json({ success: true, data: obj });
  } catch (err) {
    console.error('[ToggleStatus Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error toggling status.' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   GET /api/users/locations
// @desc    Get unique locations from all devices (for assignment modal)
// @access  Private (Admin only)
// ─────────────────────────────────────────────────────────────────────────────
exports.getLocations = async (req, res) => {
  try {
    let locations;

    // Admin → only locations from their superadmin-assigned devices
    if (req.user && req.user.role === 'admin') {
      const assignedDevices = req.user.assignedDevices || [];
      locations = await Device.distinct('location', { _id: { $in: assignedDevices } });
    } else {
      // Superadmin → all locations
      locations = await Device.distinct('location');
    }

    res.status(200).json({ success: true, data: locations });
  } catch (err) {
    console.error('[GetLocations Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error fetching locations.' });
  }
};
