export const getStatusColor = (status) => {
  switch (status) {
    case 'online': return 'text-emerald-400';
    case 'warning': return 'text-yellow-400';
    case 'critical': return 'text-red-400';
    case 'offline': return 'text-slate-500';
    default: return 'text-slate-400';
  }
};

export const getStatusBg = (status) => {
  switch (status) {
    case 'online': return 'bg-emerald-400/10 text-emerald-400 border-emerald-400/20';
    case 'warning': return 'bg-yellow-400/10 text-yellow-400 border-yellow-400/20';
    case 'critical': return 'bg-red-400/10 text-red-400 border-red-400/20';
    case 'offline': return 'bg-slate-500/10 text-slate-500 border-slate-500/20';
    default: return 'bg-slate-500/10 text-slate-400 border-slate-500/20';
  }
};

export const getStatusDot = (status) => {
  switch (status) {
    case 'online': return 'bg-emerald-400';
    case 'warning': return 'bg-yellow-400';
    case 'critical': return 'bg-red-400';
    case 'offline': return 'bg-slate-500';
    default: return 'bg-slate-500';
  }
};

export const getMetricStatus = (type, value) => {
  if (value === 0) return 'offline';
  switch (type) {
    case 'temp':
      if (value > 40) return 'critical';
      if (value > 35) return 'warning';
      return 'normal';
    case 'moisture':
      if (value < 25) return 'critical';
      if (value < 40) return 'warning';
      return 'normal';
    case 'ec':
      if (value > 4) return 'critical';
      if (value > 3) return 'warning';
      return 'normal';
    case 'ph':
      if (value < 4.5 || value > 8.5) return 'critical';
      if (value < 5.5 || value > 7.5) return 'warning';
      return 'normal';
    default:
      return 'normal';
  }
};

export const getMetricColor = (status) => {
  switch (status) {
    case 'critical': return 'text-red-400';
    case 'warning': return 'text-yellow-400';
    case 'normal': return 'text-emerald-400';
    default: return 'text-slate-500';
  }
};

export const formatTimestamp = (isoString) => {
  const date = new Date(isoString);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};
