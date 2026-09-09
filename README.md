# InHydro: Enterprise IoT Smart Farming, Precision Hydroponics and Environmental Control System

An enterprise-grade, full-stack IoT platform engineered for Controlled Environment Agriculture (CEA), precision commercial hydroponics, multi-zone greenhouse automation, and multi-probe cold storage facilities. The system integrates industrial sensory networks, autonomous closed-loop edge computing, cloud telemetry pipelines, and a high-performance web dashboard for real-time monitoring and centralized operations.

---

## Table of Contents

- [1. Executive Summary and Business Objectives](#1-executive-summary-and-business-objectives)
- [2. High-Level System Architecture](#2-high-level-system-architecture)
- [3. Core Subsystems and Hardware Profiles](#3-core-subsystems-and-hardware-profiles)
- [4. Edge Automation and Firmware Capabilities](#4-edge-automation-and-firmware-capabilities)
- [5. Cloud Infrastructure and Data Security](#5-cloud-infrastructure-and-data-security)
- [6. Operations Web Portal and Management Modules](#6-operations-web-portal-and-management-modules)
- [7. Telemetry Ingestion and Bidirectional Control](#7-telemetry-ingestion-and-bidirectional-control)
- [8. Hardware Specifications and Sensor Interfaces](#8-hardware-specifications-and-sensor-interfaces)
- [9. System Deployment and Operations Guide](#9-system-deployment-and-operations-guide)
- [10. Business Value and Return on Investment (ROI)](#10-business-value-and-return-on-investment-roi)
- [11. Intellectual Property and Commercial Terms](#11-intellectual-property-and-commercial-terms)

---

## 1. Executive Summary and Business Objectives

Commercial precision agriculture and cold chain facilities demand continuous, automated oversight to guarantee peak crop yields, optimize resource consumption, eliminate biological risks, and safeguard perishable assets. 

The InHydro IoT platform provides an end-to-end, autonomous management ecosystem that replaces manual testing and subjective decision-making with precision data analytics and automated control.

```
+---------------------------------------------------------------------------------------------------+
|                                      KEY SYSTEM DELIVERABLES                                      |
+---------------------------------------------------------------------------------------------------+
| 1. Autonomous Fertigation: Closed-loop EC and pH dosing maintaining optimal nutrient levels.      |
| 2. Multi-Zone Climate Management: Real-time cooling, heating, dehumidification, and CO2 control. |
| 3. Cold Storage Protection: Up to 7 independent high-precision probes with 30-second alarm alarms.|
| 4. Precision Irrigation: Multi-channel cyclic timers and customized day/night watering schedules. |
| 5. Zero-Latency Cloud Monitoring: Live telemetry streaming directly to any browser or device.     |
| 6. Compliance and Audit Intelligence: Trend analytics, threshold breach alerts, and CSV exports.  |
| 7. Multi-Tier Governance: SuperAdmin, Admin, and Viewer role-based security access control.        |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. High-Level System Architecture

```
+---------------------------------------------------------------------------------------------------+
|                                      DATA ACQUISITION LAYER                                       |
|                                                                                                   |
|  [Modbus Soil Sensor]   [MD02 Temp/Humi]   [Water EC / pH]   [ORP & CO2]   [Probes S1 - S7]       |
|    (Moisture/EC/pH/T)     (Ambient Air)       (Dosing Tank)    (Disinfection)   (Cold Storage)    |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  | Industrial RS485 Modbus RTU / UART / GPIO
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                       EDGE CONTROLLER LAYER                                       |
|                                                                                                   |
|  Industrial Microprocessor Units & Microcontrollers                                               |
|  - Real-Time Closed-Loop Dosing and Environmental Feedback Control                                |
|  - Multi-Channel High-Power Actuator Relay Control (4 to 32 Relay Channels)                       |
|  - On-Site Fullscreen Touchscreen Interface with Secure Local Override                            |
|  - Fail-Safe Watchdog Protection and Local Offline Buffering                                      |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  | Secure TCP Port 1883 & Encrypted WebSockets
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                    COMMUNICATION & CLOUD LAYER                                    |
|                                                                                                   |
|  [Private Mosquitto MQTT Broker]             [Cloud API & Ingestion Microservices]                |
|  - Authenticated Device Telemetry Topics     - High-Throughput Ingestion Service                  |
|  - Bidirectional Setpoint Push Channels      - Dynamic Per-Device Sharded Time-Series Database    |
|  - Multi-Zone Synchronization Pipelines      - Sub-Second Server-Sent Events (SSE) Engine         |
|                                              - Role-Based Access Control & JWT Security           |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  | HTTPS / REST APIs / Server-Sent Events
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                      FRONTEND WEB DASHBOARD                                       |
|                                                                                                   |
|  Enterprise Responsive Web Application                                                            |
|  - Executive Overview with Status Counters and Health Indicators                                  |
|  - Live Monitoring with Animated Metric Gauges and Real-Time Charts                               |
|  - Multi-Zone Greenhouses and Cold Storage Facility Management                                    |
|  - Remote Equipment Setpoint and Schedule Configuration Center                                    |
|  - Historical Analytics Engine with Anomaly Detection and One-Click CSV Export                    |
|  - Multi-Organization Governance, User Management, and Hardware Provisioning                      |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Core Subsystems and Hardware Profiles

The InHydro platform provides specialized hardware configurations engineered for distinct agricultural and storage facilities:

### 3.1 InHydro Almora Hydroponics Subsystem
- **Purpose**: Precision hydroponic nutrient dosing and primary grow-room climate control.
- **Sensory Inputs**: Industrial Submersible Water EC & pH sensors, MD02 Ambient Temperature & Humidity probe.
- **Actuator Outputs**:
  - Dosing Pump A (Nutrient Part A)
  - Dosing Pump B (Nutrient Part B)
  - pH Correction Pump (Acid/Base Buffer)
  - Grow-Room Climate Cooling Unit
  - Grow-Room Dehumidifier Unit
  - Cyclic Irrigation Circuit 1
  - Cyclic Irrigation Circuit 2
- **On-Site Display**: Fullscreen touch interface with real-time numeric readouts, parameter gauges, and on-screen keypad for local setpoint adjustments.

### 3.2 InHydro Monit Precision Water Chemistry and Dosing Subsystem
- **Purpose**: Dedicated water treatment, batch fertigation, and reservoir conditioning.
- **Sensory Inputs**: High-precision dual-channel water chemistry transmitters (Electrical Conductivity and pH) and ambient climate sensors.
- **Actuator Outputs**: Industrial 16-channel Modbus RTU relay bank managing primary dosing lines, mixing pumps, purge valves, and circulation loops.
- **Control Strategy**: Millisecond-accurate dosing pulse widths with programmable hysteresis bands to eliminate overshoot and nutrient burn.

### 3.3 InHydro Office Control: 3-Zone Commercial Greenhouse Automation
- **Purpose**: Large-scale greenhouse automation managing up to three independent climate and fertigation zones.
- **Zone Architecture**:
  - **Zone 1 (Grow Zone A)**: Soil Sensor (Moisture, Soil Temp, EC, pH), MD02 Climate Sensor, ORP Sensor, CO2 Sensor, Relay Outputs 1 to 8.
  - **Zone 2 (Grow Zone B)**: Soil Sensor (Moisture, Soil Temp, EC, pH), MD02 Climate Sensor, ORP Sensor, CO2 Sensor, Relay Outputs 17 to 24.
  - **Zone 3 (Specialized Climate Zone)**: Dual redundant MD02 Climate Sensors, CO2 Sensor, Relay Outputs 25 to 32 (Dual-stage AC cooling, dual dehumidifiers, and auxiliary circulation circuits).
- **Operation**: Supports synchronized Day/Night temperature curves, humidity triggers, and multi-channel irrigation schedules.

### 3.4 InHydro Cold Storage and Perishable Inventory Protection Subsystem
- **Purpose**: Multi-room cold storage temperature tracking, freezer monitoring, and automated alarm dispatch.
- **Sensory Inputs**: Up to 7 independent Modbus RS485 temperature and humidity probes distributed across multiple cold rooms or chambers.
- **Actuator Outputs**: 14 actuator channels (cooling unit and humidifier control per room) and a dedicated 30-second audible hardware buzzer.
- **Operating Modes**:
  - **Static Mode**: Continuous threshold monitoring against fixed minimum and maximum limits.
  - **Calendar-Scheduled Mode**: Multi-setting presets (Settings A through E) mapped to custom date ranges with 5 programmable time slots per day.
- **Safety System**: Immediate visual warning and automated physical buzzer activation upon temperature or humidity deviation.

### 3.5 InHydro 17-Factor Environmental and Agronomy Station
- **Purpose**: Comprehensive agronomic research and climate analytics.
- **Monitored Parameters**: Water Temperature, Water Moisture, Water EC, Water pH, Ambient Temperature, Ambient Humidity, ORP, CO2, Vapor Pressure Deficit (VPD), Daily Light Integral (DLI), Wind Speed, Wind Direction, Dissolved Oxygen (DO), Photosynthetic Photon Flux Density (PPFD), and Soil N-P-K (Nitrogen, Phosphorus, Potassium).

### 3.6 InHydro Standalone Soil Station
- **Purpose**: Low-power standalone soil monitoring for nursery beds and open-field plots.
- **Sensory Inputs**: 4-in-1 Soil probe measuring Moisture, Soil Temperature, EC, and pH.
- **Display**: High-resolution HDMI output for direct field-level observation.

### 3.7 InHydro Actuator and Power Control Unit
- **Purpose**: Wireless peripheral actuator automation for supplemental grow lighting, circulation fans, and booster pumps.
- **Features**: Dual Manual and Autonomous operation modes, weekday filtering schedules, and network clock synchronization.

---

## 4. Edge Automation and Firmware Capabilities

### 4.1 Industrial Modbus RS485 Communication
- **Standard**: Modbus RTU protocol over shielded twisted-pair cabling.
- **Reliability**: Deterministic polling cycles with hardware-level port mapping, preventing sensor channel crosstalk during power cycles.

### 4.2 Closed-Loop Control Algorithms
- **EC Optimization**: Continuous monitoring triggers dosing pumps when nutrient levels fall below target minimums and automatically disengages once target concentrations are restored.
- **pH Stabilization**: Closed-loop acid/base dosing maintains the ideal nutrient absorption window (pH 5.8 - 6.5).
- **Anti-Chatter Protection**: Programmable deadbands and minimum dwell times protect mechanical contactors, pumps, and compressors from rapid cycling.
- **Time-Windowed Irrigation**: Equipment cycles through precise ON and OFF durations only within authorized operational hours.

### 4.3 Offline Data Buffering and Automatic Recovery
In the event of an internet or cloud network interruption:
- All sensor metrics are buffered securely to local persistent edge storage.
- An automated reconnection engine monitors network availability.
- Upon reconnection, buffered historical records are uploaded in synchronized batches to ensure zero data loss.

---

## 5. Cloud Infrastructure and Data Security

### 5.1 Dynamic Telemetry Database
- **High-Performance Sharding**: Sensor data is organized into dedicated per-device telemetry collections, ensuring continuous high write throughput without table locks.
- **Optimized Indexing**: Time-series compound indexing enables instant data retrieval across millions of historical records.

### 5.2 Real-Time Telemetry Pipeline
- **Server-Sent Events (SSE)**: Delivers sub-second telemetry updates to client dashboards with minimal network overhead.
- **Connection Health**: Integrated 15-second heartbeat pings prevent reverse proxies and cloud gateways from terminating active monitoring sessions.

### 5.3 Three-Tier Role-Based Access Governance

| Role | Scope | Functional Permissions |
| :--- | :--- | :--- |
| **SuperAdmin** | Global Platform | System-wide visibility, creation and management of Organization Admins, device quota allocation, global hardware assignment, and infrastructure auditing. |
| **Admin** | Organization / Facility | Management of operational user accounts, live device monitoring, historical analytics, remote setpoint configuration via MQTT, and CSV report downloads. |
| **Viewer / Operator** | Assigned Devices Only | Read-only live telemetry monitoring and historical chart views for explicitly authorized farm zones and devices. |

---

## 6. Operations Web Portal and Management Modules

### 6.1 Executive Dashboard
- Comprehensive status cards displaying total active facilities, registered devices, online/offline status, and critical alerts.
- Live device grid displaying immediate sensor values and connection health.

### 6.2 Real-Time Monitoring Center
- Animated metric widgets for Temperature, Moisture, Electrical Conductivity, and pH with threshold-aware color coding.
- Dynamic multi-room switcher for multi-zone greenhouse installations.
- Multi-probe Cold Storage visualization with independent temperature status indicators for each room.
- Interactive live trendline charts displaying real-time parameter movements.

### 6.3 Historical Analytics and Audit Engine
- Flexible time-range filtering: Last 24 Hours, Last 7 Days, Last 30 Days, or Custom Date Ranges.
- Statistical computation: Minimum, Maximum, Mean, and Standard Deviation.
- Threshold breach counters identifying environmental anomalies and compliance deviations.
- Instant client-side CSV export generating formatted spreadsheets for compliance audits and agronomy reports.

### 6.4 Remote Device Configuration Center
- Centralized setpoint management: Update EC targets, pH limits, temperature curves, humidity triggers, and cyclic timer intervals remotely.
- Live synchronization verification: Confirms when physical edge controllers have received and applied new setpoints.

---

## 7. Telemetry Ingestion and Bidirectional Control

### 7.1 Ingestion Topics and Data Feeds

| Topic Channel | Direction | Functional Purpose |
| :--- | :--- | :--- |
| `Device Telemetry Feed` | Device -> Cloud | Real-time transmission of primary sensor metrics. |
| `Multi-Zone Greenhouse Feed` | Device -> Cloud | Consolidated multi-zone greenhouse telemetry. |
| `Cold Storage Probe Array` | Device -> Cloud | Multi-channel temperature and humidity records. |
| `Remote Setpoint Update` | Cloud -> Device | Push updated operational setpoints to physical hardware. |
| `Configuration Synchronization` | Device <-> Cloud | Bi-directional verification of active device parameters. |

### 7.2 Sample Data Structures

#### Multi-Zone Greenhouse Record:
```json
{
  "zone1": {
    "soil": { "soil_temp": 24.2, "moisture": 68.5, "ec": 1.45, "ph": 6.2 },
    "climate": { "room_temp": 26.1, "room_humi": 62.0 },
    "orp": 380,
    "co2": 720
  },
  "zone2": {
    "soil": { "soil_temp": 23.8, "moisture": 64.0, "ec": 1.50, "ph": 6.1 },
    "climate": { "room_temp": 25.4, "room_humi": 60.5 },
    "orp": 375,
    "co2": 705
  },
  "zone3": {
    "sensor_a": { "room_temp": 18.5, "room_humi": 85.0 },
    "sensor_b": { "room_temp": 18.6, "room_humi": 84.8 },
    "co2": 650
  }
}
```

#### Cold Storage Multi-Probe Record:
```json
{
  "probe_1": { "temperature": 4.2, "humidity": 88.5 },
  "probe_2": { "temperature": 3.9, "humidity": 89.1 },
  "probe_3": { "temperature": 4.0, "humidity": 87.8 },
  "probe_4": { "temperature": 4.5, "humidity": 86.4 },
  "probe_5": { "temperature": 4.1, "humidity": 88.0 },
  "probe_6": { "temperature": 3.8, "humidity": 90.2 },
  "probe_7": { "temperature": 22.4, "humidity": 65.0 }
}
```

---

## 8. Hardware Specifications and Sensor Interfaces

### 8.1 Environmental and Agricultural Sensor Specifications

| Parameter | Measurement Range | Resolution / Accuracy | Sensor Technology |
| :--- | :--- | :--- | :--- |
| **Water Electrical Conductivity (EC)** | 0 - 20,000 uS/cm | 1 uS/cm (+/- 1% FS) | Modbus RS485 Submersible Electrode |
| **Water pH** | 0.0 - 14.0 pH | 0.01 pH (+/- 0.05 pH) | Modbus RS485 Glass Composite Electrode |
| **Soil Moisture** | 0 - 100% Volumetric | 0.1% (+/- 2%) | Frequency Domain Reflectometry (FDR) |
| **Soil Temperature** | -40 to +80 deg C | 0.1 deg C (+/- 0.5 deg C) | Embedded Platinum RTD Probe |
| **Ambient Air Temperature** | -40 to +80 deg C | 0.1 deg C (+/- 0.3 deg C) | MD02 Industrial Modbus Transmitter |
| **Relative Humidity** | 0 - 100% RH | 0.1% (+/- 3% RH) | Capacitive Humidity Polymer |
| **Carbon Dioxide (CO2)** | 0 - 5,000 ppm | 1 ppm (+/- 50 ppm) | Non-Dispersive Infrared (NDIR) |
| **Oxidation-Reduction Potential (ORP)**| -1000 to +1000 mV | 1 mV (+/- 5 mV) | Platinum Band Modbus Probe |

---

## 9. System Deployment and Operations Guide

### 9.1 Infrastructure Deployment Overview
The platform supports modular deployment across local edge controllers, private enterprise servers, and cloud environments.

```
+---------------------------------------------------------------------------------------------------+
|                                      DEPLOYMENT WORKFLOW                                          |
+---------------------------------------------------------------------------------------------------+
| Step 1: Deploy Cloud Microservices (Node.js API, MongoDB Database, and Mosquitto Broker).         |
| Step 2: Build and publish the Web Dashboard client application to cloud hosting.                  |
| Step 3: Commission Edge Controller hardware, configure serial buses, and assign Device IDs.       |
| Step 4: Configure systemd auto-start daemons for unattended edge operation on system boot.        |
| Step 5: Provision Organization Admins and assign device access scopes via the SuperAdmin portal.  |
+---------------------------------------------------------------------------------------------------+
```

### 9.2 Edge Controller Auto-Start Daemon
Edge hardware units run as dedicated Linux background services with automatic recovery upon power interruption:

```
Service Name:    InHydro Edge HMI Service
Execution Mode:  Autonomous Boot via systemd
Restart Policy:  Always Restart with zero startup delay
Display Mode:    Direct Framebuffer / X11 Fullscreen Touch Interface
```

---

## 10. Business Value and Return on Investment (ROI)

Implementing the InHydro IoT platform delivers direct, quantifiable operational and financial advantages:

1. **Labor Reduction**: Automates continuous water testing, chemical dosing, and manual valve switching, saving hundreds of labor hours annually per facility.
2. **Nutrient and Water Efficiency**: Precision EC dosing prevents over-fertilization, cutting commercial nutrient costs by up to 30% while preserving water supplies.
3. **Crop Yield and Quality Protection**: Closed-loop stabilization eliminates nutrient toxicity, root burn, and thermal shock, maximizing crop uniformity and market value.
4. **Cold Chain Risk Mitigation**: Continuous temperature surveillance with audible and digital alarms eliminates spoilage risks in cold storage facilities.
5. **Data-Driven Agronomy**: Comprehensive historical records enable data-driven optimization of crop recipes, harvest cycles, and resource forecasting.

---

## 11. Intellectual Property and Commercial Terms

Copyright (c) InHydro Technologies. All rights reserved.

This software platform, edge firmware, hardware interface architecture, and associated documentation are proprietary commercial assets. Unauthorized reproduction, reverse engineering, redistribution, or modification of any part of this system is strictly prohibited without prior written authorization.
