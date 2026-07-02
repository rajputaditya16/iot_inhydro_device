import { useState, useEffect } from 'react';
import { Save, AlertCircle, CheckCircle2, RefreshCw, ChevronDown, Server, Edit3, Radio } from 'lucide-react';
import mqtt from 'mqtt';

const defaultSetpointsRoom12 = {
  "EC MIN": 1.2, "EC MAX": 1.8,
  "PH LOW": 5.8, "PH HIGH": 6.5,
  "D T Max": 35.0, "DT Min": 15.0,
  "N T Max": 35.0, "N T Min": 15.0,
  "H Max": 80.0, "H Min": 30.0,
  "Timer1 Name": "TIMER 1", "Timer1 Start": "10:00", "Timer1 Stop": "17:00", "Timer1 ON Min": 15, "Timer1 OFF Min": 30,
  "Timer2 Name": "TIMER 2", "Timer2 Start": "10:00", "Timer2 Stop": "17:00", "Timer2 ON Min": 15, "Timer2 OFF Min": 30,
  "Timer3 Name": "TIMER 3",
  "Timer3 D_Start": "10:00", "Timer3 D_Stop": "17:00", "Timer3 D_ON Min": 15, "Timer3 D_OFF Min": 30,
  "Timer3 N_Start": "17:05", "Timer3 N_Stop": "09:55", "Timer3 N_ON Min": 15, "Timer3 N_OFF Min": 30,
  "Timer4 Name": "AC TIMER",
  "Timer4 D_Start": "10:00", "Timer4 D_Stop": "17:00", "Timer4 D_ON Min": 15, "Timer4 D_OFF Min": 30,
  "Timer4 N_Start": "17:05", "Timer4 N_Stop": "09:55", "Timer4 N_ON Min": 15, "Timer4 N_OFF Min": 30,
};

const defaultSetpointsRoom3 = {
  "Timer1 Name": "TIMER 1", "Timer1 Start": "10:00", "Timer1 Stop": "17:00", "Timer1 ON Min": 15, "Timer1 OFF Min": 30,
  "Timer2 Name": "TIMER 2", "Timer2 Start": "10:00", "Timer2 Stop": "17:00", "Timer2 ON Min": 15, "Timer2 OFF Min": 30,
  "Timer3 Name": "TIMER 3",
  "Timer3 D_Start": "10:00", "Timer3 D_Stop": "17:00", "Timer3 D_ON Min": 15, "Timer3 D_OFF Min": 30,
  "Timer3 N_Start": "17:05", "Timer3 N_Stop": "09:55", "Timer3 N_ON Min": 15, "Timer3 N_OFF Min": 30,
  "AC1 Name": "AC 1 TIMER",
  "AC1 D_Start": "10:00", "AC1 D_Stop": "17:00",
  "AC1 D_ON Min": 15,     "AC1 D_OFF Min": 30,
  "AC1 N_Start": "17:05", "AC1 N_Stop": "09:55",
  "AC1 N_ON Min": 15,     "AC1 N_OFF Min": 30,
  "AC1 D_T Max": 35.0,    "AC1 D_T Min": 15.0,
  "AC1 N_T Max": 35.0,    "AC1 N_T Min": 15.0,
  "AC2 Name": "AC 2 TIMER",
  "AC2 D_Start": "10:00", "AC2 D_Stop": "17:00",
  "AC2 D_ON Min": 15,     "AC2 D_OFF Min": 30,
  "AC2 N_Start": "17:05", "AC2 N_Stop": "09:55",
  "AC2 N_ON Min": 15,     "AC2 N_OFF Min": 30,
  "AC2 D_T Max": 35.0,    "AC2 D_T Min": 15.0,
  "AC2 N_T Max": 35.0,    "AC2 N_T Min": 15.0,
  "HUMI1 Name": "HUMI 1 TIMER",
  "HUMI1 D_Start": "10:00", "HUMI1 D_Stop": "17:00",
  "HUMI1 D_ON Min": 15,     "HUMI1 D_OFF Min": 30,
  "HUMI1 N_Start": "17:05", "HUMI1 N_Stop": "09:55",
  "HUMI1 N_ON Min": 15,     "HUMI1 N_OFF Min": 30,
  "HUMI1 D_H Max": 80.0,    "HUMI1 D_H Min": 30.0,
  "HUMI1 N_H Max": 80.0,    "HUMI1 N_H Min": 30.0,
  "HUMI2 Name": "HUMI 2 TIMER",
  "HUMI2 D_Start": "10:00", "HUMI2 D_Stop": "17:00",
  "HUMI2 D_ON Min": 15,     "HUMI2 D_OFF Min": 30,
  "HUMI2 N_Start": "17:05", "HUMI2 N_Stop": "09:55",
  "HUMI2 N_ON Min": 15,     "HUMI2 N_OFF Min": 30,
  "HUMI2 D_H Max": 80.0,    "HUMI2 D_H Min": 30.0,
  "HUMI2 N_H Max": 80.0,    "HUMI2 N_H Min": 30.0,
};

const InputRow = ({ label, objKey, type = "number", data, onChange }) => (
  <div className="flex flex-col gap-1">
    <label className="text-xs font-medium text-slate-400">{label}</label>
    <input
      type={type}
      value={data[objKey] !== undefined ? data[objKey] : (type === "number" ? 0 : "")}
      onChange={(e) => onChange(objKey, e.target.value)}
      className="w-full rounded-lg border border-slate-700 bg-slate-900/50 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
    />
  </div>
);

const StandardTimerCard = ({ prefix, label, data, onChange }) => (
  <div className="space-y-4 border border-slate-700/50 p-4 rounded-xl">
    <InputRow data={data} onChange={onChange} label={`${label} Name`} objKey={`${prefix} Name`} type="text" />
    <div className="grid grid-cols-2 gap-4">
      <InputRow data={data} onChange={onChange} label="Start Time (HH:MM)" objKey={`${prefix} Start`} type="text" />
      <InputRow data={data} onChange={onChange} label="Stop Time (HH:MM)" objKey={`${prefix} Stop`} type="text" />
      <InputRow data={data} onChange={onChange} label="ON Duration (Min)" objKey={`${prefix} ON Min`} />
      <InputRow data={data} onChange={onChange} label="OFF Duration (Min)" objKey={`${prefix} OFF Min`} />
    </div>
  </div>
);

const DayNightTimerCard = ({ prefix, label, data, onChange, isAC = false, isHumi = false }) => (
  <div className="space-y-4 border border-slate-700/50 p-4 rounded-xl bg-slate-900/10">
    <InputRow data={data} onChange={onChange} label={`${label} Name`} objKey={`${prefix} Name`} type="text" />
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {/* Day Settings */}
      <div className="space-y-3 border border-slate-700/30 p-3 rounded-lg bg-slate-900/20">
        <h5 className="text-xs font-semibold text-green-400 uppercase tracking-wider">Day Settings</h5>
        <div className="grid grid-cols-2 gap-3">
          <InputRow data={data} onChange={onChange} label="Start Time (HH:MM)" objKey={`${prefix} D_Start`} type="text" />
          <InputRow data={data} onChange={onChange} label="Stop Time (HH:MM)" objKey={`${prefix} D_Stop`} type="text" />
          <InputRow data={data} onChange={onChange} label="ON Duration (Min)" objKey={`${prefix} D_ON Min`} />
          <InputRow data={data} onChange={onChange} label="OFF Duration (Min)" objKey={`${prefix} D_OFF Min`} />
          {isAC && (
            <>
              <InputRow data={data} onChange={onChange} label="Day Temp Max (°C)" objKey={`${prefix} D_T Max`} />
              <InputRow data={data} onChange={onChange} label="Day Temp Min (°C)" objKey={`${prefix} D_T Min`} />
            </>
          )}
          {isHumi && (
            <>
              <InputRow data={data} onChange={onChange} label="Day Humi Max (%)" objKey={`${prefix} D_H Max`} />
              <InputRow data={data} onChange={onChange} label="Day Humi Min (%)" objKey={`${prefix} D_H Min`} />
            </>
          )}
        </div>
      </div>
      {/* Night Settings */}
      <div className="space-y-3 border border-slate-700/30 p-3 rounded-lg bg-slate-900/20">
        <h5 className="text-xs font-semibold text-green-400 uppercase tracking-wider">Night Settings</h5>
        <div className="grid grid-cols-2 gap-3">
          <InputRow data={data} onChange={onChange} label="Start Time (HH:MM)" objKey={`${prefix} N_Start`} type="text" />
          <InputRow data={data} onChange={onChange} label="Stop Time (HH:MM)" objKey={`${prefix} N_Stop`} type="text" />
          <InputRow data={data} onChange={onChange} label="ON Duration (Min)" objKey={`${prefix} N_ON Min`} />
          <InputRow data={data} onChange={onChange} label="OFF Duration (Min)" objKey={`${prefix} N_OFF Min`} />
          {isAC && (
            <>
              <InputRow data={data} onChange={onChange} label="Night Temp Max (°C)" objKey={`${prefix} N_T Max`} />
              <InputRow data={data} onChange={onChange} label="Night Temp Min (°C)" objKey={`${prefix} N_T Min`} />
            </>
          )}
          {isHumi && (
            <>
              <InputRow data={data} onChange={onChange} label="Night Humi Max (%)" objKey={`${prefix} N_H Max`} />
              <InputRow data={data} onChange={onChange} label="Night Humi Min (%)" objKey={`${prefix} N_H Min`} />
            </>
          )}
        </div>
      </div>
    </div>
  </div>
);

const OfficeControlSettings = () => {
  const [devices, setDevices] = useState([]);
  const [deviceRoot, setDeviceRoot] = useState('');
  const [activeRoom, setActiveRoom] = useState(1);

  const [setpoints, setSetpoints] = useState({ 1: { ...defaultSetpointsRoom12 }, 2: { ...defaultSetpointsRoom12 }, 3: { ...defaultSetpointsRoom3 } });

  const [status, setStatus] = useState('disconnected');
  const [loading, setLoading] = useState(true);
  const [client, setClient] = useState(null);
  const [toast, setToast] = useState({ show: false, type: 'success', message: '' });

  const showToast = (type, message) => {
    setToast({ show: true, type, message });
    setTimeout(() => {
      setToast({ show: false, type: '', message: '' });
    }, 4000);
  };

  const [isEditingName, setIsEditingName] = useState(false);
  const [tempName, setTempName] = useState('');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const token = localStorage.getItem('token');
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  const role = user.role === 'superadmin' ? 'superadmin' : (user.accountType || user.role || 'user');
  const isSuperadmin = role === 'superadmin';
  const API_BASE = import.meta.env.VITE_API_URL || '';

  useEffect(() => {
    const fetchDevices = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();
        if (data.success) {
          const filtered = data.data.filter(d => d.deviceType === 'office_control' || d.deviceType === 'system2');
          setDevices(filtered);
          if (filtered.length > 0 && !deviceRoot) {
            setDeviceRoot(filtered[0].mqttId || filtered[0]._id);
          }
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

  useEffect(() => {
    setTempName(selectedDevice?.name || 'Office Control');
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
        setDevices(prev => prev.map(d => d._id === selectedDevice._id ? { ...d, name: tempName } : d));
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

    const initialSetpoints = {
      1: { ...defaultSetpointsRoom12 },
      2: { ...defaultSetpointsRoom12 },
      3: { ...defaultSetpointsRoom3 }
    };
    if (isSuperadmin && selectedDevice && selectedDevice.thingspeak) {
      const ts = selectedDevice.thingspeak;
      ['1', '2', '3'].forEach(room => {
        if (ts.clientId) initialSetpoints[room]["CLIENT ID"] = ts.clientId;
        if (ts.username) initialSetpoints[room]["USERNAME"] = ts.username;
        if (ts.password) initialSetpoints[room]["PASSWORD"] = ts.password;
        if (ts.channelId) initialSetpoints[room]["CHANNEL ID"] = ts.channelId;
        if (ts.port) initialSetpoints[room]["PORT"] = ts.port;
        if (ts.readApiKey) initialSetpoints[room]["READ API KEY"] = ts.readApiKey;
        if (ts.writeApiKey) initialSetpoints[room]["WRITE API KEY"] = ts.writeApiKey;
      });
    }
    setSetpoints(initialSetpoints);

    mqttClient.on('connect', () => {
      setStatus('connected');
      [1, 2, 3].forEach(room => {
        mqttClient.subscribe(`inhydro/${deviceRoot}/room${room}/setpoints/current`);
        mqttClient.publish(`inhydro/${deviceRoot}/room${room}/setpoints/request_sync`, '1');
      });
    });

    mqttClient.on('message', (topic, message) => {
      const parts = topic.split('/');
      const roomPart = parts.find(p => p.startsWith('room'));
      if (!roomPart) return;
      const room = parseInt(roomPart.replace('room', ''));

      if (topic.endsWith('setpoints/current')) {
        try {
          const incomingData = JSON.parse(message.toString());
          setSetpoints(prev => {
            const merged = { ...prev[room], ...incomingData };
            const credKeys = ["CLIENT ID", "USERNAME", "PASSWORD", "CHANNEL ID", "PORT", "READ API KEY", "WRITE API KEY"];
            credKeys.forEach(k => {
              if (prev[room] && prev[room][k] && (!incomingData[k] || incomingData[k] === "")) {
                merged[k] = prev[room][k];
              }
            });
            return {
              ...prev,
              [room]: merged
            };
          });
        } catch (error) {
          console.error("Error parsing current setpoints from device", error);
        }
      }
    });

    mqttClient.on('error', () => {
      setStatus('error');
    });

    setClient(mqttClient);

    return () => {
      if (mqttClient) {
        mqttClient.end();
      }
    };
  }, [deviceRoot]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (room, key, value) => {
    setSetpoints(prev => ({
      ...prev,
      [room]: { ...prev[room], [key]: value }
    }));
  };

  const handleSave = async () => {
    if (client && client.connected) {
      setStatus('saving');

      const payload = { ...setpoints[activeRoom] };
      const numericFields = [
        'EC MIN', 'EC MAX', 'PH LOW', 'PH HIGH', 'D T Max', 'DT Min', 'N T Max', 'N T Min', 'H Max', 'H Min',
        'Timer1 ON Min', 'Timer1 OFF Min', 'Timer2 ON Min', 'Timer2 OFF Min',
        'Timer3 D_ON Min', 'Timer3 D_OFF Min', 'Timer3 N_ON Min', 'Timer3 N_OFF Min',
        'Timer4 D_ON Min', 'Timer4 D_OFF Min', 'Timer4 N_ON Min', 'Timer4 N_OFF Min',
        'AC1 D_ON Min', 'AC1 D_OFF Min', 'AC1 N_ON Min', 'AC1 N_OFF Min',
        'AC1 D_T Max', 'AC1 D_T Min', 'AC1 N_T Max', 'AC1 N_T Min',
        'AC2 D_ON Min', 'AC2 D_OFF Min', 'AC2 N_ON Min', 'AC2 N_OFF Min',
        'AC2 D_T Max', 'AC2 D_T Min', 'AC2 N_T Max', 'AC2 N_T Min',
        'HUMI1 D_ON Min', 'HUMI1 D_OFF Min', 'HUMI1 N_ON Min', 'HUMI1 N_OFF Min',
        'HUMI1 D_H Max', 'HUMI1 D_H Min', 'HUMI1 N_H Max', 'HUMI1 N_H Min',
        'HUMI2 D_ON Min', 'HUMI2 D_OFF Min', 'HUMI2 N_ON Min', 'HUMI2 N_OFF Min',
        'HUMI2 D_H Max', 'HUMI2 D_H Min', 'HUMI2 N_H Max', 'HUMI2 N_H Min',
        'PORT'
      ];

      numericFields.forEach(field => {
        if (payload[field] !== undefined && payload[field] !== "") {
          const numValue = Number(payload[field]);
          payload[field] = isNaN(numValue) ? payload[field] : numValue;
        }
      });

      // Save credentials to MongoDB and trigger push-config if superadmin
      if (isSuperadmin && selectedDevice) {
        try {
          const dbPayload = {
            thingspeak: {
              clientId: payload["CLIENT ID"] || "",
              username: payload["USERNAME"] || "",
              password: payload["PASSWORD"] || "",
              channelId: payload["CHANNEL ID"] || "",
              port: Number(payload["PORT"]) || 1883,
              readApiKey: payload["READ API KEY"] || "",
              writeApiKey: payload["WRITE API KEY"] || ""
            }
          };

          // 1. Update Database
          const updateRes = await fetch(`${API_BASE}/api/devices/${selectedDevice._id}`, {
            method: 'PUT',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify(dbPayload),
          });
          const updateData = await updateRes.json();
          if (updateData.success) {
            setDevices(prev => prev.map(d => d._id === selectedDevice._id ? updateData.data : d));
          }

          // 2. Trigger push-config via Backend
          await fetch(`${API_BASE}/api/devices/${selectedDevice._id}/push-config`, {
            method: 'PUT',
            headers: {
              Authorization: `Bearer ${token}`,
            },
          });
        } catch (err) {
          console.error("Failed to sync credentials to DB/Device", err);
          showToast('error', "Failed to sync credentials to Database");
        }
      }

      if (!isSuperadmin) {
        delete payload["CLIENT ID"];
        delete payload["USERNAME"];
        delete payload["PASSWORD"];
        delete payload["CHANNEL ID"];
        delete payload["PORT"];
        delete payload["READ API KEY"];
        delete payload["WRITE API KEY"];
      }

      client.publish(`inhydro/${deviceRoot}/room${activeRoom}/setpoints/update`, JSON.stringify(payload), { retain: true }, (err) => {
        if (err) {
          console.error(err);
          setStatus('error');
          showToast('error', `Failed to push setpoints for Room ${activeRoom}`);
        } else {
          setStatus('saved');
          showToast('success', `Setpoints pushed to Room ${activeRoom} successfully!`);
          setTimeout(() => setStatus('connected'), 3000);
        }
      });
    } else {
      setStatus('error');
      showToast('error', "MQTT client is not connected");
    }
  };

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
        <Server className="mb-4 h-12 w-12 text-slate-600" />
        <h3 className="text-lg font-semibold text-white">No Office Control Devices Found</h3>
        <p className="mt-2 text-sm text-slate-400">Please add an Office Control (office_control) device from the "Devices" page first.</p>
      </div>
    );
  }

  const currentSetpoints = setpoints[activeRoom];

  return (
    <div className="space-y-6">
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
                {selectedDevice?.name || 'Office Control'}
                <button onClick={() => setIsEditingName(true)} className="text-slate-500 transition hover:text-green-400" title="Rename Machine">
                  <Edit3 className="h-4 w-4" />
                </button>
              </h3>
            )}
          </div>
          <p className="text-sm text-slate-400 mt-1">Configure Office Control Setpoints</p>
        </div>

        <div className="flex flex-wrap items-center gap-4">
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
                  {devices.map((dev) => (
                    <button
                      key={dev._id}
                      onClick={() => {
                        setDeviceRoot(dev.mqttId || dev._id);
                        setIsDropdownOpen(false);
                      }}
                      className={`flex items-center w-full justify-start px-4 py-3 text-sm transition-colors hover:bg-slate-800 ${deviceRoot === (dev.mqttId || dev._id) ? 'bg-green-500/10 text-green-400 font-semibold' : 'text-slate-300'
                        }`}
                    >
                      <span className="truncate">{dev.name}</span>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          <div className="min-w-[140px] flex justify-end">
            {status === 'connected' && <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400"><CheckCircle2 className="h-4 w-4" /> Cloud Connected</span>}
            {status === 'disconnected' && <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-400"><RefreshCw className="h-4 w-4 animate-spin" /> Connecting...</span>}
            {status === 'saving' && <span className="flex items-center gap-1.5 text-xs font-semibold text-green-400"><RefreshCw className="h-4 w-4 animate-spin" /> Pushing...</span>}
            {status === 'saved' && <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400"><CheckCircle2 className="h-4 w-4" /> Live Successfully</span>}
            {status === 'error' && <span className="flex items-center gap-1.5 text-xs font-semibold text-red-400"><AlertCircle className="h-4 w-4" /> Connection Error</span>}
          </div>
        </div>
      </div>

      <div className="flex border-b border-slate-700">
        <button
          onClick={() => setActiveRoom(1)}
          className={`flex-1 py-3 text-sm font-semibold transition-colors ${activeRoom === 1 ? 'border-b-2 border-green-500 text-green-400' : 'text-slate-400 hover:text-white'}`}
        >
          Room 1 (Zone 1)
        </button>
        <button
          onClick={() => setActiveRoom(2)}
          className={`flex-1 py-3 text-sm font-semibold transition-colors ${activeRoom === 2 ? 'border-b-2 border-green-500 text-green-400' : 'text-slate-400 hover:text-white'}`}
        >
          Room 2 (Zone 2)
        </button>
        <button
          onClick={() => setActiveRoom(3)}
          className={`flex-1 py-3 text-sm font-semibold transition-colors ${activeRoom === 3 ? 'border-b-2 border-green-500 text-green-400' : 'text-slate-400 hover:text-white'}`}
        >
          Room 3 (Zone 3)
        </button>
      </div>

      <div className="space-y-6">
        {activeRoom !== 3 && (
          <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
            <h4 className="mb-4 text-sm font-semibold text-green-400">Core Limits</h4>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <InputRow data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} label="EC Minimum (mS/cm)" objKey="EC MIN" />
              <InputRow data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} label="EC Maximum (mS/cm)" objKey="EC MAX" />
              <InputRow data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} label="pH Low Limit" objKey="PH LOW" />
              <InputRow data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} label="pH High Limit" objKey="PH HIGH" />
              <InputRow data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} label="Day Temp Min (°C)" objKey="DT Min" />
              <InputRow data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} label="Day Temp Max (°C)" objKey="D T Max" />
              <InputRow data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} label="Night Temp Min (°C)" objKey="N T Min" />
              <InputRow data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} label="Night Temp Max (°C)" objKey="N T Max" />
              <InputRow data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} label="Room Humidity Min (%)" objKey="H Min" />
              <InputRow data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} label="Room Humidity Max (%)" objKey="H Max" />
            </div>
          </div>
        )}

        <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
          <h4 className="mb-4 text-sm font-semibold text-green-400">Cyclic Timers</h4>
          
          {activeRoom === 3 ? (
            <div className="space-y-6">
              {/* Row 1: Timer 1 & Timer 2 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <StandardTimerCard prefix="Timer1" label="Timer 1" data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} />
                <StandardTimerCard prefix="Timer2" label="Timer 2" data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} />
              </div>

              {/* Row 2: Timer 3 (Full Width Day/Night) */}
              <DayNightTimerCard prefix="Timer3" label="Timer 3" data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} />

              {/* Separator Line */}
              <div className="border-t border-slate-700/50 my-6" />

              {/* Climate Control Header */}
              <h4 className="text-sm font-semibold text-green-400">Climate Control Timers</h4>

              {/* Row 3: AC Timers vs Humidifier Timers (Side by side with vertical separator) */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8 relative">
                {/* AC Timers (Left side) */}
                <div className="space-y-6">
                  <h5 className="text-xs font-bold text-slate-400 uppercase tracking-wider text-center border-b border-slate-700/50 pb-2">AC Timers</h5>
                  <DayNightTimerCard prefix="AC1" label="AC 1" data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} isAC={true} />
                  
                  {/* Internal Separator */}
                  <div className="border-t border-slate-700/30 my-4" />
                  
                  <DayNightTimerCard prefix="AC2" label="AC 2" data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} isAC={true} />
                </div>

                {/* Vertical Separator Line (visible on md screens and up) */}
                <div className="hidden md:block absolute left-1/2 top-0 bottom-0 border-l border-slate-700/50" />

                {/* Humidifier Timers (Right side) */}
                <div className="space-y-6">
                  <h5 className="text-xs font-bold text-slate-400 uppercase tracking-wider text-center border-b border-slate-700/50 pb-2">Humidifier Timers</h5>
                  <DayNightTimerCard prefix="HUMI1" label="HUMI 1" data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} isHumi={true} />
                  
                  {/* Internal Separator */}
                  <div className="border-t border-slate-700/30 my-4" />
                  
                  <DayNightTimerCard prefix="HUMI2" label="HUMI 2" data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} isHumi={true} />
                </div>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <StandardTimerCard prefix="Timer1" label="Timer 1" data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} />
              <StandardTimerCard prefix="Timer2" label="Timer 2" data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} />
              <div className="md:col-span-2">
                <DayNightTimerCard prefix="Timer3" label="Timer 3" data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} />
              </div>
              <div className="md:col-span-2">
                <DayNightTimerCard prefix="Timer4" label="Timer 4 (AC TIMER)" data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} />
              </div>
            </div>
          )}
        </div>

        {isSuperadmin && (
          <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 shadow-lg shadow-blue-500/5">
            <h4 className="mb-4 flex items-center gap-2 text-sm font-semibold text-blue-400">
             
            </h4>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">

              <InputRow data={currentSetpoints} onChange={(k, v) => handleChange(activeRoom, k, v)} label="MQTT Port" objKey="PORT" />
            </div>
          </div>
        )}
      </div>

      <div className="pt-4">
        <button
          onClick={handleSave}
          disabled={status === 'disconnected' || status === 'saving'}
          className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 active:scale-95 disabled:opacity-50"
        >
          <Save className="h-4 w-4" /> Push Setpoints to Room {activeRoom}
        </button>
      </div>
    </div>
  );
};

export default OfficeControlSettings;
