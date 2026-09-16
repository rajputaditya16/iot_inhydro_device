import { useState, useEffect } from 'react';
import { Save, AlertCircle, CheckCircle2, RefreshCw, ChevronDown, Server, Edit3, Sliders, ShieldCheck, Sprout, Layers } from 'lucide-react';
import { createMqttClient } from '../../utils/mqtt';

const defaultSetpoints = {
  "Crop Name": "Greenhouse Crop",
  "Setup Name": "Almora Climate Node Setup",
  "T MIN": 10.0,
  "T MAX": 30.0,
  "H MIN": 30.0,
  "H MAX": 80.0
};

const InputRow = ({ label, objKey, type = "number", data, onChange }) => (
  <div className="flex flex-col gap-1">
    <label className="text-xs font-medium text-slate-400">{label}</label>
    <input
      type={type}
      value={data[objKey] ?? ""}
      onChange={(e) => onChange(objKey, e.target.value)}
      className="w-full rounded-lg border border-slate-700 bg-slate-900/50 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
    />
  </div>
);

const Almora2Settings = () => {
  const [almoraDevices, setAlmoraDevices] = useState([]);
  const [deviceRoot, setDeviceRoot] = useState('');
  const [setpoints, setSetpoints] = useState(defaultSetpoints);
  const [status, setStatus] = useState('disconnected');
  const [loading, setLoading] = useState(true);
  const [client, setClient] = useState(null);
  const [liveData, setLiveData] = useState(null);
  const [machineOnline, setMachineOnline] = useState(false);

  const [isEditingName, setIsEditingName] = useState(false);
  const [tempName, setTempName] = useState('');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // Fetch Almora 2 (CO2 / Environmental) devices from database
  useEffect(() => {
    const fetchAlmoraDevices = async () => {
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
          const filtered = data.data.filter(d => d.deviceType === 'almora2');
          setAlmoraDevices(filtered);
          if (filtered.length > 0 && !deviceRoot) {
            setDeviceRoot(filtered[0].mqttId || filtered[0]._id);
          }
        }
      } catch (err) {
        console.error('Failed to fetch Almora 2 devices', err);
      } finally {
        setLoading(false);
      }
    };
    fetchAlmoraDevices();
  }, [token]);

  const selectedDevice = almoraDevices.find(d => (d.mqttId || d._id) === deviceRoot);

  useEffect(() => {
    setTempName(selectedDevice?.name || 'Unknown Almora 2');
    setMachineOnline(selectedDevice?.status === 'online');
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
        setAlmoraDevices(prev => prev.map(d => d._id === selectedDevice._id ? { ...d, name: tempName } : d));
        setIsEditingName(false);
      }
    } catch (err) {
      console.error('Failed to update name', err);
    }
  };

  useEffect(() => {
    if (!deviceRoot) return;
    setStatus('disconnected');
    const mqttClient = createMqttClient();

    const handleIncomingPacket = (topic, messageData) => {
      if (topic === `inhydro/${deviceRoot}/telemetry/live`) {
        try {
          const incoming = typeof messageData === 'string' ? JSON.parse(messageData) : messageData;
          setLiveData(incoming);
          setMachineOnline(true);
        } catch (err) {
          console.debug('Telemetry parse error:', err);
        }
      } else if (topic === `inhydro/${deviceRoot}/setpoints/current`) {
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

    mqttClient.on('connect', () => {
      console.log(`Connected to Private MQTT Broker for ${deviceRoot}`);
      setStatus('connected');

      mqttClient.subscribe(`inhydro/${deviceRoot}/setpoints/current`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/telemetry/live`);
      mqttClient.publish(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');
    });

    mqttClient.on('message', (topic, message) => {
      handleIncomingPacket(topic, message.toString());
    });

    mqttClient.on('error', () => {
      setStatus('error');
    });

    setClient(mqttClient);

    // Real-time SSE Stream Fallback (100% reliable over HTTPS cloud deployment)
    const sseUrl = `${API_BASE}/api/devices/stream?deviceId=${selectedDevice?._id || ''}&mqttId=${deviceRoot}`;
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
      } catch (err) {
        console.debug('SSE packet parse error:', err);
      }
    };

    return () => {
      if (mqttClient) {
        mqttClient.end();
      }
      eventSource.close();
    };
  }, [deviceRoot, selectedDevice, API_BASE]);

  const handleChange = (key, value) => {
    setSetpoints(prev => ({
      ...prev,
      [key]: value
    }));
  };

  const handleSave = async () => {
    setStatus('saving');

    const payload = { ...setpoints };
    const numericFields = ['T MIN', 'T MAX', 'H MIN', 'H MAX'];

    numericFields.forEach(field => {
      if (payload[field] !== undefined && payload[field] !== "") {
        const numValue = Number(payload[field]);
        payload[field] = isNaN(numValue) ? payload[field] : numValue;
      }
    });

    let published = false;

    // 1. Direct WebSocket MQTT Publish
    if (client && client.connected) {
      try {
        client.publish(`inhydro/${deviceRoot}/setpoints/update`, JSON.stringify(payload), { retain: true });
        published = true;
      } catch (e) {
        console.warn("Direct WebSocket publish failed, using backend push API:", e);
      }
    }

    // 2. Push via Backend Private Broker API (Reliable over HTTPS)
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
      if (data.success || published) {
        setStatus('saved');
        setTimeout(() => setStatus('connected'), 3000);
      } else {
        setStatus('error');
      }
    } catch (err) {
      if (published) {
        setStatus('saved');
        setTimeout(() => setStatus('connected'), 3000);
      } else {
        console.error("Save error:", err);
        setStatus('error');
      }
    }
  };

  const handleSyncRequest = async () => {
    if (!selectedDevice) return;
    if (client && client.connected) {
      client.publish(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');
    }
    try {
      await fetch(`${API_BASE}/api/devices/${selectedDevice._id}/push-config?action=sync`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        }
      });
    } catch (err) {
      console.debug('Sync request error:', err);
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20">
        <RefreshCw className="h-8 w-8 animate-spin text-green-500" />
      </div>
    );
  }

  if (almoraDevices.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20 p-8 text-center">
        <Server className="mb-4 h-12 w-12 text-slate-600" />
        <h3 className="text-lg font-semibold text-white">No Almora 2 Devices Found</h3>
        <p className="mt-2 text-sm text-slate-400">Please add an Almora 2 device from the "Devices" page first.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
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
                {selectedDevice?.name || 'Unknown Almora 2'}
                <button onClick={() => setIsEditingName(true)} className="text-slate-500 transition hover:text-green-400" title="Rename Machine">
                  <Edit3 className="h-4 w-4" />
                </button>
              </h3>
            )}
          </div>
          <p className="text-sm text-slate-400 mt-1">Manage Temperature, Humidity & CO2 Private Broker Setpoints</p>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          {/* Live Analytics Engine (Premium Display) */}
          {liveData && (
            <div className="flex items-center gap-2 overflow-hidden rounded-2xl border border-slate-700/50 bg-slate-900/40 p-1 shadow-2xl backdrop-blur-md">
              {(liveData.temp !== undefined || liveData.temperature !== undefined) && (
                <div className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-orange-500/10 to-transparent px-3 py-1.5 ring-1 ring-inset ring-orange-500/20">
                  <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-orange-400 shadow-orange-500/50 shadow-[0_0_8px_rgba(251,146,60,0.5)]"></div>
                  <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Temp</span>
                  <span className="text-sm font-black text-white">{liveData.temp ?? liveData.temperature ?? 0}<span className="text-[10px] text-orange-400 ml-0.5">°C</span></span>
                </div>
              )}

              {(liveData.hum !== undefined || liveData.humidity !== undefined) && (
                <div className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-blue-500/10 to-transparent px-3 py-1.5 ring-1 ring-inset ring-blue-500/20">
                  <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400 shadow-blue-500/50 shadow-[0_0_8px_rgba(96,165,250,0.5)]"></div>
                  <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Hum</span>
                  <span className="text-sm font-black text-white">{liveData.hum ?? liveData.humidity ?? 0}<span className="text-[10px] text-blue-400 ml-0.5">%</span></span>
                </div>
              )}

              {(liveData.co2 !== undefined || liveData.CO2 !== undefined) && (
                <div className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-emerald-500/10 to-transparent px-3 py-1.5 ring-1 ring-inset ring-emerald-500/20">
                  <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400 shadow-emerald-500/50 shadow-[0_0_8px_rgba(52,211,153,0.5)]"></div>
                  <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">CO2</span>
                  <span className="text-sm font-black text-white">{Math.round(liveData.co2 ?? liveData.CO2 ?? 0)}<span className="text-[10px] text-emerald-400 ml-1">PPM</span></span>
                </div>
              )}
            </div>
          )}

          {/* Selection Dropdown */}
          <div className="relative">
            <button
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              className={`flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium text-white outline-none transition-all ${isDropdownOpen ? 'border-green-500 bg-slate-800' : 'border-slate-700 bg-slate-900/50 hover:border-green-500 hover:bg-slate-800'}`}
            >
              <Server className="h-4 w-4 text-green-400" />
              <span className="max-w-[150px] truncate">{selectedDevice?.name || 'Select Almora 2 Node'}</span>
              <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform duration-200 ${isDropdownOpen ? 'rotate-180' : ''}`} />
            </button>

            {/* Dropdown Menu */}
            {isDropdownOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setIsDropdownOpen(false)}></div>
                <div className="absolute right-0 top-full z-50 mt-2 flex w-56 flex-col overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-xl">
                  {almoraDevices.map((dev) => (
                    <button
                      key={dev._id}
                      onClick={() => {
                        setDeviceRoot(dev.mqttId || dev._id);
                        setIsDropdownOpen(false);
                      }}
                      className={`flex items-center w-full justify-between px-4 py-3 text-sm transition-colors hover:bg-slate-800 ${deviceRoot === (dev.mqttId || dev._id) ? 'bg-green-500/10 text-green-400 font-semibold' : 'text-slate-300'
                        }`}
                    >
                      <span className="truncate">{dev.name}</span>
                      <span className={`h-1.5 w-1.5 rounded-full ${dev.status === 'online' ? 'bg-emerald-400' : 'bg-slate-500'}`} title={dev.status} />
                    </button>
                  ))}
                  {almoraDevices.length === 0 && (
                    <div className="px-4 py-3 text-sm text-slate-500 italic">No Almora 2 devices found</div>
                  )}
                </div>
              </>
            )}
          </div>

          {/* Differentiated Status Indicators: Broker vs Machine */}
          <div className="flex items-center gap-2.5">
            {/* Broker Status */}
            <div className="flex items-center gap-1.5 rounded-lg bg-slate-900/60 border border-slate-700/50 px-2.5 py-1 text-xs">
              <span className="text-slate-400">Broker:</span>
              {status === 'connected' ? (
                <span className="flex items-center gap-1 font-semibold text-emerald-400">
                  <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" /> Connected
                </span>
              ) : status === 'saving' ? (
                <span className="flex items-center gap-1 font-semibold text-green-400">
                  <RefreshCw className="h-3 w-3 animate-spin" /> Pushing...
                </span>
              ) : status === 'saved' ? (
                <span className="flex items-center gap-1 font-semibold text-emerald-400">
                  <CheckCircle2 className="h-3 w-3" /> Pushed
                </span>
              ) : status === 'error' ? (
                <span className="flex items-center gap-1 font-semibold text-red-400">
                  <AlertCircle className="h-3 w-3" /> Error
                </span>
              ) : (
                <span className="flex items-center gap-1 font-semibold text-slate-400">
                  <span className="h-2 w-2 rounded-full bg-slate-600" /> Connecting...
                </span>
              )}
            </div>

            {/* Machine Hardware Status */}
            <div className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold ${machineOnline
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                : 'border-slate-700/50 bg-slate-900/60 text-slate-400'
              }`}>
              <span className={`h-2 w-2 rounded-full ${machineOnline ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
              {machineOnline ? 'Machine Online' : 'Machine Offline'}
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-6">
        {/* Machine Offline Retained-Message Notice */}
        {!machineOnline && (
          <div className="flex items-center gap-2.5 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3.5 text-xs text-amber-300/90 shadow-sm">
            <AlertCircle className="h-4 w-4 shrink-0 text-amber-400" />
            <span>
              Physical machine <strong>"{selectedDevice?.name || deviceRoot}"</strong> is currently offline/standby. Any setpoints updated here will be <strong>retained on the Private Mosquitto Broker</strong> and automatically synced to the machine as soon as it powers on.
            </span>
          </div>
        )}

        {/* Core Environmental Limits */}
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4 pb-3 border-b border-slate-700/40">
            <h4 className="flex items-center gap-2 text-sm font-semibold text-green-400">
              <Sprout className="h-4 w-4 text-emerald-400" /> Core Environmental Limits ({setpoints["Crop Name"] || "Greenhouse"})
            </h4>
            <div className="flex flex-wrap items-center gap-2">
              <div className="w-44">
                <InputRow data={setpoints} onChange={handleChange} label="Target Crop Name" objKey="Crop Name" type="text" />
              </div>
              <div className="w-44">
                <InputRow data={setpoints} onChange={handleChange} label="Setup / System Name" objKey="Setup Name" type="text" />
              </div>
              <button
                onClick={handleSyncRequest}
                className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-medium text-slate-300 hover:border-green-500 hover:text-green-400 transition-colors mt-auto"
                title="Request active setpoints from physical edge machine"
              >
                <RefreshCw className="h-3.5 w-3.5" /> Sync from Machine
              </button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <InputRow data={setpoints} onChange={handleChange} label="T Minimum (°C)" objKey="T MIN" />
            <InputRow data={setpoints} onChange={handleChange} label="T Maximum (°C)" objKey="T MAX" />
            <InputRow data={setpoints} onChange={handleChange} label="H Minimum (%)" objKey="H MIN" />
            <InputRow data={setpoints} onChange={handleChange} label="H Maximum (%)" objKey="H MAX" />
          </div>
        </div>

        {/* Private Broker Active Routing Card */}
        {/* <div className="rounded-xl border border-slate-700/50 bg-slate-800/20 p-5 shadow-lg shadow-emerald-500/5 transition-all">
          <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold text-emerald-400">
            <ShieldCheck className="h-4 w-4" /> Private Broker & Edge Communication
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
              <span className="text-slate-500 block mb-1">Target Device Root</span>
              <span className="font-mono text-white font-semibold">{deviceRoot || 'N/A'}</span>
            </div>
            <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
              <span className="text-slate-500 block mb-1">Setpoints Channel</span>
              <span className="font-mono text-emerald-400">inhydro/{deviceRoot}/setpoints/update</span>
            </div>
            <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
              <span className="text-slate-500 block mb-1">Telemetry Channel</span>
              <span className="font-mono text-blue-400">inhydro/{deviceRoot}/telemetry/live</span>
            </div>
          </div>
        </div> */}
      </div>

      <div className="pt-4 flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={status === 'saving'}
          className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 transition-transform active:scale-95 disabled:opacity-50 cursor-pointer"
        >
          <Save className="h-4 w-4" /> Send Values to {deviceRoot.toUpperCase()}
        </button>
      </div>
    </div>
  );
};

export default Almora2Settings;
