import { useState, useEffect, useCallback, useRef, memo, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
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
  ChevronRight,
  Sun,
  Leaf,
  Sprout,
  Tag,
  Box,
  Sliders,
} from 'lucide-react';
import LiveChart from '../../components/LiveChart';
import { SkeletonCard } from '../../components/Skeleton';
import { createMqttClient } from '../../utils/mqtt';
import { telemetryWs } from '../../utils/websocketClient';
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

const DEFAULT_OFFICE_ROOM_SETUPS = {
  1: 'Room 1 Hydroponics Setup',
  2: 'Room 2 Hydroponics Setup',
  3: 'Room 3 Climate Setup',
};

const DEFAULT_PROBE_PORTS = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7'];

const getProbeName = (sensorId, deviceMeta, customNames = {}) => {
  if (!sensorId) return 'Cold Room';
  const upper = String(sensorId).toUpperCase();
  const custom =
    customNames?.[upper] ||
    customNames?.[sensorId] ||
    deviceMeta?.config?.sensor_names?.[upper] ||
    deviceMeta?.system_config?.sensor_names?.[upper] ||
    deviceMeta?.sensor_names?.[sensorId] ||
    deviceMeta?.sensor_names?.[upper] ||
    deviceMeta?.sensorNames?.[sensorId] ||
    deviceMeta?.sensorNames?.[upper];
  if (custom) return custom;
  return DEFAULT_ROOM_NAMES[upper] || `Cold Room ${upper.replace('S', '')}`;
};

const resolveRoomSetpointInfo = (setpoints, sensorId) => {
  if (!setpoints) {
    return {
      targetTemp: null,
      targetHumi: null,
      tempMin: null,
      tempMax: null,
      humiMin: null,
      humiMax: null,
      cropName: DEFAULT_ROOM_NAMES[sensorId] ? `${DEFAULT_ROOM_NAMES[sensorId]} Program` : 'Storage Program',
      stageName: null,
      setupName: DEFAULT_ROOM_NAMES[sensorId] ? `${DEFAULT_ROOM_NAMES[sensorId]} Setup` : 'Storage Setup',
    };
  }

  // Find active setting stage if nested in .settings
  const activeSettingKey = setpoints.active_setting || (setpoints.settings ? Object.keys(setpoints.settings)[0] : null);
  const activeStage = activeSettingKey && setpoints.settings?.[activeSettingKey]
    ? setpoints.settings[activeSettingKey]
    : (setpoints.time_slots ? setpoints : null);

  // Find active slot (or first slot)
  const slot = activeStage?.time_slots?.[0] || setpoints?.time_slots?.[0] || {};

  const targetTemp = setpoints.target_temp ?? slot.t_set ?? setpoints.temp ?? null;
  const targetHumi = setpoints.target_humi ?? slot.h_set ?? setpoints.humi ?? null;

  const tempMin = slot.t_min ?? setpoints.t_min ?? setpoints['T MIN'] ?? null;
  const tempMax = slot.t_max ?? setpoints.t_max ?? setpoints['T MAX'] ?? null;
  const humiMin = slot.h_min ?? setpoints.h_min ?? setpoints['H MIN'] ?? null;
  const humiMax = slot.h_max ?? setpoints.h_max ?? setpoints['H MAX'] ?? null;

  const cropName = setpoints.program_name || setpoints.crop_name || activeStage?.crop_name || setpoints['Crop Name'] || (DEFAULT_ROOM_NAMES[sensorId] ? `${DEFAULT_ROOM_NAMES[sensorId]} Program` : 'Storage Program');
  const stageName = activeStage?.name || setpoints.stage_name || null;
  const setupName = setpoints.setup_name || activeStage?.setup_name || (DEFAULT_ROOM_NAMES[sensorId] ? `${DEFAULT_ROOM_NAMES[sensorId]} Setup` : 'Storage Setup');

  return {
    targetTemp: targetTemp != null ? Number(targetTemp).toFixed(1) : null,
    targetHumi: targetHumi != null ? Number(targetHumi).toFixed(1) : null,
    tempMin: tempMin != null ? Number(tempMin).toFixed(1) : null,
    tempMax: tempMax != null ? Number(tempMax).toFixed(1) : null,
    humiMin: humiMin != null ? Number(humiMin).toFixed(1) : null,
    humiMax: humiMax != null ? Number(humiMax).toFixed(1) : null,
    cropName,
    stageName,
    setupName,
  };
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
  ({ label, value, unit, icon: Icon, type, isOnline = true }) => {
    const isValValid = Number.isFinite(value) && value !== null && (type === 'default' ? true : value > 0);
    const safeValue = isValValid ? value : null;
    const status = isOnline && safeValue != null ? getMetricStatus(type, safeValue) : 'offline';
    const color = isOnline && safeValue != null && status !== 'offline' ? getMetricColor(status) : 'text-slate-400';

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
          {safeValue != null ? (
            <>
              <span className={`text-2xl font-bold tabular-nums ${color}`}>
                {type === 'ec' ? safeValue : safeValue.toFixed(1)}
              </span>
              <span className="text-sm text-slate-500">{unit}</span>
            </>
          ) : (
            <span className="text-base font-semibold text-slate-400 font-mono tracking-wider">
              N/A
            </span>
          )}
        </div>
        <div className="mt-1.5 flex items-center gap-1.5">
          <div
            className={`h-1.5 w-1.5 rounded-full ${!isOnline || safeValue == null || status === 'offline'
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
          <span className="text-xs text-slate-500 capitalize">{isOnline && safeValue != null && status !== 'offline' ? status : 'Offline'}</span>
        </div>
      </div>
    );
  },
  (prev, next) =>
    prev.value === next.value &&
    prev.label === next.label &&
    prev.unit === next.unit &&
    prev.type === next.type &&
    prev.isOnline === next.isOnline
);

// ── Memoized Specialized EC / TDS Card (P2 Optimization) ─────────────────────
const EcMetricCard = memo(
  ({ label = 'Electrical Conductivity (EC)', ecVal, unit = 'mS/cm', isOnline = true }) => {
    const isValValid = Number.isFinite(ecVal) && ecVal > 0;
    const effectiveEc = isValValid ? ecVal : null;
    const tdsVal = effectiveEc != null ? Math.round(effectiveEc * 500) : null;
    const ecStatus = isOnline && effectiveEc != null ? getMetricStatus('ec', effectiveEc) : 'offline';
    const ecColor = isOnline && effectiveEc != null && ecStatus !== 'offline' ? getMetricColor(ecStatus) : 'text-slate-400';
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
          {effectiveEc != null ? (
            <>
              <span className={`text-2xl font-bold tabular-nums ${ecColor}`}>
                {effectiveEc}
              </span>
              <span className="text-sm text-slate-500">{unit}</span>
              {tdsVal != null && (
                <span className="text-sm text-slate-400 font-semibold font-mono">
                  ({tdsVal} ppm)
                </span>
              )}
            </>
          ) : (
            <span className="text-base font-semibold text-slate-400 font-mono tracking-wider">
              N/A
            </span>
          )}
        </div>
        <div className="mt-1.5 flex items-center gap-1.5">
          <div
            className={`h-1.5 w-1.5 rounded-full ${!isOnline || effectiveEc == null || ecStatus === 'offline'
              ? 'bg-slate-500'
              : ecStatus === 'normal'
                ? 'bg-emerald-400'
                : ecStatus === 'warning'
                  ? 'bg-yellow-400'
                  : ecStatus === 'critical'
                    ? 'bg-red-400'
                    : 'bg-slate-500'
              }`}
          />
          <span className="text-xs text-slate-500 capitalize">{isOnline && effectiveEc != null && ecStatus !== 'offline' ? ecStatus : 'Offline'}</span>
        </div>
      </div>
    );
  },
  (prev, next) => prev.ecVal === next.ecVal && prev.label === next.label && prev.isOnline === next.isOnline
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
    const tVal = isOnline && data?.t != null && Number(data.t) > 0 ? Number(data.t).toFixed(1) : null;
    const hVal = isOnline && data?.h != null && Number(data.h) > 0 ? Number(data.h).toFixed(1) : null;
    const co2Val = isOnline && data?.co2 != null && Number(data.co2) > 0 ? Number(data.co2).toFixed(0) : null;

    const spInfo = resolveRoomSetpointInfo(setpoints, sensorId);

    // Calculate min and max from history
    const tHistoryValues = (history?.t || [])
      .map((d) => (typeof d === 'object' && d !== null ? d.value : Number(d)))
      .filter((v) => Number.isFinite(v) && v > 0);
    const minT = isOnline && tHistoryValues.length > 0 ? Math.min(...tHistoryValues).toFixed(1) : 'N/A';
    const maxT = isOnline && tHistoryValues.length > 0 ? Math.max(...tHistoryValues).toFixed(1) : 'N/A';

    const isS7 = sensorId === 'S7';
    const coolingLabel = isS7 ? 'Fanpad' : 'AC';

    return (
      <motion.div
        whileHover={{ y: -3, transition: { duration: 0.2 } }}
        className={`group relative flex flex-col justify-between overflow-hidden rounded-2xl border p-4 sm:p-5 backdrop-blur-md transition-all duration-300 cursor-pointer ${hasAlarm
          ? 'border-rose-500/80 bg-rose-950/20 hover:border-rose-400 hover:bg-rose-950/30 shadow-lg shadow-rose-500/10'
          : 'border-slate-800/80 bg-slate-900/60 hover:border-emerald-500/40 hover:bg-slate-900/90 hover:shadow-xl hover:shadow-emerald-500/5'
          }`}
        onClick={() => (onFocus ? onFocus(sensorId) : onSelect(sensorId))}
      >
        {/* Top Glow Accent on Hover */}
        <div
          className={`absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent ${hasAlarm ? 'via-rose-500/80' : 'via-emerald-500/0 group-hover:via-emerald-500/60'
            } to-transparent transition-all duration-500`}
        />

        {/* Card Header: Port Badge, Room Name, Status */}
        <div className="mb-3.5 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="shrink-0 rounded-xl bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 text-xs font-mono font-black text-emerald-400">
              {sensorId}
            </span>
            <div className="min-w-0">
              <h4 className="text-sm font-bold text-white group-hover:text-emerald-300 transition-colors truncate tracking-tight">
                {roomName || `Cold Room ${sensorId.toUpperCase().replace('S', '')}`}
              </h4>
              <div className="flex items-center gap-1.5 flex-wrap text-[11px] text-slate-400 font-medium truncate mt-0.5">
                <span className="text-emerald-400 font-semibold truncate max-w-[130px] flex items-center gap-1">
                  <Sprout className="h-3 w-3" />
                  {spInfo.cropName}
                </span>
                {spInfo.stageName && (
                  <>
                    <span className="text-slate-600">•</span>
                    <span className="text-slate-400 truncate">{spInfo.stageName}</span>
                  </>
                )}
              </div>
            </div>
          </div>
          <span
            className={`shrink-0 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${isOnline
              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
              : 'bg-slate-800 text-slate-400 border border-slate-700'
              }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${isOnline ? 'bg-emerald-400 animate-pulse-dot' : 'bg-slate-500'
                }`}
            />
            {isOnline ? 'Live' : 'Standby'}
          </span>
        </div>

        {/* Main Sensor KPI Grid */}
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2.5 sm:gap-3">
            {/* Temperature Tile */}
            <div className="rounded-xl bg-slate-950/70 border border-amber-500/20 p-3 transition-colors group-hover:border-amber-500/40">
              <div className="flex items-center justify-between mb-1">
                <p className="text-[10px] font-bold uppercase tracking-wider text-amber-400/90 flex items-center gap-1">
                  <Thermometer className="h-3.5 w-3.5 text-amber-400" /> Temp
                </p>
                {spInfo.targetTemp != null ? (
                  <span className="text-[10px] font-mono font-bold text-amber-300 bg-amber-500/10 px-1.5 py-0.2 rounded border border-amber-500/20">
                    Set: {spInfo.targetTemp}°C
                  </span>
                ) : (
                  <span className="text-[9px] font-mono text-slate-400">Set: --</span>
                )}
              </div>
              <div className="flex items-baseline gap-1">
                {tVal !== null ? (
                  <>
                    <span className="text-2xl font-black font-mono tabular-nums text-white group-hover:text-amber-400 transition-colors">
                      {tVal}
                    </span>
                    <span className="text-xs font-semibold text-slate-400">°C</span>
                  </>
                ) : (
                  <span className="text-base font-semibold text-slate-400 font-mono tracking-wider">
                    N/A
                  </span>
                )}
              </div>
              {spInfo.tempMin != null && spInfo.tempMax != null && (
                <div className="mt-1 text-[9px] font-mono text-slate-400 truncate">
                  Band: {spInfo.tempMin}° - {spInfo.tempMax}°C
                </div>
              )}
            </div>

            {/* Humidity Tile */}
            <div className="rounded-xl bg-slate-950/70 border border-sky-500/20 p-3 transition-colors group-hover:border-sky-500/40">
              <div className="flex items-center justify-between mb-1">
                <p className="text-[10px] font-bold uppercase tracking-wider text-sky-400/90 flex items-center gap-1">
                  <Droplets className="h-3.5 w-3.5 text-sky-400" /> Humidity
                </p>
                {spInfo.targetHumi != null ? (
                  <span className="text-[10px] font-mono font-bold text-sky-300 bg-sky-500/10 px-1.5 py-0.2 rounded border border-sky-500/20">
                    Set: {spInfo.targetHumi}%
                  </span>
                ) : (
                  <span className="text-[9px] font-mono text-slate-400">Set: --</span>
                )}
              </div>
              <div className="flex items-baseline gap-1">
                {hVal !== null ? (
                  <>
                    <span className="text-2xl font-black font-mono tabular-nums text-white group-hover:text-sky-300 transition-colors">
                      {hVal}
                    </span>
                    <span className="text-xs font-semibold text-slate-400">%</span>
                  </>
                ) : (
                  <span className="text-base font-semibold text-slate-400 font-mono tracking-wider">
                    N/A
                  </span>
                )}
              </div>
              {spInfo.humiMin != null && spInfo.humiMax != null && (
                <div className="mt-1 text-[9px] font-mono text-slate-400 truncate">
                  Band: {spInfo.humiMin}% - {spInfo.humiMax}%
                </div>
              )}
            </div>
          </div>

          {/* Chamber CO2 */}
          <div className="flex items-center justify-between rounded-xl bg-slate-950/60 border border-slate-800/80 px-3 py-1.5 text-xs">
            <span className="text-[10px] text-emerald-400 font-bold uppercase tracking-wider flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-emerald-400" /> Chamber CO2
            </span>
            <span className="font-mono font-black text-emerald-300">
              {co2Val != null ? `${co2Val} ` : '-- '}
              <span className="text-[10px] font-normal text-slate-400">ppm</span>
            </span>
          </div>

          {/* Hardware Relays Mini Status Bar */}
          {relays && (
            <div className="grid grid-cols-3 gap-1.5 pt-0.5">
              <div
                className={`rounded-xl px-2 py-1 text-[10px] font-semibold text-center border transition-all ${relays.cooling
                  ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
                  : 'bg-slate-950/40 border-slate-800/60 text-slate-500'
                  }`}
              >
                {coolingLabel}: <strong className={relays.cooling ? 'text-emerald-400' : 'text-slate-400'}>{relays.cooling ? 'ON' : 'OFF'}</strong>
              </div>
              <div
                className={`rounded-xl px-2 py-1 text-[10px] font-semibold text-center border transition-all ${relays.humi
                  ? 'bg-sky-500/15 border-sky-500/30 text-sky-300'
                  : 'bg-slate-950/40 border-slate-800/60 text-slate-500'
                  }`}
              >
                Humi: <strong className={relays.humi ? 'text-sky-400' : 'text-slate-400'}>{relays.humi ? 'ON' : 'OFF'}</strong>
              </div>
              <div
                className={`rounded-xl px-2 py-1 text-[10px] font-semibold text-center border transition-all ${relays.light
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
            <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
              <span className="font-medium">Temperature Sparkline</span>
              {minT !== 'N/A' && minT !== maxT && (
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
          <span className="group-hover:text-emerald-400 transition-colors flex items-center gap-1 font-semibold">
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
    prev.setpoints === next.setpoints &&
    (prev.history?.t?.length || 0) === (next.history?.t?.length || 0)
);

const LiveMonitoring = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryParamDevice = searchParams.get('device') || '';

  // ── Retrieve initial cached devices for instant 0ms mount ──
  const cachedDevicesRaw = typeof window !== 'undefined' ? sessionStorage.getItem('devices_cache') : null;
  let initialDevices = [];
  try {
    if (cachedDevicesRaw) initialDevices = JSON.parse(cachedDevicesRaw);
  } catch (e) { }

  const initialSelectedId = queryParamDevice || (initialDevices.length > 0 ? initialDevices[0]._id : '');

  // ── Retrieve initial cached live metrics for instant 0ms metrics display ──
  const cachedLiveRaw = typeof window !== 'undefined' && initialSelectedId ? sessionStorage.getItem(`live_cache_${initialSelectedId}`) : null;
  let initialCachedSnapshot = null;
  try {
    if (cachedLiveRaw) {
      initialCachedSnapshot = JSON.parse(cachedLiveRaw);
      const isRajaInit =
        String(initialSelectedId || '').toLowerCase().includes('raja') ||
        String(queryParamDevice || '').toLowerCase().includes('raja') ||
        initialSelectedId === '6aa1294d6ee8e27613ac33e9';
      if (isRajaInit && initialCachedSnapshot) {
        if (Array.isArray(initialCachedSnapshot.activeFields)) {
          initialCachedSnapshot.activeFields = initialCachedSnapshot.activeFields.filter(
            (f) =>
              f.key !== 'field3' &&
              f.key !== 'field4' &&
              !String(f.label || '').toLowerCase().includes('ec') &&
              !String(f.label || '').toLowerCase().includes('ph')
          );
        }
        if (initialCachedSnapshot.chartData) {
          delete initialCachedSnapshot.chartData.field3;
          delete initialCachedSnapshot.chartData.field4;
        }
        if (initialCachedSnapshot.activeMetrics) {
          delete initialCachedSnapshot.activeMetrics.field3;
          delete initialCachedSnapshot.activeMetrics.field4;
        }
      }
    }
  } catch (e) { }

  const [loading, setLoading] = useState(!initialCachedSnapshot);
  const [initLoading, setInitLoading] = useState(initialDevices.length === 0);

  // ── All devices from DB ────────────────────────────────────────────────────
  const [allDevices, setAllDevices] = useState(initialDevices);
  const [selectedDeviceId, setSelectedDeviceId] = useState(initialSelectedId);

  // ── Live data state ────────────────────────────────────────────────────────
  const [liveDevice, setLiveDevice] = useState(initialCachedSnapshot?.liveDevice || null);
  const [activeFields, setActiveFields] = useState(initialCachedSnapshot?.activeFields || []);
  const [activeMetrics, setActiveMetrics] = useState(initialCachedSnapshot?.activeMetrics || {});
  const [chartData, setChartData] = useState(initialCachedSnapshot?.chartData || {});
  const [hasNewData, setHasNewData] = useState(true);
  const previousMetricsRef = useRef(null);
  const newDataTimeoutRef = useRef(null);
  const lastLiveStreamTimeRef = useRef(0);
  const liveMetricsRef = useRef(initialCachedSnapshot?.activeMetrics || {});

  // High-performance micro-batch buffer refs (prevents UI freeze/lag during high-frequency telemetry)
  const incomingBufferRef = useRef([]);
  const flushTimeoutRef = useRef(null);

  useEffect(() => {
    return () => {
      if (newDataTimeoutRef.current) {
        clearTimeout(newDataTimeoutRef.current);
      }
      if (flushTimeoutRef.current) {
        clearTimeout(flushTimeoutRef.current);
      }
    };
  }, []);

  // ── Multi-Sensor Live States ────────────────────────────────────────────────
  const [multiSensorData, setMultiSensorData] = useState(initialCachedSnapshot?.multiSensorData || {});
  const [sensorHistory, setSensorHistory] = useState(initialCachedSnapshot?.sensorHistory || {}); // { S1: { t: [...], h: [...], co2: [...] } }
  const [multiSensorSetpoints, setMultiSensorSetpoints] = useState(initialCachedSnapshot?.multiSensorSetpoints || {});
  const [multiSensorRelays, setMultiSensorRelays] = useState(initialCachedSnapshot?.multiSensorRelays || {});
  const [activeWarnings, setActiveWarnings] = useState(initialCachedSnapshot?.activeWarnings || []);
  const [customSensorNames, setCustomSensorNames] = useState(initialCachedSnapshot?.customSensorNames || {});
  const [activeMultiTab, setActiveMultiTab] = useState('S1'); // 'S1'..'S7'

  // ── Office Control Dual Room Live States ────────────────────────────────────
  const [officeControlData, setOfficeControlData] = useState(initialCachedSnapshot?.officeControlData || { 1: null, 2: null, 3: null });
  const [officeControlSetpoints, setOfficeControlSetpoints] = useState(initialCachedSnapshot?.officeControlSetpoints || { 1: null, 2: null, 3: null });
  const [officeControlHistory, setOfficeControlHistory] = useState(initialCachedSnapshot?.officeControlHistory || {
    1: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
    2: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
    3: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
  });
  const [activeRoomTab, setActiveRoomTab] = useState(1);

  // ── InHydro Controller Live States ──────────────────────────────────────────
  const [controllingData, setControllingData] = useState(initialCachedSnapshot?.controllingData || null);
  const [controllingHistory, setControllingHistory] = useState(initialCachedSnapshot?.controllingHistory || {
    water_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [],
    vpd: [], dli: [], wind_speed: [], wind_dir: [], do: [], ppfd: [], n: [], p: [], k: [],
  });
  // ── ITC Polyhouse Controller Live States ────────────────────────────────────
  const [polyhouseData, setPolyhouseData] = useState(initialCachedSnapshot?.polyhouseData || null);
  const [polyhouseHistory, setPolyhouseHistory] = useState(initialCachedSnapshot?.polyhouseHistory || {
    'PH-01': { temp: [], humidity: [], co2: [], par: [], dli: [] },
    'PH-02': { temp: [], humidity: [], co2: [], par: [], dli: [] },
    'PH-03': { temp: [], humidity: [], co2: [], par: [], dli: [] },
    'PH-04': { temp: [], humidity: [], co2: [], par: [], dli: [] },
    'PH-05': { temp: [], humidity: [], co2: [], par: [], dli: [] },
    'PH-06': { temp: [], humidity: [], co2: [], par: [], dli: [] },
  });
  const [activePolyhouseTab, setActivePolyhouseTab] = useState('PH-01');

  const [isMqttConnected, setIsMqttConnected] = useState(false);

  const token = localStorage.getItem('token');
  const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');

  // ── Step 1: Fetch all devices from backend (Parallel Background Refresh) ───
  useEffect(() => {
    let isMounted = true;
    const fetchDevices = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        const data = await res.json();
        if (data.success && isMounted) {
          setAllDevices(data.data);
          try {
            sessionStorage.setItem('devices_cache', JSON.stringify(data.data));
          } catch (e) { }
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
        if (isMounted) setInitLoading(false);
      }
    };
    fetchDevices();
    return () => { isMounted = false; };
  }, [token, selectedDeviceId, setSearchParams, API_BASE]);

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

    // STRICTLY EXCLUDE single Almora devices, ITC Polyhouse, and Fertigation
    if (type === 'almora' || type === 'almora2' || type === 'itc_polyhouse' || type === 'fertigation' || mqttId.startsWith('almora') || mqttId === 'sensor1') {
      return false;
    }

    return (
      type === 'multi_sensor' ||
      type === 'cold_storage' ||
      type === 'cold_room' ||
      type === 'coldroom' ||
      name.includes('cold') ||
      name.includes('storage') ||
      name.includes('room')
    );
  }, [deviceMeta]);

  const isPolyhouseDevice = deviceMeta?.deviceType === 'itc_polyhouse';
  const isOfficeControlDevice = deviceMeta?.deviceType === 'office_control';
  const isControllingDevice = deviceMeta?.deviceType === 'controlling';
  const isStandardDevice = !isMultiSensorDevice && !isOfficeControlDevice && !isControllingDevice && !isPolyhouseDevice;

  // ── RajapawRia Controller Identifier (MD02 Room Temp & Humidity ONLY - No Water EC/pH) ──
  const isRajaDevice = useMemo(() => {
    if (!deviceMeta) {
      const q = String(queryParamDevice || selectedDeviceId || '').toLowerCase();
      return q === 'raja' || q.includes('raja') || q === '6aa1294d6ee8e27613ac33e9';
    }
    const name = String(deviceMeta.name || '').toLowerCase();
    const mqttId = String(deviceMeta.mqttId || '').toLowerCase();
    const id = String(deviceMeta._id || deviceMeta.id || '').toLowerCase();
    const type = String(deviceMeta.deviceType || '').toLowerCase();
    return (
      name.includes('raja') ||
      mqttId === 'raja' ||
      mqttId.includes('raja') ||
      id === '6aa1294d6ee8e27613ac33e9' ||
      type === 'rp4iot' ||
      type === 'rajapawria'
    );
  }, [deviceMeta, queryParamDevice, selectedDeviceId]);

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

    // Telemetry freshness window: 180 seconds or backend DB online state
    const FRESHNESS_THRESHOLD_MS = 180 * 1000;

    // 1. Check liveDevice lastUpdated timestamp
    if (liveDevice?.lastUpdated) {
      const ts = new Date(typeof liveDevice.lastUpdated === 'string' && liveDevice.lastUpdated.includes(' ') && !liveDevice.lastUpdated.includes('T') ? liveDevice.lastUpdated.replace(' ', 'T') : liveDevice.lastUpdated).getTime();
      if (!isNaN(ts)) {
        const diffMs = Math.abs(nowTime - ts);
        if (diffMs < FRESHNESS_THRESHOLD_MS || liveDevice.status === 'online') {
          return true;
        }
      }
    }

    // 2. Fallback: check deviceMeta.latestPacketTime or deviceMeta.lastUpdated
    const metaTs = deviceMeta?.latestPacketTime || deviceMeta?.lastUpdated;
    if (metaTs) {
      const ts = new Date(typeof metaTs === 'string' && metaTs.includes(' ') && !metaTs.includes('T') ? metaTs.replace(' ', 'T') : metaTs).getTime();
      if (!isNaN(ts)) {
        const diffMs = Math.abs(nowTime - ts);
        if (diffMs < FRESHNESS_THRESHOLD_MS || deviceMeta.status === 'online') {
          return true;
        }
      }
    }

    return deviceMeta?.status === 'online';
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
      const hasValidData = (probe.t != null && Number(probe.t) > 0) || (probe.h != null && Number(probe.h) > 0);
      const isProbeOnline = (isDeviceOnline || hasValidData) && (probe.status === 'OK' || probe.status === 'online' || hasValidData);
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
      onlineCount: isDeviceOnline ? Math.max(online, 1) : online,
      totalProbes: 7,
      avgTemp: tempCount > 0 ? (tempSum / tempCount).toFixed(1) : 'N/A',
      minTemp: minT !== Infinity ? minT.toFixed(1) : 'N/A',
      maxTemp: maxT !== -Infinity ? maxT.toFixed(1) : 'N/A',
      avgHumi: humiCount > 0 ? (humiSum / humiCount).toFixed(1) : 'N/A',
      minHumi: minH !== Infinity ? minH.toFixed(1) : 'N/A',
      maxHumi: maxH !== -Infinity ? maxH.toFixed(1) : 'N/A',
      co2: co2Val != null ? co2Val : 'N/A',
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
    setActiveMultiTab('S1');
    setMultiSensorData({});
    setSensorHistory({});
    setMultiSensorSetpoints({});
    setMultiSensorRelays({});
    setActiveWarnings([]);
    setCustomSensorNames({});
    setOfficeControlData({ 1: null, 2: null, 3: null });
    setOfficeControlSetpoints({ 1: null, 2: null, 3: null });
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

    const isOfficeControl = isOfficeControlDevice;
    const isMultiSensor = isMultiSensorDevice;
    const isControlling = isControllingDevice;

    const url = isOfficeControl
      ? `${API_BASE}/api/devices/${selectedDeviceId}/analytics?live=true&limit=30&room=both`
      : `${API_BASE}/api/devices/${selectedDeviceId}/analytics?live=true&limit=30`;
    const headers = token ? { Authorization: `Bearer ${token}` } : {};

    fetch(url, { headers })
      .then(async (res) => {
        if (!res.ok) return null;
        const text = await res.text();
        if (!text || !text.trim()) return null;
        try {
          return JSON.parse(text);
        } catch {
          return null;
        }
      })
      .then((result) => {
        if (!result) {
          setLoading(false);
          return;
        }
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

        // For RajapawRia — delhi: strictly remove Water EC and Water pH
        if (isRajaDevice) {
          fields = fields.filter((f) => {
            const lbl = String(f.label || '').toLowerCase();
            const k = String(f.key || '').toLowerCase();
            return (
              !lbl.includes('ec') &&
              !lbl.includes('ph') &&
              k !== 'field3' &&
              k !== 'field4'
            );
          });
        }

        if (fields.length === 0) {
          const isMonitType =
            deviceMeta?.deviceType === 'monit' ||
            deviceMeta?.deviceType === 'monnet' ||
            deviceMeta?.deviceType === 'dosing';
          const isAlmoraType =
            deviceMeta?.deviceType === 'almora' ||
            deviceMeta?.deviceType === 'almora2';

          if (isRajaDevice) {
            fields = [
              { key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            ];
          } else if (deviceMeta?.deviceType === 'fertigation') {
            fields = [
              { key: 'field1', label: 'Water EC', icon: Zap, unit: 'mS/cm', type: 'ec' },
              { key: 'field2', label: 'Water pH', icon: FlaskConical, unit: 'pH', type: 'ph' },
              { key: 'field3', label: 'Water Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              // { key: 'field4', label: 'Fertigation Phase', icon: Activity, unit: '', type: 'default' },
            ];
          } else if (isMonitType) {
            fields = [
              { key: 'field3', label: 'Water EC', icon: Zap, unit: 'mS/cm', type: 'ec' },
              { key: 'field4', label: 'Water pH', icon: FlaskConical, unit: 'pH', type: 'ph' },
              { key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            ];
          } else if (deviceMeta?.deviceType === 'rp4iot') {
            fields = [
              { key: 'field1', label: 'Temperature', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field2', label: 'Humidity', icon: Droplets, unit: '%', type: 'moisture' },
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
          setLiveDevice((prev) => {
            if (prev && prev.status === 'online' && prev.lastUpdated) {
              const prevDiff = Date.now() - new Date(prev.lastUpdated).getTime();
              if (prevDiff < 2 * 60 * 1000 && prevDiff > -2 * 60 * 1000) {
                return prev;
              }
            }
            return {
              id: selectedDeviceId,
              name: deviceMeta?.name || 'Live Sensor Data',
              location: deviceMeta?.location || 'Private Broker Feed',
              status: deviceMeta?.status || 'offline',
              lastUpdated: deviceMeta?.lastUpdated || null,
            };
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

        const sData = latestFeed.sensor_data || latestFeed.telemetry?.sensor_data || latestFeed.data?.sensor_data || {};
        const currentMetrics = {};
        fields.forEach((f) => {
          let val = latestFeed[f.key] != null && latestFeed[f.key] !== '' ? parseFloat(latestFeed[f.key]) : null;
          if (val === null || isNaN(val)) {
            if (f.key === 'field5' || (f.key === 'field1' && !fields.some(x => x.key === 'field5'))) {
              val = sData.room_temp ?? sData.temp ?? sData.temperature ?? null;
            } else if (f.key === 'field6' || (f.key === 'field2' && !fields.some(x => x.key === 'field6'))) {
              val = sData.room_humi ?? sData.humi ?? sData.humidity ?? null;
            } else if (f.key === 'field3') {
              val = sData.ec ?? sData.soil_ec ?? sData.water_ec ?? null;
            } else if (f.key === 'field4') {
              val = sData.ph ?? sData.soil_ph ?? sData.water_ph ?? null;
            } else if (f.key === 'field8') {
              val = sData.co2 ?? null;
            }
          }
          currentMetrics[f.key] = val != null && !isNaN(val) ? parseFloat(val) : 0;
        });

        const newChartData = {};
        fields.forEach((f) => {
          newChartData[f.key] = feeds.map((feed) => {
            const feedSData = feed.sensor_data || feed.telemetry?.sensor_data || feed.data?.sensor_data || {};
            let val = feed[f.key] != null && feed[f.key] !== '' ? parseFloat(feed[f.key]) : null;
            if (val === null || isNaN(val)) {
              if (f.key === 'field5' || (f.key === 'field1' && !fields.some(x => x.key === 'field5'))) {
                val = feedSData.room_temp ?? feedSData.temp ?? feedSData.temperature ?? null;
              } else if (f.key === 'field6' || (f.key === 'field2' && !fields.some(x => x.key === 'field6'))) {
                val = feedSData.room_humi ?? feedSData.humi ?? feedSData.humidity ?? null;
              } else if (f.key === 'field3') {
                val = feedSData.ec ?? feedSData.soil_ec ?? feedSData.water_ec ?? null;
              } else if (f.key === 'field4') {
                val = feedSData.ph ?? feedSData.soil_ph ?? feedSData.water_ph ?? null;
              } else if (f.key === 'field8') {
                val = feedSData.co2 ?? null;
              }
            }
            return {
              time: new Date(feed.created_at || feed.timestamp || Date.now()).toLocaleTimeString('en-US', {
                hour: '2-digit',
                minute: '2-digit',
              }),
              value: val != null && !isNaN(val) ? parseFloat(val) : 0,
            };
          });
        });

        // If live stream is active (< 25s since last live telemetry packet), DO NOT clobber live chart with DB poll!
        const isLiveStreamActive = (Date.now() - lastLiveStreamTimeRef.current) < 25000;
        const previousMetrics = previousMetricsRef.current;
        const changed =
          !previousMetrics ||
          Object.keys(currentMetrics).some((key) => currentMetrics[key] !== previousMetrics[key]);

        if (isRajaDevice) {
          delete currentMetrics.field3;
          delete currentMetrics.field4;
          delete newChartData.field3;
          delete newChartData.field4;
        }

        setHasNewData(changed);
        if (!isLiveStreamActive && changed) {
          previousMetricsRef.current = currentMetrics;
          liveMetricsRef.current = currentMetrics;
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
            const mappedRelays = {};
            for (let i = 1; i <= 7; i++) {
              const sKey = `S${i}`;
              const idx = i - 1;
              const chCooling = String((idx * 3) + 1);
              const chHumi = String((idx * 3) + 2);
              const chLight = String((idx * 3) + 3);
              const roomObj = latestFeed.rooms?.[sKey] || latestFeed.sensor_data?.[sKey] || latestFeed[sKey];
              mappedRelays[sKey] = {
                cooling: Boolean(
                  rawRelays?.[chCooling] ??
                  rawRelays?.[Number(chCooling)] ??
                  roomObj?.relays?.cooling ??
                  roomObj?.cooling ??
                  false
                ),
                humi: Boolean(
                  rawRelays?.[chHumi] ??
                  rawRelays?.[Number(chHumi)] ??
                  roomObj?.relays?.humidifier ??
                  roomObj?.humidifier ??
                  false
                ),
                light: Boolean(
                  rawRelays?.[chLight] ??
                  rawRelays?.[Number(chLight)] ??
                  roomObj?.relays?.grow_lights ??
                  roomObj?.grow_lights ??
                  false
                ),
              };
            }
            setMultiSensorRelays((prev) => ({ ...prev, ...mappedRelays }));

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

          if (deviceMeta?.deviceType === 'itc_polyhouse' && latestFeed) {
            const rawPoly = latestFeed.telemetry || latestFeed;
            setPolyhouseData((prev) => ({
              ...(prev || {}),
              ...rawPoly,
              sensor_data: latestFeed.sensor_data || rawPoly.sensor_data || {},
              relay_states: latestFeed.relay_states || rawPoly.relay_states || {},
              room_paused_states: latestFeed.room_paused_states || rawPoly.room_paused_states || {},
              common_pump_active: latestFeed.common_pump_active ?? rawPoly.common_pump_active,
              active_water_zone: latestFeed.active_water_zone ?? rawPoly.active_water_zone,
              dli_data: latestFeed.dli_data || rawPoly.dli_data || {},
            }));

            if (feeds && feeds.length > 0) {
              const initHist = {
                'PH-01': { temp: [], humidity: [], co2: [], par: [], dli: [] },
                'PH-02': { temp: [], humidity: [], co2: [], par: [], dli: [] },
                'PH-03': { temp: [], humidity: [], co2: [], par: [], dli: [] },
                'PH-04': { temp: [], humidity: [], co2: [], par: [], dli: [] },
                'PH-05': { temp: [], humidity: [], co2: [], par: [], dli: [] },
                'PH-06': { temp: [], humidity: [], co2: [], par: [], dli: [] },
              };
              feeds.forEach((feed) => {
                const time = new Date(feed.created_at || feed.timestamp || Date.now()).toLocaleTimeString('en-US', {
                  hour: '2-digit',
                  minute: '2-digit',
                });
                const sData = feed.sensor_data || feed.telemetry?.sensor_data || {};
                const dliData = feed.dli_data || feed.telemetry?.dli_data || {};
                ['PH-01', 'PH-02', 'PH-03', 'PH-04', 'PH-05', 'PH-06'].forEach((zKey) => {
                  if (sData[zKey]) {
                    const z = sData[zKey];
                    initHist[zKey].temp.push({ time, value: parseFloat(z.temp) || 0 });
                    initHist[zKey].humidity.push({ time, value: parseFloat(z.humidity) || 0 });
                    initHist[zKey].co2.push({ time, value: parseFloat(z.co2) || 0 });
                    initHist[zKey].par.push({ time, value: parseFloat(z.par) || 0 });
                    initHist[zKey].dli.push({ time, value: parseFloat(dliData[zKey] ?? z.dli) || 0 });
                  }
                });
              });
              ['PH-01', 'PH-02', 'PH-03', 'PH-04', 'PH-05', 'PH-06'].forEach((zKey) => {
                initHist[zKey].temp = initHist[zKey].temp.slice(-24);
                initHist[zKey].humidity = initHist[zKey].humidity.slice(-24);
                initHist[zKey].co2 = initHist[zKey].co2.slice(-24);
                initHist[zKey].par = initHist[zKey].par.slice(-24);
                initHist[zKey].dli = initHist[zKey].dli.slice(-24);
              });
              setPolyhouseHistory((prev) => ({ ...initHist, ...prev }));
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
  }, [deviceMeta, selectedDeviceId, getFieldDisplayInfo, API_BASE, token, isRajaDevice]);

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
    if (!id && deviceMeta?.deviceType === 'fertigation') id = 'fertigation';
    if (!id && deviceMeta?.deviceType === 'controlling') id = 'controlling';
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
          deviceMeta?.deviceType === 'fertigation' ? 'fertigation' : null,
          deviceMeta?.deviceType === 'fertigation' ? 'control12' : null,
          deviceMeta?.deviceType === 'itc_polyhouse' ? (deviceMeta?.mqttId || deviceMeta?.name) : null,
          isMultiSensorDevice ? 'cold_room' : null,
          isMultiSensorDevice ? 'cold_storage' : null,
          isMultiSensorDevice ? 'control123' : null,
          deviceMeta?.id,
          deviceMeta?._id,
          selectedDeviceId,
          queryParamDevice,
        ].filter(Boolean)
      )
    );
  }, [deviceMeta, selectedDeviceId, queryParamDevice, isMultiSensorDevice]);

  const handleBatchedPackets = useCallback(
    (packets) => {
      if (!packets || packets.length === 0) return;

      const isMultiSensor = isMultiSensorDevice;
      const isOfficeControl = isOfficeControlDevice;
      const isControlling = isControllingDevice;
      const isPolyhouse = isPolyhouseDevice;

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

        const payload = packet.data;
        const rawPayload = payload.data || payload;

        // Verify that this packet belongs to the currently selected device or candidate identifiers
        const packetMqttId = String(packet.mqttId || '').toLowerCase();
        const packetDevId = String(packet.deviceId || '').toLowerCase();
        const topic = String(packet.topic || '').toLowerCase();
        const pMqtt = String(rawPayload?.device || rawPayload?.device_id || rawPayload?.devId || packetMqttId || '').toLowerCase();

        const matchesDevice =
          !selectedDeviceId ||
          (selectedDeviceId && packetDevId === String(selectedDeviceId).toLowerCase()) ||
          candidateIdentifiers.length === 0 ||
          candidateIdentifiers.some(
            (cid) =>
              cid &&
              (packetMqttId === String(cid).toLowerCase() ||
                packetDevId === String(cid).toLowerCase() ||
                (pMqtt && pMqtt === String(cid).toLowerCase()) ||
                topic.includes(String(cid).toLowerCase()))
          );

        if (!matchesDevice && candidateIdentifiers.length > 0) {
          return; // Skip packets belonging to other devices
        }

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
          const mappedRelays = {};
          for (let i = 1; i <= 7; i++) {
            const sKey = `S${i}`;
            const idx = i - 1;
            const chCooling = String((idx * 3) + 1);
            const chHumi = String((idx * 3) + 2);
            const chLight = String((idx * 3) + 3);
            const roomObj = rawPayload.rooms?.[sKey] || rawPayload.sensor_data?.[sKey] || rawPayload[sKey];
            mappedRelays[sKey] = {
              cooling: Boolean(
                rawRelays?.[chCooling] ??
                rawRelays?.[Number(chCooling)] ??
                roomObj?.relays?.cooling ??
                roomObj?.cooling ??
                false
              ),
              humi: Boolean(
                rawRelays?.[chHumi] ??
                rawRelays?.[Number(chHumi)] ??
                roomObj?.relays?.humidifier ??
                roomObj?.humidifier ??
                false
              ),
              light: Boolean(
                rawRelays?.[chLight] ??
                rawRelays?.[Number(chLight)] ??
                roomObj?.relays?.grow_lights ??
                roomObj?.grow_lights ??
                false
              ),
            };
          }
          setMultiSensorRelays((prev) => ({ ...prev, ...mappedRelays }));

          // 2. Extract Active Warnings / Alarms
          if (Array.isArray(rawPayload.active_warnings)) {
            setActiveWarnings(rawPayload.active_warnings);
          } else if (Array.isArray(rawPayload.warnings)) {
            setActiveWarnings(rawPayload.warnings);
          }

          // 3. Extract Sensor Setpoints (target temp, target humi, bands, stage, crop, setup)
          const rawSp = rawPayload.sensor_setpoints || rawPayload.setpoints;
          if (rawSp && typeof rawSp === 'object') {
            const mappedSp = {};
            Object.entries(rawSp).forEach(([k, sp]) => {
              const sKey = k.toUpperCase().startsWith('S') ? k.toUpperCase() : `S${k}`;
              mappedSp[sKey] = sp;
            });
            setMultiSensorSetpoints((prev) => ({ ...prev, ...mappedSp }));
          }
          if (rawPayload.port && (rawPayload.crop_name || rawPayload.settings || rawPayload.setup_name)) {
            const sKey = rawPayload.port.toUpperCase().startsWith('S') ? rawPayload.port.toUpperCase() : `S${rawPayload.port}`;
            setMultiSensorSetpoints((prev) => ({ ...prev, [sKey]: { ...(prev[sKey] || {}), ...rawPayload } }));
          }

          // 4. Extract Custom Sensor Names
          if (rawPayload.system_config?.sensor_names) {
            setCustomSensorNames(rawPayload.system_config.sensor_names);
          }

          // 5. Normalize Probe Telemetry Data (S1..S7)
          let normalizedSensors = {};
          const rawSensors = rawPayload.sensor_data || rawPayload.rooms || (rawPayload.S1 || rawPayload.s1 || rawPayload.S2 || rawPayload.s2 ? rawPayload : null);

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
                if (sensor && (sensor.t !== undefined || sensor.h !== undefined)) {
                  const prevState =
                    newHist[sId] && typeof newHist[sId] === 'object' ? newHist[sId] : { t: [], h: [], co2: [] };
                  const prevT = Array.isArray(prevState.t) ? prevState.t : [];
                  const prevH = Array.isArray(prevState.h) ? prevState.h : [];
                  const prevCo2 = Array.isArray(prevState.co2) ? prevState.co2 : [];

                  const tVal = Number(sensor.t);
                  const hVal = Number(sensor.h);
                  const co2Val = sensor.co2 != null ? Number(sensor.co2) : null;

                  const newT = !isNaN(tVal) && sensor.t !== null ? [...prevT, { time: timeStr, value: tVal }].slice(-30) : prevT;
                  const newH = !isNaN(hVal) && sensor.h !== null ? [...prevH, { time: timeStr, value: hVal }].slice(-30) : prevH;
                  const newCo2 = co2Val !== null && !isNaN(co2Val) && co2Val > 0 ? [...prevCo2, { time: timeStr, value: co2Val }].slice(-30) : prevCo2;

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

          // Extract Office Control Setpoints if present
          if (payload['Crop Name'] || payload.crop_name || payload['Setup Name'] || payload.setup_name) {
            let roomNum = 1;
            if (topic.includes('room3')) roomNum = 3;
            else if (topic.includes('room2')) roomNum = 2;
            else if (topic.includes('room1')) roomNum = 1;
            setOfficeControlSetpoints((prev) => ({
              ...prev,
              [roomNum]: { ...(prev[roomNum] || {}), ...payload }
            }));
          }

          if (payload.room1 || payload.room2 || payload.room3) {
            if (payload.room1) {
              updateSingleRoom(1, payload.room1);
              if (payload.room1['Crop Name'] || payload.room1.crop_name || payload.room1['Setup Name'] || payload.room1.setup_name) {
                setOfficeControlSetpoints((prev) => ({ ...prev, 1: { ...(prev[1] || {}), ...payload.room1 } }));
              }
            }
            if (payload.room2) {
              updateSingleRoom(2, payload.room2);
              if (payload.room2['Crop Name'] || payload.room2.crop_name || payload.room2['Setup Name'] || payload.room2.setup_name) {
                setOfficeControlSetpoints((prev) => ({ ...prev, 2: { ...(prev[2] || {}), ...payload.room2 } }));
              }
            }
            if (payload.room3) {
              updateSingleRoom(3, payload.room3);
              if (payload.room3['Crop Name'] || payload.room3.crop_name || payload.room3['Setup Name'] || payload.room3.setup_name) {
                setOfficeControlSetpoints((prev) => ({ ...prev, 3: { ...(prev[3] || {}), ...payload.room3 } }));
              }
            }
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
        } else if (isPolyhouse) {
          const polyPayload = payload.telemetry || payload.sensor_data ? payload : (payload.data || payload);
          if (polyPayload.sensor_data || polyPayload.relay_states || polyPayload.common_pump_active !== undefined) {
            hasMatchingTelemetry = true;
            if (!packet.isRetain) {
              latestTelemetryTimestamp = new Date();
            } else if (packetDate) {
              if (!latestTelemetryTimestamp || packetDate > latestTelemetryTimestamp) {
                latestTelemetryTimestamp = packetDate;
              }
            }
            setPolyhouseData((prev) => ({
              ...(prev || {}),
              ...polyPayload,
              sensor_data: {
                ...(prev?.sensor_data || {}),
                ...(polyPayload.sensor_data || {}),
              },
              relay_states: {
                ...(prev?.relay_states || {}),
                ...(polyPayload.relay_states || {}),
              },
              room_paused_states: {
                ...(prev?.room_paused_states || {}),
                ...(polyPayload.room_paused_states || {}),
              },
              common_pump_active: polyPayload.common_pump_active !== undefined ? polyPayload.common_pump_active : prev?.common_pump_active,
              active_water_zone: polyPayload.active_water_zone !== undefined ? polyPayload.active_water_zone : prev?.active_water_zone,
              dli_data: {
                ...(prev?.dli_data || {}),
                ...(polyPayload.dli_data || {}),
              },
            }));

            if (polyPayload.sensor_data) {
              setPolyhouseHistory((prev) => {
                const nextHist = { ...prev };
                Object.keys(polyPayload.sensor_data).forEach((zoneKey) => {
                  const zData = polyPayload.sensor_data[zoneKey] || {};
                  const prevZone = nextHist[zoneKey] || { temp: [], humidity: [], co2: [], par: [], dli: [] };
                  const dliVal = polyPayload.dli_data?.[zoneKey] ?? zData.dli ?? 0;
                  nextHist[zoneKey] = {
                    temp: [...(prevZone.temp || []), { time: timeStr, value: parseFloat(zData.temp) || 0 }].slice(-24),
                    humidity: [...(prevZone.humidity || []), { time: timeStr, value: parseFloat(zData.humidity) || 0 }].slice(-24),
                    co2: [...(prevZone.co2 || []), { time: timeStr, value: parseFloat(zData.co2) || 0 }].slice(-24),
                    par: [...(prevZone.par || []), { time: timeStr, value: parseFloat(zData.par) || 0 }].slice(-24),
                    dli: [...(prevZone.dli || []), { time: timeStr, value: parseFloat(dliVal) || 0 }].slice(-24),
                  };
                });
                return nextHist;
              });
            }
          }
        } else if (deviceMeta?.deviceType === 'fertigation' || targetMqttId === 'fertigation') {
          // ── SPECIALIZED FERTIGATION CONTINUOUS STREAM HANDLER ─────────────────
          // 1. Filter out heartbeat, setpoint sync, and remote command ACKs from resetting sensor metrics
          const isHeartbeatOrCmd =
            topic.includes('/heartbeat') ||
            topic.includes('/setpoints') ||
            topic.includes('/config') ||
            topic.includes('/command') ||
            (rawPayload.status === 'online' && rawPayload.ec === undefined && rawPayload.ph === undefined && rawPayload.water_temp === undefined && rawPayload.field1 === undefined);

          if (isHeartbeatOrCmd) {
            // Heartbeat confirms device is actively online! DO NOT wipe metrics or charts!
            hasMatchingTelemetry = true;
            if (!packet.isRetain) {
              latestTelemetryTimestamp = new Date();
            } else if (packetDate && (!latestTelemetryTimestamp || packetDate > latestTelemetryTimestamp)) {
              latestTelemetryTimestamp = packetDate;
            }
            return;
          }

          // 2. Extract and sanitize genuine sensory telemetry
          const tel = rawPayload.telemetry || rawPayload.sensors || rawPayload.data || rawPayload;

          const parseNum = (v) => {
            if (v === null || v === undefined || v === '') return null;
            const n = parseFloat(v);
            return Number.isFinite(n) ? n : null;
          };

          // For fertigation: field1 = Water EC, field2 = Water pH, field3 = Water Temp
          const rawEc = parseNum(tel.ec ?? tel.pv_ec ?? tel.water_ec ?? (tel.field1 !== undefined ? tel.field1 : null));
          const rawPh = parseNum(tel.ph ?? tel.pv_ph ?? tel.water_ph ?? (tel.field2 !== undefined ? tel.field2 : null));
          const rawTemp = parseNum(tel.water_temp ?? tel.pv_water_temp ?? tel.temp ?? (tel.field3 !== undefined ? tel.field3 : null));
          const phaseStr = tel.phase || tel.fertigation?.phase || (tel.fertigation?.is_running ? 'RUNNING' : 'READY');

          // Preserve previous non-zero readings if a single packet has transient null/disconnected value
          const prev = liveMetricsRef.current || {};
          const ecVal = rawEc !== null && rawEc > 0 ? rawEc : (prev.field1 || 0);
          const phVal = rawPh !== null && rawPh > 0 ? rawPh : (prev.field2 || 0);
          const tempVal = rawTemp !== null && rawTemp > 0 ? rawTemp : (prev.field3 || 0);

          const hasSensory = rawEc !== null || rawPh !== null || rawTemp !== null;

          if (hasSensory) {
            hasMatchingTelemetry = true;
            lastLiveStreamTimeRef.current = Date.now();
            if (!packet.isRetain) {
              latestTelemetryTimestamp = new Date();
            } else if (packetDate && (!latestTelemetryTimestamp || packetDate > latestTelemetryTimestamp)) {
              latestTelemetryTimestamp = packetDate;
            }

            const currentMetrics = {
              field1: ecVal,
              field2: phVal,
              field3: tempVal,
              field4: phaseStr,
            };

            const fields = [
              { key: 'field1', label: 'Water EC', icon: Zap, unit: 'mS/cm', type: 'ec' },
              { key: 'field2', label: 'Water pH', icon: FlaskConical, unit: 'pH', type: 'ph' },
              { key: 'field3', label: 'Water Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
            ];

            liveMetricsRef.current = currentMetrics;
            setActiveFields(fields);
            setActiveMetrics(currentMetrics);

            setChartData((prev) => {
              const newChart = { ...prev };
              fields.forEach((f) => {
                const val = currentMetrics[f.key];
                if (val !== null && val !== undefined && val > 0) {
                  newChart[f.key] = [
                    ...(newChart[f.key] || []),
                    { time: timeStr, value: val },
                  ].slice(-24);
                }
              });
              return newChart;
            });
          }
        } else {
          const tel = payload.telemetry || payload.sensors || payload.data || payload || {};
          const sData = rawPayload.sensor_data || payload.sensor_data || rawPayload.sensors || payload.sensors || {};

          // Check if payload contains sensory telemetry
          const hasSensory = Boolean(
            sData.temp !== undefined || sData.humi !== undefined || sData.temperature !== undefined || sData.humidity !== undefined ||
            tel.field1 !== undefined || tel.field2 !== undefined || tel.temp !== undefined || tel.water_temp !== undefined ||
            tel.soil_temp !== undefined || tel.room_temp !== undefined || tel.moist !== undefined || tel.ph !== undefined || tel.ec !== undefined
          );

          // Filter out heartbeat, status, or pure command acks from zeroing out generic device metrics
          const isHeartbeatOrCmd =
            topic.includes('/heartbeat') ||
            topic.endsWith('/status') ||
            topic.includes('/setpoints') ||
            topic.includes('/command') ||
            (rawPayload.status === 'online' && !hasSensory);

          if (isHeartbeatOrCmd) {
            hasMatchingTelemetry = true;
            if (!packet.isRetain) latestTelemetryTimestamp = new Date();
            else if (packetDate && (!latestTelemetryTimestamp || packetDate > latestTelemetryTimestamp)) {
              latestTelemetryTimestamp = packetDate;
            }
            return;
          }

          const isMonitType =
            deviceMeta?.deviceType === 'monit' ||
            deviceMeta?.deviceType === 'monnet' ||
            deviceMeta?.deviceType === 'dosing';

          const isAlmoraType =
            deviceMeta?.deviceType === 'almora' ||
            deviceMeta?.deviceType === 'almora2';

          const tempVal =
            tel.field1 !== undefined && tel.field1 !== null ? parseFloat(tel.field1) :
            sData.temp !== undefined && sData.temp !== null ? parseFloat(sData.temp) :
            sData.room_temp !== undefined && sData.room_temp !== null ? parseFloat(sData.room_temp) :
            sData.temperature !== undefined && sData.temperature !== null ? parseFloat(sData.temperature) :
            sData.water_temp !== undefined && sData.water_temp !== null ? parseFloat(sData.water_temp) :
            tel.temp !== undefined && tel.temp !== null ? parseFloat(tel.temp) :
            tel.room_temp !== undefined && tel.room_temp !== null ? parseFloat(tel.room_temp) :
            tel.water_temp !== undefined && tel.water_temp !== null ? parseFloat(tel.water_temp) :
            tel.soil_temp !== undefined && tel.soil_temp !== null ? parseFloat(tel.soil_temp) :
            tel.temperature !== undefined && tel.temperature !== null ? parseFloat(tel.temperature) :
            0;

          const moistVal =
            tel.field2 !== undefined && tel.field2 !== null ? parseFloat(tel.field2) :
            sData.humi !== undefined && sData.humi !== null ? parseFloat(sData.humi) :
            sData.humidity !== undefined && sData.humidity !== null ? parseFloat(sData.humidity) :
            sData.hum !== undefined && sData.hum !== null ? parseFloat(sData.hum) :
            sData.room_humi !== undefined && sData.room_humi !== null ? parseFloat(sData.room_humi) :
            sData.moist !== undefined && sData.moist !== null ? parseFloat(sData.moist) :
            sData.moisture !== undefined && sData.moisture !== null ? parseFloat(sData.moisture) :
            tel.humi !== undefined && tel.humi !== null ? parseFloat(tel.humi) :
            tel.humidity !== undefined && tel.humidity !== null ? parseFloat(tel.humidity) :
            tel.hum !== undefined && tel.hum !== null ? parseFloat(tel.hum) :
            tel.room_humi !== undefined && tel.room_humi !== null ? parseFloat(tel.room_humi) :
            tel.moist !== undefined && tel.moist !== null ? parseFloat(tel.moist) :
            tel.moisture !== undefined && tel.moisture !== null ? parseFloat(tel.moisture) :
            0;

          const ecVal =
            sData.ec !== undefined && sData.ec !== null ? parseFloat(sData.ec) :
            sData.soil_ec !== undefined && sData.soil_ec !== null ? parseFloat(sData.soil_ec) :
            sData.water_ec !== undefined && sData.water_ec !== null ? parseFloat(sData.water_ec) :
            tel.ec !== undefined && tel.ec !== null ? parseFloat(tel.ec) :
            tel.soil_ec !== undefined && tel.soil_ec !== null ? parseFloat(tel.soil_ec) :
            tel.water_ec !== undefined && tel.water_ec !== null ? parseFloat(tel.water_ec) :
            (tel.field3 !== undefined && tel.field3 !== null ? parseFloat(tel.field3) : (tel.field4 !== undefined && tel.field4 !== null && !isMonitType ? parseFloat(tel.field4) : 0));

          const phVal =
            sData.ph !== undefined && sData.ph !== null ? parseFloat(sData.ph) :
            sData.soil_ph !== undefined && sData.soil_ph !== null ? parseFloat(sData.soil_ph) :
            sData.water_ph !== undefined && sData.water_ph !== null ? parseFloat(sData.water_ph) :
            tel.ph !== undefined && tel.ph !== null ? parseFloat(tel.ph) :
            tel.soil_ph !== undefined && tel.soil_ph !== null ? parseFloat(tel.soil_ph) :
            tel.water_ph !== undefined && tel.water_ph !== null ? parseFloat(tel.water_ph) :
            (tel.field4 !== undefined && tel.field4 !== null ? parseFloat(tel.field4) : (tel.field3 !== undefined && tel.field3 !== null && !isMonitType ? parseFloat(tel.field3) : 0));

          const roomTempVal =
            tel.field5 !== undefined && tel.field5 !== null ? parseFloat(tel.field5) :
            sData.room_temp !== undefined && sData.room_temp !== null ? parseFloat(sData.room_temp) :
            tel.room_temp !== undefined && tel.room_temp !== null ? parseFloat(tel.room_temp) :
            (sData.temp !== undefined && sData.temp !== null ? parseFloat(sData.temp) : tempVal);

          const roomHumiVal =
            tel.field6 !== undefined && tel.field6 !== null ? parseFloat(tel.field6) :
            sData.room_humi !== undefined && sData.room_humi !== null ? parseFloat(sData.room_humi) :
            tel.room_humi !== undefined && tel.room_humi !== null ? parseFloat(tel.room_humi) :
            (sData.humi !== undefined && sData.humi !== null ? parseFloat(sData.humi) : moistVal);

          const orpVal =
            tel.field7 !== undefined && tel.field7 !== null ? parseFloat(tel.field7) :
            sData.orp !== undefined && sData.orp !== null ? parseFloat(sData.orp) :
            tel.orp !== undefined && tel.orp !== null ? parseFloat(tel.orp) :
            0;

          const co2Val =
            tel.field8 !== undefined && tel.field8 !== null ? parseFloat(tel.field8) :
            sData.co2 !== undefined && sData.co2 !== null ? parseFloat(sData.co2) :
            tel.co2 !== undefined && tel.co2 !== null ? parseFloat(tel.co2) :
            0;

          let currentMetrics = {
            field1: tempVal,
            field2: moistVal,
            field3: ecVal,
            field4: phVal,
            field5: roomTempVal,
            field6: roomHumiVal,
            field7: orpVal,
            field8: co2Val,
          };
          let fields = [];

          if (isRajaDevice) {
            currentMetrics.field5 = roomTempVal;
            currentMetrics.field6 = roomHumiVal;
            currentMetrics.field1 = roomTempVal;
            currentMetrics.field2 = roomHumiVal;
            delete currentMetrics.field3;
            delete currentMetrics.field4;

            fields = [
              { key: 'field5', label: ' Temperature', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field6', label: ' Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            ];
            if (co2Val > 0) {
              fields.push({ key: 'field8', label: 'CO2 Level', icon: Activity, unit: 'ppm', type: 'co2' });
            }
          } else if (isMonitType) {
            currentMetrics.field3 = ecVal;
            currentMetrics.field4 = phVal;
            currentMetrics.field5 = roomTempVal;
            currentMetrics.field6 = roomHumiVal;

            fields = [
              { key: 'field3', label: 'Water EC', icon: Zap, unit: 'mS/cm', type: 'ec' },
              { key: 'field4', label: 'Water pH', icon: FlaskConical, unit: 'pH', type: 'ph' },
              { key: 'field5', label: ' Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field6', label: ' Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            ];

            // If water temp / soil moisture are distinct and present, include them as well
            if (tel.water_temp !== undefined && tel.water_temp !== null && parseFloat(tel.water_temp) !== roomTempVal) {
              fields.unshift({ key: 'field1', label: 'Water Temp', icon: Thermometer, unit: '°C', type: 'temperature' });
            }
            if (tel.moist !== undefined && tel.moist !== null && parseFloat(tel.moist) !== roomHumiVal) {
              fields.splice(1, 0, { key: 'field2', label: 'Soil Moisture', icon: Droplets, unit: '%', type: 'moisture' });
            }
            if (co2Val > 0) {
              fields.push({ key: 'field8', label: 'CO2 Level', icon: Activity, unit: 'ppm', type: 'co2' });
            }
          } else if (deviceMeta?.deviceType === 'rp4iot') {
            fields = [
              { key: 'field1', label: 'Temperature', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field2', label: 'Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            ];
            if (ecVal > 0 || tel.ec !== undefined || tel.field3 !== undefined) {
              fields.push({ key: 'field3', label: 'Water EC', icon: Zap, unit: 'mS/cm', type: 'ec' });
            }
            if (phVal > 0 || tel.ph !== undefined || tel.field4 !== undefined) {
              fields.push({ key: 'field4', label: 'Water pH', icon: FlaskConical, unit: 'pH', type: 'ph' });
            }
            if (co2Val > 0) {
              fields.push({ key: 'field8', label: 'CO2 Level', icon: Activity, unit: 'ppm', type: 'co2' });
            }
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
              { key: 'field3', label: 'pH', icon: FlaskConical, unit: 'pH', type: 'ph' },
              { key: 'field4', label: 'EC', icon: Zap, unit: 'mS/cm', type: 'ec' },
              { key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            ];
            if (co2Val > 0 || tel.co2 !== undefined || deviceMeta?.name?.toLowerCase().includes('co2')) {
              fields.push({ key: 'field8', label: 'CO2 Level', icon: Activity, unit: 'ppm', type: 'co2' });
            }
          } else {
            fields = [
              { key: 'field1', label: 'Temperature', icon: Thermometer, unit: '°C', type: 'temperature' },
              { key: 'field2', label: 'Moisture / Humidity', icon: Droplets, unit: '%', type: 'moisture' },
            ];
            if (phVal > 0 || tel.ph !== undefined || tel.field3 !== undefined) {
              fields.push({ key: 'field3', label: 'pH Level', icon: FlaskConical, unit: 'pH', type: 'ph' });
            }
            if (ecVal > 0 || tel.ec !== undefined || tel.field4 !== undefined) {
              fields.push({ key: 'field4', label: 'EC Level', icon: Zap, unit: 'mS/cm', type: 'ec' });
            }
            if (roomTempVal > 0 && roomTempVal !== tempVal) {
              fields.push({ key: 'field5', label: 'Room Temp', icon: Thermometer, unit: '°C', type: 'temperature' });
            }
            if (roomHumiVal > 0 && roomHumiVal !== moistVal) {
              fields.push({ key: 'field6', label: 'Room Humidity', icon: Droplets, unit: '%', type: 'moisture' });
            }
            if (co2Val > 0) {
              fields.push({ key: 'field8', label: 'CO2 Level', icon: Activity, unit: 'ppm', type: 'co2' });
            }
          }

          hasMatchingTelemetry = true;
          lastLiveStreamTimeRef.current = Date.now();
          if (!packet.isRetain) {
            latestTelemetryTimestamp = new Date();
          } else if (packetDate) {
            if (!latestTelemetryTimestamp || packetDate > latestTelemetryTimestamp) {
              latestTelemetryTimestamp = packetDate;
            }
          }

          liveMetricsRef.current = currentMetrics;
          setActiveFields(fields);
          setActiveMetrics(currentMetrics);

          setChartData((prev) => {
            const newChart = { ...prev };
            if (isRajaDevice) {
              delete newChart.field3;
              delete newChart.field4;
            }
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
    [candidateIdentifiers, deviceMeta, selectedDeviceId, isMultiSensorDevice, isOfficeControlDevice, isControllingDevice, isPolyhouseDevice, isRajaDevice]
  );

  // ── High-Performance Micro-Batch Queue (Prevents UI stutter and frame drops) ──
  const queuePackets = useCallback(
    (packets) => {
      if (!packets || packets.length === 0) return;
      incomingBufferRef.current.push(...packets);

      if (!flushTimeoutRef.current) {
        flushTimeoutRef.current = setTimeout(() => {
          flushTimeoutRef.current = null;
          const queued = [...incomingBufferRef.current];
          incomingBufferRef.current = [];
          if (queued.length > 0) {
            handleBatchedPackets(queued);
          }
        }, 150); // 150ms batch window = ultra responsive 60fps UI
      }
    },
    [handleBatchedPackets]
  );

  // ── Step 3A: Direct Private Broker MQTT Connection (Fast-path when available) ──
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
          queuePackets([
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
  }, [selectedDeviceId, candidateIdentifiers, queuePackets]);

  // ── Step 3B: Enterprise WebSocket & SSE Real-time Telemetry Stream ──
  useEffect(() => {
    if (!selectedDeviceId) return;

    const targetRooms = [
      String(selectedDeviceId).toLowerCase(),
      targetMqttId ? String(targetMqttId).toLowerCase() : null,
      ...(candidateIdentifiers || []).map((id) => String(id).toLowerCase()),
    ].filter(Boolean);

    // Subscribe only to this device on WebSocket Gateway
    telemetryWs.subscribe(targetRooms);

    const unsubscribeWs = telemetryWs.onMessage((packet) => {
      if (!packet) return;
      const incomingDevId = packet.deviceId ? String(packet.deviceId).toLowerCase() : null;
      const incomingMqttId = packet.mqttId ? String(packet.mqttId).toLowerCase() : null;

      const isMatch = targetRooms.includes(incomingDevId) || targetRooms.includes(incomingMqttId);
      if (isMatch && (packet.data || packet.telemetry || packet.sensors)) {
        setIsMqttConnected(true);
        queuePackets([packet]);
      }
    });

    // Fallback SSE if WebSocket is blocked by corporate firewall or in reconnecting state
    let eventSource = null;
    let fallbackTimer = setTimeout(() => {
      if (!telemetryWs.isConnected) {
        try {
          const queryParams = new URLSearchParams();
          queryParams.set('deviceId', selectedDeviceId);
          if (targetMqttId) queryParams.set('mqttId', targetMqttId);

          const sseUrl = `${API_BASE}/api/devices/stream?${queryParams.toString()}`;
          eventSource = new EventSource(sseUrl);

          eventSource.onopen = () => setIsMqttConnected(true);

          eventSource.onmessage = (event) => {
            try {
              if (!event.data || event.data.startsWith(':')) return;
              const packet = JSON.parse(event.data);
              if (packet && (packet.data || packet.telemetry || packet.sensors)) {
                queuePackets([packet]);
              }
            } catch (err) {}
          };
        } catch (err) {
          console.warn('[LiveMonitoring] SSE stream setup skipped:', err);
        }
      }
    }, 2500);

    return () => {
      clearTimeout(fallbackTimer);
      telemetryWs.unsubscribe(targetRooms);
      unsubscribeWs();
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    };
  }, [selectedDeviceId, targetMqttId, candidateIdentifiers, queuePackets, API_BASE]);

  // ── Step 3C: Periodic Heartbeat / Analytics Fallback Poll (Keeps data active even if streams disconnect) ──
  useEffect(() => {
    if (!selectedDeviceId) return;
    const interval = setInterval(() => {
      fetchLiveData();
    }, 12000); // Poll every 12 seconds
    return () => clearInterval(interval);
  }, [fetchLiveData, selectedDeviceId]);

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
        <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-8 text-center max-w-md">
          <Cpu className="h-12 w-12 text-slate-500 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-white mb-2">No Devices Assigned</h3>
          <p className="text-sm text-slate-400">
            SuperAdmin has not assigned any devices to your account yet. Please contact SuperAdmin.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Professional Unified Device Header ───────────────────────────────── */}
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/60 p-4 sm:p-5 backdrop-blur-md space-y-3.5">
        {/* Top Control Bar: Selector + Status + Refresh */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          {/* Left: Device Selector & Online Badge */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-[220px] sm:min-w-[280px]">
              <select
                value={selectedDeviceId}
                onChange={(e) => handleDeviceChange(e.target.value)}
                className="w-full appearance-none rounded-xl border border-slate-700/80 bg-slate-950/90 pl-3.5 pr-10 py-2 text-sm font-semibold text-white outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 cursor-pointer transition-colors"
              >
                <option value="" disabled>Select a device...</option>
                {allDevices.map((d) => (
                  <option key={d._id} value={d._id}>
                    {d.name} — {d.location}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 pointer-events-none" />
            </div>

            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-wider ${deviceMeta?.status === 'blocked'
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
              {deviceMeta?.status === 'blocked' ? 'Blocked' : isDeviceOnline ? 'Online' : 'Offline'}
            </span>


          
          </div>

          {/* Right: Last Updated & Refresh */}
          <div className="flex items-center justify-between sm:justify-end gap-3 text-xs text-slate-400">
            <div className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-slate-500" />
              <span>Updated:</span>
              <span className="text-slate-300 font-medium">
                {liveDevice?.lastUpdated ? formatTimestamp(liveDevice.lastUpdated) : 'N/A'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleRefresh}
                title="Refresh Live Data"
                className="rounded-lg border border-slate-700/80 bg-slate-800/60 p-1.5 transition-all hover:bg-slate-700 hover:text-white active:scale-95 text-slate-300"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin text-emerald-400' : ''}`} />
              </button>
              <span
                className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold tracking-wide ${hasNewData
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  : 'border-slate-800 bg-slate-800/60 text-slate-400'
                  }`}
              >
                {hasNewData ? 'Live Data' : 'Cached'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Office Control Dual-Room Live View ───────────────────────────── */}
      {deviceMeta?.deviceType === 'office_control' && (
        <div className="space-y-6">
          {/* Room Selection Tabs */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-700/60 pb-px overflow-x-auto scrollbar-none gap-3">
            <div className="flex items-center">
              {[1, 2, 3].map((room) => {
                const isActive = activeRoomTab === room;
                const rSetup = officeControlSetpoints[room]?.setup_name || officeControlSetpoints[room]?.['Setup Name'] || DEFAULT_OFFICE_ROOM_SETUPS[room];

                return (
                  <button
                    key={room}
                    onClick={() => setActiveRoomTab(room)}
                    className={`relative px-5 py-3.5 text-sm font-semibold transition-all hover:text-white whitespace-nowrap flex items-center gap-2 ${isActive ? 'text-emerald-400' : 'text-slate-400'
                      }`}
                  >
                    <span>{rSetup}</span>

                    {isActive && (
                      <motion.div
                        layoutId="activeRoomTabIndicator"
                        className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-500"
                      />
                    )}
                  </button>
                );
              })}
            </div>


          </div>

          {/* Main 8-Box Grid and Trend Charts */}
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            {/* Left: 8 Sensor Grid Boxes */}
            <div className="space-y-4 xl:col-span-1">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                  Live Readings
                </h3>
              </div>
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
                        isOnline={isDeviceOnline}
                      />
                      <BigMetric
                        label="MD02 #1 Humi"
                        value={officeControlData[activeRoomTab]?.md02_1?.room_humi}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                        isOnline={isDeviceOnline}
                      />
                      <BigMetric
                        label="MD02 #2 Temp"
                        value={officeControlData[activeRoomTab]?.md02_2?.room_temp}
                        unit="°C"
                        icon={Thermometer}
                        type="temperature"
                        isOnline={isDeviceOnline}
                      />
                      <BigMetric
                        label="MD02 #2 Humi"
                        value={officeControlData[activeRoomTab]?.md02_2?.room_humi}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                        isOnline={isDeviceOnline}
                      />
                      <BigMetric
                        label="CO2 Level"
                        value={officeControlData[activeRoomTab]?.co2}
                        unit="ppm"
                        icon={Activity}
                        type="co2"
                        isOnline={isDeviceOnline}
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
                        isOnline={isDeviceOnline}
                      />
                      <BigMetric
                        label="Moisture"
                        value={officeControlData[activeRoomTab]?.soil?.moisture}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                        isOnline={isDeviceOnline}
                      />
                      <EcMetricCard
                        label="EC"
                        ecVal={officeControlData[activeRoomTab]?.soil?.ec}
                        isOnline={isDeviceOnline}
                      />
                      <BigMetric
                        label="pH"
                        value={officeControlData[activeRoomTab]?.soil?.ph}
                        unit="pH"
                        icon={FlaskConical}
                        type="ph"
                        isOnline={isDeviceOnline}
                      />
                      <BigMetric
                        label="Room Temp"
                        value={officeControlData[activeRoomTab]?.room?.room_temp}
                        unit="°C"
                        icon={Thermometer}
                        type="temperature"
                        isOnline={isDeviceOnline}
                      />
                      <BigMetric
                        label="Room Humidity"
                        value={officeControlData[activeRoomTab]?.room?.room_humi}
                        unit="%"
                        icon={Droplets}
                        type="moisture"
                        isOnline={isDeviceOnline}
                      />
                      <BigMetric
                        label="ORP Level"
                        value={officeControlData[activeRoomTab]?.orp}
                        unit="mV"
                        icon={Activity}
                        type="default"
                        isOnline={isDeviceOnline}
                      />
                      <BigMetric
                        label="CO2 Level"
                        value={officeControlData[activeRoomTab]?.co2}
                        unit="ppm"
                        icon={Activity}
                        type="co2"
                        isOnline={isDeviceOnline}
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
                        type="Room temperature"
                        title="MD02 #1 Temp Trend"
                        unit="°C"
                      />
                      <LiveChart
                        data={officeControlHistory[activeRoomTab]?.md02_1_humi || []}
                        type="Room moisture"
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
                      isOnline={isDeviceOnline}
                    />

                    {controllingMetricsConfig.map((m) => (
                      <BigMetric
                        key={m.key}
                        label={m.label}
                        value={controllingData?.[m.key]}
                        unit={m.unit}
                        icon={m.icon}
                        type={m.type}
                        isOnline={isDeviceOnline}
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

      {/* ── ITC Polyhouse Controller Live View ───────────────────────────── */}
      {isPolyhouseDevice && (() => {
        const zones = [
          { key: 'PH-01', name: 'Polyhouse 01', ch: [1, 2, 3, 4] },
          { key: 'PH-02', name: 'Polyhouse 02', ch: [5, 6, 7, 8] },
          { key: 'PH-03', name: 'Polyhouse 03', ch: [9, 10, 11, 12] },
          { key: 'PH-04', name: 'Polyhouse 04', ch: [13, 14, 15, 16] },
          { key: 'PH-05', name: 'Polyhouse 05', ch: [17, 18, 19, 20] },
          { key: 'PH-06', name: 'PH-06 (Outside / Reference)', ch: [] },
        ];

        const activeZone = zones.find((z) => z.key === activePolyhouseTab) || zones[0];
        const rawSensorData = polyhouseData?.sensor_data || {};
        const activeSensor = rawSensorData[activeZone.key] || { temp: null, humidity: null, co2: null, par: null, dli: null };
        const dliVal = polyhouseData?.dli_data?.[activeZone.key] ?? activeSensor.dli;
        const rawRelays = polyhouseData?.relay_states || {};
        const isPaused = Boolean(polyhouseData?.room_paused_states?.[activeZone.key]);
        const commonPumpOn = Boolean(polyhouseData?.common_pump_active || rawRelays['21'] == 1 || rawRelays[21] == 1);
        const waterZone = polyhouseData?.active_water_zone || null;

        const polyMetricsConfig = [
          { key: 'temp', label: 'Temperature', val: activeSensor.temp, unit: '°C', icon: Thermometer, type: 'temperature' },
          { key: 'humidity', label: 'Humidity', val: activeSensor.humidity, unit: '%', icon: Droplets, type: 'moisture' },
          { key: 'co2', label: 'CO2 Level', val: activeSensor.co2, unit: 'ppm', icon: Activity, type: 'co2' },
          { key: 'par', label: 'PAR / PPFD', val: activeSensor.par, unit: 'µmol/m²/s', icon: Sun, type: 'default' },
          { key: 'dli', label: 'Daily Light Integral (DLI)', val: dliVal, unit: 'mol/m²/d', icon: Sun, type: 'default' },
        ];

        const activeHist = polyhouseHistory[activeZone.key] || { temp: [], humidity: [], co2: [], par: [], dli: [] };

        return (
          <div className="space-y-6">
            {/* System Master Status Bar */}
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 rounded-2xl border border-emerald-500/20 bg-slate-900/60 p-4 backdrop-blur-sm shadow-xl">
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-2">
                  <span className="flex h-3 w-3 relative">
                    <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${commonPumpOn ? 'bg-emerald-400' : 'bg-slate-400'}`} />
                    <span className={`relative inline-flex rounded-full h-3 w-3 ${commonPumpOn ? 'bg-emerald-500' : 'bg-slate-500'}`} />
                  </span>
                  <span className="text-sm font-semibold text-white">Master Pump (R21):</span>
                  <span className={`rounded-lg px-2.5 py-1 text-xs font-bold border ${commonPumpOn ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' : 'bg-slate-800 text-slate-400 border-slate-700'}`}>
                    {commonPumpOn ? 'RUNNING (ACTIVE)' : 'STANDBY'}
                  </span>
                </div>

                <div className="h-4 w-px bg-slate-700 hidden sm:block" />

                <div className="flex items-center gap-2">
                  <Droplets className="h-4 w-4 text-sky-400" />
                  <span className="text-sm font-medium text-slate-400">Active Water Zone:</span>
                  <span className={`rounded-lg px-2 py-0.5 text-xs font-semibold ${waterZone ? 'bg-sky-500/20 text-sky-300 border border-sky-500/30 font-mono' : 'text-slate-400'}`}>
                    {waterZone ? `${waterZone} Active` : 'None (Idle)'}
                  </span>
                </div>

                <div className="h-4 w-px bg-slate-700 hidden sm:block" />

                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-emerald-400" />
                  <span className="text-xs text-slate-400">Hardware Relays: <strong>22 Channels</strong></span>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={() => navigate(`/polyhouse-settings?device=${selectedDeviceId}`)}
                  className="flex items-center gap-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 px-4 py-2 text-xs font-bold text-white shadow-lg shadow-emerald-900/40 transition-all hover:scale-[1.02] active:scale-[0.98]"
                >
                  <Sliders className="h-3.5 w-3.5" />
                  <span>Configure Polyhouse Setpoints</span>
                </button>
              </div>
            </div>

            {/* 6 Zones Quick Selection Grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
              {zones.map((zone) => {
                const isActive = activePolyhouseTab === zone.key;
                const zData = rawSensorData[zone.key] || {};
                const zDli = polyhouseData?.dli_data?.[zone.key] ?? zData.dli;
                const zPaused = Boolean(polyhouseData?.room_paused_states?.[zone.key]);
                const isWatering = waterZone === zone.key;

                return (
                  <button
                    key={zone.key}
                    onClick={() => setActivePolyhouseTab(zone.key)}
                    className={`flex flex-col text-left p-3.5 rounded-2xl border transition-all relative ${
                      isActive
                        ? 'bg-slate-800/90 border-emerald-500/60 shadow-lg shadow-emerald-950/40 ring-1 ring-emerald-500/40'
                        : 'bg-slate-900/50 border-slate-800/70 hover:bg-slate-800/50 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center justify-between w-full mb-2">
                      <span className="font-bold text-xs text-white flex items-center gap-1.5">
                        <Leaf className="h-3.5 w-3.5 text-emerald-400" />
                        {zone.key}
                      </span>
                      {zPaused ? (
                        <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30">
                          Paused
                        </span>
                      ) : isWatering ? (
                        <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-sky-500/20 text-sky-300 border border-sky-500/30 animate-pulse">
                          Watering
                        </span>
                      ) : (
                        <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300">
                          Active
                        </span>
                      )}
                    </div>

                    <div className="space-y-1 my-1 w-full font-mono">
                      <div className="flex justify-between items-center text-xs">
                        <span className="text-slate-400 text-[10px]">Temp:</span>
                        <span className="text-white font-bold">{zData.temp != null ? `${zData.temp}°C` : '--'}</span>
                      </div>
                      <div className="flex justify-between items-center text-xs">
                        <span className="text-slate-400 text-[10px]">Humi:</span>
                        <span className="text-white font-bold">{zData.humidity != null ? `${zData.humidity}%` : '--'}</span>
                      </div>
                      <div className="flex justify-between items-center text-xs">
                        <span className="text-slate-400 text-[10px]">PAR:</span>
                        <span className="text-amber-300 font-bold">{zData.par != null ? `${zData.par}` : '--'}</span>
                      </div>
                      <div className="flex justify-between items-center text-xs">
                        <span className="text-slate-400 text-[10px]">DLI:</span>
                        <span className="text-emerald-400 font-bold">{zDli != null ? `${zDli}` : '--'}</span>
                      </div>
                    </div>

                    {zone.ch.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-slate-800/80 grid grid-cols-4 gap-1 text-[9px] text-center w-full font-mono">
                        <div title="Air Circulator Fan (ACF)" className={`py-0.5 rounded ${rawRelays[String(zone.ch[0])] == 1 ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' : 'bg-slate-950/40 text-slate-500'}`}>
                          ACF
                        </div>
                        <div title="Sprinkler" className={`py-0.5 rounded ${rawRelays[String(zone.ch[1])] == 1 ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40' : 'bg-slate-950/40 text-slate-500'}`}>
                          SPR
                        </div>
                        <div title="Fogger" className={`py-0.5 rounded ${rawRelays[String(zone.ch[2])] == 1 ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40' : 'bg-slate-950/40 text-slate-500'}`}>
                          FOG
                        </div>
                        <div title="Zone Pump" className={`py-0.5 rounded ${rawRelays[String(zone.ch[3])] == 1 ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/40' : 'bg-slate-950/40 text-slate-500'}`}>
                          PMP
                        </div>
                      </div>
                    )}
                  </button>
                );
              })}
            </div>

            {/* Focused Zone Header & Hardware Relays Status */}
            <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 p-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-800/70">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                    <Leaf className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-white flex items-center gap-2">
                      {activeZone.name}
                      {isPaused && (
                        <span className="text-xs font-semibold px-2 py-0.5 rounded-md bg-rose-500/20 text-rose-300 border border-rose-500/30">
                          Zone Execution Paused
                        </span>
                      )}
                    </h3>
                    <p className="text-xs text-slate-400">Live Modbus Telemetry & Irrigation Relay Loop</p>
                  </div>
                </div>

                {activeZone.ch.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-slate-400">Zone Relays:</span>
                    <span className={`px-2 py-1 rounded-lg text-xs font-bold border ${rawRelays[String(activeZone.ch[0])] == 1 ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' : 'bg-slate-950/50 text-slate-500 border-slate-800'}`}>
                      ACF Fan (Ch {activeZone.ch[0]}): {rawRelays[String(activeZone.ch[0])] == 1 ? 'ON' : 'OFF'}
                    </span>
                    <span className={`px-2 py-1 rounded-lg text-xs font-bold border ${rawRelays[String(activeZone.ch[1])] == 1 ? 'bg-sky-500/20 text-sky-300 border-sky-500/40' : 'bg-slate-950/50 text-slate-500 border-slate-800'}`}>
                      Sprinkler (Ch {activeZone.ch[1]}): {rawRelays[String(activeZone.ch[1])] == 1 ? 'ON' : 'OFF'}
                    </span>
                    <span className={`px-2 py-1 rounded-lg text-xs font-bold border ${rawRelays[String(activeZone.ch[2])] == 1 ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40' : 'bg-slate-950/50 text-slate-500 border-slate-800'}`}>
                      Fogger (Ch {activeZone.ch[2]}): {rawRelays[String(activeZone.ch[2])] == 1 ? 'ON' : 'OFF'}
                    </span>
                    <span className={`px-2 py-1 rounded-lg text-xs font-bold border ${rawRelays[String(activeZone.ch[3])] == 1 ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40' : 'bg-slate-950/50 text-slate-500 border-slate-800'}`}>
                      Zone Pump (Ch {activeZone.ch[3]}): {rawRelays[String(activeZone.ch[3])] == 1 ? 'ON' : 'OFF'}
                    </span>
                  </div>
                )}
              </div>

              {/* Live Metric Cards */}
              <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4 pt-4">
                {polyMetricsConfig.map((m) => (
                  <BigMetric
                    key={m.key}
                    label={m.label}
                    value={m.val}
                    unit={m.unit}
                    icon={m.icon}
                    type={m.type}
                    isOnline={isDeviceOnline}
                  />
                ))}
              </div>
            </div>

            {/* Trend Charts */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <LiveChart
                data={activeHist.temp || []}
                type="temperature"
                title={`${activeZone.key} Temperature Trend`}
                unit="°C"
              />
              <LiveChart
                data={activeHist.humidity || []}
                type="moisture"
                title={`${activeZone.key} Humidity Trend`}
                unit="%"
              />
              <LiveChart
                data={activeHist.par || []}
                type="default"
                title={`${activeZone.key} PAR / PPFD Trend`}
                unit="µmol/m²/s"
              />
              <LiveChart
                data={activeHist.dli || []}
                type="default"
                title={`${activeZone.key} Daily Light Integral (DLI)`}
                unit="mol/m²/d"
              />
              <LiveChart
                data={activeHist.co2 || []}
                type="co2"
                title={`${activeZone.key} CO2 Trend`}
                unit="ppm"
              />
            </div>
          </div>
        );
      })()}

      {/* ── Cold Storage Multi-Room Live View (Matching Theme & Simplicity) ── */}
      {isMultiSensorDevice && (() => {
        const activeRoom = (!activeMultiTab || activeMultiTab === 'all') ? 'S1' : activeMultiTab;
        const currentData = multiSensorData[activeRoom] || { t: null, h: null, co2: null };
        const roomName = getProbeName(activeRoom, deviceMeta, customSensorNames);
        const setpointInfo = resolveRoomSetpointInfo(multiSensorSetpoints[activeRoom], activeRoom);
        const history = sensorHistory[activeRoom] || { t: [], h: [], co2: [] };

        // Channel numbers for Modbus RTU 22-relay board
        const roomIdx = parseInt(activeRoom.replace('S', ''), 10) - 1;
        const chCool = (roomIdx * 3) + 1;
        const chHumi = (roomIdx * 3) + 2;
        const chLight = (roomIdx * 3) + 3;
        const isS7 = activeRoom === 'S7';
        const coolingLabel = isS7 ? 'Fanpad' : 'AC Cooling';

        const roomRelays = multiSensorRelays[activeRoom] || {};
        const isCoolingOn = roomRelays.cooling ?? false;
        const isHumiOn = roomRelays.humi ?? false;
        const isLightOn = roomRelays.light ?? false;

        const hasValidData = (currentData?.t != null && Number(currentData.t) > 0) || (currentData?.h != null && Number(currentData.h) > 0);
        const isProbeOnline = isDeviceOnline && (currentData?.status === 'OK' || currentData?.status === 'online' || hasValidData);

        return (
          <div className="space-y-6">
            {/* Room Selection Tabs */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-700/60 pb-px overflow-x-auto scrollbar-none gap-3">
              <div className="flex items-center">
                {DEFAULT_PROBE_PORTS.map((port) => {
                  const isActive = activeRoom === port;
                  const pName = getProbeName(port, deviceMeta, customSensorNames);
                  const pData = multiSensorData[port];

                  return (
                    <button
                      key={port}
                      onClick={() => setActiveMultiTab(port)}
                      className={`relative px-4 sm:px-5 py-3.5 text-sm font-semibold transition-all hover:text-white whitespace-nowrap flex items-center gap-2 ${
                        isActive ? 'text-emerald-400' : 'text-slate-400'
                      }`}
                    >
                      <span className="font-mono text-xs opacity-75">{port}</span>
                      <span>{pName}</span>
                      {pData?.t != null && pData.t > 0 && (
                        <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                          isActive ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-400'
                        }`}>
                          {Number(pData.t).toFixed(1)}°C
                        </span>
                      )}
                      {isActive && (
                        <motion.div
                          layoutId="activeColdRoomTabIndicator"
                          className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-500"
                        />
                      )}
                    </button>
                  );
                })}
              </div>
             
            </div>

            {/* Main Content Grid: 1 col Live Readings, 2 cols Trend Charts */}
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
              {/* Left Column: Live Readings */}
              <div className="space-y-4 xl:col-span-1">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                  Live Readings
                </h3>

                <BigMetric
                  label="Temperature"
                  value={currentData.t}
                  unit="°C"
                  icon={Thermometer}
                  type="temperature"
                  isOnline={isProbeOnline}
                />

                <BigMetric
                  label="Humidity"
                  value={currentData.h}
                  unit="%"
                  icon={Droplets}
                  type="moisture"
                  isOnline={isProbeOnline}
                />

                <BigMetric
                  label="CO2 Concentration"
                  value={currentData.co2}
                  unit="ppm"
                  icon={Activity}
                  type="co2"
                  isOnline={isProbeOnline && currentData.co2 != null}
                />
              </div>

              {/* Right Column: Trend Charts */}
              <div className="space-y-4 xl:col-span-2">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
                  Trend Charts
                </h3>

                {(() => {
                  const tChartData = (history.t && history.t.length > 0)
                    ? history.t
                    : (currentData.t != null && !isNaN(currentData.t) ? [{ time: 'Live', value: Number(currentData.t) }] : []);

                  const hChartData = (history.h && history.h.length > 0)
                    ? history.h
                    : (currentData.h != null && !isNaN(currentData.h) ? [{ time: 'Live', value: Number(currentData.h) }] : []);

                  const co2ChartData = (history.co2 && history.co2.length > 0)
                    ? history.co2
                    : (currentData.co2 != null && !isNaN(currentData.co2) && Number(currentData.co2) > 0
                        ? [{ time: 'Live', value: Number(currentData.co2) }]
                        : []);

                  return (
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <LiveChart
                        data={tChartData}
                        type="temperature"
                        title={`${roomName} Temperature Trend`}
                        unit="°C"
                      />
                      <LiveChart
                        data={hChartData}
                        type="moisture"
                        title={`${roomName} Humidity Trend`}
                        unit="%"
                      />
                      <LiveChart
                        data={co2ChartData}
                        type="co2"
                        title={`${roomName} CO2 Trend`}
                        unit="ppm"
                      />
                    </div>
                  );
                })()}
              </div>
            </div>
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
                    isOnline={isDeviceOnline}
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