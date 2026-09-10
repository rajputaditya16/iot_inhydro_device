import { useState, useEffect, useMemo, useCallback } from 'react';
import { motion } from 'framer-motion';
import { Download, Calendar, RefreshCw, WifiOff, BarChart3, TrendingUp, TrendingDown, Activity, Cpu } from 'lucide-react';
import LiveChart from '../../components/LiveChart';
import { SkeletonCard } from '../../components/Skeleton';


// Get date ranges for filters
const getDateRange = (filter, customStartDate = null, customEndDate = null, durationVal = 1, durationUnit = 'hours') => {
  const now = new Date();
  let start;
  let end = new Date(now);

  switch (filter) {
    case 'today': {
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
      break;
    }
    case 'yesterday': {
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 0, 0, 0);
      end.setTime(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 23, 59, 59).getTime());
      break;
    }
    case 'week': {
      const dayOfWeek = now.getDay();
      const mondayOffset = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - mondayOffset, 0, 0, 0);
      break;
    }
    case 'month': {
      start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0);
      break;
    }
    case 'three_months': {
      start = new Date(now.getFullYear(), now.getMonth() - 3, now.getDate(), 0, 0, 0);
      break;
    }
    case 'duration': {
      const val = Math.max(1, parseFloat(durationVal) || 1);
      const msMap = {
        seconds: val * 1000,
        minutes: val * 60 * 1000,
        hours: val * 60 * 60 * 1000,
        days: val * 24 * 60 * 60 * 1000,
      };
      const durationMs = msMap[durationUnit] || msMap.hours;
      start = new Date(now.getTime() - durationMs);
      break;
    }
    case 'custom': {
      if (customStartDate && customEndDate) {
        start = new Date(customStartDate);
        end = new Date(customEndDate);
      } else if (customStartDate) {
        start = new Date(customStartDate);
      } else {
        start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
      }
      break;
    }
    default:
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
  }
  return { start, end };
};

// Get field visual info
const getFieldMeta = (name) => {
  const lowerName = name.toLowerCase();
  if (lowerName.includes('temp')) return { type: 'temperature', unit: '°C', icon: TrendingUp, color: 'text-orange-400', bg: 'bg-orange-500/10 border-orange-500/20' };
  if (lowerName.includes('moist') || lowerName.includes('hum')) return { type: 'moisture', unit: '%', icon: Activity, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' };
  if (lowerName.includes('ec')) return { type: 'ec', unit: 'mS/cm', icon: BarChart3, color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/20' };
  if (lowerName.includes('ph')) return { type: 'ph', unit: '', icon: TrendingDown, color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' };
  if (lowerName.includes('co2')) return { type: 'co2', unit: 'PPM', icon: Activity, color: 'text-teal-400', bg: 'bg-teal-500/10 border-teal-500/20' };
  if (lowerName.includes('vpd')) return { type: 'default', unit: 'kPa', icon: Activity, color: 'text-cyan-400', bg: 'bg-cyan-500/10 border-cyan-500/20' };
  if (lowerName.includes('dli')) return { type: 'default', unit: 'mol/m²/d', icon: Activity, color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20' };
  if (lowerName.includes('wind_speed') || lowerName.includes('wind speed')) return { type: 'default', unit: 'm/s', icon: Activity, color: 'text-sky-400', bg: 'bg-sky-500/10 border-sky-500/20' };
  if (lowerName.includes('wind_dir') || lowerName.includes('wind direction')) return { type: 'default', unit: '°', icon: Activity, color: 'text-indigo-400', bg: 'bg-indigo-500/10 border-indigo-500/20' };
  if (lowerName.includes('dissolved oxygen') || lowerName.includes('do')) return { type: 'default', unit: 'mg/L', icon: Activity, color: 'text-rose-400', bg: 'bg-rose-500/10 border-rose-500/20' };
  if (lowerName.includes('ppfd')) return { type: 'default', unit: 'µmol/m²/s', icon: Activity, color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/20' };
  if (lowerName.includes('(n)') || lowerName.includes('nitrogen')) return { type: 'default', unit: 'mg/kg', icon: Activity, color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' };
  if (lowerName.includes('(p)') || lowerName.includes('phosphorus')) return { type: 'default', unit: 'mg/kg', icon: Activity, color: 'text-lime-400', bg: 'bg-lime-500/10 border-lime-500/20' };
  if (lowerName.includes('(k)') || lowerName.includes('potassium')) return { type: 'default', unit: 'mg/kg', icon: Activity, color: 'text-violet-400', bg: 'bg-violet-500/10 border-violet-500/20' };
  return { type: 'default', unit: '', icon: Activity, color: 'text-slate-400', bg: 'bg-slate-800/50 border-slate-700/50' };
};

const parseRobustFloat = (val) => {
  if (typeof val === 'string' && val.trim().startsWith('[')) {
    try {
      const arr = JSON.parse(val);
      if (Array.isArray(arr) && arr.length > 0) {
        const parsedArr = arr.map(v => parseFloat(v)).filter(v => !isNaN(v));
        if (parsedArr.length > 0) {
          return parsedArr.reduce((a, b) => a + b, 0) / parsedArr.length;
        }
      }
    } catch (e) {}
  }
  const parsed = parseFloat(val);
  return isNaN(parsed) ? 0 : parsed;
};

// Downsample feeds to a maximum number of points to prevent DOM/SVG rendering lag
const downsampleFeeds = (feeds, maxPoints = 1000) => {
  if (!feeds || feeds.length <= maxPoints) return feeds;
  const step = Math.ceil(feeds.length / maxPoints);
  const result = [];
  for (let i = 0; i < feeds.length; i += step) {
    result.push(feeds[i]);
  }
  return result;
};

// Format feeds into chart-ready data dynamically based on available channel fields
const mapFeedsToCharts = (feeds, filter, channelFields, isBothRooms = false, durationUnit = 'hours') => {
  const rawFeedsArray = Array.isArray(feeds) ? feeds : [];
  const validFeeds = downsampleFeeds(rawFeedsArray, 1000);

  let isMultiDay = ['week', 'month', 'three_months'].includes(filter);
  if (!isMultiDay && filter === 'custom' && validFeeds.length > 1) {
    const firstDate = new Date(validFeeds[0].created_at).toDateString();
    const lastDate = new Date(validFeeds[validFeeds.length - 1].created_at).toDateString();
    if (firstDate !== lastDate) {
      isMultiDay = true;
    }
  }

  const showSeconds = filter === 'duration' && (durationUnit === 'seconds' || durationUnit === 'minutes');

  const timeFormat = isMultiDay
    ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
    : showSeconds
    ? { hour: '2-digit', minute: '2-digit', second: '2-digit' }
    : { hour: '2-digit', minute: '2-digit' };

  if (!isBothRooms) {
    const mappedData = {};
    channelFields.forEach(field => {
      mappedData[field.key] = validFeeds.map((f) => ({
        time: new Date(f.created_at).toLocaleString('en-US', timeFormat),
        value: parseRobustFloat(f[field.key]),
      }));
    });
    return mappedData;
  } else {
    // Both rooms: group by rounded timestamp
    const timeGroupsMap = new Map();
    validFeeds.forEach(f => {
      const timeObj = new Date(f.created_at);
      const roundedMs = Math.round(timeObj.getTime() / 15000) * 15000;
      
      if (!timeGroupsMap.has(roundedMs)) {
        timeGroupsMap.set(roundedMs, {
          time: new Date(roundedMs).toLocaleString('en-US', timeFormat),
          rawTimestamp: roundedMs
        });
      }
      
      const group = timeGroupsMap.get(roundedMs);
      const suffix = f.room === 'room3' ? 'Room3' : f.room === 'room2' ? 'Room2' : 'Room1';
      
      channelFields.forEach(field => {
        group[`${field.key}${suffix}`] = parseRobustFloat(f[field.key]);
      });
    });

    const sortedGroups = Array.from(timeGroupsMap.values()).sort((a, b) => a.rawTimestamp - b.rawTimestamp);

    const mappedData = {};
    channelFields.forEach(field => {
      mappedData[field.key] = sortedGroups.map(g => ({
        time: g.time,
        room1Value: g[`${field.key}Room1`] !== undefined ? g[`${field.key}Room1`] : null,
        room2Value: g[`${field.key}Room2`] !== undefined ? g[`${field.key}Room2`] : null,
        room3Value: g[`${field.key}Room3`] !== undefined ? g[`${field.key}Room3`] : null,
        isBoth: true
      }));
    });

    return mappedData;
  }
};

const sanitizeFileName = (name) => {
  return String(name || 'Device').trim().replace(/[^a-z0-9_-]/gi, '_').replace(/_+/g, '_');
};

// Download helpers
const downloadCSV = (feeds, channelFields, filterLabel, deviceName = 'Device', isBoth = false) => {
  if (!feeds || feeds.length === 0) return;
  
  const headers = ['Timestamp'];
  if (isBoth) {
    headers.push('Room');
  }
  channelFields.forEach(f => {
    headers.push(`${f.name} (${getFieldMeta(f.name).unit || ''})`);
  });
  
  const headerLine = headers.join(',') + '\n';
  
  const rows = feeds.map((f) => {
    const rowCells = [f.created_at];
    if (isBoth) {
      rowCells.push(f.room || 'room1');
    }
    channelFields.forEach(cfg => {
      rowCells.push(f[cfg.key] !== undefined && f[cfg.key] !== null ? f[cfg.key] : '');
    });
    return rowCells.join(',');
  }).join('\n');

  const blob = new Blob([headerLine + rows], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const deviceSlug = sanitizeFileName(deviceName);
  a.href = url;
  a.download = `${deviceSlug}_Analytics_${filterLabel}_${dateStr}.csv`;
  a.click();
  URL.revokeObjectURL(url);
};

const downloadJSON = (feeds, channelFields, filterLabel, deviceName = 'Device', isBoth = false) => {
  if (!feeds || feeds.length === 0) return;
  const data = feeds.map((f) => {
    const obj = { timestamp: f.created_at };
    if (isBoth) {
      obj.room = f.room || 'room1';
    }
    channelFields.forEach(cfg => {
      obj[cfg.name] = parseRobustFloat(f[cfg.key]);
    });
    return obj;
  });
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dateStr = new Date().toISOString().split('T')[0];
  const deviceSlug = sanitizeFileName(deviceName);
  a.href = url;
  a.download = `${deviceSlug}_Analytics_${filterLabel}_${dateStr}.json`;
  a.click();
  URL.revokeObjectURL(url);
};

const AnalyticsPage = () => {
  const [filter, setFilter] = useState('today');
  const [durationVal, setDurationVal] = useState('1');
  const [durationUnit, setDurationUnit] = useState('hours'); // 'seconds', 'minutes', 'hours', 'days'
  const [customStartDate, setCustomStartDate] = useState('');
  const [customEndDate, setCustomEndDate] = useState('');
  const [rawFeeds, setRawFeeds] = useState([]);
  const [totalDbPoints, setTotalDbPoints] = useState(0);
  const [channelFields, setChannelFields] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showDownloadMenu, setShowDownloadMenu] = useState(false);

  // Device selector state
  const [allDevices, setAllDevices] = useState([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [selectedRoom, setSelectedRoom] = useState('room1');
  const [devicesLoading, setDevicesLoading] = useState(true);

  // Reset room selection when device changes
  useEffect(() => {
    setSelectedRoom('room1');
  }, [selectedDeviceId]);
  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // Fetch devices with analytics database configuration
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const contentType = res.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
          throw new Error("Received non-JSON response from server (Backend might be down)");
        }
        const data = await res.json();
        if (data.success) {
          setAllDevices(data.data || []);
          if (data.data && data.data.length > 0 && !selectedDeviceId) {
            setSelectedDeviceId(data.data[0]._id);
          }
        }
      } catch (err) {
        console.error('Failed to fetch devices', err);
      } finally {
        setDevicesLoading(false);
      }
    };
    fetchDevices();
  }, [token]);

  const selectedDevice = allDevices.find((d) => d._id === selectedDeviceId);

  const fetchData = useCallback(async () => {
    if (!selectedDeviceId) {
      setRawFeeds([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const { start, end } = getDateRange(filter, customStartDate, customEndDate, durationVal, durationUnit);
      const roomParam = selectedDevice?.deviceType === 'office_control' ? `&room=${selectedRoom}` : '';
      const url = `${API_BASE}/api/devices/${selectedDeviceId}/analytics?start=${start.toISOString()}&end=${end.toISOString()}${roomParam}`;
      
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(url, { headers });
      if (res.status === 404) {
        throw new Error("Analytics data not found for this device (404).");
      }
      if (!res.ok) throw new Error(`API responded with ${res.status}`);
      const result = await res.json();

      if (!result.success) {
        throw new Error(result.message || 'Server failed to return analytics');
      }

      // Backend already returns correct date-filtered feeds
      const exactFeeds = result.feeds || [];
      const cFields = [];
      const isMonitDevice = selectedDevice?.deviceType === 'monit' || selectedDevice?.deviceType === 'monnet' || selectedDevice?.name?.toLowerCase().includes('monit') || selectedDevice?.name?.toLowerCase().includes('monnet');

      for (let i = 1; i <= 17; i++) {
        const key = `field${i}`;
        const fieldName = result.channel?.[key] || `Field ${i}`;

        // Exclude Water Temp and Water Moisture for Monit devices
        if (isMonitDevice) {
          const lower = fieldName.toLowerCase();
          if (lower.includes('water temp') || lower.includes('water moisture') || fieldName === 'Water Temp' || fieldName === 'Water Moisture') {
            continue;
          }
        }

        const hasData = exactFeeds.some(f => f[key] != null && f[key] !== '' && f[key] !== 'null');
        if (hasData || (result.channel?.[key] && !result.channel?.[key].startsWith('Field '))) {
          cFields.push({ key, name: fieldName });
        }
      }
      setChannelFields(cFields);
      setRawFeeds(exactFeeds);
      setTotalDbPoints(result.totalDbPoints || exactFeeds.length);
    } catch (err) {
      console.error('Analytics API error:', err);
      setError(err.message || 'Failed to fetch data');
      setRawFeeds([]);
      setTotalDbPoints(0);
      setChannelFields([]);
    } finally {
      setLoading(false);
    }
  }, [filter, customStartDate, customEndDate, durationVal, durationUnit, selectedDeviceId, token, API_BASE, selectedRoom, selectedDevice?.deviceType]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Build chart data from raw feeds
  const chartData = useMemo(() => mapFeedsToCharts(rawFeeds, filter, channelFields, selectedRoom === 'both', durationUnit), [rawFeeds, filter, channelFields, selectedRoom, durationUnit]);

  // Compute summary statistics in a single optimized pass over rawFeeds
  const summaryStats = useMemo(() => {
    const stats = {};
    channelFields.forEach(f => {
      stats[f.key] = { min: Infinity, max: -Infinity, sum: 0, count: 0 };
    });

    if (!rawFeeds || rawFeeds.length === 0) return stats;

    const len = rawFeeds.length;

    for (let i = 0; i < len; i++) {
      const feed = rawFeeds[i];
      for (let j = 0; j < channelFields.length; j++) {
        const fieldKey = channelFields[j].key;
        const val = parseRobustFloat(feed[fieldKey]);
        if (feed[fieldKey] !== undefined && feed[fieldKey] !== null && feed[fieldKey] !== '') {
          const s = stats[fieldKey];
          if (val < s.min) s.min = val;
          if (val > s.max) s.max = val;
          s.sum += val;
          s.count++;
        }
      }
    }

    const formatted = {};
    channelFields.forEach(f => {
      const s = stats[f.key];
      formatted[f.key] = {
        avg: s.count > 0 ? (s.sum / s.count).toFixed(1) : '--',
        min: s.min !== Infinity ? s.min.toFixed(1) : '--',
        max: s.max !== -Infinity ? s.max.toFixed(1) : '--'
      };
    });
    return formatted;
  }, [rawFeeds, channelFields]);

  const summaryMetrics = channelFields.map(f => {
    const meta = getFieldMeta(f.name);
    const stats = summaryStats[f.key] || { avg: '--', min: '--', max: '--' };
    return {
      name: f.name,
      label: `Avg ${f.name}`,
      value: stats.avg,
      min: stats.min,
      max: stats.max,
      unit: meta.unit,
      icon: meta.icon,
      color: meta.color,
      bg: meta.bg
    };
  });

  const chartSubtitle = useMemo(() => {
    switch (filter) {
      case 'today':
        return 'Today';
      case 'yesterday':
        return 'Yesterday';
      case 'week':
        return 'This Week';
      case 'month':
        return 'This Month';
      case 'three_months':
        return 'Last 3 Months';
      case 'duration':
        return `Last ${durationVal} ${durationUnit}`;
      case 'custom':
        if (customStartDate && customEndDate) {
          return `${customStartDate.replace('T', ' ')} to ${customEndDate.replace('T', ' ')}`;
        } else if (customStartDate) {
          return `From ${customStartDate.replace('T', ' ')}`;
        }
        return 'Custom Range';
      default:
        return 'Last 24 hours';
    }
  }, [filter, customStartDate, customEndDate, durationVal, durationUnit]);

  const filterLabel = filter === 'duration' 
    ? `last_${durationVal}_${durationUnit}` 
    : filter === 'custom' 
      ? (customStartDate && customEndDate ? `${customStartDate}_to_${customEndDate}` : customStartDate || 'custom') 
      : filter;

  const filterButtons = [
    { key: 'today', label: 'Today' },
    { key: 'yesterday', label: 'Yesterday' },
    { key: 'duration', label: 'Time Duration' },
    { key: 'week', label: 'This Week' },
    { key: 'month', label: 'This Month' },
    { key: 'three_months', label: '3 Months' },
    { key: 'custom', label: 'Custom Range' },
  ];

  const stagger = {
    hidden: { opacity: 0 },
    show: { opacity: 1, transition: { staggerChildren: 0.08 } },
  };

  if (devicesLoading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      </div>
    );
  }

  if (allDevices.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <div className="rounded-2xl border border-yellow-500/30 bg-yellow-500/10 p-8 text-center max-w-md">
          <Cpu className="h-12 w-12 text-yellow-400 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-white mb-2">No Devices Configured</h3>
          <p className="text-sm text-slate-400">
            No devices have analytics credentials configured. Go to <strong>Devices → Edit</strong> and add Channel ID & API keys.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Control Toolbar Card */}
      <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-4 backdrop-blur-md space-y-4">
        {/* Row 1: Selectors & Actions */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Left: Device & Room Selection */}
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={selectedDeviceId}
              onChange={(e) => setSelectedDeviceId(e.target.value)}
              className="rounded-xl border border-slate-700 bg-slate-800 px-3.5 py-2 text-xs font-semibold text-white outline-none focus:border-green-500 cursor-pointer"
            >
              {allDevices.map((d) => (
                <option key={d._id} value={d._id}>
                  {d.name}
                </option>
              ))}
            </select>

            {selectedDevice?.deviceType === 'office_control' && (
              <select
                value={selectedRoom}
                onChange={(e) => setSelectedRoom(e.target.value)}
                className="rounded-xl border border-slate-700 bg-slate-800 px-3.5 py-2 text-xs font-semibold text-white outline-none focus:border-green-500 cursor-pointer"
              >
                <option value="room1">Room 1</option>
                <option value="room2">Room 2</option>
                <option value="room3">Room 3</option>
                <option value="both">All Rooms</option>
              </select>
            )}

            <span className="text-xs text-slate-400">
              &bull; <strong className="text-slate-200">{rawFeeds.length.toLocaleString()}</strong> data points loaded {totalDbPoints > rawFeeds.length ? `(downsampled from ${totalDbPoints.toLocaleString()} DB records)` : ''} ({chartSubtitle})
            </span>
          </div>

          {/* Right: Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={fetchData}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-medium text-slate-300 transition-all hover:bg-slate-700 hover:text-white disabled:opacity-50"
              title="Refresh data"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin text-green-400' : ''}`} />
              <span>Refresh</span>
            </button>

            {/* Export Dropdown */}
            <div className="relative">
              <button
                onClick={() => setShowDownloadMenu(!showDownloadMenu)}
                disabled={rawFeeds.length === 0}
                className="flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-800 px-3.5 py-2 text-xs font-medium text-slate-300 transition-all hover:bg-slate-700 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Download className="h-3.5 w-3.5" /> Export
              </button>
              {showDownloadMenu && rawFeeds.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, y: 5 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="absolute right-0 top-full z-20 mt-2 w-48 rounded-xl border border-slate-700 bg-slate-900 p-1 shadow-2xl backdrop-blur-xl"
                >
                  <button
                    onClick={() => { downloadCSV(rawFeeds, channelFields, filterLabel, selectedDevice?.name || 'Device', selectedRoom === 'both'); setShowDownloadMenu(false); }}
                    className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
                  >
                    <span>Download CSV</span>
                    <span className="text-[10px] text-slate-500 font-mono">.csv</span>
                  </button>
                  <button
                    onClick={() => { downloadJSON(rawFeeds, channelFields, filterLabel, selectedDevice?.name || 'Device', selectedRoom === 'both'); setShowDownloadMenu(false); }}
                    className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
                  >
                    <span>Download JSON</span>
                    <span className="text-[10px] text-slate-500 font-mono">.json</span>
                  </button>
                </motion.div>
              )}
            </div>
          </div>
        </div>

        {/* Row 2: Time Filter Tabs */}
        <div className="flex flex-col gap-3 pt-3 border-t border-slate-700/50">
          <div className="flex gap-1 rounded-xl bg-slate-900/60 p-1 border border-slate-700/50 flex-wrap">
            {filterButtons.map((btn) => (
              <button
                key={btn.key}
                onClick={() => {
                  setFilter(btn.key);
                  if (btn.key !== 'custom') {
                    setCustomStartDate('');
                    setCustomEndDate('');
                  }
                }}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${filter === btn.key
                    ? 'bg-green-500/20 text-green-400 border border-green-500/30 font-semibold shadow-sm'
                    : 'text-slate-400 hover:text-white'
                  }`}
              >
                {btn.label}
              </button>
            ))}
          </div>

          {/* Sub-row: Duration controls or Custom Date Picker */}
          {filter === 'duration' && (
            <motion.div
              initial={{ opacity: 0, y: -5 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-wrap items-center gap-2.5 rounded-xl border border-slate-700/60 bg-slate-900/40 p-2"
            >
              <span className="text-xs text-slate-400 font-medium pl-1">Duration:</span>
              <input
                type="number"
                min="1"
                max="999"
                value={durationVal}
                onChange={(e) => setDurationVal(e.target.value)}
                className="w-16 rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-white text-center outline-none focus:border-green-500 font-semibold"
              />
              <select
                value={durationUnit}
                onChange={(e) => setDurationUnit(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 text-xs text-white outline-none cursor-pointer focus:border-green-500"
              >
                <option value="seconds">Seconds</option>
                <option value="minutes">Minutes</option>
                <option value="hours">Hours</option>
                <option value="days">Days</option>
              </select>

              {/* Quick Preset Buttons */}
              <div className="flex items-center gap-1 pl-2 border-l border-slate-700/60">
                {[
                  { val: '30', unit: 'seconds', label: '30s' },
                  { val: '5', unit: 'minutes', label: '5m' },
                  { val: '1', unit: 'hours', label: '1h' },
                  { val: '6', unit: 'hours', label: '6h' },
                  { val: '12', unit: 'hours', label: '12h' },
                  { val: '24', unit: 'hours', label: '24h' },
                ].map(preset => (
                  <button
                    key={preset.label}
                    onClick={() => { setDurationVal(preset.val); setDurationUnit(preset.unit); }}
                    className={`rounded px-2.5 py-1 text-[11px] font-medium transition-all ${
                      durationVal === preset.val && durationUnit === preset.unit
                        ? 'bg-green-500/20 text-green-400 border border-green-500/30 font-semibold shadow-sm'
                        : 'text-slate-400 hover:text-white hover:bg-slate-700/40'
                    }`}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </motion.div>
          )}

          {filter === 'custom' && (
            <motion.div
              initial={{ opacity: 0, y: -5 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-2 rounded-xl border border-slate-700/60 bg-slate-900/40 p-2"
            >
              <input
                type="datetime-local"
                value={customStartDate}
                onChange={(e) => setCustomStartDate(e.target.value)}
                className="rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-white outline-none focus:border-green-500 transition-colors"
              />
              <span className="text-xs text-slate-400">to</span>
              <input
                type="datetime-local"
                value={customEndDate}
                onChange={(e) => setCustomEndDate(e.target.value)}
                min={customStartDate}
                className="rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-white outline-none focus:border-green-500 transition-colors disabled:opacity-50"
                disabled={!customStartDate}
              />
            </motion.div>
          )}
        </div>
      </div>

      {/* Error State */}
      {error && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center justify-between rounded-2xl border border-red-500/30 bg-red-500/10 px-6 py-4"
        >
          <div className="flex items-center gap-3">
            <WifiOff className="h-5 w-5 text-red-400" />
            <div>
              <p className="text-sm font-medium text-red-300">Failed to load analytics data</p>
              <p className="text-xs text-red-400/70">{error}</p>
            </div>
          </div>
          <button
            onClick={fetchData}
            className="rounded-lg bg-red-500/20 px-4 py-2 text-xs font-medium text-red-300 hover:bg-red-500/30 transition-colors"
          >
            Retry
          </button>
        </motion.div>
      )}

      {/* Summary Cards */}
      {loading ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : (
        <motion.div
          variants={stagger}
          initial="hidden"
          animate="show"
          className="grid grid-cols-2 gap-4 lg:grid-cols-4"
        >
          {summaryMetrics.map((metric, i) => (
            <motion.div
              key={i}
              variants={{ hidden: { opacity: 0, y: 20 }, show: { opacity: 1, y: 0 } }}
              className={`rounded-2xl border p-5 backdrop-blur-md transition-all hover:scale-[1.01] ${metric.bg}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className={`rounded-lg p-2 ${metric.color} bg-white/5`}>
                    <metric.icon className="h-4 w-4" />
                  </div>
                  <p className="text-xs font-semibold text-slate-300">{metric.name}</p>
                </div>
                <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 bg-slate-900/60 px-2 py-0.5 rounded-md border border-slate-700/50">
                  Avg
                </span>
              </div>

              <div className="mt-3 flex items-baseline gap-1.5">
                <span className={`text-2xl font-bold tabular-nums ${metric.color}`}>
                  {metric.value}
                </span>
                <span className="text-xs font-medium text-slate-400">{metric.unit}</span>
              </div>

              {/* Min / Max Footer Badge Row */}
              <div className="mt-3 pt-3 border-t border-slate-700/40 flex items-center justify-between text-[11px] text-slate-400">
                <div className="flex items-center gap-1">
                  <span className="text-slate-400 font-medium">Min:</span>
                  <span className="text-slate-300 font-semibold">{metric.min} {metric.unit}</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-slate-400 font-medium">Max:</span>
                  <span className="text-slate-300 font-semibold">{metric.max} {metric.unit}</span>
                </div>
              </div>
            </motion.div>
          ))}
        </motion.div>
      )}

      {/* Charts */}
      {loading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="rounded-2xl border border-slate-700/30 bg-slate-800/30 p-4">
              <div className="skeleton mb-4 h-4 w-32 rounded" />
              <div className="skeleton h-48 w-full rounded-xl" />
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-red-500/50 bg-red-500/5 py-20">
          <WifiOff className="h-12 w-12 text-red-400 mb-4" />
          <p className="text-sm font-medium text-red-400">Unable to load charts due to an error</p>
          <p className="mt-1 text-xs text-red-400/70">Please check your database device configuration or connection</p>
        </div>
      ) : rawFeeds.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-700/50 py-20">
          <Calendar className="h-12 w-12 text-slate-700" />
          <p className="mt-4 text-sm text-slate-500">No data available for the selected time range</p>
          <p className="mt-1 text-xs text-slate-600">Try selecting a different date or time range</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {channelFields.map(f => {
            const meta = getFieldMeta(f.name);
            return (
              <LiveChart key={f.key} data={chartData[f.key]} type={meta.type} title={`${f.name} Trend`} unit={meta.unit} subtitle={chartSubtitle} />
            );
          })}
        </div>
      )}

      {/* Data Summary Table */}
      {!loading && rawFeeds.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="overflow-x-auto rounded-2xl border border-slate-700/60 bg-slate-800/40 backdrop-blur-md shadow-xl"
        >
          <div className="flex items-center justify-between border-b border-slate-700/60 px-6 py-4 bg-slate-800/60">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Activity className="h-4 w-4 text-green-400" /> Statistical Telemetry Summary
            </h3>
            <span className="rounded-full bg-slate-700/60 border border-slate-600/50 px-3 py-1 text-xs font-semibold text-slate-300">
              {rawFeeds.length} Total Readings
            </span>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-900/40">
                <th className="px-6 py-3.5 text-left text-xs font-bold uppercase tracking-wider text-slate-400">Sensor Metric</th>
                <th className="px-6 py-3.5 text-left text-xs font-bold uppercase tracking-wider text-slate-400">Average Reading</th>
                <th className="px-6 py-3.5 text-left text-xs font-bold uppercase tracking-wider text-slate-400">Minimum Reading</th>
                <th className="px-6 py-3.5 text-left text-xs font-bold uppercase tracking-wider text-slate-400">Maximum Reading</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/30">
              {channelFields.map((f) => {
                const meta = getFieldMeta(f.name);
                const stats = summaryStats[f.key] || { avg: '--', min: '--', max: '--' };
                return (
                  <tr key={f.key} className="hover:bg-slate-700/30 transition-colors">
                    <td className="px-6 py-4 font-semibold text-white flex items-center gap-2">
                      <meta.icon className="h-4 w-4 text-green-400" />
                      {f.name}
                    </td>
                    <td className="px-6 py-4 text-green-400 font-bold tabular-nums">
                      {stats.avg} <span className="text-xs text-slate-500 font-normal">{meta.unit}</span>
                    </td>
                    <td className="px-6 py-4 text-cyan-400 font-bold tabular-nums">
                      {stats.min} <span className="text-xs text-slate-500 font-normal">{meta.unit}</span>
                    </td>
                    <td className="px-6 py-4 text-orange-400 font-bold tabular-nums">
                      {stats.max} <span className="text-xs text-slate-500 font-normal">{meta.unit}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </motion.div>
      )}
    </div>
  );
};

export default AnalyticsPage;
