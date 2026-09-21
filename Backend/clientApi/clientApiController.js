const mongoose = require('mongoose');
const Device = require('../models/Device');
const TelemetryLog = require('../models/TelemetryLog');
const { getTelemetryModel } = require('../models/TelemetryLog');
const { extractFeatures, ALL_FEATURE_COLUMNS } = require('./featureExtractor');

/**
 * Helper to query telemetry documents for a specific device.
 */
const queryDevicePackets = async (device, { start, end, limit, page = 1 }) => {
  const query = {};

  if (start || end) {
    query.timestamp = {};
    if (start) query.timestamp.$gte = new Date(start);
    if (end) query.timestamp.$lte = new Date(end);
  }

  const skip = (page - 1) * limit;
  let packets = [];

  // Candidate MQTT IDs for dynamic collections
  const candidateMqttIds = [
    device.mqttId,
    device.mqttId?.toLowerCase(),
    device._id?.toString(),
    device.name,
    device.name?.toLowerCase(),
    device.deviceType === 'office_control' ? 'system2' : null,
  ].filter(Boolean);

  // 1. Check dynamic collections first
  for (const cid of candidateMqttIds) {
    try {
      const TelemetryModel = getTelemetryModel(cid);
      const count = await TelemetryModel.estimatedDocumentCount();
      if (count > 0) {
        packets = await TelemetryModel.find(query)
          .sort({ timestamp: -1 })
          .skip(skip)
          .limit(limit)
          .lean();
        if (packets && packets.length > 0) {
          packets.reverse(); // Return chronological order
          return packets;
        }
      }
    } catch (err) {
      // collection not found or error
    }
  }

  // 2. Fallback to main TelemetryLog if dynamic collection had no records
  try {
    const fallbackQuery = {
      ...query,
      $or: [
        { deviceId: device._id },
        { mqttId: device.mqttId },
        { mqttId: device.mqttId?.toLowerCase() },
        device.deviceType === 'office_control' ? { mqttId: 'system2' } : null,
      ].filter(Boolean)
    };

    packets = await TelemetryLog.find(fallbackQuery)
      .sort({ timestamp: -1 })
      .skip(skip)
      .limit(limit)
      .lean();

    if (packets && packets.length > 0) {
      packets.reverse();
    }
  } catch (err) {
    console.warn(`[ClientAPI] Telemetry query failed for ${device.name}:`, err.message);
  }

  return packets;
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   GET /api/client/devices
// @desc    Get summary list of all active devices
// @access  Protected (API Key)
// ─────────────────────────────────────────────────────────────────────────────
exports.getDevices = async (req, res) => {
  try {
    const devices = await Device.find({})
      .select('_id name location status deviceType mqttId clientName locationCode model unit cropName setupName lastUpdated createdAt')
      .sort({ createdAt: -1 })
      .lean();

    res.status(200).json({
      success: true,
      count: devices.length,
      data: devices,
    });
  } catch (err) {
    console.error('[ClientAPI Error] getDevices:', err);
    res.status(500).json({ success: false, message: 'Server error retrieving devices' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   GET /api/client/dataset/metadata
// @desc    Get AI Pipeline discovery metadata (records count, features, timestamps)
// @access  Protected (API Key)
// ─────────────────────────────────────────────────────────────────────────────
exports.getMetadata = async (req, res) => {
  try {
    const devices = await Device.find({}).lean();

    const metadataList = await Promise.all(
      devices.map(async (dev) => {
        const mqttId = dev.mqttId || dev._id.toString();
        let totalRecords = 0;
        let earliestRecord = null;
        let latestRecord = null;

        const candidateMqttIds = [
          mqttId,
          dev.mqttId,
          dev.mqttId?.toLowerCase(),
          dev._id?.toString(),
          dev.name,
          dev.name?.toLowerCase(),
          dev.deviceType === 'office_control' ? 'system2' : null,
        ].filter(Boolean);

        for (const cid of candidateMqttIds) {
          try {
            const TelemetryModel = getTelemetryModel(cid);
            const count = await TelemetryModel.estimatedDocumentCount();
            if (count > 0) {
              totalRecords = count;
              const first = await TelemetryModel.findOne().sort({ timestamp: 1 }).select('timestamp').lean();
              const last = await TelemetryModel.findOne().sort({ timestamp: -1 }).select('timestamp').lean();
              earliestRecord = first ? first.timestamp : null;
              latestRecord = last ? last.timestamp : null;
              break;
            }
          } catch (e) {}
        }

        if (totalRecords === 0) {
          try {
            const count = await TelemetryLog.countDocuments({
              $or: [{ deviceId: dev._id }, { mqttId: dev.mqttId }].filter(Boolean),
            });
            if (count > 0) {
              totalRecords = count;
              const first = await TelemetryLog.findOne({ $or: [{ deviceId: dev._id }, { mqttId: dev.mqttId }] })
                .sort({ timestamp: 1 })
                .select('timestamp')
                .lean();
              const last = await TelemetryLog.findOne({ $or: [{ deviceId: dev._id }, { mqttId: dev.mqttId }] })
                .sort({ timestamp: -1 })
                .select('timestamp')
                .lean();
              earliestRecord = first ? first.timestamp : null;
              latestRecord = last ? last.timestamp : null;
            }
          } catch (e) {}
        }

        return {
          deviceId: dev._id,
          deviceName: dev.name,
          deviceMqttId: dev.mqttId,
          deviceType: dev.deviceType,
          location: dev.location,
          cropName: dev.cropName || '',
          setupName: dev.setupName || '',
          totalRecords,
          earliestRecord,
          latestRecord,
        };
      })
    );

    const totalSystemRecords = metadataList.reduce((acc, curr) => acc + curr.totalRecords, 0);

    res.status(200).json({
      success: true,
      totalDevices: devices.length,
      totalSystemRecords,
      allFeatureColumns: ALL_FEATURE_COLUMNS,
      devices: metadataList,
    });
  } catch (err) {
    console.error('[ClientAPI Error] getMetadata:', err);
    res.status(500).json({ success: false, message: 'Server error retrieving metadata' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   GET /api/client/dataset/all-devices
// @desc    Consolidated time-series training dataset across all devices
// @access  Protected (API Key)
// ─────────────────────────────────────────────────────────────────────────────
exports.getAllDevicesDataset = async (req, res) => {
  try {
    const {
      start,
      end,
      all,
      devices: deviceFilter,
      deviceType,
      fields,
      limit = 50000,
      page = 1,
    } = req.query;

    const queryOptions = {
      start: all === 'true' ? null : (start ? new Date(start) : null),
      end: all === 'true' ? null : (end ? new Date(end) : null),
      limit: limit === 'all' || limit === '0' ? 1000000 : parseInt(limit, 10) || 50000,
      page: parseInt(page, 10) || 1,
    };

    // Filter target devices
    const deviceQuery = {};
    if (deviceType) deviceQuery.deviceType = deviceType;
    if (deviceFilter) {
      const idsOrMqtt = deviceFilter.split(',').map(s => s.trim());
      const objectIds = idsOrMqtt.filter(id => mongoose.Types.ObjectId.isValid(id));
      deviceQuery.$or = [
        { _id: { $in: objectIds } },
        { mqttId: { $in: idsOrMqtt } },
        { name: { $in: idsOrMqtt } },
      ];
    }

    const targetDevices = await Device.find(deviceQuery).lean();

    if (targetDevices.length === 0) {
      return res.status(200).json({
        success: true,
        count: 0,
        features: ALL_FEATURE_COLUMNS,
        data: [],
      });
    }

    // Collect and extract features from all target devices in parallel
    const perDeviceLimit = Math.max(10, Math.ceil(queryOptions.limit / targetDevices.length));

    const devicePacketResults = await Promise.all(
      targetDevices.map(async (dev) => {
        const packets = await queryDevicePackets(dev, {
          ...queryOptions,
          limit: queryOptions.limit === 1000000 ? 1000000 : perDeviceLimit,
        });

        const rows = [];
        for (const pkt of packets) {
          rows.push(...extractFeatures(pkt, dev));
        }
        return rows;
      })
    );

    let allExtractedRows = [];
    for (const rows of devicePacketResults) {
      allExtractedRows.push(...rows);
    }

    // Sort chronologically across all devices
    allExtractedRows.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

    // Cap at overall requested limit if needed
    if (queryOptions.limit !== 1000000 && allExtractedRows.length > queryOptions.limit) {
      allExtractedRows = allExtractedRows.slice(0, queryOptions.limit);
    }

    // Optional field filtering
    let selectedFieldsList = null;
    if (fields) {
      selectedFieldsList = fields.split(',').map(f => f.trim().toLowerCase());
      // Always retain essential identifier columns in JSON
      const mandatory = ['timestamp', 'device_id', 'device_mqtt_id', 'device_type', 'location', 'room'];
      mandatory.forEach(m => {
        if (!selectedFieldsList.includes(m)) selectedFieldsList.unshift(m);
      });

      allExtractedRows = allExtractedRows.map(row => {
        const filteredRow = {};
        selectedFieldsList.forEach(field => {
          if (row[field] !== undefined) filteredRow[field] = row[field];
        });
        return filteredRow;
      });
    }

    // Default JSON Output
    res.status(200).json({
      success: true,
      totalDevices: targetDevices.length,
      count: allExtractedRows.length,
      data: allExtractedRows,
    });
  } catch (err) {
    console.error('[ClientAPI Error] getAllDevicesDataset:', err);
    res.status(500).json({ success: false, message: 'Server error generating dataset' });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// @route   GET /api/client/dataset/device/:idOrMqttId
// @desc    Get training dataset for a single specific device
// @access  Protected (API Key)
// ─────────────────────────────────────────────────────────────────────────────
exports.getSingleDeviceDataset = async (req, res) => {
  try {
    const { idOrMqttId } = req.params;
    const { start, end, all, fields, limit = 50000, page = 1 } = req.query;

    const isOid = mongoose.Types.ObjectId.isValid(idOrMqttId);
    const device = await Device.findOne({
      $or: [
        isOid ? { _id: idOrMqttId } : null,
        { mqttId: { $regex: new RegExp(`^${idOrMqttId}$`, 'i') } },
        { name: { $regex: new RegExp(`^${idOrMqttId}$`, 'i') } },
      ].filter(Boolean)
    }).lean();

    if (!device) {
      return res.status(404).json({
        success: false,
        message: `Device "${idOrMqttId}" not found.`,
      });
    }

    const queryOptions = {
      start: all === 'true' ? null : (start ? new Date(start) : null),
      end: all === 'true' ? null : (end ? new Date(end) : null),
      limit: limit === 'all' || limit === '0' ? 1000000 : parseInt(limit, 10) || 50000,
      page: parseInt(page, 10) || 1,
    };

    const packets = await queryDevicePackets(device, queryOptions);
    let extractedRows = [];

    for (const pkt of packets) {
      const rows = extractFeatures(pkt, device);
      extractedRows.push(...rows);
    }

    // Optional field filtering
    let selectedFieldsList = null;
    if (fields) {
      selectedFieldsList = fields.split(',').map(f => f.trim().toLowerCase());
      const mandatory = ['timestamp', 'device_id', 'device_mqtt_id', 'device_type', 'location', 'room'];
      mandatory.forEach(m => {
        if (!selectedFieldsList.includes(m)) selectedFieldsList.unshift(m);
      });

      extractedRows = extractedRows.map(row => {
        const filteredRow = {};
        selectedFieldsList.forEach(field => {
          if (row[field] !== undefined) filteredRow[field] = row[field];
        });
        return filteredRow;
      });
    }

    // JSON format
    res.status(200).json({
      success: true,
      deviceId: device._id,
      deviceMqttId: device.mqttId,
      deviceName: device.name,
      deviceType: device.deviceType,
      count: extractedRows.length,
      data: extractedRows,
    });
  } catch (err) {
    console.error('[ClientAPI Error] getSingleDeviceDataset:', err);
    res.status(500).json({ success: false, message: 'Server error generating single device dataset' });
  }
};

