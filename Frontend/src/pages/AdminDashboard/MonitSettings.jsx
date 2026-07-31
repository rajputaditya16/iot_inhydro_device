import { useState, useEffect } from 'react';
import { 
  Save, CheckCircle2, RefreshCw, ChevronDown, Server, Radio, 
  Thermometer, Droplets, Zap, Clock, ShieldCheck, Activity, Sliders, 
  Power, Lock, Key, FlaskConical, AlertCircle 
} from 'lucide-react';
import { createMqttClient } from '../../utils/mqtt';

const defaultSetpoints = {
  // Nutrients & pH
  "EC MIN": 1.2,
  "EC MAX": 1.8,
  "PH LOW": 5.8,
  "PH HIGH": 6.5,

  // Climate Control
  "TEMP MAX": 28.0,
  "TEMP MIN": 22.0,
  "HUMI MAX": 70.0,
  "HUMI MIN": 50.0,

  // Humidifier Day/Night Cycle
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

  // Cyclic Timer 1
  "Timer1 Name": "Timer 1",
  "Timer1 Start": "06:00",
  "Timer1 Stop": "18:00",
  "Timer1 ON Min": 5,
  "Timer1 OFF Min": 15,

  // Cyclic Timer 2
  "Timer2 Name": "Timer 2",
  "Timer2 Start": "00:00",
  "Timer2 Stop": "23:59",
  "Timer2 ON Min": 10,
  "Timer2 OFF Min": 20,

  // User Credentials
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

  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

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
          const filtered = data.data.filter(d => d.deviceType === 'monit' || d.deviceType === 'monit_device' || d.deviceType === 'dosing');
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

    mqttClient.on('message', (topic, message) => {
      if (topic === `inhydro/${deviceRoot}/telemetry/live` || topic === `inhydro/${deviceRoot}/room1/telemetry/live`) {
        try {
          const parsed = JSON.parse(message.toString());
          const payload = Array.isArray(parsed) ? parsed[parsed.length - 1] : parsed;
          setLiveData(payload);
        } catch (e) { }
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
      console.error("MQTT Error:", err);
    });

    setClient(mqttClient);

    return () => {
      mqttClient.end();
    };
  }, [deviceRoot]);

  const [toast, setToast] = useState({ show: false, type: 'success', message: '' });

  const showToast = (type, message) => {
    setToast({ show: true, type, message });
    setTimeout(() => {
      setToast({ show: false, type: '', message: '' });
    }, 4000);
  };

  const handleInputChange = (key, value) => {
    setSetpoints(prev => ({ ...prev, [key]: value }));
  };

  const handleSaveSetpoints = async () => {
    let published = false;

    if (client && client.connected) {
      try {
        client.publish(`inhydro/${deviceRoot}/setpoints/update`, JSON.stringify(setpoints), { retain: true });
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

  const handleSyncRequest = () => {
    if (!client || status !== 'connected') return;
    client.publish(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');
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
        <h3 className="text-lg font-semibold text-white">No Monit Controllers Found</h3>
        <p className="mt-2 text-sm text-slate-400">Please register a device with type <code className="text-green-400 bg-slate-800 px-2 py-0.5 rounded">monit</code> on the Devices page first.</p>
      </div>
    );
  }

  const ecVal = Number(liveData?.temp !== undefined ? liveData.ec : null);
  const tdsPpm = Number.isFinite(ecVal) ? Math.round(ecVal * 500) : null;

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
          <h3 className="text-base font-semibold text-white">
            {selectedDevice?.name || 'Monnet Controller'}
          </h3>
            <p className="text-sm text-slate-400 mt-1">Configure Monnet Setpoints </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Device Selector */}
          <div className="relative">
            <button
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              className={`flex items-center gap-2 rounded-xl border px-4 py-2 text-sm font-medium text-white outline-none transition-all ${isDropdownOpen ? 'border-green-500 bg-slate-800' : 'border-slate-700 bg-slate-900/50 hover:border-green-500 hover:bg-slate-800'}`}
            >
              <Server className="h-4 w-4 text-green-400" />
              <span className="max-w-[150px] truncate">{selectedDevice?.name || deviceRoot}</span>
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


          {/* Broker Status Badge */}
          <div className="min-w-[130px] flex justify-end">
            {status === 'connected' && (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" /> Connected
              </span>
            )}
            {status !== 'connected' && status !== 'error' && (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-500">
                <span className="h-2 w-2 rounded-full bg-slate-600" /> Offline
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
            {/* LEFT COLUMN: NUTRIENTS & PH + FOGGER TIMER DAY/NIGHT TABLE */}
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
                </div>
              </div>

              {/* Fogger Day/Night Cycle Table Card */}
              <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4 overflow-x-auto">
                <h4 className="text-sm font-semibold text-green-400 flex items-center gap-2 border-b border-slate-700/50 pb-3">
                  <Droplets className="w-4 h-4" /> Fogger Humidifier Day/Night Cycle
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
                      <th className="py-2.5 px-3 text-center font-bold text-amber-400 bg-amber-500/10 rounded-tl-lg">Day Cycle</th>
                      <th className="py-2.5 px-3 text-center font-bold text-indigo-400 bg-indigo-500/10 rounded-tr-lg">Night Cycle</th>
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
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-amber-400 font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI N_ON Min"] ?? 5}
                          onChange={(e) => handleInputChange("HUMI N_ON Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-indigo-400 font-mono text-center outline-none focus:border-green-500"
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
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-amber-400 font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI N_OFF Min"] ?? 40}
                          onChange={(e) => handleInputChange("HUMI N_OFF Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-indigo-400 font-mono text-center outline-none focus:border-green-500"
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
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-amber-400 font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI N_Max"] ?? 80.0}
                          onChange={(e) => handleInputChange("HUMI N_Max", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-indigo-400 font-mono text-center outline-none focus:border-green-500"
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
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-amber-400 font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["HUMI N_Min"] ?? 60.0}
                          onChange={(e) => handleInputChange("HUMI N_Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-indigo-400 font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* RIGHT COLUMN: CLIMATE CONTROL + CYCLIC TIMERS TABLE + USER CREDENTIALS */}
            <div className="space-y-6">
              {/* Climate Control Limits Card */}
              <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4">
                <h4 className="text-sm font-semibold text-green-400 flex items-center gap-2 border-b border-slate-700/50 pb-3">
                  <Thermometer className="w-4 h-4" /> Climate Temperature & Humidity Limits
                </h4>

                <div className="grid grid-cols-2 gap-4">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">TEMP MAX (°C)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["TEMP MAX"] ?? 28.0}
                      onChange={(e) => handleInputChange("TEMP MAX", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>

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
                    <label className="text-xs font-medium text-slate-400">HUMI MAX (%)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["HUMI MAX"] ?? 70.0}
                      onChange={(e) => handleInputChange("HUMI MAX", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-slate-400">HUMI MIN (%)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={setpoints["HUMI MIN"] ?? 50.0}
                      onChange={(e) => handleInputChange("HUMI MIN", parseFloat(e.target.value) || 0)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 font-mono"
                    />
                  </div>
                </div>
              </div>

              {/* Cyclic Timers Side-by-Side Table Card */}
              <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4 overflow-x-auto">
                <h4 className="text-sm font-semibold text-green-400 flex items-center gap-2 border-b border-slate-700/50 pb-3">
                  <Clock className="w-4 h-4" /> Cyclic Timers Configuration
                </h4>

                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-slate-700/60 bg-slate-800/40">
                      <th className="py-2.5 px-3 text-left font-bold text-slate-400">Setting</th>
                      <th className="py-2.5 px-3 text-center font-bold text-emerald-400 bg-emerald-500/10 rounded-tl-lg">Timer 1</th>
                      <th className="py-2.5 px-3 text-center font-bold text-teal-400 bg-teal-500/10 rounded-tr-lg">Timer 2</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    <tr>
                      <td className="py-2.5 px-3 font-semibold text-slate-300">Name:</td>
                      <td className="py-2 px-3">
                        <input
                          type="text"
                          value={setpoints["Timer1 Name"] ?? "Timer 1"}
                          onChange={(e) => handleInputChange("Timer1 Name", e.target.value)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-bold text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="text"
                          value={setpoints["Timer2 Name"] ?? "Timer 2"}
                          onChange={(e) => handleInputChange("Timer2 Name", e.target.value)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-bold text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold text-slate-300">Start:</td>
                      <td className="py-2 px-3">
                        <input
                          type="text"
                          value={setpoints["Timer1 Start"] ?? "06:00"}
                          onChange={(e) => handleInputChange("Timer1 Start", e.target.value)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="text"
                          value={setpoints["Timer2 Start"] ?? "00:00"}
                          onChange={(e) => handleInputChange("Timer2 Start", e.target.value)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold text-slate-300">Stop:</td>
                      <td className="py-2 px-3">
                        <input
                          type="text"
                          value={setpoints["Timer1 Stop"] ?? "18:00"}
                          onChange={(e) => handleInputChange("Timer1 Stop", e.target.value)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="text"
                          value={setpoints["Timer2 Stop"] ?? "23:59"}
                          onChange={(e) => handleInputChange("Timer2 Stop", e.target.value)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold text-slate-300">ON Min:</td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["Timer1 ON Min"] ?? 5}
                          onChange={(e) => handleInputChange("Timer1 ON Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-emerald-400 font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["Timer2 ON Min"] ?? 10}
                          onChange={(e) => handleInputChange("Timer2 ON Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-teal-400 font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold text-slate-300">OFF Min:</td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["Timer1 OFF Min"] ?? 15}
                          onChange={(e) => handleInputChange("Timer1 OFF Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-emerald-400 font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                      <td className="py-2 px-3">
                        <input
                          type="number"
                          value={setpoints["Timer2 OFF Min"] ?? 20}
                          onChange={(e) => handleInputChange("Timer2 OFF Min", parseFloat(e.target.value) || 0)}
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-teal-400 font-mono text-center outline-none focus:border-green-500"
                        />
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Security Credentials Card */}
              <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4">
                <h4 className="text-sm font-semibold text-green-400 flex items-center gap-2 border-b border-slate-700/50 pb-3">
                  <ShieldCheck className="w-4 h-4" /> Two-User Security Credentials
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

          <div className="pt-4">
            <button
              onClick={handleSaveSetpoints}
              disabled={status !== 'connected'}
              className="flex items-center gap-2 rounded-xl bg-green-500 hover:bg-green-400 px-6 py-2.5 text-sm font-semibold text-slate-950 transition-colors disabled:opacity-50"
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
                  <Droplets className="w-4 h-4" /> Water Sensor
                </h4>
                <div className="space-y-2.5 text-xs font-mono">
                  <div className="flex justify-between items-center py-1.5 px-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
                    <span className="text-slate-400">Water Temp</span>
                    <span className={`font-bold ${liveData?.temp !== undefined ? 'text-emerald-400' : 'text-red-400'}`}>
                      {liveData?.temp !== undefined ? `${liveData.temp} °C` : 'ERROR'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1.5 px-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
                    <span className="text-slate-400">Water Moisture</span>
                    <span className={`font-bold ${liveData?.moist !== undefined ? 'text-emerald-400' : 'text-red-400'}`}>
                      {liveData?.moist !== undefined ? `${liveData.moist} %` : 'ERROR'}
                    </span>
                  </div>
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
                      <span className="font-bold text-amber-400">{tdsPpm} PPM</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Room Sensor */}
              <div>
                <h4 className="text-xs font-bold text-green-400 uppercase tracking-wider mb-3 flex items-center gap-2 border-b border-slate-700/50 pb-2">
                  <Thermometer className="w-4 h-4" /> Room Sensor
                </h4>
                <div className="space-y-2.5 text-xs font-mono">
                  <div className="flex justify-between items-center py-1.5 px-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
                    <span className="text-slate-400">Room Temp</span>
                    <span className={`font-bold ${liveData?.room_temp !== undefined ? 'text-emerald-400' : 'text-red-400'}`}>
                      {liveData?.room_temp !== undefined ? `${liveData.room_temp} °C` : 'ERROR'}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1.5 px-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
                    <span className="text-slate-400">Room Humidity</span>
                    <span className={`font-bold ${liveData?.room_humi !== undefined ? 'text-emerald-400' : 'text-red-400'}`}>
                      {liveData?.room_humi !== undefined ? `${liveData.room_humi} %` : 'ERROR'}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* COLUMN 2: RELAY STATUS DASHBOARD */}
            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4">
              <h4 className="text-xs font-bold text-green-400 uppercase tracking-wider mb-3 flex items-center gap-2 border-b border-slate-700/50 pb-2">
                <Power className="w-4 h-4" /> Relay Output Status
              </h4>

              <div className="space-y-2.5 text-xs">
                {[
                  { name: 'Timer 1 Relay', state: liveData?.timer1 },
                  { name: 'Timer 2 Relay', state: liveData?.timer2 },
                  { name: 'Temp Relay (AC/Heater)', state: liveData?.relay_temp },
                  { name: 'Humidity Relay (Fogger)', state: liveData?.relay_humi },
                ].map((relay, idx) => (
                  <div key={idx} className="flex justify-between items-center py-2 px-3 rounded-lg bg-slate-900/50 border border-slate-700/40">
                    <span className="text-slate-300 font-semibold">{relay.name}</span>
                    <span className={`px-2.5 py-0.5 rounded text-[10px] font-bold flex items-center gap-1.5 ${relay.state ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 text-slate-400 border border-slate-700'}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${relay.state ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
                      {relay.state ? 'ACTIVE (ON)' : 'INACTIVE (OFF)'}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* COLUMN 3: SYSTEM STATUS & INFO */}
            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4">
              <h4 className="text-xs font-bold text-green-400 uppercase tracking-wider mb-3 flex items-center gap-2 border-b border-slate-700/50 pb-2">
                <Activity className="w-4 h-4" /> Monit Controller Telemetry
              </h4>

              <div className="space-y-3 text-xs">
                <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-700/40 space-y-1">
                  <span className="text-slate-400 block text-[11px]">Selected Machine:</span>
                  <span className="font-bold text-white text-sm">{selectedDevice?.name || deviceRoot}</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-700/40 space-y-1 font-mono">
                  <span className="text-slate-400 block text-[11px]">MQTT Topic:</span>
                  <span className="text-green-400 font-bold">inhydro/{deviceRoot}/telemetry/live</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-700/40 space-y-1">
                  <span className="text-slate-400 block text-[11px]">Data Status:</span>
                  <span className={`font-semibold flex items-center gap-1.5 ${liveData ? 'text-emerald-400' : 'text-amber-400'}`}>
                    <span className={`w-2 h-2 rounded-full ${liveData ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
                    {liveData ? 'Receiving Live Streams' : 'Waiting for Telemetry...'}
                  </span>
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
