import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { MapPin, Cpu, Wifi, WifiOff, AlertTriangle } from 'lucide-react';
import StatCard from '../../components/StatCard';
import DeviceCard from '../../components/DeviceCard';
import { SkeletonCard, SkeletonDeviceCard } from '../../components/Skeleton';
import { useNavigate } from 'react-router-dom';

const SuperAdminDashboard = () => {
  const [loading, setLoading] = useState(true);
  const [devices, setDevices] = useState([]);
  const [filter, setFilter] = useState('all');
  const [hasNewData, setHasNewData] = useState(true);
  const previousMetricsRef = useRef(null); 
  const navigate = useNavigate();
  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // Transform ThingSpeak API response to device format
  const transformApiData = (apiData, dbDevice) => {
    if (!apiData || !apiData.entry_id) return null;
    const lastUpdatedTime = new Date(apiData.created_at); 
    const diffMs = Date.now() - lastUpdatedTime.getTime();
    // 5 minutes threshold
    const isOnline = diffMs < 5 * 60 * 1000;
    return {
      id: dbDevice._id,
      name: dbDevice.name,
      location: dbDevice.location,
      status: isOnline ? 'online' : 'offline',
      temp: parseFloat(apiData.field1) || 0,
      moisture: parseFloat(apiData.field2) || 0,  
      ph: parseFloat(apiData.field3) || 0,
      ec: parseFloat(apiData.field4) || 0,
      lastUpdated: apiData.created_at,
    };
  };

  useEffect(() => {
    const fetchData = async () => {
      try {
        // Step 1: Fetch all devices from our backend
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

        // Step 2: Map the backend devices containing MongoDB-backed live metrics directly
        const mappedDevices = dbDevices.map((d) => {
          const stats = d.liveStats || { temp: 0, moisture: 0, ph: 0, ec: 0 };
          return {
            id: d._id,
            name: d.name,
            location: d.location,
            status: d.status || 'offline',
            temp: stats.temp,
            moisture: stats.moisture,
            ph: stats.ph,
            ec: stats.ec,
            lastUpdated: d.latestPacketTime || d.lastUpdated || d.updatedAt,
          };
        });

        // Check if data changed (for animation indicator only)
        const currentKey = JSON.stringify(mappedDevices.map((d) => ({ t: d.temp, m: d.moisture, e: d.ec, p: d.ph })));
        const changed = previousMetricsRef.current !== currentKey;
        setHasNewData(changed);
        previousMetricsRef.current = currentKey;
        setDevices(mappedDevices);

        setLoading(false);
      } catch (err) {
        console.error('Super Admin Dashboard fetch error:', err);
        setDevices([]);
        setHasNewData(false);
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [token]);

  // Get unique locations
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
            <h2 className="text-lg font-semibold text-white"> Device Overview (Super Admin)</h2>
            <p className="text-sm text-slate-400">Real-time sensor data from all connected devices across the entire system</p>
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
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                  filter === tab.key
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
              <DeviceCard key={device.id} device={device} onClick={handleDeviceClick} hasNewData={hasNewData} />
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