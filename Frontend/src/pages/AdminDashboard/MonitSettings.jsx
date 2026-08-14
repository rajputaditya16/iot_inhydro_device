import { useState, useEffect } from 'react';
import { 
  Save, CheckCircle2, RefreshCw, ChevronDown, Server, 
  Thermometer, Droplets, Zap, Clock, ShieldCheck, Activity, Sliders, 
  Power, FlaskConical, AlertCircle, Wind, Fan, RotateCw, Edit3
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

const MonitSettings = () => {
  const [viewMode, setViewMode] = useState('setpoints'); // 'setpoints' | 'monitoring'
  const [monitDevices, setMonitDevices] = useState([]);
  const [deviceRoot, setDeviceRoot] = useState('');
  const [setpoints, setSetpoints] = useState(defaultSetpoints);
  const [status, setStatus] = useState('disconnected');
  const [loading, setLoading] = useState(true);
  const [client, setClient] = useState(null);
  const [liveData, setLiveData] = useState(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [toast, setToast] = useState({ show: false, type: 'success', message: '' });
  const [isEditingName, setIsEditingName] = useState(false);
  const [tempName, setTempName] = useState('');

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
          const filtered = data.data.filter(d => d.deviceType === 'monit' || d.deviceType === 'monnet' || d.deviceType === 'monit_device' || d.deviceType === 'dosing');
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
      mqttClient.publish(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');
    });

    const handleIncomingPacket = (topic, messageData) => {
      if (topic === `inhydro/${deviceRoot}/telemetry/live` || topic === `inhydro/${deviceRoot}/room1/telemetry/live` || topic?.includes('/telemetry/live')) {
        try {
          const parsed = typeof messageData === 'string' ? JSON.parse(messageData) : messageData;
          const payload = Array.isArray(parsed) ? parsed[parsed.length - 1] : parsed;
          setLiveData(payload);
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
      } catch (e) {}
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
          showToast('success', `Setpoints pushed to device "${selectedDevice?.name || deviceRoot}" successfully via Private Broker!`);
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

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20">
        <RefreshCw className="h-8 w-8 animate-spin text-green-500" />
      </div>
    );
  }

  if (monitDevices.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20 p-8 text-center">
        <Server className="mb-4 h-12 w-12 text-slate-600" />
        <h3 className="text-lg font-semibold text-white">No Monnet Controllers Found</h3>
        <p className="mt-2 text-sm text-slate-400">Please register a device with type <code className="text-green-400 bg-slate-800 px-2 py-0.5 rounded">monit</code> on the Devices page first.</p>
      </div>
    );
  }

  const ecVal = Number(liveData?.ec !== undefined ? liveData.ec : null);
  const tdsPpm = Number.isFinite(ecVal) && ecVal > 0 ? Math.round(ecVal * 500) : null;

  // List of all 13 relays according to monit.py
  const relaysList = [
    { key: 'relay_ec1', name: 'EC1 Dosing Pump', icon: Zap },
    { key: 'relay_ec2', name: 'EC2 Dosing Pump', icon: Zap },
    { key: 'relay_ph', name: 'pH Minus Dosing Pump', icon: FlaskConical },
    { key: 'relay_solenoid', name: 'S-Tank Solenoid Valve', icon: RotateCw },
    { key: 'relay_fan1', name: 'Stage 1 Fan 1 (Fan 1st 50%)', icon: Fan },
    { key: 'relay_fan2', name: 'Stage 2 Fan 2 (Fan 2nd 50%)', icon: Fan },
    { key: 'relay_pad', name: 'Cooling Pad Pump', icon: Droplets },
    { key: 'relay_fogger', name: 'Fogger Humidifier', icon: Wind },
    { key: 'relay_acf', name: 'Air Circulation Fan (ACF)', icon: Fan },
    { key: 'relay_sprinkler', name: 'Overhead Sprinkler', icon: Droplets },
    { key: 'relay_irrigation', name: 'Daytime Irrigation Pump', icon: RotateCw },
    { key: 'timer1', name: 'Cyclic Timer 1 (Water Mixing)', icon: Clock },
    { key: 'timer2', name: 'Cyclic Timer 2', icon: Clock },
  ];

  // List of equipment cyclic timers according to monit.py
  const equipmentTimersConfig = [
    {
      title: "Cooling Pad Pump (PAD)",
      prefix: "PAD",
      nameKey: "PAD Name", defaultName: "COOLING PAD PUMP",
      startKey: "PAD Start", defaultStart: "06:00",
      stopKey: "PAD Stop", defaultStop: "18:00",
      onKey: "PAD ON Min", defaultOn: 5,
      offKey: "PAD OFF Min", defaultOff: 15,
      relayKey: "relay_pad"
    },
    {
      title: "Air Circulation Fan (ACF)",
      prefix: "ACF",
      nameKey: "ACF Name", defaultName: "AIR CIRCULATION FAN",
      startKey: "ACF Start", defaultStart: "06:00",
      stopKey: "ACF Stop", defaultStop: "22:00",
      onKey: "ACF ON Min", defaultOn: 10,
      offKey: "ACF OFF Min", defaultOff: 20,
      relayKey: "relay_acf"
    },
    {
      title: "Overhead Sprinkler",
      prefix: "Sprinkler",
      nameKey: "Sprinkler Name", defaultName: "SPRINKLER",
      startKey: "Sprinkler Start", defaultStart: "08:00",
      stopKey: "Sprinkler Stop", defaultStop: "17:00",
      onKey: "Sprinkler ON Min", defaultOn: 2,
      offKey: "Sprinkler OFF Min", defaultOff: 30,
      relayKey: "relay_sprinkler"
    },
    {
      title: "Daytime Irrigation",
      prefix: "Irrigation",
      nameKey: "Irrigation Name", defaultName: "IRRIGATION",
      startKey: "Irrigation Start", defaultStart: "06:00",
      stopKey: "Irrigation Stop", defaultStop: "18:00",
      onKey: "Irrigation ON Min", defaultOn: 15,
      offKey: "Irrigation OFF Min", defaultOff: 45,
      relayKey: "relay_irrigation"
    },
    {
      title: "Cyclic Timer 1",
      prefix: "Timer1",
      nameKey: "Timer1 Name", defaultName: "WATER MIXING PUMP",
      startKey: "Timer1 Start", defaultStart: "06:00",
      stopKey: "Timer1 Stop", defaultStop: "18:00",
      onKey: "Timer1 ON Min", defaultOn: 5,
      offKey: "Timer1 OFF Min", defaultOff: 15,
      relayKey: "timer1"
    },
    {
      title: "Cyclic Timer 2",
      prefix: "Timer2",
      nameKey: "Timer2 Name", defaultName: "CYCLIC TIMER 2",
      startKey: "Timer2 Start", defaultStart: "00:00",
      stopKey: "Timer2 Stop", defaultStop: "23:59",
      onKey: "Timer2 ON Min", defaultOn: 10,
      offKey: "Timer2 OFF Min", defaultOff: 20,
      relayKey: "timer2"
    },
  ];

  return (
    <div className="space-y-6">
      {/* Toast Notification Popup */}
      {toast.show && (
        <div className={`fixed top-6 right-6 z-50 flex items-center gap-3 rounded-xl border px-4 py-3 shadow-2xl backdrop-blur-md transition-all duration-300 max-w-sm ${toast.type === 'success'
          ? 'border-emerald-500/30 bg-slate-900/95 text-emerald-400 shadow-emerald-950/20'
          : 'border-red-500/30 bg-slate-900/95 text-red-400 shadow-red-950/20'
          }`}>
          {toast.type === 'success' ? (
            <CheckCircle2 className="h-5 w-5 shrink-0 animate-pulse" />
          ) : (
            <AlertCircle className="h-5 w-5 shrink-0 animate-pulse" />
          )}
          <div className="flex flex-col">
            <span className="text-sm font-semibold text-white">
              {toast.type === 'success' ? 'Success' : 'Error'}
            </span>
            <span className="text-xs text-slate-300">{toast.message}</span>
          </div>
        </div>
      )}

      {/* Top Header Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            {isEditingName ? (
              <div className="flex items-center gap-2">
                <input
                  autoFocus
                  type="text"
                  value={tempName}
                  onChange={(e) => setTempName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleNameSave()}
                  className="rounded border border-green-500 bg-slate-900/50 px-2 py-0.5 text-base font-semibold text-white outline-none"
                />
                <button onClick={handleNameSave} className="rounded bg-green-500/20 px-2 py-1 text-xs font-semibold text-green-400 hover:bg-green-500/30 transition-all">Save</button>
              </div>
            ) : (
              <h3 className="flex items-center gap-2 text-base font-semibold text-white">
                {selectedDevice?.name || 'Monnet Device'}
                <button onClick={() => setIsEditingName(true)} className="text-slate-500 transition hover:text-green-400" title="Rename Machine">
                  <Edit3 className="h-4 w-4" />
                </button>
              </h3>
            )}
          </div>
          <p className="text-sm text-slate-400 mt-1">Configure Monnet Farm Automation Setpoints & Live Telemetry</p>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          {/* Device Selector */}
          <div className="relative">
            <button
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              className={`flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium text-white outline-none transition-all ${isDropdownOpen ? 'border-green-500 bg-slate-800' : 'border-slate-700 bg-slate-900/50 hover:border-green-500 hover:bg-slate-800'}`}
            >
              <Server className="h-4 w-4 text-green-400" />
              <span className="max-w-[150px] truncate">{selectedDevice?.name || 'Select Device'}</span>
              <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform duration-200 ${isDropdownOpen ? 'rotate-180' : ''}`} />
            </button>

            {isDropdownOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setIsDropdownOpen(false)}></div>
                <div className="absolute right-0 top-full z-50 mt-2 flex w-56 flex-col overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-xl">
                  {monitDevices.map((d) => {
                    const rootKey = d.mqttId || d._id;
                    return (
                      <button
                        key={d._id}
                        onClick={() => {
                          setDeviceRoot(rootKey);
                          setIsDropdownOpen(false);
                        }}
                        className={`flex items-center w-full justify-between px-4 py-3 text-sm transition-colors hover:bg-slate-800 ${deviceRoot === rootKey ? 'bg-green-500/10 text-green-400 font-semibold' : 'text-slate-300'}`}
                      >
                        <span className="truncate">{d.name}</span>
                        <span className={`h-1.5 w-1.5 rounded-full ${d.status === 'online' ? 'bg-emerald-400' : 'bg-slate-500'}`} />
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          <button
            onClick={handleSyncRequest}
            title="Request setpoints sync from device"
            className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2.5 text-xs font-medium text-slate-300 hover:border-green-500 hover:text-white transition-all"
          >
            <RefreshCw className="h-4 w-4 text-slate-400" /> Sync Device
          </button>

          {/* Broker Status Badge */}
          <div className="min-w-[140px] flex justify-end">
            {status === 'connected' && (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" /> Connected
              </span>
            )}
            {status !== 'connected' && status !== 'error' && (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-500">
                <span className="h-2 w-2 rounded-full bg-slate-600" /> Not Connected
              </span>
            )}
            {status === 'error' && (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-red-400">
                <AlertCircle className="h-4 w-4" /> Connection Error
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Mode Tabs */}
      <div className="flex border-b border-slate-700">
        <button
          onClick={() => setViewMode('setpoints')}
          className={`flex-1 py-3 text-sm font-semibold transition-colors flex items-center justify-center gap-2 ${viewMode === 'setpoints' ? 'border-b-2 border-green-500 text-green-400' : 'text-slate-400 hover:text-white'}`}
        >
          <Sliders className="w-4 h-4" /> Setpoints Setup
        </button>
        <button
          onClick={() => setViewMode('monitoring')}
          className={`flex-1 py-3 text-sm font-semibold transition-colors flex items-center justify-center gap-2 ${viewMode === 'monitoring' ? 'border-b-2 border-green-500 text-green-400' : 'text-slate-400 hover:text-white'}`}
        >
          <Activity className="w-4 h-4" /> Live Monitor
        </button>
      </div>

      {/* SECTION 1: SYSTEM SETPOINTS CONFIGURATION */}
      {viewMode === 'setpoints' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            
            {/* LEFT COLUMN: NUTRIENTS & PH + FOGGER HUMIDIFIER DAY/NIGHT */}
            <div className="space-y-6">
              {/* Nutrients & pH Limits Card */}
              <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4">
                <h4 className="text-sm font-semibold text-green-400 flex items-center gap-2 border-b border-slate-700/50 pb-3">
                  <Zap className="w-4 h-4" /> Nutrients & pH Threshold Limits
                </h4>

                <div className="grid grid-cols-2 gap-4">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">EC MIN (mS/cm)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["EC MIN"] ?? 1.2}
                      onChange={(e) => handleInputChange("EC MIN", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">EC MAX (mS/cm)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["EC MAX"] ?? 1.8}
                      onChange={(e) => handleInputChange("EC MAX", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">pH LOW Limit</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["PH LOW"] ?? 5.8}
                      onChange={(e) => handleInputChange("PH LOW", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">pH HIGH Limit</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["PH HIGH"] ?? 6.5}
                      onChange={(e) => handleInputChange("PH HIGH", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>

                  <div className="col-span-2 flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">S-TANK Solenoid Threshold (mS/cm)</label>
                    <input
                      type="number"
                      step="0.05"
                      value={setpoints["S_TANK"] ?? 0.45}
                      onChange={(e) => handleInputChange("S_TANK", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm font-bold outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>
                </div>
              </div>

              {/* Fogger Day/Night Cycle Table Card */}
              <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4 overflow-x-auto">
                <h4 className="text-sm font-semibold text-green-400 flex items-center gap-2 border-b border-slate-700/50 pb-3">
                  <Wind className="w-4 h-4" /> Fogger Humidifier Day/Night Cycle
                </h4>

                <div className="flex justify-between items-center bg-slate-900/60 p-2.5 rounded-lg border border-slate-700/50">
                  <span className="text-xs font-semibold text-slate-300">Timer Label:</span>
                  <input
                    type="text"
                    value={setpoints["HUMI Name"] ?? "FOGGER TIMER"}
                    onChange={(e) => handleInputChange("HUMI Name", e.target.value)}
                    className="w-48 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white font-bold text-center outline-none focus:border-green-500"
                  />
                </div>

                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-slate-700/60 bg-slate-800/40">
                      <th className="py-2.5 px-3 text-left font-bold text-slate-400">Setting</th>
                      <th className="py-2.5 px-3 text-center font-bold  rounded-tl-lg">Day Cycle</th>
                      <th className="py-2.5 px-3 text-center font-bold rounded-tr-lg">Night Cycle</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    <tr>
                      <td className="py-2.5 px-3 font-semibold text-slate-300">Start Time:</td>
                      <td className="py-2 px-3">
                        <input
                          type="text"
                          value={setpoints["HUMI D_Start"] ?? "06:00"}
                          onChange={(e) => handleInputChange("HUMI D_Start", e.target.value)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="text"
                          value={setpoints["HUMI N_Start"] ?? "18:00"}
                          onChange={(e) => handleInputChange("HUMI N_Start", e.target.value)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold text-slate-300">Stop Time:</td>
                      <td className="py-2 px-3">
                        <input
                          type="text"
                          value={setpoints["HUMI D_Stop"] ?? "18:00"}
                          onChange={(e) => handleInputChange("HUMI D_Stop", e.target.value)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="text"
                          value={setpoints["HUMI N_Stop"] ?? "06:00"}
                          onChange={(e) => handleInputChange("HUMI N_Stop", e.target.value)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold text-slate-300">ON Duration (Min):</td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI D_ON Min"] ?? 10}
                          onChange={(e) => handleInputChange("HUMI D_ON Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs  font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI N_ON Min"] ?? 5}
                          onChange={(e) => handleInputChange("HUMI N_ON Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs  font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold text-slate-300">OFF Duration (Min):</td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI D_OFF Min"] ?? 20}
                          onChange={(e) => handleInputChange("HUMI D_OFF Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs  font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI N_OFF Min"] ?? 40}
                          onChange={(e) => handleInputChange("HUMI N_OFF Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs  font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold text-slate-300">Target Humidity Max (%):</td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI D_Max"] ?? 75.0}
                          onChange={(e) => handleInputChange("HUMI D_Max", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs  font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI N_Max"] ?? 80.0}
                          onChange={(e) => handleInputChange("HUMI N_Max", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs  font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold text-slate-300">Target Humidity Min (%):</td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI D_Min"] ?? 55.0}
                          onChange={(e) => handleInputChange("HUMI D_Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs  font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI N_Min"] ?? 60.0}
                          onChange={(e) => handleInputChange("HUMI N_Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs  font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* RIGHT COLUMN: CLIMATE CONTROL + USER CREDENTIALS */}
            <div className="space-y-6">
              {/* Climate Control Limits Card (Including TEMP MED and Hysteresis) */}
              <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4">
                <h4 className="text-sm font-semibold text-green-400 flex items-center gap-2 border-b border-slate-700/50 pb-3">
                  <Thermometer className="w-4 h-4" /> Climate Control & 2-Stage Fan Thresholds
                </h4>

                <div className="grid grid-cols-2 gap-4">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">TEMP MIN (°C)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["TEMP MIN"] ?? 22.0}
                      onChange={(e) => handleInputChange("TEMP MIN", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">TEMP MED (Stage 1 Fan 1 °C)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["TEMP MED"] ?? 25.0}
                      onChange={(e) => handleInputChange("TEMP MED", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2  font-bold outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">TEMP MAX (Stage 2 Fan 2 & Pad °C)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["TEMP MAX"] ?? 28.0}
                      onChange={(e) => handleInputChange("TEMP MAX", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm  font-bold outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">TEMP Hysteresis (°C)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["TEMP Hyst"] ?? 0.5}
                      onChange={(e) => handleInputChange("TEMP Hyst", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">Pad Max Humi Cutoff (PAD H_Max %)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["PAD H_Max"] ?? 75.0}
                      onChange={(e) => handleInputChange("PAD H_Max", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 px-3 py-2 text-sm font-bold outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">Pad Safety Buffer (PAD Safety %)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["PAD Safety"] ?? 2.0}
                      onChange={(e) => handleInputChange("PAD Safety", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm  font-bold outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>
                </div>
              </div>

              {/* Security Credentials Card */}
              <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4">
                <h4 className="text-sm font-semibold text-green-400 flex items-center gap-2 border-b border-slate-700/50 pb-3">
                  <ShieldCheck className="w-4 h-4" /> Two-User Security Access Credentials
                </h4>

                <div className="grid grid-cols-2 gap-4">
                  <div className="p-3 rounded-xl bg-slate-900/50 border border-slate-700/50 space-y-2">
                    <label className="text-[11px] font-bold text-slate-400 block">Operator 1</label>
                    <input
                      type="text"
                      value={setpoints["USER 1 Name"] ?? "Operator 1"}
                      onChange={(e) => handleInputChange("USER 1 Name", e.target.value)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white outline-none focus:border-green-500 mb-1"
                      placeholder="Name"
                    />
                    <input
                      type="password"
                      value={setpoints["USER 1 PASSWORD"] ?? "1111"}
                      onChange={(e) => handleInputChange("USER 1 PASSWORD", e.target.value)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white font-mono outline-none focus:border-green-500"
                      placeholder="PIN"
                    />
                  </div>

                  <div className="p-3 rounded-xl bg-slate-900/50 border border-slate-700/50 space-y-2">
                    <label className="text-[11px] font-bold text-slate-400 block">Operator 2</label>
                    <input
                      type="text"
                      value={setpoints["USER 2 Name"] ?? "Operator 2"}
                      onChange={(e) => handleInputChange("USER 2 Name", e.target.value)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white outline-none focus:border-green-500 mb-1"
                      placeholder="Name"
                    />
                    <input
                      type="password"
                      value={setpoints["USER 2 PASSWORD"] ?? "2222"}
                      onChange={(e) => handleInputChange("USER 2 PASSWORD", e.target.value)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white font-mono outline-none focus:border-green-500"
                      placeholder="PIN"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* FULL EQUIPMENT CYCLIC TIMERS CONFIGURATION (ALL 6 TIMERS MATCHING MONIT.PY) */}
          <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4 overflow-x-auto">
            <h4 className="text-sm font-semibold text-green-400 flex items-center gap-2 border-b border-slate-700/50 pb-3">
              <Clock className="w-4 h-4" /> Equipment Cyclic Timers Configuration (All 6 Timers)
            </h4>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {equipmentTimersConfig.map((timer) => (
                <div key={timer.prefix} className="p-4 rounded-xl bg-slate-900/60 border border-slate-700/60 space-y-3">
                  <div className="border-b border-slate-700/60 pb-2">
                    <span className="text-[10px] font-bold text-slate-400 block uppercase">Timer Label Name:</span>
                    <input
                      type="text"
                      value={setpoints[timer.nameKey] ?? timer.defaultName}
                      onChange={(e) => handleInputChange(timer.nameKey, e.target.value)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-green-400 font-bold outline-none focus:border-green-500"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <label className="text-[11px] font-medium text-slate-400">Start Time</label>
                      <input
                        type="text"
                        value={setpoints[timer.startKey] ?? timer.defaultStart}
                        onChange={(e) => handleInputChange(timer.startKey, e.target.value)}
                        className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-green-500"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-medium text-slate-400">Stop Time</label>
                      <input
                        type="text"
                        value={setpoints[timer.stopKey] ?? timer.defaultStop}
                        onChange={(e) => handleInputChange(timer.stopKey, e.target.value)}
                        className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-green-500"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-medium ">ON Min</label>
                      <input
                        type="number"
                        value={setpoints[timer.onKey] ?? timer.defaultOn}
                        onChange={(e) => handleInputChange(timer.onKey, parseFloat(e.target.value) || 0)}
                        className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs font-mono text-center outline-none focus:border-green-500"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-medium">OFF Min</label>
                      <input
                        type="number"
                        value={setpoints[timer.offKey] ?? timer.defaultOff}
                        onChange={(e) => handleInputChange(timer.offKey, parseFloat(e.target.value) || 0)}
                        className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs  font-mono text-center outline-none focus:border-green-500"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="pt-4">
            <button
              onClick={handleSaveSetpoints}
              disabled={!selectedDevice}
              className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 active:scale-95 disabled:opacity-50 hover:opacity-90 transition-all"
            >
              <Save className="h-4 w-4" /> Save & Push Monnet Setpoints
            </button>
          </div>
        </div>
      )}

      {/* SECTION 2: DEVICE CONTROLLER & MONITOR DASHBOARD */}
      {viewMode === 'monitoring' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

            {/* COLUMN 1: WATER SENSOR & ROOM SENSOR */}
            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-6">
              {/* Water Sensor */}
              <div>
                <h4 className="text-xs font-bold text-green-400 uppercase tracking-wider mb-3 flex items-center gap-2 border-b border-slate-700/50 pb-2">
                  <Droplets className="w-4 h-4" /> Water Sensors Data
                </h4>
                <div className="space-y-2.5 text-xs font-mono">
                  <div className="flex justify-between items-center py-1.5 px-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
                    <span className="text-slate-400">Water EC</span>
                    <span className={`font-bold ${liveData?.ec !== undefined ? 'text-emerald-400' : 'text-red-400'}`}>
                      {liveData?.ec !== undefined ? `${liveData.ec} mS/cm` : 'ERROR'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1.5 px-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
                    <span className="text-slate-400">Water pH</span>
                    <span className={`font-bold ${liveData?.ph !== undefined ? 'text-emerald-400' : 'text-red-400'}`}>
                      {liveData?.ph !== undefined ? `${liveData.ph} pH` : 'ERROR'}
                    </span>
                  </div>
                  {tdsPpm !== null && (
                    <div className="flex justify-between items-center py-1.5 px-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
                      <span className="text-slate-400">Calculated TDS</span>
                      <span className="font-bold ">{tdsPpm} PPM</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Room Sensor (MD02) */}
              <div>
                <h4 className="text-xs font-bold text-green-400 uppercase tracking-wider mb-3 flex items-center gap-2 border-b border-slate-700/50 pb-2">
                  <Thermometer className="w-4 h-4" /> Room Climate Sensor (MD02)
                </h4>
                <div className="space-y-2.5 text-xs font-mono">
                  <div className="flex justify-between items-center py-1.5 px-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
                    <span className="text-slate-400">Room Temp</span>
                    <span className={`font-bold ${liveData?.room_temp !== undefined && liveData.room_temp !== null ? 'text-emerald-400' : 'text-red-400'}`}>
                      {liveData?.room_temp !== undefined && liveData.room_temp !== null ? `${liveData.room_temp} °C` : 'ERROR'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1.5 px-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
                    <span className="text-slate-400">Room Humidity</span>
                    <span className={`font-bold ${liveData?.room_humi !== undefined && liveData.room_humi !== null ? 'text-emerald-400' : 'text-red-400'}`}>
                      {liveData?.room_humi !== undefined && liveData.room_humi !== null ? `${liveData.room_humi} %` : 'ERROR'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Telemetry Status Card */}
              {/* <div>
                <h4 className="text-xs font-bold text-green-400 uppercase tracking-wider mb-3 flex items-center gap-2 border-b border-slate-700/50 pb-2">
                  <Activity className="w-4 h-4" /> Telemetry Info
                </h4>
                <div className="space-y-2 text-xs">
                  <div className="p-2.5 rounded-lg bg-slate-900/50 border border-slate-700/40 font-mono">
                    <span className="text-slate-400 block text-[10px]">MQTT Topic:</span>
                    <span className="text-green-400 font-bold truncate block">inhydro/{deviceRoot}/telemetry/live</span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-slate-900/50 border border-slate-700/40 flex justify-between items-center">
                    <span className="text-slate-400 text-[11px]">Stream Status:</span>
                    <span className={`font-semibold text-xs flex items-center gap-1.5 ${liveData ? 'text-emerald-400' : ''}`}>
                      <span className={`w-2 h-2 rounded-full ${liveData ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
                      {liveData ? 'Live Telemetry' : 'Waiting...'}
                    </span>
                  </div>
                </div>
              </div> */}
            </div>

            {/* COLUMN 2 & 3: ALL 12 RELAYS OUTPUT DASHBOARD */}
            <div className="lg:col-span-2 rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-5">
              <h4 className="text-xs font-bold text-green-400 uppercase tracking-wider flex items-center justify-between border-b border-slate-700/50 pb-2">
                <span className="flex items-center gap-2"><Power className="w-4 h-4" /> All 12 Relay Output Status (Modbus RTU)</span>
                <span className="text-[11px] text-slate-400 font-normal">Slave ID: 1</span>
              </h4>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {relaysList.map((relay) => {
                  const RelayIcon = relay.icon;
                  const isRelayOn = liveData ? Boolean(liveData[relay.key]) : false;
                  return (
                    <div
                      key={relay.key}
                      className={`p-3 rounded-xl border transition-all flex flex-col justify-between gap-2 ${isRelayOn
                        ? 'bg-emerald-500/10 border-emerald-500/30 shadow-lg shadow-emerald-950/20'
                        : 'bg-slate-900/60 border-slate-700/50'}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <div className={`p-1.5 rounded-lg ${isRelayOn ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-800 text-slate-500'}`}>
                            <RelayIcon className="w-4 h-4" />
                          </div>
                          <span className="text-xs font-semibold text-white truncate">{relay.name}</span>
                        </div>
                      </div>

                      <div className="flex items-center justify-between pt-1 border-t border-slate-800">
                        <span className="text-[10px] font-mono text-slate-500">{relay.key}</span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold flex items-center gap-1.5 ${isRelayOn ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-slate-800 text-slate-400 border border-slate-700'}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${isRelayOn ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
                          {isRelayOn ? 'ACTIVE (ON)' : 'OFF'}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* LIVE EQUIPMENT TIMERS STATUS SUMMARY GRID */}
              <div className="pt-3 border-t border-slate-700/50 space-y-3">
                <h4 className="text-xs font-bold text-green-400 uppercase tracking-wider flex items-center gap-2">
                  <Clock className="w-4 h-4" /> Live Equipment Timers Summary
                </h4>

                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 text-xs">
                  {/* Fogger Humidifier Timer Summary */}
                  <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-700/50 space-y-1.5">
                    <div className="flex justify-between items-center">
                      <span className="font-bold text-white text-xs">{setpoints["HUMI Name"] || "FOGGER TIMER"}</span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${liveData?.relay_fogger || liveData?.relay_humi ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-800 text-slate-400'}`}>
                        {liveData?.relay_fogger || liveData?.relay_humi ? 'ON' : 'OFF'}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-400 font-mono flex justify-between">
                      <span>Day Cycle:</span>
                      <span className="">{setpoints["HUMI D_ON Min"] || 10}m ON / {setpoints["HUMI D_OFF Min"] || 20}m OFF</span>
                    </div>
                    <div className="text-[11px] text-slate-400 font-mono flex justify-between">
                      <span>Night Cycle:</span>
                      <span className="">{setpoints["HUMI N_ON Min"] || 5}m ON / {setpoints["HUMI N_OFF Min"] || 40}m OFF</span>
                    </div>
                  </div>

                  {/* 6 Equipment Timers Summary */}
                  {equipmentTimersConfig.map(t => {
                    const isTimerActive = liveData ? Boolean(liveData[t.relayKey]) : false;
                    const timerName = setpoints[t.nameKey] || t.defaultName;
                    const startTime = setpoints[t.startKey] || t.defaultStart;
                    const stopTime = setpoints[t.stopKey] || t.defaultStop;
                    const onMin = setpoints[t.onKey] || t.defaultOn;
                    const offMin = setpoints[t.offKey] || t.defaultOff;

                    return (
                      <div key={t.prefix} className="p-3 rounded-xl bg-slate-900/60 border border-slate-700/50 space-y-1.5">
                        <div className="flex justify-between items-center">
                          <span className="font-bold text-white text-xs truncate max-w-[130px]">{timerName}</span>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${isTimerActive ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-800 text-slate-400'}`}>
                            {isTimerActive ? 'ON' : 'OFF'}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-400 font-mono flex justify-between">
                          <span>Window:</span>
                          <span className="text-slate-200">{startTime} - {stopTime}</span>
                        </div>
                        <div className="text-[11px] text-slate-400 font-mono flex justify-between">
                          <span>Cycle:</span>
                          <span className="text-emerald-400">{onMin}m ON / {offMin}m OFF</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

            </div>

          </div>
        </div>
      )}
    </div>
  );
};

export default MonitSettings;
