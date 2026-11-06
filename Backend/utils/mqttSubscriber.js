const mqtt = require('mqtt');
const mongoose = require('mongoose');
const Device = require('../models/Device');
const { getTelemetryModel } = require('../models/TelemetryLog');
const EventEmitter = require('events');

// Enterprise EventEmitter with high listener ceiling for 10,000+ real-time subscribers
const telemetryEmitter = new EventEmitter();
telemetryEmitter.setMaxListeners(50000);

const BROKER_URL = process.env.MQTT_BROKER_URL || 'mqtt://147.93.106.142:1883';

// ── In-Memory Hot State Caches (P2 Zero-DB Ingestion Optimization) ───────────
// Caches mqttId / name / id -> { id: ObjectId, status: string }
const deviceCache = new Map();
const deviceStatusCache = new Map(); // deviceId (string) -> status ('active' | 'blocked' | 'offline' | 'online')

/**
 * Preloads all registered devices into memory cache on startup.
 * Ensures zero MongoDB lookups during high-frequency telemetry ingestion.
 */
const preloadDeviceCache = async () => {
  try {
    const devices = await Device.find({}).select('_id mqttId name deviceName status deviceType');
    devices.forEach((dev) => {
      const info = { id: dev._id, status: dev.status || 'active' };
      const idStr = String(dev._id);
      if (dev.mqttId) deviceCache.set(String(dev.mqttId).toLowerCase(), info);
      if (dev.name) deviceCache.set(String(dev.name).toLowerCase(), info);
      if (dev.deviceName) deviceCache.set(String(dev.deviceName).toLowerCase(), info);
      if (dev.deviceType === 'fertigation') deviceCache.set('fertigation', info);
      if (dev.deviceType === 'office_control') deviceCache.set('system2', info);
      deviceCache.set(idStr, info);
      deviceStatusCache.set(idStr, dev.status || 'active');
    });
    console.log(`✅ [MQTT Subscriber] Preloaded ${devices.length} devices into zero-latency memory cache.`);
  } catch (err) {
    console.error('[MQTT Subscriber] Failed to preload device cache:', err.message);
  }
};

/**
 * Resolves device info from fast memory cache, falling back to MongoDB once if newly registered.
 * @param {string} mqttId 
 * @returns {Promise<{ id: mongoose.Types.ObjectId, status: string } | null>}
 */
const resolveDeviceInfo = async (mqttId) => {
  if (!mqttId) return null;
  const cleanKey = String(mqttId).toLowerCase();

  if (deviceCache.has(cleanKey)) {
    return deviceCache.get(cleanKey);
  }

  // Fallback DB query if newly added device hasn't been cached yet
  try {
    const cleanRegex = cleanKey.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const device = await Device.findOne({
      $or: [
        { mqttId: { $regex: new RegExp(`^${cleanRegex}$`, 'i') } },
        { name: { $regex: new RegExp(`^${cleanRegex}$`, 'i') } },
        { deviceName: { $regex: new RegExp(`^${cleanRegex}$`, 'i') } },
        { deviceType: cleanKey === 'fertigation' ? 'fertigation' : (cleanKey === 'system2' ? 'office_control' : null) },
        { _id: mongoose.Types.ObjectId.isValid(mqttId) ? mqttId : null }
      ].filter(Boolean)
    }).select('_id mqttId name deviceName status');

    if (device) {
      const info = { id: device._id, status: device.status || 'active' };
      const idStr = String(device._id);
      deviceCache.set(cleanKey, info);
      if (device.mqttId) deviceCache.set(String(device.mqttId).toLowerCase(), info);
      deviceCache.set(idStr, info);
      deviceStatusCache.set(idStr, device.status || 'active');
      return info;
    }
  } catch (e) { }

  return null;
};

/**
 * Update memory cache when device status changes (e.g. blocked, unblocked, deleted).
 */
const updateDeviceCacheStatus = (deviceId, newStatus) => {
  const idStr = String(deviceId);
  deviceStatusCache.set(idStr, newStatus);
  for (const [key, val] of deviceCache.entries()) {
    if (val && String(val.id) === idStr) {
      val.status = newStatus;
    }
  }
};

// ── In-Memory Device State Batching Buffer (P2 MongoDB Write Reducer) ─────────
// Buffers metadata updates (lastUpdated, cropName, settings, config) and flushes via bulkWrite
const deviceUpdateBuffer = new Map(); // id (string) -> fields

const queueDeviceStateUpdate = (deviceId, fields) => {
  if (!deviceId || !fields || Object.keys(fields).length === 0) return;
  const idStr = String(deviceId);
  const existing = deviceUpdateBuffer.get(idStr) || {};
  deviceUpdateBuffer.set(idStr, { ...existing, ...fields });
};

const flushDeviceStateUpdates = async () => {
  if (deviceUpdateBuffer.size === 0) return;

  const entries = Array.from(deviceUpdateBuffer.entries());
  deviceUpdateBuffer.clear(); // Drain immediately

  const bulkOps = entries.map(([id, fields]) => ({
    updateOne: {
      filter: { _id: id },
      update: { $set: fields }
    }
  }));

  const CHUNK_SIZE = 500;
  for (let i = 0; i < bulkOps.length; i += CHUNK_SIZE) {
    const chunk = bulkOps.slice(i, i + CHUNK_SIZE);
    try {
      await Device.bulkWrite(chunk, { ordered: false });
    } catch (err) {
      console.error('[MQTT Device BulkWrite] Error updating device statuses:', err.message);
    }
  }
};

// ── In-Memory Telemetry Write Queue & Parallel Batch Flush Engine ─────────────
const writeBuffer = new Map(); // cleanId -> Array of docs

const queueTelemetryDoc = (mqttId, doc) => {
  const cleanId = String(mqttId).toLowerCase();
  if (!writeBuffer.has(cleanId)) {
    writeBuffer.set(cleanId, []);
  }
  const queue = writeBuffer.get(cleanId);
  queue.push(doc);

  // If buffer for this device exceeds 250 items, trigger immediate flush
  if (queue.length >= 250) {
    flushDeviceQueue(cleanId);
  }
};

const flushDeviceQueue = async (cleanId) => {
  const docs = writeBuffer.get(cleanId);
  if (!docs || docs.length === 0) return;

  writeBuffer.delete(cleanId); // Drain immediately

  try {
    const TelemetryModel = getTelemetryModel(cleanId);
    await TelemetryModel.insertMany(docs, { ordered: false });
  } catch (err) {
    console.error(`[MQTT Buffer Flush] Error saving batch for "${cleanId}":`, err.message);
  }
};

const flushAllQueues = async () => {
  const keys = Array.from(writeBuffer.keys());
  if (keys.length === 0) return;

  // Process collections concurrently in pools of 25 at a time
  const CONCURRENCY = 25;
  for (let i = 0; i < keys.length; i += CONCURRENCY) {
    const chunk = keys.slice(i, i + CONCURRENCY);
    await Promise.allSettled(chunk.map((k) => flushDeviceQueue(k)));
  }
};

// ── Starts MQTT Subscriber Daemon ─────────────────────────────────────────────
const startMqttSubscriber = () => {
  console.log(`[MQTT Subscriber] Connecting to Mosquitto VPS broker: ${BROKER_URL}`);

  // Warm device cache immediately
  preloadDeviceCache();

  const options = {
    clientId: `backend_subscriber_daemon_${Date.now()}`,
    username: process.env.MQTT_USERNAME,
    password: process.env.MQTT_PASSWORD,
    clean: true,
    reconnectPeriod: 5000,
    rejectUnauthorized: false,
  };
  const client = mqtt.connect(BROKER_URL, options);

  client.on('connect', () => {
    console.log('✅ [MQTT Subscriber] Connected to Mosquitto VPS broker.');

    client.subscribe('inhydro/#', (err) => {
      if (err) console.error('[MQTT Subscriber] Failed to subscribe to inhydro/# topics:', err);
      else console.log('✅ [MQTT Subscriber] Subscribed to inhydro/# (all private broker device telemetry)');
    });
  });

  client.on('message', async (topic, message, packet) => {
    try {
      const topicParts = topic.split('/');
      const mqttId = topicParts[1];

      if (!mqttId) return;

      // Parse payload
      const payloadString = message.toString();
      let payloadData;
      try {
        payloadData = JSON.parse(payloadString);
      } catch (e) {
        payloadData = { raw: payloadString };
      }

      const isRetain = Boolean(packet && packet.retain);
      const rawTs = payloadData?.timestamp || payloadData?.created_at || payloadData?.time;
      const parsedTime = rawTs && !isNaN(new Date(typeof rawTs === 'string' && rawTs.includes(' ') && !rawTs.includes('T') ? rawTs.replace(' ', 'T') : rawTs).getTime())
        ? new Date(typeof rawTs === 'string' && rawTs.includes(' ') && !rawTs.includes('T') ? rawTs.replace(' ', 'T') : rawTs)
        : null;

      const now = new Date();

      // Check if this is an outbound server command / setpoint push topic
      const isOutboundTopic =
        topic.endsWith('/setpoints/update') ||
        topic.endsWith('/setpoints/set') ||
        topic.endsWith('/config/update') ||
        topic.endsWith('/command') ||
        topic.endsWith('/setpoints/request_sync') ||
        topic.includes('/command/') ||
        topic.endsWith('/command/status');

      // Check if this payload contains sensor/device telemetry data or heartbeat
      const hasTelemetryData = Boolean(
        payloadData && typeof payloadData === 'object' && (
          payloadData.sensor_data ||
          payloadData.rooms ||
          payloadData.S1 || payloadData.S2 || payloadData.S3 || payloadData.S4 || payloadData.S5 || payloadData.S6 || payloadData.S7 ||
          payloadData.temp !== undefined || payloadData.t !== undefined || payloadData.temperature !== undefined ||
          payloadData.humi !== undefined || payloadData.h !== undefined || payloadData.humidity !== undefined ||
          payloadData.co2 !== undefined || payloadData.ec !== undefined || payloadData.ph !== undefined ||
          payloadData.relays || payloadData.relay_states ||
          payloadData.sensors || Array.isArray(payloadData.data) || Array.isArray(payloadData.readings) ||
          payloadData.status === 'online' || payloadData.heartbeat !== undefined || payloadData.ping !== undefined ||
          topic.includes('/heartbeat') || topic.includes('/telemetry') || topic.includes('/status')
        )
      );

      const isFresh = !isOutboundTopic && hasTelemetryData && (
        !isRetain
          ? true
          : Boolean(parsedTime && Math.abs(now.getTime() - parsedTime.getTime()) < 180 * 1000)
      );

      const packetTimestamp = !isRetain ? now : (parsedTime || now);

      // Resolve device info from zero-latency memory cache
      const devInfo = await resolveDeviceInfo(mqttId);
      const deviceId = devInfo ? devInfo.id : null;

      // Check if device is blocked (in-memory lookup: 0ms)
      if (devInfo && devInfo.status === 'blocked') {
        return; // Device is blocked, ignore telemetry
      }

      if (deviceId) {
        const updateFields = {};

        if (isFresh && packetTimestamp) {
          updateFields.lastUpdated = packetTimestamp;
          updateFields.status = 'online';
        }

        const incomingCrop = payloadData?.crop_name || payloadData?.['Crop Name'] || payloadData?.cropName;
        const incomingSetup = payloadData?.setup_name || payloadData?.['Setup Name'] || payloadData?.['Setup Details'] || payloadData?.setupName;
        if (incomingCrop) updateFields.cropName = incomingCrop;
        if (incomingSetup) updateFields.setupName = incomingSetup;

        if (payloadData?.crop_programs && typeof payloadData.crop_programs === 'object') {
          updateFields['cropPrograms'] = payloadData.crop_programs;
        }

        if (payloadData?.sensor_setpoints && typeof payloadData.sensor_setpoints === 'object') {
          updateFields['settings'] = payloadData.sensor_setpoints;
        } else if (payloadData?.port && payloadData?.settings) {
          updateFields[`settings.${payloadData.port}`] = payloadData.settings;
        }

        if (payloadData?.system_config && typeof payloadData.system_config === 'object') {
          updateFields['config'] = payloadData.system_config;
        } else if (
          payloadData?.upload_frequency_min !== undefined ||
          payloadData?.upload_hours !== undefined ||
          payloadData?.temp_alarm_offset !== undefined ||
          payloadData?.sensor_names !== undefined
        ) {
          const cfgUpdate = {};
          if (payloadData.upload_hours !== undefined) cfgUpdate.upload_hours = payloadData.upload_hours;
          if (payloadData.upload_mins !== undefined) cfgUpdate.upload_mins = payloadData.upload_mins;
          if (payloadData.upload_secs !== undefined) cfgUpdate.upload_secs = payloadData.upload_secs;
          if (payloadData.upload_frequency_min !== undefined) cfgUpdate.upload_frequency_min = payloadData.upload_frequency_min;
          if (payloadData.upload_frequency_sec !== undefined) cfgUpdate.upload_frequency_sec = payloadData.upload_frequency_sec;
          if (payloadData.temp_alarm_offset !== undefined) cfgUpdate.temp_alarm_offset = payloadData.temp_alarm_offset;
          if (payloadData.humi_alarm_offset !== undefined) cfgUpdate.humi_alarm_offset = payloadData.humi_alarm_offset;
          if (payloadData.sensor_names !== undefined) cfgUpdate.sensor_names = payloadData.sensor_names;
          updateFields['config'] = cfgUpdate;
        }

        // Buffer device state updates into bulkWrite queue (eliminates individual DB queries)
        if (Object.keys(updateFields).length > 0) {
          queueDeviceStateUpdate(deviceId, updateFields);
        }
      }

      // Broadcast in-memory telemetry event IMMEDIATELY for zero-latency WebSocket and SSE streaming
      telemetryEmitter.emit('telemetry', {
        deviceId: deviceId ? String(deviceId) : null,
        mqttId,
        topic,
        data: payloadData,
        isRetain,
        timestamp: packetTimestamp || now
      });

      // Filter out commands and setpoint configuration packets from time-series storage
      const isTelemetryStream = (topic.includes('/telemetry') || (!topic.includes('/state') && !topic.includes('/setpoints') && !topic.includes('/config'))) && !isRetain;

      if (isOutboundTopic || topic.includes('/heartbeat') || topic.endsWith('/command/status') || !hasTelemetryData || !isTelemetryStream) {
        return;
      }

      // ── High-Throughput Bulk Write Queue ──
      const saveTimestamp = packetTimestamp || new Date();

      const sanitizeTelemetryItem = (item) => {
        if (!item || typeof item !== 'object') return item;
        if (item.sensor_data) {
          return {
            sensor_data: item.sensor_data,
            dli_data: item.dli_data || {},
            relay_states: item.relay_states || {},
            common_pump_active: item.common_pump_active ?? false,
            active_water_zone: item.active_water_zone || null,
            room_paused_states: item.room_paused_states || {},
            active_warnings: item.active_warnings || []
          };
        }
        return item;
      };

      if (Array.isArray(payloadData)) {
        payloadData.forEach(item => {
          const itemTime = (item && item.timestamp && !isNaN(new Date(item.timestamp).getTime()))
            ? new Date(item.timestamp)
            : saveTimestamp;
          queueTelemetryDoc(mqttId, {
            deviceId: deviceId || null,
            mqttId,
            topic,
            data: sanitizeTelemetryItem(item),
            timestamp: itemTime
          });
        });
      } else {
        queueTelemetryDoc(mqttId, {
          deviceId: deviceId || null,
          mqttId,
          topic,
          data: sanitizeTelemetryItem(payloadData),
          timestamp: saveTimestamp
        });
      }
    } catch (err) {
      console.error(`[MQTT Subscriber] Error processing incoming MQTT packet on "${topic}":`, err.message);
    }
  });

  client.on('error', (err) => {
    console.error('❌ [MQTT Subscriber] Connection error:', err.message);
  });

  client.on('close', () => {
    console.log('[MQTT Subscriber] Connection closed.');
  });

  return client;
};

// ── Background Flush Intervals ────────────────────────────────────────────────
// 1. Flush telemetry document queues every 1000ms
const telemetryFlushTimer = setInterval(flushAllQueues, 1000);

// 2. Flush device state bulkWrite buffer every 1000ms
const deviceStateFlushTimer = setInterval(flushDeviceStateUpdates, 1000);

// Graceful process exit cleanup
const gracefulShutdown = async () => {
  clearInterval(telemetryFlushTimer);
  clearInterval(deviceStateFlushTimer);
  await flushAllQueues();
  await flushDeviceStateUpdates();
};
process.on('SIGINT', gracefulShutdown);
process.on('SIGTERM', gracefulShutdown);

// ── High-Efficiency Bulk Offline Watchdog (Every 15s) ─────────────────────────
setInterval(async () => {
  try {
    const threshold = new Date(Date.now() - 45000);
    const staleDevices = await Device.find({
      status: 'online',
      $or: [
        { lastUpdated: { $lt: threshold } },
        { lastUpdated: null }
      ]
    }).select('_id mqttId');

    if (staleDevices.length === 0) return;

    const staleIds = staleDevices.map(d => d._id);
    // 1 single bulk update for all stale devices instead of loop of dev.save()
    await Device.updateMany({ _id: { $in: staleIds } }, { $set: { status: 'offline' } });

    staleDevices.forEach(dev => {
      const idStr = String(dev._id);
      deviceStatusCache.set(idStr, 'offline');
      telemetryEmitter.emit('telemetry', {
        deviceId: idStr,
        mqttId: dev.mqttId,
        topic: `inhydro/${dev.mqttId}/status`,
        data: { status: 'offline', timestamp: new Date() },
        isRetain: false,
        timestamp: new Date()
      });
    });
  } catch (err) {
    // Ignore transient DB query errors
  }
}, 15000);

module.exports = {
  startMqttSubscriber,
  telemetryEmitter,
  flushAllQueues,
  flushDeviceStateUpdates,
  updateDeviceCacheStatus,
  preloadDeviceCache
};
