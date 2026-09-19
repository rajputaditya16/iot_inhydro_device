const mongoose = require('mongoose');
const Device = require('../models/Device');
const TelemetryLog = require('../models/TelemetryLog');
const { getTelemetryModel } = require('../models/TelemetryLog');
const { publishToDevice } = require('../utils/mqttPublisher');
const { telemetryEmitter } = require('../utils/mqttSubscriber');


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

    // Admin (not superadmin) → only restrict if specific devices are assigned, otherwise show all
    if (req.user && req.user.role === 'admin') {
      const assignedDevices = req.user.assignedDevices || [];
      if (assignedDevices.length > 0) {
        query = { _id: { $in: assignedDevices } };
      }
    }

    const devices = await Device.find(query).sort({ createdAt: -1 }).lean();
    const now = new Date();

    const fs = require('fs');
    const path = require('path');
    const rootDir = path.resolve(__dirname, '../..');
    const cropFile = path.join(rootDir, 'crop_programs.json');
    let localCropPrograms = {};
    if (fs.existsSync(cropFile)) {
      try { localCropPrograms = JSON.parse(fs.readFileSync(cropFile, 'utf8')); } catch (e) { }
    }

    const updatedDevices = devices.map((device) => {
      const mqttId = (device.mqttId || '').trim();
      const lastSeenTime = device.lastUpdated || null;
      const diffMs = lastSeenTime ? (now.getTime() - new Date(lastSeenTime).getTime()) : Infinity;
      const isOnline = Boolean(lastSeenTime && Math.abs(diffMs) < 3 * 60 * 1000);

      let status = device.status;
      if (device.status !== 'blocked') {
        status = isOnline ? 'online' : 'offline';
      }

      const devId = (mqttId || (device?._id ? device._id.toString() : '')).toString();
      const setpFile = devId ? path.join(rootDir, `setpoints_${devId}.json`) : null;
      let localSetpoints = {};
      if (setpFile && fs.existsSync(setpFile)) {
        try { localSetpoints = JSON.parse(fs.readFileSync(setpFile, 'utf8')); } catch (e) { }
      }

      return {
        ...device,
        status,
        crop_programs: localCropPrograms,
        saved_programs: localCropPrograms,
        sensor_setpoints: localSetpoints,
        latestPacketTime: lastSeenTime
      };
    });

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
// Helper to resolve device by Mongo ObjectId, MQTT ID, or device name
const resolveDeviceByIdOrMqtt = async (idParam) => {
  if (!idParam) return null;
  let device = null;
  if (mongoose.Types.ObjectId.isValid(idParam)) {
    device = await Device.findById(idParam);
  }
  if (!device) {
    device = await Device.findOne({
      $or: [
        { mqttId: { $regex: new RegExp(`^${idParam}$`, 'i') } },
        { name: { $regex: new RegExp(`^${idParam}$`, 'i') } }
      ]
    });
  }
  return device;
};

// @route   PUT /api/devices/:id/push-config or POST /api/devices/:id/setpoints
// @desc    Push setpoints and config to the physical device via Private Broker MQTT
// @access  Private (Admin only)
exports.pushDeviceConfig = async (req, res) => {
  try {
    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    const deviceRoot = device?.mqttId || (device?._id ? device._id.toString() : req.params.id);

    const isCommandRequest = req.body?.action === 'restart' || req.body?.action === 'exit' || req.query?.action === 'restart' || req.query?.action === 'exit';
    if (isCommandRequest) {
      const action = req.body?.action || req.query?.action;
      const cmd_id = req.body?.cmd_id || ('cmd_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6));
      await publishToDevice(`inhydro/${deviceRoot}/command`, { action, cmd_id, timestamp: Date.now() }, { retain: false });
      if (deviceRoot !== deviceRoot.toLowerCase()) {
        await publishToDevice(`inhydro/${deviceRoot.toLowerCase()}/command`, { action, cmd_id, timestamp: Date.now() }, { retain: false });
      }
      return res.status(200).json({
        success: true,
        message: `Command "${action}" sent to device "${device?.name || deviceRoot}" via Private Broker MQTT`,
      });
    }

    const isSyncRequest = !req.body || Object.keys(req.body).length === 0 || req.body.action === 'sync' || req.query?.action === 'sync';

    if (isSyncRequest) {
      // Request setpoints sync from device
      if (device && (device.deviceType === 'office_control' || device.deviceType === 'system2')) {
        await publishToDevice(`inhydro/${deviceRoot}/room1/setpoints/request_sync`, '1');
        await publishToDevice(`inhydro/${deviceRoot}/room2/setpoints/request_sync`, '1');
        await publishToDevice(`inhydro/${deviceRoot}/room3/setpoints/request_sync`, '1');
      } else if (device && device.deviceType === 'controlling') {
        await publishToDevice(`inhydro/${deviceRoot}/monitor/setpoints/request_sync`, '1');
      } else {
        await publishToDevice(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');
        if (deviceRoot !== deviceRoot.toLowerCase()) {
          await publishToDevice(`inhydro/${deviceRoot.toLowerCase()}/setpoints/request_sync`, '1');
        }
      }

      return res.status(200).json({
        success: true,
        message: `Setpoints sync requested for device "${device?.name || deviceRoot}" via Private Broker MQTT`,
      });
    } else {
      // Push updated setpoints / config to device
      const payload = req.body;

      // Persist cropName and setupName to DB if present in payload
      if (device) {
        const incomingCrop = payload.cropName || payload.crop_name || payload['Crop Name'];
        const incomingSetup = payload.setupName || payload.setup_name || payload['Setup Name'] || payload['Setup Details'];
        let shouldSave = false;
        if (incomingCrop && device.cropName !== incomingCrop) {
          device.cropName = incomingCrop;
          shouldSave = true;
        }
        if (incomingSetup && device.setupName !== incomingSetup) {
          device.setupName = incomingSetup;
          shouldSave = true;
        }
        if (shouldSave) {
          await device.save();
        }
      }

      // Synchronize changes to local files immediately so REST API returns updated counts & setpoints instantly
      try {
        const fs = require('fs');
        const path = require('path');
        const rootDir = path.resolve(__dirname, '../..');
        const cropFile = path.join(rootDir, 'crop_programs.json');
        const devId = (deviceRoot || '').toString();
        const setpFile = devId ? path.join(rootDir, `setpoints_${devId}.json`) : null;

        if (payload.action === 'save_program' && payload.program_name) {
          let progs = {};
          if (fs.existsSync(cropFile)) {
            try { progs = JSON.parse(fs.readFileSync(cropFile, 'utf8')); } catch (e) { }
          }
          progs[payload.program_name] = payload.settings || {};
          fs.writeFileSync(cropFile, JSON.stringify(progs, null, 4));

          let setps = {};
          if (fs.existsSync(setpFile)) {
            try { setps = JSON.parse(fs.readFileSync(setpFile, 'utf8')); } catch (e) { }
          }
          const r = payload.room || payload.port || 'S1';
          if (!setps[r]) setps[r] = {};
          setps[r].program_name = payload.program_name;
          if (payload.settings) setps[r].settings = payload.settings;
          fs.writeFileSync(setpFile, JSON.stringify(setps, null, 4));
        } else if (payload.action === 'delete_program' && payload.program_name) {
          let progs = {};
          if (fs.existsSync(cropFile)) {
            try { progs = JSON.parse(fs.readFileSync(cropFile, 'utf8')); } catch (e) { }
          }
          delete progs[payload.program_name];
          Object.keys(progs).forEach(rk => {
            if (progs[rk] && typeof progs[rk] === 'object' && progs[rk][payload.program_name]) {
              delete progs[rk][payload.program_name];
            }
          });
          fs.writeFileSync(cropFile, JSON.stringify(progs, null, 4));

          let setps = {};
          if (fs.existsSync(setpFile)) {
            try { setps = JSON.parse(fs.readFileSync(setpFile, 'utf8')); } catch (e) { }
          }
          Object.keys(setps).forEach(rk => {
            if (setps[rk]?.program_name === payload.program_name) {
              setps[rk].program_name = 'Default Program';
            }
          });
          fs.writeFileSync(setpFile, JSON.stringify(setps, null, 4));
        } else if (payload.action === 'apply_program' && payload.program_name) {
          let setps = {};
          if (fs.existsSync(setpFile)) {
            try { setps = JSON.parse(fs.readFileSync(setpFile, 'utf8')); } catch (e) { }
          }
          const r = payload.room || payload.port || 'S1';
          if (!setps[r]) setps[r] = {};
          setps[r].program_name = payload.program_name;
          if (payload.settings) setps[r].settings = payload.settings;
          fs.writeFileSync(setpFile, JSON.stringify(setps, null, 4));
        } else if (payload.port && payload.settings) {
          let setps = {};
          if (fs.existsSync(setpFile)) {
            try { setps = JSON.parse(fs.readFileSync(setpFile, 'utf8')); } catch (e) { }
          }
          const r = payload.port;
          setps[r] = { ...(setps[r] || {}), ...payload };
          fs.writeFileSync(setpFile, JSON.stringify(setps, null, 4));

          const progName = payload.program_name || setps[r]?.program_name;
          if (progName && progName !== 'Default Program' && fs.existsSync(cropFile)) {
            try {
              let progs = JSON.parse(fs.readFileSync(cropFile, 'utf8'));
              progs[progName] = payload.settings;
              if (progs[r] && typeof progs[r] === 'object') {
                progs[r][progName] = payload.settings;
              }
              fs.writeFileSync(cropFile, JSON.stringify(progs, null, 4));
            } catch (e) { }
          }
        }

        // Save system_config to config_<devId>.json on disk
        const cfgFile = devId ? path.join(rootDir, `config_${devId}.json`) : null;
        if (cfgFile) {
          let curCfg = {};
          if (fs.existsSync(cfgFile)) {
            try { curCfg = JSON.parse(fs.readFileSync(cfgFile, 'utf8')); } catch (e) { }
          }
          const incomingSysConfig = { ...(payload.system_config || {}) };
          if (payload.upload_frequency_min !== undefined) incomingSysConfig.upload_frequency_min = payload.upload_frequency_min;
          if (payload.upload_hours !== undefined) incomingSysConfig.upload_hours = payload.upload_hours;
          if (payload.upload_mins !== undefined) incomingSysConfig.upload_mins = payload.upload_mins;
          if (payload.upload_secs !== undefined) incomingSysConfig.upload_secs = payload.upload_secs;
          if (payload.upload_frequency_sec !== undefined) incomingSysConfig.upload_frequency_sec = payload.upload_frequency_sec;
          if (payload.temp_alarm_offset !== undefined) incomingSysConfig.temp_alarm_offset = payload.temp_alarm_offset;
          if (payload.humi_alarm_offset !== undefined) incomingSysConfig.humi_alarm_offset = payload.humi_alarm_offset;
          if (payload.sensor_names !== undefined) incomingSysConfig.sensor_names = payload.sensor_names;

          if (Object.keys(incomingSysConfig).length > 0) {
            const mergedCfg = { ...curCfg, ...incomingSysConfig };
            fs.writeFileSync(cfgFile, JSON.stringify(mergedCfg, null, 4));
          }
        }
      } catch (fErr) {
        console.error('File sync in pushDeviceConfig error:', fErr);
      }

      if (device && (device.deviceType === 'office_control' || device.deviceType === 'system2')) {
        const room = req.query.room || req.body.room || 1;
        await publishToDevice(`inhydro/${deviceRoot}/room${room}/setpoints/update`, payload);
      } else if (device && device.deviceType === 'controlling') {
        await publishToDevice(`inhydro/${deviceRoot}/monitor/setpoints/update`, payload);
      } else {
        await publishToDevice(`inhydro/${deviceRoot}/setpoints/update`, payload);
        await publishToDevice(`inhydro/${deviceRoot}/config/update`, payload);
        if (deviceRoot !== deviceRoot.toLowerCase()) {
          await publishToDevice(`inhydro/${deviceRoot.toLowerCase()}/setpoints/update`, payload);
        }
      }

      return res.status(200).json({
        success: true,
        message: `Setpoints updated for device "${device?.name || deviceRoot}" via Private Broker MQTT`,
      });
    }
  } catch (err) {
    console.error('Push config error:', err);
    res.status(500).json({
      success: false,
      message: err.message || 'Failed to push config to device',
    });
  }
};

// Backward compatibility alias
exports.pushThingspeakConfig = exports.pushDeviceConfig;

// In-memory cooldown tracking to prevent rapid duplicate commands from hitting the broker
const recentDeviceCommands = new Map();

// @route   POST /api/devices/:id/command
// @desc    Send remote hardware/script command (restart, exit, pause, resume) to device via Private Broker MQTT
// @access  Private (Admin only)
exports.sendDeviceCommand = async (req, res) => {
  try {
    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    const deviceRoot = device?.mqttId || (device?._id ? device._id.toString() : req.params.id);
    const action = req.body?.action || req.body?.command || req.query?.action;

    if (!action) {
      return res.status(400).json({ success: false, message: 'Command action is required' });
    }

    // Cooldown check: Deduplicate rapid duplicate commands sent within 4s
    const now = Date.now();
    const dedupKey = `${deviceRoot}_${String(action).toLowerCase()}`;
    const lastSent = recentDeviceCommands.get(dedupKey) || 0;
    if (now - lastSent < 4000) {
      console.log(`[BACKEND DEDUP] Ignored duplicate command "${action}" for ${deviceRoot} (active cooldown)`);
      return res.status(200).json({
        success: true,
        message: `Command "${action}" is already in progress. Duplicate ignored.`,
        deduplicated: true,
      });
    }
    recentDeviceCommands.set(dedupKey, now);

    const cmd_id = req.body?.cmd_id || ('cmd_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6));
    const cmdPayload = {
      action,
      cmd_id,
      room: req.body?.room || req.body?.skey || req.query?.room,
      timestamp: Date.now()
    };

    await publishToDevice(`inhydro/${deviceRoot}/command`, cmdPayload, { retain: false });
    if (deviceRoot !== deviceRoot.toLowerCase()) {
      await publishToDevice(`inhydro/${deviceRoot.toLowerCase()}/command`, cmdPayload, { retain: false });
    }

    return res.status(200).json({
      success: true,
      message: `Command "${action}" dispatched to device "${device?.name || deviceRoot}" successfully`,
    });
  } catch (err) {
    console.error('Send device command error:', err);
    res.status(500).json({
      success: false,
      message: err.message || 'Failed to send command to device',
    });
  }
};

// @route   GET /api/devices/:id/analytics
// @desc    Get device telemetry packets (analytics) from DB
// @access  Private
exports.getDeviceAnalytics = async (req, res) => {
  try {
    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    if (!device) {
      return res.status(404).json({ success: false, message: 'Device not found' });
    }

    // Parse date filters, default to last 24 hours
    let start, end;
    if (req.query.all === 'true' || req.query.filter === 'all' || req.query.start === 'all') {
      start = new Date(0); // Epoch 1970
      end = new Date(Date.now() + 24 * 60 * 60 * 1000);
    } else {
      start = req.query.start ? new Date(req.query.start) : new Date(Date.now() - 24 * 60 * 60 * 1000);
      end = req.query.end ? new Date(req.query.end) : new Date();
    }
    const room = req.query.room || 'room1'; // 'room1', 'room2', 'room3' or 'both'

    // Map Mongoose documents to standard telemetry feeds format
    let feeds = [];
    const candidateMqttIds = [
      device.mqttId,
      device.deviceType === 'office_control' ? 'system2' : null,
      device.name,
      device._id.toString()
    ].filter(Boolean);

    const query = {
      timestamp: { $gte: start, $lte: end },
      $or: [
        { deviceId: device._id },
        { mqttId: device.mqttId || '' },
        { mqttId: 'system2' },
      ].filter(c => c.deviceId || c.mqttId)
    };

    let packets = [];
    let targetModel = null;
    let totalCollectionDocs = 0;

    // 1. Identify which dynamic collection belongs to this device
    for (const mId of candidateMqttIds) {
      try {
        const TelemetryModel = getTelemetryModel(mId);
        const count = await TelemetryModel.estimatedDocumentCount().maxTimeMS(2000);
        if (count > 0) {
          targetModel = TelemetryModel;
          totalCollectionDocs = count;
          break;
        }
      } catch (e) { }
    }

    // 2. Query within the date range from the target collection or fallback to TelemetryLog
    if (targetModel) {
      try {
        packets = await targetModel.find({
          timestamp: { $gte: start, $lte: end }
        }).sort({ timestamp: 1 }).limit(1000).maxTimeMS(3000).lean();
      } catch (tErr) {
        console.warn('[Analytics API] Target collection query warning, falling back to TelemetryLog:', tErr.message);
        packets = [];
      }

      if (packets.length === 0) {
        try {
          const fallbackPackets = await TelemetryLog.find(query).sort({ timestamp: 1 }).limit(1000).maxTimeMS(3000).lean();
          if (fallbackPackets && fallbackPackets.length > 0) {
            packets = fallbackPackets;
          }
        } catch (e) { }
      }
    } else {
      try {
        packets = await TelemetryLog.find(query).sort({ timestamp: 1 }).limit(1000).maxTimeMS(3000).lean();
      } catch (e) {
        packets = [];
      }
      try {
        totalCollectionDocs = await TelemetryLog.countDocuments({
          $or: [
            { deviceId: device._id },
            { mqttId: device.mqttId || '' },
            { mqttId: 'system2' },
          ].filter(c => c.deviceId || c.mqttId)
        }).maxTimeMS(2000);
      } catch (e) { }
    }

    const totalDbCount = packets.length;
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
      } else if (device.deviceType === 'multi_sensor' || device.deviceType === 'almora' || device.deviceType === 'almora2' || device.deviceType === 'cold_storage' || (device.name && (device.name.toLowerCase().includes('almora') || device.name.toLowerCase().includes('cold')))) {
        // Multi-sensor / Almora 7 Cold Storage rooms mapping
        const getSensor = (sNum) => {
          const sLower = `s${sNum}`;
          const sUpper = `S${sNum}`;
          if (d[sLower]) return d[sLower];
          if (d[sUpper]) return d[sUpper];
          if (d.sensor_data && typeof d.sensor_data === 'object') {
            if (d.sensor_data[sLower]) return d.sensor_data[sLower];
            if (d.sensor_data[sUpper]) return d.sensor_data[sUpper];
            for (const probe of Object.values(d.sensor_data)) {
              if (probe && (probe.id === sNum || probe.id === String(sNum))) {
                return probe;
              }
            }
          }
          return null;
        };

        const s1 = getSensor(1);
        const s2 = getSensor(2);
        const s3 = getSensor(3);
        const s4 = getSensor(4);
        const s5 = getSensor(5);
        const s6 = getSensor(6);
        const s7 = getSensor(7);

        mappedFeeds.push({
          created_at: p.timestamp.toISOString(),
          entry_id: mappedFeeds.length + 1,
          field1: s1 ? (s1.t ?? s1.temp ?? null) : null,
          field2: s2 ? (s2.t ?? s2.temp ?? null) : null,
          field3: s3 ? (s3.t ?? s3.temp ?? null) : null,
          field4: s4 ? (s4.t ?? s4.temp ?? null) : null,
          field5: s5 ? (s5.t ?? s5.temp ?? null) : null,
          field6: s6 ? (s6.t ?? s6.temp ?? null) : null,
          field7: s7 ? (s7.t ?? s7.temp ?? null) : null,
          field8: null,
          multi_sensor_data: {
            S1: s1 ? { t: s1.t ?? s1.temp ?? null, h: s1.h ?? s1.humi ?? s1.hum ?? null, co2: s1.co2 ?? null, status: s1.status || 'OK' } : null,
            S2: s2 ? { t: s2.t ?? s2.temp ?? null, h: s2.h ?? s2.humi ?? s2.hum ?? null, co2: s2.co2 ?? null, status: s2.status || 'OK' } : null,
            S3: s3 ? { t: s3.t ?? s3.temp ?? null, h: s3.h ?? s3.humi ?? s3.hum ?? null, co2: s3.co2 ?? null, status: s3.status || 'OK' } : null,
            S4: s4 ? { t: s4.t ?? s4.temp ?? null, h: s4.h ?? s4.humi ?? s4.hum ?? null, co2: s4.co2 ?? null, status: s4.status || 'OK' } : null,
            S5: s5 ? { t: s5.t ?? s5.temp ?? null, h: s5.h ?? s5.humi ?? s5.hum ?? null, co2: s5.co2 ?? null, status: s5.status || 'OK' } : null,
            S6: s6 ? { t: s6.t ?? s6.temp ?? null, h: s6.h ?? s6.humi ?? s6.hum ?? null, co2: s6.co2 ?? null, status: s6.status || 'OK' } : null,
            S7: s7 ? { t: s7.t ?? s7.temp ?? null, h: s7.h ?? s7.humi ?? s7.hum ?? null, co2: s7.co2 ?? null, status: s7.status || 'OK' } : null,
          }
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
      } else if (device.deviceType === 'monit' || device.deviceType === 'monnet' || device.deviceType === 'dosing') {
        mappedFeeds.push({
          created_at: p.timestamp.toISOString(),
          entry_id: mappedFeeds.length + 1,
          field1: d.temp != null ? String(d.temp) : (d.water_temp != null ? String(d.water_temp) : (d.soil_temp != null ? String(d.soil_temp) : null)),
          field2: d.moist != null ? String(d.moist) : (d.moisture != null ? String(d.moisture) : (d.soil_moisture != null ? String(d.soil_moisture) : null)),
          field3: d.ec != null ? String(d.ec) : (d.soil_ec != null ? String(d.soil_ec) : null),
          field4: d.ph != null ? String(d.ph) : (d.soil_ph != null ? String(d.soil_ph) : null),
          field5: d.room_temp != null ? String(d.room_temp) : (d.temperature != null ? String(d.temperature) : null),
          field6: d.room_humi != null ? String(d.room_humi) : (d.humidity != null ? String(d.humidity) : null),
          field7: d.orp != null ? String(d.orp) : null,
          field8: d.co2 != null ? String(d.co2) : null,
        });
      } else {
        // Standard / system2 / almora mapping
        const tel = d.telemetry || d || {};
        mappedFeeds.push({
          created_at: p.timestamp.toISOString(),
          entry_id: mappedFeeds.length + 1,
          field1: tel.water_temp !== undefined && tel.water_temp !== null ? String(tel.water_temp) : (tel.temp !== undefined && tel.temp !== null ? String(tel.temp) : null),
          field2: tel.moisture !== undefined && tel.moisture !== null ? String(tel.moisture) : (tel.moist !== undefined && tel.moist !== null ? String(tel.moist) : null),
          field3: tel.ec !== undefined && tel.ec !== null ? String(tel.ec) : null,
          field4: tel.ph !== undefined && tel.ph !== null ? String(tel.ph) : null,
          field5: tel.room_temp !== undefined && tel.room_temp !== null ? String(tel.room_temp) : null,
          field6: tel.room_humi !== undefined && tel.room_humi !== null ? String(tel.room_humi) : null,
          field7: tel.orp !== undefined && tel.orp !== null ? String(tel.orp) : null,
          field8: tel.co2 !== undefined && tel.co2 !== null ? String(tel.co2) : null,
        });
      }
    });

    // ── Downsampling / Stride Sampling for large datasets (Post-mapping per room) ──
    const isExport = req.query.export === 'true' || req.query.raw === 'true' || req.query.limit === '0' || req.query.limit === 'all';
    const MAX_ANALYTICS_POINTS = parseInt(req.query.limit) || 3500;
    if (!isExport && mappedFeeds.length > MAX_ANALYTICS_POINTS) {
      const stride = Math.ceil(mappedFeeds.length / MAX_ANALYTICS_POINTS);
      const sampled = [];
      for (let i = 0; i < mappedFeeds.length; i += stride) {
        sampled.push(mappedFeeds[i]);
      }
      if (sampled[sampled.length - 1] !== mappedFeeds[mappedFeeds.length - 1]) {
        sampled.push(mappedFeeds[mappedFeeds.length - 1]);
      }
      feeds = sampled;
    } else {
      feeds = mappedFeeds;
    }

    // Channel metadata for telemetry labels
    let channelData = {
      id: device.mqttId || device._id.toString(),
      name: device.name,
      field1: 'Water Temp',
      field2: 'Water Moisture',
      field3: 'Water EC',
      field4: 'Water pH',
      field5: 'Room Temp',
      field6: 'Room Humidity',
      field7: 'ORP',
      field8: 'CO2',
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
        channelData.field1 = 'Water Temp';
        channelData.field2 = 'Water Moisture';
        channelData.field3 = 'Water EC';
        channelData.field4 = 'Water pH';
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
    } else if (device.deviceType === 'monit' || device.deviceType === 'monnet') {
      channelData.field1 = 'Water Temp';
      channelData.field2 = 'Water Moisture';
      channelData.field3 = 'Water EC';
      channelData.field4 = 'Water pH';
      channelData.field5 = 'Room Temp';
      channelData.field6 = 'Room Humidity';
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

const formatHumanReadableDate = (dateInput, tz = 'Asia/Kolkata') => {
  if (!dateInput) return '';
  const d = new Date(dateInput);
  if (isNaN(d.getTime())) return String(dateInput);
  
  try {
    const formatter = new Intl.DateTimeFormat('en-IN', {
      timeZone: tz || 'Asia/Kolkata',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true
    });
    const parts = formatter.formatToParts(d);
    const getPart = (type) => parts.find(p => p.type === type)?.value || '';
    const year = getPart('year');
    const month = getPart('month').padStart(2, '0');
    const day = getPart('day').padStart(2, '0');
    const hour = getPart('hour').padStart(2, '0');
    const minute = getPart('minute').padStart(2, '0');
    const second = getPart('second').padStart(2, '0');
    const dayPeriod = (getPart('dayPeriod') || '').toUpperCase();
    
    return `${year}-${month}-${day} ${hour}:${minute}:${second} ${dayPeriod}`.trim();
  } catch (e) {
    const pad = (n) => String(n).padStart(2, '0');
    const year = d.getFullYear();
    const month = pad(d.getMonth() + 1);
    const day = pad(d.getDate());
    let hours = d.getHours();
    const minutes = pad(d.getMinutes());
    const seconds = pad(d.getSeconds());
    const ampm = hours >= 12 ? 'PM' : 'AM';
    const hours12 = pad(hours % 12 || 12);
    return `${year}-${month}-${day} ${hours12}:${minutes}:${seconds} ${ampm}`;
  }
};

    if (req.query.format === 'csv') {
      const isBoth = room === 'both';
      const timezone = req.query.timezone || 'Asia/Kolkata';
      const headers = ['Timestamp'];
      if (isBoth) headers.push('Room');
      
      const activeFields = [];
      for (let i = 1; i <= 17; i++) {
        const key = `field${i}`;
        const rawName = (channelData[key] || `Field ${i}`).replace(/\bSoil\b/gi, 'Water');
        const hasData = mappedFeeds.some(f => f[key] != null && f[key] !== '' && f[key] !== 'null');
        if (hasData) {
          let unit = '';
          const lower = rawName.toLowerCase();
          if (lower.includes('temp')) unit = ' (°C)';
          else if (lower.includes('moist') || lower.includes('hum')) unit = ' (%)';
          else if (lower.includes('ec')) unit = ' (mS/cm)';
          else if (lower.includes('ph')) unit = ' (pH)';
          else if (lower.includes('co2')) unit = ' (PPM)';
          else if (lower.includes('vpd')) unit = ' (kPa)';
          else if (lower.includes('dli')) unit = ' (mol/m²/d)';
          else if (lower.includes('wind_speed') || lower.includes('wind speed')) unit = ' (m/s)';
          else if (lower.includes('wind_dir') || lower.includes('wind direction')) unit = ' (°)';
          else if (lower.includes('dissolved oxygen') || lower.includes('do')) unit = ' (mg/L)';
          else if (lower.includes('ppfd')) unit = ' (µmol/m²/s)';
          else if (lower.includes('nitrogen') || lower.includes('(n)')) unit = ' (mg/kg)';
          else if (lower.includes('phosphorus') || lower.includes('(p)')) unit = ' (mg/kg)';
          else if (lower.includes('potassium') || lower.includes('(k)')) unit = ' (mg/kg)';
          
          activeFields.push({ key, name: `${rawName}${unit}` });
          headers.push(`"${rawName}${unit}"`);
        }
      }

      const rows = mappedFeeds.map(f => {
        const readableTime = formatHumanReadableDate(f.created_at, timezone);
        const rowCells = [`"${readableTime}"`];
        if (isBoth) rowCells.push(`"${f.room || 'room1'}"`);
        activeFields.forEach(af => {
          const val = f[af.key] !== undefined && f[af.key] !== null ? f[af.key] : '';
          rowCells.push(val !== '' ? val : '');
        });
        return rowCells.join(',');
      });

      const csvContent = headers.join(',') + '\n' + rows.join('\n');
      const safeSlug = String(device.name || 'Device').replace(/[^a-z0-9_-]/gi, '_');
      res.setHeader('Content-Type', 'text/csv; charset=utf-8');
      res.setHeader('Content-Disposition', `attachment; filename="${safeSlug}_Analytics.csv"`);
      return res.status(200).send(csvContent);
    }

    if (req.query.format === 'json' && isExport) {
      const isBoth = room === 'both';
      const timezone = req.query.timezone || 'Asia/Kolkata';
      const activeFields = [];
      for (let i = 1; i <= 17; i++) {
        const key = `field${i}`;
        const rawName = (channelData[key] || `Field ${i}`).replace(/\bSoil\b/gi, 'Water');
        const hasData = mappedFeeds.some(f => f[key] != null && f[key] !== '' && f[key] !== 'null');
        if (hasData) {
          activeFields.push({ key, name: rawName });
        }
      }
      const exportJson = mappedFeeds.map(f => {
        const readableTime = formatHumanReadableDate(f.created_at, timezone);
        const obj = { timestamp: readableTime, rawTimestamp: f.created_at };
        if (isBoth) obj.room = f.room || 'room1';
        activeFields.forEach(af => {
          obj[af.name] = f[af.key] !== undefined && f[af.key] !== null && f[af.key] !== '' ? parseFloat(f[af.key]) || f[af.key] : null;
        });
        return obj;
      });
      const safeSlug = String(device.name || 'Device').replace(/[^a-z0-9_-]/gi, '_');
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.setHeader('Content-Disposition', `attachment; filename="${safeSlug}_Analytics.json"`);
      return res.status(200).json(exportJson);
    }

    res.status(200).json({
      success: true,
      channel: channelData,
      feeds: feeds,
      totalDbPoints: totalDbCount,
      totalCollectionDocs: totalCollectionDocs,
      totalFeeds: mappedFeeds.length,
    });
  } catch (err) {
    console.error('[Analytics API] Error fetching analytics:', err);
    res.status(500).json({ success: false, message: 'Server Error fetching analytics' });
  }
};

// @route   GET /api/devices/stream
// @desc    Real-time Server-Sent Events (SSE) telemetry stream with device filtering support (P1 Optimization)
// @access  Public / Private
exports.streamTelemetry = (req, res) => {
  const origin = req.headers.origin;
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache, no-transform',
    'Connection': 'keep-alive',
    'X-Accel-Buffering': 'no', // Critical: Disables Nginx & reverse proxy buffering on cloud deployments
    'Access-Control-Allow-Origin': origin || '*',
    'Access-Control-Allow-Headers': 'Origin, X-Requested-With, Content-Type, Accept, Authorization',
    'Access-Control-Allow-Credentials': 'true'
  });

  if (typeof res.flushHeaders === 'function') {
    res.flushHeaders();
  }
  res.write(': connected\n\n');
  if (typeof res.flush === 'function') {
    res.flush();
  }

  // ── Targeted Device Filtering (P1) ──
  const filterDeviceId = req.query.deviceId ? String(req.query.deviceId).toLowerCase() : null;
  const filterMqttId = req.query.mqttId ? String(req.query.mqttId).toLowerCase() : null;
  const filterDevices = req.query.devices ? req.query.devices.split(',').map(s => s.trim().toLowerCase()).filter(Boolean) : [];

  const allowedSet = new Set();
  if (filterDeviceId) allowedSet.add(filterDeviceId);
  if (filterMqttId) allowedSet.add(filterMqttId);
  filterDevices.forEach(d => allowedSet.add(d));

  // If filterDeviceId is an ObjectId, lookup device attributes (mqttId, name) so we match even if client only knows deviceId
  if (filterDeviceId && mongoose.Types.ObjectId.isValid(filterDeviceId)) {
    Device.findById(filterDeviceId).select('mqttId name _id').lean().then(dev => {
      if (dev) {
        if (dev.mqttId) allowedSet.add(String(dev.mqttId).toLowerCase());
        if (dev.name) allowedSet.add(String(dev.name).toLowerCase());
      }
    }).catch(() => { });
  }

  // Immediately send cached local setpoints & crop programs if available
  try {
    const fs = require('fs');
    const path = require('path');
    const rootDir = path.resolve(__dirname, '../..');
    const cropFile = path.join(rootDir, 'crop_programs.json');
    let localCropPrograms = {};
    if (fs.existsSync(cropFile)) {
      try { localCropPrograms = JSON.parse(fs.readFileSync(cropFile, 'utf8')); } catch (e) { }
    }
    const devId = (filterMqttId || filterDeviceId || '').toString();
    const setpFile = devId ? path.join(rootDir, `setpoints_${devId}.json`) : null;
    let localSetpoints = {};
    if (setpFile && fs.existsSync(setpFile)) {
      try { localSetpoints = JSON.parse(fs.readFileSync(setpFile, 'utf8')); } catch (e) { }
    }

    if (Object.keys(localCropPrograms).length > 0 || Object.keys(localSetpoints).length > 0) {
      const initPayload = {
        deviceId: filterDeviceId || null,
        mqttId: filterMqttId || null,
        topic: filterMqttId ? `inhydro/${filterMqttId}/setpoints/current` : '',
        data: {
          crop_programs: localCropPrograms,
          saved_programs: localCropPrograms,
          sensor_setpoints: localSetpoints,
          timestamp: new Date().toISOString()
        }
      };
      res.write(`data: ${JSON.stringify(initPayload)}\n\n`);
    }
  } catch (e) { }

  let isClosed = false;

  const cleanup = () => {
    if (isClosed) return;
    isClosed = true;
    clearInterval(pingInterval);
    telemetryEmitter.off('telemetry', onTelemetry);
  };

  // Periodic heartbeat ping to prevent cloud load balancers/proxies (Render, Cloudflare, Nginx) from dropping connection
  const pingInterval = setInterval(() => {
    if (isClosed) return;
    try {
      res.write(': ping\n\n');
      if (typeof res.flush === 'function') {
        res.flush();
      }
    } catch (e) {
      cleanup();
    }
  }, 15000);

  const onTelemetry = (payload) => {
    if (isClosed) return;

    // Filter incoming packets if device filter is provided
    if (allowedSet.size > 0) {
      const pMqttId = String(payload.mqttId || '').toLowerCase();
      const pDevId = String(payload.deviceId || '').toLowerCase();
      const pTopic = String(payload.topic || '').toLowerCase();

      const isMatch =
        (pDevId && allowedSet.has(pDevId)) ||
        (pMqttId && allowedSet.has(pMqttId)) ||
        Array.from(allowedSet).some(id => id && (pTopic.includes(id) || (pMqttId && pMqttId.includes(id)) || (pDevId && pDevId.includes(id))));

      if (!isMatch) {
        return; // Skip sending to this specific client
      }
    }

    try {
      res.write(`data: ${JSON.stringify(payload)}\n\n`);
      if (typeof res.flush === 'function') {
        res.flush();
      }
    } catch (e) {
      cleanup();
    }
  };

  telemetryEmitter.on('telemetry', onTelemetry);

  req.on('close', cleanup);
  req.on('end', cleanup);
  res.on('close', cleanup);
  res.on('finish', cleanup);
  res.on('error', cleanup);
};

// @route   GET /api/devices/:id/programs
// @desc    Directly read saved crop programs from crop_programs.json on device filesystem
exports.getCropPrograms = async (req, res) => {
  try {
    const fs = require('fs');
    const path = require('path');
    const cropFile = path.resolve(__dirname, '../../crop_programs.json');
    let progs = {};
    if (fs.existsSync(cropFile)) {
      try { progs = JSON.parse(fs.readFileSync(cropFile, 'utf8')); } catch (e) { }
    }
    const count = Object.keys(progs).filter(k => !['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].includes(k)).length;
    res.status(200).json({ success: true, count, data: progs });
  } catch (err) {
    console.error('getCropPrograms error:', err);
    res.status(500).json({ success: false, message: err.message });
  }
};

// @route   POST /api/devices/:id/programs
// @desc    Directly save a program to crop_programs.json and publish to MQTT
exports.saveCropProgram = async (req, res) => {
  try {
    const fs = require('fs');
    const path = require('path');
    const cropFile = path.resolve(__dirname, '../../crop_programs.json');
    const { program_name, name, settings, room, port } = req.body;
    const pName = (program_name || name || '').trim();
    if (!pName) {
      return res.status(400).json({ success: false, message: 'Program name required' });
    }
    let progs = {};
    if (fs.existsSync(cropFile)) {
      try { progs = JSON.parse(fs.readFileSync(cropFile, 'utf8')); } catch (e) { }
    }
    const rKey = room || port || 'S1';
    progs[pName] = settings || {};
    if (!progs[rKey] || typeof progs[rKey] !== 'object') progs[rKey] = {};
    progs[rKey][pName] = settings || {};
    fs.writeFileSync(cropFile, JSON.stringify(progs, null, 4));

    // Update setpoints file for the device
    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    const devId = (device?.mqttId || (device?._id ? device._id.toString() : req.params.id)).toString();
    const setpFile = devId ? path.resolve(__dirname, `../../setpoints_${devId}.json`) : null;
    let setps = {};
    if (setpFile && fs.existsSync(setpFile)) {
      try { setps = JSON.parse(fs.readFileSync(setpFile, 'utf8')); } catch (e) { }
    }
    if (!setps[rKey]) setps[rKey] = {};
    setps[rKey].program_name = pName;
    if (settings) setps[rKey].settings = settings;
    if (setpFile) fs.writeFileSync(setpFile, JSON.stringify(setps, null, 4));

    // Broadcast over MQTT
    const mqttPayload = { action: 'save_program', program_name: pName, room: rKey, port: rKey, settings };
    const targetMqttId = (device?.mqttId || req.params.id || devId).toString();
    await publishToDevice(`inhydro/${targetMqttId}/setpoints/update`, mqttPayload);
    if (targetMqttId !== targetMqttId.toLowerCase()) {
      await publishToDevice(`inhydro/${targetMqttId.toLowerCase()}/setpoints/update`, mqttPayload);
    }

    const count = Object.keys(progs).filter(k => !['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].includes(k)).length;
    res.status(200).json({ success: true, count, data: progs, message: `Program "${pName}" saved successfully` });
  } catch (err) {
    console.error('saveCropProgram error:', err);
    res.status(500).json({ success: false, message: err.message });
  }
};

// @route   DELETE /api/devices/:id/programs/:programName
// @desc    Directly delete a program from crop_programs.json and publish to MQTT
exports.deleteCropProgram = async (req, res) => {
  try {
    const fs = require('fs');
    const path = require('path');
    const cropFile = path.resolve(__dirname, '../../crop_programs.json');
    const pName = decodeURIComponent(req.params.programName || '').trim();
    if (!pName) {
      return res.status(400).json({ success: false, message: 'Program name required' });
    }
    let progs = {};
    if (fs.existsSync(cropFile)) {
      try { progs = JSON.parse(fs.readFileSync(cropFile, 'utf8')); } catch (e) { }
    }
    delete progs[pName];
    ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].forEach(rk => {
      if (progs[rk] && typeof progs[rk] === 'object' && progs[rk][pName]) {
        delete progs[rk][pName];
      }
    });
    fs.writeFileSync(cropFile, JSON.stringify(progs, null, 4));

    // Update setpoints file
    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    const devId = (device?.mqttId || (device?._id ? device._id.toString() : req.params.id)).toString();
    const setpFile = devId ? path.resolve(__dirname, `../../setpoints_${devId}.json`) : null;
    let setps = {};
    if (setpFile && fs.existsSync(setpFile)) {
      try { setps = JSON.parse(fs.readFileSync(setpFile, 'utf8')); } catch (e) { }
      ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].forEach(rk => {
        if (setps[rk]?.program_name === pName) {
          setps[rk].program_name = 'Default Program';
        }
      });
      fs.writeFileSync(setpFile, JSON.stringify(setps, null, 4));
    }

    // Broadcast over MQTT
    const mqttPayload = { action: 'delete_program', program_name: pName };
    const targetMqttId = (device?.mqttId || req.params.id || devId).toString();
    await publishToDevice(`inhydro/${targetMqttId}/setpoints/update`, mqttPayload);
    if (targetMqttId !== targetMqttId.toLowerCase()) {
      await publishToDevice(`inhydro/${targetMqttId.toLowerCase()}/setpoints/update`, mqttPayload);
    }

    const count = Object.keys(progs).filter(k => !['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].includes(k)).length;
    res.status(200).json({ success: true, count, data: progs, message: `Program "${pName}" deleted successfully` });
  } catch (err) {
    console.error('deleteCropProgram error:', err);
    res.status(500).json({ success: false, message: err.message });
  }
};

// @route   POST /api/devices/:id/programs/:programName/apply
// @desc    Apply a saved program to a room
exports.applyCropProgram = async (req, res) => {
  try {
    const fs = require('fs');
    const path = require('path');
    const cropFile = path.resolve(__dirname, '../../crop_programs.json');
    const pName = decodeURIComponent(req.params.programName || '').trim();
    const { room, port } = req.body;
    const rKey = room || port || 'S1';
    
    let progs = {};
    if (fs.existsSync(cropFile)) {
      try { progs = JSON.parse(fs.readFileSync(cropFile, 'utf8')); } catch (e) { }
    }
    const progSettings = progs[pName] || progs[rKey]?.[pName] || req.body.settings;
    if (!progSettings) {
      return res.status(404).json({ success: false, message: 'Program not found in device library' });
    }

    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    const devId = (device?.mqttId || (device?._id ? device._id.toString() : req.params.id)).toString();
    const setpFile = devId ? path.resolve(__dirname, `../../setpoints_${devId}.json`) : null;
    let setps = {};
    if (setpFile && fs.existsSync(setpFile)) {
      try { setps = JSON.parse(fs.readFileSync(setpFile, 'utf8')); } catch (e) { }
    }
    if (!setps[rKey]) setps[rKey] = {};
    setps[rKey].program_name = pName;
    setps[rKey].settings = progSettings;
    if (setpFile) fs.writeFileSync(setpFile, JSON.stringify(setps, null, 4));

    // Broadcast over MQTT
    const mqttPayload = { action: 'apply_program', program_name: pName, room: rKey, port: rKey, settings: progSettings };
    const targetMqttId = (device?.mqttId || req.params.id || devId).toString();
    await publishToDevice(`inhydro/${targetMqttId}/setpoints/update`, mqttPayload);
    if (targetMqttId !== targetMqttId.toLowerCase()) {
      await publishToDevice(`inhydro/${targetMqttId.toLowerCase()}/setpoints/update`, mqttPayload);
    }

    res.status(200).json({ success: true, setpoints: setps, message: `Program "${pName}" applied to ${rKey}` });
  } catch (err) {
    console.error('applyCropProgram error:', err);
    res.status(500).json({ success: false, message: err.message });
  }
};

// @route   GET /api/devices/:id/setpoints-json
// @desc    Directly read setpoints and system_config from disk
exports.getSetpointsJson = async (req, res) => {
  try {
    const fs = require('fs');
    const path = require('path');
    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    const devId = (device?.mqttId || (device?._id ? device._id.toString() : req.params.id)).toString();
    const setpFile = devId ? path.resolve(__dirname, `../../setpoints_${devId}.json`) : null;
    const cfgFile = devId ? path.resolve(__dirname, `../../config_${devId}.json`) : null;
    let setps = {};
    let cfg = {};
    if (setpFile && fs.existsSync(setpFile)) {
      try { setps = JSON.parse(fs.readFileSync(setpFile, 'utf8')); } catch (e) { }
    }
    if (cfgFile && fs.existsSync(cfgFile)) {
      try { cfg = JSON.parse(fs.readFileSync(cfgFile, 'utf8')); } catch (e) { }
    }
    res.status(200).json({ success: true, data: setps, system_config: cfg });
  } catch (err) {
    console.error('getSetpointsJson error:', err);
    res.status(500).json({ success: false, message: err.message });
  }
};
