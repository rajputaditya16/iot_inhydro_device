# 📡 InHydro — MQTT Direct Data Storage & Analytics Plan

> **Goal:** ThingSpeak hatao, MQTT ka per-second live data seedha MongoDB mein store karo aur analytics ke liye wahi data use karo.
> **Type:** Architecture & Logic Document (No Code)
> **Date:** 10 June 2026

---

## 🔍 Problem Statement

| | Abhi (Current) | Naya (Proposed) |
|---|---|---|
| **Live Data Source** | HiveMQ MQTT (per second) | HiveMQ MQTT (per second) ✅ Same |
| **Analytics Data Source** | ThingSpeak REST API (35s delay) | MongoDB (real-time, no delay) ✅ Better |
| **Data Consistency** | Dono sources alag hain ❌ | Ek hi source ✅ |
| **Data Loss Risk** | ThingSpeak rate limit pe reject hota hai ❌ | Har message store hoga ✅ |
| **CSV Export** | ThingSpeak se limited data | MongoDB se full historical data ✅ |

---

## 🏗️ New Architecture (Big Picture)

```
Raspberry Pi (Device)
       │
       │  MQTT Publish (every 1 second)
       │  Topic: inhydro/{device}/room{1,2}/telemetry/live
       │
       ▼
  HiveMQ Broker (broker.hivemq.com)
       │
       ├──────────────────────────────────────────────────────┐
       │                                                      │
       ▼                                                      ▼
  Frontend (React)                                    Backend (Node.js)
  Live Monitoring Page                                New MQTT Subscriber
  (WebSocket — already working)                       (Subscribe karo same topic)
                                                             │
                                                             │  On every message received
                                                             ▼
                                                      MongoDB Database
                                                      (New Collection: "telemetry_logs")
                                                             │
                                                             ▼
                                                      Analytics Page (React)
                                                      REST API se fetch karo
                                                      from Backend
```

---

## 🧩 Logic — Step by Step

### STEP 1 — Backend mein MQTT Subscriber banana

**Kya hoga:**
Backend (Node.js server) start hote hi HiveMQ broker se connect karega aur yeh topics subscribe karega:
- `inhydro/+/room1/telemetry/live`
- `inhydro/+/room2/telemetry/live`

`+` ka matlab wildcard hai — iska matlab **kisi bhi device ka** data capture hoga automatically.

**Logic:**
- Jab bhi Pi se koi MQTT message aaye → backend us message ko receive karega
- Message mein device name bhi hoga, room bhi hoga, aur sensor data bhi
- Backend us message ko parse karega aur MongoDB mein save karega

---

### STEP 2 — MongoDB mein naya Collection banana

**Collection name:** `telemetry_logs`

**Har ek document (record) mein yeh store hoga:**

| Field | Description |
|---|---|
| `deviceId` | Kaun sa device hai (e.g., "system1") |
| `room` | Room 1 ya Room 2 |
| `timestamp` | Exact time jab data aaya (automatic) |
| `water_temp` | Paani ka temperature (°C) |
| `moisture` | Moisture percentage |
| `ec` | EC value (mS/cm, scaled) |
| `ph` | pH value |
| `room_temp` | Room ka temperature |
| `room_humi` | Room ki humidity |
| `orp` | ORP mV |
| `co2` | CO2 ppm |
| `relay_status` | Konse relays ON/OFF hain |
| `timer_state` | Timers ka current state |

**Data kitna aayega?**
- Per second: 1 record
- Per minute: 60 records
- Per hour: 3,600 records
- Per day: 86,400 records
- Per month: ~26 lakh records

> ⚠️ **Important:** Har second ka data store karna bahut zyada hoga. Isliye hum sampling karenge — har **10 second** mein ek record save karenge. Isse per day ~8,640 records = manageable.

---

### STEP 3 — Data Retention (Purana Data Kab Delete Karo)

Unlimited data rakhna MongoDB storage ko bhar dega. Isliye:

**Rule:** Jo data **30 days** se purana ho, woh automatically delete ho jaye.

**Kaise:**
- MongoDB mein ek **TTL Index** (Time-To-Live) lagao `timestamp` field pe
- MongoDB apne aap 30 din se purane records delete karta rehega — koi manual kaam nahi

---

### STEP 4 — Backend API Routes banana (Analytics ke liye)

Frontend ko data dene ke liye kuch naye API endpoints banane honge:

**Endpoint 1 — Historical Data Fetch**
- Frontend yeh API call karega: "Mujhe device X ke room 1 ka last 24 ghante ka data do"
- Backend MongoDB mein query lagayega aur data return karega
- Filter options: device, room, time range (1h / 6h / 24h / 7d / 30d / custom dates)

**Endpoint 2 — Statistics**
- Frontend yeh maange: "Mujhe EC ka min/max/avg do last 7 din mein"
- Backend MongoDB aggregation se calculate karega aur directly stats return karega
- Is se frontend pe koi heavy calculation nahi karni padegi

**Endpoint 3 — CSV Export**
- Frontend yeh maange: "Mujhe CSV file chahiye last 7 din ka"
- Backend MongoDB se data nikale, CSV format mein convert kare, aur file response mein bheje
- User ke browser mein seedha download ho jaye

---

### STEP 5 — Frontend Analytics Page Update

**Abhi:** Analytics page ThingSpeak API call karta hai

**Naya:** Analytics page apna Backend API call karega

**Kya dikhega Analytics page pe:**

1. **Time Range Selector** — 1 hour / 6 hours / 24 hours / 7 days / 30 days / Custom
2. **Device + Room Selector** — Kaun sa device, kaun sa room
3. **Live Charts** — Recharts se same charts, but data MongoDB se
4. **Statistics Cards** — Min / Max / Avg / Std Dev har sensor ke liye
5. **Breach Count** — Kitni baar EC / pH setpoint se bahar gaya
6. **Download CSV Button** — Backend se CSV file download

---

## 📋 Kya Kya Banana Padega

### Backend Changes (3 cheezein)

| # | Kya Banana Hai | File / Location |
|---|---|---|
| 1 | MQTT Subscriber (HiveMQ connect + subscribe) | `Backend/utils/mqttSubscriber.js` (new file) |
| 2 | MongoDB Model (telemetry_logs collection) | `Backend/models/TelemetryLog.js` (new file) |
| 3 | API Routes (data fetch, stats, CSV) | `Backend/routes/telemetryRoutes.js` (new file) |
| 4 | server.js mein subscriber ko start karna | `Backend/server.js` (small change) |

### Frontend Changes (1 file)

| # | Kya Banana Hai | File |
|---|---|---|
| 1 | ThingSpeak calls hato, Backend API calls lao | `Frontend/src/pages/AdminDashboard/AnalyticsPage.jsx` |

### Python Script Changes

> **Kuch nahi.** Pi script waise hi chalti rahegi — same MQTT publish karte rehna.

---

## ⚡ Data Flow (Final — Naya System)

```
Pi Device
  │
  │  MQTT Publish (every 1 sec)
  ▼
HiveMQ Broker
  │
  ├── WebSocket ──► React Frontend (Live Monitoring) ── koi change nahi
  │
  └── TCP ──────► Node.js Backend (MQTT Subscriber)
                      │
                      │  Every 10 seconds — save to DB
                      ▼
                  MongoDB (telemetry_logs)
                      │
                      │  REST API
                      ▼
                  React Frontend (Analytics Page)
                      │
                      ├── Charts (Recharts)
                      ├── Statistics Cards
                      └── CSV Download
```

---

## ✅ Fayde (Advantages)

| Feature | ThingSpeak (Purana) | MongoDB (Naya) |
|---|---|---|
| Data delay | 35 seconds | 10 seconds |
| Data loss on rate limit | Haan ❌ | Nahi ✅ |
| Custom time range | Limited | Koi bhi range ✅ |
| CSV export | Manual ya 3rd party | Direct from backend ✅ |
| Statistics | Frontend pe calculate | Backend se ready ✅ |
| Relay + Timer state | Nahi ❌ | Haan ✅ |
| Storage control | ThingSpeak ke haath | Apne haath ✅ |
| Internet dependency | ThingSpeak cloud pe | Apna server ✅ |

---

## ⚠️ Important Considerations

> **1. Storage Size**
> Agar har second save karo → 1 month mein ~7.5 crore records. Isliye **10-second sampling + 30-day TTL** mandatory hai.

> **2. HiveMQ Public Broker**
> Abhi `broker.hivemq.com` public broker hai — matlab koi bhi subscribe kar sakta hai. Production mein private broker use karna better hoga (HiveMQ Cloud free tier ya self-hosted Mosquitto).

> **3. Backend Server**
> Backend 24/7 chalna chahiye tabhi MQTT subscriber kaam karega. Local development mein koi dikkat nahi, production mein server pe deploy karna hoga.

> **4. Multiple Devices**
> Wildcard topic subscribe karne se saare devices ka data ek hi collection mein aayega — `deviceId` se filter karke har device ka alag data dekh sakte ho.

---

## 🗺️ Summary

```
SIMPLE WORDS MEIN:

  Backend ek listener banayega →
  Jo HiveMQ pe baitha rahega →
  Pi jo bhi data bheje, wo sun leta hai →
  Har 10 second mein ek record MongoDB mein save karta hai →
  Analytics page Backend API se data maangta hai →
  Charts, Stats, CSV — sab wahan se aata hai →
  ThingSpeak ki zaroorat nahi
```

---

*Ready to implement? Code likhna shuru karein — batao!*
