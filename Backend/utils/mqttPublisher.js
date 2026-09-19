/**
 * MQTT Publisher Utility
 * Connects to Mosquitto VPS broker (same broker the Pi uses)
 * and publishes messages to specific device topics.
 */
const mqtt = require('mqtt');

const CONTROL_BROKER = process.env.MQTT_BROKER_URL || 'mqtt://147.93.106.142:1883';

// Maintain a persistent client pool to avoid 2-3s TCP/handshake lag on every publish
let publisherClient = null;

const getPublisherClient = () => {
  if (publisherClient && publisherClient.connected) {
    return publisherClient;
  }
  if (!publisherClient) {
    const options = {
      clientId: `backend_publisher_pool_${process.pid}_${Date.now().toString(36)}`,
      username: process.env.MQTT_USERNAME || 'Inhydro@5598',
      password: process.env.MQTT_PASSWORD || 'MGPL@5598',
      connectTimeout: 5000,
      reconnectPeriod: 3000,
      rejectUnauthorized: false,
    };
    publisherClient = mqtt.connect(CONTROL_BROKER, options);
    publisherClient.on('connect', () => {
      console.log('✅ [MQTT Publisher Pool] Connected to Mosquitto VPS broker');
    });
    publisherClient.on('error', (err) => {
      console.error('[MQTT Publisher Pool] Connection error:', err.message);
    });
  }
  return publisherClient;
};

// Initialize publisher client eagerly on module load
try {
  getPublisherClient();
} catch (e) { }

/**
 * Publish a message to a topic on Mosquitto VPS.
 * @param {string} topic - MQTT topic to publish to
 * @param {object|string} payload - Message payload (will be JSON.stringified if object)
 * @param {object} [opts] - Options { retain: false }
 * @returns {Promise<void>}
 */
const publishToDevice = (topic, payload, opts = {}) => {
  return new Promise((resolve, reject) => {
    const isCommand = topic.endsWith('/command') || (typeof payload === 'object' && (payload?.action || payload?.command));
    // CRITICAL: Remote hardware/script commands must NEVER be retained on broker!
    const retain = isCommand ? false : (opts.retain !== undefined ? Boolean(opts.retain) : false);

    const message = typeof payload === 'string' ? payload : JSON.stringify(payload);
    const client = getPublisherClient();

    const executePublish = () => {
      client.publish(topic, message, { retain }, (err) => {
        if (err) {
          console.error(`MQTT publish error on ${topic}:`, err);
          reject(err);
        } else {
          console.log(`✅ Published to ${topic} (retain: ${retain})`);
          resolve();
        }
      });
    };

    if (client.connected) {
      executePublish();
    } else {
      let timeoutId = null;
      const onConnect = () => {
        clearTimeout(timeoutId);
        executePublish();
      };
      timeoutId = setTimeout(() => {
        client.removeListener('connect', onConnect);
        reject(new Error(`MQTT publish timeout on ${topic}`));
      }, 5000);
      client.once('connect', onConnect);
    }
  });
};

module.exports = { publishToDevice };
