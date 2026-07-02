const Device = require('../models/Device');
const SensorPacket = require('../models/SensorPacket');
const MqttPacket = require('../models/MqttPacket');
const { getTelemetryModel } = require('../models/TelemetryLog');
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
    const now = new Date();

    const updatedDevices = await Promise.all(
      devices.map(async (device) => {
        let status = device.status;
        
        // If device is online but hasn't sent telemetry in 2 minutes, mark as offline
        if (
          status === 'online' &&
          device.lastUpdated &&
          now - new Date(device.lastUpdated) > 120000
        ) {
          status = 'offline';
          device.status = 'offline';
          await device.save();
        }

        // Fetch latest telemetry packet from the dynamic collection
        const mqttId = device.mqttId || device._id.toString();
        let latestPacket = null;
        try {
          const TelemetryModel = getTelemetryModel(mqttId);
          latestPacket = await TelemetryModel.findOne({ deviceId: device._id }).sort({ timestamp: -1 });
        } catch (e) {
          console.warn(`[DeviceController] Could not fetch latest packet for ${mqttId}: ${e.message}`);
        }

        let latestData = {};
        if (latestPacket && latestPacket.data) {
          latestData = latestPacket.data;
        }

        // Map live stats based on device type
        let liveStats = { temp: 0, moisture: 0, ph: 0, ec: 0 };
        if (device.deviceType === 'office_control' || device.deviceType === 'system2') {
          // Handle room1 structure or root structure
          const room1 = latestData.room1 || latestData || {};
          liveStats.temp = parseFloat(room1.room?.room_temp || room1.temp || 0);
          liveStats.moisture = parseFloat(room1.soil?.moisture || room1.humidity || 0);
          liveStats.ph = parseFloat(room1.soil?.ph || room1.ph || 0);
          liveStats.ec = parseFloat(room1.soil?.ec || room1.ec || 0);
        } else if (device.deviceType === 'controlling') {
          const tel = latestData.telemetry || latestData || {};
          liveStats.temp = parseFloat(tel.water_temp || tel.room_temp || 0);
          liveStats.moisture = parseFloat(tel.moisture || tel.room_humi || 0);
          liveStats.ph = parseFloat(tel.ph || 0);
          liveStats.ec = parseFloat(tel.ec || 0);
        } else if (device.deviceType === 'multi_sensor') {
          liveStats.temp = parseFloat(latestData.s1?.t || 0);
          liveStats.moisture = parseFloat(latestData.s2?.t || 0);
          liveStats.ph = parseFloat(latestData.s3?.t || 0);
          liveStats.ec = parseFloat(latestData.s4?.t || 0);
        } else {
          // Fallback for general devices
          liveStats.temp = parseFloat(latestData.field1 || latestData.temp || 0);
          liveStats.moisture = parseFloat(latestData.field2 || latestData.humidity || 0);
          liveStats.ph = parseFloat(latestData.field3 || latestData.ph || 0);
          liveStats.ec = parseFloat(latestData.field4 || latestData.ec || 0);
        }

        return {
          ...device.toObject(),
          status,
          liveStats,
          latestPacketTime: latestPacket ? latestPacket.timestamp : null
        };
      })
    );

    res.status(200).json({ success: true, count: updatedDevices.length, data: updatedDevices });
  } catch (err) {
    console.error('[DeviceController] getDevices error:', err);
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

    const isControlling = device.deviceType === 'controlling';
    const { channelId, readApiKey, writeApiKey, port, username, password, clientId } = device.thingspeak || {};
    if (!isControlling && (!channelId || !readApiKey || !writeApiKey || !port || !username || !password || !clientId)) {
      return res.status(400).json({
        success: false,
        message: 'Device does not have complete ThingSpeak configuration (all fields required)',
      });
    }

    // Publish to the Pi's MQTT topic
    // We prioritize the custom mqttId set by the user (e.g. device1, almora1)
    const deviceRoot = device.mqttId || device._id;
    const payload = {
      channelId: channelId || '',
      readApiKey: readApiKey || '',
      writeApiKey: writeApiKey || '',
      port: port || 1883,
      username: username || '',
      password: password || '',
      clientId: clientId || '',
      deviceName: device.name,
      pushedAt: new Date().toISOString(),
    };

    if (device.deviceType === 'office_control' || device.deviceType === 'system2') {
      await publishToDevice(`inhydro/${deviceRoot}/room1/setpoints/update`, payload);
      await publishToDevice(`inhydro/${deviceRoot}/room2/setpoints/update`, payload);
      await publishToDevice(`inhydro/${deviceRoot}/room3/setpoints/update`, payload);
    } else if (device.deviceType === 'controlling') {
      await publishToDevice(`inhydro/${deviceRoot}/monitor/setpoints/update`, payload);
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
    const room = req.query.room || 'room1'; // 'room1', 'room2', 'room3' or 'both'

    // Map Mongoose documents to standard ThingSpeak feeds format
    let feeds = [];

    if (true) {
      const mqttId = device.mqttId || device._id.toString();
      const TelemetryModel = getTelemetryModel(mqttId);

      const query = {
        deviceId: device._id,
        timestamp: { $gte: start, $lte: end },
      };

      if (device.deviceType === 'office_control' && room !== 'both') {
        const targetRoom = (room === 'room2' || room === 'room3') ? room : 'room1';
        query.$or = [
          { topic: { $regex: targetRoom, $options: 'i' } },
          { topic: { $regex: 'rooms', $options: 'i' } }
        ];
      }

      let packets = await TelemetryModel.find(query).sort({ timestamp: 1 });

      // Fallback: If no packets exist in the dynamic telemetry collection, query the legacy MqttPacket collection
      if (packets.length === 0) {
        const oldQuery = {
          deviceId: device._id,
          timestamp: { $gte: start, $lte: end },
        };
        if (device.deviceType === 'office_control' && room !== 'both') {
          const targetRoom = (room === 'room2' || room === 'room3') ? room : 'room1';
          oldQuery.topic = { $regex: targetRoom, $options: 'i' };
        }
        packets = await MqttPacket.find(oldQuery).sort({ timestamp: 1 });
      }

      const mappedFeeds = [];
      packets.forEach((p) => {
        const d = p.data || {};
        if (device.deviceType === 'office_control') {
          const isMerged = (d.room1 !== undefined || d.room2 !== undefined || d.room3 !== undefined);

          if (isMerged) {
            if (room === 'both') {
              ['room1', 'room2', 'room3'].forEach((rName) => {
                const roomData = d[rName] || {};
                if (rName === 'room3') {
                  mappedFeeds.push({
                    created_at: p.timestamp.toISOString(),
                    entry_id: mappedFeeds.length + 1,
                    room: rName,
                    field1: roomData.md02_1?.room_temp !== undefined && roomData.md02_1?.room_temp !== null ? String(roomData.md02_1.room_temp) : null,
                    field2: roomData.md02_1?.room_humi !== undefined && roomData.md02_1?.room_humi !== null ? String(roomData.md02_1.room_humi) : null,
                    field3: roomData.md02_2?.room_temp !== undefined && roomData.md02_2?.room_temp !== null ? String(roomData.md02_2.room_temp) : null,
                    field4: roomData.md02_2?.room_humi !== undefined && roomData.md02_2?.room_humi !== null ? String(roomData.md02_2.room_humi) : null,
                    field5: null,
                    field6: null,
                    field7: null,
                    field8: roomData.co2 !== undefined && roomData.co2 !== null ? String(roomData.co2) : null,
                  });
                } else {
                  mappedFeeds.push({
                    created_at: p.timestamp.toISOString(),
                    entry_id: mappedFeeds.length + 1,
                    room: rName,
                    field1: roomData.soil?.soil_temp !== undefined && roomData.soil?.soil_temp !== null ? String(roomData.soil.soil_temp) : null,
                    field2: roomData.soil?.moisture !== undefined && roomData.soil?.moisture !== null ? String(roomData.soil.moisture) : null,
                    field3: roomData.soil?.ec !== undefined && roomData.soil?.ec !== null ? String(roomData.soil.ec) : null,
                    field4: roomData.soil?.ph !== undefined && roomData.soil?.ph !== null ? String(roomData.soil.ph) : null,
                    field5: roomData.room?.room_temp !== undefined && roomData.room?.room_temp !== null ? String(roomData.room.room_temp) : null,
                    field6: roomData.room?.room_humi !== undefined && roomData.room?.room_humi !== null ? String(roomData.room.room_humi) : null,
                    field7: roomData.orp !== undefined && roomData.orp !== null ? String(roomData.orp) : null,
                    field8: roomData.co2 !== undefined && roomData.co2 !== null ? String(roomData.co2) : null,
                  });
                }
              });
            } else {
              const roomData = d[room] || {};
              if (room === 'room3') {
                mappedFeeds.push({
                  created_at: p.timestamp.toISOString(),
                  entry_id: mappedFeeds.length + 1,
                  room: room,
                  field1: roomData.md02_1?.room_temp !== undefined && roomData.md02_1?.room_temp !== null ? String(roomData.md02_1.room_temp) : null,
                  field2: roomData.md02_1?.room_humi !== undefined && roomData.md02_1?.room_humi !== null ? String(roomData.md02_1.room_humi) : null,
                  field3: roomData.md02_2?.room_temp !== undefined && roomData.md02_2?.room_temp !== null ? String(roomData.md02_2.room_temp) : null,
                  field4: roomData.md02_2?.room_humi !== undefined && roomData.md02_2?.room_humi !== null ? String(roomData.md02_2.room_humi) : null,
                  field5: null,
                  field6: null,
                  field7: null,
                  field8: roomData.co2 !== undefined && roomData.co2 !== null ? String(roomData.co2) : null,
                });
              } else {
                mappedFeeds.push({
                  created_at: p.timestamp.toISOString(),
                  entry_id: mappedFeeds.length + 1,
                  room: room,
                  field1: roomData.soil?.soil_temp !== undefined && roomData.soil?.soil_temp !== null ? String(roomData.soil.soil_temp) : null,
                  field2: roomData.soil?.moisture !== undefined && roomData.soil?.moisture !== null ? String(roomData.soil.moisture) : null,
                  field3: roomData.soil?.ec !== undefined && roomData.soil?.ec !== null ? String(roomData.soil.ec) : null,
                  field4: roomData.soil?.ph !== undefined && roomData.soil?.ph !== null ? String(roomData.soil.ph) : null,
                  field5: roomData.room?.room_temp !== undefined && roomData.room?.room_temp !== null ? String(roomData.room.room_temp) : null,
                  field6: roomData.room?.room_humi !== undefined && roomData.room?.room_humi !== null ? String(roomData.room.room_humi) : null,
                  field7: roomData.orp !== undefined && roomData.orp !== null ? String(roomData.orp) : null,
                  field8: roomData.co2 !== undefined && roomData.co2 !== null ? String(roomData.co2) : null,
                });
              }
            }
          } else {
            const packetRoom = p.topic && p.topic.toLowerCase().includes('room3') ? 'room3' : p.topic && p.topic.toLowerCase().includes('room2') ? 'room2' : 'room1';
            if (room === 'both' || packetRoom === room) {
              if (packetRoom === 'room3') {
                mappedFeeds.push({
                  created_at: p.timestamp.toISOString(),
                  entry_id: mappedFeeds.length + 1,
                  room: packetRoom,
                  field1: d.md02_1?.room_temp !== undefined && d.md02_1?.room_temp !== null ? String(d.md02_1.room_temp) : null,
                  field2: d.md02_1?.room_humi !== undefined && d.md02_1?.room_humi !== null ? String(d.md02_1.room_humi) : null,
                  field3: d.md02_2?.room_temp !== undefined && d.md02_2?.room_temp !== null ? String(d.md02_2.room_temp) : null,
                  field4: d.md02_2?.room_humi !== undefined && d.md02_2?.room_humi !== null ? String(d.md02_2.room_humi) : null,
                  field5: null,
                  field6: null,
                  field7: null,
                  field8: d.co2 !== undefined && d.co2 !== null ? String(d.co2) : null,
                });
              } else {
                mappedFeeds.push({
                  created_at: p.timestamp.toISOString(),
                  entry_id: mappedFeeds.length + 1,
                  room: packetRoom,
                  field1: d.soil?.soil_temp !== undefined && d.soil?.soil_temp !== null ? String(d.soil.soil_temp) : null,
                  field2: d.soil?.moisture !== undefined && d.soil?.moisture !== null ? String(d.soil.moisture) : null,
                  field3: d.soil?.ec !== undefined && d.soil?.ec !== null ? String(d.soil.ec) : null,
                  field4: d.soil?.ph !== undefined && d.soil?.ph !== null ? String(d.soil.ph) : null,
                  field5: d.room?.room_temp !== undefined && d.room?.room_temp !== null ? String(d.room.room_temp) : null,
                  field6: d.room?.room_humi !== undefined && d.room?.room_humi !== null ? String(d.room.room_humi) : null,
                  field7: d.orp !== undefined && d.orp !== null ? String(d.orp) : null,
                  field8: d.co2 !== undefined && d.co2 !== null ? String(d.co2) : null,
                });
              }
            }
          }
        } else if (device.deviceType === 'multi_sensor') {
          // multi_sensor mapping
          mappedFeeds.push({
            created_at: p.timestamp.toISOString(),
            entry_id: mappedFeeds.length + 1,
            field1: d.s1?.t !== undefined && d.s1?.t !== null ? String(d.s1.t) : null,
            field2: d.s2?.t !== undefined && d.s2?.t !== null ? String(d.s2.t) : null,
            field3: d.s3?.t !== undefined && d.s3?.t !== null ? String(d.s3.t) : null,
            field4: d.s4?.t !== undefined && d.s4?.t !== null ? String(d.s4.t) : null,
            field5: d.s5?.t !== undefined && d.s5?.t !== null ? String(d.s5.t) : null,
            field6: d.s6?.t !== undefined && d.s6?.t !== null ? String(d.s6.t) : null,
            field7: d.s7?.t !== undefined && d.s7?.t !== null ? String(d.s7.t) : null,
            field8: null,
          });
        } else if (device.deviceType === 'controlling') {
          const tel = d.telemetry || d || {};
          mappedFeeds.push({
            created_at: p.timestamp.toISOString(),
            entry_id: mappedFeeds.length + 1,
            field1: tel.water_temp !== undefined && tel.water_temp !== null ? String(tel.water_temp) : null,
            field2: tel.moisture !== undefined && tel.moisture !== null ? String(tel.moisture) : null,
            field3: tel.ec !== undefined && tel.ec !== null ? String(tel.ec) : null,
            field4: tel.ph !== undefined && tel.ph !== null ? String(tel.ph) : null,
            field5: tel.room_temp !== undefined && tel.room_temp !== null ? String(tel.room_temp) : null,
            field6: tel.room_humi !== undefined && tel.room_humi !== null ? String(tel.room_humi) : null,
            field7: tel.orp !== undefined && tel.orp !== null ? String(tel.orp) : null,
            field8: tel.co2 !== undefined && tel.co2 !== null ? String(tel.co2) : null,
            field9: tel.vpd !== undefined && tel.vpd !== null ? String(tel.vpd) : null,
            field10: tel.dli !== undefined && tel.dli !== null ? String(tel.dli) : null,
            field11: tel.wind_speed !== undefined && tel.wind_speed !== null ? String(tel.wind_speed) : null,
            field12: tel.wind_dir !== undefined && tel.wind_dir !== null ? String(tel.wind_dir) : null,
            field13: tel.do !== undefined && tel.do !== null ? String(tel.do) : null,
            field14: tel.ppfd !== undefined && tel.ppfd !== null ? String(tel.ppfd) : null,
            field15: tel.n !== undefined && tel.n !== null ? String(tel.n) : null,
            field16: tel.p !== undefined && tel.p !== null ? String(tel.p) : null,
            field17: tel.k !== undefined && tel.k !== null ? String(tel.k) : null,
          });
        } else {
          // Standard / system2 / almora mapping
          const tel = d.telemetry || d || {};
          mappedFeeds.push({
            created_at: p.timestamp.toISOString(),
            entry_id: mappedFeeds.length + 1,
            field1: tel.water_temp !== undefined && tel.water_temp !== null ? String(tel.water_temp) : null,
            field2: tel.moisture !== undefined && tel.moisture !== null ? String(tel.moisture) : null,
            field3: tel.ec !== undefined && tel.ec !== null ? String(tel.ec) : null,
            field4: tel.ph !== undefined && tel.ph !== null ? String(tel.ph) : null,
            field5: tel.room_temp !== undefined && tel.room_temp !== null ? String(tel.room_temp) : null,
            field6: tel.room_humi !== undefined && tel.room_humi !== null ? String(tel.room_humi) : null,
            field7: tel.orp !== undefined && tel.orp !== null ? String(tel.orp) : null,
            field8: tel.co2 !== undefined && tel.co2 !== null ? String(tel.co2) : null,
          });
        }
      });

      feeds = mappedFeeds;
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
    if (device.deviceType === 'controlling') {
      channelData.field1 = 'Water Temp';
      channelData.field2 = 'Water Moisture';
      channelData.field3 = 'Water EC';
      channelData.field4 = 'Water pH';
      channelData.field5 = 'Room Temp';
      channelData.field6 = 'Room Humidity';
      channelData.field7 = 'ORP';
      channelData.field8 = 'CO2';
      channelData.field9 = 'VPD';
      channelData.field10 = 'DLI';
      channelData.field11 = 'Wind Speed';
      channelData.field12 = 'Wind Direction';
      channelData.field13 = 'Dissolved Oxygen (DO)';
      channelData.field14 = 'PPFD';
      channelData.field15 = 'Nitrogen (N)';
      channelData.field16 = 'Phosphorus (P)';
      channelData.field17 = 'Potassium (K)';
    } else if (device.deviceType === 'office_control') {
      if (room === 'room3') {
        channelData.field1 = 'MD02 #1 Temp';
        channelData.field2 = 'MD02 #1 Humi';
        channelData.field3 = 'MD02 #2 Temp';
        channelData.field4 = 'MD02 #2 Humi';
        channelData.field5 = 'Field 5';
        channelData.field6 = 'Field 6';
        channelData.field7 = 'Field 7';
        channelData.field8 = 'CO2 Level';
      } else {
        channelData.field1 = 'Soil Temp';
        channelData.field2 = 'Soil Moisture';
        channelData.field3 = 'Soil EC';
        channelData.field4 = 'Soil pH';
        channelData.field5 = 'Room Temp';
        channelData.field6 = 'Room Humidity';
        channelData.field7 = 'ORP Level';
        channelData.field8 = 'CO2 Level';
      }
    } else if (device.deviceType === 'multi_sensor') {
      channelData.field1 = 'Cold Room 1 Temp';
      channelData.field2 = 'Cold Room 2 Temp';
      channelData.field3 = 'Cold Room 3 Temp';
      channelData.field4 = 'Cold Room 4 Temp';
      channelData.field5 = 'Cold Room 5 Temp';
      channelData.field6 = 'Cold Room 6 Temp';
      channelData.field7 = 'Cold Room 7 Temp';
      channelData.field8 = 'Field 8';
    } else {
      channelData.field1 = 'Water Temp';
      channelData.field2 = 'Water Moisture';
      channelData.field3 = 'Water EC';
      channelData.field4 = 'Water pH';
      channelData.field5 = 'Room Temp';
      channelData.field6 = 'Room Humidity';
      channelData.field7 = 'ORP';
      channelData.field8 = 'CO2';
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

