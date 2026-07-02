const mqtt = require('mqtt');
const mongoose = require('mongoose');
const Device = require('../models/Device');
const { getTelemetryModel } = require('../models/TelemetryLog');

const BROKER_URL = process.env.MQTT_BROKER_URL || 'mqtt://147.93.106.142:1883';
const MQTT_USER = process.env.MQTT_USERNAME || 'Inhydro@5598';
const MQTT_PASS = process.env.MQTT_PASSWORD || 'MGPL@5598';
const deviceCache = new Map(); // Caches mqttId -> deviceId to prevent redundant DB queries

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
    typeCriteria = { deviceType: { $in: ['office_control', 'system2'] } };
  } else {
    // default/multi_sensor
    typeCriteria = { deviceType: { $nin: ['controlling', 'office_control', 'system2'] } };
  }

  // Look up device in database using both MQTT ID and topic device type criteria
  let device = await Device.findOne({
    $and: [
      {
        $or: [
          { mqttId: mqttId },
          { _id: mongoose.Types.ObjectId.isValid(mqttId) ? mqttId : null }
        ]
      },
      typeCriteria
    ]
  });

  // Fallback to match by ID/mqttId only if no matching type found
  if (!device) {
    device = await Device.findOne({
      $or: [
        { mqttId: mqttId },
        { _id: mongoose.Types.ObjectId.isValid(mqttId) ? mqttId : null }
      ]
    });
  }

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
  console.log(`[MQTT Subscriber] Connecting to HiveMQ broker: ${BROKER_URL}`);

  const client = mqtt.connect(BROKER_URL, {
    username: MQTT_USER,
    password: MQTT_PASS,
    clientId: `backend_subscriber_daemon_${Date.now()}`,
    clean: true,
    reconnectPeriod: 5000, // Reconnect every 5 seconds if connection is lost
    rejectUnauthorized: false, // Bypass self-signed certificate validation on raw IP
  });

  client.on('connect', () => {
    console.log('✅ [MQTT Subscriber] Connected to HiveMQ broker.');

    // Subscribe to multi-sensor telemetry: inhydro/{mqttId}/telemetry/live
    client.subscribe('inhydro/+/telemetry/live', (err) => {
      if (err) console.error('[MQTT Subscriber] Failed to subscribe to multi_sensor topic:', err);
      else console.log('[MQTT Subscriber] Subscribed to inhydro/+/telemetry/live');
    });

    // Subscribe to office control telemetry: inhydro/{mqttId}/room{1,2}/telemetry/live
    client.subscribe('inhydro/+/+/telemetry/live', (err) => {
      if (err) console.error('[MQTT Subscriber] Failed to subscribe to office_control topic:', err);
      else console.log('[MQTT Subscriber] Subscribed to inhydro/+/+/telemetry/live');
    });
  });

  client.on('message', async (topic, message) => {
    try {
      const topicParts = topic.split('/');
      // Topic structure is either:
      // - inhydro/{mqttId}/telemetry/live
      // - inhydro/{mqttId}/{room}/telemetry/live
      const mqttId = topicParts[1];

      if (!mqttId) {
        return;
      }

      // Resolve device from DB/cache using mqttId and the topic
      const deviceId = await resolveDeviceId(mqttId, topic);
      if (!deviceId) {
        // Device not registered in our dashboard, skip saving
        return;
      }

      // Update status to online and lastUpdated to now
      try {
        await Device.findByIdAndUpdate(deviceId, {
          status: 'online',
          lastUpdated: new Date()
        });
      } catch (err) {
        console.error(`[MQTT Subscriber] Failed to update device online status: ${err.message}`);
      }

      // Parse payload
      const payloadString = message.toString();
      let payloadData;
      try {
        payloadData = JSON.parse(payloadString);
      } catch (e) {
        // Fallback for non-JSON payloads
        payloadData = { raw: payloadString };
      }

      // Get the correct dynamic model for this device's collection
      const TelemetryModel = getTelemetryModel(mqttId);

      if (Array.isArray(payloadData)) {
        // Bulk insertion for synced offline array
        const documents = payloadData.map(item => {
          let packetTimestamp = new Date();
          if (item && item.timestamp) {
            const parsedDate = new Date(item.timestamp);
            if (!isNaN(parsedDate.getTime())) {
              packetTimestamp = parsedDate;
            }
          }
          return {
            deviceId,
            mqttId,
            topic,
            data: item,
            timestamp: packetTimestamp
          };
        });

        await TelemetryModel.insertMany(documents);
        console.log(`[MQTT Subscriber] Saved ${documents.length} bulk telemetry packets for "${mqttId}" on topic "${topic}" in collection ${TelemetryModel.collection.name}`);
      } else {
        // Single packet insertion
        let packetTimestamp = new Date();
        if (payloadData && payloadData.timestamp) {
          const parsedDate = new Date(payloadData.timestamp);
          if (!isNaN(parsedDate.getTime())) {
            packetTimestamp = parsedDate;
          }
        }

        await TelemetryModel.create({
          deviceId,
          mqttId,
          topic,
          data: payloadData,
          timestamp: packetTimestamp
        });
        console.log(`[MQTT Subscriber] Saved live telemetry for "${mqttId}" on topic "${topic}" in collection ${TelemetryModel.collection.name}`);
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

  // Export disconnect functionality to allow clean shutdowns if needed
  return client;
};

module.exports = { startMqttSubscriber };
