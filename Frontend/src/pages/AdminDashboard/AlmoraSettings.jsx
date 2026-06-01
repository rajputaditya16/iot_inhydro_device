import { useState, useEffect } from 'react';
import { Save, AlertCircle, CheckCircle2, RefreshCw, ChevronDown, Server, Edit3, Radio } from 'lucide-react';
import mqtt from 'mqtt';

const defaultSetpoints = {
  "EC MIN": 1200,
  "EC MAX": 1800,
  "PH LOW": 5.8,
  "PH HIGH": 6.5
};

const InputRow = ({ label, objKey, type = "number", data, onChange }) => (
  <div className="flex flex-col gap-1">
    <label className="text-xs font-medium text-slate-400">{label}</label>
    <input
      type={type}
      value={data[objKey] || ""}
      onChange={(e) => onChange(objKey, e.target.value)}
      className="w-full rounded-lg border border-slate-700 bg-slate-900/50 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
    />
  </div>
);

const AlmoraSettings = () => {
  const [almoraDevices, setAlmoraDevices] = useState([]);
  const [deviceRoot, setDeviceRoot] = useState('');
  const [setpoints, setSetpoints] = useState(defaultSetpoints);
  const [status, setStatus] = useState('disconnected');
  const [loading, setLoading] = useState(true);
  const [client, setClient] = useState(null);
  const [liveData, setLiveData] = useState(null);

  const [isEditingName, setIsEditingName] = useState(false);
  const [tempName, setTempName] = useState('');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const token = localStorage.getItem('token');
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  const role = user.role === 'superadmin' ? 'superadmin' : (user.accountType || user.role || 'user');
  const isSuperadmin = role === 'superadmin';
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // Fetch Almora devices from database
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
          const filtered = data.data.filter(d => d.deviceType === 'almora');
          setAlmoraDevices(filtered);
          if (filtered.length > 0 && !deviceRoot) {
            setDeviceRoot(filtered[0].mqttId || filtered[0]._id);
          }
        }
      } catch (err) {
        console.error('Failed to fetch Almora devices', err);
      } finally {
        setLoading(false);
      }
    };
    fetchAlmoraDevices();
  }, [token]);

  const selectedDevice = almoraDevices.find(d => (d.mqttId || d._id) === deviceRoot);

  useEffect(() => {
    setTempName(selectedDevice?.name || 'Unknown Machine');
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
    const mqttClient = mqtt.connect('wss://broker.hivemq.com:8884/mqtt');

    // Merge database ThingSpeak config if it exists
    const initialSetpoints = { ...defaultSetpoints };
    if (isSuperadmin && selectedDevice && selectedDevice.thingspeak) {
      const ts = selectedDevice.thingspeak;
      if (ts.clientId) initialSetpoints["CLIENT ID"] = ts.clientId;
      if (ts.username) initialSetpoints["USERNAME"] = ts.username;
      if (ts.password) initialSetpoints["PASSWORD"] = ts.password;
      if (ts.channelId) initialSetpoints["CHANNEL ID"] = ts.channelId;
      if (ts.port) initialSetpoints["PORT"] = ts.port;
      if (ts.readApiKey) initialSetpoints["READ API KEY"] = ts.readApiKey;
      if (ts.writeApiKey) initialSetpoints["WRITE API KEY"] = ts.writeApiKey;
    }
    setSetpoints(initialSetpoints);

    mqttClient.on('connect', () => {
        console.log(`Connected to MQTT Cloud Broker for ${deviceRoot}`);
        setStatus('connected');
        
        mqttClient.subscribe(`inhydro/${deviceRoot}/setpoints/current`);
        mqttClient.subscribe(`inhydro/${deviceRoot}/telemetry/live`);
        mqttClient.publish(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');
    });

    mqttClient.on('message', (topic, message) => {
      if (topic === `inhydro/${deviceRoot}/telemetry/live`) {
        try {
          const incomingLiveData = JSON.parse(message.toString());
          setLiveData(incomingLiveData);
        } catch (e) {}
      }
      else if (topic === `inhydro/${deviceRoot}/setpoints/current`) {
        try {
          const incomingData = JSON.parse(message.toString());
          setSetpoints(prev => ({
            ...prev,
            ...incomingData
          }));
        } catch (error) {
          console.error("Error parsing current setpoints from device", error);
        }
      }
    });

    mqttClient.on('error', (err) => {
      setStatus('error');
    });

    setClient(mqttClient);

    return () => {
      if (mqttClient) {
        mqttClient.end();
      }
    };
  }, [deviceRoot, selectedDevice, isSuperadmin]); 

  const handleChange = (key, value) => {
    setSetpoints(prev => ({
      ...prev,
      [key]: value
    }));
  };

  const handleSave = () => {
    if (client && client.connected) {
      setStatus('saving');
      
      const payload = { ...setpoints };
      const numericFields = ['EC MIN', 'EC MAX', 'PH LOW', 'PH HIGH', 'PORT'];
                             
      numericFields.forEach(field => {
        if (payload[field] !== undefined && payload[field] !== "") {
          const numValue = Number(payload[field]);
          payload[field] = isNaN(numValue) ? payload[field] : numValue;
        }
      });

      if (!isSuperadmin) {
        delete payload["CLIENT ID"];
        delete payload["USERNAME"];
        delete payload["PASSWORD"];
        delete payload["CHANNEL ID"];
        delete payload["PORT"];
        delete payload["READ API KEY"];
        delete payload["WRITE API KEY"];
      }

      if (isSuperadmin) {
        const dbPayload = {
          thingspeak: {
            clientId: payload["CLIENT ID"],
            username: payload["USERNAME"],
            password: payload["PASSWORD"],
            channelId: payload["CHANNEL ID"],
            port: Number(payload["PORT"]),
            readApiKey: payload["READ API KEY"],
            writeApiKey: payload["WRITE API KEY"]
          }
        };

        fetch(`${API_BASE}/api/devices/${selectedDevice._id}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(dbPayload)
        }).catch(err => console.error("DB Sync error:", err));
      }

      client.publish(`inhydro/${deviceRoot}/setpoints/update`, JSON.stringify(payload), (err) => {
        if (err) {
          console.error(err);
          setStatus('error');
        } else {
          setStatus('saved');
          setTimeout(() => setStatus('connected'), 3000);
        }
      });
    } else {
      setStatus('error');
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
        <h3 className="text-lg font-semibold text-white">No Almora Devices Found</h3>
        <p className="mt-2 text-sm text-slate-400">Please add an Almora device from the "Devices" page first.</p>
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
                {selectedDevice?.name || 'Unknown Machine'}
                <button onClick={() => setIsEditingName(true)} className="text-slate-500 transition hover:text-green-400" title="Rename Machine">
                  <Edit3 className="h-4 w-4" />
                </button>
              </h3>
            )}
          </div>
          <p className="text-sm text-slate-400 mt-1">Manage Environment & ThingSpeak Integrations</p>
        </div>
        
        <div className="flex flex-wrap items-center gap-4">
            {/* Live Analytics Engine (Premium Display) */}
            {liveData && ( 
              <div className="flex items-center gap-2 overflow-hidden rounded-2xl border border-slate-700/50 bg-slate-900/40 p-1 shadow-2xl backdrop-blur-md">
                <div className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-green-500/10 to-transparent px-3 py-1.5 ring-1 ring-inset ring-green-500/20">
                  <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-400 shadow-green-500/50 shadow-[0_0_8px_rgba(34,197,94,0.5)]"></div>
                  <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">EC</span>
                  <span className="text-sm font-black text-white">{liveData.ec || liveData.EC || 0}<span className="text-[10px] text-green-400 ml-0.5">µS/cm</span></span>
                </div>
                
                <div className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-purple-500/10 to-transparent px-3 py-1.5 ring-1 ring-inset ring-purple-500/20">
                  <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-purple-400 shadow-purple-500/50 shadow-[0_0_8px_rgba(168,85,247,0.5)]"></div>
                  <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">pH</span>
                  <span className="text-sm font-black text-white">{liveData.ph || liveData.PH || 0}</span>
                </div>
              </div>
            )}

            {/* Custom Click dropdown (Dynamic) */}
            <div className="relative"> 
              <button 
                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                className={`flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium text-white outline-none transition-all ${isDropdownOpen ? 'border-green-500 bg-slate-800' : 'border-slate-700 bg-slate-900/50 hover:border-green-500 hover:bg-slate-800'}`}
              >
                <Server className="h-4 w-4 text-green-400" />
                <span className="max-w-[150px] truncate">{selectedDevice?.name || 'Select Almora Machine'}</span>
                <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform duration-200 ${isDropdownOpen ? 'rotate-180' : ''}`} />
              </button>
              
              {/* Dropdown Menu (Visible on Click) */}
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
                        className={`flex items-center w-full justify-start px-4 py-3 text-sm transition-colors hover:bg-slate-800 ${
                          deviceRoot === (dev.mqttId || dev._id) ? 'bg-green-500/10 text-green-400 font-semibold' : 'text-slate-300'
                        }`}
                      >
                        <span className="truncate">{dev.name}</span>
                      </button>
                    ))}
                    {almoraDevices.length === 0 && (
                      <div className="px-4 py-3 text-sm text-slate-500 italic">No Almora devices found</div>
                    )}
                  </div>
                </>
              )}
            </div>
            
            <div className="min-w-[140px] flex justify-end">
              {status === 'connected' && <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400"><CheckCircle2 className="h-4 w-4" /> Cloud Connected</span>}
              {status === 'disconnected' && <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-400"><RefreshCw className="h-4 w-4 animate-spin" /> Connecting...</span>}
              {status === 'saving' && <span className="flex items-center gap-1.5 text-xs font-semibold text-green-400"><RefreshCw className="h-4 w-4 animate-spin" /> Pushing...</span>}
              {status === 'saved' && <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400"><CheckCircle2 className="h-4 w-4" /> Live Successfully</span>}
              {status === 'error' && <span className="flex items-center gap-1.5 text-xs font-semibold text-red-400"><AlertCircle className="h-4 w-4" /> Check Connection</span>}
            </div>
        </div>
      </div>

      <div className="space-y-6">
        {/* Core Environmental */}
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
          <h4 className="mb-4 text-sm font-semibold text-green-400">Core Environmental Limits</h4>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <InputRow data={setpoints} onChange={handleChange} label="EC Minimum (µS/cm)" objKey="EC MIN" />
            <InputRow data={setpoints} onChange={handleChange} label="EC Maximum (µS/cm)" objKey="EC MAX" />
            <InputRow data={setpoints} onChange={handleChange} label="pH Low Limit" objKey="PH LOW" />
            <InputRow data={setpoints} onChange={handleChange} label="pH High Limit" objKey="PH HIGH" />
          </div>
        </div>

        {isSuperadmin && (
          <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 shadow-lg shadow-blue-500/5 transition-all hover:border-blue-500/30">
            <h4 className="mb-4 flex items-center gap-2 text-sm font-semibold text-blue-400">
              <Radio className="h-4 w-4 animate-pulse" /> ThingSpeak Cloud Configuration
            </h4>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <InputRow data={setpoints} onChange={handleChange} label="MQTT Client ID" objKey="CLIENT ID" type="text" />
              <InputRow data={setpoints} onChange={handleChange} label="MQTT Username" objKey="USERNAME" type="text" />
              <InputRow data={setpoints} onChange={handleChange} label="MQTT Password" objKey="PASSWORD" type="text" />
              <InputRow data={setpoints} onChange={handleChange} label="Channel ID" objKey="CHANNEL ID" type="text" />
              <InputRow data={setpoints} onChange={handleChange} label="Read API Key" objKey="READ API KEY" type="text" />
              <InputRow data={setpoints} onChange={handleChange} label="Write API Key" objKey="WRITE API KEY" type="text" />
              <InputRow data={setpoints} onChange={handleChange} label="MQTT Port" objKey="PORT" />
            </div>
            <p className="mt-4 text-[11px] text-slate-500">
              Changes will trigger a ThingSpeak reconnection on the device.
            </p>
          </div>
        )}
 

      </div>

      <div className="pt-4">
        <button 
          onClick={handleSave}
          disabled={status === 'disconnected' || status === 'saving'}
          className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 transition-transform active:scale-95 disabled:opacity-50"
        >
          <Save className="h-4 w-4" /> Send Values to {deviceRoot.toUpperCase()}
        </button>
      </div>
    </div>
  );
};

export default AlmoraSettings;
