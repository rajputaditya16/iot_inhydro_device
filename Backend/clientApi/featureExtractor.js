/**
 * Feature Extractor Utility for AI / Machine Learning Data Pipelines
 * Normalizes varied IoT device schemas into standardized, flat feature records.
 */

const cleanNumber = (val) => {
  if (val === null || val === undefined || val === '') return null;
  const num = parseFloat(val);
  if (isNaN(num) || num === -999 || num === -999.0) return null;
  return num;
};

/**
 * Normalizes a raw telemetry document into one or more flat feature rows.
 * @param {object} packet - The MongoDB TelemetryLog document
 * @param {object} deviceMeta - The Device metadata document
 * @returns {Array<object>} Array of flat feature objects
 */
const extractFeatures = (packet, deviceMeta = {}) => {
  if (!packet) return [];

  const rawData = packet.data || {};
  const timestamp = packet.timestamp ? new Date(packet.timestamp).toISOString() : new Date().toISOString();
  const deviceId = packet.deviceId ? String(packet.deviceId) : (deviceMeta._id ? String(deviceMeta._id) : null);
  const deviceMqttId = packet.mqttId || deviceMeta.mqttId || 'unknown';
  const deviceType = deviceMeta.deviceType || 'generic';
  const deviceName = deviceMeta.name || deviceMqttId;
  const location = deviceMeta.location || '';
  const cropName = deviceMeta.cropName || '';
  const setupName = deviceMeta.setupName || '';

  const baseMeta = {
    timestamp,
    device_id: deviceId,
    device_mqtt_id: deviceMqttId,
    device_name: deviceName,
    device_type: deviceType,
    location,
    crop_name: cropName,
    setup_name: setupName,
  };

  const rows = [];

  // ── 1. Office Control / System2 (Multi-Room or Single Room) ─────────────────
  if (deviceType === 'office_control' || deviceType === 'system2') {
    const isMerged = (rawData.room1 !== undefined || rawData.room2 !== undefined || rawData.room3 !== undefined);

    if (isMerged) {
      // Process Room 1
      if (rawData.room1) {
        const r1 = rawData.room1;
        rows.push({
          ...baseMeta,
          room: 'room1',
          water_temp: cleanNumber(r1.soil?.soil_temp ?? r1.soil?.temp ?? r1.water_temp),
          soil_moisture: cleanNumber(r1.soil?.moisture ?? r1.soil?.humidity ?? r1.moisture),
          ec: cleanNumber(r1.soil?.ec ?? r1.ec),
          ph: cleanNumber(r1.soil?.ph ?? r1.ph),
          room_temp: cleanNumber(r1.room?.room_temp ?? r1.room?.temp ?? r1.room_temp),
          room_humidity: cleanNumber(r1.room?.room_humi ?? r1.room?.humidity ?? r1.room_humi),
          orp: cleanNumber(r1.orp),
          co2: cleanNumber(r1.co2),
        });
      }

      // Process Room 2
      if (rawData.room2) {
        const r2 = rawData.room2;
        rows.push({
          ...baseMeta,
          room: 'room2',
          water_temp: cleanNumber(r2.soil?.soil_temp ?? r2.soil?.temp ?? r2.water_temp),
          soil_moisture: cleanNumber(r2.soil?.moisture ?? r2.soil?.humidity ?? r2.moisture),
          ec: cleanNumber(r2.soil?.ec ?? r2.ec),
          ph: cleanNumber(r2.soil?.ph ?? r2.ph),
          room_temp: cleanNumber(r2.room?.room_temp ?? r2.room?.temp ?? r2.room_temp),
          room_humidity: cleanNumber(r2.room?.room_humi ?? r2.room?.humidity ?? r2.room_humi),
          orp: cleanNumber(r2.orp),
          co2: cleanNumber(r2.co2),
        });
      }

      // Process Room 3 (Dual MD02 + CO2)
      if (rawData.room3) {
        const r3 = rawData.room3;
        rows.push({
          ...baseMeta,
          room: 'room3',
          sensor1_temp: cleanNumber(r3.md02_1?.room_temp ?? r3.md02_1?.temp),
          sensor1_humidity: cleanNumber(r3.md02_1?.room_humi ?? r3.md02_1?.humidity),
          sensor2_temp: cleanNumber(r3.md02_2?.room_temp ?? r3.md02_2?.temp),
          sensor2_humidity: cleanNumber(r3.md02_2?.room_humi ?? r3.md02_2?.humidity),
          co2: cleanNumber(r3.co2),
        });
      }
    } else {
      // Non-merged packet (per-room topic or flat data)
      const topic = packet.topic || '';
      let detectedRoom = 'room1';
      if (topic.includes('room3')) detectedRoom = 'room3';
      else if (topic.includes('room2')) detectedRoom = 'room2';

      if (detectedRoom === 'room3') {
        rows.push({
          ...baseMeta,
          room: detectedRoom,
          sensor1_temp: cleanNumber(rawData.md02_1?.room_temp ?? rawData.md02_1?.temp ?? rawData.field1),
          sensor1_humidity: cleanNumber(rawData.md02_1?.room_humi ?? rawData.md02_1?.humidity ?? rawData.field2),
          sensor2_temp: cleanNumber(rawData.md02_2?.room_temp ?? rawData.md02_2?.temp ?? rawData.field3),
          sensor2_humidity: cleanNumber(rawData.md02_2?.room_humi ?? rawData.md02_2?.humidity ?? rawData.field4),
          co2: cleanNumber(rawData.co2 ?? rawData.field8),
        });
      } else {
        rows.push({
          ...baseMeta,
          room: detectedRoom,
          water_temp: cleanNumber(rawData.soil?.soil_temp ?? rawData.soil?.temp ?? rawData.water_temp ?? rawData.field1),
          soil_moisture: cleanNumber(rawData.soil?.moisture ?? rawData.soil?.humidity ?? rawData.moisture ?? rawData.field2),
          ec: cleanNumber(rawData.soil?.ec ?? rawData.ec ?? rawData.field3),
          ph: cleanNumber(rawData.soil?.ph ?? rawData.ph ?? rawData.field4),
          room_temp: cleanNumber(rawData.room?.room_temp ?? rawData.room?.temp ?? rawData.room_temp ?? rawData.field5),
          room_humidity: cleanNumber(rawData.room?.room_humi ?? rawData.room?.humidity ?? rawData.room_humi ?? rawData.field6),
          orp: cleanNumber(rawData.orp ?? rawData.field7),
          co2: cleanNumber(rawData.co2 ?? rawData.field8),
        });
      }
    }
  }
  // ── 2. Controlling Subsystem (Greenhouse CEA Master Controller) ─────────────
  else if (deviceType === 'controlling') {
    const tel = rawData.telemetry || rawData.sensors || rawData || {};
    rows.push({
      ...baseMeta,
      water_temp: cleanNumber(tel.water_temp ?? tel.temp),
      soil_moisture: cleanNumber(tel.moisture ?? tel.moist ?? tel.humidity),
      ec: cleanNumber(tel.ec),
      ph: cleanNumber(tel.ph),
      room_temp: cleanNumber(tel.room_temp ?? tel.temp_room),
      room_humidity: cleanNumber(tel.room_humi ?? tel.humidity_room),
      orp: cleanNumber(tel.orp),
      co2: cleanNumber(tel.co2),
      vpd: cleanNumber(tel.vpd),
      dli: cleanNumber(tel.dli),
      wind_speed: cleanNumber(tel.wind_speed),
      wind_direction: cleanNumber(tel.wind_dir ?? tel.wind_direction),
      dissolved_oxygen: cleanNumber(tel.do ?? tel.dissolved_oxygen),
      ppfd: cleanNumber(tel.ppfd),
      nitrogen: cleanNumber(tel.n ?? tel.nitrogen),
      phosphorus: cleanNumber(tel.p ?? tel.phosphorus),
      potassium: cleanNumber(tel.k ?? tel.potassium),
    });
  }
  // ── 3. Multi-Sensor / Almora 7-Chamber Cold Storage ──────────────────────────
  else if (deviceType === 'multi_sensor' || deviceType === 'almora' || deviceType === 'almora2' || deviceType === 'cold_storage') {
    const getProbe = (num) => {
      const lower = `s${num}`;
      const upper = `S${num}`;
      if (rawData[lower]) return rawData[lower];
      if (rawData[upper]) return rawData[upper];
      if (rawData.sensor_data && typeof rawData.sensor_data === 'object') {
        if (rawData.sensor_data[lower]) return rawData.sensor_data[lower];
        if (rawData.sensor_data[upper]) return rawData.sensor_data[upper];
        for (const probe of Object.values(rawData.sensor_data)) {
          if (probe && (probe.id === num || probe.id === String(num))) return probe;
        }
      }
      return null;
    };

    const s1 = getProbe(1);
    const s2 = getProbe(2);
    const s3 = getProbe(3);
    const s4 = getProbe(4);
    const s5 = getProbe(5);
    const s6 = getProbe(6);
    const s7 = getProbe(7);

    rows.push({
      ...baseMeta,
      chamber1_temp: cleanNumber(s1?.t ?? s1?.temp ?? rawData.field1),
      chamber1_humidity: cleanNumber(s1?.h ?? s1?.humi ?? s1?.hum),
      chamber2_temp: cleanNumber(s2?.t ?? s2?.temp ?? rawData.field2),
      chamber2_humidity: cleanNumber(s2?.h ?? s2?.humi ?? s2?.hum),
      chamber3_temp: cleanNumber(s3?.t ?? s3?.temp ?? rawData.field3),
      chamber3_humidity: cleanNumber(s3?.h ?? s3?.humi ?? s3?.hum),
      chamber4_temp: cleanNumber(s4?.t ?? s4?.temp ?? rawData.field4),
      chamber4_humidity: cleanNumber(s4?.h ?? s4?.humi ?? s4?.hum),
      chamber5_temp: cleanNumber(s5?.t ?? s5?.temp ?? rawData.field5),
      chamber5_humidity: cleanNumber(s5?.h ?? s5?.humi ?? s5?.hum),
      chamber6_temp: cleanNumber(s6?.t ?? s6?.temp ?? rawData.field6),
      chamber6_humidity: cleanNumber(s6?.h ?? s6?.humi ?? s6?.hum),
      chamber7_temp: cleanNumber(s7?.t ?? s7?.temp ?? rawData.field7),
      chamber7_humidity: cleanNumber(s7?.h ?? s7?.humi ?? s7?.hum),
    });
  }
  // ── 4. Monit / Monnet / Generic Devices ──────────────────────────────────────
  else {
    const d = rawData.telemetry || rawData || {};
    rows.push({
      ...baseMeta,
      water_temp: cleanNumber(d.water_temp ?? d.temp ?? d.soil_temp ?? d.field1),
      soil_moisture: cleanNumber(d.moisture ?? d.moist ?? d.soil_moisture ?? d.humidity ?? d.field2),
      ec: cleanNumber(d.ec ?? d.soil_ec ?? d.field3),
      ph: cleanNumber(d.ph ?? d.soil_ph ?? d.field4),
      room_temp: cleanNumber(d.room_temp ?? d.temperature ?? d.field5),
      room_humidity: cleanNumber(d.room_humi ?? d.humidity ?? d.field6),
      orp: cleanNumber(d.orp ?? d.field7),
      co2: cleanNumber(d.co2 ?? d.field8),
    });
  }

  return rows;
};

/**
 * Standard list of all known ML feature column names.
 */
const ALL_FEATURE_COLUMNS = [
  'timestamp',
  'device_id',
  'device_mqtt_id',
  'device_name',
  'device_type',
  'location',
  'crop_name',
  'setup_name',
  'room',
  'water_temp',
  'soil_moisture',
  'ec',
  'ph',
  'room_temp',
  'room_humidity',
  'co2',
  'orp',
  'vpd',
  'dli',
  'wind_speed',
  'wind_direction',
  'dissolved_oxygen',
  'ppfd',
  'nitrogen',
  'phosphorus',
  'potassium',
  'sensor1_temp',
  'sensor1_humidity',
  'sensor2_temp',
  'sensor2_humidity',
  'chamber1_temp',
  'chamber1_humidity',
  'chamber2_temp',
  'chamber2_humidity',
  'chamber3_temp',
  'chamber3_humidity',
  'chamber4_temp',
  'chamber4_humidity',
  'chamber5_temp',
  'chamber5_humidity',
  'chamber6_temp',
  'chamber6_humidity',
  'chamber7_temp',
  'chamber7_humidity'
];

module.exports = {
  extractFeatures,
  cleanNumber,
  ALL_FEATURE_COLUMNS,
};
