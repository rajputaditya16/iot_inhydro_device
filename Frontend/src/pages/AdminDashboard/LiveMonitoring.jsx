import { useState, useEffect, useCallback, useRef, useMemo, memo, useTransition } from 'react';
import { useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Thermometer, Droplets, Zap, FlaskConical, RefreshCw, Clock, Radio, AlertTriangle, Cpu, ChevronDown, Activity } from 'lucide-react';
import LiveChart from '../../components/LiveChart';
import { SkeletonCard } from '../../components/Skeleton';
import { useAnimatedCounter } from '../../hooks/useAnimatedCounter';
import { getStatusBg, getStatusDot, getMetricStatus, getMetricColor, formatTimestamp } from '../../utils/helpers';

// Static Controlling Metrics Config defined outside component to prevent re-allocation on render
const CONTROLLING_METRICS_CONFIG = [
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
  { key: 'k', label: 'Potassium (K)', unit: 'mg/kg', icon: Activity, type: 'default' }
];

// Memoized BigMetric Component
const BigMetric = memo(({ label, value, unit, icon: Icon, type }) => {
  const safeValue = Number.isFinite(value) ? value : 0;
  const animated = useAnimatedCounter(safeValue, 150); // Reduced duration for faster numbers update
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
      className={`rounded-2xl border p-4 ${bgColorMap[color] || 'bg-slate-800/50 border-slate-700/50'} backdrop-blur-sm transition-colors`}
    >
      <div className="flex items-center gap-2.5">
        <div className={`rounded-lg p-1.5 ${color} bg-white/5`}>
          <Icon className="h-4 w-4" />
        </div>
        <span className="text-sm font-medium text-slate-400">{label}</span>
      </div>
      <div className="mt-3 flex items-baseline gap-1.5">
        <span className={`text-2xl font-bold tabular-nums ${color}`}>
          {safeValue === 0 ? '--' : animated.toFixed(1)}
        </span>
        <span className="text-sm text-slate-500">{unit}</span>
      </div>
      <div className="mt-1.5 flex items-center gap-1.5">
        <div className={`h-1.5 w-1.5 rounded-full ${status === 'normal' ? 'bg-emerald-400' : status === 'warning' ? 'bg-yellow-400' : status === 'critical' ? 'bg-red-400' : 'bg-slate-500'}`} />
        <span className="text-xs text-slate-500 capitalize">{status}</span>
      </div>
    </div>
  );
}, (prevProps, nextProps) => (
  prevProps.label === nextProps.label &&
  prevProps.value === nextProps.value &&
  prevProps.unit === nextProps.unit &&
  prevProps.type === nextProps.type
));

BigMetric.displayName = 'BigMetric';

// Memoized Multi-Sensor Card
const MultiSensorCard = memo(({ sensorId, data, historyData, sortBy, onSelect }) => {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      whileHover={{ y: -5 }}
      animate={{ opacity: 1, scale: 1 }}
      onClick={() => onSelect(sensorId)}
      className="rounded-2xl border border-slate-700 bg-slate-800/40 p-4 backdrop-blur-md cursor-pointer hover:border-blue-500/50 transition-all hover:bg-slate-800/60"
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="rounded-lg bg-blue-500/10 px-2 py-1 text-[10px] font-bold text-blue-400">
          {`Cold Room ${sensorId.toUpperCase().replace('S', '')}`}
        </span>
        <span className={`h-1.5 w-1.5 rounded-full ${data.status === 'OK' ? 'bg-emerald-500' : 'bg-red-500'}`} />
      </div>

      <div className="space-y-4">
        <div className="flex justify-between items-end">
          <div className="space-y-1">
            <p className="text-[10px] text-slate-500 flex items-center gap-1"><Thermometer className="h-3 w-3 " /> Temperature</p>
            <p className="text-xl font-bold text-white tabular-nums">{data.t?.toFixed(1) || '--'}<span className="text-xs font-normal text-slate-500 ml-0.5">°C</span></p>
          </div>
          <div className="space-y-1 text-right">
            <p className="text-[10px] text-slate-500 flex items-center gap-1 justify-end"><Droplets className="h-3 w-3 " /> Humidity</p>
            <p className="text-xl font-bold text-blue-400 tabular-nums">{data.h?.toFixed(1) || '--'}<span className="text-xs font-normal text-slate-500 ml-0.5">%</span></p>
          </div>
        </div>

        {/* Real-time Sparkline of Temperature */}
        <div className="h-12 w-full bg-slate-900/40 rounded-lg flex items-end gap-1 px-2 py-1.5 border border-slate-700/30">
          {(historyData?.t || [0]).map((val, i) => {
            const min = 10, max = 45;
            const h = Math.min(100, Math.max(10, ((val - min) / (max - min)) * 100));
            return (
              <div
                key={i}
                className={`w-full rounded-t transition-all duration-500 ${val > 30 ? 'bg-red-400' : 'bg-blue-400'}`}
                style={{ height: `${h}%` }}
              />
            );
          })}
        </div>
      </div>
    </motion.div>
  );
}, (prev, next) => (
  prev.sensorId === next.sensorId &&
  prev.sortBy === next.sortBy &&
  prev.data?.t === next.data?.t &&
  prev.data?.h === next.data?.h &&
  prev.data?.status === next.data?.status &&
  prev.historyData?.t === next.historyData?.t
));

MultiSensorCard.displayName = 'MultiSensorCard';

const LiveMonitoring = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [, startTransition] = useTransition();
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
  const lastTelemetryTimeRef = useRef(0);
  const pendingTelemetryRef = useRef([]);
  const throttleTimerRef = useRef(null);
  const hasNewDataTimerRef = useRef(null);

  // ── Multi-Sensor Live States ────────────────────────────────────────────────
  const [multiSensorData, setMultiSensorData] = useState({});
  const [sensorHistory, setSensorHistory] = useState({}); // { S1: [t1, t2...], S2: [...] }
  const [sortBy, setSortBy] = useState('id'); // 'id', 'temp', 'humi'
  const [selectedSensor, setSelectedSensor] = useState(null); // The sensor currently "clicked" for detail

  // ── Office Control Dual Room Live States ────────────────────────────────────
  const [officeControlData, setOfficeControlData] = useState({ 1: null, 2: null, 3: null });
  const [officeControlHistory, setOfficeControlHistory] = useState({
    1: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
    2: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
    3: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] }
  });
  const [activeRoomTab, setActiveRoomTab] = useState(1);

  // ── InHydro Controller Live States ──────────────────────────────────────────
  const [controllingData, setControllingData] = useState(null);
  const [controllingHistory, setControllingHistory] = useState({
    water_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [],
    vpd: [], dli: [], wind_speed: [], wind_dir: [], do: [], ppfd: [], n: [], p: [], k: []
  });
  const [controllingChartTab, setControllingChartTab] = useState('primary'); // 'primary', 'climate', 'nutrients', 'all'

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
        }
      } catch (err) {
        console.error('Failed to fetch devices', err);
      } finally {
        setInitLoading(false);
      }
    };
    fetchDevices();
  }, [token, API_BASE]);

  // ── Get current selected device meta ───────────────────────────────────────
  const deviceMeta = useMemo(() => {
    return allDevices.find(
      (d) => d._id === selectedDeviceId || d.id === selectedDeviceId
    );
  }, [allDevices, selectedDeviceId]);

  const deviceType = deviceMeta?.deviceType;
  const deviceMqttId = useMemo(() => {
    return deviceMeta?.mqttId || deviceMeta?.id || deviceMeta?._id || (deviceType === 'office_control' ? 'system2' : selectedDeviceId);
  }, [deviceMeta, deviceType, selectedDeviceId]);

  // Live status is ONLINE if telemetry came within last 30 seconds, otherwise OFFLINE
  const isDeviceOffline = liveDevice ? liveDevice.status === 'offline' : true;

  // ── Handle device change from dropdown ─────────────────────────────────────
  const handleDeviceChange = (newId) => {
    setSelectedDeviceId(newId);

    startTransition(() => {
      setSearchParams({ device: newId }, { replace: true });
      setLiveDevice({
        id: newId,
        name: deviceMeta?.name || 'Device',
        location: deviceMeta?.location || '',
        status: 'offline',
        lastUpdated: null,
      });
      setLoading(true);
      setHasNewData(true);
      previousMetricsRef.current = null;
      lastTelemetryTimeRef.current = 0;
      setChartData({});
      setActiveMetrics({});
      setActiveFields([]);
      setOfficeControlData({ 1: null, 2: null, 3: null });
      setOfficeControlHistory({
        1: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
        2: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
        3: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] }
      });
      setControllingData(null);
      setControllingHistory({
        water_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: []
      });
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

  // ── Step 2: Fetch initial analytics / historical data from backend ──────────
  const fetchLiveData = useCallback(() => {
    if (!selectedDeviceId) return;
    const url = `${API_BASE}/api/devices/${selectedDeviceId}/analytics`;
    const headers = token ? { Authorization: `Bearer ${token}` } : {};

    fetch(url, { headers })
      .then((res) => res.json())
      .then((result) => {
        const channel = result?.channel || {};
        const feeds = result?.feeds || [];
        const latestFeed = feeds[feeds.length - 1];

        let fields = Object.keys(channel)
          .filter((k) => k.startsWith('field') && channel[k])
          .map((k) => ({
            key: k,
            label: channel[k],
            ...getFieldDisplayInfo(channel[k]),
          }));

        if (fields.length === 0) {
          const isMonitType = deviceType === 'monit' || deviceType === 'dosing';
          fields = isMonitType ? [
            { key: 'field3', label: 'Water EC', icon: Zap, unit: 'mS/cm', type: 'ec' },
            { key: 'field4', label: 'Water pH', icon: FlaskConical, unit: 'pH', type: 'ph' },
            { key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
            { key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' },
          ] : [
            { key: 'field1', label: 'Temperature', icon: Thermometer, unit: '°C', type: 'temperature' },
            { key: 'field2', label: 'Moisture / Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            { key: 'field3', label: 'pH Level', icon: FlaskConical, unit: 'pH', type: 'ph' },
            { key: 'field4', label: 'EC Level', icon: Zap, unit: 'mS/cm', type: 'ec' },
          ];
        }

        setActiveFields(fields);

        const now = Date.now();
        const lastTime = lastTelemetryTimeRef.current;
        const recentlyStreamed = lastTime > 0 && (now - lastTime < 30000);

        if (!latestFeed) {
          setLiveDevice(prev => prev ? {
            ...prev,
            status: recentlyStreamed ? 'online' : 'offline',
          } : {
            id: selectedDeviceId,
            name: deviceMeta?.name || 'Live Sensor Data',
            location: deviceMeta?.location || 'Private Broker Feed',
            status: recentlyStreamed ? 'online' : 'offline',
            lastUpdated: deviceMeta?.lastUpdated || null,
          });
          setHasNewData(false);
          setLoading(false);
          return;
        }

        const lastUpdatedTime = new Date(latestFeed.created_at || Date.now());
        const diffMs = now - lastUpdatedTime.getTime();

        const isOnline = recentlyStreamed || (diffMs < 3 * 60 * 1000);

        const device = {
          id: selectedDeviceId,
          name: deviceMeta?.name || 'Live Sensor Data',
          location: deviceMeta?.location || 'Private Broker Feed',
          status: isOnline ? 'online' : 'offline',
          lastUpdated: latestFeed.created_at || new Date().toISOString(),
        };

        const currentMetrics = {};
        fields.forEach(f => {
          currentMetrics[f.key] = parseFloat(latestFeed[f.key]) || 0;
        });

        const newChartData = {};
        fields.forEach(f => {
          newChartData[f.key] = feeds.map(feed => ({
            time: new Date(feed.created_at || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
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
          setActiveMetrics(prev => ({ ...prev, ...currentMetrics }));
          setChartData(newChartData);
        }

        setLoading(false);
      })
      .catch((error) => {
        console.error('Analytics Fetch Error:', error);
        setLoading(false);
      });
  }, [deviceMeta, selectedDeviceId, deviceType, getFieldDisplayInfo, API_BASE, token]);

  useEffect(() => {
    const isSpecialType = deviceType === 'office_control' || deviceType === 'controlling' || deviceType === 'multi_sensor';
    if (selectedDeviceId) {
      setLoading(true);
      fetchLiveData();
      if (!isSpecialType) {
        const interval = setInterval(fetchLiveData, 20000);
        return () => clearInterval(interval);
      }
    }
  }, [fetchLiveData, selectedDeviceId, deviceType]);

  // ── Watchdog: Automatically flip status between ONLINE / OFFLINE based on live stream ──
  useEffect(() => {
    if (!selectedDeviceId) return;

    const watchdog = setInterval(() => {
      const now = Date.now();
      const lastTime = lastTelemetryTimeRef.current;
      // Strict rule: Online ONLY if telemetry received within last 30 seconds
      const isOnline = lastTime > 0 && (now - lastTime < 30000);

      setLiveDevice(prev => {
        const targetStatus = isOnline ? 'online' : 'offline';
        if (prev && prev.status === targetStatus) return prev;
        return {
          id: selectedDeviceId,
          name: deviceMeta?.name || prev?.name || 'Live Sensor Data',
          location: deviceMeta?.location || prev?.location || 'Private Broker Stream',
          status: targetStatus,
          lastUpdated: lastTime > 0 ? new Date(lastTime).toISOString() : (prev?.lastUpdated || null),
        };
      });
    }, 2000);

    return () => clearInterval(watchdog);
  }, [selectedDeviceId, deviceMeta?.name, deviceMeta?.location]);

  // ── Process Telemetry Packet (Core Data Processor for MQTT Stream) ─────────
  const processTelemetryPacket = useCallback((topic, payload) => {
    const isMultiSensor = deviceType === 'multi_sensor';
    const isOfficeControl = deviceType === 'office_control';
    const isControlling = deviceType === 'controlling';
    const isMonitType = deviceType === 'monit' || deviceType === 'dosing';

    if (isMultiSensor) {
      setMultiSensorData(prev => ({ ...prev, ...payload }));
      setSensorHistory(prev => {
        const newHist = { ...prev };
        Object.keys(payload).forEach(sId => {
          const prevState = newHist[sId] && !Array.isArray(newHist[sId]) ? newHist[sId] : { t: [], h: [] };
          newHist[sId] = {
            t: [...(prevState.t || []), payload[sId].t].slice(-20),
            h: [...(prevState.h || []), payload[sId].h].slice(-20)
          };
        });
        return newHist;
      });
    } else if (isOfficeControl) {
      // DEEP MERGE incoming room packet into existing officeControlData state so fields don't disappear
      setOfficeControlData(prev => {
        const nextState = { ...prev };
        if (payload.room1 || payload.room2 || payload.room3) {
          [1, 2, 3].forEach(r => {
            if (payload[`room${r}`]) {
              const prevRoom = prev[r] || {};
              const pRoom = payload[`room${r}`];
              nextState[r] = {
                ...prevRoom,
                ...pRoom,
                soil: { ...(prevRoom.soil || {}), ...(pRoom.soil || {}) },
                room: { ...(prevRoom.room || {}), ...(pRoom.room || {}) },
                md02_1: { ...(prevRoom.md02_1 || {}), ...(pRoom.md02_1 || {}) },
                md02_2: { ...(prevRoom.md02_2 || {}), ...(pRoom.md02_2 || {}) },
              };
            }
          });
        } else {
          const parts = topic.split('/');
          const roomPart = parts.find(p => p.startsWith('room'));
          const room = roomPart ? parseInt(roomPart.replace('room', '')) : 1;
          const prevRoom = prev[room] || {};
          nextState[room] = {
            ...prevRoom,
            ...payload,
            soil: { ...(prevRoom.soil || {}), ...(payload.soil || {}) },
            room: { ...(prevRoom.room || {}), ...(payload.room || {}) },
            md02_1: { ...(prevRoom.md02_1 || {}), ...(payload.md02_1 || {}) },
            md02_2: { ...(prevRoom.md02_2 || {}), ...(payload.md02_2 || {}) },
          };
        }
        return nextState;
      });

      const timeStr = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      setOfficeControlHistory(prev => {
        const parts = topic.split('/');
        const roomPart = parts.find(p => p.startsWith('room'));
        const room = roomPart ? parseInt(roomPart.replace('room', '')) : 1;

        const roomHist = { ...(prev[room] || {}) };
        let metrics = {};
        if (room === 3) {
          metrics = {
            md02_1_temp: payload.md02_1?.room_temp,
            md02_1_humi: payload.md02_1?.room_humi,
            md02_2_temp: payload.md02_2?.room_temp,
            md02_2_humi: payload.md02_2?.room_humi,
            co2: payload.co2
          };
        } else {
          metrics = {
            soil_temp: payload.soil?.soil_temp ?? payload.soil_temp,
            moisture: payload.soil?.moisture ?? payload.moisture,
            ec: payload.soil?.ec ?? payload.ec,
            ph: payload.soil?.ph ?? payload.ph,
            room_temp: payload.room?.room_temp ?? payload.room_temp,
            room_humi: payload.room?.room_humi ?? payload.room_humi,
            orp: payload.orp,
            co2: payload.co2
          };
        }
        Object.keys(metrics).forEach(key => {
          const rawVal = metrics[key];
          if (rawVal !== undefined && rawVal !== null && rawVal !== '') {
            const val = parseFloat(rawVal);
            if (!isNaN(val)) {
              roomHist[key] = [...(roomHist[key] || []), { time: timeStr, value: val }].slice(-24);
            }
          }
        });
        return { ...prev, [room]: roomHist };
      });
    } else if (isControlling) {
      const tel = payload.telemetry || payload || {};
      setControllingData(prev => ({
        ...(prev || {}),
        ...tel
      }));

      const timeStr = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      setControllingHistory(prev => {
        const nextHist = { ...prev };
        const metrics = {
          water_temp: tel.water_temp,
          moisture: tel.moisture,
          ec: tel.ec,
          ph: tel.ph,
          room_temp: tel.room_temp,
          room_humi: tel.room_humi,
          orp: tel.orp,
          co2: tel.co2,
          vpd: tel.vpd,
          dli: tel.dli,
          wind_speed: tel.wind_speed,
          wind_dir: tel.wind_dir,
          do: tel.do,
          ppfd: tel.ppfd,
          n: tel.n,
          p: tel.p,
          k: tel.k
        };
        Object.keys(metrics).forEach(key => {
          const rawVal = metrics[key];
          if (rawVal !== undefined && rawVal !== null && rawVal !== '') {
            const val = parseFloat(rawVal);
            if (!isNaN(val)) {
              nextHist[key] = [...(nextHist[key] || []), { time: timeStr, value: val }].slice(-24);
            }
          }
        });
        return nextHist;
      });
    } else {
      // Standard / General Private Broker Device
      const tel = payload.telemetry || payload.data || payload || {};
      const tempVal = tel.field1 !== undefined ? parseFloat(tel.field1) : (tel.temp !== undefined ? parseFloat(tel.temp) : (tel.water_temp !== undefined ? parseFloat(tel.water_temp) : (tel.room_temp !== undefined ? parseFloat(tel.room_temp) : 0)));
      const moistVal = tel.field2 !== undefined ? parseFloat(tel.field2) : (tel.moist !== undefined ? parseFloat(tel.moist) : (tel.moisture !== undefined ? parseFloat(tel.moisture) : (tel.humidity !== undefined ? parseFloat(tel.humidity) : (tel.room_humi !== undefined ? parseFloat(tel.room_humi) : 0))));
      const phVal = tel.field3 !== undefined ? parseFloat(tel.field3) : (tel.ph !== undefined ? parseFloat(tel.ph) : 0);
      const ecVal = tel.field4 !== undefined ? parseFloat(tel.field4) : (tel.ec !== undefined ? parseFloat(tel.ec) : 0);
      const roomTempVal = tel.field5 !== undefined ? parseFloat(tel.field5) : (tel.room_temp !== undefined ? parseFloat(tel.room_temp) : 0);
      const roomHumiVal = tel.field6 !== undefined ? parseFloat(tel.field6) : (tel.room_humi !== undefined ? parseFloat(tel.room_humi) : 0);

      const currentMetrics = isMonitType ? {
        field3: ecVal,
        field4: phVal,
        field5: roomTempVal,
        field6: roomHumiVal,
      } : {
        field1: tempVal,
        field2: moistVal,
        field3: phVal,
        field4: ecVal,
      };

      const fields = isMonitType ? [
        { key: 'field3', label: 'Water EC', icon: Zap, unit: 'mS/cm', type: 'ec' },
        { key: 'field4', label: 'Water pH', icon: FlaskConical, unit: 'pH', type: 'ph' },
        { key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
        { key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' },
      ] : [
        { key: 'field1', label: 'Temperature', icon: Thermometer, unit: '°C', type: 'temperature' },
        { key: 'field2', label: 'Moisture / Humidity', icon: Droplets, unit: '%', type: 'moisture' },
        { key: 'field3', label: 'pH Level', icon: FlaskConical, unit: 'pH', type: 'ph' },
        { key: 'field4', label: 'EC Level', icon: Zap, unit: 'mS/cm', type: 'ec' },
      ];

      setActiveFields(fields);
      setActiveMetrics(prev => ({ ...prev, ...currentMetrics }));

      const timeStr = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      setChartData(prev => {
        const newChart = { ...prev };
        fields.forEach(f => {
          newChart[f.key] = [...(newChart[f.key] || []), { time: timeStr, value: currentMetrics[f.key] }].slice(-24);
        });
        return newChart;
      });
    }

    lastTelemetryTimeRef.current = Date.now();
    setLiveDevice({
      id: selectedDeviceId,
      name: deviceMeta?.name || 'Live Sensor Data',
      location: deviceMeta?.location || 'Private Broker Stream',
      status: 'online',
      lastUpdated: new Date().toISOString(),
    });

    setLoading(false);

    if (hasNewDataTimerRef.current) clearTimeout(hasNewDataTimerRef.current);
    setHasNewData(true);
    hasNewDataTimerRef.current = setTimeout(() => setHasNewData(false), 2000);
  }, [deviceType, selectedDeviceId, deviceMeta?.name, deviceMeta?.location]);

  // ── Zero-Latency Instant Packet Processor ────────────────────────────────────
  const scheduleFlush = useCallback(() => {
    if (throttleTimerRef.current) return;
    throttleTimerRef.current = requestAnimationFrame(() => {
      throttleTimerRef.current = null;
      const packets = pendingTelemetryRef.current;
      if (packets.length === 0) return;

      pendingTelemetryRef.current = [];
      packets.forEach(p => {
        processTelemetryPacket(p.topic, p.payload);
      });
    });
  }, [processTelemetryPacket]);

  // ── Step 3: Private Broker SSE Real-Time Stream Hook ────────────────────────
  useEffect(() => {
    if (!selectedDeviceId) return;

    setLoading(true);

    const sseUrl = `${API_BASE}/api/devices/stream`;
    const eventSource = new EventSource(sseUrl);

    eventSource.onmessage = (event) => {
      try {
        const packet = JSON.parse(event.data);
        const mId = (deviceMqttId || '').toLowerCase();
        const devMqttId = (deviceMeta?.mqttId || '').toLowerCase();
        const dId = String(selectedDeviceId || '').toLowerCase();
        const pMqttId = String(packet.mqttId || '').toLowerCase();
        const pDevId = String(packet.deviceId || '').toLowerCase();
        const pTopic = String(packet.topic || '').toLowerCase();

        const isMatch =
          (mId && pMqttId === mId) ||
          (devMqttId && pMqttId === devMqttId) ||
          (dId && pDevId === dId) ||
          (mId && pTopic.includes(mId)) ||
          (devMqttId && pTopic.includes(devMqttId)) ||
          (dId && pTopic.includes(dId));

        if (isMatch) {
          pendingTelemetryRef.current.push({ topic: packet.topic, payload: packet.data });
          scheduleFlush();
        }
      } catch (e) {
        console.error('SSE packet parse error:', e);
      }
    };

    return () => {
      eventSource.close();
      if (throttleTimerRef.current) {
        cancelAnimationFrame(throttleTimerRef.current);
        throttleTimerRef.current = null;
      }
    };
  }, [deviceType, deviceMqttId, deviceMeta?.mqttId, selectedDeviceId, API_BASE, scheduleFlush]);

  const handleRefresh = () => {
    setLoading(true);
    fetchLiveData();
  };

  // ── Filtered Controlling Metrics Config for Charts ─────────────────────────
  const filteredControllingCharts = useMemo(() => {
    if (controllingChartTab === 'primary') {
      return CONTROLLING_METRICS_CONFIG.filter(m => ['water_temp', 'moisture', 'ph', 'room_temp', 'room_humi', 'co2'].includes(m.key));
    }
    if (controllingChartTab === 'climate') {
      return CONTROLLING_METRICS_CONFIG.filter(m => ['room_temp', 'room_humi', 'co2', 'vpd', 'dli', 'wind_speed', 'wind_dir'].includes(m.key));
    }
    if (controllingChartTab === 'nutrients') {
      return CONTROLLING_METRICS_CONFIG.filter(m => ['ph', 'do', 'n', 'p', 'k'].includes(m.key));
    }
    return CONTROLLING_METRICS_CONFIG;
  }, [controllingChartTab]);

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
              {allDevices.map((d) => {
                return (
                  <option key={d._id} value={d._id}>
                    {d.name} — {d.location}
                  </option>
                );
              })}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500 pointer-events-none" />
          </div>

          {/* Status Badge */}
          {liveDevice && (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider ${getStatusBg(liveDevice.status)}`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${getStatusDot(liveDevice.status)} ${liveDevice.status === 'online' ? 'animate-pulse-dot' : ''}`}
              />
              {liveDevice.status}
            </span>
          )}
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
            className={`rounded-full border px-2.5 py-1 font-medium ${hasNewData ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-slate-700 bg-slate-800 text-slate-400'}`}
          >
            {hasNewData ? 'Updated' : 'No change'}
          </span>
        </div>
      </div>

      {/* ── No device selected prompt ───────────────────────────────────── */}
      {!selectedDeviceId && (
        <div className="flex flex-col items-center justify-center py-20">
          <div className="rounded-2xl border border-slate-700/50 bg-slate-800/30 p-8 text-center max-w-md backdrop-blur-sm">
            <Cpu className="h-12 w-12 text-blue-400 mx-auto mb-4 animate-pulse" />
            <h3 className="text-lg font-semibold text-white mb-2">Select a Device</h3>
            <p className="text-sm text-slate-400">
              Please select a device from the dropdown above to start live real-time monitoring.
            </p>
          </div>
        </div>
      )}

      {/* ── Office Control Dual-Room Live View ───────────────────────────── */}
      {deviceType === 'office_control' && (
        <div className="space-y-6">
          {/* Room Selection Tabs */}
          <div className="flex border-b border-slate-700/60 pb-px">
            {[1, 2, 3].map((room) => (
              <button
                key={room}
                onClick={() => setActiveRoomTab(room)}
                className={`relative px-6 py-3.5 text-sm font-semibold transition-all hover:text-white ${activeRoomTab === room ? 'text-green-400' : 'text-slate-400'}`}
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
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Live Readings (Room {activeRoomTab})</h3>
              {!officeControlData[activeRoomTab] && isDeviceOffline ? (
                <div className="rounded-2xl border border-dashed border-rose-500/30 bg-rose-500/5 p-6 text-center">
                  <AlertTriangle className="h-8 w-8 text-rose-400 mx-auto mb-2" />
                  <div className="text-sm font-semibold text-white mb-1">Office Control Device Offline</div>
                  <div className="text-xs text-slate-400">Device is currently offline or not broadcasting telemetry.</div>
                </div>
              ) : !officeControlData[activeRoomTab] && loading ? (
                <div className="space-y-4">
                  {[...Array(4)].map((_, i) => (
                    <SkeletonCard key={i} />
                  ))}
                </div>
              ) : !officeControlData[activeRoomTab] ? (
                <div className="rounded-2xl border border-dashed border-slate-700/50 p-6 text-sm text-slate-400 text-center">
                  <div className="text-green-500 font-medium mb-1">Waiting for Live Device Stream...</div>
                  <div className="text-xs text-slate-500">Please start control.py on your device to stream real-time data.</div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-2 xl:grid-cols-1">
                  {activeRoomTab === 3 ? (
                    <>
                      <BigMetric
                        label="MD02 #1 Temp"
                        value={officeControlData[activeRoomTab].md02_1?.room_temp}
                        unit="°C"
                        icon={Thermometer}
                        type="temperature"
                      />
                      <BigMetric
                        label="MD02 #1 Humi"
                        value={officeControlData[activeRoomTab].md02_1?.room_humi}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                      />
                      <BigMetric
                        label="MD02 #2 Temp"
                        value={officeControlData[activeRoomTab].md02_2?.room_temp}
                        unit="°C"
                        icon={Thermometer}
                        type="temperature"
                      />
                      <BigMetric
                        label="MD02 #2 Humi"
                        value={officeControlData[activeRoomTab].md02_2?.room_humi}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                      />
                      <BigMetric
                        label="CO2 Level"
                        value={officeControlData[activeRoomTab].co2}
                        unit="ppm"
                        icon={Activity}
                        type="co2"
                      />
                    </>
                  ) : (
                    <>
                      <BigMetric
                        label=" Temp"
                        value={officeControlData[activeRoomTab].soil?.soil_temp ?? officeControlData[activeRoomTab].soil_temp}
                        unit="°C"
                        icon={Thermometer}
                        type="temperature"
                      />
                      <BigMetric
                        label="Moisture"
                        value={officeControlData[activeRoomTab].soil?.moisture ?? officeControlData[activeRoomTab].moisture}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                      />
                      {/* EC card */}
                      {(() => {
                        const ecVal = officeControlData[activeRoomTab].soil?.ec ?? officeControlData[activeRoomTab].ec;
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
                            className={`rounded-2xl border p-4 ${bgMap[ecColor] || 'bg-slate-800/50 border-slate-700/50'} backdrop-blur-sm`}
                          >
                            <div className="flex items-center gap-2.5">
                              <div className={`rounded-lg p-1.5 ${ecColor} bg-white/5`}>
                                <Zap className="h-4 w-4" />
                              </div>
                              <span className="text-sm font-medium text-slate-400"> EC</span>
                            </div>
                            <div className="mt-3 flex items-baseline gap-1.5 flex-wrap">
                              <span className={`text-2xl font-bold tabular-nums ${ecColor}`}>
                                {ecVal != null ? parseFloat(ecVal).toFixed(2) : '--'}
                              </span>
                              <span className="text-sm text-slate-500">mS/cm</span>
                              {tdsVal != null && (
                                <span className="text-sm text-slate-400 font-semibold">
                                  ({tdsVal} ppm)
                                </span>
                              )}
                            </div>
                            <div className="mt-1.5 flex items-center gap-1.5">
                              <div className={`h-1.5 w-1.5 rounded-full ${ecStatus === 'normal' ? 'bg-emerald-400' : ecStatus === 'warning' ? 'bg-yellow-400' : ecStatus === 'critical' ? 'bg-red-400' : 'bg-slate-500'}`} />
                              <span className="text-xs text-slate-500 capitalize">{ecStatus}</span>
                            </div>
                          </div>
                        );
                      })()}
                      <BigMetric
                        label="pH"
                        value={officeControlData[activeRoomTab].soil?.ph ?? officeControlData[activeRoomTab].ph}
                        unit="pH"
                        icon={FlaskConical}
                        type="ph"
                      />
                      <BigMetric
                        label="Room Temp"
                        value={officeControlData[activeRoomTab].room?.room_temp ?? officeControlData[activeRoomTab].room_temp}
                        unit="°C"
                        icon={Thermometer}
                        type="temperature"
                      />
                      <BigMetric
                        label="Room Humidity"
                        value={officeControlData[activeRoomTab].room?.room_humi ?? officeControlData[activeRoomTab].room_humi}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                      />
                      <BigMetric
                        label="ORP Level"
                        value={officeControlData[activeRoomTab].orp}
                        unit="mV"
                        icon={Activity}
                        type="default"
                      />
                      <BigMetric
                        label="CO2 Level"
                        value={officeControlData[activeRoomTab].co2}
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
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Trend Charts</h3>
              {isDeviceOffline ? (
                <div className="rounded-2xl border border-dashed border-slate-700/50 bg-slate-800/20 p-8 text-center text-slate-400 text-sm">
                  Trend charts unavailable while device is offline.
                </div>
              ) : !officeControlData[activeRoomTab] && loading ? (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {[...Array(4)].map((_, i) => (
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
                        data={officeControlHistory[activeRoomTab].md02_1_temp}
                        type="temperature"
                        title="MD02 #1 Temp Trend"
                        unit="°C"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].md02_1_humi}
                        type="moisture"
                        title="MD02 #1 Humi Trend"
                        unit="%"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].md02_2_temp}
                        type="temperature"
                        title="MD02 #2 Temp Trend"
                        unit="°C"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].md02_2_humi}
                        type="moisture"
                        title="MD02 #2 Humi Trend"
                        unit="%"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].co2}
                        type="moisture"
                        title="CO2 Level Trend"
                        unit="ppm"
                      />
                    </>
                  ) : (
                    <>
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].soil_temp}
                        type="temperature"
                        title="Temperature Trend"
                        unit="°C"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].moisture}
                        type="moisture"
                        title="Moisture Trend"
                        unit="%"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].ec}
                        type="ec"
                        title=" EC Trend"
                        unit="mS/cm"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].ph}
                        type="ph"
                        title=" pH Trend"
                        unit="pH"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].room_temp}
                        type="temperature"
                        title="Room Temperature Trend"
                        unit="°C"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].room_humi}
                        type="moisture"
                        title="Room Humidity Trend"
                        unit="%"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].orp}
                        type="temperature"
                        title="ORP Level Trend"
                        unit="mV"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab].co2}
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
      {deviceType === 'controlling' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            {/* Left: Sensor Grid Boxes */}
            <div className="space-y-4 xl:col-span-1">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Live Readings</h3>

              {!controllingData && isDeviceOffline ? (
                <div className="rounded-2xl border border-dashed border-rose-500/30 bg-rose-500/5 p-6 text-center">
                  <AlertTriangle className="h-8 w-8 text-rose-400 mx-auto mb-2" />
                  <div className="text-sm font-semibold text-white mb-1">Controller Device Offline</div>
                  <div className="text-xs text-slate-400">Device is currently offline. Start controlling.py to stream telemetry.</div>
                </div>
              ) : !controllingData && loading ? (
                <div className="space-y-4">
                  {[...Array(4)].map((_, i) => (
                    <SkeletonCard key={i} />
                  ))}
                </div>
              ) : !controllingData ? (
                <div className="rounded-2xl border border-dashed border-slate-700/50 p-6 text-sm text-slate-400 text-center">
                  <div className="text-green-500 font-medium mb-1">Waiting for Live Device Stream...</div>
                  <div className="text-xs text-slate-500">Please start controlling.py on your device to stream real-time data.</div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-2 xl:grid-cols-1">
                  {/* EC card */}
                  {(() => {
                    const ecVal = controllingData.ec;
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
                        className={`rounded-2xl border p-4 ${bgMap[ecColor] || 'bg-slate-800/50 border-slate-700/50'} backdrop-blur-sm`}
                      >
                        <div className="flex items-center gap-2.5">
                          <div className={`rounded-lg p-1.5 ${ecColor} bg-white/5`}>
                            <Zap className="h-4 w-4" />
                          </div>
                          <span className="text-sm font-medium text-slate-400">Electrical Conductivity (EC)</span>
                        </div>
                        <div className="mt-3 flex items-baseline gap-1.5 flex-wrap">
                          <span className={`text-2xl font-bold tabular-nums ${ecColor}`}>
                            {ecVal != null ? parseFloat(ecVal).toFixed(2) : '--'}
                          </span>
                          <span className="text-sm text-slate-500">mS/cm</span>
                          {tdsVal != null && (
                            <span className="text-sm text-slate-400 font-semibold font-mono">
                              ({tdsVal} ppm)
                            </span>
                          )}
                        </div>
                        <div className="mt-1.5 flex items-center gap-1.5">
                          <div className={`h-1.5 w-1.5 rounded-full ${ecStatus === 'normal' ? 'bg-emerald-400' : ecStatus === 'warning' ? 'bg-yellow-400' : ecStatus === 'critical' ? 'bg-red-400' : 'bg-slate-500'}`} />
                          <span className="text-xs text-slate-500 capitalize">{ecStatus}</span>
                        </div>
                      </div>
                    );
                  })()}

                  {CONTROLLING_METRICS_CONFIG.map(m => (
                    <BigMetric
                      key={m.key}
                      label={m.label}
                      value={controllingData[m.key]}
                      unit={m.unit}
                      icon={m.icon}
                      type={m.type}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Right: Real-time Charts with Category Selector */}
            <div className="space-y-4 xl:col-span-2">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Trend Charts</h3>
                <div className="flex flex-wrap gap-2">
                  {[
                    { id: 'primary', label: 'Primary Trends' },
                    { id: 'climate', label: 'Climate & Env' },
                    { id: 'nutrients', label: 'Nutrients & O₂' },
                    { id: 'all', label: 'All Charts' },
                  ].map((tab) => (
                    <button
                      key={tab.id}
                      onClick={() => setControllingChartTab(tab.id)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                        controllingChartTab === tab.id
                          ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                          : 'bg-slate-800 text-slate-400 border border-slate-700 hover:text-white'
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
              </div>

              {isDeviceOffline ? (
                <div className="rounded-2xl border border-dashed border-slate-700/50 bg-slate-800/20 p-8 text-center text-slate-400 text-sm">
                  Trend charts unavailable while device is offline.
                </div>
              ) : !controllingData && loading ? (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className="rounded-2xl border border-slate-700/30 bg-slate-800/30 p-4">
                      <div className="skeleton mb-4 h-4 w-32 rounded" />
                      <div className="skeleton h-48 w-full rounded-xl" />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {(controllingChartTab === 'primary' || controllingChartTab === 'nutrients' || controllingChartTab === 'all') && (
                    <LiveChart
                      data={controllingHistory.ec}
                      type="ec"
                      title="EC Trend"
                      unit="mS/cm"
                    />
                  )}
                  {filteredControllingCharts.map(m => (
                    <LiveChart
                      key={m.key}
                      data={controllingHistory[m.key]}
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
      )}

      {/* ── Multi-Sensor View ────────────────────────────────────────────── */}
      {deviceType === 'multi_sensor' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">7-Sensor Matrix</h3>
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
                <MultiSensorCard
                  key={sensorId}
                  sensorId={sensorId}
                  data={data}
                  historyData={sensorHistory[sensorId]}
                  sortBy={sortBy}
                  onSelect={setSelectedSensor}
                />
              ))}
          </div>

          {isDeviceOffline && Object.keys(multiSensorData).length === 0 && (
            <div className="rounded-2xl border border-dashed border-rose-500/30 bg-rose-500/5 p-8 text-center my-4">
              <AlertTriangle className="h-8 w-8 text-rose-400 mx-auto mb-2" />
              <div className="text-sm font-semibold text-white mb-1">Cold Storage Sensors Offline</div>
              <div className="text-xs text-slate-400">Sensors are currently offline or disconnected.</div>
            </div>
          )}

          {Object.keys(multiSensorData).length === 0 && !isDeviceOffline && !loading && (
            <div className="py-12 text-center text-slate-500 text-sm italic">
              Waiting for the sensor to be online...
            </div>
          )}
        </div>
      )}

      {/* ── Multi-Sensor Detail Modal ────────────────────────────────────── */}
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
                <h2 className="text-xl sm:text-2xl font-bold text-white uppercase tracking-wider truncate">{`Cold Room ${selectedSensor.toUpperCase().replace('S', '')}`}</h2>
                <span className="text-xs text-slate-400 block truncate">Live Telemetry Analysis — {formatTimestamp(liveDevice?.lastUpdated)}</span>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6 sm:mb-8">
              <div className="bg-slate-800/50 p-4 sm:p-6 rounded-2xl border border-slate-700 flex flex-col justify-center">
                <p className="text-xs sm:text-sm text-slate-400 mb-1 sm:mb-2">Live Temperature</p>
                <p className="text-2xl sm:text-3xl font-bold text-white truncate">{multiSensorData[selectedSensor].t?.toFixed(2)} °C</p>
              </div>
              <div className="bg-slate-800/50 p-4 sm:p-6 rounded-2xl border border-slate-700 flex flex-col justify-center">
                <p className="text-xs sm:text-sm text-slate-400 mb-1 sm:mb-2">Live Humidity</p>
                <p className="text-2xl sm:text-3xl font-bold text-blue-400 truncate">{multiSensorData[selectedSensor].h?.toFixed(2)} %</p>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <LiveChart
                data={(sensorHistory[selectedSensor]?.t || []).map((v, i) => ({ time: i, value: v }))}
                type="temperature"
                title="Temperature History"
                unit="°C"
              />
              <LiveChart
                data={(sensorHistory[selectedSensor]?.h || []).map((v, i) => ({ time: i, value: v }))}
                type="moisture"
                title="Humidity History"
                unit="%"
              />
            </div>
          </motion.div>
        </div>
      )}

      {/* ── Standard Single-Device Content Grid ───────────────────────────────── */}
      {Boolean(selectedDeviceId) && deviceType !== 'multi_sensor' && deviceType !== 'office_control' && deviceType !== 'controlling' && (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
          {/* Left: Big Metrics */}
          <div className="space-y-4 xl:col-span-1">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Live Readings</h3>
            {isDeviceOffline ? (
              <div className="rounded-2xl border border-dashed border-rose-500/30 bg-rose-500/5 p-6 text-center">
                <AlertTriangle className="h-8 w-8 text-rose-400 mx-auto mb-2" />
                <div className="text-sm font-semibold text-white mb-1">Device Offline</div>
                <div className="text-xs text-slate-400">Selected device is currently offline or not broadcasting telemetry.</div>
              </div>
            ) : loading ? (
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
                {activeFields.map(f => (
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
            <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Trend Charts</h3>
            {isDeviceOffline ? (
              <div className="rounded-2xl border border-dashed border-slate-700/50 bg-slate-800/20 p-8 text-center text-slate-400 text-sm">
                Trend charts unavailable while device is offline.
              </div>
            ) : loading ? (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {[...Array(activeFields.length || 4)].map((_, i) => (
                  <div key={i} className="rounded-2xl border border-slate-700/30 bg-slate-800/30 p-4">
                    <div className="skeleton mb-4 h-4 w-32 rounded" />
                    <div className="skeleton h-48 w-full rounded-xl" />
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {activeFields.map(f => (
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
