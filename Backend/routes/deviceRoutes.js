const express = require('express');
const {
  getDevices,
  createDevice,
  updateDevice,
  deleteDevice,
  toggleBlockDevice,
  pushDeviceConfig,
  sendDeviceCommand,
  getDeviceAnalytics,
  streamTelemetry,
  getCropPrograms,
  saveCropProgram,
  deleteCropProgram,
  applyCropProgram,
  getSetpointsJson
} = require('../controllers/deviceController');
const { protect, restrictTo } = require('../middleware/auth');

const router = express.Router();

// Real-time SSE telemetry stream (unprotected or protected)
router.get('/stream', streamTelemetry);

router.use(protect);

router
  .route('/')
  .get(getDevices)
  .post(restrictTo('admin', 'superadmin'), createDevice);

router
  .route('/:id')
  .put(restrictTo('admin', 'superadmin'), updateDevice)
  .delete(restrictTo('admin', 'superadmin'), deleteDevice);

router.put('/:id/block', restrictTo('superadmin'), toggleBlockDevice);
router.route('/:id/push-config')
  .post(restrictTo('admin', 'superadmin'), pushDeviceConfig)
  .put(restrictTo('admin', 'superadmin'), pushDeviceConfig);
router.route('/:id/setpoints')
  .post(restrictTo('admin', 'superadmin'), pushDeviceConfig)
  .put(restrictTo('admin', 'superadmin'), pushDeviceConfig)
  .get(restrictTo('admin', 'superadmin'), pushDeviceConfig);

// Direct Program & Setpoints JSON Endpoints
router.route('/:id/programs')
  .get(getCropPrograms)
  .post(restrictTo('admin', 'superadmin'), saveCropProgram);
router.route('/:id/programs/:programName')
  .delete(restrictTo('admin', 'superadmin'), deleteCropProgram);
router.route('/:id/programs/:programName/apply')
  .post(restrictTo('admin', 'superadmin'), applyCropProgram);
router.route('/:id/setpoints-json')
  .get(getSetpointsJson);

router.post('/:id/command', restrictTo('admin', 'superadmin'), sendDeviceCommand);
router.get('/:id/analytics', getDeviceAnalytics);

module.exports = router;
