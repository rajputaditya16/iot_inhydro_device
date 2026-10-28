const mongoose = require('mongoose');

const deviceSchema = new mongoose.Schema(
  {
    name: {
      type: String,
      required: [true, 'Device name is required'],
      trim: true,
    },
    location: {
      type: String,
      required: [true, 'Device location is required'],
      trim: true,
    },
    status: {
      type: String,
      enum: ['online', 'offline', 'warning', 'critical', 'blocked'],
      default: 'offline',
    },
    deviceType: {
      type: String,
      enum: ['system2', 'controlling', 'almora', 'almora2', 'cold_storage', 'multi_sensor', 'light_motor_pump', 'office_control', 'monit', 'monnet', 'itc_polyhouse', 'fertigation'],
      default: 'system2',
    },
    mqttId: {
      type: String,
      trim: true,
      default: '',
    },
    clientName: {
      type: String,
      trim: true,
      default: '',
    },
    locationCode: {
      type: String,
      trim: true,
      default: '',
    },
    model: {
      type: String,
      trim: true,
      default: '',
    },
    unit: {
      type: String,
      trim: true,
      default: '',
    },
    nicknameByClient: {
      type: String,
      trim: true,
      default: '',
    },
    cropName: {
      type: String,
      trim: true,
      default: '',
    },
    setupName: {
      type: String,
      trim: true,
      default: '',
    },
    settings: {
      type: mongoose.Schema.Types.Mixed,
      default: {},
    },
    cropPrograms: {
      type: mongoose.Schema.Types.Mixed,
      default: {},
    },
    config: {
      type: mongoose.Schema.Types.Mixed,
      default: {},
    },
    lastUpdated: {
      type: Date,
      default: null,
    },
  },
  {
    timestamps: true,
  }
);

// Compound and single field indexes for ultra-fast query execution and sorting
deviceSchema.index({ createdAt: -1 });
deviceSchema.index({ mqttId: 1 });
deviceSchema.index({ status: 1 });
deviceSchema.index({ location: 1 });

module.exports = mongoose.model('Device', deviceSchema);

