const Device = require('../models/Device');
const SensorPacket = require('../models/SensorPacket');
const MqttPacket = require('../models/MqttPacket');
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
    console.log('[DEBUG] createDevice incoming req.body:', req.body);
    const device = await Device.create(req.body);
    console.log('[DEBUG] createDevice saved document:', device);
    res.status(201).json({ success: true, data: device });
  } catch (err) {
    console.error('[DEBUG] createDevice error:', err.message);
    res.status(400).json({ success: false, message: err.message });
  }
};

// @route   PUT /api/devices/:id
// @desc    Update device
// @access  Private (Admin only)
exports.updateDevice = async (req, res) => {
  try {
    console.log('[DEBUG] updateDevice ID:', req.params.id);
    console.log('[DEBUG] updateDevice incoming req.body:', req.body);
    const device = await Device.findByIdAndUpdate(req.params.id, req.body, {
      returnDocument: 'after',
      runValidators: true,
    });
    if (!device) {
      console.log('[DEBUG] updateDevice device not found');
      return res.status(404).json({ success: false, message: 'Device not found' });
    }
    console.log('[DEBUG] updateDevice saved document:', device);
    res.status(200).json({ success: true, data: device });
  } catch (err) {
    console.error('[DEBUG] updateDevice error:', err.message);
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

// @route   GET /api/devices/:id/analytics
// @desc    Get device telemetry packets (analytics) from DB
// @access  Private
exports.getDeviceAnalytics = async (req, res) => {
  try {
    const device = await Device.findById(req.params.id);
    if (!device) {
      return res.status(404).json({ success: false, message: 'Device not found' });
    }

    const channelId = device.thingspeak?.channelId || device.tempChannelId;
    const readApiKey = device.thingspeak?.readApiKey || device.tempReadApiKey;

    // Parse date filters, default to last 24 hours
    const start = req.query.start ? new Date(req.query.start) : new Date(Date.now() - 24 * 60 * 60 * 1000);
    const end = req.query.end ? new Date(req.query.end) : new Date();

    // Map Mongoose documents to standard ThingSpeak feeds format
    let feeds = [];

    if (device.deviceType === 'office_control' || device.deviceType === 'multi_sensor') {
      const query = {
        deviceId: device._id,
        timestamp: { $gte: start, $lte: end },
      };

      if (device.deviceType === 'office_control') {
        // Filter by topic containing selected room to avoid mixed graph lines
        const room = req.query.room === 'room2' ? 'room2' : 'room1';
        query.topic = { $regex: room, $options: 'i' };
      }

      const packets = await MqttPacket.find(query).sort({ timestamp: 1 });

      feeds = packets.map((p, idx) => {
        const d = p.data || {};
        if (device.deviceType === 'office_control') {
          return {
            created_at: p.timestamp.toISOString(),
            entry_id: idx + 1,
            field1: d.soil?.soil_temp !== undefined && d.soil?.soil_temp !== null ? String(d.soil.soil_temp) : null,
            field2: d.soil?.moisture !== undefined && d.soil?.moisture !== null ? String(d.soil.moisture) : null,
            field3: d.soil?.ec !== undefined && d.soil?.ec !== null ? String(d.soil.ec) : null,
            field4: d.soil?.ph !== undefined && d.soil?.ph !== null ? String(d.soil.ph) : null,
            field5: d.room?.room_temp !== undefined && d.room?.room_temp !== null ? String(d.room.room_temp) : null,
            field6: d.room?.room_humi !== undefined && d.room?.room_humi !== null ? String(d.room.room_humi) : null,
            field7: d.orp !== undefined && d.orp !== null ? String(d.orp) : null,
            field8: d.co2 !== undefined && d.co2 !== null ? String(d.co2) : null,
          };
        } else {
          // multi_sensor mapping
          return {
            created_at: p.timestamp.toISOString(),
            entry_id: idx + 1,
            field1: d.s1?.t !== undefined && d.s1?.t !== null ? String(d.s1.t) : null,
            field2: d.s2?.t !== undefined && d.s2?.t !== null ? String(d.s2.t) : null,
            field3: d.s3?.t !== undefined && d.s3?.t !== null ? String(d.s3.t) : null,
            field4: d.s4?.t !== undefined && d.s4?.t !== null ? String(d.s4.t) : null,
            field5: d.s5?.t !== undefined && d.s5?.t !== null ? String(d.s5.t) : null,
            field6: d.s6?.t !== undefined && d.s6?.t !== null ? String(d.s6.t) : null,
            field7: d.s7?.t !== undefined && d.s7?.t !== null ? String(d.s7.t) : null,
            field8: null,
          };
        }
      });
    } else {
      const packets = await SensorPacket.find({
        deviceId: device._id,
        timestamp: { $gte: start, $lte: end },
      }).sort({ timestamp: 1 });

      feeds = packets.map((p) => ({
        created_at: p.timestamp.toISOString(),
        entry_id: p.entryId,
        field1: p.field1,
        field2: p.field2,
        field3: p.field3,
        field4: p.field4,
        field5: p.field5,
        field6: p.field6,
        field7: p.field7,
        field8: p.field8,
      }));
    }

    // Try to fetch channel metadata from ThingSpeak to retain custom field names if configured
    let channelData = {
      id: channelId || '',
      name: device.name,
      field1: 'Field 1',
      field2: 'Field 2',
      field3: 'Field 3',
      field4: 'Field 4',
      field5: 'Field 5',
      field6: 'Field 6',
      field7: 'Field 7',
      field8: 'Field 8',
    };

    // Apply default deviceType-based labels
    if (device.deviceType === 'office_control') {
      channelData.field1 = 'Avg Water Temperature';
      channelData.field2 = 'Avg Water Moisture';
      channelData.field3 = 'Avg EC';
      channelData.field4 = 'Avg Ph';
      channelData.field5 = 'Avg Room Temperature';
      channelData.field6 = 'Avg Room Humidity';
      channelData.field7 = 'Avg ORP';
      channelData.field8 = 'Avg CO2';
    } else if (device.deviceType === 'multi_sensor') {
      channelData.field1 = 'Cold Room 1 Temp';
      channelData.field2 = 'Cold Room 2 Temp';
      channelData.field3 = 'Cold Room 3 Temp';
      channelData.field4 = 'Cold Room 4 Temp';
      channelData.field5 = 'Cold Room 5 Temp';
      channelData.field6 = 'Cold Room 6 Temp';
      channelData.field7 = 'Cold Room 7 Temp';
      channelData.field8 = 'Field 8';
    }

    if (channelId && readApiKey) {
      try {
        const metadataUrl = `https://api.thingspeak.com/channels/${channelId}/feeds.json?api_key=${readApiKey}&results=0`;
        const metaRes = await fetch(metadataUrl);
        if (metaRes.ok) {
          const metaResult = await metaRes.json();
          if (metaResult && metaResult.channel) {
            channelData = {
              ...channelData,
              ...metaResult.channel,
            };
          }
        }
      } catch (metaErr) {
        console.warn(`[Analytics API] Failed to fetch channel metadata from ThingSpeak: ${metaErr.message}. Falling back to default field names.`);
      }
    }

    res.status(200).json({
      success: true,
      channel: channelData,
      feeds: feeds,
    });
  } catch (err) {
    console.error('[Analytics API] Error fetching analytics:', err);
    res.status(500).json({ success: false, message: 'Server Error fetching analytics' });
  }
};

