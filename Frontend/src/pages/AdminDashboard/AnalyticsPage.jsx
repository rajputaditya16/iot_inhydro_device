import { useState, useEffect, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Download, Calendar, RefreshCw, WifiOff, BarChart3, TrendingUp, TrendingDown,
  Activity, Cpu, Thermometer, Droplets, Layers, Eye, CheckCircle2,
  SlidersHorizontal, ChevronRight, FileSpreadsheet, Sparkles, Wind, ArrowUpRight,
  Target, Clock, Sun, Moon, Zap, AlertTriangle, FileDown, ChevronDown, Check,
  FolderDown, FileText, Leaf
} from 'lucide-react';
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend
} from 'recharts';
import LiveChart from '../../components/LiveChart';
import { SkeletonCard } from '../../components/Skeleton';

// Get date ranges for filters
const getDateRange = (filter, customStartDate = null, customEndDate = null, durationVal = 1, durationUnit = 'hours') => {
  const now = new Date();
  let start;
  let end = new Date(now);

  switch (filter) {
    case 'today': {
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
      break;
    }
    case 'yesterday': {
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 0, 0, 0, 0);
      end = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 23, 59, 59, 999);
      break;
    }
    case 'week': {
      const dayOfWeek = now.getDay();
      const mondayOffset = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - mondayOffset, 0, 0, 0, 0);
      break;
    }
    case 'month': {
      start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0, 0);
      break;
    }
    case 'three_months': {
      start = new Date(now.getFullYear(), now.getMonth() - 3, now.getDate(), 0, 0, 0, 0);
      break;
    }
    case 'all': {
      start = new Date(0);
      break;
    }
    case 'duration': {
      const val = Math.max(1, parseFloat(durationVal) || 1);
      const msMap = {
        seconds: val * 1000,
        minutes: val * 60 * 1000,
        hours: val * 60 * 60 * 1000,
        days: val * 24 * 60 * 60 * 1000,
      };
      const durationMs = msMap[durationUnit] || msMap.hours;
      start = new Date(now.getTime() - durationMs);
      break;
    }
    case 'custom': {
      if (customStartDate && customEndDate) {
        start = new Date(customStartDate);
        end = new Date(customEndDate);
      } else if (customStartDate) {
        start = new Date(customStartDate);
      } else if (customEndDate) {
        start = new Date(new Date(customEndDate).getTime() - 7 * 24 * 60 * 60 * 1000);
        end = new Date(customEndDate);
      } else {
        start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      }
      break;
    }
    default:
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
  }
  return { start, end };
};

// Get field visual info
const getFieldMeta = (name) => {
  const lowerName = name.toLowerCase();
  if (lowerName.includes('temp')) return { type: 'temperature', unit: '°C', icon: Thermometer, color: 'text-orange-400', bg: 'bg-orange-500/10 border-orange-500/20' };
  if (lowerName.includes('moist') || lowerName.includes('hum')) return { type: 'moisture', unit: '%', icon: Droplets, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' };
  if (lowerName.includes('ec')) return { type: 'ec', unit: 'mS/cm', icon: BarChart3, color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/20' };
  if (lowerName.includes('ph')) return { type: 'ph', unit: '', icon: TrendingDown, color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' };
  if (lowerName.includes('co2')) return { type: 'co2', unit: 'PPM', icon: Activity, color: 'text-teal-400', bg: 'bg-teal-500/10 border-teal-500/20' };
  if (lowerName.includes('vpd')) return { type: 'default', unit: 'kPa', icon: Activity, color: 'text-cyan-400', bg: 'bg-cyan-500/10 border-cyan-500/20' };
  if (lowerName.includes('dli')) return { type: 'default', unit: 'mol/m²/d', icon: Activity, color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20' };
  if (lowerName.includes('wind_speed') || lowerName.includes('wind speed')) return { type: 'default', unit: 'm/s', icon: Activity, color: 'text-sky-400', bg: 'bg-sky-500/10 border-sky-500/20' };
  if (lowerName.includes('wind_dir') || lowerName.includes('wind direction')) return { type: 'default', unit: '°', icon: Activity, color: 'text-indigo-400', bg: 'bg-indigo-500/10 border-indigo-500/20' };
  if (lowerName.includes('dissolved oxygen') || lowerName.includes('do')) return { type: 'default', unit: 'mg/L', icon: Activity, color: 'text-rose-400', bg: 'bg-rose-500/10 border-rose-500/20' };
  if (lowerName.includes('ppfd')) return { type: 'default', unit: 'µmol/m²/s', icon: Activity, color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/20' };
  if (lowerName.includes('(n)') || lowerName.includes('nitrogen')) return { type: 'default', unit: 'mg/kg', icon: Activity, color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' };
  if (lowerName.includes('(p)') || lowerName.includes('phosphorus')) return { type: 'default', unit: 'mg/kg', icon: Activity, color: 'text-lime-400', bg: 'bg-lime-500/10 border-lime-500/20' };
  if (lowerName.includes('(k)') || lowerName.includes('potassium')) return { type: 'default', unit: 'mg/kg', icon: Activity, color: 'text-violet-400', bg: 'bg-violet-500/10 border-violet-500/20' };
  return { type: 'default', unit: '', icon: Activity, color: 'text-slate-400', bg: 'bg-slate-800/50 border-slate-700/50' };
};

const parseRobustFloat = (val) => {
  if (val === null || val === undefined || val === '') return null;
  if (typeof val === 'string' && val.trim().startsWith('[')) {
    try {
      const arr = JSON.parse(val);
      if (Array.isArray(arr) && arr.length > 0) {
        const parsedArr = arr.map(v => parseFloat(v)).filter(v => !isNaN(v));
        if (parsedArr.length > 0) {
          return parsedArr.reduce((a, b) => a + b, 0) / parsedArr.length;
        }
      }
    } catch (e) { }
  }
  const parsed = parseFloat(val);
  return isNaN(parsed) ? null : parsed;
};

// Date helpers for Setpoint stage matching
const parseIsoOrDmy = (dateStr) => {
  if (!dateStr) return null;
  const s = String(dateStr).trim();
  const dmyMatch = s.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$/);
  if (dmyMatch) {
    const day = parseInt(dmyMatch[1], 10);
    const month = parseInt(dmyMatch[2], 10) - 1;
    const year = parseInt(dmyMatch[3], 10);
    const d = new Date(year, month, day);
    return isNaN(d.getTime()) ? null : d;
  }
  const isoMatch = s.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
  if (isoMatch) {
    const year = parseInt(isoMatch[1], 10);
    const month = parseInt(isoMatch[2], 10) - 1;
    const day = parseInt(isoMatch[3], 10);
    const d = new Date(year, month, day);
    return isNaN(d.getTime()) ? null : d;
  }
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
};

const formatDmy = (d) => {
  if (!d) return '';
  const dateObj = (d instanceof Date) ? d : parseIsoOrDmy(d);
  if (!dateObj || isNaN(dateObj.getTime())) return String(d);
  const day = String(dateObj.getDate()).padStart(2, '0');
  const month = String(dateObj.getMonth() + 1).padStart(2, '0');
  const year = dateObj.getFullYear();
  return `${day}-${month}-${year}`;
};

const formatTime24h = (tStr) => {
  if (!tStr) return '00:00';
  const s = String(tStr).trim();
  if (!s.toUpperCase().includes('AM') && !s.toUpperCase().includes('PM')) {
    return s;
  }
  try {
    const match = s.match(/(\d+):(\d+)\s*(AM|PM)/i);
    if (match) {
      let hh = parseInt(match[1], 10);
      const mm = parseInt(match[2], 10);
      const meridiem = match[3].toUpperCase();
      if (meridiem === 'PM' && hh < 12) hh += 12;
      else if (meridiem === 'AM' && hh === 12) hh = 0;
      return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
    }
  } catch { }
  return s;
};

const timeToMinutes = (tStr) => {
  const t24 = formatTime24h(tStr);
  const parts = t24.split(':');
  const h = parseInt(parts[0] || '0', 10);
  const m = parseInt(parts[1] || '0', 10);
  return (isNaN(h) ? 0 : h) * 60 + (isNaN(m) ? 0 : m);
};

const getMatchingTimeSlot = (stage, date) => {
  if (!stage || !stage.time_slots || stage.time_slots.length === 0) return null;
  const d = (date instanceof Date) ? date : new Date(date);
  if (isNaN(d.getTime())) return stage.time_slots[0];

  const currentMin = d.getHours() * 60 + d.getMinutes();
  const enabledSlots = stage.time_slots.filter(s => s.enabled !== false);
  if (enabledSlots.length === 0) return stage.time_slots[0];

  for (const slot of enabledSlots) {
    const sMin = timeToMinutes(slot.start || '00:00');
    let eMin = timeToMinutes(slot.stop || '23:59');
    if (eMin <= sMin) {
      // Over midnight slot (e.g. 20:00 - 05:00)
      if (currentMin >= sMin || currentMin < eMin) {
        return slot;
      }
    } else {
      if (currentMin >= sMin && currentMin < eMin) {
        return slot;
      }
    }
  }
  return enabledSlots[0];
};

const getMatchingStage = (stagesDict, date, activeSettingKey = 'Setting A') => {
  if (!stagesDict) return null;
  const d = (date instanceof Date) ? date : new Date(date);
  if (isNaN(d.getTime())) return stagesDict[activeSettingKey] ? { key: activeSettingKey, ...stagesDict[activeSettingKey] } : null;

  for (const key of ALL_SETTING_KEYS) {
    const st = stagesDict[key];
    if (!st || st.enabled === false) continue;
    const sDate = parseIsoOrDmy(st.start_date);
    const eDate = parseIsoOrDmy(st.end_date);
    if (sDate && eDate) {
      const sDay = new Date(sDate.getFullYear(), sDate.getMonth(), sDate.getDate(), 0, 0, 0, 0);
      const eDay = new Date(eDate.getFullYear(), eDate.getMonth(), eDate.getDate(), 23, 59, 59, 999);
      if (d >= sDay && d <= eDay) {
        return { key, ...st };
      }
    }
  }
  return stagesDict[activeSettingKey]
    ? { key: activeSettingKey, ...stagesDict[activeSettingKey] }
    : (Object.values(stagesDict)[0] ? { key: Object.keys(stagesDict)[0], ...Object.values(stagesDict)[0] } : null);
};

const ALL_SETTING_KEYS = [
  'Setting A', 'Setting B', 'Setting C', 'Setting D', 'Setting E',
  'Setting F', 'Setting G', 'Setting H', 'Setting I', 'Setting J'
];

const generateDefaultAlmoraSchedule = (sKey = 'S1') => {
  const defaultCrop = `${DEFAULT_COLD_ROOM_NAMES[sKey] || sKey} Program`;
  const defaultSetup = `${DEFAULT_COLD_ROOM_NAMES[sKey] || sKey} Setup`;

  const stages = {};
  const stageDefs = [
    { key: 'Setting A', name: 'Crop Stage 1', start: '01-07-2026', end: '15-07-2026' },
    { key: 'Setting B', name: 'Crop Stage 2', start: '16-07-2026', end: '31-07-2026' },
    { key: 'Setting C', name: 'Crop Stage 3', start: '01-08-2026', end: '15-08-2026' },
    { key: 'Setting D', name: 'Crop Stage 4', start: '16-08-2026', end: '31-08-2026' },
    { key: 'Setting E', name: 'Crop Stage 5', start: '01-09-2026', end: '15-09-2026' },
    { key: 'Setting F', name: 'Crop Stage 6', start: '16-09-2026', end: '30-09-2026' },
    { key: 'Setting G', name: 'Crop Stage 7', start: '01-10-2026', end: '15-10-2026' },
    { key: 'Setting H', name: 'Crop Stage 8', start: '16-10-2026', end: '31-10-2026' },
    { key: 'Setting I', name: 'Crop Stage 9', start: '01-11-2026', end: '15-11-2026' },
    { key: 'Setting J', name: 'Crop Stage 10', start: '16-11-2026', end: '30-11-2026' }
  ];

  stageDefs.forEach((def, index) => {
    stages[def.key] = {
      name: def.name,
      crop_name: defaultCrop,
      setup_name: defaultSetup,
      start_date: def.start,
      end_date: def.end,
      enabled: index < 5,
      photoperiod_on: '06:00 AM',
      photoperiod_off: '08:00 PM',
      lighting_enabled: true,
      time_slots: [
        { id: 1, name: 'Slot 1', start: '12:00 AM', stop: '05:00 AM', t_set: 24.0, t_max: 25.0, t_min: 20.0, h_set: 60.0, h_max: 70.0, h_min: 55.0, enabled: true },
        { id: 2, name: 'Slot 2', start: '05:00 AM', stop: '10:00 AM', t_set: 25.0, t_max: 26.0, t_min: 21.0, h_set: 65.0, h_max: 70.0, h_min: 60.0, enabled: true },
        { id: 3, name: 'Slot 3', start: '10:00 AM', stop: '03:00 PM', t_set: 27.0, t_max: 28.0, t_min: 23.0, h_set: 70.0, h_max: 75.0, h_min: 60.0, enabled: true },
        { id: 4, name: 'Slot 4', start: '03:00 PM', stop: '08:00 PM', t_set: 26.0, t_max: 27.0, t_min: 22.0, h_set: 68.0, h_max: 72.0, h_min: 60.0, enabled: true },
        { id: 5, name: 'Slot 5', start: '08:00 PM', stop: '12:00 AM', t_set: 24.0, t_max: 25.0, t_min: 20.0, h_set: 62.0, h_max: 68.0, h_min: 55.0, enabled: true }
      ]
    };
  });

  return {
    crop_name: defaultCrop,
    setup_name: defaultSetup,
    mode: 'SCHEDULED',
    active_setting: 'Setting A',
    'T MIN': 10.0,
    'T MAX': 30.0,
    'H MIN': 30.0,
    'H MAX': 80.0,
    settings: stages
  };
};

// Format feeds into chart-ready data dynamically based on available channel fields
const mapFeedsToCharts = (feeds, filter, channelFields, isBothRooms = false, durationUnit = 'hours') => {
  const validFeeds = Array.isArray(feeds) ? feeds : [];
  if (validFeeds.length === 0) return {};

  let isMultiDay = ['week', 'month', 'three_months'].includes(filter);
  if (!isMultiDay && filter === 'custom' && validFeeds.length > 1) {
    const firstDate = new Date(validFeeds[0].created_at).toDateString();
    const lastDate = new Date(validFeeds[validFeeds.length - 1].created_at).toDateString();
    if (firstDate !== lastDate) {
      isMultiDay = true;
    }
  }

  const showSeconds = filter === 'duration' && (durationUnit === 'seconds' || durationUnit === 'minutes');

  const timeFormat = isMultiDay
    ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
    : showSeconds
      ? { hour: '2-digit', minute: '2-digit', second: '2-digit' }
      : { hour: '2-digit', minute: '2-digit' };

  const dtf = new Intl.DateTimeFormat('en-US', timeFormat);

  if (!isBothRooms) {
    const formattedTimes = new Array(validFeeds.length);
    for (let i = 0; i < validFeeds.length; i++) {
      formattedTimes[i] = dtf.format(new Date(validFeeds[i].created_at));
    }

    const mappedData = {};
    channelFields.forEach(field => {
      const arr = new Array(validFeeds.length);
      for (let i = 0; i < validFeeds.length; i++) {
        const parsedVal = parseRobustFloat(validFeeds[i][field.key]);
        arr[i] = {
          time: formattedTimes[i],
          value: parsedVal !== null ? parsedVal : 0,
        };
      }
      mappedData[field.key] = arr;
    });
    return mappedData;
  } else {
    const timeGroupsMap = new Map();
    for (let i = 0; i < validFeeds.length; i++) {
      const f = validFeeds[i];
      const timeObj = new Date(f.created_at);
      const roundedMs = Math.round(timeObj.getTime() / 15000) * 15000;

      if (!timeGroupsMap.has(roundedMs)) {
        timeGroupsMap.set(roundedMs, {
          time: dtf.format(new Date(roundedMs)),
          rawTimestamp: roundedMs
        });
      }

      const group = timeGroupsMap.get(roundedMs);
      const suffix = f.room === 'room3' ? 'Room3' : f.room === 'room2' ? 'Room2' : 'Room1';

      channelFields.forEach(field => {
        const parsedVal = parseRobustFloat(f[field.key]);
        group[`${field.key}${suffix}`] = parsedVal;
      });
    }

    const sortedGroups = Array.from(timeGroupsMap.values()).sort((a, b) => a.rawTimestamp - b.rawTimestamp);

    const mappedData = {};
    channelFields.forEach(field => {
      mappedData[field.key] = sortedGroups.map(g => ({
        time: g.time,
        room1Value: g[`${field.key}Room1`] !== undefined ? g[`${field.key}Room1`] : null,
        room2Value: g[`${field.key}Room2`] !== undefined ? g[`${field.key}Room2`] : null,
        room3Value: g[`${field.key}Room3`] !== undefined ? g[`${field.key}Room3`] : null,
        isBoth: true
      }));
    });

    return mappedData;
  }
};

// Helpers to determine device capabilities
const isColdStorageDevice = (device) => {
  if (!device) return false;
  const type = (device.deviceType || device.type || '').toLowerCase();
  const name = (device.name || '').toLowerCase();
  if (type === 'itc_polyhouse') return false;
  return (
    type === 'cold_storage' ||
    type === 'multi_sensor' ||
    type === 'almora' ||
    type === 'almora2' ||
    type.includes('cold') ||
    type.includes('storage') ||
    name.includes('cold') ||
    name.includes('storage') ||
    name.includes('almora')
  );
};

const isOfficeControlDevice = (device) => {
  if (!device) return false;
  const type = (device.deviceType || device.type || '').toLowerCase();
  return type === 'office_control';
};

const isPolyhouseDevice = (device) => {
  if (!device) return false;
  const type = (device.deviceType || device.type || '').toLowerCase();
  return type === 'itc_polyhouse';
};

const DEFAULT_COLD_ROOM_NAMES = {
  S1: 'Cold Room 1',
  S2: 'Cold Room 2',
  S3: 'Cold Room 3',
  S4: 'Cold Room 4',
  S5: 'Cold Room 5',
  S6: 'Cold Room 6',
  S7: 'Greenhouse'
};

const COLD_ROOM_COLORS = {
  S1: { stroke: '#38bdf8', bg: 'bg-sky-500/10', border: 'border-sky-500/30', text: 'text-sky-400' },
  S2: { stroke: '#34d399', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400' },
  S3: { stroke: '#fbbf24', bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400' },
  S4: { stroke: '#a78bfa', bg: 'bg-purple-500/10', border: 'border-purple-500/30', text: 'text-purple-400' },
  S5: { stroke: '#f472b6', bg: 'bg-pink-500/10', border: 'border-pink-500/30', text: 'text-pink-400' },
  S6: { stroke: '#2dd4bf', bg: 'bg-teal-500/10', border: 'border-teal-500/30', text: 'text-teal-400' },
  S7: { stroke: '#a3e635', bg: 'bg-lime-500/10', border: 'border-lime-500/30', text: 'text-lime-400' }
};

const sanitizeFileName = (name) => {
  return String(name || 'Device').trim().replace(/[^a-z0-9_-]/gi, '_').replace(/_+/g, '_');
};

const normalizeMetricName = (name) => {
  if (!name) return '';
  return name.replace(/\bsoil\b/gi, 'Water');
};

const formatCSVTimestamp = (dateInput) => {
  if (!dateInput) return '';
  const d = new Date(dateInput);
  if (isNaN(d.getTime())) return String(dateInput);

  const pad = (n) => String(n).padStart(2, '0');
  const year = d.getFullYear();
  const month = pad(d.getMonth() + 1);
  const day = pad(d.getDate());
  let hours = d.getHours();
  const minutes = pad(d.getMinutes());
  const seconds = pad(d.getSeconds());
  const ampm = hours >= 12 ? 'PM' : 'AM';
  const hours12 = pad(hours % 12 || 12);

  return `${year}-${month}-${day} ${hours12}:${minutes}:${seconds} ${ampm}`;
};

// --- CSV EXPORT GENERATORS ---
const downloadCSV = (feeds, channelFields, filterLabel, deviceName = 'Device', isBoth = false, roomLabel = '') => {
  if (!feeds || feeds.length === 0) return;

  const headers = ['Timestamp'];
  if (isBoth) {
    headers.push('Room');
  }
  channelFields.forEach(f => {
    const cleanName = normalizeMetricName(f.name);
    const meta = getFieldMeta(cleanName);
    headers.push(`"${cleanName}${meta.unit ? ` (${meta.unit})` : ''}"`);
  });

  const headerLine = headers.join(',') + '\n';

  const rows = feeds.map((f) => {
    const readableTime = formatCSVTimestamp(f.created_at);
    const rowCells = [`"${readableTime}"`];
    if (isBoth) {
      rowCells.push(`"${f.room || 'room1'}"`);
    }
    channelFields.forEach(cfg => {
      rowCells.push(f[cfg.key] !== undefined && f[cfg.key] !== null ? f[cfg.key] : '');
    });
    return rowCells.join(',');
  }).join('\n');

  const blob = new Blob([headerLine + rows], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const deviceSlug = sanitizeFileName(deviceName);
  const roomSlug = roomLabel ? `_${sanitizeFileName(roomLabel)}` : '';
  a.href = url;
  a.download = `${deviceSlug}${roomSlug}_Analytics_${filterLabel}_${dateStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// Export clean single-room CSV (Timestamp, Room Code, Room Name, Temp °C, Humidity %)
const downloadColdRoomSingleCSV = (feeds, roomKey, roomName, filterLabel, deviceName = 'Device') => {
  if (!feeds || feeds.length === 0) return;
  const sIdx = parseInt(roomKey.replace('S', ''), 10);
  const tempKey = `field${sIdx}`;
  const humiKey = `field${sIdx + 7}`;

  const headers = ['Timestamp', 'Room ID', 'Room Name', 'Temperature (°C)', 'Humidity (%)'];
  const headerLine = headers.map(h => `"${h}"`).join(',') + '\n';

  const rows = feeds.map(f => {
    const readableTime = formatCSVTimestamp(f.created_at);
    const tempVal = f[tempKey] ?? f.multi_sensor_data?.[roomKey]?.temp ?? '';
    const humiVal = f[humiKey] ?? f.multi_sensor_data?.[roomKey]?.humi ?? '';
    return [
      `"${readableTime}"`,
      `"${roomKey}"`,
      `"${roomName}"`,
      tempVal !== '' && tempVal !== null && tempVal !== undefined ? parseRobustFloat(tempVal) : '',
      humiVal !== '' && humiVal !== null && humiVal !== undefined ? parseRobustFloat(humiVal) : ''
    ].join(',');
  }).join('\n');

  const blob = new Blob([headerLine + rows], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const devSlug = sanitizeFileName(deviceName);
  const roomSlug = sanitizeFileName(`${roomKey}_${roomName}`);
  a.href = url;
  a.download = `${devSlug}_${roomSlug}_Analytics_${filterLabel}_${dateStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// Export All Rooms Combined Matrix CSV (Wide Format: S1..S7)
const downloadColdRoomAllMatrixCSV = (feeds, coldRoomNames, filterLabel, deviceName = 'Device') => {
  if (!feeds || feeds.length === 0) return;

  const roomKeys = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'];
  const headers = ['Timestamp'];
  roomKeys.forEach(rk => {
    const rName = coldRoomNames[rk] || DEFAULT_COLD_ROOM_NAMES[rk] || rk;
    headers.push(`"${rk} - ${rName} Temp (°C)"`);
    headers.push(`"${rk} - ${rName} Humidity (%)"`);
  });

  const headerLine = headers.join(',') + '\n';

  const rows = feeds.map(f => {
    const readableTime = formatCSVTimestamp(f.created_at);
    const cells = [`"${readableTime}"`];
    roomKeys.forEach((rk, idx) => {
      const sNum = idx + 1;
      const tKey = `field${sNum}`;
      const hKey = `field${sNum + 7}`;
      const tempVal = f[tKey] ?? f.multi_sensor_data?.[rk]?.temp ?? '';
      const humiVal = f[hKey] ?? f.multi_sensor_data?.[rk]?.humi ?? '';
      cells.push(tempVal !== '' && tempVal !== null && tempVal !== undefined ? parseRobustFloat(tempVal) : '');
      cells.push(humiVal !== '' && humiVal !== null && humiVal !== undefined ? parseRobustFloat(humiVal) : '');
    });
    return cells.join(',');
  }).join('\n');

  const blob = new Blob([headerLine + rows], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const devSlug = sanitizeFileName(deviceName);
  a.href = url;
  a.download = `${devSlug}_AllRooms_ColdStorage_Analytics_${filterLabel}_${dateStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// Export All Rooms Row-by-Row Long Format CSV (Ideal for Excel pivot analysis)
const downloadColdRoomLongFormatCSV = (feeds, coldRoomNames, filterLabel, deviceName = 'Device') => {
  if (!feeds || feeds.length === 0) return;

  const roomKeys = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'];
  const headers = ['Timestamp', 'Room Code', 'Room Name', 'Temperature (°C)', 'Humidity (%)'];
  const headerLine = headers.map(h => `"${h}"`).join(',') + '\n';

  const rows = [];
  feeds.forEach(f => {
    const readableTime = formatCSVTimestamp(f.created_at);
    roomKeys.forEach((rk, idx) => {
      const sNum = idx + 1;
      const tKey = `field${sNum}`;
      const hKey = `field${sNum + 7}`;
      const tempVal = f[tKey] ?? f.multi_sensor_data?.[rk]?.temp ?? '';
      const humiVal = f[hKey] ?? f.multi_sensor_data?.[rk]?.humi ?? '';
      const rName = coldRoomNames[rk] || DEFAULT_COLD_ROOM_NAMES[rk] || rk;
      if ((tempVal !== '' && tempVal !== null && tempVal !== undefined) || (humiVal !== '' && humiVal !== null && humiVal !== undefined)) {
        rows.push([
          `"${readableTime}"`,
          `"${rk}"`,
          `"${rName}"`,
          tempVal !== '' && tempVal !== null && tempVal !== undefined ? parseRobustFloat(tempVal) : '',
          humiVal !== '' && humiVal !== null && humiVal !== undefined ? parseRobustFloat(humiVal) : ''
        ].join(','));
      }
    });
  });

  const blob = new Blob([headerLine + rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const devSlug = sanitizeFileName(deviceName);
  a.href = url;
  a.download = `${devSlug}_AllRooms_RowWise_Analytics_${filterLabel}_${dateStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

const downloadJSON = (feeds, channelFields, filterLabel, deviceName = 'Device', isBoth = false, roomLabel = '') => {
  if (!feeds || feeds.length === 0) return;
  const data = feeds.map((f) => {
    const obj = { timestamp: formatCSVTimestamp(f.created_at), rawTimestamp: f.created_at };
    if (isBoth) {
      obj.room = f.room || 'room1';
    }
    channelFields.forEach(cfg => {
      const cleanName = normalizeMetricName(cfg.name);
      obj[cleanName] = parseRobustFloat(f[cfg.key]);
    });
    return obj;
  });
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const deviceSlug = sanitizeFileName(deviceName);
  const roomSlug = roomLabel ? `_${sanitizeFileName(roomLabel)}` : '';
  a.href = url;
  a.download = `${deviceSlug}${roomSlug}_Analytics_${filterLabel}_${dateStr}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// --- SETPOINTS SCHEDULE & AUDIT EXPORTERS ---

// 1. Export Single Stage Setpoints Schedule CSV
const downloadSingleStageSetpointsCSV = (roomKey, roomName, stageKey, stageData, roomSetpoints, deviceName = 'Device') => {
  if (!stageData) return;
  const progName = roomSetpoints?.program_name || `${roomName} Program`;
  const cropName = roomSetpoints?.crop_name || '';
  const mode = roomSetpoints?.mode || 'SCHEDULED';

  const headers = [
    'Room Code',
    'Room Name',
    'Program Name',
    'Crop Name',
    'Schedule Mode',
    'Stage Code',
    'Stage Name',
    'Start Date',
    'End Date',
    'Stage Enabled',
    'Photoperiod On',
    'Photoperiod Off',
    'Lighting Enabled',
    'Slot ID',
    'Slot Name',
    'Slot Time Window',
    'Target Temp (°C)',
    'Min Temp (°C)',
    'Max Temp (°C)',
    'Target Humidity (%)',
    'Min Humidity (%)',
    'Max Humidity (%)'
  ];

  const rows = (stageData.time_slots || []).map((slot, sIdx) => [
    `"${roomKey}"`,
    `"${roomName}"`,
    `"${progName}"`,
    `"${cropName}"`,
    `"${mode}"`,
    `"${stageKey}"`,
    `"${stageData.name || stageKey}"`,
    `"${stageData.start_date || ''}"`,
    `"${stageData.end_date || ''}"`,
    stageData.enabled !== false ? 'YES' : 'NO',
    `"${stageData.photoperiod_on || '06:00 AM'}"`,
    `"${stageData.photoperiod_off || '08:00 PM'}"`,
    stageData.lighting_enabled !== false ? 'YES' : 'NO',
    slot.id || (sIdx + 1),
    `"${slot.name || `Slot ${sIdx + 1}`}"`,
    `"${slot.start || ''} - ${slot.stop || ''}"`,
    slot.t_set !== undefined ? slot.t_set : '',
    slot.t_min !== undefined ? slot.t_min : '',
    slot.t_max !== undefined ? slot.t_max : '',
    slot.h_set !== undefined ? slot.h_set : '',
    slot.h_min !== undefined ? slot.h_min : '',
    slot.h_max !== undefined ? slot.h_max : ''
  ].join(','));

  const csvContent = headers.map(h => `"${h}"`).join(',') + '\n' + rows.join('\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const devSlug = sanitizeFileName(deviceName);
  const stageSlug = sanitizeFileName(`${stageKey}_${stageData.name || ''}`);
  a.href = url;
  a.download = `${devSlug}_${roomKey}_${stageSlug}_Setpoints_${dateStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// 2. Export All 10 Stages for a Single Room
const downloadRoomSetpointsCSV = (roomKey, roomName, roomSetpoints, deviceName = 'Device') => {
  const stages = roomSetpoints?.settings || generateDefaultAlmoraSchedule(roomKey).settings || {};
  const progName = roomSetpoints?.program_name || `${roomName} Program`;
  const cropName = roomSetpoints?.crop_name || '';
  const mode = roomSetpoints?.mode || 'SCHEDULED';

  const headers = [
    'Room Code',
    'Room Name',
    'Program Name',
    'Crop Name',
    'Schedule Mode',
    'Stage Code',
    'Stage Name',
    'Start Date',
    'End Date',
    'Stage Enabled',
    'Photoperiod On',
    'Photoperiod Off',
    'Lighting Enabled',
    'Slot ID',
    'Slot Name',
    'Slot Time Window',
    'Target Temp (°C)',
    'Min Temp (°C)',
    'Max Temp (°C)',
    'Target Humidity (%)',
    'Min Humidity (%)',
    'Max Humidity (%)'
  ];

  const rows = [];
  ALL_SETTING_KEYS.forEach(stageKey => {
    const st = stages[stageKey];
    if (!st) return;
    const slots = st.time_slots || [];
    slots.forEach((slot, sIdx) => {
      rows.push([
        `"${roomKey}"`,
        `"${roomName}"`,
        `"${progName}"`,
        `"${cropName}"`,
        `"${mode}"`,
        `"${stageKey}"`,
        `"${st.name || stageKey}"`,
        `"${st.start_date || ''}"`,
        `"${st.end_date || ''}"`,
        st.enabled !== false ? 'YES' : 'NO',
        `"${st.photoperiod_on || '06:00 AM'}"`,
        `"${st.photoperiod_off || '08:00 PM'}"`,
        st.lighting_enabled !== false ? 'YES' : 'NO',
        slot.id || (sIdx + 1),
        `"${slot.name || `Slot ${sIdx + 1}`}"`,
        `"${slot.start || ''} - ${slot.stop || ''}"`,
        slot.t_set !== undefined ? slot.t_set : '',
        slot.t_min !== undefined ? slot.t_min : '',
        slot.t_max !== undefined ? slot.t_max : '',
        slot.h_set !== undefined ? slot.h_set : '',
        slot.h_min !== undefined ? slot.h_min : '',
        slot.h_max !== undefined ? slot.h_max : ''
      ].join(','));
    });
  });

  const csvContent = headers.map(h => `"${h}"`).join(',') + '\n' + rows.join('\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const devSlug = sanitizeFileName(deviceName);
  const roomSlug = sanitizeFileName(`${roomKey}_${roomName}`);
  a.href = url;
  a.download = `${devSlug}_${roomSlug}_All_Stages_Setpoints_${dateStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// 3. Export All 7 Chambers Master Setpoints Schedule
const downloadAllRoomsSetpointsCSV = (allSetpointsDict, coldRoomNames, deviceName = 'Device') => {
  const roomKeys = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'];
  const headers = [
    'Room Code',
    'Room Name',
    'Program Name',
    'Crop Name',
    'Schedule Mode',
    'Stage Code',
    'Stage Name',
    'Start Date',
    'End Date',
    'Stage Enabled',
    'Photoperiod On',
    'Photoperiod Off',
    'Lighting Enabled',
    'Slot ID',
    'Slot Name',
    'Slot Time Window',
    'Target Temp (°C)',
    'Min Temp (°C)',
    'Max Temp (°C)',
    'Target Humidity (%)',
    'Min Humidity (%)',
    'Max Humidity (%)'
  ];

  const rows = [];
  roomKeys.forEach(rk => {
    const rName = coldRoomNames[rk] || DEFAULT_COLD_ROOM_NAMES[rk] || rk;
    const rSetps = (allSetpointsDict && allSetpointsDict[rk]) ? allSetpointsDict[rk] : generateDefaultAlmoraSchedule(rk);
    const stages = rSetps?.settings || {};
    const progName = rSetps?.program_name || `${rName} Program`;
    const cropName = rSetps?.crop_name || '';
    const mode = rSetps?.mode || 'SCHEDULED';

    ALL_SETTING_KEYS.forEach(stageKey => {
      const st = stages[stageKey];
      if (!st) return;
      const slots = st.time_slots || [];
      slots.forEach((slot, sIdx) => {
        rows.push([
          `"${rk}"`,
          `"${rName}"`,
          `"${progName}"`,
          `"${cropName}"`,
          `"${mode}"`,
          `"${stageKey}"`,
          `"${st.name || stageKey}"`,
          `"${st.start_date || ''}"`,
          `"${st.end_date || ''}"`,
          st.enabled !== false ? 'YES' : 'NO',
          `"${st.photoperiod_on || '06:00 AM'}"`,
          `"${st.photoperiod_off || '08:00 PM'}"`,
          st.lighting_enabled !== false ? 'YES' : 'NO',
          slot.id || (sIdx + 1),
          `"${slot.name || `Slot ${sIdx + 1}`}"`,
          `"${slot.start || ''} - ${slot.stop || ''}"`,
          slot.t_set !== undefined ? slot.t_set : '',
          slot.t_min !== undefined ? slot.t_min : '',
          slot.t_max !== undefined ? slot.t_max : '',
          slot.h_set !== undefined ? slot.h_set : '',
          slot.h_min !== undefined ? slot.h_min : '',
          slot.h_max !== undefined ? slot.h_max : ''
        ].join(','));
      });
    });
  });

  const csvContent = headers.map(h => `"${h}"`).join(',') + '\n' + rows.join('\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const devSlug = sanitizeFileName(deviceName);
  a.href = url;
  a.download = `${devSlug}_All_7_Chambers_Master_Setpoints_${dateStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// 4. Export Target vs Actual Variance & Compliance Audit CSV (Single Room)
const downloadTargetVsActualComplianceCSV = (feeds, roomKey, roomName, roomSetpoints, filterLabel, deviceName = 'Device') => {
  if (!feeds || feeds.length === 0) return;
  const stagesDict = roomSetpoints?.settings || generateDefaultAlmoraSchedule(roomKey).settings || {};
  const progName = roomSetpoints?.program_name || `${roomName} Program`;
  const activeSetting = roomSetpoints?.active_setting || 'Setting A';

  const sIdx = parseInt(roomKey.replace('S', ''), 10);
  const tempKey = `field${sIdx}`;
  const humiKey = `field${sIdx + 7}`;

  const headers = [
    'Timestamp',
    'Room ID',
    'Room Name',
    'Program Name',
    'Active Stage Code',
    'Active Stage Name',
    'Active Slot Name',
    'Slot Time Window',
    'Actual Temp (°C)',
    'Target Temp (°C)',
    'Min Allowed Temp (°C)',
    'Max Allowed Temp (°C)',
    'Temp Delta (°C)',
    'Temp Compliance Status',
    'Actual Humidity (%)',
    'Target Humidity (%)',
    'Min Allowed Humidity (%)',
    'Max Allowed Humidity (%)',
    'Humidity Delta (%)',
    'Humidity Compliance Status',
    'Photoperiod State'
  ];

  const rows = [];
  feeds.forEach(f => {
    const rawDate = f.created_at || f.timestamp || f.time;
    const d = new Date(rawDate);
    const readableTime = formatCSVTimestamp(rawDate);

    const tempVal = f[tempKey] ?? f.multi_sensor_data?.[roomKey]?.temp ?? null;
    const humiVal = f[humiKey] ?? f.multi_sensor_data?.[roomKey]?.humi ?? null;
    const actT = parseRobustFloat(tempVal);
    const actH = parseRobustFloat(humiVal);

    if (actT === null && actH === null) return;

    const stage = getMatchingStage(stagesDict, d, activeSetting);
    const stageKey = stage?.key || activeSetting;
    const stageName = stage?.name || stageKey;
    const slot = getMatchingTimeSlot(stage, d);
    const slotName = slot?.name || 'Standard Slot';
    const slotWindow = slot ? `${slot.start || ''} - ${slot.stop || ''}` : '';

    const targetT = slot?.t_set !== undefined ? Number(slot.t_set) : null;
    const minT = slot?.t_min !== undefined ? Number(slot.t_min) : (targetT !== null ? targetT - 1 : null);
    const maxT = slot?.t_max !== undefined ? Number(slot.t_max) : (targetT !== null ? targetT + 1 : null);

    const targetH = slot?.h_set !== undefined ? Number(slot.h_set) : null;
    const minH = slot?.h_min !== undefined ? Number(slot.h_min) : (targetH !== null ? targetH - 5 : null);
    const maxH = slot?.h_max !== undefined ? Number(slot.h_max) : (targetH !== null ? targetH + 5 : null);

    let tDelta = '';
    let tStatus = 'NO_DATA';
    if (actT !== null && targetT !== null) {
      tDelta = +(actT - targetT).toFixed(2);
      if (minT !== null && maxT !== null) {
        if (actT >= minT && actT <= maxT) tStatus = 'OPTIMAL_IN_BAND';
        else if (actT > maxT) tStatus = 'ABOVE_MAX_WARM';
        else tStatus = 'BELOW_MIN_COLD';
      } else {
        tStatus = Math.abs(actT - targetT) <= 1.0 ? 'OPTIMAL' : actT > targetT ? 'WARM' : 'COLD';
      }
    }

    let hDelta = '';
    let hStatus = 'NO_DATA';
    if (actH !== null && targetH !== null) {
      hDelta = +(actH - targetH).toFixed(2);
      if (minH !== null && maxH !== null) {
        if (actH >= minH && actH <= maxH) hStatus = 'OPTIMAL_IN_BAND';
        else if (actH > maxH) hStatus = 'ABOVE_MAX_HUMID';
        else hStatus = 'BELOW_MIN_DRY';
      } else {
        hStatus = Math.abs(actH - targetH) <= 5.0 ? 'OPTIMAL' : actH > targetH ? 'HUMID' : 'DRY';
      }
    }

    let photoState = 'UNKNOWN';
    if (stage) {
      const curMin = !isNaN(d.getTime()) ? (d.getHours() * 60 + d.getMinutes()) : 0;
      const onMin = timeToMinutes(stage.photoperiod_on || '06:00 AM');
      const offMin = timeToMinutes(stage.photoperiod_off || '08:00 PM');
      if (offMin >= onMin) {
        photoState = (curMin >= onMin && curMin <= offMin) ? 'LIGHT_DAY' : 'DARK_NIGHT';
      } else {
        photoState = (curMin >= onMin || curMin <= offMin) ? 'LIGHT_DAY' : 'DARK_NIGHT';
      }
    }

    rows.push([
      `"${readableTime}"`,
      `"${roomKey}"`,
      `"${roomName}"`,
      `"${progName}"`,
      `"${stageKey}"`,
      `"${stageName}"`,
      `"${slotName}"`,
      `"${slotWindow}"`,
      actT !== null ? actT : '',
      targetT !== null ? targetT : '',
      minT !== null ? minT : '',
      maxT !== null ? maxT : '',
      tDelta !== '' ? tDelta : '',
      `"${tStatus}"`,
      actH !== null ? actH : '',
      targetH !== null ? targetH : '',
      minH !== null ? minH : '',
      maxH !== null ? maxH : '',
      hDelta !== '' ? hDelta : '',
      `"${hStatus}"`,
      `"${photoState}"`
    ].join(','));
  });

  const csvContent = headers.map(h => `"${h}"`).join(',') + '\n' + rows.join('\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const devSlug = sanitizeFileName(deviceName);
  const roomSlug = sanitizeFileName(`${roomKey}_${roomName}`);
  a.href = url;
  a.download = `${devSlug}_${roomSlug}_Target_vs_Actual_Audit_${filterLabel}_${dateStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// 5. Export Target vs Actual Variance Audit for All 7 Chambers Combined
const downloadAllRoomsTargetVsActualComplianceCSV = (feeds, allSetpointsDict, coldRoomNames, filterLabel, deviceName = 'Device') => {
  if (!feeds || feeds.length === 0) return;
  const roomKeys = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'];

  const headers = [
    'Timestamp',
    'Room ID',
    'Room Name',
    'Program Name',
    'Active Stage Code',
    'Active Stage Name',
    'Active Slot Name',
    'Slot Time Window',
    'Actual Temp (°C)',
    'Target Temp (°C)',
    'Min Allowed Temp (°C)',
    'Max Allowed Temp (°C)',
    'Temp Delta (°C)',
    'Temp Compliance Status',
    'Actual Humidity (%)',
    'Target Humidity (%)',
    'Min Allowed Humidity (%)',
    'Max Allowed Humidity (%)',
    'Humidity Delta (%)',
    'Humidity Compliance Status',
    'Photoperiod State'
  ];

  const rows = [];
  feeds.forEach(f => {
    const rawDate = f.created_at || f.timestamp || f.time;
    const d = new Date(rawDate);
    const readableTime = formatCSVTimestamp(rawDate);

    roomKeys.forEach((rk, idx) => {
      const sNum = idx + 1;
      const tKey = `field${sNum}`;
      const hKey = `field${sNum + 7}`;
      const tempVal = f[tKey] ?? f.multi_sensor_data?.[rk]?.temp ?? null;
      const humiVal = f[hKey] ?? f.multi_sensor_data?.[rk]?.humi ?? null;
      const actT = parseRobustFloat(tempVal);
      const actH = parseRobustFloat(humiVal);

      if (actT === null && actH === null) return;

      const rName = coldRoomNames[rk] || DEFAULT_COLD_ROOM_NAMES[rk] || rk;
      const rSetps = (allSetpointsDict && allSetpointsDict[rk]) ? allSetpointsDict[rk] : generateDefaultAlmoraSchedule(rk);
      const stagesDict = rSetps?.settings || {};
      const progName = rSetps?.program_name || `${rName} Program`;
      const activeSetting = rSetps?.active_setting || 'Setting A';

      const stage = getMatchingStage(stagesDict, d, activeSetting);
      const stageKey = stage?.key || activeSetting;
      const stageName = stage?.name || stageKey;
      const slot = getMatchingTimeSlot(stage, d);
      const slotName = slot?.name || 'Standard Slot';
      const slotWindow = slot ? `${slot.start || ''} - ${slot.stop || ''}` : '';

      const targetT = slot?.t_set !== undefined ? Number(slot.t_set) : null;
      const minT = slot?.t_min !== undefined ? Number(slot.t_min) : (targetT !== null ? targetT - 1 : null);
      const maxT = slot?.t_max !== undefined ? Number(slot.t_max) : (targetT !== null ? targetT + 1 : null);

      const targetH = slot?.h_set !== undefined ? Number(slot.h_set) : null;
      const minH = slot?.h_min !== undefined ? Number(slot.h_min) : (targetH !== null ? targetH - 5 : null);
      const maxH = slot?.h_max !== undefined ? Number(slot.h_max) : (targetH !== null ? targetH + 5 : null);

      let tDelta = '';
      let tStatus = 'NO_DATA';
      if (actT !== null && targetT !== null) {
        tDelta = +(actT - targetT).toFixed(2);
        if (minT !== null && maxT !== null) {
          if (actT >= minT && actT <= maxT) tStatus = 'OPTIMAL_IN_BAND';
          else if (actT > maxT) tStatus = 'ABOVE_MAX_WARM';
          else tStatus = 'BELOW_MIN_COLD';
        } else {
          tStatus = Math.abs(actT - targetT) <= 1.0 ? 'OPTIMAL' : actT > targetT ? 'WARM' : 'COLD';
        }
      }

      let hDelta = '';
      let hStatus = 'NO_DATA';
      if (actH !== null && targetH !== null) {
        hDelta = +(actH - targetH).toFixed(2);
        if (minH !== null && maxH !== null) {
          if (actH >= minH && actH <= maxH) hStatus = 'OPTIMAL_IN_BAND';
          else if (actH > maxH) hStatus = 'ABOVE_MAX_HUMID';
          else hStatus = 'BELOW_MIN_DRY';
        } else {
          hStatus = Math.abs(actH - targetH) <= 5.0 ? 'OPTIMAL' : actH > targetH ? 'HUMID' : 'DRY';
        }
      }

      let photoState = 'UNKNOWN';
      if (stage) {
        const curMin = !isNaN(d.getTime()) ? (d.getHours() * 60 + d.getMinutes()) : 0;
        const onMin = timeToMinutes(stage.photoperiod_on || '06:00 AM');
        const offMin = timeToMinutes(stage.photoperiod_off || '08:00 PM');
        if (offMin >= onMin) {
          photoState = (curMin >= onMin && curMin <= offMin) ? 'LIGHT_DAY' : 'DARK_NIGHT';
        } else {
          photoState = (curMin >= onMin || curMin <= offMin) ? 'LIGHT_DAY' : 'DARK_NIGHT';
        }
      }

      rows.push([
        `"${readableTime}"`,
        `"${rk}"`,
        `"${rName}"`,
        `"${progName}"`,
        `"${stageKey}"`,
        `"${stageName}"`,
        `"${slotName}"`,
        `"${slotWindow}"`,
        actT !== null ? actT : '',
        targetT !== null ? targetT : '',
        minT !== null ? minT : '',
        maxT !== null ? maxT : '',
        tDelta !== '' ? tDelta : '',
        `"${tStatus}"`,
        actH !== null ? actH : '',
        targetH !== null ? targetH : '',
        minH !== null ? minH : '',
        maxH !== null ? maxH : '',
        hDelta !== '' ? hDelta : '',
        `"${hStatus}"`,
        `"${photoState}"`
      ].join(','));
    });
  });

  const csvContent = headers.map(h => `"${h}"`).join(',') + '\n' + rows.join('\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const devSlug = sanitizeFileName(deviceName);
  a.href = url;
  a.download = `${devSlug}_All_7_Chambers_Target_vs_Actual_Audit_${filterLabel}_${dateStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// 6. Export Full JSON Configuration Snapshot
const downloadSetpointsJSON = (data, filename = 'Setpoints_Schedule.json') => {
  const jsonStr = JSON.stringify(data, null, 2);
  const blob = new Blob([jsonStr], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// Custom Multi-Room Synchronized Chart Tooltip
const MultiRoomTooltip = ({ active, payload, label, unit = '°C', coldRoomNames }) => {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-xl border border-slate-700/80 bg-slate-900/95 p-3 shadow-2xl backdrop-blur-md space-y-1.5 min-w-[200px]">
        <p className="text-[11px] font-mono text-slate-400 border-b border-slate-800 pb-1 flex items-center justify-between">
          <span>{label}</span>
          <span className="text-slate-500 font-normal">({unit})</span>
        </p>
        <div className="space-y-1 pt-0.5">
          {payload.map((p, idx) => {
            const rKey = p.dataKey?.replace('_Temp', '')?.replace('_Humi', '');
            const rName = coldRoomNames?.[rKey] || DEFAULT_COLD_ROOM_NAMES[rKey] || rKey;
            return (
              <div key={idx} className="flex items-center justify-between text-xs gap-3">
                <div className="flex items-center gap-1.5 truncate">
                  <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: p.stroke || p.color }} />
                  <span className="font-semibold text-slate-200 truncate">{rKey} - {rName}:</span>
                </div>
                <span className="font-mono font-bold" style={{ color: p.stroke || p.color }}>
                  {p.value !== null && p.value !== undefined ? `${p.value}${unit}` : '--'}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }
  return null;
};

const AnalyticsPage = () => {
  const queryParams = new URLSearchParams(window.location.search);
  const urlDeviceId = queryParams.get('deviceId') || queryParams.get('device');
  const urlRoom = queryParams.get('room');

  const [filter, setFilter] = useState('today');
  const [durationVal, setDurationVal] = useState('1');
  const [durationUnit, setDurationUnit] = useState('hours');
  const [customStartDate, setCustomStartDate] = useState('');
  const [customEndDate, setCustomEndDate] = useState('');
  const [rawFeeds, setRawFeeds] = useState([]);
  const [totalDbPoints, setTotalDbPoints] = useState(0);
  const [totalCollectionDocs, setTotalCollectionDocs] = useState(0);
  const [channelFields, setChannelFields] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showDownloadMenu, setShowDownloadMenu] = useState(false);
  const [isExporting, setIsExporting] = useState(false);

  const [allDevices, setAllDevices] = useState([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [selectedRoom, setSelectedRoom] = useState(urlRoom || 'all');
  const [devicesLoading, setDevicesLoading] = useState(true);

  // Setpoints & Stage History Snapshot State
  const [allSetpoints, setAllSetpoints] = useState({});
  const [selectedStageKey, setSelectedStageKey] = useState(null);
  const [showSetpointsDetails, setShowSetpointsDetails] = useState(true);
  const [showSetpointsDropdown, setShowSetpointsDropdown] = useState(false);
  const [showSetpointsExportModal, setShowSetpointsExportModal] = useState(false);
  const [exportModalRoom, setExportModalRoom] = useState('S1');
  const [exportModalType, setExportModalType] = useState('audit');

  // Cold Room View Mode: 'matrix' (Overview cards & multi-room trend) | 'individual' (Each sensor card/chart)
  const [coldOverviewMode, setColdOverviewMode] = useState('matrix');

  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // Fetch devices with analytics credentials
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const contentType = res.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
          throw new Error("Received non-JSON response from server (Backend might be down)");
        }
        const data = await res.json();
        if (data.success && Array.isArray(data.data)) {
          setAllDevices(data.data);
          let initialDevId = '';
          if (urlDeviceId) {
            const matched = data.data.find(d => d._id === urlDeviceId || (d.mqttId && d.mqttId.toLowerCase() === urlDeviceId.toLowerCase()));
            if (matched) initialDevId = matched._id;
          }
          if (!initialDevId && data.data.length > 0) {
            initialDevId = data.data[0]._id;
          }
          if (initialDevId && !selectedDeviceId) {
            setSelectedDeviceId(initialDevId);
            const devObj = data.data.find(d => d._id === initialDevId);
            if (isColdStorageDevice(devObj) || isPolyhouseDevice(devObj)) {
              setSelectedRoom(urlRoom || 'all');
            } else if (isOfficeControlDevice(devObj)) {
              setSelectedRoom(urlRoom || 'room1');
            } else {
              setSelectedRoom('');
            }
          }
        }
      } catch (err) {
        console.error('Failed to fetch devices', err);
      } finally {
        setDevicesLoading(false);
      }
    };
    fetchDevices();
  }, [token, API_BASE, urlDeviceId, urlRoom]);

  const selectedDevice = allDevices.find((d) => d._id === selectedDeviceId);
  const isCold = isColdStorageDevice(selectedDevice);
  const isOffice = isOfficeControlDevice(selectedDevice);
  const isPoly = isPolyhouseDevice(selectedDevice);

  // Dynamic sensor / room names for Cold Storage devices
  const coldRoomNames = useMemo(() => {
    const custom = selectedDevice?.config?.sensor_names ||
      selectedDevice?.system_config?.sensor_names ||
      selectedDevice?.sensor_setpoints?.system_config?.sensor_names ||
      selectedDevice?.sensor_names || {};

    return {
      S1: custom.S1 || DEFAULT_COLD_ROOM_NAMES.S1,
      S2: custom.S2 || DEFAULT_COLD_ROOM_NAMES.S2,
      S3: custom.S3 || DEFAULT_COLD_ROOM_NAMES.S3,
      S4: custom.S4 || DEFAULT_COLD_ROOM_NAMES.S4,
      S5: custom.S5 || DEFAULT_COLD_ROOM_NAMES.S5,
      S6: custom.S6 || DEFAULT_COLD_ROOM_NAMES.S6,
      S7: custom.S7 || DEFAULT_COLD_ROOM_NAMES.S7,
    };
  }, [selectedDevice]);

  // Fetch device setpoints from backend
  useEffect(() => {
    if (!selectedDeviceId || !isCold) return;
    const fetchSetpoints = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/devices/${selectedDeviceId}/setpoints-json`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const json = await res.json();
        if (json.success && json.data) {
          setAllSetpoints(json.data);
        }
      } catch (e) {
        console.error('Error fetching setpoints:', e);
      }
    };
    fetchSetpoints();
  }, [selectedDeviceId, isCold, API_BASE, token]);

  const getRoomSetpoints = useCallback((rKey) => {
    if (allSetpoints && allSetpoints[rKey] && typeof allSetpoints[rKey] === 'object') {
      return allSetpoints[rKey];
    }
    if (selectedDevice?.settings && selectedDevice.settings[rKey]) {
      return selectedDevice.settings[rKey];
    }
    return generateDefaultAlmoraSchedule(rKey);
  }, [allSetpoints, selectedDevice]);

  // Handle device change
  const handleDeviceChange = (devId) => {
    setSelectedDeviceId(devId);
    setSelectedStageKey(null);
    const targetDev = allDevices.find(d => d._id === devId);
    if (isColdStorageDevice(targetDev) || isPolyhouseDevice(targetDev)) {
      setSelectedRoom('all');
    } else if (isOfficeControlDevice(targetDev)) {
      setSelectedRoom('room1');
    } else {
      setSelectedRoom('');
    }
  };

  const getSelectedRoomLabel = useCallback(() => {
    if (isOffice) {
      if (selectedRoom === 'both' || selectedRoom === 'all') return 'All Rooms';
      if (selectedRoom === 'room1') return 'Room 1';
      if (selectedRoom === 'room2') return 'Room 2';
      if (selectedRoom === 'room3') return 'Room 3';
      return selectedRoom;
    }
    if (isCold) {
      if (!selectedRoom || selectedRoom === 'all' || selectedRoom === 'both') return 'All Rooms Overview';
      return `${coldRoomNames[selectedRoom] || selectedRoom} (${selectedRoom})`;
    }
    if (isPoly) {
      if (!selectedRoom || selectedRoom === 'all' || selectedRoom === 'both') return 'All Polyhouse Zones (PH-01 to PH-06)';
      return `${selectedRoom} Zone`;
    }
    return '';
  }, [isOffice, isCold, isPoly, selectedRoom, coldRoomNames]);

  const fetchData = useCallback(async (isRefresh = false) => {
    if (!selectedDeviceId) {
      setRawFeeds([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const { start, end } = getDateRange(filter, customStartDate, customEndDate, durationVal, durationUnit);
      let roomParam = '';
      if (isOffice) {
        roomParam = `&room=${selectedRoom || 'room1'}`;
      } else if (isCold || isPoly) {
        roomParam = `&room=${selectedRoom || 'all'}`;
      }

      const refreshParam = isRefresh ? '&refresh=true' : '';
      const url = `${API_BASE}/api/devices/${selectedDeviceId}/analytics?start=${start.toISOString()}&end=${end.toISOString()}&filter=${filter}&downsample=true&sampleLimit=1500${roomParam}${refreshParam}`;

      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(url, { headers });
      if (res.status === 404) {
        throw new Error("Analytics data not found for this device (404).");
      }
      if (!res.ok) throw new Error(`API responded with ${res.status}`);
      const result = await res.json();

      if (!result.success) {
        throw new Error(result.message || 'Server failed to return analytics');
      }

      const exactFeeds = result.feeds || [];
      const cFields = [];

      for (let i = 1; i <= 17; i++) {
        const key = `field${i}`;
        const rawFieldName = result.channel?.[key];
        if (!rawFieldName) continue;
        const fieldName = normalizeMetricName(rawFieldName);

        // For cold storage devices, strictly enforce ONLY Temp, Humidity, and CO2 (no Water EC, pH, ORP, etc.)
        if (isCold) {
          const lower = fieldName.toLowerCase();
          const isHydro = (
            lower.includes('water') ||
            lower.includes('soil') ||
            lower.includes('ec') ||
            lower.includes('ph') ||
            lower.includes('orp') ||
            lower.includes('moisture') ||
            lower.includes('vpd') ||
            lower.includes('dli') ||
            lower.includes('dissolved oxygen') ||
            lower.includes('ppfd') ||
            lower.includes('nitrogen') ||
            lower.includes('phosphorus') ||
            lower.includes('potassium')
          );
          const isColdValid = (
            lower.includes('temp') ||
            lower.includes('humidity') ||
            lower.includes('humi') ||
            lower.includes('co2')
          );

          if (isHydro || !isColdValid) continue;

          // If a single room (e.g. S1..S7) is selected, only accept fields for that room + CO2
          if (selectedRoom && selectedRoom !== 'all' && selectedRoom !== 'both') {
            const sNum = parseInt(selectedRoom.replace('S', ''), 10);
            const isTargetTemp = key === `field${sNum}`;
            const isTargetHumi = key === `field${sNum + 7}`;
            const isCo2 = key === 'field15' || lower.includes('co2');
            if (!isTargetTemp && !isTargetHumi && !isCo2) continue;
          }
        }

        const hasData = exactFeeds.some(f => f[key] != null && f[key] !== '' && f[key] !== 'null' && f[key] !== 'undefined');
        if (hasData) {
          cFields.push({ key, name: fieldName });
        }
      }
      setChannelFields(cFields);
      setRawFeeds(exactFeeds);
      setTotalDbPoints(result.totalFeeds !== undefined ? result.totalFeeds : (result.totalDbPoints || exactFeeds.length));
      setTotalCollectionDocs(result.totalCollectionDocs || 0);
    } catch (err) {
      console.error('Analytics API error:', err);
      setError(err.message || 'Failed to fetch data');
      setRawFeeds([]);
      setTotalDbPoints(0);
      setTotalCollectionDocs(0);
      setChannelFields([]);
    } finally {
      setLoading(false);
    }
  }, [filter, customStartDate, customEndDate, durationVal, durationUnit, selectedDeviceId, token, API_BASE, selectedRoom, isOffice, isCold, isPoly]);

  // Server-side Full Export Handler
  const handleFullExport = async (format = 'csv') => {
    if (!selectedDeviceId) return;
    setIsExporting(true);
    setShowDownloadMenu(false);
    try {
      const { start, end } = getDateRange(filter, customStartDate, customEndDate, durationVal, durationUnit);
      let roomParam = '';
      if (isOffice) {
        roomParam = `&room=${selectedRoom || 'room1'}`;
      } else if (isCold || isPoly) {
        roomParam = `&room=${selectedRoom || 'all'}`;
      }

      const exportLabel = filterLabel;
      const deviceSlug = sanitizeFileName(selectedDevice?.name || 'Device');
      const roomLabel = getSelectedRoomLabel();
      const roomSlug = roomLabel ? `_${sanitizeFileName(roomLabel)}` : '';
      const dateStr = new Date().toISOString().split('T')[0];
      const filename = `${deviceSlug}${roomSlug}_Analytics_${exportLabel}_${dateStr}.${format}`;

      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Kolkata';
      const url = `${API_BASE}/api/devices/${selectedDeviceId}/analytics?start=${start.toISOString()}&end=${end.toISOString()}&filter=${filter}&export=true&format=${format}&timezone=${encodeURIComponent(tz)}${roomParam}`;

      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(url, { headers });
      if (!res.ok) throw new Error(`Export request failed with status ${res.status}`);

      const blob = await res.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(downloadUrl);
    } catch (err) {
      console.error('Export error, falling back to loaded feeds:', err);
      const roomLabel = getSelectedRoomLabel();
      if (format === 'csv') {
        if (isCold) {
          if (!selectedRoom || selectedRoom === 'all') {
            downloadColdRoomAllMatrixCSV(rawFeeds, coldRoomNames, filterLabel, selectedDevice?.name || 'Device');
          } else {
            downloadColdRoomSingleCSV(rawFeeds, selectedRoom, coldRoomNames[selectedRoom] || selectedRoom, filterLabel, selectedDevice?.name || 'Device');
          }
        } else {
          downloadCSV(rawFeeds, channelFields, filterLabel, selectedDevice?.name || 'Device', selectedRoom === 'both', roomLabel);
        }
      } else {
        downloadJSON(rawFeeds, channelFields, filterLabel, selectedDevice?.name || 'Device', selectedRoom === 'both', roomLabel);
      }
    } finally {
      setIsExporting(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Build standard chart data
  const chartData = useMemo(() => mapFeedsToCharts(rawFeeds, filter, channelFields, selectedRoom === 'both', durationUnit), [rawFeeds, filter, channelFields, selectedRoom, durationUnit]);

  // --- COLD STORAGE ROOM-WISE DEEP ANALYSIS AGGREGATIONS ---
  const roomWiseAnalysis = useMemo(() => {
    if (!isCold || !rawFeeds || rawFeeds.length === 0) return { stats: {}, multiRoomData: [], hasAnyData: false };

    const roomKeys = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'];
    const stats = {};

    roomKeys.forEach(rk => {
      stats[rk] = {
        key: rk,
        name: coldRoomNames[rk] || DEFAULT_COLD_ROOM_NAMES[rk] || rk,
        temp: { min: Infinity, max: -Infinity, sum: 0, count: 0, current: null },
        humi: { min: Infinity, max: -Infinity, sum: 0, count: 0, current: null },
      };
    });

    let isMultiDay = ['week', 'month', 'three_months'].includes(filter);
    if (!isMultiDay && filter === 'custom' && rawFeeds.length > 1) {
      const firstDate = new Date(rawFeeds[0].created_at).toDateString();
      const lastDate = new Date(rawFeeds[rawFeeds.length - 1].created_at).toDateString();
      if (firstDate !== lastDate) isMultiDay = true;
    }
    const showSeconds = filter === 'duration' && (durationUnit === 'seconds' || durationUnit === 'minutes');
    const timeFormat = isMultiDay
      ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
      : showSeconds
        ? { hour: '2-digit', minute: '2-digit', second: '2-digit' }
        : { hour: '2-digit', minute: '2-digit' };
    const dtf = new Intl.DateTimeFormat('en-US', timeFormat);

    const multiRoomData = [];

    for (let i = 0; i < rawFeeds.length; i++) {
      const f = rawFeeds[i];
      const timeStr = dtf.format(new Date(f.created_at));
      const point = { time: timeStr, rawTimestamp: f.created_at };

      roomKeys.forEach((rk, idx) => {
        const sNum = idx + 1;
        const tKey = `field${sNum}`;
        const hKey = `field${sNum + 7}`;

        const tVal = parseRobustFloat(f[tKey] ?? f.multi_sensor_data?.[rk]?.temp);
        const hVal = parseRobustFloat(f[hKey] ?? f.multi_sensor_data?.[rk]?.humi);

        if (tVal !== null) {
          const st = stats[rk].temp;
          if (tVal < st.min) st.min = tVal;
          if (tVal > st.max) st.max = tVal;
          st.sum += tVal;
          st.count++;
          st.current = tVal;
          point[`${rk}_Temp`] = tVal;
        }

        if (hVal !== null) {
          const sh = stats[rk].humi;
          if (hVal < sh.min) sh.min = hVal;
          if (hVal > sh.max) sh.max = hVal;
          sh.sum += hVal;
          sh.count++;
          sh.current = hVal;
          point[`${rk}_Humi`] = hVal;
        }
      });

      multiRoomData.push(point);
    }

    // Format computed stats
    const formattedStats = {};
    let hasAnyData = false;

    roomKeys.forEach(rk => {
      const s = stats[rk];
      const hasRoomData = s.temp.count > 0 || s.humi.count > 0;
      if (hasRoomData) hasAnyData = true;

      formattedStats[rk] = {
        key: rk,
        name: s.name,
        hasData: hasRoomData,
        temp: {
          current: s.temp.current !== null ? s.temp.current.toFixed(1) : '--',
          avg: s.temp.count > 0 ? (s.temp.sum / s.temp.count).toFixed(1) : '--',
          min: s.temp.min !== Infinity ? s.temp.min.toFixed(1) : '--',
          max: s.temp.max !== -Infinity ? s.temp.max.toFixed(1) : '--',
          count: s.temp.count
        },
        humi: {
          current: s.humi.current !== null ? s.humi.current.toFixed(1) : '--',
          avg: s.humi.count > 0 ? (s.humi.sum / s.humi.count).toFixed(1) : '--',
          min: s.humi.min !== Infinity ? s.humi.min.toFixed(1) : '--',
          max: s.humi.max !== -Infinity ? s.humi.max.toFixed(1) : '--',
          count: s.humi.count
        }
      };
    });

    return { stats: formattedStats, multiRoomData, hasAnyData };
  }, [isCold, rawFeeds, coldRoomNames, filter, durationUnit]);

  const isSingleColdRoom = isCold && selectedRoom && selectedRoom !== 'all' && selectedRoom !== 'both';
  const activeSingleRoomStats = isSingleColdRoom ? roomWiseAnalysis.stats[selectedRoom] : null;

  // ── FILTER-AWARE SETPOINTS & STAGE SNAPSHOT CALCULATION ──
  const setpointsSnapshot = useMemo(() => {
    if (!isCold) return null;
    const targetRoom = (selectedRoom && selectedRoom !== 'all' && selectedRoom !== 'both') ? selectedRoom : 'S1';
    const roomSetps = getRoomSetpoints(targetRoom);
    const stagesDict = roomSetps?.settings || generateDefaultAlmoraSchedule(targetRoom).settings || {};

    // Active date range of current analytics filter
    const { start: fStart, end: fEnd } = getDateRange(filter, customStartDate, customEndDate, durationVal, durationUnit);
    const now = new Date();

    const stageList = ALL_SETTING_KEYS.filter(k => k in stagesDict).map((k) => {
      const st = stagesDict[k];
      const sDate = parseIsoOrDmy(st.start_date);
      const eDate = parseIsoOrDmy(st.end_date);

      // Determine timeline status relative to selected filter range
      let filterStatus = 'future'; // 'past' | 'in_filter' | 'future'
      if (sDate && eDate) {
        if (eDate < fStart) {
          filterStatus = 'past'; // Pehle ka stage
        } else if (sDate > fEnd) {
          filterStatus = 'future'; // Aage ka stage
        } else {
          filterStatus = 'in_filter'; // Currently active during selected filter
        }
      }

      // Check if it is currently live right now
      const isCurrentlyLive = sDate && eDate && (now >= sDate && now <= eDate);
      const isConfiguredActive = roomSetps.active_setting === k;

      // Compute averages across enabled slots for this stage
      const slots = (st.time_slots || []).filter(s => s.enabled !== false);
      const avgTargetTemp = slots.length > 0 ? (slots.reduce((acc, s) => acc + (Number(s.t_set) || 0), 0) / slots.length).toFixed(1) : '--';
      const avgTargetHumi = slots.length > 0 ? (slots.reduce((acc, s) => acc + (Number(s.h_set) || 0), 0) / slots.length).toFixed(1) : '--';

      const minTargetTemp = slots.length > 0 ? Math.min(...slots.map(s => Number(s.t_min ?? s.t_set ?? 0))) : '--';
      const maxTargetTemp = slots.length > 0 ? Math.max(...slots.map(s => Number(s.t_max ?? s.t_set ?? 0))) : '--';
      const minTargetHumi = slots.length > 0 ? Math.min(...slots.map(s => Number(s.h_min ?? s.h_set ?? 0))) : '--';
      const maxTargetHumi = slots.length > 0 ? Math.max(...slots.map(s => Number(s.h_max ?? s.h_set ?? 0))) : '--';

      return {
        key: k,
        name: st.name || k,
        start_date: st.start_date,
        end_date: st.end_date,
        enabled: st.enabled,
        photoperiod_on: st.photoperiod_on || '06:00 AM',
        photoperiod_off: st.photoperiod_off || '08:00 PM',
        lighting_enabled: st.lighting_enabled !== false,
        time_slots: st.time_slots || [],
        filterStatus,
        isCurrentlyLive,
        isConfiguredActive,
        avgTargetTemp,
        avgTargetHumi,
        minTargetTemp,
        maxTargetTemp,
        minTargetHumi,
        maxTargetHumi,
      };
    });

    // Default displayed stage
    const matchingFilterStage = stageList.find(s => s.filterStatus === 'in_filter');
    const activeSettingStage = stageList.find(s => s.isConfiguredActive);
    const effectiveStageKey = selectedStageKey || matchingFilterStage?.key || activeSettingStage?.key || stageList[0]?.key || 'Setting A';
    const activeStageData = stageList.find(s => s.key === effectiveStageKey) || stageList[0];

    // Compute Target vs Actual Compliance for the selected room
    const stActual = roomWiseAnalysis.stats[targetRoom];
    let tempDelta = null;
    let humiDelta = null;
    let tempCompliance = 'neutral';
    let humiCompliance = 'neutral';

    if (stActual && stActual.hasData && activeStageData && activeStageData.avgTargetTemp !== '--') {
      const actT = parseFloat(stActual.temp.avg);
      const tarT = parseFloat(activeStageData.avgTargetTemp);
      if (!isNaN(actT) && !isNaN(tarT)) {
        tempDelta = +(actT - tarT).toFixed(1);
        if (Math.abs(tempDelta) <= 1.0) tempCompliance = 'optimal';
        else if (tempDelta > 1.0) tempCompliance = 'warm';
        else tempCompliance = 'cold';
      }
    }

    if (stActual && stActual.hasData && activeStageData && activeStageData.avgTargetHumi !== '--') {
      const actH = parseFloat(stActual.humi.avg);
      const tarH = parseFloat(activeStageData.avgTargetHumi);
      if (!isNaN(actH) && !isNaN(tarH)) {
        humiDelta = +(actH - tarH).toFixed(1);
        if (Math.abs(humiDelta) <= 5.0) humiCompliance = 'optimal';
        else if (humiDelta > 5.0) humiCompliance = 'high';
        else humiCompliance = 'low';
      }
    }

    return {
      targetRoom,
      roomName: coldRoomNames[targetRoom] || DEFAULT_COLD_ROOM_NAMES[targetRoom] || targetRoom,
      programName: roomSetps?.program_name || `${coldRoomNames[targetRoom] || targetRoom} Program`,
      cropName: roomSetps?.crop_name || 'Standard Cold Program',
      mode: roomSetps?.mode || 'SCHEDULED',
      stages: stageList,
      activeStageKey: effectiveStageKey,
      activeStage: activeStageData,
      tempDelta,
      humiDelta,
      tempCompliance,
      humiCompliance,
      globalTMin: roomSetps?.['T MIN'] ?? 10.0,
      globalTMax: roomSetps?.['T MAX'] ?? 30.0,
      globalHMin: roomSetps?.['H MIN'] ?? 30.0,
      globalHMax: roomSetps?.['H MAX'] ?? 80.0,
    };
  }, [isCold, selectedRoom, getRoomSetpoints, filter, customStartDate, customEndDate, durationVal, durationUnit, selectedStageKey, roomWiseAnalysis, coldRoomNames]);

  // Standard statistical summary
  const summaryStats = useMemo(() => {
    const stats = {};
    channelFields.forEach(f => {
      stats[f.key] = { min: Infinity, max: -Infinity, sum: 0, count: 0 };
    });

    if (!rawFeeds || rawFeeds.length === 0) return stats;

    const len = rawFeeds.length;
    for (let i = 0; i < len; i++) {
      const feed = rawFeeds[i];
      for (let j = 0; j < channelFields.length; j++) {
        const fieldKey = channelFields[j].key;
        const val = parseRobustFloat(feed[fieldKey]);
        if (val !== null) {
          const s = stats[fieldKey];
          if (val < s.min) s.min = val;
          if (val > s.max) s.max = val;
          s.sum += val;
          s.count++;
        }
      }
    }

    const formatted = {};
    channelFields.forEach(f => {
      const s = stats[f.key];
      formatted[f.key] = {
        avg: s.count > 0 ? (s.sum / s.count).toFixed(1) : '--',
        min: s.min !== Infinity ? s.min.toFixed(1) : '--',
        max: s.max !== -Infinity ? s.max.toFixed(1) : '--'
      };
    });
    return formatted;
  }, [rawFeeds, channelFields]);

  const summaryMetrics = channelFields.map(f => {
    const meta = getFieldMeta(f.name);
    const stats = summaryStats[f.key] || { avg: '--', min: '--', max: '--' };
    return {
      name: f.name,
      label: `Avg ${f.name}`,
      value: stats.avg,
      min: stats.min,
      max: stats.max,
      unit: meta.unit,
      icon: meta.icon,
      color: meta.color,
      bg: meta.bg
    };
  });

  const chartSubtitle = useMemo(() => {
    switch (filter) {
      case 'today':
        return 'Today';
      case 'yesterday':
        return 'Yesterday';
      case 'week':
        return 'This Week';
      case 'month':
        return 'This Month';
      case 'three_months':
        return 'Last 3 Months';
      case 'all':
        return 'All History';
      case 'duration':
        return `Last ${durationVal} ${durationUnit}`;
      case 'custom':
        if (customStartDate && customEndDate) {
          return `${customStartDate.replace('T', ' ')} to ${customEndDate.replace('T', ' ')}`;
        } else if (customStartDate) {
          return `From ${customStartDate.replace('T', ' ')}`;
        }
        return 'Custom Range';
      default:
        return 'Last 24 hours';
    }
  }, [filter, customStartDate, customEndDate, durationVal, durationUnit]);

  const filterLabel = filter === 'duration'
    ? `last_${durationVal}_${durationUnit}`
    : filter === 'custom'
      ? (customStartDate && customEndDate ? `${customStartDate}_to_${customEndDate}` : customStartDate || 'custom')
      : filter;

  const filterButtons = [
    { key: 'today', label: 'Today' },
    { key: 'yesterday', label: 'Yesterday' },
    { key: 'duration', label: 'Time Duration' },
    { key: 'week', label: 'This Week' },
    { key: 'month', label: 'This Month' },
    { key: 'three_months', label: '3 Months' },
    { key: 'all', label: 'All History' },
    { key: 'custom', label: 'Custom Range' },
  ];

  const stagger = {
    hidden: { opacity: 0 },
    show: { opacity: 1, transition: { staggerChildren: 0.08 } },
  };

  if (devicesLoading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      </div>
    );
  }

  if (allDevices.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <div className="rounded-2xl border border-yellow-500/30 bg-yellow-500/10 p-8 text-center max-w-md">
          <Cpu className="h-12 w-12 text-yellow-400 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-white mb-2">No Devices Configured</h3>
          <p className="text-sm text-slate-400">
            No devices have analytics credentials configured. Go to <strong>Devices → Edit</strong> and add Channel ID & API keys.
          </p>
        </div>
      </div>
    );
  }

  const roomLabel = getSelectedRoomLabel();

  return (
    <div className="space-y-6">
      {/* ── CONTROL TOOLBAR CARD ── */}
      <div className="relative z-20 rounded-2xl border border-slate-700/60 bg-slate-800/40 p-3.5 sm:p-4 backdrop-blur-md space-y-3.5 sm:space-y-4 shadow-lg">
        {/* Row 1: Selectors & Global Actions */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          {/* Left: Device Selection & Scope Badge */}
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <select
              value={selectedDeviceId}
              onChange={(e) => handleDeviceChange(e.target.value)}
              className="w-full sm:w-auto rounded-xl border border-slate-700 bg-slate-800 px-3.5 py-2 text-xs font-semibold text-white outline-none focus:border-emerald-500 cursor-pointer shadow-sm hover:border-slate-600 transition-colors"
            >
              {allDevices.map((d) => (
                <option key={d._id} value={d._id}>
                  {d.name}
                </option>
              ))}
            </select>

            {/* Room Selector for Office Control */}
            {isOffice && (
              <select
                value={selectedRoom || 'room1'}
                onChange={(e) => setSelectedRoom(e.target.value)}
                className="w-full sm:w-auto rounded-xl border border-slate-700 bg-slate-800 px-3.5 py-2 text-xs font-semibold text-white outline-none focus:border-emerald-500 cursor-pointer shadow-sm"
              >
                <option value="room1">Room 1</option>
                <option value="room2">Room 2</option>
                <option value="room3">Room 3</option>
                <option value="both">All Rooms</option>
              </select>
            )}

            <div className="text-xs text-slate-400 flex flex-wrap items-center gap-1.5 pt-0.5">
              <span className="hidden sm:inline">&bull;</span>
              <span><strong className="text-slate-200 font-bold">{totalDbPoints.toLocaleString()}</strong> Rows in Range</span>
              {roomLabel && (
                <span className="text-emerald-400 font-semibold px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-[11px]">
                  {roomLabel}
                </span>
              )}
              <span className="hidden sm:inline">&bull;</span>
              <span className="text-slate-300 font-medium">{chartSubtitle}</span>
              {/* {totalCollectionDocs > 0 && totalCollectionDocs !== totalDbPoints && (
                <span className="text-slate-500 font-normal text-[11px]"> (DB: {totalCollectionDocs.toLocaleString()})</span>
              )} */}
            </div>
          </div>

          {/* Right: Actions (Refresh, Export & Cold Room Panel Link) */}
          <div className="flex flex-wrap items-center gap-2 w-full lg:w-auto justify-start lg:justify-end">
            {isCold && (
              <a
                href={`/cold-storage?mqttId=${selectedDevice?.mqttId || selectedDevice?._id}`}
                className="flex-1 sm:flex-initial flex items-center justify-center gap-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-300 transition-all hover:bg-emerald-500/20 hover:text-white"
                title="Go to Cold Storage Setpoints & Controller Panel"
              >
                <Wind className="h-3.5 w-3.5 text-emerald-400" />
                <span>Cold Room Panel</span>
              </a>
            )}

            <button
              onClick={() => fetchData(true)}
              disabled={loading}
              className="flex-1 sm:flex-initial flex items-center justify-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-medium text-slate-300 transition-all hover:bg-slate-700 hover:text-white disabled:opacity-50"
              title="Refresh data"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin text-green-400' : ''}`} />
              <span>Refresh</span>
            </button>

            {/* Comprehensive Export Dropdown */}
            <div className="relative z-50 flex-1 sm:flex-initial">
              <button
                onClick={() => setShowDownloadMenu(!showDownloadMenu)}
                disabled={rawFeeds.length === 0 || isExporting}
                className="w-full flex items-center justify-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-3.5 py-2 text-xs font-bold text-emerald-300 transition-all hover:bg-emerald-500/25 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed shadow-sm shadow-emerald-500/10 whitespace-nowrap"
              >
                {isExporting ? (
                  <>
                    <RefreshCw className="h-3.5 w-3.5 animate-spin text-emerald-400" />
                    <span>Exporting CSV...</span>
                  </>
                ) : (
                  <>
                    <Download className="h-3.5 w-3.5 text-emerald-400" />
                    <span>Download CSV ({totalDbPoints.toLocaleString()})</span>
                  </>
                )}
              </button>

              <AnimatePresence>
                {showDownloadMenu && rawFeeds.length > 0 && !isExporting && (
                  <>
                    <div
                      className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[1px]"
                      onClick={() => setShowDownloadMenu(false)}
                    />
                    <motion.div
                      initial={{ opacity: 0, y: 5, scale: 0.97 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 5, scale: 0.97 }}
                      className="absolute right-0 top-full z-50 mt-2 w-[calc(100vw-2rem)] max-w-sm sm:w-80 rounded-2xl border border-slate-700 bg-slate-900/98 p-2.5 shadow-2xl shadow-black/90 backdrop-blur-2xl space-y-2 max-h-[80vh] overflow-y-auto"
                    >
                      <div className="px-2.5 py-1.5 border-b border-slate-800 flex items-center justify-between">
                        <span className="text-[11px] font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                          <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-400" />
                          Export Data Options
                        </span>
                        <span className="text-[10px] text-slate-500">{totalDbPoints.toLocaleString()} Rows</span>
                      </div>

                      {/* Cold Room Specific Multi-Options */}
                      {isCold && (
                        <div className="space-y-1">
                          {/* Single Room Direct CSVs */}
                          <div className="pt-1 border-t border-slate-800/80 space-y-0.5">
                            <span className="text-[10px] text-slate-400 px-2.5 block font-medium">Download Specific Room CSV:</span>
                            {['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].map(sKey => {
                              const rName = coldRoomNames[sKey] || DEFAULT_COLD_ROOM_NAMES[sKey] || sKey;
                              return (
                                <button
                                  key={sKey}
                                  onClick={() => {
                                    setShowDownloadMenu(false);
                                    downloadColdRoomSingleCSV(rawFeeds, sKey, rName, filterLabel, selectedDevice?.name || 'Device');
                                  }}
                                  className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors text-left"
                                >
                                  <span className="truncate pr-2 font-medium">
                                    <strong className="text-emerald-400 font-mono">{sKey}:</strong> {rName}
                                  </span>
                                  <span className="text-[10px] text-slate-400 font-mono shrink-0">Download CSV</span>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {/* Standard Full Server Export */}
                      <div className="pt-1.5 border-t border-slate-800 space-y-1">
                        <span className="text-[10px] font-semibold text-slate-400 px-2.5 block uppercase">
                          Current View Full Export
                        </span>
                        <button
                          onClick={() => handleFullExport('csv')}
                          className="flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
                        >
                          <span className="flex flex-col text-left">
                            <span className="font-semibold text-white"> CSV Export</span>
                            <span className="text-[10px] text-slate-400">{totalDbPoints.toLocaleString()} records ({roomLabel || 'Range'})</span>
                          </span>
                          <span className="text-[10px] text-emerald-400 font-mono font-bold bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">.csv</span>
                        </button>

                      </div>

                      {/* Setpoints Schedule & Compliance Audit Export Section */}
                      {isCold && (
                        <div className="pt-1.5 border-t border-slate-800 space-y-1">
                          <span className="text-[10px] font-semibold text-emerald-400 px-2.5 block uppercase tracking-wider flex items-center justify-between">
                            <span className="flex items-center gap-1.5">
                              <Target className="h-3 w-3" />
                              Setpoints & Audit Exports
                            </span>
                            <button
                              onClick={() => {
                                setShowDownloadMenu(false);
                                setExportModalRoom((selectedRoom && selectedRoom !== 'all' && selectedRoom !== 'both') ? selectedRoom : 'S1');
                                setExportModalType('audit');
                                setShowSetpointsExportModal(true);
                              }}
                              className="text-[9.5px] text-emerald-400 hover:text-emerald-300 font-mono font-bold flex items-center gap-0.5 hover:underline"
                            >
                              Open Hub <ArrowUpRight className="h-2.5 w-2.5" />
                            </button>
                          </span>

                          {/* Target vs Actual Compliance Audit */}
                          <button
                            onClick={() => {
                              setShowDownloadMenu(false);
                              if (selectedRoom && selectedRoom !== 'all' && selectedRoom !== 'both') {
                                const rName = coldRoomNames[selectedRoom] || DEFAULT_COLD_ROOM_NAMES[selectedRoom] || selectedRoom;
                                downloadTargetVsActualComplianceCSV(rawFeeds, selectedRoom, rName, getRoomSetpoints(selectedRoom), filterLabel, selectedDevice?.name || 'Device');
                              } else {
                                downloadAllRoomsTargetVsActualComplianceCSV(rawFeeds, allSetpoints, coldRoomNames, filterLabel, selectedDevice?.name || 'Device');
                              }
                            }}
                            className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors text-left"
                          >
                            <span className="truncate pr-2 font-medium">
                              <span className="text-emerald-400 font-bold">Audit:</span> {selectedRoom && selectedRoom !== 'all' && selectedRoom !== 'both' ? `${selectedRoom} Target vs Actual` : 'All 7 Chambers Audit'}
                            </span>
                            <span className="text-[10px] text-emerald-400 font-mono font-bold bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">.csv</span>
                          </button>

                          {/* Room Schedule CSV */}
                          <button
                            onClick={() => {
                              setShowDownloadMenu(false);
                              const curRoom = (selectedRoom && selectedRoom !== 'all' && selectedRoom !== 'both') ? selectedRoom : 'S1';
                              const rName = coldRoomNames[curRoom] || DEFAULT_COLD_ROOM_NAMES[curRoom] || curRoom;
                              downloadRoomSetpointsCSV(curRoom, rName, getRoomSetpoints(curRoom), selectedDevice?.name || 'Device');
                            }}
                            className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors text-left"
                          >
                            <span className="truncate pr-2 font-medium">
                              {selectedRoom && selectedRoom !== 'all' && selectedRoom !== 'both' ? `${selectedRoom} Schedule (10 Stages)` : 'S1 Schedule (10 Stages)'}
                            </span>
                            <span className="text-[10px] text-emerald-400 font-mono font-bold bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">.csv</span>
                          </button>

                          {/* Master 7 Chambers Setpoints CSV */}
                          <button
                            onClick={() => {
                              setShowDownloadMenu(false);
                              downloadAllRoomsSetpointsCSV(allSetpoints, coldRoomNames, selectedDevice?.name || 'Device');
                            }}
                            className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors text-left"
                          >
                            <span className="truncate pr-2 font-medium">
                              All 7 Chambers Master Schedule
                            </span>
                            <span className="text-[10px] text-emerald-400 font-mono font-bold bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">.csv</span>
                          </button>

                          {/* Setpoints Backup JSON */}
                          <button
                            onClick={() => {
                              setShowDownloadMenu(false);
                              const devSlug = sanitizeFileName(selectedDevice?.name || 'Device');
                              const dateStr = new Date().toISOString().split('T')[0];
                              downloadSetpointsJSON(allSetpoints, `${devSlug}_All_Setpoints_Schedule_${dateStr}.json`);
                            }}
                            className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors text-left"
                          >
                            <span className="truncate pr-2 font-medium">
                              Full Setpoints Config Backup
                            </span>
                            <span className="text-[10px] text-sky-400 font-mono font-bold bg-sky-500/10 border border-sky-500/20 px-1.5 py-0.5 rounded">.json</span>
                          </button>
                        </div>
                      )}
                    </motion.div>
                  </>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>

        {/* ── COLD STORAGE ROOM-WISE SELECTOR PILLS (S1 to S7) ── */}
        {isCold && (
          <div className="flex items-center gap-2 overflow-x-auto pt-2.5 pb-1.5 border-t border-slate-700/50 scrollbar-none no-scrollbar -mx-1 px-1 touch-pan-x">
            <span className="text-xs font-bold text-slate-300 pr-1 shrink-0 flex items-center gap-1.5">
              <Wind className="h-3.5 w-3.5 text-emerald-400" />
              Chamber Filter:
            </span>

            {/* All Rooms Overview Pill */}
            <button
              onClick={() => setSelectedRoom('all')}
              className={`flex items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-bold whitespace-nowrap transition-all shrink-0 ${!selectedRoom || selectedRoom === 'all'
                ? 'bg-emerald-500 text-slate-950 font-bold shadow-md shadow-emerald-500/20 ring-1 ring-emerald-400'
                : 'bg-slate-900/80 border border-slate-700 text-slate-300 hover:text-white hover:border-slate-600'
                }`}
            >
              <Layers className="h-3.5 w-3.5" />
              <span>All Rooms Overview</span>
            </button>

            {/* Individual Room Pills (S1 - S7) */}
            {['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].map((sKey) => {
              const isSelected = selectedRoom === sKey;
              const name = coldRoomNames[sKey] || DEFAULT_COLD_ROOM_NAMES[sKey];
              const st = roomWiseAnalysis.stats[sKey];
              const hasData = st?.hasData;

              return (
                <button
                  key={sKey}
                  onClick={() => setSelectedRoom(sKey)}
                  className={`flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-all shrink-0 ${isSelected
                    ? 'bg-emerald-500 text-slate-950 font-bold shadow-md shadow-emerald-500/20 ring-1 ring-emerald-400'
                    : 'bg-slate-900/80 border border-slate-700 text-slate-300 hover:text-white hover:border-slate-600'
                    }`}
                >
                  <span className={`h-2 w-2 rounded-full ${hasData ? 'bg-emerald-400' : 'bg-slate-600'}`} />
                  <span>{name}</span>
                  <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded font-bold ${isSelected ? 'bg-slate-950/40 text-emerald-950' : 'bg-slate-800 text-slate-400'}`}>
                    {sKey}
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {/* ── ITC POLYHOUSE ZONE SELECTOR PILLS (PH-01 to PH-06) ── */}
        {isPoly && (
          <div className="flex items-center gap-2 overflow-x-auto pt-2.5 pb-1.5 border-t border-slate-700/50 scrollbar-none no-scrollbar -mx-1 px-1 touch-pan-x">
            <span className="text-xs font-bold text-slate-300 pr-1 shrink-0 flex items-center gap-1.5">
              <Leaf className="h-3.5 w-3.5 text-emerald-400" />
              Zone Filter:
            </span>

            {/* All Zones Overview Pill */}
            <button
              onClick={() => setSelectedRoom('all')}
              className={`flex items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-bold whitespace-nowrap transition-all shrink-0 ${!selectedRoom || selectedRoom === 'all'
                ? 'bg-emerald-500 text-slate-950 font-bold shadow-md shadow-emerald-500/20 ring-1 ring-emerald-400'
                : 'bg-slate-900/80 border border-slate-700 text-slate-300 hover:text-white hover:border-slate-600'
                }`}
            >
              <Layers className="h-3.5 w-3.5" />
              <span>All Zones Overview</span>
            </button>

            {/* Individual Zone Pills (PH-01 - PH-06) */}
            {['PH-01', 'PH-02', 'PH-03', 'PH-04', 'PH-05', 'PH-06'].map((zKey) => {
              const isSelected = selectedRoom === zKey;
              return (
                <button
                  key={zKey}
                  onClick={() => setSelectedRoom(zKey)}
                  className={`flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-semibold whitespace-nowrap transition-all shrink-0 ${isSelected
                    ? 'bg-emerald-500 text-slate-950 font-bold shadow-md shadow-emerald-500/20 ring-1 ring-emerald-400'
                    : 'bg-slate-900/80 border border-slate-700 text-slate-300 hover:text-white hover:border-slate-600'
                    }`}
                >
                  <span className={`h-2 w-2 rounded-full ${isSelected ? 'bg-slate-950' : 'bg-emerald-400'}`} />
                  <span>{zKey === 'PH-06' ? 'PH-06 (Outside / Ref)' : zKey}</span>
                </button>
              );
            })}
          </div>
        )}

        {/* Row 2: Time Filter Tabs */}
        <div className="flex flex-col gap-3 pt-3 border-t border-slate-700/50">
          <div className="flex gap-1.5 rounded-xl bg-slate-900/60 p-1.5 border border-slate-700/50 flex-wrap sm:flex-nowrap overflow-x-auto scrollbar-none">
            {filterButtons.map((btn) => (
              <button
                key={btn.key}
                onClick={() => {
                  setFilter(btn.key);
                  if (btn.key === 'custom') {
                    if (!customStartDate || !customEndDate) {
                      const now = new Date();
                      const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
                      const pad = (n) => String(n).padStart(2, '0');
                      const formatIso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
                      setCustomStartDate(formatIso(sevenDaysAgo));
                      setCustomEndDate(formatIso(now));
                    }
                  }
                }}
                className={`flex-1 min-w-[70px] text-center rounded-lg px-2.5 sm:px-3 py-1.5 text-xs font-medium transition-all whitespace-nowrap ${filter === btn.key
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 font-semibold shadow-sm'
                  : 'text-slate-400 hover:text-white'
                  }`}
              >
                {btn.label}
              </button>
            ))}
          </div>

          {/* Sub-row: Duration controls or Custom Date Picker */}
          {filter === 'duration' && (
            <motion.div
              initial={{ opacity: 0, y: -5 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-wrap items-center gap-2.5 rounded-xl border border-slate-700/60 bg-slate-900/40 p-2.5"
            >
              <span className="text-xs text-slate-400 font-medium pl-1">Duration:</span>
              <input
                type="number"
                min="1"
                max="999"
                value={durationVal}
                onChange={(e) => setDurationVal(e.target.value)}
                className="w-16 rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-white text-center outline-none focus:border-emerald-500 font-semibold"
              />
              <select
                value={durationUnit}
                onChange={(e) => setDurationUnit(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 text-xs text-white outline-none cursor-pointer focus:border-emerald-500"
              >
                <option value="seconds">Seconds</option>
                <option value="minutes">Minutes</option>
                <option value="hours">Hours</option>
                <option value="days">Days</option>
              </select>

              {/* Quick Preset Buttons */}
              <div className="flex flex-wrap items-center gap-1 sm:pl-2 sm:border-l border-slate-700/60 w-full sm:w-auto pt-1 sm:pt-0">
                {[
                  { val: '30', unit: 'seconds', label: '30s' },
                  { val: '5', unit: 'minutes', label: '5m' },
                  { val: '1', unit: 'hours', label: '1h' },
                  { val: '6', unit: 'hours', label: '6h' },
                  { val: '12', unit: 'hours', label: '12h' },
                  { val: '24', unit: 'hours', label: '24h' },
                ].map(preset => (
                  <button
                    key={preset.label}
                    onClick={() => { setDurationVal(preset.val); setDurationUnit(preset.unit); }}
                    className={`rounded px-2.5 py-1 text-[11px] font-medium transition-all ${durationVal === preset.val && durationUnit === preset.unit
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 font-semibold shadow-sm'
                      : 'text-slate-400 hover:text-white hover:bg-slate-700/40'
                      }`}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </motion.div>
          )}

          {filter === 'custom' && (
            <motion.div
              initial={{ opacity: 0, y: -5 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5 rounded-xl border border-slate-700/60 bg-slate-900/40 p-2.5"
            >
              <div className="flex items-center gap-2 flex-1">
                <span className="text-xs text-slate-400 w-10 sm:w-auto shrink-0 font-medium">From:</span>
                <input
                  type="datetime-local"
                  value={customStartDate}
                  onChange={(e) => setCustomStartDate(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-white outline-none focus:border-emerald-500 transition-colors"
                />
              </div>
              <div className="flex items-center gap-2 flex-1">
                <span className="text-xs text-slate-400 w-10 sm:w-auto shrink-0 font-medium">To:</span>
                <input
                  type="datetime-local"
                  value={customEndDate}
                  onChange={(e) => setCustomEndDate(e.target.value)}
                  min={customStartDate}
                  className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-white outline-none focus:border-emerald-500 transition-colors"
                />
              </div>
            </motion.div>
          )}
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center justify-between rounded-2xl border border-red-500/30 bg-red-500/10 px-6 py-4"
        >
          <div className="flex items-center gap-3">
            <WifiOff className="h-5 w-5 text-red-400" />
            <div>
              <p className="text-sm font-medium text-red-300">Failed to load analytics data</p>
              <p className="text-xs text-red-400/70">{error}</p>
            </div>
          </div>
          <button
            onClick={() => fetchData(true)}
            className="rounded-lg bg-red-500/20 px-4 py-2 text-xs font-medium text-red-300 hover:bg-red-500/30 transition-colors"
          >
            Retry
          </button>
        </motion.div>
      )}

      {/* ── COLD STORAGE ROOM-WISE ANALYSIS WORKSPACE ── */}
      {isCold && (
        <div className="space-y-6">
          {/* A. SINGLE ROOM FOCUSED ANALYSIS VIEW (when S1..S7 is selected) */}
          {isSingleColdRoom && (
            <div className="space-y-5">
              {/* Single Room Focus Banner */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between p-4 rounded-2xl bg-slate-900/80 border border-emerald-500/30 shadow-lg gap-3">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shrink-0 font-mono font-bold text-sm">
                    {selectedRoom}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-base font-bold text-white">
                        {coldRoomNames[selectedRoom] || DEFAULT_COLD_ROOM_NAMES[selectedRoom]}
                      </h3>
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                        {selectedRoom === 'S7' ? 'Greenhouse Chamber' : 'Cold Storage Room'}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400">
                      Room-specific historical sensor analysis & telemetry telemetry records
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
                  <button
                    onClick={() => downloadColdRoomSingleCSV(rawFeeds, selectedRoom, coldRoomNames[selectedRoom] || selectedRoom, filterLabel, selectedDevice?.name || 'Device')}
                    disabled={rawFeeds.length === 0}
                    className="flex-1 sm:flex-initial flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-xl bg-emerald-500 text-slate-950 hover:bg-emerald-400 font-bold text-xs transition-all shadow-sm shadow-emerald-500/20 disabled:opacity-50 whitespace-nowrap"
                    title={`Export ${selectedRoom} CSV`}
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>Download {selectedRoom} CSV</span>
                  </button>

                  <button
                    onClick={() => setSelectedRoom('all')}
                    className="flex-1 sm:flex-initial flex items-center justify-center gap-1 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-xs font-semibold transition-colors border border-slate-700 whitespace-nowrap"
                  >
                    <Layers className="h-3.5 w-3.5 text-slate-400" />
                    <span>All Rooms</span>
                  </button>
                </div>
              </div>

              {/* Single Room 2 Stats Cards (Temp & Humidity) */}
              {activeSingleRoomStats && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Temperature Card */}
                  <div className="rounded-2xl border border-orange-500/20 bg-orange-500/5 p-5 backdrop-blur-md">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="rounded-lg p-2 bg-orange-500/10 text-orange-400">
                          <Thermometer className="h-5 w-5" />
                        </div>
                        <div>
                          <p className="text-xs font-semibold text-slate-300">Room Temperature</p>
                          <p className="text-[10px] text-slate-500 font-mono">Chamber Sensor {selectedRoom}</p>
                        </div>
                      </div>
                      <span className="text-xs font-bold text-orange-400 font-mono bg-orange-500/10 px-2.5 py-1 rounded-lg border border-orange-500/30">
                        Latest: {activeSingleRoomStats.temp.current}°C
                      </span>
                    </div>

                    <div className="mt-4 flex items-baseline gap-2">
                      <span className="text-3xl font-bold text-orange-400 tabular-nums">
                        {activeSingleRoomStats.temp.avg}
                      </span>
                      <span className="text-sm font-medium text-slate-400">°C (Average)</span>
                    </div>

                    <div className="mt-4 pt-3 border-t border-slate-700/40 grid grid-cols-3 gap-2 text-xs font-mono">
                      <div>
                        <span className="text-slate-400 text-[10px] block">Min Temp</span>
                        <span className="text-slate-200 font-bold">{activeSingleRoomStats.temp.min}°C</span>
                      </div>
                      <div>
                        <span className="text-slate-400 text-[10px] block">Max Temp</span>
                        <span className="text-slate-200 font-bold">{activeSingleRoomStats.temp.max}°C</span>
                      </div>
                      <div>
                        <span className="text-slate-400 text-[10px] block">Readings</span>
                        <span className="text-slate-200 font-bold">{(totalDbPoints > 0 ? totalDbPoints : activeSingleRoomStats.temp.count).toLocaleString()}</span>
                      </div>
                    </div>
                  </div>

                  {/* Humidity Card */}
                  <div className="rounded-2xl border border-blue-500/20 bg-blue-500/5 p-5 backdrop-blur-md">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="rounded-lg p-2 bg-blue-500/10 text-blue-400">
                          <Droplets className="h-5 w-5" />
                        </div>
                        <div>
                          <p className="text-xs font-semibold text-slate-300">Relative Humidity</p>
                          <p className="text-[10px] text-slate-500 font-mono">Chamber Sensor {selectedRoom}</p>
                        </div>
                      </div>
                      <span className="text-xs font-bold text-blue-400 font-mono bg-blue-500/10 px-2.5 py-1 rounded-lg border border-blue-500/30">
                        Latest: {activeSingleRoomStats.humi.current}%
                      </span>
                    </div>

                    <div className="mt-4 flex items-baseline gap-2">
                      <span className="text-3xl font-bold text-blue-400 tabular-nums">
                        {activeSingleRoomStats.humi.avg}
                      </span>
                      <span className="text-sm font-medium text-slate-400">% (Average)</span>
                    </div>

                    <div className="mt-4 pt-3 border-t border-slate-700/40 grid grid-cols-3 gap-2 text-xs font-mono">
                      <div>
                        <span className="text-slate-400 text-[10px] block">Min Humidity</span>
                        <span className="text-slate-200 font-bold">{activeSingleRoomStats.humi.min}%</span>
                      </div>
                      <div>
                        <span className="text-slate-400 text-[10px] block">Max Humidity</span>
                        <span className="text-slate-200 font-bold">{activeSingleRoomStats.humi.max}%</span>
                      </div>
                      <div>
                        <span className="text-slate-400 text-[10px] block">Readings</span>
                        <span className="text-slate-200 font-bold">{(totalDbPoints > 0 ? totalDbPoints : activeSingleRoomStats.humi.count).toLocaleString()}</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* ── SETPOINTS & SCHEDULE SNAPSHOT (Filter-Aware) ── */}
              {setpointsSnapshot && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded-2xl border border-slate-700/70 bg-gradient-to-br from-slate-900/90 via-slate-900/70 to-slate-950/90 p-4 sm:p-5 backdrop-blur-xl shadow-xl space-y-4"
                >
                  {/* Header: Title, Active Program & Filter Context */}
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-slate-800 pb-3.5">
                    <div className="flex items-start sm:items-center gap-3">
                      <div className="p-2.5 rounded-xl bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 shrink-0">
                        <Target className="h-5 w-5" />
                      </div>
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-sm sm:text-base font-bold text-white">
                            {setpointsSnapshot.roomName} Setpoints & Stage Snapshot
                          </h4>
                          <span className="text-[10px] font-bold font-mono px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                            {setpointsSnapshot.programName}
                          </span>
                        </div>
                        <p className="text-xs text-slate-400 flex flex-wrap items-center gap-1.5 pt-0.5">
                          <span>Filter Period: <strong className="text-slate-200 font-semibold">{chartSubtitle}</strong></span>
                          <span>&bull;</span>
                          <span className="text-slate-400">Mode: <strong className="text-emerald-400 font-mono">{setpointsSnapshot.mode}</strong></span>
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2 self-start md:self-center relative">
                      {/* Setpoints Download Dropdown Menu */}
                      <div className="relative">
                        <button
                          onClick={() => setShowSetpointsDropdown(!showSetpointsDropdown)}
                          className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 hover:text-white text-xs font-bold border border-emerald-500/40 transition-all shadow-sm shadow-emerald-500/10"
                          title="Open Setpoints & Audit Download Options"
                        >
                          <Download className="h-3.5 w-3.5 text-emerald-400" />
                          <span>Download Setpoints</span>
                          <ChevronDown className={`h-3 w-3 text-emerald-400/80 transition-transform ${showSetpointsDropdown ? 'rotate-180' : ''}`} />
                        </button>

                        <AnimatePresence>
                          {showSetpointsDropdown && (
                            <>
                              <div
                                className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[1px]"
                                onClick={() => setShowSetpointsDropdown(false)}
                              />
                              <motion.div
                                initial={{ opacity: 0, y: 4, scale: 0.96 }}
                                animate={{ opacity: 1, y: 0, scale: 1 }}
                                exit={{ opacity: 0, y: 4, scale: 0.96 }}
                                className="absolute right-0 top-full z-50 mt-1.5 w-72 rounded-2xl border border-slate-700 bg-slate-900/98 p-2 shadow-2xl shadow-black/90 backdrop-blur-2xl space-y-1"
                              >
                                <div className="px-2.5 py-1.5 border-b border-slate-800 flex items-center justify-between">
                                  <span className="text-[10.5px] font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                                    <Target className="h-3.5 w-3.5 text-emerald-400" />
                                    {setpointsSnapshot.roomName} Setpoints
                                  </span>
                                  <span className="text-[9.5px] text-emerald-400 font-mono font-bold bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">
                                    {setpointsSnapshot.targetRoom}
                                  </span>
                                </div>

                                {/* 1. Target vs Actual Audit CSV */}
                                <button
                                  onClick={() => {
                                    setShowSetpointsDropdown(false);
                                    downloadTargetVsActualComplianceCSV(
                                      rawFeeds,
                                      setpointsSnapshot.targetRoom,
                                      setpointsSnapshot.roomName,
                                      getRoomSetpoints(setpointsSnapshot.targetRoom),
                                      filterLabel,
                                      selectedDevice?.name || 'Device'
                                    );
                                  }}
                                  className="flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors text-left"
                                >
                                  <div className="flex flex-col">
                                    <span className="font-semibold text-white flex items-center gap-1">
                                      <Activity className="h-3 w-3 text-orange-400" /> Target vs Actual Audit
                                    </span>
                                    <span className="text-[9.5px] text-slate-400">Sensor readings vs targets & tolerances</span>
                                  </div>
                                  <span className="text-[10px] text-emerald-400 font-mono font-bold bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">.csv</span>
                                </button>

                                {/* 2. Active Stage Only CSV */}
                                {setpointsSnapshot.activeStage && (
                                  <button
                                    onClick={() => {
                                      setShowSetpointsDropdown(false);
                                      downloadSingleStageSetpointsCSV(
                                        setpointsSnapshot.targetRoom,
                                        setpointsSnapshot.roomName,
                                        setpointsSnapshot.activeStageKey,
                                        setpointsSnapshot.activeStage,
                                        getRoomSetpoints(setpointsSnapshot.targetRoom),
                                        selectedDevice?.name || 'Device'
                                      );
                                    }}
                                    className="flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors text-left"
                                  >
                                    <div className="flex flex-col">
                                      <span className="font-semibold text-white flex items-center gap-1">
                                        <Clock className="h-3 w-3 text-emerald-400" /> {setpointsSnapshot.activeStage.name} Only
                                      </span>
                                      <span className="text-[9.5px] text-slate-400">Selected stage 5 daily slots</span>
                                    </div>
                                    <span className="text-[10px] text-emerald-400 font-mono font-bold bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">.csv</span>
                                  </button>
                                )}

                                {/* 3. Full Room Schedule CSV */}
                                <button
                                  onClick={() => {
                                    setShowSetpointsDropdown(false);
                                    downloadRoomSetpointsCSV(
                                      setpointsSnapshot.targetRoom,
                                      setpointsSnapshot.roomName,
                                      getRoomSetpoints(setpointsSnapshot.targetRoom),
                                      selectedDevice?.name || 'Device'
                                    );
                                  }}
                                  className="flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors text-left"
                                >
                                  <div className="flex flex-col">
                                    <span className="font-semibold text-white flex items-center gap-1">
                                      <FileSpreadsheet className="h-3 w-3 text-sky-400" /> Full Room Schedule
                                    </span>
                                    <span className="text-[9.5px] text-slate-400">All 10 stages (Setting A to J)</span>
                                  </div>
                                  <span className="text-[10px] text-emerald-400 font-mono font-bold bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">.csv</span>
                                </button>

                                {/* 4. Master 7 Chambers Setpoints CSV */}
                                <button
                                  onClick={() => {
                                    setShowSetpointsDropdown(false);
                                    downloadAllRoomsSetpointsCSV(
                                      allSetpoints,
                                      coldRoomNames,
                                      selectedDevice?.name || 'Device'
                                    );
                                  }}
                                  className="flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors text-left"
                                >
                                  <div className="flex flex-col">
                                    <span className="font-semibold text-white flex items-center gap-1">
                                      <Layers className="h-3 w-3 text-purple-400" /> All 7 Chambers Master
                                    </span>
                                    <span className="text-[9.5px] text-slate-400">Complete facility setpoint schedule</span>
                                  </div>
                                  <span className="text-[10px] text-emerald-400 font-mono font-bold bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">.csv</span>
                                </button>



                                {/* Modal Trigger */}
                                <div className="pt-1 border-t border-slate-800">
                                  <button
                                    onClick={() => {
                                      setShowSetpointsDropdown(false);
                                      setExportModalRoom(setpointsSnapshot.targetRoom);
                                      setExportModalType('audit');
                                      setShowSetpointsExportModal(true);
                                    }}
                                    className="flex w-full items-center justify-center gap-1.5 py-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-[11px] font-bold text-emerald-300 transition-colors"
                                  >
                                    <FileDown className="h-3.5 w-3.5" />
                                    <span>Export Center Dialog...</span>
                                  </button>
                                </div>
                              </motion.div>
                            </>
                          )}
                        </AnimatePresence>
                      </div>


                      {/* Edit Setpoints Link */}
                      <a
                        href={`/cold-storage?mqttId=${selectedDevice?.mqttId || selectedDevice?._id}&room=${selectedRoom || 'S1'}`}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-xs font-semibold border border-slate-700 transition-colors"
                        title="Open Cold Storage Setpoints Configuration"
                      >
                        <SlidersHorizontal className="h-3.5 w-3.5 text-emerald-400" />
                        <span>Edit</span>
                        <ArrowUpRight className="h-3 w-3 opacity-60" />
                      </a>
                    </div>
                  </div>

                  {/* Stage Timeline Navigation Pills ("Pehle kya tha, Ab kya hai, Aage kya hoga") */}
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-slate-400 font-medium flex items-center gap-1.5">
                        <Clock className="h-3.5 w-3.5 text-slate-400" />
                        <span>Stage History & Schedule Timeline:</span>
                      </span>
                      <span className="text-[11px] text-slate-500 hidden sm:inline">
                        Click any stage to view past/future configured setpoints
                      </span>
                    </div>

                    <div className="flex items-center gap-2 overflow-x-auto pb-1.5 no-scrollbar hide-scrollbar touch-pan-x">
                      {setpointsSnapshot.stages.map((st) => {
                        const isSelected = st.key === setpointsSnapshot.activeStageKey;
                        const isFilterActive = st.filterStatus === 'in_filter';
                        const isPast = st.filterStatus === 'past';
                        const isFuture = st.filterStatus === 'future';

                        return (
                          <button
                            key={st.key}
                            onClick={() => setSelectedStageKey(st.key)}
                            className={`flex items-center gap-2 rounded-xl px-3 py-2 text-xs transition-all shrink-0 text-left border ${isSelected
                                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50 shadow-md shadow-emerald-500/10 ring-1 ring-emerald-400/50 font-bold'
                                : isFilterActive
                                  ? 'bg-slate-800/90 text-white border-emerald-500/40 hover:bg-slate-800 font-semibold'
                                  : isPast
                                    ? 'bg-slate-900/60 text-slate-400 border-slate-800 hover:text-slate-200 hover:bg-slate-800/60'
                                    : 'bg-slate-900/40 text-slate-500 border-slate-800/80 hover:text-slate-300'
                              }`}
                          >
                            <div className="flex flex-col">
                              <div className="flex items-center gap-1.5">
                                <span className={`h-1.5 w-1.5 rounded-full ${isSelected ? 'bg-emerald-400' : isFilterActive ? 'bg-emerald-500' : isPast ? 'bg-slate-600' : 'bg-slate-700'}`} />
                                <span className="font-semibold">{st.name}</span>
                                {isFilterActive && (
                                  <span className="text-[9px] font-mono font-bold px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                                    In Filter
                                  </span>
                                )}
                                {st.isCurrentlyLive && !isFilterActive && (
                                  <span className="text-[9px] font-mono font-bold px-1.5 py-0.2 rounded bg-sky-500/20 text-sky-300 border border-sky-500/30">
                                    Live Today
                                  </span>
                                )}
                              </div>
                              <span className="text-[10px] text-slate-500 font-mono pt-0.5">
                                {st.start_date || '--'} → {st.end_date || '--'}
                              </span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Stage Details & Target vs Actual Compliance */}
                  {setpointsSnapshot.activeStage && (
                    <div className="space-y-3.5 pt-2 border-t border-slate-800/80">
                      {/* Stage Overview Banner */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                        {/* Target Temperature KPI */}
                        <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800 space-y-1">
                          <span className="text-[11px] text-slate-400 flex items-center justify-between font-semibold">
                            <span className="flex items-center gap-1.5 text-orange-400">
                              <Thermometer className="h-3.5 w-3.5" /> Target Temp (Avg)
                            </span>
                            <span className="text-slate-500 font-mono text-[10px]">
                              {setpointsSnapshot.activeStage.minTargetTemp}° - {setpointsSnapshot.activeStage.maxTargetTemp}°C
                            </span>
                          </span>
                          <div className="flex items-baseline justify-between pt-1">
                            <span className="text-2xl font-bold text-orange-400 font-mono">
                              {setpointsSnapshot.activeStage.avgTargetTemp}°C
                            </span>
                            {setpointsSnapshot.tempDelta !== null && (
                              <span className={`text-[11px] font-mono font-bold px-2 py-0.5 rounded ${setpointsSnapshot.tempCompliance === 'optimal'
                                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                                  : setpointsSnapshot.tempCompliance === 'warm'
                                    ? 'bg-orange-500/15 text-orange-400 border border-orange-500/30'
                                    : 'bg-blue-500/15 text-blue-400 border border-blue-500/30'
                                }`}>
                                {setpointsSnapshot.tempDelta > 0 ? `+${setpointsSnapshot.tempDelta}` : setpointsSnapshot.tempDelta}°C {setpointsSnapshot.tempCompliance === 'optimal' ? 'Optimal' : setpointsSnapshot.tempCompliance === 'warm' ? 'Above' : 'Below'}
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] text-slate-500 block pt-0.5">
                            Actual recorded avg: <strong className="text-slate-300">{activeSingleRoomStats?.temp.avg || '--'}°C</strong>
                          </span>
                        </div>

                        {/* Target Humidity KPI */}
                        <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800 space-y-1">
                          <span className="text-[11px] text-slate-400 flex items-center justify-between font-semibold">
                            <span className="flex items-center gap-1.5 text-blue-400">
                              <Droplets className="h-3.5 w-3.5" /> Target Humidity (Avg)
                            </span>
                            <span className="text-slate-500 font-mono text-[10px]">
                              {setpointsSnapshot.activeStage.minTargetHumi}% - {setpointsSnapshot.activeStage.maxTargetHumi}%
                            </span>
                          </span>
                          <div className="flex items-baseline justify-between pt-1">
                            <span className="text-2xl font-bold text-blue-400 font-mono">
                              {setpointsSnapshot.activeStage.avgTargetHumi}%
                            </span>
                            {setpointsSnapshot.humiDelta !== null && (
                              <span className={`text-[11px] font-mono font-bold px-2 py-0.5 rounded ${setpointsSnapshot.humiCompliance === 'optimal'
                                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                                  : setpointsSnapshot.humiCompliance === 'high'
                                    ? 'bg-blue-500/15 text-blue-400 border border-blue-500/30'
                                    : 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                                }`}>
                                {setpointsSnapshot.humiDelta > 0 ? `+${setpointsSnapshot.humiDelta}` : setpointsSnapshot.humiDelta}% {setpointsSnapshot.humiCompliance === 'optimal' ? 'Optimal' : setpointsSnapshot.humiCompliance === 'high' ? 'Humid' : 'Dry'}
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] text-slate-500 block pt-0.5">
                            Actual recorded avg: <strong className="text-slate-300">{activeSingleRoomStats?.humi.avg || '--'}%</strong>
                          </span>
                        </div>

                        {/* Stage Duration & Photoperiod */}
                        <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800 space-y-1">
                          <span className="text-[11px] text-slate-400 flex items-center gap-1.5 font-semibold">
                            <Sun className="h-3.5 w-3.5 text-amber-400" /> Photoperiod & Lighting
                          </span>
                          <div className="text-sm font-bold text-white font-mono pt-1">
                            {setpointsSnapshot.activeStage.photoperiod_on} → {setpointsSnapshot.activeStage.photoperiod_off}
                          </div>
                          <div className="text-[10px] text-slate-400 flex items-center gap-1.5 pt-0.5">
                            <span className={`h-1.5 w-1.5 rounded-full ${setpointsSnapshot.activeStage.lighting_enabled ? 'bg-emerald-400' : 'bg-slate-600'}`} />
                            <span>{setpointsSnapshot.activeStage.lighting_enabled ? 'Lighting Enabled' : 'Lighting Disabled'}</span>
                          </div>
                        </div>

                        {/* Stage Schedule Bounds */}
                        <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800 space-y-1">
                          <span className="text-[11px] text-slate-400 flex items-center gap-1.5 font-semibold">
                            <Calendar className="h-3.5 w-3.5 text-emerald-400" /> Stage Schedule Range
                          </span>
                          <div className="text-sm font-bold text-emerald-400 font-mono pt-1 truncate">
                            {setpointsSnapshot.activeStage.start_date} → {setpointsSnapshot.activeStage.end_date}
                          </div>
                          <span className="text-[10px] text-slate-400 block pt-0.5">
                            Status: <strong className="text-slate-200">{setpointsSnapshot.activeStage.filterStatus === 'in_filter' ? 'Active in Filter Range' : setpointsSnapshot.activeStage.filterStatus === 'past' ? 'Past / Historical Stage' : 'Future Scheduled Stage'}</strong>
                          </span>
                        </div>
                      </div>

                      {/* 5 Daily Time Slots Breakdown */}
                      <div className="space-y-2">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-slate-300 font-semibold flex items-center gap-1.5">
                            <Clock className="h-3.5 w-3.5 text-emerald-400" />
                            Daily 5-Slot Target Setpoints ({setpointsSnapshot.activeStage.name}):
                          </span>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2.5">
                          {setpointsSnapshot.activeStage.time_slots.map((slot, sIdx) => {
                            const isEnabled = slot.enabled !== false;
                            return (
                              <div
                                key={slot.id || sIdx}
                                className={`p-3 rounded-xl border transition-all ${isEnabled
                                    ? 'bg-slate-950/70 border-slate-800 hover:border-slate-700'
                                    : 'bg-slate-950/30 border-slate-900 opacity-60'
                                  }`}
                              >
                                <div className="flex items-center justify-between border-b border-slate-800/80 pb-1.5 mb-2">
                                  <span className="text-xs font-bold text-white truncate">{slot.name || `Slot ${sIdx + 1}`}</span>
                                  <span className="text-[9.5px] font-mono text-slate-400 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                                    {slot.start} - {slot.stop}
                                  </span>
                                </div>

                                <div className="space-y-1.5 text-xs font-mono">
                                  <div className="flex items-center justify-between">
                                    <span className="text-[10px] text-slate-400">Target Temp:</span>
                                    <span className="font-bold text-orange-400">{slot.t_set}°C</span>
                                  </div>
                                  <div className="text-[9px] text-slate-500 flex items-center justify-between">
                                    <span>Band:</span>
                                    <span>{slot.t_min ?? slot.t_set}° → {slot.t_max ?? slot.t_set}°C</span>
                                  </div>

                                  <div className="flex items-center justify-between pt-1 border-t border-slate-900">
                                    <span className="text-[10px] text-slate-400">Target Humi:</span>
                                    <span className="font-bold text-blue-400">{slot.h_set}%</span>
                                  </div>
                                  <div className="text-[9px] text-slate-500 flex items-center justify-between">
                                    <span>Band:</span>
                                    <span>{slot.h_min ?? slot.h_set}% → {slot.h_max ?? slot.h_set}%</span>
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  )}
                </motion.div>
              )}
            </div>
          )}

          {/* B. ALL ROOMS COMPARATIVE ANALYSIS VIEW */}
          {(!selectedRoom || selectedRoom === 'all') && (
            <div className="space-y-6">
              {/* Overview Mode & Header Switcher */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between p-4 rounded-2xl bg-slate-900/80 border border-slate-800 shadow-md gap-3">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400">
                    <Sparkles className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white">Cold Storage 7-Room Comparative Matrix</h3>
                    <p className="text-xs text-slate-400">Live & statistical comparison across all storage rooms (S1 to S7)</p>
                  </div>
                </div>

                <div className="flex items-center gap-2 self-end sm:self-center">
                  <button
                    onClick={() => setColdOverviewMode('matrix')}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${coldOverviewMode === 'matrix'
                      ? 'bg-emerald-500 text-slate-950 font-bold shadow-sm'
                      : 'bg-slate-800 text-slate-400 hover:text-white border border-slate-700'
                      }`}
                  >
                    <BarChart3 className="h-3.5 w-3.5" />
                    <span>Multi-Room Charts & Matrix</span>
                  </button>

                </div>
              </div>

              {/* 1. 7-ROOM COMPARISON MATRIX CARDS */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3.5">
                {['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].map((sKey) => {
                  const rName = coldRoomNames[sKey] || DEFAULT_COLD_ROOM_NAMES[sKey] || sKey;
                  const st = roomWiseAnalysis.stats[sKey];
                  const colors = COLD_ROOM_COLORS[sKey] || COLD_ROOM_COLORS.S1;
                  const hasData = st?.hasData;

                  return (
                    <div
                      key={sKey}
                      className={`rounded-2xl border p-4 backdrop-blur-md transition-all hover:scale-[1.01] flex flex-col justify-between space-y-3.5 shadow-md ${hasData ? `${colors.bg} ${colors.border}` : 'bg-slate-900/50 border-slate-800/80 opacity-70'
                        }`}
                    >
                      {/* Room Header */}
                      <div className="flex items-center justify-between border-b border-slate-700/40 pb-2.5">
                        <div className="flex items-center gap-2 truncate pr-2">
                          <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: colors.stroke }} />
                          <span className="font-bold text-white text-xs truncate">{rName}</span>
                        </div>
                        <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-900/90 text-slate-200 border border-slate-700 shrink-0">
                          {sKey}
                        </span>
                      </div>

                      {/* Metrics: Temperature & Humidity Dual Grid */}
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        {/* Temp Block */}
                        <div className="p-2.5 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-1">
                          <span className="text-[10px] text-slate-400 flex items-center gap-1 font-semibold uppercase">
                            <Thermometer className="h-3 w-3 text-orange-400" /> Temp
                          </span>
                          <div className="font-bold text-orange-400 text-sm font-mono">
                            {st ? `${st.temp.avg}°C` : '--'}
                          </div>
                          <div className="text-[9.5px] text-slate-400 font-mono flex items-center justify-between pt-0.5">
                            <span>{st?.temp.min}°</span>
                            <span className="text-slate-500">→</span>
                            <span>{st?.temp.max}°</span>
                          </div>
                        </div>

                        {/* Humidity Block */}
                        <div className="p-2.5 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-1">
                          <span className="text-[10px] text-slate-400 flex items-center gap-1 font-semibold uppercase">
                            <Droplets className="h-3 w-3 text-blue-400" /> Humidity
                          </span>
                          <div className="font-bold text-blue-400 text-sm font-mono">
                            {st ? `${st.humi.avg}%` : '--'}
                          </div>
                          <div className="text-[9.5px] text-slate-400 font-mono flex items-center justify-between pt-0.5">
                            <span>{st?.humi.min}%</span>
                            <span className="text-slate-500">→</span>
                            <span>{st?.humi.max}%</span>
                          </div>
                        </div>
                      </div>

                      {/* Setpoint Target Quick Snapshot */}
                      {(() => {
                        const rSetps = getRoomSetpoints(sKey);
                        const curStage = (rSetps?.settings && rSetps.settings[rSetps.active_setting || 'Setting A']) || {};
                        const slots = (curStage.time_slots || []).filter(s => s.enabled !== false);
                        const avgT = slots.length > 0 ? (slots.reduce((acc, s) => acc + (Number(s.t_set) || 0), 0) / slots.length).toFixed(1) : null;
                        const avgH = slots.length > 0 ? (slots.reduce((acc, s) => acc + (Number(s.h_set) || 0), 0) / slots.length).toFixed(1) : null;

                        if (!avgT && !avgH) return null;
                        return (
                          <div className="flex items-center justify-between text-[10.5px] font-mono px-2 py-1 rounded-lg bg-slate-950/80 border border-slate-800 text-slate-400">
                            <span className="flex items-center gap-1 text-slate-400">
                              <Target className="h-3 w-3 text-emerald-400" /> Target:
                            </span>
                            <span className="text-slate-200 font-semibold">
                              {avgT ? `${avgT}°C` : '--'} &bull; {avgH ? `${avgH}%` : '--'}
                            </span>
                          </div>
                        );
                      })()}

                      {/* Card Action Buttons */}
                      <div className="flex items-center gap-1.5 pt-1 border-t border-slate-700/40">
                        <button
                          onClick={() => setSelectedRoom(sKey)}
                          className="flex-1 py-1.5 px-2 rounded-xl bg-slate-900/90 hover:bg-slate-800 border border-slate-700 text-[11px] font-semibold text-slate-200 hover:text-white transition-colors flex items-center justify-center gap-1"
                          title={`Focus analysis on ${rName}`}
                        >
                          <Eye className="h-3 w-3 text-emerald-400" />
                          <span>Focus</span>
                        </button>
                        <button
                          onClick={() => downloadColdRoomSingleCSV(rawFeeds, sKey, rName, filterLabel, selectedDevice?.name || 'Device')}
                          disabled={!hasData}
                          className="py-1.5 px-2 rounded-xl bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/30 text-[11px] font-bold text-emerald-300 transition-colors flex items-center justify-center gap-1 disabled:opacity-30"
                          title={`Download Telemetry CSV for ${rName}`}
                        >
                          <Download className="h-3 w-3" />
                          <span>CSV</span>
                        </button>
                        <button
                          onClick={() => downloadRoomSetpointsCSV(sKey, rName, getRoomSetpoints(sKey), selectedDevice?.name || 'Device')}
                          className="py-1.5 px-2 rounded-xl bg-slate-800/90 hover:bg-slate-700 border border-slate-700 text-[11px] font-semibold text-slate-300 hover:text-white transition-colors flex items-center justify-center gap-1"
                          title={`Download Setpoints Schedule CSV for ${rName}`}
                        >
                          <Target className="h-3 w-3 text-emerald-400" />
                          <span>Setpoints</span>
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* 2. SYNCHRONIZED MULTI-ROOM COMPARISON CHARTS (TEMPERATURE & HUMIDITY) */}
              {coldOverviewMode === 'matrix' && roomWiseAnalysis.multiRoomData.length > 0 && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                  {/* Multi-Room Temperature Chart */}
                  <div className="rounded-2xl border border-slate-800/90 bg-slate-900/80 p-4 sm:p-5 backdrop-blur-md shadow-xl space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="p-2 rounded-lg bg-orange-500/10 text-orange-400">
                          <Thermometer className="h-4.5 w-4.5" />
                        </div>
                        <div>
                          <h4 className="text-sm font-bold text-white">Multi-Room Temperature Comparison</h4>
                          <p className="text-[10px] text-slate-400">{chartSubtitle} &bull; S1 through S7 Overlay</p>
                        </div>
                      </div>
                      <span className="text-xs font-mono font-bold text-orange-400 bg-orange-500/10 px-2 py-0.5 rounded border border-orange-500/20">
                        °C
                      </span>
                    </div>

                    <div className="h-64 w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={roomWiseAnalysis.multiRoomData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                          <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#64748b' }} axisLine={{ stroke: '#334155' }} tickLine={false} />
                          <YAxis tick={{ fontSize: 10, fill: '#64748b' }} axisLine={{ stroke: '#334155' }} tickLine={false} domain={['auto', 'auto']} />
                          <Tooltip content={<MultiRoomTooltip unit="°C" coldRoomNames={coldRoomNames} />} />
                          <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                          {['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].map(sKey => (
                            <Line
                              key={sKey}
                              type="monotone"
                              dataKey={`${sKey}_Temp`}
                              name={`${sKey} (${coldRoomNames[sKey] || DEFAULT_COLD_ROOM_NAMES[sKey]})`}
                              stroke={COLD_ROOM_COLORS[sKey]?.stroke || '#38bdf8'}
                              strokeWidth={2}
                              dot={false}
                              isAnimationActive={false}
                            />
                          ))}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  {/* Multi-Room Humidity Chart */}
                  <div className="rounded-2xl border border-slate-800/90 bg-slate-900/80 p-4 sm:p-5 backdrop-blur-md shadow-xl space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="p-2 rounded-lg bg-blue-500/10 text-blue-400">
                          <Droplets className="h-4.5 w-4.5" />
                        </div>
                        <div>
                          <h4 className="text-sm font-bold text-white">Multi-Room Humidity Comparison</h4>
                          <p className="text-[10px] text-slate-400">{chartSubtitle} &bull; S1 through S7 Overlay</p>
                        </div>
                      </div>
                      <span className="text-xs font-mono font-bold text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">
                        %
                      </span>
                    </div>

                    <div className="h-64 w-full">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={roomWiseAnalysis.multiRoomData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                          <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#64748b' }} axisLine={{ stroke: '#334155' }} tickLine={false} />
                          <YAxis tick={{ fontSize: 10, fill: '#64748b' }} axisLine={{ stroke: '#334155' }} tickLine={false} domain={['auto', 'auto']} />
                          <Tooltip content={<MultiRoomTooltip unit="%" coldRoomNames={coldRoomNames} />} />
                          <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                          {['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].map(sKey => (
                            <Line
                              key={sKey}
                              type="monotone"
                              dataKey={`${sKey}_Humi`}
                              name={`${sKey} (${coldRoomNames[sKey] || DEFAULT_COLD_ROOM_NAMES[sKey]})`}
                              stroke={COLD_ROOM_COLORS[sKey]?.stroke || '#38bdf8'}
                              strokeWidth={2}
                              dot={false}
                              isAnimationActive={false}
                            />
                          ))}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── STANDARD SUMMARY METRIC CARDS (Non-Cold or Individual Channel Breakdown) ── */}
      {(!isCold || (isCold && coldOverviewMode === 'individual' && !isSingleColdRoom)) && (
        <>
          {loading ? (
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
            </div>
          ) : (
            <motion.div
              variants={stagger}
              initial="hidden"
              animate="show"
              className="grid grid-cols-2 gap-4 lg:grid-cols-4"
            >
              {summaryMetrics.map((metric, i) => (
                <motion.div
                  key={i}
                  variants={{ hidden: { opacity: 0, y: 20 }, show: { opacity: 1, y: 0 } }}
                  className={`rounded-2xl border p-5 backdrop-blur-md transition-all hover:scale-[1.01] ${metric.bg}`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className={`rounded-lg p-2 ${metric.color} bg-white/5`}>
                        <metric.icon className="h-4 w-4" />
                      </div>
                      <p className="text-xs font-semibold text-slate-300 truncate">{metric.name}</p>
                    </div>
                    <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 bg-slate-900/60 px-2 py-0.5 rounded-md border border-slate-700/50">
                      Avg
                    </span>
                  </div>

                  <div className="mt-3 flex items-baseline gap-1.5">
                    <span className={`text-2xl font-bold tabular-nums ${metric.color}`}>
                      {metric.value}
                    </span>
                    <span className="text-xs font-medium text-slate-400">{metric.unit}</span>
                  </div>

                  <div className="mt-3 pt-3 border-t border-slate-700/40 flex items-center justify-between text-[11px] text-slate-400">
                    <div className="flex items-center gap-1">
                      <span className="text-slate-400 font-medium">Min:</span>
                      <span className="text-slate-300 font-semibold">{metric.min} {metric.unit}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="text-slate-400 font-medium">Max:</span>
                      <span className="text-slate-300 font-semibold">{metric.max} {metric.unit}</span>
                    </div>
                  </div>
                </motion.div>
              ))}
            </motion.div>
          )}
        </>
      )}

      {/* ── CHARTS CONTAINER ── */}
      {loading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="rounded-2xl border border-slate-700/30 bg-slate-800/30 p-4">
              <div className="skeleton mb-4 h-4 w-32 rounded" />
              <div className="skeleton h-48 w-full rounded-xl" />
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-red-500/50 bg-red-500/5 py-20">
          <WifiOff className="h-12 w-12 text-red-400 mb-4" />
          <p className="text-sm font-medium text-red-400">Unable to load charts due to an error</p>
          <p className="mt-1 text-xs text-red-400/70">Please check your database device configuration or connection</p>
        </div>
      ) : rawFeeds.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-700/50 py-20">
          <Calendar className="h-12 w-12 text-slate-700" />
          <p className="mt-4 text-sm text-slate-500">No data available for the selected time range</p>
          <p className="mt-1 text-xs text-slate-600">Try selecting a different date or time range</p>
        </div>
      ) : (
        /* Render individual charts for Non-Cold devices, single room focus, or when in individual mode */
        (!isCold || coldOverviewMode === 'individual' || isSingleColdRoom) && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {channelFields.map(f => {
              const meta = getFieldMeta(f.name);
              return (
                <LiveChart key={f.key} data={chartData[f.key]} type={meta.type} title={`${f.name} Trend`} unit={meta.unit} subtitle={chartSubtitle} />
              );
            })}
          </div>
        )
      )}

      {/* ── COLD STORAGE ROOM-BY-ROOM STATISTICAL SUMMARY TABLE ── */}
      {!loading && isCold && rawFeeds.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="overflow-x-auto rounded-2xl border border-slate-700/60 bg-slate-800/40 backdrop-blur-md shadow-xl"
        >
          <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-700/60 px-6 py-4 bg-slate-800/60 gap-3">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400">
                <FileSpreadsheet className="h-4 w-4" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Cold Storage Room-by-Room Statistical Breakdown</h3>
                <p className="text-xs text-slate-400">Comprehensive room-wise temperature and humidity aggregation</p>
              </div>
            </div>

          </div>

          <table className="w-full text-sm min-w-[640px]">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-900/40 text-xs uppercase tracking-wider text-slate-400 font-bold">
                <th className="px-6 py-3.5 text-left">Room / Chamber</th>
                <th className="px-6 py-3.5 text-left">Avg Temp (°C)</th>
                <th className="px-6 py-3.5 text-left">Min - Max Temp</th>
                <th className="px-6 py-3.5 text-left">Avg Humidity (%)</th>
                <th className="px-6 py-3.5 text-left">Min - Max Humidity</th>
                <th className="px-6 py-3.5 text-right">Quick Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/30 font-mono text-xs">
              {['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].map((sKey) => {
                const rName = coldRoomNames[sKey] || DEFAULT_COLD_ROOM_NAMES[sKey] || sKey;
                const st = roomWiseAnalysis.stats[sKey];
                const colors = COLD_ROOM_COLORS[sKey] || COLD_ROOM_COLORS.S1;
                const hasData = st?.hasData;

                return (
                  <tr key={sKey} className="hover:bg-slate-700/30 transition-colors">
                    <td className="px-6 py-3.5 font-sans font-semibold text-white flex items-center gap-2">
                      <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: colors.stroke }} />
                      <span className="font-mono text-xs font-bold text-slate-300">{sKey}:</span>
                      <span>{rName}</span>
                    </td>
                    <td className="px-6 py-3.5 text-orange-400 font-bold tabular-nums">
                      {st ? `${st.temp.avg}°C` : '--'}
                    </td>
                    <td className="px-6 py-3.5 text-slate-300 tabular-nums">
                      {st && st.temp.min !== '--' ? `[${st.temp.min}° - ${st.temp.max}°]` : '--'}
                    </td>
                    <td className="px-6 py-3.5 text-blue-400 font-bold tabular-nums">
                      {st ? `${st.humi.avg}%` : '--'}
                    </td>
                    <td className="px-6 py-3.5 text-slate-300 tabular-nums">
                      {st && st.humi.min !== '--' ? `[${st.humi.min}% - ${st.humi.max}%]` : '--'}
                    </td>
                    <td className="px-6 py-3.5 text-right font-sans">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => setSelectedRoom(sKey)}
                          className="px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-700 text-slate-300 hover:text-white hover:border-emerald-500 text-xs font-semibold transition-colors"
                        >
                          Inspect
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </motion.div>
      )}

      {/* ── STANDARD DATA SUMMARY TABLE (For non-cold devices) ── */}
      {!loading && !isCold && rawFeeds.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="overflow-x-auto rounded-2xl border border-slate-700/60 bg-slate-800/40 backdrop-blur-md shadow-xl scrollbar-thin scrollbar-thumb-slate-700"
        >
          <div className="flex items-center justify-between border-b border-slate-700/60 px-6 py-4 bg-slate-800/60">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Activity className="h-4 w-4 text-green-400" /> Statistical Telemetry Summary
            </h3>
            <span className="rounded-full bg-slate-700/60 border border-slate-600/50 px-3 py-1 text-xs font-semibold text-slate-300">
              {(totalDbPoints > 0 ? totalDbPoints : rawFeeds.length).toLocaleString()} Total Readings
            </span>
          </div>
          <table className="w-full text-sm min-w-[540px]">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-900/40">
                <th className="px-6 py-3.5 text-left text-xs font-bold uppercase tracking-wider text-slate-400">Sensor Metric</th>
                <th className="px-6 py-3.5 text-left text-xs font-bold uppercase tracking-wider text-slate-400">Average Reading</th>
                <th className="px-6 py-3.5 text-left text-xs font-bold uppercase tracking-wider text-slate-400">Minimum Reading</th>
                <th className="px-6 py-3.5 text-left text-xs font-bold uppercase tracking-wider text-slate-400">Maximum Reading</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/30">
              {channelFields.map((f) => {
                const meta = getFieldMeta(f.name);
                const stats = summaryStats[f.key] || { avg: '--', min: '--', max: '--' };
                return (
                  <tr key={f.key} className="hover:bg-slate-700/30 transition-colors">
                    <td className="px-6 py-4 font-semibold text-white flex items-center gap-2">
                      <meta.icon className="h-4 w-4 text-green-400" />
                      {f.name}
                    </td>
                    <td className="px-6 py-4 text-green-400 font-bold tabular-nums">
                      {stats.avg} <span className="text-xs text-slate-500 font-normal">{meta.unit}</span>
                    </td>
                    <td className="px-6 py-4 text-cyan-400 font-bold tabular-nums">
                      {stats.min} <span className="text-xs text-slate-500 font-normal">{meta.unit}</span>
                    </td>
                    <td className="px-6 py-4 text-orange-400 font-bold tabular-nums">
                      {stats.max} <span className="text-xs text-slate-500 font-normal">{meta.unit}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </motion.div>
      )}

      {/* ── SETPOINTS & COMPLIANCE EXPORT CENTER MODAL ── */}
      <AnimatePresence>
        {showSetpointsExportModal && isCold && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/70 backdrop-blur-sm"
              onClick={() => setShowSetpointsExportModal(false)}
            />

            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="relative z-10 w-full max-w-2xl rounded-2xl border border-slate-700/80 bg-slate-900/98 p-5 sm:p-6 shadow-2xl backdrop-blur-xl space-y-5 max-h-[90vh] overflow-y-auto"
            >
              {/* Modal Header */}
              <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-xl bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                    <Target className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-white flex items-center gap-2">
                      Cold Storage Setpoints & Compliance Export Hub
                    </h3>
                    <p className="text-xs text-slate-400">
                      Download scheduled targets, stage profiles, or historical compliance audit reports
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setShowSetpointsExportModal(false)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                >
                  <span className="text-lg font-bold">&times;</span>
                </button>
              </div>

              {/* Step 1: Select Room Target */}
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-300 flex items-center justify-between">
                  <span>1. Select Chamber / Room:</span>
                  <span className="text-[11px] text-slate-400 font-normal">
                    Target: <strong className="text-emerald-400">{exportModalRoom === 'all' ? 'All 7 Chambers' : `${exportModalRoom} - ${coldRoomNames[exportModalRoom] || exportModalRoom}`}</strong>
                  </span>
                </label>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <button
                    type="button"
                    onClick={() => setExportModalRoom('all')}
                    className={`px-3 py-2 rounded-xl text-xs font-bold border transition-all text-center ${exportModalRoom === 'all'
                        ? 'bg-emerald-500 text-slate-950 border-emerald-400 shadow-md font-bold'
                        : 'bg-slate-800/80 text-slate-300 border-slate-700 hover:bg-slate-800'
                      }`}
                  >
                    All 7 Chambers
                  </button>
                  {['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].map(rk => {
                    const rName = coldRoomNames[rk] || DEFAULT_COLD_ROOM_NAMES[rk] || rk;
                    const isSelected = exportModalRoom === rk;
                    return (
                      <button
                        key={rk}
                        type="button"
                        onClick={() => setExportModalRoom(rk)}
                        className={`px-3 py-2 rounded-xl text-xs font-semibold border transition-all flex items-center justify-between truncate ${isSelected
                            ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/60 ring-1 ring-emerald-500 font-bold'
                            : 'bg-slate-800/80 text-slate-300 border-slate-700 hover:bg-slate-800'
                          }`}
                      >
                        <span className="font-mono text-emerald-400 font-bold">{rk}</span>
                        <span className="text-[11px] truncate pl-1">{rName}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Step 2: Select Export Type */}
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-300">
                  2. Choose Export Format & Content:
                </label>
                <div className="space-y-2">
                  {/* Option A: Target vs Actual Variance Audit */}
                  <label
                    onClick={() => setExportModalType('audit')}
                    className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${exportModalType === 'audit'
                        ? 'bg-emerald-500/15 border-emerald-500/60 ring-1 ring-emerald-500/40'
                        : 'bg-slate-800/40 border-slate-700 hover:bg-slate-800/70'
                      }`}
                  >
                    <input
                      type="radio"
                      name="exportType"
                      checked={exportModalType === 'audit'}
                      onChange={() => setExportModalType('audit')}
                      className="mt-1 text-emerald-500 focus:ring-0"
                    />
                    <div className="space-y-0.5 flex-1">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-white flex items-center gap-1.5">
                          <Activity className="h-3.5 w-3.5 text-orange-400" />
                          Target vs Actual Variance & Compliance Audit (.csv)
                        </span>
                        <span className="text-[10px] font-mono font-bold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.2 rounded border border-emerald-500/20">
                          Recommended
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed">
                        Matches every recorded sensor reading in the selected filter ({chartSubtitle}) with scheduled target setpoints, tolerance bounds, and calculates compliance deltas.
                      </p>
                    </div>
                  </label>

                  {/* Option B: Full Room Setpoints Schedule */}
                  <label
                    onClick={() => setExportModalType('room_schedule')}
                    className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${exportModalType === 'room_schedule'
                        ? 'bg-emerald-500/15 border-emerald-500/60 ring-1 ring-emerald-500/40'
                        : 'bg-slate-800/40 border-slate-700 hover:bg-slate-800/70'
                      }`}
                  >
                    <input
                      type="radio"
                      name="exportType"
                      checked={exportModalType === 'room_schedule'}
                      onChange={() => setExportModalType('room_schedule')}
                      className="mt-1 text-emerald-500 focus:ring-0"
                    />
                    <div className="space-y-0.5 flex-1">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-white flex items-center gap-1.5">
                          <FileSpreadsheet className="h-3.5 w-3.5 text-sky-400" />
                          Full 10-Stage Setpoints Schedule (.csv)
                        </span>
                        <span className="text-[10px] font-mono text-slate-400">Stages A to J</span>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed">
                        Exports the complete crop calendar: all 10 stages with their 5 daily time slot targets (Temp, Humidity, Lighting, Photoperiod).
                      </p>
                    </div>
                  </label>

                  {/* Option C: Active Stage Only */}
                  {exportModalRoom !== 'all' && (
                    <label
                      onClick={() => setExportModalType('active_stage')}
                      className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${exportModalType === 'active_stage'
                          ? 'bg-emerald-500/15 border-emerald-500/60 ring-1 ring-emerald-500/40'
                          : 'bg-slate-800/40 border-slate-700 hover:bg-slate-800/70'
                        }`}
                    >
                      <input
                        type="radio"
                        name="exportType"
                        checked={exportModalType === 'active_stage'}
                        onChange={() => setExportModalType('active_stage')}
                        className="mt-1 text-emerald-500 focus:ring-0"
                      />
                      <div className="space-y-0.5 flex-1">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-white flex items-center gap-1.5">
                            <Clock className="h-3.5 w-3.5 text-emerald-400" />
                            Active Filter Stage Schedule Only (.csv)
                          </span>
                          <span className="text-[10px] font-mono text-emerald-400 font-bold">
                            {setpointsSnapshot?.activeStage?.name || 'Current Stage'}
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-400 leading-relaxed">
                          Exports just the stage scheduled during the current active date filter window.
                        </p>
                      </div>
                    </label>
                  )}

                  {/* Option D: Program JSON Configuration */}
                  <label
                    onClick={() => setExportModalType('json')}
                    className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${exportModalType === 'json'
                        ? 'bg-emerald-500/15 border-emerald-500/60 ring-1 ring-emerald-500/40'
                        : 'bg-slate-800/40 border-slate-700 hover:bg-slate-800/70'
                      }`}
                  >
                    <input
                      type="radio"
                      name="exportType"
                      checked={exportModalType === 'json'}
                      onChange={() => setExportModalType('json')}
                      className="mt-1 text-emerald-500 focus:ring-0"
                    />
                    <div className="space-y-0.5 flex-1">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-white flex items-center gap-1.5">
                          <FileText className="h-3.5 w-3.5 text-purple-400" />
                          Complete Setpoint JSON Backup (.json)
                        </span>
                        <span className="text-[10px] font-mono text-sky-400 font-bold bg-sky-500/10 px-1.5 py-0.2 rounded border border-sky-500/20">
                          JSON Schema
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed">
                        Full machine-readable JSON containing entire program definition, crop details, stages, and safety limits.
                      </p>
                    </div>
                  </label>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowSetpointsExportModal(false)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                >
                  Cancel
                </button>

                <button
                  type="button"
                  onClick={() => {
                    const devName = selectedDevice?.name || 'Device';
                    const devSlug = sanitizeFileName(devName);
                    const dateStr = new Date().toISOString().split('T')[0];

                    if (exportModalType === 'audit') {
                      if (exportModalRoom === 'all') {
                        downloadAllRoomsTargetVsActualComplianceCSV(rawFeeds, allSetpoints, coldRoomNames, filterLabel, devName);
                      } else {
                        const rName = coldRoomNames[exportModalRoom] || DEFAULT_COLD_ROOM_NAMES[exportModalRoom] || exportModalRoom;
                        downloadTargetVsActualComplianceCSV(rawFeeds, exportModalRoom, rName, getRoomSetpoints(exportModalRoom), filterLabel, devName);
                      }
                    } else if (exportModalType === 'room_schedule') {
                      if (exportModalRoom === 'all') {
                        downloadAllRoomsSetpointsCSV(allSetpoints, coldRoomNames, devName);
                      } else {
                        const rName = coldRoomNames[exportModalRoom] || DEFAULT_COLD_ROOM_NAMES[exportModalRoom] || exportModalRoom;
                        downloadRoomSetpointsCSV(exportModalRoom, rName, getRoomSetpoints(exportModalRoom), devName);
                      }
                    } else if (exportModalType === 'active_stage') {
                      const curRoom = exportModalRoom === 'all' ? 'S1' : exportModalRoom;
                      const rName = coldRoomNames[curRoom] || DEFAULT_COLD_ROOM_NAMES[curRoom] || curRoom;
                      const rSetps = getRoomSetpoints(curRoom);
                      const curStageKey = selectedStageKey || setpointsSnapshot?.activeStageKey || 'Setting A';
                      const curStageData = (rSetps?.settings && rSetps.settings[curStageKey]) || setpointsSnapshot?.activeStage;
                      downloadSingleStageSetpointsCSV(curRoom, rName, curStageKey, curStageData, rSetps, devName);
                    } else if (exportModalType === 'json') {
                      if (exportModalRoom === 'all') {
                        downloadSetpointsJSON(allSetpoints, `${devSlug}_All_7_Chambers_Setpoints_${dateStr}.json`);
                      } else {
                        const rName = coldRoomNames[exportModalRoom] || DEFAULT_COLD_ROOM_NAMES[exportModalRoom] || exportModalRoom;
                        const roomSlug = sanitizeFileName(`${exportModalRoom}_${rName}`);
                        downloadSetpointsJSON(getRoomSetpoints(exportModalRoom), `${devSlug}_${roomSlug}_Setpoints_${dateStr}.json`);
                      }
                    }

                    setShowSetpointsExportModal(false);
                  }}
                  className="flex items-center gap-2 px-5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-bold transition-all shadow-lg shadow-emerald-500/20"
                >
                  <Download className="h-4 w-4" />
                  <span>Download File Now</span>
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default AnalyticsPage;