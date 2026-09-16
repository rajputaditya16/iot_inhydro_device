const mqtt = require('mqtt');
const mongoose = require('mongoose');
const Device = require('../models/Device');
const { getTelemetryModel } = require('../models/TelemetryLog');
const EventEmitter = require('events');
const telemetryEmitter = new EventEmitter();
telemetryEmitter.setMaxListeners(100);

const BROKER_URL = process.env.MQTT_BROKER_URL || 'mqtt://147.93.106.142:1883';
const deviceCache = new Map(); // Caches mqttId -> deviceId to prevent redundant DB queries
const deviceStatusCache = new Map(); // Caches deviceId -> { status, lastCheck, lastUpdate }

/**
 * Resolves the device ID for a given MQTT ID, using memory cache or DB query.
 * @param {string} mqttId - The MQTT client ID from the topic
 * @param {string} topic - The MQTT topic to check device type criteria
 * @returns {Promise<mongoose.Types.ObjectId|null>}
 */
const resolveDeviceId = async (mqttId, topic) => {
  const cacheKey = `${mqttId}_${topic}`;
  if (deviceCache.has(cacheKey)) {
    return deviceCache.get(cacheKey);
  }

  // Determine device type criteria based on the topic structure
  let typeCriteria = {};
  if (topic.includes('/monitor/')) {
    typeCriteria = { deviceType: 'controlling' };
  } else if (topic.includes('/room1/') || topic.includes('/room2/') || topic.includes('/room3/')) {
    typeCriteria = { deviceType: { $in: ['office_control', 'system2', 'monit', 'monnet'] } };
  } else {
    // default/multi_sensor
    typeCriteria = { deviceType: { $nin: ['controlling', 'office_control', 'system2'] } };
  }

  // Look up device in database using MQTT ID, device name, or ObjectId
  let device = null;
  try {
    device = await Device.findOne({
      $or: [
        { mqttId: { $regex: new RegExp(`^${mqttId}$`, 'i') } },
        { name: { $regex: new RegExp(`^${mqttId}$`, 'i') } },
        { _id: mongoose.Types.ObjectId.isValid(mqttId) ? mqttId : null }
      ].filter(Boolean)
    });
  } catch (e) { }

  if (device) {
    deviceCache.set(cacheKey, device._id);
    return device._id;
  }

  return null;
};

/**
 * Initializes and starts the MQTT Subscriber listener.
 */
const startMqttSubscriber = () => {
  console.log(`[MQTT Subscriber] Connecting to Mosquitto VPS broker: ${BROKER_URL}`);

  const options = {
    clientId: `backend_subscriber_daemon_${Date.now()}`,
    username: process.env.MQTT_USERNAME || 'Inhydro@5598',
    password: process.env.MQTT_PASSWORD || 'MGPL@5598',
    clean: true,
    reconnectPeriod: 5000, // Reconnect every 5 seconds if connection is lost
    rejectUnauthorized: false, // Bypass self-signed certificate validation on raw IP
  };
  const client = mqtt.connect(BROKER_URL, options);

  client.on('connect', () => {
    console.log('✅ [MQTT Subscriber] Connected to Mosquitto VPS broker.');

    // Subscribe to all private broker telemetry topics under inhydro/#
    client.subscribe('inhydro/#', (err) => {
      if (err) console.error('[MQTT Subscriber] Failed to subscribe to inhydro/# topics:', err);
      else console.log('✅ [MQTT Subscriber] Subscribed to inhydro/# (all private broker device telemetry)');
    });
  });

  client.on('message', async (topic, message, packet) => {
    try {
      const topicParts = topic.split('/');
      // Topic structure is: inhydro/{mqttId}/...
      const mqttId = topicParts[1];

      if (!mqttId) {
        return;
      }

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
      const packetTimestamp = parsedTime || (isRetain ? null : new Date());

      // Stream setpoint updates real-time via SSE to web dashboard
      if (topic.includes('/setpoints/')) {
        const deviceId = await resolveDeviceId(mqttId, topic);
        const now = Date.now();
        const isFresh = !isRetain && packetTimestamp && (now - packetTimestamp.getTime() < 2 * 60 * 1000);

        if (deviceId) {
          const updateFields = {};
          if (isFresh) {
            updateFields.status = 'online';
            updateFields.lastUpdated = packetTimestamp;
          }
          const incomingCrop = payloadData?.crop_name || payloadData?.['Crop Name'] || payloadData?.cropName;
          const incomingSetup = payloadData?.setup_name || payloadData?.['Setup Name'] || payloadData?.['Setup Details'] || payloadData?.setupName;
          if (incomingCrop) updateFields.cropName = incomingCrop;
          if (incomingSetup) updateFields.setupName = incomingSetup;

          if (Object.keys(updateFields).length > 0) {
            Device.findByIdAndUpdate(deviceId, updateFields).catch(() => { });
          }
        }
        telemetryEmitter.emit('telemetry', {
          deviceId: deviceId ? String(deviceId) : null,
          mqttId,
          topic,
          data: payloadData,
          isRetain,
          timestamp: packetTimestamp || new Date()
        });

        // If packet contains sensor_data, queue telemetry document for history
        if (payloadData && payloadData.sensor_data && typeof payloadData.sensor_data === 'object') {
          const normData = {};
          Object.entries(payloadData.sensor_data).forEach(([pKey, pVal]) => {
            if (!pVal || typeof pVal !== 'object') return;
            let sKey = null;
            if (pVal.id !== undefined && pVal.id !== null) sKey = `s${pVal.id}`;
            else if (pKey.toLowerCase().startsWith('s')) sKey = pKey.toLowerCase();
            if (sKey) {
              normData[sKey] = {
                t: pVal.temp ?? pVal.t ?? null,
                h: pVal.humi ?? pVal.h ?? null,
                co2: pVal.co2 ?? null,
                status: pVal.status || 'OK'
              };
            }
          });
          if (Object.keys(normData).length > 0) {
            queueTelemetryDoc(mqttId, {
              deviceId: deviceId || null,
              mqttId,
              topic: `inhydro/${mqttId}/telemetry/live`,
              data: normData,
              timestamp: packetTimestamp || new Date()
            });
          }
        }
        return;
      }

      // Resolve device from DB/cache using mqttId and the topic
      const deviceId = await resolveDeviceId(mqttId, topic);

      // Broadcast in-memory SSE telemetry event IMMEDIATELY for zero-latency streaming with resolved deviceId
      telemetryEmitter.emit('telemetry', {
        deviceId: deviceId ? String(deviceId) : null,
        mqttId,
        topic,
        data: payloadData,
        isRetain,
        timestamp: packetTimestamp || new Date()
      });

      if (deviceId) {
        // Check if device is blocked (cached for 10 seconds to prevent DB saturation)
        const now = Date.now();
        let cachedStatus = deviceStatusCache.get(String(deviceId));
        if (!cachedStatus || now - cachedStatus.lastCheck > 10000) {
          const deviceCheck = await Device.findById(deviceId).select('status');
          cachedStatus = {
            status: deviceCheck ? deviceCheck.status : 'active',
            lastCheck: now,
            lastUpdate: cachedStatus ? cachedStatus.lastUpdate : 0
          };
          deviceStatusCache.set(String(deviceId), cachedStatus);
        }

        if (cachedStatus.status === 'blocked') {
          return; // Device is blocked, ignore telemetry
        }

        // Only mark online if packet is fresh (not a stale retained message)
        const tsForCheck = packetTimestamp ? packetTimestamp.getTime() : 0;
        const isFresh = !isRetain && tsForCheck > 0 && (now - tsForCheck < 2 * 60 * 1000);

        // Throttle DB online status update to at most once per 15 seconds per device
        if (isFresh && (now - cachedStatus.lastUpdate > 15000)) {
          cachedStatus.lastUpdate = now;
          Device.findByIdAndUpdate(deviceId, {
            status: 'online',
            lastUpdated: packetTimestamp
          }).catch(err => {
            console.error(`[MQTT Subscriber] Failed to update device online status: ${err.message}`);
          });
        }
      }

      // ── High-Throughput Bulk Write Queue (P3 Optimization) ──
      const saveTimestamp = packetTimestamp || new Date();

      if (Array.isArray(payloadData)) {
        payloadData.forEach(item => {
          const itemTime = (item && item.timestamp && !isNaN(new Date(item.timestamp).getTime()))
            ? new Date(item.timestamp)
            : saveTimestamp;
          queueTelemetryDoc(mqttId, {
            deviceId: deviceId || null,
            mqttId,
            topic,
            data: item,
            timestamp: itemTime
          });
        });
      } else {
        queueTelemetryDoc(mqttId, {
          deviceId: deviceId || null,
          mqttId,
          topic,
          data: payloadData,
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

// ── In-Memory Write Queue & Batch Flush Engine ────────────────────────────────
const writeBuffer = new Map(); // mqttId -> Array of docs
let flushTimer = null;

const queueTelemetryDoc = (mqttId, doc) => {
  const cleanId = String(mqttId).toLowerCase();
  if (!writeBuffer.has(cleanId)) {
    writeBuffer.set(cleanId, []);
  }
  const queue = writeBuffer.get(cleanId);
  queue.push(doc);

  // If buffer for this device exceeds 100 items, trigger immediate flush
  if (queue.length >= 100) {
    flushDeviceQueue(cleanId);
  }
};

const flushDeviceQueue = async (cleanId) => {
  const docs = writeBuffer.get(cleanId);
  if (!docs || docs.length === 0) return;

  writeBuffer.set(cleanId, []); // Drain the queue immediately

  try {
    const TelemetryModel = getTelemetryModel(cleanId);
    await TelemetryModel.insertMany(docs, { ordered: false });
    // console.log(`[MQTT Buffer Flush] Batch saved ${docs.length} packets for "${cleanId}" in ${TelemetryModel.collection.name}`);
  } catch (err) {
    console.error(`[MQTT Buffer Flush] Error saving batch for "${cleanId}":`, err.message);
  }
};

const flushAllQueues = async () => {
  const keys = Array.from(writeBuffer.keys());
  for (const key of keys) {
    await flushDeviceQueue(key);
  }
};

// Start 2-second background flush loop
if (!flushTimer) {
  flushTimer = setInterval(flushAllQueues, 2000);
}

// Graceful process exit cleanup
process.on('SIGINT', async () => {
  if (flushTimer) clearInterval(flushTimer);
  await flushAllQueues();
});
process.on('SIGTERM', async () => {
  if (flushTimer) clearInterval(flushTimer);
  await flushAllQueues();
});

module.exports = { startMqttSubscriber, telemetryEmitter, flushAllQueues };

