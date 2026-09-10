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
  } catch (e) {}

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

  client.on('message', async (topic, message) => {
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

      // Stream setpoint updates real-time via SSE to web dashboard
      if (topic.includes('/setpoints/')) {
        telemetryEmitter.emit('telemetry', {
          mqttId,
          topic,
          data: payloadData,
          timestamp: new Date()
        });
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
        timestamp: new Date()
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

        // Throttle DB online status update to at most once per 15 seconds per device
        if (now - cachedStatus.lastUpdate > 15000) {
          cachedStatus.lastUpdate = now;
          Device.findByIdAndUpdate(deviceId, {
            status: 'online',
            lastUpdated: new Date()
          }).catch(err => {
            console.error(`[MQTT Subscriber] Failed to update device online status: ${err.message}`);
          });
        }
      }

      // ── High-Throughput Bulk Write Queue (P3 Optimization) ──
      const packetTimestamp = (payloadData && payloadData.timestamp && !isNaN(new Date(payloadData.timestamp).getTime()))
        ? new Date(payloadData.timestamp)
        : new Date();

      if (Array.isArray(payloadData)) {
        payloadData.forEach(item => {
          const itemTime = (item && item.timestamp && !isNaN(new Date(item.timestamp).getTime()))
            ? new Date(item.timestamp)
            : new Date();
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
          timestamp: packetTimestamp
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

