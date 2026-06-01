const Device = require('../models/Device');
const { publishToDevice } = require('../utils/mqttPublisher');

// @route   GET /api/devices
// @desc    Get all devices
// @access  Private (Admin only or All depending on requirement, usually viewer can view, admin can edit)
exports.getDevices = async (req, res) => {
  try {
    let query = {};

    // Regular (non-admin) users → only their assigned devices
    if (req.user && req.user.role !== 'admin' && req.user.role !== 'superadmin') {
      const assignedDevices = req.user.assignedDevices || [];
      query = { _id: { $in: assignedDevices } };
    }

    // Admin (not superadmin) → only devices assigned to them by superadmin
    if (req.user && req.user.role === 'admin') {
      const assignedDevices = req.user.assignedDevices || [];
      query = { _id: { $in: assignedDevices } };
    }

    const devices = await Device.find(query).sort({ createdAt: -1 });
    res.status(200).json({ success: true, count: devices.length, data: devices });
  } catch (err) {
    res.status(500).json({ success: false, message: 'Server Error' });
  }
};

// @route   POST /api/devices
// @desc    Create new device
// @access  Private (Admin only)
exports.createDevice = async (req, res) => {
  try {
    const device = await Device.create(req.body);
    res.status(201).json({ success: true, data: device });
  } catch (err) {
    res.status(400).json({ success: false, message: err.message });
  }
};

// @route   PUT /api/devices/:id
// @desc    Update device
// @access  Private (Admin only)
exports.updateDevice = async (req, res) => {
  try {
    const device = await Device.findByIdAndUpdate(req.params.id, req.body, {
      returnDocument: 'after',
      runValidators: true,
    });
    if (!device) return res.status(404).json({ success: false, message: 'Device not found' });
    res.status(200).json({ success: true, data: device });
  } catch (err) {
    res.status(400).json({ success: false, message: err.message });
  }
};

// @route   DELETE /api/devices/:id
// @desc    Delete device
// @access  Private (Admin only)
exports.deleteDevice = async (req, res) => {
  try {
    const device = await Device.findByIdAndDelete(req.params.id);
    if (!device) return res.status(404).json({ success: false, message: 'Device not found' });
    res.status(200).json({ success: true, message: 'Device deleted' });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
};

// @route   PUT /api/devices/:id/block
// @desc    Toggle block status of a device
// @access  Private (Admin only)
exports.toggleBlockDevice = async (req, res) => {
  try {
    const device = await Device.findById(req.params.id);
    if (!device) return res.status(404).json({ success: false, message: 'Device not found' });
    
    device.status = device.status === 'blocked' ? 'offline' : 'blocked';
    await device.save();
    
    res.status(200).json({ success: true, data: device });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
};

// @route   PUT /api/devices/:id/push-config
// @desc    Push ThingSpeak config to the physical device via MQTT
// @access  Private (Admin only)
exports.pushThingspeakConfig = async (req, res) => {
  try {
    const device = await Device.findById(req.params.id);
    if (!device) {
      return res.status(404).json({ success: false, message: 'Device not found' });
    }

    const { channelId, readApiKey, writeApiKey, port, username, password, clientId } = device.thingspeak || {};
    if (!channelId || !readApiKey || !writeApiKey || !port || !username || !password || !clientId) {
      return res.status(400).json({
        success: false,
        message: 'Device does not have complete ThingSpeak configuration (all fields required)',
      });
    }

    // Publish to the Pi's MQTT topic
    // We prioritize the custom mqttId set by the user (e.g. device1, almora1)
    const deviceRoot = device.mqttId || device._id;
    const payload = {
      channelId,
      readApiKey,
      writeApiKey,
      port,
      username,
      password,
      clientId,
      deviceName: device.name,
      pushedAt: new Date().toISOString(),
    };

    if (device.deviceType === 'office_control' || device.deviceType === 'system2') {
      await publishToDevice(`inhydro/${deviceRoot}/room1/setpoints/update`, payload);
      await publishToDevice(`inhydro/${deviceRoot}/room2/setpoints/update`, payload);
    } else {
      await publishToDevice(`inhydro/${deviceRoot}/setpoints/update`, payload);
    }

    res.status(200).json({
      success: true,
      message: `ThingSpeak config pushed to device "${device.name}" via MQTT`,
      topic: `inhydro/${deviceRoot}/setpoints/update`,
    });
  } catch (err) {
    console.error('Push config error:', err);
    res.status(500).json({
      success: false,
      message: err.message || 'Failed to push config to device',
    });
  }
};

