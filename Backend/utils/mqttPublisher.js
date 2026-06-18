/**
 * MQTT Publisher Utility
 * Connects to HiveMQ public broker (same broker the Pi uses)
 * and publishes messages to specific device topics.
 */
const mqtt = require('mqtt');

const CONTROL_BROKER = process.env.MQTT_BROKER_URL || 'mqtt://147.93.106.142:1883';
const MQTT_USER = process.env.MQTT_USERNAME || 'Inhydro@5598';
const MQTT_PASS = process.env.MQTT_PASSWORD || 'MGPL@5598';

/**
 * Publish a message to a topic on HiveMQ and disconnect.
 * @param {string} topic - MQTT topic to publish to
 * @param {object|string} payload - Message payload (will be JSON.stringified if object)
 * @returns {Promise<void>}
 */
const publishToDevice = (topic, payload) => {
  return new Promise((resolve, reject) => {
    const client = mqtt.connect(CONTROL_BROKER, {
      username: MQTT_USER,
      password: MQTT_PASS,
      clientId: `backend_publisher_${Date.now()}`,
      connectTimeout: 10000,
      rejectUnauthorized: false, // Bypass self-signed certificate validation on raw IP
    });

    const message = typeof payload === 'string' ? payload : JSON.stringify(payload);

    client.on('connect', () => {
      client.publish(topic, message, { retain: true }, (err) => {
        client.end();
        if (err) {
          console.error('MQTT publish error:', err);
          reject(err);
        } else {
          console.log(`✅ Published to ${topic}`);
          resolve();
        }
      });
    });

    client.on('error', (err) => {
      client.end();
      console.error('MQTT connection error:', err);
      reject(err);
    });

    // Timeout after 15 seconds
    setTimeout(() => {
      client.end();
      reject(new Error('MQTT connection timeout'));
    }, 15000);
  });
};
module.exports = { publishToDevice };
