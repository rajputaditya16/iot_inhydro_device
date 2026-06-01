# InHydro -- IoT-Based Hydroponic Monitoring and Control System

A full-stack IoT platform for real-time hydroponic environment monitoring and automated nutrient dosing. The system combines a Raspberry Pi edge controller with a modern React web dashboard to provide end-to-end visibility and remote control over soil and nutrient parameters.

---

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Hardware Requirements](#hardware-requirements)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [MQTT Topics](#mqtt-topics)
- [Frontend Pages](#frontend-pages)
- [Sensor Thresholds](#sensor-thresholds)
- [Systemd Service](#systemd-service)
- [License](#license)

---

## Overview

InHydro is designed for precision agriculture environments where maintaining optimal soil EC (Electrical Conductivity), pH, temperature, and moisture levels is critical. The system continuously reads sensor data via Modbus RS485, activates dosing relays when parameters drift outside defined setpoints, and streams telemetry to ThingSpeak for cloud storage and visualization. A React-based web dashboard consumes this cloud data to deliver live monitoring, analytics, device management, and remote configuration -- all from any browser.

---

## System Architecture

```
+-------------------+        Modbus RS485        +--------------------+
|  Soil Sensor      | <----------------------->  |  Raspberry Pi      |
|  (Temp, Moisture, |    (Read/Write Registers)  |  (system2.py)      |
|   EC, pH)         |                            |                    |
+-------------------+                            |  GPIO Relays       |
                                                 |  - EC Dosing (x2)  |
                                                 |  - pH Correction   |
                                                 |  - Cyclic Timers   |
                                                 +--------+-----------+
                                                          |
                                          +---------------+---------------+
                                          |                               |
                                   MQTT (ThingSpeak)              MQTT (HiveMQ)
                                   Telemetry Upload               Remote Control
                                          |                               |
                                          v                               v
                                 +------------------+          +-------------------+
                                 | ThingSpeak Cloud |          | HiveMQ Public     |
                                 | (Data Storage)   |          | Broker            |
                                 +--------+---------+          +--------+----------+
                                          ^                             ^
                                          |                             |
                                          |    +------------------+     |
                                          |    |                  |     |
                                          +----+ React Dashboard +-----+
                                   Fetch Data  |   (Frontend)    |  Push Setpoints
                                   (REST API)  |                 |  Sync Config
                                               +------------------+ (WebSocket MQTT)
```

---

## Features

### Edge Controller (Raspberry Pi)

- **Modbus RS485 Sensor Integration** -- Reads temperature, moisture, EC, and pH from industrial soil sensors via the `minimalmodbus` library.
- **Automated EC Dosing** -- Activates two dosing relays when EC drops below the configured minimum and deactivates them when EC reaches the configured maximum.
- **Automated pH Correction** -- Activates a pH dosing relay when pH exceeds the high limit and deactivates it when pH falls to the low limit.
- **Cyclic Timer Relays** -- Three independently configurable cyclic timers with adjustable active windows (start/stop times), ON durations, and OFF durations for irrigation scheduling.
- **Dual MQTT Communication** -- Publishes telemetry data to ThingSpeak every 2 seconds and accepts remote setpoint updates from HiveMQ.
- **Tkinter HMI** -- A fullscreen touchscreen-friendly interface displaying real-time sensor readings, relay statuses, timer states, and an on-screen keypad for local setpoint editing.
- **Persistent Configuration** -- Setpoints are saved to a local JSON file (`setpoints.json`) and loaded on startup.
- **Safety Controls** -- Manual stop button to immediately deactivate all relays, program restart capability, and safe GPIO cleanup on exit via `atexit`.

### Web Dashboard (React Frontend)

- **Admin Dashboard** -- Overview cards showing total locations, total devices, online/offline counts, and active alerts. Live device cards display real-time sensor readings pulled from ThingSpeak.
- **Live Monitoring** -- Dedicated monitoring page with large animated metric displays for temperature, moisture, EC, and pH. Real-time trend charts rendered with Recharts. Automatic 10-second polling with visual "Updated" / "No change" indicators.
- **Device Management** -- Searchable, filterable device table with status badges, battery levels, and navigation to per-device live monitoring.
- **Location Management** -- Grid and table views for managing deployment locations with device counts and active device tracking.
- **Analytics** -- Per-device historical trend charts with time range selection (24h, 7d, 30d), summary statistics (average, min, max), and data export capability.
- **Remote Device Configuration** -- Push EC/pH setpoints and cyclic timer settings directly to the Raspberry Pi over MQTT via WebSocket (HiveMQ). Includes real-time connection status and sync of current device settings.
- **User Management** -- Role-based user table (Admin, Manager, Operator, Viewer) with device and location assignment via modal dialogs.
- **Settings Panel** -- Tabbed interface for profile management, device control, notification preferences, security (password change, 2FA), and appearance (theme, density).
- **Responsive Design** -- Collapsible sidebar navigation with smooth animations, fully responsive layout for desktop and mobile.
- **Loading States** -- Skeleton loaders across all pages for a polished loading experience.

---

## Tech Stack

### Backend (Edge Device)

| Component       | Technology                                   |
|-----------------|----------------------------------------------|
| Language        | Python 3                                     |
| Sensor Protocol | Modbus RTU via `minimalmodbus`               |
| Serial          | `pyserial`                                   |
| GPIO Control    | `gpiozero` with `pigpio` backend             |
| MQTT Client     | `paho-mqtt`                                  |
| Cloud Platform  | ThingSpeak (telemetry), HiveMQ (control)     |
| HMI Framework   | Tkinter with PIL/Pillow for image rendering  |

### Frontend (Web Dashboard)

| Component       | Technology                                   |
|-----------------|----------------------------------------------|
| Framework       | React 19                                     |
| Build Tool      | Vite 7                                       |
| Styling         | Tailwind CSS v4                              |
| Routing         | React Router DOM v7                          |
| Charts          | Recharts                                     |
| Animations      | Framer Motion                                |
| Icons           | Lucide React                                 |
| MQTT Client     | mqtt.js (WebSocket)                          |

---

## Hardware Requirements

- Raspberry Pi (3B+/4/5) with Raspbian OS
- RS485-to-USB adapter (e.g., CH340/FT232)
- Modbus RTU soil sensor (temperature, moisture, EC, pH)
- 3-channel relay module for EC and pH dosing pumps (GPIO 22, 23, 24)
- 4-channel relay module for cyclic timer outputs (GPIO 5, 6, 13, 19)
- 7-inch touchscreen display (recommended for HMI)
- Stable internet connection for MQTT communication

---

## Project Structure

```
IOT_PROJECT/
|-- system2.py              # Raspberry Pi edge controller (sensor, relays, MQTT, HMI)
|-- hmi.service             # systemd unit file for auto-starting the HMI on boot
|-- setpoints.json          # Persisted setpoint configuration (auto-generated)
|-- Frontend/
    |-- index.html          # Application entry point
    |-- package.json        # Dependencies and scripts
    |-- vite.config.js      # Vite build configuration
    |-- src/
        |-- main.jsx        # React DOM root
        |-- App.jsx         # Route definitions
        |-- index.css       # Global styles
        |-- pages/
        |   |-- LoginPage.jsx         # Authentication page
        |   |-- AdminDashboard.jsx    # Main dashboard with stat cards and device overview
        |   |-- LiveMonitoring.jsx    # Real-time sensor metrics and trend charts
        |   |-- DevicesPage.jsx       # Device inventory table
        |   |-- LocationsPage.jsx     # Location management (grid/table views)
        |   |-- AnalyticsPage.jsx     # Historical data analysis and charts
        |   |-- DeviceSettings.jsx    # Remote MQTT device configuration
        |   |-- SettingsPage.jsx      # User settings (profile, notifications, security)
        |   |-- UserManagement.jsx    # Role-based user and access management
        |-- components/
        |   |-- DeviceCard.jsx        # Individual device card with sensor readings
        |   |-- LiveChart.jsx         # Recharts-based live data chart
        |   |-- StatCard.jsx          # Dashboard summary statistic card
        |   |-- Modal.jsx             # Reusable modal dialog
        |   |-- Skeleton.jsx          # Loading skeleton components
        |   |-- EmptyState.jsx        # Empty state placeholder
        |-- layouts/
        |   |-- DashboardLayout.jsx   # Main layout wrapper with sidebar
        |   |-- Sidebar.jsx           # Collapsible navigation sidebar
        |   |-- TopNavbar.jsx         # Top navigation bar
        |-- hooks/
        |   |-- useAnimatedCounter.js # Smooth numeric animation hook
        |-- utils/
        |   |-- helpers.js            # Status colors, metric thresholds, formatting
        |-- data/
            |-- mockData.js           # Mock data for development and demo
```

---

## Getting Started

### Prerequisites

- **Node.js** v18 or higher
- **npm** v9 or higher
- **Python 3.8+** (for edge controller)

### Frontend Setup

```bash
# Navigate to the frontend directory
cd Frontend

# Install dependencies
npm install

# Start the development server
npm run dev
```

The development server will start at `http://localhost:5173` by default.

### Production Build

```bash
cd Frontend
npm run build
npm run preview
```

### Edge Controller Setup (Raspberry Pi)

```bash
# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install minimalmodbus pyserial paho-mqtt gpiozero pigpio Pillow

# Run the controller
python3 system2.py
```

> **Note:** The edge controller requires physical hardware (Modbus sensor, relays, GPIO) and is intended to run exclusively on a Raspberry Pi.

---

## Configuration

### Setpoints (Default Values)

| Parameter        | Default  | Description                          |
|------------------|----------|--------------------------------------|
| `EC_MIN`         | 1200     | EC lower threshold (uS/cm)          |
| `EC_MAX`         | 1800     | EC upper threshold (uS/cm)          |
| `PH_LOW`         | 5.8      | pH lower limit                       |
| `PH_HIGH`        | 6.5      | pH upper limit                       |
| `timer1_start`   | 10:00    | Timer 1 active window start          |
| `timer1_stop`    | 17:00    | Timer 1 active window stop           |
| `timer1_on_min`  | 15       | Timer 1 ON duration (minutes)        |
| `timer1_off_min` | 30       | Timer 1 OFF duration (minutes)       |

Timers 2 and 3 follow the same configuration pattern. All setpoints can be modified locally via the Tkinter HMI or remotely via the web dashboard.

### GPIO Pin Mapping

| GPIO Pin | Function              | Relay Type     |
|----------|-----------------------|----------------|
| 22       | EC Dosing Relay 1     | Active Low     |
| 23       | EC Dosing Relay 2     | Active Low     |
| 24       | pH Correction Relay   | Active Low     |
| 5        | Cyclic Timer Relay 1  | Active High    |
| 6        | Cyclic Timer Relay 2  | Active High    |
| 13       | Cyclic Timer Relay 3  | Active High    |
| 19       | Cyclic Timer Relay 4  | Active High    |

---

## MQTT Topics

### ThingSpeak (Telemetry -- Outbound)

| Topic                                    | Direction | Purpose                      |
|------------------------------------------|-----------|------------------------------|
| `channels/{CHANNEL_ID}/publish`          | Device -> Cloud | Publish sensor telemetry |

Payload format: `field1={temp}&field2={moisture}&field3={ph}&field4={ec}`

### HiveMQ (Remote Control -- Bidirectional)

| Topic                                    | Direction        | Purpose                          |
|------------------------------------------|------------------|----------------------------------|
| `inhydro/device1/setpoints/update`       | Cloud -> Device  | Push new setpoint values         |
| `inhydro/device1/setpoints/current`      | Device -> Cloud  | Publish current setpoint state   |

Payload format: JSON object containing setpoint key-value pairs.

---

## Frontend Pages

| Route          | Page               | Description                                                    |
|----------------|--------------------|----------------------------------------------------------------|
| `/login`       | Login              | Authentication entry point                                     |
| `/dashboard`   | Admin Dashboard    | Overview stats, live device cards with sensor readings          |
| `/monitoring`  | Live Monitoring    | Per-device real-time metrics with animated counters and charts  |
| `/devices`     | Devices            | Searchable device inventory with status filtering              |
| `/locations`   | Locations          | Grid/table view of deployment locations                        |
| `/analytics`   | Analytics          | Historical trend analysis with configurable time ranges        |
| `/users`       | User Management    | Role-based access control and device assignment                |
| `/settings`    | Settings           | Profile, device control, notifications, security, appearance   |

---

## Sensor Thresholds

The dashboard uses the following thresholds for color-coded status indicators:

| Metric       | Normal        | Warning         | Critical          |
|--------------|---------------|-----------------|-------------------|
| Temperature  | <= 35 C       | 35 - 40 C       | > 40 C            |
| Moisture     | >= 40%        | 25% - 40%       | < 25%             |
| EC           | <= 3 mS/cm    | 3 - 4 mS/cm     | > 4 mS/cm         |
| pH           | 5.5 - 7.5     | 4.5 - 5.5 or 7.5 - 8.5 | < 4.5 or > 8.5 |

---

## Systemd Service

The project includes a systemd service unit (`hmi.service`) for auto-starting the HMI application on boot:

```bash
# Copy the service file
sudo cp hmi.service /etc/systemd/system/

# Enable and start the service
sudo systemctl daemon-reload
sudo systemctl enable hmi.service
sudo systemctl start hmi.service

# Check status
sudo systemctl status hmi.service
```

The service is configured with `Restart=always` and `StartLimitIntervalSec=0` to ensure the HMI recovers from any crash or display-manager timing issue.

---

## License

This project is proprietary. All rights reserved.
