const mongoose = require('mongoose');

const mqttPacketSchema = new mongoose.Schema(
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
mqttPacketSchema.index({ deviceId: 1, timestamp: -1 });

module.exports = mongoose.model('MqttPacket', mqttPacketSchema);


