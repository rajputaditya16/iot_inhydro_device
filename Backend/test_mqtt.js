const mqtt = require('./node_modules/mqtt');

console.log('Testing MQTT connection to 147.93.106.142:1883...');

const client = mqtt.connect('mqtt://147.93.106.142:1883', {
  username: 'Inhydro@5598',
  password: 'MGPL@5598',
  connectTimeout: 5000,
});

client.on('connect', () => {
  console.log('✅ Connected successfully to TCP MQTT (147.93.106.142:1883)!');
  client.end();
});

client.on('error', (err) => {
  console.error('❌ Connection error to TCP MQTT:', err.message);
  client.end();
});

console.log('Testing WebSocket MQTT connection to ws://147.93.106.142:8083/mqtt...');

const wsClient = mqtt.connect('ws://147.93.106.142:8083/mqtt', {
  username: 'Inhydro@5598',
  password: 'MGPL@5598',
  connectTimeout: 5000,
});

wsClient.on('connect', () => {
  console.log('✅ Connected successfully to WebSocket MQTT (ws://147.93.106.142:8083/mqtt)!');
  wsClient.end();
});

wsClient.on('error', (err) => {
  console.error('❌ Connection error to WebSocket MQTT:', err.message);
  wsClient.end();
});
