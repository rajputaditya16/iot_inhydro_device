import mqtt from 'mqtt';

const DEFAULT_BROKER_URL = import.meta.env.VITE_MQTT_BROKER_URL || '';

class MockMqttClient {
  constructor() {
    this.connected = false;
    this.listeners = {};
  }
  on(event, fn) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(fn);
    return this;
  }
  off(event, fn) {
    if (!this.listeners[event]) return this;
    this.listeners[event] = this.listeners[event].filter(f => f !== fn);
    return this;
  }
  emit(event, ...args) {
    if (this.listeners[event]) {
      this.listeners[event].forEach(fn => {
        try { fn(...args); } catch (e) {}
      });
    }
  }
  subscribe(topic, opts, cb) {
    const callback = typeof opts === 'function' ? opts : cb;
    if (typeof callback === 'function') callback(null);
    return this;
  }
  unsubscribe(topic, opts, cb) {
    const callback = typeof opts === 'function' ? opts : cb;
    if (typeof callback === 'function') callback(null);
    return this;
  }
  publish(topic, message, options, cb) {
    const callback = typeof options === 'function' ? options : cb;
    if (typeof callback === 'function') callback(null);
    return this;
  }
  end(force, opts, cb) {
    const callback = typeof force === 'function' ? force : typeof opts === 'function' ? opts : cb;
    if (typeof callback === 'function') callback();
    return this;
  }
  reconnect() { return this; }
}

const isSecureContext = typeof window !== 'undefined' && window.location.protocol === 'https:';

export const MQTT_CONFIG = {
  brokerUrl: DEFAULT_BROKER_URL,
  username: import.meta.env.VITE_MQTT_USERNAME || 'Inhydro@5598',
  password: import.meta.env.VITE_MQTT_PASSWORD || 'MGPL@5598',
  enableDirect: import.meta.env.VITE_ENABLE_DIRECT_MQTT === 'true',
};

/**
 * Creates and returns an MQTT client connected to the configured broker.
 * If direct broker WebSocket is disabled or running on HTTPS without secure WSS,
 * returns MockMqttClient to eliminate console errors while letting Server-Sent Events (SSE)
 * stream live telemetry seamlessly from the backend.
 * @param {Object} overrideOptions Optional MQTT options to merge or override
 * @returns {mqtt.MqttClient|MockMqttClient}
 */
export const createMqttClient = (overrideOptions = {}) => {
  const brokerUrl = overrideOptions.brokerUrl || MQTT_CONFIG.brokerUrl;

  // If direct MQTT is not explicitly configured or disabled, fallback to MockClient
  // The frontend automatically receives all telemetry via Backend SSE stream (/api/devices/stream)
  if (!MQTT_CONFIG.enableDirect || !brokerUrl || (isSecureContext && brokerUrl.startsWith('ws://'))) {
    return new MockMqttClient();
  }

  try {
    const client = mqtt.connect(brokerUrl, {
      username: MQTT_CONFIG.username,
      password: MQTT_CONFIG.password,
      keepalive: 60,
      reconnectPeriod: 10000,
      connectTimeout: 5000,
      ...overrideOptions,
    });
    return client;
  } catch (err) {
    console.warn('[MQTT] Direct broker connection skipped, using backend stream fallback:', err.message);
    return new MockMqttClient();
  }
};

export default createMqttClient;
