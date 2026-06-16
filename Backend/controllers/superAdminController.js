const Admin = require('../models/Admin');
const User = require('../models/User');
const Device = require('../models/Device');

// @desc    Get all admins
// @route   GET /api/superadmin/admins
// @access  Private/SuperAdmin
exports.getAdmins = async (req, res) => {
  try {
    const admins = await Admin.find({ _id: { $ne: req.user._id } })
      .populate('assignedDevices', 'name location status')
      .select('-password');

    const adminsWithCounts = await Promise.all(
      admins.map(async (admin) => {
        const userCount = await User.countDocuments({ createdBy: admin._id });
        const obj = admin.toObject();
        obj.status = obj.isActive ? 'active' : 'inactive';
        obj.userCount = userCount;
        return obj;
      })
    );

    res.status(200).json({
      success: true,
      count: adminsWithCounts.length,
      data: adminsWithCounts,
    });
  } catch (err) {
    res.status(500).json({ success: false, message: 'Server error' });
  }
};

// @desc    Create new admin
// @route   POST /api/superadmin/admins
// @access  Private/SuperAdmin
exports.createAdmin = async (req, res) => {
  try {
    const { name, email, password, role, maxUsersAllowed } = req.body;

    const existingAdmin = await Admin.findOne({ email });
    if (existingAdmin) {
      return res.status(400).json({ success: false, message: 'Admin already exists' });
    }

    const admin = await Admin.create({
      name,
      email,
      password,
      role: role || 'admin',
      maxUsersAllowed: maxUsersAllowed !== undefined ? Number(maxUsersAllowed) : 1,
    });

    res.status(201).json({
      success: true,
      data: {
        _id: admin._id,
        name: admin.name,
        email: admin.email,
        role: admin.role,
      },
    });
  } catch (err) {
    res.status(400).json({ success: false, message: err.message || 'Invalid data' });
  }
};

// @desc    Update admin
// @route   PUT /api/superadmin/admins/:id
// @access  Private/SuperAdmin
exports.updateAdmin = async (req, res) => {
  try {
    const { name, email, role, password, maxUsersAllowed } = req.body;
    const admin = await Admin.findById(req.params.id);

    if (!admin) {
      return res.status(404).json({ success: false, message: 'Admin not found' });
    }

    if (name) admin.name = name;
    if (email) admin.email = email;
    if (role) admin.role = role;
    if (password) admin.password = password; // pre-save hook handles hashing
    if (maxUsersAllowed !== undefined) admin.maxUsersAllowed = Number(maxUsersAllowed);

    await admin.save();

    // remove password from response
    admin.password = undefined;

    res.status(200).json({ success: true, data: admin });
  } catch (err) {
    res.status(500).json({ success: false, message: 'Server error updating admin' });
  }
};

// @desc    Delete admin
// @route   DELETE /api/superadmin/admins/:id
// @access  Private/SuperAdmin
exports.deleteAdmin = async (req, res) => {
  try {
    if (req.params.id === req.user.id) {
      return res.status(400).json({ success: false, message: 'Cannot delete yourself' });
    }

    const admin = await Admin.findByIdAndDelete(req.params.id);
    if (!admin) {
      return res.status(404).json({ success: false, message: 'Admin not found' });
    }

    res.status(200).json({ success: true, data: {} });
  } catch (err) {
    res.status(500).json({ success: false, message: 'Server error' });
  }
};

// @desc    Get system wide stats
// @route   GET /api/superadmin/stats
// @access  Private/SuperAdmin
exports.getSystemStats = async (req, res) => {
  try {
    const adminCount = await Admin.countDocuments();
    const userCount = await User.countDocuments();
    const deviceCount = await Device.countDocuments();
    const onlineDevices = await Device.countDocuments({ status: 'online' });

    res.status(200).json({
      success: true,
      data: {
        admins: adminCount,
        users: userCount,
        devices: deviceCount,
        onlineDevices,
      },
    });
  } catch (err) {
    res.status(500).json({ success: false, message: 'Server error' });
  }
};

// @desc    Assign locations & devices to an admin
// @route   PUT /api/superadmin/admins/:id/assign
// @access  Private/SuperAdmin
exports.assignToAdmin = async (req, res) => {
  try {
    const { assignedLocations, assignedDevices } = req.body;

    const updateData = {};
    if (assignedLocations !== undefined) updateData.assignedLocations = assignedLocations;
    if (assignedDevices !== undefined) updateData.assignedDevices = assignedDevices;

    const admin = await Admin.findByIdAndUpdate(req.params.id, updateData, {
      returnDocument: 'after',
      runValidators: true,
    })
      .populate('assignedDevices', 'name location status')
      .select('-password');

    if (!admin) {
      return res.status(404).json({ success: false, message: 'Admin not found.' });
    }

    const obj = admin.toObject();
    obj.status = obj.isActive ? 'active' : 'inactive';

    res.status(200).json({ success: true, data: obj });
  } catch (err) {
    console.error('[AssignToAdmin Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error assigning to admin.' });
  }
};

// @desc    Toggle admin active/inactive status
// @route   PUT /api/superadmin/admins/:id/toggle-status
// @access  Private/SuperAdmin
exports.toggleAdminStatus = async (req, res) => {
  try {
    const admin = await Admin.findById(req.params.id);
    if (!admin) {
      return res.status(404).json({ success: false, message: 'Admin not found.' });
    }

    // prevent toggling own status
    if (admin._id.toString() === req.user._id.toString()) {
      return res.status(400).json({ success: false, message: 'Cannot block yourself' });
    }

    admin.isActive = !admin.isActive;
    await admin.save({ validateBeforeSave: false });

    const obj = admin.toObject();
    obj.status = obj.isActive ? 'active' : 'inactive';
    obj.password = undefined;

    res.status(200).json({ success: true, data: obj });
  } catch (err) {
    console.error('[ToggleStatus Error]', err.message);
    res.status(500).json({ success: false, message: 'Server error toggling status.' });
  }
};
