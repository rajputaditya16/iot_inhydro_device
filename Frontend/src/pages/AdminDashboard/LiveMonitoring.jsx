import { useState, useEffect, useCallback, useRef, memo, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Thermometer,
  Droplets,
  Zap,
  FlaskConical,
  RefreshCw,
  Clock,
  Radio,
  Cpu,
  ChevronDown,
  Activity,
} from 'lucide-react';
import LiveChart from '../../components/LiveChart';
import { SkeletonCard } from '../../components/Skeleton';
import { useThrottledStream } from '../../hooks/useThrottledStream';
import { createMqttClient } from '../../utils/mqtt';
import {
  getStatusBg,
  getStatusDot,
  getMetricStatus,
  getMetricColor,
  formatTimestamp,
} from '../../utils/helpers';

// ── Memoized Atomic Metric Card (P2 Optimization) ────────
const BigMetric = memo(
  ({ label, value, unit, icon: Icon, type }) => {
    const safeValue = Number.isFinite(value) ? value : 0;
    const status = getMetricStatus(type, safeValue);
    const color = getMetricColor(status);

    const bgColorMap = {
      'text-emerald-400': 'bg-emerald-500/10 border-emerald-500/20',
      'text-yellow-400': 'bg-yellow-500/10 border-yellow-500/20',
      'text-red-400': 'bg-red-500/10 border-red-500/20',
      'text-slate-500': 'bg-slate-500/10 border-slate-500/20',
    };

    return (
      <div
        className={`rounded-2xl border p-4 ${bgColorMap[color] || 'bg-slate-800/50 border-slate-700/50'} backdrop-blur-sm transition-colors duration-200`}
      >
        <div className="flex items-center gap-2.5">
          <div className={`rounded-lg p-1.5 ${color} bg-white/5`}>
            <Icon className="h-4 w-4" />
          </div>
          <span className="text-sm font-medium text-slate-400">{label}</span>
        </div>
        <div className="mt-3 flex items-baseline gap-1.5">
          <span className={`text-2xl font-bold tabular-nums ${color}`}>
            {safeValue === 0 ? '--' : type === 'ec' ? safeValue : safeValue.toFixed(1)}
          </span>
          <span className="text-sm text-slate-500">{unit}</span>
        </div>
        <div className="mt-1.5 flex items-center gap-1.5">
          <div
            className={`h-1.5 w-1.5 rounded-full ${
              status === 'normal'
                ? 'bg-emerald-400'
                : status === 'warning'
                ? 'bg-yellow-400'
                : status === 'critical'
                ? 'bg-red-400'
                : 'bg-slate-500'
            }`}
          />
          <span className="text-xs text-slate-500 capitalize">{status}</span>
        </div>
      </div>
    );
  },
  (prev, next) =>
    prev.value === next.value &&
    prev.label === next.label &&
    prev.unit === next.unit &&
    prev.type === next.type
);

// ── Memoized Specialized EC / TDS Card (P2 Optimization) ─────────────────────
const EcMetricCard = memo(
  ({ label = 'Electrical Conductivity (EC)', ecVal, unit = 'mS/cm' }) => {
    const tdsVal = ecVal != null ? Math.round(ecVal * 500) : null;
    const ecStatus = getMetricStatus('ec', ecVal ?? 0);
    const ecColor = getMetricColor(ecStatus);
    const bgMap = {
      'text-emerald-400': 'bg-emerald-500/10 border-emerald-500/20',
      'text-yellow-400': 'bg-yellow-500/10 border-yellow-500/20',
      'text-red-400': 'bg-red-500/10 border-red-500/20',
      'text-slate-500': 'bg-slate-500/10 border-slate-500/20',
    };

    return (
      <div
        className={`rounded-2xl border p-4 ${bgMap[ecColor] || 'bg-slate-800/50 border-slate-700/50'} backdrop-blur-sm transition-colors duration-200`}
      >
        <div className="flex items-center gap-2.5">
          <div className={`rounded-lg p-1.5 ${ecColor} bg-white/5`}>
            <Zap className="h-4 w-4" />
          </div>
          <span className="text-sm font-medium text-slate-400">{label}</span>
        </div>
        <div className="mt-3 flex items-baseline gap-1.5 flex-wrap">
          <span className={`text-2xl font-bold tabular-nums ${ecColor}`}>
            {ecVal != null ? ecVal : '--'}
          </span>
          <span className="text-sm text-slate-500">{unit}</span>
          {tdsVal != null && (
            <span className="text-sm text-slate-400 font-semibold font-mono">
              ({tdsVal} ppm)
            </span>
          )}
        </div>
        <div className="mt-1.5 flex items-center gap-1.5">
          <div
            className={`h-1.5 w-1.5 rounded-full ${
              ecStatus === 'normal'
                ? 'bg-emerald-400'
                : ecStatus === 'warning'
                ? 'bg-yellow-400'
                : ecStatus === 'critical'
                ? 'bg-red-400'
                : 'bg-slate-500'
            }`}
          />
          <span className="text-xs text-slate-500 capitalize">{ecStatus}</span>
        </div>
      </div>
    );
  },
  (prev, next) => prev.ecVal === next.ecVal && prev.label === next.label
);

// ── Memoized Cold Room Probe Card (P2 Optimization) ──────────────────────────
const ColdRoomProbeCard = memo(
  ({ sensorId, data, history, onSelect }) => {
    return (
      <div
        onClick={() => onSelect(sensorId)}
        className="rounded-2xl border border-slate-700 bg-slate-800/40 p-4 backdrop-blur-md cursor-pointer hover:border-blue-500/50 transition-all hover:bg-slate-800/60"
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="rounded-lg bg-blue-500/10 px-2 py-1 text-[10px] font-bold text-blue-400">
            {`Cold Room ${sensorId.toUpperCase().replace('S', '')}`}
          </span>
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              data?.status === 'OK' || data?.t != null ? 'bg-emerald-500' : 'bg-red-500'
            }`}
          />
        </div>

        <div className="space-y-4">
          <div className="flex justify-between items-end">
            <div className="space-y-1">
              <p className="text-[10px] text-slate-500 flex items-center gap-1">
                <Thermometer className="h-3 w-3 " /> Temperature
              </p>
              <p className="text-xl font-bold text-white tabular-nums">
                {data?.t != null ? data.t.toFixed(1) : '--'}
                <span className="text-xs font-normal text-slate-500 ml-0.5">°C</span>
              </p>
            </div>
            <div className="space-y-1 text-right">
              <p className="text-[10px] text-slate-500 flex items-center gap-1 justify-end">
                <Droplets className="h-3 w-3 " /> Humidity
              </p>
              <p className="text-xl font-bold text-blue-400 tabular-nums">
                {data?.h != null ? data.h.toFixed(1) : '--'}
                <span className="text-xs font-normal text-slate-500 ml-0.5">%</span>
              </p>
            </div>
          </div>

          {/* Real-time Sparkline */}
          <div className="h-12 w-full bg-slate-900/40 rounded-lg flex items-end gap-1 px-2 py-1.5 border border-slate-700/30">
            {(history?.t || [0]).map((val, i) => {
              const min = 10,
                max = 45;
              const h = Math.min(100, Math.max(10, ((val - min) / (max - min)) * 100));
              return (
                <div
                  key={i}
                  className={`w-full rounded-t transition-all duration-300 ${
                    val > 30 ? 'bg-red-400' : 'bg-blue-400'
                  }`}
                  style={{ height: `${h}%` }}
                />
              );
            })}
          </div>
        </div>
      </div>
    );
  },
  (prev, next) =>
    prev.data?.t === next.data?.t &&
    prev.data?.h === next.data?.h &&
    prev.data?.status === next.data?.status &&
    (prev.history?.t?.length || 0) === (next.history?.t?.length || 0)
);

const LiveMonitoring = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [initLoading, setInitLoading] = useState(true);

  // ── All devices from DB ────────────────────────────────────────────────────
  const [allDevices, setAllDevices] = useState([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState(searchParams.get('device') || '');

  // ── Live data state ────────────────────────────────────────────────────────
  const [liveDevice, setLiveDevice] = useState(null);
  const [activeFields, setActiveFields] = useState([]);
  const [activeMetrics, setActiveMetrics] = useState({});
  const [chartData, setChartData] = useState({});
  const [hasNewData, setHasNewData] = useState(true);
  const previousMetricsRef = useRef(null);
  const newDataTimeoutRef = useRef(null);

  useEffect(() => {
    return () => {
      if (newDataTimeoutRef.current) {
        clearTimeout(newDataTimeoutRef.current);
      }
    };
  }, []);

  // ── Multi-Sensor Live States ────────────────────────────────────────────────
  const [multiSensorData, setMultiSensorData] = useState({});
  const [sensorHistory, setSensorHistory] = useState({}); // { S1: [t1, t2...], S2: [...] }
  const [sortBy, setSortBy] = useState('id'); // 'id', 'temp', 'humi'
  const [selectedSensor, setSelectedSensor] = useState(null);

  // ── Office Control Dual Room Live States ────────────────────────────────────
  const [officeControlData, setOfficeControlData] = useState({ 1: null, 2: null, 3: null });
  const [officeControlHistory, setOfficeControlHistory] = useState({
    1: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
    2: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
    3: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
  });
  const [activeRoomTab, setActiveRoomTab] = useState(1);

  // ── InHydro Controller Live States ──────────────────────────────────────────
  const [controllingData, setControllingData] = useState(null);
  const [controllingHistory, setControllingHistory] = useState({
    water_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [],
    vpd: [], dli: [], wind_speed: [], wind_dir: [], do: [], ppfd: [], n: [], p: [], k: [],
  });
  const [isMqttConnected, setIsMqttConnected] = useState(false);

  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // ── Step 1: Fetch all devices from backend ─────────────────────────────────
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();
        if (data.success) {
          setAllDevices(data.data);
          if (!selectedDeviceId && data.data.length > 0) {
            const firstConfigured =
              data.data.find((d) => d.mqttId) || data.data[0];
            if (firstConfigured) {
              setSelectedDeviceId(firstConfigured._id);
              setSearchParams({ device: firstConfigured._id });
            }
          }
        }
      } catch (err) {
        console.error('Failed to fetch devices', err);
      } finally {
        setInitLoading(false);
      }
    };
    fetchDevices();
  }, [token]);

  // ── Get current selected device meta ───────────────────────────────────────
  const deviceMeta = useMemo(() => {
    return allDevices.find((d) => d._id === selectedDeviceId || d.id === selectedDeviceId);
  }, [allDevices, selectedDeviceId]);

  // ── Determine if the currently selected device is Online or Offline ─────────
  const isDeviceOnline = useMemo(() => {
    if (deviceMeta?.status === 'blocked') return false;
    // 1. If we have liveDevice with a lastUpdated timestamp, check 5 min threshold
    if (liveDevice?.lastUpdated) {
      const diffMs = Date.now() - new Date(liveDevice.lastUpdated).getTime();
      return diffMs < 5 * 60 * 1000 && (liveDevice.status === 'online' || !liveDevice.status);
    }
    // 2. If liveDevice has status directly
    if (liveDevice?.status) {
      return liveDevice.status === 'online';
    }
    // 3. Fallback to deviceMeta status from DB
    if (deviceMeta?.status) {
      return deviceMeta.status === 'online';
    }
    return false;
  }, [liveDevice, deviceMeta]);

  // ── Handle device change from dropdown ─────────────────────────────────────
  const handleDeviceChange = (newId) => {
    setSelectedDeviceId(newId);
    setSearchParams({ device: newId });
    setLiveDevice(null);
    setLoading(true);
    setHasNewData(true);
    previousMetricsRef.current = null;
    setChartData({});
    setActiveMetrics({});
    setActiveFields([]);
    setOfficeControlData({ 1: null, 2: null, 3: null });
    setOfficeControlHistory({
      1: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
      2: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
      3: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
    });
    setControllingData(null);
    setControllingHistory({
      water_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [],
      vpd: [], dli: [], wind_speed: [], wind_dir: [], do: [], ppfd: [], n: [], p: [], k: [],
    });
  };

  // ── Dynamic Field Icon & Label Display Helper ──────────────────────────────
  const getFieldDisplayInfo = useCallback((name) => {
    const lower = String(name || '').toLowerCase();
    if (lower.includes('temp')) return { icon: Thermometer, unit: '°C', type: 'temperature' };
    if (lower.includes('moist') || lower.includes('humid')) return { icon: Droplets, unit: '%', type: 'moisture' };
    if (lower.includes('ec') || lower.includes('conduct')) return { icon: Zap, unit: 'mS/cm', type: 'ec' };
    if (lower.includes('ph')) return { icon: FlaskConical, unit: 'pH', type: 'ph' };
    if (lower.includes('co2') || lower.includes('carbon')) return { icon: Activity, unit: 'ppm', type: 'co2' };
    return { icon: Radio, unit: '', type: 'default' };
  }, []);

  // ── Step 2: Fetch live analytics data from Private Broker backend ──────────
  const fetchLiveData = useCallback(() => {
    if (!selectedDeviceId) return;

    const isOfficeControl = deviceMeta?.deviceType === 'office_control';
    const isMultiSensor = deviceMeta?.deviceType === 'multi_sensor';
    const isControlling = deviceMeta?.deviceType === 'controlling';

    const url = isOfficeControl
      ? `${API_BASE}/api/devices/${selectedDeviceId}/analytics?room=both`
      : `${API_BASE}/api/devices/${selectedDeviceId}/analytics`;
    const headers = token ? { Authorization: `Bearer ${token}` } : {};

    fetch(url, { headers })
      .then((res) => res.json())
      .then((result) => {
        const channel = result?.channel || {};
        const feeds = result?.feeds || [];
        const latestFeed = feeds[feeds.length - 1];

        // ── Special handling for Office Control (Room 1, 2, 3) ──
        if (isOfficeControl) {
          const room1Feeds = feeds.filter(f => f.room === 'room1' || !f.room);
          const room2Feeds = feeds.filter(f => f.room === 'room2');
          const room3Feeds = feeds.filter(f => f.room === 'room3');

          const latestR1 = room1Feeds[room1Feeds.length - 1];
          const latestR2 = room2Feeds[room2Feeds.length - 1];
          const latestR3 = room3Feeds[room3Feeds.length - 1];

          if (latestR1 || latestR2 || latestR3) {
            setOfficeControlData({
              1: latestR1 ? {
                soil: {
                  soil_temp: parseFloat(latestR1.field1) || 0,
                  moisture: parseFloat(latestR1.field2) || 0,
                  ec: parseFloat(latestR1.field3) || 0,
                  ph: parseFloat(latestR1.field4) || 0,
                },
                room: {
                  room_temp: parseFloat(latestR1.field5) || 0,
                  room_humi: parseFloat(latestR1.field6) || 0,
                },
                orp: parseFloat(latestR1.field7) || 0,
                co2: parseFloat(latestR1.field8) || 0,
              } : null,
              2: latestR2 ? {
                soil: {
                  soil_temp: parseFloat(latestR2.field1) || 0,
                  moisture: parseFloat(latestR2.field2) || 0,
                  ec: parseFloat(latestR2.field3) || 0,
                  ph: parseFloat(latestR2.field4) || 0,
                },
                room: {
                  room_temp: parseFloat(latestR2.field5) || 0,
                  room_humi: parseFloat(latestR2.field6) || 0,
                },
                orp: parseFloat(latestR2.field7) || 0,
                co2: parseFloat(latestR2.field8) || 0,
              } : null,
              3: latestR3 ? {
                md02_1: {
                  room_temp: parseFloat(latestR3.field1) || 0,
                  room_humi: parseFloat(latestR3.field2) || 0,
                },
                md02_2: {
                  room_temp: parseFloat(latestR3.field3) || 0,
                  room_humi: parseFloat(latestR3.field4) || 0,
                },
                co2: parseFloat(latestR3.field8) || 0,
              } : null,
            });

            // Map chart history for each room
            const mapRoomHistory = (rFeeds, isRoom3 = false) => {
              if (isRoom3) {
                return {
                  md02_1_temp: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field1) || 0 })),
                  md02_1_humi: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field2) || 0 })),
                  md02_2_temp: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field3) || 0 })),
                  md02_2_humi: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field4) || 0 })),
                  co2: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field8) || 0 })),
                };
              }
              return {
                soil_temp: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field1) || 0 })),
                moisture: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field2) || 0 })),
                ec: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field3) || 0 })),
                ph: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field4) || 0 })),
                room_temp: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field5) || 0 })),
                room_humi: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field6) || 0 })),
                orp: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field7) || 0 })),
                co2: rFeeds.map(f => ({ time: new Date(f.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }), value: parseFloat(f.field8) || 0 })),
              };
            };

            setOfficeControlHistory({
              1: mapRoomHistory(room1Feeds, false),
              2: mapRoomHistory(room2Feeds, false),
              3: mapRoomHistory(room3Feeds, true),
            });
          }
        }

        let fields = Object.keys(channel)
          .filter((k) => k.startsWith('field') && channel[k] && !channel[k].startsWith('Field '))
          .map((k) => ({
            key: k,
            label: channel[k],
            ...getFieldDisplayInfo(channel[k]),
          }));

        if (fields.length === 0) {
          const isMonitType =
            deviceMeta?.deviceType === 'monit' ||
            deviceMeta?.deviceType === 'monnet' ||
            deviceMeta?.deviceType === 'dosing';
          const isAlmoraType =
            deviceMeta?.deviceType === 'almora' ||
            deviceMeta?.deviceType === 'almora2';

          if (isMonitType) {
            fields = [
              { key: 'field3', label: 'Water EC', icon: Zap, unit: 'mS/cm', type: 'ec' },
              { key: 'field4', label: 'Water pH', icon: FlaskConical, unit: 'pH', type: 'ph' },
              { key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            ];
          } else if (isAlmoraType) {
            fields = [
              { key: 'field1', label: 'Water Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field2', label: 'Soil Moisture', icon: Droplets, unit: '%', type: 'moisture' },
              { key: 'field3', label: 'Water pH', icon: FlaskConical, unit: 'pH', type: 'ph' },
              { key: 'field4', label: 'Water EC', icon: Zap, unit: 'mS/cm', type: 'ec' },
              { key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' },
              { key: 'field8', label: 'CO2 Level', icon: Activity, unit: 'ppm', type: 'co2' },
            ];
          } else {
            fields = [
              { key: 'field1', label: 'Temperature', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field2', label: 'Moisture / Humidity', icon: Droplets, unit: '%', type: 'moisture' },
              { key: 'field3', label: 'pH Level', icon: FlaskConical, unit: 'pH', type: 'ph' },
              { key: 'field4', label: 'EC Level', icon: Zap, unit: 'mS/cm', type: 'ec' },
              { key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            ];
          }
        }

        setActiveFields(fields);

        if (!latestFeed) {
          setLiveDevice({
            id: selectedDeviceId,
            name: deviceMeta?.name || 'Live Sensor Data',
            location: deviceMeta?.location || 'Private Broker Feed',
            status: deviceMeta?.status || 'offline',
            lastUpdated: deviceMeta?.lastUpdated || null,
          });
          setHasNewData(false);
          setLoading(false);
          return;
        }

        const lastUpdatedTime = new Date(latestFeed.created_at || Date.now());
        const diffMs = Date.now() - lastUpdatedTime.getTime();
        const isOnline = diffMs < 5 * 60 * 1000;

        const device = {
          id: selectedDeviceId,
          name: deviceMeta?.name || 'Live Sensor Data',
          location: deviceMeta?.location || 'Private Broker Feed',
          status: isOnline ? 'online' : 'offline',
          lastUpdated: latestFeed.created_at || new Date().toISOString(),
        };

        const currentMetrics = {};
        fields.forEach((f) => {
          currentMetrics[f.key] = parseFloat(latestFeed[f.key]) || 0;
        });

        const newChartData = {};
        fields.forEach((f) => {
          newChartData[f.key] = feeds.map((feed) => ({
            time: new Date(feed.created_at || Date.now()).toLocaleTimeString('en-US', {
              hour: '2-digit',
              minute: '2-digit',
            }),
            value: parseFloat(feed[f.key]) || 0,
          }));
        });

        const previousMetrics = previousMetricsRef.current;
        const changed =
          !previousMetrics ||
          Object.keys(currentMetrics).some((key) => currentMetrics[key] !== previousMetrics[key]);

        setHasNewData(changed);
        if (changed) {
          previousMetricsRef.current = currentMetrics;
          setLiveDevice(device);
          setActiveMetrics(currentMetrics);
          setChartData(newChartData);
        }

        setLoading(false);
      })
      .catch((error) => {
        console.error('API Error:', error);
        setLiveDevice(null);
        setHasNewData(false);
        setLoading(false);
      });
  }, [deviceMeta, selectedDeviceId, getFieldDisplayInfo, API_BASE, token]);

  useEffect(() => {
    if (selectedDeviceId) {
      setLoading(true);
      fetchLiveData();
      const interval = setInterval(fetchLiveData, 15000);
      return () => clearInterval(interval);
    }
  }, [fetchLiveData, selectedDeviceId]);

  // ── Step 3: High-Throughput Throttled Packet Processor (P1 + P2 Optimization) ──
  const targetMqttId = useMemo(() => {
    const isOfficeControl = deviceMeta?.deviceType === 'office_control';
    let id = deviceMeta?.mqttId;
    if (!id && isOfficeControl) id = 'system2';
    if (!id) id = deviceMeta?.name;
    if (!id) id = deviceMeta?.id || deviceMeta?._id || selectedDeviceId;
    return id;
  }, [deviceMeta, selectedDeviceId]);

  const candidateIdentifiers = useMemo(() => {
    return Array.from(
      new Set(
        [
          deviceMeta?.mqttId,
          deviceMeta?.name,
          deviceMeta?.deviceType === 'office_control' ? 'system2' : null,
          deviceMeta?.deviceType === 'controlling' ? 'controlling' : null,
          deviceMeta?.id,
          deviceMeta?._id,
          selectedDeviceId,
        ].filter(Boolean)
      )
    );
  }, [deviceMeta, selectedDeviceId]);

  const handleBatchedPackets = useCallback(
    (packets) => {
      if (!packets || packets.length === 0) return;

      const isMultiSensor = deviceMeta?.deviceType === 'multi_sensor';
      const isOfficeControl = deviceMeta?.deviceType === 'office_control';
      const isControlling = deviceMeta?.deviceType === 'controlling';

      // Iterate through EVERY packet in the batch so no room or probe is skipped
      packets.forEach((packet) => {
        if (!packet || !packet.data) return;

        const payload = packet.data;
        const topic = String(packet.topic || '').toLowerCase();
        const timeStr = packet.timestamp
          ? new Date(packet.timestamp).toLocaleTimeString('en-US', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            })
          : new Date().toLocaleTimeString('en-US', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            });

        if (isMultiSensor) {
          let normalizedSensors = {};
          if (payload.temp !== undefined || payload.hum !== undefined || payload.humi !== undefined) {
            normalizedSensors = {
              S1: {
                t: parseFloat(payload.temp ?? payload.t ?? 0) || 0,
                h: parseFloat(payload.hum ?? payload.humi ?? payload.h ?? 0) || 0,
                status: 'OK',
              },
            };
          } else {
            Object.keys(payload).forEach((k) => {
              const upperKey = k.toUpperCase();
              const probe = payload[k] || {};
              normalizedSensors[upperKey] = {
                t: parseFloat(probe.t ?? probe.temp ?? 0) || 0,
                h: parseFloat(probe.h ?? probe.hum ?? probe.humidity ?? probe.humi ?? 0) || 0,
                status: probe.status || 'OK',
              };
            });
          }

          setMultiSensorData((prev) => ({ ...prev, ...normalizedSensors }));
          setSensorHistory((prev) => {
            const newHist = { ...prev };
            Object.keys(normalizedSensors).forEach((sId) => {
              const prevState =
                newHist[sId] && !Array.isArray(newHist[sId]) ? newHist[sId] : { t: [], h: [] };
              newHist[sId] = {
                t: [...(prevState.t || []), normalizedSensors[sId].t].slice(-24),
                h: [...(prevState.h || []), normalizedSensors[sId].h].slice(-24),
              };
            });
            return newHist;
          });
        } else if (isOfficeControl) {
          const updateSingleRoom = (roomNum, roomPayload) => {
            if (!roomPayload) return;

            const s = roomPayload.sensors || {};
            const soil = roomPayload.soil || {};
            const room = roomPayload.room || {};

            let normalizedRoomData = null;
            let metrics = {};

            if (roomNum === 3) {
              const md1 = roomPayload.md02_1 || {};
              const md2 = roomPayload.md02_2 || {};
              const md1_t = md1.room_temp ?? md1.temp ?? roomPayload.md02_1_temp ?? 0;
              const md1_h = md1.room_humi ?? md1.humi ?? roomPayload.md02_1_humi ?? 0;
              const md2_t = md2.room_temp ?? md2.temp ?? roomPayload.md02_2_temp ?? 0;
              const md2_h = md2.room_humi ?? md2.humi ?? roomPayload.md02_2_humi ?? 0;
              const co2Val = roomPayload.co2 ?? s.co2 ?? 0;

              normalizedRoomData = {
                md02_1: { room_temp: parseFloat(md1_t) || 0, room_humi: parseFloat(md1_h) || 0 },
                md02_2: { room_temp: parseFloat(md2_t) || 0, room_humi: parseFloat(md2_h) || 0 },
                co2: parseFloat(co2Val) || 0,
              };

              metrics = {
                md02_1_temp: normalizedRoomData.md02_1.room_temp,
                md02_1_humi: normalizedRoomData.md02_1.room_humi,
                md02_2_temp: normalizedRoomData.md02_2.room_temp,
                md02_2_humi: normalizedRoomData.md02_2.room_humi,
                co2: normalizedRoomData.co2,
              };
            } else {
              const st = soil.soil_temp ?? s.soil_temp ?? roomPayload.soil_temp ?? roomPayload.temp ?? 0;
              const sm = soil.moisture ?? s.soil_moisture ?? roomPayload.moisture ?? roomPayload.humidity ?? 0;
              const sec = soil.ec ?? s.soil_ec ?? roomPayload.ec ?? 0;
              const sph = soil.ph ?? s.soil_ph ?? roomPayload.ph ?? 0;
              const rt = room.room_temp ?? s.room_temp ?? roomPayload.room_temp ?? 0;
              const rh = room.room_humi ?? s.room_humi ?? roomPayload.room_humi ?? 0;
              const orpVal = roomPayload.orp ?? s.orp ?? 0;
              const co2Val = roomPayload.co2 ?? s.co2 ?? 0;

              normalizedRoomData = {
                soil: {
                  soil_temp: parseFloat(st) || 0,
                  moisture: parseFloat(sm) || 0,
                  ec: parseFloat(sec) || 0,
                  ph: parseFloat(sph) || 0,
                },
                room: {
                  room_temp: parseFloat(rt) || 0,
                  room_humi: parseFloat(rh) || 0,
                },
                orp: parseFloat(orpVal) || 0,
                co2: parseFloat(co2Val) || 0,
              };

              metrics = {
                soil_temp: normalizedRoomData.soil.soil_temp,
                moisture: normalizedRoomData.soil.moisture,
                ec: normalizedRoomData.soil.ec,
                ph: normalizedRoomData.soil.ph,
                room_temp: normalizedRoomData.room.room_temp,
                room_humi: normalizedRoomData.room.room_humi,
                orp: normalizedRoomData.orp,
                co2: normalizedRoomData.co2,
              };
            }

            setOfficeControlData((prev) => ({ ...prev, [roomNum]: normalizedRoomData }));

            setOfficeControlHistory((prev) => {
              const roomHist = { ...(prev[roomNum] || {}) };
              Object.keys(metrics).forEach((key) => {
                const val =
                  metrics[key] !== undefined && metrics[key] !== null ? parseFloat(metrics[key]) : 0;
                roomHist[key] = [...(roomHist[key] || []), { time: timeStr, value: val }].slice(-24);
              });
              return { ...prev, [roomNum]: roomHist };
            });
          };

          // Check if payload is merged: { room1: {...}, room2: {...}, room3: {...} }
          if (payload.room1 || payload.room2 || payload.room3) {
            if (payload.room1) updateSingleRoom(1, payload.room1);
            if (payload.room2) updateSingleRoom(2, payload.room2);
            if (payload.room3) updateSingleRoom(3, payload.room3);
          } else {
            // Per-room topic: inhydro/{id}/room1/... or inhydro/{id}/room2/...
            let roomNum = 1;
            if (topic.includes('room3')) roomNum = 3;
            else if (topic.includes('room2')) roomNum = 2;
            else if (topic.includes('room1')) roomNum = 1;

            updateSingleRoom(roomNum, payload);
          }
        } else if (isControlling) {
          const tel = payload.telemetry || payload.sensors || payload || {};
          setControllingData(tel);

          setControllingHistory((prev) => {
            const nextHist = { ...prev };
            const metrics = {
              water_temp: tel.water_temp ?? tel.temp ?? 0,
              moisture: tel.moisture ?? tel.moist ?? 0,
              ec: tel.ec ?? 0,
              ph: tel.ph ?? 0,
              room_temp: tel.room_temp ?? 0,
              room_humi: tel.room_humi ?? 0,
              orp: tel.orp ?? 0,
              co2: tel.co2 ?? 0,
              vpd: tel.vpd ?? 0,
              dli: tel.dli ?? 0,
              wind_speed: tel.wind_speed ?? 0,
              wind_dir: tel.wind_dir ?? 0,
              do: tel.do ?? 0,
              ppfd: tel.ppfd ?? 0,
              n: tel.n ?? 0,
              p: tel.p ?? 0,
              k: tel.k ?? 0,
            };
            Object.keys(metrics).forEach((key) => {
              const val =
                metrics[key] !== undefined && metrics[key] !== null ? parseFloat(metrics[key]) : 0;
              nextHist[key] = [...(nextHist[key] || []), { time: timeStr, value: val }].slice(-24);
            });
            return nextHist;
          });
        } else {
          const tel = payload.telemetry || payload.sensors || payload.data || payload || {};
          const tempVal =
            tel.field1 !== undefined
              ? parseFloat(tel.field1)
              : tel.temp !== undefined
              ? parseFloat(tel.temp)
              : tel.water_temp !== undefined
              ? parseFloat(tel.water_temp)
              : tel.soil_temp !== undefined
              ? parseFloat(tel.soil_temp)
              : tel.room_temp !== undefined
              ? parseFloat(tel.room_temp)
              : 0;
          const moistVal =
            tel.field2 !== undefined
              ? parseFloat(tel.field2)
              : tel.moist !== undefined
              ? parseFloat(tel.moist)
              : tel.moisture !== undefined
              ? parseFloat(tel.moisture)
              : tel.humidity !== undefined
              ? parseFloat(tel.humidity)
              : tel.room_humi !== undefined
              ? parseFloat(tel.room_humi)
              : 0;
          const phVal =
            tel.field3 !== undefined
              ? parseFloat(tel.field3)
              : tel.ph !== undefined
              ? parseFloat(tel.ph)
              : tel.soil_ph !== undefined
              ? parseFloat(tel.soil_ph)
              : 0;
          const ecVal =
            tel.field4 !== undefined
              ? parseFloat(tel.field4)
              : tel.ec !== undefined
              ? parseFloat(tel.ec)
              : tel.soil_ec !== undefined
              ? parseFloat(tel.soil_ec)
              : 0;
          const roomTempVal =
            tel.field5 !== undefined
              ? parseFloat(tel.field5)
              : tel.room_temp !== undefined
              ? parseFloat(tel.room_temp)
              : 0;
          const roomHumiVal =
            tel.field6 !== undefined
              ? parseFloat(tel.field6)
              : tel.room_humi !== undefined
              ? parseFloat(tel.room_humi)
              : 0;
          const orpVal =
            tel.field7 !== undefined
              ? parseFloat(tel.field7)
              : tel.orp !== undefined
              ? parseFloat(tel.orp)
              : 0;
          const co2Val =
            tel.field8 !== undefined
              ? parseFloat(tel.field8)
              : tel.co2 !== undefined
              ? parseFloat(tel.co2)
              : 0;

          const isMonitType =
            deviceMeta?.deviceType === 'monit' ||
            deviceMeta?.deviceType === 'monnet' ||
            deviceMeta?.deviceType === 'dosing';

          const isAlmoraType =
            deviceMeta?.deviceType === 'almora' ||
            deviceMeta?.deviceType === 'almora2';

          let currentMetrics = {};
          let fields = [];

          if (isMonitType) {
            currentMetrics = { field3: ecVal, field4: phVal, field5: roomTempVal, field6: roomHumiVal };
            fields = [
              { key: 'field3', label: 'Water EC', icon: Zap, unit: 'mS/cm', type: 'ec' },
              { key: 'field4', label: 'Water pH', icon: FlaskConical, unit: 'pH', type: 'ph' },
              { key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            ];
          } else if (isAlmoraType) {
            currentMetrics = {
              field1: tempVal,
              field2: moistVal,
              field3: phVal,
              field4: ecVal,
              field5: roomTempVal,
              field6: roomHumiVal,
              field8: co2Val,
            };
            fields = [
              { key: 'field1', label: 'Water Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field2', label: 'Soil Moisture', icon: Droplets, unit: '%', type: 'moisture' },
              { key: 'field3', label: 'Water pH', icon: FlaskConical, unit: 'pH', type: 'ph' },
              { key: 'field4', label: 'Water EC', icon: Zap, unit: 'mS/cm', type: 'ec' },
              { key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            ];
            if (co2Val > 0 || tel.co2 !== undefined || deviceMeta?.name?.toLowerCase().includes('co2')) {
              fields.push({ key: 'field8', label: 'CO2 Level', icon: Activity, unit: 'ppm', type: 'co2' });
            }
          } else {
            currentMetrics = {
              field1: tempVal,
              field2: moistVal,
              field3: phVal,
              field4: ecVal,
              field5: roomTempVal,
              field6: roomHumiVal,
            };
            fields = [
              { key: 'field1', label: 'Temperature', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field2', label: 'Moisture / Humidity', icon: Droplets, unit: '%', type: 'moisture' },
              { key: 'field3', label: 'pH Level', icon: FlaskConical, unit: 'pH', type: 'ph' },
              { key: 'field4', label: 'EC Level', icon: Zap, unit: 'mS/cm', type: 'ec' },
            ];
            if (roomTempVal > 0 || roomHumiVal > 0) {
              fields.push(
                { key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
                { key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' }
              );
            }
          }

          setActiveFields(fields);
          setActiveMetrics(currentMetrics);

          setChartData((prev) => {
            const newChart = { ...prev };
            fields.forEach((f) => {
              newChart[f.key] = [
                ...(newChart[f.key] || []),
                { time: timeStr, value: currentMetrics[f.key] ?? 0 },
              ].slice(-24);
            });
            return newChart;
          });
        }
      });

      setLiveDevice({
        id: selectedDeviceId,
        name: deviceMeta?.name || 'Live Sensor Data',
        location: deviceMeta?.location || 'Private Broker Stream',
        status: 'online',
        lastUpdated: new Date().toISOString(),
      });

      setLoading(false);
      setHasNewData(true);
      if (newDataTimeoutRef.current) clearTimeout(newDataTimeoutRef.current);
      newDataTimeoutRef.current = setTimeout(() => {
        setHasNewData(false);
        newDataTimeoutRef.current = null;
      }, 2000);
    },
    [deviceMeta, selectedDeviceId]
  );

  // ── Step 3A: Direct Private Broker MQTT Connection (WebSocket fallback/fast-path) ──
  useEffect(() => {
    if (!selectedDeviceId || candidateIdentifiers.length === 0) return;

    let client = null;

    try {
      client = createMqttClient();

      client.on('connect', () => {
        setIsMqttConnected(true);
        candidateIdentifiers.forEach((id) => {
          if (!id) return;
          client.subscribe(`inhydro/${id}/#`, { qos: 0 });
        });
      });

      client.on('message', (topic, message) => {
        try {
          const payloadData = JSON.parse(message.toString());
          const parts = topic.split('/');
          const mqttId = parts[1] || '';
          handleBatchedPackets([
            {
              deviceId: selectedDeviceId,
              mqttId,
              topic,
              data: payloadData,
              timestamp: new Date(),
            },
          ]);
        } catch (e) {
          // ignore non-json messages
        }
      });

      client.on('close', () => setIsMqttConnected(false));
      client.on('error', () => setIsMqttConnected(false));
    } catch (err) {
      console.warn('[LiveMonitoring] Direct MQTT client connection skipped:', err);
    }

    return () => {
      if (client) {
        try {
          client.end(true);
        } catch (e) {}
      }
      setIsMqttConnected(false);
    };
  }, [selectedDeviceId, candidateIdentifiers, handleBatchedPackets]);

  // ── Step 3B: Server-Sent Events (SSE) Stream Bridge ──
  const { isConnected: isStreamConnected } = useThrottledStream(
    API_BASE,
    {
      deviceId: selectedDeviceId,
      mqttId: targetMqttId,
      devices: candidateIdentifiers.join(','),
    },
    300,
    handleBatchedPackets
  );

  const handleRefresh = () => {
    setLoading(true);
    fetchLiveData();
  };

  // ── Loading State ──────────────────────────────────────────────────────────
  if (initLoading) {
    return (
      <div className="space-y-6">
        <div className="space-y-4">
          {[...Array(4)].map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      </div>
    );
  }

  // ── No devices at all ──────────────────────────────────────────────────────
  if (allDevices.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <div className="rounded-2xl border border-yellow-500/30 bg-yellow-500/10 p-8 text-center max-w-md">
          <Cpu className="h-12 w-12 text-yellow-400 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-white mb-2">No Devices Found</h3>
          <p className="text-sm text-slate-400">
            Add devices in the <strong>Devices</strong> page to start monitoring.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Header with Device Dropdown ────────────────────────────────────── */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          {/* Device Selector Dropdown */}
          <div className="relative">
            <select
              value={selectedDeviceId}
              onChange={(e) => handleDeviceChange(e.target.value)}
              className="appearance-none rounded-xl border border-slate-700 bg-slate-800 pl-4 pr-10 py-2.5 text-sm font-medium text-white outline-none focus:border-green-500 focus:ring-2 focus:ring-green-500/20 cursor-pointer transition-all min-w-[220px]"
            >
              <option value="" disabled>
                Select a device...
              </option>
              {allDevices.map((d) => (
                <option key={d._id} value={d._id}>
                  {d.name} — {d.location}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500 pointer-events-none" />
          </div>

          {/* Status Badge */}
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider ${
              deviceMeta?.status === 'blocked'
                ? 'border-red-500/30 bg-red-500/10 text-red-400'
                : isDeviceOnline
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                : 'border-rose-500/30 bg-rose-500/10 text-rose-400'
            }`}
            title={`Device Status: ${deviceMeta?.status === 'blocked' ? 'Blocked' : isDeviceOnline ? 'Online' : 'Offline'}${isMqttConnected ? ' (Broker Live)' : ''}`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                deviceMeta?.status === 'blocked'
                  ? 'bg-red-400'
                  : isDeviceOnline
                  ? 'bg-emerald-400 animate-pulse-dot'
                  : 'bg-rose-400'
              }`}
            />
            {deviceMeta?.status === 'blocked'
              ? 'Blocked'
              : isDeviceOnline
              ? 'Online'
              : 'Offline'}
          </span>
        </div>

        {/* Right: Refresh & Status */}
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <Clock className="h-3.5 w-3.5" />
          Last updated: {liveDevice?.lastUpdated ? formatTimestamp(liveDevice.lastUpdated) : '--'}
          <button
            onClick={handleRefresh}
            className="rounded-lg border border-slate-700 p-1.5 transition-colors hover:bg-slate-800 hover:text-white"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <span
            className={`rounded-full border px-2.5 py-1 font-medium ${
              hasNewData
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                : 'border-slate-700 bg-slate-800 text-slate-400'
            }`}
          >
            {hasNewData ? 'Updated' : 'No change'}
          </span>
        </div>
      </div>

      {/* ── Office Control Dual-Room Live View ───────────────────────────── */}
      {deviceMeta?.deviceType === 'office_control' && (
        <div className="space-y-6">
          {/* Room Selection Tabs */}
          <div className="flex border-b border-slate-700/60 pb-px">
            {[1, 2, 3].map((room) => (
              <button
                key={room}
                onClick={() => setActiveRoomTab(room)}
                className={`relative px-6 py-3.5 text-sm font-semibold transition-all hover:text-white ${
                  activeRoomTab === room ? 'text-green-400' : 'text-slate-400'
                }`}
              >
                Room {room} Control
                {activeRoomTab === room && (
                  <motion.div
                    layoutId="activeRoomTabIndicator"
                    className="absolute bottom-0 left-0 right-0 h-0.5 bg-green-500"
                  />
                )}
              </button>
            ))}
          </div>

          {/* Main 8-Box Grid and Trend Charts */}
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            {/* Left: 8 Sensor Grid Boxes */}
            <div className="space-y-4 xl:col-span-1">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                Live Readings (Room {activeRoomTab})
              </h3>
              {!officeControlData[activeRoomTab] && loading ? (
                <div className="space-y-4">
                  {[...Array(8)].map((_, i) => (
                    <SkeletonCard key={i} />
                  ))}
                </div>
              ) : !officeControlData[activeRoomTab] ? (
                <div className="rounded-2xl border border-dashed border-slate-700/50 p-6 text-sm text-slate-400 text-center">
                  <div className="animate-pulse mb-2 text-green-500 font-medium">
                    Waiting for Live Device Stream...
                  </div>
                  <div className="text-xs text-slate-500">
                    Please start control.py on your device to stream real-time data.
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-2 xl:grid-cols-1">
                  {activeRoomTab === 3 ? (
                    <>
                      <BigMetric
                        label="MD02 #1 Temp"
                        value={officeControlData[activeRoomTab]?.md02_1?.room_temp}
                        unit="°C"
                        icon={Thermometer}
                        type="temperature"
                      />
                      <BigMetric
                        label="MD02 #1 Humi"
                        value={officeControlData[activeRoomTab]?.md02_1?.room_humi}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                      />
                      <BigMetric
                        label="MD02 #2 Temp"
                        value={officeControlData[activeRoomTab]?.md02_2?.room_temp}
                        unit="°C"
                        icon={Thermometer}
                        type="temperature"
                      />
                      <BigMetric
                        label="MD02 #2 Humi"
                        value={officeControlData[activeRoomTab]?.md02_2?.room_humi}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                      />
                      <BigMetric
                        label="CO2 Level"
                        value={officeControlData[activeRoomTab]?.co2}
                        unit="ppm"
                        icon={Activity}
                        type="co2"
                      />
                    </>
                  ) : (
                    <>
                      <BigMetric
                        label="Soil Temp"
                        value={officeControlData[activeRoomTab]?.soil?.soil_temp}
                        unit="°C"
                        icon={Thermometer}
                        type="temperature"
                      />
                      <BigMetric
                        label="Soil Moisture"
                        value={officeControlData[activeRoomTab]?.soil?.moisture}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                      />
                      <EcMetricCard
                        label="Soil EC"
                        ecVal={officeControlData[activeRoomTab]?.soil?.ec}
                      />
                      <BigMetric
                        label="Soil pH"
                        value={officeControlData[activeRoomTab]?.soil?.ph}
                        unit="pH"
                        icon={FlaskConical}
                        type="ph"
                      />
                      <BigMetric
                        label="Room Temp"
                        value={officeControlData[activeRoomTab]?.room?.room_temp}
                        unit="°C"
                        icon={Thermometer}
                        type="temperature"
                      />
                      <BigMetric
                        label="Room Humidity"
                        value={officeControlData[activeRoomTab]?.room?.room_humi}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                      />
                      <BigMetric
                        label="ORP Level"
                        value={officeControlData[activeRoomTab]?.orp}
                        unit="mV"
                        icon={Activity}
                        type="default"
                      />
                      <BigMetric
                        label="CO2 Level"
                        value={officeControlData[activeRoomTab]?.co2}
                        unit="ppm"
                        icon={Activity}
                        type="co2"
                      />
                    </>
                  )}
                </div>
              )}
            </div>

            {/* Right: Real-time Charts */}
            <div className="space-y-4 xl:col-span-2">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                Trend Charts
              </h3>
              {!officeControlData[activeRoomTab] && loading ? (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {[...Array(8)].map((_, i) => (
                    <div key={i} className="rounded-2xl border border-slate-700/30 bg-slate-800/30 p-4">
                      <div className="skeleton mb-4 h-4 w-32 rounded" />
                      <div className="skeleton h-48 w-full rounded-xl" />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {activeRoomTab === 3 ? (
                    <>
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.md02_1_temp || []}
                        type="temperature"
                        title="MD02 #1 Temp Trend"
                        unit="°C"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.md02_1_humi || []}
                        type="moisture"
                        title="MD02 #1 Humi Trend"
                        unit="%"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.md02_2_temp || []}
                        type="temperature"
                        title="MD02 #2 Temp Trend"
                        unit="°C"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.md02_2_humi || []}
                        type="moisture"
                        title="MD02 #2 Humi Trend"
                        unit="%"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.co2 || []}
                        type="moisture"
                        title="CO2 Level Trend"
                        unit="ppm"
                      />
                    </>
                  ) : (
                    <>
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.soil_temp || []}
                        type="temperature"
                        title="Soil Temperature Trend"
                        unit="°C"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.moisture || []}
                        type="moisture"
                        title="Moisture Trend"
                        unit="%"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.ec || []}
                        type="ec"
                        title="Soil EC Trend"
                        unit="mS/cm"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.ph || []}
                        type="ph"
                        title="Soil pH Trend"
                        unit="pH"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.room_temp || []}
                        type="temperature"
                        title="Room Temperature Trend"
                        unit="°C"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.room_humi || []}
                        type="moisture"
                        title="Room Humidity Trend"
                        unit="%"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.orp || []}
                        type="temperature"
                        title="ORP Level Trend"
                        unit="mV"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.co2 || []}
                        type="moisture"
                        title="CO2 Level Trend"
                        unit="ppm"
                      />
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── InHydro Controller (controlling.py) Live View ───────────────────────────── */}
      {deviceMeta?.deviceType === 'controlling' && (() => {
        const controllingMetricsConfig = [
          { key: 'water_temp', label: 'Water Temperature', unit: '°C', icon: Thermometer, type: 'temperature' },
          { key: 'moisture', label: 'Moisture / Humidity', unit: '%', icon: Droplets, type: 'moisture' },
          { key: 'ph', label: 'pH Level', unit: 'pH', icon: FlaskConical, type: 'ph' },
          { key: 'room_temp', label: 'Room Temperature', unit: '°C', icon: Thermometer, type: 'temperature' },
          { key: 'room_humi', label: 'Room Humidity', unit: '%', icon: Droplets, type: 'moisture' },
          { key: 'orp', label: 'ORP Level', unit: 'mV', icon: Activity, type: 'default' },
          { key: 'co2', label: 'CO2 Level', unit: 'ppm', icon: Activity, type: 'co2' },
          { key: 'vpd', label: 'VPD', unit: 'kPa', icon: Activity, type: 'default' },
          { key: 'dli', label: 'DLI', unit: 'mol/m²/d', icon: Activity, type: 'default' },
          { key: 'wind_speed', label: 'Wind Speed', unit: 'm/s', icon: Activity, type: 'default' },
          { key: 'wind_dir', label: 'Wind Direction', unit: '°', icon: Activity, type: 'default' },
          { key: 'do', label: 'Dissolved Oxygen (DO)', unit: 'mg/L', icon: Activity, type: 'default' },
          { key: 'ppfd', label: 'PPFD', unit: 'µmol/m²/s', icon: Activity, type: 'default' },
          { key: 'n', label: 'Nitrogen (N)', unit: 'mg/kg', icon: Activity, type: 'default' },
          { key: 'p', label: 'Phosphorus (P)', unit: 'mg/kg', icon: Activity, type: 'default' },
          { key: 'k', label: 'Potassium (K)', unit: 'mg/kg', icon: Activity, type: 'default' },
        ];

        return (
          <div className="space-y-6">
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
              {/* Left: Sensor Grid Boxes */}
              <div className="space-y-4 xl:col-span-1">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                  Live Readings
                </h3>

                {!controllingData && loading ? (
                  <div className="space-y-4">
                    {[...Array(17)].map((_, i) => (
                      <SkeletonCard key={i} />
                    ))}
                  </div>
                ) : !controllingData ? (
                  <div className="rounded-2xl border border-dashed border-slate-700/50 p-6 text-sm text-slate-400 text-center">
                    <div className="animate-pulse mb-2 text-green-500 font-medium">
                      Waiting for Live Device Stream...
                    </div>
                    <div className="text-xs text-slate-500">
                      Please start controlling.py on your device to stream real-time data.
                    </div>
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-4 sm:grid-cols-2 xl:grid-cols-1">
                    <EcMetricCard
                      label="Electrical Conductivity (EC)"
                      ecVal={controllingData?.ec}
                    />

                    {controllingMetricsConfig.map((m) => (
                      <BigMetric
                        key={m.key}
                        label={m.label}
                        value={controllingData?.[m.key]}
                        unit={m.unit}
                        icon={m.icon}
                        type={m.type}
                      />
                    ))}
                  </div>
                )}
              </div>

              {/* Right: Real-time Charts */}
              <div className="space-y-4 xl:col-span-2">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                  Trend Charts
                </h3>
                {!controllingData && loading ? (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    {[...Array(17)].map((_, i) => (
                      <div key={i} className="rounded-2xl border border-slate-700/30 bg-slate-800/30 p-4">
                        <div className="skeleton mb-4 h-4 w-32 rounded" />
                        <div className="skeleton h-48 w-full rounded-xl" />
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <LiveChart
                      data={controllingHistory?.ec || []}
                      type="ec"
                      title="EC Trend"
                      unit="mS/cm"
                    />
                    {controllingMetricsConfig.map((m) => (
                      <LiveChart
                        key={m.key}
                        data={controllingHistory?.[m.key] || []}
                        type={m.type}
                        title={`${m.label} Trend`}
                        unit={m.unit}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })()}

      {/* ── Multi-Sensor Cold Storage Matrix ───────────────────────────────── */}
      {deviceMeta?.deviceType === 'multi_sensor' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
              7-Sensor Matrix
            </h3>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-slate-500">Sort by:</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1 text-[10px] text-white outline-none"
              >
                <option value="id">Position</option>
                <option value="temp">Temperature</option>
                <option value="humi">Humidity</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Object.entries(multiSensorData)
              .sort(([idA, dataA], [idB, dataB]) => {
                if (sortBy === 'temp') return (dataB.t || 0) - (dataA.t || 0);
                if (sortBy === 'humi') return (dataB.h || 0) - (dataA.h || 0);
                return idA.localeCompare(idB);
              })
              .map(([sensorId, data]) => (
                <ColdRoomProbeCard
                  key={sensorId}
                  sensorId={sensorId}
                  data={data}
                  history={sensorHistory?.[sensorId] || { t: [], h: [] }}
                  onSelect={setSelectedSensor}
                />
              ))}
          </div>

          {Object.keys(multiSensorData).length === 0 && !loading && (
            <div className="py-12 text-center text-slate-500 text-sm italic">
              Waiting for the sensor to be online...
            </div>
          )}
        </div>
      )}

      {/* ── Multi-Sensor Sensor Detail Modal ─────────────────────────────── */}
      {selectedSensor && multiSensorData[selectedSensor] && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="w-full max-w-4xl bg-slate-900 border border-slate-700 rounded-3xl p-6 sm:p-8 shadow-2xl relative overflow-y-auto max-h-[90vh]"
          >
            <button
              onClick={() => setSelectedSensor(null)}
              className="absolute top-4 right-4 text-slate-500 hover:text-white"
            >
              ✕ Close
            </button>
            <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 mb-6 sm:mb-8 mt-2 sm:mt-0">
              <div className="p-3 sm:p-4 bg-blue-500/10 rounded-2xl shrink-0">
                <Cpu className="h-6 w-6 sm:h-8 sm:w-8 text-blue-400" />
              </div>
              <div className="min-w-0">
                <h2 className="text-xl sm:text-2xl font-bold text-white uppercase tracking-wider truncate">
                  {`Cold Room ${selectedSensor.toUpperCase().replace('S', '')}`}
                </h2>
                <span className="text-xs text-slate-400 block truncate">
                  Live Telemetry Analysis — {formatTimestamp(liveDevice?.lastUpdated)}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6 sm:mb-8">
              <div className="bg-slate-800/50 p-4 sm:p-6 rounded-2xl border border-slate-700 flex flex-col justify-center">
                <p className="text-xs sm:text-sm text-slate-400 mb-1 sm:mb-2">Live Temperature</p>
                <p className="text-2xl sm:text-3xl font-bold text-white truncate">
                  {multiSensorData[selectedSensor]?.t != null ? multiSensorData[selectedSensor].t.toFixed(2) : '--'} °C
                </p>
              </div>
              <div className="bg-slate-800/50 p-4 sm:p-6 rounded-2xl border border-slate-700 flex flex-col justify-center">
                <p className="text-xs sm:text-sm text-slate-400 mb-1 sm:mb-2">Live Humidity</p>
                <p className="text-2xl sm:text-3xl font-bold text-blue-400 truncate">
                  {multiSensorData[selectedSensor]?.h != null ? multiSensorData[selectedSensor].h.toFixed(2) : '--'} %
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <LiveChart
                data={(sensorHistory?.[selectedSensor]?.t || []).map((v, i) => ({
                  time: i,
                  value: v,
                }))}
                type="temperature"
                title="Temperature History"
                unit="°C"
              />
              <LiveChart
                data={(sensorHistory?.[selectedSensor]?.h || []).map((v, i) => ({
                  time: i,
                  value: v,
                }))}
                type="moisture"
                title="Humidity History"
                unit="%"
              />
            </div>
          </motion.div>
        </div>
      )}

      {/* ── Standard Single-Device Content Grid (Almora, Monit, System2) ──── */}
      {deviceMeta?.deviceType !== 'multi_sensor' &&
        deviceMeta?.deviceType !== 'office_control' &&
        deviceMeta?.deviceType !== 'controlling' && (
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            {/* Left: Big Metrics */}
            <div className="space-y-4 xl:col-span-1">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                Live Readings
              </h3>
              {loading ? (
                <div className="space-y-4">
                  {[...Array(activeFields.length || 4)].map((_, i) => (
                    <SkeletonCard key={i} />
                  ))}
                </div>
              ) : !liveDevice ? (
                <div className="rounded-2xl border border-dashed border-slate-700/50 p-6 text-sm text-slate-400">
                  No live device data available.
                </div>
              ) : (
                <div className="space-y-4">
                  {activeFields.map((f) => (
                    <BigMetric
                      key={f.key}
                      label={f.label}
                      value={activeMetrics[f.key]}
                      unit={f.unit}
                      icon={f.icon}
                      type={f.type}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Right: Charts */}
            <div className="space-y-4 xl:col-span-2">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                Trend Charts
              </h3>
              {loading ? (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {[...Array(activeFields.length || 4)].map((_, i) => (
                    <div
                      key={i}
                      className="rounded-2xl border border-slate-700/30 bg-slate-800/30 p-4"
                    >
                      <div className="skeleton mb-4 h-4 w-32 rounded" />
                      <div className="skeleton h-48 w-full rounded-xl" />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {activeFields.map((f) => (
                    <LiveChart
                      key={f.key}
                      data={chartData[f.key] || []}
                      type={f.type}
                      title={f.label}
                      unit={f.unit}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
    </div>
  );
};

export default LiveMonitoring;