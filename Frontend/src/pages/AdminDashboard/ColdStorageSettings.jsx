import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
  Save, RefreshCw, ChevronDown, Server, Thermometer, Droplets, Activity,
  Wind, Sun, Clock, Calendar, Plus, Trash2, Edit3, Sliders, Power, Zap,
  CheckCircle2, X, Bell, Bookmark, RotateCcw, AlertTriangle, ChevronRight,
  ChevronLeft, Sparkles, Check, Sprout, Layers, RotateCw, PowerOff
} from 'lucide-react';
import { createMqttClient } from '../../utils/mqtt';

// --- NUMBER & TIME FORMATTING HELPERS ---
const safeNum = (val, fallback = 0) => {
  if (val === null || val === undefined || val === '') return fallback;
  const n = parseFloat(val);
  return isNaN(n) ? fallback : n;
};

const safeFixed = (val, digits = 1, fallback = '--') => {
  if (val === null || val === undefined || val === '') return fallback;
  const n = Number(val);
  return isNaN(n) ? fallback : n.toFixed(digits);
};

const formatTime12h = (tStr) => {
  if (!tStr) return '12:00 AM';
  const s = String(tStr).trim();
  if (s.toUpperCase().includes('AM') || s.toUpperCase().includes('PM')) {
    return s.toUpperCase();
  }
  try {
    const parts = s.split(':');
    let hh = parseInt(parts[0], 10);
    const mm = parseInt(parts[1] || '0', 10);
    const meridiem = hh >= 12 ? 'PM' : 'AM';
    hh = hh % 12;
    if (hh === 0) hh = 12;
    return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')} ${meridiem}`;
  } catch {
    return s;
  }
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
  return h * 60 + m;
};

const formatUploadHmsDisplay = (hours = 0, mins = 0, secs = 0, totalMin = 0) => {
  let h = Number(hours) || 0;
  let m = Number(mins) || 0;
  let s = Number(secs) || 0;
  let totalSec = (h * 3600) + (m * 60) + s;
  if (totalSec <= 0 && totalMin > 0) {
    totalSec = Math.round(Number(totalMin) * 60);
    h = Math.floor(totalSec / 3600);
    const rem = totalSec % 3600;
    m = Math.floor(rem / 60);
    s = rem % 60;
  }
  if (totalSec <= 1) return '1s (Stream)';
  const parts = [];
  if (h > 0) parts.push(`${h}h`);
  if (m > 0) parts.push(`${m}m`);
  if (s > 0) parts.push(`${s}s`);
  return `${parts.join(' ')} (${totalSec}s)`;
};

const checkTimeSlotOverlaps = (slots) => {
  const enabledSlots = (slots || []).filter(s => s.enabled !== false);
  const warnings = [];
  const parsed = [];

  enabledSlots.forEach((slot, idx) => {
    let sMin = timeToMinutes(slot.start || '00:00');
    let eMin = timeToMinutes(slot.stop || '23:59');
    if (eMin <= sMin) eMin += 1440;
    parsed.push({ idx: idx + 1, name: slot.name || `Slot ${idx + 1}`, sMin, eMin });
  });

  for (let i = 0; i < parsed.length; i++) {
    for (let j = i + 1; j < parsed.length; j++) {
      const a = parsed[i];
      const b = parsed[j];
      if (Math.max(a.sMin, b.sMin) < Math.min(a.eMin, b.eMin)) {
        warnings.push(`Slot "${a.name}" & "${b.name}" overlap in time window.`);
      }
    }
  }
  return warnings;
};

// --- DATE FORMATTING HELPERS (DD-MM-YYYY) ---
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

const formatIsoDate = (d) => {
  if (!d) return '';
  const dateObj = (d instanceof Date) ? d : parseIsoOrDmy(d);
  if (!dateObj || isNaN(dateObj.getTime())) return '';
  const day = String(dateObj.getDate()).padStart(2, '0');
  const month = String(dateObj.getMonth() + 1).padStart(2, '0');
  const year = dateObj.getFullYear();
  return `${year}-${month}-${day}`;
};

// --- ALMORA DEFAULTS ---
const ALL_SETTING_KEYS = [
  'Setting A', 'Setting B', 'Setting C', 'Setting D', 'Setting E',
  'Setting F', 'Setting G', 'Setting H', 'Setting I', 'Setting J'
];

const SENSOR_KEYS = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'];

const DEFAULT_ROOM_NAMES = {
  S1: 'Cold Room 1',
  S2: 'Cold Room 2',
  S3: 'Cold Room 3',
  S4: 'Cold Room 4',
  S5: 'Cold Room 5',
  S6: 'Cold Room 6',
  S7: 'Greenhouse'
};

const generateDefaultAlmoraSchedule = (sKey = 'S1') => {
  const defaultCrop = `${DEFAULT_ROOM_NAMES[sKey] || sKey} Program`;
  const defaultSetup = `${DEFAULT_ROOM_NAMES[sKey] || sKey} Setup`;

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

const autoChainDates = (settingsDict, changedKey) => {
  const newSettings = JSON.parse(JSON.stringify(settingsDict || {}));
  const stages = ALL_SETTING_KEYS.filter(k => k in newSettings);
  const startIdx = stages.indexOf(changedKey);
  if (startIdx === -1) return newSettings;

  const cur = newSettings[changedKey];
  let curStart = parseIsoOrDmy(cur.start_date);
  let curEnd = parseIsoOrDmy(cur.end_date);
  if (!curStart || !curEnd) return newSettings;
  if (curEnd < curStart) {
    curEnd = new Date(curStart);
    cur.end_date = formatDmy(curEnd);
  }

  for (let i = startIdx; i < stages.length - 1; i++) {
    const cKey = stages[i];
    const nKey = stages[i + 1];
    const cObj = newSettings[cKey];
    const nObj = newSettings[nKey];
    if (!cObj || !nObj) continue;

    const cEndD = parseIsoOrDmy(cObj.end_date);
    const nStartOrig = parseIsoOrDmy(nObj.start_date);
    const nEndOrig = parseIsoOrDmy(nObj.end_date);

    let durationDays = 14;
    if (nStartOrig && nEndOrig && nEndOrig >= nStartOrig) {
      durationDays = Math.max(1, Math.round((nEndOrig - nStartOrig) / (1000 * 60 * 60 * 24)) + 1);
    }

    const nextStart = new Date(cEndD);
    nextStart.setDate(nextStart.getDate() + 1);

    const nextEnd = new Date(nextStart);
    nextEnd.setDate(nextEnd.getDate() + durationDays - 1);

    nObj.start_date = formatDmy(nextStart);
    nObj.end_date = formatDmy(nextEnd);
  }

  return newSettings;
};



const ColdStorageSettings = () => {
  // Device & API State
  const queryParams = new URLSearchParams(window.location.search);
  const paramMqtt = queryParams.get('mqttId');
  const paramDev = queryParams.get('device');

  const [devices, setDevices] = useState([]);
  const [selectedMqttId, setSelectedMqttId] = useState(paramMqtt || 'cold_room');
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState('connected');
  const [statusMsg, setStatusMsg] = useState('');
  const [client, setClient] = useState(null);
  const [isMachineOnline, setIsMachineOnline] = useState(false);
  const lastTelemetryTimeRef = useRef(null);
  const lastChartUpdateRef = useRef(0);

  // Setpoints & System Configuration
  const [allSetpoints, setAllSetpoints] = useState({});
  const [activeRoom, setActiveRoom] = useState('S1');
  const [activeStageKey, setActiveStageKey] = useState('Setting A');
  const [systemConfig, setSystemConfig] = useState({
    upload_hours: 0,
    upload_mins: 0,
    upload_secs: 0,
    upload_frequency_min: 0,
    upload_frequency_sec: 1,
    temp_alarm_offset: 5.0,
    humi_alarm_offset: 5.0,
    relay_port: '/dev/serial/by-path/usb-0:1:2:1:0-port0',
    sensor_names: { ...DEFAULT_ROOM_NAMES }
  });

  // Telemetry & Hardware Matrix
  const [liveData, setLiveData] = useState({});
  const [relayStates, setRelayStates] = useState({});
  const [activeWarnings, setActiveWarnings] = useState([]);
  const [roomPausedStates, setRoomPausedStates] = useState({});
  const [chartData, setChartData] = useState([]);

  // Modals & Navigation
  const [activeTab, setActiveTab] = useState('control'); // 'control' | 'relays' | 'trends'
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [showRenameModal, setShowRenameModal] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const [showSlotModal, setShowSlotModal] = useState(false);
  const [editingSlotIdx, setEditingSlotIdx] = useState(null);
  const [slotForm, setSlotForm] = useState(null);
  const [devicePrograms, setDevicePrograms] = useState({});
  const [showPresetModal, setShowPresetModal] = useState(false);
  const [showSaveProgramModal, setShowSaveProgramModal] = useState(false);
  const [presetNameInput, setPresetNameInput] = useState('');

  // Remote Hardware Command State
  const [confirmModal, setConfirmModal] = useState({ open: false, action: null });
  const [commandLoading, setCommandLoading] = useState(false);
  const [commandCooldown, setCommandCooldown] = useState(0);

  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  const selectedDevice = devices.find(d => (d.mqttId || d._id) === selectedMqttId || d.mqttId === selectedMqttId || d._id === selectedMqttId);
  const targetDevId = selectedDevice?.mqttId || selectedDevice?._id || selectedMqttId || 'cold_room';

  const candidateIdsStr = useMemo(() => {
    return Array.from(
      new Set(
        [
          selectedMqttId,
          selectedDevice?.mqttId,
          selectedDevice?._id,
          selectedDevice?.deviceId,
          selectedMqttId ? String(selectedMqttId).toLowerCase() : null,
          selectedDevice?.mqttId ? String(selectedDevice.mqttId).toLowerCase() : null,
          selectedDevice?._id ? String(selectedDevice._id).toLowerCase() : null,
          'cold_room',
          'cold_storage',
          'control123'
        ].filter(Boolean)
      )
    ).join(',');
  }, [selectedMqttId, selectedDevice?.mqttId, selectedDevice?._id, selectedDevice?.deviceId]);

  const candidateIdentifiers = useMemo(() => {
    return candidateIdsStr ? candidateIdsStr.split(',') : [];
  }, [candidateIdsStr]);

  // Active heartbeat watchdog: checks device status & telemetry freshness without false offline flips
  useEffect(() => {
    const ticker = setInterval(() => {
      const uploadSec = Number(systemConfig.upload_frequency_sec) || (Number(systemConfig.upload_frequency_min) * 60) || 1;
      const allowedTimeoutMs = Math.max(300000, (uploadSec * 2.5 + 60) * 1000);

      const hasRecentTelemetry = Boolean(
        lastTelemetryTimeRef.current && (Date.now() - lastTelemetryTimeRef.current < allowedTimeoutMs)
      );
      const isOnline = Boolean(hasRecentTelemetry || selectedDevice?.status === 'online');
      setIsMachineOnline((prev) => (prev !== isOnline ? isOnline : prev));
    }, 5000);
    return () => clearInterval(ticker);
  }, [systemConfig.upload_frequency_sec, systemConfig.upload_frequency_min, selectedDevice?.status]);

  useEffect(() => {
    if (commandCooldown <= 0) return;
    const timer = setInterval(() => {
      setCommandCooldown((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [commandCooldown]);

  // Get or initialize room setpoints
  const getRoomSetpoints = useCallback((sKey) => {
    if (allSetpoints[sKey]) return allSetpoints[sKey];
    return generateDefaultAlmoraSchedule(sKey);
  }, [allSetpoints]);

  const currentRoomSetpoints = getRoomSetpoints(activeRoom);
  const currentStage = (currentRoomSetpoints.settings && currentRoomSetpoints.settings[activeStageKey]) ||
    generateDefaultAlmoraSchedule(activeRoom).settings[activeStageKey] || {};

  const currentRoomPrograms = useMemo(() => {
    if (!devicePrograms || typeof devicePrograms !== 'object') return [];

    const programsMap = {};
    const roomKeys = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'];

    // 1. Collect all root-level programs (excluding room keys & raw settings)
    Object.entries(devicePrograms).forEach(([key, val]) => {
      if (
        key &&
        val &&
        typeof val === 'object' &&
        !roomKeys.includes(key.toUpperCase()) &&
        !key.startsWith('Setting ') &&
        !key.startsWith('Stage ')
      ) {
        programsMap[key] = val;
      }
    });

    // 2. Collect room-nested programs (if any are saved inside S1..S7)
    roomKeys.forEach(rk => {
      const rProgs = devicePrograms[rk];
      if (rProgs && typeof rProgs === 'object') {
        Object.entries(rProgs).forEach(([pName, pData]) => {
          if (
            pName &&
            pData &&
            typeof pData === 'object' &&
            !programsMap[pName] &&
            !pName.startsWith('Setting ') &&
            !pName.startsWith('Stage ')
          ) {
            programsMap[pName] = pData;
          }
        });
      }
    });

    return Object.entries(programsMap).map(([pName, pData]) => {
      const settings = (pData && typeof pData === 'object' && pData.settings) ? pData.settings : (pData || {});
      const stageKeys = Object.keys(settings).filter(k => k.startsWith('Setting') || k.startsWith('Stage'));
      const stageCount = stageKeys.length > 0 ? stageKeys.length : Object.keys(settings).length;
      return {
        name: pName,
        crop_name: pData?.crop_name || '',
        setup_name: pData?.setup_name || '',
        desc: `${stageCount} Stage${stageCount > 1 ? 's' : ''} Profile (${stageKeys.slice(0, 3).join(', ')}${stageKeys.length > 3 ? '...' : ''})`,
        settings: settings
      };
    });
  }, [devicePrograms, activeRoom]);

  // Fetch registered devices (strictly filtered to cold storage / almora / multi-room devices)
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.success && Array.isArray(data.data)) {
          const rawList = data.data;

          // Strictly filter for Cold Storage / Multi-Room Cold Room devices ONLY
          const isColdStorageDevice = (d) => {
            if (!d) return false;
            const type = (d.deviceType || d.type || '').toLowerCase();
            const name = (d.name || '').toLowerCase();

            // Strictly reject Almora single-sensor devices (handled on Almora settings)
            if (type === 'almora' || type === 'almora2') {
              return false;
            }

            // Strictly reject other unrelated non-cold device categories
            const nonColdTypes = ['office_control', 'system2', 'monit', 'monnet', 'controlling', 'light_motor_pump', 'dosing'];
            if (nonColdTypes.includes(type)) {
              return false;
            }

            // Accept any device categorized or named for cold storage/cold rooms
            if (type.includes('cold') || type.includes('storage') || type.includes('room') || type === 'multi_sensor') {
              return true;
            }

            if (name.includes('cold') || name.includes('storage') || name.includes('room')) {
              return true;
            }

            return true;
          };

          const list = rawList.filter(isColdStorageDevice);
          const finalDevices = list.length > 0 ? list : rawList;

          setDevices(finalDevices);

          let selected = null;
          if (paramMqtt) {
            const matched = finalDevices.find(d => (d.mqttId && d.mqttId.toLowerCase() === paramMqtt.toLowerCase()) || d._id === paramMqtt);
            selected = matched ? (matched.mqttId || matched._id) : paramMqtt;
          } else if (paramDev) {
            const matched = finalDevices.find(d => d._id === paramDev || (d.mqttId && d.mqttId.toLowerCase() === paramDev.toLowerCase()));
            selected = matched ? (matched.mqttId || matched._id) : paramDev;
          } else {
            // Pick online cold storage device, or first available device
            const onlineCold = finalDevices.find(d => d.status === 'online');
            selected = onlineCold ? (onlineCold.mqttId || onlineCold._id) : (finalDevices[0]?.mqttId || finalDevices[0]?._id || 'cold_room');
          }
          setSelectedMqttId(selected || 'cold_room');
        }
      } catch (err) {
        console.error('Failed to fetch devices', err);
      } finally {
        setLoading(false);
      }
    };
    fetchDevices();
  }, [token, API_BASE, paramMqtt, paramDev]);

  // Directly fetch latest crop_programs.json and setpoints_<devId>.json from device disk
  const fetchDiskStateDirectly = useCallback(async () => {
    const devTarget = targetDevId || selectedMqttId || selectedDevice?.mqttId || selectedDevice?._id || 'cold_room';
    if (!devTarget) return;

    try {
      // 1. Programs
      const pRes = await fetch(`${API_BASE}/api/devices/${encodeURIComponent(devTarget)}/programs`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const pJson = await pRes.json();
      if (pJson.success && pJson.data) {
        setDevicePrograms(prev => {
          if (JSON.stringify(prev) === JSON.stringify(pJson.data)) return prev;
          return pJson.data;
        });
      }

      // 2. Active Setpoints & System Config from device disk
      const sRes = await fetch(`${API_BASE}/api/devices/${encodeURIComponent(devTarget)}/setpoints-json`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const sJson = await sRes.json();
      if (sJson.success && sJson.data && Object.keys(sJson.data).length > 0) {
        setAllSetpoints(prev => {
          if (JSON.stringify(prev) === JSON.stringify(sJson.data)) return prev;
          return { ...prev, ...sJson.data };
        });
      }
      if (sJson.system_config && typeof sJson.system_config === 'object') {
        const h = Number(sJson.system_config.upload_hours ?? 0);
        const m = Number(sJson.system_config.upload_mins ?? 0);
        const s = Number(sJson.system_config.upload_secs ?? 0);
        const totalSec = (h * 3600) + (m * 60) + s;
        const totalMin = totalSec > 0 ? +(totalSec / 60).toFixed(4) : (Number(sJson.system_config.upload_frequency_min) || 0);

        setSystemConfig(prev => {
          const updated = {
            ...prev,
            ...sJson.system_config,
            upload_hours: h,
            upload_mins: m,
            upload_secs: s,
            upload_frequency_min: totalMin,
            upload_frequency_sec: totalSec > 0 ? totalSec : 1,
            temp_alarm_offset: Number(sJson.system_config.temp_alarm_offset ?? prev.temp_alarm_offset ?? 5.0),
            humi_alarm_offset: Number(sJson.system_config.humi_alarm_offset ?? prev.humi_alarm_offset ?? 5.0),
            sensor_names: {
              ...(prev.sensor_names || DEFAULT_ROOM_NAMES),
              ...(sJson.system_config.sensor_names || {})
            }
          };
          if (JSON.stringify(prev) === JSON.stringify(updated)) return prev;
          return updated;
        });
      }
    } catch (e) { }
  }, [targetDevId, selectedMqttId, selectedDevice?.mqttId, selectedDevice?._id, API_BASE, token]);

  // Initialize device programs, setpoints, and online status on device target change
  useEffect(() => {
    if (selectedDevice) {
      const devTs = selectedDevice.latestPacketTime || selectedDevice.lastUpdated;
      const uploadSec = Number(systemConfig.upload_frequency_sec) || (Number(systemConfig.upload_frequency_min) * 60) || 1;
      const allowedTimeoutMs = Math.max(120000, (uploadSec * 2.5 + 60) * 1000);
      let isFresh = false;
      if (devTs) {
        const ts = new Date(typeof devTs === 'string' && devTs.includes(' ') && !devTs.includes('T') ? devTs.replace(' ', 'T') : devTs).getTime();
        if (!isNaN(ts) && (Date.now() - ts < allowedTimeoutMs)) {
          isFresh = true;
          lastTelemetryTimeRef.current = ts;
        }
      }
      if (selectedDevice.status === 'online' || isFresh) {
        setIsMachineOnline(true);
        if (!lastTelemetryTimeRef.current) {
          lastTelemetryTimeRef.current = Date.now();
        }
      }
    }
    if (selectedDevice?.crop_programs) {
      setDevicePrograms(selectedDevice.crop_programs);
    }
    if (selectedDevice?.sensor_setpoints) {
      setAllSetpoints(prev => ({ ...prev, ...selectedDevice.sensor_setpoints }));
    }
    fetchDiskStateDirectly();
  }, [targetDevId, selectedDevice, systemConfig.upload_frequency_sec, systemConfig.upload_frequency_min]);

  // Robust Telemetry Normalizer (Extracts S1..S7 from any packet structure)
  const processIncomingTelemetry = useCallback((payload) => {
    if (!payload) return;
    lastTelemetryTimeRef.current = Date.now();
    setIsMachineOnline(true);
    setStatus(prev => prev !== 'connected' ? 'connected' : prev);

    // 1. Process Setpoints, Programs & Config if present
    if (payload.crop_programs || payload.saved_programs) {
      const incomingProgs = payload.crop_programs || payload.saved_programs;
      if (incomingProgs && typeof incomingProgs === 'object') {
        setDevicePrograms(prev => {
          if (JSON.stringify(prev) === JSON.stringify(incomingProgs)) return prev;
          return incomingProgs;
        });
      }
    }
    if (payload.sensor_setpoints) {
      setAllSetpoints(prev => {
        if (JSON.stringify(prev) === JSON.stringify(payload.sensor_setpoints)) return prev;
        return { ...prev, ...payload.sensor_setpoints };
      });
    }
    if (payload.port && payload.settings) {
      setAllSetpoints(prev => {
        const curPort = prev[payload.port] || {};
        const merged = { ...curPort, ...payload };
        if (JSON.stringify(curPort) === JSON.stringify(merged)) return prev;
        return { ...prev, [payload.port]: merged };
      });
    }
    if (payload.system_config) {
      setSystemConfig(prev => {
        const updated = {
          ...prev,
          ...payload.system_config,
          sensor_names: {
            ...DEFAULT_ROOM_NAMES,
            ...(payload.system_config.sensor_names || {})
          }
        };
        if (JSON.stringify(prev) === JSON.stringify(updated)) return prev;
        return updated;
      });
    }
    const rawRelayStates = payload.relay_states || payload.relays;
    if (rawRelayStates && typeof rawRelayStates === 'object') {
      setRelayStates(prev => {
        if (JSON.stringify(prev) === JSON.stringify(rawRelayStates)) return prev;
        return { ...prev, ...rawRelayStates };
      });
    }

    if (payload.rooms && typeof payload.rooms === 'object') {
      const roomRelayMap = {};
      Object.entries(payload.rooms).forEach(([rk, rObj]) => {
        if (!rObj || typeof rObj !== 'object') return;
        const m = rk.match(/\d+/);
        if (m) {
          const idx = parseInt(m[0], 10) - 1;
          const cCh = (idx * 3) + 1;
          const hCh = (idx * 3) + 2;
          const lCh = (idx * 3) + 3;
          if (rObj.relays?.cooling !== undefined) roomRelayMap[cCh] = Boolean(rObj.relays.cooling);
          else if (rObj.cooling !== undefined) roomRelayMap[cCh] = Boolean(rObj.cooling);

          if (rObj.relays?.humidifier !== undefined) roomRelayMap[hCh] = Boolean(rObj.relays.humidifier);
          else if (rObj.humidifier !== undefined) roomRelayMap[hCh] = Boolean(rObj.humidifier);

          if (rObj.relays?.grow_lights !== undefined) roomRelayMap[lCh] = Boolean(rObj.relays.grow_lights);
          else if (rObj.grow_lights !== undefined) roomRelayMap[lCh] = Boolean(rObj.grow_lights);
        }
      });
      if (Object.keys(roomRelayMap).length > 0) {
        setRelayStates(prev => ({ ...prev, ...roomRelayMap }));
      }
    }

    if (payload.room_paused_states) {
      setRoomPausedStates(prev => {
        if (JSON.stringify(prev) === JSON.stringify(payload.room_paused_states)) return prev;
        return payload.room_paused_states;
      });
    } else if (payload.system_config?.room_paused) {
      setRoomPausedStates(prev => {
        if (JSON.stringify(prev) === JSON.stringify(payload.system_config.room_paused)) return prev;
        return payload.system_config.room_paused;
      });
    }
    if (Array.isArray(payload.active_warnings)) {
      setActiveWarnings(prev => {
        if (JSON.stringify(prev) === JSON.stringify(payload.active_warnings)) return prev;
        return payload.active_warnings;
      });
    }

    // 2. Normalize sensor readings to S1..S7
    const rawSensors = payload.sensor_data || payload.rooms || (payload.S1 ? payload : null);

    if (rawSensors && typeof rawSensors === 'object') {
      const normalized = {};
      Object.entries(rawSensors).forEach(([key, val]) => {
        if (!val || typeof val !== 'object') return;

        let sKey = null;
        if (val.id !== undefined) {
          sKey = `S${val.id}`;
        } else if (key.startsWith('S') && key.length <= 3) {
          sKey = key.toUpperCase();
        } else {
          const m = key.match(/S(\d+)/i) || key.match(/port(\d+)/i);
          if (m) sKey = `S${m[1]}`;
        }

        if (sKey && SENSOR_KEYS.includes(sKey)) {
          const tempVal = val.temp ?? val.t ?? null;
          const humiVal = val.humi ?? val.h ?? null;
          normalized[sKey] = {
            id: val.id,
            temp: typeof tempVal === 'number' ? tempVal : (tempVal ? parseFloat(tempVal) : null),
            humi: typeof humiVal === 'number' ? humiVal : (humiVal ? parseFloat(humiVal) : null),
            co2: val.co2 ?? null,
            status: val.status || (tempVal !== null ? 'OK' : 'OFFLINE')
          };
        }
      });

      if (Object.keys(normalized).length > 0) {
        setLiveData(prev => {
          let hasDiff = false;
          for (const k of Object.keys(normalized)) {
            if (!prev[k] || prev[k].temp !== normalized[k].temp || prev[k].humi !== normalized[k].humi || prev[k].co2 !== normalized[k].co2 || prev[k].status !== normalized[k].status) {
              hasDiff = true;
              break;
            }
          }
          return hasDiff ? { ...prev, ...normalized } : prev;
        });

        // Throttle chart trend update to at most once every 5 seconds
        const nowMs = Date.now();
        if (nowMs - lastChartUpdateRef.current > 5000) {
          lastChartUpdateRef.current = nowMs;
          setChartData(prev => {
            const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            const point = { time: timeStr };
            SENSOR_KEYS.forEach(k => {
              if (normalized[k] && normalized[k].temp !== null) {
                point[`${k}_T`] = normalized[k].temp;
                point[`${k}_H`] = normalized[k].humi;
              }
            });
            const next = [...prev, point];
            if (next.length > 30) next.shift();
            return next;
          });
        }
      }
    }
  }, []);

  const processTelemetryRef = useRef(processIncomingTelemetry);
  useEffect(() => {
    processTelemetryRef.current = processIncomingTelemetry;
  });

  // --- DUAL-CHANNEL REAL-TIME SYNC (MQTT WEBSOCKET + SSE FALLBACK) ---
  useEffect(() => {
    if (loading || !candidateIdsStr) return;

    const idsList = candidateIdsStr.split(',');
    const mqttClient = createMqttClient();

    mqttClient.on('connect', () => {
      setStatus('connected');
      idsList.forEach((id) => {
        if (!id) return;
        mqttClient.subscribe(`inhydro/${id}/#`, { qos: 0 });
        mqttClient.publish(`inhydro/${id}/setpoints/request_sync`, '1');
      });
    });

    mqttClient.on('message', (topic, message) => {
      try {
        const payload = JSON.parse(message.toString());
        setStatus('connected');
        processTelemetryRef.current(payload);
      } catch (err) {
        console.debug('MQTT parse error', err);
      }
    });

    mqttClient.on('error', () => {
      // Direct WS error is expected when direct broker is disabled; fallback to SSE stream
    });

    setClient(mqttClient);

    const sseUrl = `${API_BASE}/api/devices/stream?deviceId=${targetDevId}&mqttId=${selectedMqttId || ''}`;
    let eventSource = null;
    try {
      eventSource = new EventSource(sseUrl);
      eventSource.onopen = () => {
        setStatus('connected');
      };
      eventSource.onmessage = (event) => {
        try {
          if (!event.data || event.data.startsWith(':')) return;
          const packet = JSON.parse(event.data);
          setStatus('connected');
          const pData = packet.data || packet.telemetry || packet;
          processTelemetryRef.current(pData);
        } catch { }
      };
      eventSource.onerror = () => {
        // SSE reconnects automatically
      };
    } catch (e) { }

    return () => {
      if (mqttClient) mqttClient.end();
      if (eventSource) eventSource.close();
    };
  }, [candidateIdsStr, targetDevId, API_BASE, loading]);

  // Request sync from physical device
  const handleRequestSync = async () => {
    const devTarget = targetDevId || selectedMqttId || selectedDevice?.mqttId || selectedDevice?._id || 'cold_room';
    setStatusMsg('Requesting sync from hardware...');
    if (client && client.connected) {
      candidateIdentifiers.forEach((id) => {
        try {
          client.publish(`inhydro/${id}/setpoints/request_sync`, '1');
        } catch (e) { }
      });
    }
    try {
      await fetch(`${API_BASE}/api/devices/${encodeURIComponent(devTarget)}/push-config?action=sync`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
    } catch (e) { }
    await fetchDiskStateDirectly();
    setTimeout(() => setStatusMsg(''), 2500);
  };

  // Auto-request sync immediately once when device target changes
  const prevSyncIdRef = useRef(null);
  useEffect(() => {
    if (!targetDevId || prevSyncIdRef.current === targetDevId) return;
    prevSyncIdRef.current = targetDevId;
    const timer = setTimeout(() => {
      handleRequestSync();
    }, 500);
    return () => clearTimeout(timer);
  }, [targetDevId]);

  // State update helpers (bullet-proof null safety)
  const updateRoomState = (updater) => {
    setAllSetpoints(prev => {
      const fallback = generateDefaultAlmoraSchedule(activeRoom);
      const cur = prev[activeRoom] ? JSON.parse(JSON.stringify(prev[activeRoom])) : fallback;
      if (!cur.settings) cur.settings = fallback.settings;
      if (!cur.settings[activeStageKey]) cur.settings[activeStageKey] = fallback.settings[activeStageKey] || {};
      const updated = updater(cur) || cur;
      return { ...prev, [activeRoom]: updated };
    });
  };

  const updateActiveStage = (field, val) => {
    updateRoomState(room => {
      const fallback = generateDefaultAlmoraSchedule(activeRoom);
      if (!room.settings) room.settings = fallback.settings;
      if (!room.settings[activeStageKey]) room.settings[activeStageKey] = fallback.settings[activeStageKey] || {};
      room.settings[activeStageKey][field] = val;
      return room;
    });
  };

  const handleStageDateChange = (field, dateStr) => {
    updateRoomState(room => {
      const fallback = generateDefaultAlmoraSchedule(activeRoom);
      if (!room.settings) room.settings = fallback.settings;
      if (!room.settings[activeStageKey]) room.settings[activeStageKey] = fallback.settings[activeStageKey] || {};
      room.settings[activeStageKey][field] = dateStr;
      room.settings = autoChainDates(room.settings, activeStageKey);
      return room;
    });
  };

  // Calculate active enabled stages count (1-10)
  const activeStagesCount = useMemo(() => {
    if (!currentRoomSetpoints?.settings) return 5;
    let count = 0;
    for (const k of ALL_SETTING_KEYS) {
      if (currentRoomSetpoints.settings[k]?.enabled !== false) {
        count++;
      }
    }
    return Math.max(1, Math.min(10, count || 5));
  }, [currentRoomSetpoints]);

  // Set number of active crop stages (matches desktop select_num_stages)
  const handleSelectNumStages = (count) => {
    const num = parseInt(count, 10);
    updateRoomState(prevRoom => {
      const nextSettings = { ...(prevRoom.settings || {}) };
      ALL_SETTING_KEYS.forEach((k, idx) => {
        nextSettings[k] = {
          ...(nextSettings[k] || {}),
          enabled: idx < num
        };
      });
      return { ...prevRoom, settings: nextSettings };
    });
    // If active stage is beyond new count, switch to Setting A
    const activeIdx = ALL_SETTING_KEYS.indexOf(activeStageKey);
    if (activeIdx >= num) {
      setActiveStageKey(ALL_SETTING_KEYS[0]);
    }
    setStatusMsg(`Configured ${num} active crop stage${num > 1 ? 's' : ''} for ${systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]}`);
    setTimeout(() => setStatusMsg(''), 3000);
  };

  // Instant Stage Active / Disabled Toggle Sync
  const handleToggleStageEnabled = async () => {
    const isCurrentlyEnabled = currentStage.enabled !== false;
    const nextEnabled = !isCurrentlyEnabled;
    updateActiveStage('enabled', nextEnabled);

    // Instant hardware push and sync
    const curRoom = currentRoomSetpoints;
    const updatedSettings = {
      ...(curRoom.settings || {}),
      [activeStageKey]: {
        ...(curRoom.settings?.[activeStageKey] || {}),
        enabled: nextEnabled
      }
    };
    const payload = {
      port: activeRoom,
      room: activeRoom,
      action: 'stage_toggle',
      stage: activeStageKey,
      enabled: nextEnabled,
      settings: updatedSettings
    };
    if (client && client.connected) {
      candidateIdentifiers.forEach((id) => {
        try {
          client.publish(`inhydro/${id}/setpoints/update`, JSON.stringify(payload), { retain: true });
        } catch (e) { }
      });
    }
    const targetId = selectedDevice?.mqttId || selectedDevice?._id || selectedMqttId;
    if (targetId) {
      try {
        await fetch(`${API_BASE}/api/devices/${targetId}/push-config`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(payload)
        });
      } catch { }
    }
  };

  // Load a saved program into active room from device
  const handleApplyPresetProgram = async (presetName) => {
    const p = currentRoomPrograms.find(item => item.name === presetName);
    if (!p) return;
    updateRoomState(prev => ({
      ...prev,
      program_name: p.name,
      crop_name: p.crop_name || prev.crop_name,
      setup_name: p.setup_name || prev.setup_name,
      settings: JSON.parse(JSON.stringify(p.settings))
    }));

    const payload = {
      action: 'apply_program',
      room: activeRoom,
      port: activeRoom,
      program_name: p.name,
      settings: p.settings
    };

    if (client && client.connected) {
      candidateIdentifiers.forEach((id) => {
        try {
          client.publish(`inhydro/${id}/setpoints/update`, JSON.stringify(payload), { retain: false });
        } catch (e) { }
      });
    }

    const targetId = selectedDevice?.mqttId || selectedDevice?._id || selectedMqttId;
    if (targetId) {
      try {
        await fetch(`${API_BASE}/api/devices/${targetId}/programs/${encodeURIComponent(p.name)}/apply`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ room: activeRoom, port: activeRoom, settings: p.settings })
        });
      } catch {
        try {
          await fetch(`${API_BASE}/api/devices/${targetId}/push-config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify(payload)
          });
        } catch { }
      }
    }

    await fetchDiskStateDirectly();
    setStatusMsg(`Applied program "${p.name}" to ${systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]}!`);
    setTimeout(() => setStatusMsg(''), 3000);
  };

  // Save current room configuration as a named program on hardware
  const handleSaveCurrentAsProgram = async (nameToSave) => {
    const trimmed = (nameToSave || '').trim();
    if (!trimmed) return;

    const currentSettings = JSON.parse(JSON.stringify(currentRoomSetpoints.settings || {}));

    setDevicePrograms(prev => ({
      ...prev,
      [trimmed]: currentSettings,
      [activeRoom]: {
        ...(prev[activeRoom] || {}),
        [trimmed]: currentSettings
      }
    }));

    updateRoomState(prev => ({
      ...prev,
      program_name: trimmed
    }));

    const payload = {
      action: 'save_program',
      room: activeRoom,
      port: activeRoom,
      program_name: trimmed,
      settings: currentSettings
    };

    if (client && client.connected) {
      candidateIdentifiers.forEach((id) => {
        try {
          client.publish(`inhydro/${id}/setpoints/update`, JSON.stringify(payload), { retain: false });
        } catch (e) { }
      });
    }

    const targetId = selectedDevice?.mqttId || selectedDevice?._id || selectedMqttId;
    if (targetId) {
      try {
        const res = await fetch(`${API_BASE}/api/devices/${targetId}/programs`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success && data.data) {
          setDevicePrograms(data.data);
        }
      } catch {
        try {
          await fetch(`${API_BASE}/api/devices/${targetId}/push-config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify(payload)
          });
        } catch { }
      }
    }

    await fetchDiskStateDirectly();
    setStatusMsg(`Saved and activated program "${trimmed}" on device for ${systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]}!`);
    setTimeout(() => setStatusMsg(''), 3000);
  };

  // Delete program from hardware
  const handleDeleteProgram = async (nameToDelete) => {
    if (!nameToDelete) return;

    setDevicePrograms(prev => {
      const copy = { ...prev };
      delete copy[nameToDelete];
      Object.keys(copy).forEach(rk => {
        if (copy[rk] && typeof copy[rk] === 'object') {
          const rCopy = { ...copy[rk] };
          delete rCopy[nameToDelete];
          copy[rk] = rCopy;
        }
      });
      return copy;
    });

    if (currentRoomSetpoints.program_name === nameToDelete) {
      updateRoomState(prev => ({ ...prev, program_name: 'Default Program' }));
    }

    const payload = {
      action: 'delete_program',
      room: activeRoom,
      port: activeRoom,
      program_name: nameToDelete
    };

    if (client && client.connected) {
      candidateIdentifiers.forEach((id) => {
        try {
          client.publish(`inhydro/${id}/setpoints/update`, JSON.stringify(payload), { retain: false });
        } catch (e) { }
      });
    }

    const targetId = selectedDevice?.mqttId || selectedDevice?._id || selectedMqttId;
    if (targetId) {
      try {
        const res = await fetch(`${API_BASE}/api/devices/${targetId}/programs/${encodeURIComponent(nameToDelete)}`, {
          method: 'DELETE',
          headers: { Authorization: `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.success && data.data) {
          setDevicePrograms(data.data);
        }
      } catch {
        try {
          await fetch(`${API_BASE}/api/devices/${targetId}/push-config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify(payload)
          });
        } catch { }
      }
    }

    await fetchDiskStateDirectly();
    setStatusMsg(`Deleted program "${nameToDelete}" from device.`);
    setTimeout(() => setStatusMsg(''), 3000);
  };

  // Save changes to device
  const handleSaveToDevice = async () => {
    setStatus('saving');
    setStatusMsg('Pushing setpoints to hardware...');

    const curRoomData = currentRoomSetpoints;
    const roomCrop = curRoomData.program_name || currentStage.crop_name || curRoomData.crop_name || `${systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]} Program`;
    const roomSetup = currentStage.setup_name || curRoomData.setup_name || `${systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]} Setup`;

    const h = Math.max(0, parseInt(systemConfig.upload_hours, 10) || 0);
    const m = Math.max(0, parseInt(systemConfig.upload_mins, 10) || 0);
    const s = Math.max(0, parseInt(systemConfig.upload_secs, 10) || 0);
    const totalSec = (h * 3600) + (m * 60) + s;
    const totalMin = totalSec > 0 ? +(totalSec / 60).toFixed(4) : 0;

    const normalizedConfig = {
      ...systemConfig,
      upload_hours: h,
      upload_mins: m,
      upload_secs: s,
      upload_frequency_min: totalMin,
      upload_frequency_sec: totalSec > 0 ? totalSec : 1,
      temp_alarm_offset: parseFloat(systemConfig.temp_alarm_offset) || 5.0,
      humi_alarm_offset: parseFloat(systemConfig.humi_alarm_offset) || 5.0,
      sensor_names: systemConfig.sensor_names || DEFAULT_ROOM_NAMES
    };

    const payload = {
      port: activeRoom,
      program_name: curRoomData.program_name || 'Default Program',
      crop_name: roomCrop,
      setup_name: roomSetup,
      mode: curRoomData.mode || 'SCHEDULED',
      'T MIN': curRoomData['T MIN'] ?? 10.0,
      'T MAX': curRoomData['T MAX'] ?? 30.0,
      'H MIN': curRoomData['H MIN'] ?? 30.0,
      'H MAX': curRoomData['H MAX'] ?? 80.0,
      settings: curRoomData.settings || {},
      system_config: normalizedConfig,
      upload_hours: h,
      upload_mins: m,
      upload_secs: s,
      upload_frequency_min: totalMin,
      upload_frequency_sec: totalSec > 0 ? totalSec : 1,
      temp_alarm_offset: normalizedConfig.temp_alarm_offset,
      humi_alarm_offset: normalizedConfig.humi_alarm_offset,
      sensor_names: normalizedConfig.sensor_names
    };

    // 1. Direct WebSocket MQTT publish to all candidate IDs
    if (client && client.connected) {
      candidateIdentifiers.forEach((id) => {
        try {
          client.publish(`inhydro/${id}/setpoints/update`, JSON.stringify(payload), { retain: true });
          client.publish(`inhydro/${id}/config/update`, JSON.stringify(payload), { retain: true });
        } catch (err) {
          console.error('MQTT publish err', err);
        }
      });
    }

    // 2. Backend REST API fallback
    const targetId = selectedDevice?.mqttId || selectedDevice?._id || selectedMqttId;
    if (targetId) {
      try {
        await fetch(`${API_BASE}/api/devices/${targetId}/push-config`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(payload)
        });
      } catch (err) {
        console.error('REST sync err', err);
      }
    }

    await fetchDiskStateDirectly();
    setStatus('saved');
    setStatusMsg('Setpoints updated successfully!');
    setTimeout(() => {
      setStatus('connected');
      setStatusMsg('');
    }, 2000);
  };

  // Dedicated Save for System Configuration (Upload Frequency, Alarms, etc.)
  const handleSaveSystemConfig = async (overrideCfg) => {
    setStatus('saving');
    setStatusMsg('Syncing system config to device...');

    const base = overrideCfg || systemConfig;
    const h = Math.max(0, parseInt(base.upload_hours, 10) || 0);
    const m = Math.max(0, parseInt(base.upload_mins, 10) || 0);
    const s = Math.max(0, parseInt(base.upload_secs, 10) || 0);
    const totalSec = (h * 3600) + (m * 60) + s;
    const totalMin = totalSec > 0 ? +(totalSec / 60).toFixed(4) : 0;

    const normalizedConfig = {
      ...base,
      upload_hours: h,
      upload_mins: m,
      upload_secs: s,
      upload_frequency_min: totalMin,
      upload_frequency_sec: totalSec > 0 ? totalSec : 1,
      temp_alarm_offset: parseFloat(base.temp_alarm_offset) || 5.0,
      humi_alarm_offset: parseFloat(base.humi_alarm_offset) || 5.0,
      sensor_names: base.sensor_names || DEFAULT_ROOM_NAMES
    };

    setSystemConfig(normalizedConfig);

    const payload = {
      system_config: normalizedConfig,
      upload_hours: h,
      upload_mins: m,
      upload_secs: s,
      upload_frequency_min: totalMin,
      upload_frequency_sec: totalSec > 0 ? totalSec : 1,
      temp_alarm_offset: normalizedConfig.temp_alarm_offset,
      humi_alarm_offset: normalizedConfig.humi_alarm_offset,
      sensor_names: normalizedConfig.sensor_names
    };

    // 1. Direct WebSocket MQTT publish
    if (client && client.connected) {
      candidateIdentifiers.forEach((id) => {
        try {
          client.publish(`inhydro/${id}/config/update`, JSON.stringify(payload), { retain: true });
          client.publish(`inhydro/${id}/setpoints/update`, JSON.stringify(payload), { retain: true });
        } catch (err) {
          console.error('MQTT publish err', err);
        }
      });
    }

    // 2. Backend REST API fallback
    const targetId = selectedDevice?.mqttId || selectedDevice?._id || selectedMqttId;
    if (targetId) {
      try {
        await fetch(`${API_BASE}/api/devices/${targetId}/push-config`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(payload)
        });
      } catch (err) {
        console.error('REST sync err', err);
      }
    }

    await fetchDiskStateDirectly();
    setStatus('saved');
    setStatusMsg('System configuration synced successfully!');
    setTimeout(() => {
      setStatus('connected');
      setStatusMsg('');
    }, 2000);
  };

  // Remote Hardware Command Dispatcher (Restart, Exit)
  const handleDeviceCommand = async (action) => {
    if (!selectedMqttId && candidateIdentifiers.length === 0) return;
    if (commandCooldown > 0) {
      setStatusMsg('Command in progress. Please wait a moment.');
      setTimeout(() => setStatusMsg(''), 3000);
      return;
    }
    setCommandLoading(true);
    setCommandCooldown(6);
    setConfirmModal({ open: false, action: null });

    const cmd_id = `cmd_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`;
    const cmdPayload = { action, cmd_id, timestamp: Date.now() };

    // 1. Direct WebSocket MQTT Publish across candidate IDs
    if (client && client.connected) {
      candidateIdentifiers.forEach((id) => {
        try {
          client.publish(`inhydro/${id}/command`, JSON.stringify(cmdPayload), { retain: false });
        } catch (err) {
          console.warn("Direct MQTT command publish failed:", err);
        }
      });
    }

    // 2. Fallback via backend REST API
    const targetId = selectedDevice?.mqttId || selectedDevice?._id || selectedMqttId;
    if (targetId) {
      try {
        const res = await fetch(`${API_BASE}/api/devices/${targetId}/command`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify(cmdPayload),
        });
        const data = await res.json();
        if (data.success) {
          setStatusMsg(`${action === 'restart' ? 'Restart' : 'Exit'} command dispatched to "${selectedDevice?.name || selectedMqttId}"`);
        } else {
          setStatusMsg(data.message || `Command dispatched`);
        }
      } catch (err) {
        console.error("Command error:", err);
        setStatusMsg(`Command dispatched to device.`);
      }
    }
    setTimeout(() => setStatusMsg(''), 4000);
    setCommandLoading(false);
  };

  // Toggle Room Automation Run / Stop
  const handleToggleRoomPause = async (skey) => {
    if (!selectedMqttId && candidateIdentifiers.length === 0) return;
    const isCurrentlyPaused = Boolean(roomPausedStates[skey]);
    const action = isCurrentlyPaused ? 'resume' : 'pause';
    const cmdPayload = { action, room: skey, timestamp: Date.now() };

    // 1. Direct WebSocket MQTT Publish across candidate IDs
    if (client && client.connected) {
      candidateIdentifiers.forEach((id) => {
        try {
          client.publish(`inhydro/${id}/command`, JSON.stringify(cmdPayload), { retain: false });
        } catch (e) { }
      });
    }

    // 2. Backend REST API
    const targetId = selectedDevice?.mqttId || selectedDevice?._id || selectedMqttId;
    if (targetId) {
      try {
        await fetch(`${API_BASE}/api/devices/${targetId}/command`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify(cmdPayload),
        });
      } catch (e) { }
    }

    setRoomPausedStates(prev => ({ ...prev, [skey]: !isCurrentlyPaused }));
    setStatusMsg(`${isCurrentlyPaused ? 'Resuming' : 'Stopping'} automation for ${systemConfig.sensor_names[skey] || DEFAULT_ROOM_NAMES[skey]}...`);
    setTimeout(() => setStatusMsg(''), 3000);
  };

  // Slot editor handlers
  const openEditSlot = (idx) => {
    const slot = currentStage.time_slots[idx];
    if (!slot) return;
    setEditingSlotIdx(idx);
    setSlotForm({ ...slot });
    setShowSlotModal(true);
  };

  const handleSaveSlotForm = () => {
    if (editingSlotIdx === null || !slotForm) return;
    updateRoomState(room => {
      const st = room.settings[activeStageKey];
      if (st && st.time_slots && st.time_slots[editingSlotIdx]) {
        st.time_slots[editingSlotIdx] = {
          ...slotForm,
          t_set: Number(slotForm.t_set) || 24.0,
          t_min: Number(slotForm.t_min) || 20.0,
          t_max: Number(slotForm.t_max) || 26.0,
          h_set: Number(slotForm.h_set) || 60.0,
          h_min: Number(slotForm.h_min) || 55.0,
          h_max: Number(slotForm.h_max) || 70.0,
          start: formatTime12h(slotForm.start),
          stop: formatTime12h(slotForm.stop)
        };
      }
      return room;
    });
    setShowSlotModal(false);
  };

  const handleDeleteSlot = (idx) => {
    updateRoomState(room => {
      const st = room.settings[activeStageKey];
      if (st && st.time_slots && st.time_slots.length > 1) {
        st.time_slots.splice(idx, 1);
        st.time_slots.forEach((s, i) => { s.id = i + 1; });
      }
      return room;
    });
  };

  const handleAddSlot = () => {
    updateRoomState(room => {
      const st = room.settings[activeStageKey];
      if (!st.time_slots) st.time_slots = [];
      const newId = st.time_slots.length + 1;
      st.time_slots.push({
        id: newId,
        name: `Slot ${newId}`,
        start: '12:00 PM',
        stop: '04:00 PM',
        t_set: 25.0,
        t_min: 21.0,
        t_max: 27.0,
        h_set: 65.0,
        h_min: 60.0,
        h_max: 70.0,
        enabled: true
      });
      return room;
    });
  };

  // Overlap warnings
  const slotWarnings = useMemo(() => {
    return checkTimeSlotOverlaps(currentStage.time_slots);
  }, [currentStage.time_slots]);

  // Current active room live telemetry
  const activeRoomLive = liveData[activeRoom] || {};
  const currentRoomIdx = SENSOR_KEYS.indexOf(activeRoom);
  const chCool = (currentRoomIdx * 3) + 1;
  const chHumi = (currentRoomIdx * 3) + 2;
  const chLight = (currentRoomIdx * 3) + 3;

  if (loading) {
    return (
      <div className="flex h-80 items-center justify-center rounded-2xl border border-slate-800 bg-slate-900/40 backdrop-blur-sm p-6 mx-auto max-w-7xl">
        <div className="flex flex-col sm:flex-row items-center gap-3 text-slate-400">
          <RefreshCw className="h-6 w-6 animate-spin text-emerald-500" />
          <span className="text-sm font-medium">Connecting to Almora Controller & Storage Nodes...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-5 pb-16 text-slate-100 font-sans px-2 sm:px-4">
      {/* ── 1. CLEAN TOP HEADER & CONTROLS ── */}
      <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4 p-4 sm:p-5 rounded-2xl bg-slate-900/80 border border-slate-800/80 backdrop-blur-sm shadow-lg shadow-black/20">
        <div className="flex items-center gap-3.5">
          <div className="h-10 w-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0">
            <Wind className="h-5 w-5" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-base sm:text-lg font-bold text-white tracking-tight">
                Almora Cold Storage & Greenhouse
              </h1>
              {/* Broker & Machine Status Badges */}
              <div className="flex items-center gap-1.5">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold border ${status === 'connected'
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                  : 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                  }`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${status === 'connected' ? 'bg-emerald-400 animate-pulse' : 'bg-rose-500'}`} />
                  Broker: {status === 'connected' ? 'Connected' : 'Disconnected'}
                </span>

                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold border ${isMachineOnline
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                  : 'bg-slate-800 text-slate-400 border-slate-700'
                  }`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${isMachineOnline ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
                  Machine {isMachineOnline ? 'Online' : 'Offline'}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center gap-2 w-full lg:w-auto justify-start sm:justify-end">
          {/* Device Selector */}
          <div className="relative flex-1 sm:flex-initial min-w-[180px]">
            <select
              value={selectedMqttId}
              onChange={(e) => setSelectedMqttId(e.target.value)}
              className="w-full appearance-none bg-slate-950 border border-slate-700/80 text-white text-xs font-semibold rounded-xl pl-8 pr-8 py-2 outline-none hover:border-slate-600 focus:border-emerald-500/60 focus:ring-1 focus:ring-emerald-500/30 cursor-pointer transition-colors"
            >
              {devices.map(d => (
                <option key={d._id} value={d.mqttId || d._id}>
                  {d.name.replace(/\s*\([^)]*\)/g, '').trim() || d.name}
                </option>
              ))}
            </select>
            <Server className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-emerald-400 pointer-events-none" />
            <ChevronDown className="absolute right-2.5 top-2.5 h-3.5 w-3.5 text-slate-400 pointer-events-none" />
          </div>

          {/* Sync Hardware Button */}
          <button
            onClick={handleRequestSync}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-xs font-medium text-slate-200 hover:text-white transition-all shadow-sm"
            title="Request Instant Sync from Device"
          >
            <RotateCcw className="h-3.5 w-3.5 text-sky-400" />
            <span className="hidden sm:inline">Sync Hardware</span>
            <span className="sm:hidden">Sync</span>
          </button>

          {/* Programs */}
          <button
            onClick={() => setShowPresetModal(true)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-xs font-medium text-slate-200 hover:text-white transition-all shadow-sm"
            title="Browse & manage programs saved on device"
          >
            <Bookmark className="h-3.5 w-3.5 text-emerald-400" />
            <span>Programs ({currentRoomPrograms.length})</span>
          </button>

          {/* Config */}
          <button
            onClick={() => setShowConfigModal(true)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-xs font-medium text-slate-200 hover:text-white transition-all shadow-sm"
          >
            <Sliders className="h-3.5 w-3.5 text-sky-400" />
            <span>Config</span>
          </button>

          {/* Remote Hardware Controls: Restart & Exit */}
          <button
            onClick={() => setConfirmModal({ open: true, action: 'restart' })}
            disabled={commandCooldown > 0 || commandLoading}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-amber-500/30 bg-amber-500/10 hover:bg-amber-500/20 active:scale-95 text-xs font-semibold text-amber-300 hover:text-amber-200 transition-all disabled:opacity-50 shadow-sm"
            title="Remotely restart the controller program"
          >
            <RotateCw className={`h-3.5 w-3.5 text-amber-400 ${commandLoading ? 'animate-spin' : ''}`} />
            <span>Restart</span>
          </button>

          <button
            onClick={() => setConfirmModal({ open: true, action: 'exit' })}
            disabled={commandCooldown > 0 || commandLoading}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-rose-500/30 bg-rose-500/10 hover:bg-rose-500/20 active:scale-95 text-xs font-semibold text-rose-300 hover:text-rose-200 transition-all disabled:opacity-50 shadow-sm"
            title="Remotely stop/exit the controller program"
          >
            <PowerOff className="h-3.5 w-3.5 text-rose-400" />
            <span>Exit</span>
          </button>

          {/* Save Button */}
          <button
            onClick={handleSaveToDevice}
            disabled={status === 'saving'}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 active:scale-95 text-slate-950 font-bold text-xs transition-all shadow-sm shadow-emerald-500/20 disabled:opacity-50"
          >
            {status === 'saving' ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            <span>Save Changes</span>
          </button>
        </div>
      </div>

      {/* ── Offline Retained Notice Banner ── */}
      {!isMachineOnline && (
        <div className="flex items-center gap-2.5 p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs font-medium animate-in fade-in">
          <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
          <span>
            <strong>Machine is currently offline:</strong> New setpoints and schedule changes will be safely retained on the server and automatically pushed when the controller connects.
          </span>
        </div>
      )}

      {/* ── 2. COMPACT NOTIFICATION BAR ── */}
      {statusMsg && (
        <div className="flex items-center gap-2 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-medium animate-in fade-in shadow-sm">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{statusMsg}</span>
        </div>
      )}

      {activeWarnings.length > 0 && (
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs font-semibold">
          <div className="flex items-center gap-2">
            <Bell className="h-4 w-4 text-rose-400 animate-pulse shrink-0" />
            <span>Warning: {activeWarnings.join(' | ')}</span>
          </div>
          <span className="text-[10px] font-mono px-2.5 py-0.5 rounded-lg bg-rose-500/20 text-rose-300 border border-rose-500/30 self-end sm:self-center">
            Alarm Active
          </span>
        </div>
      )}

      {/* ── 3. ELEGANT ROOM SELECTOR PILLS (S1 - S7) ── */}
      <div className="flex items-center gap-2.5 overflow-x-auto pb-1.5 scrollbar-thin">
        {SENSOR_KEYS.map((sKey) => {
          const isSelected = activeRoom === sKey;
          const name = systemConfig.sensor_names[sKey] || DEFAULT_ROOM_NAMES[sKey];
          const data = liveData[sKey] || {};
          const isOnline = (data.status === 'OK' || data.temp !== undefined) && isMachineOnline;

          return (
            <button
              key={sKey}
              onClick={() => setActiveRoom(sKey)}
              className={`flex items-center gap-2.5 px-3.5 py-2.5 rounded-2xl border text-xs whitespace-nowrap transition-all shadow-sm ${isSelected
                ? 'bg-slate-900 border-emerald-500/80 text-white ring-1 ring-emerald-500/30 shadow-emerald-500/10'
                : 'bg-slate-900/60 border-slate-800/80 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                }`}
            >
              <span className={`h-2 w-2 rounded-full shrink-0 ${isOnline ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
              <span className="font-bold tracking-tight">{name}</span>
            </button>
          );
        })}
      </div>

      {/* ── 4. MAIN WORKSPACE WITH VIEW TABS ── */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-sm sm:text-base font-bold text-white">
              {systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]}
            </span>
            <button
              onClick={() => {
                setRenameValue(systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]);
                setShowRenameModal(true);
              }}
              className="p-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:border-slate-700 transition-colors"
              title="Rename Room"
            >
              <Edit3 className="h-3 w-3" />
            </button>
          </div>

          {/* Room-wise Crop, Setup & Automation Run/Stop badges */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold">
              <Bookmark className="h-3.5 w-3.5" />
              <span>Program: {currentRoomSetpoints.program_name || 'Default Program'}</span>
            </span>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs font-semibold">
              <Sparkles className="h-3.5 w-3.5" />
              <span>Stage: {currentStage.name || `Crop Stage ${ALL_SETTING_KEYS.indexOf(activeStageKey) + 1}`}</span>
            </span>
            <button
              onClick={() => handleToggleRoomPause(activeRoom)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-semibold border transition-all shadow-sm ${
                roomPausedStates[activeRoom]
                  ? 'bg-amber-500/15 border-amber-500/30 text-amber-400 hover:bg-amber-500/25'
                  : 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/25'
              }`}
              title={roomPausedStates[activeRoom] ? "Click to resume automation for this room" : "Click to stop/pause automation for this room"}
            >
              <Power className="h-3.5 w-3.5" />
              <span>{roomPausedStates[activeRoom] ? 'Room: Stopped' : 'Room: Running'}</span>
            </button>
          </div>
        </div>

        {/* Tab Switcher */}
        <div className="grid grid-cols-2 sm:flex items-center gap-1 bg-slate-900 p-1 rounded-xl border border-slate-800 text-xs w-full lg:w-auto">
          <button
            onClick={() => setActiveTab('control')}
            className={`px-3.5 py-1.5 rounded-lg font-semibold transition-all text-center ${activeTab === 'control' ? 'bg-emerald-500 text-slate-950 font-bold shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
          >
            Schedule & Setpoints
          </button>
          <button
            onClick={() => setActiveTab('relays')}
            className={`px-3.5 py-1.5 rounded-lg font-semibold transition-all text-center ${activeTab === 'relays' ? 'bg-emerald-500 text-slate-950 font-bold shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
          >
            Appliances State
          </button>
        </div>
      </div>

      {/* ── VIEW 1: SCHEDULE & SETPOINTS (PRIMARY VIEW - FULL WIDTH VERTICAL COLUMN) ── */}
      {activeTab === 'control' && (
        <div className="space-y-6">
          {/* ── 2. FULL-WIDTH STAGE & SCHEDULE PROFILE CARD ── */}
          <div className="rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 p-5 sm:p-6 space-y-4">
            {/* Header: Stage Selector, No. of Stages & Program Controls */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5 pb-4 border-b border-slate-800/80">
              {/* Card 1: Crop Stage & Active Status */}
              <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800/90 flex flex-col justify-between space-y-2.5 shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                    <Sparkles className="h-3.5 w-3.5 text-purple-400" />
                    Crop Stage
                  </span>
                  <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded bg-purple-500/10 text-purple-300 border border-purple-500/20">
                    Stage {ALL_SETTING_KEYS.indexOf(activeStageKey) + 1}
                  </span>
                </div>

                <select
                  value={activeStageKey}
                  onChange={(e) => setActiveStageKey(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700/80 hover:border-purple-500/50 focus:border-purple-500 text-white font-bold text-sm rounded-xl px-3.5 py-2.5 outline-none transition-all cursor-pointer shadow-inner"
                >
                  {ALL_SETTING_KEYS.map((k, idx) => {
                    const stName = currentRoomSetpoints.settings?.[k]?.name;
                    const isEnabled = currentRoomSetpoints.settings?.[k]?.enabled !== false;
                    const stageLabel = (stName && !stName.startsWith('Setting ')) ? stName : `Crop Stage ${idx + 1}`;
                    return (
                      <option key={k} value={k} className="bg-slate-900 text-white font-medium text-sm py-2">
                        {stageLabel} {!isEnabled ? '(Disabled)' : ''}
                      </option>
                    );
                  })}
                </select>

                <button
                  onClick={handleToggleStageEnabled}
                  className={`w-full py-2 px-3 rounded-xl text-xs font-bold border transition-all flex items-center justify-center gap-2 ${currentStage.enabled !== false
                    ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40 shadow-sm shadow-emerald-500/10 hover:bg-emerald-500/25'
                    : 'bg-slate-800/80 text-slate-400 border-slate-700 hover:bg-slate-800'
                    }`}
                >
                  <span className={`h-2 w-2 rounded-full ${currentStage.enabled !== false ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
                  <span>{currentStage.enabled !== false ? 'Stage Active (Running)' : 'Stage Disabled'}</span>
                </button>
              </div>

              {/* Card 2: No. of Crop Stages */}
              <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800/90 flex flex-col justify-between space-y-2.5 shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                    <Layers className="h-3.5 w-3.5 text-emerald-400" />
                    Active Stages Count
                  </span>
                  <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                    {activeStagesCount} Total
                  </span>
                </div>

                <select
                  value={activeStagesCount}
                  onChange={(e) => handleSelectNumStages(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700/80 hover:border-emerald-500/50 focus:border-emerald-500 text-emerald-300 font-bold text-sm rounded-xl px-3.5 py-2.5 outline-none transition-all cursor-pointer shadow-inner"
                >
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(num => (
                    <option key={num} value={num} className="bg-slate-900 text-white font-medium text-sm py-2">
                      {num} Stage{num > 1 ? 's' : ''} Configured
                    </option>
                  ))}
                </select>

                <div className="text-[11px] text-slate-400 font-mono flex items-center justify-between pt-1">
                  <span>Cycle Range:</span>
                  <span className="text-slate-300 font-semibold">Stage 1 → Stage {activeStagesCount}</span>
                </div>
              </div>

              {/* Card 3: Program & Preset Library */}
              <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800/90 flex flex-col justify-between space-y-2.5 shadow-sm md:col-span-2 lg:col-span-1">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                    <Bookmark className="h-3.5 w-3.5 text-sky-400" />
                    Recipe Program
                  </span>
                  <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded bg-sky-500/10 text-sky-300 border border-sky-500/20">
                    {systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]}
                  </span>
                </div>

                <select
                  value={currentRoomSetpoints.program_name || 'Default Program'}
                  onChange={(e) => {
                    if (e.target.value !== currentRoomSetpoints.program_name) {
                      handleApplyPresetProgram(e.target.value);
                    }
                  }}
                  className="w-full bg-slate-900 border border-slate-700/80 hover:border-sky-500/50 focus:border-sky-500 text-sky-300 font-bold text-sm rounded-xl px-3.5 py-2.5 outline-none transition-all cursor-pointer truncate shadow-inner"
                >
                  <option value={currentRoomSetpoints.program_name || 'Default Program'} className="bg-slate-900 text-white font-medium text-sm py-2">
                    {currentRoomSetpoints.program_name || 'Default Program'} (Active)
                  </option>
                  {currentRoomPrograms.length > 0 && (
                    <optgroup label="Saved Programs" className="bg-slate-900 text-slate-400">
                      {currentRoomPrograms
                        .filter(p => p.name !== (currentRoomSetpoints.program_name || 'Default Program'))
                        .map(p => (
                          <option key={p.name} value={p.name} className="bg-slate-900 text-white font-medium text-sm py-2">
                            {p.name}
                          </option>
                        ))}
                    </optgroup>
                  )}
                </select>

                <div className="flex items-center gap-2 pt-0.5">
                  <button
                    onClick={() => {
                      setPresetNameInput(currentRoomSetpoints.program_name && currentRoomSetpoints.program_name !== 'Default Program'
                        ? currentRoomSetpoints.program_name
                        : `Program ${currentRoomPrograms.length + 1}`);
                      setShowSaveProgramModal(true);
                    }}
                    className="flex-1 py-2 px-2.5 rounded-xl bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/30 text-xs font-bold transition-all flex items-center justify-center gap-1.5 whitespace-nowrap shadow-sm"
                    title="Save current stage settings as a named preset program on device"
                  >
                    <Save className="h-3.5 w-3.5" />
                    <span>Save Program</span>
                  </button>

                  <button
                    onClick={() => setShowPresetModal(true)}
                    className="flex-1 py-2 px-2.5 rounded-xl bg-slate-800 hover:bg-slate-750 text-slate-300 border border-slate-700 text-xs font-semibold transition-all flex items-center justify-center gap-1.5 whitespace-nowrap"
                    title="View & manage all saved programs on device"
                  >
                    <Bookmark className="h-3.5 w-3.5 text-sky-400" />
                    <span>Manage ({currentRoomPrograms.length}/20)</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Row 1: Crop Stage Name & Setup Details */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
              {/* Crop Stage Name */}
              <div className="flex items-center gap-3 bg-slate-950/70 border border-slate-800/90 hover:border-slate-700 rounded-xl px-4 py-3 transition-colors shadow-sm">
                <div className="p-2.5 rounded-xl bg-purple-500/10 text-purple-400 shrink-0">
                  <Sparkles className="h-4.5 w-4.5" />
                </div>
                <div className="flex flex-col flex-1 min-w-0">
                  <span className="text-[10px] text-slate-400 uppercase tracking-wider font-bold mb-0.5">
                    Crop Stage Name
                  </span>
                  <input
                    type="text"
                    value={currentStage.name || ''}
                    onChange={(e) => {
                      updateActiveStage('name', e.target.value);
                    }}
                    placeholder={`e.g. Vegetative Stage / Flowering Stage / Crop Stage ${ALL_SETTING_KEYS.indexOf(activeStageKey) + 1}`}
                    className="bg-transparent text-white font-bold text-sm outline-none w-full placeholder:text-slate-600"
                  />
                </div>
              </div>

              {/* Setup Name / Chamber Details */}
              <div className="flex items-center gap-3 bg-slate-950/70 border border-slate-800/90 hover:border-slate-700 rounded-xl px-4 py-3 transition-colors shadow-sm">
                <div className="p-2.5 rounded-xl bg-blue-500/10 text-blue-400 shrink-0">
                  <Layers className="h-4.5 w-4.5" />
                </div>
                <div className="flex flex-col flex-1 min-w-0">
                  <span className="text-[10px] text-slate-400 uppercase tracking-wider font-bold mb-0.5">
                    Setup / Chamber Notes
                  </span>
                  <input
                    type="text"
                    value={currentStage.setup_name || currentRoomSetpoints.setup_name || ''}
                    onChange={(e) => {
                      updateActiveStage('setup_name', e.target.value);
                      updateRoomState(r => ({ ...r, setup_name: e.target.value }));
                    }}
                    placeholder={`${systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]} Setup`}
                    className="bg-transparent text-white font-bold text-sm outline-none w-full placeholder:text-slate-600"
                  />
                </div>
              </div>
            </div>

            {/* Row 2: Stage Date Range & Lights */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5 pt-3.5 border-t border-slate-800/80 text-xs">
              {/* Start Date */}
              <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-2 shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold text-slate-400 flex items-center gap-1.5 uppercase tracking-wider">
                    <Calendar className="h-3.5 w-3.5 text-emerald-400" /> Start Date
                  </span>
                  <span className="text-[10px] font-mono font-bold text-emerald-400/90 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                    {formatDmy(currentStage.start_date) || 'DD-MM-YYYY'}
                  </span>
                </div>
                <input
                  type="date"
                  value={formatIsoDate(currentStage.start_date)}
                  onChange={(e) => handleStageDateChange('start_date', formatDmy(e.target.value))}
                  className="w-full bg-slate-900 border border-slate-700/80 hover:border-slate-600 focus:border-emerald-500/60 rounded-xl px-3 py-2 text-white font-mono text-xs outline-none transition-colors"
                />
              </div>

              {/* End Date */}
              <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-2 shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold text-slate-400 flex items-center gap-1.5 uppercase tracking-wider">
                    <Calendar className="h-3.5 w-3.5 text-rose-400" /> End Date
                  </span>
                  <span className="text-[10px] font-mono font-bold text-rose-400/90 bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20">
                    {formatDmy(currentStage.end_date) || 'DD-MM-YYYY'}
                  </span>
                </div>
                <input
                  type="date"
                  value={formatIsoDate(currentStage.end_date)}
                  onChange={(e) => handleStageDateChange('end_date', formatDmy(e.target.value))}
                  className="w-full bg-slate-900 border border-slate-700/80 hover:border-slate-600 focus:border-rose-500/60 rounded-xl px-3 py-2 text-white font-mono text-xs outline-none transition-colors"
                />
              </div>

              {/* Lights (Daily Photoperiod) */}
              <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-2 shadow-sm sm:col-span-2 lg:col-span-1">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold text-slate-400 flex items-center gap-1.5 uppercase tracking-wider">
                    <Sun className="h-3.5 w-3.5 text-amber-400" /> Lights
                  </span>
                  <span className="text-[10px] font-mono font-semibold text-amber-400/90 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                    Daily Timer
                  </span>
                </div>
                <div className="flex items-center gap-2 font-mono bg-slate-900 border border-slate-700/80 rounded-xl px-3 py-1.5">
                  <input
                    type="text"
                    value={currentStage.photoperiod_on || '06:00 AM'}
                    onChange={(e) => updateActiveStage('photoperiod_on', e.target.value)}
                    className="w-1/2 bg-transparent text-white text-center text-xs font-bold outline-none placeholder:text-slate-600"
                    placeholder="06:00 AM"
                  />
                  <span className="text-slate-500 font-bold">→</span>
                  <input
                    type="text"
                    value={currentStage.photoperiod_off || '08:00 PM'}
                    onChange={(e) => updateActiveStage('photoperiod_off', e.target.value)}
                    className="w-1/2 bg-transparent text-white text-center text-xs font-bold outline-none placeholder:text-slate-600"
                    placeholder="08:00 PM"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Overlap Alert Banner (if any) */}
          {slotWarnings.length > 0 && (
            <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center gap-2.5 shadow-sm">
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400 animate-pulse" />
              <span className="font-medium">Slot Overlap Detected: {slotWarnings.join(' • ')}</span>
            </div>
          )}

          {/* ── 3. FULL-WIDTH DIURNAL TIME SLOTS TABLE ── */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/80 backdrop-blur-sm overflow-hidden shadow-lg shadow-black/20">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between p-4 sm:p-5 border-b border-slate-800 bg-slate-900/95 gap-3">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-sky-500/10 text-sky-400">
                  <Clock className="h-5 w-5" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-white block">
                    Diurnal Setpoints Schedule
                  </h4>
                  <p className="text-xs text-slate-400">
                    {currentStage.time_slots?.length || 0} Time Frame{(currentStage.time_slots?.length || 0) === 1 ? '' : 's'} Configured for {activeRoom}
                  </p>
                </div>
              </div>

              <button
                onClick={handleAddSlot}
                className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/30 text-xs font-semibold transition-all shadow-sm shadow-emerald-500/10 self-end sm:self-center"
              >
                <Plus className="h-4 w-4" />
                <span>Add Time Slot</span>
              </button>
            </div>

            <div className="w-full overflow-x-auto">
              <table className="w-full text-left text-xs min-w-[580px]">
                <thead className="bg-slate-950/80 text-[11px] text-slate-400 font-semibold border-b border-slate-800 uppercase tracking-wider">
                  <tr>
                    <th className="py-2.5 px-3 sm:px-4">Time Window</th>
                    <th className="py-2.5 px-3 sm:px-4">Slot Name</th>
                    <th className="py-2.5 px-3 sm:px-4">Target Temperature</th>
                    <th className="py-2.5 px-3 sm:px-4">Target Humidity</th>
                    <th className="py-2.5 px-3 sm:px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {(!currentStage.time_slots || currentStage.time_slots.length === 0) ? (
                    <tr>
                      <td colSpan={5} className="py-10 text-center text-slate-500 font-sans text-xs">
                        No diurnal time slots configured for this stage. Click "+ Add Time Slot" above to create one.
                      </td>
                    </tr>
                  ) : (
                    currentStage.time_slots.map((slot, idx) => (
                      <tr key={slot.id || idx} className="hover:bg-slate-800/30 transition-colors group">
                        <td className="py-2.5 px-3 sm:px-4 text-slate-200 font-bold">
                          <span className="inline-flex items-center gap-1.5 bg-slate-950/90 border border-slate-800 px-2 py-1 rounded-lg text-emerald-300 text-xs">
                            <Clock className="h-3.5 w-3.5 text-slate-500 shrink-0" />
                            <span>{formatTime12h(slot.start)}</span>
                            <span className="text-slate-500">→</span>
                            <span>{formatTime12h(slot.stop)}</span>
                          </span>
                        </td>
                        <td className="py-2.5 px-3 sm:px-4 font-sans text-white font-medium text-xs">
                          {slot.name || `Slot ${idx + 1}`}
                        </td>
                        <td className="py-2.5 px-3 sm:px-4">
                          <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-2">
                            <span className="font-bold text-amber-300 bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded text-xs font-mono w-fit">
                              {safeFixed(slot.t_set, 1)}°C
                            </span>
                            <span className="text-[10px] text-slate-400 font-mono">
                              [{safeFixed(slot.t_min, 1)} - {safeFixed(slot.t_max, 1)}°C]
                            </span>
                          </div>
                        </td>
                        <td className="py-2.5 px-3 sm:px-4">
                          <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-2">
                            <span className="font-bold text-sky-300 bg-sky-500/10 border border-sky-500/20 px-2 py-0.5 rounded text-xs font-mono w-fit">
                              {safeFixed(slot.h_set, 1)}%
                            </span>
                            <span className="text-[10px] text-slate-400 font-mono">
                              [{safeFixed(slot.h_min, 1)} - {safeFixed(slot.h_max, 1)}%]
                            </span>
                          </div>
                        </td>
                        <td className="py-2.5 px-3 sm:px-4 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              onClick={() => openEditSlot(idx)}
                              className="p-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-400 hover:text-sky-400 hover:border-sky-500/30 transition-colors"
                              title="Edit Slot"
                            >
                              <Edit3 className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => handleDeleteSlot(idx)}
                              disabled={(currentStage.time_slots || []).length <= 1}
                              className="p-1.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-400 hover:text-rose-400 hover:border-rose-500/30 disabled:opacity-30 disabled:hover:text-slate-400 disabled:hover:border-slate-800 transition-colors"
                              title="Delete Slot"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── VIEW 2: APPLIANCES STATE ── */}
      {activeTab === 'relays' && (
        <div className="p-4 sm:p-5 rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800 text-xs gap-2">
            <div>
              <span className="font-bold text-white text-sm block">Appliances State</span>
              <span className="text-slate-400 font-mono text-[11px]">Real-Time Actuator Relay Status for All Configured Rooms</span>
            </div>
            <div className="flex items-center gap-3 self-end sm:self-center">
              <span className="flex items-center gap-1.5 text-emerald-400 font-semibold text-xs">
                <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" /> ACTIVE ON
              </span>
              <span className="flex items-center gap-1.5 text-slate-500 font-semibold text-xs">
                <span className="h-2 w-2 rounded-full bg-slate-600" /> OFF
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 text-xs">
            {['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'].map((sKey, rIdx) => {
              const roomName = systemConfig.sensor_names?.[sKey] || `Room ${rIdx + 1}`;
              const coolCh = (rIdx * 3) + 1;
              const humiCh = (rIdx * 3) + 2;
              const lightCh = (rIdx * 3) + 3;

              const isCoolOn = Boolean(
                relayStates[coolCh] ??
                relayStates[String(coolCh)] ??
                relayStates[`CH${coolCh}`] ??
                liveData[sKey]?.relays?.cooling ??
                liveData[sKey]?.cooling
              );
              const isHumiOn = Boolean(
                relayStates[humiCh] ??
                relayStates[String(humiCh)] ??
                relayStates[`CH${humiCh}`] ??
                liveData[sKey]?.relays?.humidifier ??
                liveData[sKey]?.humidifier
              );
              const isLightOn = Boolean(
                relayStates[lightCh] ??
                relayStates[String(lightCh)] ??
                relayStates[`CH${lightCh}`] ??
                liveData[sKey]?.relays?.grow_lights ??
                liveData[sKey]?.grow_lights
              );
              const coolLabel = sKey === 'S7' ? 'Fanpad Cooling' : 'AC Cooling';

              return (
                <div
                  key={sKey}
                  className="rounded-xl border border-slate-800 bg-slate-950/80 p-3.5 space-y-2.5 shadow-sm"
                >
                  <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
                    <span className="font-bold text-white text-xs truncate">{roomName}</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-slate-800 text-slate-400">
                      {sKey}
                    </span>
                  </div>

                  <div className="space-y-1.5">
                    {/* Cooling */}
                    <div className={`p-2 rounded-lg border flex items-center justify-between transition-all ${
                      isCoolOn
                        ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                        : 'bg-slate-900/60 border-slate-800/80 text-slate-500'
                    }`}>
                      <div className="flex items-center gap-2">
                        <span className={`h-1.5 w-1.5 rounded-full ${isCoolOn ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
                        <span className="text-xs font-semibold">{coolLabel}</span>
                      </div>
                      <span className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded ${
                        isCoolOn ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-500'
                      }`}>
                        {isCoolOn ? 'ON' : 'OFF'}
                      </span>
                    </div>

                    {/* Humidifier */}
                    <div className={`p-2 rounded-lg border flex items-center justify-between transition-all ${
                      isHumiOn
                        ? 'bg-sky-500/10 border-sky-500/30 text-sky-300'
                        : 'bg-slate-900/60 border-slate-800/80 text-slate-500'
                    }`}>
                      <div className="flex items-center gap-2">
                        <span className={`h-1.5 w-1.5 rounded-full ${isHumiOn ? 'bg-sky-400 animate-pulse' : 'bg-slate-600'}`} />
                        <span className="text-xs font-semibold">Humidifier</span>
                      </div>
                      <span className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded ${
                        isHumiOn ? 'bg-sky-500/20 text-sky-300' : 'bg-slate-800 text-slate-500'
                      }`}>
                        {isHumiOn ? 'ON' : 'OFF'}
                      </span>
                    </div>

                    {/* Lights */}
                    <div className={`p-2 rounded-lg border flex items-center justify-between transition-all ${
                      isLightOn
                        ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                        : 'bg-slate-900/60 border-slate-800/80 text-slate-500'
                    }`}>
                      <div className="flex items-center gap-2">
                        <span className={`h-1.5 w-1.5 rounded-full ${isLightOn ? 'bg-amber-400 animate-pulse' : 'bg-slate-600'}`} />
                        <span className="text-xs font-semibold">Grow Lights</span>
                      </div>
                      <span className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded ${
                        isLightOn ? 'bg-amber-500/20 text-amber-300' : 'bg-slate-800 text-slate-500'
                      }`}>
                        {isLightOn ? 'ON' : 'OFF'}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}

            {/* System Alarm Card */}
            <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-3.5 space-y-2.5 shadow-sm flex flex-col justify-between">
              <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
                <span className="font-bold text-white text-xs">System Safety</span>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-slate-800 text-slate-400">
                  ALARM
                </span>
              </div>

              <div className={`p-3 rounded-lg border flex items-center justify-between transition-all ${
                relayStates[22]
                  ? 'bg-rose-500/10 border-rose-500/30 text-rose-300'
                  : 'bg-slate-900/60 border-slate-800/80 text-slate-500'
              }`}>
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${relayStates[22] ? 'bg-rose-400 animate-pulse' : 'bg-slate-600'}`} />
                  <span className="text-xs font-semibold">Siren Buzzer Alarm</span>
                </div>
                <span className={`font-mono text-[10px] font-bold px-2 py-0.5 rounded ${
                  relayStates[22] ? 'bg-rose-500/20 text-rose-300' : 'bg-slate-800 text-slate-500'
                }`}>
                  {relayStates[22] ? 'ACTIVE' : 'OFF'}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: EDIT TIME SLOT ── */}
      {showSlotModal && slotForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/70 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-lg rounded-2xl bg-slate-900 border border-slate-700/80 shadow-2xl p-5 sm:p-6 space-y-4 text-xs max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <span className="font-bold text-white text-sm">Edit Diurnal Time Slot</span>
              <button onClick={() => setShowSlotModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-3.5">
              <div>
                <label className="text-slate-400 block mb-1 font-semibold">Slot Name</label>
                <input
                  type="text"
                  value={slotForm.name || ''}
                  onChange={(e) => setSlotForm({ ...slotForm, name: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-700 focus:border-emerald-500 rounded-xl px-3 py-2 text-white outline-none transition-colors"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-slate-400 block mb-1 font-semibold">Start Time</label>
                  <input
                    type="text"
                    value={slotForm.start || ''}
                    onChange={(e) => setSlotForm({ ...slotForm, start: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 focus:border-emerald-500 rounded-xl px-3 py-2 text-white font-mono"
                    placeholder="06:00 AM"
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-1 font-semibold">Stop Time</label>
                  <input
                    type="text"
                    value={slotForm.stop || ''}
                    onChange={(e) => setSlotForm({ ...slotForm, stop: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-700 focus:border-emerald-500 rounded-xl px-3 py-2 text-white font-mono"
                    placeholder="12:00 PM"
                  />
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                <span className="text-xs font-bold text-amber-400 flex items-center gap-1.5">
                  <Thermometer className="h-3.5 w-3.5" /> Temperature Targets (°C)
                </span>
                <div className="grid grid-cols-3 gap-2.5 font-mono">
                  <div>
                    <label className="text-[10px] text-slate-400 block mb-1">Target</label>
                    <input
                      type="number"
                      step="0.1"
                      value={slotForm.t_set ?? 24.0}
                      onChange={(e) => setSlotForm({ ...slotForm, t_set: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-amber-500/60 rounded-lg px-2.5 py-1.5 text-white"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-slate-400 block mb-1">Min</label>
                    <input
                      type="number"
                      step="0.1"
                      value={slotForm.t_min ?? 20.0}
                      onChange={(e) => setSlotForm({ ...slotForm, t_min: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-amber-500/60 rounded-lg px-2.5 py-1.5 text-white"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-slate-400 block mb-1">Max</label>
                    <input
                      type="number"
                      step="0.1"
                      value={slotForm.t_max ?? 26.0}
                      onChange={(e) => setSlotForm({ ...slotForm, t_max: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-amber-500/60 rounded-lg px-2.5 py-1.5 text-white"
                    />
                  </div>
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                <span className="text-xs font-bold text-sky-400 flex items-center gap-1.5">
                  <Droplets className="h-3.5 w-3.5" /> Humidity Targets (%)
                </span>
                <div className="grid grid-cols-3 gap-2.5 font-mono">
                  <div>
                    <label className="text-[10px] text-slate-400 block mb-1">Target</label>
                    <input
                      type="number"
                      step="0.1"
                      value={slotForm.h_set ?? 60.0}
                      onChange={(e) => setSlotForm({ ...slotForm, h_set: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-sky-500/60 rounded-lg px-2.5 py-1.5 text-white"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-slate-400 block mb-1">Min</label>
                    <input
                      type="number"
                      step="0.1"
                      value={slotForm.h_min ?? 55.0}
                      onChange={(e) => setSlotForm({ ...slotForm, h_min: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-sky-500/60 rounded-lg px-2.5 py-1.5 text-white"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-slate-400 block mb-1">Max</label>
                    <input
                      type="number"
                      step="0.1"
                      value={slotForm.h_max ?? 70.0}
                      onChange={(e) => setSlotForm({ ...slotForm, h_max: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-sky-500/60 rounded-lg px-2.5 py-1.5 text-white"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-slate-800">
              <button
                onClick={() => setShowSlotModal(false)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveSlotForm}
                className="px-5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold transition-all shadow-sm shadow-emerald-500/20"
              >
                Apply Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: SYSTEM CONFIG & ALARMS ── */}
      {showConfigModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/75 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-lg rounded-2xl bg-slate-900 border border-slate-700/80 shadow-2xl p-5 sm:p-6 space-y-5 text-xs max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Sliders className="h-4 w-4 text-sky-400" />
                <span className="font-bold text-white text-sm">System & Cloud Configuration</span>
              </div>
              <button onClick={() => setShowConfigModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-4">
              {/* Cloud Upload Frequency */}
              <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 space-y-3">
                <div className="flex items-center justify-between">
                  <label className="text-slate-300 font-semibold flex items-center gap-1.5">
                    <Clock className="h-3.5 w-3.5 text-sky-400" />
                    <span>Cloud Telemetry Upload Frequency</span>
                  </label>
                  <span className="px-2 py-0.5 rounded-md bg-sky-500/10 border border-sky-500/30 text-sky-400 font-mono text-[11px] font-bold">
                    {formatUploadHmsDisplay(systemConfig.upload_hours, systemConfig.upload_mins, systemConfig.upload_secs, systemConfig.upload_frequency_min)}
                  </span>
                </div>

                {/* Quick Preset Buttons */}
                <div>
                  <span className="text-[10px] text-slate-400 block mb-1.5 uppercase font-medium tracking-wider">Quick Presets</span>
                  <div className="grid grid-cols-4 sm:grid-cols-7 gap-1.5">
                    {[
                      { label: '1s (Stream)', h: 0, m: 0, s: 0 },
                      { label: '30s', h: 0, m: 0, s: 30 },
                      { label: '1m', h: 0, m: 1, s: 0 },
                      { label: '5m', h: 0, m: 5, s: 0 },
                      { label: '15m', h: 0, m: 15, s: 0 },
                      { label: '30m', h: 0, m: 30, s: 0 },
                      { label: '1h', h: 1, m: 0, s: 0 },
                    ].map((preset) => {
                      const curSec = (Number(systemConfig.upload_hours || 0) * 3600) + (Number(systemConfig.upload_mins || 0) * 60) + Number(systemConfig.upload_secs || 0);
                      const targetSec = (preset.h * 3600) + (preset.m * 60) + preset.s;
                      const isSelected = (curSec === targetSec) || (targetSec === 0 && curSec <= 1);
                      return (
                        <button
                          key={preset.label}
                          type="button"
                          onClick={() => {
                            setSystemConfig(prev => ({
                              ...prev,
                              upload_hours: preset.h,
                              upload_mins: preset.m,
                              upload_secs: preset.s,
                              upload_frequency_min: +(targetSec / 60).toFixed(4),
                              upload_frequency_sec: targetSec > 0 ? targetSec : 1
                            }));
                          }}
                          className={`px-2 py-1.5 rounded-lg text-center font-medium transition-all text-[11px] ${
                            isSelected
                              ? 'bg-sky-500 text-slate-950 font-bold shadow-sm shadow-sky-500/20'
                              : 'bg-slate-850 hover:bg-slate-800 text-slate-300 border border-slate-750'
                          }`}
                        >
                          {preset.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Keypad HMS Number Inputs (Hour / Min / Sec) */}
                <div>
                  <span className="text-[10px] text-slate-400 block mb-1.5 uppercase font-medium tracking-wider">Custom Time Inputs (HH : MM : SS)</span>
                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <label className="text-[10px] text-slate-400 block mb-0.5">Hours (0-23)</label>
                      <input
                        type="number"
                        min="0"
                        max="23"
                        value={systemConfig.upload_hours ?? 0}
                        onChange={(e) => {
                          const h = Math.max(0, Math.min(23, parseInt(e.target.value, 10) || 0));
                          setSystemConfig(prev => ({ ...prev, upload_hours: h }));
                        }}
                        className="w-full bg-slate-900 border border-slate-700 focus:border-sky-500 rounded-xl px-3 py-2 text-white font-mono text-center text-sm font-bold outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] text-slate-400 block mb-0.5">Minutes (0-59)</label>
                      <input
                        type="number"
                        min="0"
                        max="59"
                        value={systemConfig.upload_mins ?? 0}
                        onChange={(e) => {
                          const m = Math.max(0, Math.min(59, parseInt(e.target.value, 10) || 0));
                          setSystemConfig(prev => ({ ...prev, upload_mins: m }));
                        }}
                        className="w-full bg-slate-900 border border-slate-700 focus:border-sky-500 rounded-xl px-3 py-2 text-white font-mono text-center text-sm font-bold outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] text-slate-400 block mb-0.5">Seconds (0-59)</label>
                      <input
                        type="number"
                        min="0"
                        max="59"
                        value={systemConfig.upload_secs ?? 0}
                        onChange={(e) => {
                          const s = Math.max(0, Math.min(59, parseInt(e.target.value, 10) || 0));
                          setSystemConfig(prev => ({ ...prev, upload_secs: s }));
                        }}
                        className="w-full bg-slate-900 border border-slate-700 focus:border-sky-500 rounded-xl px-3 py-2 text-white font-mono text-center text-sm font-bold outline-none"
                      />
                    </div>
                  </div>
                  <p className="text-[10.5px] text-slate-400 mt-1.5 italic">
                    Note: Setting 00:00:00 will transmit live per-second telemetry data stream to the cloud.
                  </p>
                </div>
              </div>

              {/* Deviation & Alarm Offsets */}
              <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 space-y-3">
                <div className="flex items-center gap-1.5 text-slate-300 font-semibold">
                  <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                  <span>Alarm Deviation Limits</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="text-slate-400 block mb-1 text-[11px]">Temp Deviation Limit (± °C)</label>
                    <input
                      type="number"
                      step="0.5"
                      min="0.5"
                      max="20"
                      value={systemConfig.temp_alarm_offset ?? 5.0}
                      onChange={(e) => setSystemConfig({ ...systemConfig, temp_alarm_offset: parseFloat(e.target.value) || 5.0 })}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-amber-500 rounded-xl px-3 py-2 text-white font-mono text-sm font-bold outline-none"
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 block mb-1 text-[11px]">Humidity Deviation Limit (± %)</label>
                    <input
                      type="number"
                      step="0.5"
                      min="0.5"
                      max="50"
                      value={systemConfig.humi_alarm_offset ?? 5.0}
                      onChange={(e) => setSystemConfig({ ...systemConfig, humi_alarm_offset: parseFloat(e.target.value) || 5.0 })}
                      className="w-full bg-slate-900 border border-slate-700 focus:border-amber-500 rounded-xl px-3 py-2 text-white font-mono text-sm font-bold outline-none"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-slate-800">
              <button
                onClick={() => setShowConfigModal(false)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
              >
                Close
              </button>
              <button
                onClick={() => {
                  setShowConfigModal(false);
                  handleSaveSystemConfig();
                }}
                className="px-5 py-2 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold transition-all shadow-sm shadow-sky-500/20"
              >
                Save Configuration
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: RENAME ROOM ── */}
      {showRenameModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/70 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-sm rounded-2xl bg-slate-900 border border-slate-700/80 shadow-2xl p-5 space-y-3.5 text-xs">
            <div className="flex items-center justify-between pb-2 border-b border-slate-800">
              <span className="font-bold text-white text-sm">Rename Room ({activeRoom})</span>
              <button onClick={() => setShowRenameModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-white">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div>
              <label className="text-slate-400 block mb-1">Room Display Name</label>
              <input
                type="text"
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 focus:border-emerald-500 rounded-xl px-3 py-2 text-white font-bold outline-none"
                placeholder="e.g. Cold Room 1"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setShowRenameModal(false)} className="px-3.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300">
                Cancel
              </button>
              <button
                onClick={() => {
                  if (renameValue.trim()) {
                    const updatedNames = { ...systemConfig.sensor_names, [activeRoom]: renameValue.trim() };
                    const updatedCfg = { ...systemConfig, sensor_names: updatedNames };
                    setSystemConfig(updatedCfg);
                    handleSaveSystemConfig(updatedCfg);
                  }
                  setShowRenameModal(false);
                }}
                className="px-4 py-1.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: SAVE PROGRAM ── */}
      {showSaveProgramModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/75 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-md rounded-2xl bg-slate-900 border border-slate-700/80 shadow-2xl p-5 sm:p-6 space-y-4 text-slate-100">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Bookmark className="h-4 w-4 text-emerald-400" />
                <h4 className="text-sm font-bold text-white">Save Current Program</h4>
              </div>
              <button
                onClick={() => setShowSaveProgramModal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <p className="text-xs text-slate-400 leading-relaxed">
              Save the current stage configuration ({activeStagesCount} stages) for {systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]} into your preset programs library.
            </p>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300">Program Name</label>
              <input
                type="text"
                value={presetNameInput}
                onChange={(e) => setPresetNameInput(e.target.value)}
                placeholder="e.g. Strawberry Autumn Cycle"
                className="w-full bg-slate-950 border border-slate-700 focus:border-emerald-500 rounded-xl px-3 py-2 text-white text-xs outline-none transition-colors"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
              <button
                onClick={() => setShowSaveProgramModal(false)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (presetNameInput.trim()) {
                    handleSaveCurrentAsProgram(presetNameInput.trim());
                    setShowSaveProgramModal(false);
                  }
                }}
                disabled={!presetNameInput.trim()}
                className="px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-bold transition-all disabled:opacity-50"
              >
                Save & Activate Program
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: PRESET PROGRAMS (DEVICE MEMORY) ── */}
      {showPresetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/70 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-lg rounded-2xl bg-slate-900 border border-slate-700/80 shadow-2xl p-5 sm:p-6 space-y-4 text-xs max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div>
                <div className="flex items-center gap-2">
                  <Bookmark className="h-4 w-4 text-sky-400" />
                  <span className="font-bold text-white text-sm">Saved Device Programs</span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-slate-300 font-mono">
                    {currentRoomPrograms.length}/20 Saved
                  </span>
                </div>
                <span className="text-slate-400 text-[11px] block mt-0.5">
                  Programs stored in device memory for {systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]}
                </span>
              </div>
              <button onClick={() => setShowPresetModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-2.5">
              {currentRoomPrograms.length === 0 ? (
                <div className="p-6 text-center rounded-xl bg-slate-950/60 border border-slate-800/80 space-y-2">
                  <Bookmark className="h-8 w-8 text-slate-600 mx-auto" />
                  <p className="font-semibold text-slate-300">No Saved Programs on Device</p>
                  <p className="text-slate-400 text-[11px] max-w-xs mx-auto">
                    No custom preset programs are currently saved for {systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]}.
                    Configure your schedule above and click <strong className="text-emerald-400">Save Program</strong> to store it in device memory.
                  </p>
                </div>
              ) : (
                currentRoomPrograms.map(preset => {
                  const isActive = preset.name === currentRoomSetpoints.program_name;
                  return (
                    <div key={preset.name} className={`flex flex-col sm:flex-row sm:items-center justify-between p-3 rounded-xl border transition-colors gap-2 ${
                      isActive ? 'bg-emerald-950/20 border-emerald-500/40' : 'bg-slate-950/80 border-slate-800 hover:border-slate-700'
                    }`}>
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-white text-xs block">{preset.name}</span>
                          {isActive && (
                            <span className="text-[10px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-1.5 py-0.2 rounded font-semibold">Active on Device</span>
                          )}
                        </div>
                        <span className="text-[11px] text-slate-400 block">{preset.desc}</span>
                      </div>
                      <div className="flex items-center gap-2 self-end sm:self-center">
                        <button
                          onClick={() => {
                            handleApplyPresetProgram(preset.name);
                            setShowPresetModal(false);
                          }}
                          disabled={isActive}
                          className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all border ${
                            isActive
                              ? 'bg-slate-800 text-slate-500 border-slate-700 opacity-60 cursor-default'
                              : 'bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border-emerald-500/30'
                          }`}
                        >
                          {isActive ? 'Loaded' : 'Apply Program'}
                        </button>
                        <button
                          onClick={() => handleDeleteProgram(preset.name)}
                          className="p-1.5 rounded-xl bg-slate-800 hover:bg-rose-500/20 text-slate-400 hover:text-rose-400 transition-colors"
                          title="Delete Program from Device"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            <div className="flex items-center justify-between pt-3 border-t border-slate-800">
              <button
                onClick={() => {
                  setShowPresetModal(false);
                  setPresetNameInput(currentRoomSetpoints.program_name && currentRoomSetpoints.program_name !== 'Default Program'
                    ? currentRoomSetpoints.program_name
                    : `Program ${currentRoomPrograms.length + 1}`);
                  setShowSaveProgramModal(true);
                }}
                className="px-3 py-2 rounded-xl bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/30 text-xs font-bold transition-all"
              >
                + Save Current Settings as Program
              </button>
              <button onClick={() => setShowPresetModal(false)} className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300">
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: CONFIRM REMOTE RESTART / EXIT ── */}
      {confirmModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-md rounded-2xl bg-slate-900 border border-slate-700/80 shadow-2xl p-5 sm:p-6 space-y-4 text-slate-100">
            <div className="flex items-center gap-3">
              <div className={`h-11 w-11 rounded-xl flex items-center justify-center shrink-0 ${confirmModal.action === 'restart' ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30' : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'}`}>
                {confirmModal.action === 'restart' ? <RotateCw className="h-5 w-5" /> : <PowerOff className="h-5 w-5" />}
              </div>
              <div>
                <h3 className="text-base font-bold text-white capitalize">
                  Confirm Remote {confirmModal.action === 'restart' ? 'Restart' : 'Exit'}
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Target Device: <span className="text-slate-200 font-semibold">{(selectedDevice?.name || 'Almora Cold Storage').replace(/\s*\([^)]*\)/g, '').trim()}</span>
                </p>
              </div>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed bg-slate-950/60 p-3.5 rounded-xl border border-slate-800">
              {confirmModal.action === 'restart'
                ? 'Are you sure you want to reboot the controller program? The hardware will safely reset relays and restart within a few seconds.'
                : 'Are you sure you want to exit the controller program? All relays will be turned OFF for safety.'}
            </p>

            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-slate-800/80">
              <button
                type="button"
                onClick={() => setConfirmModal({ open: false, action: null })}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleDeviceCommand(confirmModal.action)}
                className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold transition-all shadow-md ${confirmModal.action === 'restart'
                  ? 'bg-amber-500 hover:bg-amber-400 text-slate-950 shadow-amber-500/20'
                  : 'bg-rose-600 hover:bg-rose-500 text-white shadow-rose-600/20'}`}
              >
                {confirmModal.action === 'restart' ? <RotateCw className="h-3.5 w-3.5" /> : <PowerOff className="h-3.5 w-3.5" />}
                <span>Yes, {confirmModal.action === 'restart' ? 'Restart' : 'Exit'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ColdStorageSettings;
