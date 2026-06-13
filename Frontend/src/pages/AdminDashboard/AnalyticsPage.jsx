import { useState, useEffect, useMemo, useCallback } from 'react';
import { motion } from 'framer-motion';
import { Download, Calendar, RefreshCw, WifiOff, BarChart3, TrendingUp, TrendingDown, Activity, Cpu } from 'lucide-react';
import LiveChart from '../../components/LiveChart';
import { SkeletonCard } from '../../components/Skeleton';


// Get date ranges for filters
const getDateRange = (filter, customStartDate = null, customEndDate = null) => {
  const now = new Date();
  let start;
  const end = new Date(now);

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
    case 'custom': {
      if (customStartDate && customEndDate) {
        const sd = new Date(customStartDate);
        const ed = new Date(customEndDate);
        start = new Date(sd.getFullYear(), sd.getMonth(), sd.getDate(), 0, 0, 0);
        end.setTime(new Date(ed.getFullYear(), ed.getMonth(), ed.getDate(), 23, 59, 59).getTime());
      } else if (customStartDate) {
        const d = new Date(customStartDate);
        start = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0);
        end.setTime(new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59, 59).getTime());
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

// Format feeds into chart-ready data dynamically based on available channel fields
const mapFeedsToCharts = (feeds, filter, channelFields, isBothRooms = false) => {
  const validFeeds = Array.isArray(feeds) ? feeds : [];
  const timeFormat = filter === 'today' || filter === 'custom'
    ? { hour: '2-digit', minute: '2-digit' }
    : { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };

  if (!isBothRooms) {
    const mappedData = {};
    channelFields.forEach(field => {
      mappedData[field.key] = validFeeds.map((f) => ({
        time: new Date(f.created_at).toLocaleTimeString('en-US', timeFormat),
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
          time: new Date(roundedMs).toLocaleTimeString('en-US', timeFormat),
          rawTimestamp: roundedMs
        });
      }
      
      const group = timeGroupsMap.get(roundedMs);
      const isRoom2 = f.room === 'room2';
      const suffix = isRoom2 ? 'Room2' : 'Room1';
      
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
        isBoth: true
      }));
    });

    return mappedData;
  }
};

// Download helpers
const downloadCSV = (feeds, channelFields, filterLabel, isBoth = false) => {
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
  const date = new Date().toISOString().split('T')[0];
  a.href = url;
  a.download = `sensor_data_${filterLabel}_${date}.csv`;
  a.click();
  URL.revokeObjectURL(url);
};

const downloadJSON = (feeds, channelFields, filterLabel, isBoth = false) => {
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
  const date = new Date().toISOString().split('T')[0];
  a.href = url;
  a.download = `sensor_data_${filterLabel}_${date}.json`;
  a.click();
  URL.revokeObjectURL(url);
};

const AnalyticsPage = () => {
  const [filter, setFilter] = useState('today');
  const [customStartDate, setCustomStartDate] = useState('');
  const [customEndDate, setCustomEndDate] = useState('');
  const [rawFeeds, setRawFeeds] = useState([]);
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
          const tsDevices = data.data.filter(
            (d) => (d.thingspeak?.channelId || d.tempChannelId)
          );
          setAllDevices(tsDevices);
          if (tsDevices.length > 0 && !selectedDeviceId) {
            setSelectedDeviceId(tsDevices[0]._id);
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
      const { start, end } = getDateRange(filter, customStartDate, customEndDate);
      const roomParam = selectedDevice?.deviceType === 'office_control' ? `&room=${selectedRoom}` : '';
      const url = `${API_BASE}/api/devices/${selectedDeviceId}/analytics?start=${start.toISOString()}&end=${end.toISOString()}${roomParam}`;
      
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });
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
      for (let i = 1; i <= 8; i++) {
        const key = `field${i}`;
        const hasData = exactFeeds.some(f => f[key] != null && f[key] !== '');
        if (result.channel?.[key] || hasData) {
          cFields.push({ key, name: result.channel?.[key] || `Field ${i}` });
        }
      }
      setChannelFields(cFields);

      setRawFeeds(exactFeeds);
    } catch (err) {
      console.error('Analytics API error:', err);
      setError(err.message || 'Failed to fetch data');
      setRawFeeds([]);
      setChannelFields([]);
    } finally {
      setLoading(false);
    }
  }, [filter, customStartDate, customEndDate, selectedDeviceId, token, API_BASE, selectedRoom, selectedDevice?.deviceType]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Build chart data from raw feeds
  const chartData = useMemo(() => mapFeedsToCharts(rawFeeds, filter, channelFields, selectedRoom === 'both'), [rawFeeds, filter, channelFields, selectedRoom]);

  // Statistical helpers
  const calcAvg = (data) => {
    if (!data || data.length === 0) return '--';
    const values = data.map(d => {
      if (d.isBoth) {
        const vals = [d.room1Value, d.room2Value].filter(v => v !== null && v !== undefined);
        return vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
      }
      return d.value;
    }).filter(v => v !== null && v !== undefined);
    if (values.length === 0) return '--';
    return (values.reduce((s, v) => s + v, 0) / values.length).toFixed(1);
  };
  const calcMax = (data) => {
    if (!data || data.length === 0) return '--';
    const values = data.map(d => {
      if (d.isBoth) {
        const vals = [d.room1Value, d.room2Value].filter(v => v !== null && v !== undefined);
        return vals.length > 0 ? Math.max(...vals) : null;
      }
      return d.value;
    }).filter(v => v !== null && v !== undefined);
    if (values.length === 0) return '--';
    return Math.max(...values).toFixed(1);
  };
  const calcMin = (data) => {
    if (!data || data.length === 0) return '--';
    const values = data.map(d => {
      if (d.isBoth) {
        const vals = [d.room1Value, d.room2Value].filter(v => v !== null && v !== undefined);
        return vals.length > 0 ? Math.min(...vals) : null;
      }
      return d.value;
    }).filter(v => v !== null && v !== undefined);
    if (values.length === 0) return '--';
    return Math.min(...values).toFixed(1);
  };

  const summaryMetrics = channelFields.map(f => {
    const meta = getFieldMeta(f.name);
    return {
      label: `Avg ${f.name}`,
      value: calcAvg(chartData[f.key]),
      unit: meta.unit,
      icon: meta.icon,
      color: meta.color,
      bg: meta.bg
    };
  });

  const filterLabel = filter === 'custom' ? (customStartDate && customEndDate ? `${customStartDate}_to_${customEndDate}` : customStartDate || 'custom') : filter;

  const filterButtons = [
    { key: 'yesterday', label: 'Yesterday' },
    { key: 'today', label: 'Today' },
    { key: 'week', label: 'This Week' },
    { key: 'month', label: 'This Month' },
    { key: 'three_months', label: '3 Months' },
    { key: 'custom', label: 'Custom Date' },
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
      {/* Header */}
      <div className="flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-sm text-slate-400 mb-4">
            {selectedDevice?.name || 'Select a device'} &bull; {rawFeeds.length} data points loaded ({filter === 'custom' ? (customStartDate && customEndDate ? `${customStartDate} to ${customEndDate}` : customStartDate || 'Custom Date') : filterButtons.find(b => b.key === filter)?.label})
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3 justify-between ">
          {/* Device Selector */}
          <select
            value={selectedDeviceId}
            onChange={(e) => setSelectedDeviceId(e.target.value)}
            className="rounded-xl border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm text-white outline-none focus:border-green-500"
          >
            {allDevices.map((d) => (
              <option key={d._id} value={d._id}>
                {d.name} (CH: {d.thingspeak?.channelId || 'Local'})
              </option>
            ))}
          </select>

          {/* Room Selector for office_control Devices */}
          {selectedDevice?.deviceType === 'office_control' && (
            <select
              value={selectedRoom}
              onChange={(e) => setSelectedRoom(e.target.value)}
              className="rounded-xl border border-slate-700 bg-slate-800/50 px-3 py-2 text-sm text-white outline-none focus:border-green-500"
            >
              <option value="room1">Room 1</option>
              <option value="room2">Room 2</option>
              <option value="both">Both Rooms</option>
            </select>
          )}

          {/* Time Filter Tabs */}
          <div className="flex gap-1 rounded-xl bg-slate-800/50 p-1">
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
                    ? 'bg-green-500/20 text-green-400 shadow-sm'
                    : 'text-slate-400 hover:text-white'
                  }`}
              >
                {btn.label}
              </button>
            ))}
          </div>

          {/* Custom Date Picker */}
          {filter === 'custom' && (
            <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="flex items-center gap-2">
              <input
                type="date"
                value={customStartDate}
                onChange={(e) => setCustomStartDate(e.target.value)}
                max={new Date().toISOString().split('T')[0]}
                className="rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-white outline-none focus:border-blue-500 transition-colors"
              />
              <span className="text-slate-400">to</span>
              <input
                type="date"
                value={customEndDate}
                onChange={(e) => setCustomEndDate(e.target.value)}
                min={customStartDate}
                max={new Date().toISOString().split('T')[0]}
                className="rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-white outline-none focus:border-blue-500 transition-colors disabled:opacity-50"
                disabled={!customStartDate}
              />
            </motion.div>
          )}

          {/* Refresh */}
          <button
            onClick={fetchData}
            disabled={loading}
            className="rounded-xl border border-slate-700 p-2.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white disabled:opacity-50"
            title="Refresh data"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>

          {/* Download Dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowDownloadMenu(!showDownloadMenu)}
              disabled={rawFeeds.length === 0}
              className="flex items-center gap-2 rounded-xl border border-slate-700 px-4 py-2.5 text-sm font-medium text-slate-400 transition-colors hover:bg-slate-800 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Download className="h-4 w-4" /> Export
            </button>
            {showDownloadMenu && rawFeeds.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: -5 }}
                animate={{ opacity: 1, y: 0 }}
                className="absolute right-0 top-full z-20 mt-2 w-48 rounded-xl border border-slate-700 bg-slate-800 p-1 shadow-2xl"
              >
                <button
                  onClick={() => { downloadCSV(rawFeeds, channelFields, filterLabel, selectedRoom === 'both'); setShowDownloadMenu(false); }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-sm text-slate-300 hover:bg-slate-700 hover:text-white transition-colors"
                >
                  <Download className="h-3.5 w-3.5" /> Download CSV
                </button>
                <button
                  onClick={() => { downloadJSON(rawFeeds, channelFields, filterLabel, selectedRoom === 'both'); setShowDownloadMenu(false); }}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-sm text-slate-300 hover:bg-slate-700 hover:text-white transition-colors"
                >
                  <Download className="h-3.5 w-3.5" /> Download JSON
                </button>
              </motion.div>
            )}
          </div>
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
              className={`rounded-2xl border p-5 backdrop-blur-sm ${metric.bg}`}
            >
              <div className="flex items-center gap-2">
                <metric.icon className={`h-4 w-4 ${metric.color}`} />
                <p className="text-xs font-medium text-slate-500">{metric.label}</p>
              </div>
              <p className={`mt-2 text-2xl font-bold tabular-nums ${metric.color}`}>
                {metric.value}{metric.value !== '--' ? metric.unit : ''}
              </p>
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
              <LiveChart key={f.key} data={chartData[f.key]} type={meta.type} title={`${f.name} Trend`} unit={meta.unit} />
            );
          })}
        </div>
      )}

      {/* Data Summary Table */}
      {!loading && rawFeeds.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="overflow-x-auto rounded-2xl border border-slate-700/50 bg-slate-800/30"
        >
          <div className="flex items-center justify-between border-b border-slate-700/50 px-6 py-4">
            <h3 className="text-sm font-semibold text-white">Data Summary</h3>
            <span className="text-xs text-slate-500">{rawFeeds.length} readings</span>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Metric</th>
                <th className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Average</th>
                <th className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Min</th>
                <th className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Max</th>
              </tr>
            </thead>
            <tbody>
              {channelFields.map((f) => {
                const meta = getFieldMeta(f.name);
                const data = chartData[f.key];
                return (
                  <tr key={f.key} className="border-b border-slate-700/30 hover:bg-slate-800/50 transition-colors">
                    <td className="px-6 py-3 font-medium text-white">{f.name}</td>
                    <td className="px-6 py-3 text-slate-300">{calcAvg(data)} {meta.unit}</td>
                    <td className="px-6 py-3 text-cyan-400">{calcMin(data)} {meta.unit}</td>
                    <td className="px-6 py-3 text-orange-400">{calcMax(data)} {meta.unit}</td>
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
