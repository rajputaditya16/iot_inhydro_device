const mongoose = require('mongoose');

const notificationLogSchema = new mongoose.Schema(
  {
    deviceId: {
      type: mongoose.Schema.Types.ObjectId,
      ref: 'Device',
      required: true,
    },
    mqttId: {
      type: String,
      default: '',
    },
    alertType: {
      type: String,
      enum: [
        'critical_ph',
        'critical_ec',
        'critical_temp',
        'critical_humidity',
        'status_online',
        'status_offline',
        'setpoint_change',
      ],
      required: true,
    },
    room: {
      type: String,
      default: '',
    },
    message: {
      type: String,
      required: true,
    },
    sentTo: {
      type: [String],
      default: [],
    },
    values: {
      type: mongoose.Schema.Types.Mixed,
      default: {},
    },
  },
  {
    timestamps: true,
  }
);

// Auto-expire old logs after 90 days to prevent unbounded growth
notificationLogSchema.index({ createdAt: 1 }, { expireAfterSeconds: 90 * 24 * 60 * 60 });

// Index for fast lookups by device + alert type (used by cooldown checks)
notificationLogSchema.index({ deviceId: 1, alertType: 1, createdAt: -1 });

module.exports = mongoose.model('NotificationLog', notificationLogSchema);
