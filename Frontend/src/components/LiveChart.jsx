import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts';

const colorSchemes = {
  temperature: { stroke: '#f97316', fill: '#f97316', gradient: ['#f97316', '#f9731600'] },
  moisture: { stroke: '#3b82f6', fill: '#3b82f6', gradient: ['#3b82f6', '#3b82f600'] },
  ec: { stroke: '#a855f7', fill: '#a855f7', gradient: ['#a855f7', '#a855f700'] },
  ph: { stroke: '#22c55e', fill: '#22c55e', gradient: ['#22c55e', '#22c55e00'] },
};

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 shadow-xl">
        <p className="text-xs text-slate-400">{label}</p>
        <p className="text-sm font-semibold text-white">{payload[0].value}</p>
      </div>
    );
  }
  return null;
};

const LiveChart = ({ data, type = 'temperature', title, unit }) => {
  const colors = colorSchemes[type] || colorSchemes.temperature;
  const gradientId = `gradient-${type}`;

  return (
    <div className="rounded-2xl border border-slate-700/50 bg-slate-800/50 p-4 backdrop-blur-sm">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h4 className="text-sm font-semibold text-white">{title}</h4>
          <p className="text-[10px] text-slate-500">Last 24 hours</p>
        </div>
        <span className="text-xs text-slate-400">{unit}</span>
      </div>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.gradient[0]} stopOpacity={0.3} />
                <stop offset="100%" stopColor={colors.gradient[1]} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis
              dataKey="time"
              tick={{ fontSize: 10, fill: '#64748b' }}
              axisLine={{ stroke: '#334155' }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#64748b' }}
              axisLine={{ stroke: '#334155' }}
              tickLine={false}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="value"
              stroke={colors.stroke}
              strokeWidth={2}
              fill={`url(#${gradientId})`}
              dot={false}
              activeDot={{ r: 4, fill: colors.stroke, stroke: '#0f172a', strokeWidth: 2 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default LiveChart;
