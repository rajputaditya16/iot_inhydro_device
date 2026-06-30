import { useState, useEffect, useRef } from 'react';
import { Save, AlertCircle, CheckCircle2, RefreshCw, Zap, Radio, ChevronDown, X } from 'lucide-react';
import mqtt from 'mqtt';
import DimmableLightControl from '../../components/DimmableLightControl';

const DEFAULT_CONFIG = {
  relays: {
    light: { pin: 4, mode: 'manual', manual_state: 0, brightness: 100, start_time: '08:00', end_time: '20:00', on_min: 0, off_min: 0, days: [1, 1, 1, 1, 1, 1, 1] }
  }
};

const DimmableLightSettings = () => {
  const [devices, setDevices] = useState([]);
  const [deviceRoot, setDeviceRoot] = useState('');
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [savedConfig, setSavedConfig] = useState(DEFAULT_CONFIG);
  const [status, setStatus] = useState('disconnected');
  const [loading, setLoading] = useState(true);
  const [client, setClient] = useState(null);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [showSuccessToast, setShowSuccessToast] = useState(false);
  const dropdownRef = useRef(null);

  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // Unsaved changes check
  const isDirty = JSON.stringify(config.relays.light) !== JSON.stringify(savedConfig.relays.light);

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

  // Fetch all devices from backend database
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();
        if (data.success) {
          // Allow all system controllers to be dimmable light targets
          const filtered = data.data.filter(
            d => !d.deviceType || d.deviceType === 'system2' || d.deviceType === 'standard' || d.deviceType === 'light_motor_pump' || d.deviceType === 'office_control'
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

  // Sync state and connect to HiveMQ MQTT
  useEffect(() => {
    if (!deviceRoot) return;

    // Reset local UI config
    setConfig(DEFAULT_CONFIG);
    setSavedConfig(DEFAULT_CONFIG);
    setStatus('disconnected');

    const mqttClient = mqtt.connect('wss://broker.hivemq.com:8884/mqtt');

    mqttClient.on('connect', () => {
      setStatus('connected');
      const currentTopic = `inhydro/${deviceRoot}/config/current`;
      const requestTopic = `inhydro/${deviceRoot}/config/request`;
      mqttClient.subscribe(currentTopic);
      // Publish request to prompt the physical device to respond with current config
      mqttClient.publish(requestTopic, '1');
    });

    mqttClient.on('message', (topic, message) => {
      if (topic === `inhydro/${deviceRoot}/config/current`) {
        try {
          const incoming = JSON.parse(message.toString());
          if (incoming.relays && incoming.relays.light) {
            const merged = {
              relays: {
                light: {
                  ...DEFAULT_CONFIG.relays.light,
                  ...incoming.relays.light
                }
              }
            };
            setConfig(merged);
            setSavedConfig(merged);
          }
        } catch (e) {
          console.error('[MQTT] Dimmable Config parse error', e);
        }
      }
    });

    mqttClient.on('error', (err) => {
      console.error('[MQTT] Connection error:', err);
      setStatus('error');
    });

    mqttClient.on('offline', () => setStatus('disconnected'));
    mqttClient.on('reconnect', () => setStatus('disconnected'));

    setClient(mqttClient);
    return () => {
      mqttClient.end();
    };
  }, [deviceRoot]);

  const handleRequestSync = () => {
    if (client && client.connected) {
      client.publish(`inhydro/${deviceRoot}/config/request`, '1');
    }
  };

  const updateLightConfig = (data) => {
    setConfig(prev => ({
      ...prev,
      relays: {
        ...prev.relays,
        light: data
      }
    }));
  };

  const handlePushConfig = () => {
    if (!client || !client.connected) {
      setStatus('error');
      return;
    }

    setStatus('saving');

    const payload = {
      relays: {
        light: config.relays.light
      }
    };

    client.publish(`inhydro/${deviceRoot}/config/update`, JSON.stringify(payload), (err) => {
      if (err) {
        setStatus('error');
      } else {
        setStatus('saved');
        setSavedConfig(config);
        setShowSuccessToast(true);
        setTimeout(() => { setStatus('connected'); }, 3000);
        setTimeout(() => { setShowSuccessToast(false); }, 5000);
      }
    });
  };

  // Status mapping
  const statusMap = {
    connected: <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400"><CheckCircle2 className="h-4 w-4" /> Connected</span>,
    disconnected: <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-400"><RefreshCw className="h-4 w-4 animate-spin" /> Connecting…</span>,
    saving: <span className="flex items-center gap-1.5 text-xs font-semibold text-amber-400"><RefreshCw className="h-4 w-4 animate-spin" /> Pushing…</span>,
    saved: <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400"><CheckCircle2 className="h-4 w-4" /> Pushed Config</span>,
    error: <span className="flex items-center gap-1.5 text-xs font-semibold text-red-400"><AlertCircle className="h-4 w-4" /> Comm Error</span>,
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20">
        <RefreshCw className="h-8 w-8 animate-spin text-amber-500" />
      </div>
    );
  }

  if (devices.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20 p-8 text-center">
        <Zap className="mb-4 h-12 w-12 text-slate-600" />
        <h3 className="text-lg font-semibold text-white">No Compatible Devices Found</h3>
        <p className="mt-2 text-sm text-slate-400">Add a device from the "Devices" page first.</p>
      </div>
    );
  }

  return (
    <>
      {/* Toast Alert */}
      {showSuccessToast && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-5 py-3 shadow-xl backdrop-blur-sm animate-in slide-in-from-bottom-4">
          <CheckCircle2 className="h-5 w-5 text-emerald-400" />
          <span className="text-sm font-medium text-emerald-300">Light dimming parameters pushed successfully!</span>
          <button onClick={() => setShowSuccessToast(false)} className="ml-2 text-slate-400 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-white">Dimmable Light Controller</h3>
            <p className="text-sm text-slate-400 mt-1">Configure duty cycles and state parameters wirelessly</p>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            {/* Dropdown device selector */}
            <div className="relative" ref={dropdownRef}>
              <button
                onClick={() => setIsDropdownOpen(v => !v)}
                className="flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-800/60 px-3 py-2 text-sm text-white hover:border-slate-600 transition-all"
              >
                <Zap className="h-3.5 w-3.5 text-amber-400" />
                <span className="max-w-[140px] truncate">{selectedDevice?.name || deviceRoot || 'Select Light Target'}</span>
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
                          ? 'bg-amber-500/10 text-amber-400'
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

            {/* MQTT status and sync button */}
            <div className="flex items-center gap-2">
              {statusMap[status]}
              <button
                onClick={handleRequestSync}
                title="Sync state from controller board"
                disabled={status !== 'connected'}
                className="rounded-lg border border-slate-700 p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 disabled:opacity-40 transition-all"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>

        {/* MQTT Topics info */}
        <div className="rounded-lg border border-slate-700/40 bg-slate-900/40 px-4 py-2 text-[11px] text-slate-500 space-y-0.5">
          <p>
            <span className="text-slate-600">Light Publish Topic: </span>
            <span className="font-mono text-amber-600">inhydro/{deviceRoot}/config/update</span>
          </p>
          <p>
            <span className="text-slate-600">Light Telemetry Topic: </span>
            <span className="font-mono text-blue-600">inhydro/{deviceRoot}/config/current</span>
          </p>
        </div>

        {/* Dynamic Light Card */}
        <DimmableLightControl 
          name="light" 
          relay={config.relays.light} 
          onChange={updateLightConfig} 
        />

        {/* Save/Push Button */}
        <div className="pt-2 flex items-center gap-4">
          <button
            onClick={handlePushConfig}
            disabled={status === 'disconnected' || status === 'saving'}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-amber-500 to-yellow-500 px-6 py-2.5 text-sm font-semibold text-slate-950 shadow-lg shadow-amber-500/20 transition-transform active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Save className="h-4 w-4" />
            Push Config to {selectedDevice?.name || 'Device'}
          </button>

          {isDirty && (
            <span className="flex items-center gap-1.5 text-xs text-amber-400 font-medium animate-pulse">
              <AlertCircle className="h-3.5 w-3.5" />
              Unsaved light adjustments
            </span>
          )}
        </div>
      </div>
    </>
  );
};

export default DimmableLightSettings;
