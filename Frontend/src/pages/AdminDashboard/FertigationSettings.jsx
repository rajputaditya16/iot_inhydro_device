import { useState, useEffect, useRef } from 'react';
import {
  Save, AlertCircle, CheckCircle2, RefreshCw, ChevronDown, Server, Edit3,
  Sliders, ShieldCheck, Sprout, Layers, Play, Square, Clock, FlaskConical,
  Activity, Thermometer, Zap, Droplets, ArrowLeft, Info, Cpu, ChevronLeft, ChevronRight, Home
} from 'lucide-react';
import { createMqttClient } from '../../utils/mqtt';
import { telemetryWs } from '../../utils/websocketClient';

//  -----------------------------------------------------------------------------
//   EXACT 4-VENTURI & 2-ZONE DEFAULT RECIPES MATCHING fertigation_hmi_controller.py
//   -----------------------------------------------------------------------------
const defaultRecipes = {
  cucumber: {
    crop_name: 'Cucumber',
    ec_min: 1.80,
    ec_max: 2.20,
    ph_min: 5.40,
    ph_target: 5.80,
    ph_max: 6.40,
    ec1_safety_max: 2.50,
    ec2_safety_max: 2.50,
    ph_down_safety_min: 4.60,
    ph_up_safety_max: 7.20,
    timer_enabled: true,
    start_time: '06:00',
    stop_time: '18:00',
    on_min: 5.0,
    off_min: 60.0,
    zones: {
      both: { crop_name: 'Cucumber', ec_min: 1.80, ec_max: 2.20, ph_min: 5.40, ph_target: 5.80, ph_max: 6.40, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true },
      zone_1: { crop_name: 'Cucumber', ec_min: 1.80, ec_max: 2.20, ph_min: 5.40, ph_target: 5.80, ph_max: 6.40, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true },
      zone_2: { crop_name: 'Cucumber', ec_min: 1.80, ec_max: 2.20, ph_min: 5.40, ph_target: 5.80, ph_max: 6.40, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true }
    }
  },
  tomato: {
    crop_name: 'Tomato',
    ec_min: 2.00,
    ec_max: 2.50,
    ph_min: 5.50,
    ph_target: 6.00,
    ph_max: 6.50,
    ec1_safety_max: 2.80,
    ec2_safety_max: 2.80,
    ph_down_safety_min: 4.80,
    ph_up_safety_max: 7.50,
    timer_enabled: true,
    start_time: '06:00',
    stop_time: '18:00',
    on_min: 5.0,
    off_min: 60.0,
    zones: {
      both: { crop_name: 'Tomato', ec_min: 2.00, ec_max: 2.50, ph_min: 5.50, ph_target: 6.00, ph_max: 6.50, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true },
      zone_1: { crop_name: 'Tomato', ec_min: 2.00, ec_max: 2.50, ph_min: 5.50, ph_target: 6.00, ph_max: 6.50, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true },
      zone_2: { crop_name: 'Tomato', ec_min: 2.00, ec_max: 2.50, ph_min: 5.50, ph_target: 6.00, ph_max: 6.50, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true }
    }
  },
  capsicum: {
    crop_name: 'Capsicum / Bell Pepper',
    ec_min: 1.80,
    ec_max: 2.20,
    ph_min: 5.80,
    ph_target: 6.20,
    ph_max: 6.60,
    ec1_safety_max: 2.50,
    ec2_safety_max: 2.50,
    ph_down_safety_min: 5.00,
    ph_up_safety_max: 7.50,
    timer_enabled: true,
    start_time: '06:00',
    stop_time: '18:00',
    on_min: 5.0,
    off_min: 60.0,
    zones: {
      both: { crop_name: 'Capsicum / Bell Pepper', ec_min: 1.80, ec_max: 2.20, ph_min: 5.80, ph_target: 6.20, ph_max: 6.60, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true },
      zone_1: { crop_name: 'Capsicum / Bell Pepper', ec_min: 1.80, ec_max: 2.20, ph_min: 5.80, ph_target: 6.20, ph_max: 6.60, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true },
      zone_2: { crop_name: 'Capsicum / Bell Pepper', ec_min: 1.80, ec_max: 2.20, ph_min: 5.80, ph_target: 6.20, ph_max: 6.60, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true }
    }
  },
  strawberry: {
    crop_name: 'Strawberry',
    ec_min: 1.20,
    ec_max: 1.60,
    ph_min: 5.40,
    ph_target: 5.80,
    ph_max: 6.30,
    ec1_safety_max: 1.90,
    ec2_safety_max: 1.90,
    ph_down_safety_min: 4.80,
    ph_up_safety_max: 7.00,
    timer_enabled: true,
    start_time: '06:00',
    stop_time: '18:00',
    on_min: 5.0,
    off_min: 60.0,
    zones: {
      both: { crop_name: 'Strawberry', ec_min: 1.20, ec_max: 1.60, ph_min: 5.40, ph_target: 5.80, ph_max: 6.30, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true },
      zone_1: { crop_name: 'Strawberry', ec_min: 1.20, ec_max: 1.60, ph_min: 5.40, ph_target: 5.80, ph_max: 6.30, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true },
      zone_2: { crop_name: 'Strawberry', ec_min: 1.20, ec_max: 1.60, ph_min: 5.40, ph_target: 5.80, ph_max: 6.30, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true }
    }
  },
  lettuce: {
    crop_name: 'Lettuce / Leafy Greens',
    ec_min: 1.10,
    ec_max: 1.40,
    ph_min: 5.40,
    ph_target: 5.80,
    ph_max: 6.30,
    ec1_safety_max: 1.70,
    ec2_safety_max: 1.70,
    ph_down_safety_min: 4.80,
    ph_up_safety_max: 7.00,
    timer_enabled: true,
    start_time: '06:00',
    stop_time: '18:00',
    on_min: 5.0,
    off_min: 60.0,
    zones: {
      both: { crop_name: 'Lettuce / Leafy Greens', ec_min: 1.10, ec_max: 1.40, ph_min: 5.40, ph_target: 5.80, ph_max: 6.30, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true },
      zone_1: { crop_name: 'Lettuce / Leafy Greens', ec_min: 1.10, ec_max: 1.40, ph_min: 5.40, ph_target: 5.80, ph_max: 6.30, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true },
      zone_2: { crop_name: 'Lettuce / Leafy Greens', ec_min: 1.10, ec_max: 1.40, ph_min: 5.40, ph_target: 5.80, ph_max: 6.30, start_time: '06:00', stop_time: '18:00', on_min: 5.0, off_min: 60.0, timer_enabled: true }
    }
  }
};

const defaultCyclicTimers = {
  zone_1: {
    name: 'Zone 1 Drip Line',
    enabled: true,
    start_time: '06:00',
    stop_time: '18:00',
    on_min: 5.0,
    off_min: 15.0
  },
  zone_2: {
    name: 'Zone 2 Drip Line',
    enabled: true,
    start_time: '06:00',
    stop_time: '18:00',
    on_min: 5.0,
    off_min: 15.0
  }
};

const ACTUATOR_NAMES = {
  1:  { name: 'EC 1 (Stock A)', code: 'EC1' },
  2:  { name: 'EC 2 (Stock B)', code: 'EC2' },
  3:  { name: 'pH Down (Acid)', code: 'pH Down' },
  4:  { name: 'pH Up (Base)', code: 'pH Up' },
  5:  { name: 'Spare Valve', code: 'Relay 5' },
  6:  { name: 'RO Fresh Water Pump', code: 'RO Pump' },
  7:  { name: 'Tank Return Loop Valve', code: 'S.V 7' },
  8:  { name: 'Main Circulation Pump', code: 'Main Pump' },
  9:  { name: 'Pump Outlet Discharge Valve', code: 'S.V 9' },
  10: { name: 'Fertigation Loop Valve', code: 'S.V 10' },
  11: { name: 'Irrigation Master Valve', code: 'S.V 11' },
  12: { name: 'Zone 1 Delivery Valve', code: 'Zone 1' },
  13: { name: 'Zone 2 Delivery Valve', code: 'Zone 2' },
};

// Module sequence matching Python HMI PAGE_SEQUENCE
const PAGE_SEQUENCE = ['settings', 'monitoring', 'fertigation', 'irrigation'];

export default function FertigationSettings() {
  const [devices, setDevices] = useState([]);
  const [deviceRoot, setDeviceRoot] = useState('');
  const [recipes, setRecipes] = useState(defaultRecipes);
  const [activeCrop, setActiveCrop] = useState('cucumber');
  const [deliveryZone, setDeliveryZone] = useState('both'); // both | zone_1 | zone_2
  const [cyclicTimers, setCyclicTimers] = useState(defaultCyclicTimers);

  // Active Screen Tab: settings (default matching user's photo), monitoring, fertigation, irrigation
  const [activeTab, setActiveTab] = useState('settings');

  const [loading, setLoading] = useState(true);
  const [brokerStatus, setBrokerStatus] = useState('disconnected');
  const [machineOnline, setMachineOnline] = useState(false);
  const [liveData, setLiveData] = useState(null);
  const [isDeviceDropdownOpen, setIsDeviceDropdownOpen] = useState(false);
  const [saveStatus, setSaveStatus] = useState('idle');
  const [statusMessage, setStatusMessage] = useState('');

  const mqttClientRef = useRef(null);
  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // 1. Fetch fertigation devices
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.success && Array.isArray(data.data)) {
          const fert = data.data.filter(
            d => d.deviceType === 'fertigation' ||
              (d.name && d.name.toLowerCase().includes('fert')) ||
              (d.mqttId && d.mqttId.toLowerCase().includes('control12')) ||
              (d.mqttId && d.mqttId.toLowerCase().includes('fert'))
          );
          setDevices(fert.length > 0 ? fert : data.data);
          if (fert.length > 0 && !deviceRoot) {
            setDeviceRoot(fert[0].mqttId || fert[0]._id);
          } else if (data.data.length > 0 && !deviceRoot) {
            setDeviceRoot(data.data[0].mqttId || data.data[0]._id);
          }
        }
      } catch (err) {
        console.error('Fetch devices error:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchDevices();
  }, [token, API_BASE]);

  const selectedDevice = devices.find(d => (d.mqttId || d._id) === deviceRoot);
  const selectedDeviceId = selectedDevice?._id || '';

  const onlineWatchdogRef = useRef(null);

  // Hydrate DB setpoints
  useEffect(() => {
    if (selectedDevice) {
      if (selectedDevice.status === 'online') {
        setMachineOnline(true);
      }
      const saved = selectedDevice.settings?.fertigation;
      if (saved) {
        if (saved.crop_recipes) setRecipes(prev => ({ ...prev, ...saved.crop_recipes }));
        if (saved.cyclic_timers) setCyclicTimers(prev => ({ ...prev, ...saved.cyclic_timers }));
        if (saved.active_crop) setActiveCrop(saved.active_crop);
        if (saved.delivery_zone) setDeliveryZone(saved.delivery_zone);
      }
    }
  }, [selectedDeviceId, selectedDevice?.status]);

  // 2. Real-Time Telemetry & MQTT Listener
  useEffect(() => {
    if (!deviceRoot) return;
    setBrokerStatus('connected');
    const mqttClient = createMqttClient();
    mqttClientRef.current = mqttClient;

    const markOnline = () => {
      setMachineOnline(true);
      if (onlineWatchdogRef.current) clearTimeout(onlineWatchdogRef.current);
      onlineWatchdogRef.current = setTimeout(() => {
        setMachineOnline(false);
      }, 25000); // 25s timeout allows smooth bridge across 3s heartbeat/telemetry bursts
    };

    const handlePacket = (topic, messageData) => {
      try {
        const payload = typeof messageData === 'string' ? JSON.parse(messageData) : messageData;
        if (!payload) return;

        markOnline();

        // 1. Setpoints sync packet handling
        if ((topic && (topic.includes('/setpoints/current') || topic.includes('/config'))) || payload.crop_recipes) {
          if (payload.crop_recipes) setRecipes(prev => ({ ...prev, ...payload.crop_recipes }));
          if (payload.cyclic_timers) setCyclicTimers(prev => ({ ...prev, ...payload.cyclic_timers }));
          if (payload.active_crop) setActiveCrop(payload.active_crop);
          if (payload.delivery_zone) setDeliveryZone(payload.delivery_zone);
        }

        // 2. Telemetry packet merging (Do NOT overwrite if packet is heartbeat or pure config)
        const incoming = payload.telemetry || payload;
        const hasSensoryData =
          incoming.ec !== undefined ||
          incoming.ph !== undefined ||
          incoming.water_temp !== undefined ||
          incoming.temp !== undefined ||
          incoming.relays !== undefined ||
          incoming.fertigation !== undefined ||
          incoming.irrigation !== undefined;

        if (hasSensoryData) {
          setLiveData(prev => {
            const next = { ...(prev || {}) };

            if (incoming.ec !== undefined && incoming.ec !== null) next.ec = incoming.ec;
            if (incoming.ph !== undefined && incoming.ph !== null) next.ph = incoming.ph;
            if (incoming.water_temp !== undefined && incoming.water_temp !== null) {
              next.water_temp = incoming.water_temp;
            } else if (incoming.temp !== undefined && incoming.temp !== null) {
              next.water_temp = incoming.temp;
            }

            if (incoming.fertigation && typeof incoming.fertigation === 'object') {
              next.fertigation = { ...(prev?.fertigation || {}), ...incoming.fertigation };
            }
            if (incoming.irrigation && typeof incoming.irrigation === 'object') {
              next.irrigation = { ...(prev?.irrigation || {}), ...incoming.irrigation };
            }
            if (incoming.relays && typeof incoming.relays === 'object') {
              next.relays = { ...(prev?.relays || {}), ...incoming.relays };
            }

            next.timestamp = incoming.timestamp || new Date().toISOString();
            return next;
          });
        }
      } catch (err) {
        console.debug('Telemetry parse error:', err);
      }
    };

    mqttClient.on('connect', () => {
      setBrokerStatus('connected');
      mqttClient.subscribe(`inhydro/${deviceRoot}/setpoints/current`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/telemetry`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/telemetry/live`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/heartbeat`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/state`);
      mqttClient.publish(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');
    });

    mqttClient.on('message', (topic, message) => {
      handlePacket(topic, message.toString());
    });

    mqttClient.on('error', () => {
      // Don't mark broker disconnected if WS or SSE is still streaming
    });

    // WebSocket Room Subscription
    const targetRooms = [selectedDeviceId, deviceRoot].filter(Boolean).map(s => String(s).toLowerCase());
    telemetryWs.subscribe(targetRooms);

    const unbindWs = telemetryWs.onMessage((packet) => {
      if (!packet) return;
      const mId = packet.mqttId ? String(packet.mqttId).toLowerCase() : '';
      const top = packet.topic ? String(packet.topic).toLowerCase() : '';
      if (targetRooms.includes(mId) || targetRooms.some(r => top.includes(r))) {
        handlePacket(packet.topic, packet.data);
      }
    });

    // SSE fallback
    const sseUrl = `${API_BASE}/api/devices/stream?deviceId=${selectedDeviceId || ''}&mqttId=${deviceRoot}`;
    const eventSource = new EventSource(sseUrl);
    eventSource.onmessage = (event) => {
      try {
        if (!event.data || event.data.startsWith(':')) return;
        const packet = JSON.parse(event.data);
        if (packet.mqttId === deviceRoot || packet.topic?.includes(deviceRoot)) {
          handlePacket(packet.topic, packet.data);
        }
      } catch (e) {}
    };

    return () => {
      if (onlineWatchdogRef.current) clearTimeout(onlineWatchdogRef.current);
      telemetryWs.unsubscribe(targetRooms);
      unbindWs();
      if (mqttClient) mqttClient.end();
      mqttClientRef.current = null;
      eventSource.close();
    };
  }, [deviceRoot, selectedDeviceId, API_BASE]);

  // 3. Command Dispatch
  const sendCommand = async (action, extra = {}) => {
    if (!deviceRoot) return;
    setStatusMessage(`Sending "${action}" command...`);
    try {
      const devId = selectedDevice?._id || deviceRoot;
      const res = await fetch(`${API_BASE}/api/devices/${devId}/command`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ action, ...extra })
      });
      const data = await res.json();
      if (data.success) {
        setStatusMessage(`Command "${action}" sent.`);
        setTimeout(() => setStatusMessage(''), 3000);
      } else {
        setStatusMessage(`Notice: ${data.message || 'Error executing'}`);
      }
    } catch (err) {
      setStatusMessage(`Error: ${err.message}`);
    }
  };

  // Active Crop / Zone data resolution
  const cropData = recipes[activeCrop] || defaultRecipes[activeCrop] || defaultRecipes.cucumber;
  const zoneRecipe = (cropData.zones && cropData.zones[deliveryZone]) || cropData;

  const handleRecipeFieldChange = (field, val) => {
    const isNum = !isNaN(parseFloat(val)) && field !== 'crop_name' && field !== 'start_time' && field !== 'stop_time';
    const parsed = isNum ? parseFloat(val) : val;

    setRecipes(prev => {
      const curCrop = prev[activeCrop] || defaultRecipes[activeCrop] || {};
      const curZones = { ...(curCrop.zones || {}) };
      const curZoneObj = { ...(curZones[deliveryZone] || curCrop), [field]: parsed };

      curZones[deliveryZone] = curZoneObj;

      const updatedCrop = {
        ...curCrop,
        [field]: parsed,
        zones: curZones
      };

      return {
        ...prev,
        [activeCrop]: updatedCrop
      };
    });
  };

  const handleZoneTimerChange = (zoneKey, field, val) => {
    const isNum = !isNaN(parseFloat(val)) && field !== 'name' && field !== 'start_time' && field !== 'stop_time';
    const parsed = isNum ? parseFloat(val) : val;
    setCyclicTimers(prev => ({
      ...prev,
      [zoneKey]: {
        ...prev[zoneKey],
        [field]: parsed
      }
    }));
  };

  // 4. Save Setpoints & Sync
  const handleSave = async () => {
    if (!deviceRoot) return;
    setSaveStatus('saving');
    setStatusMessage('Saving crop setpoints & timers...');

    const payload = {
      crop_recipes: recipes,
      cyclic_timers: cyclicTimers,
      active_crop: activeCrop,
      delivery_zone: deliveryZone,
      crop: activeCrop,
      crop_name: zoneRecipe.crop_name || activeCrop,
      ec_min: zoneRecipe.ec_min,
      ec_max: zoneRecipe.ec_max,
      ph_min: zoneRecipe.ph_min,
      ph_target: zoneRecipe.ph_target,
      ph_max: zoneRecipe.ph_max,
      start_time: zoneRecipe.start_time || '06:00',
      stop_time: zoneRecipe.stop_time || '18:00',
      on_min: zoneRecipe.on_min || 5.0,
      off_min: zoneRecipe.off_min || 60.0
    };

    let publishedDirect = false;
    if (mqttClientRef.current && mqttClientRef.current.connected) {
      try {
        mqttClientRef.current.publish(`inhydro/${deviceRoot}/setpoints/set`, JSON.stringify(payload), { retain: true });
        mqttClientRef.current.publish(`inhydro/${deviceRoot}/setpoints/update`, JSON.stringify(payload), { retain: true });
        publishedDirect = true;
      } catch (e) {
        console.warn('Direct WebSocket MQTT publish error:', e);
      }
    }

    try {
      const devId = selectedDevice?._id || deviceRoot;
      const res = await fetch(`${API_BASE}/api/devices/${devId}/push-config`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.success || publishedDirect) {
        setSaveStatus('saved');
        setStatusMessage('Crop Setpoints & Cyclic Timer saved successfully!');
        setTimeout(() => setSaveStatus('idle'), 3500);
      } else {
        setSaveStatus('error');
        setStatusMessage(`Failed to save: ${data.message || 'Error'}`);
      }
    } catch (err) {
      if (publishedDirect) {
        setSaveStatus('saved');
        setStatusMessage('Setpoints saved via direct MQTT.');
        setTimeout(() => setSaveStatus('idle'), 3500);
      } else {
        setSaveStatus('error');
        setStatusMessage(`Network error: ${err.message}`);
      }
    }
  };

  const handleSyncRequest = async () => {
    setStatusMessage('Syncing setpoints from machine...');
    if (mqttClientRef.current && mqttClientRef.current.connected) {
      mqttClientRef.current.publish(`inhydro/${deviceRoot}/setpoints/request_sync`, '1');
    }
    sendCommand('request_sync');
  };

  // Navigation handlers
  const handlePrevTab = () => {
    const curIdx = PAGE_SEQUENCE.indexOf(activeTab);
    const prevIdx = (curIdx - 1 + PAGE_SEQUENCE.length) % PAGE_SEQUENCE.length;
    setActiveTab(PAGE_SEQUENCE[prevIdx]);
  };

  const handleNextTab = () => {
    const curIdx = PAGE_SEQUENCE.indexOf(activeTab);
    const nextIdx = (curIdx + 1) % PAGE_SEQUENCE.length;
    setActiveTab(PAGE_SEQUENCE[nextIdx]);
  };

  // Safe telemetry extracts
  const liveEc = liveData?.ec != null ? Number(liveData.ec).toFixed(2) : '--';
  const livePh = liveData?.ph != null ? Number(liveData.ph).toFixed(2) : '--';
  const liveTemp = liveData?.water_temp != null ? Number(liveData.water_temp).toFixed(1) : '--';
  const fertPhase = liveData?.fertigation?.phase || (liveData?.is_running ? 'RUNNING' : 'IDLE / READY');
  const fertRunning = Boolean(liveData?.fertigation?.is_running);
  const relayMap = liveData?.relays || {};

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-3 sm:p-5 md:p-6 lg:p-8">
      {/* ── TOP HEADER BAR ── */}
      <div className="max-w-6xl mx-auto mb-5 sm:mb-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
          <div>
            <div className="flex items-center gap-3">
              <span className="p-2.5 rounded-xl bg-green-500/10 border border-green-500/20 text-[#60bf71]">
                <FlaskConical className="w-5 h-5" />
              </span>
              <div>
                <h1 className="text-lg sm:text-xl md:text-2xl font-bold tracking-tight text-white uppercase">
                  InHydro Fertigation &amp; Cyclic Irrigation System
                </h1>
                <p className="text-xs text-slate-400">
                  Precision EC &amp; pH Dosing, Dual-Zone Cyclic Irrigation &amp; 13-Actuator Hardware Control
                </p>
              </div>
            </div>
          </div>

          {/* Device Selector & Live Status Indicator */}
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="relative">
              <button
                type="button"
                onClick={() => setIsDeviceDropdownOpen(!isDeviceDropdownOpen)}
                className="flex items-center gap-2 rounded-xl border border-slate-700/80 bg-slate-800/90 px-3.5 py-2 text-xs font-semibold text-white hover:border-green-500/50 hover:bg-slate-750 focus:outline-none transition-all shadow-sm"
              >
                <Server className="w-3.5 h-3.5 text-[#60bf71]" />
                <span className="max-w-[140px] truncate">{selectedDevice?.name || deviceRoot || 'Select Controller'}</span>
                <ChevronDown className="w-3.5 h-3.5 text-slate-400 ml-0.5" />
              </button>

              {isDeviceDropdownOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setIsDeviceDropdownOpen(false)}></div>
                  <div className="absolute right-0 mt-2 w-64 rounded-xl border border-slate-700 bg-slate-800 py-1.5 shadow-2xl z-50">
                    <div className="px-3 py-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      Fertigation Controllers
                    </div>
                    {devices.map((d) => (
                      <button
                        key={d._id}
                        type="button"
                        onClick={() => {
                          setDeviceRoot(d.mqttId || d._id);
                          setIsDeviceDropdownOpen(false);
                        }}
                        className={`w-full px-3 py-2 text-left text-xs flex items-center justify-between hover:bg-slate-700/60 ${
                          (d.mqttId || d._id) === deviceRoot ? 'bg-green-500/15 text-[#60bf71] font-semibold' : 'text-slate-300'
                        }`}
                      >
                        <span className="truncate">{d.name}</span>
                        <span className="text-[10px] text-slate-500 ml-2 font-mono">{d.mqttId || 'ID'}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>

            <div className="flex items-center gap-2 rounded-xl border border-slate-700/80 bg-slate-800/90 px-3 py-2 shadow-sm">
              <span className={`w-2.5 h-2.5 rounded-full ${machineOnline ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
              <span className="text-xs font-semibold text-slate-300">
                {machineOnline ? 'Online' : 'Offline'}
              </span>
            </div>

            <button
              onClick={handleSyncRequest}
              title="Sync Setpoints from Machine"
              className="p-2 rounded-xl border border-slate-700/80 bg-slate-800/90 text-slate-300 hover:text-[#60bf71] hover:border-green-500/40 hover:bg-slate-750 transition shadow-sm"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Global Notification Banner */}
        {statusMessage && (
          <div className="mt-3 px-4 py-2.5 rounded-xl bg-green-500/10 border border-green-500/30 text-[#60bf71] text-xs font-medium flex items-center justify-between shadow-sm">
            <span>{statusMessage}</span>
            <span className="text-[10px] text-slate-400 font-mono">MQTT 147.93.106.142</span>
          </div>
        )}
      </div>

      {/* ── TOP MODULE TABS (Matching 4 Controller Pages) ── */}
      <div className="max-w-6xl mx-auto mb-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 p-1.5 rounded-2xl border border-slate-800 bg-slate-850/80 backdrop-blur">
          <button
            type="button"
            onClick={() => setActiveTab('settings')}
            className={`flex items-center justify-center gap-2 px-3 sm:px-4 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all ${
              activeTab === 'settings'
                ? 'bg-green-600 text-white shadow-md shadow-green-900/30 ring-1 ring-green-400/30'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/80'
            }`}
          >
            <Sliders className="w-4 h-4" />
            <span className="truncate">Crop Settings &amp; Timers</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('monitoring')}
            className={`flex items-center justify-center gap-2 px-3 sm:px-4 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all ${
              activeTab === 'monitoring'
                ? 'bg-green-600 text-white shadow-md shadow-green-900/30 ring-1 ring-green-400/30'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/80'
            }`}
          >
            <Activity className="w-4 h-4" />
            <span className="truncate">Live Monitoring</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('fertigation')}
            className={`flex items-center justify-center gap-2 px-3 sm:px-4 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all ${
              activeTab === 'fertigation'
                ? 'bg-green-600 text-white shadow-md shadow-green-900/30 ring-1 ring-green-400/30'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/80'
            }`}
          >
            <Droplets className="w-4 h-4" />
            <span className="truncate">Fertigation Engine</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('irrigation')}
            className={`flex items-center justify-center gap-2 px-3 sm:px-4 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all ${
              activeTab === 'irrigation'
                ? 'bg-green-600 text-white shadow-md shadow-green-900/30 ring-1 ring-green-400/30'
                : 'text-slate-400 hover:text-white hover:bg-slate-800/80'
            }`}
          >
            <Clock className="w-4 h-4" />
            <span className="truncate">Field Irrigation (2 Zones)</span>
          </button>
        </div>
      </div>

      {/* ── TAB 1: CROP SETTINGS & TIMERS (EXACT MATCH OF USER'S PHOTO / SCREEN 5) ── */}
      {activeTab === 'settings' && (
        <div className="max-w-6xl mx-auto space-y-6">
          {/* Top Selector Bar: Select Crop & Target Zone / Room */}
          <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-4 shadow-sm">
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-center gap-4 sm:gap-8 text-sm">
              <div className="flex items-center justify-between sm:justify-start gap-3">
                <span className="font-bold text-[#60bf71]">Select Crop:</span>
                <select
                  value={activeCrop}
                  onChange={(e) => setActiveCrop(e.target.value)}
                  className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-sm font-semibold text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 cursor-pointer shadow-inner"
                >
                  {Object.keys(recipes).map((k) => (
                    <option key={k} value={k}>
                      {recipes[k].crop_name || k.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center justify-between sm:justify-start gap-3">
                <span className="font-bold text-[#60bf71]">Target Zone / Room:</span>
                <select
                  value={deliveryZone}
                  onChange={(e) => setDeliveryZone(e.target.value)}
                  className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-sm font-semibold text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 cursor-pointer shadow-inner"
                >
                  <option value="both">Both Zones (Common)</option>
                  <option value="zone_1">Zone 1 (Room 1)</option>
                  <option value="zone_2">Zone 2 (Room 2)</option>
                </select>
              </div>
            </div>
          </div>

          {/* Card 1: CROP NUTRIENT TARGET SETPOINTS (EC & pH) */}
          <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-4 sm:p-5 shadow-lg">
            <div className="flex items-center justify-between mb-4 pb-2.5 border-b border-slate-700/80">
              <h2 className="text-xs sm:text-sm md:text-base font-bold text-[#60bf71] tracking-wide uppercase flex items-center gap-2">
                <Sliders className="w-4 h-4 text-green-400" />
                <span>Crop Nutrient Target Setpoints (EC &amp; pH)</span>
              </h2>
              <span className="text-xs text-slate-400 font-medium hidden sm:inline-block">
                Active Zone: <span className="text-[#60bf71] font-bold">{deliveryZone.toUpperCase()}</span>
              </span>
            </div>

            {/* Fully Responsive 3 Equal Columns Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
              {/* Row 1, Col 1: Crop Name */}
              <div className="rounded-xl border border-slate-700/70 bg-slate-900/60 p-3.5 flex items-center justify-between gap-2 shadow-sm hover:border-slate-600 transition">
                <div className="flex-1">
                  <div className="text-xs font-semibold text-slate-400">Crop Name:</div>
                  <input
                    type="text"
                    value={zoneRecipe.crop_name || ''}
                    onChange={(e) => handleRecipeFieldChange('crop_name', e.target.value)}
                    className="mt-1 w-full max-w-[130px] rounded-lg border border-slate-700 bg-slate-800/90 px-3 py-1 text-sm font-bold text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                  />
                </div>
                <span className="px-3 py-1 rounded-lg bg-green-500/15 border border-green-500/30 text-[#60bf71] text-xs font-bold tracking-wide select-none">
                  EDIT
                </span>
              </div>

              {/* Row 1, Col 2: EC Min (Start) */}
              <div className="rounded-xl border border-slate-700/70 bg-slate-900/60 p-3.5 flex items-center justify-between gap-2 shadow-sm hover:border-slate-600 transition">
                <div className="flex-1">
                  <div className="text-xs font-semibold text-slate-400">EC Min (Start):</div>
                  <div className="flex items-center gap-1.5 mt-1">
                    <input
                      type="number"
                      step="0.05"
                      value={zoneRecipe.ec_min ?? 1.80}
                      onChange={(e) => handleRecipeFieldChange('ec_min', e.target.value)}
                      className="w-24 rounded-lg border border-slate-700 bg-slate-800/90 px-3 py-1 text-sm font-bold text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                    />
                    <span className="text-[11px] text-slate-500 font-medium">mS/cm</span>
                  </div>
                </div>
                <span className="px-3 py-1 rounded-lg bg-green-500/15 border border-green-500/30 text-[#60bf71] text-xs font-bold tracking-wide select-none">
                  EDIT
                </span>
              </div>

              {/* Row 1, Col 3: EC Max (Stop) */}
              <div className="rounded-xl border border-slate-700/70 bg-slate-900/60 p-3.5 flex items-center justify-between gap-2 shadow-sm hover:border-slate-600 transition">
                <div className="flex-1">
                  <div className="text-xs font-semibold text-slate-400">EC Max (Stop):</div>
                  <div className="flex items-center gap-1.5 mt-1">
                    <input
                      type="number"
                      step="0.05"
                      value={zoneRecipe.ec_max ?? 2.20}
                      onChange={(e) => handleRecipeFieldChange('ec_max', e.target.value)}
                      className="w-24 rounded-lg border border-slate-700 bg-slate-800/90 px-3 py-1 text-sm font-bold text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                    />
                    <span className="text-[11px] text-slate-500 font-medium">mS/cm</span>
                  </div>
                </div>
                <span className="px-3 py-1 rounded-lg bg-green-500/15 border border-green-500/30 text-[#60bf71] text-xs font-bold tracking-wide select-none">
                  EDIT
                </span>
              </div>

              {/* Row 2, Col 1: pH Min (Up) */}
              <div className="rounded-xl border border-slate-700/70 bg-slate-900/60 p-3.5 flex items-center justify-between gap-2 shadow-sm hover:border-slate-600 transition">
                <div className="flex-1">
                  <div className="text-xs font-semibold text-slate-400">pH Min (Up):</div>
                  <input
                    type="number"
                    step="0.05"
                    value={zoneRecipe.ph_min ?? 5.40}
                    onChange={(e) => handleRecipeFieldChange('ph_min', e.target.value)}
                    className="mt-1 w-24 rounded-lg border border-slate-700 bg-slate-800/90 px-3 py-1 text-sm font-bold text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                  />
                </div>
                <span className="px-3 py-1 rounded-lg bg-green-500/15 border border-green-500/30 text-[#60bf71] text-xs font-bold tracking-wide select-none">
                  EDIT
                </span>
              </div>

              {/* Row 2, Col 2: pH Target */}
              <div className="rounded-xl border border-slate-700/70 bg-slate-900/60 p-3.5 flex items-center justify-between gap-2 shadow-sm hover:border-slate-600 transition">
                <div className="flex-1">
                  <div className="text-xs font-semibold text-slate-400">pH Target:</div>
                  <input
                    type="number"
                    step="0.05"
                    value={zoneRecipe.ph_target ?? 5.80}
                    onChange={(e) => handleRecipeFieldChange('ph_target', e.target.value)}
                    className="mt-1 w-24 rounded-lg border border-slate-700 bg-slate-800/90 px-3 py-1 text-sm font-bold text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                  />
                </div>
                <span className="px-3 py-1 rounded-lg bg-green-500/15 border border-green-500/30 text-[#60bf71] text-xs font-bold tracking-wide select-none">
                  EDIT
                </span>
              </div>

              {/* Row 2, Col 3: pH Max (Down) - In high-contrast Red */}
              <div className="rounded-xl border border-red-500/40 bg-slate-900/60 p-3.5 flex items-center justify-between gap-2 shadow-sm hover:border-red-500/60 transition">
                <div className="flex-1">
                  <div className="text-xs font-semibold text-red-400">pH Max (Down):</div>
                  <input
                    type="number"
                    step="0.05"
                    value={zoneRecipe.ph_max ?? 6.40}
                    onChange={(e) => handleRecipeFieldChange('ph_max', e.target.value)}
                    className="mt-1 w-24 rounded-lg border border-red-500/50 bg-slate-800/90 px-3 py-1 text-sm font-bold text-red-400 outline-none focus:border-red-500 focus:ring-1 focus:ring-red-500"
                  />
                </div>
                <span className="px-3 py-1 rounded-lg bg-red-600/20 border border-red-500/40 text-red-300 text-xs font-bold tracking-wide select-none">
                  EDIT
                </span>
              </div>
            </div>
          </div>

          {/* Card 2: CYCLIC FERTIGATION TIMER CONFIGURATION */}
          <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-4 sm:p-5 shadow-lg">
            <div className="flex items-center justify-between mb-4 pb-2.5 border-b border-slate-700/80">
              <h2 className="text-xs sm:text-sm md:text-base font-bold text-[#60bf71] tracking-wide uppercase flex items-center gap-2">
                <Clock className="w-4 h-4 text-green-400" />
                <span>Cyclic Fertigation Timer Configuration</span>
              </h2>
              <span className="text-xs text-slate-400 font-medium hidden sm:inline-block">
                Crop Scheduled Window
              </span>
            </div>

            {/* Fully Responsive 2 Equal Columns Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              {/* Row 1, Col 1: Window Start Time */}
              <div className="rounded-xl border border-slate-700/70 bg-slate-900/60 p-3.5 flex items-center justify-between gap-2 shadow-sm hover:border-slate-600 transition">
                <div className="flex-1">
                  <div className="text-xs font-semibold text-slate-400">Window Start Time:</div>
                  <input
                    type="time"
                    value={zoneRecipe.start_time || '06:00'}
                    onChange={(e) => handleRecipeFieldChange('start_time', e.target.value)}
                    className="mt-1 rounded-lg border border-slate-700 bg-slate-800/90 px-3 py-1 text-sm font-bold text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                  />
                </div>
                <span className="px-3 py-1 rounded-lg bg-green-500/15 border border-green-500/30 text-[#60bf71] text-xs font-bold tracking-wide select-none">
                  EDIT
                </span>
              </div>

              {/* Row 1, Col 2: Window Stop Time */}
              <div className="rounded-xl border border-slate-700/70 bg-slate-900/60 p-3.5 flex items-center justify-between gap-2 shadow-sm hover:border-slate-600 transition">
                <div className="flex-1">
                  <div className="text-xs font-semibold text-slate-400">Window Stop Time:</div>
                  <input
                    type="time"
                    value={zoneRecipe.stop_time || '18:00'}
                    onChange={(e) => handleRecipeFieldChange('stop_time', e.target.value)}
                    className="mt-1 rounded-lg border border-slate-700 bg-slate-800/90 px-3 py-1 text-sm font-bold text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                  />
                </div>
                <span className="px-3 py-1 rounded-lg bg-green-500/15 border border-green-500/30 text-[#60bf71] text-xs font-bold tracking-wide select-none">
                  EDIT
                </span>
              </div>

              {/* Row 2, Col 1: Delivery ON (min) */}
              <div className="rounded-xl border border-slate-700/70 bg-slate-900/60 p-3.5 flex items-center justify-between gap-2 shadow-sm hover:border-slate-600 transition">
                <div className="flex-1">
                  <div className="text-xs font-semibold text-slate-400">Delivery ON (min):</div>
                  <div className="flex items-center gap-1.5 mt-1">
                    <input
                      type="number"
                      step="0.5"
                      value={zoneRecipe.on_min ?? 5.0}
                      onChange={(e) => handleRecipeFieldChange('on_min', e.target.value)}
                      className="w-24 rounded-lg border border-slate-700 bg-slate-800/90 px-3 py-1 text-sm font-bold text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                    />
                    <span className="text-[11px] text-slate-500 font-medium">minutes</span>
                  </div>
                </div>
                <span className="px-3 py-1 rounded-lg bg-green-500/15 border border-green-500/30 text-[#60bf71] text-xs font-bold tracking-wide select-none">
                  EDIT
                </span>
              </div>

              {/* Row 2, Col 2: Interval OFF (min) */}
              <div className="rounded-xl border border-slate-700/70 bg-slate-900/60 p-3.5 flex items-center justify-between gap-2 shadow-sm hover:border-slate-600 transition">
                <div className="flex-1">
                  <div className="text-xs font-semibold text-slate-400">Interval OFF (min):</div>
                  <div className="flex items-center gap-1.5 mt-1">
                    <input
                      type="number"
                      step="1"
                      value={zoneRecipe.off_min ?? 60.0}
                      onChange={(e) => handleRecipeFieldChange('off_min', e.target.value)}
                      className="w-24 rounded-lg border border-slate-700 bg-slate-800/90 px-3 py-1 text-sm font-bold text-white outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500"
                    />
                    <span className="text-[11px] text-slate-500 font-medium">minutes</span>
                  </div>
                </div>
                <span className="px-3 py-1 rounded-lg bg-green-500/15 border border-green-500/30 text-[#60bf71] text-xs font-bold tracking-wide select-none">
                  EDIT
                </span>
              </div>
            </div>
          </div>

          {/* Action Button: Save Crop Setpoints & Cyclic Timer */}
          <div className="flex justify-center pt-2">
            <button
              type="button"
              onClick={handleSave}
              disabled={saveStatus === 'saving'}
              className="flex items-center justify-center gap-2.5 rounded-xl bg-green-600 hover:bg-green-500 text-white font-bold text-sm sm:text-base px-8 py-3.5 shadow-xl shadow-green-950/40 transition active:scale-95 disabled:opacity-50"
            >
              <Save className="w-5 h-5" />
              <span>
                {saveStatus === 'saving'
                  ? 'Saving Setpoints...'
                  : saveStatus === 'saved'
                  ? 'Saved Successfully!'
                  : ' Save Crop Setpoints & Cyclic Timer'}
              </span>
            </button>
          </div>
        </div>
      )}

      {/* ── TAB 2: LIVE MONITORING (SCREEN 2) ── */}
      {activeTab === 'monitoring' && (
        <div className="max-w-6xl mx-auto space-y-6">
          {/* Top 3 Live Sensory Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
            {/* EC Card */}
            <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-5 text-center shadow-lg hover:border-green-500/30 transition">
              <div className="text-xs font-bold text-[#60bf71] uppercase tracking-wider mb-1">
                EC Value (mS/cm)
              </div>
              <div className="text-3xl md:text-4xl font-extrabold text-white tracking-tight my-2">
                {liveEc}
              </div>
              <div className="text-xs text-slate-400 font-medium">
                Target: {zoneRecipe.ec_max?.toFixed(2)} mS/cm
              </div>
            </div>

            {/* pH Card */}
            <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-5 text-center shadow-lg hover:border-green-500/30 transition">
              <div className="text-xs font-bold text-[#60bf71] uppercase tracking-wider mb-1">
                pH Value
              </div>
              <div className="text-3xl md:text-4xl font-extrabold text-white tracking-tight my-2">
                {livePh}
              </div>
              <div className="text-xs text-slate-400 font-medium">
                Target: {zoneRecipe.ph_target?.toFixed(2)}
              </div>
            </div>

            {/* Water Temp Card */}
            <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-5 text-center shadow-lg hover:border-green-500/30 transition">
              <div className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-1">
                Water Temperature
              </div>
              <div className="text-3xl md:text-4xl font-extrabold text-white tracking-tight my-2">
                {liveTemp !== '--' ? `${liveTemp} °C` : '--'}
              </div>
              <div className="text-xs text-slate-400 font-medium">
                Solution Manifold
              </div>
            </div>
          </div>

          {/* Phase Badge & Automation Log */}
          <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-4 sm:p-5 flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4 shadow-sm">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-slate-900 border border-slate-700 text-[#60bf71]">
                <Activity className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                  Automation Status
                </div>
                <div className="text-sm font-bold text-white flex items-center gap-2 mt-0.5">
                  <span className={`w-2.5 h-2.5 rounded-full ${fertRunning ? 'bg-green-400 animate-ping' : 'bg-slate-400'}`} />
                  PHASE: {fertPhase}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2.5">
              <button
                type="button"
                onClick={() => sendCommand('start_fertigation', { crop: activeCrop, delivery_target: deliveryZone })}
                className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-green-600 hover:bg-green-500 text-white font-bold text-xs uppercase shadow-sm transition active:scale-95"
              >
                <Play className="w-3.5 h-3.5" />
                <span>Start Fertigation</span>
              </button>
              <button
                type="button"
                onClick={() => sendCommand('stop_fertigation')}
                className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-red-600/90 hover:bg-red-500 text-white font-bold text-xs uppercase shadow-sm transition active:scale-95"
              >
                <Square className="w-3.5 h-3.5" />
                <span>Abort / Stop</span>
              </button>
            </div>
          </div>

          {/* 13 Actuator Modbus Relay Status Badges */}
          <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-4 sm:p-5 shadow-lg">
            <h3 className="text-xs font-bold text-[#60bf71] uppercase tracking-wider mb-4 pb-2.5 border-b border-slate-700/80">
              13-Channel Modbus Actuator Relay States
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2.5">
              {Object.entries(ACTUATOR_NAMES).map(([chNum, meta]) => {
                const isActive = Boolean(relayMap[`ch_${chNum}`]);
                return (
                  <div
                    key={chNum}
                    className={`rounded-xl border p-3 flex flex-col justify-between transition-all ${
                      isActive
                        ? 'border-green-500/80 bg-green-500/10 text-white shadow-sm ring-1 ring-green-500/20'
                        : 'border-slate-800 bg-slate-900/60 text-slate-400'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-mono font-bold text-slate-400">CH {chNum}</span>
                      <span
                        className={`px-2 py-0.5 rounded-md text-[10px] font-extrabold ${
                          isActive ? 'bg-green-600 text-white' : 'bg-slate-800 text-slate-400'
                        }`}
                      >
                        {isActive ? 'ON' : 'OFF'}
                      </span>
                    </div>
                    <div className="mt-2.5 text-xs font-bold truncate text-slate-200" title={meta.name}>
                      {meta.name}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ── TAB 3: FERTIGATION ENGINE (SCREEN 3) ── */}
      {activeTab === 'fertigation' && (
        <div className="max-w-6xl mx-auto space-y-6">
          {/* Active Target Header Card */}
          <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-4 sm:p-5 shadow-sm">
            <div className="flex items-center justify-between mb-4 pb-2.5 border-b border-slate-700/80">
              <h3 className="text-xs sm:text-sm font-bold text-[#60bf71] uppercase tracking-wider">
                Active Crop Nutrient &amp; Multi-Injector Setpoints
              </h3>
              <span className="text-xs text-[#60bf71] font-bold">
                {zoneRecipe.crop_name} ({deliveryZone.toUpperCase()})
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2.5 text-center">
              <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
                <div className="text-[10px] text-slate-400 font-bold uppercase">Crop</div>
                <div className="text-xs font-bold text-white mt-1 truncate">{zoneRecipe.crop_name}</div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
                <div className="text-[10px] text-slate-400 font-bold uppercase">EC Min (Start)</div>
                <div className="text-xs font-bold text-white mt-1">{zoneRecipe.ec_min}</div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
                <div className="text-[10px] text-slate-400 font-bold uppercase">EC Max (Stop)</div>
                <div className="text-xs font-bold text-white mt-1">{zoneRecipe.ec_max}</div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
                <div className="text-[10px] text-slate-400 font-bold uppercase">pH Min (Up)</div>
                <div className="text-xs font-bold text-white mt-1">{zoneRecipe.ph_min}</div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
                <div className="text-[10px] text-slate-400 font-bold uppercase">pH Target</div>
                <div className="text-xs font-bold text-white mt-1">{zoneRecipe.ph_target}</div>
              </div>
              <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
                <div className="text-[10px] text-red-400 font-bold uppercase">pH Max (Down)</div>
                <div className="text-xs font-bold text-red-400 mt-1">{zoneRecipe.ph_max}</div>
              </div>
            </div>
          </div>

          {/* 4-Venturi Solution Dosing Engine Table */}
          <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-4 sm:p-5 shadow-lg">
            <h3 className="text-xs sm:text-sm font-bold text-[#60bf71] uppercase tracking-wider mb-4 pb-2.5 border-b border-slate-700/80">
              4-Venturi Solution Dosing Engine Logic
            </h3>

            <div className="overflow-x-auto rounded-xl border border-slate-700/50">
              <table className="w-full text-left text-xs min-w-[500px]">
                <thead className="bg-slate-900/80">
                  <tr className="border-b border-slate-700 text-slate-400">
                    <th className="p-3 font-semibold uppercase">Venturi Channel</th>
                    <th className="p-3 font-semibold uppercase">Hardware Mapping</th>
                    <th className="p-3 font-semibold uppercase">Dosing Trigger</th>
                    <th className="p-3 font-semibold uppercase">Target Cutoff</th>
                    <th className="p-3 font-semibold uppercase text-right">Relay Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 font-medium">
                  {/* EC 1 */}
                  <tr className="hover:bg-slate-800/30 transition">
                    <td className="p-3 font-bold text-white">EC 1 (Stock A)</td>
                    <td className="p-3 text-slate-400 font-mono">Relay 1 (S.V 1)</td>
                    <td className="p-3 text-[#60bf71] font-mono">EC &le; {zoneRecipe.ec_min}</td>
                    <td className="p-3 text-emerald-400 font-mono">EC &ge; {zoneRecipe.ec_max}</td>
                    <td className="p-3 text-right">
                      <span className={`px-2.5 py-1 rounded-md text-[11px] font-bold ${relayMap.ch_1 ? 'bg-green-600 text-white' : 'bg-slate-800 text-slate-400'}`}>
                        {relayMap.ch_1 ? 'DOSING' : 'OFF'}
                      </span>
                    </td>
                  </tr>

                  {/* EC 2 */}
                  <tr className="hover:bg-slate-800/30 transition">
                    <td className="p-3 font-bold text-white">EC 2 (Stock B)</td>
                    <td className="p-3 text-slate-400 font-mono">Relay 2 (S.V 2)</td>
                    <td className="p-3 text-[#60bf71] font-mono">EC &le; {zoneRecipe.ec_min}</td>
                    <td className="p-3 text-emerald-400 font-mono">EC &ge; {zoneRecipe.ec_max}</td>
                    <td className="p-3 text-right">
                      <span className={`px-2.5 py-1 rounded-md text-[11px] font-bold ${relayMap.ch_2 ? 'bg-green-600 text-white' : 'bg-slate-800 text-slate-400'}`}>
                        {relayMap.ch_2 ? 'DOSING' : 'OFF'}
                      </span>
                    </td>
                  </tr>

                  {/* pH Down */}
                  <tr className="hover:bg-slate-800/30 transition">
                    <td className="p-3 font-bold text-white">pH Down (Acid)</td>
                    <td className="p-3 text-slate-400 font-mono">Relay 3 (S.V 3)</td>
                    <td className="p-3 text-red-400 font-mono">pH &ge; {zoneRecipe.ph_max}</td>
                    <td className="p-3 text-emerald-400 font-mono">pH &le; {zoneRecipe.ph_target}</td>
                    <td className="p-3 text-right">
                      <span className={`px-2.5 py-1 rounded-md text-[11px] font-bold ${relayMap.ch_3 ? 'bg-red-500 text-white' : 'bg-slate-800 text-slate-400'}`}>
                        {relayMap.ch_3 ? 'DOSING' : 'OFF'}
                      </span>
                    </td>
                  </tr>

                  {/* pH Up */}
                  <tr className="hover:bg-slate-800/30 transition">
                    <td className="p-3 font-bold text-white">pH Up (Base)</td>
                    <td className="p-3 text-slate-400 font-mono">Relay 4 (S.V 4)</td>
                    <td className="p-3 text-[#60bf71] font-mono">pH &le; {zoneRecipe.ph_min}</td>
                    <td className="p-3 text-emerald-400 font-mono">pH &ge; {zoneRecipe.ph_target}</td>
                    <td className="p-3 text-right">
                      <span className={`px-2.5 py-1 rounded-md text-[11px] font-bold ${relayMap.ch_4 ? 'bg-green-600 text-white' : 'bg-slate-800 text-slate-400'}`}>
                        {relayMap.ch_4 ? 'DOSING' : 'OFF'}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── TAB 4: FIELD CYCLIC IRRIGATION (SCREEN 4) ── */}
      {activeTab === 'irrigation' && (
        <div className="max-w-6xl mx-auto space-y-6">
          <div className="rounded-2xl border border-slate-700/60 bg-slate-800/40 p-4 sm:p-5 shadow-lg">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 pb-2.5 border-b border-slate-700/80">
              <h2 className="text-xs sm:text-sm md:text-base font-bold text-[#60bf71] tracking-wide uppercase flex items-center gap-2">
                <Clock className="w-4 h-4 text-green-400" />
                <span>Field Irrigation Cyclic Timers (2 Independent Zones)</span>
              </h2>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => sendCommand('stop_all_irrigation')}
                  className="px-3.5 py-1.5 rounded-xl bg-red-600/90 hover:bg-red-500 text-white text-xs font-bold transition shadow-sm"
                >
                  ⏹ Stop All Irrigation
                </button>
              </div>
            </div>

            {/* 2-Zone Comparison Table */}
            <div className="overflow-x-auto rounded-xl border border-slate-700/50">
              <table className="w-full text-left text-xs min-w-[500px]">
                <thead className="bg-slate-900/80">
                  <tr className="border-b border-slate-700 text-slate-400">
                    <th className="p-3 font-semibold uppercase">Setting Parameter</th>
                    <th className="p-3 font-semibold uppercase text-[#60bf71]">Zone 1 (S.V 12)</th>
                    <th className="p-3 font-semibold uppercase text-emerald-300">Zone 2 (S.V 13)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 font-medium">
                  {/* Timer Line Name */}
                  <tr className="hover:bg-slate-800/30 transition">
                    <td className="p-3 text-slate-300">Timer Line Name</td>
                    <td className="p-3">
                      <input
                        type="text"
                        value={cyclicTimers.zone_1?.name || ''}
                        onChange={(e) => handleZoneTimerChange('zone_1', 'name', e.target.value)}
                        className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-white outline-none focus:border-green-500"
                      />
                    </td>
                    <td className="p-3">
                      <input
                        type="text"
                        value={cyclicTimers.zone_2?.name || ''}
                        onChange={(e) => handleZoneTimerChange('zone_2', 'name', e.target.value)}
                        className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-white outline-none focus:border-green-500"
                      />
                    </td>
                  </tr>

                  {/* Automation Status */}
                  <tr className="hover:bg-slate-800/30 transition">
                    <td className="p-3 text-slate-300">Timer Automation</td>
                    <td className="p-3">
                      <button
                        type="button"
                        onClick={() => handleZoneTimerChange('zone_1', 'enabled', !cyclicTimers.zone_1?.enabled)}
                        className={`px-3 py-1 rounded-lg text-xs font-bold transition shadow-sm ${
                          cyclicTimers.zone_1?.enabled ? 'bg-green-600 text-white' : 'bg-red-500/20 text-red-400 border border-red-500/30'
                        }`}
                      >
                        {cyclicTimers.zone_1?.enabled ? 'ENABLED' : 'DISABLED'}
                      </button>
                    </td>
                    <td className="p-3">
                      <button
                        type="button"
                        onClick={() => handleZoneTimerChange('zone_2', 'enabled', !cyclicTimers.zone_2?.enabled)}
                        className={`px-3 py-1 rounded-lg text-xs font-bold transition shadow-sm ${
                          cyclicTimers.zone_2?.enabled ? 'bg-green-600 text-white' : 'bg-red-500/20 text-red-400 border border-red-500/30'
                        }`}
                      >
                        {cyclicTimers.zone_2?.enabled ? 'ENABLED' : 'DISABLED'}
                      </button>
                    </td>
                  </tr>

                  {/* Start Window */}
                  <tr className="hover:bg-slate-800/30 transition">
                    <td className="p-3 text-slate-300">Start Window Time</td>
                    <td className="p-3">
                      <input
                        type="time"
                        value={cyclicTimers.zone_1?.start_time || '06:00'}
                        onChange={(e) => handleZoneTimerChange('zone_1', 'start_time', e.target.value)}
                        className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-white font-bold outline-none focus:border-green-500"
                      />
                    </td>
                    <td className="p-3">
                      <input
                        type="time"
                        value={cyclicTimers.zone_2?.start_time || '06:00'}
                        onChange={(e) => handleZoneTimerChange('zone_2', 'start_time', e.target.value)}
                        className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-white font-bold outline-none focus:border-green-500"
                      />
                    </td>
                  </tr>

                  {/* Stop Window */}
                  <tr className="hover:bg-slate-800/30 transition">
                    <td className="p-3 text-slate-300">Stop Window Time</td>
                    <td className="p-3">
                      <input
                        type="time"
                        value={cyclicTimers.zone_1?.stop_time || '18:00'}
                        onChange={(e) => handleZoneTimerChange('zone_1', 'stop_time', e.target.value)}
                        className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-white font-bold outline-none focus:border-green-500"
                      />
                    </td>
                    <td className="p-3">
                      <input
                        type="time"
                        value={cyclicTimers.zone_2?.stop_time || '18:00'}
                        onChange={(e) => handleZoneTimerChange('zone_2', 'stop_time', e.target.value)}
                        className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-white font-bold outline-none focus:border-green-500"
                      />
                    </td>
                  </tr>

                  {/* ON Duration */}
                  <tr className="hover:bg-slate-800/30 transition">
                    <td className="p-3 text-slate-300">ON Duration (Min)</td>
                    <td className="p-3">
                      <input
                        type="number"
                        step="0.5"
                        value={cyclicTimers.zone_1?.on_min ?? 5.0}
                        onChange={(e) => handleZoneTimerChange('zone_1', 'on_min', e.target.value)}
                        className="w-20 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white font-bold outline-none focus:border-green-500"
                      />
                    </td>
                    <td className="p-3">
                      <input
                        type="number"
                        step="0.5"
                        value={cyclicTimers.zone_2?.on_min ?? 5.0}
                        onChange={(e) => handleZoneTimerChange('zone_2', 'on_min', e.target.value)}
                        className="w-20 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white font-bold outline-none focus:border-green-500"
                      />
                    </td>
                  </tr>

                  {/* OFF Interval */}
                  <tr className="hover:bg-slate-800/30 transition">
                    <td className="p-3 text-slate-300">OFF Interval (Min)</td>
                    <td className="p-3">
                      <input
                        type="number"
                        step="1"
                        value={cyclicTimers.zone_1?.off_min ?? 15.0}
                        onChange={(e) => handleZoneTimerChange('zone_1', 'off_min', e.target.value)}
                        className="w-20 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white font-bold outline-none focus:border-green-500"
                      />
                    </td>
                    <td className="p-3">
                      <input
                        type="number"
                        step="1"
                        value={cyclicTimers.zone_2?.off_min ?? 15.0}
                        onChange={(e) => handleZoneTimerChange('zone_2', 'off_min', e.target.value)}
                        className="w-20 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white font-bold outline-none focus:border-green-500"
                      />
                    </td>
                  </tr>

                  {/* Live Status & Trigger Controls */}
                  <tr className="hover:bg-slate-800/30 transition">
                    <td className="p-3 text-slate-300">Live Operation Status</td>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${relayMap.ch_12 ? 'bg-green-600 text-white' : 'bg-slate-800 text-slate-400'}`}>
                          {relayMap.ch_12 ? 'RUNNING' : 'OFF'}
                        </span>
                        <button
                          type="button"
                          onClick={() => sendCommand(relayMap.ch_12 ? 'stop_zone_1' : 'start_zone_1')}
                          className="px-2.5 py-1 rounded-lg bg-green-600 hover:bg-green-500 text-white text-[11px] font-bold shadow-sm transition active:scale-95"
                        >
                          {relayMap.ch_12 ? 'Stop (12)' : 'Start (12)'}
                        </button>
                      </div>
                    </td>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${relayMap.ch_13 ? 'bg-green-600 text-white' : 'bg-slate-800 text-slate-400'}`}>
                          {relayMap.ch_13 ? 'RUNNING' : 'OFF'}
                        </span>
                        <button
                          type="button"
                          onClick={() => sendCommand(relayMap.ch_13 ? 'stop_zone_2' : 'start_zone_2')}
                          className="px-2.5 py-1 rounded-lg bg-green-600 hover:bg-green-500 text-white text-[11px] font-bold shadow-sm transition active:scale-95"
                        >
                          {relayMap.ch_13 ? 'Stop (13)' : 'Start (13)'}
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="flex justify-center mt-6">
              <button
                type="button"
                onClick={handleSave}
                disabled={saveStatus === 'saving'}
                className="flex items-center gap-2.5 rounded-xl bg-green-600 hover:bg-green-500 text-white font-bold text-sm px-7 py-3 shadow-lg shadow-green-950/40 transition active:scale-95 disabled:opacity-50"
              >
                <Save className="w-4 h-4" />
                <span> Save Both Zone Settings</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── PERSISTENT BOTTOM NAVIGATION DOCK (MATCHING THE MACHINE IN USER'S PHOTO) ── */}
      <div className="max-w-6xl mx-auto mt-8 pt-4 border-t border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          onClick={handlePrevTab}
          className="flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-slate-200 px-5 py-2.5 text-xs font-bold uppercase transition active:scale-95"
        >
          <ChevronLeft className="w-4 h-4 text-[#60bf71]" />
          <span>PREV</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('settings')}
          className="flex items-center gap-2 rounded-xl border border-green-500/40 bg-green-500/10 hover:bg-green-500/20 text-[#60bf71] px-6 py-2.5 text-xs font-bold uppercase transition active:scale-95"
        >
          <Home className="w-4 h-4" />
          <span>DASHBOARD</span>
        </button>

        <button
          type="button"
          onClick={handleNextTab}
          className="flex items-center gap-2 rounded-xl border border-green-600 bg-green-600 hover:bg-green-500 text-white px-5 py-2.5 text-xs font-bold uppercase transition active:scale-95 shadow-sm shadow-green-950/40"
        >
          <span>NEXT</span>
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
