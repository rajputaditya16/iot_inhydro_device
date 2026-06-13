const mongoose = require('mongoose');
require('dotenv').config();
const Device = require('./models/Device');
const Admin = require('./models/Admin');

async function run() {
  try {
    await mongoose.connect(process.env.MONGO_URI);
    console.log('Database connected.');
    
    const devices = await Device.find({});
    console.log(`Found ${devices.length} devices:`);
    devices.forEach(d => {
      console.log(`- ID: ${d._id}, Name: ${d.name}, Type: ${d.deviceType}, MQTT ID: ${d.mqttId}, ThingSpeak Channel ID: ${d.thingspeak?.channelId}`);
    });

    // Let's also check if testadmin has any assigned devices, and assign them all
    const admin = await Admin.findOne({ email: 'testadmin@inhydro.in' });
    if (admin) {
      admin.assignedDevices = devices.map(d => d._id);
      admin.role = 'superadmin'; // Try to set it to superadmin in the DB via this script
      await admin.save();
      console.log(`Assigned all ${devices.length} devices to testadmin@inhydro.in and upgraded to superadmin`);
    }

    await mongoose.disconnect();
  } catch (error) {
    console.error('Error listing devices:', error);
    process.exit(1);
  }
}

run();
