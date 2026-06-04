import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Thermometer, Droplets, Zap, FlaskConical, RefreshCw, Clock, Radio, AlertTriangle, Cpu, ChevronDown, Activity, ArrowUpDown } from 'lucide-react';
import LiveChart from '../../components/LiveChart';
import { SkeletonCard } from '../../components/Skeleton';
import { useAnimatedCounter } from '../../hooks/useAnimatedCounter';
import { getStatusBg, getStatusDot, getMetricStatus, getMetricColor, formatTimestamp } from '../../utils/helpers';
import mqtt from 'mqtt';

const BigMetric = ({ label, value, unit, icon: Icon, type }) => {
  const safeValue = Number.isFinite(value) ? value : 0;
  const animated = useAnimatedCounter(safeValue);
  const status = getMetricStatus(type, safeValue);
  const color = getMetricColor(status);

  const bgColorMap = {
    'text-emerald-400': 'bg-emerald-500/10 border-emerald-500/20',
    'text-yellow-400': 'bg-yellow-500/10 border-yellow-500/20',
    'text-red-400': 'bg-red-500/10 border-red-500/20',
    'text-slate-500': 'bg-slate-500/10 border-slate-500/20',
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      className={`rounded-2xl border p-4 ${bgColorMap[color] || 'bg-slate-800/50 border-slate-700/50'} backdrop-blur-sm`}
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
    </motion.div>
  );
};

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

  // ── Multi-Sensor Live States ────────────────────────────────────────────────
  const [multiSensorData, setMultiSensorData] = useState({});
  const [sensorHistory, setSensorHistory] = useState({}); // { S1: [t1, t2...], S2: [...] }
  const [sortBy, setSortBy] = useState('id'); // 'id', 'temp', 'humi'
  const [selectedSensor, setSelectedSensor] = useState(null); // The sensor currently "clicked" for detail
  const mqttClientRef = useRef(null);

  // ── Office Control Dual Room Live States ────────────────────────────────────
  const [officeControlData, setOfficeControlData] = useState({ 1: null, 2: null });
  const [officeControlHistory, setOfficeControlHistory] = useState({
    1: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
    2: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] }
  });
  const [activeRoomTab, setActiveRoomTab] = useState(1);

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
          // Auto-select the first device with ThingSpeak config if none is selected
          if (!selectedDeviceId && data.data.length > 0) {
            const firstConfigured = data.data.find(
              (d) => (d.thingspeak?.channelId || d.tempChannelId)
            );
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
  const deviceMeta = allDevices.find(
    (d) => d._id === selectedDeviceId || d.id === selectedDeviceId
  );
  const hasThingspeak = (deviceMeta?.thingspeak?.channelId || deviceMeta?.tempChannelId) && (deviceMeta?.thingspeak?.readApiKey || deviceMeta?.tempReadApiKey);

  // ── Handle device change from dropdown ─────────────────────────────────────
  const handleDeviceChange = (newId) => {
    setSelectedDeviceId(newId);
    setSearchParams({ device: newId });
    // Reset live state
    setLiveDevice(null);
    setLoading(true);
    setHasNewData(true);
    previousMetricsRef.current = null;
    setChartData({});
    setActiveMetrics({});
    setActiveFields([]);
    
    // Clear dual-room MQTT states
    setOfficeControlData({ 1: null, 2: null });
    setOfficeControlHistory({
      1: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] },
      2: { soil_temp: [], moisture: [], ec: [], ph: [], room_temp: [], room_humi: [], orp: [], co2: [] }
    });
  };

  // ── Dynamic Field Parsing from ThingSpeak ──────────────────────────────────
  const getFieldDisplayInfo = useCallback((name) => {
    const lower = name.toLowerCase();
    if (lower.includes('temp')) return { icon: Thermometer, unit: '°C', type: 'temperature' };
    if (lower.includes('moist') || lower.includes('humid')) return { icon: Droplets, unit: '%', type: 'moisture' };
    if (lower.includes('ec') || lower.includes('conduct')) return { icon: Zap, unit: 'µS/cm', type: 'ec' };
    if (lower.includes('ph')) return { icon: FlaskConical, unit: 'pH', type: 'ph' };
    if (lower.includes('co2') || lower.includes('carbon')) return { icon: Activity, unit: 'ppm', type: 'co2' };
    return { icon: Radio, unit: '', type: 'default' };
  }, []);

  // ── Step 2: Fetch live data from ThingSpeak using the selected device's keys
  const fetchLiveData = useCallback(() => {
    const channelId = deviceMeta?.thingspeak?.channelId || deviceMeta?.tempChannelId;
    const readApiKey = deviceMeta?.thingspeak?.readApiKey || deviceMeta?.tempReadApiKey;

    if (!channelId || !readApiKey) return;

    const url = `https://api.thingspeak.com/channels/${channelId}/feeds.json?api_key=${readApiKey}&results=24`;

    fetch(url)
      .then((res) => res.json())
      .then((result) => {
        const channel = result?.channel || {};
        const feeds = result?.feeds || [];
        const latestFeed = feeds[feeds.length - 1];

        // Parse dynamic fields configuration from channel
        const fields = Object.keys(channel)
          .filter((k) => k.startsWith('field') && channel[k])
          .map((k) => ({
            key: k,
            label: channel[k],
            ...getFieldDisplayInfo(channel[k]),
          }));

        setActiveFields(fields);

        if (!latestFeed || !latestFeed.entry_id) {
          setLiveDevice(null);
          setHasNewData(false);
          setLoading(false);
          return;
        }

        const lastUpdatedTime = new Date(latestFeed.created_at);
        const diffMs = Date.now() - lastUpdatedTime.getTime();
        // 5 minutes threshold
        const isOnline = diffMs < 5 * 60 * 1000;

        const device = {
          id: selectedDeviceId,
          name: deviceMeta?.name || 'Live Sensor Data',
          location: deviceMeta?.location || 'API Feed',
          status: isOnline ? 'online' : 'offline',
          lastUpdated: latestFeed.created_at,
        };

        const currentMetrics = {};
        fields.forEach(f => {
          currentMetrics[f.key] = parseFloat(latestFeed[f.key]) || 0;
        });

        const newChartData = {};
        fields.forEach(f => {
          newChartData[f.key] = feeds.map(feed => ({
            time: new Date(feed.created_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
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
          setActiveMetrics(currentMetrics);
          setChartData(newChartData);
        }

        setLoading(false);
      })
      .catch((error) => {
        console.error('API Error:', error);
        setLiveDevice(null);
        setHasNewData(false);
        setLoading(false);
      });
  }, [deviceMeta, selectedDeviceId, getFieldDisplayInfo]);

  useEffect(() => {
    const isOfficeControl = deviceMeta?.deviceType === 'office_control';
    if (isOfficeControl) {
      return;
    }

    if (!hasThingspeak && deviceMeta?.deviceType !== 'multi_sensor') {
      setLoading(false);
      return;
    }

    if (hasThingspeak) {
      setLoading(true);
      fetchLiveData();
      const interval = setInterval(fetchLiveData, 15000);
      return () => clearInterval(interval);
    }
  }, [hasThingspeak, fetchLiveData, deviceMeta]);

  // ── Step 3: MQTT Subscription for Multi-Sensor & Office Control Devices ──────
  useEffect(() => {
    const isMultiSensor = deviceMeta?.deviceType === 'multi_sensor';
    const isOfficeControl = deviceMeta?.deviceType === 'office_control';

    let mqttId = deviceMeta?.mqttId;
    if (!mqttId && isOfficeControl) {
      mqttId = 'system2'; // Default fallback for control.py scripts
    }
    if (!mqttId) {
      mqttId = deviceMeta?.id || deviceMeta?._id;
    }

    if ((!isMultiSensor && !isOfficeControl) || !mqttId) {
      if (mqttClientRef.current) {
        mqttClientRef.current.end();
        mqttClientRef.current = null;
      }
      return;
    }

    setLoading(true);
    const client = mqtt.connect('wss://broker.hivemq.com:8884/mqtt');
    mqttClientRef.current = client;

    client.on('connect', () => {
      console.log(`Connected to HiveMQ for ${deviceMeta.deviceType} Live Data`);
      if (isMultiSensor) {
        client.subscribe(`inhydro/${mqttId}/telemetry/live`);
      } else if (isOfficeControl) {
        client.subscribe(`inhydro/${mqttId}/room1/telemetry/live`);
        client.subscribe(`inhydro/${mqttId}/room2/telemetry/live`);
      }
    });

    client.on('message', (topic, message) => {
      try {
        const payload = JSON.parse(message.toString());

        if (isMultiSensor) {
          setMultiSensorData(payload);
          // Update history for sparklines (keep last 20 points)
          setSensorHistory(prev => {
            const newHist = { ...prev };
            Object.keys(payload).forEach(sId => {
              const prevState = newHist[sId] && !Array.isArray(newHist[sId]) ? newHist[sId] : { t: [], h: [] };
              newHist[sId] = {
                t: [...prevState.t, payload[sId].t].slice(-20),
                h: [...prevState.h, payload[sId].h].slice(-20)
              };
            });
            return newHist;
          });
        } else if (isOfficeControl) {
          // Determine room from topic (inhydro/{mqttId}/room{N}/telemetry/live)
          const parts = topic.split('/');
          const roomPart = parts.find(p => p.startsWith('room'));
          const room = roomPart ? parseInt(roomPart.replace('room', '')) : 1;

          setOfficeControlData(prev => ({ ...prev, [room]: payload }));

          // Update history for graphs
          const timeStr = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          setOfficeControlHistory(prev => {
            const roomHist = { ...prev[room] };
            const metrics = {
              soil_temp: payload.soil?.soil_temp,
              moisture: payload.soil?.moisture,
              ec: payload.soil?.ec,
              ph: payload.soil?.ph,
              room_temp: payload.room?.room_temp,
              room_humi: payload.room?.room_humi,
              orp: payload.orp,
              co2: payload.co2
            };
            Object.keys(metrics).forEach(key => {
              const val = metrics[key] !== undefined && metrics[key] !== null ? parseFloat(metrics[key]) : 0;
              roomHist[key] = [...(roomHist[key] || []), { time: timeStr, value: val }].slice(-24);
            });
            return { ...prev, [room]: roomHist };
          });
        }

        setLiveDevice({
          id: selectedDeviceId,
          name: deviceMeta?.name || 'Live Sensor Data',
          location: deviceMeta?.location || 'MQTT Stream',
          status: 'online',
          lastUpdated: new Date().toISOString(),
        });

        setLoading(false);
        setHasNewData(true);
        setTimeout(() => setHasNewData(false), 2000);
      } catch (e) {
        console.error('MQTT Parse Error', e);
      }
    });

    return () => {
      if (client) client.end();
    };
  }, [deviceMeta, selectedDeviceId]);

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
            Add devices in the <strong>Devices</strong> page with ThingSpeak configuration to start monitoring.
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
                const hasCfg = d.thingspeak?.channelId && d.thingspeak?.readApiKey;
                return (
                  <option key={d._id} value={d._id}>
                    {d.name} — {d.location}
                    {hasCfg ? ` (CH:${d.thingspeak.channelId})` : ' (No ThingSpeak)'}
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

          {/* ThingSpeak Channel Badge */}
          {hasThingspeak && (
            <span className="inline-flex items-center gap-1 rounded-full border border-blue-500/20 bg-blue-500/10 px-2.5 py-1 text-[10px] font-semibold text-blue-400">
              <Radio className="h-3 w-3" /> CH: {deviceMeta.thingspeak.channelId}
            </span>
          )}
        </div>

        {/* Right: Refresh & Status */}
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <Clock className="h-3.5 w-3.5" />
          Last updated: {liveDevice?.lastUpdated ? formatTimestamp(liveDevice.lastUpdated) : '--'}
          <button
            onClick={handleRefresh}
            disabled={!hasThingspeak}
            className="rounded-lg border border-slate-700 p-1.5 transition-colors hover:bg-slate-800 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
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

      {/* ── ThingSpeak Not Configured Warning ─────────────────────────────── */}
      {selectedDeviceId && !hasThingspeak && deviceMeta?.deviceType !== 'multi_sensor' && deviceMeta?.deviceType !== 'office_control' && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-start gap-4 rounded-2xl border border-yellow-500/30 bg-yellow-500/10 p-6"
        >
          <AlertTriangle className="h-6 w-6 text-yellow-400 shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-white mb-1">ThingSpeak Not Configured</h3>
            <p className="text-sm text-slate-400">
              {deviceMeta
                ? `"${deviceMeta.name}" does not have ThingSpeak API keys configured.`
                : 'Device not found.'}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Go to <strong>Devices → Edit</strong> and add the Channel ID &amp; Read API Key to start streaming live data.
            </p>
          </div>
        </motion.div>
      )}

      {/* ── Office Control Dual-Room Live View ───────────────────────────── */}
      {deviceMeta?.deviceType === 'office_control' && (
        <div className="space-y-6">
          {/* Room Selection Tabs */}
          <div className="flex border-b border-slate-700/60 pb-px">
            {[1, 2].map((room) => (
              <button
                key={room}
                onClick={() => setActiveRoomTab(room)}
                className={`relative px-6 py-3.5 text-sm font-semibold transition-all hover:text-white ${
                  activeRoomTab === room ? 'text-green-400' : 'text-slate-400'
                }`}
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
              
              {!officeControlData[activeRoomTab] && loading ? (
                <div className="space-y-4">
                  {[...Array(8)].map((_, i) => (
                    <SkeletonCard key={i} />
                  ))}
                </div>
              ) : !officeControlData[activeRoomTab] ? (
                <div className="rounded-2xl border border-dashed border-slate-700/50 p-6 text-sm text-slate-400 text-center">
                  <div className="animate-pulse mb-2 text-green-500 font-medium">Waiting for Live Device Stream...</div>
                  <div className="text-xs text-slate-500">Please start control.py on your device to stream real-time data.</div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-2 xl:grid-cols-1">
                  <BigMetric
                    label="Soil Temp"
                    value={officeControlData[activeRoomTab].soil?.soil_temp}
                    unit="°C"
                    icon={Thermometer}
                    type="temperature"
                  />
                  <BigMetric
                    label="Soil Moisture"
                    value={officeControlData[activeRoomTab].soil?.moisture}
                    unit="%"
                    icon={Droplets}
                    type="moisture"
                  />
                  <BigMetric
                    label="Soil EC"
                    value={officeControlData[activeRoomTab].soil?.ec}
                    unit="µS/cm"
                    icon={Zap}
                    type="ec"
                  />
                  <BigMetric
                    label="Soil pH"
                    value={officeControlData[activeRoomTab].soil?.ph}
                    unit="pH"
                    icon={FlaskConical}
                    type="ph"
                  />
                  <BigMetric
                    label="Room Temp"
                    value={officeControlData[activeRoomTab].room?.room_temp}
                    unit="°C"
                    icon={Thermometer}
                    type="temperature"
                  />
                  <BigMetric
                    label="Room Humidity"
                    value={officeControlData[activeRoomTab].room?.room_humi}
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
                </div>
              )}
            </div>

            {/* Right: Real-time Charts */}
            <div className="space-y-4 xl:col-span-2">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Trend Charts</h3>
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
                  <LiveChart
                    data={officeControlHistory[activeRoomTab].soil_temp}
                    type="temperature"
                    title="Soil Temperature Trend"
                    unit="°C"
                  />
                  <LiveChart
                    data={officeControlHistory[activeRoomTab].moisture}
                    type="moisture"
                    title="Soil Moisture Trend"
                    unit="%"
                  />
                  <LiveChart
                    data={officeControlHistory[activeRoomTab].ec}
                    type="ec"
                    title="Soil EC Trend"
                    unit="µS/cm"
                  />
                  <LiveChart
                    data={officeControlHistory[activeRoomTab].ph}
                    type="ph"
                    title="Soil pH Trend"
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
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {deviceMeta?.deviceType === 'multi_sensor' && (
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
                <motion.div
                  key={sensorId}
                  initial={{ opacity: 0, scale: 0.95 }}
                  whileHover={{ y: -5 }}
                  animate={{ opacity: 1, scale: 1 }}
                  onClick={() => setSelectedSensor(sensorId)}
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
                      {(sensorHistory[sensorId]?.t || [0]).map((val, i) => {
                        // Scale value between 10% and 100% based on range (e.g. 10-40 degrees)
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
              ))}
          </div>

          {Object.keys(multiSensorData).length === 0 && !loading && (
            <div className="py-12 text-center text-slate-500 text-sm italic">
              Waiting for the sensor to be online...
            </div>
          )}
        </div>
      )}

      {/* ── Multi-Sensor Sensor Detail Modal ─────────────────────────────── */}
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
      {hasThingspeak && deviceMeta?.deviceType !== 'multi_sensor' && deviceMeta?.deviceType !== 'office_control' && (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
          {/* Left: Big Metrics */}
          <div className="space-y-4 xl:col-span-1">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Live Readings</h3>
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
            {loading ? (
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
