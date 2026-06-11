const mongoose = require('mongoose');

const sensorPacketSchema = new mongoose.Schema(
  {
    deviceId: {
      type: mongoose.Schema.Types.ObjectId,
      ref: 'Device',
      required: true,
      index: true,
    },
    channelId: {
      type: String,
      required: true,
      index: true,
    },
    entryId: {
      type: Number,
      required: true,
    },
    timestamp: {
      type: Date,
      required: true,
      index: true,
    },
    field1: {
      type: String,
      default: null,
    },
    field2: {
      type: String,
      default: null,
    },
    field3: {
      type: String,
      default: null,
    },
    field4: {
      type: String,
      default: null,
    },
    field5: {
      type: String,
      default: null,
    },
    field6: {
      type: String,
      default: null,
    },
    field7: {
      type: String,
      default: null,
    },
    field8: {
      type: String,
      default: null,
    },
  },
  {
    timestamps: true,
  }
);

// Compound unique index to prevent duplicate entries for the same channel and entry_id
sensorPacketSchema.index({ channelId: 1, entryId: 1 }, { unique: true });
// Compound index for efficient historical queries by device and timestamp
sensorPacketSchema.index({ deviceId: 1, timestamp: -1 });

module.exports = mongoose.model('SensorPacket', sensorPacketSchema);
