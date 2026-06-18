import { useState, useEffect, useRef } from 'react';
import { Save, AlertCircle, CheckCircle2, RefreshCw, Cpu, ChevronDown, Radio } from 'lucide-react';
import mqtt from 'mqtt';

const defaultSetpoints = {
  "EC MIN": 1200,
  "EC MAX": 1800,
  "PH LOW": 5.8,
  "PH HIGH": 6.5,
  "Timer1 Name": "TIMER 1",
  "Timer1 Pin": 17,
  "Timer1 Start": "10:00",
  "Timer1 Stop": "17:00",
  "Timer1 ON Min": 15,
  "Timer1 OFF Min": 30,
  "Timer2 Name": "TIMER 2",
  "Timer2 Pin": 27,
  "Timer2 Start": "10:00",
  "Timer2 Stop": "17:00",
  "Timer2 ON Min": 15,
  "Timer2 OFF Min": 30,
  "Timer3 Name": "TIMER 3",
  "Timer3 Pin": 25,
  "Timer3 Start": "10:00",
  "Timer3 Stop": "17:00",
  "Timer3 ON Min": 15,
  "Timer3 OFF Min": 30,
  "Timer4 Name": "AC TIMER",
  "Timer4 Start": "10:00",
  "Timer4 Stop": "17:00",
  "Timer4 ON Min": 15,
  "Timer4 OFF Min": 30
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

const DeviceSettings = () => {
  const [setpoints, setSetpoints] = useState(defaultSetpoints);
  const [status, setStatus] = useState('disconnected');
  const [client, setClient] = useState(null);
  const [liveData, setLiveData] = useState(null);
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
  // We prioritize the user-defined mqttId, falling back to the DB _id
  const selectedDevice = allDevices.find((d) => d._id === selectedDeviceId);
  const deviceRoot = selectedDevice ? (selectedDevice.mqttId || selectedDevice._id) : 'device1';

  const updateTopic = `inhydro/${deviceRoot}/setpoints/update`;
  const currentTopic = `inhydro/${deviceRoot}/setpoints/current`;
  const liveTopic = `inhydro/${deviceRoot}/telemetry/live`;

  // ── Step 1: Fetch devices from backend ─────────────────────────────────────
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const contentType = res.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
          throw new Error("Received non-JSON response from server");
        }
        const data = await res.json();
        if (data.success && data.data.length > 0) {
          const system2Devices = data.data.filter(d => (!d.deviceType || d.deviceType === 'system2' || d.deviceType === 'standard'));
          setAllDevices(system2Devices);
          // Auto-select the first device
          if (!selectedDeviceId && system2Devices.length > 0) {
            setSelectedDeviceId(system2Devices[0]._id);
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

  // ── Keep a ref of the current topic so the message handler is never stale ───
  const currentTopicRef = useRef(currentTopic);
  const liveTopicRef = useRef(liveTopic);
  useEffect(() => {
    currentTopicRef.current = currentTopic;
    liveTopicRef.current = liveTopic;
  }, [currentTopic, liveTopic]);

  // ── Step 2: Connect to MQTT once on mount ──────────────────────────────────
  useEffect(() => {
    const mqttClient = mqtt.connect('wss://broker.hivemq.com:8884/mqtt');

    mqttClient.on('connect', () => {
      console.log('Connected to MQTT Cloud Broker');
      setStatus('connected');

      // Subscribe to whatever device is currently selected
      const topic = currentTopicRef.current;
      const lTopic = liveTopicRef.current;
      if (topic) {
        mqttClient.subscribe(topic);
        prevTopicRef.current = topic;
        console.log(`Subscribed to: ${topic}`);
      }
      if (lTopic) {
        mqttClient.subscribe(lTopic);
        prevLiveTopicRef.current = lTopic;
        console.log(`Subscribed to: ${lTopic}`);
      }
    });

    mqttClient.on('message', (topic, message) => {
      if (topic === liveTopicRef.current) {
        try {
          const incomingLiveData = JSON.parse(message.toString());
          setLiveData(incomingLiveData);
        } catch (e) { }
      } else if (topic === currentTopicRef.current) {
        try {
          const incomingData = JSON.parse(message.toString());
          setSetpoints((prev) => ({
            ...prev,
            ...incomingData,
          }));
          console.log(`Synced setpoints from topic: ${topic}`);
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
  }, []); // Connect once on mount

  // ── Step 3: When device changes, resubscribe to correct topic ──────────────
  useEffect(() => {
    if (!client || !client.connected || !currentTopic) return;

    // Unsubscribe from previous topic
    if (prevTopicRef.current && prevTopicRef.current !== currentTopic) {
      client.unsubscribe(prevTopicRef.current);
      console.log(`Unsubscribed from: ${prevTopicRef.current}`);
    }

    if (prevLiveTopicRef.current && prevLiveTopicRef.current !== liveTopic) {
      client.unsubscribe(prevLiveTopicRef.current);
      console.log(`Unsubscribed from: ${prevLiveTopicRef.current}`);
    }

    // Subscribe to new topic
    client.subscribe(currentTopic);
    prevTopicRef.current = currentTopic;
    console.log(`Subscribed to: ${currentTopic}`);

    client.subscribe(liveTopic);
    prevLiveTopicRef.current = liveTopic;
    console.log(`Subscribed to: ${liveTopic}`);

    client.publish(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');

    // Reset setpoints to default when switching devices
    // (will be overwritten when the device's retained message arrives)
    const initialSetpoints = { ...defaultSetpoints };

    // Merge database ThingSpeak config if it exists
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

      // Convert numeric fields from string to float/int
      const payload = { ...setpoints };
      const numericFields = [
        'EC MIN', 'EC MAX', 'PH LOW', 'PH HIGH',
        'Timer1 ON Min', 'Timer1 OFF Min',
        'Timer2 ON Min', 'Timer2 OFF Min',
        'Timer3 ON Min', 'Timer3 OFF Min',
        'Timer4 ON Min', 'Timer4 OFF Min', 'PORT',
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
            clientId: payload["CLIENT ID"],
            username: payload["USERNAME"],
            password: payload["PASSWORD"],
            channelId: payload["CHANNEL ID"],
            port: Number(payload["PORT"]),
            readApiKey: payload["READ API KEY"],
            writeApiKey: payload["WRITE API KEY"]
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

      client.publish(updateTopic, JSON.stringify(payload), { retain: true }, (err) => {
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
        <h3 className="text-lg font-semibold text-white">No Devices Registered</h3>
        <p className="mt-2 text-sm text-slate-400">Please register a standard device in the "Devices" page first.</p>
      </div>
    );
  }

  // ── Handle device change ───────────────────────────────────────────────────
  const handleDeviceChange = (newId) => {
    setSelectedDeviceId(newId);
  };

  return (
    <div className="space-y-6">
      {/* Header with Device Selector */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">Remote Device Configuration</h3>
          <p className="text-sm text-slate-400">Push changes directly to the Raspberry Pi over MQTT</p>
        </div>

        {/* Right side: Live Analytics, Device Selector + Status */}
        <div className="flex flex-col items-end gap-3">
          {/* Live Analytics Engine (Premium Display) */}
          {liveData && (
            <div className="flex items-center gap-2 overflow-hidden rounded-2xl border border-slate-700/50 bg-slate-900/40 p-1 shadow-2xl backdrop-blur-md">
              <div className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-orange-500/10 to-transparent px-3 py-1.5 ring-1 ring-inset ring-orange-500/20">
                <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-orange-400 shadow-[0_0_8px_rgba(249,115,22,0.5)]"></div>
                <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Temp</span>
                <span className="text-sm font-black text-white">{liveData.temp ?? 0}<span className="text-[10px] text-orange-400 ml-0.5">°C</span></span>
              </div>

              <div className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-blue-500/10 to-transparent px-3 py-1.5 ring-1 ring-inset ring-blue-500/20">
                <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400 shadow-[0_0_8px_rgba(59,130,246,0.5)]"></div>
                <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Moist</span>
                <span className="text-sm font-black text-white">{liveData.moist ?? 0}<span className="text-[10px] text-blue-400 ml-0.5">%</span></span>
              </div>

              <div className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-green-500/10 to-transparent px-3 py-1.5 ring-1 ring-inset ring-green-500/20">
                <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-400 shadow-[0_0_8px_rgba(34,197,94,0.5)]"></div>
                <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">EC</span>
                <span className="text-sm font-black text-white">{liveData.ec || liveData.EC || 0}<span className="text-[10px] text-green-400 ml-0.5">µS/cm</span></span>
              </div>

              <div className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-purple-500/10 to-transparent px-3 py-1.5 ring-1 ring-inset ring-purple-500/20">
                <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-purple-400 shadow-[0_0_8px_rgba(168,85,247,0.5)]"></div>
                <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">pH</span>
                <span className="text-sm font-black text-white">{liveData.ph || liveData.PH || 0}</span>
              </div>
            </div>
          )}

          <div className="flex items-center gap-3">
            {/* Device Dropdown */}
            {devicesLoading ? (
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <RefreshCw className="h-3.5 w-3.5 animate-spin" /> Loading devices...
              </div>
            ) : allDevices.length === 0 ? (
              <div className="flex items-center gap-2 text-xs text-yellow-400">
                <AlertCircle className="h-3.5 w-3.5" /> No devices found
              </div>
            ) : (
              <div className="relative">
                <select
                  value={selectedDeviceId}
                  onChange={(e) => handleDeviceChange(e.target.value)}
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
            )}

            {/* Connection status */}
            <div>
              {status === 'connected' && (
                <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Cloud Connected
                </span>
              )}
              {status === 'disconnected' && (
                <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-400">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" /> Connecting...
                </span>
              )}
              {status === 'saving' && (
                <span className="flex items-center gap-1.5 text-xs font-semibold text-green-400">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" /> Pushing to Device...
                </span>
              )}
              {status === 'saved' && (
                <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Pushed Successfully
                </span>
              )}
              {status === 'error' && (
                <span className="flex items-center gap-1.5 text-xs font-semibold text-red-400">
                  <AlertCircle className="h-3.5 w-3.5" /> Connection Error
                </span>
              )}
            </div>
          </div>
        </div>
      </div>


      {/* Configuration Forms */}
      <div className="space-y-6">
        {/* Core Environmental */}
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
          <h4 className="mb-4 text-sm font-semibold text-green-400">Core Environmental Setpoints</h4>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <InputRow data={setpoints} onChange={handleChange} label="EC Minimum (µS/cm)" objKey="EC MIN" />
            <InputRow data={setpoints} onChange={handleChange} label="EC Maximum (µS/cm)" objKey="EC MAX" />
            <InputRow data={setpoints} onChange={handleChange} label="pH Low Limit" objKey="PH LOW" />
            <InputRow data={setpoints} onChange={handleChange} label="pH High Limit" objKey="PH HIGH" />
          </div>
        </div>

        {/* Timers */}
        {[1, 2, 3, 4].map((num) => (
          <div key={num} className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5">
            <h4 className="mb-4 text-sm font-semibold text-cyan-400">Cyclic Timer {num} Settings</h4>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-5">
              <InputRow data={setpoints} onChange={handleChange} label="Timer Name" objKey={`Timer${num} Name`} type="text" />
              <InputRow data={setpoints} onChange={handleChange} label="Active Window Start" objKey={`Timer${num} Start`} type="time" />
              <InputRow data={setpoints} onChange={handleChange} label="Active Window Stop" objKey={`Timer${num} Stop`} type="time" />
              <InputRow data={setpoints} onChange={handleChange} label="ON Duration (Mins)" objKey={`Timer${num} ON Min`} />
              <InputRow data={setpoints} onChange={handleChange} label="OFF Duration (Mins)" objKey={`Timer${num} OFF Min`} />
            </div>
          </div>
        ))}

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
          disabled={status === 'disconnected' || status === 'saving' || !selectedDeviceId}
          className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 transition-transform active:scale-95 disabled:opacity-50"
        >
          <Save className="h-4 w-4" />
          {selectedDevice
            ? `Push Settings to "${selectedDevice.name}"`
            : 'Push Remote Settings to Device'}
        </button>
      </div>
    </div>
  );
};

export default DeviceSettings;
