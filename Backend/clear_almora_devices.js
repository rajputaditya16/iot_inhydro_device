const mongoose = require('mongoose');
const Device = require('./models/Device');
require('dotenv').config();

const MONGO_URI = process.env.MONGO_URI || 'mongodb://localhost:27017/iot_project';

const deleteAlmoraDevices = async () => {
    try {
        await mongoose.connect(MONGO_URI);
        console.log('Connected to MongoDB');
        
        const result = await Device.deleteMany({ deviceType: 'almora' });
        console.log(`Deleted ${result.deletedCount} Almora devices.`);
        
        process.exit(0);
    } catch (err) {
        console.error('Error deleting devices:', err);
        process.exit(1);
    }
};

deleteAlmoraDevices();
