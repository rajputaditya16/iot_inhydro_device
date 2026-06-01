import { useState, useEffect } from 'react';
import { Save, AlertCircle, CheckCircle2, RefreshCw, Lock, Eye, EyeOff } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

const DeviceMqttConfig = ({ deviceId, onClose }) => {
  const [config, setConfig] = useState({
    channelId: '',
    readApiKey: '',
    writeApiKey: '',
    port: 1883,
    username: '',
    password: '',
    clientId: ''
  });
  const [status, setStatus] = useState('idle');
  const [loading, setLoading] = useState(true);
  const [showPasswords, setShowPasswords] = useState(false);
  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // Fetch current config
  useEffect(() => {
    const fetchDeviceConfig = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/devices/${deviceId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const contentType = res.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
          throw new Error("Received non-JSON response from server");
        }
        const data = await res.json();
        if (data.success && data.data?.thingspeak) {
          setConfig(data.data.thingspeak);
        }
        setLoading(false);
      } catch (err) {
        console.error('Error fetching device config:', err);
        setStatus('error');
        setLoading(false);
      }
    };

    if (deviceId) fetchDeviceConfig();
  }, [deviceId, token]);

  const handleChange = (field, value) => {
    setConfig(prev => ({
      ...prev,
      [field]: field === 'port' ? Number(value) : value
    }));
  };

  const handleSave = async () => {
    if (!config.channelId || !config.readApiKey || !config.writeApiKey || !config.username || !config.password || !config.clientId) {
      setStatus('error');
      alert('All fields are required');
      return;
    }

    setStatus('saving');
    try {
      const res = await fetch(`${API_BASE}/api/devices/${deviceId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ thingspeak: config })
      });

      const contentType = res.headers.get("content-type");
      if (!contentType || !contentType.includes("application/json")) {
        throw new Error("Received non-JSON response from server");
      }
      
      const data = await res.json();
      if (data.success) {
        setStatus('saved');
        setTimeout(() => setStatus('idle'), 3000);
      } else {
        setStatus('error');
      }
    } catch (err) {
      console.error('Error saving config:', err);
      setStatus('error');
    }
  };

  const handlePushToDevice = async () => {
    setStatus('pushing');
    try {
      const res = await fetch(`${API_BASE}/api/devices/${deviceId}/push-config`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });

      const data = await res.json();
      if (data.success) {
        setStatus('pushed');
        setTimeout(() => setStatus('idle'), 3000);
      } else {
        setStatus('error');
        alert(`Failed: ${data.message}`);
      }
    } catch (err) {
      console.error('Error pushing config:', err);
      setStatus('error');
      alert('Failed to push configuration to device');
    }
  };

  const InputField = ({ label, field, type = 'text', required = true }) => (
    <div className="flex flex-col gap-2">
      <label className="text-sm font-medium text-slate-300">
        {label} {required && <span className="text-red-400">*</span>}
      </label>
      <div className="relative">
        <input
          type={type === 'password' && !showPasswords ? 'password' : 'text'}
          value={config[field]}
          onChange={(e) => handleChange(field, e.target.value)}
          className="w-full rounded-lg border border-slate-700 bg-slate-900/50 px-4 py-2 text-sm text-white outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          required={required}
        />
        {type === 'password' && (
          <button
            type="button"
            onClick={() => setShowPasswords(!showPasswords)}
            className="absolute right-3 top-2.5 text-slate-400 hover:text-slate-300"
          >
            {showPasswords ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        )}
      </div>
    </div>
  );

  if (loading) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-6">
        <div className="flex items-center justify-center gap-2">
          <RefreshCw className="h-5 w-5 animate-spin text-blue-400" />
          <span className="text-sm text-slate-300">Loading configuration...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-6">
        <div className="mb-6 flex items-start gap-3">
          <Lock className="h-5 w-5 flex-shrink-0 text-blue-400 mt-0.5" />
          <div>
            <h3 className="text-base font-semibold text-white mb-1">MQTT Broker Configuration</h3>
            <p className="text-xs text-slate-400">Securely configure ThingSpeak MQTT credentials. These settings are only visible to admins.</p>
          </div>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <InputField label="Channel ID" field="channelId" />
            <InputField label="Port" field="port" type="number" />
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <InputField label="Read API Key" field="readApiKey" />
            <InputField label="Write API Key" field="writeApiKey" />
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <InputField label="Username" field="username" />
            <InputField label="Password" field="password" type="password" />
          </div>

          <InputField label="Client ID" field="clientId" />

          <div className="bg-slate-900/30 border border-slate-700/30 rounded-lg p-3 mt-4">
            <p className="text-xs text-slate-400">
              💡 <strong>Tip:</strong> Copy these exactly from your ThingSpeak device settings. Ensure all fields match your MQTT broker configuration.
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 mt-6 pt-4 border-t border-slate-700">
          <div>
            {status === 'saving' && (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-blue-400">
                <RefreshCw className="h-3 w-3 animate-spin" /> Saving to Database...
              </span>
            )}
            {status === 'saved' && (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                <CheckCircle2 className="h-3 w-3" /> Saved to Database
              </span>
            )}
            {status === 'pushing' && (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-purple-400">
                <RefreshCw className="h-3 w-3 animate-spin" /> Pushing to Device...
              </span>
            )}
            {status === 'pushed' && (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                <CheckCircle2 className="h-3 w-3" /> Pushed to Device Successfully
              </span>
            )}
            {status === 'error' && (
              <span className="flex items-center gap-1.5 text-xs font-semibold text-red-400">
                <AlertCircle className="h-3 w-3" /> Error
              </span>
            )}
          </div>
          <div className="flex gap-2">
            {onClose && (
              <button
                onClick={onClose}
                className="rounded-lg border border-slate-600 bg-slate-700/30 px-4 py-2 text-sm font-semibold text-slate-300 hover:bg-slate-700/50 transition-colors"
              >
                Close
              </button>
            )}
            <button
              onClick={handleSave}
              disabled={status === 'saving' || status === 'pushing'}
              className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-blue-600 to-blue-700 px-4 py-2 text-sm font-semibold text-white hover:from-blue-700 hover:to-blue-800 disabled:opacity-50 transition-colors"
            >
              <Save className="h-4 w-4" /> Save to Database
            </button>
            <button
              onClick={handlePushToDevice}
              disabled={status === 'saving' || status === 'pushing'}
              className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-purple-600 to-purple-700 px-4 py-2 text-sm font-semibold text-white hover:from-purple-700 hover:to-purple-800 disabled:opacity-50 transition-colors"
            >
              <RefreshCw className="h-4 w-4" /> Push to Device
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DeviceMqttConfig;
