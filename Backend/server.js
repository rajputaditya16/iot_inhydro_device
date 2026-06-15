const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');
const User = require('./models/User');
const Admin = require('./models/Admin');
// const { syncAllDevices } = require('./scripts/syncThingspeak');
const { startMqttSubscriber } = require('./utils/mqttSubscriber');
require('dotenv').config();

// ── Route imports ────────────────────────────
const authRoutes = require('./routes/authRoutes');
const deviceRoutes = require('./routes/deviceRoutes');
const userRoutes = require('./routes/userRoutes');
const superAdminRoutes = require('./routes/superAdminRoutes');
const app = express();

const ADMIN_NAME = process.env.ADMIN_NAME || 'Rajesh Kumar';
const ADMIN_EMAIL = (process.env.ADMIN_EMAIL || 'anujprajapa3@gmail.com').toLowerCase();
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'Admin@1221';

const ensureDefaultAdmin = async () => {
  const existingAdmin = await Admin.findOne().select('_id email');

  if (existingAdmin) {
    console.log(`Admin already created: ${existingAdmin.email}`);
    return;
  }

  // Migrate legacy admin user into dedicated admins collection.
  const legacyAdminUser = await User.findOne({
    $or: [{ role: 'admin' }, { email: ADMIN_EMAIL }],
  }).select('+password');

  if (legacyAdminUser) {
    await Admin.create({
      name: legacyAdminUser.name,
      email: legacyAdminUser.email,
      password: ADMIN_PASSWORD,
      role: 'admin',
      isActive: legacyAdminUser.isActive,
    });
    legacyAdminUser.role = 'viewer';
    await legacyAdminUser.save({ validateBeforeSave: false });
    console.log(`Legacy admin migrated to Admin schema: ${legacyAdminUser.email}`);
    return;
  }

  await Admin.create({
    name: ADMIN_NAME,
    email: ADMIN_EMAIL,
    password: ADMIN_PASSWORD,
    role: 'admin',
    isActive: true,
  });

  console.log(`Default admin created: ${ADMIN_EMAIL}`);
};


const ensureDefaultSuperAdmin = async () => {
  // Ensure default superadmin
  const existingSuperAdmin = await Admin.findOne({ role: 'superadmin' });
  if (!existingSuperAdmin) {
    await Admin.create({
      name: 'Super Admin',
      email:'binit@inhydro.in',
      password: 'superadmin102340',
      role: 'superadmin',
      isActive: true, 
    });
    console.log(`Default superadmin created: binit@inhydro.in`);
  }
};

// ── Middleware ───────────────────────────────────────────────────────────────
app.use(
  cors({
    origin: (origin, callback) => {
      // Allow requests with no origin (mobile apps, curl, Postman, server-to-server)
      if (!origin) return callback(null, true);
      // Allow any localhost port during development
      if (/^http:\/\/localhost:\d+$/.test(origin)) return callback(null, true);
      // Allow the deployed frontend origin set via env var
      const allowed = process.env.ALLOWED_ORIGIN;
      if (allowed && origin === allowed) return callback(null, true);
      // If no ALLOWED_ORIGIN is set, allow all origins (permissive mode for deployment)
      if (!allowed) return callback(null, true);
      callback(new Error(`CORS: origin ${origin} not allowed`));
    },
    credentials: true,
  })
);
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ── Routes ───────────────────────────────────────────────────────────────────
app.get('/', (req, res) => res.json({ message: 'IOT Project API is running 🚀' }));

app.use('/api/auth', authRoutes);
app.use('/api/devices', deviceRoutes);
app.use('/api/users', userRoutes);
app.use('/api/superadmin', superAdminRoutes);

// Catch-all for API routes to clearly return a 404 JSON instead of falling through to the frontend handler
app.use('/api', (req, res) => {
  res.status(404).json({ success: false, message: `API Route ${req.method} ${req.originalUrl} not found` });
});

// ── 404 and Frontend handler ───────────────────────────────────────────────
const path = require('path');

// Serve static React build files in production
if (process.env.NODE_ENV === 'production') {
  app.use(express.static(path.join(__dirname, '../Frontend/dist')));
  
  // Hand over routing to React Router
  app.get(/(.*)/, (req, res) => {
    res.sendFile(path.resolve(__dirname, '../Frontend', 'dist', 'index.html'));
  });
} else {
  app.use((req, res) => {
    res.status(404).json({ success: false, message: `Route ${req.originalUrl} not found` });
  });
}

// ── Global error handler ─────────────────────────────────────────────────────
app.use((err, req, res, next) => {
  console.error('[Unhandled Error]', err);
  res.status(err.statusCode || 500).json({
    success: false,
    message: err.message || 'Internal Server Error',
  });
});

// ── Connect to MongoDB & start server ────────────────────────────────────────
const PORT = process.env.PORT || 5000;
const MONGO_URI = process.env.MONGO_URI || 'mongodb://localhost:27017/iot_project';

const connectWithRetry = (uri, attempt = 1) => {
  console.log(`Connecting to MongoDB (Attempt ${attempt})...`);
  mongoose
    .connect(uri)
    .then(async () => {
      console.log(`✅  MongoDB connected successfully to: ${uri}`);

      await ensureDefaultAdmin();
      await ensureDefaultSuperAdmin();

      app.listen(PORT, () => {
        console.log(`🚀  Server running on http://localhost:${PORT}`);
        // Start the MQTT Subscriber daemon to store real-time telemetry
        startMqttSubscriber();
      });
    })
    .catch(async (err) => {
      console.error(`❌  MongoDB connection error (Attempt ${attempt}):`, err.message);
      if (attempt < 3) {
        console.log('Retrying connection in 5 seconds...');
        setTimeout(() => connectWithRetry(uri, attempt + 1), 5000);
      } else if (uri !== 'mongodb://localhost:27017/iot_project') {
        console.log('⚠️  Atlas connection failed. Falling back to local MongoDB: mongodb://localhost:27017/iot_project');
        connectWithRetry('mongodb://localhost:27017/iot_project', 1);
      } else {
        console.error('💥  Could not connect to any MongoDB instance. Exiting...');
        process.exit(1);
      }
    });
};

connectWithRetry(MONGO_URI);
