/**
 * Enterprise Real-Time WebSocket Client for InHydro IoT
 * Features:
 * - Viewport-Aware Subscriptions (Only streams devices currently in view)
 * - Automatic Exponential Backoff Reconnection
 * - Resubscription on Reconnect
 * - Low-overhead binary/JSON message dispatch
 */

class TelemetryWebSocketClient {
  constructor() {
    this.ws = null;
    this.listeners = new Set();
    this.currentRooms = new Set();
    this.reconnectAttempts = 0;
    this.maxReconnectDelay = 10000;
    this.reconnectTimer = null;
    this.isConnected = false;
    this.connectionStateListeners = new Set();
  }

  getWsUrl() {
    const apiBase = import.meta.env.VITE_Backend_URL || import.meta.env.VITE_BACKEND_URL || import.meta.env.VITE_API_URL || '';
    if (apiBase.startsWith('http')) {
      const url = new URL(apiBase);
      const wsProto = url.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${wsProto}//${url.host}/ws/telemetry`;
    }
    const loc = window.location;
    const wsProto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = (loc.hostname === 'localhost' && !['5173', '5000', '3000'].includes(loc.port)) ? 'localhost:5000' : loc.host;
    return `${wsProto}//${host}/ws/telemetry`;
  }

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    try {
      const url = this.getWsUrl();
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        this.isConnected = true;
        this.reconnectAttempts = 0;
        this.notifyStateChange(true);

        // Re-subscribe to all active rooms on reconnect
        if (this.currentRooms.size > 0) {
          this.send({
            action: 'subscribe_viewport',
            rooms: Array.from(this.currentRooms)
          });
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const packet = JSON.parse(event.data);
          this.listeners.forEach((listener) => {
            try {
              listener(packet);
            } catch (e) { }
          });
        } catch (e) { }
      };

      this.ws.onclose = () => {
        this.isConnected = false;
        this.notifyStateChange(false);
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        this.isConnected = false;
        this.notifyStateChange(false);
      };
    } catch (err) {
      this.scheduleReconnect();
    }
  }

  scheduleReconnect() {
    if (this.reconnectTimer) return;
    const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), this.maxReconnectDelay);
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  /**
   * Set the visible viewport of devices.
   * Unsubscribes from devices that scrolled out of view and subscribes to new visible devices.
   * @param {string[]} deviceIds 
   */
  setViewport(deviceIds = []) {
    this.connect();
    const cleanList = deviceIds.map((id) => String(id || '').trim().toLowerCase()).filter(Boolean);
    const newRooms = new Set(cleanList);

    // Find rooms to unsubscribe
    const toRemove = [];
    this.currentRooms.forEach((r) => {
      if (!newRooms.has(r)) toRemove.push(r);
    });

    if (toRemove.length > 0) {
      this.send({ action: 'unsubscribe', rooms: toRemove });
      toRemove.forEach((r) => this.currentRooms.delete(r));
    }

    // Find rooms to subscribe
    const toAdd = [];
    newRooms.forEach((r) => {
      if (!this.currentRooms.has(r)) {
        toAdd.push(r);
        this.currentRooms.add(r);
      }
    });

    if (toAdd.length > 0) {
      this.send({ action: 'subscribe_viewport', rooms: toAdd });
    }
  }

  /**
   * Subscribe to specific device IDs or rooms
   */
  subscribe(deviceIds = []) {
    this.connect();
    const list = Array.isArray(deviceIds) ? deviceIds : [deviceIds];
    const clean = list.map((id) => String(id || '').trim().toLowerCase()).filter(Boolean);
    clean.forEach((id) => this.currentRooms.add(id));
    this.send({ action: 'subscribe_viewport', rooms: clean });
  }

  /**
   * Unsubscribe from specific device IDs or rooms
   */
  unsubscribe(deviceIds = []) {
    const list = Array.isArray(deviceIds) ? deviceIds : [deviceIds];
    const clean = list.map((id) => String(id || '').trim().toLowerCase()).filter(Boolean);
    clean.forEach((id) => this.currentRooms.delete(id));
    this.send({ action: 'unsubscribe', rooms: clean });
  }

  /**
   * Subscribe to global wildcard (all devices) - for SuperAdmin or Master View
   */
  subscribeAll() {
    this.connect();
    this.currentRooms.add('*');
    this.send({ action: 'subscribe', rooms: ['*'] });
  }

  onMessage(callback) {
    this.listeners.add(callback);
    this.connect();
    return () => this.listeners.delete(callback);
  }

  onConnectionChange(callback) {
    this.connectionStateListeners.add(callback);
    callback(this.isConnected);
    return () => this.connectionStateListeners.delete(callback);
  }

  notifyStateChange(state) {
    this.connectionStateListeners.forEach((cb) => {
      try {
        cb(state);
      } catch (e) { }
    });
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.isConnected = false;
  }
}

// Export singleton instance
export const telemetryWs = new TelemetryWebSocketClient();
