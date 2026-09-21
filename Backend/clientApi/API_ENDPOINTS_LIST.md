# 🌿 InHydro Client API — Complete Endpoints List

> **Base URL (Local):** `http://localhost:5000/api/client`  
> **Base URL (Production):** `https://<YOUR_DEPLOYED_DOMAIN>/api/client`  
> **Default API Key:** `inhydro_ai_dataset_key_2026` *(Configurable via `CLIENT_API_KEY` in `.env`)*  
> **Auth Header:** `x-api-key: inhydro_ai_dataset_key_2026` OR `?apiKey=inhydro_ai_dataset_key_2026`

---

## 📑 Summary Table of All Endpoints

| # | Endpoint URL | Method | Purpose & Description | Output Format |
| :-: | :--- | :-: | :--- | :-: |
| **1** | `/api/client/devices` | `GET` | **Device Discovery:** Returns a list of all active registered IoT hardware devices, locations, assigned crops, and metadata. | `JSON` |
| **2** | `/api/client/dataset/metadata` | `GET` | **AI Discovery & Stats:** Returns total record count across database, earliest/latest timestamps per device, and 44 standard ML feature columns. | `JSON` |
| **3** | `/api/client/dataset/all-devices` | `GET` | **Bulk All-Devices Dataset:** Consolidated time-series training data from all devices. Supports date filtering, column slicing, and full dumps. | `JSON` |
| **4** | `/api/client/dataset` *(Alias)* | `GET` | Alias to `/api/client/dataset/all-devices`. | `JSON` |
| **5** | `/api/client/data` *(Alias)* | `GET` | Short alias to `/api/client/dataset/all-devices`. | `JSON` |
| **6** | `/api/client/dataset/device/:idOrMqttId` | `GET` | **Single Device Dataset:** Detailed time-series dataset for a single target device (searched by `_id`, `mqttId`, or `name`). | `JSON` |
| **7** | `/api/client/device/:idOrMqttId` *(Alias)* | `GET` | Short alias to `/api/client/dataset/device/:idOrMqttId`. | `JSON` |

---

## 🔐 Authentication Guide

All endpoints require authentication. Choose any one of the following methods:

1. **Header (Recommended):**
   ```http
   x-api-key: inhydro_ai_dataset_key_2026
   ```
2. **Alternative Header:**
   ```http
   x-client-key: inhydro_ai_dataset_key_2026
   ```
3. **Bearer Token:**
   ```http
   Authorization: Bearer inhydro_ai_dataset_key_2026
   ```
4. **Query Parameter:**
   ```http
   ?apiKey=inhydro_ai_dataset_key_2026
   ```

---

## 🛠️ Detailed Endpoint Documentation & Examples

---

### 1️⃣ Device Discovery List
Get a summary list of all registered devices with their hardware IDs, online status, crop details, and setup types.

- **URL:** `GET /api/client/devices`
- **Auth Required:** Yes
- **Query Parameters:** None

#### cURL Request:
```bash
curl -H "x-api-key: inhydro_ai_dataset_key_2026" \
  http://localhost:5000/api/client/devices
```

#### Sample JSON Response:
```json
{
  "success": true,
  "count": 2,
  "data": [
    {
      "_id": "6aabcde9ee26d49d6e7f1729",
      "name": "Polyhouse Lab Sector 4",
      "location": "Polyhouse Sector 4",
      "status": "online",
      "deviceType": "office_control",
      "mqttId": "system2",
      "cropName": "Cherry Tomato",
      "setupName": "NFT Hydroponics",
      "lastUpdated": "2026-09-19T08:00:00.000Z",
      "createdAt": "2026-01-10T00:00:00.000Z"
    },
    {
      "_id": "6aabcde9ee26d49d6e7f1730",
      "name": "Chamber Cold Storage 1",
      "location": "Almora Storage Hub",
      "status": "online",
      "deviceType": "multi_sensor",
      "mqttId": "control123",
      "cropName": "Apples",
      "setupName": "Cold Storage",
      "lastUpdated": "2026-09-19T08:00:00.000Z",
      "createdAt": "2026-01-15T00:00:00.000Z"
    }
  ]
}
```

---

### 2️⃣ AI Pipeline Metadata & Discovery
Scans all dynamic per-device collections and returns overall dataset volume, timestamps range, and list of ML feature names.

- **URL:** `GET /api/client/dataset/metadata`
- **Auth Required:** Yes
- **Query Parameters:** None

#### cURL Request:
```bash
curl -H "x-api-key: inhydro_ai_dataset_key_2026" \
  http://localhost:5000/api/client/dataset/metadata
```

#### Sample JSON Response:
```json
{
  "success": true,
  "totalDevices": 10,
  "totalSystemRecords": 45112,
  "allFeatureColumns": [
    "timestamp", "device_id", "device_mqtt_id", "device_name", "device_type",
    "location", "crop_name", "setup_name", "room", "water_temp", "soil_moisture",
    "ec", "ph", "room_temp", "room_humidity", "co2", "orp", "vpd", "dli",
    "wind_speed", "wind_direction", "dissolved_oxygen", "ppfd", "nitrogen",
    "phosphorus", "potassium", "sensor1_temp", "sensor1_humidity", "sensor2_temp",
    "sensor2_humidity", "chamber1_temp", "chamber1_humidity", "chamber2_temp",
    "chamber2_humidity", "chamber3_temp", "chamber3_humidity", "chamber4_temp",
    "chamber4_humidity", "chamber5_temp", "chamber5_humidity", "chamber6_temp",
    "chamber6_humidity", "chamber7_temp", "chamber7_humidity"
  ],
  "devices": [
    {
      "deviceId": "6aabcde9ee26d49d6e7f1729",
      "deviceName": "Polyhouse Lab Sector 4",
      "deviceMqttId": "system2",
      "deviceType": "office_control",
      "location": "Polyhouse Sector 4",
      "cropName": "Cherry Tomato",
      "setupName": "NFT Hydroponics",
      "totalRecords": 18450,
      "earliestRecord": "2026-01-01T00:00:15.000Z",
      "latestRecord": "2026-09-19T06:50:00.000Z"
    }
  ]
}
```

---

### 3️⃣ Bulk AI Dataset (All Devices)
Consolidated chronological time-series records across all or selected devices in clean JSON format.

- **Primary URL:** `GET /api/client/dataset/all-devices`
- **Aliases:** `GET /api/client/dataset`, `GET /api/client/data`
- **Auth Required:** Yes

#### Supported Query Parameters:

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `all` | Boolean | `false` | When `all=true`, ignores limits and dumps all historical data |
| `limit` | Number/String | `50000` | Max rows returned. Use `all` or `0` for full dataset dump |
| `page` | Number | `1` | Pagination page number |
| `start` | ISO Date String | `null` | Start timestamp filter (e.g. `2026-09-01T00:00:00Z`) |
| `end` | ISO Date String | `null` | End timestamp filter (e.g. `2026-09-19T23:59:59Z`) |
| `devices` | String | `null` | Comma-separated list of target device IDs or MQTT IDs |
| `deviceType` | String | `null` | Filter by type (`office_control`, `controlling`, `multi_sensor`, `monit`) |
| `fields` | String | `null` | Comma-separated list of feature columns to return |

#### Example 3.1 — Fetch 100 Records in JSON:
```bash
curl -H "x-api-key: inhydro_ai_dataset_key_2026" \
  "http://localhost:5000/api/client/dataset/all-devices?limit=100"
```

#### Example 3.2 — Fetch Entire Historical Dataset:
```bash
curl -H "x-api-key: inhydro_ai_dataset_key_2026" \
  "http://localhost:5000/api/client/dataset/all-devices?all=true"
```

#### Example 3.3 — Filter by Date Range and Specific Columns:
```bash
curl -H "x-api-key: inhydro_ai_dataset_key_2026" \
  "http://localhost:5000/api/client/dataset/all-devices?start=2026-09-01T00:00:00Z&end=2026-09-19T23:59:59Z&fields=water_temp,soil_moisture,ec,ph,room_temp,room_humidity"
```

---

### 4️⃣ Single Device AI Dataset
Retrieves chronological time-series records for a specific single device in JSON format. The device parameter `:idOrMqttId` can be MongoDB `_id`, `mqttId` (e.g. `system2`, `control123`), or device `name`.

- **Primary URL:** `GET /api/client/dataset/device/:idOrMqttId`
- **Alias:** `GET /api/client/device/:idOrMqttId`
- **Auth Required:** Yes

#### Supported Query Parameters:
- `all`: `true` for entire history
- `limit`: Max records (default `50000`)
- `start` / `end`: ISO timestamp filters
- `fields`: Comma-separated feature columns

#### Example 4.1 — Single Device Query:
```bash
curl -H "x-api-key: inhydro_ai_dataset_key_2026" \
  "http://localhost:5000/api/client/dataset/device/system2?limit=50"
```

#### Example 4.2 — Single Device Complete History:
```bash
curl -H "x-api-key: inhydro_ai_dataset_key_2026" \
  "http://localhost:5000/api/client/dataset/device/control123?all=true"
```

---

## ⚡ Quick Testing Command

Run the automated test runner in the terminal to verify all endpoints at once:

```powershell
cd Backend
node test_client_api.js
```

---

## 📁 File Structure in `Backend/clientApi`

```text
Backend/clientApi/
├── API_ENDPOINTS_LIST.md    # 👈 Complete JSON API reference document
├── clientApiAuth.js         # API Key security & middleware validation
├── clientApiController.js   # Fast parallel query execution & JSON engine
├── clientApiRoutes.js       # Route definitions & aliases
└── featureExtractor.js      # 44-Column ML feature normalization engine
```
