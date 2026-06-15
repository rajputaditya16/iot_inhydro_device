import { useState, useEffect, useRef } from 'react';
import { Save, AlertCircle, CheckCircle2, RefreshCw, Cpu, ChevronDown, Radio, Thermometer, Droplets, Activity, Gauge } from 'lucide-react';
import mqtt from 'mqtt';

const defaultSetpoints = {
  "EC MIN": 1.2,
  "EC MAX": 1.8,
  "PH LOW": 5.8,
  "PH HIGH": 6.5,
  "D T Max": 35.0,
  "DT Min": 15.0,
  "N T Max": 35.0,
  "N T Min": 15.0,
  "H Max": 80.0,
  "H Min": 30.0,

  "CO2 TARGET": 800,
  "SYSTEM PASSWORD": "1234",
  "WATER TEMP MAX": 21.0,
  "WATER TEMP MIN": 18.0,

  "Timer1 Name": "TIMER 1",
  "Timer1 Start": "10:00",
  "Timer1 Stop": "17:00",
  "Timer1 ON Min": 15,
  "Timer1 OFF Min": 30,

  "Timer2 Name": "TIMER 2",
  "Timer2 Start": "10:00",
  "Timer2 Stop": "17:00",
  "Timer2 ON Min": 15,
  "Timer2 OFF Min": 30,

  "Timer3 Name": "TIMER 3",
  "Timer3 Start": "10:00",
  "Timer3 Stop": "17:00",
  "Timer3 ON Min": 15,
  "Timer3 OFF Min": 30,

  "Timer4 Name": "AC TIMER",
  "Timer4 D_Start": "10:00",
  "Timer4 D_Stop": "17:00",
  "Timer4 D_ON Min": 15,
  "Timer4 D_OFF Min": 30,
  "Timer4 N_Start": "17:05",
  "Timer4 N_Stop": "09:55",
  "Timer4 N_ON Min": 15,
  "Timer4 N_OFF Min": 30,

  "Timer5 Name": "TIMER 5",
  "Timer5 Start": "10:00",
  "Timer5 Stop": "17:00",
  "Timer5 ON Min": 15,
  "Timer5 OFF Min": 30,

  "Timer6 Name": "TIMER 6",
  "Timer6 Start": "10:00",
  "Timer6 Stop": "17:00",
  "Timer6 ON Min": 15,
  "Timer6 OFF Min": 30,

  "Timer7 Name": "TIMER 7",
  "Timer7 Start": "10:00",
  "Timer7 Stop": "17:00",
  "Timer7 ON Min": 15,
  "Timer7 OFF Min": 30,

  "Timer8 Name": "TIMER 8",
  "Timer8 D_Start": "10:00",
  "Timer8 D_Stop": "17:00",
  "Timer8 D_ON Min": 15,
  "Timer8 D_OFF Min": 30,
  "Timer8 N_Start": "17:05",
  "Timer8 N_Stop": "09:55",
  "Timer8 N_ON Min": 15,
  "Timer8 N_OFF Min": 30,

  "Timer9 Name": "TIMER 9",
  "Timer9 D_Start": "10:00",
  "Timer9 D_Stop": "17:00",
  "Timer9 D_ON Min": 15,
  "Timer9 D_OFF Min": 30,
  "Timer9 N_Start": "17:05",
  "Timer9 N_Stop": "09:55",
  "Timer9 N_ON Min": 15,
  "Timer9 N_OFF Min": 30,

  "Timer10 Name": "TIMER 10",
  "Timer10 D_Start": "10:00",
  "Timer10 D_Stop": "17:00",
  "Timer10 D_ON Min": 15,
  "Timer10 D_OFF Min": 30,
  "Timer10 N_Start": "17:05",
  "Timer10 N_Stop": "09:55",
  "Timer10 N_ON Min": 15,
  "Timer10 N_OFF Min": 30,
};

const InputRow = ({ label, objKey, type = "number", data, onChange }) => (
  <div className="flex flex-col gap-1">
    <label className="text-xs font-medium text-slate-400">{label}</label>
    <input
      type={type}
      value={data[objKey] ?? ''}
      onChange={(e) => onChange(objKey, e.target.value)}
      className="w-full rounded-lg border border-slate-700 bg-slate-900/50 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
    />
  </div>
);

const ControllingDeviceSettings = () => {
  const [setpoints, setSetpoints] = useState(defaultSetpoints);
  const [status, setStatus] = useState('disconnected');
  const [client, setClient] = useState(null);
  const [liveData, setLiveData] = useState(null);
  const [configSubTab, setConfigSubTab] = useState('env'); // 'env', 'cyclic', 'daynight', 'advanced'
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // ── Device selector state ──────────────────────────────────────────────────
  const [allDevices, setAllDevices] = useState([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [devicesLoading, setDevicesLoading] = useState(true);
  const token = localStorage.getItem('token');
  const prevTopicRef = useRef(null);
  const prevLiveTopicRef = useRef(null);
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  const role = user.role === 'superadmin' ? 'superadmin' : (user.accountType || user.role || 'user');
  const isSuperadmin = role === 'superadmin';

  // ── Compute MQTT topics based on selected device ───────────────────────────
  const selectedDevice = allDevices.find((d) => d._id === selectedDeviceId);
  const deviceRoot = selectedDevice ? (selectedDevice.mqttId || selectedDevice._id) : 'device1';
  
  const updateTopic = `inhydro/${deviceRoot}/monitor/setpoints/update`;
  const currentTopic = `inhydro/${deviceRoot}/monitor/setpoints/current`;
  const liveTopic = `inhydro/${deviceRoot}/monitor/telemetry/live`;

  // ── Fetch devices ──────────────────────────────────────────────────────────
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();
        if (data.success && data.data.length > 0) {
          const controllingDevices = data.data.filter(d => d.deviceType === 'controlling');
          setAllDevices(controllingDevices);
          if (!selectedDeviceId && controllingDevices.length > 0) {
            setSelectedDeviceId(controllingDevices[0]._id);
          }
        }
      } catch (err) {
        console.error('Failed to fetch devices', err);
      } finally {
        setDevicesLoading(false);
      }
    };
    fetchDevices();
  }, [token]);

  const currentTopicRef = useRef(currentTopic);
  const liveTopicRef = useRef(liveTopic);
  useEffect(() => {
    currentTopicRef.current = currentTopic;
    liveTopicRef.current = liveTopic;
  }, [currentTopic, liveTopic]);

  // ── MQTT Connection ────────────────────────────────────────────────────────
  useEffect(() => {
    const mqttClient = mqtt.connect('wss://broker.hivemq.com:8884/mqtt');

    mqttClient.on('connect', () => {
      console.log('Connected to MQTT Cloud Broker (controlling.py configuration)');
      setStatus('connected');

      const topic = currentTopicRef.current;
      const lTopic = liveTopicRef.current;
      if (topic) {
        mqttClient.subscribe(topic);
        prevTopicRef.current = topic;
      }
      if (lTopic) {
        mqttClient.subscribe(lTopic);
        prevLiveTopicRef.current = lTopic;
      }
    });

    mqttClient.on('message', (topic, message) => {
      if (topic === liveTopicRef.current) {
        try {
          const incomingLiveData = JSON.parse(message.toString());
          // Extract nested telemetry if it is in controlling.py format
          const tel = incomingLiveData.telemetry || incomingLiveData || {};
          setLiveData(tel);
        } catch (e) {}
      } else if (topic === currentTopicRef.current) {
        try {
          const incomingData = JSON.parse(message.toString());
          setSetpoints((prev) => ({
            ...prev,
            ...incomingData,
          }));
        } catch (error) {
          console.error('Error parsing setpoints from device', error);
        }
      }
    });

    mqttClient.on('error', (err) => {
      console.error('MQTT Error: ', err);
      setStatus('error');
    });

    setClient(mqttClient);

    return () => {
      if (mqttClient) {
        mqttClient.end();
      }
    };
  }, []);

  // ── Device Change ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!client || !client.connected || !currentTopic) return;

    if (prevTopicRef.current && prevTopicRef.current !== currentTopic) {
      client.unsubscribe(prevTopicRef.current);
    }
    if (prevLiveTopicRef.current && prevLiveTopicRef.current !== liveTopic) {
      client.unsubscribe(prevLiveTopicRef.current);
    }

    client.subscribe(currentTopic);
    prevTopicRef.current = currentTopic;

    client.subscribe(liveTopic);
    prevLiveTopicRef.current = liveTopic;

    client.publish(`inhydro/${deviceRoot}/monitor/setpoints/request_sync`, '1');

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
  }, [selectedDeviceId, client, selectedDevice, isSuperadmin]);

  const handleChange = (key, value) => {
    setSetpoints((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  const handleSave = () => {
    if (client && client.connected) {
      setStatus('saving');

      const payload = { ...setpoints };
      const numericFields = [
        'EC MIN', 'EC MAX', 'PH LOW', 'PH HIGH',
        'D T Max', 'DT Min', 'N T Max', 'N T Min', 'H Max', 'H Min',
        'Timer1 ON Min', 'Timer1 OFF Min',
        'Timer2 ON Min', 'Timer2 OFF Min',
        'Timer3 ON Min', 'Timer3 OFF Min',
        'Timer4 D_ON Min', 'Timer4 D_OFF Min', 'Timer4 N_ON Min', 'Timer4 N_OFF Min',
        'Timer5 ON Min', 'Timer5 OFF Min',
        'Timer6 ON Min', 'Timer6 OFF Min',
        'Timer7 ON Min', 'Timer7 OFF Min',
        'Timer8 D_ON Min', 'Timer8 D_OFF Min', 'Timer8 N_ON Min', 'Timer8 N_OFF Min',
        'Timer9 D_ON Min', 'Timer9 D_OFF Min', 'Timer9 N_ON Min', 'Timer9 N_OFF Min',
        'Timer10 D_ON Min', 'Timer10 D_OFF Min', 'Timer10 N_ON Min', 'Timer10 N_OFF Min',
        'PORT',
        'CO2 TARGET', 'WATER TEMP MAX', 'WATER TEMP MIN'
      ];

      numericFields.forEach((field) => {
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
            clientId: payload["CLIENT ID"] || "",
            username: payload["USERNAME"] || "",
            password: payload["PASSWORD"] || "",
            channelId: payload["CHANNEL ID"] || "",
            port: Number(payload["PORT"] || 1883),
            readApiKey: payload["READ API KEY"] || "",
            writeApiKey: payload["WRITE API KEY"] || ""
          }
        };

        fetch(`${API_BASE}/api/devices/${selectedDeviceId}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(dbPayload)
        }).catch(err => console.error("DB Sync error:", err));
      }

      client.publish(updateTopic, JSON.stringify(payload), (err) => {
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

  if (devicesLoading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20">
        <RefreshCw className="h-8 w-8 animate-spin text-green-500" />
      </div>
    );
  }

  if (allDevices.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/20 p-8 text-center">
        <Cpu className="mb-4 h-12 w-12 text-slate-600" />
        <h3 className="text-lg font-semibold text-white">No Controller Devices Registered</h3>
        <p className="mt-2 text-sm text-slate-400">Please register a device of type "InHydro Controller" in the "Devices" page first.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header with Device Selector */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">Controller Configuration</h3>
          <p className="text-sm text-slate-400">Sync setpoint modifications to the local Python script over MQTT</p>
        </div>

        {/* Right side: Live Analytics, Device Selector + Status */}
        <div className="flex flex-col items-end gap-3">


          <div className="flex items-center gap-3">
            <div className="relative">
              <select
                value={selectedDeviceId}
                onChange={(e) => setSelectedDeviceId(e.target.value)}
                className="appearance-none rounded-xl border border-slate-700 bg-slate-800 pl-9 pr-8 py-2 text-sm font-medium text-white outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 cursor-pointer transition-all min-w-[200px]"
              >
                {allDevices.map((d) => (
                  <option key={d._id} value={d._id}>
                    {d.name} — {d.location}
                  </option>
                ))}
              </select>
              <Cpu className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-green-400 pointer-events-none" />
              <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500 pointer-events-none" />
            </div>

            <div>
              {status === 'connected' && (
                <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400 animate-pulse">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Online
                </span>
              )}
              {status === 'disconnected' && (
                <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-400">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" /> Connecting...
                </span>
              )}
              {status === 'saving' && (
                <span className="flex items-center gap-1.5 text-xs font-semibold text-green-400">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" /> Saving...
                </span>
              )}
              {status === 'saved' && (
                <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Pushed!
                </span>
              )}
              {status === 'error' && (
                <span className="flex items-center gap-1.5 text-xs font-semibold text-red-400">
                  <AlertCircle className="h-3.5 w-3.5" /> Error
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Sub-tab Navigation */}
      <div className="flex gap-2 border-b border-slate-700/60 pb-px">
        <button
          onClick={() => setConfigSubTab('env')}
          className={`px-4 py-2 text-sm font-semibold border-b-2 transition-all ${
            configSubTab === 'env'
              ? 'border-green-500 text-green-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          Environment & Nutrients
        </button>
        <button
          onClick={() => setConfigSubTab('cyclic')}
          className={`px-4 py-2 text-sm font-semibold border-b-2 transition-all ${
            configSubTab === 'cyclic'
              ? 'border-green-500 text-green-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          Cyclic Timers (1-3, 5-7)
        </button>
        <button
          onClick={() => setConfigSubTab('daynight')}
          className={`px-4 py-2 text-sm font-semibold border-b-2 transition-all ${
            configSubTab === 'daynight'
              ? 'border-green-500 text-green-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          Day/Night Timers (4, 8-10)
        </button>
        <button
          onClick={() => setConfigSubTab('advanced')}
          className={`px-4 py-2 text-sm font-semibold border-b-2 transition-all ${
            configSubTab === 'advanced'
              ? 'border-orange-500 text-orange-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          Advanced Control
        </button>
      </div>

      {/* Configuration Forms */}
      <div className="space-y-6">
        {configSubTab === 'env' && (
          <div className="space-y-6">
            {/* Core Environmental */}
            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
              <h4 className="mb-4 text-sm font-semibold text-green-400">Nutrient Setpoints</h4>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <InputRow data={setpoints} onChange={handleChange} label="EC Minimum (µS/cm)" objKey="EC MIN" />
                <InputRow data={setpoints} onChange={handleChange} label="EC Maximum (µS/cm)" objKey="EC MAX" />
                <InputRow data={setpoints} onChange={handleChange} label="pH Low Limit" objKey="PH LOW" />
                <InputRow data={setpoints} onChange={handleChange} label="pH High Limit" objKey="PH HIGH" />
              </div>
            </div>

            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
              <h4 className="mb-4 text-sm font-semibold text-orange-400">Climate Setpoints</h4>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-6">
                <InputRow data={setpoints} onChange={handleChange} label="Day Temp Max (°C)" objKey="D T Max" />
                <InputRow data={setpoints} onChange={handleChange} label="Day Temp Min (°C)" objKey="DT Min" />
                <InputRow data={setpoints} onChange={handleChange} label="Night Temp Max (°C)" objKey="N T Max" />
                <InputRow data={setpoints} onChange={handleChange} label="Night Temp Min (°C)" objKey="N T Min" />
                <InputRow data={setpoints} onChange={handleChange} label="Humidity Max (%)" objKey="H Max" />
                <InputRow data={setpoints} onChange={handleChange} label="Humidity Min (%)" objKey="H Min" />
              </div>
            </div>
          </div>
        )}

        {configSubTab === 'cyclic' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
            {/* Left Column: Timers 1, 2, 3 */}
            <div className="space-y-6">
              {[1, 2, 3].map((num) => (
                <div key={num} className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4 shadow-md shadow-black/10">
                  <InputRow data={setpoints} onChange={handleChange} label={`Timer ${num} Name`} objKey={`Timer${num} Name`} type="text" />
                  <div className="grid grid-cols-2 gap-4">
                    <InputRow data={setpoints} onChange={handleChange} label="Start Time (HH:MM)" objKey={`Timer${num} Start`} type="text" />
                    <InputRow data={setpoints} onChange={handleChange} label="Stop Time (HH:MM)" objKey={`Timer${num} Stop`} type="text" />
                    <InputRow data={setpoints} onChange={handleChange} label="ON Duration (Min)" objKey={`Timer${num} ON Min`} />
                    <InputRow data={setpoints} onChange={handleChange} label="OFF Duration (Min)" objKey={`Timer${num} OFF Min`} />
                  </div>
                </div>
              ))}
            </div>

            {/* Right Column: Timers 5, 6, 7 */}
            <div className="space-y-6">
              {[5, 6, 7].map((num) => (
                <div key={num} className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4 shadow-md shadow-black/10">
                  <InputRow data={setpoints} onChange={handleChange} label={`Timer ${num} Name`} objKey={`Timer${num} Name`} type="text" />
                  <div className="grid grid-cols-2 gap-4">
                    <InputRow data={setpoints} onChange={handleChange} label="Start Time (HH:MM)" objKey={`Timer${num} Start`} type="text" />
                    <InputRow data={setpoints} onChange={handleChange} label="Stop Time (HH:MM)" objKey={`Timer${num} Stop`} type="text" />
                    <InputRow data={setpoints} onChange={handleChange} label="ON Duration (Min)" objKey={`Timer${num} ON Min`} />
                    <InputRow data={setpoints} onChange={handleChange} label="OFF Duration (Min)" objKey={`Timer${num} OFF Min`} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {configSubTab === 'daynight' && (
          <div className="space-y-6">
            {[4, 8, 9, 10].map((num) => (
              <div key={num} className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4">
                <div className="flex items-center gap-2 text-cyan-400">
                  <InputRow data={setpoints} onChange={handleChange} label={`Timer ${num} Name`} objKey={`Timer${num} Name`} type="text" />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Day Settings */}
                  <div className="space-y-4 border border-slate-700/30 p-4 rounded-xl bg-slate-900/20">
                    <h5 className="text-xs font-semibold text-green-400 uppercase tracking-wider">Day Settings</h5>
                    <div className="grid grid-cols-2 gap-3">
                      <InputRow data={setpoints} onChange={handleChange} label="Start Time (HH:MM)" objKey={`Timer${num} D_Start`} type="text" />
                      <InputRow data={setpoints} onChange={handleChange} label="Stop Time (HH:MM)" objKey={`Timer${num} D_Stop`} type="text" />
                      <InputRow data={setpoints} onChange={handleChange} label="ON Duration (Min)" objKey={`Timer${num} D_ON Min`} />
                      <InputRow data={setpoints} onChange={handleChange} label="OFF Duration (Min)" objKey={`Timer${num} D_OFF Min`} />
                    </div>
                  </div>
                  {/* Night Settings */}
                  <div className="space-y-4 border border-slate-700/30 p-4 rounded-xl bg-slate-900/20">
                    <h5 className="text-xs font-semibold text-purple-400 uppercase tracking-wider">Night Settings</h5>
                    <div className="grid grid-cols-2 gap-3">
                      <InputRow data={setpoints} onChange={handleChange} label="Start Time (HH:MM)" objKey={`Timer${num} N_Start`} type="text" />
                      <InputRow data={setpoints} onChange={handleChange} label="Stop Time (HH:MM)" objKey={`Timer${num} N_Stop`} type="text" />
                      <InputRow data={setpoints} onChange={handleChange} label="ON Duration (Min)" objKey={`Timer${num} N_ON Min`} />
                      <InputRow data={setpoints} onChange={handleChange} label="OFF Duration (Min)" objKey={`Timer${num} N_OFF Min`} />
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {configSubTab === 'advanced' && (
          <div className="rounded-xl border border-orange-500/20 bg-gradient-to-b from-slate-800/40 to-slate-800/20 p-5 space-y-4 shadow-lg shadow-orange-500/5">
            <h4 className="text-sm font-semibold text-orange-400 uppercase tracking-wider flex items-center gap-2">
              <Cpu className="h-4 w-4 text-orange-400" /> Advanced Control
            </h4>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
              <InputRow data={setpoints} onChange={handleChange} label="CO2 Target (PPM)" objKey="CO2 TARGET" />
              <InputRow data={setpoints} onChange={handleChange} label="System PIN / Password" objKey="SYSTEM PASSWORD" type="text" />
              <InputRow data={setpoints} onChange={handleChange} label="H2O Temp Max (°C)" objKey="WATER TEMP MAX" />
              <InputRow data={setpoints} onChange={handleChange} label="H2O Temp Min (°C)" objKey="WATER TEMP MIN" />
              {isSuperadmin && <InputRow data={setpoints} onChange={handleChange} label="MQTT Port" objKey="PORT" />}
            </div>
          </div>
        )}
      </div>

      <div className="pt-4">
        <button
          onClick={handleSave}
          disabled={status === 'disconnected' || status === 'saving' || !selectedDeviceId}
          className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 active:scale-95 disabled:opacity-50"
        >
          <Save className="h-4 w-4" />
          {selectedDevice
            ? `Push Config to "${selectedDevice.name}"`
            : 'Push Config to Device'}
        </button>
      </div>
    </div>
  );
};

export default ControllingDeviceSettings;
