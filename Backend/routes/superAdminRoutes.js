const express = require('express');
const {
  getAdmins,
  createAdmin,
  updateAdmin,
  deleteAdmin,
  getSystemStats,
  assignToAdmin,
  toggleAdminStatus,
} = require('../controllers/superAdminController');
const { protect, restrictTo } = require('../middleware/auth');

const router = express.Router();

// Require auth and superadmin role for ALL routes below
router.use(protect);
router.use(restrictTo('superadmin'));

router.route('/admins')
  .get(getAdmins)
  .post(createAdmin);

router.route('/admins/:id')
  .put(updateAdmin)
  .delete(deleteAdmin);

router.route('/admins/:id/assign')
  .put(assignToAdmin);

router.route('/admins/:id/toggle-status')
  .put(toggleAdminStatus);

router.route('/stats')
  .get(getSystemStats);

module.exports = router;
