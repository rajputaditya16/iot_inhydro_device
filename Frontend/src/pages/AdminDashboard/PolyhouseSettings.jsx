import { useState, useEffect, useMemo, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Save, RefreshCw, Power, AlertTriangle, ShieldCheck, Cpu, Sliders, CheckCircle2,
  Clock, Sun, Droplets, Thermometer, Wind, Activity, Layers, Play, Pause,
  ChevronDown, Settings, Plus, Trash2, ArrowLeft, Info, Bell, BellOff, Volume2
} from 'lucide-react';
import { createMqttClient } from '../../utils/mqtt';
import { telemetryWs } from '../../utils/websocketClient';

const ALL_POLYHOUSES = ['PH-01', 'PH-02', 'PH-03', 'PH-04', 'PH-05', 'PH-06'];
const ACTIVE_POLYHOUSES = ['PH-01', 'PH-02', 'PH-03', 'PH-04', 'PH-05'];

const DEFAULT_SETPOINTS = {
  'PH-01': {
    name: 'POLYHOUSE 01',
    mode: 'AUTO',
    temp_low: 22.0, temp_target: 25.0, temp_high: 28.0, temp_hysteresis: 1.0,
    humi_low: 60.0, humi_target: 70.0, humi_high: 80.0, humi_hysteresis: 3.0,
    'Timer1 Name': 'ACF FANS', 'Timer1 Start': '00:00', 'Timer1 Stop': '23:59', 'Timer1 ON Min': 15, 'Timer1 OFF Min': 30,
    'Timer2 Name': 'SPRINKLER', 'Timer2 Start': '06:00', 'Timer2 Stop': '18:00', 'Timer2 ON Min': 2, 'Timer2 OFF Min': 30,
    'Timer3 Name': 'FOGGER', 'Timer3 Start': '08:00', 'Timer3 Stop': '17:00', 'Timer3 ON Min': 1, 'Timer3 OFF Min': 2,
    irrigation_slots: [
      { id: 1, start: '07:00 AM', duration_sec: 120, type: 'sprinkler', enabled: true },
      { id: 2, start: '12:30 PM', duration_sec: 120, type: 'sprinkler', enabled: true },
      { id: 3, start: '04:30 PM', duration_sec: 120, type: 'fogger', enabled: true }
    ]
  },
  'PH-02': {
    name: 'POLYHOUSE 02',
    mode: 'AUTO',
    temp_low: 22.0, temp_target: 25.0, temp_high: 28.0, temp_hysteresis: 1.0,
    humi_low: 60.0, humi_target: 70.0, humi_high: 80.0, humi_hysteresis: 3.0,
    'Timer1 Name': 'ACF FANS', 'Timer1 Start': '00:00', 'Timer1 Stop': '23:59', 'Timer1 ON Min': 15, 'Timer1 OFF Min': 30,
    'Timer2 Name': 'SPRINKLER', 'Timer2 Start': '06:00', 'Timer2 Stop': '18:00', 'Timer2 ON Min': 2, 'Timer2 OFF Min': 30,
    'Timer3 Name': 'FOGGER', 'Timer3 Start': '08:00', 'Timer3 Stop': '17:00', 'Timer3 ON Min': 1, 'Timer3 OFF Min': 2,
    irrigation_slots: []
  },
  'PH-03': {
    name: 'POLYHOUSE 03',
    mode: 'AUTO',
    temp_low: 22.0, temp_target: 25.0, temp_high: 28.0, temp_hysteresis: 1.0,
    humi_low: 60.0, humi_target: 70.0, humi_high: 80.0, humi_hysteresis: 3.0,
    'Timer1 Name': 'ACF FANS', 'Timer1 Start': '00:00', 'Timer1 Stop': '23:59', 'Timer1 ON Min': 15, 'Timer1 OFF Min': 30,
    'Timer2 Name': 'SPRINKLER', 'Timer2 Start': '06:00', 'Timer2 Stop': '18:00', 'Timer2 ON Min': 2, 'Timer2 OFF Min': 30,
    'Timer3 Name': 'FOGGER', 'Timer3 Start': '08:00', 'Timer3 Stop': '17:00', 'Timer3 ON Min': 1, 'Timer3 OFF Min': 2,
    irrigation_slots: []
  },
  'PH-04': {
    name: 'POLYHOUSE 04',
    mode: 'AUTO',
    temp_low: 22.0, temp_target: 25.0, temp_high: 28.0, temp_hysteresis: 1.0,
    humi_low: 60.0, humi_target: 70.0, humi_high: 80.0, humi_hysteresis: 3.0,
    'Timer1 Name': 'ACF FANS', 'Timer1 Start': '00:00', 'Timer1 Stop': '23:59', 'Timer1 ON Min': 15, 'Timer1 OFF Min': 30,
    'Timer2 Name': 'SPRINKLER', 'Timer2 Start': '06:00', 'Timer2 Stop': '18:00', 'Timer2 ON Min': 2, 'Timer2 OFF Min': 30,
    'Timer3 Name': 'FOGGER', 'Timer3 Start': '08:00', 'Timer3 Stop': '17:00', 'Timer3 ON Min': 1, 'Timer3 OFF Min': 2,
    irrigation_slots: []
  },
  'PH-05': {
    name: 'POLYHOUSE 05',
    mode: 'AUTO',
    temp_low: 22.0, temp_target: 25.0, temp_high: 28.0, temp_hysteresis: 1.0,
    humi_low: 60.0, humi_target: 70.0, humi_high: 80.0, humi_hysteresis: 3.0,
    'Timer1 Name': 'ACF FANS', 'Timer1 Start': '00:00', 'Timer1 Stop': '23:59', 'Timer1 ON Min': 15, 'Timer1 OFF Min': 30,
    'Timer2 Name': 'SPRINKLER', 'Timer2 Start': '06:00', 'Timer2 Stop': '18:00', 'Timer2 ON Min': 2, 'Timer2 OFF Min': 30,
    'Timer3 Name': 'FOGGER', 'Timer3 Start': '08:00', 'Timer3 Stop': '17:00', 'Timer3 ON Min': 1, 'Timer3 OFF Min': 2,
    irrigation_slots: []
  },
  'PH-06': {
    name: 'POLYHOUSE 06 (MONITOR)',
    mode: 'MONITOR',
    temp_high_limit: 32.0, temp_low_limit: 15.0,
    humi_high_limit: 85.0, humi_low_limit: 35.0
  }
};

const DEFAULT_SYSTEM_CONFIG = {
  upload_hours: 0,
  upload_mins: 1,
  upload_secs: 0,
  upload_frequency_min: 1.0,
  temp_alarm_offset: 5.0,
  humi_alarm_offset: 5.0,
  pump_arbitration_mode: 'sequential',
  pump_start_delay_sec: 3.0,
  pump_post_run_delay_sec: 3.0,
  buzzer_auto_silence_sec: 30,
  sensor_names: {
    'PH-01': 'POLYHOUSE 01',
    'PH-02': 'POLYHOUSE 02',
    'PH-03': 'POLYHOUSE 03',
    'PH-04': 'POLYHOUSE 04',
    'PH-05': 'POLYHOUSE 05',
    'PH-06': 'POLYHOUSE 06 (MONITOR)'
  }
};

const RELAY_CHANNELS = {
  'PH-01': { acf: 1, sprinkler: 2, fogger: 3, pump: 4 },
  'PH-02': { acf: 5, sprinkler: 6, fogger: 7, pump: 8 },
  'PH-03': { acf: 9, sprinkler: 10, fogger: 11, pump: 12 },
  'PH-04': { acf: 13, sprinkler: 14, fogger: 15, pump: 16 },
  'PH-05': { acf: 17, sprinkler: 18, fogger: 19, pump: 20 },
};

export default function PolyhouseSettings() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  const [devices, setDevices] = useState([]);
  const [selectedDeviceRoot, setSelectedDeviceRoot] = useState('');
  const [loading, setLoading] = useState(true);
  const [activePh, setActivePh] = useState('PH-01');
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [saveStatus, setSaveStatus] = useState('idle'); // idle | saving | saved | error
  const [statusMessage, setStatusMessage] = useState('');

  // Master State from Controller
  const [sensorSetpoints, setSensorSetpoints] = useState(DEFAULT_SETPOINTS);
  const [systemConfig, setSystemConfig] = useState(DEFAULT_SYSTEM_CONFIG);
  const [liveTelemetry, setLiveTelemetry] = useState(null);
  const [relayStates, setRelayStates] = useState({});
  const [commonPumpActive, setCommonPumpActive] = useState(false);
  const [activeWaterZone, setActiveWaterZone] = useState(null);
  const [roomPausedStates, setRoomPausedStates] = useState({});
  const [activeWarnings, setActiveWarnings] = useState([]);
  const [isDeviceOnline, setIsDeviceOnline] = useState(false);

  // 1. Fetch Polyhouse devices from database
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.success && Array.isArray(data.data)) {
          const phDevices = data.data.filter(
            d => d.deviceType === 'itc_polyhouse' || (d.name && d.name.toLowerCase().includes('polyhouse'))
          );
          setDevices(phDevices);

          const paramDevId = searchParams.get('device');
          const paramMqtt = searchParams.get('mqttId');
          const matched = phDevices.find(d => (d._id === paramDevId || d.mqttId === paramMqtt));

          if (matched) {
            setSelectedDeviceRoot(matched.mqttId || matched._id);
          } else if (phDevices.length > 0) {
            setSelectedDeviceRoot(phDevices[0].mqttId || phDevices[0]._id);
          }
        }
      } catch (err) {
        console.error('Fetch devices error:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchDevices();
  }, [API_BASE, token, searchParams]);

  const selectedDevice = useMemo(() => {
    return devices.find(d => (d.mqttId || d._id) === selectedDeviceRoot);
  }, [devices, selectedDeviceRoot]);

  // 2. Real-time MQTT & SSE listener for selected device
  useEffect(() => {
    if (!selectedDeviceRoot) return;

    const handlePacket = (topic, data) => {
      if (!data || typeof data !== 'object') return;
      setIsDeviceOnline(true);

      // Handle full state snapshot from controller
      if (topic.includes('/setpoints/current') || data.sensor_setpoints) {
        if (data.sensor_setpoints) {
          setSensorSetpoints(prev => ({ ...prev, ...data.sensor_setpoints }));
        }
        if (data.system_config) {
          setSystemConfig(prev => ({ ...prev, ...data.system_config }));
        }
        if (data.relay_states) setRelayStates(data.relay_states);
        if (data.common_pump_active !== undefined) setCommonPumpActive(Boolean(data.common_pump_active));
        if (data.active_water_zone !== undefined) setActiveWaterZone(data.active_water_zone);
        if (data.room_paused_states) setRoomPausedStates(data.room_paused_states);
        if (data.active_warnings) setActiveWarnings(data.active_warnings);
        if (data.sensor_data) setLiveTelemetry(data.sensor_data);
      } else if (data.sensor_data) {
        setLiveTelemetry(data.sensor_data);
        if (data.relay_states) setRelayStates(data.relay_states);
        if (data.common_pump_active !== undefined) setCommonPumpActive(Boolean(data.common_pump_active));
        if (data.active_water_zone !== undefined) setActiveWaterZone(data.active_water_zone);
        if (data.room_paused_states) setRoomPausedStates(data.room_paused_states);
        if (data.active_warnings) setActiveWarnings(data.active_warnings);
      }
    };

    // Initialize MQTT
    const mqttClient = createMqttClient();
    mqttClient.on('connect', () => {
      mqttClient.subscribe(`inhydro/${selectedDeviceRoot}/setpoints/current`);
      mqttClient.subscribe(`inhydro/${selectedDeviceRoot}/telemetry/live`);
      mqttClient.subscribe(`inhydro/${selectedDeviceRoot}/telemetry`);
      mqttClient.publish(`inhydro/${selectedDeviceRoot}/setpoints/request_sync`, '1');
    });

    mqttClient.on('message', (topic, payload) => {
      try {
        const parsed = JSON.parse(payload.toString());
        handlePacket(topic, parsed);
      } catch (e) {}
    });

    const targetRooms = [selectedDevice?._id, selectedDeviceRoot].filter(Boolean).map((s) => String(s).toLowerCase());
    telemetryWs.subscribe(targetRooms);

    const unbindWs = telemetryWs.onMessage((packet) => {
      if (!packet) return;
      const mId = packet.mqttId ? String(packet.mqttId).toLowerCase() : '';
      const top = packet.topic ? String(packet.topic).toLowerCase() : '';
      if (targetRooms.includes(mId) || targetRooms.some((r) => top.includes(r))) {
        handlePacket(packet.topic, packet.data);
      }
    });

    // Real-time SSE fallback
    const sseUrl = `${API_BASE}/api/devices/stream?deviceId=${selectedDevice?._id || ''}&mqttId=${selectedDeviceRoot}`;
    const eventSource = new EventSource(sseUrl);
    eventSource.onmessage = (event) => {
      try {
        const packet = JSON.parse(event.data);
        if (packet.mqttId === selectedDeviceRoot || packet.topic?.includes(selectedDeviceRoot)) {
          handlePacket(packet.topic, packet.data);
        }
      } catch (e) {}
    };

    return () => {
      telemetryWs.unsubscribe(targetRooms);
      unbindWs();
      if (mqttClient) mqttClient.end();
      eventSource.close();
    };
  }, [selectedDeviceRoot, selectedDevice, API_BASE]);

  // Setpoint mutation helpers
  const updatePhField = (phKey, field, val) => {
    setSensorSetpoints(prev => ({
      ...prev,
      [phKey]: {
        ...(prev[phKey] || {}),
        [field]: val
      }
    }));
  };

  const updateSystemConfigField = (field, val) => {
    setSystemConfig(prev => ({
      ...prev,
      [field]: val
    }));
  };

  // Add / Edit / Delete Irrigation Slot
  const handleAddSlot = (phKey) => {
    setSensorSetpoints(prev => {
      const curPh = prev[phKey] || {};
      const curSlots = curPh.irrigation_slots || [];
      const newSlot = {
        id: curSlots.length + 1,
        start: '08:00 AM',
        duration_sec: 120,
        type: 'sprinkler',
        enabled: true
      };
      return {
        ...prev,
        [phKey]: {
          ...curPh,
          irrigation_slots: [...curSlots, newSlot]
        }
      };
    });
  };

  const handleDeleteSlot = (phKey, slotIndex) => {
    setSensorSetpoints(prev => {
      const curPh = prev[phKey] || {};
      const curSlots = [...(curPh.irrigation_slots || [])];
      curSlots.splice(slotIndex, 1);
      curSlots.forEach((s, idx) => { s.id = idx + 1; });
      return {
        ...prev,
        [phKey]: {
          ...curPh,
          irrigation_slots: curSlots
        }
      };
    });
  };

  const handleUpdateSlot = (phKey, slotIndex, field, val) => {
    setSensorSetpoints(prev => {
      const curPh = prev[phKey] || {};
      const curSlots = [...(curPh.irrigation_slots || [])];
      curSlots[slotIndex] = { ...curSlots[slotIndex], [field]: val };
      return {
        ...prev,
        [phKey]: {
          ...curPh,
          irrigation_slots: curSlots
        }
      };
    });
  };

  // 3. API Commands & Setpoint Push
  const handleSaveAll = async () => {
    if (!selectedDevice) return;
    setSaveStatus('saving');
    setStatusMessage('Saving & pushing setpoints to controller...');

    const payload = {
      device_id: selectedDeviceRoot,
      polyhouse: activePh,
      sensor_setpoints: sensorSetpoints,
      system_config: systemConfig,
      ...sensorSetpoints[activePh]
    };

    try {
      const res = await fetch(`${API_BASE}/api/devices/${selectedDevice._id}/push-config`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.success) {
        setSaveStatus('saved');
        setStatusMessage('Setpoints saved & synced successfully!');
        setTimeout(() => setSaveStatus('idle'), 3500);
      } else {
        setSaveStatus('error');
        setStatusMessage(data.message || 'Failed to save setpoints');
      }
    } catch (err) {
      console.error('Save error:', err);
      setSaveStatus('error');
      setStatusMessage(err.message || 'Network error pushing configuration');
    }
  };

  const handleSendAction = async (action, polyhouse = null) => {
    if (!selectedDevice) return;
    setSaveStatus('saving');
    setStatusMessage(`Sending "${action}" command to hardware...`);

    try {
      const res = await fetch(`${API_BASE}/api/devices/${selectedDevice._id}/push-config`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ action, polyhouse })
      });
      const data = await res.json();
      if (data.success) {
        setSaveStatus('saved');
        setStatusMessage(data.message || `Command ${action} sent!`);
        setTimeout(() => setSaveStatus('idle'), 3000);
      } else {
        setSaveStatus('error');
        setStatusMessage(data.message || 'Action failed');
      }
    } catch (err) {
      setSaveStatus('error');
      setStatusMessage(err.message || 'Failed to execute command');
    }
  };

  const activePhSetpoints = sensorSetpoints[activePh] || DEFAULT_SETPOINTS[activePh] || {};
  const activePhTelemetry = liveTelemetry?.[activePh] || {};
  const activePhRelays = RELAY_CHANNELS[activePh] || {};
  const isCurrentPhPaused = Boolean(roomPausedStates[activePh]);

  return (
    <div className="space-y-6 pb-12 font-sans">
      {/* ── Top Header & Global Status ── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-700/60 pb-5">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/devices')}
            className="rounded-xl border border-slate-700 bg-slate-800/80 p-2 text-slate-400 hover:text-white transition-all cursor-pointer"
            title="Back to Devices"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-bold text-white tracking-tight">ITC Polyhouse Automation Controller</h1>
              <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${isDeviceOnline ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-700/50 text-slate-400'}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${isDeviceOnline ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
                {isDeviceOnline ? 'Hardware Connected' : 'Offline'}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Target: <span className="text-sky-400 font-mono font-medium">{selectedDevice?.name || 'ITC Polyhouse'}</span> ({selectedDeviceRoot}) • 6-Zone Climate, Hydraulic Arbitration & Misting
            </p>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => handleSendAction('sync')}
            className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800 px-3.5 py-2 text-xs font-medium text-slate-300 hover:bg-slate-700 hover:text-white transition-all"
            title="Request setpoints sync from Raspberry Pi"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Sync State
          </button>

          <button
            onClick={() => setShowConfigModal(true)}
            className="flex items-center gap-1.5 rounded-xl border border-sky-500/30 bg-sky-500/10 px-3.5 py-2 text-xs font-medium text-sky-400 hover:bg-sky-500 hover:text-white transition-all"
          >
            <Sliders className="h-3.5 w-3.5" /> System & Pump Config
          </button>

          <button
            onClick={handleSaveAll}
            disabled={saveStatus === 'saving'}
            className="flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-500 px-4 py-2 text-xs font-bold text-white shadow-lg shadow-emerald-500/20 hover:from-emerald-500 hover:to-teal-400 transition-all cursor-pointer disabled:opacity-50"
          >
            <Save className="h-4 w-4" /> Save & Push
          </button>
        </div>
      </div>

      {/* ── Notification Banner / Status Feedback ── */}
      {statusMessage && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className={`rounded-xl border p-3 text-xs flex items-center justify-between ${
            saveStatus === 'saved' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' :
            saveStatus === 'error' ? 'bg-rose-500/10 border-rose-500/30 text-rose-300' :
            'bg-sky-500/10 border-sky-500/30 text-sky-300'
          }`}
        >
          <div className="flex items-center gap-2 font-medium">
            {saveStatus === 'saved' && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
            {saveStatus === 'error' && <AlertTriangle className="h-4 w-4 text-rose-400" />}
            {saveStatus === 'saving' && <RefreshCw className="h-4 w-4 animate-spin text-sky-400" />}
            <span>{statusMessage}</span>
          </div>
          <button onClick={() => setStatusMessage('')} className="text-slate-400 hover:text-white">✕</button>
        </motion.div>
      )}

      {/* ── Active Warnings Pill Banner ── */}
      {activeWarnings.length > 0 && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3">
          <div className="flex items-center gap-2 text-amber-300 text-xs font-semibold mb-1">
            <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
            <span>Active Environmental Alerts & Hardware Comm Status ({activeWarnings.length}):</span>
          </div>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {activeWarnings.map((w, idx) => (
              <span key={idx} className="rounded-md bg-amber-950/60 border border-amber-500/20 px-2 py-0.5 text-[11px] text-amber-200">
                {w}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── System Overview Cards (Master Pump, Buzzer, Arbitration) ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 p-3.5">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>Common Master Pump (Relay 21)</span>
            <Activity className="h-4 w-4 text-sky-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className={`text-base font-bold ${commonPumpActive ? 'text-emerald-400' : 'text-slate-400'}`}>
              {commonPumpActive ? 'RUNNING (ACTIVE)' : 'IDLE (OFF)'}
            </span>
          </div>
          <p className="text-[11px] text-slate-500 mt-1 truncate">
            Active Zone: <span className="text-sky-300 font-mono">{activeWaterZone || 'None (Standby)'}</span>
          </p>
        </div>

        <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 p-3.5">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>Pump Arbitration Mode</span>
            <Sliders className="h-4 w-4 text-purple-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-base font-bold text-purple-300 uppercase">
              {systemConfig.pump_arbitration_mode || 'sequential'}
            </span>
          </div>
          <p className="text-[11px] text-slate-500 mt-1">
            Delays: Pre-Start {systemConfig.pump_start_delay_sec}s / Post-Run {systemConfig.pump_post_run_delay_sec}s
          </p>
        </div>

        <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 p-3.5">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>Hardware Alarm Buzzer (Relay 22)</span>
            <Volume2 className="h-4 w-4 text-amber-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className={`text-base font-bold ${relayStates[22] ? 'text-rose-400 animate-pulse' : 'text-slate-400'}`}>
              {relayStates[22] ? 'ALARM SOUNDING' : 'SILENT / STANDBY'}
            </span>
          </div>
          <p className="text-[11px] text-slate-500 mt-1">
            Auto-Silence Limit: {systemConfig.buzzer_auto_silence_sec || 30}s
          </p>
        </div>

        <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>Emergency Operations</span>
            <Power className="h-4 w-4 text-rose-400" />
          </div>
          <div className="flex items-center gap-2 mt-1">
            <button
              onClick={() => handleSendAction('pause')}
              className="flex-1 rounded-lg bg-rose-500/20 border border-rose-500/30 px-2 py-1.5 text-xs font-bold text-rose-400 hover:bg-rose-500 hover:text-white transition-all cursor-pointer"
            >
              STOP ALL
            </button>
            <button
              onClick={() => handleSendAction('resume')}
              className="flex-1 rounded-lg bg-emerald-500/20 border border-emerald-500/30 px-2 py-1.5 text-xs font-bold text-emerald-400 hover:bg-emerald-500 hover:text-white transition-all cursor-pointer"
            >
              RUN ALL
            </button>
          </div>
        </div>
      </div>

      {/* ── Polyhouse 6-Zone Selector Tabs ── */}
      <div className="flex border-b border-slate-700/60 overflow-x-auto gap-2 pb-1 scrollbar-none">
        {ALL_POLYHOUSES.map((phKey) => {
          const isSelected = activePh === phKey;
          const phName = systemConfig.sensor_names?.[phKey] || sensorSetpoints[phKey]?.name || phKey;
          const isPaused = Boolean(roomPausedStates[phKey]);
          const tele = liveTelemetry?.[phKey] || {};

          return (
            <button
              key={phKey}
              onClick={() => setActivePh(phKey)}
              className={`flex items-center gap-2.5 rounded-t-xl px-4 py-3 text-xs font-bold transition-all border-b-2 whitespace-nowrap cursor-pointer ${
                isSelected
                  ? 'border-emerald-400 bg-slate-800 text-white shadow-lg shadow-emerald-500/5'
                  : 'border-transparent bg-slate-900/60 text-slate-400 hover:bg-slate-800/50 hover:text-slate-200'
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${
                isPaused ? 'bg-amber-400' :
                tele.status === 'OK' ? 'bg-emerald-400' : 'bg-slate-500'
              }`} />
              <span>{phKey} • {phName}</span>
              {phKey === 'PH-06' && <span className="rounded bg-sky-500/20 text-sky-300 px-1.5 py-0.2 text-[10px]">MONITOR</span>}
              {isPaused && <span className="rounded bg-rose-500/20 text-rose-300 px-1 py-0.2 text-[9px]">STOPPED</span>}
            </button>
          );
        })}
      </div>

      {/* ── Selected Zone Detail & Configuration Layout ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Live Telemetry & Relays (Screen 02 Style) */}
        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-700/60 bg-slate-800/60 p-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-700/50">
              <div>
                <h3 className="text-base font-bold text-white">
                  {systemConfig.sensor_names?.[activePh] || activePhSetpoints.name || activePh}
                </h3>
                <span className="text-xs text-slate-400">
                  {activePh === 'PH-06' ? 'Dedicated Monitoring Zone' : `Climate & Irrigation Node (${activePh})`}
                </span>
              </div>
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold uppercase ${
                isCurrentPhPaused ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' :
                'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
              }`}>
                {isCurrentPhPaused ? 'MANUAL STOPPED' : ' ACTIVE'}
              </span>
            </div>

            {/* Live Readings */}
            <div className="grid grid-cols-2 gap-3 my-4">
              <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 p-3">
                <span className="flex items-center gap-1.5 text-xs text-slate-400">
                  <Thermometer className="h-3.5 w-3.5 text-orange-400" /> Temperature
                </span>
                <p className="text-lg font-bold text-white mt-1">
                  {activePhTelemetry.temp !== undefined && activePhTelemetry.temp !== null ? `${activePhTelemetry.temp}°C` : '--'}
                </p>
                <span className="text-[10px] text-slate-500">
                  Target: {activePhSetpoints.temp_target || activePhSetpoints.temp_high_limit || '--'}°C
                </span>
              </div>

              <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 p-3">
                <span className="flex items-center gap-1.5 text-xs text-slate-400">
                  <Droplets className="h-3.5 w-3.5 text-blue-400" /> Humidity
                </span>
                <p className="text-lg font-bold text-white mt-1">
                  {activePhTelemetry.humi !== undefined && activePhTelemetry.humi !== null ? `${activePhTelemetry.humi}%` : '--'}
                </p>
                <span className="text-[10px] text-slate-500">
                  Target: {activePhSetpoints.humi_target || activePhSetpoints.humi_high_limit || '--'}%
                </span>
              </div>

              {activePh !== 'PH-06' && (
                <>
                  <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 p-3">
                    <span className="flex items-center gap-1.5 text-xs text-slate-400">
                      <Activity className="h-3.5 w-3.5 text-purple-400" /> CO₂ Level
                    </span>
                    <p className="text-base font-bold text-white mt-1">
                      {activePhTelemetry.co2 !== undefined && activePhTelemetry.co2 !== null ? `${activePhTelemetry.co2} ppm` : '--'}
                    </p>
                  </div>

                  <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 p-3">
                    <span className="flex items-center gap-1.5 text-xs text-slate-400">
                      <Sun className="h-3.5 w-3.5 text-amber-400" /> PAR / PPFD
                    </span>
                    <p className="text-base font-bold text-white mt-1">
                      {activePhTelemetry.par !== undefined && activePhTelemetry.par !== null ? `${activePhTelemetry.par} µmol` : '--'}
                    </p>
                    <span className="text-[10px] text-emerald-400 font-mono">
                      DLI: {activePhTelemetry.dli !== undefined ? Number(activePhTelemetry.dli).toFixed(2) : '0.00'} mol/m²/d
                    </span>
                  </div>
                </>
              )}
            </div>

            {/* Actuator Relay Status Indicators (PH-01 to PH-05) */}
            {activePh !== 'PH-06' && (
              <div className="space-y-2 border-t border-slate-700/50 pt-3">
                <span className="text-xs font-semibold text-slate-300">Actuator States & Relay Pinouts:</span>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="flex items-center justify-between p-2 rounded-lg bg-slate-900/40 border border-slate-700/30">
                    <span className="text-slate-400">ACF Fans (Ch {activePhRelays.acf})</span>
                    <span className={`font-bold ${relayStates[activePhRelays.acf] ? 'text-emerald-400' : 'text-slate-500'}`}>
                      {relayStates[activePhRelays.acf] ? 'ON' : 'OFF'}
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-2 rounded-lg bg-slate-900/40 border border-slate-700/30">
                    <span className="text-slate-400">Sprinkler (Ch {activePhRelays.sprinkler})</span>
                    <span className={`font-bold ${relayStates[activePhRelays.sprinkler] ? 'text-emerald-400' : 'text-slate-500'}`}>
                      {relayStates[activePhRelays.sprinkler] ? 'ON' : 'OFF'}
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-2 rounded-lg bg-slate-900/40 border border-slate-700/30">
                    <span className="text-slate-400">Fogger (Ch {activePhRelays.fogger})</span>
                    <span className={`font-bold ${relayStates[activePhRelays.fogger] ? 'text-emerald-400' : 'text-slate-500'}`}>
                      {relayStates[activePhRelays.fogger] ? 'ON' : 'OFF'}
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-2 rounded-lg bg-slate-900/40 border border-slate-700/30">
                    <span className="text-slate-400">Zone Pump (Ch {activePhRelays.pump})</span>
                    <span className={`font-bold ${relayStates[activePhRelays.pump] ? 'text-emerald-400' : 'text-slate-500'}`}>
                      {relayStates[activePhRelays.pump] ? 'ON' : 'OFF'}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Zone Control Stop/Run Button */}
            <div className="pt-4 border-t border-slate-700/50 flex gap-2">
              <button
                onClick={() => handleSendAction(isCurrentPhPaused ? 'resume' : 'pause', activePh)}
                className={`w-full py-2.5 rounded-xl font-bold text-xs flex items-center justify-center gap-2 transition-all cursor-pointer ${
                  isCurrentPhPaused
                    ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/20'
                    : 'bg-rose-600 hover:bg-rose-500 text-white shadow-lg shadow-rose-600/20'
                }`}
              >
                {isCurrentPhPaused ? (
                  <>
                    <Play className="h-4 w-4" /> RESUME / RUN AUTOMATION ({activePh})
                  </>
                ) : (
                  <>
                    <Pause className="h-4 w-4" /> STOP ROOM AUTOMATION ({activePh})
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Right 2 Columns: Setpoints, Cyclic Timers & Irrigation Slots */}
        <div className="lg:col-span-2 space-y-5">
          {/* Mode Selector for PH-01 to PH-05 */}
          {activePh !== 'PH-06' && (
            <div className="rounded-2xl border border-slate-700/60 bg-slate-800/60 p-4">
              <span className="text-xs font-bold text-slate-300 block mb-2.5">
                OPERATIONAL AUTOMATION MODE:
              </span>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  { key: 'AUTO', label: 'AUTO (Climate Matrix)', desc: 'Sensor matrix with hysteresis' },
                  { key: 'CYCLIC', label: 'CYCLIC TIMERS', desc: 'Table 20A interval cycling' },
                  { key: 'SCHEDULE', label: 'SCHEDULED SLOTS', desc: 'Time-of-day irrigation' },
                  { key: 'MANUAL', label: 'MANUAL OVERRIDE', desc: 'Hold operator commands' }
                ].map(m => (
                  <button
                    key={m.key}
                    onClick={() => updatePhField(activePh, 'mode', m.key)}
                    className={`rounded-xl border p-2.5 text-left transition-all cursor-pointer ${
                      activePhSetpoints.mode === m.key
                        ? 'border-emerald-500 bg-emerald-500/10 text-white'
                        : 'border-slate-700 bg-slate-900/40 text-slate-400 hover:border-slate-600 hover:text-slate-200'
                    }`}
                  >
                    <span className="text-xs font-bold block">{m.label}</span>
                    <span className="text-[10px] text-slate-500 block mt-0.5">{m.desc}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Climate Thresholds */}
          <div className="rounded-2xl border border-slate-700/60 bg-slate-800/60 p-5 space-y-4">
            <h4 className="text-sm font-bold text-white flex items-center gap-2">
              <Thermometer className="h-4 w-4 text-emerald-400" />
              {activePh === 'PH-06' ? 'Environmental Thresholds (Monitoring Alarm Limits)' : 'Climate Control Thresholds & Setpoints'}
            </h4>

            {activePh === 'PH-06' ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">High Temp Limit Max (°C)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.temp_high_limit ?? 32.0}
                    onChange={(e) => updatePhField(activePh, 'temp_high_limit', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3.5 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">Low Temp Limit Min (°C)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.temp_low_limit ?? 15.0}
                    onChange={(e) => updatePhField(activePh, 'temp_low_limit', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3.5 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">High Humidity Limit Max (%)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.humi_high_limit ?? 85.0}
                    onChange={(e) => updatePhField(activePh, 'humi_high_limit', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3.5 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">Low Humidity Limit Min (%)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.humi_low_limit ?? 35.0}
                    onChange={(e) => updatePhField(activePh, 'humi_low_limit', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3.5 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">Temp Min (°C)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.temp_low ?? 22.0}
                    onChange={(e) => updatePhField(activePh, 'temp_low', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">Temp Target (°C)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.temp_target ?? 25.0}
                    onChange={(e) => updatePhField(activePh, 'temp_target', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">Temp Max (°C)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.temp_high ?? 28.0}
                    onChange={(e) => updatePhField(activePh, 'temp_high', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">Temp Hysteresis</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.temp_hysteresis ?? 1.0}
                    onChange={(e) => updatePhField(activePh, 'temp_hysteresis', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">Humi Min (%)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.humi_low ?? 60.0}
                    onChange={(e) => updatePhField(activePh, 'humi_low', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">Humi Target (%)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.humi_target ?? 70.0}
                    onChange={(e) => updatePhField(activePh, 'humi_target', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">Humi Max (%)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.humi_high ?? 80.0}
                    onChange={(e) => updatePhField(activePh, 'humi_high', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-400">Humi Hysteresis</label>
                  <input
                    type="number"
                    step="0.1"
                    value={activePhSetpoints.humi_hysteresis ?? 3.0}
                    onChange={(e) => updatePhField(activePh, 'humi_hysteresis', parseFloat(e.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Cyclic Timers (Table 20A Matrix) */}
          {activePh !== 'PH-06' && (
            <div className="rounded-2xl border border-slate-700/60 bg-slate-800/60 p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  <Clock className="h-4 w-4 text-sky-400" />
                  Cyclic Interval Timers (Table 20A Matrix)
                </h4>
                <span className="text-xs text-slate-400">Independent ACF, Sprinkler & Fogger cycles</span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-900/50 text-slate-400 border-b border-slate-700/50 uppercase">
                    <tr>
                      <th className="px-3 py-2.5">Timer Name</th>
                      <th className="px-3 py-2.5">Start Window</th>
                      <th className="px-3 py-2.5">Stop Window</th>
                      <th className="px-3 py-2.5">ON Duration</th>
                      <th className="px-3 py-2.5">OFF Interval</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/40">
                    {[
                      { prefix: 'Timer1', defName: 'ACF FANS', defOn: 15, defOff: 30 },
                      { prefix: 'Timer2', defName: 'SPRINKLER', defOn: 2, defOff: 30 },
                      { prefix: 'Timer3', defName: 'FOGGER', defOn: 1, defOff: 2 }
                    ].map(t => (
                      <tr key={t.prefix} className="hover:bg-slate-700/20">
                        <td className="px-3 py-2 font-bold text-white whitespace-nowrap">
                          {activePhSetpoints[`${t.prefix} Name`] || t.defName}
                        </td>
                        <td className="px-3 py-2">
                          <input
                            type="text"
                            value={activePhSetpoints[`${t.prefix} Start`] || '00:00'}
                            onChange={(e) => updatePhField(activePh, `${t.prefix} Start`, e.target.value)}
                            className="w-20 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-center font-mono text-white"
                          />
                        </td>
                        <td className="px-3 py-2">
                          <input
                            type="text"
                            value={activePhSetpoints[`${t.prefix} Stop`] || '23:59'}
                            onChange={(e) => updatePhField(activePh, `${t.prefix} Stop`, e.target.value)}
                            className="w-20 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-center font-mono text-white"
                          />
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-1">
                            <input
                              type="number"
                              value={activePhSetpoints[`${t.prefix} ON Min`] ?? t.defOn}
                              onChange={(e) => updatePhField(activePh, `${t.prefix} ON Min`, parseInt(e.target.value) || 1)}
                              className="w-16 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-center font-mono text-emerald-400 font-bold"
                            />
                            <span className="text-slate-400">min</span>
                          </div>
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center gap-1">
                            <input
                              type="number"
                              value={activePhSetpoints[`${t.prefix} OFF Min`] ?? t.defOff}
                              onChange={(e) => updatePhField(activePh, `${t.prefix} OFF Min`, parseInt(e.target.value) || 1)}
                              className="w-16 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-center font-mono text-amber-400 font-bold"
                            />
                            <span className="text-slate-400">min</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Irrigation & Fogging Slots (Screen 12) */}
          {activePh !== 'PH-06' && (
            <div className="rounded-2xl border border-slate-700/60 bg-slate-800/60 p-5 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-bold text-white flex items-center gap-2">
                    <Droplets className="h-4 w-4 text-teal-400" />
                    Scheduled Irrigation & Fogging Slots (Screen 12)
                  </h4>
                  <p className="text-xs text-slate-400 mt-0.5">Automated time-of-day actuation triggers</p>
                </div>
                <button
                  onClick={() => handleAddSlot(activePh)}
                  className="flex items-center gap-1 rounded-xl bg-sky-500/10 border border-sky-500/30 px-3 py-1.5 text-xs font-semibold text-sky-400 hover:bg-sky-500 hover:text-white transition-all cursor-pointer"
                >
                  <Plus className="h-3.5 w-3.5" /> Add Slot
                </button>
              </div>

              {(activePhSetpoints.irrigation_slots || []).length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-700 p-6 text-center text-xs text-slate-500">
                  No irrigation slots configured for {activePh}. Click "+ Add Slot" above to define time triggers.
                </div>
              ) : (
                <div className="space-y-2">
                  {activePhSetpoints.irrigation_slots.map((slot, sIdx) => (
                    <div
                      key={sIdx}
                      className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-slate-900/50 border border-slate-700/40 text-xs"
                    >
                      <span className="font-bold text-sky-400 w-14">Slot #{slot.id || sIdx + 1}</span>

                      {/* Start Time */}
                      <div className="flex items-center gap-1.5">
                        <span className="text-slate-400">Start:</span>
                        <input
                          type="text"
                          value={slot.start || '08:00 AM'}
                          onChange={(e) => handleUpdateSlot(activePh, sIdx, 'start', e.target.value)}
                          className="w-24 rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-center font-mono text-white"
                        />
                      </div>

                      {/* Type Toggle */}
                      <div className="flex items-center gap-1.5">
                        <span className="text-slate-400">Type:</span>
                        <button
                          onClick={() => handleUpdateSlot(activePh, sIdx, 'type', (slot.type === 'sprinkler' ? 'fogger' : 'sprinkler'))}
                          className={`rounded-lg px-2.5 py-1 font-bold uppercase transition-all cursor-pointer ${
                            slot.type === 'fogger'
                              ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                              : 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                          }`}
                        >
                          {slot.type || 'sprinkler'}
                        </button>
                      </div>

                      {/* Duration */}
                      <div className="flex items-center gap-1.5">
                        <span className="text-slate-400">Duration:</span>
                        <input
                          type="number"
                          value={slot.duration_sec ?? 120}
                          onChange={(e) => handleUpdateSlot(activePh, sIdx, 'duration_sec', parseInt(e.target.value) || 0)}
                          className="w-16 rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-center font-mono text-emerald-400 font-bold"
                        />
                        <span className="text-slate-500">sec</span>
                      </div>

                      {/* Enabled Toggle */}
                      <button
                        onClick={() => handleUpdateSlot(activePh, sIdx, 'enabled', !slot.enabled)}
                        className={`rounded-lg px-2.5 py-1 font-bold transition-all cursor-pointer ${
                          slot.enabled
                            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                            : 'bg-slate-700/40 text-slate-500'
                        }`}
                      >
                        {slot.enabled ? 'ENABLED' : 'DISABLED'}
                      </button>

                      {/* Delete */}
                      <button
                        onClick={() => handleDeleteSlot(activePh, sIdx)}
                        className="rounded-lg p-1.5 text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition-all cursor-pointer"
                        title="Delete slot"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Modal: Master Hydraulic & System Settings ── */}
      {showConfigModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="w-full max-w-2xl rounded-2xl border border-slate-700 bg-slate-800 p-6 shadow-2xl space-y-5 max-h-[90vh] overflow-y-auto"
          >
            <div className="flex items-center justify-between pb-3 border-b border-slate-700">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Sliders className="h-5 w-5 text-sky-400" />
                Master Hydraulic & System Configuration
              </h3>
              <button
                onClick={() => setShowConfigModal(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4 text-xs">
              {/* Pump Arbitration */}
              <div className="rounded-xl border border-slate-700/60 bg-slate-900/50 p-4 space-y-3">
                <span className="font-bold text-white block">HYDRAULIC ARBITRATION & INTERLOCKS:</span>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="text-slate-400 block mb-1">Arbitration Mode</label>
                    <select
                      value={systemConfig.pump_arbitration_mode || 'sequential'}
                      onChange={(e) => updateSystemConfigField('pump_arbitration_mode', e.target.value)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-white outline-none"
                    >
                      <option value="sequential">Sequential Priority Time-Slicing (120s per room)</option>
                      <option value="parallel">Parallel Multi-Zone Simultaneous</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Buzzer Auto-Silence Limit (sec)</label>
                    <input
                      type="number"
                      value={systemConfig.buzzer_auto_silence_sec ?? 30}
                      onChange={(e) => updateSystemConfigField('buzzer_auto_silence_sec', parseInt(e.target.value) || 30)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-white outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Pump Pre-Start Delay (sec)</label>
                    <input
                      type="number"
                      step="0.5"
                      value={systemConfig.pump_start_delay_sec ?? 3.0}
                      onChange={(e) => updateSystemConfigField('pump_start_delay_sec', parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-white outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Pump Post-Run Stop Delay (sec)</label>
                    <input
                      type="number"
                      step="0.5"
                      value={systemConfig.pump_post_run_delay_sec ?? 3.0}
                      onChange={(e) => updateSystemConfigField('pump_post_run_delay_sec', parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-white outline-none"
                    />
                  </div>
                </div>
              </div>

              {/* Cloud Upload & Alarm Offsets */}
              <div className="rounded-xl border border-slate-700/60 bg-slate-900/50 p-4 space-y-3">
                <span className="font-bold text-white block">TELEMETRY UPLOAD & ALARM TOLERANCE:</span>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="text-slate-400 block mb-1">Upload Hours</label>
                    <input
                      type="number"
                      value={systemConfig.upload_hours ?? 0}
                      onChange={(e) => updateSystemConfigField('upload_hours', parseInt(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-white text-center"
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Upload Mins</label>
                    <input
                      type="number"
                      value={systemConfig.upload_mins ?? 1}
                      onChange={(e) => updateSystemConfigField('upload_mins', parseInt(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-white text-center"
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Upload Secs</label>
                    <input
                      type="number"
                      value={systemConfig.upload_secs ?? 0}
                      onChange={(e) => updateSystemConfigField('upload_secs', parseInt(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-white text-center"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 pt-2">
                  <div>
                    <label className="text-slate-400 block mb-1">Temp Alarm Offset (±°C)</label>
                    <input
                      type="number"
                      step="0.5"
                      value={systemConfig.temp_alarm_offset ?? 5.0}
                      onChange={(e) => updateSystemConfigField('temp_alarm_offset', parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-white"
                    />
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Humidity Alarm Offset (±%)</label>
                    <input
                      type="number"
                      step="0.5"
                      value={systemConfig.humi_alarm_offset ?? 5.0}
                      onChange={(e) => updateSystemConfigField('humi_alarm_offset', parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-white"
                    />
                  </div>
                </div>
              </div>

              {/* Custom Polyhouse Names */}
              <div className="rounded-xl border border-slate-700/60 bg-slate-900/50 p-4 space-y-3">
                <span className="font-bold text-white block">CUSTOM POLYHOUSE DISPLAY NAMES:</span>
                <div className="grid grid-cols-2 gap-2">
                  {ALL_POLYHOUSES.map(phKey => (
                    <div key={phKey}>
                      <label className="text-slate-400 block mb-1">{phKey} Name</label>
                      <input
                        type="text"
                        value={systemConfig.sensor_names?.[phKey] || ''}
                        onChange={(e) => {
                          const val = e.target.value;
                          setSystemConfig(prev => ({
                            ...prev,
                            sensor_names: {
                              ...(prev.sensor_names || {}),
                              [phKey]: val
                            }
                          }));
                        }}
                        className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-white"
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-slate-700">
              <button
                onClick={() => setShowConfigModal(false)}
                className="px-4 py-2 rounded-xl border border-slate-700 text-slate-300 hover:text-white text-xs cursor-pointer"
              >
                Close
              </button>
              <button
                onClick={() => {
                  setShowConfigModal(false);
                  handleSaveAll();
                }}
                className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs cursor-pointer"
              >
                Apply & Save Config
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  );
}
