const mongoose = require('mongoose');
const Device = require('../models/Device');
const User = require('../models/User');
const Admin = require('../models/Admin');
const TelemetryLog = require('../models/TelemetryLog');
const { getTelemetryModel } = require('../models/TelemetryLog');
const { publishToDevice } = require('../utils/mqttPublisher');
const { telemetryEmitter, updateDeviceCacheStatus, preloadDeviceCache } = require('../utils/mqttSubscriber');
const { downsampleFeeds } = require('../utils/downsampler');
const { makeAnalyticsCacheKey, resolveTTL, getCache, setCache } = require('../utils/redisCache');


// @route   GET /api/devices
// @desc    Get all devices
// @access  Private
exports.getDevices = async (req, res) => {
  try {
    let query = {};

    // Only superadmin can view all devices.
    // Admins and regular users can ONLY view devices explicitly assigned to them.
    if (req.user && req.user.role !== 'superadmin') {
      const assignedDevices = req.user.assignedDevices || [];
      query = { _id: { $in: assignedDevices } };
    }

    const isMinimal = req.query.minimal === 'true';
    let findQuery = Device.find(query).sort({ createdAt: -1 });
    if (isMinimal) {
      findQuery = findQuery.select('_id name location status deviceType mqttId clientName locationCode model unit nicknameByClient cropName setupName lastUpdated createdAt updatedAt');
    }
    const devices = await findQuery.lean();
    const now = new Date();

    const updatedDevices = devices.map((device) => {
      const lastSeenTime = device.lastUpdated || null;
      const diffMs = lastSeenTime ? (now.getTime() - new Date(lastSeenTime).getTime()) : Infinity;
      const isOnline = Boolean(lastSeenTime && diffMs >= -60000 && diffMs <= 180 * 1000);

      let status = device.status;
      if (device.status !== 'blocked') {
        status = isOnline ? 'online' : 'offline';
      }

      if (isMinimal) {
        return {
          ...device,
          status,
          latestPacketTime: lastSeenTime
        };
      }

      const progs = (device.cropPrograms && typeof device.cropPrograms === 'object') ? device.cropPrograms : {};
      const setps = (device.settings && typeof device.settings === 'object') ? device.settings : {};
      const cfg = (device.config && typeof device.config === 'object') ? device.config : {};

      return {
        ...device,
        status,
        crop_programs: progs,
        saved_programs: progs,
        cropPrograms: progs,
        sensor_setpoints: setps,
        settings: setps,
        system_config: cfg,
        config: cfg,
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

    // If created by an Admin (not superadmin), automatically add it to their assigned devices
    if (req.user && req.user.role === 'admin') {
      await Admin.findByIdAndUpdate(req.user._id, {
        $addToSet: { assignedDevices: device._id }
      });
    }

    console.log('[DEBUG] createDevice saved document:', device);
    preloadDeviceCache(); // Re-warm hot cache for instant MQTT resolution
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
    preloadDeviceCache(); // Re-warm hot cache for updated MQTT ID / name
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

    // Clean up references in User and Admin models
    await Promise.all([
      User.updateMany({ assignedDevices: req.params.id }, { $pull: { assignedDevices: req.params.id } }),
      Admin.updateMany({ assignedDevices: req.params.id }, { $pull: { assignedDevices: req.params.id } })
    ]);

    preloadDeviceCache(); // Refresh cache after deletion
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

    updateDeviceCacheStatus(device._id, device.status);

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

    const isCommandRequest =
      req.body?.action === 'restart' ||
      req.body?.action === 'exit' ||
      req.body?.action === 'pause' ||
      req.body?.action === 'resume' ||
      req.body?.action === 'stop' ||
      req.body?.action === 'run' ||
      req.query?.action === 'restart' ||
      req.query?.action === 'exit';
    if (isCommandRequest) {
      const action = req.body?.action || req.query?.action;
      const polyhouse = req.body?.polyhouse || req.body?.room || req.body?.skey;
      const cmd_id = req.body?.cmd_id || ('cmd_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6));
      const cmdPayload = { action, cmd_id, timestamp: Date.now() };
      if (polyhouse) cmdPayload.polyhouse = polyhouse;

      await publishToDevice(`inhydro/${deviceRoot}/command`, cmdPayload, { retain: false });
      if (deviceRoot !== deviceRoot.toLowerCase()) {
        await publishToDevice(`inhydro/${deviceRoot.toLowerCase()}/command`, cmdPayload, { retain: false });
      }
      return res.status(200).json({
        success: true,
        message: `Command "${action}"${polyhouse ? ` for ${polyhouse}` : ''} sent to device "${device?.name || deviceRoot}" via Private Broker MQTT`,
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
        if (device) {
          const updateFields = {};
          if (payload.action === 'save_program' && payload.program_name) {
            const r = payload.room || payload.port || 'S1';
            const curProgs = { ...(device.cropPrograms || {}) };
            if (!curProgs[r] || typeof curProgs[r] !== 'object') curProgs[r] = {};
            curProgs[r][payload.program_name] = payload.settings || {};
            updateFields['cropPrograms'] = curProgs;
            updateFields[`settings.${r}.program_name`] = payload.program_name;
            if (payload.settings) updateFields[`settings.${r}.settings`] = payload.settings;
          } else if (payload.action === 'delete_program' && payload.program_name) {
            const r = payload.room || payload.port;
            const curProgs = { ...(device.cropPrograms || {}) };
            if (r && curProgs[r]) {
              delete curProgs[r][payload.program_name];
            } else {
              ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].forEach(k => {
                if (curProgs[k]) delete curProgs[k][payload.program_name];
              });
            }
            updateFields['cropPrograms'] = curProgs;
          } else if (payload.action === 'apply_program' && payload.program_name) {
            const r = payload.room || payload.port || 'S1';
            updateFields[`settings.${r}.program_name`] = payload.program_name;
            if (payload.settings) updateFields[`settings.${r}.settings`] = payload.settings;
          } else if (payload.port && payload.settings) {
            const curSettings = (device.settings && typeof device.settings === 'object') ? device.settings : {};
            const existingRoom = curSettings[payload.port] || {};
            updateFields[`settings.${payload.port}`] = {
              ...existingRoom,
              crop_name: payload.crop_name || payload.cropName || existingRoom.crop_name || '',
              setup_name: payload.setup_name || payload.setupName || existingRoom.setup_name || '',
              program_name: payload.program_name || existingRoom.program_name || 'Default Program',
              mode: payload.mode || existingRoom.mode || 'SCHEDULED',
              'T MIN': payload['T MIN'] ?? existingRoom['T MIN'] ?? 10.0,
              'T MAX': payload['T MAX'] ?? existingRoom['T MAX'] ?? 30.0,
              'H MIN': payload['H MIN'] ?? existingRoom['H MIN'] ?? 30.0,
              'H MAX': payload['H MAX'] ?? existingRoom['H MAX'] ?? 80.0,
              settings: payload.settings
            };
          } else if (payload.sensor_setpoints) {
            updateFields['settings'] = payload.sensor_setpoints;
          }

          if (payload.system_config && typeof payload.system_config === 'object') {
            updateFields['config'] = payload.system_config;
          }
          if (Object.keys(updateFields).length > 0) {
            await Device.findByIdAndUpdate(device._id, { $set: updateFields }).catch(() => { });
          }
        }
      } catch (fErr) {
        console.error('DB update in pushDeviceConfig error:', fErr);
      }

      if (device && (device.deviceType === 'office_control' || device.deviceType === 'system2')) {
        const room = req.query.room || req.body.room || 1;
        await publishToDevice(`inhydro/${deviceRoot}/room${room}/setpoints/update`, payload);
      } else if (device && device.deviceType === 'controlling') {
        await publishToDevice(`inhydro/${deviceRoot}/monitor/setpoints/update`, payload);
      } else {
        await publishToDevice(`inhydro/${deviceRoot}/setpoints/update`, payload);
        await publishToDevice(`inhydro/${deviceRoot}/config/update`, payload);
        await publishToDevice(`inhydro/${deviceRoot}/control`, payload);
        if (deviceRoot !== deviceRoot.toLowerCase()) {
          await publishToDevice(`inhydro/${deviceRoot.toLowerCase()}/setpoints/update`, payload);
          await publishToDevice(`inhydro/${deviceRoot.toLowerCase()}/control`, payload);
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
    const room = req.query.room || (device.deviceType === 'office_control' ? 'room1' : 'all');

    // Check if this is a live monitoring fast-fetch or an export request
    const isLive = req.query.live === 'true' || (req.query.limit && parseInt(req.query.limit) <= 50);
    const isExport = req.query.export === 'true' || req.query.format === 'csv' || req.query.format === 'json' || req.query.raw === 'true' || req.query.limit === '0' || req.query.limit === 'all';
    const isDownsample = req.query.downsample === 'true' && !isExport;
    const sampleLimit = parseInt(req.query.sampleLimit || req.query.limit) || 1500;

    // ── Redis Cache Check (skip for live & export queries) ──
    const useCache = !isLive && !isExport;
    let cacheKey = null;
    if (useCache) {
      cacheKey = makeAnalyticsCacheKey(device._id.toString(), {
        start: start.toISOString(),
        end: end.toISOString(),
        room,
        downsample: isDownsample,
        sampleLimit,
        format: req.query.format || '',
      });
      const cached = await getCache(cacheKey);
      if (cached) {
        cached._fromCache = true;
        return res.status(200).json(cached);
      }
    }

    // 1. Target collection resolution
    const primaryMqttId = device.mqttId || (device.deviceType === 'office_control' ? 'system2' : null) || device.name;
    const targetModel = primaryMqttId ? getTelemetryModel(primaryMqttId) : null;
    const sortOrder = isLive ? { timestamp: -1 } : { timestamp: 1 };

    // Build clean indexed query (indexed timestamp range query for 100,000+ to 1,000,000+ records)
    const targetQuery = isLive
      ? {}
      : { timestamp: { $gte: start, $lte: end } };

    // For office_control, filter by room directly in MongoDB if a specific room is requested
    if (device.deviceType === 'office_control' && room !== 'both' && room !== 'all') {
      targetQuery.$or = [
        { topic: new RegExp(room, 'i') },
        { [`data.${room}`]: { $exists: true } }
      ];
    }

    let packets = [];
    let totalInRange = 0;
    let totalInCollection = 0;

    if (targetModel) {
      try {
        // Step 1: Count total documents in range and in collection with generous timeouts
        const [inRangeCount, collectionCount] = await Promise.all([
          targetModel.countDocuments(targetQuery).maxTimeMS(20000).catch(() => null),
          targetModel.estimatedDocumentCount().maxTimeMS(10000).catch(() => null)
        ]);

        totalInRange = inRangeCount !== null ? inRangeCount : 0;
        totalInCollection = collectionCount !== null ? collectionCount : totalInRange;

        // Step 2: Fetch documents based on query type
        if (isLive) {
          packets = await targetModel.find(targetQuery)
            .sort(sortOrder)
            .limit(parseInt(req.query.limit) || 30)
            .select('timestamp data topic room deviceId mqttId')
            .maxTimeMS(10000)
            .lean();
        } else if (isExport) {
          // Full export: fetch up to 1,000,000 records
          const exportLimit = parseInt(req.query.limit) || 1000000;
          packets = await targetModel.find(targetQuery)
            .sort(sortOrder)
            .limit(exportLimit)
            .select('timestamp data topic room deviceId mqttId')
            .maxTimeMS(60000)
            .lean();
        } else if (isDownsample && totalInRange > sampleLimit * 2) {
          // ── High-Speed Cursor Stride Sampling for 100,000+ records ──
          // Streams cursor in constant O(1) memory, extracting ~sampleLimit points across entire range in < 500ms
          const stride = Math.max(1, Math.floor(totalInRange / sampleLimit));
          const cursor = targetModel.find(targetQuery)
            .sort(sortOrder)
            .select('timestamp data topic room deviceId mqttId')
            .maxTimeMS(60000)
            .lean()
            .cursor();

          let countIdx = 0;
          for await (const doc of cursor) {
            if (countIdx % stride === 0) {
              packets.push(doc);
            }
            countIdx++;
          }
        } else {
          // Standard range fetch (up to 100,000 records)
          const fetchLimit = parseInt(req.query.limit) || 100000;
          packets = await targetModel.find(targetQuery)
            .sort(sortOrder)
            .limit(fetchLimit)
            .select('timestamp data topic room deviceId mqttId')
            .maxTimeMS(45000)
            .lean();
        }
      } catch (tErr) {
        console.warn('[Analytics API] Target collection query warning, falling back to TelemetryLog:', tErr.message);
        packets = [];
      }
    }

    // Fallback to main TelemetryLog only if dynamic collection returned 0 packets
    if (packets.length === 0 && (!totalInRange || totalInRange === 0)) {
      try {
        const fallbackQuery = {
          ...targetQuery,
          $or: [
            { deviceId: device._id },
            { mqttId: device.mqttId || '' },
            { mqttId: 'system2' },
          ].filter(c => c.deviceId || c.mqttId)
        };

        const [fbDocs, fbCount] = await Promise.all([
          TelemetryLog.find(fallbackQuery)
            .sort(sortOrder)
            .limit(isLive ? 30 : 100000)
            .select('timestamp data topic room deviceId mqttId')
            .maxTimeMS(30000)
            .lean(),
          TelemetryLog.countDocuments(fallbackQuery).maxTimeMS(10000).catch(() => 0)
        ]);

        packets = fbDocs || [];
        totalInRange = fbCount || packets.length;
        totalInCollection = totalInCollection || totalInRange;
      } catch (e) {
        packets = [];
      }
    }

    // For live queries, reverse back to chronological order (oldest to newest) for chart rendering
    if (isLive && packets.length > 1) {
      packets.reverse();
    }

    // Custom sensor names if configured on device
    const customSensorNames = device.config?.sensor_names || {};

    const mappedFeeds = [];
    packets.forEach((p) => {
      const d = p.data || {};
      const packetTime = p.timestamp ? (typeof p.timestamp === 'string' ? p.timestamp : p.timestamp.toISOString()) : new Date().toISOString();

      if (device.deviceType === 'office_control') {
        const isMerged = (d.room1 !== undefined || d.room2 !== undefined || d.room3 !== undefined);

        if (isMerged) {
          if (room === 'both') {
            ['room1', 'room2', 'room3'].forEach((rName) => {
              const roomData = d[rName] || {};
              if (rName === 'room3') {
                mappedFeeds.push({
                  created_at: packetTime,
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
                  created_at: packetTime,
                  entry_id: mappedFeeds.length + 1,
                  room: rName,
                  field1: roomData.soil?.soil_temp !== undefined && roomData.soil?.soil_temp !== null ? String(roomData.soil.soil_temp) : (roomData.water_temp !== undefined && roomData.water_temp !== null ? String(roomData.water_temp) : null),
                  field2: roomData.soil?.moisture !== undefined && roomData.soil?.moisture !== null ? String(roomData.soil.moisture) : (roomData.moisture !== undefined && roomData.moisture !== null ? String(roomData.moisture) : null),
                  field3: roomData.soil?.ec !== undefined && roomData.soil?.ec !== null ? String(roomData.soil.ec) : (roomData.ec !== undefined && roomData.ec !== null ? String(roomData.ec) : null),
                  field4: roomData.soil?.ph !== undefined && roomData.soil?.ph !== null ? String(roomData.soil.ph) : (roomData.ph !== undefined && roomData.ph !== null ? String(roomData.ph) : null),
                  field5: roomData.room?.room_temp !== undefined && roomData.room?.room_temp !== null ? String(roomData.room.room_temp) : (roomData.room_temp !== undefined && roomData.room_temp !== null ? String(roomData.room_temp) : null),
                  field6: roomData.room?.room_humi !== undefined && roomData.room?.room_humi !== null ? String(roomData.room.room_humi) : (roomData.room_humi !== undefined && roomData.room_humi !== null ? String(roomData.room_humi) : null),
                  field7: roomData.orp !== undefined && roomData.orp !== null ? String(roomData.orp) : null,
                  field8: roomData.co2 !== undefined && roomData.co2 !== null ? String(roomData.co2) : null,
                });
              }
            });
          } else {
            const roomData = d[room] || {};
            if (room === 'room3') {
              mappedFeeds.push({
                created_at: packetTime,
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
                created_at: packetTime,
                entry_id: mappedFeeds.length + 1,
                room: room,
                field1: roomData.soil?.soil_temp !== undefined && roomData.soil?.soil_temp !== null ? String(roomData.soil.soil_temp) : (roomData.water_temp !== undefined && roomData.water_temp !== null ? String(roomData.water_temp) : null),
                field2: roomData.soil?.moisture !== undefined && roomData.soil?.moisture !== null ? String(roomData.soil.moisture) : (roomData.moisture !== undefined && roomData.moisture !== null ? String(roomData.moisture) : null),
                field3: roomData.soil?.ec !== undefined && roomData.soil?.ec !== null ? String(roomData.soil.ec) : (roomData.ec !== undefined && roomData.ec !== null ? String(roomData.ec) : null),
                field4: roomData.soil?.ph !== undefined && roomData.soil?.ph !== null ? String(roomData.soil.ph) : (roomData.ph !== undefined && roomData.ph !== null ? String(roomData.ph) : null),
                field5: roomData.room?.room_temp !== undefined && roomData.room?.room_temp !== null ? String(roomData.room.room_temp) : (roomData.room_temp !== undefined && roomData.room_temp !== null ? String(roomData.room_temp) : null),
                field6: roomData.room?.room_humi !== undefined && roomData.room?.room_humi !== null ? String(roomData.room.room_humi) : (roomData.room_humi !== undefined && roomData.room_humi !== null ? String(roomData.room_humi) : null),
                field7: roomData.orp !== undefined && roomData.orp !== null ? String(roomData.orp) : null,
                field8: roomData.co2 !== undefined && roomData.co2 !== null ? String(roomData.co2) : null,
              });
            }
          }
        } else {
          const packetRoom = p.topic && p.topic.toLowerCase().includes('room3') ? 'room3' : (p.topic && p.topic.toLowerCase().includes('room2') ? 'room2' : 'room1');
          if (room === 'both' || packetRoom === room) {
            if (packetRoom === 'room3') {
              mappedFeeds.push({
                created_at: packetTime,
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
                created_at: packetTime,
                entry_id: mappedFeeds.length + 1,
                room: packetRoom,
                field1: d.soil?.soil_temp !== undefined && d.soil?.soil_temp !== null ? String(d.soil.soil_temp) : (d.water_temp !== undefined && d.water_temp !== null ? String(d.water_temp) : null),
                field2: d.soil?.moisture !== undefined && d.soil?.moisture !== null ? String(d.soil.moisture) : (d.moisture !== undefined && d.moisture !== null ? String(d.moisture) : null),
                field3: d.soil?.ec !== undefined && d.soil?.ec !== null ? String(d.soil.ec) : (d.ec !== undefined && d.ec !== null ? String(d.ec) : null),
                field4: d.soil?.ph !== undefined && d.soil?.ph !== null ? String(d.soil.ph) : (d.ph !== undefined && d.ph !== null ? String(d.ph) : null),
                field5: d.room?.room_temp !== undefined && d.room?.room_temp !== null ? String(d.room.room_temp) : (d.room_temp !== undefined && d.room_temp !== null ? String(d.room_temp) : null),
                field6: d.room?.room_humi !== undefined && d.room?.room_humi !== null ? String(d.room.room_humi) : (d.room_humi !== undefined && d.room_humi !== null ? String(d.room_humi) : null),
                field7: d.orp !== undefined && d.orp !== null ? String(d.orp) : null,
                field8: d.co2 !== undefined && d.co2 !== null ? String(d.co2) : null,
              });
            }
          }
        }
      } else if (device.deviceType === 'multi_sensor' || device.deviceType === 'almora' || device.deviceType === 'almora2' || device.deviceType === 'cold_storage' || (device.name && (device.name.toLowerCase().includes('almora') || device.name.toLowerCase().includes('cold')))) {
        // Multi-sensor / Almora / Cold Storage mapping (supporting rooms, sensor_data, and S1-S7 structures)
        const getSensor = (sNum) => {
          const sLower = `s${sNum}`;
          const sUpper = `S${sNum}`;
          if (d[sLower]) return d[sLower];
          if (d[sUpper]) return d[sUpper];
          if (d.rooms && typeof d.rooms === 'object') {
            if (d.rooms[sUpper]) return d.rooms[sUpper];
            if (d.rooms[sLower]) return d.rooms[sLower];
          }
          if (d.sensor_data && typeof d.sensor_data === 'object') {
            if (d.sensor_data[sLower]) return d.sensor_data[sLower];
            if (d.sensor_data[sUpper]) return d.sensor_data[sUpper];
            for (const probe of Object.values(d.sensor_data)) {
              if (probe && (probe.id === sNum || probe.id === String(sNum))) {
                return probe;
              }
            }
          }
          if (d.sensors && typeof d.sensors === 'object') {
            if (d.sensors[sUpper]) return d.sensors[sUpper];
            if (d.sensors[sLower]) return d.sensors[sLower];
          }
          return null;
        };

        const getSensorTemp = (s, sNum) => {
          if (s) {
            const val = s.t ?? s.temp ?? s.temperature ?? s.room_temp;
            if (val !== undefined && val !== null && val !== '') return String(val);
          }
          // Only fallback to raw field if sNum provided and no explicit sensor object
          if (sNum) {
            const rawF = d[`field${sNum}`];
            if (rawF !== undefined && rawF !== null && rawF !== '') return String(rawF);
          }
          return null;
        };

        const getSensorHumi = (s, sNum) => {
          if (s) {
            const val = s.h ?? s.humi ?? s.humidity ?? s.hum ?? s.room_humi;
            if (val !== undefined && val !== null && val !== '') return String(val);
          }
          if (sNum) {
            const rawF = d[`field${sNum + 7}`];
            if (rawF !== undefined && rawF !== null && rawF !== '') return String(rawF);
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

        const co2Val = d.co2 ?? d.CO2 ?? d.co2_ppm ?? d.room?.co2 ?? s1?.co2 ?? s2?.co2 ?? s3?.co2 ?? s4?.co2 ?? s5?.co2 ?? s6?.co2 ?? s7?.co2 ?? (d.sensor_data && d.sensor_data.co2) ?? null;

        mappedFeeds.push({
          created_at: packetTime,
          entry_id: mappedFeeds.length + 1,
          field1: getSensorTemp(s1, 1),
          field2: getSensorTemp(s2, 2),
          field3: getSensorTemp(s3, 3),
          field4: getSensorTemp(s4, 4),
          field5: getSensorTemp(s5, 5),
          field6: getSensorTemp(s6, 6),
          field7: getSensorTemp(s7, 7),
          field8: getSensorHumi(s1, 1),
          field9: getSensorHumi(s2, 2),
          field10: getSensorHumi(s3, 3),
          field11: getSensorHumi(s4, 4),
          field12: getSensorHumi(s5, 5),
          field13: getSensorHumi(s6, 6),
          field14: getSensorHumi(s7, 7),
          field15: co2Val !== null && co2Val !== undefined && co2Val !== '' ? String(co2Val) : null,
          multi_sensor_data: {
            S1: { temp: getSensorTemp(s1, 1), humi: getSensorHumi(s1, 1), t: getSensorTemp(s1, 1), h: getSensorHumi(s1, 1), co2: s1?.co2 ?? null, status: s1?.status || 'OK' },
            S2: { temp: getSensorTemp(s2, 2), humi: getSensorHumi(s2, 2), t: getSensorTemp(s2, 2), h: getSensorHumi(s2, 2), co2: s2?.co2 ?? null, status: s2?.status || 'OK' },
            S3: { temp: getSensorTemp(s3, 3), humi: getSensorHumi(s3, 3), t: getSensorTemp(s3, 3), h: getSensorHumi(s3, 3), co2: s3?.co2 ?? null, status: s3?.status || 'OK' },
            S4: { temp: getSensorTemp(s4, 4), humi: getSensorHumi(s4, 4), t: getSensorTemp(s4, 4), h: getSensorHumi(s4, 4), co2: s4?.co2 ?? null, status: s4?.status || 'OK' },
            S5: { temp: getSensorTemp(s5, 5), humi: getSensorHumi(s5, 5), t: getSensorTemp(s5, 5), h: getSensorHumi(s5, 5), co2: s5?.co2 ?? null, status: s5?.status || 'OK' },
            S6: { temp: getSensorTemp(s6, 6), humi: getSensorHumi(s6, 6), t: getSensorTemp(s6, 6), h: getSensorHumi(s6, 6), co2: s6?.co2 ?? null, status: s6?.status || 'OK' },
            S7: { temp: getSensorTemp(s7, 7), humi: getSensorHumi(s7, 7), t: getSensorTemp(s7, 7), h: getSensorHumi(s7, 7), co2: s7?.co2 ?? null, status: s7?.status || 'OK' },
          }
        });
      } else if (device.deviceType === 'controlling') {
        const tel = d.telemetry || d.sensors || d || {};
        mappedFeeds.push({
          created_at: packetTime,
          entry_id: mappedFeeds.length + 1,
          field1: tel.water_temp != null ? String(tel.water_temp) : (tel.temp != null ? String(tel.temp) : null),
          field2: tel.moisture != null ? String(tel.moisture) : (tel.moist != null ? String(tel.moist) : null),
          field3: tel.ec != null ? String(tel.ec) : null,
          field4: tel.ph != null ? String(tel.ph) : null,
          field5: tel.room_temp != null ? String(tel.room_temp) : (tel.temp_room != null ? String(tel.temp_room) : null),
          field6: tel.room_humi != null ? String(tel.room_humi) : (tel.humidity_room != null ? String(tel.humidity_room) : null),
          field7: tel.orp != null ? String(tel.orp) : null,
          field8: tel.co2 != null ? String(tel.co2) : null,
          field9: tel.vpd != null ? String(tel.vpd) : null,
          field10: tel.dli != null ? String(tel.dli) : null,
          field11: tel.wind_speed != null ? String(tel.wind_speed) : null,
          field12: tel.wind_dir != null ? String(tel.wind_dir) : (tel.wind_direction != null ? String(tel.wind_direction) : null),
          field13: tel.do != null ? String(tel.do) : (tel.dissolved_oxygen != null ? String(tel.dissolved_oxygen) : null),
          field14: tel.ppfd != null ? String(tel.ppfd) : null,
          field15: tel.n != null ? String(tel.n) : (tel.nitrogen != null ? String(tel.nitrogen) : null),
          field16: tel.p != null ? String(tel.p) : (tel.phosphorus != null ? String(tel.phosphorus) : null),
          field17: tel.k != null ? String(tel.k) : (tel.potassium != null ? String(tel.potassium) : null),
        });
      } else if (device.deviceType === 'monit' || device.deviceType === 'monnet' || device.deviceType === 'dosing') {
        mappedFeeds.push({
          created_at: packetTime,
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
      } else if (device.deviceType === 'itc_polyhouse') {
        const sData = d.sensor_data || {};
        const dliData = d.dli_data?.accumulators || {};
        const phKeys = ['PH-01', 'PH-02', 'PH-03', 'PH-04', 'PH-05', 'PH-06'];
        const targetPh = room && phKeys.includes(room.toUpperCase()) ? room.toUpperCase() : null;

        if (targetPh) {
          const phObj = sData[targetPh] || {};
          const dliObj = dliData[targetPh] || {};
          mappedFeeds.push({
            created_at: packetTime,
            entry_id: mappedFeeds.length + 1,
            room: targetPh,
            field1: phObj.temp != null ? String(phObj.temp) : null,
            field2: phObj.humi != null ? String(phObj.humi) : null,
            field3: phObj.co2 != null ? String(phObj.co2) : null,
            field4: phObj.par != null ? String(phObj.par) : null,
            field5: dliObj.dli != null ? String(dliObj.dli) : (phObj.dli != null ? String(phObj.dli) : null),
            polyhouse_data: { [targetPh]: phObj }
          });
        } else {
          const ph1 = sData['PH-01'] || {};
          const ph2 = sData['PH-02'] || {};
          const ph3 = sData['PH-03'] || {};
          const ph4 = sData['PH-04'] || {};
          const ph5 = sData['PH-05'] || {};
          const ph6 = sData['PH-06'] || {};
          mappedFeeds.push({
            created_at: packetTime,
            entry_id: mappedFeeds.length + 1,
            field1: ph1.temp != null ? String(ph1.temp) : null,
            field2: ph2.temp != null ? String(ph2.temp) : null,
            field3: ph3.temp != null ? String(ph3.temp) : null,
            field4: ph4.temp != null ? String(ph4.temp) : null,
            field5: ph5.temp != null ? String(ph5.temp) : null,
            field6: ph6.temp != null ? String(ph6.temp) : null,
            field7: ph1.humi != null ? String(ph1.humi) : null,
            field8: ph2.humi != null ? String(ph2.humi) : null,
            field9: ph3.humi != null ? String(ph3.humi) : null,
            field10: ph4.humi != null ? String(ph4.humi) : null,
            field11: ph5.humi != null ? String(ph5.humi) : null,
            field12: ph6.humi != null ? String(ph6.humi) : null,
            field13: ph1.co2 != null ? String(ph1.co2) : null,
            field14: ph1.par != null ? String(ph1.par) : null,
            polyhouse_data: sData
          });
        }
      } else {
        // Standard / system2 mapping
        const tel = d.telemetry || d || {};
        mappedFeeds.push({
          created_at: packetTime,
          entry_id: mappedFeeds.length + 1,
          field1: tel.water_temp != null ? String(tel.water_temp) : (tel.temp != null ? String(tel.temp) : null),
          field2: tel.moisture != null ? String(tel.moisture) : (tel.moist != null ? String(tel.moist) : null),
          field3: tel.ec != null ? String(tel.ec) : null,
          field4: tel.ph != null ? String(tel.ph) : null,
          field5: tel.room_temp != null ? String(tel.room_temp) : null,
          field6: tel.room_humi != null ? String(tel.room_humi) : null,
          field7: tel.orp != null ? String(tel.orp) : null,
          field8: tel.co2 != null ? String(tel.co2) : null,
        });
      }
    });

    // ── Peak-Preserving Downsampling (Guarantees charts never freeze, renders in < 16ms) ──
    const isRaw = req.query.raw === 'true' || req.query.downsample === 'false' || isExport;
    let feeds;
    const maxSamplePoints = parseInt(req.query.sampleLimit || req.query.limit) || 1200;
    if (!isRaw && mappedFeeds.length > maxSamplePoints) {
      feeds = downsampleFeeds(mappedFeeds, maxSamplePoints);
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

    // Apply deviceType-based and custom labels
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
    } else if (device.deviceType === 'multi_sensor' || device.deviceType === 'almora' || device.deviceType === 'almora2' || device.deviceType === 'cold_storage' || (device.name && (device.name.toLowerCase().includes('almora') || device.name.toLowerCase().includes('cold')))) {
      // Re-initialize channelData completely for Cold Storage so NO hydro metrics (Water Temp, Water EC, Water pH, ORP, etc.) leak through
      channelData = {
        id: device.mqttId || device._id.toString(),
        name: device.name,
      };

      const sName = (sKey, def) => customSensorNames[sKey] || def;
      const s1Name = sName('S1', 'Cold Room 1');
      const s2Name = sName('S2', 'Cold Room 2');
      const s3Name = sName('S3', 'Cold Room 3');
      const s4Name = sName('S4', 'Cold Room 4');
      const s5Name = sName('S5', 'Cold Room 5');
      const s6Name = sName('S6', 'Cold Room 6');
      const s7Name = sName('S7', 'Greenhouse');

      const roomNames = { S1: s1Name, S2: s2Name, S3: s3Name, S4: s4Name, S5: s5Name, S6: s6Name, S7: s7Name };
      const isSingleRoom = room && room !== 'all' && room !== 'both';
      const targetRoomKey = isSingleRoom ? (room.toUpperCase().startsWith('S') ? room.toUpperCase() : `S${room.replace(/\D/g, '')}`) : null;

      if (targetRoomKey && ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].includes(targetRoomKey)) {
        const sIndex = parseInt(targetRoomKey.replace('S', ''), 10);
        const tempField = `field${sIndex}`;
        const humiField = `field${sIndex + 7}`;
        channelData[tempField] = `${roomNames[targetRoomKey] || targetRoomKey} Temp`;
        channelData[humiField] = `${roomNames[targetRoomKey] || targetRoomKey} Humidity`;

        const hasCo2 = mappedFeeds.some(f => f.field15 != null && f.field15 !== '');
        if (hasCo2) {
          channelData.field15 = 'CO2 Level';
        }
      } else {
        channelData.field1 = `${s1Name} Temp`;
        channelData.field2 = `${s2Name} Temp`;
        channelData.field3 = `${s3Name} Temp`;
        channelData.field4 = `${s4Name} Temp`;
        channelData.field5 = `${s5Name} Temp`;
        channelData.field6 = `${s6Name} Temp`;
        channelData.field7 = `${s7Name} Temp`;
        channelData.field8 = `${s1Name} Humidity`;
        channelData.field9 = `${s2Name} Humidity`;
        channelData.field10 = `${s3Name} Humidity`;
        channelData.field11 = `${s4Name} Humidity`;
        channelData.field12 = `${s5Name} Humidity`;
        channelData.field13 = `${s6Name} Humidity`;
        channelData.field14 = `${s7Name} Humidity`;

        const hasCo2 = mappedFeeds.some(f => f.field15 != null && f.field15 !== '');
        if (hasCo2) {
          channelData.field15 = 'CO2 Level';
        }
      }
    } else if (device.deviceType === 'monit' || device.deviceType === 'monnet') {
      channelData.field1 = 'Water Temp';
      channelData.field2 = 'Water Moisture';
      channelData.field3 = 'Water EC';
      channelData.field4 = 'Water pH';
      channelData.field5 = 'Room Temp';
      channelData.field6 = 'Room Humidity';
      channelData.field7 = 'ORP';
      channelData.field8 = 'CO2';
    } else if (device.deviceType === 'itc_polyhouse') {
      channelData = {
        id: device.mqttId || device._id.toString(),
        name: device.name,
      };
      const phKeys = ['PH-01', 'PH-02', 'PH-03', 'PH-04', 'PH-05', 'PH-06'];
      const targetRoom = room && phKeys.includes(room.toUpperCase()) ? room.toUpperCase() : null;
      if (targetRoom) {
        channelData.field1 = `${targetRoom} Temperature`;
        channelData.field2 = `${targetRoom} Humidity`;
        channelData.field3 = `${targetRoom} CO2`;
        channelData.field4 = `${targetRoom} PAR (PPFD)`;
        channelData.field5 = `${targetRoom} DLI Integral`;
      } else {
        channelData.field1 = 'PH-01 Temp';
        channelData.field2 = 'PH-02 Temp';
        channelData.field3 = 'PH-03 Temp';
        channelData.field4 = 'PH-04 Temp';
        channelData.field5 = 'PH-05 Temp';
        channelData.field6 = 'PH-06 Temp';
        channelData.field7 = 'PH-01 Humidity';
        channelData.field8 = 'PH-02 Humidity';
        channelData.field9 = 'PH-03 Humidity';
        channelData.field10 = 'PH-04 Humidity';
        channelData.field11 = 'PH-05 Humidity';
        channelData.field12 = 'PH-06 Humidity';
        channelData.field13 = 'PH-01 CO2';
        channelData.field14 = 'PH-01 PAR';
      }
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
        return `${year}-${month}-${day} ${hours12}:${minutes}:${second} ${ampm}`;
      }
    };

    if (req.query.format === 'csv') {
      const isBoth = room === 'both' || (room === 'all' && device.deviceType === 'office_control');
      const timezone = req.query.timezone || 'Asia/Kolkata';
      const headers = ['Timestamp'];
      if (isBoth) headers.push('Room');

      const activeFields = [];
      for (let i = 1; i <= 17; i++) {
        const key = `field${i}`;
        const rawName = channelData[key] || (device.deviceType === 'controlling' ? `Field ${i}` : null);
        if (!rawName) continue;
        const cleanName = rawName.replace(/\bSoil\b/gi, 'Water');
        const hasData = mappedFeeds.some(f => f[key] != null && f[key] !== '' && f[key] !== 'null' && f[key] !== 'undefined');
        if (hasData) {
          let unit = '';
          const lower = cleanName.toLowerCase();
          if (lower.includes('temp')) unit = ' (°C)';
          else if (lower.includes('moist') || lower.includes('hum')) unit = ' (%)';
          else if (lower.includes('ec')) unit = ' (mS/cm)';
          else if (lower.includes('ph')) unit = ' (pH)';
          else if (lower.includes('orp')) unit = ' (mV)';
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

          activeFields.push({ key, name: `${cleanName}${unit}` });
          headers.push(`"${cleanName}${unit}"`);
        }
      }

      const rows = mappedFeeds.map(f => {
        const readableTime = formatHumanReadableDate(f.created_at, timezone);
        const rowCells = [`"${readableTime}"`];
        if (isBoth) rowCells.push(`"${f.room || 'room1'}"`);
        activeFields.forEach(af => {
          const val = f[af.key] !== undefined && f[af.key] !== null && f[af.key] !== 'null' ? f[af.key] : '';
          rowCells.push(val !== '' ? val : '');
        });
        return rowCells.join(',');
      });

      const csvContent = headers.join(',') + '\n' + rows.join('\n');
      const safeSlug = String(device.name || 'Device').replace(/[^a-z0-9_-]/gi, '_');
      const roomSlug = room && room !== 'all' && room !== 'both' ? `_${String(room).replace(/[^a-z0-9_-]/gi, '_')}` : '';
      res.setHeader('Content-Type', 'text/csv; charset=utf-8');
      res.setHeader('Content-Disposition', `attachment; filename="${safeSlug}${roomSlug}_Analytics.csv"`);
      return res.status(200).send(csvContent);
    }

    if (req.query.format === 'json' && isExport) {
      const isBoth = room === 'both' || (room === 'all' && device.deviceType === 'office_control');
      const timezone = req.query.timezone || 'Asia/Kolkata';
      const activeFields = [];
      for (let i = 1; i <= 17; i++) {
        const key = `field${i}`;
        const rawName = channelData[key] || (device.deviceType === 'controlling' ? `Field ${i}` : null);
        if (!rawName) continue;
        const cleanName = rawName.replace(/\bSoil\b/gi, 'Water');
        const hasData = mappedFeeds.some(f => f[key] != null && f[key] !== '' && f[key] !== 'null' && f[key] !== 'undefined');
        if (hasData) {
          activeFields.push({ key, name: cleanName });
        }
      }
      const exportJson = mappedFeeds.map(f => {
        const readableTime = formatHumanReadableDate(f.created_at, timezone);
        const obj = { timestamp: readableTime, rawTimestamp: f.created_at };
        if (isBoth) obj.room = f.room || 'room1';
        activeFields.forEach(af => {
          obj[af.name] = f[af.key] !== undefined && f[af.key] !== null && f[af.key] !== '' && f[af.key] !== 'null' ? parseFloat(f[af.key]) || f[af.key] : null;
        });
        return obj;
      });
      const safeSlug = String(device.name || 'Device').replace(/[^a-z0-9_-]/gi, '_');
      const roomSlug = room && room !== 'all' && room !== 'both' ? `_${String(room).replace(/[^a-z0-9_-]/gi, '_')}` : '';
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.setHeader('Content-Disposition', `attachment; filename="${safeSlug}${roomSlug}_Analytics.json"`);
      return res.status(200).json(exportJson);
    }

    const reportedTotalPoints = Math.max(totalInRange, mappedFeeds.length);
    const reportedCollectionDocs = Math.max(totalInCollection, reportedTotalPoints);

    const responseBody = {
      success: true,
      channel: channelData,
      feeds: feeds,
      totalDbPoints: reportedTotalPoints,
      totalCollectionDocs: reportedCollectionDocs,
      totalFeeds: reportedTotalPoints,
    };

    // ── Redis Cache Store ──
    if (useCache && cacheKey) {
      const ttl = resolveTTL(start, end);
      setCache(cacheKey, responseBody, ttl).catch(() => {}); // non-blocking, fire & forget
    }

    res.status(200).json(responseBody);
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

  // Immediately send cached DB setpoints & crop programs if available
  try {
    const lookupKey = filterDeviceId || filterMqttId;
    if (lookupKey) {
      resolveDeviceByIdOrMqtt(lookupKey).then(dev => {
        if (dev && !isClosed) {
          const progs = dev.cropPrograms || {};
          const setps = dev.settings || {};
          const cfg = dev.config || {};
          if (Object.keys(progs).length > 0 || Object.keys(setps).length > 0 || Object.keys(cfg).length > 0) {
            const initPayload = {
              deviceId: dev._id ? dev._id.toString() : null,
              mqttId: dev.mqttId || null,
              topic: dev.mqttId ? `inhydro/${dev.mqttId}/setpoints/current` : '',
              data: {
                crop_programs: progs,
                saved_programs: progs,
                sensor_setpoints: setps,
                system_config: cfg,
                timestamp: new Date().toISOString()
              }
            };
            res.write(`data: ${JSON.stringify(initPayload)}\n\n`);
          }
        }
      }).catch(() => { });
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
// @desc    Read saved crop programs partitioned by room (S1..S7)
exports.getCropPrograms = async (req, res) => {
  try {
    const fs = require('fs');
    const path = require('path');
    const cropFile = path.resolve(__dirname, '../../crop_programs.json');
    let progs = { S1: {}, S2: {}, S3: {}, S4: {}, S5: {}, S6: {}, S7: {} };

    // Check DB first
    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    if (device?.cropPrograms && typeof device.cropPrograms === 'object') {
      progs = { ...progs, ...device.cropPrograms };
    }

    const room = (req.query.room || '').toUpperCase();
    const count = room && progs[room] ? Object.keys(progs[room]).length : Object.values(progs).reduce((acc, r) => acc + (r && typeof r === 'object' ? Object.keys(r).length : 0), 0);
    res.status(200).json({ success: true, count, data: progs });
  } catch (err) {
    console.error('getCropPrograms error:', err);
    res.status(500).json({ success: false, message: err.message });
  }
};

// @route   POST /api/devices/:id/programs
// @desc    Save a room-specific program (max 20 programs per room, max 10 stages each) and publish to MQTT
exports.saveCropProgram = async (req, res) => {
  try {
    const { program_name, name, settings, room, port } = req.body;
    const pName = (program_name || name || '').trim();
    if (!pName) {
      return res.status(400).json({ success: false, message: 'Program name required' });
    }
    const rKey = (room || port || 'S1').toUpperCase();

    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    const devId = (device?.mqttId || (device?._id ? device._id.toString() : req.params.id)).toString();

    let progs = { S1: {}, S2: {}, S3: {}, S4: {}, S5: {}, S6: {}, S7: {} };
    if (device?.cropPrograms && typeof device.cropPrograms === 'object') {
      progs = { ...progs, ...device.cropPrograms };
    }
    if (!progs[rKey] || typeof progs[rKey] !== 'object') progs[rKey] = {};

    // Enforce max 20 programs per room
    const currentRoomProgKeys = Object.keys(progs[rKey]);
    if (currentRoomProgKeys.length >= 20 && !progs[rKey][pName]) {
      return res.status(400).json({ success: false, message: `Maximum 20 programs limit reached for ${rKey}` });
    }

    progs[rKey][pName] = settings || {};

    if (device) {
      const curSetps = { ...(device.settings || {}) };
      if (!curSetps[rKey]) curSetps[rKey] = {};
      curSetps[rKey].program_name = pName;
      if (settings) curSetps[rKey].settings = settings;

      await Device.findByIdAndUpdate(device._id, {
        $set: {
          cropPrograms: progs,
          settings: curSetps
        }
      }).catch(() => { });
    }

    // Broadcast over MQTT strictly with room/port specified
    const mqttPayload = { action: 'save_program', program_name: pName, room: rKey, port: rKey, settings };
    const targetMqttId = (device?.mqttId || req.params.id || devId).toString();
    await publishToDevice(`inhydro/${targetMqttId}/setpoints/update`, mqttPayload);
    if (targetMqttId !== targetMqttId.toLowerCase()) {
      await publishToDevice(`inhydro/${targetMqttId.toLowerCase()}/setpoints/update`, mqttPayload);
    }

    const count = Object.keys(progs[rKey]).length;
    res.status(200).json({ success: true, count, data: progs, message: `Program "${pName}" saved for ${rKey}` });
  } catch (err) {
    console.error('saveCropProgram error:', err);
    res.status(500).json({ success: false, message: err.message });
  }
};

// @route   DELETE /api/devices/:id/programs/:programName
// @desc    Delete a program from room-specific library and publish to MQTT
exports.deleteCropProgram = async (req, res) => {
  try {
    const pName = decodeURIComponent(req.params.programName || '').trim();
    if (!pName) {
      return res.status(400).json({ success: false, message: 'Program name required' });
    }
    const rKey = (req.query.room || req.body?.room || req.query.port || req.body?.port || '').toUpperCase();

    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    const devId = (device?.mqttId || (device?._id ? device._id.toString() : req.params.id)).toString();

    let progs = { S1: {}, S2: {}, S3: {}, S4: {}, S5: {}, S6: {}, S7: {} };
    if (device?.cropPrograms && typeof device.cropPrograms === 'object') {
      progs = { ...progs, ...device.cropPrograms };
    }

    if (rKey && progs[rKey] && typeof progs[rKey] === 'object') {
      delete progs[rKey][pName];
    } else {
      ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].forEach(k => {
        if (progs[k] && typeof progs[k] === 'object') delete progs[k][pName];
      });
      delete progs[pName];
    }

    if (device) {
      const curSetps = { ...(device.settings || {}) };
      const roomsToCheck = rKey ? [rKey] : ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'];
      roomsToCheck.forEach(k => {
        if (curSetps[k]?.program_name === pName) {
          curSetps[k].program_name = 'Default Program';
        }
      });
      await Device.findByIdAndUpdate(device._id, {
        $set: {
          cropPrograms: progs,
          settings: curSetps
        }
      }).catch(() => { });
    }

    // Broadcast over MQTT
    const mqttPayload = { action: 'delete_program', program_name: pName, room: rKey || undefined };
    const targetMqttId = (device?.mqttId || req.params.id || devId).toString();
    await publishToDevice(`inhydro/${targetMqttId}/setpoints/update`, mqttPayload);
    if (targetMqttId !== targetMqttId.toLowerCase()) {
      await publishToDevice(`inhydro/${targetMqttId.toLowerCase()}/setpoints/update`, mqttPayload);
    }

    res.status(200).json({ success: true, data: progs, message: `Program "${pName}" deleted successfully` });
  } catch (err) {
    console.error('deleteCropProgram error:', err);
    res.status(500).json({ success: false, message: err.message });
  }
};

// @route   POST /api/devices/:id/programs/:programName/apply
// @desc    Apply a saved program to a specific room
exports.applyCropProgram = async (req, res) => {
  try {
    const pName = decodeURIComponent(req.params.programName || '').trim();
    const { room, port } = req.body;
    const rKey = (room || port || 'S1').toUpperCase();

    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    const devId = (device?.mqttId || (device?._id ? device._id.toString() : req.params.id)).toString();

    let progs = {};
    if (device?.cropPrograms && typeof device.cropPrograms === 'object') {
      progs = device.cropPrograms;
    }
    const progSettings = progs[rKey]?.[pName] || progs[pName] || req.body.settings;
    if (!progSettings) {
      return res.status(404).json({ success: false, message: `Program "${pName}" not found for ${rKey}` });
    }

    let curSetps = {};
    if (device) {
      curSetps = { ...(device.settings || {}) };
      if (!curSetps[rKey]) curSetps[rKey] = {};
      curSetps[rKey].program_name = pName;
      curSetps[rKey].settings = progSettings;

      await Device.findByIdAndUpdate(device._id, {
        $set: { settings: curSetps }
      }).catch(() => { });
    }

    // Broadcast over MQTT
    const mqttPayload = { action: 'apply_program', program_name: pName, room: rKey, port: rKey, settings: progSettings };
    const targetMqttId = (device?.mqttId || req.params.id || devId).toString();
    await publishToDevice(`inhydro/${targetMqttId}/setpoints/update`, mqttPayload);
    if (targetMqttId !== targetMqttId.toLowerCase()) {
      await publishToDevice(`inhydro/${targetMqttId.toLowerCase()}/setpoints/update`, mqttPayload);
    }

    res.status(200).json({ success: true, setpoints: curSetps, message: `Program "${pName}" applied to ${rKey}` });
  } catch (err) {
    console.error('applyCropProgram error:', err);
    res.status(500).json({ success: false, message: err.message });
  }
};

// @route   GET /api/devices/:id/setpoints-json
// @desc    Read setpoints and system_config strictly from MongoDB
exports.getSetpointsJson = async (req, res) => {
  try {
    const device = await resolveDeviceByIdOrMqtt(req.params.id);
    let setps = device?.settings || {};
    let cfg = device?.config || {};
    res.status(200).json({ success: true, data: setps, system_config: cfg });
  } catch (err) {
    console.error('getSetpointsJson error:', err);
    res.status(500).json({ success: false, message: err.message });
  }
};
