const mongoose = require('mongoose');

const telemetryLogSchema = new mongoose.Schema(
  {
    deviceId: {
      type: mongoose.Schema.Types.ObjectId,
      ref: 'Device',
      required: true,
      index: true,
    },
    mqttId: {
      type: String,
      required: true,
      index: true,
    },
    topic: {
      type: String,
      required: true,
    },
    timestamp: {
      type: Date,
      default: Date.now,
      index: true,
    },
    data: {
      type: mongoose.Schema.Types.Mixed,
      required: true,
    },
  },
  {
    timestamps: true,
  }
);

// Compound index for efficient historical queries of real-time telemetry by device and time
telemetryLogSchema.index({ deviceId: 1, timestamp: -1 });

const TelemetryLog = mongoose.model('TelemetryLog', telemetryLogSchema);

/**
 * Resolves or creates a dynamic Mongoose model for a specific device's telemetry logs.
 * Each device's data is stored in its own collection (e.g. `telemetry_logs_<mqttId>`).
 * @param {string} mqttId - The MQTT ID of the device
 * @returns {mongoose.Model}
 */
const getTelemetryModel = (mqttId) => {
  if (!mqttId) {
    throw new Error('mqttId is required to resolve dynamic telemetry model');
  }
  // Sanitize the collection name to make it safe and lowercase
  const collectionName = `telemetry_logs_${mqttId.toLowerCase().replace(/[^a-z0-9_]/g, '_')}`;

  if (mongoose.models[collectionName]) {
    return mongoose.models[collectionName];
  }

  return mongoose.model(collectionName, telemetryLogSchema, collectionName);
};

module.exports = TelemetryLog;
module.exports.getTelemetryModel = getTelemetryModel;
module.exports.telemetryLogSchema = telemetryLogSchema;
