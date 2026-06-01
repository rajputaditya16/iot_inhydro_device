/**
 * MQTT Publisher Utility
 * Connects to HiveMQ public broker (same broker the Pi uses)
 * and publishes messages to specific device topics.
 */
const mqtt = require('mqtt');

const CONTROL_BROKER = 'mqtt://broker.hivemq.com:1883';

/**
 * Publish a message to a topic on HiveMQ and disconnect.
 * @param {string} topic - MQTT topic to publish to
 * @param {object|string} payload - Message payload (will be JSON.stringified if object)
 * @returns {Promise<void>}
 */
const publishToDevice = (topic, payload) => {
  return new Promise((resolve, reject) => {
    const client = mqtt.connect(CONTROL_BROKER, {
      clientId: `backend_publisher_${Date.now()}`,
      connectTimeout: 10000,
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
