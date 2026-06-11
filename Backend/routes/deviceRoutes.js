const express = require('express');
const { getDevices, createDevice, updateDevice, deleteDevice, toggleBlockDevice, pushThingspeakConfig, getDeviceAnalytics } = require('../controllers/deviceController');
const { protect, restrictTo } = require('../middleware/auth');

const router = express.Router();

router.use(protect);

router
  .route('/')
  .get(getDevices)
  .post(restrictTo('admin', 'superadmin'), createDevice);

router
  .route('/:id')
  .put(restrictTo('admin', 'superadmin'), updateDevice)
  .delete(restrictTo('admin', 'superadmin'), deleteDevice);

router.put('/:id/block', restrictTo('admin', 'superadmin'), toggleBlockDevice);
router.put('/:id/push-config', restrictTo('admin', 'superadmin'), pushThingspeakConfig);
router.get('/:id/analytics', getDeviceAnalytics);
module.exports = router;
