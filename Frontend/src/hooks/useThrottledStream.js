import { useEffect, useRef, useState, useCallback } from 'react';

/**
 * 
 * @param {string} apiBase - The base API URL
 * @param {Object} filter - Device filtering params { deviceId, mqttId }
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

  useEffect(() => {
    if (!deviceId && !mqttId && !devices) {
      return;
    }

    // Build targeted SSE URL with query parameters
    const params = new URLSearchParams();
    if (deviceId) params.set('deviceId', deviceId);
    if (mqttId) params.set('mqttId', mqttId);
    if (devices) params.set('devices', devices);

    const sseUrl = `${apiBase || ''}/api/devices/stream?${params.toString()}`;
    const eventSource = new EventSource(sseUrl);

    eventSource.onopen = () => {
      setIsConnected(true);
      setError(null);
    };

    eventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (!payload) return;

        // Push packet to high-speed in-memory buffer
        bufferRef.current.push(payload);

        // Schedule throttled flush if not already active
        if (!timerRef.current) {
          timerRef.current = setTimeout(flushBuffer, throttleMs);
        }
      } catch (e) {
        // Ignore heartbeat ping messages
      }
    };

    eventSource.onerror = (err) => {
      setIsConnected(false);
      setError(err);
    };

    return () => {
      eventSource.close();
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      bufferRef.current = [];
    };
  }, [apiBase, deviceId, mqttId, throttleMs, flushBuffer]);

  return { isConnected, latestPacket, lastUpdated, error };
}

export default useThrottledStream;
