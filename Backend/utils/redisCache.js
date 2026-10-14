/**
 * Redis Cache Utility for InHydro IoT Backend
 * ---
 * Uses ioredis for caching Analytics API responses.
 * Gracefully falls back (no-op) if Redis is unavailable or not configured.
 *
 * ENV vars:
 *   REDIS_URL     - full redis:// or rediss:// URL  (optional, default: redis://127.0.0.1:6379)
 *   REDIS_ENABLED - set to "false" to disable Redis entirely (default: true)
 */

const Redis = require("ioredis");

const REDIS_ENABLED = process.env.REDIS_ENABLED !== "false";
const REDIS_URL = process.env.REDIS_URL || "redis://127.0.0.1:6379";

// Default TTLs (seconds)
const TTL = {
  ANALYTICS_SHORT: 60,    // 1 min  — live / today queries
  ANALYTICS_MEDIUM: 300,  // 5 min  — week / month queries
  ANALYTICS_LONG: 1800,   // 30 min — 3-month / all-history queries
  DEVICE_LIST: 30,        // 30 sec — device list
};

let client = null;
let isConnected = false;

if (REDIS_ENABLED) {
  try {
    client = new Redis(REDIS_URL, {
      maxRetriesPerRequest: 1,
      enableOfflineQueue: false,
      connectTimeout: 3000,
      lazyConnect: true,
    });

    client.on("connect", () => {
      isConnected = true;
      console.log("[Redis] Connected to Redis cache at", REDIS_URL);
    });

    client.on("error", (err) => {
      if (isConnected) {
        console.warn("[Redis] Connection error (cache disabled temporarily):", err.message);
      }
      isConnected = false;
    });

    client.on("close", () => {
      isConnected = false;
    });

    // Attempt initial connection (non-blocking)
    client.connect().catch(() => {
      console.warn("[Redis] Could not connect to Redis. Analytics caching disabled. Start Redis with: redis-server");
    });
  } catch (e) {
    console.warn("[Redis] ioredis init error:", e.message);
    client = null;
  }
}

/**
 * Generate a deterministic cache key for analytics requests.
 * @param {string} deviceId
 * @param {Object} params - { start, end, room, downsample, sampleLimit, format }
 * @returns {string}
 */
function makeAnalyticsCacheKey(deviceId, params = {}) {
  const { start, end, room = "all", downsample = false, sampleLimit = 1500, format = "" } = params;
  // Round timestamps to nearest minute for better cache hit rate
  const roundedStart = start ? new Date(Math.floor(new Date(start).getTime() / 60000) * 60000).toISOString() : "all";
  const roundedEnd = end ? new Date(Math.floor(new Date(end).getTime() / 60000) * 60000).toISOString() : "now";
  return `analytics:${deviceId}:${room}:${roundedStart}:${roundedEnd}:ds=${downsample}:sl=${sampleLimit}:fmt=${format}`;
}

/**
 * Determine TTL based on the analytics time range.
 * @param {string|Date} start
 * @param {string|Date} end
 * @returns {number} TTL in seconds
 */
function resolveTTL(start, end) {
  if (!start || start === "all" || new Date(start).getTime() <= 0) {
    return TTL.ANALYTICS_LONG;  // All history / epoch start -> cache 30 min
  }
  const now = Date.now();
  const startMs = new Date(start).getTime();
  const rangeMs = now - startMs;
  const ONE_DAY = 24 * 60 * 60 * 1000;
  const ONE_WEEK = 7 * ONE_DAY;

  if (rangeMs <= ONE_DAY) return TTL.ANALYTICS_SHORT;    // Today / live-range -> 1 min
  if (rangeMs <= ONE_WEEK) return TTL.ANALYTICS_MEDIUM;  // This week -> 5 min
  return TTL.ANALYTICS_LONG;                              // Longer ranges -> 30 min
}

/**
 * Get a cached analytics response.
 * @param {string} key - Cache key from makeAnalyticsCacheKey()
 * @returns {Object|null} Parsed JSON or null on miss/error
 */
async function getCache(key) {
  if (!client || !isConnected) return null;
  try {
    const raw = await client.get(key);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (e) {
    console.warn("[Redis] getCache error:", e.message);
    return null;
  }
}

/**
 * Store an analytics response in cache.
 * @param {string} key   - Cache key
 * @param {Object} value - JSON-serializable response object
 * @param {number} ttl   - TTL in seconds (default: 60)
 */
async function setCache(key, value, ttl = TTL.ANALYTICS_SHORT) {
  if (!client || !isConnected) return;
  try {
    await client.set(key, JSON.stringify(value), "EX", ttl);
  } catch (e) {
    console.warn("[Redis] setCache error:", e.message);
  }
}

/**
 * Invalidate (delete) one or more cache keys by pattern.
 * @param {string} pattern - e.g. "analytics:DEVICE_ID:*"
 */
async function invalidatePattern(pattern) {
  if (!client || !isConnected) return;
  try {
    const keys = await client.keys(pattern);
    if (keys.length > 0) {
      await client.del(...keys);
      console.log("[Redis] Invalidated", keys.length, "key(s) for pattern:", pattern);
    }
  } catch (e) {
    console.warn("[Redis] invalidatePattern error:", e.message);
  }
}

/**
 * Gracefully close the Redis connection (call on server shutdown).
 */
async function closeRedis() {
  if (client) {
    try { await client.quit(); } catch (_) {}
  }
}

module.exports = {
  makeAnalyticsCacheKey,
  resolveTTL,
  getCache,
  setCache,
  invalidatePattern,
  closeRedis,
  TTL,
  get isReady() { return isConnected; },
};
