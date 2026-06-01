import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { MapPin, Cpu, Wifi, WifiOff, AlertTriangle } from 'lucide-react';
import StatCard from '../../components/StatCard';
import DeviceCard from '../../components/DeviceCard';
import { SkeletonCard, SkeletonDeviceCard } from '../../components/Skeleton';
import { useNavigate } from 'react-router-dom';

const AdminDashboard = () => {
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
    return {
      id: dbDevice._id,
      name: dbDevice.name,
      location: dbDevice.location,
      status: 'online',
      temp: parseFloat(apiData.field1) || 0,
      moisture: parseFloat(apiData.field2) || 0,  
      ph: parseFloat(apiData.field3) || 0,
      ec: parseFloat(apiData.field4) || 0,
      lastUpdated: apiData.created_at,
      battery: dbDevice.battery || 100,
    };
  };

  useEffect(() => {
    const fetchData = async () => {
      try {
        // Step 1: Fetch all devices from our backend
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });

        const contentType = res.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
          throw new Error("Received non-JSON response from server (Backend might be down)");
        }

        const data = await res.json();
        if (!data.success) {
          setDevices([]);
          setLoading(false);
          return;
        }

        const dbDevices = data.data || [];

        // Step 2: For each device that has ThingSpeak config, fetch latest data
        const thingspeakDevices = dbDevices.filter(
          (d) => d.thingspeak?.channelId && d.thingspeak?.readApiKey
        );

        if (thingspeakDevices.length === 0) {
          // Show DB devices without live data
          const offlineDevices = dbDevices.map((d) => ({
            id: d._id,
            name: d.name,
            location: d.location,
            status: d.status || 'offline',
            temp: 0,
            moisture: 0,
            ph: 0,
            ec: 0,
            lastUpdated: d.lastUpdated || d.updatedAt,
            battery: d.battery || 100,
          }));
          setDevices(offlineDevices);
          setHasNewData(false);
          setLoading(false);
          return;
        }

        // Fetch ThingSpeak data for each device in parallel
        const liveDevicePromises = thingspeakDevices.map(async (dbDevice) => {
          try {
            const { channelId, readApiKey } = dbDevice.thingspeak;
            const tsRes = await fetch(
              `https://api.thingspeak.com/channels/${channelId}/feeds.json?api_key=${readApiKey}&results=1`
            );
            const tsResult = await tsRes.json();
            const latestFeed = tsResult?.feeds?.[0];
            const liveDevice = transformApiData(latestFeed, dbDevice);
            return liveDevice || {
              id: dbDevice._id,
              name: dbDevice.name,
              location: dbDevice.location,
              status: 'offline',
              temp: 0, moisture: 0, ph: 0, ec: 0,
              lastUpdated: dbDevice.lastUpdated || dbDevice.updatedAt,
              battery: dbDevice.battery || 100,
            };
          } catch {
            return {
              id: dbDevice._id,
              name: dbDevice.name,
              location: dbDevice.location,
              status: 'offline',
              temp: 0, moisture: 0, ph: 0, ec: 0,
              lastUpdated: dbDevice.lastUpdated || dbDevice.updatedAt,
              battery: dbDevice.battery || 100,
            };
          }
        });

        // Include devices without ThingSpeak as offline
        const devicesWithoutTS = dbDevices
          .filter((d) => !d.thingspeak?.channelId || !d.thingspeak?.readApiKey)
          .map((d) => ({
            id: d._id,
            name: d.name,
            location: d.location,
            status: d.status || 'offline',
            temp: 0, moisture: 0, ph: 0, ec: 0,
            lastUpdated: d.lastUpdated || d.updatedAt,
            battery: d.battery || 100,
          }));

        const liveDevices = await Promise.all(liveDevicePromises);
        const allDevices = [...liveDevices, ...devicesWithoutTS];

        // Check if data changed
        const currentKey = JSON.stringify(allDevices.map((d) => ({ t: d.temp, m: d.moisture, e: d.ec, p: d.ph })));
        const changed = previousMetricsRef.current !== currentKey;
        setHasNewData(changed);
        if (changed) {
          previousMetricsRef.current = currentKey;
          setDevices(allDevices);
        }

        setLoading(false);
      } catch (err) {
        console.error('Dashboard fetch error:', err);
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

export default AdminDashboard;
