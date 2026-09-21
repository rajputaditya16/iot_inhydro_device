import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { MapPin, Cpu, Wifi, WifiOff, AlertTriangle } from 'lucide-react';
import StatCard from '../../components/StatCard';
import DeviceCard from '../../components/DeviceCard';
import { SkeletonCard, SkeletonDeviceCard } from '../../components/Skeleton';
import { useNavigate } from 'react-router-dom';

// Parse raw or ISO timestamp safely
const parseDateSafe = (ts) => {
  if (!ts) return null;
  const str = typeof ts === 'string' && ts.includes(' ') && !ts.includes('T') ? ts.replace(' ', 'T') : ts;
  const d = new Date(str);
  return isNaN(d.getTime()) || d.getTime() === 0 ? null : d;
};

// Check if telemetry is fresh (arrived within last 45 seconds)
const FRESH_TELEMETRY_WINDOW_MS = 45 * 1000;

const isTelemetryFresh = (lastUpdatedTime) => {
  const d = parseDateSafe(lastUpdatedTime);
  if (!d) return false;
  const diffMs = Date.now() - d.getTime();
  return diffMs >= 0 && diffMs <= FRESH_TELEMETRY_WINDOW_MS;
};

const SuperAdminDashboard = () => {
  const [loading, setLoading] = useState(true);
  const [devices, setDevices] = useState([]);
  const [filter, setFilter] = useState('all');
  const [, setTick] = useState(0);
  const navigate = useNavigate();
  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  const processDevices = useCallback((dbDevices) => {
    return dbDevices.map((d) => {
      const stats = d.liveStats || { temp: 0, moisture: 0, ph: 0, ec: 0 };
      const lastUpdatedTime = d.latestPacketTime || d.lastUpdated || null;
      const fresh = isTelemetryFresh(lastUpdatedTime);

      let computedStatus = 'offline';
      if (d.status === 'blocked') {
        computedStatus = 'blocked';
      } else if (fresh) {
        computedStatus = 'online';
      } else {
        computedStatus = 'offline';
      }

      return {
        id: d._id || d.id,
        _id: d._id || d.id,
        mqttId: d.mqttId || '',
        name: d.name,
        location: d.location,
        status: computedStatus,
        temp: stats.temp || 0,
        moisture: stats.moisture || 0,
        ph: stats.ph || 0,
        ec: stats.ec || 0,
        lastUpdated: lastUpdatedTime,
      };
    });
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/devices`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      const contentType = res.headers.get('content-type');
      if (!contentType || !contentType.includes('application/json')) {
        throw new Error('Received non-JSON response from server (Backend might be down)');
      }

      const data = await res.json();
      if (!data.success) {
        setDevices([]);
        setLoading(false);
        return;
      }

      const dbDevices = data.data || [];
      const mappedDevices = processDevices(dbDevices);
      setDevices(mappedDevices);
      setLoading(false);
    } catch (err) {
      console.error('Super Admin Dashboard fetch error:', err);
      setLoading(false);
    }
  }, [API_BASE, token, processDevices]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Real-time SSE stream
  useEffect(() => {
    const sseUrl = `${API_BASE}/api/devices/stream`;
    let eventSource = null;

    try {
      eventSource = new EventSource(sseUrl);
      eventSource.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (!payload) return;

          const incomingDevId = payload.deviceId ? String(payload.deviceId) : null;
          const incomingMqttId = payload.mqttId ? String(payload.mqttId).toLowerCase() : null;
          const nowIso = new Date().toISOString();
          const isExplicitOffline = payload.data?.status === 'offline';

          setDevices((prevDevices) =>
            prevDevices.map((dev) => {
              const matchesId = incomingDevId && String(dev.id) === incomingDevId;
              const matchesMqtt = incomingMqttId && dev.mqttId && dev.mqttId.toLowerCase() === incomingMqttId;

              if (matchesId || matchesMqtt) {
                if (dev.status === 'blocked') return dev;
                if (isExplicitOffline) return { ...dev, status: 'offline' };

                const data = payload.data || {};
                const temp = data.temp ?? data.temperature ?? data.room_temp ?? data.soil_temp ?? dev.temp;
                const moisture = data.moisture ?? data.humidity ?? data.soil_moisture ?? dev.moisture;
                const ph = data.ph ?? dev.ph;
                const ec = data.ec ?? dev.ec;

                return {
                  ...dev,
                  status: 'online',
                  lastUpdated: nowIso,
                  temp: typeof temp === 'number' ? temp : dev.temp,
                  moisture: typeof moisture === 'number' ? moisture : dev.moisture,
                  ph: typeof ph === 'number' ? ph : dev.ph,
                  ec: typeof ec === 'number' ? ec : dev.ec,
                };
              }
              return dev;
            })
          );
        } catch (_ignore) {
          // Ignore non-JSON heartbeat pings
        }
      };
    } catch (_err) {
      console.warn('[Dashboard SSE] Real-time stream failed, using polling fallback');
    }

    return () => {
      if (eventSource) eventSource.close();
    };
  }, [API_BASE]);

  // Local time decay watchdog
  useEffect(() => {
    const decayTimer = setInterval(() => {
      setDevices((prevDevices) => {
        let hasChanges = false;
        const updated = prevDevices.map((dev) => {
          if (dev.status === 'online') {
            const fresh = isTelemetryFresh(dev.lastUpdated);
            if (!fresh) {
              hasChanges = true;
              return { ...dev, status: 'offline' };
            }
          }
          return dev;
        });
        return hasChanges ? updated : prevDevices;
      });
      setTick((t) => (t + 1) % 1000);
    }, 3000);

    return () => clearInterval(decayTimer);
  }, []);

  const uniqueLocations = [...new Set(devices.map((d) => d.location))];

  const stats = {
    totalLocations: uniqueLocations.length,
    totalDevices: devices.length,
    onlineDevices: devices.filter((d) => d.status === 'online').length,
    offlineDevices: devices.filter((d) => d.status === 'offline').length,
    warningDevices: devices.filter((d) => d.status === 'warning' || d.status === 'critical').length,
  };

  const filteredDevices = filter === 'all' ? devices : devices.filter((d) => d.status === filter);

  const handleDeviceClick = (device) => {
    navigate(`/monitoring?device=${device.id}`);
  };

  const staggerContainer = {
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: { staggerChildren: 0.08 },
    },
  };

  return (
    <div className="space-y-6">
      {/* Stats Row */}
      {loading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
          {[...Array(5)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : (
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5"
        >
          <StatCard
            title="Total Locations"
            value={stats.totalLocations}
            icon={MapPin}
            color="cyan"
          />
          <StatCard
            title="Total Devices"
            value={stats.totalDevices}
            icon={Cpu}
            color="blue"
          />
          <StatCard
            title="Online Devices"
            value={stats.onlineDevices}
            icon={Wifi}
            color="green"
          />
          <StatCard
            title="Offline Devices"
            value={stats.offlineDevices}
            icon={WifiOff}
            color="red"
          />
          <StatCard
            title="Alerts Active"
            value={stats.warningDevices}
            icon={AlertTriangle}
            color="yellow"
          />
        </motion.div>
      )}

      {/* Device Overview */}
      <div>
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-white">Live Device Overview</h2>
            <p className="text-sm text-slate-400">Real-time sensor data from all connected devices</p>
          </div>
          {/* Filter Tabs */}
          <div className="flex gap-1.5 rounded-xl bg-slate-800/50 p-1">
            {[
              { key: 'all', label: 'All' },
              { key: 'online', label: 'Online' },
              { key: 'warning', label: 'Warning' },
              { key: 'critical', label: 'Critical' },
              { key: 'offline', label: 'Offline' },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setFilter(tab.key)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${filter === tab.key
                    ? 'bg-green-500/20 text-green-400 shadow-sm'
                    : 'text-slate-400 hover:text-white'
                  }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {[...Array(8)].map((_, i) => <SkeletonDeviceCard key={i} />)}
          </div>
        ) : (
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="show"
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
          >
            {filteredDevices.map((device) => (
              <DeviceCard key={device.id} device={device} onClick={handleDeviceClick} />
            ))}
          </motion.div>
        )}


        {!loading && filteredDevices.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-700/50 py-16">
            <Cpu className="h-12 w-12 text-slate-700" />
            <p className="mt-3 text-sm text-slate-500">No devices found with status "{filter}"</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default SuperAdminDashboard;