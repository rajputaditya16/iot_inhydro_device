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
    battery: {
      type: Number,
      min: 0,
      max: 100,
      default: 100,
    },
    deviceType: {
      type: String,
      enum: ['system2', 'almora', 'almora2', 'multi_sensor', 'light_motor_pump', 'office_control'],
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
    // ── ThingSpeak Configuration ──────────────────────────────────────────
    thingspeak: {
      channelId: {
        type: String,
        trim: true,
        default: '',
      },
      readApiKey: {
        type: String,
        trim: true,
        default: '',
      },
      writeApiKey: {
        type: String,
        trim: true,
        default: '',
      },
      port: {
        type: Number,
        default: 1883,
      },
      username: {
        type: String,
        trim: true,
        default: '',
      },
      password: {
        type: String,
        trim: true,
        default: '',
      },
      clientId: {
        type: String,
        trim: true,
        default: '',
      },
    },
  },
  {
    timestamps: true,
  }
);

module.exports = mongoose.model('Device', deviceSchema);

