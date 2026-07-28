import mqtt from 'mqtt';

const DEFAULT_BROKER_URL = 'ws://147.93.106.142:8083/mqtt';

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
      this.listeners[event].forEach(fn => fn(...args));
    }
  }
  subscribe() { return this; }
  unsubscribe() { return this; }
  publish(topic, message, options, cb) {
    const callback = typeof options === 'function' ? options : cb;
    if (typeof callback === 'function') callback(new Error('Using Backend API for HTTPS setpoint push'));
    return this;
  }
  end() { return this; }
  reconnect() { return this; }
}

const isSecureContext = typeof window !== 'undefined' && window.location.protocol === 'https:';

export const MQTT_CONFIG = {
  brokerUrl: import.meta.env.VITE_MQTT_BROKER_URL || DEFAULT_BROKER_URL,
  username: import.meta.env.VITE_MQTT_USERNAME || 'Inhydro@5598',
  password: import.meta.env.VITE_MQTT_PASSWORD || 'MGPL@5598',
};

/**
 * Creates and returns an MQTT client connected to the configured broker with credentials from .env
 * On HTTPS pages where raw IP WSS is blocked, returns MockMqttClient to eliminate console errors.
 * @param {Object} overrideOptions Optional MQTT options to merge or override
 * @returns {mqtt.MqttClient|MockMqttClient}
 */
export const createMqttClient = (overrideOptions = {}) => {
  let brokerUrl = overrideOptions.brokerUrl || MQTT_CONFIG.brokerUrl || DEFAULT_BROKER_URL;

  // Normalize wss:// to ws:// for raw IP (since 147.93.106.142:8083 is plain WS)
  if (brokerUrl.includes('147.93.106.142') && brokerUrl.startsWith('wss://')) {
    brokerUrl = brokerUrl.replace(/^wss:\/\//, 'ws://');
  }

  // If running over HTTPS (where browser blocks insecure ws://), return MockMqttClient
  if (isSecureContext && brokerUrl.startsWith('ws://')) {
    return new MockMqttClient();
  }

  try {
    return mqtt.connect(brokerUrl, {
      username: MQTT_CONFIG.username,
      password: MQTT_CONFIG.password,
      keepalive: 60,
      reconnectPeriod: 5000,
      ...overrideOptions,
    });
  } catch (err) {
    return new MockMqttClient();
  }
};

export default createMqttClient;
