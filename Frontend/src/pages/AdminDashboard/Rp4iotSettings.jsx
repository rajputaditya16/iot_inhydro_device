import { useState, useEffect, useRef } from 'react';
import {
  Save, AlertCircle, CheckCircle2, RefreshCw, ChevronDown, Play, Square,
  Clock, Activity, Thermometer, Zap, Droplets, Fan, ShieldAlert,
  Sliders, Cpu, AlertTriangle, ArrowLeft, Power, Eye, Radio, Server,
  RotateCcw, StopCircle, CloudSun, Moon, Sun, Wind
} from 'lucide-react';
import { createMqttClient } from '../../utils/mqtt';
import { telemetryWs } from '../../utils/websocketClient';
import { useNavigate, useSearchParams } from 'react-router-dom';

const defaultSystemConfig = {
  relay_port: '/dev/ttyUSB0',
  relay_baud: 9600,
  relay_slave_id: 1,
  md02_port: '/dev/ttyUSB1',
  md02_baud: 9600,
  md02_slave_id: 1,
  sv1_delay_sec: 10,
  fert_duration_sec: 600,
  irrig_duration_sec: 900,
  simulation_mode: false,
  device_name: 'rp4_controller'
};

const defaultCyclicTimers = {
  fertigation: {
    enabled: false,
    start_time: '06:00',
    stop_time: '18:00',
    on_min: 10.0,
    off_min: 60.0
  },
  irrigation: {
    enabled: false,
    start_time: '06:00',
    stop_time: '18:00',
    on_min: 15.0,
    off_min: 60.0
  }
};

const defaultClimateSetpoints = {
  'DAY Start': '06:00',
  'DAY Stop': '18:00',
  'NIGHT Start': '18:00',
  'NIGHT Stop': '06:00',
  'FOGGER TRIGGER MODE': 'SENSOR', // SENSOR, CYCLIC, BOTH
  'HUMI D_Start': '06:00',
  'HUMI D_Stop': '18:00',
  'HUMI D_ON Min': 2.0,
  'HUMI D_OFF Min': 10.0,
  'HUMI D_Min': 60.0,
  'HUMI D_Max': 80.0,
  'HUMI N_Start': '18:00',
  'HUMI N_Stop': '06:00',
  'HUMI N_ON Min': 1.0,
  'HUMI N_OFF Min': 20.0,
  'HUMI N_Min': 70.0,
  'HUMI N_Max': 85.0,
  'ACF Temp Min': 24.0,
  'ACF Temp Max': 30.0
};

const relayDescriptions = [
  { ch: 0, key: 'ch_0', name: 'Master Relay', code: 'Ch 0', purpose: 'System Master Power & Interlock', icon: Zap },
  { ch: 1, key: 'ch_1', name: 'Main Line Valve (SV1)', code: 'Ch 1', purpose: 'Process Line Feed Valve (SV1 Delay)', icon: Droplets },
  { ch: 2, key: 'ch_2', name: 'Irrigation Valve (SV2)', code: 'Ch 2', purpose: 'Irrigation Branch Delivery Valve', icon: Droplets },
  { ch: 3, key: 'ch_3', name: 'Fogger Valve (SV4)', code: 'Ch 3', purpose: 'High Pressure Fogging / Misting Line', icon: CloudSun },
  { ch: 4, key: 'ch_4', name: 'Fertigation Valve (SV3)', code: 'Ch 4', purpose: 'Nutrient Injection Delivery Valve', icon: Activity },
  { ch: 5, key: 'ch_5', name: 'ACF Circulation Fan', code: 'Ch 5', purpose: 'Air Circulation & Humidity Dispersion', icon: Fan },
  { ch: 6, key: 'ch_6', name: 'Auxiliary Valve (SV5)', code: 'Ch 6', purpose: 'Secondary Line Delivery Valve', icon: Droplets },
];

export default function Rp4iotSettings({ isEmbedded = false, defaultDeviceId = '', defaultMqttId = '' }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialDeviceId = defaultDeviceId || searchParams.get('device') || '';
  const initialMqttId = defaultMqttId || searchParams.get('mqttId') || '';

  const [devices, setDevices] = useState([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState(initialDeviceId);
  const [deviceRoot, setDeviceRoot] = useState(initialMqttId);
  const [isDeviceDropdownOpen, setIsDeviceDropdownOpen] = useState(false);

  // Settings State
  const [systemConfig, setSystemConfig] = useState(defaultSystemConfig);
  const [cyclicTimers, setCyclicTimers] = useState(defaultCyclicTimers);
  const [climateSetpoints, setClimateSetpoints] = useState(defaultClimateSetpoints);

  // User Edit & Dirty Tracking State (P1 Fix: prevents background telemetry overwriting active edits)
  const [isDirty, setIsDirty] = useState(false);
  const isDirtyRef = useRef(false);
  const hasLoadedConfigRef = useRef(false);
  const isSyncRequestedRef = useRef(false);
  const lastHydratedDeviceIdRef = useRef(null);
  const baselineConfigRef = useRef({
    systemConfig: null,
    cyclicTimers: null,
    climateSetpoints: null
  });

  // Live Telemetry Hot State
  const [liveSensors, setLiveSensors] = useState({ temp: null, humi: null, status: 'OFFLINE' });
  const [processState, setProcessState] = useState({ mode: 'IDLE', status_msg: 'Idle', elapsed_sec: 0, target_sec: 0 });
  const [climateState, setClimateState] = useState({ fogger_active: false, fogger_status: 'Idle', acf_active: false, acf_status: 'Idle', period: 'DAY' });
  const [relays, setRelays] = useState({ ch_0: false, ch_1: false, ch_2: false, ch_3: false, ch_4: false, ch_5: false, ch_6: false });

  // Connectivity & Feedback
  const [machineOnline, setMachineOnline] = useState(false);
  const [brokerConnected, setBrokerConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saveStatus, setSaveStatus] = useState('idle'); // idle | saving | success | error
  const [statusMessage, setStatusMessage] = useState('');
  const [activeTab, setActiveTab] = useState('overview'); // overview | process | cyclic | climate | hardware

  const mqttClientRef = useRef(null);
  const onlineWatchdogRef = useRef(null);
  const token = localStorage.getItem('token');
  const API_BASE = import.meta.env.VITE_API_URL || '';

  // 1. Fetch RP4 IoT devices from Backend
  useEffect(() => {
    const fetchDevices = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/api/devices`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const data = await res.json();
        if (data.success && Array.isArray(data.data)) {
          const rp4Devices = data.data.filter(
            d => d.deviceType === 'rp4iot' ||
              d.deviceType === 'rajapawria' ||
              (d.mqttId && (
                d.mqttId.toLowerCase().includes('rp4') ||
                d.mqttId.toLowerCase().includes('pi4') ||
                d.mqttId.toLowerCase().includes('raja')
              )) ||
              (d.name && (
                d.name.toLowerCase().includes('rp4') ||
                d.name.toLowerCase().includes('pi4') ||
                d.name.toLowerCase().includes('raja') ||
                d.name.toLowerCase().includes('rajapawria')
              ))
          );

          const list = rp4Devices.length > 0 ? rp4Devices : data.data;
          setDevices(list);

          if (!selectedDeviceId && list.length > 0) {
            const first = list[0];
            setSelectedDeviceId(first._id);
            setDeviceRoot(first.mqttId || first.name || 'rp4_controller');
          } else if (selectedDeviceId) {
            const current = list.find(d => d._id === selectedDeviceId || d.mqttId === selectedDeviceId);
            if (current) {
              setDeviceRoot(current.mqttId || current.name || 'rp4_controller');
            }
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

  const selectedDevice = devices.find(d => d._id === selectedDeviceId || d.mqttId === deviceRoot);

  // 2. Hydrate DB settings when device changes
  useEffect(() => {
    if (!selectedDevice) return;

    if (lastHydratedDeviceIdRef.current !== selectedDeviceId) {
      lastHydratedDeviceIdRef.current = selectedDeviceId;
      hasLoadedConfigRef.current = true;
      isDirtyRef.current = false;
      setIsDirty(false);

      if (selectedDevice.status === 'online') {
        setMachineOnline(true);
      }

      let nextSys = { ...defaultSystemConfig };
      if (selectedDevice.config && typeof selectedDevice.config === 'object') {
        nextSys = { ...nextSys, ...selectedDevice.config };
        setSystemConfig(nextSys);
      }

      let nextCyc = { ...defaultCyclicTimers };
      let nextClim = { ...defaultClimateSetpoints };

      if (selectedDevice.settings && typeof selectedDevice.settings === 'object') {
        const s = selectedDevice.settings;
        if (s.cyclic_timers) {
          nextCyc = { ...nextCyc, ...s.cyclic_timers };
          setCyclicTimers(nextCyc);
        }
        if (s.climate_setpoints) {
          const cs = s.climate_setpoints;
          const dStart = cs['HUMI D_Start'] || cs['DAY Start'] || nextClim['HUMI D_Start'] || '06:00';
          const dStop = cs['HUMI D_Stop'] || cs['DAY Stop'] || nextClim['HUMI D_Stop'] || '18:00';
          const nStart = cs['HUMI N_Start'] || cs['NIGHT Start'] || nextClim['HUMI N_Start'] || '18:00';
          const nStop = cs['HUMI N_Stop'] || cs['NIGHT Stop'] || nextClim['HUMI N_Stop'] || '06:00';
          const fogMode = cs['fogger_trigger_mode'] || cs['FOGGER TRIGGER MODE'] || nextClim['fogger_trigger_mode'] || 'SENSOR';

          nextClim = {
            ...nextClim,
            ...cs,
            'HUMI D_Start': dStart,
            'DAY Start': dStart,
            'HUMI D_Stop': dStop,
            'DAY Stop': dStop,
            'HUMI N_Start': nStart,
            'NIGHT Start': nStart,
            'HUMI N_Stop': nStop,
            'NIGHT Stop': nStop,
            'fogger_trigger_mode': fogMode,
            'FOGGER TRIGGER MODE': fogMode,
          };
          setClimateSetpoints(nextClim);
        }
        if (s.relays) setRelays(prev => ({ ...prev, ...s.relays }));
        if (s.process_state) setProcessState(prev => ({ ...prev, ...s.process_state }));
        if (s.climate_state) setClimateState(prev => ({ ...prev, ...s.climate_state }));
        if (s.sensor_data) setLiveSensors(prev => ({ ...prev, ...s.sensor_data }));
      }

      baselineConfigRef.current = {
        systemConfig: JSON.parse(JSON.stringify(nextSys)),
        cyclicTimers: JSON.parse(JSON.stringify(nextCyc)),
        climateSetpoints: JSON.parse(JSON.stringify(nextClim))
      };
    } else {
      if (selectedDevice.status === 'online') {
        setMachineOnline(true);
      }
    }
  }, [selectedDeviceId, selectedDevice]);

  // 3. Multi-Channel Real-time Ingestion (MQTT + SSE + WebSocket)
  useEffect(() => {
    if (!deviceRoot) return;

    const markOnline = () => {
      setMachineOnline(true);
      if (onlineWatchdogRef.current) clearTimeout(onlineWatchdogRef.current);
      onlineWatchdogRef.current = setTimeout(() => {
        setMachineOnline(false);
      }, 25000);
    };

    const handlePacket = (topic, rawData) => {
      try {
        const raw = typeof rawData === 'string' ? JSON.parse(rawData) : rawData;
        if (!raw) return;
        const item = Array.isArray(raw) ? raw[raw.length - 1] : raw;
        const payload = (item?.data && typeof item.data === 'object' && !item.sensor_data && !item.relays && !item.climate_setpoints)
          ? item.data
          : (item?.data && typeof item.data === 'object' ? { ...item, ...item.data } : item);
        if (!payload) return;

        markOnline();

        // Sensor updates
        if (payload.sensor_data && typeof payload.sensor_data === 'object') {
          setLiveSensors({
            temp: payload.sensor_data.temp ?? payload.temp ?? null,
            humi: payload.sensor_data.humi ?? payload.humi ?? null,
            status: payload.sensor_data.status || 'OK'
          });
        } else if (payload.temp !== undefined || payload.humi !== undefined) {
          setLiveSensors(prev => ({
            ...prev,
            temp: payload.temp ?? prev.temp,
            humi: payload.humi ?? prev.humi,
            status: 'OK'
          }));
        }

        // Process State
        if (payload.process_state && typeof payload.process_state === 'object') {
          setProcessState(prev => ({
            ...prev,
            mode: payload.process_state.mode || payload.process_state.active_process || prev.mode,
            status_msg: payload.process_state.status_msg || prev.status_msg,
            elapsed_sec: payload.process_state.elapsed_sec ?? prev.elapsed_sec,
            target_sec: payload.process_state.target_sec ?? prev.target_sec
          }));
        }

        // Climate State
        if (payload.climate_state && typeof payload.climate_state === 'object') {
          setClimateState(prev => ({
            ...prev,
            fogger_active: payload.climate_state.fogger_active ?? prev.fogger_active,
            fogger_status: payload.climate_state.fogger_status || prev.fogger_status,
            acf_active: payload.climate_state.acf_active ?? prev.acf_active,
            acf_status: payload.climate_state.acf_status || prev.acf_status,
            period: payload.climate_state.period || prev.period
          }));
        }

        // Relays
        if (payload.relays && typeof payload.relays === 'object') {
          setRelays(prev => ({ ...prev, ...payload.relays }));
        }

        // Configuration sync from Edge:
        // Protect user edits! NEVER overwrite if user has unsaved edits (isDirtyRef.current === true)
        // Whenever idle (!isDirtyRef.current), automatically sync real-time hardware changes
        const canSyncConfig = !isDirtyRef.current;

        if (canSyncConfig) {
          let hasSyncedAny = false;
          let newSys = null;
          let newCyc = null;
          let newClim = null;

          if (payload.system_config && typeof payload.system_config === 'object') {
            newSys = payload.system_config;
            setSystemConfig(prev => ({ ...prev, ...payload.system_config }));
            hasSyncedAny = true;
          }
          if (payload.cyclic_timers && typeof payload.cyclic_timers === 'object') {
            newCyc = payload.cyclic_timers;
            setCyclicTimers(prev => ({ ...prev, ...payload.cyclic_timers }));
            hasSyncedAny = true;
          }
          if (payload.climate_setpoints && typeof payload.climate_setpoints === 'object') {
            const cs = payload.climate_setpoints;
            const dStart = cs['HUMI D_Start'] || cs['DAY Start'] || '06:00';
            const dStop = cs['HUMI D_Stop'] || cs['DAY Stop'] || '18:00';
            const nStart = cs['HUMI N_Start'] || cs['NIGHT Start'] || '18:00';
            const nStop = cs['HUMI N_Stop'] || cs['NIGHT Stop'] || '06:00';
            const fogMode = cs['fogger_trigger_mode'] || cs['FOGGER TRIGGER MODE'] || 'SENSOR';

            const normalized = {
              ...cs,
              'HUMI D_Start': dStart,
              'DAY Start': dStart,
              'HUMI D_Stop': dStop,
              'DAY Stop': dStop,
              'HUMI N_Start': nStart,
              'NIGHT Start': nStart,
              'HUMI N_Stop': nStop,
              'NIGHT Stop': nStop,
              'fogger_trigger_mode': fogMode,
              'FOGGER TRIGGER MODE': fogMode,
            };
            newClim = normalized;
            setClimateSetpoints(prev => ({ ...prev, ...normalized }));
            hasSyncedAny = true;
          }
          if (payload.simulation_mode !== undefined) {
            setSystemConfig(prev => ({ ...prev, simulation_mode: Boolean(payload.simulation_mode) }));
            hasSyncedAny = true;
          }

          if (hasSyncedAny) {
            hasLoadedConfigRef.current = true;
            isSyncRequestedRef.current = false;
            baselineConfigRef.current = {
              systemConfig: newSys ? JSON.parse(JSON.stringify(newSys)) : baselineConfigRef.current.systemConfig,
              cyclicTimers: newCyc ? JSON.parse(JSON.stringify(newCyc)) : baselineConfigRef.current.cyclicTimers,
              climateSetpoints: newClim ? JSON.parse(JSON.stringify(newClim)) : baselineConfigRef.current.climateSetpoints
            };
          }
        }
      } catch (err) {
        console.debug('Error processing packet:', err);
      }
    };

    // A. Browser MQTT Client
    const mqttClient = createMqttClient();
    mqttClientRef.current = mqttClient;

    mqttClient.on('connect', () => {
      setBrokerConnected(true);
      const target = deviceRoot.toLowerCase();
      mqttClient.subscribe(`inhydro/${deviceRoot}/telemetry/live`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/telemetry`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/state`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/status`);
      mqttClient.subscribe(`inhydro/${deviceRoot}/command/status`);

      if (target !== deviceRoot) {
        mqttClient.subscribe(`inhydro/${target}/telemetry/live`);
        mqttClient.subscribe(`inhydro/${target}/state`);
      }

      // Request fresh state on connect
      mqttClient.publish(`inhydro/${deviceRoot}/request_sync`, '1');
    });

    mqttClient.on('message', (top, msg) => {
      handlePacket(top, msg.toString());
    });

    mqttClient.on('error', () => {
      setBrokerConnected(false);
    });

    // B. WebSocket Subscription
    const targetRooms = [selectedDeviceId, deviceRoot].filter(Boolean).map(s => String(s).toLowerCase());
    telemetryWs.subscribe(targetRooms);
    const unbindWs = telemetryWs.onMessage((pkt) => {
      if (!pkt) return;
      const mId = pkt.mqttId ? String(pkt.mqttId).toLowerCase() : '';
      const top = pkt.topic ? String(pkt.topic).toLowerCase() : '';
      if (targetRooms.includes(mId) || targetRooms.some(r => top.includes(r))) {
        handlePacket(pkt.topic, pkt.data);
      }
    });

    // C. SSE Stream Fallback
    const sseUrl = `${API_BASE}/api/devices/stream?deviceId=${selectedDeviceId || ''}&mqttId=${deviceRoot}`;
    const eventSource = new EventSource(sseUrl);
    eventSource.onmessage = (event) => {
      try {
        if (!event.data || event.data.startsWith(':')) return;
        const pkt = JSON.parse(event.data);
        if (pkt.mqttId === deviceRoot || pkt.topic?.includes(deviceRoot)) {
          handlePacket(pkt.topic, pkt.data);
        }
      } catch (e) { }
    };

    return () => {
      if (onlineWatchdogRef.current) clearTimeout(onlineWatchdogRef.current);
      telemetryWs.unsubscribe(targetRooms);
      unbindWs();
      eventSource.close();
      if (mqttClient) mqttClient.end();
    };
  }, [deviceRoot, selectedDeviceId, API_BASE]);

  // 4. Remote Command Dispatcher
  const sendCommand = async (action, extra = {}) => {
    if (!deviceRoot) return;
    setStatusMessage(`Sending "${action}" command...`);
    try {
      const devId = selectedDeviceId || deviceRoot;
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
        setStatusMessage(`Command "${action}" executed.`);
        setTimeout(() => setStatusMessage(''), 3500);
      } else {
        setStatusMessage(`Notice: ${data.message || 'Execution error'}`);
      }
    } catch (err) {
      setStatusMessage(`Error dispatching command: ${err.message}`);
    }
  };

  // 5. Request State Sync from Edge Controller
  const handleSyncRequest = async () => {
    if (!deviceRoot) return;
    isSyncRequestedRef.current = true;
    isDirtyRef.current = false;
    setIsDirty(false);
    setStatusMessage('Requesting live state sync from RP4 Edge Controller...');
    try {
      const devId = selectedDeviceId || deviceRoot;
      const res = await fetch(`${API_BASE}/api/devices/${devId}/push-config`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ action: 'sync' })
      });
      const data = await res.json();
      if (data.success) {
        setStatusMessage('Sync requested. Awaiting edge controller broadcast...');
        setTimeout(() => setStatusMessage(''), 3000);
      }
    } catch (err) {
      setStatusMessage(`Sync request failed: ${err.message}`);
    }
  };

  // 6. Push Full Config & Setpoints to Device
  const handleSave = async () => {
    if (!deviceRoot) return;
    setSaveStatus('saving');
    setStatusMessage('Pushing setpoints and configurations to RP4 Edge Controller...');

    const payload = {
      system_config: systemConfig,
      cyclic_timers: cyclicTimers,
      climate_setpoints: {
        ...climateSetpoints,
        'DAY Start': climateSetpoints['HUMI D_Start'] || climateSetpoints['DAY Start'] || '06:00',
        'DAY Stop': climateSetpoints['HUMI D_Stop'] || climateSetpoints['DAY Stop'] || '18:00',
        'NIGHT Start': climateSetpoints['HUMI N_Start'] || climateSetpoints['NIGHT Start'] || '18:00',
        'NIGHT Stop': climateSetpoints['HUMI N_Stop'] || climateSetpoints['NIGHT Stop'] || '06:00',
        'HUMI D_Start': climateSetpoints['HUMI D_Start'] || climateSetpoints['DAY Start'] || '06:00',
        'HUMI D_Stop': climateSetpoints['HUMI D_Stop'] || climateSetpoints['DAY Stop'] || '18:00',
        'HUMI N_Start': climateSetpoints['HUMI N_Start'] || climateSetpoints['NIGHT Start'] || '18:00',
        'HUMI N_Stop': climateSetpoints['HUMI N_Stop'] || climateSetpoints['NIGHT Stop'] || '06:00',
        'FOGGER TRIGGER MODE': climateSetpoints['fogger_trigger_mode'] || climateSetpoints['FOGGER TRIGGER MODE'] || 'SENSOR',
        'fogger_trigger_mode': climateSetpoints['fogger_trigger_mode'] || climateSetpoints['FOGGER TRIGGER MODE'] || 'SENSOR'
      },
      sv1_delay_sec: Number(systemConfig.sv1_delay_sec),
      fert_duration_sec: Number(systemConfig.fert_duration_sec),
      irrig_duration_sec: Number(systemConfig.irrig_duration_sec),
      simulation_mode: Boolean(systemConfig.simulation_mode)
    };

    try {
      const devId = selectedDeviceId || deviceRoot;
      const res = await fetch(`${API_BASE}/api/devices/${devId}/push-config`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.success) {
        baselineConfigRef.current = {
          systemConfig: JSON.parse(JSON.stringify(systemConfig)),
          cyclicTimers: JSON.parse(JSON.stringify(cyclicTimers)),
          climateSetpoints: JSON.parse(JSON.stringify(climateSetpoints))
        };
        isDirtyRef.current = false;
        setIsDirty(false);
        hasLoadedConfigRef.current = true;
        setSaveStatus('success');
        setStatusMessage('Setpoints & configurations synchronized to Edge device successfully!');
        setTimeout(() => {
          setSaveStatus('idle');
          setStatusMessage('');
        }, 4000);
      } else {
        setSaveStatus('error');
        setStatusMessage(`Push failed: ${data.message || 'Server error'}`);
      }
    } catch (err) {
      setSaveStatus('error');
      setStatusMessage(`Error saving configuration: ${err.message}`);
    }
  };

  // 7. Discard unsaved edits and restore last synced setpoints
  const handleDiscard = () => {
    if (baselineConfigRef.current.systemConfig) {
      setSystemConfig(JSON.parse(JSON.stringify(baselineConfigRef.current.systemConfig)));
    }
    if (baselineConfigRef.current.cyclicTimers) {
      setCyclicTimers(JSON.parse(JSON.stringify(baselineConfigRef.current.cyclicTimers)));
    }
    if (baselineConfigRef.current.climateSetpoints) {
      setClimateSetpoints(JSON.parse(JSON.stringify(baselineConfigRef.current.climateSetpoints)));
    }
    isDirtyRef.current = false;
    setIsDirty(false);
    setStatusMessage('Unsaved edits discarded. Restored last known setpoints.');
    setTimeout(() => setStatusMessage(''), 3000);
  };

  // Helper change handlers
  const handleSystemConfigChange = (key, val) => {
    isDirtyRef.current = true;
    setIsDirty(true);
    setSystemConfig(prev => ({ ...prev, [key]: val }));
  };

  const handleCyclicTimerChange = (mode, field, val) => {
    isDirtyRef.current = true;
    setIsDirty(true);
    setCyclicTimers(prev => ({
      ...prev,
      [mode]: {
        ...prev[mode],
        [field]: val
      }
    }));
  };

  const handleClimateSetpointChange = (key, val) => {
    isDirtyRef.current = true;
    setIsDirty(true);
    setClimateSetpoints(prev => {
      const updated = { ...prev, [key]: val };
      if (key === 'DAY Start') updated['HUMI D_Start'] = val;
      if (key === 'DAY Stop') updated['HUMI D_Stop'] = val;
      if (key === 'NIGHT Start') updated['HUMI N_Start'] = val;
      if (key === 'NIGHT Stop') updated['HUMI N_Stop'] = val;
      if (key === 'HUMI D_Start') updated['DAY Start'] = val;
      if (key === 'HUMI D_Stop') updated['DAY Stop'] = val;
      if (key === 'HUMI N_Start') updated['NIGHT Start'] = val;
      if (key === 'HUMI N_Stop') updated['NIGHT Stop'] = val;
      if (key === 'FOGGER TRIGGER MODE') updated['fogger_trigger_mode'] = val;
      if (key === 'fogger_trigger_mode') updated['FOGGER TRIGGER MODE'] = val;
      return updated;
    });
  };

  // Mutual exclusion check
  const isProcessRunning = processState.mode === 'FERTIGATION' || processState.mode === 'IRRIGATION';

  return (
    <div className={isEmbedded ? "w-full text-slate-100 space-y-6" : "min-h-screen bg-slate-950 text-slate-100 p-4 md:p-6 pb-24"}>
      {/* ── Top Header & Navigation ────────────────────────────────────────── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5 mb-6">
        <div className="flex items-center gap-3">
          {!isEmbedded && (
            <button
              onClick={() => navigate('/devices')}
              className="p-2 rounded-xl bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition"
              title="Back to Devices"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
          )}
          <div>
            <div className="flex items-center gap-2">
              <Cpu className="w-7 h-7 text-emerald-400" />
              <h1 className="text-2xl font-bold tracking-tight text-white">
                RajapawRia Controller Setup
              </h1>
              {/* <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                2-Way Synced
              </span> */}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Climate Automation Edge Suite (RajapawRia)
            </p>
          </div>
        </div>

        {/* Device Switcher & Status Indicators */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Device Dropdown */}
          <div className="relative">
            <button
              onClick={() => setIsDeviceDropdownOpen(!isDeviceDropdownOpen)}
              className="flex items-center gap-2 bg-slate-800/90 border border-slate-700 px-3 py-1.5 rounded-xl text-sm font-medium hover:bg-slate-700/80 transition"
            >
              <Server className="w-4 h-4 text-emerald-400" />
              <span className="max-w-[130px] truncate">{selectedDevice?.name || deviceRoot || 'Select Device'}</span>
              <ChevronDown className="w-4 h-4 text-slate-400" />
            </button>

            {isDeviceDropdownOpen && (
              <div className="absolute right-0 mt-2 w-64 bg-slate-800 border border-slate-700 rounded-xl shadow-2xl z-50 py-1 overflow-hidden">
                <div className="px-3 py-1.5 text-xs font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-700">
                  Select Controller
                </div>
                {devices.map(d => (
                  <button
                    key={d._id}
                    onClick={() => {
                      setSelectedDeviceId(d._id);
                      setDeviceRoot(d.mqttId || d.name || 'rp4_controller');
                      setIsDeviceDropdownOpen(false);
                      hasLoadedConfigRef.current = false;
                      isDirtyRef.current = false;
                      setIsDirty(false);
                    }}
                    className={`w-full text-left px-3 py-2 text-sm flex items-center justify-between hover:bg-slate-700/60 transition ${
                      d._id === selectedDeviceId ? 'bg-emerald-500/10 text-emerald-300 font-semibold' : 'text-slate-300'
                    }`}
                  >
                    <span className="truncate">{d.name}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${d.status === 'online' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-700 text-slate-400'}`}>
                      {d.status || 'offline'}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Machine Online Badge */} 
          <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-medium ${
            machineOnline
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : 'bg-red-500/10 border-red-500/30 text-red-400'
          }`}>
            <span className={`w-2 h-2 rounded-full ${machineOnline ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
            <span>{machineOnline ? ' Online' : ' Offline'}</span>
          </div>

          {/* Broker Status */}
          {/* <div className={`flex items-center gap-1 px-2.5 py-1.5 rounded-xl border text-xs ${
            brokerConnected
              ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'
              : 'bg-slate-800 border-slate-700 text-slate-400'
          }`}>
            <Radio className="w-3.5 h-3.5" />
            <span>{brokerConnected ? 'MQTT Live' : 'MQTT Standby'}</span>
          </div> */}

          {/* Simulation Mode Badge */}
          {systemConfig.simulation_mode && (
            <div className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs font-medium">
              <AlertTriangle className="w-3.5 h-3.5" />
              <span>Simulated Mode</span>
            </div>
          )}

          {/* Unsaved Changes Pill */}
          {isDirty && (
            <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs font-semibold animate-pulse">
              <span className="w-2 h-2 rounded-full bg-amber-400" />
              <span>Unsaved Edits</span>
            </div>
          )}

          {/* Discard Edits Button */}
          {isDirty && (
            <button
              onClick={handleDiscard}
              className="flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-amber-300 px-3 py-1.5 rounded-xl text-xs font-medium transition cursor-pointer"
              title="Discard unsaved edits and restore last synced setpoints"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Discard</span>
            </button>
          )}

          {/* Sync from Device Button */}
          <button
            onClick={handleSyncRequest}
            className="flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 px-3 py-1.5 rounded-xl text-xs font-medium transition cursor-pointer"
            title="Request fresh configuration and state from Raspberry Pi"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Sync</span>
          </button>

          {/* Save & Push Button */}
          <button
            onClick={handleSave}
            disabled={saveStatus === 'saving'}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold shadow-lg transition cursor-pointer disabled:opacity-50 ${
              isDirty
                ? 'bg-emerald-500 hover:bg-emerald-400 text-white ring-2 ring-emerald-400/40 shadow-emerald-900/50'
                : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-900/30'
            }`}
          >
            {saveStatus === 'saving' ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Save className="w-3.5 h-3.5" />
            )}
            <span>{isDirty ? 'Push Changes' : 'Push Setpoints'}</span>
          </button>
        </div>
      </div>

      {/* ── Status Notification Toast ──────────────────────────────────────── */}
      {statusMessage && (
        <div className={`mb-6 p-3 rounded-xl border text-xs flex items-center justify-between shadow-lg transition-all ${
          saveStatus === 'error'
            ? 'bg-red-950/60 border-red-500/50 text-red-200'
            : saveStatus === 'success'
            ? 'bg-emerald-950/60 border-emerald-500/50 text-emerald-200'
            : 'bg-cyan-950/60 border-cyan-500/50 text-cyan-200'
        }`}>
          <div className="flex items-center gap-2">
            {saveStatus === 'error' ? (
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
            ) : saveStatus === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            ) : (
              <RefreshCw className="w-4 h-4 text-cyan-400 animate-spin shrink-0" />
            )}
            <span>{statusMessage}</span>
          </div>
          <button
            onClick={() => setStatusMessage('')}
            className="text-slate-400 hover:text-white ml-3 text-xs"
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Tabs Navigation ────────────────────────────────────────────────── */}
      <div className="flex overflow-x-auto gap-2 border-b border-slate-800 pb-3 mb-6 no-scrollbar">
        {[
          { id: 'overview', label: 'Live Overview & Controls', icon: Activity },
          { id: 'process', label: 'Sequence & Durations', icon: Clock },
          { id: 'cyclic', label: 'Automated Schedulers', icon: Sliders },
          { id: 'climate', label: 'Climate Automation', icon: CloudSun },
          // { id: 'hardware', label: 'Hardware & Modbus', icon: Cpu },
        ].map(t => {
          const Icon = t.icon;
          const isActive = activeTab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition ${
                isActive
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm'
                  : 'bg-slate-900 hover:bg-slate-800 text-slate-400 border border-slate-800'
              }`}
            >
              <Icon className={`w-4 h-4 ${isActive ? 'text-emerald-400' : 'text-slate-500'}`} />
              <span>{t.label}</span>
            </button>
          );
        })}
      </div>

      {/* ── TAB 1: LIVE OVERVIEW & CONTROLS ─────────────────────────────────── */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Sensory Metrics & Climate Period Banner */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {/* Temperature Card */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 shadow-sm relative overflow-hidden">
              <div className="flex items-center justify-between text-slate-400 mb-2">
                <span className="text-xs font-medium uppercase tracking-wider">Room Temperature</span>
                <Thermometer className="w-4 h-4 text-amber-400" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-extrabold text-white">
                  {liveSensors.temp !== null ? `${Number(liveSensors.temp).toFixed(1)}` : '--'}
                </span>
                <span className="text-sm font-semibold text-slate-400">°C</span>
              </div>
              <div className="text-[11px] text-slate-500 mt-2 flex items-center justify-between">
                <span>ACF Thresholds: {climateSetpoints['ACF Temp Min']}°C - {climateSetpoints['ACF Temp Max']}°C</span>
                <span className={liveSensors.temp > climateSetpoints['ACF Temp Max'] ? 'text-amber-400 font-bold' : 'text-slate-400'}>
                  {liveSensors.temp > climateSetpoints['ACF Temp Max'] ? 'HIGH' : 'NORMAL'}
                </span>
              </div>
            </div>

            {/* Humidity Card */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 shadow-sm relative overflow-hidden">
              <div className="flex items-center justify-between text-slate-400 mb-2">
                <span className="text-xs font-medium uppercase tracking-wider">Room Humidity</span>
                <Droplets className="w-4 h-4 text-cyan-400" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-extrabold text-white">
                  {liveSensors.humi !== null ? `${Number(liveSensors.humi).toFixed(1)}` : '--'}
                </span>
                <span className="text-sm font-semibold text-slate-400">%</span>
              </div>
              <div className="text-[11px] text-slate-500 mt-2 flex items-center justify-between">
                <span>Target: {climateSetpoints['HUMI D_Min']}% - {climateSetpoints['HUMI D_Max']}%</span>
                <span className={liveSensors.humi < climateSetpoints['HUMI D_Min'] ? 'text-cyan-400 font-bold' : 'text-slate-400'}>
                  {liveSensors.humi < climateSetpoints['HUMI D_Min'] ? 'LOW (DRY)' : 'OPTIMAL'}
                </span>
              </div>
            </div>

            {/* Climate Period & Mode */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 shadow-sm">
              <div className="flex items-center justify-between text-slate-400 mb-2">
                <span className="text-xs font-medium uppercase tracking-wider">Climate Period</span>
                {climateState.period === 'DAY' ? (
                  <Sun className="w-4 h-4 text-amber-400" />
                ) : (
                  <Moon className="w-4 h-4 text-indigo-400" />
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-2xl font-bold text-white capitalize">{climateState.period || 'DAY'} PERIOD</span>
              </div>
              <div className="text-[11px] text-slate-500 mt-2">
                Day: {climateSetpoints['DAY Start']} to {climateSetpoints['DAY Stop']} | Trigger: {climateSetpoints['FOGGER TRIGGER MODE']}
              </div>
            </div>

            {/* Interlock & Safety Status */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 shadow-sm">
              <div className="flex items-center justify-between text-slate-400 mb-2">
                <span className="text-xs font-medium uppercase tracking-wider">Process Safety Interlock</span>
                <ShieldAlert className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-base font-bold ${isProcessRunning ? 'text-amber-400' : 'text-emerald-400'}`}>
                  {isProcessRunning ? 'Interlock Active' : 'All Clear (Ready)'}
                </span>
              </div>
              <p className="text-[11px] text-slate-500 mt-2">
                {isProcessRunning
                  ? 'Fogger is locked out while fertigation/irrigation cycle is running'
                  : 'Automated climate controls & cyclic schedulers armed'}
              </p>
            </div>
          </div>

          {/* Process Engine Control Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-5">
              <div>
                <div className="flex items-center gap-2">
                  <Clock className="w-5 h-5 text-emerald-400" />
                  <h2 className="text-lg font-bold text-white">Process Sequencer</h2>
                  <span className={`text-xs px-2.5 py-0.5 rounded-full font-semibold border ${
                    processState.mode === 'FERTIGATION'
                      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 animate-pulse'
                      : processState.mode === 'IRRIGATION'
                      ? 'bg-blue-500/20 text-blue-300 border-blue-500/40 animate-pulse'
                      : 'bg-slate-800 text-slate-400 border-slate-700'
                  }`}>
                    {processState.mode}
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-1">
                  Active Status: <span className="text-slate-200 font-medium">{processState.status_msg || 'Ready'}</span>
                </p>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-wrap items-center gap-2.5">
                <button
                  onClick={() => sendCommand('start_fertigation')}
                  disabled={isProcessRunning}
                  className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white px-4 py-2 rounded-xl text-xs font-semibold shadow-md transition"
                >
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Start Fertigation</span>
                </button>

                <button
                  onClick={() => sendCommand('start_irrigation')}
                  disabled={isProcessRunning}
                  className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white px-4 py-2 rounded-xl text-xs font-semibold shadow-md transition"
                >
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Start Irrigation</span>
                </button>

                <button
                  onClick={() => sendCommand('stop')}
                  disabled={!isProcessRunning}
                  className="flex items-center gap-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-40 text-white px-4 py-2 rounded-xl text-xs font-semibold shadow-md transition"
                >
                  <Square className="w-3.5 h-3.5 fill-current" />
                  <span>Stop Cycle</span>
                </button>

                <button
                  onClick={() => sendCommand('all_off')}
                  className="flex items-center gap-2 bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-xl text-xs font-semibold shadow-md transition"
                  title="Force stop all cycles, disable foggers, and turn OFF all 7 relay channels"
                >
                  <StopCircle className="w-3.5 h-3.5" />
                  <span>Emergency ALL OFF</span>
                </button>
              </div>
            </div>

            {/* Progress Bar */}
            {isProcessRunning && (
              <div className="space-y-2 bg-slate-950/60 p-4 rounded-xl border border-slate-800">
                <div className="flex justify-between text-xs font-medium">
                  <span className="text-slate-300">Elapsed: {processState.elapsed_sec}s</span>
                  <span className="text-emerald-400 font-semibold">
                    Target: {processState.mode === 'FERTIGATION' ? systemConfig.fert_duration_sec : systemConfig.irrig_duration_sec}s
                  </span>
                </div>
                <div className="w-full bg-slate-800 h-2.5 rounded-full overflow-hidden">
                  <div
                    className="bg-emerald-500 h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${Math.min(
                        100,
                        (processState.elapsed_sec /
                          (processState.mode === 'FERTIGATION'
                            ? systemConfig.fert_duration_sec || 600
                            : systemConfig.irrig_duration_sec || 900)) *
                          100
                      )}%`
                    }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* 7-Channel Relay Live State Grid */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Zap className="w-5 h-5 text-amber-400" />
                <h2 className="text-lg font-bold text-white">7-Channel Modbus Relays</h2>
              </div>
              <span className="text-xs text-slate-400">Live hardware feedback</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7 gap-3">
              {relayDescriptions.map((r) => {
                const isOn = Boolean(relays[r.key]);
                const Icon = r.icon;
                return (
                  <div
                    key={r.ch}
                    className={`p-3.5 rounded-xl border transition-all ${
                      isOn
                        ? 'bg-emerald-950/30 border-emerald-500/50 shadow-md shadow-emerald-950/40'
                        : 'bg-slate-950/50 border-slate-800'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[11px] font-bold text-slate-400">{r.code}</span>
                      <span
                        className={`w-2.5 h-2.5 rounded-full ${
                          isOn ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]' : 'bg-slate-700'
                        }`}
                      />
                    </div>
                    <div className="flex items-center gap-2 mb-1.5">
                      <Icon className={`w-4 h-4 ${isOn ? 'text-emerald-400' : 'text-slate-500'}`} />
                      <span className="text-xs font-bold text-white truncate">{r.name}</span>
                    </div>
                    <p className="text-[10px] text-slate-500 leading-tight line-clamp-2">
                      {r.purpose}
                    </p>
                    <div className="mt-2.5 pt-2 border-t border-slate-800/80 flex items-center justify-between">
                      <span className={`text-[10px] font-semibold ${isOn ? 'text-emerald-400' : 'text-slate-500'}`}>
                        {isOn ? 'ENERGIZED (ON)' : 'DE-ENERGIZED (OFF)'}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Quick Climate Automation Controls */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Fogger Control Card */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <CloudSun className="w-5 h-5 text-cyan-400" />
                  <h3 className="text-base font-bold text-white">Fogger Misting Automation</h3>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded font-semibold ${
                  climateState.fogger_active ? 'bg-cyan-500/20 text-cyan-300' : 'bg-slate-800 text-slate-400'
                }`}>
                  {climateState.fogger_active ? 'Misting Active' : 'Idle'}
                </span>
              </div>
              <p className="text-xs text-slate-400 mb-4">{climateState.fogger_status || 'Automated sensor/cyclic triggers'}</p>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => sendCommand('fogger_auto')}
                  className="flex-1 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
                >
                  AUTO
                </button>
                <button
                  onClick={() => sendCommand('fogger_on')}
                  disabled={isProcessRunning}
                  className="flex-1 py-1.5 rounded-lg text-xs font-semibold bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 text-white transition"
                >
                  FORCE ON
                </button>
                <button
                  onClick={() => sendCommand('fogger_off')}
                  className="flex-1 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
                >
                  FORCE OFF
                </button>
              </div>
            </div>

            {/* ACF Circulation Fan Control Card */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Fan className="w-5 h-5 text-emerald-400" />
                  <h3 className="text-base font-bold text-white">ACF Circulation Fan</h3>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded font-semibold ${
                  climateState.acf_active ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-400'
                }`}>
                  {climateState.acf_active ? 'Fan Running' : 'Idle'}
                </span>
              </div>
              <p className="text-xs text-slate-400 mb-4">{climateState.acf_status || 'Thermostatic cooling & fogger sync'}</p>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => sendCommand('acf_auto')}
                  className="flex-1 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
                >
                  AUTO
                </button>
                <button
                  onClick={() => sendCommand('acf_on')}
                  className="flex-1 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition"
                >
                  FORCE ON
                </button>
                <button
                  onClick={() => sendCommand('acf_off')}
                  className="flex-1 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
                >
                  FORCE OFF
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── TAB 2: SEQUENCE & DURATIONS ─────────────────────────────────────── */}
      {activeTab === 'process' && (
        <div className="max-w-full bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-sm space-y-6">
          <div>
            <h2 className="text-lg font-bold text-white">Process Sequence & Delays</h2>
            <p className="text-xs text-slate-400 mt-1">
              Configure master delay intervals and execution times for Fertigation and Irrigation lines.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* SV1 Start Delay */}
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
              <label className="block text-xs font-bold text-slate-300 mb-1">
                SV1 Start Delay (seconds)
              </label>
              <p className="text-[11px] text-slate-500 mb-3">
                Delay between opening the main line and activating the secondary valve.
              </p>
              <input
                type="number"
                min="1"
                max="300"
                value={systemConfig.sv1_delay_sec}
                onChange={(e) => handleSystemConfigChange('sv1_delay_sec', Number(e.target.value))}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-base font-bold text-center focus:border-emerald-500 focus:outline-none"
              />
              <span className="text-[10px] text-slate-500 block text-center mt-1">Recommended: 10 sec</span>
            </div>

            {/* Fertigation Run Duration */}
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
              <label className="block text-xs font-bold text-slate-300 mb-1">
                Fertigation Duration (seconds)
              </label>
              <p className="text-[11px] text-slate-500 mb-3">
                Total operating time for a complete fertigation nutrient cycle.
              </p>
              <input
                type="number"
                min="10"
                max="86400"
                value={systemConfig.fert_duration_sec}
                onChange={(e) => handleSystemConfigChange('fert_duration_sec', Number(e.target.value))}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-base font-bold text-center focus:border-emerald-500 focus:outline-none"
              />
              <span className="text-[10px] text-slate-500 block text-center mt-1">
                {Math.round(systemConfig.fert_duration_sec / 60)} minutes
              </span>
            </div>

            {/* Irrigation Run Duration */}
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
              <label className="block text-xs font-bold text-slate-300 mb-1">
                Irrigation Duration (seconds)
              </label>
              <p className="text-[11px] text-slate-500 mb-3">
                Total operating time for fresh water irrigation delivery.
              </p>
              <input
                type="number"
                min="10"
                max="86400"
                value={systemConfig.irrig_duration_sec}
                onChange={(e) => handleSystemConfigChange('irrig_duration_sec', Number(e.target.value))}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-base font-bold text-center focus:border-emerald-500 focus:outline-none"
              />
              <span className="text-[10px] text-slate-500 block text-center mt-1">
                {Math.round(systemConfig.irrig_duration_sec / 60)} minutes
              </span>
            </div>
          </div>
        </div>
      )}

      {/* ── TAB 3: AUTOMATED CYCLIC SCHEDULERS ──────────────────────────────── */}
      {activeTab === 'cyclic' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Cyclic Fertigation */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-base font-bold text-white">Cyclic Fertigation Scheduler</h3>
                <p className="text-xs text-slate-400">Repeats fertigation nutrient cycles in a time window</p>
              </div>
              <button
                onClick={() => handleCyclicTimerChange('fertigation', 'enabled', !cyclicTimers.fertigation?.enabled)}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold transition ${
                  cyclicTimers.fertigation?.enabled
                    ? 'bg-emerald-600 text-white shadow-md'
                    : 'bg-slate-800 text-slate-400 border border-slate-700'
                }`}
              >
                {cyclicTimers.fertigation?.enabled ? 'ENABLED' : 'DISABLED'}
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Window Start Time</label>
                <input
                  type="time"
                  value={cyclicTimers.fertigation?.start_time || '06:00'}
                  onChange={(e) => handleCyclicTimerChange('fertigation', 'start_time', e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Window Stop Time</label>
                <input
                  type="time"
                  value={cyclicTimers.fertigation?.stop_time || '18:00'}
                  onChange={(e) => handleCyclicTimerChange('fertigation', 'stop_time', e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Cycle ON Duration (Minutes)</label>
                <input
                  type="number"
                  step="0.5"
                  min="0.5"
                  value={cyclicTimers.fertigation?.on_min || 10}
                  onChange={(e) => handleCyclicTimerChange('fertigation', 'on_min', Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Cycle OFF Interval (Minutes)</label>
                <input
                  type="number"
                  step="1"
                  min="1"
                  value={cyclicTimers.fertigation?.off_min || 60}
                  onChange={(e) => handleCyclicTimerChange('fertigation', 'off_min', Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none"
                />
              </div>
            </div>
          </div>

          {/* Cyclic Irrigation */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-base font-bold text-white">Cyclic Irrigation Scheduler</h3>
                <p className="text-xs text-slate-400">Repeats fresh water delivery cycles in a time window</p>
              </div>
              <button
                onClick={() => handleCyclicTimerChange('irrigation', 'enabled', !cyclicTimers.irrigation?.enabled)}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold transition ${
                  cyclicTimers.irrigation?.enabled
                    ? 'bg-blue-600 text-white shadow-md'
                    : 'bg-slate-800 text-slate-400 border border-slate-700'
                }`}
              >
                {cyclicTimers.irrigation?.enabled ? 'ENABLED' : 'DISABLED'}
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Window Start Time</label>
                <input
                  type="time"
                  value={cyclicTimers.irrigation?.start_time || '06:00'}
                  onChange={(e) => handleCyclicTimerChange('irrigation', 'start_time', e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Window Stop Time</label>
                <input
                  type="time"
                  value={cyclicTimers.irrigation?.stop_time || '18:00'}
                  onChange={(e) => handleCyclicTimerChange('irrigation', 'stop_time', e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Cycle ON Duration (Minutes)</label>
                <input
                  type="number"
                  step="0.5"
                  min="0.5"
                  value={cyclicTimers.irrigation?.on_min || 15}
                  onChange={(e) => handleCyclicTimerChange('irrigation', 'on_min', Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Cycle OFF Interval (Minutes)</label>
                <input
                  type="number"
                  step="1"
                  min="1"
                  value={cyclicTimers.irrigation?.off_min || 60}
                  onChange={(e) => handleCyclicTimerChange('irrigation', 'off_min', Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── TAB 4: CLIMATE AUTOMATION ───────────────────────────────────────── */}
      {activeTab === 'climate' && (
        <div className="space-y-6">
          {/* Day / Night Definition & Trigger Mode */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <Clock className="w-5 h-5 text-emerald-400" />
                  Day / Night Period Schedule
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Configure active time windows for Day and Night automation cycles and Fogger trigger mode
                </p>
              </div>

              {/* Fogger Trigger Mode */}
              <div className="w-full sm:w-auto min-w-[240px]">
                <label className="block text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-1">
                  Fogger Trigger Mode
                </label>
                <select
                  value={climateSetpoints['fogger_trigger_mode'] || climateSetpoints['FOGGER TRIGGER MODE'] || 'SENSOR'}
                  onChange={(e) => handleClimateSetpointChange('fogger_trigger_mode', e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs font-semibold text-emerald-400 focus:outline-none focus:border-emerald-500 shadow-inner"
                >
                  <option value="SENSOR">SENSOR ONLY (Humidity Thresholds)</option>
                  <option value="CYCLIC">CYCLIC ONLY (Timed Pulses)</option>
                  <option value="BOTH">BOTH (Sensor Guarded Cyclic)</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
              {/* Day Period Schedule */}
              <div className="bg-slate-950/70 border border-amber-500/25 rounded-xl p-4 space-y-3">
                <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
                  <div className="flex items-center gap-2 text-amber-400">
                    <Sun className="w-4 h-4" />
                    <span className="text-xs font-bold text-white uppercase tracking-wider">Day Period Schedule</span>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20 font-semibold">
                    DAY MODE
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Day Start Time</label>
                    <input
                      type="time"
                      value={climateSetpoints['HUMI D_Start'] || climateSetpoints['DAY Start'] || '06:00'}
                      onChange={(e) => handleClimateSetpointChange('HUMI D_Start', e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-400 font-semibold"
                    />
                    <span className="text-[10px] text-slate-500 block mt-1">Transitions to DAY</span>
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Day End Time</label>
                    <input
                      type="time"
                      value={climateSetpoints['HUMI D_Stop'] || climateSetpoints['DAY Stop'] || '18:00'}
                      onChange={(e) => handleClimateSetpointChange('HUMI D_Stop', e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-400 font-semibold"
                    />
                    <span className="text-[10px] text-slate-500 block mt-1">Transitions to NIGHT</span>
                  </div>
                </div>
              </div>

              {/* Night Period Schedule */}
              <div className="bg-slate-950/70 border border-indigo-500/25 rounded-xl p-4 space-y-3">
                <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
                  <div className="flex items-center gap-2 text-indigo-400">
                    <Moon className="w-4 h-4" />
                    <span className="text-xs font-bold text-white uppercase tracking-wider">Night Period Schedule</span>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-semibold">
                    NIGHT MODE
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Night Start Time</label>
                    <input
                      type="time"
                      value={climateSetpoints['HUMI N_Start'] || climateSetpoints['NIGHT Start'] || '18:00'}
                      onChange={(e) => handleClimateSetpointChange('HUMI N_Start', e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-400 font-semibold"
                    />
                    <span className="text-[10px] text-slate-500 block mt-1">Transitions to NIGHT</span>
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Night End Time</label>
                    <input
                      type="time"
                      value={climateSetpoints['HUMI N_Stop'] || climateSetpoints['NIGHT Stop'] || '06:00'}
                      onChange={(e) => handleClimateSetpointChange('HUMI N_Stop', e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-400 font-semibold"
                    />
                    <span className="text-[10px] text-slate-500 block mt-1">Transitions to DAY</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Fogger Day & Night Settings */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Day Fogger Settings */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
              <div className="flex items-center gap-2 text-amber-400 border-b border-slate-800 pb-3">
                <Sun className="w-5 h-5" />
                <h4 className="text-sm font-bold text-white">DAY Humidity & Fogging Parameters</h4>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">H_Min (% ON Threshold)</label>
                  <input
                    type="number"
                    step="1"
                    value={climateSetpoints['HUMI D_Min'] || 60}
                    onChange={(e) => handleClimateSetpointChange('HUMI D_Min', Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none text-center font-bold"
                  />
                  <span className="text-[10px] text-slate-500 block text-center mt-1">Turns ON when &lt; Min</span>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">H_Max (% OFF Threshold)</label>
                  <input
                    type="number"
                    step="1"
                    value={climateSetpoints['HUMI D_Max'] || 80}
                    onChange={(e) => handleClimateSetpointChange('HUMI D_Max', Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none text-center font-bold"
                  />
                  <span className="text-[10px] text-slate-500 block text-center mt-1">Turns OFF when &ge; Max</span>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Pulse ON Time (Minutes)</label>
                  <input
                    type="number"
                    step="0.5"
                    value={climateSetpoints['HUMI D_ON Min'] || 2.0}
                    onChange={(e) => handleClimateSetpointChange('HUMI D_ON Min', Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none text-center"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Pulse OFF Interval (Minutes)</label>
                  <input
                    type="number"
                    step="1"
                    value={climateSetpoints['HUMI D_OFF Min'] || 10.0}
                    onChange={(e) => handleClimateSetpointChange('HUMI D_OFF Min', Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none text-center"
                  />
                </div>
              </div>
            </div>

            {/* Night Fogger Settings */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
              <div className="flex items-center gap-2 text-indigo-400 border-b border-slate-800 pb-3">
                <Moon className="w-5 h-5" />
                <h4 className="text-sm font-bold text-white">NIGHT Humidity & Fogging Parameters</h4>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">H_Min (% ON Threshold)</label>
                  <input
                    type="number"
                    step="1"
                    value={climateSetpoints['HUMI N_Min'] || 70}
                    onChange={(e) => handleClimateSetpointChange('HUMI N_Min', Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none text-center font-bold"
                  />
                  <span className="text-[10px] text-slate-500 block text-center mt-1">Turns ON when &lt; Min</span>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">H_Max (% OFF Threshold)</label>
                  <input
                    type="number"
                    step="1"
                    value={climateSetpoints['HUMI N_Max'] || 85}
                    onChange={(e) => handleClimateSetpointChange('HUMI N_Max', Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none text-center font-bold"
                  />
                  <span className="text-[10px] text-slate-500 block text-center mt-1">Turns OFF when &ge; Max</span>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Pulse ON Time (Minutes)</label>
                  <input
                    type="number"
                    step="0.5"
                    value={climateSetpoints['HUMI N_ON Min'] || 1.0}
                    onChange={(e) => handleClimateSetpointChange('HUMI N_ON Min', Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none text-center"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Pulse OFF Interval (Minutes)</label>
                  <input
                    type="number"
                    step="1"
                    value={climateSetpoints['HUMI N_OFF Min'] || 20.0}
                    onChange={(e) => handleClimateSetpointChange('HUMI N_OFF Min', Number(e.target.value))}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none text-center"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* ACF Circulation Fan Temperature Setpoints */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
              <Fan className="w-5 h-5 text-emerald-400" />
              <div>
                <h4 className="text-sm font-bold text-white">ACF Circulation Fan Cooling Thresholds</h4>
                <p className="text-xs text-slate-400">Thermostatic control turns fan ON during high temperature excursions</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-full">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Temp Min (°C) - Fan Turns OFF
                </label>
                <input
                  type="number"
                  step="0.5"
                  value={climateSetpoints['ACF Temp Min'] || 24.0}
                  onChange={(e) => handleClimateSetpointChange('ACF Temp Min', Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-base text-white focus:outline-none text-center font-bold"
                />
                <span className="text-[10px] text-slate-500 block text-center mt-1">Hysteresis lower bound</span>
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Temp Max (°C) - Fan Turns ON
                </label>
                <input
                  type="number"
                  step="0.5"
                  value={climateSetpoints['ACF Temp Max'] || 30.0}
                  onChange={(e) => handleClimateSetpointChange('ACF Temp Max', Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-base text-white focus:outline-none text-center font-bold"
                />
                <span className="text-[10px] text-slate-500 block text-center mt-1">High temp threshold</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

