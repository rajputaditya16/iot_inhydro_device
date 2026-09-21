const express = require('express');
const { validateClientApiKey } = require('./clientApiAuth');
const {
  getDevices,
  getMetadata,
  getAllDevicesDataset,
  getSingleDeviceDataset,
} = require('./clientApiController');

const router = express.Router();

// Apply API Key security to all client endpoints
router.use(validateClientApiKey);

// Discovery & Device list
router.get('/devices', getDevices);
router.get('/dataset/metadata', getMetadata);

// Bulk AI Training Dataset (All or Selected Devices)
router.get('/dataset/all-devices', getAllDevicesDataset);
router.get('/dataset', getAllDevicesDataset); // Alias
router.get('/data', getAllDevicesDataset);    // Alias

// Single Device AI Training Dataset
router.get('/dataset/device/:idOrMqttId', getSingleDeviceDataset);
router.get('/device/:idOrMqttId', getSingleDeviceDataset); // Alias

module.exports = router;
