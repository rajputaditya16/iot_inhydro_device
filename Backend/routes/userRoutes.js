const express = require('express');
const { body } = require('express-validator');
const {
  getUsers,
  getUser,
  createUser,
  updateUser,
  deleteUser,
  assignToUser,
  toggleUserStatus,
  getLocations,
} = require('../controllers/userController');
const { protect, restrictTo } = require('../middleware/auth');

const router = express.Router();

// All routes require authentication + admin role
router.use(protect);
router.use(restrictTo('admin', 'superadmin'));

// ── Validation rules ─────────────────────────────────────────────────────────
const createValidation = [
  body('name')
    .trim()
    .notEmpty().withMessage('Name is required')
    .isLength({ max: 50 }).withMessage('Name too long'),
  body('email')
    .trim()
    .notEmpty().withMessage('Email is required')
    .isEmail().withMessage('Invalid email address'),
  body('password')
    .notEmpty().withMessage('Password is required')
    .isLength({ min: 6 }).withMessage('Password must be at least 6 characters'),
  body('role')
    .optional()
    .isIn(['admin', 'operator', 'viewer']).withMessage('Role must be admin, operator, or viewer'),
];

// ── Routes ───────────────────────────────────────────────────────────────────

// GET unique locations (must be before /:id to avoid conflict)
router.get('/locations', getLocations);

// CRUD
router
  .route('/')
  .get(getUsers)
  .post(createValidation, createUser);

router
  .route('/:id')
  .get(getUser)
  .put(updateUser)
  .delete(deleteUser);

// Assign devices/locations
router.put('/:id/assign', assignToUser);

// Toggle active/inactive
router.put('/:id/toggle-status', toggleUserStatus);

module.exports = router;
