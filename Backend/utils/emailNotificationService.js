/**
 * Email Notification Service for InHydro IoT Platform
 * Handles three types of email notifications:
 *   1. Critical Alerts   — sensor values breach setpoint limits (pH, EC, Temp, Humidity)
 *   2. Status Changes     — device goes online ↔ offline
 *   3. Setpoint Changes   — someone pushes new setpoints from the dashboard
 
 * Anti-Spam:
 *   Layer 1 — In-memory cooldown map  (per alert-type + device + room)
 *   Layer 2 — Duplicate value check   (skip if same alert with same values)
 *   Layer 3 — Daily cap per device    (max 50 emails/day)
 */

const sendEmail = require('./sendEmail');
const Admin = require('../models/Admin');
const Device = require('../models/Device');
const NotificationLog = require('../models/NotificationLog');

// ─── Device & Recipient Filter ──────────────────────────────────────────────
// Only send notifications for this specific device (Noida Head Office)
const ALLOWED_MQTT_ID = 'control1';
// Only send to this admin email
const ADMIN_EMAIL = 'anujprajapa3@gmail.com';

// ─── Cooldown Configuration (milliseconds) ──────────────────────────────────
const COOLDOWNS = {
  critical_ph: 15 * 60 * 1000,       // 15 minutes
  critical_ec: 15 * 60 * 1000,
  critical_temp: 15 * 60 * 1000,
  critical_humidity: 15 * 60 * 1000,
  status_offline: 30 * 60 * 1000,    // 30 minutes
  status_online: 0,                   // Always notify recovery
  setpoint_change: 5 * 60 * 1000,    // 5 minutes
};

const DAILY_CAP_PER_DEVICE = 50;

// ─── In-Memory State ─────────────────────────────────────────────────────────
// Maps: "alertType:deviceId:room" → { lastSent: timestamp, lastValues: {...} }
const cooldownMap = new Map();

// Maps: "deviceId" → previous status string
const previousStatusMap = new Map();

// Maps: "deviceId:date" → count of emails sent today
const dailyCountMap = new Map();

// Maps: "mqttId:room" → last known setpoints from MQTT (for critical alert comparison)
const setpointCache = new Map();

// ─── Helper: Build cooldown key ─────────────────────────────────────────────
const buildKey = (alertType, deviceId, room = '') => `${alertType}:${deviceId}:${room}`;

// ─── Helper: Check if cooldown has elapsed ───────────────────────────────────
const isCooldownActive = (key, alertType) => {
  const entry = cooldownMap.get(key);
  if (!entry) return false;
  const elapsed = Date.now() - entry.lastSent;
  return elapsed < (COOLDOWNS[alertType] || 15 * 60 * 1000);
};

// ─── Helper: Check daily cap ─────────────────────────────────────────────────
const isDailyCapReached = (deviceId) => {
  const today = new Date().toISOString().slice(0, 10); // "YYYY-MM-DD"
  const countKey = `${deviceId}:${today}`;
  const count = dailyCountMap.get(countKey) || 0;
  return count >= DAILY_CAP_PER_DEVICE;
};

const incrementDailyCount = (deviceId) => {
  const today = new Date().toISOString().slice(0, 10);
  const countKey = `${deviceId}:${today}`;
  dailyCountMap.set(countKey, (dailyCountMap.get(countKey) || 0) + 1);

  // Clean up old date entries to prevent memory leak
  for (const [key] of dailyCountMap) {
    if (!key.endsWith(today)) dailyCountMap.delete(key);
  }
};

// ─── Helper: Check duplicate values (Layer 2) ───────────────────────────────
const isDuplicateValues = (key, newValues) => {
  const entry = cooldownMap.get(key);
  if (!entry || !entry.lastValues) return false;
  // Check if the alert is for the same issue (within 5% tolerance for numbers)
  const prev = entry.lastValues;
  for (const k of Object.keys(newValues)) {
    if (typeof newValues[k] === 'number' && typeof prev[k] === 'number') {
      if (Math.abs(newValues[k] - prev[k]) / (Math.abs(prev[k]) || 1) > 0.05) return false;
    } else if (newValues[k] !== prev[k]) {
      return false;
    }
  }
  return true;
};

// ─── Helper: Get all admin emails ────────────────────────────────────────────
const getAdminEmails = async () => {
  // Only send to the designated admin
  return [ADMIN_EMAIL];
};

// ─── Helper: Get device info ─────────────────────────────────────────────────
const getDeviceInfo = async (deviceId) => {
  try {
    return await Device.findById(deviceId).lean();
  } catch {
    return null;
  }
};

// ─── Core: Send notification with all anti-spam checks ───────────────────────
const trySendNotification = async ({ alertType, deviceId, room, subject, html, values }) => {
  const key = buildKey(alertType, deviceId, room);

  // Layer 1: Cooldown check
  if (isCooldownActive(key, alertType)) {
    return;
  }

  // Layer 2: Duplicate value check
  if (isDuplicateValues(key, values || {})) {
    return;
  }

  // Layer 3: Daily cap
  if (isDailyCapReached(deviceId)) {
    console.log(`[EmailNotification] Daily cap reached for device ${deviceId}. Skipping.`);
    return;
  }

  // Fetch admin emails
  const adminEmails = await getAdminEmails();
  if (adminEmails.length === 0) {
    console.warn('[EmailNotification] No active admin emails found. Skipping notification.');
    return;
  }

  try {
    await sendEmail({
      to: adminEmails.join(','),
      subject,
      html,
    });

    // Update cooldown map
    cooldownMap.set(key, { lastSent: Date.now(), lastValues: values || {} });
    incrementDailyCount(deviceId);

    // Log to database
    await NotificationLog.create({
      deviceId,
      alertType,
      room,
      message: subject,
      sentTo: adminEmails,
      values: values || {},
    });

    console.log(`[EmailNotification] ✅ Sent [${alertType}] to ${adminEmails.length} admin(s) for device ${deviceId}`);
  } catch (err) {
    console.error(`[EmailNotification] ❌ Failed to send [${alertType}]:`, err.message);
  }
};

// ═══════════════════════════════════════════════════════════════════════════════
//  1. CRITICAL ALERT DETECTION
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Called from mqttSubscriber every time a telemetry/live message arrives.
 * Compares live values against cached setpoints and fires email if breached.
 */
const checkCriticalAlerts = async (mqttId, deviceId, topic, telemetryData) => {
  // Only process the allowed device
  if (mqttId !== ALLOWED_MQTT_ID) return;
  if (!telemetryData || typeof telemetryData !== 'object') return;

  // Determine room from topic
  const parts = topic.split('/');
  const roomPart = parts.find(p => p.startsWith('room'));
  if (!roomPart) return; // Only check room-based telemetry

  const room = roomPart; // e.g. "room1"
  const cacheKey = `${mqttId}:${room}`;
  const setpoints = setpointCache.get(cacheKey);

  // If we haven't received setpoints for this device+room yet, skip
  if (!setpoints) return;

  const device = await getDeviceInfo(deviceId);
  const deviceName = device?.name || mqttId;
  const roomLabel = room.replace('room', 'Room ');
  const timestamp = new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });

  // Extract live values from telemetry
  // Handle both flat and nested structures
  const liveTemp = parseFloat(
    telemetryData.room?.room_temp ?? telemetryData.md02_1?.room_temp ?? telemetryData.room_temp ?? NaN
  );
  const liveHumidity = parseFloat(
    telemetryData.room?.room_humi ?? telemetryData.md02_1?.room_humi ?? telemetryData.room_humi ?? NaN
  );
  const livePH = parseFloat(
    telemetryData.soil?.ph ?? telemetryData.ph ?? NaN
  );
  const liveEC = parseFloat(
    telemetryData.soil?.ec ?? telemetryData.ec ?? NaN
  );

  // ── pH Check ──
  if (!isNaN(livePH) && setpoints['PH LOW'] !== undefined && setpoints['PH HIGH'] !== undefined) {
    const phLow = parseFloat(setpoints['PH LOW']);
    const phHigh = parseFloat(setpoints['PH HIGH']);
    if (livePH < phLow || livePH > phHigh) {
      await trySendNotification({
        alertType: 'critical_ph',
        deviceId,
        room,
        subject: `⚠️ pH Alert — ${deviceName} ${roomLabel}`,
        html: buildCriticalEmailHTML({
          deviceName, room: roomLabel, timestamp,
          parameter: 'pH Level',
          actual: livePH,
          min: phLow,
          max: phHigh,
          unit: '',
          color: '#ef4444',
        }),
        values: { livePH, phLow, phHigh },
      });
    }
  }

  // ── EC Check ──
  if (!isNaN(liveEC) && setpoints['EC MIN'] !== undefined && setpoints['EC MAX'] !== undefined) {
    const ecMin = parseFloat(setpoints['EC MIN']);
    const ecMax = parseFloat(setpoints['EC MAX']);
    if (liveEC < ecMin || liveEC > ecMax) {
      await trySendNotification({
        alertType: 'critical_ec',
        deviceId,
        room,
        subject: `⚠️ EC Alert — ${deviceName} ${roomLabel}`,
        html: buildCriticalEmailHTML({
          deviceName, room: roomLabel, timestamp,
          parameter: 'EC (Electrical Conductivity)',
          actual: liveEC,
          min: ecMin,
          max: ecMax,
          unit: 'mS/cm',
          color: '#f59e0b',
        }),
        values: { liveEC, ecMin, ecMax },
      });
    }
  }

  // ── Temperature Check ──
  if (!isNaN(liveTemp)) {
    // Determine if it's day or night based on current hour
    const currentHour = new Date().getHours();
    const isDaytime = currentHour >= 6 && currentHour < 18;

    let tempMin, tempMax;
    if (isDaytime) {
      tempMin = parseFloat(setpoints['DT Min'] ?? setpoints['AC1 D_T Min'] ?? NaN);
      tempMax = parseFloat(setpoints['D T Max'] ?? setpoints['AC1 D_T Max'] ?? NaN);
    } else {
      tempMin = parseFloat(setpoints['N T Min'] ?? setpoints['AC1 N_T Min'] ?? NaN);
      tempMax = parseFloat(setpoints['N T Max'] ?? setpoints['AC1 N_T Max'] ?? NaN);
    }

    if (!isNaN(tempMin) && !isNaN(tempMax) && (liveTemp < tempMin || liveTemp > tempMax)) {
      await trySendNotification({
        alertType: 'critical_temp',
        deviceId,
        room,
        subject: `🌡️ Temperature Alert — ${deviceName} ${roomLabel}`,
        html: buildCriticalEmailHTML({
          deviceName, room: roomLabel, timestamp,
          parameter: `Temperature (${isDaytime ? 'Day' : 'Night'})`,
          actual: liveTemp,
          min: tempMin,
          max: tempMax,
          unit: '°C',
          color: '#ef4444',
        }),
        values: { liveTemp, tempMin, tempMax },
      });
    }
  }

  // ── Humidity Check ──
  if (!isNaN(liveHumidity)) {
    let humiMin = parseFloat(setpoints['H Min'] ?? setpoints['HUMI1 D_H Min'] ?? NaN);
    let humiMax = parseFloat(setpoints['H Max'] ?? setpoints['HUMI1 D_H Max'] ?? NaN);

    if (!isNaN(humiMin) && !isNaN(humiMax) && (liveHumidity < humiMin || liveHumidity > humiMax)) {
      await trySendNotification({
        alertType: 'critical_humidity',
        deviceId,
        room,
        subject: `💧 Humidity Alert — ${deviceName} ${roomLabel}`,
        html: buildCriticalEmailHTML({
          deviceName, room: roomLabel, timestamp,
          parameter: 'Humidity',
          actual: liveHumidity,
          min: humiMin,
          max: humiMax,
          unit: '%',
          color: '#3b82f6',
        }),
        values: { liveHumidity, humiMin, humiMax },
      });
    }
  }
};

// ═══════════════════════════════════════════════════════════════════════════════
//  2. SETPOINT CACHE UPDATE
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Called when setpoints/current is received from the device.
 * Stores them in memory so critical alerts can compare against them.
 */
const updateSetpointCache = (mqttId, room, setpointData) => {
  if (!setpointData || typeof setpointData !== 'object') return;
  const cacheKey = `${mqttId}:${room}`;
  const existing = setpointCache.get(cacheKey) || {};
  setpointCache.set(cacheKey, { ...existing, ...setpointData });
};

// ═══════════════════════════════════════════════════════════════════════════════
//  3. SETPOINT CHANGE DETECTION
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Called when a setpoints/update message is published (someone changed setpoints).
 * Compares old vs new and sends a diff email.
 */
const checkSetpointChange = async (mqttId, deviceId, room, newSetpoints) => {
  // Only process the allowed device
  if (mqttId !== ALLOWED_MQTT_ID) return;
  if (!newSetpoints || typeof newSetpoints !== 'object') return;

  const device = await getDeviceInfo(deviceId);
  const deviceName = device?.name || mqttId;
  const roomLabel = room.replace('room', 'Room ');
  const timestamp = new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });

  // Get old setpoints from cache for diff
  const cacheKey = `${mqttId}:${room}`;
  const oldSetpoints = setpointCache.get(cacheKey) || {};

  // Build diff of changed fields (skip credential fields)
  const credentialFields = ['CLIENT ID', 'USERNAME', 'PASSWORD', 'CHANNEL ID', 'PORT', 'READ API KEY', 'WRITE API KEY'];
  const changes = [];

  for (const [key, newVal] of Object.entries(newSetpoints)) {
    if (credentialFields.includes(key)) continue;
    const oldVal = oldSetpoints[key];
    if (oldVal !== undefined && String(oldVal) !== String(newVal)) {
      changes.push({ field: key, oldVal, newVal });
    }
  }

  // Only send if there are meaningful changes (or first time = no old setpoints)
  if (changes.length === 0 && Object.keys(oldSetpoints).length > 0) return;

  await trySendNotification({
    alertType: 'setpoint_change',
    deviceId,
    room,
    subject: `🔧 Setpoints Changed — ${deviceName} ${roomLabel}`,
    html: buildSetpointChangeEmailHTML({
      deviceName,
      room: roomLabel,
      timestamp,
      changes,
      isFirstSync: Object.keys(oldSetpoints).length === 0,
    }),
    values: { changesCount: changes.length },
  });

  // Update cache with new setpoints
  setpointCache.set(cacheKey, { ...oldSetpoints, ...newSetpoints });
};

// ═══════════════════════════════════════════════════════════════════════════════
//  4. DEVICE STATUS CHANGE DETECTION
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Called when device status transitions (online→offline or offline→online).
 */
const checkStatusChange = async (deviceId, newStatus) => {
  const deviceIdStr = String(deviceId);

  // Only process the allowed device
  const device = await getDeviceInfo(deviceId);
  if (!device) return;
  const mqttId = device.mqttId || '';
  if (mqttId !== ALLOWED_MQTT_ID) return;

  const prevStatus = previousStatusMap.get(deviceIdStr);

  // Store current status
  previousStatusMap.set(deviceIdStr, newStatus);

  // Skip if no previous status (first detection) or no change
  if (!prevStatus || prevStatus === newStatus) return;

  // Only alert on meaningful transitions
  if (
    (prevStatus === 'online' && newStatus === 'offline') ||
    (prevStatus === 'offline' && newStatus === 'online')
  ) {
    const device = await getDeviceInfo(deviceId);
    const deviceName = device?.name || deviceIdStr;
    const timestamp = new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
    const isOnline = newStatus === 'online';
    const alertType = isOnline ? 'status_online' : 'status_offline';

    await trySendNotification({
      alertType,
      deviceId: deviceIdStr,
      room: '',
      subject: isOnline
        ? `✅ Device Online — ${deviceName}`
        : `🔴 Device Offline — ${deviceName}`,
      html: buildStatusChangeEmailHTML({
        deviceName,
        timestamp,
        isOnline,
        location: device?.location || 'N/A',
      }),
      values: { prevStatus, newStatus },
    });
  }
};

// ═══════════════════════════════════════════════════════════════════════════════
//  HTML EMAIL TEMPLATES
// ═══════════════════════════════════════════════════════════════════════════════

const emailWrapper = (title, bodyContent) => `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#0f172a;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0f172a;padding:32px 16px;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color:#1e293b;border-radius:16px;overflow:hidden;border:1px solid #334155;">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#059669,#0d9488);padding:24px 32px;">
              <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:700;">
                🌿 INHYDRO Smart Agriculture
              </h1>
              <p style="margin:4px 0 0;color:#a7f3d0;font-size:12px;text-transform:uppercase;letter-spacing:1px;">
                ${title}
              </p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:32px;">
              ${bodyContent}
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:16px 32px;border-top:1px solid #334155;background-color:#0f172a;">
              <p style="margin:0;color:#64748b;font-size:11px;text-align:center;">
                This is an automated alert from InHydro IoT Platform. Do not reply to this email.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>`;

const buildCriticalEmailHTML = ({ deviceName, room, timestamp, parameter, actual, min, max, unit, color }) => {
  const status = actual < min ? 'BELOW MINIMUM' : 'ABOVE MAXIMUM';
  return emailWrapper('Critical Sensor Alert', `
    <div style="background-color:${color}15;border:1px solid ${color}40;border-radius:12px;padding:20px;margin-bottom:20px;">
      <h2 style="margin:0 0 8px;color:${color};font-size:18px;">⚠️ ${parameter} — ${status}</h2>
      <p style="margin:0;color:#94a3b8;font-size:13px;">
        ${deviceName} • ${room} • ${timestamp}
      </p>
    </div>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
      <tr>
        <td style="padding:12px;background-color:#0f172a;border-radius:8px;text-align:center;width:33%;">
          <p style="margin:0;color:#64748b;font-size:11px;text-transform:uppercase;">Current Value</p>
          <p style="margin:4px 0 0;color:${color};font-size:24px;font-weight:700;">${actual}${unit ? ' ' + unit : ''}</p>
        </td>
        <td style="width:8px;"></td>
        <td style="padding:12px;background-color:#0f172a;border-radius:8px;text-align:center;width:33%;">
          <p style="margin:0;color:#64748b;font-size:11px;text-transform:uppercase;">Min Limit</p>
          <p style="margin:4px 0 0;color:#22c55e;font-size:24px;font-weight:700;">${min}${unit ? ' ' + unit : ''}</p>
        </td>
        <td style="width:8px;"></td>
        <td style="padding:12px;background-color:#0f172a;border-radius:8px;text-align:center;width:33%;">
          <p style="margin:0;color:#64748b;font-size:11px;text-transform:uppercase;">Max Limit</p>
          <p style="margin:4px 0 0;color:#22c55e;font-size:24px;font-weight:700;">${max}${unit ? ' ' + unit : ''}</p>
        </td>
      </tr>
    </table>

    <p style="color:#94a3b8;font-size:13px;margin:0;">
      Please check the device immediately. This alert will not repeat for <strong style="color:#e2e8f0;">15 minutes</strong> for the same issue.
    </p>
  `);
};

const buildStatusChangeEmailHTML = ({ deviceName, timestamp, isOnline, location }) => {
  const color = isOnline ? '#22c55e' : '#ef4444';
  const statusText = isOnline ? 'ONLINE' : 'OFFLINE';
  const icon = isOnline ? '✅' : '🔴';
  const message = isOnline
    ? 'The device is back online and transmitting telemetry data.'
    : 'The device has stopped sending data for more than 2 minutes. Please check the device connection, power supply, and network.';

  return emailWrapper('Device Status Change', `
    <div style="background-color:${color}15;border:1px solid ${color}40;border-radius:12px;padding:20px;margin-bottom:20px;">
      <h2 style="margin:0 0 8px;color:${color};font-size:18px;">${icon} Device ${statusText}</h2>
      <p style="margin:0;color:#94a3b8;font-size:13px;">${timestamp}</p>
    </div>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
      <tr>
        <td style="padding:12px;background-color:#0f172a;border-radius:8px;">
          <table width="100%" cellpadding="4" cellspacing="0">
            <tr>
              <td style="color:#64748b;font-size:12px;width:120px;">Device Name</td>
              <td style="color:#e2e8f0;font-size:13px;font-weight:600;">${deviceName}</td>
            </tr>
            <tr>
              <td style="color:#64748b;font-size:12px;">Location</td>
              <td style="color:#e2e8f0;font-size:13px;">${location}</td>
            </tr>
            <tr>
              <td style="color:#64748b;font-size:12px;">New Status</td>
              <td>
                <span style="display:inline-block;padding:2px 10px;border-radius:999px;font-size:11px;font-weight:700;color:${color};background-color:${color}20;border:1px solid ${color}40;">
                  ${statusText}
                </span>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>

    <p style="color:#94a3b8;font-size:13px;margin:0;">${message}</p>
  `);
};

const buildSetpointChangeEmailHTML = ({ deviceName, room, timestamp, changes, isFirstSync }) => {
  if (isFirstSync) {
    return emailWrapper('Setpoints Updated', `
      <div style="background-color:#3b82f615;border:1px solid #3b82f640;border-radius:12px;padding:20px;margin-bottom:20px;">
        <h2 style="margin:0 0 8px;color:#3b82f6;font-size:18px;">🔧 Setpoints Pushed</h2>
        <p style="margin:0;color:#94a3b8;font-size:13px;">
          ${deviceName} • ${room} • ${timestamp}
        </p>
      </div>
      <p style="color:#94a3b8;font-size:13px;margin:0;">
        New setpoints have been pushed to this device room. This is the first sync detected by the notification system.
      </p>
    `);
  }

  let changesHTML = '';
  for (const c of changes.slice(0, 20)) { // Max 20 rows in email
    changesHTML += `
      <tr>
        <td style="padding:8px 12px;color:#e2e8f0;font-size:12px;border-bottom:1px solid #1e293b;">${c.field}</td>
        <td style="padding:8px 12px;color:#ef4444;font-size:12px;text-align:center;border-bottom:1px solid #1e293b;">${c.oldVal}</td>
        <td style="padding:8px 12px;color:#22c55e;font-size:12px;text-align:center;border-bottom:1px solid #1e293b;font-weight:600;">${c.newVal}</td>
      </tr>`;
  }

  return emailWrapper('Setpoints Updated', `
    <div style="background-color:#f59e0b15;border:1px solid #f59e0b40;border-radius:12px;padding:20px;margin-bottom:20px;">
      <h2 style="margin:0 0 8px;color:#f59e0b;font-size:18px;">🔧 Setpoints Changed (${changes.length} field${changes.length !== 1 ? 's' : ''})</h2>
      <p style="margin:0;color:#94a3b8;font-size:13px;">
        ${deviceName} • ${room} • ${timestamp}
      </p>
    </div>

    <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0f172a;border-radius:8px;overflow:hidden;margin-bottom:20px;">
      <tr>
        <th style="padding:10px 12px;color:#64748b;font-size:11px;text-transform:uppercase;text-align:left;border-bottom:1px solid #334155;">Parameter</th>
        <th style="padding:10px 12px;color:#64748b;font-size:11px;text-transform:uppercase;text-align:center;border-bottom:1px solid #334155;">Old Value</th>
        <th style="padding:10px 12px;color:#64748b;font-size:11px;text-transform:uppercase;text-align:center;border-bottom:1px solid #334155;">New Value</th>
      </tr>
      ${changesHTML}
    </table>

    ${changes.length > 20 ? `<p style="color:#94a3b8;font-size:12px;">...and ${changes.length - 20} more changes</p>` : ''}
    <p style="color:#94a3b8;font-size:13px;margin:0;">
      Someone has modified the setpoints for this device. If this was not authorized, please check the dashboard immediately.
    </p>
  `);
};

// ═══════════════════════════════════════════════════════════════════════════════
//  EXPORTS
// ═══════════════════════════════════════════════════════════════════════════════

module.exports = {
  checkCriticalAlerts,
  checkStatusChange,
  checkSetpointChange,
  updateSetpointCache,
};
