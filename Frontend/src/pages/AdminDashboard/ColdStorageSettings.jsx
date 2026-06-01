import { useState, useEffect } from 'react';
import { Save, AlertCircle, CheckCircle2, RefreshCw, ChevronDown, Server, Radio, Thermometer, Droplets, Activity } from 'lucide-react';
import mqtt from 'mqtt';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

const defaultSetpoints = {
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

const ColdStorageSettings = () => {
  const [multiSensorDevices, setMultiSensorDevices] = useState([]);
  const [deviceRoot, setDeviceRoot] = useState('');
  const [allSetpoints, setAllSetpoints] = useState({});
  const [selectedPort, setSelectedPort] = useState('default');
  const [status, setStatus] = useState('disconnected');
  const [loading, setLoading] = useState(true);
  const [client, setClient] = useState(null);
  const [liveData, setLiveData] = useState({});
  const [chartData, setChartData] = useState([]); // Array of { time: '12:00', S1_T: 25, S1_H: 60, ... }
  const [systemConfig, setSystemConfig] = useState({
    "TS CLIENT ID": '',
    "TS USERNAME": '',
    "TS PASSWORD": '',
    "TS CHANNEL ID": '',
    "TS READ KEY": '',
    "TS WRITE KEY": '',
    "PORT": 1883
  });

  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const token = localStorage.getItem('token');
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  const role = user.role === 'superadmin' ? 'superadmin' : (user.accountType || user.role || 'user');
  const isSuperadmin = role === 'superadmin';
  const API_BASE = import.meta.env.VITE_API_URL || '';

  useEffect(() => {
    const fetchMultiSensorDevices = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();
        if (data.success) {
          const filtered = data.data.filter(d => d.deviceType === 'multi_sensor');
          setMultiSensorDevices(filtered);
          if (filtered.length > 0 && !deviceRoot) {
            const first = filtered[0];
            setDeviceRoot(first.mqttId || 'sensor1');
            
            const ts = first.thingspeak || {};
            setSystemConfig({
              "TS CLIENT ID":  ts.clientId  || '',
              "TS USERNAME":   ts.username  || '',
              "TS PASSWORD":   ts.password  || '',
              "TS CHANNEL ID": ts.channelId || '',
              "TS READ KEY":   ts.readApiKey  || '',
              "TS WRITE KEY":  ts.writeApiKey || '',
              "PORT":          ts.port || 1883
            });
          }
        }
      } catch (err) {
        console.error('Failed to fetch Multi Sensor devices', err);
      } finally {
        setLoading(false);
      }
    };
    fetchMultiSensorDevices();
  }, [token]);

  const selectedDevice = multiSensorDevices.find(d => (d.mqttId || 'sensor1') === deviceRoot);

  // AUTO-FILL CREDENTIALS WHEN HUB CHANGES
  useEffect(() => {
    if (selectedDevice) {
        const ts = selectedDevice.thingspeak || {};
        setSystemConfig({
            "TS CLIENT ID":  ts.clientId  || ts.tempReadApiKey || '',
            "TS USERNAME":   ts.username  || ts.tempWriteApiKey || '',
            "TS PASSWORD":   ts.password  || ts.tempChannelId || '',
            "TS CHANNEL ID": ts.channelId || '',
            "TS READ KEY":  ts.readApiKey || '',
            "TS WRITE KEY": ts.writeApiKey || '',
            "PORT":          ts.port      || 1883
        });
    }
  }, [deviceRoot, multiSensorDevices]);

  useEffect(() => {
    if (!deviceRoot) return;
    setStatus('disconnected');
    const mqttClient = mqtt.connect('wss://broker.hivemq.com:8884/mqtt');

    mqttClient.on('connect', () => {
        setStatus('connected');
        mqttClient.subscribe(`inhydro/${deviceRoot}/setpoints/current`);
        mqttClient.subscribe(`inhydro/${deviceRoot}/telemetry/live`);
        mqttClient.publish(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');
    });

    mqttClient.on('message', (topic, message) => {
      const topicTail = topic.split('/').pop();
      try {
        const data = JSON.parse(message.toString());
        if (topicTail === 'live') {
          setLiveData(data);
          
          setChartData(prev => {
            const timeStr = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'});
            const newPoint = { time: timeStr };
            Object.entries(data).forEach(([sKey, d]) => {
                if(d.status === 'OK') {
                    newPoint[`${sKey}_T`] = d.t;
                    newPoint[`${sKey}_H`] = d.h;
                }
            });
            const next = [...prev, newPoint];
            if(next.length > 25) next.shift(); // Keep last 25 readings for analysis
            return next;
          });
          
        } else if (topicTail === 'current') {
          if (data.sensor_setpoints) {
            setAllSetpoints(prev => {
              const next = { ...prev };
              Object.keys(data.sensor_setpoints).forEach(port => {
                next[port] = data.sensor_setpoints[port];
              });
              return next;
            });
          }
          if (data.system_config) {
            setSystemConfig(prev => {
              const next = { ...prev };
              Object.keys(data.system_config).forEach(k => {
                if (data.system_config[k] || !prev[k]) next[k] = data.system_config[k];
              });
              return next;
            });
          }
        }
      } catch (e) {}
    });

    setClient(mqttClient);
    return () => { if (mqttClient) mqttClient.end(); };
  }, [deviceRoot]);

  const handleSetpointChange = (key, value) => {
    setAllSetpoints(prev => ({
      ...prev,
      [selectedPort]: {
        ...(prev[selectedPort] || defaultSetpoints),
        [key]: value
      }
    }));
  };

  const handleConfigChange = (key, value) => {
    setSystemConfig(prev => ({ ...prev, [key]: value }));
  };

  const handleSave = () => {
    if (!client || !client.connected) {
      setStatus('error');
      return;
    }
    
    setStatus('saving');
    const payload = { 
        ...systemConfig,
        port: selectedPort === 'default' ? null : selectedPort,
        ...(allSetpoints[selectedPort] || defaultSetpoints)
    };

    ['T MIN', 'T MAX', 'H MIN', 'H MAX', 'PORT'].forEach(k => {
        if (payload[k] !== undefined && payload[k] !== "") {
            const n = Number(payload[k]);
            payload[k] = isNaN(n) ? payload[k] : n;
        }
    });

    if (isSuperadmin && selectedDevice) {
        const currentTS = selectedDevice.thingspeak || {};
        const dbPayload = {
            thingspeak: {
                ...currentTS,
                clientId:  systemConfig["TS CLIENT ID"] || currentTS.clientId,
                username:  systemConfig["TS USERNAME"] || currentTS.username,
                password:  systemConfig["TS PASSWORD"] || currentTS.password,
                channelId: systemConfig["TS CHANNEL ID"] || currentTS.channelId,
                readApiKey: systemConfig["TS READ KEY"] || currentTS.readApiKey,
                writeApiKey: systemConfig["TS WRITE KEY"] || currentTS.writeApiKey,
                port:      Number(systemConfig["PORT"] || currentTS.port || 1883)
            }
        };
        fetch(`${API_BASE}/api/devices/${selectedDevice._id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify(dbPayload)
        }).catch(err => console.error("DB Update error:", err));
    }

    client.publish(`inhydro/${deviceRoot}/setpoints/update`, JSON.stringify(payload), (err) => {
        if (err) { setStatus('error'); }
        else {
            setStatus('saved');
            setTimeout(() => setStatus('connected'), 2000);
        }
    });
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20">
        <RefreshCw className="h-8 w-8 animate-spin text-green-500" />
      </div>
    );
  }

  if (multiSensorDevices.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20 p-8 text-center">
        <Server className="mb-4 h-12 w-12 text-slate-600" />
        <h3 className="text-lg font-semibold text-white">No Cold Storage Devices Found</h3>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-white flex items-center gap-2">
            Cold Storage Management Hub
            {status === 'connected' && <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />}
          </h3>
          <p className="text-[11px] text-slate-400">Universal Two-Way Sync: Control settings globally</p>
        </div>
        
        <div className="relative"> 
          <button 
            onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            className="flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-xs font-medium text-white hover:border-green-500 transition-all"
          >
            <Server className="h-3.5 w-3.5 text-green-400" />
            <span className="max-w-[120px] truncate">{selectedDevice?.name || 'Select Hub'}</span>
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
          
          {isDropdownOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 flex w-48 flex-col overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
              {multiSensorDevices.map((dev) => (
                <button
                  key={dev._id}
                  onClick={() => { setDeviceRoot(dev.mqttId || dev._id); setIsDropdownOpen(false); }}
                  className="px-4 py-2.5 text-left text-xs text-slate-300 hover:bg-slate-800 transition-colors"
                >
                  {dev.name}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* SENSOR SPECIFIC CONTROL (Full Width) */}
        <div className="lg:col-span-3">
          <div className="rounded-2xl border border-slate-700 bg-slate-800/30 p-6 backdrop-blur-sm shadow-xl">
            <div className="flex items-center justify-between mb-6">
              <h4 className="text-sm font-semibold text-white flex items-center gap-2">
                <Thermometer className="h-4 w-4 text-blue-400" />
                Individual Sensor Setpoints
              </h4>
              
              <select 
                value={selectedPort}
                onChange={(e) => setSelectedPort(e.target.value)}
                className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white outline-none"
              >
                <option value="default">Default (All Sensors)</option>
                {['S1','S2','S3','S4','S5','S6','S7'].map(s => (
                    <option key={s} value={s}>Sensor {s}</option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-6">
                <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-700/50">
                  <h5 className="text-[11px] font-bold text-slate-500 mb-4 flex items-center gap-2 uppercase tracking-widest"><Thermometer className="h-3 w-3" /> Temperature Control</h5>
                  <div className="grid grid-cols-2 gap-4">
                    <InputRow label="Min Temp (°C)" objKey="T MIN" data={allSetpoints[selectedPort] || defaultSetpoints} onChange={handleSetpointChange} />
                    <InputRow label="Max Temp (°C)" objKey="T MAX" data={allSetpoints[selectedPort] || defaultSetpoints} onChange={handleSetpointChange} />
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-700/50">
                  <h5 className="text-[11px] font-bold text-slate-500 mb-4 flex items-center gap-2 uppercase tracking-widest"><Droplets className="h-3 w-3" /> Humidity Control</h5>
                  <div className="grid grid-cols-2 gap-4">
                    <InputRow label="Min Humid (%)" objKey="H MIN" data={allSetpoints[selectedPort] || defaultSetpoints} onChange={handleSetpointChange} />
                    <InputRow label="Max Humid (%)" objKey="H MAX" data={allSetpoints[selectedPort] || defaultSetpoints} onChange={handleSetpointChange} />
                  </div>
                </div>
            </div>

            <div className="mt-8 flex justify-end">
              <button
                onClick={handleSave}
                disabled={status === 'saving'}
                className="flex items-center gap-2 rounded-xl bg-blue-600 px-8 py-3 text-sm font-semibold text-white hover:bg-blue-500 transition-all disabled:opacity-50"
              >
                {status === 'saving' ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Save Sensor Settings
              </button>
            </div>
          </div>

          {/* Live Preview */}
          <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
            {Object.entries(liveData || {}).map(([s, d]) => (
                <div key={s} className={`p-4 rounded-2xl border ${d.status==='OK' ? 'border-green-500/20 bg-green-500/5' : 'border-slate-700 bg-slate-800/10'}`}>
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[9px] font-bold text-slate-500 uppercase truncate max-w-[60px]">{s.split('/').pop()}</span>
                        <div className={`h-1.5 w-1.5 rounded-full ${d.status==='OK' ? 'bg-green-500' : 'bg-slate-600'}`} />
                    </div>
                    <div className="text-sm font-semibold text-white">{d.t?.toFixed(1)}°C</div>
                    <div className="text-[10px] text-slate-400">{d.h?.toFixed(1)}% RH</div>
                </div>
            ))}
          </div>
        </div>
      </div>

      {/* REAL TIME ANALYSIS GRAPHS */}
      <div className="mt-6 grid grid-cols-1 xl:grid-cols-2 gap-6 w-full max-w-7xl mx-auto px-4 md:px-8 mb-12">
        
     
        <div className="rounded-2xl border border-slate-700 bg-slate-800/30 p-6 backdrop-blur-sm shadow-xl">
            <h4 className="text-sm font-semibold text-white mb-6 flex items-center gap-2">
                <Activity className="h-4 w-4 text-orange-400" />
                Live Temperature Analysis (°C)
            </h4>
            <div className="h-[300px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                        <XAxis dataKey="time" stroke="#94a3b8" fontSize={11} tickMargin={10} />
                        <YAxis stroke="#94a3b8" fontSize={11} domain={['dataMin - 2', 'dataMax + 2']} />
                        <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '8px', fontSize: '12px' }} itemStyle={{ color: '#fff' }} />
                        <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
                        
                        <Line type="monotone" dataKey="S1_T" name="S1" stroke="#ef4444" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S2_T" name="S2" stroke="#f97316" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S3_T" name="S3" stroke="#eab308" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S4_T" name="S4" stroke="#22c55e" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S5_T" name="S5" stroke="#06b6d4" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S6_T" name="S6" stroke="#3b82f6" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S7_T" name="S7" stroke="#8b5cf6" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                    </LineChart>
                </ResponsiveContainer>
            </div>
        </div>

    
        <div className="rounded-2xl border border-slate-700 bg-slate-800/30 p-6 backdrop-blur-sm shadow-xl">
            <h4 className="text-sm font-semibold text-white mb-6 flex items-center gap-2">
                <Activity className="h-4 w-4 text-blue-400" />
                Live Humidity Analysis (%)
            </h4>
            <div className="h-[300px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                        <XAxis dataKey="time" stroke="#94a3b8" fontSize={11} tickMargin={10} />
                        <YAxis stroke="#94a3b8" fontSize={11} domain={['dataMin - 5', 'dataMax + 5']} />
                        <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '8px', fontSize: '12px' }} itemStyle={{ color: '#fff' }} />
                        <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
                        
                        <Line type="monotone" dataKey="S1_H" name="S1" stroke="#ef4444" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S2_H" name="S2" stroke="#f97316" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S3_H" name="S3" stroke="#eab308" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S4_H" name="S4" stroke="#22c55e" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S5_H" name="S5" stroke="#06b6d4" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S6_H" name="S6" stroke="#3b82f6" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                        <Line type="monotone" dataKey="S7_H" name="S7" stroke="#8b5cf6" strokeWidth={2} dot={{r:3}} activeDot={{r:6}} isAnimationActive={false} />
                    </LineChart>
                </ResponsiveContainer>
            </div>
        </div>

      </div>

    </div>

  );
};

export default ColdStorageSettings;
