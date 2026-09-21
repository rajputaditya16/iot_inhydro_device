import { useState, useEffect, useRef } from 'react';
import {
  Save, CheckCircle2, RefreshCw, ChevronDown, Server,
  Thermometer, Droplets, Zap, Clock, ShieldCheck, Activity, Sliders,
  FlaskConical, AlertCircle, Wind, Fan, RotateCw, Edit3, X,
  PowerOff, AlertTriangle, Eye, EyeOff, Sparkles, Sun, Moon
} from 'lucide-react';
import { createMqttClient } from '../../utils/mqtt';

const defaultSetpoints = {
  // Nutrients & pH
  "EC MIN": 1.2,
  "EC MAX": 1.8,
  "PH LOW": 5.8,
  "PH HIGH": 6.5,
  "S_TANK": 2.0,

  // Climate Control (MD02 Temp & Cooling Pad Humidity Safety)
  "TEMP MIN": 22.0,
  "TEMP MED": 25.0,
  "TEMP MAX": 28.0,
  "TEMP Hyst": 0.5,
  "PAD H_Max": 75.0,
  "PAD Safety": 2.0,

  // Fogger Humidifier Day/Night Cycle
  "HUMI Name": "FOGGER TIMER",
  "HUMI D_Start": "06:00",
  "HUMI D_Stop": "18:00",
  "HUMI D_ON Min": 10,
  "HUMI D_OFF Min": 20,
  "HUMI D_Max": 75.0,
  "HUMI D_Min": 55.0,

  "HUMI N_Start": "18:00",
  "HUMI N_Stop": "06:00",
  "HUMI N_ON Min": 5,
  "HUMI N_OFF Min": 40,
  "HUMI N_Max": 80.0,
  "HUMI N_Min": 60.0,

  // Cooling Pad Pump
  "PAD Name": "COOLING PAD PUMP",
  "PAD Start": "06:00",
  "PAD Stop": "18:00",
  "PAD ON Min": 5,
  "PAD OFF Min": 15,

  // Air Circulation Fan (ACF)
  "ACF Name": "AIR CIRCULATION FAN",
  "ACF Start": "06:00",
  "ACF Stop": "22:00",
  "ACF ON Min": 10,
  "ACF OFF Min": 20,

  // Overhead Sprinkler
  "Sprinkler Name": "SPRINKLER",
  "Sprinkler Start": "08:00",
  "Sprinkler Stop": "17:00",
  "Sprinkler ON Min": 2,
  "Sprinkler OFF Min": 30,

  // Daytime Irrigation
  "Irrigation Name": "IRRIGATION",
  "Irrigation Start": "06:00",
  "Irrigation Stop": "18:00",
  "Irrigation ON Min": 15,
  "Irrigation OFF Min": 45,

  // Cyclic Timer 1 (Water Mixing Pump)
  "Timer1 Name": "WATER MIXING PUMP",
  "Timer1 Start": "06:00",
  "Timer1 Stop": "18:00",
  "Timer1 ON Min": 5,
  "Timer1 OFF Min": 15,

  // Cyclic Timer 2
  "Timer2 Name": "CYCLIC TIMER 2",
  "Timer2 Start": "00:00",
  "Timer2 Stop": "23:59",
  "Timer2 ON Min": 10,
  "Timer2 OFF Min": 20,

  // Two-User Authentication Credentials
  "USER 1 Name": "Operator 1",
  "USER 1 PASSWORD": "1111",
  "USER 2 Name": "Operator 2",
  "USER 2 PASSWORD": "2222",
};

// 13 Modbus RTU Relays Definition
const relaysList = [
  { key: 'relay_ec1', name: 'EC1 Dosing Pump', icon: Zap },
  { key: 'relay_ec2', name: 'EC2 Dosing Pump', icon: Zap },
  { key: 'relay_ph', name: 'pH Minus Dosing Pump', icon: FlaskConical },
  { key: 'relay_solenoid', name: 'S-Tank Solenoid Valve', icon: RotateCw },
  { key: 'relay_fan1', name: 'Stage 1 Fan 1 (1st 50%)', icon: Fan },
  { key: 'relay_fan2', name: 'Stage 2 Fan 2 (2nd 50%)', icon: Fan },
  { key: 'relay_pad', name: 'Cooling Pad Pump', icon: Droplets },
  { key: 'relay_fogger', name: 'Fogger Humidifier', icon: Wind },
  { key: 'relay_acf', name: 'Air Circulation Fan (ACF)', icon: Fan },
  { key: 'relay_sprinkler', name: 'Overhead Sprinkler', icon: Droplets },
  { key: 'relay_irrigation', name: 'Daytime Irrigation Pump', icon: RotateCw },
  { key: 'timer1', name: 'Cyclic Timer 1 (Water Mixing)', icon: Clock },
  { key: 'timer2', name: 'Cyclic Timer 2', icon: Clock },
];

// 6 Equipment Cyclic Timers Configuration
const equipmentTimersConfig = [
  {
    title: "Cooling Pad Pump",
    prefix: "PAD",
    nameKey: "PAD Name", defaultName: "COOLING PAD PUMP",
    startKey: "PAD Start", defaultStart: "06:00",
    stopKey: "PAD Stop", defaultStop: "18:00",
    onKey: "PAD ON Min", defaultOn: 5,
    offKey: "PAD OFF Min", defaultOff: 15,
    relayKey: "relay_pad",
    icon: Droplets
  },
  {
    title: "Air Circulation Fan (ACF)",
    prefix: "ACF",
    nameKey: "ACF Name", defaultName: "AIR CIRCULATION FAN",
    startKey: "ACF Start", defaultStart: "06:00",
    stopKey: "ACF Stop", defaultStop: "22:00",
    onKey: "ACF ON Min", defaultOn: 10,
    offKey: "ACF OFF Min", defaultOff: 20,
    relayKey: "relay_acf",
    icon: Fan
  },
  {
    title: "Overhead Sprinkler",
    prefix: "Sprinkler",
    nameKey: "Sprinkler Name", defaultName: "SPRINKLER",
    startKey: "Sprinkler Start", defaultStart: "08:00",
    stopKey: "Sprinkler Stop", defaultStop: "17:00",
    onKey: "Sprinkler ON Min", defaultOn: 2,
    offKey: "Sprinkler OFF Min", defaultOff: 30,
    relayKey: "relay_sprinkler",
    icon: Droplets
  },
  {
    title: "Daytime Irrigation",
    prefix: "Irrigation",
    nameKey: "Irrigation Name", defaultName: "IRRIGATION",
    startKey: "Irrigation Start", defaultStart: "06:00",
    stopKey: "Irrigation Stop", defaultStop: "18:00",
    onKey: "Irrigation ON Min", defaultOn: 15,
    offKey: "Irrigation OFF Min", defaultOff: 45,
    relayKey: "relay_irrigation",
    icon: RotateCw
  },
  {
    title: "Cyclic Timer 1 (Water Mixing)",
    prefix: "Timer1",
    nameKey: "Timer1 Name", defaultName: "WATER MIXING PUMP",
    startKey: "Timer1 Start", defaultStart: "06:00",
    stopKey: "Timer1 Stop", defaultStop: "18:00",
    onKey: "Timer1 ON Min", defaultOn: 5,
    offKey: "Timer1 OFF Min", defaultOff: 15,
    relayKey: "timer1",
    icon: Clock
  },
  {
    title: "Cyclic Timer 2",
    prefix: "Timer2",
    nameKey: "Timer2 Name", defaultName: "CYCLIC TIMER 2",
    startKey: "Timer2 Start", defaultStart: "00:00",
    stopKey: "Timer2 Stop", defaultStop: "23:59",
    onKey: "Timer2 ON Min", defaultOn: 10,
    offKey: "Timer2 OFF Min", defaultOff: 20,
    relayKey: "timer2",
    icon: Clock
  },
];

const MonitSettings = () => {
  const [viewMode, setViewMode] = useState('setpoints'); // 'setpoints' | 'monitoring'
  const [monitDevices, setMonitDevices] = useState([]);
  const [deviceRoot, setDeviceRoot] = useState('');
  const [setpoints, setSetpoints] = useState(defaultSetpoints);
  const [status, setStatus] = useState('disconnected');
  const [loading, setLoading] = useState(true);
  const [client, setClient] = useState(null);
  const [liveData, setLiveData] = useState(null);
  const [isMachineOnline, setIsMachineOnline] = useState(false);
  const lastTelemetryTimeRef = useRef(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Operator PIN reveal states
  const [showPin1, setShowPin1] = useState(false);
  const [showPin2, setShowPin2] = useState(false);

  // Status message / toast
  const [toast, setToast] = useState({ show: false, type: 'success', message: '' });
  const [isEditingName, setIsEditingName] = useState(false);
  const [tempName, setTempName] = useState('');
  const [confirmModal, setConfirmModal] = useState({ open: false, action: null });
  const [commandLoading, setCommandLoading] = useState(false);
  const [commandCooldown, setCommandCooldown] = useState(0);

  // Heartbeat watchdog: checks every 3s if fresh packet was received in the last 45s
  useEffect(() => {
    const ticker = setInterval(() => {
      const isFresh = Boolean(
        lastTelemetryTimeRef.current && (Date.now() - lastTelemetryTimeRef.current < 45000)
      );
      setIsMachineOnline((prev) => (prev !== isFresh ? isFresh : prev));
    }, 3000);
    return () => clearInterval(ticker);
  }, []);

  // Cooldown timer countdown
  useEffect(() => {
    if (commandCooldown <= 0) return;
    const timer = setInterval(() => {
      setCommandCooldown((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [commandCooldown]);

  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  const showToast = (type, message) => {
    setToast({ show: true, type, message });
    setTimeout(() => {
      setToast({ show: false, type: '', message: '' });
    }, 4000);
  };

  // Fetch Monit devices from database
  useEffect(() => {
    const fetchMonitDevices = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const contentType = res.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
          throw new Error("Received non-JSON response from server");
        }
        const data = await res.json();
        if (data.success) {
          const filtered = data.data.filter(d =>
            d.deviceType === 'monit' || d.deviceType === 'monnet' || d.deviceType === 'monit_device' || d.deviceType === 'dosing'
          );
          setMonitDevices(filtered);
          if (filtered.length > 0 && !deviceRoot) {
            setDeviceRoot(filtered[0].mqttId || filtered[0]._id);
          }
        }
      } catch (err) {
        console.error('Failed to fetch Monit devices', err);
      } finally {
        setLoading(false);
      }
    };
    fetchMonitDevices();
  }, [token, API_BASE]);

  const selectedDevice = monitDevices.find(d => (d.mqttId || d._id) === deviceRoot);

  useEffect(() => {
    setTempName(selectedDevice?.name || 'Monnet Device');
    setIsEditingName(false);
  }, [deviceRoot, selectedDevice]);

  const handleNameSave = async () => {
    if (!tempName.trim() || !selectedDevice) return;
    try {
      const res = await fetch(`${API_BASE}/api/devices/${selectedDevice._id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ name: tempName }),
      });
      const data = await res.json();
      if (data.success) {
        setMonitDevices(prev => prev.map(d => d._id === selectedDevice._id ? { ...d, name: tempName } : d));
        setIsEditingName(false);
        showToast('success', 'Device renamed successfully');
      }
    } catch (err) {
      console.error('Failed to update name', err);
      showToast('error', 'Failed to rename device');
    }
  };

  useEffect(() => {
    if (!deviceRoot) return;
    setStatus('disconnected');
    const mqttClient = createMqttClient();

    setSetpoints(defaultSetpoints);

    mqttClient.on('connect', () => {
      setStatus('connected');
      mqttClient.subscribe(`inhydro/${deviceRoot}/setpoints/current`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/telemetry/live`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/room1/telemetry/live`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/command/status`);
      // Request current configuration on initial mount
      mqttClient.publish(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');
    });

    const handleIncomingPacket = (topic, messageData) => {
      if (topic === `inhydro/${deviceRoot}/telemetry/live` || topic === `inhydro/${deviceRoot}/room1/telemetry/live` || topic?.includes('/telemetry/live')) {
        try {
          const parsed = typeof messageData === 'string' ? JSON.parse(messageData) : messageData;
          const payload = Array.isArray(parsed) ? parsed[parsed.length - 1] : parsed;
          if (payload && (payload.ec !== undefined || payload.ph !== undefined || payload.room_temp !== undefined || payload.temp !== undefined || payload.relay_ec1 !== undefined)) {
            setLiveData(payload);
            lastTelemetryTimeRef.current = Date.now();
            setIsMachineOnline(true);
          }
        } catch (e) { }
      }
      else if (topic === `inhydro/${deviceRoot}/command/status` || topic?.endsWith('/command/status')) {
        try {
          const statusData = typeof messageData === 'string' ? JSON.parse(messageData) : messageData;
          if (statusData?.status === 'executing') {
            showToast('success', `Device acknowledged: Executing ${statusData.action} now...`);
          }
        } catch (e) { }
      }
      else if (topic === `inhydro/${deviceRoot}/setpoints/current` || topic?.includes('/setpoints/')) {
        try {
          const incomingData = typeof messageData === 'string' ? JSON.parse(messageData) : messageData;
          setSetpoints(prev => ({
            ...prev,
            ...incomingData
          }));
        } catch (error) {
          console.error("Error parsing current setpoints from device", error);
        }
      }
    };

    mqttClient.on('message', (topic, message) => {
      handleIncomingPacket(topic, message.toString());
    });

    mqttClient.on('error', (err) => {
      console.error("Direct Browser MQTT Error over HTTPS:", err);
    });

    setClient(mqttClient);

    // Real-time SSE Stream Fallback (100% reliable over HTTPS cloud deployment)
    const sseUrl = `${API_BASE}/api/devices/stream`;
    const eventSource = new EventSource(sseUrl);

    eventSource.onopen = () => {
      setStatus('connected');
    };

    eventSource.onmessage = (event) => {
      try {
        const packet = JSON.parse(event.data);
        if (packet.mqttId === deviceRoot || packet.topic?.includes(deviceRoot)) {
          setStatus('connected');
          handleIncomingPacket(packet.topic, packet.data);
        }
      } catch (e) { }
    };

    return () => {
      if (mqttClient) mqttClient.end();
      eventSource.close();
    };
  }, [deviceRoot, API_BASE]);

  const handleInputChange = (key, value) => {
    setSetpoints(prev => ({ ...prev, [key]: value }));
  };

  const handleSaveSetpoints = async () => {
    let published = false;

    if (client && client.connected) {
      try {
        client.publish(`inhydro/${deviceRoot}/setpoints/update`, JSON.stringify(setpoints), { retain: false });
        published = true;
        setSaveSuccess(true);
        showToast('success', `Setpoints pushed to device "${selectedDevice?.name || deviceRoot}" successfully!`);
        setTimeout(() => setSaveSuccess(false), 3000);
      } catch (e) {
        console.warn("Direct WebSocket publish failed, using backend push API:", e);
      }
    }

    if (!published && selectedDevice) {
      try {
        const res = await fetch(`${API_BASE}/api/devices/${selectedDevice._id}/push-config`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify(setpoints),
        });
        const data = await res.json();
        if (data.success) {
          setSaveSuccess(true);
          showToast('success', `Setpoints pushed to device "${selectedDevice?.name || deviceRoot}" successfully via Broker!`);
          setTimeout(() => setSaveSuccess(false), 3000);
        } else {
          showToast('error', data.message || "Failed to push setpoints to device.");
        }
      } catch (err) {
        console.error("Setpoints Push Error:", err);
        showToast('error', "Failed to push setpoints to device.");
      }
    }
  };

  const handleSyncRequest = async () => {
    if (!selectedDevice) return;
    if (client && client.connected) {
      client.publish(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');
      showToast('success', 'Sync request published to device');
    } else {
      try {
        const res = await fetch(`${API_BASE}/api/devices/${selectedDevice._id}/push-config?action=sync`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
        });
        const data = await res.json();
        if (data.success) {
          showToast('success', 'Device sync requested via Backend Broker');
        } else {
          showToast('error', data.message || 'Failed to request sync');
        }
      } catch (err) {
        console.error('Sync Request Error:', err);
        showToast('error', 'Failed to request sync');
      }
    }
  };

  const handleDeviceCommand = async (action) => {
    if (!selectedDevice && !deviceRoot) return;
    if (commandCooldown > 0) {
      showToast('error', 'Command in progress. Please wait a moment.');
      return;
    }
    setCommandLoading(true);
    setCommandCooldown(6);
    setConfirmModal({ open: false, action: null });

    const cmd_id = `cmd_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`;
    const cmdPayload = { action, cmd_id, timestamp: Date.now() };
    let sentViaWs = false;

    // 1. Instant Direct WebSocket MQTT publish
    if (client && client.connected) {
      try {
        client.publish(`inhydro/${deviceRoot}/command`, JSON.stringify(cmdPayload), { retain: false });
        sentViaWs = true;
        showToast('success', `${action === 'restart' ? 'Restart' : 'Exit'} command dispatched to "${selectedDevice?.name || deviceRoot}"`);
        setCommandLoading(false);
      } catch (err) {
        console.warn("Direct MQTT command publish failed, falling back to REST API:", err);
      }
    }

    // 2. Fallback via backend REST API
    if (!sentViaWs) {
      try {
        const deviceId = selectedDevice?._id || deviceRoot;
        const res = await fetch(`${API_BASE}/api/devices/${deviceId}/command`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify(cmdPayload),
        });
        const data = await res.json();
        if (data.success) {
          showToast('success', `${action === 'restart' ? 'Restart' : 'Exit'} command dispatched to "${selectedDevice?.name || deviceRoot}"`);
        } else {
          showToast('error', data.message || `Failed to dispatch ${action} command`);
        }
      } catch (err) {
        console.error("Command error:", err);
        showToast('error', `Failed to send ${action} command to device.`);
      } finally {
        setCommandLoading(false);
      }
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm shadow-lg">
        <RefreshCw className="h-8 w-8 animate-spin text-emerald-400" />
      </div>
    );
  }

  if (monitDevices.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-slate-800 bg-slate-900/60 p-8 text-center backdrop-blur-sm shadow-lg">
        <Server className="mb-4 h-12 w-12 text-slate-600" />
        <h3 className="text-lg font-bold text-white">No Monnet Controllers Found</h3>
        <p className="mt-2 text-sm text-slate-400">Please register a device with type <code className="text-emerald-400 bg-slate-950 px-2 py-0.5 rounded font-mono border border-slate-800">monit</code> on the Devices page first.</p>
      </div>
    );
  }

  const ecVal = isMachineOnline && liveData?.ec != null && Number(liveData.ec) > 0 ? Number(liveData.ec) : null;
  const tdsPpm = isMachineOnline && Number.isFinite(ecVal) && ecVal > 0 ? Math.round(ecVal * 500) : null;

  return (
    <div className="max-w-7xl mx-auto space-y-5 pb-16 text-slate-100 font-sans px-2 sm:px-4">
      {/* Toast Notification Popup */}
      {toast.show && (
        <div className={`fixed top-6 right-6 z-50 flex items-center gap-3 rounded-2xl border px-4 py-3 shadow-2xl backdrop-blur-md transition-all duration-300 max-w-sm ${toast.type === 'success'
          ? 'border-emerald-500/30 bg-slate-950/95 text-emerald-400 shadow-emerald-950/30'
          : 'border-rose-500/30 bg-slate-950/95 text-rose-400 shadow-rose-950/30'
          }`}>
          {toast.type === 'success' ? (
            <CheckCircle2 className="h-5 w-5 shrink-0 animate-pulse text-emerald-400" />
          ) : (
            <AlertCircle className="h-5 w-5 shrink-0 animate-pulse text-rose-400" />
          )}
          <div className="flex flex-col">
            <span className="text-xs font-bold text-white uppercase tracking-wider">
              {toast.type === 'success' ? 'Success' : 'Error'}
            </span>
            <span className="text-xs text-slate-300">{toast.message}</span>
          </div>
        </div>
      )}

      {/* Remote Action Confirmation Modal */}
      {confirmModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 animate-in fade-in duration-200">
          <div className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="flex items-center gap-2 text-base font-bold text-white">
                {confirmModal.action === 'restart' ? (
                  <>
                    <RotateCw className="h-4 w-4 text-amber-400" />
                    Restart Controller
                  </>
                ) : (
                  <>
                    <PowerOff className="h-4 w-4 text-rose-400" />
                    Exit Controller
                  </>
                )}
              </h3>
              <button
                onClick={() => setConfirmModal({ open: false, action: null })}
                className="rounded-lg p-1 text-slate-400 hover:text-white hover:bg-slate-800 transition-all"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <p className="text-sm text-slate-300 leading-relaxed">
              Are you sure you want to {confirmModal.action === 'restart' ? 'restart' : 'exit'}{' '}
              <span className="font-semibold text-white">"{selectedDevice?.name || deviceRoot}"</span>?
            </p>

            <div className="flex justify-end gap-2.5 pt-2">
              <button
                onClick={() => setConfirmModal({ open: false, action: null })}
                disabled={commandLoading}
                className="rounded-xl border border-slate-700 bg-slate-800/80 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-700 hover:text-white transition-all"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDeviceCommand(confirmModal.action)}
                disabled={commandLoading || commandCooldown > 0}
                className={`flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-bold text-white shadow-lg active:scale-95 disabled:opacity-50 transition-all ${confirmModal.action === 'restart'
                  ? 'border border-amber-500/40 bg-amber-500/20 text-amber-300 hover:bg-amber-500/30'
                  : 'border border-rose-500/40 bg-rose-500/20 text-rose-300 hover:bg-rose-500/30'
                  }`}
              >
                {commandLoading ? (
                  <>
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    Sending...
                  </>
                ) : confirmModal.action === 'restart' ? (
                  <>
                    <RotateCw className="h-3.5 w-3.5" />
                    Restart
                  </>
                ) : (
                  <>
                    <PowerOff className="h-3.5 w-3.5" />
                    Exit
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 1. CLEAN TOP HEADER & CONTROLS ── */}
      <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4 p-4 sm:p-5 rounded-2xl bg-slate-900/80 border border-slate-800/80 backdrop-blur-sm shadow-lg shadow-black/20">
        <div className="flex items-center gap-3.5">
          <div className="h-10 w-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0">
            <Activity className="h-5 w-5" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              {isEditingName ? (
                <div className="flex items-center gap-2">
                  <input
                    autoFocus
                    type="text"
                    value={tempName}
                    onChange={(e) => setTempName(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleNameSave()}
                    className="rounded-xl border border-emerald-500/80 bg-slate-950 px-2.5 py-1 text-sm font-semibold text-white outline-none focus:ring-1 focus:ring-emerald-500/30"
                  />
                  <button
                    onClick={handleNameSave}
                    className="rounded-xl bg-emerald-500 hover:bg-emerald-400 px-3 py-1 text-xs font-bold text-slate-950 transition-all shadow-sm"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => setIsEditingName(false)}
                    className="rounded-xl bg-slate-800 hover:bg-slate-700 px-2.5 py-1 text-xs font-medium text-slate-400 hover:text-white transition-all"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <h1 className="text-base sm:text-lg font-bold text-white tracking-tight">
                    {selectedDevice?.name || 'Monnet Device'}
                  </h1>
                  <button
                    onClick={() => setIsEditingName(true)}
                    className="p-1 rounded-lg text-slate-500 hover:text-emerald-400 hover:bg-slate-800/60 transition-colors"
                    title="Rename Controller"
                  >
                    <Edit3 className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}

              {/* Status Badges */}
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
            {/* <p className="text-xs text-slate-400 mt-0.5">Automated Dosing, Climate Thresholds & Relay Timers</p> */}
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center gap-2 w-full lg:w-auto justify-start sm:justify-end">
          {/* Device Selector */}
          <div className="relative flex-1 sm:flex-initial min-w-[170px]">
            <select
              value={deviceRoot}
              onChange={(e) => setDeviceRoot(e.target.value)}
              className="w-full appearance-none bg-slate-950 border border-slate-700/80 text-white text-xs font-semibold rounded-xl pl-8 pr-8 py-2 outline-none hover:border-slate-600 focus:border-emerald-500/60 focus:ring-1 focus:ring-emerald-500/30 cursor-pointer transition-colors"
            >
              {monitDevices.map(d => (
                <option key={d._id} value={d.mqttId || d._id}>
                  {d.name.replace(/\s*\([^)]*\)/g, '').trim() || d.name}
                </option>
              ))}
            </select>
            <Server className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-emerald-400 pointer-events-none" />
            <ChevronDown className="absolute right-2.5 top-2.5 h-3.5 w-3.5 text-slate-400 pointer-events-none" />
          </div>

          {/* Sync Button */}
          <button
            onClick={handleSyncRequest}
            title="Request setpoints sync from device"
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-xs font-medium text-slate-200 hover:text-white transition-all shadow-sm"
          >
            <RefreshCw className="h-3.5 w-3.5 text-slate-400" />
            <span>Sync</span>
          </button>

          {/* Restart */}
          <button
            onClick={() => setConfirmModal({ open: true, action: 'restart' })}
            disabled={commandCooldown > 0 || commandLoading}
            title="Restart Device"
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-amber-500/30 bg-amber-500/10 hover:bg-amber-500/20 active:scale-95 text-xs font-semibold text-amber-300 hover:text-amber-200 transition-all disabled:opacity-50 shadow-sm"
          >
            <RotateCw className={`h-3.5 w-3.5 text-amber-400 ${commandCooldown > 0 ? 'animate-spin' : ''}`} />
            <span>Restart</span>
          </button>

          {/* Exit */}
          <button
            onClick={() => setConfirmModal({ open: true, action: 'exit' })}
            disabled={commandCooldown > 0 || commandLoading}
            title="Exit"
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-rose-500/30 bg-rose-500/10 hover:bg-rose-500/20 active:scale-95 text-xs font-semibold text-rose-300 hover:text-rose-200 transition-all disabled:opacity-50 shadow-sm"
          >
            <PowerOff className="h-3.5 w-3.5 text-rose-400" />
            <span>Exit</span>
          </button>

          {/* Save Button */}
          <button
            onClick={handleSaveSetpoints}
            disabled={!selectedDevice || saveSuccess}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 active:scale-95 text-slate-950 font-bold text-xs transition-all shadow-sm shadow-emerald-500/20 disabled:opacity-50"
          >
            {saveSuccess ? (
              <>
                <CheckCircle2 className="h-3.5 w-3.5" />
                <span>Pushed!</span>
              </>
            ) : (
              <>
                <Save className="h-3.5 w-3.5" />
                <span>Save Changes</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* ── Offline Retained Notice Banner ── */}
      {!isMachineOnline && (
        <div className="flex items-center gap-2.5 p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs font-medium animate-in fade-in">
          <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
          <span>
            <strong>Machine is currently offline:</strong> New setpoints and cyclic timer values will be safely retained on the server and automatically synced when the controller connects.
          </span>
        </div>
      )}

      {/* ── 2. VIEW MODE TABS SWITCHER ── */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-1 bg-slate-900 p-1 rounded-xl border border-slate-800 text-xs w-full sm:w-auto">
          <button
            onClick={() => setViewMode('setpoints')}
            className={`flex items-center justify-center gap-2 px-4 py-2 rounded-lg font-semibold transition-all flex-1 sm:flex-initial ${viewMode === 'setpoints' ? 'bg-emerald-500 text-slate-950 font-bold shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
          >
            <Sliders className="w-3.5 h-3.5" /> Setpoints Setup
          </button>
          <button
            onClick={() => setViewMode('monitoring')}
            className={`flex items-center justify-center gap-2 px-4 py-2 rounded-lg font-semibold transition-all flex-1 sm:flex-initial ${viewMode === 'monitoring' ? 'bg-emerald-500 text-slate-950 font-bold shadow-sm' : 'text-slate-400 hover:text-white'
              }`}
          >
            <Activity className="w-3.5 h-3.5" /> Live Monitor & Relays
          </button>
        </div>
      </div>

      {/* ── SECTION 1: SYSTEM SETPOINTS CONFIGURATION ── */}
      {viewMode === 'setpoints' && (
        <div className="space-y-6 animate-in fade-in duration-200">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

            {/* LEFT COLUMN: NUTRIENTS & PH + FOGGER HUMIDIFIER DAY/NIGHT */}
            <div className="space-y-5">
              {/* Nutrients & pH Limits Card */}
              <div className="rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 p-5 sm:p-6 space-y-4">
                <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
                  <div className="flex items-center gap-2 text-sm font-bold text-white">
                    <span className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      <Zap className="w-4 h-4" />
                    </span>
                    Nutrients & pH Threshold Limits
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                    Dosing
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                  <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">EC MIN (mS/cm)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["EC MIN"] ?? 1.2}
                      onChange={(e) => handleInputChange("EC MIN", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white font-mono font-bold outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition-all"
                    />
                  </div>

                  <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">EC MAX (mS/cm)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["EC MAX"] ?? 1.8}
                      onChange={(e) => handleInputChange("EC MAX", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white font-mono font-bold outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition-all"
                    />
                  </div>

                  <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">pH LOW Limit</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["PH LOW"] ?? 5.8}
                      onChange={(e) => handleInputChange("PH LOW", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white font-mono font-bold outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition-all"
                    />
                  </div>

                  <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">pH HIGH Limit</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["PH HIGH"] ?? 6.5}
                      onChange={(e) => handleInputChange("PH HIGH", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white font-mono font-bold outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition-all"
                    />
                  </div>

                  <div className="sm:col-span-2 flex flex-col gap-1.5 p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">S-TANK Solenoid Threshold (mS/cm)</label>
                    <input
                      type="number"
                      step="0.05"
                      value={setpoints["S_TANK"] ?? 0.45}
                      onChange={(e) => handleInputChange("S_TANK", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white font-mono font-bold outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition-all"
                    />
                  </div>
                </div>
              </div>

              {/* Fogger Day/Night Cycle Table Card */}
              <div className="rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 p-5 sm:p-6 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
                  <div className="flex items-center gap-2 text-sm font-bold text-white">
                    <span className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      <Wind className="w-4 h-4" />
                    </span>
                    Fogger Humidifier Day/Night Cycle
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-semibold text-slate-400">Label:</span>
                    <input
                      type="text"
                      value={setpoints["HUMI Name"] ?? "FOGGER TIMER"}
                      onChange={(e) => handleInputChange("HUMI Name", e.target.value)}
                      className="rounded-xl border border-slate-700/80 bg-slate-950 px-2.5 py-1 text-xs text-emerald-400 font-bold outline-none focus:border-emerald-500"
                    />
                  </div>
                </div>

                {/* Responsive Day & Night Cards */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                  {/* Day Cycle Card */}
                  <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-3">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                      <span className="flex items-center gap-1.5 text-xs font-bold text-amber-300">
                        <Sun className="h-3.5 w-3.5 text-amber-400" /> Day Cycle
                      </span>
                      <span className="text-[10px] font-mono text-slate-400">06:00 - 18:00</span>
                    </div>

                    <div className="space-y-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">Start Time:</span>
                        <input
                          type="text"
                          value={setpoints["HUMI D_Start"] ?? "06:00"}
                          onChange={(e) => handleInputChange("HUMI D_Start", e.target.value)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">Stop Time:</span>
                        <input
                          type="text"
                          value={setpoints["HUMI D_Stop"] ?? "18:00"}
                          onChange={(e) => handleInputChange("HUMI D_Stop", e.target.value)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">ON Time (min):</span>
                        <input
                          type="number"
                          value={setpoints["HUMI D_ON Min"] ?? 10}
                          onChange={(e) => handleInputChange("HUMI D_ON Min", parseFloat(e.target.value) || 0)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">OFF Time (min):</span>
                        <input
                          type="number"
                          value={setpoints["HUMI D_OFF Min"] ?? 20}
                          onChange={(e) => handleInputChange("HUMI D_OFF Min", parseFloat(e.target.value) || 0)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">Target Max %:</span>
                        <input
                          type="number"
                          value={setpoints["HUMI D_Max"] ?? 75.0}
                          onChange={(e) => handleInputChange("HUMI D_Max", parseFloat(e.target.value) || 0)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-emerald-400 font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">Target Min %:</span>
                        <input
                          type="number"
                          value={setpoints["HUMI D_Min"] ?? 55.0}
                          onChange={(e) => handleInputChange("HUMI D_Min", parseFloat(e.target.value) || 0)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-emerald-400 font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Night Cycle Card */}
                  <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-3">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                      <span className="flex items-center gap-1.5 text-xs font-bold text-slate-300">
                        <Moon className="h-3.5 w-3.5 text-slate-400" /> Night Cycle
                      </span>
                      <span className="text-[10px] font-mono text-slate-400">18:00 - 06:00</span>
                    </div>

                    <div className="space-y-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">Start Time:</span>
                        <input
                          type="text"
                          value={setpoints["HUMI N_Start"] ?? "18:00"}
                          onChange={(e) => handleInputChange("HUMI N_Start", e.target.value)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">Stop Time:</span>
                        <input
                          type="text"
                          value={setpoints["HUMI N_Stop"] ?? "06:00"}
                          onChange={(e) => handleInputChange("HUMI N_Stop", e.target.value)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">ON Time (min):</span>
                        <input
                          type="number"
                          value={setpoints["HUMI N_ON Min"] ?? 5}
                          onChange={(e) => handleInputChange("HUMI N_ON Min", parseFloat(e.target.value) || 0)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">OFF Time (min):</span>
                        <input
                          type="number"
                          value={setpoints["HUMI N_OFF Min"] ?? 40}
                          onChange={(e) => handleInputChange("HUMI N_OFF Min", parseFloat(e.target.value) || 0)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">Target Max %:</span>
                        <input
                          type="number"
                          value={setpoints["HUMI N_Max"] ?? 80.0}
                          onChange={(e) => handleInputChange("HUMI N_Max", parseFloat(e.target.value) || 0)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-emerald-400 font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-400">Target Min %:</span>
                        <input
                          type="number"
                          value={setpoints["HUMI N_Min"] ?? 60.0}
                          onChange={(e) => handleInputChange("HUMI N_Min", parseFloat(e.target.value) || 0)}
                          className="w-24 rounded-lg border border-slate-700/80 bg-slate-900 px-2 py-1 text-xs text-emerald-400 font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* RIGHT COLUMN: CLIMATE CONTROL + USER CREDENTIALS */}
            <div className="space-y-5">
              {/* Climate Control Limits Card */}
              <div className="rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 p-5 sm:p-6 space-y-4">
                <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
                  <div className="flex items-center gap-2 text-sm font-bold text-white">
                    <span className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      <Thermometer className="w-4 h-4" />
                    </span>
                    Climate Control & 2-Stage Fan Thresholds
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                    MD02 Sensor
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                  <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">TEMP MIN (°C)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["TEMP MIN"] ?? 22.0}
                      onChange={(e) => handleInputChange("TEMP MIN", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white font-mono font-bold outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition-all"
                    />
                  </div>

                  <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">TEMP MED (Stage 1 Fan °C)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["TEMP MED"] ?? 25.0}
                      onChange={(e) => handleInputChange("TEMP MED", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white font-mono font-bold outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition-all"
                    />
                  </div>

                  <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">TEMP MAX (Stage 2 Fan & Pad °C)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["TEMP MAX"] ?? 28.0}
                      onChange={(e) => handleInputChange("TEMP MAX", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white font-mono font-bold outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition-all"
                    />
                  </div>

                  <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">TEMP Hysteresis (°C)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["TEMP Hyst"] ?? 0.5}
                      onChange={(e) => handleInputChange("TEMP Hyst", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white font-mono font-bold outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition-all"
                    />
                  </div>

                  <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Pad Max Humi Cutoff (PAD H_Max %)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["PAD H_Max"] ?? 75.0}
                      onChange={(e) => handleInputChange("PAD H_Max", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white font-mono font-bold outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition-all"
                    />
                  </div>

                  <div className="flex flex-col gap-1.5 p-3 rounded-xl bg-slate-950/70 border border-slate-800/90">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Pad Safety Buffer (PAD Safety %)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["PAD Safety"] ?? 2.0}
                      onChange={(e) => handleInputChange("PAD Safety", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-2 text-sm text-white font-mono font-bold outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition-all"
                    />
                  </div>
                </div>
              </div>

              {/* Security Credentials Card */}
              <div className="rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 p-5 sm:p-6 space-y-4">
                <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
                  <div className="flex items-center gap-2 text-sm font-bold text-white">
                    <span className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      <ShieldCheck className="w-4 h-4" />
                    </span>
                    Two-User Security Access Credentials
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                    Auth PIN
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                  {/* Operator 1 */}
                  <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-2.5">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block">Operator 1</label>
                    <div>
                      <input
                        type="text"
                        value={setpoints["USER 1 Name"] ?? "Operator 1"}
                        onChange={(e) => handleInputChange("USER 1 Name", e.target.value)}
                        className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-1.5 text-xs text-white outline-none focus:border-emerald-500"
                        placeholder="Operator 1 Name"
                      />
                    </div>
                    <div className="relative">
                      <input
                        type={showPin1 ? "text" : "password"}
                        value={setpoints["USER 1 PASSWORD"] ?? "1111"}
                        onChange={(e) => handleInputChange("USER 1 PASSWORD", e.target.value)}
                        className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-1.5 pr-8 text-xs text-white font-mono outline-none focus:border-emerald-500"
                        placeholder="PIN (e.g. 1111)"
                      />
                      <button
                        type="button"
                        onClick={() => setShowPin1(!showPin1)}
                        className="absolute right-2.5 top-2 text-slate-500 hover:text-white"
                      >
                        {showPin1 ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                      </button>
                    </div>
                  </div>

                  {/* Operator 2 */}
                  <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-2.5">
                    <label className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block">Operator 2</label>
                    <div>
                      <input
                        type="text"
                        value={setpoints["USER 2 Name"] ?? "Operator 2"}
                        onChange={(e) => handleInputChange("USER 2 Name", e.target.value)}
                        className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-1.5 text-xs text-white outline-none focus:border-emerald-500"
                        placeholder="Operator 2 Name"
                      />
                    </div>
                    <div className="relative">
                      <input
                        type={showPin2 ? "text" : "password"}
                        value={setpoints["USER 2 PASSWORD"] ?? "2222"}
                        onChange={(e) => handleInputChange("USER 2 PASSWORD", e.target.value)}
                        className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-1.5 pr-8 text-xs text-white font-mono outline-none focus:border-emerald-500"
                        placeholder="PIN (e.g. 2222)"
                      />
                      <button
                        type="button"
                        onClick={() => setShowPin2(!showPin2)}
                        className="absolute right-2.5 top-2 text-slate-500 hover:text-white"
                      >
                        {showPin2 ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* ── EQUIPMENT CYCLIC TIMERS CONFIGURATION (ALL 6 TIMERS) ── */}
          <div className="rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 p-5 sm:p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2 text-sm font-bold text-white">
                <span className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  <Clock className="w-4 h-4" />
                </span>
                Equipment Cyclic Timers Configuration (All 6 Timers)
              </div>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                6 Equipment Channels
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {equipmentTimersConfig.map((timer) => {
                const IconComponent = timer.icon;
                return (
                  <div key={timer.prefix} className="p-4 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-3 shadow-sm hover:border-slate-700 transition-colors">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
                      <div className="flex items-center gap-2">
                        <IconComponent className="h-4 w-4 text-emerald-400 shrink-0" />
                        <span className="text-xs font-bold text-white">{timer.title}</span>
                      </div>
                      <span className="text-[10px] font-mono text-slate-500">{timer.prefix}</span>
                    </div>

                    <div className="space-y-1">
                      <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Timer Label Name</label>
                      <input
                        type="text"
                        value={setpoints[timer.nameKey] ?? timer.defaultName}
                        onChange={(e) => handleInputChange(timer.nameKey, e.target.value)}
                        className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-3 py-1.5 text-xs text-emerald-400 font-bold outline-none focus:border-emerald-500"
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-2.5 text-xs pt-1">
                      <div>
                        <label className="text-[11px] font-medium text-slate-400 block mb-1">Start Time</label>
                        <input
                          type="text"
                          value={setpoints[timer.startKey] ?? timer.defaultStart}
                          onChange={(e) => handleInputChange(timer.startKey, e.target.value)}
                          className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-2.5 py-1.5 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-medium text-slate-400 block mb-1">Stop Time</label>
                        <input
                          type="text"
                          value={setpoints[timer.stopKey] ?? timer.defaultStop}
                          onChange={(e) => handleInputChange(timer.stopKey, e.target.value)}
                          className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-2.5 py-1.5 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-medium text-slate-400 block mb-1">ON (min)</label>
                        <input
                          type="number"
                          value={setpoints[timer.onKey] ?? timer.defaultOn}
                          onChange={(e) => handleInputChange(timer.onKey, parseFloat(e.target.value) || 0)}
                          className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-2.5 py-1.5 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-medium text-slate-400 block mb-1">OFF (min)</label>
                        <input
                          type="number"
                          value={setpoints[timer.offKey] ?? timer.defaultOff}
                          onChange={(e) => handleInputChange(timer.offKey, parseFloat(e.target.value) || 0)}
                          className="w-full rounded-xl border border-slate-700/80 bg-slate-900 px-2.5 py-1.5 text-xs text-white font-mono text-center outline-none focus:border-emerald-500"
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Bottom Prominent Save Button */}
          <div className="flex justify-end pt-2">
            <button
              onClick={handleSaveSetpoints}
              disabled={!selectedDevice || saveSuccess}
              className="flex items-center gap-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 px-6 py-3 text-sm font-bold text-slate-950 shadow-lg shadow-emerald-500/20 active:scale-95 disabled:opacity-50 transition-all"
            >
              {saveSuccess ? (
                <>
                  <CheckCircle2 className="h-4 w-4" />
                  <span>Setpoints Pushed Successfully!</span>
                </>
              ) : (
                <>
                  <Save className="h-4 w-4" />
                  <span>Save & Push Monnet Setpoints</span>
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* ── SECTION 2: DEVICE CONTROLLER & LIVE MONITOR DASHBOARD ── */}
      {viewMode === 'monitoring' && (
        <div className="space-y-6 animate-in fade-in duration-200">
          {/* Top Live Sensor Metrics Banner */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5">
            {/* Water EC */}
            <div className="p-4 rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-md flex flex-col justify-between">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Water EC</span>
                <Droplets className="h-4 w-4 text-emerald-400" />
              </div>
              <div className="mt-2">
                <span className={`text-xl sm:text-2xl font-black font-mono ${ecVal !== null ? 'text-emerald-400' : 'text-slate-500'}`}>
                  {ecVal !== null ? ecVal.toFixed(2) : '--'}
                </span>
                <span className="text-[11px] text-slate-400 ml-1">mS/cm</span>
              </div>
            </div>

            {/* Water pH */}
            <div className="p-4 rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-md flex flex-col justify-between">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Water pH</span>
                <FlaskConical className="h-4 w-4 text-emerald-400" />
              </div>
              <div className="mt-2">
                <span className={`text-xl sm:text-2xl font-black font-mono ${isMachineOnline && liveData?.ph != null && Number(liveData.ph) > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
                  {isMachineOnline && liveData?.ph != null && Number(liveData.ph) > 0 ? Number(liveData.ph).toFixed(2) : '--'}
                </span>
                <span className="text-[11px] text-slate-400 ml-1">pH</span>
              </div>
            </div>

            {/* Calculated TDS */}
            <div className="p-4 rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-md flex flex-col justify-between">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Calc TDS</span>
                <Zap className="h-4 w-4 text-emerald-400" />
              </div>
              <div className="mt-2">
                <span className={`text-xl sm:text-2xl font-black font-mono ${tdsPpm !== null ? 'text-white' : 'text-slate-500'}`}>
                  {tdsPpm !== null ? tdsPpm : '--'}
                </span>
                <span className="text-[11px] text-slate-400 ml-1">PPM</span>
              </div>
            </div>

            {/* Room Temperature */}
            <div className="p-4 rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-md flex flex-col justify-between">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Room Temp</span>
                <Thermometer className="h-4 w-4 text-emerald-400" />
              </div>
              <div className="mt-2">
                <span className={`text-xl sm:text-2xl font-black font-mono ${isMachineOnline && liveData?.room_temp != null && Number(liveData.room_temp) > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
                  {isMachineOnline && liveData?.room_temp != null && Number(liveData.room_temp) > 0 ? Number(liveData.room_temp).toFixed(1) : '--'}
                </span>
                <span className="text-[11px] text-slate-400 ml-1">°C</span>
              </div>
            </div>

            {/* Room Humidity */}
            <div className="p-4 rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-md flex flex-col justify-between col-span-2 sm:col-span-1">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Room Humidity</span>
                <Droplets className="h-4 w-4 text-emerald-400" />
              </div>
              <div className="mt-2">
                <span className={`text-xl sm:text-2xl font-black font-mono ${isMachineOnline && liveData?.room_humi != null && Number(liveData.room_humi) > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
                  {isMachineOnline && liveData?.room_humi != null && Number(liveData.room_humi) > 0 ? Number(liveData.room_humi).toFixed(1) : '--'}
                </span>
                <span className="text-[11px] text-slate-400 ml-1">%</span>
              </div>
            </div>
          </div>

          {/* ALL 13 MODBUS RELAYS OUTPUT DASHBOARD */}
          <div className="rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 p-5 sm:p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2 text-sm font-bold text-white">
                <span className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  <Activity className="w-4 h-4" />
                </span>
                Modbus RTU Relay Channels (13 Relays)
              </div>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                Slave ID: 1
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3.5">
              {relaysList.map((relay) => {
                const RelayIcon = relay.icon;
                const isRelayOn = isMachineOnline && liveData ? Boolean(liveData[relay.key]) : false;
                return (
                  <div
                    key={relay.key}
                    className={`p-3.5 rounded-xl border transition-all flex flex-col justify-between gap-2.5 ${isRelayOn
                      ? 'bg-emerald-500/10 border-emerald-500/30 text-white ring-1 ring-emerald-500/20 shadow-md shadow-emerald-950/20'
                      : 'bg-slate-950/70 border-slate-800/90 text-slate-400'
                      }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2.5">
                        <div className={`p-2 rounded-xl ${isRelayOn ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-900 text-slate-500'}`}>
                          <RelayIcon className="w-4 h-4" />
                        </div>
                        <span className="text-xs font-bold text-white truncate">{relay.name}</span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-slate-800">
                      <span className="text-[10px] font-mono text-slate-500">{relay.key}</span>
                      <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold flex items-center gap-1.5 ${isRelayOn
                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                        : 'bg-slate-900 text-slate-500 border border-slate-800'
                        }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${isRelayOn ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
                        {isRelayOn ? 'ACTIVE' : 'OFF'}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* LIVE EQUIPMENT TIMERS STATUS SUMMARY GRID */}
          <div className="rounded-2xl bg-slate-900/80 backdrop-blur-sm border border-slate-800 shadow-lg shadow-black/20 p-5 sm:p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
              <div className="flex items-center gap-2 text-sm font-bold text-white">
                <span className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  <Clock className="w-4 h-4" />
                </span>
                Live Equipment Timers Status
              </div>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                7 Cyclic Programs
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3.5 text-xs">
              {/* Fogger Humidifier Timer Summary */}
              <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-2">
                <div className="flex justify-between items-center">
                  <span className="font-bold text-white text-xs">{setpoints["HUMI Name"] || "FOGGER TIMER"}</span>
                  <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${isMachineOnline && (liveData?.relay_fogger || liveData?.relay_humi)
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                    : 'bg-slate-900 text-slate-500 border border-slate-800'
                    }`}>
                    {isMachineOnline && (liveData?.relay_fogger || liveData?.relay_humi) ? 'ACTIVE' : 'OFF'}
                  </span>
                </div>
                <div className="text-[11px] text-slate-400 font-mono flex justify-between">
                  <span>Day Cycle:</span>
                  <span className="text-slate-200">{setpoints["HUMI D_ON Min"] || 10}m ON / {setpoints["HUMI D_OFF Min"] || 20}m OFF</span>
                </div>
                <div className="text-[11px] text-slate-400 font-mono flex justify-between">
                  <span>Night Cycle:</span>
                  <span className="text-slate-200">{setpoints["HUMI N_ON Min"] || 5}m ON / {setpoints["HUMI N_OFF Min"] || 40}m OFF</span>
                </div>
              </div>

              {/* 6 Equipment Timers Summary */}
              {equipmentTimersConfig.map(t => {
                const isTimerActive = isMachineOnline && liveData ? Boolean(liveData[t.relayKey]) : false;
                const timerName = setpoints[t.nameKey] || t.defaultName;
                const startTime = setpoints[t.startKey] || t.defaultStart;
                const stopTime = setpoints[t.stopKey] || t.defaultStop;
                const onMin = setpoints[t.onKey] || t.defaultOn;
                const offMin = setpoints[t.offKey] || t.defaultOff;

                return (
                  <div key={t.prefix} className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-2">
                    <div className="flex justify-between items-center">
                      <span className="font-bold text-white text-xs truncate max-w-[140px]">{timerName}</span>
                      <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${isTimerActive
                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                        : 'bg-slate-900 text-slate-500 border border-slate-800'
                        }`}>
                        {isTimerActive ? 'ACTIVE' : 'OFF'}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-400 font-mono flex justify-between">
                      <span>Window:</span>
                      <span className="text-slate-200">{startTime} - {stopTime}</span>
                    </div>
                    <div className="text-[11px] text-slate-400 font-mono flex justify-between">
                      <span>Interval:</span>
                      <span className="text-emerald-400">{onMin}m ON / {offMin}m OFF</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MonitSettings;
