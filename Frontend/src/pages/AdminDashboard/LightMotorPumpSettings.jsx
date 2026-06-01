import { useState, useEffect, useRef } from 'react';
import { Save, AlertCircle, CheckCircle2, RefreshCw, Zap, Wifi, Radio, ToggleLeft, ToggleRight, Clock, ChevronDown, X } from 'lucide-react';
import mqtt from 'mqtt';

// ─── Day picker ───────────────────────────────────────────────────────────────
const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const DayPicker = ({ days, onChange }) => (
  <div className="flex gap-1 flex-wrap">
    {DAY_LABELS.map((d, i) => (
      <button
        key={i}
        type="button"
        onClick={() => {
          const next = [...days];
          next[i] = next[i] === 1 ? 0 : 1;
          onChange(next);
        }}
        className={`rounded-lg px-2 py-1 text-[10px] font-bold transition-all ${days[i] === 1
          ? 'bg-green-500/20 text-green-400 ring-1 ring-green-500/40'
          : 'bg-slate-800 text-slate-500 hover:text-slate-300'
          }`}
      >
        {d}
      </button>
    ))}
  </div>
);

// ─── Field input ──────────────────────────────────────────────────────────────
const Field = ({ label, value, onChange, type = 'text', placeholder = '' }) => (
  <div className="flex flex-col gap-1">
    <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</label>
    <input
      type={type}
      value={value ?? ''}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500/40 transition-all"
    />
  </div>
);

// ─── Mode toggle ──────────────────────────────────────────────────────────────
const ModeToggle = ({ mode, onChange }) => (
  <div className="flex gap-2">
    {['auto', 'manual'].map(m => (
      <button
        key={m}
        type="button"
        onClick={() => onChange(m)}
        className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold capitalize transition-all ${mode === m
          ? 'bg-green-500/20 text-green-400 ring-1 ring-green-500/40'
          : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
      >
        {m === 'auto' ? <Clock className="h-3 w-3" /> : <ToggleRight className="h-3 w-3" />}
        {m}
      </button>
    ))}
  </div>
);

// ─── Relay card ───────────────────────────────────────────────────────────────
const RELAY_COLORS = { light: '#facc15', motor: '#60a5fa', pump: '#22d3ee' };

const RelayCard = ({ name, relay, onChange }) => {
  const update = (key, val) => onChange({ ...relay, [key]: val });
  const color = RELAY_COLORS[name] || '#a3a3a3';

  return (
    <div className="rounded-xl border bg-slate-800/30 p-5 transition-all"
      style={{ borderColor: 'rgba(51,65,85,0.5)' }}>
      <div className="mb-4 flex items-center justify-between">
        <h4 className="flex items-center gap-2 text-sm font-semibold" style={{ color }}>
          <Zap className="h-4 w-4" />
          {name.toUpperCase()} Relay
          <span className="text-[10px] text-slate-500 font-normal">pin {relay.pin}</span>
        </h4>
        <ModeToggle mode={relay.mode} onChange={v => update('mode', v)} />
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 mb-4">
        <Field label="Start Time" value={relay.start_time} type="time" onChange={v => update('start_time', v)} />
        <Field label="End Time" value={relay.end_time} type="time" onChange={v => update('end_time', v)} />
        <Field label="ON Duration (min)" value={relay.on_min} type="number" onChange={v => update('on_min', Number(v))} />
        <Field label="OFF Duration (min)" value={relay.off_min} type="number" onChange={v => update('off_min', Number(v))} />
      </div>

      {relay.mode === 'manual' && (
        <div className="mb-4 flex items-center gap-3">
          <span className="text-xs text-slate-400">Manual State:</span>
          <button
            type="button"
            onClick={() => update('manual_state', relay.manual_state === 1 ? 0 : 1)}
            className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${relay.manual_state === 1
              ? 'bg-green-500/20 text-green-400 ring-1 ring-green-500/40'
              : 'bg-red-500/10 text-red-400 ring-1 ring-red-500/20'
              }`}
          >
            {relay.manual_state === 1 ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
            {relay.manual_state === 1 ? 'ON' : 'OFF'}
          </button>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Active Days</span>
        <DayPicker days={relay.days} onChange={v => update('days', v)} />
      </div>
    </div>
  );
};

// ─── Save Confirmation Modal ──────────────────────────────────────────────────
const SaveModal = ({ onConfirm, onCancel, status }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-base font-semibold text-white">
          <Save className="h-5 w-5 text-emerald-400" />
          Save Changes
        </h3>
        <button onClick={onCancel} className="rounded-lg p-1 text-slate-400 hover:text-white hover:bg-slate-800 transition-all">
          <X className="h-4 w-4" />
        </button>
      </div>

      <p className="mb-2 text-sm text-slate-300">
        Are you sure you want to push the updated configuration to the device?
      </p>
      <p className="mb-6 text-xs text-slate-500">
        This will publish the new settings via MQTT. The device will apply changes immediately upon receiving them.
      </p>

      {status === 'error' && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          MQTT not connected. Please wait for connection before saving.
        </div>
      )}

      <div className="flex justify-end gap-3">
        <button
          onClick={onCancel}
          className="rounded-xl border border-slate-700 px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-800 transition-all"
        >
          Cancel
        </button>
        <button
          onClick={onConfirm}
          disabled={status === 'saving'}
          className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-5 py-2 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 disabled:opacity-50 transition-all"
        >
          {status === 'saving'
            ? <><RefreshCw className="h-4 w-4 animate-spin" /> Saving…</>
            : <><Save className="h-4 w-4" /> Confirm & Push</>}
        </button>
      </div>
    </div>
  </div>
);

// ─── Success Toast ────────────────────────────────────────────────────────────
const SuccessToast = ({ onClose }) => (
  <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-5 py-3 shadow-xl backdrop-blur-sm animate-in slide-in-from-bottom-4">
    <CheckCircle2 className="h-5 w-5 text-emerald-400" />
    <span className="text-sm font-medium text-emerald-300">Configuration pushed successfully!</span>
    <button onClick={onClose} className="ml-2 text-slate-400 hover:text-white">
      <X className="h-4 w-4" />
    </button>
  </div>
);

// ─── Default config ───────────────────────────────────────────────────────────
const DEFAULT_CONFIG = {
  ssid: '',
  password: '',
  device_id: '',
  tz_offset: 5.5,
  mqtt_broker: 'mqtt3.thingspeak.com',
  mqtt_client_id: '',
  mqtt_user: '',
  mqtt_pass: '',
  ts_channel_id: '',
  ts_write_key: '',
  ts_read_key: '',
  mqtt_cmd_topic: '',
  mqtt_status_topic: '',
  relays: {
    light: { pin: 4, mode: 'auto', manual_state: 0, start_time: '08:00', end_time: '20:00', on_min: 0, off_min: 0, days: [1, 1, 1, 1, 1, 1, 1] },
    motor: { pin: 12, mode: 'auto', manual_state: 0, start_time: '00:00', end_time: '23:59', on_min: 15, off_min: 30, days: [1, 1, 1, 1, 1, 1, 1] },
    pump: { pin: 5, mode: 'manual', manual_state: 0, start_time: '10:00', end_time: '15:00', on_min: 5, off_min: 10, days: [1, 1, 1, 1, 1, 1, 1] },
  },
};

// ─── Main component ───────────────────────────────────────────────────────────
const LightMotorPumpSettings = () => {
  const [devices, setDevices] = useState([]);
  const [deviceRoot, setDeviceRoot] = useState('');
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [savedConfig, setSavedConfig] = useState(DEFAULT_CONFIG);
  const [status, setStatus] = useState('disconnected');
  const [loading, setLoading] = useState(true);
  const [client, setClient] = useState(null);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [showSuccessToast, setShowSuccessToast] = useState(false);
  const dropdownRef = useRef(null);

  const token = localStorage.getItem('token');
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  // Accept both role and accountType fields (backend uses 'role')
  const isSuperadmin = user.role === 'superadmin' || user.accountType === 'superadmin';
  const isAdmin = user.role === 'admin' || user.role === 'superadmin'
    || user.accountType === 'admin' || user.accountType === 'superadmin';
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // Dirty check — any unsaved changes?
  const isDirty = JSON.stringify(config) !== JSON.stringify(savedConfig);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // ── Fetch devices ────────────────────────────────────────────────────────────
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();
        if (data.success) {
          const filtered = data.data.filter(
            d => !d.deviceType || d.deviceType === 'system2' || d.deviceType === 'standard' || d.deviceType === 'light_motor_pump'
          );
          setDevices(filtered);
          if (filtered.length > 0) setDeviceRoot(filtered[0].mqttId || filtered[0]._id);
        }
      } catch (err) {
        console.error('Failed to fetch devices', err);
      } finally {
        setLoading(false);
      }
    };
    fetchDevices();
  }, [token]);

  const selectedDevice = devices.find(d => (d.mqttId || d._id) === deviceRoot);

  // ── DB Pre-fill & MQTT connection ──────────────────────────────────────────
  useEffect(() => {
    if (!deviceRoot) return;

    // 1. Get DB values for this device
    const device = devices.find(d => (d.mqttId || d._id) === deviceRoot);
    const ts = device?.thingspeak || {};

    const dbConfig = {
      ...DEFAULT_CONFIG,
      mqtt_broker: ts.broker || DEFAULT_CONFIG.mqtt_broker,
      mqtt_client_id: ts.clientId || DEFAULT_CONFIG.mqtt_client_id,
      mqtt_user: ts.username || DEFAULT_CONFIG.mqtt_user,
      mqtt_pass: ts.password || DEFAULT_CONFIG.mqtt_pass,
      ts_channel_id: ts.channelId || DEFAULT_CONFIG.ts_channel_id,
      ts_write_key: ts.writeApiKey || DEFAULT_CONFIG.ts_write_key,
      ts_read_key: ts.readApiKey || DEFAULT_CONFIG.ts_read_key,
    };

    // 2. Set UI immediately to DB values
    setConfig(dbConfig);
    setSavedConfig(dbConfig);
    setStatus('disconnected');

    // 3. Connect to MQTT
    const mqttClient = mqtt.connect('wss://broker.hivemq.com:8884/mqtt');

    mqttClient.on('connect', () => {
      setStatus('connected');
      const currentTopic = `inhydro/${deviceRoot}/config/current`;
      const requestTopic = `inhydro/${deviceRoot}/config/request`;
      mqttClient.subscribe(currentTopic);
      mqttClient.publish(requestTopic, '1');
    });

    mqttClient.on('message', (topic, message) => {
      if (topic === `inhydro/${deviceRoot}/config/current`) {
        try {
          const incoming = JSON.parse(message.toString());

          setConfig(prev => {
            const merged = {
              ...dbConfig, // Start with DB config
              ...incoming, // Overwrite with device current config

              // BUT if device sends empty ThingSpeak keys, fallback to DB config!
              mqtt_broker: incoming.mqtt_broker || dbConfig.mqtt_broker,
              mqtt_client_id: incoming.mqtt_client_id || dbConfig.mqtt_client_id,
              mqtt_user: incoming.mqtt_user || dbConfig.mqtt_user,
              mqtt_pass: incoming.mqtt_pass || dbConfig.mqtt_pass,
              ts_channel_id: incoming.ts_channel_id || dbConfig.ts_channel_id,
              ts_write_key: incoming.ts_write_key || dbConfig.ts_write_key,
              ts_read_key: incoming.ts_read_key || dbConfig.ts_read_key,

              // Relays from incoming (falling back to DEFAULT_CONFIG.relays)
              relays: { ...DEFAULT_CONFIG.relays, ...(incoming.relays || {}) },
            };
            setSavedConfig(merged);
            return merged;
          });
        } catch (e) {
          console.error('[MQTT] Config parse error', e);
        }
      }
    });

    mqttClient.on('error', (err) => { console.error('[MQTT] Error:', err); setStatus('error'); });
    mqttClient.on('offline', () => setStatus('disconnected'));
    mqttClient.on('reconnect', () => setStatus('disconnected'));

    setClient(mqttClient);
    return () => { mqttClient.end(); };
  }, [deviceRoot, devices]);

  const handleRequestSync = () => {
    if (client && client.connected) {
      client.publish(`inhydro/${deviceRoot}/config/request`, '1');
    }
  };

  const updateTop = (key, val) => setConfig(prev => ({ ...prev, [key]: val }));
  const updateRelay = (name, data) => setConfig(prev => ({ ...prev, relays: { ...prev.relays, [name]: data } }));

  // ── Open save modal ───────────────────────────────────────────────────────────
  const handleSaveClick = () => {
    setShowSaveModal(true);
  };

  // ── Confirm save ─────────────────────────────────────────────────────────────
  const handleConfirmSave = () => {
    if (!client || !client.connected) {
      setStatus('error');
      return;
    }
    setStatus('saving');

    const payload = isSuperadmin ? { ...config } : { relays: config.relays };

    // Sync ThingSpeak keys to DB for superadmin
    if (isSuperadmin && selectedDevice) {
      const dbPayload = {
        thingspeak: {
          channelId: config.ts_channel_id,
          readApiKey: config.ts_read_key,
          writeApiKey: config.ts_write_key,
          clientId: config.mqtt_client_id,
          username: config.mqtt_user,
          password: config.mqtt_pass,
        },
      };
      fetch(`${API_BASE}/api/devices/${selectedDevice._id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(dbPayload),
      }).catch(err => console.error('DB sync error:', err));
    }

    client.publish(`inhydro/${deviceRoot}/config/update`, JSON.stringify(payload), (err) => {
      if (err) {
        setStatus('error');
      } else {
        setStatus('saved');
        setSavedConfig(config); // mark as clean
        setShowSaveModal(false);
        setShowSuccessToast(true);
        setTimeout(() => { setStatus('connected'); }, 3000);
        setTimeout(() => { setShowSuccessToast(false); }, 5000);
      }
    });
  };

  // ── Status map ────────────────────────────────────────────────────────────────
  const statusMap = {
    connected: <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400"><CheckCircle2 className="h-4 w-4" /> Cloud Connected</span>,
    disconnected: <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-400"><RefreshCw className="h-4 w-4 animate-spin" /> Connecting…</span>,
    saving: <span className="flex items-center gap-1.5 text-xs font-semibold text-green-400"><RefreshCw className="h-4 w-4 animate-spin" /> Pushing…</span>,
    saved: <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400"><CheckCircle2 className="h-4 w-4" /> Sent Successfully</span>,
    error: <span className="flex items-center gap-1.5 text-xs font-semibold text-red-400"><AlertCircle className="h-4 w-4" /> Check Connection</span>,
  };

  // ── Loading / empty states ────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20">
        <RefreshCw className="h-8 w-8 animate-spin text-green-500" />
      </div>
    );
  }

  if (devices.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20 p-8 text-center">
        <Zap className="mb-4 h-12 w-12 text-slate-600" />
        <h3 className="text-lg font-semibold text-white">No Devices Found</h3>
        <p className="mt-2 text-sm text-slate-400">Add a compatible device from the "Devices" page first.</p>
      </div>
    );
  }

  return (
    <>
      {/* ── Save Confirmation Modal ── */}
      {showSaveModal && (
        <SaveModal
          status={status}
          onConfirm={handleConfirmSave}
          onCancel={() => setShowSaveModal(false)}
        />
      )}

      {/* ── Success Toast ── */}
      {showSuccessToast && (
        <SuccessToast onClose={() => setShowSuccessToast(false)} />
      )}

      <div className="space-y-6">
        {/* ── Header ── */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-white">Light · Motor · Pump Settings</h3>
            <p className="text-sm text-slate-400 mt-1">Configure relay automation and device provisioning</p>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            {/* Device selector */}
            <div className="relative" ref={dropdownRef}>
              <button
                onClick={() => setIsDropdownOpen(v => !v)}
                className="flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-800/60 px-3 py-2 text-sm text-white hover:border-slate-600 transition-all"
              >
                <Zap className="h-3.5 w-3.5 text-green-400" />
                <span className="max-w-[140px] truncate">{selectedDevice?.name || deviceRoot || 'Select Device'}</span>
                <ChevronDown className={`h-3.5 w-3.5 text-slate-400 transition-transform ${isDropdownOpen ? 'rotate-180' : ''}`} />
              </button>
              {isDropdownOpen && (
                <div className="absolute right-0 top-full mt-1 z-20 min-w-[200px] rounded-xl border border-slate-700 bg-slate-900 shadow-2xl overflow-hidden">
                  {devices.map(d => {
                    const id = d.mqttId || d._id;
                    return (
                      <button
                        key={d._id}
                        onClick={() => { setDeviceRoot(id); setIsDropdownOpen(false); }}
                        className={`w-full flex items-center gap-2 px-4 py-2.5 text-sm text-left transition-all ${id === deviceRoot
                          ? 'bg-green-500/10 text-green-400'
                          : 'text-slate-300 hover:bg-slate-800'
                          }`}
                      >
                        <Zap className="h-3 w-3 shrink-0" />
                        <span className="truncate">{d.name}</span>
                        {d.mqttId && <span className="ml-auto text-[10px] text-slate-500 font-mono">{d.mqttId}</span>}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Status + sync */}
            <div className="flex items-center gap-2">
              {statusMap[status]}
              <button
                onClick={handleRequestSync}
                title="Ask device to resend its current config"
                disabled={status !== 'connected'}
                className="rounded-lg border border-slate-700 p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 disabled:opacity-40 transition-all"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>

        {/* ── MQTT topic info ── */}
        <div className="rounded-lg border border-slate-700/40 bg-slate-900/40 px-4 py-2 text-[11px] text-slate-500 space-y-0.5">
          <p>
            <span className="text-slate-600">MQTT Topic (push): </span>
            <span className="font-mono text-green-600">inhydro/{deviceRoot}/config/update</span>
          </p>
          <p>
            <span className="text-slate-600">MQTT Topic (listen): </span>
            <span className="font-mono text-blue-600">inhydro/{deviceRoot}/config/current</span>
          </p>
          {!selectedDevice?.mqttId && (
            <p className="text-yellow-500 font-semibold">
              ⚠️ Device has no mqttId set in DB — using DB _id as topic root. Ensure device_id in config.json matches: <span className="font-mono">{deviceRoot}</span>
            </p>
          )}
        </div>

        {/* ── Relay Cards ── */}
        <div className="space-y-4">
          <RelayCard name="light" relay={config.relays.light} onChange={d => updateRelay('light', d)} />
          <RelayCard name="motor" relay={config.relays.motor} onChange={d => updateRelay('motor', d)} />
          <RelayCard name="pump" relay={config.relays.pump} onChange={d => updateRelay('pump', d)} />
        </div>

        {/* ── Admin provisioning panel (visible to all admins) ── */}
        {isAdmin && (
          <div className="space-y-4">
            {/* Network — superadmin only */}
            {isSuperadmin && (
              <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
                <h4 className="mb-4 flex items-center gap-2 text-sm font-semibold text-yellow-400">
                  <Wifi className="h-4 w-4" /> Network &amp; Device Identity
                </h4>
                <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                  <Field label="WiFi SSID" value={config.ssid} onChange={v => updateTop('ssid', v)} />
                  <Field label="WiFi Password" value={config.password} onChange={v => updateTop('password', v)} type="password" />
                  <Field label="Device ID (opt)" value={config.device_id} onChange={v => updateTop('device_id', v)} placeholder="auto-generated" />
                  <Field label="Timezone Offset" value={config.tz_offset} onChange={v => updateTop('tz_offset', parseFloat(v))} type="number" />
                </div>
              </div>
            )}

            {/* MQTT / ThingSpeak — visible to all admins */}
            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
              <h4 className="mb-4 flex items-center gap-2 text-sm font-semibold text-blue-400">
                <Radio className="h-4 w-4 animate-pulse" /> MQTT / ThingSpeak Cloud Configuration
              </h4>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
                <Field label="MQTT Broker" value={config.mqtt_broker} onChange={v => updateTop('mqtt_broker', v)} />
                <Field label="MQTT Client ID" value={config.mqtt_client_id} onChange={v => updateTop('mqtt_client_id', v)} placeholder="auto" />
                <Field label="MQTT Username" value={config.mqtt_user} onChange={v => updateTop('mqtt_user', v)} />
                <Field label="MQTT Password" value={config.mqtt_pass} onChange={v => updateTop('mqtt_pass', v)} type="password" />
                <Field label="TS Channel ID" value={config.ts_channel_id} onChange={v => updateTop('ts_channel_id', v)} />
                <Field label="TS Write API Key" value={config.ts_write_key} onChange={v => updateTop('ts_write_key', v)} />
                <Field label="TS Read API Key" value={config.ts_read_key} onChange={v => updateTop('ts_read_key', v)} />
                <Field label="CMD Topic (opt)" value={config.mqtt_cmd_topic} onChange={v => updateTop('mqtt_cmd_topic', v)} placeholder="auto from channel" />
                <Field label="Status Topic (opt)" value={config.mqtt_status_topic} onChange={v => updateTop('mqtt_status_topic', v)} placeholder="auto from channel" />
              </div>
              <p className="mt-3 text-[11px] text-slate-500">
                Leave CMD/Status Topics blank to auto-derive from Channel ID. Changes trigger a ThingSpeak reconnect on device.
              </p>
            </div>
          </div>
        )}

        {/* ── Save button ── */}
        <div className="pt-2 flex items-center gap-4">
          <button
            onClick={handleSaveClick}
            disabled={status === 'disconnected' || status === 'saving'}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 transition-transform active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Save className="h-4 w-4" />
            Push Config to {selectedDevice?.name || deviceRoot?.toUpperCase() || 'Device'}
          </button>

          {isDirty && (
            <span className="flex items-center gap-1.5 text-xs text-amber-400 font-medium animate-pulse">
              <AlertCircle className="h-3.5 w-3.5" />
              Unsaved changes
            </span>
          )}
        </div>
      </div>
    </>
  );
};

export default LightMotorPumpSettings;