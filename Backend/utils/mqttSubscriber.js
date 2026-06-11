const mqtt = require('mqtt');
const mongoose = require('mongoose');
const Device = require('../models/Device');
const MqttPacket = require('../models/MqttPacket');

const BROKER_URL = 'mqtt://broker.hivemq.com:1883';
const deviceCache = new Map(); // Caches mqttId -> deviceId to prevent redundant DB queries

/**
 * Resolves the device ID for a given MQTT ID, using memory cache or DB query.
 * @param {string} mqttId - The MQTT client ID from the topic
 * @returns {Promise<mongoose.Types.ObjectId|null>}
 */
const resolveDeviceId = async (mqttId) => {
  if (deviceCache.has(mqttId)) {
    return deviceCache.get(mqttId);
  }

  // Look up device in database
  const device = await Device.findOne({
    $or: [
      { mqttId: mqttId },
      { _id: mongoose.Types.ObjectId.isValid(mqttId) ? mqttId : null }
    ]
  });

  if (device) {
    deviceCache.set(mqttId, device._id);
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
    clientId: `backend_subscriber_daemon_${Date.now()}`,
    clean: true,
    reconnectPeriod: 5000, // Reconnect every 5 seconds if connection is lost
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

      // Resolve device from DB/cache
      const deviceId = await resolveDeviceId(mqttId);
      if (!deviceId) {
        // Device not registered in our dashboard, skip saving
        return;
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

      // Store in MongoDB
      const packet = await MqttPacket.create({
        deviceId,
        mqttId,
        topic,
        data: payloadData,
        timestamp: new Date()
      });

      console.log(`[MQTT Subscriber] Saved live telemetry for "${mqttId}" on topic "${topic}" (ID: ${packet._id})`);
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
