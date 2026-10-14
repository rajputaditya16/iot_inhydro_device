const { WebSocketServer } = require('ws');
const { telemetryEmitter } = require('./mqttSubscriber');

let wss = null;
// Map of roomKey (e.g. deviceId or mqttId in lowercase) -> Set of WebSocket clients
const roomSubscribers = new Map();
// Global broadcast subscribers (e.g. superadmin or wildcard)
const globalSubscribers = new Set();

/**
 * Normalizes an identifier string to a clean lowercase room key
 */
const toRoomKey = (id) => String(id || '').trim().toLowerCase();

/**
 * Initializes high-throughput WebSocket gateway on existing HTTP server
 * @param {import('http').Server} server 
 */
const initWebSocketGateway = (server) => {
  if (wss) return wss;

  wss = new WebSocketServer({
    server,
    path: '/ws/telemetry'
  });

  console.log('✅ [WebSocket Gateway] Initialized on path /ws/telemetry');

  wss.on('connection', (ws, req) => {
    ws.isAlive = true;
    ws.subscribedRooms = new Set();

    ws.on('pong', () => {
      ws.isAlive = true;
    });

    ws.on('message', (messageRaw) => {
      try {
        const msg = JSON.parse(messageRaw.toString());
        const action = msg.action || msg.type;

        switch (action) {
          case 'subscribe':
          case 'subscribe_viewport': {
            const rooms = Array.isArray(msg.rooms || msg.deviceIds) 
              ? (msg.rooms || msg.deviceIds) 
              : [msg.room || msg.deviceId];

            rooms.filter(Boolean).forEach((r) => {
              const rKey = toRoomKey(r);
              if (rKey === '*' || rKey === 'all') {
                globalSubscribers.add(ws);
              } else {
                if (!roomSubscribers.has(rKey)) {
                  roomSubscribers.set(rKey, new Set());
                }
                roomSubscribers.get(rKey).add(ws);
                ws.subscribedRooms.add(rKey);
              }
            });

            ws.send(JSON.stringify({
              type: 'subscribed',
              rooms: Array.from(ws.subscribedRooms),
              count: ws.subscribedRooms.size,
              timestamp: new Date().toISOString()
            }));
            break;
          }

          case 'unsubscribe': {
            const rooms = Array.isArray(msg.rooms || msg.deviceIds) 
              ? (msg.rooms || msg.deviceIds) 
              : [msg.room || msg.deviceId];

            rooms.filter(Boolean).forEach((r) => {
              const rKey = toRoomKey(r);
              if (rKey === '*' || rKey === 'all') {
                globalSubscribers.delete(ws);
              } else {
                if (roomSubscribers.has(rKey)) {
                  roomSubscribers.get(rKey).delete(ws);
                  if (roomSubscribers.get(rKey).size === 0) {
                    roomSubscribers.delete(rKey);
                  }
                }
                ws.subscribedRooms.delete(rKey);
              }
            });

            ws.send(JSON.stringify({
              type: 'unsubscribed',
              remaining: Array.from(ws.subscribedRooms)
            }));
            break;
          }

          case 'clear_subscriptions': {
            ws.subscribedRooms.forEach((rKey) => {
              if (roomSubscribers.has(rKey)) {
                roomSubscribers.get(rKey).delete(ws);
                if (roomSubscribers.get(rKey).size === 0) {
                  roomSubscribers.delete(rKey);
                }
              }
            });
            globalSubscribers.delete(ws);
            ws.subscribedRooms.clear();
            ws.send(JSON.stringify({ type: 'subscriptions_cleared' }));
            break;
          }

          case 'ping': {
            ws.send(JSON.stringify({ type: 'pong', timestamp: Date.now() }));
            break;
          }

          default:
            break;
        }
      } catch (err) {
        // Ignore non-JSON or invalid client frames
      }
    });

    ws.on('close', () => {
      cleanupClient(ws);
    });

    ws.on('error', () => {
      cleanupClient(ws);
    });

    // Send initial welcome & connection confirmation
    ws.send(JSON.stringify({
      type: 'connected',
      message: 'InHydro High-Throughput Real-Time Gateway connected',
      version: '3.0-enterprise'
    }));
  });

  // Client cleanup helper
  const cleanupClient = (ws) => {
    globalSubscribers.delete(ws);
    if (ws.subscribedRooms) {
      ws.subscribedRooms.forEach((rKey) => {
        if (roomSubscribers.has(rKey)) {
          roomSubscribers.get(rKey).delete(ws);
          if (roomSubscribers.get(rKey).size === 0) {
            roomSubscribers.delete(rKey);
          }
        }
      });
      ws.subscribedRooms.clear();
    }
  };

  // 30-second Ping-Pong Watchdog to prune stale connection sockets
  const pingInterval = setInterval(() => {
    if (!wss) return;
    wss.clients.forEach((ws) => {
      if (ws.isAlive === false) {
        cleanupClient(ws);
        return ws.terminate();
      }
      ws.isAlive = false;
      try {
        ws.ping();
      } catch (e) { }
    });
  }, 30000);

  wss.on('close', () => {
    clearInterval(pingInterval);
  });

  // ── High-Speed Telemetry Dispatcher ───────────────────────────────────────
  telemetryEmitter.on('telemetry', (payload) => {
    if (!payload || !wss || wss.clients.size === 0) return;

    const devId = toRoomKey(payload.deviceId);
    const mqttId = toRoomKey(payload.mqttId);

    // Target clients = global subscribers + clients subscribed to devId or mqttId
    const targetClients = new Set(globalSubscribers);

    if (devId && roomSubscribers.has(devId)) {
      roomSubscribers.get(devId).forEach((client) => targetClients.add(client));
    }

    if (mqttId && roomSubscribers.has(mqttId)) {
      roomSubscribers.get(mqttId).forEach((client) => targetClients.add(client));
    }

    if (targetClients.size === 0) {
      return; // Discard: No connected client is currently viewing this device
    }

    const payloadJson = JSON.stringify(payload);

    targetClients.forEach((client) => {
      if (client.readyState === 1 /* OPEN */) {
        try {
          client.send(payloadJson);
        } catch (err) {
          // Socket write failure, client will be reaped by watchdog
        }
      }
    });
  });

  return wss;
};

const getGatewayStats = () => {
  return {
    totalClients: wss ? wss.clients.size : 0,
    activeRooms: roomSubscribers.size,
    globalSubscribers: globalSubscribers.size
  };
};

module.exports = {
  initWebSocketGateway,
  getGatewayStats
};
