import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Save, RefreshCw, ChevronDown, Server, Thermometer, Droplets, Activity,
  Wind, Sun, Clock, Calendar, Plus, Trash2, Edit3, Sliders, Power, Zap,
  CheckCircle2, X, Bell, Bookmark, RotateCcw, AlertTriangle, ChevronRight,
  ChevronLeft, Sparkles, Check, Sprout, Layers
} from 'lucide-react';
import { createMqttClient } from '../../utils/mqtt';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

// --- TIME FORMATTING HELPERS ---
export const formatTime12h = (tStr) => {
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

export const formatTime24h = (tStr) => {
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

export const timeToMinutes = (tStr) => {
  const t24 = formatTime24h(tStr);
  const parts = t24.split(':');
  const h = parseInt(parts[0] || '0', 10);
  const m = parseInt(parts[1] || '0', 10);
  return h * 60 + m;
};

export const checkTimeSlotOverlaps = (slots) => {
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

// --- ALMORA DEFAULTS ---
export const ALL_SETTING_KEYS = [
  'Setting A', 'Setting B', 'Setting C', 'Setting D', 'Setting E',
  'Setting F', 'Setting G', 'Setting H', 'Setting I', 'Setting J'
];

export const SENSOR_KEYS = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'];

export const DEFAULT_ROOM_NAMES = {
  S1: 'Cold Room 1',
  S2: 'Cold Room 2',
  S3: 'Cold Room 3',
  S4: 'Cold Room 4',
  S5: 'Cold Room 5',
  S6: 'Cold Room 6',
  S7: 'Greenhouse'
};

export const DEFAULT_ROOM_CROPS = {
  S1: 'Strawberry',
  S2: 'Blueberry',
  S3: 'Apples / Pears',
  S4: 'Leafy Greens',
  S5: 'Herbs & Microgreens',
  S6: 'Vegetables',
  S7: 'Greenhouse - Flowers & Seedlings'
};

export const DEFAULT_ROOM_SETUPS = {
  S1: 'Strawberry Storage Setup',
  S2: 'Blueberry Storage Setup',
  S3: 'Apples / Pears Storage Setup',
  S4: 'Leafy Greens Storage Setup',
  S5: 'Herbs & Microgreens Storage Setup',
  S6: 'Vegetables Storage Setup',
  S7: 'Greenhouse Hydroponic Setup'
};

export const generateDefaultAlmoraSchedule = (sKey = 'S1') => {
  const defaultCrop = DEFAULT_ROOM_CROPS[sKey] || `${DEFAULT_ROOM_NAMES[sKey] || sKey} Crop`;
  const defaultSetup = DEFAULT_ROOM_SETUPS[sKey] || `${DEFAULT_ROOM_NAMES[sKey] || sKey} Setup`;

  const stages = {};
  const stageDefs = [
    { key: 'Setting A', name: 'Crop Stage 1', start: '2026-07-01', end: '2026-07-15' },
    { key: 'Setting B', name: 'Crop Stage 2', start: '2026-07-16', end: '2026-07-31' },
    { key: 'Setting C', name: 'Crop Stage 3', start: '2026-08-01', end: '2026-08-15' },
    { key: 'Setting D', name: 'Crop Stage 4', start: '2026-08-16', end: '2026-08-31' },
    { key: 'Setting E', name: 'Crop Stage 5', start: '2026-09-01', end: '2026-09-15' },
    { key: 'Setting F', name: 'Crop Stage 6', start: '2026-09-16', end: '2026-09-30' },
    { key: 'Setting G', name: 'Crop Stage 7', start: '2026-10-01', end: '2026-10-15' },
    { key: 'Setting H', name: 'Crop Stage 8', start: '2026-10-16', end: '2026-10-31' },
    { key: 'Setting I', name: 'Crop Stage 9', start: '2026-11-01', end: '2026-11-15' },
    { key: 'Setting J', name: 'Crop Stage 10', start: '2026-11-16', end: '2026-11-30' }
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
        { id: 1, name: 'Early Morning', start: '12:00 AM', stop: '05:00 AM', t_set: 24.0, t_max: 25.0, t_min: 20.0, h_set: 60.0, h_max: 70.0, h_min: 55.0, enabled: true },
        { id: 2, name: 'Morning Light', start: '05:00 AM', stop: '10:00 AM', t_set: 25.0, t_max: 26.0, t_min: 21.0, h_set: 65.0, h_max: 70.0, h_min: 60.0, enabled: true },
        { id: 3, name: 'Midday Peak', start: '10:00 AM', stop: '03:00 PM', t_set: 27.0, t_max: 28.0, t_min: 23.0, h_set: 70.0, h_max: 75.0, h_min: 60.0, enabled: true },
        { id: 4, name: 'Late Afternoon', start: '03:00 PM', stop: '08:00 PM', t_set: 26.0, t_max: 27.0, t_min: 22.0, h_set: 68.0, h_max: 72.0, h_min: 60.0, enabled: true },
        { id: 5, name: 'Night Cooling', start: '08:00 PM', stop: '12:00 AM', t_set: 24.0, t_max: 25.0, t_min: 20.0, h_set: 62.0, h_max: 68.0, h_min: 55.0, enabled: true }
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

export const autoChainDates = (settingsDict, changedKey) => {
  const newSettings = JSON.parse(JSON.stringify(settingsDict || {}));
  const stages = ALL_SETTING_KEYS.filter(k => k in newSettings);
  const startIdx = stages.indexOf(changedKey);
  if (startIdx === -1) return newSettings;

  const cur = newSettings[changedKey];
  let curStart = new Date(cur.start_date);
  let curEnd = new Date(cur.end_date);
  if (isNaN(curStart.getTime()) || isNaN(curEnd.getTime())) return newSettings;
  if (curEnd < curStart) {
    curEnd = new Date(curStart);
    cur.end_date = curEnd.toISOString().split('T')[0];
  }

  for (let i = startIdx; i < stages.length - 1; i++) {
    const cKey = stages[i];
    const nKey = stages[i + 1];
    const cObj = newSettings[cKey];
    const nObj = newSettings[nKey];
    if (!cObj || !nObj) continue;

    const cEndD = new Date(cObj.end_date);
    const nStartOrig = new Date(nObj.start_date);
    const nEndOrig = new Date(nObj.end_date);

    let durationDays = 14;
    if (!isNaN(nStartOrig.getTime()) && !isNaN(nEndOrig.getTime()) && nEndOrig >= nStartOrig) {
      durationDays = Math.max(1, Math.round((nEndOrig - nStartOrig) / (1000 * 60 * 60 * 24)) + 1);
    }

    const nextStart = new Date(cEndD);
    nextStart.setDate(nextStart.getDate() + 1);

    const nextEnd = new Date(nextStart);
    nextEnd.setDate(nextEnd.getDate() + durationDays - 1);

    nObj.start_date = nextStart.toISOString().split('T')[0];
    nObj.end_date = nextEnd.toISOString().split('T')[0];
  }

  return newSettings;
};

// --- DEFAULT RECIPES ---
const BUILTIN_PRESETS = [
  {
    name: 'Strawberry Cycle',
    crop_name: 'Strawberry',
    setup_name: 'Cold Storage Room Setup',
    desc: 'Cool climate, 14-hour photoperiod, staged vegetative to fruiting',
    settings: generateDefaultAlmoraSchedule('S1').settings
  },
  {
    name: 'Leafy Greens & Lettuce',
    crop_name: 'Leafy Greens & Lettuce',
    setup_name: 'Vertical Hydroponic Rack',
    desc: '18-22°C, 65-75% RH, 16-hour light cycle',
    settings: generateDefaultAlmoraSchedule('S4').settings
  },
  {
    name: 'Blueberry Cold Storage',
    crop_name: 'Blueberry',
    setup_name: 'Cold Storage Room Setup',
    desc: 'Optimal cooling and humidity storage',
    settings: generateDefaultAlmoraSchedule('S2').settings
  },
  {
    name: 'Greenhouse Flora & Nursery',
    crop_name: 'Flowers & Nursery',
    setup_name: 'Greenhouse Hydroponic Setup',
    desc: 'Fanpad and misting control for greenhouse environments',
    settings: generateDefaultAlmoraSchedule('S7').settings
  }
];

const ColdStorageSettings = () => {
  // Device & API State
  const [devices, setDevices] = useState([]);
  const [selectedMqttId, setSelectedMqttId] = useState('control122');
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState('disconnected');
  const [statusMsg, setStatusMsg] = useState('');
  const [client, setClient] = useState(null);

  // Setpoints & System Configuration
  const [allSetpoints, setAllSetpoints] = useState({});
  const [activeRoom, setActiveRoom] = useState('S1');
  const [activeStageKey, setActiveStageKey] = useState('Setting A');
  const [systemConfig, setSystemConfig] = useState({
    upload_frequency_min: 0,
    temp_alarm_offset: 5.0,
    humi_alarm_offset: 5.0,
    relay_port: '/dev/serial/by-path/usb-0:1:2:1:0-port0',
    sensor_names: { ...DEFAULT_ROOM_NAMES }
  });

  // Telemetry & Hardware Matrix
  const [liveData, setLiveData] = useState({});
  const [relayStates, setRelayStates] = useState({});
  const [activeWarnings, setActiveWarnings] = useState([]);
  const [chartData, setChartData] = useState([]);

  // Modals & Navigation
  const [activeTab, setActiveTab] = useState('control'); // 'control' | 'relays' | 'trends'
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [showRenameModal, setShowRenameModal] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const [showSlotModal, setShowSlotModal] = useState(false);
  const [editingSlotIdx, setEditingSlotIdx] = useState(null);
  const [slotForm, setSlotForm] = useState(null);
  const [savedPresets, setSavedPresets] = useState([]);
  const [showPresetModal, setShowPresetModal] = useState(false);
  const [presetNameInput, setPresetNameInput] = useState('');

  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // Get or initialize room setpoints
  const getRoomSetpoints = useCallback((sKey) => {
    if (allSetpoints[sKey]) return allSetpoints[sKey];
    return generateDefaultAlmoraSchedule(sKey);
  }, [allSetpoints]);

  const currentRoomSetpoints = getRoomSetpoints(activeRoom);
  const currentStage = (currentRoomSetpoints.settings && currentRoomSetpoints.settings[activeStageKey]) ||
    generateDefaultAlmoraSchedule(activeRoom).settings[activeStageKey] || {};

  // Fetch registered devices
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.success && Array.isArray(data.data)) {
          let list = data.data;
          // Ensure control122 is selectable if from hardware
          const hasControl122 = list.some(d => (d.mqttId || d._id) === 'control122');
          if (!hasControl122) {
            list = [{ _id: 'control122', name: 'Almora Controller (control122)', mqttId: 'control122' }, ...list];
          }
          setDevices(list);
          if (!selectedMqttId && list.length > 0) {
            setSelectedMqttId(list[0].mqttId || list[0]._id);
          }
        }
      } catch (err) {
        console.error('Failed to fetch devices', err);
      } finally {
        setLoading(false);
      }
    };
    fetchDevices();
  }, [token, API_BASE]);

  const selectedDevice = devices.find(d => (d.mqttId || d._id) === selectedMqttId);

  // Load Presets
  useEffect(() => {
    try {
      const stored = localStorage.getItem(`almora_presets_${selectedMqttId}`);
      if (stored) setSavedPresets(JSON.parse(stored));
      else setSavedPresets(BUILTIN_PRESETS);
    } catch {
      setSavedPresets(BUILTIN_PRESETS);
    }
  }, [selectedMqttId]);

  // Robust Telemetry Normalizer (Extracts S1..S7 from any packet structure)
  const processIncomingTelemetry = useCallback((payload) => {
    if (!payload) return;

    // 1. Process Setpoints & Config if present
    if (payload.sensor_setpoints) {
      setAllSetpoints(prev => ({ ...prev, ...payload.sensor_setpoints }));
    }
    if (payload.port && payload.settings) {
      setAllSetpoints(prev => ({ ...prev, [payload.port]: { ...(prev[payload.port] || {}), ...payload } }));
    }
    if (payload.system_config) {
      setSystemConfig(prev => ({
        ...prev,
        ...payload.system_config,
        sensor_names: {
          ...DEFAULT_ROOM_NAMES,
          ...(payload.system_config.sensor_names || {})
        }
      }));
    }
    if (payload.relay_states) {
      setRelayStates(payload.relay_states);
    }
    if (Array.isArray(payload.active_warnings)) {
      setActiveWarnings(payload.active_warnings);
    }

    // 2. Normalize sensor readings to S1..S7
    const normalized = {};

    // Check payload.sensor_data (standard from sensor_monitor2_almora.py)
    const rawSensors = payload.sensor_data || (payload.S1 ? payload : null);

    if (rawSensors && typeof rawSensors === 'object') {
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
    }

    if (Object.keys(normalized).length > 0) {
      setLiveData(prev => ({ ...prev, ...normalized }));

      // Append point to trends
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
  }, []);

  // --- DUAL-CHANNEL REAL-TIME SYNC (MQTT WEBSOCKET + SSE FALLBACK) ---
  useEffect(() => {
    if (!selectedMqttId) return;
    setStatus('disconnected');

    // 1. MQTT WebSocket Connection
    const mqttClient = createMqttClient();

    mqttClient.on('connect', () => {
      setStatus('connected');
      mqttClient.subscribe(`inhydro/${selectedMqttId}/setpoints/current`);
      mqttClient.subscribe(`inhydro/${selectedMqttId}/telemetry/live`);
      mqttClient.publish(`inhydro/${selectedMqttId}/setpoints/request_sync`, '1');
    });

    mqttClient.on('message', (topic, message) => {
      try {
        const payload = JSON.parse(message.toString());
        processIncomingTelemetry(payload);
      } catch (err) {
        console.debug('MQTT parse error', err);
      }
    });

    mqttClient.on('error', () => {
      setStatus('error');
    });

    setClient(mqttClient);

    // 2. Real-time SSE Stream Fallback (Guarantees data flow via Backend even if raw WS is blocked)
    const sseUrl = `${API_BASE}/api/devices/stream?deviceId=${selectedDevice?._id || ''}&mqttId=${selectedMqttId}`;
    let eventSource = null;
    try {
      eventSource = new EventSource(sseUrl);
      eventSource.onopen = () => setStatus('connected');
      eventSource.onmessage = (event) => {
        try {
          const packet = JSON.parse(event.data);
          if (packet.mqttId === selectedMqttId || packet.topic?.includes(selectedMqttId)) {
            setStatus('connected');
            processIncomingTelemetry(packet.data);
          }
        } catch { }
      };
    } catch (e) { }

    return () => {
      if (mqttClient) mqttClient.end();
      if (eventSource) eventSource.close();
    };
  }, [selectedMqttId, selectedDevice, API_BASE, processIncomingTelemetry]);

  // Request sync from physical device
  const handleRequestSync = () => {
    if (client && client.connected) {
      client.publish(`inhydro/${selectedMqttId}/setpoints/request_sync`, '1');
    }
    if (selectedDevice?._id) {
      fetch(`${API_BASE}/api/devices/${selectedDevice._id}/setpoints?action=sync`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      }).catch(() => { });
    }
    setStatusMsg('Sync command sent to hardware...');
    setTimeout(() => setStatusMsg(''), 2500);
  };

  // State update helpers
  const updateRoomState = (updater) => {
    setAllSetpoints(prev => {
      const cur = prev[activeRoom] ? JSON.parse(JSON.stringify(prev[activeRoom])) : generateDefaultAlmoraSchedule(activeRoom);
      const updated = updater(cur);
      return { ...prev, [activeRoom]: updated };
    });
  };

  const updateActiveStage = (field, val) => {
    updateRoomState(room => {
      const st = room.settings[activeStageKey] || {};
      st[field] = val;
      room.settings[activeStageKey] = st;
      return room;
    });
  };

  const handleStageDateChange = (field, dateStr) => {
    updateRoomState(room => {
      const st = room.settings[activeStageKey] || {};
      st[field] = dateStr;
      room.settings[activeStageKey] = st;
      room.settings = autoChainDates(room.settings, activeStageKey);
      return room;
    });
  };

  // Save changes to device
  const handleSaveToDevice = async () => {
    setStatus('saving');
    setStatusMsg('Pushing setpoints to hardware...');

    const curRoomData = currentRoomSetpoints;
    const roomCrop = currentStage.crop_name || curRoomData.crop_name || DEFAULT_ROOM_CROPS[activeRoom] || 'Strawberry';
    const roomSetup = currentStage.setup_name || curRoomData.setup_name || DEFAULT_ROOM_SETUPS[activeRoom] || 'Cold Storage Room Setup';
    const payload = {
      port: activeRoom,
      crop_name: roomCrop,
      setup_name: roomSetup,
      mode: curRoomData.mode || 'SCHEDULED',
      'T MIN': curRoomData['T MIN'] ?? 10.0,
      'T MAX': curRoomData['T MAX'] ?? 30.0,
      'H MIN': curRoomData['H MIN'] ?? 30.0,
      'H MAX': curRoomData['H MAX'] ?? 80.0,
      settings: curRoomData.settings || {},
      system_config: systemConfig,
      upload_frequency_min: systemConfig.upload_frequency_min,
      temp_alarm_offset: systemConfig.temp_alarm_offset,
      humi_alarm_offset: systemConfig.humi_alarm_offset,
      sensor_names: systemConfig.sensor_names
    };

    if (client && client.connected) {
      try {
        client.publish(`inhydro/${selectedMqttId}/setpoints/update`, JSON.stringify(payload), { retain: true });
      } catch (err) {
        console.error('MQTT publish err', err);
      }
    }

    if (selectedDevice?._id) {
      try {
        await fetch(`${API_BASE}/api/devices/${selectedDevice._id}/setpoints`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(payload)
        });
      } catch (err) {
        console.error('REST sync err', err);
      }
    }

    setStatus('saved');
    setStatusMsg('Setpoints updated successfully!');
    setTimeout(() => {
      setStatus('connected');
      setStatusMsg('');
    }, 2000);
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

  const isMachineOnline = selectedDevice?.status === 'online';

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
                  {d.name} ({d.mqttId || 'No ID'})
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

          {/* Presets */}
          <button
            onClick={() => setShowPresetModal(true)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-xs font-medium text-slate-200 hover:text-white transition-all shadow-sm"
          >
            <Bookmark className="h-3.5 w-3.5 text-emerald-400" />
            <span>Presets</span>
          </button>

          {/* Config */}
          <button
            onClick={() => setShowConfigModal(true)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-xs font-medium text-slate-200 hover:text-white transition-all shadow-sm"
          >
            <Sliders className="h-3.5 w-3.5 text-amber-400" />
            <span>Config</span>
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
              className={`flex items-center gap-3 px-3.5 py-2.5 rounded-2xl border text-xs whitespace-nowrap transition-all shadow-sm ${isSelected
                ? 'bg-slate-900 border-emerald-500/80 text-white ring-1 ring-emerald-500/30 shadow-emerald-500/10'
                : 'bg-slate-900/60 border-slate-800/80 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                }`}
            >
              <div className="flex items-center gap-2">
                <span className={`h-2 w-2 rounded-full shrink-0 ${isOnline ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
                <span className="font-bold tracking-tight">{name}</span>
              </div>

              {/* Telemetry pill */}
              <div className="flex items-center gap-2 font-mono text-[11px] text-slate-400 border-l border-slate-800/80 pl-2.5">
                <span className={isOnline && data.temp ? 'text-amber-400 font-bold' : ''}>
                  {isOnline && data.temp !== null && data.temp !== undefined ? `${Number(data.temp).toFixed(1)}°C` : '--'}
                </span>
                <span className={isOnline && data.humi ? 'text-sky-400 font-bold' : ''}>
                  {isOnline && data.humi !== null && data.humi !== undefined ? `${Number(data.humi).toFixed(1)}%` : '--'}
                </span>
              </div>
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

          {/* Room-wise Crop & Setup badges */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold">
              <Sprout className="h-3.5 w-3.5" />
              <span>Crop: {currentStage.crop_name || currentRoomSetpoints.crop_name || DEFAULT_ROOM_CROPS[activeRoom]}</span>
            </span>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-semibold">
              <Layers className="h-3.5 w-3.5" />
              <span>Setup: {currentStage.setup_name || currentRoomSetpoints.setup_name || DEFAULT_ROOM_SETUPS[activeRoom]}</span>
            </span>
          </div>
        </div>

        {/* Tab Switcher */}
        <div className="grid grid-cols-3 sm:flex items-center gap-1 bg-slate-900 p-1 rounded-xl border border-slate-800 text-xs w-full lg:w-auto">
          <button
            onClick={() => setActiveTab('control')}
            className={`px-3 py-1.5 rounded-lg font-semibold transition-all text-center ${activeTab === 'control' ? 'bg-emerald-500 text-slate-950 font-bold shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
          >
            Schedule & Setpoints
          </button>
          <button
            onClick={() => setActiveTab('relays')}
            className={`px-3 py-1.5 rounded-lg font-semibold transition-all text-center ${activeTab === 'relays' ? 'bg-emerald-500 text-slate-950 font-bold shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
          >
            Relay Board (22-Ch)
          </button>
          <button
            onClick={() => setActiveTab('trends')}
            className={`px-3 py-1.5 rounded-lg font-semibold transition-all text-center ${activeTab === 'trends' ? 'bg-emerald-500 text-slate-950 font-bold shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
          >
            Live Trends
          </button>
        </div>
      </div>

      {/* ── VIEW 1: SCHEDULE & SETPOINTS (PRIMARY VIEW) ── */}
      {activeTab === 'control' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          {/* LEFT 8-COLS: Stage Stepper, Crop Details & Diurnal Slots Table */}
          <div className="lg:col-span-8 space-y-4">
            {/* Stage & Schedule Control Card */}
            <div className="p-4 sm:p-5 rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 space-y-4">
              {/* Row 1: Stage Stepper & Control Mode */}
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 pb-3.5 border-b border-slate-800/80">
                {/* Stage Selector & Enable Pill */}
                <div className="flex flex-wrap items-center gap-2.5">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-400">
                    <Sparkles className="h-3.5 w-3.5 text-amber-400" />
                    <span>Crop Stage:</span>
                  </div>

                  <select
                    value={activeStageKey}
                    onChange={(e) => setActiveStageKey(e.target.value)}
                    className="bg-slate-950 border border-slate-700/90 text-white font-bold text-xs rounded-xl px-3 py-1.5 outline-none focus:border-emerald-500/60 focus:ring-1 focus:ring-emerald-500/30 transition-all cursor-pointer"
                  >
                    {ALL_SETTING_KEYS.map(k => (
                      <option key={k} value={k}>
                        {currentRoomSetpoints.settings?.[k]?.name || k} {!currentRoomSetpoints.settings?.[k]?.enabled ? '(Disabled)' : ''}
                      </option>
                    ))}
                  </select>

                  <button
                    onClick={() => updateActiveStage('enabled', !currentStage.enabled)}
                    className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-xl text-xs font-bold border transition-all ${currentStage.enabled
                      ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40 shadow-sm shadow-emerald-500/10 hover:bg-emerald-500/25'
                      : 'bg-slate-800/80 text-slate-400 border-slate-700 hover:bg-slate-800'
                      }`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${currentStage.enabled ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
                    {currentStage.enabled ? 'Stage Active' : 'Stage Disabled'}
                  </button>
                </div>

                {/* Mode Selector */}
                <div className="flex items-center gap-2 self-end sm:self-center bg-slate-950/80 border border-slate-800 rounded-xl px-2.5 py-1">
                  <Sliders className="h-3.5 w-3.5 text-emerald-400" />
                  <span className="text-[11px] font-medium text-slate-400">Mode:</span>
                  <select
                    value={currentRoomSetpoints.mode || 'SCHEDULED'}
                    onChange={(e) => updateRoomState(r => ({ ...r, mode: e.target.value }))}
                    className="bg-transparent text-emerald-400 font-bold text-xs outline-none cursor-pointer pr-1"
                  >
                    <option value="SCHEDULED" className="bg-slate-900 text-white">Scheduled (10-Stage)</option>
                    <option value="STATIC" className="bg-slate-900 text-white">Static (Fixed Limits)</option>
                  </select>
                </div>
              </div>

              {/* Row 2: Crop Name & Setup Name */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {/* Crop Name */}
                <div className="flex items-center gap-2.5 bg-slate-950/90 border border-slate-800 hover:border-slate-700 rounded-xl px-3.5 py-2 transition-colors">
                  <div className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 shrink-0">
                    <Sprout className="h-4 w-4" />
                  </div>
                  <div className="flex flex-col flex-1 min-w-0">
                    <span className="text-[10px] text-slate-400 uppercase tracking-wider font-bold">
                      Crop Name
                    </span>
                    <input
                      type="text"
                      value={currentStage.crop_name || currentRoomSetpoints.crop_name || ''}
                      onChange={(e) => {
                        updateActiveStage('crop_name', e.target.value);
                        updateRoomState(r => ({ ...r, crop_name: e.target.value }));
                      }}
                      placeholder={`${systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]} Crop`}
                      className="bg-transparent text-white font-bold text-xs outline-none w-full placeholder:text-slate-600"
                    />
                  </div>
                </div>

                {/* Setup Name */}
                <div className="flex items-center gap-2.5 bg-slate-950/90 border border-slate-800 hover:border-slate-700 rounded-xl px-3.5 py-2 transition-colors">
                  <div className="p-1.5 rounded-lg bg-blue-500/10 text-blue-400 shrink-0">
                    <Layers className="h-4 w-4" />
                  </div>
                  <div className="flex flex-col flex-1 min-w-0">
                    <span className="text-[10px] text-slate-400 uppercase tracking-wider font-bold">
                      Setup Name
                    </span>
                    <input
                      type="text"
                      value={currentStage.setup_name || currentRoomSetpoints.setup_name || ''}
                      onChange={(e) => {
                        updateActiveStage('setup_name', e.target.value);
                        updateRoomState(r => ({ ...r, setup_name: e.target.value }));
                      }}
                      placeholder={`${systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]} Setup`}
                      className="bg-transparent text-white font-bold text-xs outline-none w-full placeholder:text-slate-600"
                    />
                  </div>
                </div>
              </div>

              {/* Row 3: Stage Date Range & Photoperiod Lighting */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-3.5 border-t border-slate-800/80 text-xs">
                {/* Start Date */}
                <div className="space-y-1.5">
                  <span className="text-[11px] font-semibold text-slate-400 flex items-center gap-1.5">
                    <Calendar className="h-3.5 w-3.5 text-emerald-400" /> Start Date
                  </span>
                  <input
                    type="date"
                    value={currentStage.start_date || ''}
                    onChange={(e) => handleStageDateChange('start_date', e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 hover:border-slate-700 focus:border-emerald-500/60 rounded-xl px-3 py-2 text-white font-mono text-xs outline-none transition-colors"
                  />
                </div>

                {/* End Date */}
                <div className="space-y-1.5">
                  <span className="text-[11px] font-semibold text-slate-400 flex items-center gap-1.5">
                    <Calendar className="h-3.5 w-3.5 text-rose-400" /> End Date
                  </span>
                  <input
                    type="date"
                    value={currentStage.end_date || ''}
                    onChange={(e) => handleStageDateChange('end_date', e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 hover:border-slate-700 focus:border-rose-500/60 rounded-xl px-3 py-2 text-white font-mono text-xs outline-none transition-colors"
                  />
                </div>

                {/* Photoperiod Lighting */}
                <div className="space-y-1.5">
                  <span className="text-[11px] font-semibold text-slate-400 flex items-center gap-1.5">
                    <Sun className="h-3.5 w-3.5 text-amber-400" /> Photoperiod Lights
                  </span>
                  <div className="flex items-center gap-2 font-mono bg-slate-950 border border-slate-800 rounded-xl px-2.5 py-1.5">
                    <input
                      type="text"
                      value={currentStage.photoperiod_on || '06:00 AM'}
                      onChange={(e) => updateActiveStage('photoperiod_on', e.target.value)}
                      className="w-1/2 bg-transparent text-white text-center text-xs font-semibold outline-none placeholder:text-slate-600"
                      placeholder="06:00 AM"
                    />
                    <span className="text-slate-600 font-bold">→</span>
                    <input
                      type="text"
                      value={currentStage.photoperiod_off || '08:00 PM'}
                      onChange={(e) => updateActiveStage('photoperiod_off', e.target.value)}
                      className="w-1/2 bg-transparent text-white text-center text-xs font-semibold outline-none placeholder:text-slate-600"
                      placeholder="08:00 PM"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* Overlap Alert */}
            {slotWarnings.length > 0 && (
              <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center gap-2.5 shadow-sm">
                <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400 animate-pulse" />
                <span className="font-medium">Slot Overlap Detected: {slotWarnings.join(' • ')}</span>
              </div>
            )}

            {/* Diurnal Time Slots Table Card */}
            <div className="rounded-2xl border border-slate-800 bg-slate-900/80 backdrop-blur-sm overflow-hidden shadow-lg shadow-black/20">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between p-4 border-b border-slate-800 bg-slate-900/90 gap-3">
                <div className="flex items-center gap-2.5">
                  <div className="p-1.5 rounded-lg bg-sky-500/10 text-sky-400">
                    <Clock className="h-4 w-4" />
                  </div>
                  <div>
                    <span className="text-xs font-bold text-white block">
                      Diurnal Setpoints
                    </span>
                    <span className="text-[11px] text-slate-400">
                      {currentStage.time_slots?.length || 0} Time Frame{(currentStage.time_slots?.length || 0) === 1 ? '' : 's'} Configured
                    </span>
                  </div>
                </div>

                <button
                  onClick={handleAddSlot}
                  className="inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-xl bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/30 text-xs font-semibold transition-all shadow-sm shadow-emerald-500/10 self-end sm:self-center"
                >
                  <Plus className="h-3.5 w-3.5" />
                  <span>Add Time Slot</span>
                </button>
              </div>

              <div className="overflow-x-auto min-w-full">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-950/80 text-[11px] text-slate-400 font-semibold border-b border-slate-800 uppercase tracking-wider">
                    <tr>
                      <th className="py-3.5 px-4 whitespace-nowrap">Time Window</th>
                      <th className="py-3.5 px-4 whitespace-nowrap">Slot Name</th>
                      <th className="py-3.5 px-4 whitespace-nowrap">Target Temp</th>
                      <th className="py-3.5 px-4 whitespace-nowrap">Target Humidity</th>
                      <th className="py-3.5 px-4 text-right whitespace-nowrap">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono">
                    {(!currentStage.time_slots || currentStage.time_slots.length === 0) ? (
                      <tr>
                        <td colSpan={5} className="py-8 text-center text-slate-500 font-sans text-xs">
                          No time slots configured for this stage. Click "+ Add Time Slot" to create one.
                        </td>
                      </tr>
                    ) : (
                      currentStage.time_slots.map((slot, idx) => (
                        <tr key={slot.id || idx} className="hover:bg-slate-800/30 transition-colors group">
                          <td className="py-3 px-4 text-slate-200 font-bold whitespace-nowrap">
                            <span className="inline-flex items-center gap-1.5 bg-slate-950/90 border border-slate-800 px-2.5 py-1 rounded-lg text-emerald-300">
                              <Clock className="h-3 w-3 text-slate-500" />
                              {formatTime12h(slot.start)} <span className="text-slate-500">→</span> {formatTime12h(slot.stop)}
                            </span>
                          </td>
                          <td className="py-3 px-4 font-sans text-white font-medium whitespace-nowrap">
                            {slot.name || `Slot ${idx + 1}`}
                          </td>
                          <td className="py-3 px-4 whitespace-nowrap">
                            <span className="font-bold text-amber-300 bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded-md">
                              {slot.t_set?.toFixed(1)}°C
                            </span>
                            <span className="text-[10px] text-slate-400 ml-2 font-mono">
                              [{slot.t_min?.toFixed(1)} - {slot.t_max?.toFixed(1)}°C]
                            </span>
                          </td>
                          <td className="py-3 px-4 whitespace-nowrap">
                            <span className="font-bold text-sky-300 bg-sky-500/10 border border-sky-500/20 px-2 py-0.5 rounded-md">
                              {slot.h_set?.toFixed(1)}%
                            </span>
                            <span className="text-[10px] text-slate-400 ml-2 font-mono">
                              [{slot.h_min?.toFixed(1)} - {slot.h_max?.toFixed(1)}%]
                            </span>
                          </td>
                          <td className="py-3 px-4 text-right whitespace-nowrap">
                            <div className="flex items-center justify-end gap-1">
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

          {/* RIGHT 4-COLS: Live Telemetry & Relay Monitor for Active Room */}
          <div className="lg:col-span-4 space-y-4">
            {/* Live Readings Card */}
            <div className="p-4 sm:p-5 rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800/80">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-emerald-400" />
                  <span className="text-xs font-bold text-white">Live Room Telemetry</span>
                </div>
                <div className="flex items-center gap-1.5 bg-slate-950 border border-slate-800 px-2.5 py-1 rounded-lg">
                  <span className={`h-1.5 w-1.5 rounded-full ${isMachineOnline ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
                  <span className="text-[11px] font-mono font-bold text-slate-300">{activeRoom}</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                {/* Temp */}
                <div className="p-3.5 rounded-xl bg-gradient-to-b from-slate-950 to-slate-950/60 border border-amber-500/20 space-y-2">
                  <span className="text-[10px] font-bold text-amber-400/90 uppercase tracking-wider flex items-center gap-1">
                    <Thermometer className="h-3.5 w-3.5 text-amber-400" /> Temperature
                  </span>
                  <div className="text-xl sm:text-2xl font-black font-mono tracking-tight text-white truncate">
                    {isMachineOnline && activeRoomLive.temp !== undefined && activeRoomLive.temp !== null && Number(activeRoomLive.temp) > 0 ? (
                      `${Number(activeRoomLive.temp).toFixed(1)}°C`
                    ) : (
                      <span className="text-base font-semibold text-slate-500 font-mono">N/A</span>
                    )}
                  </div>
                  <div className="pt-1 border-t border-slate-800/60">
                    <span className="text-[10px] font-mono text-slate-400 truncate block">
                      Target: <span className="text-amber-300 font-bold">{currentStage.time_slots?.[0]?.t_set?.toFixed(1) || '24.0'}°C</span>
                    </span>
                  </div>
                </div>

                {/* Humidity */}
                <div className="p-3.5 rounded-xl bg-gradient-to-b from-slate-950 to-slate-950/60 border border-sky-500/20 space-y-2">
                  <span className="text-[10px] font-bold text-sky-400/90 uppercase tracking-wider flex items-center gap-1">
                    <Droplets className="h-3.5 w-3.5 text-sky-400" /> Humidity
                  </span>
                  <div className="text-xl sm:text-2xl font-black font-mono tracking-tight text-white truncate">
                    {isMachineOnline && activeRoomLive.humi !== undefined && activeRoomLive.humi !== null && Number(activeRoomLive.humi) > 0 ? (
                      `${Number(activeRoomLive.humi).toFixed(1)}%`
                    ) : (
                      <span className="text-base font-semibold text-slate-500 font-mono">N/A</span>
                    )}
                  </div>
                  <div className="pt-1 border-t border-slate-800/60">
                    <span className="text-[10px] font-mono text-slate-400 truncate block">
                      Target: <span className="text-sky-300 font-bold">{currentStage.time_slots?.[0]?.h_set?.toFixed(1) || '60.0'}%</span>
                    </span>
                  </div>
                </div>
              </div>

              {/* CO2 if available */}
              {activeRoomLive.co2 !== undefined && activeRoomLive.co2 !== null && (
                <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between text-xs">
                  <span className="text-slate-400 font-medium">Carbon Dioxide (CO2)</span>
                  <span className="font-bold font-mono text-emerald-400">
                    {isMachineOnline && Number(activeRoomLive.co2) > 0 ? (
                      `${Number(activeRoomLive.co2).toFixed(0)} ppm`
                    ) : (
                      <span className="text-xs font-semibold text-slate-500 font-mono">N/A</span>
                    )}
                  </span>
                </div>
              )}
            </div>

            {/* Room Relays Status */}
            <div className="p-4 sm:p-5 rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 space-y-3">
              <div className="flex items-center justify-between pb-2.5 border-b border-slate-800/80">
                <div className="flex items-center gap-2">
                  <Zap className="h-4 w-4 text-amber-400" />
                  <span className="text-xs font-bold text-white">Dedicated Relay Channels</span>
                </div>
                <span className="text-[10px] font-mono text-slate-500">Live Status</span>
              </div>

              <div className="space-y-2 text-xs">
                {/* Cooling / AC */}
                <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-950/80 border border-slate-800/80 hover:border-slate-700 transition-colors">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">CH {chCool}</span>
                    <span className="text-slate-200 font-medium">{activeRoom === 'S7' ? 'Fanpad System' : 'Cooling / AC Compressor'}</span>
                  </div>
                  <span className={`px-2.5 py-0.5 rounded-lg text-[10px] font-bold border ${relayStates[chCool]
                    ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                    : 'bg-slate-800/80 text-slate-500 border-slate-700/60'
                    }`}>
                    {relayStates[chCool] ? 'ACTIVE ON' : 'OFF'}
                  </span>
                </div>

                {/* Humidifier */}
                <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-950/80 border border-slate-800/80 hover:border-slate-700 transition-colors">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">CH {chHumi}</span>
                    <span className="text-slate-200 font-medium">Humidifier Unit</span>
                  </div>
                  <span className={`px-2.5 py-0.5 rounded-lg text-[10px] font-bold border ${relayStates[chHumi]
                    ? 'bg-sky-500/20 text-sky-400 border-sky-500/30'
                    : 'bg-slate-800/80 text-slate-500 border-slate-700/60'
                    }`}>
                    {relayStates[chHumi] ? 'ACTIVE ON' : 'OFF'}
                  </span>
                </div>

                {/* Grow Lights */}
                <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-950/80 border border-slate-800/80 hover:border-slate-700 transition-colors">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">CH {chLight}</span>
                    <span className="text-slate-200 font-medium">Photoperiod Grow Lights</span>
                  </div>
                  <span className={`px-2.5 py-0.5 rounded-lg text-[10px] font-bold border ${relayStates[chLight]
                    ? 'bg-amber-500/20 text-amber-400 border-amber-500/30'
                    : 'bg-slate-800/80 text-slate-500 border-slate-700/60'
                    }`}>
                    {relayStates[chLight] ? 'ACTIVE ON' : 'OFF'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── VIEW 2: FULL 22-CHANNEL RELAY MATRIX ── */}
      {activeTab === 'relays' && (
        <div className="p-4 sm:p-5 rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800 text-xs gap-2">
            <div>
              <span className="font-bold text-white text-sm block">Modbus RTU 22-Channel Relay Board</span>
              <span className="text-slate-400 font-mono text-[11px]">Hardware Port: {systemConfig.relay_port}</span>
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

          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 gap-2.5 sm:gap-3 text-xs font-mono">
            {Array.from({ length: 22 }).map((_, i) => {
              const ch = i + 1;
              const isOn = !!relayStates[ch];
              let label = `CH ${ch}`;
              if (ch === 22) label = 'Siren Buzzer';
              else {
                const rIdx = Math.floor((ch - 1) / 3);
                const sub = (ch - 1) % 3;
                const rName = `S${rIdx + 1}`;
                label = `${rName} ${sub === 0 ? 'AC' : sub === 1 ? 'HUM' : 'LGT'}`;
              }

              return (
                <div
                  key={ch}
                  className={`p-3 rounded-xl border text-center transition-all shadow-sm ${isOn
                    ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400 font-bold shadow-emerald-500/5 ring-1 ring-emerald-500/20'
                    : 'bg-slate-950 border-slate-800 text-slate-500 hover:border-slate-700'
                    }`}
                >
                  <div className="text-[10px] text-slate-400 mb-0.5">{`CH ${ch}`}</div>
                  <div className="text-xs truncate font-semibold">{label}</div>
                  <div className={`text-[9px] mt-1.5 font-bold uppercase ${isOn ? 'text-emerald-400' : 'text-slate-600'}`}>
                    {isOn ? 'ON' : 'OFF'}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── VIEW 3: LIVE TRENDS CHART ── */}
      {activeTab === 'trends' && (
        <div className="p-4 sm:p-5 rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800 text-xs gap-1">
            <span className="font-bold text-white text-sm">Live Multi-Zone Sensor Trends</span>
            <span className="text-slate-400 font-mono text-[11px]">Rolling 30 Real-Time Samples</span>
          </div>

          <div className="h-72 sm:h-96 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 10, right: 10, bottom: 5, left: -25 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis dataKey="time" stroke="#64748b" fontSize={10} />
                <YAxis stroke="#64748b" fontSize={10} domain={['dataMin - 1', 'dataMax + 1']} />
                <Tooltip contentStyle={{ backgroundColor: '#020617', borderColor: '#334155', borderRadius: '12px', fontSize: '11px', color: '#fff' }} />
                <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
                <Line type="monotone" dataKey="S1_T" name="S1 (Strawberry)" stroke="#10b981" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="S2_T" name="S2 (Blueberry)" stroke="#0ea5e9" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="S3_T" name="S3 (Apples/Pears)" stroke="#f59e0b" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="S4_T" name="S4 (Greens)" stroke="#8b5cf6" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="S7_T" name="S7 (Greenhouse)" stroke="#ec4899" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
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
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/70 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-md rounded-2xl bg-slate-900 border border-slate-700/80 shadow-2xl p-5 sm:p-6 space-y-4 text-xs max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <span className="font-bold text-white text-sm">System Configuration</span>
              <button onClick={() => setShowConfigModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-3.5">
              <div>
                <label className="text-slate-400 block mb-1 font-semibold">Cloud Telemetry Upload Frequency</label>
                <select
                  value={systemConfig.upload_frequency_min ?? 0}
                  onChange={(e) => setSystemConfig({ ...systemConfig, upload_frequency_min: Number(e.target.value) })}
                  className="w-full bg-slate-950 border border-slate-700 focus:border-emerald-500 rounded-xl px-3 py-2 text-white outline-none"
                >
                  <option value={0}>0 - Real-time Streaming (1 Sec)</option>
                  <option value={1}>1 Minute</option>
                  <option value={5}>5 Minutes</option>
                  <option value={15}>15 Minutes</option>
                  <option value={60}>1 Hour</option>
                </select>
              </div>

              <div>
                <label className="text-slate-400 block mb-1 font-semibold">Temp Alarm Deviation Limit (± °C)</label>
                <input
                  type="number"
                  step="0.5"
                  value={systemConfig.temp_alarm_offset ?? 5.0}
                  onChange={(e) => setSystemConfig({ ...systemConfig, temp_alarm_offset: parseFloat(e.target.value) || 5.0 })}
                  className="w-full bg-slate-950 border border-slate-700 focus:border-emerald-500 rounded-xl px-3 py-2 text-white font-mono"
                />
              </div>

              <div>
                <label className="text-slate-400 block mb-1 font-semibold">Humidity Alarm Deviation Limit (± %)</label>
                <input
                  type="number"
                  step="0.5"
                  value={systemConfig.humi_alarm_offset ?? 5.0}
                  onChange={(e) => setSystemConfig({ ...systemConfig, humi_alarm_offset: parseFloat(e.target.value) || 5.0 })}
                  className="w-full bg-slate-950 border border-slate-700 focus:border-emerald-500 rounded-xl px-3 py-2 text-white font-mono"
                />
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
                  handleSaveToDevice();
                }}
                className="px-5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold transition-all shadow-sm shadow-emerald-500/20"
              >
                Save Config
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
                    setSystemConfig(prev => ({
                      ...prev,
                      sensor_names: { ...prev.sensor_names, [activeRoom]: renameValue.trim() }
                    }));
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

      {/* ── MODAL: PRESETS ── */}
      {showPresetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/70 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-lg rounded-2xl bg-slate-900 border border-slate-700/80 shadow-2xl p-5 sm:p-6 space-y-4 text-xs max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div>
                <span className="font-bold text-white text-sm block">Crop Presets & Recipes</span>
                <span className="text-slate-400 text-[11px]">Load pre-configured multi-stage schedules into {systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]}</span>
              </div>
              <button onClick={() => setShowPresetModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-2.5">
              {savedPresets.map(preset => (
                <div key={preset.name} className="flex flex-col sm:flex-row sm:items-center justify-between p-3 rounded-xl bg-slate-950/80 border border-slate-800 hover:border-slate-700 transition-colors gap-2">
                  <div className="space-y-0.5">
                    <span className="font-bold text-white block">{preset.name}</span>
                    <span className="text-[11px] text-slate-400 block">{preset.desc || 'Standard multi-stage profile'}</span>
                  </div>
                  <button
                    onClick={() => {
                      updateRoomState(r => ({
                        ...r,
                        crop_name: preset.crop_name || r.crop_name,
                        setup_name: preset.setup_name || r.setup_name,
                        settings: JSON.parse(JSON.stringify(preset.settings))
                      }));
                      setShowPresetModal(false);
                      setStatusMsg(`Applied preset "${preset.name}" to ${systemConfig.sensor_names[activeRoom] || DEFAULT_ROOM_NAMES[activeRoom]}!`);
                      setTimeout(() => setStatusMsg(''), 2500);
                    }}
                    className="px-3 py-1.5 rounded-xl bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/30 text-xs font-semibold self-end sm:self-center transition-all"
                  >
                    Apply Preset
                  </button>
                </div>
              ))}
            </div>

            <div className="flex justify-end pt-3 border-t border-slate-800">
              <button onClick={() => setShowPresetModal(false)} className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300">
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ColdStorageSettings;
