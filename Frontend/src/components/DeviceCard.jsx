import { motion } from 'framer-motion';
import { Thermometer, Droplets, Zap, FlaskConical, Wifi, WifiOff, Battery } from 'lucide-react';
import { getStatusBg, getStatusDot, getMetricStatus, getMetricColor, formatTimestamp } from '../utils/helpers';
import { useAnimatedCounter } from '../hooks/useAnimatedCounter';

const MetricValue = ({ type, baseValue, unit, icon: Icon }) => {
  const safeValue = Number.isFinite(baseValue) ? baseValue : 0;
  const animated = useAnimatedCounter(safeValue);
  const status = getMetricStatus(type, safeValue);
  const color = getMetricColor(status);

  return (
    <div className="flex items-center gap-2">
      <Icon className={`h-4 w-4 ${color}`} />
      <span className={`text-sm font-semibold tabular-nums ${color}`}>
        {baseValue === 0 || baseValue === undefined ? '--' : typeof animated === 'number' ? animated.toFixed(1) : '--'}
      </span>
      <span className="text-[10px] text-slate-500">{unit}</span>
    </div>
  );
};

const DeviceCard = ({ device, onClick, hasNewData = true }) => {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      whileHover={{ scale: 1.02, y: -2 }}
      transition={{ duration: 0.3 }}
      onClick={() => onClick?.(device)}
      className="group cursor-pointer rounded-2xl border border-slate-700/50 bg-slate-800/50 p-5 backdrop-blur-sm transition-all hover:border-slate-600/50 hover:bg-slate-800/80 hover:shadow-lg hover:shadow-green-500/5"
    >
      {/* Header */}
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white group-hover:text-green-400 transition-colors">
            {device.name}
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">{device.location}</p>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${getStatusBg(device.status)}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${getStatusDot(device.status)} ${device.status === 'online' ? 'animate-pulse-dot' : ''}`} />
          {device.status}
        </span>
      </div>

      {/* Metrics Grid */}
      {/* <div className="grid grid-cols-2 gap-3">
        <MetricValue type="temp" baseValue={device.temp} unit="°C" icon={Thermometer} />
        <MetricValue type="moisture" baseValue={device.moisture} unit="%" icon={Droplets} />
        <MetricValue type="ec" baseValue={device.ec} unit="mS/cm" icon={Zap} />
        <MetricValue type="ph" baseValue={device.ph} unit="pH" icon={FlaskConical} />
      </div> */}

      {!hasNewData && (
        <p className="mt-3 text-[10px] font-medium text-amber-300/90">No new sensor change yet</p>
      )}

      {/* Footer */}
      <div className="mt-4 flex items-center justify-between border-t border-slate-700/50 pt-3">
        <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
          {device.status === 'offline' ? <WifiOff className="h-3 w-3" /> : <Wifi className="h-3 w-3" />}
          {formatTimestamp(device.lastUpdated)}
        </div>
        <div className="flex items-center gap-1 text-[10px] text-slate-500">
          <Battery className="h-3 w-3" />
          {device.battery}%
        </div>
      </div>
    </motion.div>
  );
};

export default DeviceCard;
