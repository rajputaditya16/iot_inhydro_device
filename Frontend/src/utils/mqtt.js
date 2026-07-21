import mqtt from 'mqtt';

export const MQTT_CONFIG = {
  brokerUrl: import.meta.env.VITE_MQTT_BROKER_URL || 'ws://147.93.106.142:8083/mqtt',
  username: import.meta.env.VITE_MQTT_USERNAME || 'Inhydro@5598',
  password: import.meta.env.VITE_MQTT_PASSWORD || 'MGPL@5598',
};

/**
 * Creates and returns an MQTT client connected to the configured broker with credentials from .env
 * @param {Object} overrideOptions Optional MQTT options to merge or override
 * @returns {mqtt.MqttClient}
 */
export const createMqttClient = (overrideOptions = {}) => {
  const { brokerUrl, username, password } = MQTT_CONFIG;
  return mqtt.connect(brokerUrl, {
    username,
    password,
    keepalive: 60,
    reconnectPeriod: 5000,
    ...overrideOptions,
  });
};

export default createMqttClient;
