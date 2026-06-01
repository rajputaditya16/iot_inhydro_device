import { motion } from 'framer-motion';

const StatCard = ({ title, value, icon: Icon, trend, trendValue, color = 'blue' }) => {
  const colorMap = {
    blue: 'from-blue-500/20 to-blue-600/5 border-blue-500/20',
    green: 'from-emerald-500/20 to-emerald-600/5 border-emerald-500/20',
    yellow: 'from-yellow-500/20 to-yellow-600/5 border-yellow-500/20',
    red: 'from-red-500/20 to-red-600/5 border-red-500/20',
    cyan: 'from-cyan-500/20 to-cyan-600/5 border-cyan-500/20',
  };

  const iconColorMap = {
    blue: 'text-blue-400 bg-blue-500/10',
    green: 'text-emerald-400 bg-emerald-500/10',
    yellow: 'text-yellow-400 bg-yellow-500/10',
    red: 'text-red-400 bg-red-500/10',
    cyan: 'text-cyan-400 bg-cyan-500/10',
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className={`relative overflow-hidden rounded-2xl border bg-gradient-to-br ${colorMap[color]} p-5 backdrop-blur-sm`}
    >
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <p className="text-sm font-medium text-slate-400">{title}</p>
          <p className="text-3xl font-bold text-white">{value}</p>
          {trend && (
            <p className={`text-xs font-medium ${trend === 'up' ? 'text-emerald-400' : 'text-red-400'}`}>
              {trend === 'up' ? '↑' : '↓'} {trendValue}
            </p>
          )}
        </div>
        <div className={`rounded-xl p-3 ${iconColorMap[color]}`}>
          <Icon className="h-6 w-6" />
        </div>
      </div>
      {/* Decorative element */}
      <div className="absolute -bottom-4 -right-4 h-24 w-24 rounded-full bg-white/5 blur-2xl" />
    </motion.div>
  );
};

export default StatCard;
