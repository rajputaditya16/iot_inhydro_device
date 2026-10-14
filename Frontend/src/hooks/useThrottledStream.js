import { useEffect, useRef, useState, useCallback } from 'react';
import { telemetryWs } from '../utils/websocketClient';

/**
 * Enterprise Throttled Stream Hook for InHydro IoT
 * Automatically uses low-latency selective WebSocket gateway with fallback to SSE.
 * Buffers incoming telemetry packets in memory and flushes in batches at throttleMs rate.
 *
 * @param {string} apiBase - The base API URL
 * @param {Object} filter - Device filtering params { deviceId, mqttId, devices }
 * @param {number} throttleMs - Throttle flush interval in milliseconds (default: 500ms)
 * @param {Function} onBatchedPackets - Optional callback invoked with batched packets
 * @returns {Object} { isConnected, latestPacket, lastUpdated, error }
 */
export function useThrottledStream(apiBase, { deviceId, mqttId, devices } = {}, throttleMs = 500, onBatchedPackets = null) {
  const [isConnected, setIsConnected] = useState(false);
  const [latestPacket, setLatestPacket] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState(null);

  // In-memory buffer refs (mutate without triggering React re-renders)
  const bufferRef = useRef([]);
  const timerRef = useRef(null);
  const callbackRef = useRef(onBatchedPackets);
  callbackRef.current = onBatchedPackets;

  // Flush buffer to React state
  const flushBuffer = useCallback(() => {
    if (bufferRef.current.length === 0) {
      timerRef.current = null;
      return;
    }

    const packets = [...bufferRef.current];
    bufferRef.current = []; // Clear buffer

    const mostRecent = packets[packets.length - 1];
    setLatestPacket(mostRecent);
    setLastUpdated(new Date());

    if (callbackRef.current) {
      callbackRef.current(packets, mostRecent);
    }

    timerRef.current = null;
  }, []);

  const queuePacket = useCallback((payload) => {
    if (!payload) return;
    bufferRef.current.push(payload);
    if (!timerRef.current) {
      timerRef.current = setTimeout(flushBuffer, throttleMs);
    }
  }, [flushBuffer, throttleMs]);

  useEffect(() => {
    if (!deviceId && !mqttId && !devices) {
      return;
    }

    const cleanDeviceId = deviceId ? String(deviceId).toLowerCase() : null;
    const cleanMqttId = mqttId ? String(mqttId).toLowerCase() : null;
    const listDevices = devices ? devices.split(',').map(s => s.trim().toLowerCase()) : [];

    const targetRooms = [cleanDeviceId, cleanMqttId, ...listDevices].filter(Boolean);

    // 1. Subscribe specific rooms on WebSocket Gateway
    if (targetRooms.length > 0) {
      telemetryWs.subscribe(targetRooms);
    }

    // 2. Track connection status
    const unbindConn = telemetryWs.onConnectionChange((connected) => {
      setIsConnected(connected);
      if (connected) setError(null);
    });

    // 3. WebSocket message listener with selective room matching
    const unbindWs = telemetryWs.onMessage((payload) => {
      if (!payload) return;
      const incomingDevId = payload.deviceId ? String(payload.deviceId).toLowerCase() : null;
      const incomingMqttId = payload.mqttId ? String(payload.mqttId).toLowerCase() : null;

      const isMatch =
        (cleanDeviceId && incomingDevId === cleanDeviceId) ||
        (cleanMqttId && incomingMqttId === cleanMqttId) ||
        (listDevices.length > 0 && (listDevices.includes(incomingDevId) || listDevices.includes(incomingMqttId))) ||
        (!cleanDeviceId && !cleanMqttId && listDevices.length === 0);

      if (isMatch) {
        queuePacket(payload);
      }
    });

    // 4. SSE Fallback (Active if WebSocket is disconnected or in restrictive proxies)
    let sseSource = null;
    const fallbackTimer = setTimeout(() => {
      if (!telemetryWs.isConnected) {
        const params = new URLSearchParams();
        if (deviceId) params.set('deviceId', deviceId);
        if (mqttId) params.set('mqttId', mqttId);
        if (devices) params.set('devices', devices);

        const sseUrl = `${apiBase || ''}/api/devices/stream?${params.toString()}`;
        try {
          sseSource = new EventSource(sseUrl);
          sseSource.onopen = () => {
            setIsConnected(true);
            setError(null);
          };
          sseSource.onmessage = (event) => {
            try {
              const data = JSON.parse(event.data);
              queuePacket(data);
            } catch {}
          };
          sseSource.onerror = (err) => {
            setError(err);
          };
        } catch (e) {
          setError(e);
        }
      }
    }, 2500);

    return () => {
      clearTimeout(fallbackTimer);
      if (targetRooms.length > 0) {
        telemetryWs.unsubscribe(targetRooms);
      }
      unbindConn();
      unbindWs();
      if (sseSource) {
        sseSource.close();
      }
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      bufferRef.current = [];
    };
  }, [apiBase, deviceId, mqttId, devices, queuePacket]);

  return { isConnected, latestPacket, lastUpdated, error };
}

export default useThrottledStream;
