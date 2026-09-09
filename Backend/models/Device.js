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
      enum: ['system2', 'controlling', 'almora', 'almora2', 'multi_sensor', 'light_motor_pump', 'office_control', 'monit', 'monnet'],
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
    lastUpdated: {
      type: Date,
      default: Date.now,
    },
  },
  {
    timestamps: true,
  }
);

module.exports = mongoose.model('Device', deviceSchema);

