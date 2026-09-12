import { useState, useEffect, useCallback, useRef, memo, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
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
  Layers,
  LayoutGrid,
  ChevronRight,
  ArrowLeft,
  ArrowUpRight,
  ShieldCheck,
  MapPin,
  Maximize2,
  X,
  TrendingUp,
  AlertTriangle,
  Sun,
  Fan,
} from 'lucide-react';
import LiveChart from '../../components/LiveChart';
import { SkeletonCard } from '../../components/Skeleton';
import { useThrottledStream } from '../../hooks/useThrottledStream';
import { createMqttClient } from '../../utils/mqtt';
import {
  getMetricStatus,
  getMetricColor,
  formatTimestamp,
} from '../../utils/helpers';

// ── Cold Storage Constants & Probe Naming ────────────────────────────────────
const DEFAULT_ROOM_NAMES = {
  S1: 'Cold Room 1',
  S2: 'Cold Room 2',
  S3: 'Cold Room 3',
  S4: 'Cold Room 4',
  S5: 'Cold Room 5',
  S6: 'Cold Room 6',
  S7: 'Greenhouse',
};

const DEFAULT_PROBE_PORTS = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'];

const getProbeName = (sensorId, deviceMeta, customNames = {}) => {
  if (!sensorId) return 'Cold Room';
  const upper = String(sensorId).toUpperCase();
  const custom =
    customNames?.[upper] ||
    customNames?.[sensorId] ||
    deviceMeta?.sensor_names?.[sensorId] ||
    deviceMeta?.sensor_names?.[upper] ||
    deviceMeta?.sensorNames?.[sensorId] ||
    deviceMeta?.sensorNames?.[upper];
  if (custom) return custom;
  return DEFAULT_ROOM_NAMES[upper] || `Cold Room ${upper.replace('S', '')}`;
};

// ── Smooth SVG Sparkline Component (Theme-Aware) ─────────────────────────────
const SvgSparkline = memo(({ data = [], color = '#60bf71', height = 36 }) => {
  if (!data || data.length < 2) {
    return (
      <div className="h-9 w-full rounded-lg bg-slate-950/30 flex items-center justify-center border border-slate-800/40 text-[10px] text-slate-500 italic">
        Awaiting live trend...
      </div>
    );
  }

  const values = data.map((d) => (typeof d === 'object' && d !== null ? d.value ?? 0 : Number(d) || 0));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max === min ? 1 : max - min;
  const width = 220;
  const padding = 3;
  const usableHeight = height - padding * 2;

  const points = values.map((val, idx) => {
    const x = (idx / (values.length - 1)) * width;
    const y = height - padding - ((val - min) / range) * usableHeight;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const polylinePoints = points.join(' ');
  const areaPoints = `0,${height} ${polylinePoints} ${width},${height}`;
  const lastPoint = points[points.length - 1]?.split(',') || [];

  return (
    <div className="relative w-full overflow-hidden rounded-lg bg-slate-950/50 border border-slate-800/50 py-1 px-1">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-9 overflow-visible"
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id={`grad-spark-${color.replace(/[^a-zA-Z0-9]/g, '')}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.35" />
            <stop offset="100%" stopColor={color} stopOpacity="0.0" />
          </linearGradient>
        </defs>
        <polygon points={areaPoints} fill={`url(#grad-spark-${color.replace(/[^a-zA-Z0-9]/g, '')})`} />
        <polyline
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          points={polylinePoints}
        />
        {lastPoint.length === 2 && (
          <circle
            cx={lastPoint[0]}
            cy={lastPoint[1]}
            r="3"
            fill={color}
            className="animate-pulse"
          />
        )}
      </svg>
    </div>
  );
});

// ── Memoized Atomic Metric Card (P2 Optimization) ────────
const BigMetric = memo(
  ({ label, value, unit, icon: Icon, type }) => {
    const safeValue = Number.isFinite(value) ? value : null;
    const status = safeValue != null ? getMetricStatus(type, safeValue) : 'normal';
    const color = safeValue != null ? getMetricColor(status) : 'text-slate-400';

    const bgColorMap = {
      'text-emerald-400': 'bg-emerald-500/10 border-emerald-500/20',
      'text-yellow-400': 'bg-yellow-500/10 border-yellow-500/20',
      'text-red-400': 'bg-red-500/10 border-red-500/20',
      'text-slate-500': 'bg-slate-500/10 border-slate-500/20',
    };

    return (
      <div
        className={`rounded-2xl border p-4 ${bgColorMap[color] || 'bg-slate-900/60 border-slate-800/80'} backdrop-blur-sm transition-colors duration-200`}
      >
        <div className="flex items-center gap-2.5">
          <div className={`rounded-lg p-1.5 ${color} bg-white/5`}>
            <Icon className="h-4 w-4" />
          </div>
          <span className="text-sm font-medium text-slate-400">{label}</span>
        </div>
        <div className="mt-3 flex items-baseline gap-1.5">
          <span className={`text-2xl font-bold tabular-nums ${safeValue != null ? color : 'text-slate-400'}`}>
            {safeValue == null ? '--' : type === 'ec' ? safeValue : safeValue.toFixed(1)}
          </span>
          <span className="text-sm text-slate-500">{unit}</span>
        </div>
        <div className="mt-1.5 flex items-center gap-1.5">
          <div
            className={`h-1.5 w-1.5 rounded-full ${
              safeValue == null
                ? 'bg-slate-500'
                : status === 'normal'
                ? 'bg-emerald-400'
                : status === 'warning'
                ? 'bg-yellow-400'
                : status === 'critical'
                ? 'bg-red-400'
                : 'bg-slate-500'
            }`}
          />
          <span className="text-xs text-slate-500 capitalize">{safeValue != null ? status : 'Standby'}</span>
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
        className={`rounded-2xl border p-4 ${bgMap[ecColor] || 'bg-slate-900/60 border-slate-800/80'} backdrop-blur-sm transition-colors duration-200`}
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
            className={`h-1.5 w-1.5 rounded-full ${ecStatus === 'normal'
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

// ── Upgraded Cold Room Probe Card (Theme-Consistent & Hardware-Aware) ─────────────
const ColdRoomProbeCard = memo(
  ({
    sensorId,
    roomName,
    data,
    history,
    setpoints,
    relays,
    hasAlarm,
    isDeviceOnline = false,
    onSelect,
    onFocus,
  }) => {
    const isOnline = Boolean(isDeviceOnline && (data?.status === 'OK' || data?.status === 'online'));
    const tVal = data?.t != null && data.t > 0 ? Number(data.t).toFixed(1) : '--';
    const hVal = data?.h != null && data.h > 0 ? Number(data.h).toFixed(1) : '--';
    const co2Val = data?.co2 != null && Number(data.co2) > 0 ? Number(data.co2).toFixed(0) : null;

    // Calculate min and max from history
    const tHistoryValues = (history?.t || [])
      .map((d) => (typeof d === 'object' && d !== null ? d.value : Number(d)))
      .filter((v) => Number.isFinite(v) && v > 0);
    const minT = tHistoryValues.length > 0 ? Math.min(...tHistoryValues).toFixed(1) : tVal;
    const maxT = tHistoryValues.length > 0 ? Math.max(...tHistoryValues).toFixed(1) : tVal;

    const isS7 = sensorId === 'S7';
    const coolingLabel = isS7 ? 'Fanpad' : 'AC';

    return (
      <motion.div
        whileHover={{ y: -3, transition: { duration: 0.2 } }}
        className={`group relative flex flex-col justify-between overflow-hidden rounded-2xl border p-4 sm:p-5 backdrop-blur-md transition-all duration-300 cursor-pointer ${
          hasAlarm
            ? 'border-rose-500/80 bg-rose-950/20 hover:border-rose-400 hover:bg-rose-950/30 shadow-lg shadow-rose-500/10'
            : 'border-slate-800/80 bg-slate-900/60 hover:border-emerald-500/40 hover:bg-slate-900/90 hover:shadow-xl hover:shadow-emerald-500/5'
        }`}
        onClick={() => (onFocus ? onFocus(sensorId) : onSelect(sensorId))}
      >
        {/* Top Glow Accent on Hover */}
        <div
          className={`absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent ${
            hasAlarm ? 'via-rose-500/80' : 'via-emerald-500/0 group-hover:via-emerald-500/60'
          } to-transparent transition-all duration-500`}
        />

        {/* Card Header: Port Badge, Room Name, Status */}
        <div className="mb-3.5 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="shrink-0 rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 text-[11px] font-mono font-bold text-emerald-400">
              {sensorId}
            </span>
            <div className="min-w-0">
              <h4 className="text-sm font-semibold text-white group-hover:text-emerald-300 transition-colors truncate">
                {roomName || `Cold Room ${sensorId.toUpperCase().replace('S', '')}`}
              </h4>
              {setpoints?.stage_name && (
                <p className="text-[10px] text-slate-400 font-medium truncate">
                  {setpoints.stage_name} {setpoints.slot_id ? `• Slot ${setpoints.slot_id}` : ''}
                </p>
              )}
            </div>
          </div>
          <span
            className={`shrink-0 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
              isOnline
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                : 'bg-slate-800 text-slate-400 border border-slate-700'
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                isOnline ? 'bg-emerald-400 animate-pulse-dot' : 'bg-slate-500'
              }`}
            />
            {isOnline ? 'Live' : 'Standby'}
          </span>
        </div>

        {/* Main Sensor KPI Grid */}
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2.5 sm:gap-3">
            {/* Temperature Tile */}
            <div className="rounded-xl bg-slate-950/50 border border-slate-800/60 p-3 transition-colors group-hover:border-slate-800">
              <div className="flex items-center justify-between mb-1">
                <p className="text-[10px] font-medium text-slate-400 flex items-center gap-1">
                  <Thermometer className="h-3 w-3 text-emerald-400" /> Temp
                </p>
                {setpoints?.target_temp != null && (
                  <span className="text-[9px] font-mono font-semibold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.2 rounded border border-emerald-500/20">
                    Set: {setpoints.target_temp}°
                  </span>
                )}
              </div>
              <div className="flex items-baseline gap-1">
                <span className="text-xl sm:text-2xl font-bold tabular-nums text-white group-hover:text-emerald-400 transition-colors">
                  {tVal}
                </span>
                <span className="text-xs font-normal text-slate-500">°C</span>
              </div>
            </div>

            {/* Humidity Tile */}
            <div className="rounded-xl bg-slate-950/50 border border-slate-800/60 p-3 transition-colors group-hover:border-slate-800">
              <div className="flex items-center justify-between mb-1">
                <p className="text-[10px] font-medium text-slate-400 flex items-center gap-1">
                  <Droplets className="h-3 w-3 text-emerald-400" /> Humidity
                </p>
                {setpoints?.target_humi != null && (
                  <span className="text-[9px] font-mono font-semibold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.2 rounded border border-emerald-500/20">
                    Set: {setpoints.target_humi}%
                  </span>
                )}
              </div>
              <div className="flex items-baseline gap-1">
                <span className="text-xl sm:text-2xl font-bold tabular-nums text-white group-hover:text-emerald-300 transition-colors">
                  {hVal}
                </span>
                <span className="text-xs font-normal text-slate-500">%</span>
              </div>
            </div>
          </div>

          {/* Chamber CO2 (if present) */}
          {co2Val != null && (
            <div className="flex items-center justify-between rounded-xl bg-slate-950/60 border border-slate-800/80 px-3 py-1.5 text-xs">
              <span className="text-[10px] text-slate-400 font-medium flex items-center gap-1.5">
                <Activity className="h-3 w-3 text-emerald-400" /> Chamber CO2
              </span>
              <span className="font-mono font-bold text-emerald-400">
                {co2Val} <span className="text-[10px] font-normal text-slate-500">ppm</span>
              </span>
            </div>
          )}

          {/* Hardware Relays Mini Status Bar */}
          {relays && (
            <div className="grid grid-cols-3 gap-1.5 pt-0.5">
              <div
                className={`rounded-lg px-2 py-1 text-[10px] font-semibold text-center border transition-all ${
                  relays.cooling
                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
                    : 'bg-slate-950/40 border-slate-800/60 text-slate-500'
                }`}
              >
                {coolingLabel}: <strong className={relays.cooling ? 'text-emerald-400' : 'text-slate-400'}>{relays.cooling ? 'ON' : 'OFF'}</strong>
              </div>
              <div
                className={`rounded-lg px-2 py-1 text-[10px] font-semibold text-center border transition-all ${
                  relays.humi
                    ? 'bg-sky-500/15 border-sky-500/30 text-sky-300'
                    : 'bg-slate-950/40 border-slate-800/60 text-slate-500'
                }`}
              >
                Humi: <strong className={relays.humi ? 'text-sky-400' : 'text-slate-400'}>{relays.humi ? 'ON' : 'OFF'}</strong>
              </div>
              <div
                className={`rounded-lg px-2 py-1 text-[10px] font-semibold text-center border transition-all ${
                  relays.light
                    ? 'bg-amber-500/15 border-amber-500/30 text-amber-300'
                    : 'bg-slate-950/40 border-slate-800/60 text-slate-500'
                }`}
              >
                Light: <strong className={relays.light ? 'text-amber-400' : 'text-slate-400'}>{relays.light ? 'ON' : 'OFF'}</strong>
              </div>
            </div>
          )}

          {/* SVG Trend Sparkline */}
          <div className="pt-1">
            <div className="flex items-center justify-between text-[10px] text-slate-500 mb-1">
              <span>Telemetry Sparkline</span>
              {minT !== '--' && minT !== maxT && (
                <span className="font-mono text-slate-400">
                  {minT}° - {maxT}°C
                </span>
              )}
            </div>
            <SvgSparkline data={history?.t || []} color={hasAlarm ? '#f43f5e' : '#60bf71'} height={36} />
          </div>
        </div>

        {/* Card Footer: Action Bar */}
        <div className="mt-3.5 flex items-center justify-between border-t border-slate-800/60 pt-3 text-[11px] text-slate-400">
          <span className="group-hover:text-emerald-400 transition-colors flex items-center gap-1 font-medium">
            Inspect Analytics & Charts
          </span>
          <ChevronRight className="h-4 w-4 text-slate-500 group-hover:text-emerald-400 group-hover:translate-x-0.5 transition-all" />
        </div>
      </motion.div>
    );
  },
  (prev, next) =>
    prev.isDeviceOnline === next.isDeviceOnline &&
    prev.data?.t === next.data?.t &&
    prev.data?.h === next.data?.h &&
    prev.data?.co2 === next.data?.co2 &&
    prev.data?.status === next.data?.status &&
    prev.roomName === next.roomName &&
    prev.hasAlarm === next.hasAlarm &&
    prev.relays?.cooling === next.relays?.cooling &&
    prev.relays?.humi === next.relays?.humi &&
    prev.relays?.light === next.relays?.light &&
    prev.setpoints?.target_temp === next.setpoints?.target_temp &&
    prev.setpoints?.target_humi === next.setpoints?.target_humi &&
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
  const [sensorHistory, setSensorHistory] = useState({}); // { S1: { t: [...], h: [...], co2: [...] } }
  const [multiSensorSetpoints, setMultiSensorSetpoints] = useState({});
  const [multiSensorRelays, setMultiSensorRelays] = useState({});
  const [activeWarnings, setActiveWarnings] = useState([]);
  const [customSensorNames, setCustomSensorNames] = useState({});
  const [sortBy, setSortBy] = useState('id'); // 'id', 'temp', 'humi'
  const [selectedSensor, setSelectedSensor] = useState(null);
  const [activeMultiTab, setActiveMultiTab] = useState('all'); // 'all' or 'S1'..'S7'

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

  // ── Device Type Classification (Mutually Exclusive Clean Branches) ─────────
  const isMultiSensorDevice = useMemo(() => {
    if (!deviceMeta) return false;
    const type = String(deviceMeta.deviceType || '').toLowerCase();
    const name = String(deviceMeta.name || '').toLowerCase();
    const mqttId = String(deviceMeta.mqttId || '').toLowerCase();
    return (
      type === 'multi_sensor' ||
      type === 'almora' ||
      type === 'almora2' ||
      type === 'cold_storage' ||
      type === 'cold_room' ||
      type === 'coldroom' ||
      name.includes('almora') ||
      name.includes('cold') ||
      name.includes('storage') ||
      mqttId.includes('almora') ||
      mqttId === 'control122'
    );
  }, [deviceMeta]);

  const isOfficeControlDevice = deviceMeta?.deviceType === 'office_control';
  const isControllingDevice = deviceMeta?.deviceType === 'controlling';
  const isStandardDevice = !isMultiSensorDevice && !isOfficeControlDevice && !isControllingDevice;

  // ── Real-time freshness ticker (ticks every 5 seconds to evaluate device timeout) ──
  const [nowTime, setNowTime] = useState(Date.now());
  useEffect(() => {
    const interval = setInterval(() => {
      setNowTime(Date.now());
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  // ── Determine if the currently selected device is Online or Offline ─────────
  const isDeviceOnline = useMemo(() => {
    if (deviceMeta?.status === 'blocked') return false;

    // Telemetry freshness window: 2 minutes (120,000 ms) with clock tolerance
    const FRESHNESS_THRESHOLD_MS = 2 * 60 * 1000;

    // 1. If we have liveDevice with a lastUpdated timestamp
    if (liveDevice?.lastUpdated) {
      const ts = new Date(typeof liveDevice.lastUpdated === 'string' && liveDevice.lastUpdated.includes(' ') && !liveDevice.lastUpdated.includes('T') ? liveDevice.lastUpdated.replace(' ', 'T') : liveDevice.lastUpdated).getTime();
      if (!isNaN(ts)) {
        const diffMs = nowTime - ts;
        return diffMs < FRESHNESS_THRESHOLD_MS && diffMs > -2 * 60 * 1000 && liveDevice.status === 'online';
      }
    }

    // 2. Fallback: check deviceMeta.lastUpdated
    if (deviceMeta?.lastUpdated) {
      const ts = new Date(typeof deviceMeta.lastUpdated === 'string' && deviceMeta.lastUpdated.includes(' ') && !deviceMeta.lastUpdated.includes('T') ? deviceMeta.lastUpdated.replace(' ', 'T') : deviceMeta.lastUpdated).getTime();
      if (!isNaN(ts)) {
        const diffMs = nowTime - ts;
        return diffMs < FRESHNESS_THRESHOLD_MS && diffMs > -2 * 60 * 1000 && deviceMeta.status === 'online';
      }
    }

    return false;
  }, [nowTime, liveDevice, deviceMeta]);

  // ── Multi-Sensor Facility Aggregates (Summary KPI Cards) ───────────────────
  const multiSensorSummary = useMemo(() => {
    let tempSum = 0, tempCount = 0, minT = Infinity, maxT = -Infinity;
    let humiSum = 0, humiCount = 0, minH = Infinity, maxH = -Infinity;
    let co2Val = null;
    let online = 0;

    DEFAULT_PROBE_PORTS.forEach((sKey) => {
      const probe = multiSensorData[sKey];
      if (!probe) return;
      const isProbeOnline = isDeviceOnline && (probe.status === 'OK' || probe.status === 'online');
      if (isProbeOnline) online++;

      if (probe.t != null && Number(probe.t) > 0) {
        const t = Number(probe.t);
        tempSum += t;
        tempCount++;
        if (t < minT) minT = t;
        if (t > maxT) maxT = t;
      }
      if (probe.h != null && Number(probe.h) > 0) {
        const h = Number(probe.h);
        humiSum += h;
        humiCount++;
        if (h < minH) minH = h;
        if (h > maxH) maxH = h;
      }
      if (probe.co2 != null && Number(probe.co2) > 0) {
        co2Val = probe.co2;
      }
    });

    return {
      onlineCount: isDeviceOnline ? online : 0,
      totalProbes: 7,
      avgTemp: tempCount > 0 ? (tempSum / tempCount).toFixed(1) : '--',
      minTemp: minT !== Infinity ? minT.toFixed(1) : '--',
      maxTemp: maxT !== -Infinity ? maxT.toFixed(1) : '--',
      avgHumi: humiCount > 0 ? (humiSum / humiCount).toFixed(1) : '--',
      minHumi: minH !== Infinity ? minH.toFixed(1) : '--',
      maxHumi: maxH !== -Infinity ? maxH.toFixed(1) : '--',
      co2: co2Val,
    };
  }, [multiSensorData, isDeviceOnline]);

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
    setActiveMultiTab('all');
    setMultiSensorData({});
    setSensorHistory({});
    setMultiSensorSetpoints({});
    setMultiSensorRelays({});
    setActiveWarnings([]);
    setCustomSensorNames({});
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
    const isMultiSensor = deviceMeta?.deviceType === 'multi_sensor' || deviceMeta?.deviceType === 'almora' || deviceMeta?.deviceType === 'almora2' || (deviceMeta?.name && (deviceMeta.name.toLowerCase().includes('almora') || deviceMeta.name.toLowerCase().includes('cold')));
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
              { key: 'field2', label: ' Moisture', icon: Droplets, unit: '%', type: 'moisture' },
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

        const feedTimestamp = latestFeed.created_at || latestFeed.timestamp || null;
        const lastUpdatedTime = feedTimestamp ? new Date(typeof feedTimestamp === 'string' && feedTimestamp.includes(' ') && !feedTimestamp.includes('T') ? feedTimestamp.replace(' ', 'T') : feedTimestamp) : new Date(0);
        const diffMs = Date.now() - lastUpdatedTime.getTime();
        const isOnline = Boolean(feedTimestamp && diffMs < 2 * 60 * 1000 && diffMs > -2 * 60 * 1000);

        const device = {
          id: selectedDeviceId,
          name: deviceMeta?.name || 'Live Sensor Data',
          location: deviceMeta?.location || 'Private Broker Feed',
          status: isOnline ? 'online' : 'offline',
          lastUpdated: lastUpdatedTime.getTime() > 0 ? lastUpdatedTime.toISOString() : null,
        };

        setLiveDevice((prev) => {
          // If prev is already marked online from live streaming and is fresh, preserve it!
          if (prev && prev.status === 'online' && prev.lastUpdated) {
            const prevDiff = Date.now() - new Date(prev.lastUpdated).getTime();
            if (prevDiff < 2 * 60 * 1000 && prevDiff > -2 * 60 * 1000) {
              return prev;
            }
          }
          return device;
        });

        const currentMetrics = {};
        fields.forEach((f) => {
          currentMetrics[f.key] = parseFloat(latestFeed[f.key]) || 0;
        });

        const newChartData = {};
        fields.forEach((f) => {
          newChartData[f.key] = feeds.map((feed) => ({
            time: new Date(feed.created_at || feed.timestamp || Date.now()).toLocaleTimeString('en-US', {
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
          setActiveMetrics(currentMetrics);
          setChartData(newChartData);

          if (isMultiSensor && latestFeed) {
            const initMulti = {};
            const multiSource = latestFeed.multi_sensor_data || {};
            for (let i = 1; i <= 7; i++) {
              const sKey = `S${i}`;
              const probe = multiSource[sKey];
              if (probe && (Number(probe.t) > 0 || Number(probe.h) > 0)) {
                initMulti[sKey] = {
                  t: Number(probe.t) || 0,
                  h: Number(probe.h) || 0,
                  co2: probe.co2 != null ? Number(probe.co2) : null,
                  status: isOnline ? (probe.status || 'OK') : 'OFFLINE',
                };
              } else {
                const fVal = latestFeed[`field${i}`];
                if (fVal !== undefined && fVal !== null && fVal !== '') {
                  const t = parseFloat(fVal) || 0;
                  if (t > 0) {
                    initMulti[sKey] = { t, h: 60.0, status: isOnline ? 'OK' : 'OFFLINE' };
                  }
                }
              }
            }
            if (Object.keys(initMulti).length > 0) {
              setMultiSensorData((prev) => ({ ...initMulti, ...prev }));
            }

            // Pre-populate sensorHistory so sparklines and charts show real data immediately
            if (feeds && feeds.length > 0) {
              const initHist = {};
              for (let i = 1; i <= 7; i++) {
                const sKey = `S${i}`;
                const fKey = `field${i}`;
                const tPoints = [];
                const hPoints = [];
                const co2Points = [];

                feeds.forEach((feed) => {
                  const time = new Date(feed.created_at || Date.now()).toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                  });

                  let t = null;
                  let h = null;
                  let co2 = null;

                  if (feed.multi_sensor_data && feed.multi_sensor_data[sKey]) {
                    const p = feed.multi_sensor_data[sKey];
                    if (p.t != null && Number(p.t) > 0) t = Number(p.t);
                    if (p.h != null && Number(p.h) > 0) h = Number(p.h);
                    if (p.co2 != null && Number(p.co2) > 0) co2 = Number(p.co2);
                  } else if (feed[fKey] !== undefined && feed[fKey] !== null && feed[fKey] !== '') {
                    const val = parseFloat(feed[fKey]);
                    if (val > 0) {
                      t = val;
                      h = 60.0;
                    }
                  }

                  if (t !== null) tPoints.push({ time, value: t });
                  if (h !== null) hPoints.push({ time, value: h });
                  if (co2 !== null) co2Points.push({ time, value: co2 });
                });

                if (tPoints.length > 0 || hPoints.length > 0) {
                  initHist[sKey] = {
                    t: tPoints.slice(-24),
                    h: hPoints.slice(-24),
                    co2: co2Points.slice(-24),
                  };
                }
              }
              if (Object.keys(initHist).length > 0) {
                setSensorHistory((prev) => ({ ...initHist, ...prev }));
              }
            }

            // Extract initial relay states if present in latestFeed
            const rawRelays = latestFeed.relay_states || latestFeed.relays;
            if (rawRelays && typeof rawRelays === 'object') {
              const mappedRelays = {};
              for (let i = 1; i <= 7; i++) {
                const sKey = `S${i}`;
                const idx = i - 1;
                const chCooling = String((idx * 3) + 1);
                const chHumi = String((idx * 3) + 2);
                const chLight = String((idx * 3) + 3);
                mappedRelays[sKey] = {
                  cooling: Boolean(rawRelays[chCooling] ?? rawRelays[Number(chCooling)]),
                  humi: Boolean(rawRelays[chHumi] ?? rawRelays[Number(chHumi)]),
                  light: Boolean(rawRelays[chLight] ?? rawRelays[Number(chLight)]),
                };
              }
              setMultiSensorRelays((prev) => ({ ...prev, ...mappedRelays }));
            }

            // Extract initial setpoints if present in latestFeed
            const rawSp = latestFeed.sensor_setpoints || latestFeed.setpoints;
            if (rawSp && typeof rawSp === 'object') {
              const mappedSp = {};
              Object.entries(rawSp).forEach(([k, sp]) => {
                const sKey = k.toUpperCase().startsWith('S') ? k.toUpperCase() : `S${k}`;
                mappedSp[sKey] = sp;
              });
              setMultiSensorSetpoints((prev) => ({ ...prev, ...mappedSp }));
            }

            // Extract active warnings
            if (Array.isArray(latestFeed.active_warnings)) {
              setActiveWarnings(latestFeed.active_warnings);
            }
            if (latestFeed.system_config?.sensor_names) {
              setCustomSensorNames(latestFeed.system_config.sensor_names);
            }
          }
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

      const isMultiSensor =
        deviceMeta?.deviceType === 'multi_sensor' ||
        deviceMeta?.deviceType === 'almora' ||
        deviceMeta?.deviceType === 'almora2' ||
        (deviceMeta?.name &&
          (deviceMeta.name.toLowerCase().includes('almora') ||
            deviceMeta.name.toLowerCase().includes('cold')));
      const isOfficeControl = deviceMeta?.deviceType === 'office_control';
      const isControlling = deviceMeta?.deviceType === 'controlling';

      let latestTelemetryTimestamp = null;
      let hasMatchingTelemetry = false;

      const parsePacketTime = (rawTs) => {
        if (!rawTs) return null;
        if (rawTs instanceof Date) return isNaN(rawTs.getTime()) ? null : rawTs;
        if (typeof rawTs === 'string') {
          const isoStr = rawTs.includes(' ') && !rawTs.includes('T') ? rawTs.replace(' ', 'T') : rawTs;
          const d = new Date(isoStr);
          if (!isNaN(d.getTime())) return d;
        }
        const d = new Date(rawTs);
        return isNaN(d.getTime()) ? null : d;
      };

      // Iterate through EVERY packet in the batch so no room or probe is skipped
      packets.forEach((packet) => {
        if (!packet || !packet.data) return;

        // Verify that this packet belongs to the currently selected device or candidate identifiers
        const packetMqttId = String(packet.mqttId || '').toLowerCase();
        const packetDevId = String(packet.deviceId || '').toLowerCase();
        const topic = String(packet.topic || '').toLowerCase();

        const matchesDevice =
          (selectedDeviceId && packetDevId === String(selectedDeviceId).toLowerCase()) ||
          candidateIdentifiers.some(
            (cid) =>
              cid &&
              (packetMqttId === String(cid).toLowerCase() ||
                packetDevId === String(cid).toLowerCase() ||
                topic.includes(String(cid).toLowerCase()))
          );

        if (!matchesDevice && candidateIdentifiers.length > 0) {
          return; // Skip packets belonging to other devices
        }

        const payload = packet.data;
        const rawPayload = payload.data || payload;

        // Parse genuine packet timestamp
        const rawTs =
          rawPayload.timestamp ||
          rawPayload.created_at ||
          rawPayload.time ||
          payload.timestamp ||
          payload.created_at ||
          payload.time ||
          (packet.isRetain ? null : packet.timestamp);

        const packetDate = parsePacketTime(rawTs);
        const timeStr = packetDate
          ? packetDate.toLocaleTimeString('en-US', {
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
          // 1. Extract Relay States (24 relays total, 3 channels per cold storage room)
          const rawRelays = rawPayload.relay_states || rawPayload.relays;
          if (rawRelays && typeof rawRelays === 'object') {
            const mappedRelays = {};
            for (let i = 1; i <= 7; i++) {
              const sKey = `S${i}`;
              const idx = i - 1;
              const chCooling = String((idx * 3) + 1);
              const chHumi = String((idx * 3) + 2);
              const chLight = String((idx * 3) + 3);
              mappedRelays[sKey] = {
                cooling: Boolean(rawRelays[chCooling] ?? rawRelays[Number(chCooling)]),
                humi: Boolean(rawRelays[chHumi] ?? rawRelays[Number(chHumi)]),
                light: Boolean(rawRelays[chLight] ?? rawRelays[Number(chLight)]),
              };
            }
            setMultiSensorRelays((prev) => ({ ...prev, ...mappedRelays }));
          }

          // 2. Extract Active Warnings / Alarms
          if (Array.isArray(rawPayload.active_warnings)) {
            setActiveWarnings(rawPayload.active_warnings);
          } else if (Array.isArray(rawPayload.warnings)) {
            setActiveWarnings(rawPayload.warnings);
          }

          // 3. Extract Sensor Setpoints (target temp, target humi, bands, stage)
          const rawSp = rawPayload.sensor_setpoints || rawPayload.setpoints;
          if (rawSp && typeof rawSp === 'object') {
            const mappedSp = {};
            Object.entries(rawSp).forEach(([k, sp]) => {
              const sKey = k.toUpperCase().startsWith('S') ? k.toUpperCase() : `S${k}`;
              mappedSp[sKey] = sp;
            });
            setMultiSensorSetpoints((prev) => ({ ...prev, ...mappedSp }));
          }

          // 4. Extract Custom Sensor Names
          if (rawPayload.system_config?.sensor_names) {
            setCustomSensorNames(rawPayload.system_config.sensor_names);
          }

          // 5. Normalize Probe Telemetry Data (S1..S7)
          let normalizedSensors = {};
          const rawSensors = rawPayload.sensor_data || (rawPayload.S1 || rawPayload.s1 || rawPayload.S2 || rawPayload.s2 ? rawPayload : null);

          if (rawSensors && typeof rawSensors === 'object') {
            Object.entries(rawSensors).forEach(([key, probe]) => {
              if (!probe || typeof probe !== 'object') return;
              let sKey = null;
              if (probe.id !== undefined && probe.id !== null) {
                sKey = `S${probe.id}`;
              } else if (key.toUpperCase().startsWith('S') && key.length <= 3) {
                sKey = key.toUpperCase();
              } else {
                const m = key.match(/S(\d+)/i) || key.match(/port(\d+)/i);
                if (m) sKey = `S${m[1]}`;
              }

              if (sKey) {
                const tVal = parseFloat(probe.t ?? probe.temp ?? 0);
                const hVal = parseFloat(probe.h ?? probe.hum ?? probe.humi ?? probe.humidity ?? 0);
                const isProbeOk = probe.status === 'OK' || (tVal > 0);
                normalizedSensors[sKey] = {
                  t: isNaN(tVal) ? 0 : tVal,
                  h: isNaN(hVal) ? 0 : hVal,
                  co2: probe.co2 != null ? parseFloat(probe.co2) : null,
                  status: isProbeOk ? 'OK' : 'OFFLINE',
                };
              }
            });
          } else if (rawPayload.temp !== undefined || rawPayload.hum !== undefined || rawPayload.humi !== undefined) {
            normalizedSensors = {
              S1: {
                t: parseFloat(rawPayload.temp ?? rawPayload.t ?? 0) || 0,
                h: parseFloat(rawPayload.hum ?? rawPayload.humi ?? rawPayload.h ?? 0) || 0,
                status: 'OK',
              },
            };
          } else {
            Object.keys(rawPayload).forEach((k) => {
              const upperKey = k.toUpperCase();
              if (upperKey.startsWith('S') && upperKey.length <= 3) {
                const probe = rawPayload[k] || {};
                const tVal = parseFloat(probe.t ?? probe.temp ?? 0);
                const hVal = parseFloat(probe.h ?? probe.hum ?? probe.humidity ?? probe.humi ?? 0);
                const isProbeOk = probe.status === 'OK' || (tVal > 0);
                normalizedSensors[upperKey] = {
                  t: isNaN(tVal) ? 0 : tVal,
                  h: isNaN(hVal) ? 0 : hVal,
                  co2: probe.co2 != null ? parseFloat(probe.co2) : null,
                  status: isProbeOk ? 'OK' : 'OFFLINE',
                };
              }
            });
          }

          if (Object.keys(normalizedSensors).length > 0) {
            hasMatchingTelemetry = true;
            if (!packet.isRetain) {
              latestTelemetryTimestamp = new Date();
            } else if (packetDate) {
              if (!latestTelemetryTimestamp || packetDate > latestTelemetryTimestamp) {
                latestTelemetryTimestamp = packetDate;
              }
            }

            setMultiSensorData((prev) => ({ ...prev, ...normalizedSensors }));
            setSensorHistory((prev) => {
              const newHist = { ...prev };
              Object.keys(normalizedSensors).forEach((sId) => {
                const sensor = normalizedSensors[sId];
                if (sensor.t > 0 || sensor.h > 0) {
                  const prevState =
                    newHist[sId] && typeof newHist[sId] === 'object' ? newHist[sId] : { t: [], h: [], co2: [] };
                  const prevT = Array.isArray(prevState.t) ? prevState.t : [];
                  const prevH = Array.isArray(prevState.h) ? prevState.h : [];
                  const prevCo2 = Array.isArray(prevState.co2) ? prevState.co2 : [];

                  const newT = sensor.t > 0 ? [...prevT, { time: timeStr, value: sensor.t }].slice(-24) : prevT;
                  const newH = sensor.h > 0 ? [...prevH, { time: timeStr, value: sensor.h }].slice(-24) : prevH;
                  const newCo2 = sensor.co2 != null && sensor.co2 > 0 ? [...prevCo2, { time: timeStr, value: sensor.co2 }].slice(-24) : prevCo2;

                  newHist[sId] = {
                    t: newT,
                    h: newH,
                    co2: newCo2,
                  };
                }
              });
              return newHist;
            });
          }
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

            hasMatchingTelemetry = true;
            if (!packet.isRetain) {
              latestTelemetryTimestamp = new Date();
            } else if (packetDate) {
              if (!latestTelemetryTimestamp || packetDate > latestTelemetryTimestamp) {
                latestTelemetryTimestamp = packetDate;
              }
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

          hasMatchingTelemetry = true;
          if (!packet.isRetain) {
            latestTelemetryTimestamp = new Date();
          } else if (packetDate) {
            if (!latestTelemetryTimestamp || packetDate > latestTelemetryTimestamp) {
              latestTelemetryTimestamp = packetDate;
            }
          }

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

          hasMatchingTelemetry = true;
          if (!packet.isRetain) {
            latestTelemetryTimestamp = new Date();
          } else if (packetDate) {
            if (!latestTelemetryTimestamp || packetDate > latestTelemetryTimestamp) {
              latestTelemetryTimestamp = packetDate;
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

      if (hasMatchingTelemetry && latestTelemetryTimestamp) {
        const diffMs = Date.now() - latestTelemetryTimestamp.getTime();
        const isFresh = diffMs < 2 * 60 * 1000 && diffMs > -2 * 60 * 1000;

        setLiveDevice({
          id: selectedDeviceId,
          name: deviceMeta?.name || 'Live Sensor Data',
          location: deviceMeta?.location || 'Private Broker Stream',
          status: isFresh ? 'online' : 'offline',
          lastUpdated: latestTelemetryTimestamp.toISOString(),
        });

        setLoading(false);
        setHasNewData(true);
        if (newDataTimeoutRef.current) clearTimeout(newDataTimeoutRef.current);
        newDataTimeoutRef.current = setTimeout(() => {
          setHasNewData(false);
          newDataTimeoutRef.current = null;
        }, 2000);
      }
    },
    [candidateIdentifiers, deviceMeta, selectedDeviceId]
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

      client.on('message', (topic, message, packet) => {
        try {
          const payloadData = JSON.parse(message.toString());
          const parts = topic.split('/');
          const mqttId = parts[1] || '';
          const isRetain = Boolean(packet && packet.retain);
          handleBatchedPackets([
            {
              deviceId: selectedDeviceId,
              mqttId,
              topic,
              data: payloadData,
              isRetain,
              timestamp: isRetain ? null : new Date(),
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
        } catch (e) { }
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
      <div className="flex flex-col gap-4 rounded-2xl border border-slate-800/80 bg-slate-900/60 p-4 sm:p-5 sm:flex-row sm:items-center sm:justify-between backdrop-blur-md">
        <div className="flex flex-wrap items-center gap-2.5 sm:gap-3 w-full sm:w-auto">
          {/* Device Selector Dropdown */}
          <div className="relative w-full sm:w-auto flex-1 sm:flex-initial">
            <select
              value={selectedDeviceId}
              onChange={(e) => handleDeviceChange(e.target.value)}
              className="w-full sm:w-auto appearance-none rounded-xl border border-slate-700/80 bg-slate-950/80 pl-4 pr-10 py-2.5 text-xs sm:text-sm font-semibold text-white outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 cursor-pointer transition-all min-w-0 sm:min-w-[240px]"
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
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 pointer-events-none" />
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Status Badge */}
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider ${deviceMeta?.status === 'blocked'
                ? 'border-red-500/30 bg-red-500/10 text-red-400'
                : isDeviceOnline
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                  : 'border-rose-500/30 bg-rose-500/10 text-rose-400'
                }`}
              title={`Device Status: ${deviceMeta?.status === 'blocked' ? 'Blocked' : isDeviceOnline ? 'Online' : 'Offline'}`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${deviceMeta?.status === 'blocked'
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

            {/* Broker Status Badge */}
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium ${isMqttConnected
                ? 'border-emerald-500/20 bg-emerald-500/5 text-emerald-300'
                : 'border-slate-800 bg-slate-900 text-slate-500'
                }`}
            >
              <ShieldCheck className="h-3 w-3 text-emerald-400" />
              {isMqttConnected ? 'Broker Live' : 'SSE Bridge'}
            </span>

            {deviceMeta?.location && (
              <span className="hidden md:inline-flex items-center gap-1 text-xs text-slate-400 font-medium px-2 py-1 rounded-lg bg-slate-800/40 border border-slate-700/30">
                <MapPin className="h-3 w-3 text-slate-500" />
                {deviceMeta.location}
              </span>
            )}
          </div>
        </div>

        {/* Right: Refresh & Status */}
        <div className="flex items-center justify-between sm:justify-end gap-3 text-xs text-slate-400 w-full sm:w-auto pt-2 sm:pt-0 border-t border-slate-800/60 sm:border-t-0">
          <div className="flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5 text-slate-500" />
            <span>Updated:</span>
            <span className="text-slate-300 font-medium">
              {liveDevice?.lastUpdated ? formatTimestamp(liveDevice.lastUpdated) : '--'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              title="Refresh Live Data"
              className="rounded-lg border border-slate-700/80 bg-slate-800/60 p-2 transition-all hover:bg-slate-700 hover:text-white active:scale-95 text-slate-300"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin text-emerald-400' : ''}`} />
            </button>
            <span
              className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold tracking-wide ${hasNewData
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                : 'border-slate-800 bg-slate-800/60 text-slate-400'
                }`}
            >
              {hasNewData ? 'Live Data' : 'Cached'}
            </span>
          </div>
        </div>
      </div>

      {/* ── Office Control Dual-Room Live View ───────────────────────────── */}
      {deviceMeta?.deviceType === 'office_control' && (
        <div className="space-y-6">
          {/* Room Selection Tabs */}
          <div className="flex border-b border-slate-700/60 pb-px overflow-x-auto scrollbar-none">
            {[1, 2, 3].map((room) => (
              <button
                key={room}
                onClick={() => setActiveRoomTab(room)}
                className={`relative px-6 py-3.5 text-sm font-semibold transition-all hover:text-white whitespace-nowrap ${activeRoomTab === room ? 'text-emerald-400' : 'text-slate-400'
                  }`}
              >
                Room {room} Control
                {activeRoomTab === room && (
                  <motion.div
                    layoutId="activeRoomTabIndicator"
                    className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-500"
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
                  <div className="animate-pulse mb-2 text-emerald-400 font-medium">
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
                        label="Temp"
                        value={officeControlData[activeRoomTab]?.soil?.soil_temp}
                        unit="°C"
                        icon={Thermometer}
                        type="temperature"
                      />
                      <BigMetric
                        label="Moisture"
                        value={officeControlData[activeRoomTab]?.soil?.moisture}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                      />
                      <EcMetricCard
                        label="EC"
                        ecVal={officeControlData[activeRoomTab]?.soil?.ec}
                      />
                      <BigMetric
                        label=" pH"
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
                        title=" Temperature Trend"
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
                        title="EC Trend"
                        unit="mS/cm"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.ph || []}
                        type="ph"
                        title=" pH Trend"
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
                    <div className="animate-pulse mb-2 text-emerald-400 font-medium">
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

      {/* ── Multi-Sensor Cold Storage Matrix View ──────────────────────────── */}
      {isMultiSensorDevice && (() => {
        const sortedPorts = [...DEFAULT_PROBE_PORTS].sort((a, b) => {
          if (sortBy === 'temp') return (multiSensorData[b]?.t || 0) - (multiSensorData[a]?.t || 0);
          if (sortBy === 'humi') return (multiSensorData[b]?.h || 0) - (multiSensorData[a]?.h || 0);
          return a.localeCompare(b);
        });

        // Current focused room data if activeMultiTab is S1..S7
        const isFocusedRoom = activeMultiTab !== 'all';
        const focusedProbeData = isFocusedRoom ? multiSensorData[activeMultiTab] : null;
        const focusedRoomName = isFocusedRoom ? getProbeName(activeMultiTab, deviceMeta, customSensorNames) : '';
        const focusedHistT = isFocusedRoom ? (sensorHistory?.[activeMultiTab]?.t || []) : [];
        const focusedHistH = isFocusedRoom ? (sensorHistory?.[activeMultiTab]?.h || []) : [];
        const focusedHistCo2 = isFocusedRoom ? (sensorHistory?.[activeMultiTab]?.co2 || []) : [];
        const focusedSetpoints = isFocusedRoom ? multiSensorSetpoints[activeMultiTab] : null;
        const focusedRelays = isFocusedRoom ? multiSensorRelays[activeMultiTab] : null;

        const focusedRoomIdx = isFocusedRoom ? parseInt(activeMultiTab.replace('S', ''), 10) - 1 : 0;
        const focusedChCooling = (focusedRoomIdx * 3) + 1;
        const focusedChHumi = (focusedRoomIdx * 3) + 2;
        const focusedChLight = (focusedRoomIdx * 3) + 3;
        const focusedIsS7 = activeMultiTab === 'S7';
        const focusedCoolingLabel = focusedIsS7 ? 'Fanpad' : 'AC / Cooling';

        const focusedAlarms = isFocusedRoom
          ? activeWarnings.filter((w) => {
              const text = typeof w === 'string' ? w.toLowerCase() : JSON.stringify(w).toLowerCase();
              return text.includes(activeMultiTab.toLowerCase()) || text.includes(`room ${activeMultiTab.replace('S', '')}`);
            })
          : [];

        const focusedTValues = focusedHistT
          .map((d) => (typeof d === 'object' && d !== null ? d.value : Number(d)))
          .filter((v) => Number.isFinite(v) && v > 0);
        const focusedHValues = focusedHistH
          .map((d) => (typeof d === 'object' && d !== null ? d.value : Number(d)))
          .filter((v) => Number.isFinite(v) && v > 0);

        const focusedMinT = focusedTValues.length > 0 ? Math.min(...focusedTValues).toFixed(1) : '--';
        const focusedMaxT = focusedTValues.length > 0 ? Math.max(...focusedTValues).toFixed(1) : '--';
        const focusedAvgT = focusedTValues.length > 0 ? (focusedTValues.reduce((a, b) => a + b, 0) / focusedTValues.length).toFixed(1) : '--';

        const focusedMinH = focusedHValues.length > 0 ? Math.min(...focusedHValues).toFixed(1) : '--';
        const focusedMaxH = focusedHValues.length > 0 ? Math.max(...focusedHValues).toFixed(1) : '--';
        const focusedAvgH = focusedHValues.length > 0 ? (focusedHValues.reduce((a, b) => a + b, 0) / focusedHValues.length).toFixed(1) : '--';

        return (
          <div className="space-y-6">
            {/* ── Active Hardware Alarm / System Normal Status Banner ── */}
            {activeWarnings.length > 0 ? (
              <motion.div
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-2xl border border-rose-500/40 bg-gradient-to-r from-rose-950/50 via-rose-900/30 to-slate-900/70 p-4 backdrop-blur-md shadow-lg shadow-rose-950/20 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
              >
                <div className="flex items-start sm:items-center gap-3">
                  <div className="rounded-xl bg-rose-500/20 border border-rose-500/30 p-2.5 text-rose-400 shrink-0 animate-pulse">
                    <AlertTriangle className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-bold text-white tracking-wide">
                        Cold Storage Hardware Warnings Active
                      </h4>
                      <span className="rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] font-bold font-mono text-rose-300 border border-rose-500/30">
                        {activeWarnings.length} {activeWarnings.length === 1 ? 'Alert' : 'Alerts'}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-2 text-xs text-rose-200/90 font-medium">
                      {activeWarnings.map((w, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-rose-900/50 border border-rose-700/40 px-2.5 py-0.5"
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-rose-400 animate-ping" />
                          {typeof w === 'string' ? w : w.message || JSON.stringify(w)}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="text-[11px] font-mono text-rose-300/90 shrink-0 sm:text-right">
                  <span className="inline-block bg-rose-500/10 px-2.5 py-1 rounded-lg border border-rose-500/20">
                    Warning Buzzer Relay Ch22 Active
                  </span>
                </div>
              </motion.div>
            ) : (
            <></>
            )}

            {/* ── Top Summary KPI Strip ── */}
            <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
              {/* Card 1: Active Chambers */}
              <div className="rounded-2xl border border-slate-800/80 bg-slate-900/80 p-3.5 sm:p-5 backdrop-blur-sm hover:border-emerald-500/30 transition-all flex flex-col justify-between">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className={`rounded-xl p-2 shrink-0 ${isDeviceOnline ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400' : 'bg-slate-800 border border-slate-700 text-slate-400'}`}>
                      <Cpu className="h-4 w-4" />
                    </div>
                    <span className="text-xs font-semibold text-slate-300 truncate">Active Chambers</span>
                  </div>
                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider shrink-0 ${
                    isDeviceOnline
                      ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'
                      : 'bg-slate-800 border border-slate-700 text-slate-400'
                  }`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${isDeviceOnline ? 'bg-emerald-400 animate-pulse-dot' : 'bg-slate-500'}`} />
                    {isDeviceOnline ? `${multiSensorSummary.onlineCount}/${multiSensorSummary.totalProbes} Live` : 'Standby / Offline'}
                  </span>
                </div>
                <div className="mt-3 flex items-baseline gap-1.5">
                  <span className="text-2xl sm:text-3xl font-bold text-white tabular-nums tracking-tight">
                    {isDeviceOnline ? multiSensorSummary.onlineCount : 0}
                  </span>
                  <span className="text-xs text-slate-400 font-medium">/ {multiSensorSummary.totalProbes} online</span>
                </div>
                <p className="mt-2 text-[11px] text-slate-400 truncate">
                  {isDeviceOnline ? 'Monitored Cold Storage Rooms (S1–S7)' : 'Awaiting Live Hardware Telemetry'}
                </p>
              </div>

              {/* Card 2: Facility Average Temp */}
              <div className="rounded-2xl border border-slate-800/80 bg-slate-900/80 p-3.5 sm:p-5 backdrop-blur-sm hover:border-emerald-500/30 transition-all flex flex-col justify-between">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/20 p-2 text-emerald-400 shrink-0">
                      <Thermometer className="h-4 w-4" />
                    </div>
                    <span className="text-xs font-semibold text-slate-300 truncate">Facility Avg Temp</span>
                  </div>
                  <span className="text-[10px] font-mono font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20 shrink-0">
                    °C
                  </span>
                </div>
                <div className="mt-3 flex items-baseline gap-1">
                  <span className="text-2xl sm:text-3xl font-bold text-white tabular-nums tracking-tight">
                    {multiSensorSummary.avgTemp}
                  </span>
                  <span className="text-xs text-slate-400 font-medium">°C</span>
                </div>
                <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400 flex-wrap gap-1">
                  <span>Min: <strong className="text-slate-200 font-mono">{multiSensorSummary.minTemp}°C</strong></span>
                  <span>Max: <strong className="text-slate-200 font-mono">{multiSensorSummary.maxTemp}°C</strong></span>
                </div>
              </div>

              {/* Card 3: Facility Average Humidity */}
              <div className="rounded-2xl border border-slate-800/80 bg-slate-900/80 p-3.5 sm:p-5 backdrop-blur-sm hover:border-emerald-500/30 transition-all flex flex-col justify-between">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/20 p-2 text-emerald-400 shrink-0">
                      <Droplets className="h-4 w-4" />
                    </div>
                    <span className="text-xs font-semibold text-slate-300 truncate">Facility Avg Humidity</span>
                  </div>
                  <span className="text-[10px] font-mono font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20 shrink-0">
                    %
                  </span>
                </div>
                <div className="mt-3 flex items-baseline gap-1">
                  <span className="text-2xl sm:text-3xl font-bold text-white tabular-nums tracking-tight">
                    {multiSensorSummary.avgHumi}
                  </span>
                  <span className="text-xs text-slate-400 font-medium">%</span>
                </div>
                <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400 flex-wrap gap-1">
                  <span>Min: <strong className="text-slate-200 font-mono">{multiSensorSummary.minHumi}%</strong></span>
                  <span>Max: <strong className="text-slate-200 font-mono">{multiSensorSummary.maxHumi}%</strong></span>
                </div>
              </div>

              {/* Card 4: Atmosphere / CO2 */}
              <div className="rounded-2xl border border-slate-800/80 bg-slate-900/80 p-3.5 sm:p-5 backdrop-blur-sm hover:border-emerald-500/30 transition-all flex flex-col justify-between">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/20 p-2 text-emerald-400 shrink-0">
                      <Activity className="h-4 w-4" />
                    </div>
                    <span className="text-xs font-semibold text-slate-300 truncate">Chamber CO2</span>
                  </div>
                  <span className="text-[10px] font-mono font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20 shrink-0">
                    PPM
                  </span>
                </div>
                <div className="mt-3 flex items-baseline gap-1">
                  <span className="text-2xl sm:text-3xl font-bold text-white tabular-nums tracking-tight">
                    {multiSensorSummary.co2 != null ? multiSensorSummary.co2 : '--'}
                  </span>
                  <span className="text-xs text-slate-400 font-medium">ppm</span>
                </div>
                <p className="mt-2 text-[11px] text-slate-400 truncate">
                  Controlled Air Atmosphere
                </p>
              </div>
            </div>

            {/* ── Navigation & Sort Bar (Responsive & Touch-Friendly) ── */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-2 sm:pb-0">
              <div className="flex items-center gap-1 overflow-x-auto scrollbar-none touch-pan-x pb-1 sm:pb-0 -mx-1 px-1">
                {/* All Rooms Tab */}
                <button
                  onClick={() => setActiveMultiTab('all')}
                  className={`relative shrink-0 flex items-center gap-2 px-4 sm:px-5 py-3 text-xs sm:text-sm font-semibold transition-all hover:text-white ${
                    activeMultiTab === 'all' ? 'text-emerald-400' : 'text-slate-400'
                  }`}
                >
                  <LayoutGrid className="h-4 w-4" />
                  <span className="whitespace-nowrap">All Rooms Matrix</span>
                  <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] font-bold text-slate-300 border border-slate-700">
                    7
                  </span>
                  {activeMultiTab === 'all' && (
                    <motion.div
                      layoutId="activeMultiTabIndicator"
                      className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-500"
                    />
                  )}
                </button>

                {/* Individual Room Tabs (S1–S7) */}
                {DEFAULT_PROBE_PORTS.map((port) => {
                  const pData = multiSensorData[port];
                  const pName = getProbeName(port, deviceMeta, customSensorNames);
                  const isOnline = isDeviceOnline && (pData?.status === 'OK' || pData?.status === 'online');
                  const isActive = activeMultiTab === port;
                  const hasAlarm = activeWarnings.some((w) => {
                    const text = typeof w === 'string' ? w.toLowerCase() : JSON.stringify(w).toLowerCase();
                    return text.includes(port.toLowerCase()) || text.includes(`room ${port.replace('S', '')}`);
                  });

                  return (
                    <button
                      key={port}
                      onClick={() => setActiveMultiTab(port)}
                      className={`relative shrink-0 flex items-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-3 text-xs font-semibold transition-all hover:text-white ${
                        isActive ? 'text-emerald-400' : hasAlarm ? 'text-rose-400' : 'text-slate-400'
                      }`}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          hasAlarm ? 'bg-rose-500 animate-ping' : isOnline ? 'bg-emerald-400' : 'bg-slate-600'
                        }`}
                      />
                      <span className="whitespace-nowrap">{pName}</span>
                      <span className="font-mono text-[10px] text-slate-500">({port})</span>
                      {pData?.t != null && pData.t > 0 && (
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-mono tabular-nums ${
                            isActive
                              ? 'bg-emerald-500/20 text-emerald-300'
                              : 'bg-slate-800/80 text-slate-300'
                          }`}
                        >
                          {pData.t.toFixed(1)}°C
                        </span>
                      )}
                      {isActive && (
                        <motion.div
                          layoutId="activeMultiTabIndicator"
                          className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-500"
                        />
                      )}
                    </button>
                  );
                })}
              </div>

              {activeMultiTab === 'all' && (
                <div className="flex items-center justify-between sm:justify-end gap-2 shrink-0 pt-1 sm:pt-0 sm:pl-4">
                  <span className="text-[11px] text-slate-400 font-medium">Sort:</span>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value)}
                    className="bg-slate-950 border border-slate-700/80 rounded-lg px-2.5 py-1 text-xs text-slate-200 outline-none focus:border-emerald-500 transition-colors"
                  >
                    <option value="id">Port Sequence (S1–S7)</option>
                    <option value="temp">Highest Temperature</option>
                    <option value="humi">Highest Humidity</option>
                  </select>
                </div>
              )}
            </div>

            {/* ── View 1: All Rooms 7-Card Matrix ── */}
            {activeMultiTab === 'all' && (
              <div className="space-y-4">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {sortedPorts.map((sensorId) => {
                    const data = multiSensorData[sensorId] || { t: null, h: null, status: 'STANDBY' };
                    const history = sensorHistory?.[sensorId] || { t: [], h: [] };
                    const roomName = getProbeName(sensorId, deviceMeta, customSensorNames);
                    const setpoints = multiSensorSetpoints[sensorId];
                    const relays = multiSensorRelays[sensorId];
                    const hasAlarm = activeWarnings.some((w) => {
                      const text = typeof w === 'string' ? w.toLowerCase() : JSON.stringify(w).toLowerCase();
                      return text.includes(sensorId.toLowerCase()) || text.includes(`room ${sensorId.replace('S', '')}`);
                    });

                    return (
                      <ColdRoomProbeCard
                        key={sensorId}
                        sensorId={sensorId}
                        roomName={roomName}
                        data={data}
                        history={history}
                        setpoints={setpoints}
                        relays={relays}
                        hasAlarm={hasAlarm}
                        isDeviceOnline={isDeviceOnline}
                        onSelect={setSelectedSensor}
                        onFocus={(id) => setActiveMultiTab(id)}
                      />
                    );
                  })}
                </div>

                {Object.keys(multiSensorData).length === 0 && !loading && (
                  <div className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/30 py-12 text-center text-slate-400 text-sm">
                    <p className="animate-pulse text-emerald-400 font-semibold mb-1">
                      Listening for Multi-Sensor Telemetry Packets...
                    </p>
                    <p className="text-xs text-slate-500">
                      Cold storage telemetry will automatically stream here over MQTT / SSE.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* ── View 2: Single Room Detailed Focus View ── */}
            {activeMultiTab !== 'all' && (
              <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
                {/* Left Column (1 col): Live Readings, Actuators & Targets */}
                <div className="space-y-4 xl:col-span-1">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-2">
                      Live Chamber Focus ({focusedRoomName})
                    </h3>
                    <button
                      onClick={() => setActiveMultiTab('all')}
                      className="flex items-center gap-1 text-xs font-semibold text-emerald-400 hover:text-emerald-300 transition-colors"
                    >
                      <ArrowLeft className="h-3.5 w-3.5" /> All Rooms
                    </button>
                  </div>

                  {/* Room Identity Card */}
                  <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 p-4 backdrop-blur-sm">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <span className="rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 text-xs font-mono font-bold text-emerald-400">
                          {activeMultiTab}
                        </span>
                        <div>
                          <h4 className="text-sm font-bold text-white">{focusedRoomName}</h4>
                          <p className="text-[11px] text-slate-400">
                            {focusedSetpoints?.stage_name
                              ? `${focusedSetpoints.stage_name} • Slot ${focusedSetpoints.slot_id || '1'}`
                              : 'Cold Storage Room Channel'}
                          </p>
                        </div>
                      </div>
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                          isDeviceOnline && (focusedProbeData?.status === 'OK' || focusedProbeData?.status === 'online')
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-slate-800 text-slate-400 border border-slate-700'
                        }`}
                      >
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${
                            isDeviceOnline && (focusedProbeData?.status === 'OK' || focusedProbeData?.status === 'online')
                              ? 'bg-emerald-400 animate-pulse-dot'
                              : 'bg-slate-500'
                          }`}
                        />
                        {isDeviceOnline && (focusedProbeData?.status === 'OK' || focusedProbeData?.status === 'online')
                          ? 'Online'
                          : 'Standby'}
                      </span>
                    </div>

                    {focusedAlarms.length > 0 && (
                      <div className="mt-3 rounded-xl border border-rose-500/30 bg-rose-950/40 p-2.5 text-xs text-rose-300 flex items-center gap-2">
                        <AlertTriangle className="h-4 w-4 text-rose-400 shrink-0" />
                        <span className="truncate">{focusedAlarms.join(' • ')}</span>
                      </div>
                    )}
                  </div>

                  
                  {/* Target Setpoints & Tolerance Bounds */}
                  {focusedSetpoints && (
                    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 p-4 backdrop-blur-sm space-y-3">
                      <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                        <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                          <Layers className="h-3.5 w-3.5 text-emerald-400" /> Target Setpoints & Bounds
                        </span>
                        {focusedSetpoints.stage_name && (
                          <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                            {focusedSetpoints.stage_name}
                          </span>
                        )}
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="rounded-xl bg-slate-950/40 p-2.5 border border-slate-800/60">
                          <span className="text-[10px] text-slate-500 block mb-0.5">Target Temp</span>
                          <div className="text-lg font-bold text-white font-mono">
                            {focusedSetpoints.target_temp != null ? `${focusedSetpoints.target_temp}°C` : '--'}
                          </div>
                          {focusedSetpoints.temp_range != null && (
                            <span className="text-[10px] text-slate-400 font-mono">
                              ±{focusedSetpoints.temp_range}°C band
                            </span>
                          )}
                          {(focusedSetpoints.min_temp != null || focusedSetpoints.max_temp != null) && (
                            <div className="mt-1 text-[9px] text-slate-500 font-mono truncate">
                              Safety: {focusedSetpoints.min_temp ?? 0}° - {focusedSetpoints.max_temp ?? 50}°C
                            </div>
                          )}
                        </div>

                        <div className="rounded-xl bg-slate-950/40 p-2.5 border border-slate-800/60">
                          <span className="text-[10px] text-slate-500 block mb-0.5">Target Humidity</span>
                          <div className="text-lg font-bold text-white font-mono">
                            {focusedSetpoints.target_humi != null ? `${focusedSetpoints.target_humi}%` : '--'}
                          </div>
                          {focusedSetpoints.humi_range != null && (
                            <span className="text-[10px] text-slate-400 font-mono">
                              ±{focusedSetpoints.humi_range}% band
                            </span>
                          )}
                          {(focusedSetpoints.min_humi != null || focusedSetpoints.max_humi != null) && (
                            <div className="mt-1 text-[9px] text-slate-500 font-mono truncate">
                              Safety: {focusedSetpoints.min_humi ?? 0}% - {focusedSetpoints.max_humi ?? 100}%
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Big Metric Cards Grid */}
                  <div className="space-y-3">
                    <BigMetric
                      label={`${focusedRoomName} Temperature`}
                      value={focusedProbeData?.t}
                      unit="°C"
                      icon={Thermometer}
                      type="temperature"
                    />

                    <BigMetric
                      label={`${focusedRoomName} Humidity`}
                      value={focusedProbeData?.h}
                      unit="%"
                      icon={Droplets}
                      type="moisture"
                    />

                    {focusedProbeData?.co2 != null && (
                      <BigMetric
                        label={`${focusedRoomName} CO2 Level`}
                        value={focusedProbeData?.co2}
                        unit="ppm"
                        icon={Activity}
                        type="co2"
                      />
                    )}
                  </div>

                
                </div>

                {/* Right Column (2 cols): Real-time Trend Charts */}
                <div className="space-y-4 xl:col-span-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                      Real-Time Telemetry Trends ({focusedRoomName})
                    </h3>
                    <button
                      onClick={() => setSelectedSensor(activeMultiTab)}
                      className="flex items-center gap-1 text-xs text-slate-400 hover:text-emerald-400 transition-colors"
                      title="Inspect in full modal"
                    >
                      <Maximize2 className="h-3.5 w-3.5" /> Fullscreen Modal
                    </button>
                  </div>

                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <LiveChart
                      data={focusedHistT}
                      type="temperature"
                      title={`${focusedRoomName} Temperature`}
                      unit="°C"
                      subtitle="Continuous Telemetry Feed"
                    />

                    <LiveChart
                      data={focusedHistH}
                      type="moisture"
                      title={`${focusedRoomName} Humidity`}
                      unit="%"
                      subtitle="Continuous Telemetry Feed"
                    />

                    {focusedProbeData?.co2 != null && (
                      <div className="md:col-span-2">
                        <LiveChart
                          data={(focusedHistCo2.length > 0 ? focusedHistCo2 : focusedHistT).map((pt) => ({
                            time: pt.time,
                            value: pt.value ?? focusedProbeData?.co2 ?? 420,
                          }))}
                          type="co2"
                          title={`${focusedRoomName} CO2 Atmospheric Trend`}
                          unit="ppm"
                          subtitle="Atmospheric Carbon Dioxide"
                        />
                      </div>
                    )}
                  </div>
                  {/* Hardware Actuators & Relays State */}
                  <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 p-4 backdrop-blur-sm space-y-3">
                    <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                      <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                        <Zap className="h-3.5 w-3.5 text-emerald-400" /> Chamber Actuators (Relays)
                      </span>
                      <span className="text-[10px] font-mono text-slate-400">
                        Channels {focusedChCooling}, {focusedChHumi}, {focusedChLight}
                      </span>
                    </div>

                    <div className="grid grid-cols-3 gap-2 text-xs">
                      {/* Cooling / AC / Fanpad */}
                      <div
                        className={`rounded-xl p-2.5 border text-center transition-all ${
                          focusedRelays?.cooling
                            ? 'bg-emerald-500/15 border-emerald-500/30 shadow-sm shadow-emerald-500/10'
                            : 'bg-slate-950/40 border-slate-800/60'
                        }`}
                      >
                        <div className="flex items-center justify-center mb-1">
                          {focusedIsS7 ? (
                            <Fan
                              className={`h-4 w-4 ${
                                focusedRelays?.cooling ? 'text-emerald-400 animate-spin' : 'text-slate-500'
                              }`}
                            />
                          ) : (
                            <Thermometer
                              className={`h-4 w-4 ${
                                focusedRelays?.cooling ? 'text-emerald-400' : 'text-slate-500'
                              }`}
                            />
                          )}
                        </div>
                        <div className="text-[10px] font-medium text-slate-400 truncate">{focusedCoolingLabel}</div>
                        <div className="text-[9px] text-slate-500 font-mono">Ch {focusedChCooling}</div>
                        <div
                          className={`mt-1 text-[11px] font-bold font-mono ${
                            focusedRelays?.cooling ? 'text-emerald-300' : 'text-slate-500'
                          }`}
                        >
                          {focusedRelays?.cooling ? 'ON' : 'OFF'}
                        </div>
                      </div>

                      {/* Humidifier */}
                      <div
                        className={`rounded-xl p-2.5 border text-center transition-all ${
                          focusedRelays?.humi
                            ? 'bg-sky-500/15 border-sky-500/30 shadow-sm shadow-sky-500/10'
                            : 'bg-slate-950/40 border-slate-800/60'
                        }`}
                      >
                        <div className="flex items-center justify-center mb-1">
                          <Droplets
                            className={`h-4 w-4 ${focusedRelays?.humi ? 'text-sky-400' : 'text-slate-500'}`}
                          />
                        </div>
                        <div className="text-[10px] font-medium text-slate-400 truncate">Humidifier</div>
                        <div className="text-[9px] text-slate-500 font-mono">Ch {focusedChHumi}</div>
                        <div
                          className={`mt-1 text-[11px] font-bold font-mono ${
                            focusedRelays?.humi ? 'text-sky-300' : 'text-slate-500'
                          }`}
                        >
                          {focusedRelays?.humi ? 'ON' : 'OFF'}
                        </div>
                      </div>

                      {/* Grow Lights */}
                      <div
                        className={`rounded-xl p-2.5 border text-center transition-all ${
                          focusedRelays?.light
                            ? 'bg-amber-500/15 border-amber-500/30 shadow-sm shadow-amber-500/10'
                            : 'bg-slate-950/40 border-slate-800/60'
                        }`}
                      >
                        <div className="flex items-center justify-center mb-1">
                          <Sun
                            className={`h-4 w-4 ${focusedRelays?.light ? 'text-amber-400' : 'text-slate-500'}`}
                          />
                        </div>
                        <div className="text-[10px] font-medium text-slate-400 truncate">Grow Lights</div>
                        <div className="text-[9px] text-slate-500 font-mono">Ch {focusedChLight}</div>
                        <div
                          className={`mt-1 text-[11px] font-bold font-mono ${
                            focusedRelays?.light ? 'text-amber-300' : 'text-slate-500'
                          }`}
                        >
                          {focusedRelays?.light ? 'ON' : 'OFF'}
                        </div>
                      </div>
                    </div>
                  </div>

                </div>
              </div>
            )}
          </div>
        );
      })()}

      {/* ── Multi-Sensor Sensor Detail Modal (Theme Elevated) ─────────────── */}
      {selectedSensor && multiSensorData[selectedSensor] && (() => {
        const modalData = multiSensorData[selectedSensor];
        const modalRoomName = getProbeName(selectedSensor, deviceMeta, customSensorNames);
        const modalSetpoints = multiSensorSetpoints[selectedSensor];
        const modalRelays = multiSensorRelays[selectedSensor];
        const modalIdx = parseInt(selectedSensor.replace('S', ''), 10) - 1;
        const modalChCooling = (modalIdx * 3) + 1;
        const modalChHumi = (modalIdx * 3) + 2;
        const modalChLight = (modalIdx * 3) + 3;
        const modalIsS7 = selectedSensor === 'S7';
        const modalCoolingLabel = modalIsS7 ? 'Fanpad' : 'AC / Cooling';

        return (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in">
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 15 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96 }}
              className="w-full max-w-4xl bg-slate-900 border border-slate-700/80 rounded-3xl p-6 sm:p-8 shadow-2xl relative overflow-y-auto max-h-[90vh]"
            >
              <button
                onClick={() => setSelectedSensor(null)}
                className="absolute top-5 right-5 rounded-full p-2 text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
              >
                <X className="h-5 w-5" />
              </button>

              {/* Modal Header */}
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 mb-6 sm:mb-8">
                <div className="p-3 sm:p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-2xl shrink-0">
                  <Cpu className="h-6 w-6 sm:h-7 sm:w-7 text-emerald-400" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 text-xs font-mono font-bold text-emerald-400">
                      {selectedSensor}
                    </span>
                    <h2 className="text-xl sm:text-2xl font-bold text-white tracking-wide truncate">
                      {modalRoomName}
                    </h2>
                    {modalSetpoints?.stage_name && (
                      <span className="rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-0.5 text-[10px] font-bold text-emerald-300">
                        {modalSetpoints.stage_name}
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-slate-400 block truncate">
                    Live Telemetry Analysis & Historical Trends • Updated {formatTimestamp(liveDevice?.lastUpdated)}
                  </span>
                </div>
              </div>

              {/* Live KPI Tiles */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                <div className="bg-slate-950/60 p-4 sm:p-5 rounded-2xl border border-slate-800/80 hover:border-emerald-500/20 transition-all flex flex-col justify-center">
                  <div className="flex items-center justify-between mb-1.5">
                    <p className="text-xs text-slate-400 flex items-center gap-1.5 font-medium">
                      <Thermometer className="h-4 w-4 text-emerald-400" /> Live Temperature
                    </p>
                    {modalSetpoints?.target_temp != null && (
                      <span className="text-[10px] font-mono font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                        Target: {modalSetpoints.target_temp}°C
                      </span>
                    )}
                  </div>
                  <div className="flex items-baseline gap-1">
                    <span className="text-2xl sm:text-3xl font-bold text-white tabular-nums tracking-tight">
                      {modalData?.t != null ? Number(modalData.t).toFixed(2) : '--'}
                    </span>
                    <span className="text-xs text-slate-400 font-medium">°C</span>
                  </div>
                </div>

                <div className="bg-slate-950/60 p-4 sm:p-5 rounded-2xl border border-slate-800/80 hover:border-emerald-500/20 transition-all flex flex-col justify-center">
                  <div className="flex items-center justify-between mb-1.5">
                    <p className="text-xs text-slate-400 flex items-center gap-1.5 font-medium">
                      <Droplets className="h-4 w-4 text-emerald-400" /> Live Humidity
                    </p>
                    {modalSetpoints?.target_humi != null && (
                      <span className="text-[10px] font-mono font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                        Target: {modalSetpoints.target_humi}%
                      </span>
                    )}
                  </div>
                  <div className="flex items-baseline gap-1">
                    <span className="text-2xl sm:text-3xl font-bold text-white tabular-nums tracking-tight">
                      {modalData?.h != null ? Number(modalData.h).toFixed(2) : '--'}
                    </span>
                    <span className="text-xs text-slate-400 font-medium">%</span>
                  </div>
                </div>

                <div className="bg-slate-950/60 p-4 sm:p-5 rounded-2xl border border-slate-800/80 hover:border-emerald-500/20 transition-all flex flex-col justify-center sm:col-span-2 lg:col-span-1">
                  <p className="text-xs text-slate-400 mb-1.5 flex items-center gap-1.5 font-medium">
                    <Activity className="h-4 w-4 text-emerald-400" /> Chamber CO2
                  </p>
                  <div className="flex items-baseline gap-1">
                    <span className="text-2xl sm:text-3xl font-bold text-white tabular-nums tracking-tight">
                      {modalData?.co2 != null ? modalData.co2 : '420'}
                    </span>
                    <span className="text-xs text-slate-400 font-medium">ppm</span>
                  </div>
                </div>
              </div>

              {/* Hardware Relays Status Row */}
              {modalRelays && (
                <div className="mb-6 rounded-2xl border border-slate-800/80 bg-slate-950/50 p-4">
                  <div className="flex items-center justify-between text-xs font-semibold text-slate-300 mb-3">
                    <span className="flex items-center gap-1.5">
                      <Zap className="h-3.5 w-3.5 text-emerald-400" /> Actuator Relay States
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">
                      Channels {modalChCooling}, {modalChHumi}, {modalChLight}
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    <div
                      className={`rounded-xl p-3 border text-center ${
                        modalRelays.cooling
                          ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
                          : 'bg-slate-900/60 border-slate-800 text-slate-500'
                      }`}
                    >
                      <div className="text-[11px] font-medium">{modalCoolingLabel} (Ch {modalChCooling})</div>
                      <div className="text-sm font-bold font-mono mt-1">
                        {modalRelays.cooling ? 'ACTIVE (ON)' : 'OFF'}
                      </div>
                    </div>
                    <div
                      className={`rounded-xl p-3 border text-center ${
                        modalRelays.humi
                          ? 'bg-sky-500/15 border-sky-500/30 text-sky-300'
                          : 'bg-slate-900/60 border-slate-800 text-slate-500'
                      }`}
                    >
                      <div className="text-[11px] font-medium">Humidifier (Ch {modalChHumi})</div>
                      <div className="text-sm font-bold font-mono mt-1">
                        {modalRelays.humi ? 'ACTIVE (ON)' : 'OFF'}
                      </div>
                    </div>
                    <div
                      className={`rounded-xl p-3 border text-center ${
                        modalRelays.light
                          ? 'bg-amber-500/15 border-amber-500/30 text-amber-300'
                          : 'bg-slate-900/60 border-slate-800 text-slate-500'
                      }`}
                    >
                      <div className="text-[11px] font-medium">Grow Lights (Ch {modalChLight})</div>
                      <div className="text-sm font-bold font-mono mt-1">
                        {modalRelays.light ? 'ACTIVE (ON)' : 'OFF'}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Live Trend Charts in Modal */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <LiveChart
                  data={sensorHistory?.[selectedSensor]?.t || []}
                  type="temperature"
                  title={`${modalRoomName} Temperature Trend`}
                  unit="°C"
                />
                <LiveChart
                  data={sensorHistory?.[selectedSensor]?.h || []}
                  type="moisture"
                  title={`${modalRoomName} Humidity Trend`}
                  unit="%"
                />
              </div>
            </motion.div>
          </div>
        );
      })()}

      {/* ── Standard Single-Device Content Grid (Monit, Generic Single Device) ──── */}
      {isStandardDevice && (
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