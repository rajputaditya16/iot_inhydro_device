import { motion } from 'framer-motion';
import { Wifi, WifiOff } from 'lucide-react';
import { getStatusBg, getStatusDot,  formatTimestamp } from '../utils/helpers';


const DeviceCard = ({ device, onClick }) => {
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

      {/* Footer */}
      <div className="mt-4 flex items-center justify-between border-t border-slate-700/50 pt-3">
        <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
          {device.status === 'offline' ? <WifiOff className="h-3 w-3" /> : <Wifi className="h-3 w-3" />}
          {formatTimestamp(device.lastUpdated)}
        </div>
      </div>
    </motion.div>
  );
};

export default DeviceCard;
