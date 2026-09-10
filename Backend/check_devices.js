const mongoose = require('mongoose');
require('dotenv').config();
const Device = require('./models/Device');

async function check() {
  await mongoose.connect(process.env.MONGO_URI);
  const devices = await Device.find({});
  devices.forEach(d => {
    console.log(`[${d.deviceType}] ${d.name} (mqttId: ${d.mqttId}) -> Status: ${d.status}, LastUpdated: ${d.lastUpdated}`);
  });
  await mongoose.disconnect();
}
check();
