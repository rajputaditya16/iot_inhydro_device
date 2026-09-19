#!/usr/bin/env python3
import time
import minimalmodbus
import threading
import json
import os
import datetime
import copy
import re
import queue
from collections import deque
import subprocess
import socket
import fcntl
import glob
import sys
import tkinter as tk
from tkinter import font, ttk, messagebox
import paho.mqtt.client as mqtt
from PIL import Image, ImageTk

# -----------------------------------------------------------------------------
# BASE PATHS & DEVICE IDENTITY
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                val = f.read().strip()
                if val: return val
        except Exception: pass
    return "itc_polyhouse"

DEVICE_NAME = get_device_id()
CONFIG_FILE = os.path.join(BASE_DIR, "config_itc.json")
SETPOINTS_FILE = os.path.join(BASE_DIR, "setpoints_itc.json")
DLI_FILE = os.path.join(BASE_DIR, "dli_history_itc.json")
ALARM_LOG_FILE = os.path.join(BASE_DIR, "alarm_history.jsonl")
LOG_DIR = os.path.join(BASE_DIR, "local_logs")
ACTIVE_LOG_FILE = os.path.join(LOG_DIR, "active.jsonl")

# -----------------------------------------------------------------------------
# MODBUS & HARDWARE CHANNEL MAPPING
# -----------------------------------------------------------------------------
SLAVE_ID = 1
BAUDRATE = 4800
RELAY_BAUD = 9600
DELAY_BETWEEN_PORTS = 0.2

ALL_POLYHOUSES = ["PH-01", "PH-02", "PH-03", "PH-04", "PH-05", "PH-06"]
ACTIVE_POLYHOUSES = ["PH-01", "PH-02", "PH-03", "PH-04", "PH-05"]

# Serial USB Ports for Temp & RH Sensors
SENSOR_MAP = {
    "PH-01": "/dev/serial/by-path/usb-itc-ph01",
    "PH-02": "/dev/serial/by-path/usb-itc-ph02",
    "PH-03": "/dev/serial/by-path/usb-itc-ph03",
    "PH-04": "/dev/serial/by-path/usb-itc-ph04",
    "PH-05": "/dev/serial/by-path/usb-itc-ph05",
    "PH-06": "/dev/serial/by-path/usb-itc-ph06"
}

# Dedicated CO2 Sensor Ports for PH-01 to PH-05
CO2_SENSOR_MAP = {
    "PH-01": "/dev/serial/by-path/usb-itc-co2-ph01",
    "PH-02": "/dev/serial/by-path/usb-itc-co2-ph02",
    "PH-03": "/dev/serial/by-path/usb-itc-co2-ph03",
    "PH-04": "/dev/serial/by-path/usb-itc-co2-ph04",
    "PH-05": "/dev/serial/by-path/usb-itc-co2-ph05"
}

# Dedicated PAR (PPFD) Sensor Ports for PH-01 to PH-05
PAR_SENSOR_MAP = {
    "PH-01": "/dev/serial/by-path/usb-itc-par-ph01",
    "PH-02": "/dev/serial/by-path/usb-itc-par-ph02",
    "PH-03": "/dev/serial/by-path/usb-itc-par-ph03",
    "PH-04": "/dev/serial/by-path/usb-itc-par-ph04",
    "PH-05": "/dev/serial/by-path/usb-itc-par-ph05"
}

RELAY_PORT_FIXED = "/dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.2.7:1.0-port0"
POSSIBLE_RELAY_IDS = [1, 255, 2, 0, 3]
working_relay_id = None

# Waveshare 32-Channel Modbus RTU Relay Channels (Section 6 & Section 20A)
RELAY_CH_ACF = {"PH-01": 1, "PH-02": 2, "PH-03": 3, "PH-04": 4, "PH-05": 5}
RELAY_CH_SPRINKLER = {"PH-01": 6, "PH-02": 7, "PH-03": 8, "PH-04": 9, "PH-05": 10}
RELAY_CH_FOGGER = {"PH-01": 11, "PH-02": 12, "PH-03": 13, "PH-04": 14, "PH-05": 15}
RELAY_CH_COMMON_PUMP = 16
BUZZER_CHANNEL = 22

# -----------------------------------------------------------------------------
# GLOBAL SYSTEM CONFIGURATION & DEFAULTS
# -----------------------------------------------------------------------------
system_config = {
    'relay_port': RELAY_PORT_FIXED,
    'upload_frequency_min': 1.0,
    'temp_alarm_offset': 5.0,
    'humi_alarm_offset': 5.0,
    'system_password': '1234',
    'pump_arbitration_mode': 'sequential',  # 'sequential' or 'parallel'
    'pump_start_delay_sec': 3.0,
    'pump_post_run_delay_sec': 3.0,
    'buzzer_auto_silence_sec': 30,
    'sensor_names': {
        'PH-01': 'POLYHOUSE 01',
        'PH-02': 'POLYHOUSE 02',
        'PH-03': 'POLYHOUSE 03',
        'PH-04': 'POLYHOUSE 04',
        'PH-05': 'POLYHOUSE 05',
        'PH-06': 'POLYHOUSE 06 (MONITOR)'
    }
}

sensor_data = {}
sensor_setpoints = {}
sensor_data_lock = threading.Lock()
running = True
system_paused = False
relay_states = {ch: False for ch in range(1, 33)}

# Sensor Error & Fault Tracking (Section 15 & Section 20A Note)
sensor_consecutive_fails = {ph: 0 for ph in ALL_POLYHOUSES}
sensor_fault_logged = {ph: False for ph in ALL_POLYHOUSES}

# UI Toast Notification Tracker
setpoint_toast_message = ""
setpoint_toast_expiry = 0

def set_ui_toast(msg, duration_sec=5):
    global setpoint_toast_message, setpoint_toast_expiry
    setpoint_toast_message = msg
    setpoint_toast_expiry = time.time() + duration_sec

# DLI State (Daily Light Integral in mol/m²/day)
dli_data = {
    "date": datetime.date.today().isoformat(),
    "accumulators": {ph: {"dli": 0.0, "status": "CALCULATED"} for ph in ACTIVE_POLYHOUSES}
}
dli_lock = threading.Lock()

# Pump Arbitration State
pump_active = False
pump_start_time = 0
pump_stop_scheduled_time = 0
active_water_zone = None
active_water_zone_start = 0

# 5 ACF Cyclic Timers (for PH-01 to PH-05)
acf_timers = {ph: {"state": "ON", "switch_time": time.time()} for ph in ACTIVE_POLYHOUSES}

# Sprinkler & Fogger Cyclic Timers (for CYCLIC mode)
sprinkler_cyclic_timers = {ph: {"state": "OFF", "switch_time": time.time()} for ph in ACTIVE_POLYHOUSES}
fogger_cyclic_timers = {ph: {"state": "OFF", "switch_time": time.time()} for ph in ACTIVE_POLYHOUSES}

# Buzzer & Alarm State
buzzer_active = False
buzzer_start_time = 0
buzzer_silenced_for_current_alarm = False
buzzer_lock = threading.Lock()
active_warnings = []

# Sync & Upload Trackers
last_upload_time = 0
last_dli_calc_time = time.time()
last_offline_save_time = 0

# Rolling Trend History for Screen 14 (120 points per polyhouse)
trend_data_history = {ph: deque(maxlen=120) for ph in ALL_POLYHOUSES}
trend_lock = threading.Lock()
last_trend_sample_time = 0

# Scheduled Irrigation / Fogging Runtime State (Screen 12)
active_scheduled_irrigation = {}

# -----------------------------------------------------------------------------
# TIME FORMAT HELPERS (12-HOUR AM/PM <-> 24-HOUR)
# -----------------------------------------------------------------------------
def format_time_12h(t_str):
    t_str = str(t_str).strip()
    if "AM" in t_str.upper() or "PM" in t_str.upper():
        return t_str.upper()
    try:
        parts = t_str.split(":")
        hh = int(parts[0])
        mm = int(parts[1])
        meridiem = "PM" if hh >= 12 else "AM"
        hh12 = hh % 12
        if hh12 == 0: hh12 = 12
        return f"{hh12:02d}:{mm:02d} {meridiem}"
    except Exception:
        return t_str

def format_time_24h(t_str):
    t_str = str(t_str).strip()
    if not ("AM" in t_str.upper() or "PM" in t_str.upper()):
        return t_str
    try:
        m = re.search(r'(\d+):(\d+)\s*(AM|PM)', t_str, re.IGNORECASE)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2))
            meridiem = m.group(3).upper()
            if meridiem == "PM" and hh < 12: hh += 12
            elif meridiem == "AM" and hh == 12: hh = 0
            return f"{hh:02d}:{mm:02d}"
    except Exception: pass
    return t_str

def is_within_window(start_str, stop_str):
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist_tz).time()
    try:
        s_24 = format_time_24h(str(start_str))
        e_24 = format_time_24h(str(stop_str))
        st = datetime.datetime.strptime(s_24, "%H:%M").time()
        et = datetime.datetime.strptime(e_24, "%H:%M").time()
    except Exception:
        return True
    return (st <= now <= et) if st <= et else (now >= st or now <= et)

# -----------------------------------------------------------------------------
# DEFAULT ITC POLYHOUSE SCHEDULE & SETPOINTS GENERATOR
# -----------------------------------------------------------------------------
def generate_default_itc_schedule(skey):
    if skey == "PH-06":
        return {
            "name": "POLYHOUSE 06 (MONITOR)",
            "mode": "MONITOR",
            "temp_high_limit": 32.0,
            "temp_low_limit": 15.0,
            "humi_high_limit": 85.0,
            "humi_low_limit": 35.0
        }

    stages = {}
    stage_defs = [
        ("Setting A", "Vegetative Phase", "2026-09-01", "2026-09-30"),
        ("Setting B", "Flowering Phase", "2026-10-01", "2026-10-31"),
        ("Setting C", "Fruiting Phase", "2026-11-01", "2026-11-30"),
        ("Setting D", "Harvest Phase", "2026-12-01", "2026-12-31"),
        ("Setting E", "Post-Harvest", "2027-01-01", "2027-01-15")
    ]
    for key, name, sdate, edate in stage_defs:
        stages[key] = {
            "name": name,
            "start_date": sdate,
            "end_date": edate,
            "enabled": (key == "Setting A"),
            "time_slots": [
                {"id": 1, "name": "Morning", "start": "06:00 AM", "stop": "11:00 AM", "t_set": 24.0, "t_max": 28.0, "t_min": 20.0, "h_set": 70.0, "h_max": 80.0, "h_min": 60.0, "enabled": True},
                {"id": 2, "name": "Midday", "start": "11:00 AM", "stop": "03:00 PM", "t_set": 26.0, "t_max": 30.0, "t_min": 22.0, "h_set": 65.0, "h_max": 75.0, "h_min": 55.0, "enabled": True},
                {"id": 3, "name": "Afternoon", "start": "03:00 PM", "stop": "07:00 PM", "t_set": 25.0, "t_max": 28.0, "t_min": 21.0, "h_set": 70.0, "h_max": 80.0, "h_min": 60.0, "enabled": True},
                {"id": 4, "name": "Evening", "start": "07:00 PM", "stop": "11:00 PM", "t_set": 22.0, "t_max": 25.0, "t_min": 18.0, "h_set": 75.0, "h_max": 85.0, "h_min": 65.0, "enabled": True},
                {"id": 5, "name": "Night", "start": "11:00 PM", "stop": "06:00 AM", "t_set": 20.0, "t_max": 23.0, "t_min": 16.0, "h_set": 75.0, "h_max": 85.0, "h_min": 65.0, "enabled": True}
            ]
        }

    return {
        "name": system_config.get("sensor_names", {}).get(skey, skey),
        "mode": "AUTO",  # "AUTO", "MANUAL", "SCHEDULE", "CYCLIC"
        "temp_high": 28.0,
        "temp_low": 22.0,
        "temp_target": 25.0,
        "temp_hysteresis": 1.0,
        "humi_high": 80.0,
        "humi_low": 60.0,
        "humi_target": 70.0,
        "humi_hysteresis": 3.0,
        "fogger_min_on_sec": 60,
        "fogger_min_off_sec": 120,
        "sprinkler_duration_sec": 120,
        "sprinkler_interval_min": 30,
        "acf_cycle_enabled": True,
        "acf_on_min": 15,
        "acf_off_min": 30,
        # Control122.py Tabular Cyclic Timers
        "Timer1 Name": "ACF FANS",
        "Timer1 Start": "00:00",
        "Timer1 Stop": "23:59",
        "Timer1 ON Min": 15,
        "Timer1 OFF Min": 30,
        "Timer2 Name": "SPRINKLER",
        "Timer2 Start": "06:00",
        "Timer2 Stop": "18:00",
        "Timer2 ON Min": 2,
        "Timer2 OFF Min": 30,
        "Timer3 Name": "FOGGER",
        "Timer3 Start": "08:00",
        "Timer3 Stop": "17:00",
        "Timer3 ON Min": 1,
        "Timer3 OFF Min": 2,
        "active_setting": "Setting A",
        "settings": stages,
        "irrigation_slots": [
            {"id": 1, "start": "07:00 AM", "duration_sec": 120, "type": "sprinkler", "enabled": True},
            {"id": 2, "start": "12:30 PM", "duration_sec": 120, "type": "sprinkler", "enabled": True},
            {"id": 3, "start": "04:30 PM", "duration_sec": 120, "type": "fogger", "enabled": True}
        ]
    }

# -----------------------------------------------------------------------------
# ALARM EVENT LOGGING (alarm_history.jsonl)
# -----------------------------------------------------------------------------
def log_alarm_event(skey, msg, actual_val, target_val):
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_iso = datetime.datetime.now(ist_tz).isoformat()
    entry = {
        "timestamp": now_iso,
        "skey": skey,
        "sensor_name": get_sensor_display_name(skey),
        "message": msg,
        "actual": actual_val,
        "target": target_val
    }
    try:
        with open(ALARM_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"Alarm Log Error: {e}")

# -----------------------------------------------------------------------------
# PERSISTENCE LOAD & SAVE (SETPOINTS, CONFIG, DLI)
# -----------------------------------------------------------------------------
def load_config():
    global system_config, SENSOR_MAP, CO2_SENSOR_MAP, PAR_SENSOR_MAP, RELAY_PORT_FIXED
    need_save = False
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                system_config.update(json.load(f))
        except Exception: 
            need_save = True
    else:
        need_save = True

    if 'sensor_ports' in system_config:
        SENSOR_MAP.update(system_config['sensor_ports'])
    else:
        system_config['sensor_ports'] = copy.deepcopy(SENSOR_MAP)
        need_save = True

    if 'co2_sensor_ports' in system_config:
        CO2_SENSOR_MAP.update(system_config['co2_sensor_ports'])
    else:
        system_config['co2_sensor_ports'] = copy.deepcopy(CO2_SENSOR_MAP)
        need_save = True

    if 'par_sensor_ports' in system_config:
        PAR_SENSOR_MAP.update(system_config['par_sensor_ports'])
    else:
        system_config['par_sensor_ports'] = copy.deepcopy(PAR_SENSOR_MAP)
        need_save = True

    if 'relay_port' in system_config:
        RELAY_PORT_FIXED = system_config['relay_port']
    else:
        system_config['relay_port'] = RELAY_PORT_FIXED
        need_save = True

    if 'upload_frequency_min' not in system_config: 
        system_config['upload_frequency_min'] = 1.0
        need_save = True
    if 'temp_alarm_offset' not in system_config: 
        system_config['temp_alarm_offset'] = 5.0
        need_save = True
    if 'humi_alarm_offset' not in system_config: 
        system_config['humi_alarm_offset'] = 5.0
        need_save = True
    if 'pump_arbitration_mode' not in system_config: 
        system_config['pump_arbitration_mode'] = 'sequential'
        need_save = True
    if 'pump_start_delay_sec' not in system_config: 
        system_config['pump_start_delay_sec'] = 3.0
        need_save = True
    if 'pump_post_run_delay_sec' not in system_config: 
        system_config['pump_post_run_delay_sec'] = 3.0
        need_save = True
    if 'system_password' not in system_config:
        system_config['system_password'] = '1234'
        need_save = True
    if 'sensor_names' not in system_config:
        system_config['sensor_names'] = {
            'PH-01': 'POLYHOUSE 01',
            'PH-02': 'POLYHOUSE 02',
            'PH-03': 'POLYHOUSE 03',
            'PH-04': 'POLYHOUSE 04',
            'PH-05': 'POLYHOUSE 05',
            'PH-06': 'POLYHOUSE 06 (MONITOR)'
        }
        need_save = True

    if need_save or not os.path.exists(CONFIG_FILE):
        save_config()

def save_config():
    try:
        os.makedirs(os.path.dirname(os.path.abspath(CONFIG_FILE)), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(system_config, f, indent=4)
        print(f"[STORAGE] Config saved to {CONFIG_FILE}")
    except Exception as e:
        print(f"Save Config Error: {e}")

def load_dli_history():
    global dli_data
    today = datetime.date.today().isoformat()
    if os.path.exists(DLI_FILE):
        try:
            with open(DLI_FILE, 'r') as f:
                saved = json.load(f)
                if saved.get("date") == today:
                    dli_data = saved
                    return
        except Exception: pass
    dli_data = {
        "date": today,
        "accumulators": {ph: {"dli": 0.0, "status": "CALCULATED"} for ph in ACTIVE_POLYHOUSES}
    }
    save_dli_history()

def save_dli_history():
    try:
        os.makedirs(os.path.dirname(os.path.abspath(DLI_FILE)), exist_ok=True)
        with open(DLI_FILE, 'w') as f:
            json.dump(dli_data, f, indent=4)
        print(f"[STORAGE] DLI history saved to {DLI_FILE}")
    except Exception as e:
        print(f"Save DLI Error: {e}")

def load_trend_history_from_logs():
    if not os.path.exists(ACTIVE_LOG_FILE):
        return
    try:
        with open(ACTIVE_LOG_FILE, "r") as f:
            lines = [l.strip() for l in f if l.strip()]
        for l in lines[-60:]:
            try:
                rec = json.loads(l)
                ts = rec.get("timestamp", "")
                time_label = ts.split("T")[1][:5] if "T" in ts else ts[:5]
                s_data = rec.get("sensor_data", {})
                for port, item in s_data.items():
                    skey = item.get("skey")
                    if skey in trend_data_history and item.get("status") == "OK":
                        trend_data_history[skey].append({
                            "time": time_label,
                            "temp": item.get("temp"),
                            "humi": item.get("humi"),
                            "co2": item.get("co2"),
                            "par": item.get("par"),
                            "dli": item.get("dli")
                        })
            except Exception: pass
        print(f"[STORAGE] Pre-loaded trend buffer from {ACTIVE_LOG_FILE}")
    except Exception as e:
        print(f"Load Trend Log Error: {e}")

def load_setpoints():
    global sensor_setpoints
    need_save = False
    if os.path.exists(SETPOINTS_FILE):
        try:
            with open(SETPOINTS_FILE, 'r') as f:
                sensor_setpoints = json.load(f)
        except Exception: 
            need_save = True
    else:
        need_save = True

    for skey in ALL_POLYHOUSES:
        if skey not in sensor_setpoints:
            sensor_setpoints[skey] = generate_default_itc_schedule(skey)
            need_save = True
        else:
            if skey in ACTIVE_POLYHOUSES:
                if "temp_high" not in sensor_setpoints[skey] or "settings" not in sensor_setpoints[skey]:
                    def_sp = generate_default_itc_schedule(skey)
                    def_sp.update(sensor_setpoints[skey])
                    sensor_setpoints[skey] = def_sp
                    need_save = True

    if need_save or not os.path.exists(SETPOINTS_FILE):
        save_setpoints()

def save_setpoints(source="LOCAL_HMI"):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(SETPOINTS_FILE)), exist_ok=True)
        with open(SETPOINTS_FILE, 'w') as f:
            json.dump(sensor_setpoints, f, indent=4)
        print(f"[STORAGE] Setpoints saved to {SETPOINTS_FILE} ({source})")
        log_alarm_event("SYSTEM", f"Setpoints updated from {source}", "-", "-")
        set_ui_toast(f"✔ SETPOINTS UPDATED ({source})")
        broadcast_current_state()
    except Exception as e:
        print(f"Save Setpoints Error: {e}")

def get_setpoints(skey):
    if skey not in sensor_setpoints:
        sensor_setpoints[skey] = generate_default_itc_schedule(skey)
    sp = sensor_setpoints[skey]
    if skey in ACTIVE_POLYHOUSES:
        sp.setdefault("Timer1 Name", "ACF FANS")
        sp.setdefault("Timer1 Start", "00:00")
        sp.setdefault("Timer1 Stop", "23:59")
        sp.setdefault("Timer1 ON Min", int(sp.get("acf_on_min", 15)))
        sp.setdefault("Timer1 OFF Min", int(sp.get("acf_off_min", 30)))

        sp.setdefault("Timer2 Name", "SPRINKLER")
        sp.setdefault("Timer2 Start", "06:00")
        sp.setdefault("Timer2 Stop", "18:00")
        sp.setdefault("Timer2 ON Min", max(1, int(sp.get("sprinkler_duration_sec", 120)) // 60))
        sp.setdefault("Timer2 OFF Min", int(sp.get("sprinkler_interval_min", 30)))

        sp.setdefault("Timer3 Name", "FOGGER")
        sp.setdefault("Timer3 Start", "08:00")
        sp.setdefault("Timer3 Stop", "17:00")
        sp.setdefault("Timer3 ON Min", max(1, int(sp.get("fogger_min_on_sec", 60)) // 60))
        sp.setdefault("Timer3 OFF Min", max(1, int(sp.get("fogger_min_off_sec", 120)) // 60))
    return sp

def get_sensor_display_name(skey):
    names = system_config.get("sensor_names", {})
    if skey in names and names[skey].strip():
        return names[skey].strip()
    return f"POLYHOUSE {skey.replace('PH-', '')}"

# -----------------------------------------------------------------------------
# ACTIVE SETPOINTS EVALUATION (AUTO, SCHEDULE, CYCLIC, MANUAL)
# -----------------------------------------------------------------------------
def get_active_setpoints(skey):
    sp_data = get_setpoints(skey)
    mode = sp_data.get("mode", "AUTO").upper()

    t_high = float(sp_data.get("temp_high", sp_data.get("temp_high_limit", sp_data.get("T MAX", 28.0))))
    t_low = float(sp_data.get("temp_low", sp_data.get("temp_low_limit", sp_data.get("T MIN", 22.0))))
    t_set = float(sp_data.get("temp_target", round((t_high + t_low) / 2.0, 1)))

    h_high = float(sp_data.get("humi_high", sp_data.get("humi_high_limit", sp_data.get("H MAX", 80.0))))
    h_low = float(sp_data.get("humi_low", sp_data.get("humi_low_limit", sp_data.get("H MIN", 60.0))))
    h_set = float(sp_data.get("humi_target", round((h_high + h_low) / 2.0, 1)))

    active_info = {
        "mode": mode,
        "setting_name": "Standard Setpoints",
        "stage_name": "Climate Thresholds",
        "slot_id": 1,
        "start": "00:00 AM",
        "stop": "11:59 PM",
        "target_temp": t_set,
        "target_humi": h_set,
        "T MIN": t_low,
        "T MAX": t_high,
        "H MIN": h_low,
        "H MAX": h_high,
        "temp_hysteresis": float(sp_data.get("temp_hysteresis", 1.0)),
        "humi_hysteresis": float(sp_data.get("humi_hysteresis", 3.0)),
        "fogger_min_on_sec": int(sp_data.get("fogger_min_on_sec", 60)),
        "fogger_min_off_sec": int(sp_data.get("fogger_min_off_sec", 120)),
        "sprinkler_duration_sec": int(sp_data.get("sprinkler_duration_sec", 120)),
        "sprinkler_interval_min": int(sp_data.get("sprinkler_interval_min", 30)),
        "acf_cycle_enabled": bool(sp_data.get("acf_cycle_enabled", True)),
        "acf_on_min": int(sp_data.get("acf_on_min", 15)),
        "acf_off_min": int(sp_data.get("acf_off_min", 30)),
        "Timer1 Name": sp_data.get("Timer1 Name", "ACF FANS"),
        "Timer1 Start": sp_data.get("Timer1 Start", "00:00"),
        "Timer1 Stop": sp_data.get("Timer1 Stop", "23:59"),
        "Timer1 ON Min": int(sp_data.get("Timer1 ON Min", sp_data.get("acf_on_min", 15))),
        "Timer1 OFF Min": int(sp_data.get("Timer1 OFF Min", sp_data.get("acf_off_min", 30))),
        "Timer2 Name": sp_data.get("Timer2 Name", "SPRINKLER"),
        "Timer2 Start": sp_data.get("Timer2 Start", "06:00"),
        "Timer2 Stop": sp_data.get("Timer2 Stop", "18:00"),
        "Timer2 ON Min": int(sp_data.get("Timer2 ON Min", 2)),
        "Timer2 OFF Min": int(sp_data.get("Timer2 OFF Min", 30)),
        "Timer3 Name": sp_data.get("Timer3 Name", "FOGGER"),
        "Timer3 Start": sp_data.get("Timer3 Start", "08:00"),
        "Timer3 Stop": sp_data.get("Timer3 Stop", "17:00"),
        "Timer3 ON Min": int(sp_data.get("Timer3 ON Min", 1)),
        "Timer3 OFF Min": int(sp_data.get("Timer3 OFF Min", 2))
    }

    if mode != "SCHEDULE":
        return active_info

    # SCHEDULE Mode: evaluate active RTC stage and time slot
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist_tz)
    today_str = now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%H:%M")

    settings = sp_data.get("settings", {})
    for set_key in ["Setting A", "Setting B", "Setting C", "Setting D", "Setting E"]:
        setting = settings.get(set_key)
        if not setting or not setting.get("enabled", True): continue

        s_date = setting.get("start_date", "")
        e_date = setting.get("end_date", "")
        if s_date and e_date:
            if not (s_date <= today_str <= e_date): continue

        time_slots = setting.get("time_slots", [])
        for slot in time_slots:
            if not slot.get("enabled", True): continue

            start_t = format_time_24h(slot.get("start", "00:00"))
            stop_t = format_time_24h(slot.get("stop", "23:59"))

            is_in_slot = False
            if start_t <= stop_t:
                is_in_slot = (start_t <= current_time_str <= stop_t)
            else:
                is_in_slot = (current_time_str >= start_t or current_time_str <= stop_t)

            if is_in_slot:
                t_set_v = float(slot.get("t_set", 25.0))
                t_max_v = float(slot.get("t_max", t_set_v + 3.0))
                t_min_v = float(slot.get("t_min", t_set_v - 3.0))
                h_set_v = float(slot.get("h_set", 70.0))
                h_max_v = float(slot.get("h_max", h_set_v + 10.0))
                h_min_v = float(slot.get("h_min", h_set_v - 10.0))

                active_info.update({
                    "setting_name": setting.get("name", set_key),
                    "stage_name": slot.get("name", f"Slot {slot.get('id', 1)}"),
                    "slot_id": slot.get("id", 1),
                    "start": slot.get("start", "06:00 AM"),
                    "stop": slot.get("stop", "11:00 AM"),
                    "target_temp": round(t_set_v, 1),
                    "target_humi": round(h_set_v, 1),
                    "T MIN": round(t_min_v, 1),
                    "T MAX": round(t_max_v, 1),
                    "H MIN": round(h_min_v, 1),
                    "H MAX": round(h_max_v, 1)
                })
                return active_info

    return active_info

# -----------------------------------------------------------------------------
# HARDWARE RELAY CONTROL & BUZZER ROUTINES (THREAD-SAFE QUEUE)
# -----------------------------------------------------------------------------
relay_cmd_queue = queue.Queue()

def relay_worker_loop():
    global working_relay_id, running
    while running:
        try:
            cmd = relay_cmd_queue.get(timeout=0.5)
            if cmd is None:
                break
            channel, state = cmd
            port = system_config.get("relay_port", RELAY_PORT_FIXED)
            if os.path.exists(port):
                slave_ids_to_try = [working_relay_id] if working_relay_id is not None else POSSIBLE_RELAY_IDS
                for s_id in slave_ids_to_try:
                    if s_id is None: continue
                    inst = None
                    try:
                        inst = minimalmodbus.Instrument(port, s_id)
                        inst.serial.baudrate = RELAY_BAUD
                        inst.serial.timeout = 0.2
                        inst.close_port_after_each_call = True
                        inst.write_bit(channel - 1, 1 if state else 0, functioncode=5)
                        working_relay_id = s_id
                        break
                    except Exception:
                        pass
                    finally:
                        if inst and hasattr(inst, 'serial') and inst.serial and getattr(inst.serial, 'is_open', False):
                            try: inst.serial.close()
                            except Exception: pass
            relay_cmd_queue.task_done()
        except queue.Empty:
            continue
        except Exception:
            pass

threading.Thread(target=relay_worker_loop, daemon=True).start()

def set_relay(channel, state):
    if channel < 1 or channel > 32: return
    relay_states[channel] = bool(state)
    relay_cmd_queue.put((channel, bool(state)))

def trigger_buzzer_pulse(duration_sec=5.0):
    def _pulse():
        set_relay(BUZZER_CHANNEL, True)
        time.sleep(duration_sec)
        set_relay(BUZZER_CHANNEL, False)
    threading.Thread(target=_pulse, daemon=True).start()

def emergency_stop_all():
    global system_paused, pump_active, active_water_zone
    system_paused = True
    pump_active = False
    active_water_zone = None
    while not relay_cmd_queue.empty():
        try:
            relay_cmd_queue.get_nowait()
            relay_cmd_queue.task_done()
        except Exception: break
    for ch in range(1, 33):
        relay_states[ch] = False
        relay_cmd_queue.put((ch, False))
    print("[EMERGENCY] All 32 relays de-energized. System paused.")

# -----------------------------------------------------------------------------
# MQTT REMOTE SYNCHRONIZATION & TELEMETRY GATEWAY
# -----------------------------------------------------------------------------
CONTROL_TOPIC = f"inhydro/{DEVICE_NAME}/control"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"

try:
    control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
except Exception:
    control_client = mqtt.Client()
is_mqtt_connected = False
CONTROL_BROKER = "147.93.106.142"
CONTROL_PORT = 1883
CONTROL_USER = "Inhydro@5598"
CONTROL_PASS = "MGPL@5598"

def broadcast_current_state():
    if control_client and is_mqtt_connected:
        with sensor_data_lock: snap_sensor = dict(sensor_data)
        with dli_lock: snap_dli = dict(dli_data)
        payload = {
            "device_id": DEVICE_NAME,
            "project": "ITC Farm, Madhya Pradesh",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "system_config": system_config,
            "sensor_setpoints": sensor_setpoints,
            "sensor_data": snap_sensor,
            "dli_data": snap_dli,
            "active_warnings": active_warnings,
            "relay_states": relay_states,
            "common_pump_active": pump_active,
            "active_water_zone": active_water_zone
        }
        try:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(payload), retain=True)
        except Exception as e:
            print(f"Broadcast error: {e}")

def save_local_telemetry_if_offline(snap_sensor, snap_dli, relay_st, pump_st):
    global last_offline_save_time
    if is_mqtt_connected:
        return
    cur_t = time.time()
    if cur_t - last_offline_save_time < 30.0:
        return
    last_offline_save_time = cur_t

    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ts_str = datetime.datetime.now(ist_tz).isoformat()
    record = {
        "timestamp": ts_str,
        "device_id": DEVICE_NAME,
        "sensor_data": snap_sensor,
        "dli_data": snap_dli,
        "relay_states": relay_st,
        "pump_active": pump_st
    }
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(ACTIVE_LOG_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
        if os.path.exists(ACTIVE_LOG_FILE) and os.path.getsize(ACTIVE_LOG_FILE) > 1500000:
            rot = os.path.join(LOG_DIR, f"log_{int(time.time())}.jsonl")
            os.rename(ACTIVE_LOG_FILE, rot)
    except Exception as e:
        print(f"[OFFLINE LOG] Error: {e}")

def sync_offline_thread():
    while running:
        time.sleep(15)
        if not is_mqtt_connected or not control_client:
            continue
        try:
            if not os.path.exists(LOG_DIR): continue
            files = [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl")]
            if not files: continue

            target_f = os.path.join(LOG_DIR, files[0])
            if os.path.exists(target_f) and os.path.getsize(target_f) > 0:
                with open(target_f, "r") as f:
                    lines = [line.strip() for line in f if line.strip()][:50]
                if lines:
                    batch = [json.loads(l) for l in lines]
                    control_client.publish(f"inhydro/{DEVICE_NAME}/telemetry/history", json.dumps(batch), retain=False)
                    with open(target_f, "r") as f:
                        all_lines = f.readlines()
                    remaining = all_lines[len(lines):]
                    if remaining:
                        with open(target_f, "w") as f:
                            f.writelines(remaining)
                    else:
                        os.remove(target_f)
        except Exception:
            pass

def on_control_message(client, userdata, msg):
    try:
        if msg.topic == CONTROL_SYNC_TOPIC:
            broadcast_current_state()
            return

        new_data = json.loads(msg.payload.decode())
        target_ph = str(new_data.get("polyhouse", "")).strip().upper()
        if target_ph in ALL_POLYHOUSES:
            sp = get_setpoints(target_ph)
            sp.update(new_data)
            save_setpoints(source="CLOUD_MQTT")
    except Exception as e:
        print(f"[MQTT Error] {e}")

def on_control_connect(client, userdata, flags, rc=0, *args, **kwargs):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(CONTROL_SYNC_TOPIC)
        broadcast_current_state()
    else: is_mqtt_connected = False

def on_control_disconnect(client, userdata, *args, **kwargs):
    global is_mqtt_connected
    is_mqtt_connected = False

control_client.on_message = on_control_message
control_client.on_connect = on_control_connect
control_client.on_disconnect = on_control_disconnect

try:
    if CONTROL_USER and CONTROL_PASS:
        control_client.username_pw_set(CONTROL_USER, CONTROL_PASS)
    control_client.connect_async(CONTROL_BROKER, CONTROL_PORT, 60)
    control_client.loop_start()
except Exception: pass

# -----------------------------------------------------------------------------
# BLUETOOTH SERIAL TERMINAL & WI-FI PROVISIONING (MONIT.PY / ALMORA2.PY PATTERN)
# -----------------------------------------------------------------------------
def set_wifi(ssid, password):
    try:
        ssid = str(ssid).strip()
        password = str(password).strip()
        if not ssid:
            return "FAILED: Empty SSID"
        try:
            subprocess.run(['sudo', 'rfkill', 'unblock', 'wifi'], capture_output=True, timeout=3)
            subprocess.run(['sudo', 'nmcli', 'radio', 'wifi', 'on'], capture_output=True, timeout=3)
        except Exception: pass
        try:
            subprocess.run(['sudo', 'nmcli', 'connection', 'delete', 'id', ssid], capture_output=True, timeout=4)
            subprocess.run(['sudo', 'nmcli', 'connection', 'delete', ssid], capture_output=True, timeout=4)
        except Exception: pass
        cmd = ['sudo', 'nmcli', '--wait', '15', 'device', 'wifi', 'connect', ssid]
        if password:
            cmd += ['password', password]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=18)
        if res.returncode != 0 and password:
            try:
                subprocess.run(['sudo', 'nmcli', 'connection', 'delete', 'id', ssid], capture_output=True, timeout=4)
                subprocess.run(['sudo', 'nmcli', 'connection', 'add', 'type', 'wifi', 'con-name', ssid, 'ssid', ssid], capture_output=True, timeout=8)
                subprocess.run(['sudo', 'nmcli', 'connection', 'modify', ssid, '802-11-wireless-security.key-mgmt', 'wpa-psk', '802-11-wireless-security.psk', password], capture_output=True, timeout=6)
                res = subprocess.run(['sudo', 'nmcli', '--wait', '15', 'connection', 'up', 'id', ssid], capture_output=True, text=True, timeout=18)
            except Exception: pass
        if res.returncode == 0:
            return f"SUCCESS: Connected to '{ssid}'!"
        err_msg = res.stderr.strip() or res.stdout.strip() or "Connection failed"
        return f"FAILED: {err_msg}"
    except Exception as e: return f"ERROR: {str(e)}"

def scan_wifi():
    try:
        command = ['sudo', 'nmcli', '-t', '-f', 'SSID,SIGNAL', 'dev', 'wifi', 'list']
        result = subprocess.run(command, capture_output=True, text=True, timeout=8)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            found = {}
            for line in lines:
                if ':' in line:
                    parts = line.rsplit(':', 1)
                    s_name = parts[0].strip()
                    sig = parts[1].strip()
                    if s_name and s_name not in found:
                        found[s_name] = sig
            if not found:
                return "\r\n[NO WIFI NETWORKS FOUND]\r\n"
            response = "\r\n--- NEARBY WIFI NETWORKS ---\r\n"
            for i, (s_name, sig) in enumerate(found.items(), 1):
                response += f"{i}. {s_name} ({sig}% Signal)\r\n"
            response += "\r\nUse command: WIFI:SSID:PASSWORD\r\n"
            return response
        else:
            return f"SCAN FAILED: {result.stderr.strip()}"
    except Exception as e:
        return f"SCAN ERROR: {str(e)}"

def get_system_ip_summary():
    try:
        res = subprocess.run(['hostname', '-I'], capture_output=True, text=True)
        ips = res.stdout.strip()
        return ips if ips else "127.0.0.1"
    except Exception:
        return "Unknown"

def process_bt_command(text, write_fn):
    cmd = text.strip()
    if not cmd: return
    print(f"[BLUETOOTH] Received Command: '{cmd}'")

    if cmd.startswith("WIFI:") or cmd.startswith("4:"):
        raw = cmd[5:] if cmd.startswith("WIFI:") else cmd[2:]
        parts = raw.split(":")
        if len(parts) >= 2:
            ssid = parts[0].strip()
            passw = ":".join(parts[1:]).strip()
            write_fn(f"\r\nCONNECTING TO WIFI '{ssid}'...\r\n")
            resp = set_wifi(ssid, passw)
            write_fn(f"\r\n{resp}\r\n\r\n")
        else:
            write_fn("\r\nERROR: Format is WIFI:SSID:PASSWORD or 4:SSID:PASSWORD\r\n\r\n")

    elif cmd.startswith("ID:") or cmd.startswith("5:"):
        raw_id = cmd[3:] if cmd.startswith("ID:") else cmd[2:]
        new_id = raw_id.strip()
        if new_id:
            with open(ID_FILE, "w") as f: f.write(new_id)
            write_fn(f"\r\nSUCCESS: Device ID set to {new_id}. Restarting...\r\n\r\n")
            root.after(2000, restart_program)

    elif cmd.upper() in ["SCAN", "2"]:
        write_fn("\r\nSCANNING NEARBY WIFI NETWORKS...\r\n")
        scan_res = scan_wifi()
        write_fn(f"{scan_res}\r\n")

    elif cmd.upper() in ["PING", "1"]:
        write_fn("\r\nPONG - ITC Polyhouse System Alive & Ready!\r\n\r\n")

    elif cmd.upper() in ["STATUS", "INFO", "3"]:
        with sensor_data_lock: snap = dict(sensor_data)
        lines = [
            "=========================================",
            f"--- ITC POLYHOUSE CONTROLLER STATUS ---",
            f"Device ID  : {DEVICE_NAME}",
            f"IP Address : {get_system_ip_summary()}",
            f"Cloud MQTT : {'ONLINE' if is_mqtt_connected else 'OFFLINE'}",
            f"Water Pump : {'RUNNING' if pump_active else 'IDLE'} (Zone: {active_water_zone or 'None'})",
            "-----------------------------------------"
        ]
        for ph in ALL_POLYHOUSES:
            port = SENSOR_MAP.get(ph)
            d = snap.get(port, {})
            if d.get("status") == "OK":
                t_str = f"{d.get('temp', '--'):.1f}C"
                h_str = f"{d.get('humi', '--'):.1f}%"
                c_str = f", CO2: {d.get('co2')}ppm" if d.get('co2') else ""
                lines.append(f"{ph}: Temp {t_str}, RH {h_str}{c_str}")
            else:
                lines.append(f"{ph}: SENSOR OFFLINE")
        lines.append(f"Active Warnings: {', '.join(active_warnings) if active_warnings else 'None'}")
        lines.append("=========================================\r\n")
        write_fn("\r\n" + "\r\n".join(lines))

    else:
        fallback = f"\r\nACK: Received '{cmd}'\r\nAvailable Commands: 1.PING | 2.SCAN | 3.STATUS | 4.WIFI:SSID:PASSWORD | 5.ID:new_id\r\n\r\n"
        write_fn(fallback)

def handle_bt_client_fd(fd_int):
    try:
        print(f"[BLUETOOTH] Client Connected (FD: {fd_int})")
        welcome_msg = (
            "\r\n=================================================\r\n"
            f"--- INHYDRO ITC POLYHOUSE AUTOMATION SYSTEM ---\r\n"
            f"Device ID: {DEVICE_NAME}\r\n"
            "=================================================\r\n"
            "COMMAND MENU:\r\n"
            "1. PING\r\n"
            "2. SCAN\r\n"
            "3. STATUS\r\n"
            "4. WIFI:SSID:PASSWORD\r\n"
            "5. ID:new_device_id\r\n"
            "=================================================\r\n\r\n"
        )
        os.write(fd_int, welcome_msg.encode('utf-8'))

        buf = ""
        while True:
            raw = os.read(fd_int, 1024)
            if not raw:
                print(f"[BLUETOOTH] Client Disconnected (FD: {fd_int})")
                break
            buf += raw.decode('utf-8', errors='ignore')

            lines = []
            while "\n" in buf or "\r" in buf:
                if "\r\n" in buf: line, buf = buf.split("\r\n", 1)
                elif "\n" in buf: line, buf = buf.split("\n", 1)
                else: line, buf = buf.split("\r", 1)
                lines.append(line)

            if not lines and buf.strip():
                lines.append(buf)
                buf = ""

            for l in lines:
                process_bt_command(l, lambda s: os.write(fd_int, s.encode('utf-8')))
    except Exception as e:
        print(f"[BLUETOOTH] Client FD error: {e}")
    finally:
        try: os.close(fd_int)
        except Exception: pass

def handle_bt_client_sock(client_sock):
    try:
        welcome_msg = (
            "\r\n=================================================\r\n"
            f"--- INHYDRO ITC POLYHOUSE AUTOMATION SYSTEM ---\r\n"
            f"Device ID: {DEVICE_NAME}\r\n"
            "=================================================\r\n"
            "COMMAND MENU:\r\n"
            "1. PING\r\n"
            "2. SCAN\r\n"
            "3. STATUS\r\n"
            "4. WIFI:SSID:PASSWORD\r\n"
            "5. ID:new_device_id\r\n"
            "=================================================\r\n\r\n"
        )
        client_sock.send(welcome_msg.encode('utf-8'))
        buf = ""
        while True:
            raw = client_sock.recv(1024)
            if not raw: break
            buf += raw.decode('utf-8', errors='ignore')

            lines = []
            while "\n" in buf or "\r" in buf:
                if "\r\n" in buf: line, buf = buf.split("\r\n", 1)
                elif "\n" in buf: line, buf = buf.split("\n", 1)
                else: line, buf = buf.split("\r", 1)
                lines.append(line)

            if not lines and buf.strip():
                lines.append(buf)
                buf = ""

            for l in lines:
                process_bt_command(l, lambda s: client_sock.send(s.encode('utf-8')))
    except Exception as e:
        pass
    finally:
        try: client_sock.close()
        except Exception: pass

def auto_trust_devices():
    try:
        subprocess.run(["bluetoothctl", "power", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "discoverable-timeout", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "pairable-timeout", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "discoverable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "pairable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception: pass

    while running:
        try:
            output = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True)
            for line in output.split('\n'):
                if line.startswith('Device '):
                    mac = line.split(" ")[1]
                    subprocess.run(["bluetoothctl", "trust", mac], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception: pass
        time.sleep(15)

def register_spp_dbus():
    try:
        for p_path in glob.glob('/usr/lib/python3*/dist-packages'):
            if p_path not in sys.path: sys.path.append(p_path)
        import dbus, dbus.service
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib

        DBusGMainLoop(set_as_default=True)

        class BluetoothAgent(dbus.service.Object):
            @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
            def Release(self): pass
            @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
            def AuthorizeService(self, device, uuid): return
            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='s')
            def RequestPinCode(self, device): return '0000'
            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='u')
            def RequestPasskey(self, device): return dbus.UInt32(123456)
            @dbus.service.method('org.bluez.Agent1', in_signature='ouq', out_signature='')
            def DisplayPasskey(self, device, passkey, entered): pass
            @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
            def DisplayPinCode(self, device, pincode): pass
            @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='')
            def RequestConfirmation(self, device, passkey): return
            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
            def RequestAuthorization(self, device): return
            @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
            def Cancel(self): pass

        class BluezProfile(dbus.service.Object):
            @dbus.service.method('org.bluez.Profile1', in_signature='oha{sv}', out_signature='')
            def NewConnection(self, path, fd, properties):
                fd_int = fd.take()
                flags = fcntl.fcntl(fd_int, fcntl.F_GETFL)
                fcntl.fcntl(fd_int, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
                threading.Thread(target=handle_bt_client_fd, args=(fd_int,), daemon=True).start()
            @dbus.service.method('org.bluez.Profile1', in_signature='o', out_signature='')
            def RequestDisconnection(self, path): pass

        bus = dbus.SystemBus()
        agent_path = '/inhydro/auto_agent'
        try:
            agent = BluetoothAgent(bus, agent_path)
            obj = bus.get_object('org.bluez', '/org/bluez')
            manager = dbus.Interface(obj, 'org.bluez.AgentManager1')
            try: manager.UnregisterAgent(agent_path)
            except Exception: pass
            manager.RegisterAgent(agent_path, 'NoInputNoOutput')
            manager.RequestDefaultAgent(agent_path)
        except Exception: pass

        profile_path = '/inhydro/spp_profile'
        profile = BluezProfile(bus, profile_path)
        manager_p = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.ProfileManager1')
        opts = {
            'AutoConnect': dbus.Boolean(True),
            'Role': 'server',
            'Name': f'Inhydro_{DEVICE_NAME}',
            'Service': '00001101-0000-1000-8000-00805F9B34FB',
            'Channel': dbus.UInt16(1),
            'RequireAuthentication': dbus.Boolean(False),
            'RequireAuthorization': dbus.Boolean(False)
        }
        manager_p.RegisterProfile(profile_path, '00001101-0000-1000-8000-00805F9B34FB', opts)

        mainloop = GLib.MainLoop()
        threading.Thread(target=mainloop.run, daemon=True).start()
        print("[BLUETOOTH] BlueZ SPP Profile1 & GLib Event Dispatcher Registered!")
    except Exception as e:
        print(f"[BLUETOOTH] Notice: BlueZ DBus setup fallback: {e}")

def start_bluetooth_server():
    # 1. Register DBus Profile
    register_spp_dbus()

    # 2. Start RFCOMM socket fallback loop
    while running:
        server_sock = None
        try:
            os.system("sdptool add --channel=1 SP >/dev/null 2>&1")
            time.sleep(0.5)
            server_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            server_sock.bind((socket.BDADDR_ANY, 1))
            server_sock.listen(1)
            print("[BLUETOOTH] Native RFCOMM Server Listening on Channel 1")
            while running:
                client_sock, client_info = server_sock.accept()
                print(f"[BLUETOOTH] Direct RFCOMM Client connected: {client_info}")
                threading.Thread(target=handle_bt_client_sock, args=(client_sock,), daemon=True).start()
        except Exception as e:
            time.sleep(5)
        finally:
            if server_sock:
                try: server_sock.close()
                except Exception: pass

# -----------------------------------------------------------------------------
# MAIN AUTOMATION & SENSOR ACQUISITION THREAD
# -----------------------------------------------------------------------------
def sensor_reader():
    global running, system_paused, active_warnings, last_upload_time, last_dli_calc_time, last_trend_sample_time
    global pump_active, pump_start_time, pump_stop_scheduled_time, active_water_zone, active_water_zone_start
    global buzzer_active, buzzer_start_time, buzzer_silenced_for_current_alarm

    while running:
        if system_paused:
            time.sleep(1.0)
            continue

        now = time.time()
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_dt = datetime.datetime.now(ist_tz)
        today_iso = now_dt.date().isoformat()

        # Midnight DLI Reset
        with dli_lock:
            if dli_data.get("date") != today_iso:
                save_dli_history()
                dli_data["date"] = today_iso
                dli_data["accumulators"] = {ph: {"dli": 0.0, "status": "CALCULATED"} for ph in ACTIVE_POLYHOUSES}

        # 1. READ ALL PHYSICAL SENSORS (MODBUS RS485 ONLY)
        for skey, port in SENSOR_MAP.items():
            if not running or system_paused: break
            time.sleep(0.03)

            temp, humi, co2, par = None, None, None, None

            # Physical Modbus Sensor Acquisition (100% Live Data Only)
            if os.path.exists(port):
                try:
                    values = None
                    for baud in [4800, 9600]:
                        for s_id in [SLAVE_ID, 1, 2, 3, 255]:
                            try:
                                inst = minimalmodbus.Instrument(port, s_id)
                                inst.serial.baudrate = baud
                                inst.serial.timeout = 0.2
                                inst.close_port_after_each_call = True
                                for fc in [4, 3]:
                                    for addr in [0, 1]:
                                        try:
                                            res = inst.read_registers(addr, 2, functioncode=fc)
                                            if res and len(res) >= 2 and (res[0] > 0 or res[1] > 0):
                                                values = res
                                                break
                                        except Exception: pass
                                    if values: break
                                if values: break
                            except Exception: pass
                        if values: break

                    if values and len(values) >= 2:
                        val0 = values[0] / 10.0
                        val1 = values[1] / 10.0
                        if val0 > 150: val0 /= 10.0
                        if val1 > 150: val1 /= 10.0

                        if val0 > val1 and val0 > 45.0:
                            humi = round(val0, 1)
                            temp = round(val1, 1)
                        else:
                            temp = round(val0, 1)
                            humi = round(val1, 1)
                except Exception: pass

                if skey in ACTIVE_POLYHOUSES:
                    c_port = CO2_SENSOR_MAP.get(skey)
                    if c_port and os.path.exists(c_port):
                        try:
                            inst_c = minimalmodbus.Instrument(c_port, 1)
                            inst_c.serial.baudrate = 9600
                            inst_c.serial.timeout = 0.3
                            inst_c.close_port_after_each_call = True
                            for fc in [4, 3]:
                                for addr in [0, 1]:
                                    try:
                                        c_vals = inst_c.read_registers(addr, 2, functioncode=fc)
                                        if c_vals and len(c_vals) >= 1 and c_vals[0] > 0:
                                            raw_c = float(c_vals[0])
                                            if raw_c > 5000: raw_c /= 10.0
                                            co2 = round(raw_c, 1)
                                            break
                                    except Exception: pass
                                if co2 is not None: break
                        except Exception: pass

                    p_port = PAR_SENSOR_MAP.get(skey)
                    if p_port and os.path.exists(p_port):
                        try:
                            inst_p = minimalmodbus.Instrument(p_port, 1)
                            inst_p.serial.baudrate = 9600
                            inst_p.serial.timeout = 0.3
                            inst_p.close_port_after_each_call = True
                            for fc in [4, 3]:
                                for addr in [0, 1]:
                                    try:
                                        p_vals = inst_p.read_registers(addr, 2, functioncode=fc)
                                        if p_vals and len(p_vals) >= 1 and p_vals[0] > 0:
                                            par = round(float(p_vals[0]), 1)
                                            break
                                    except Exception: pass
                                if par is not None: break
                        except Exception: pass

            # DLI Integration: DLI (mol/m²/day) = Σ[PPFD × dt] / 1,000,000
            dli_val = 0.0
            if skey in ACTIVE_POLYHOUSES:
                dt_dli = now - last_dli_calc_time
                if dt_dli >= 1.0:
                    with dli_lock:
                        acc = dli_data["accumulators"].setdefault(skey, {"dli": 0.0, "status": "CALCULATED"})
                        if par is not None and par >= 0:
                            acc["dli"] = round(acc["dli"] + (par * dt_dli) / 1000000.0, 3)
                            acc["status"] = "CALCULATED"
                        else:
                            acc["status"] = "INVALID"
                        dli_val = acc["dli"]

            with sensor_data_lock:
                sensor_data[port] = {
                    'skey': skey,
                    'temp': temp,
                    'humi': humi,
                    'co2': co2,
                    'par': par,
                    'dli': dli_val,
                    'status': 'OK' if (temp is not None and humi is not None) else 'OFFLINE'
                }

            if temp is not None and humi is not None:
                sensor_consecutive_fails[skey] = 0
                sensor_fault_logged[skey] = False
            else:
                sensor_consecutive_fails[skey] = sensor_consecutive_fails.get(skey, 0) + 1

        last_dli_calc_time = now

        # Periodic Historical Trend Data Point Sampling (Screen 14)
        if (now - last_trend_sample_time) >= 30.0:
            last_trend_sample_time = now
            with trend_lock:
                for p_key in ALL_POLYHOUSES:
                    p_port = SENSOR_MAP.get(p_key)
                    with sensor_data_lock: sd = sensor_data.get(p_port, {})
                    if sd.get("status") == "OK":
                        trend_data_history[p_key].append({
                            "time": now_dt.strftime("%H:%M"),
                            "temp": sd.get("temp"),
                            "humi": sd.get("humi"),
                            "co2": sd.get("co2"),
                            "par": sd.get("par"),
                            "dli": sd.get("dli")
                        })

        # 2. EVALUATE CONTROL LOGIC & ALARMS
        current_warnings = []
        water_requests = []
        temp_alarm_offset = float(system_config.get('temp_alarm_offset', 5.0))
        humi_alarm_offset = float(system_config.get('humi_alarm_offset', 5.0))
        current_time_str = now_dt.strftime("%H:%M")

        # Process PH-01 to PH-05
        for skey in ACTIVE_POLYHOUSES:
            port = SENSOR_MAP[skey]
            with sensor_data_lock: d = sensor_data.get(port, {})
            if d.get("status") != "OK":
                if sensor_consecutive_fails.get(skey, 0) >= 3:
                    msg = f"⚠ SENSOR FAULT: {get_sensor_display_name(skey)} Comm Error"
                    current_warnings.append(msg)
                    if not sensor_fault_logged.get(skey, False):
                        log_alarm_event(skey, msg, "OFFLINE", "ONLINE")
                        trigger_buzzer_pulse(5.0)
                        sensor_fault_logged[skey] = True
                else:
                    current_warnings.append(f"{get_sensor_display_name(skey)} RETRYING...")

                # Safe-State Strategy (Section 15):
                # Inhibit all active water requests to prevent flooding/runaway
                # Maintain ACF fan in safe cyclic circulation mode
                timer_acf = acf_timers[skey]
                t_on_sec = float(get_setpoints(skey).get("acf_on_min", 15)) * 60.0
                t_off_sec = float(get_setpoints(skey).get("acf_off_min", 30)) * 60.0
                if timer_acf["state"] == "ON" and (now - timer_acf["switch_time"]) >= t_on_sec:
                    timer_acf["state"] = "OFF"; timer_acf["switch_time"] = now
                elif timer_acf["state"] == "OFF" and (now - timer_acf["switch_time"]) >= t_off_sec:
                    timer_acf["state"] = "ON"; timer_acf["switch_time"] = now
                set_relay(RELAY_CH_ACF[skey], timer_acf["state"] == "ON")
                set_relay(RELAY_CH_FOGGER[skey], False)
                set_relay(RELAY_CH_SPRINKLER[skey], False)
                continue

            t, h = d['temp'], d['humi']
            sp_eval = get_active_setpoints(skey)
            mode = sp_eval.get("mode", "AUTO")

            t_target = sp_eval['target_temp']
            h_target = sp_eval['target_humi']
            t_min, t_max = sp_eval['T MIN'], sp_eval['T MAX']
            h_min, h_max = sp_eval['H MIN'], sp_eval['H MAX']

            # High/Low Deviation Alarms
            if t >= (t_target + temp_alarm_offset):
                msg = f"{get_sensor_display_name(skey)} High Temp ({t:.1f}°C > {t_target + temp_alarm_offset:.1f}°C)"
                current_warnings.append(msg)
                log_alarm_event(skey, msg, t, t_target)
            elif t <= (t_target - temp_alarm_offset):
                msg = f"{get_sensor_display_name(skey)} Low Temp ({t:.1f}°C < {t_target - temp_alarm_offset:.1f}°C)"
                current_warnings.append(msg)
                log_alarm_event(skey, msg, t, t_target)

            if h >= (h_target + humi_alarm_offset):
                msg = f"{get_sensor_display_name(skey)} High Humidity ({h:.1f}% > {h_target + humi_alarm_offset:.1f}%)"
                current_warnings.append(msg)
                log_alarm_event(skey, msg, h, h_target)
            elif h <= (h_target - humi_alarm_offset):
                msg = f"{get_sensor_display_name(skey)} Low Humidity ({h:.1f}% < {h_target - humi_alarm_offset:.1f}%)"
                current_warnings.append(msg)
                log_alarm_event(skey, msg, h, h_target)

            # --- MODE HANDLING ---
            if mode == "MANUAL":
                # Operator has manual command authority; do not overwrite relays
                continue

            elif mode == "CYCLIC":
                # Control122.py style Cyclic Timers (Timer 1: ACF Fans, Timer 2: Sprinkler, Timer 3: Fogger)
                # Timer 1: ACF Fans
                timer_acf = acf_timers[skey]
                t_on_sec = float(sp_eval.get("Timer1 ON Min", sp_eval.get("acf_on_min", 15))) * 60.0
                t_off_sec = float(sp_eval.get("Timer1 OFF Min", sp_eval.get("acf_off_min", 30))) * 60.0
                in_win_acf = is_within_window(sp_eval.get("Timer1 Start", "00:00"), sp_eval.get("Timer1 Stop", "23:59"))
                if in_win_acf:
                    if timer_acf["state"] == "ON" and (now - timer_acf["switch_time"]) >= t_on_sec:
                        timer_acf["state"] = "OFF"; timer_acf["switch_time"] = now
                    elif timer_acf["state"] == "OFF" and (now - timer_acf["switch_time"]) >= t_off_sec:
                        timer_acf["state"] = "ON"; timer_acf["switch_time"] = now
                    set_relay(RELAY_CH_ACF[skey], timer_acf["state"] == "ON")
                else:
                    timer_acf["state"] = "OFF"; timer_acf["switch_time"] = 0.0
                    set_relay(RELAY_CH_ACF[skey], False)

                # Timer 2: Sprinkler Valve
                spr_cyc = sprinkler_cyclic_timers[skey]
                dur_s = float(sp_eval.get("Timer2 ON Min", max(1, int(sp_eval.get("sprinkler_duration_sec", 120)) // 60))) * 60.0
                int_s = float(sp_eval.get("Timer2 OFF Min", sp_eval.get("sprinkler_interval_min", 30))) * 60.0
                in_win_spr = is_within_window(sp_eval.get("Timer2 Start", "06:00"), sp_eval.get("Timer2 Stop", "18:00"))
                if in_win_spr:
                    if spr_cyc["state"] == "ON" and (now - spr_cyc["switch_time"]) >= dur_s:
                        spr_cyc["state"] = "OFF"; spr_cyc["switch_time"] = now
                    elif spr_cyc["state"] == "OFF" and (now - spr_cyc["switch_time"]) >= int_s:
                        spr_cyc["state"] = "ON"; spr_cyc["switch_time"] = now
                    if spr_cyc["state"] == "ON":
                        water_requests.append(("SPRINKLER", skey))
                else:
                    spr_cyc["state"] = "OFF"; spr_cyc["switch_time"] = 0.0

                # Timer 3: Fogger Valve
                fog_cyc = fogger_cyclic_timers[skey]
                dur_f = float(sp_eval.get("Timer3 ON Min", max(1, int(sp_eval.get("fogger_min_on_sec", 60)) // 60))) * 60.0
                int_f = float(sp_eval.get("Timer3 OFF Min", max(1, int(sp_eval.get("fogger_min_off_sec", 120)) // 60))) * 60.0
                in_win_fog = is_within_window(sp_eval.get("Timer3 Start", "08:00"), sp_eval.get("Timer3 Stop", "17:00"))
                if in_win_fog:
                    if fog_cyc["state"] == "ON" and (now - fog_cyc["switch_time"]) >= dur_f:
                        fog_cyc["state"] = "OFF"; fog_cyc["switch_time"] = now
                    elif fog_cyc["state"] == "OFF" and (now - fog_cyc["switch_time"]) >= int_f:
                        fog_cyc["state"] = "ON"; fog_cyc["switch_time"] = now
                    if fog_cyc["state"] == "ON":
                        water_requests.append(("FOGGER", skey))
                else:
                    fog_cyc["state"] = "OFF"; fog_cyc["switch_time"] = 0.0

            elif mode in ["AUTO", "SCHEDULE"]:
                # Check scheduled irrigation/fogging slots (Screen 12)
                raw_sp = get_setpoints(skey)
                for islot in raw_sp.get("irrigation_slots", []):
                    if islot.get("enabled", True):
                        st_slot = format_time_24h(islot.get("start", "00:00"))
                        slot_id = islot.get("id", 1)
                        curr_active = active_scheduled_irrigation.get(skey)
                        if st_slot == current_time_str:
                            if not curr_active or curr_active.get("trig_minute") != current_time_str:
                                req_type = str(islot.get("type", "sprinkler")).upper()
                                dur_s = float(islot.get("duration_sec", 120))
                                active_scheduled_irrigation[skey] = {
                                    "type": req_type,
                                    "stop_time": now + dur_s,
                                    "slot_id": slot_id,
                                    "trig_minute": current_time_str
                                }
                                log_alarm_event(skey, f"Scheduled {req_type} Slot {slot_id} Started ({dur_s:.0f}s)", "RUNNING", "SCHEDULE")

                if skey in active_scheduled_irrigation:
                    sched_info = active_scheduled_irrigation[skey]
                    if now < sched_info["stop_time"]:
                        water_requests.append((sched_info["type"], skey))
                    else:
                        del active_scheduled_irrigation[skey]

                # Table 13 Environmental Control Matrix (Rev 02)
                t_hyst = float(sp_eval.get("temp_hysteresis", 1.0))
                h_hyst = float(sp_eval.get("humi_hysteresis", 3.0))

                is_high_t = (t >= (t_max + t_hyst))
                is_low_t = (t <= (t_min - t_hyst))
                is_normal_t = not (is_high_t or is_low_t)

                is_high_h = (h >= (h_max + h_hyst))
                is_low_h = (h <= (h_min - h_hyst))
                is_normal_h = not (is_high_h or is_low_h)

                req_fogger, req_sprinkler, req_acf_env = False, False, False

                if is_high_t and is_normal_h:
                    req_fogger, req_sprinkler, req_acf_env = True, True, True
                elif is_high_t and is_high_h:
                    req_fogger, req_sprinkler, req_acf_env = False, True, True
                    current_warnings.append(f"{get_sensor_display_name(skey)} High Temp & High Humidity")
                elif is_normal_t and is_low_h:
                    req_fogger, req_sprinkler, req_acf_env = True, False, True
                elif is_normal_t and is_normal_h:
                    req_fogger, req_sprinkler, req_acf_env = False, False, False
                elif is_low_h and not is_low_t:
                    req_fogger, req_sprinkler, req_acf_env = True, False, True
                elif is_high_h:
                    req_fogger, req_sprinkler, req_acf_env = False, False, True  # Ventilation
                    current_warnings.append(f"{get_sensor_display_name(skey)} High Humidity Ventilation")
                elif is_low_t and is_low_h:
                    req_fogger, req_sprinkler, req_acf_env = True, False, False
                elif is_low_t and is_normal_h:
                    req_fogger, req_sprinkler, req_acf_env = False, False, False

                # ACF Cyclic Timer fallback when cooling demand is idle
                timer_acf = acf_timers[skey]
                t_on_sec = float(sp_eval.get("acf_on_min", 15)) * 60.0
                t_off_sec = float(sp_eval.get("acf_off_min", 30)) * 60.0
                if timer_acf["state"] == "ON" and (now - timer_acf["switch_time"]) >= t_on_sec:
                    timer_acf["state"] = "OFF"; timer_acf["switch_time"] = now
                elif timer_acf["state"] == "OFF" and (now - timer_acf["switch_time"]) >= t_off_sec:
                    timer_acf["state"] = "ON"; timer_acf["switch_time"] = now

                acf_cyc_enabled = sp_eval.get("acf_cycle_enabled", True)
                req_acf_cyclic = (timer_acf["state"] == "ON") if acf_cyc_enabled else False
                final_acf = req_acf_env or req_acf_cyclic

                set_relay(RELAY_CH_ACF[skey], final_acf)
                if req_fogger: water_requests.append(("FOGGER", skey))
                if req_sprinkler: water_requests.append(("SPRINKLER", skey))

        # Check PH-06 (Monitoring-Only Zone)
        p6_port = SENSOR_MAP.get("PH-06")
        if p6_port:
            with sensor_data_lock: d6 = sensor_data.get(p6_port, {})
            if d6.get("status") == "OK":
                t6, h6 = d6['temp'], d6['humi']
                sp6 = get_setpoints("PH-06")
                t6_max = float(sp6.get("temp_high_limit", 32.0))
                h6_max = float(sp6.get("humi_high_limit", 85.0))
                if t6 >= t6_max:
                    msg = f"PH-06 High Temp ({t6:.1f}°C > {t6_max:.1f}°C)"
                    current_warnings.append(msg)
                    log_alarm_event("PH-06", msg, t6, t6_max)
                if h6 >= h6_max:
                    msg = f"PH-06 High Humidity ({h6:.1f}% > {h6_max:.1f}%)"
                    current_warnings.append(msg)
                    log_alarm_event("PH-06", msg, h6, h6_max)

        # 3. SHARED PUMP ARBITRATION & INTERLOCK ROUTINE (Section 9.4)
        arb_mode = system_config.get("pump_arbitration_mode", "sequential")
        start_delay = float(system_config.get("pump_start_delay_sec", 3.0))
        post_run_delay = float(system_config.get("pump_post_run_delay_sec", 3.0))

        if not water_requests:
            # No water demand: stop pump with post-run delay, then close solenoids
            if pump_active:
                if pump_stop_scheduled_time == 0:
                    pump_stop_scheduled_time = now + post_run_delay
                elif now >= pump_stop_scheduled_time:
                    set_relay(RELAY_CH_COMMON_PUMP, False)
                    pump_active = False
                    pump_stop_scheduled_time = 0
                    for ph in ACTIVE_POLYHOUSES:
                        set_relay(RELAY_CH_FOGGER[ph], False)
                        set_relay(RELAY_CH_SPRINKLER[ph], False)
                    active_water_zone = None
            else:
                set_relay(RELAY_CH_COMMON_PUMP, False)
                for ph in ACTIVE_POLYHOUSES:
                    set_relay(RELAY_CH_FOGGER[ph], False)
                    set_relay(RELAY_CH_SPRINKLER[ph], False)
                active_water_zone = None
        else:
            pump_stop_scheduled_time = 0
            if arb_mode == "parallel":
                # Open all requested valves first
                for ph in ACTIVE_POLYHOUSES:
                    f_req = ("FOGGER", ph) in water_requests
                    s_req = ("SPRINKLER", ph) in water_requests
                    set_relay(RELAY_CH_FOGGER[ph], f_req)
                    set_relay(RELAY_CH_SPRINKLER[ph], s_req)

                if not pump_active:
                    time.sleep(start_delay)
                    set_relay(RELAY_CH_COMMON_PUMP, True)
                    pump_active = True
                active_water_zone = "PARALLEL (ALL ACTIVE)"
            else:
                # Sequential Priority Arbitration: run one zone at a time
                req_keys = [f"{t}:{p}" for t, p in water_requests]
                if active_water_zone not in req_keys:
                    active_water_zone = req_keys[0]
                    active_water_zone_start = now
                elif now - active_water_zone_start > 120.0:
                    idx = (req_keys.index(active_water_zone) + 1) % len(req_keys)
                    active_water_zone = req_keys[idx]
                    active_water_zone_start = now

                act_type, act_ph = active_water_zone.split(":")
                for ph in ACTIVE_POLYHOUSES:
                    set_relay(RELAY_CH_FOGGER[ph], (act_type == "FOGGER" and ph == act_ph))
                    set_relay(RELAY_CH_SPRINKLER[ph], (act_type == "SPRINKLER" and ph == act_ph))

                if not pump_active:
                    time.sleep(start_delay)
                    set_relay(RELAY_CH_COMMON_PUMP, True)
                    pump_active = True

        # 4. BUZZER HARDWARE ROUTINE WITH 30-SECOND AUTO-SILENCE
        active_warnings = current_warnings
        if active_warnings:
            if not buzzer_active and not buzzer_silenced_for_current_alarm:
                buzzer_active = True
                buzzer_start_time = now
                set_relay(BUZZER_CHANNEL, True)
            elif buzzer_active:
                silence_limit = float(system_config.get("buzzer_auto_silence_sec", 30))
                if now - buzzer_start_time >= silence_limit:
                    set_relay(BUZZER_CHANNEL, False)
                    buzzer_active = False
                    buzzer_silenced_for_current_alarm = True
        else:
            if buzzer_active:
                set_relay(BUZZER_CHANNEL, False)
                buzzer_active = False
            buzzer_silenced_for_current_alarm = False

        # 5. CLOUD MQTT PUBLISH AT CONFIGURABLE INTERVAL
        upload_freq_sec = float(system_config.get('upload_frequency_min', 1.0)) * 60.0
        if upload_freq_sec <= 0 or (now - last_upload_time) >= upload_freq_sec:
            broadcast_current_state()
            last_upload_time = now

        # 6. LOCAL OFFLINE DATA BUFFERING (Sections 16 & 17)
        with sensor_data_lock: snap_sensor = dict(sensor_data)
        with dli_lock: snap_dli = dict(dli_data)
        save_local_telemetry_if_offline(snap_sensor, snap_dli, relay_states, pump_active)

        time.sleep(1.0)

# -----------------------------------------------------------------------------
# TKINTER GRAPHICAL USER INTERFACE (HMI)
# -----------------------------------------------------------------------------
root = tk.Tk()
root.title("INHYDRO ITC Polyhouse Automation System")
is_kiosk = "--fullscreen" in sys.argv or os.path.exists("/etc/rpi-issue")
root.attributes("-fullscreen", is_kiosk)
root.geometry("1024x600")
root.bind("<Escape>", lambda event: root.attributes("-fullscreen", False))
root.bind("<F11>", lambda event: root.attributes("-fullscreen", not bool(root.attributes("-fullscreen"))))
root.protocol("WM_DELETE_WINDOW", lambda: quit_app())
root.configure(bg="white")

big = font.Font(family="Helvetica", size=14, weight="bold")
med = font.Font(family="Helvetica", size=10, weight="bold")
small = font.Font(family="Helvetica", size=9)

FRAME_BTN_WIDTH = 18
FRAME_BTN_HEIGHT = 2
BTN_FONT_MAIN = ("Helvetica", 10, "bold")
BTN_FONT_INLINE = ("Helvetica", 8, "bold")

def quit_app():
    global running
    print("[APP] Shutting down ITC Polyhouse Controller gracefully...")
    running = False
    emergency_stop_all()
    try: root.destroy()
    except Exception: pass
    sys.exit(0)

def restart_program():
    global running
    running = False
    emergency_stop_all()
    try: root.destroy()
    except Exception: pass
    os.execv(sys.executable, ['python3'] + sys.argv)

# Main UI Frames
frame_main = tk.Frame(root, bg="white")
frame_detail = tk.Frame(root, bg="white")
frame_set = tk.Frame(root, bg="white")
frame_schedule = tk.Frame(root, bg="white")

def add_logo(parent):
    try:
        path = os.path.join(BASE_DIR, "logo.png")
        if os.path.exists(path):
            img = Image.open(path)
            width, height = 140, 50
            img = img.resize((width, height), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(parent, image=photo, bg="white")
            lbl.image = photo
            lbl.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=12)
            lbl.lift()
            return lbl
    except Exception: pass
    return None

def add_top_left_exit(parent):
    btn_exit = tk.Button(
        parent,
        text="✖ EXIT",
        font=("Helvetica", 11, "bold"),
        bg="#dc2626",
        fg="white",
        activebackground="#b91c1c",
        activeforeground="white",
        relief="flat",
        bd=0,
        padx=14,
        pady=10,
        cursor="hand2",
        command=quit_app
    )
    btn_exit.place(relx=0.0, rely=0.0, anchor="nw", x=20, y=12)
    btn_exit.lift()
    return btn_exit

clock_labels = []

def add_bottom_right_clock(parent, bg_color="white"):
    lbl = tk.Label(
        parent,
        text=" Day, YYYY-MM-DD\n hh:mm:ss AM/PM (IST)",
        font=("Helvetica", 10, "bold"),
        fg="#00897b",
        bg=bg_color,
        justify="right",
        padx=10,
        pady=4
    )
    lbl.place(relx=1.0, rely=1.0, anchor="se", x=-15, y=-10)
    lbl.lift()
    clock_labels.append(lbl)
    return lbl

def show(frame):
    for f in [frame_main, frame_detail, frame_set, frame_schedule]:
        f.pack_forget()
    frame.pack(fill="both", expand=True)
    add_logo(frame)
    add_top_left_exit(frame)
    if frame != frame_main:
        add_bottom_right_clock(frame)

# -----------------------------------------------------------------------------
# SCREEN 02: MAIN DASHBOARD (frame_main)
# -----------------------------------------------------------------------------
lbl_title = tk.Label(frame_main, text="INHYDRO ITC POLYHOUSE AUTOMATION DASHBOARD", font=big, fg="#1565c0", bg="white")
lbl_title.pack(pady=(35, 6))

lbl_warning_bar = tk.Label(frame_main, text="SYSTEM NORMAL", font=med, bg="#2e7d32", fg="white", height=2)
lbl_warning_bar.pack(fill="x", padx=15, pady=4)

sensors_grid = tk.Frame(frame_main, bg="white")
sensors_grid.pack(pady=6)
sensor_widgets = {}

footer_main = tk.Frame(frame_main, bg="#f1f5f9", height=80, bd=1, relief="solid", highlightbackground="#cbd5e1")
footer_main.pack(side="bottom", fill="x")
footer_main.pack_propagate(False)

btn_setpoints_timers = tk.Button(footer_main, text="SETPOINTS & TIMERS", font=("Helvetica", 11, "bold"), width=22, height=FRAME_BTN_HEIGHT, bg="#0284c7", fg="white", cursor="hand2", command=lambda: check_pin_and_proceed("Setpoints & Timers", lambda: open_setpoints("PH-01")))
btn_setpoints_timers.pack(side="left", padx=12, pady=10)

btn_sys_settings = tk.Button(footer_main, text="SETTINGS", font=("Helvetica", 11, "bold"), width=16, height=FRAME_BTN_HEIGHT, bg="#0891b2", fg="white", cursor="hand2", command=lambda: check_pin_and_proceed("System Settings", open_system_settings_modal))
btn_sys_settings.pack(side="left", padx=12, pady=10)

btn_restart_app = tk.Button(footer_main, text="RESTART", font=("Helvetica", 11, "bold"), width=14, height=FRAME_BTN_HEIGHT, bg="#1565c0", fg="white", cursor="hand2", command=lambda: restart_program())
btn_restart_app.pack(side="left", padx=12, pady=10)

lbl_clock = tk.Label(footer_main, text="Day, YYYY-MM-DD\n hh:mm:ss AM/PM (IST)", font=("Helvetica", 10, "bold"), fg="#00897b", bg="#f1f5f9", justify="right")
lbl_clock.pack(side="right", padx=15, pady=5)

def update_clock_display():
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist_tz)
    now_str = now.strftime(" %A, %Y-%m-%d\n %I:%M:%S %p (IST)")
    if 'lbl_clock' in globals() and lbl_clock.winfo_exists():
        lbl_clock.config(text=now_str)
    for lbl in list(clock_labels):
        try:
            if lbl.winfo_exists(): lbl.config(text=now_str)
            else: clock_labels.remove(lbl)
        except Exception: pass
    root.after(1000, update_clock_display)

def toggle_pause():
    global system_paused
    system_paused = not system_paused
    if system_paused:
        emergency_stop_all()
        if 'btn_pause' in globals() and btn_pause.winfo_exists():
            btn_pause.config(text="RESUME RUN", bg="#2e7d32")
    else:
        if 'btn_pause' in globals() and btn_pause.winfo_exists():
            btn_pause.config(text="STOP ALL", bg="#c62828")

def rebuild_grid():
    for i in range(10):
        sensors_grid.columnconfigure(i, weight=0)
        sensors_grid.rowconfigure(i, weight=0)
    idx = 0
    for skey in ALL_POLYHOUSES:
        if skey in sensor_widgets:
            r, c = idx // 3, idx % 3
            sensor_widgets[skey].grid(row=r, column=c, padx=10, pady=8)
            idx += 1

# -----------------------------------------------------------------------------
# SCREEN 04-09: POLYHOUSE DETAILED CONTROL & MONITORING (frame_detail)
# -----------------------------------------------------------------------------
active_detail_port = None
active_detail_skey = "PH-01"

lbl_detail_title = tk.Label(frame_detail, text="POLYHOUSE DETAILS", font=big, fg="#1565c0", bg="white")
lbl_detail_title.pack(pady=(35, 4))

txt_detail_data = tk.Text(frame_detail, font=font.Font(size=11, weight="bold"), bg="white", bd=0, highlightthickness=0, height=16, width=75)
txt_detail_data.pack(pady=10, expand=True, fill="both")
txt_detail_data.tag_configure("black", foreground="#000000", justify="center")
txt_detail_data.tag_configure("blue", foreground="#1565c0", justify="center")
txt_detail_data.tag_configure("green", foreground="#16a34a", justify="center")
txt_detail_data.tag_configure("red", foreground="#c62828", justify="center")
txt_detail_data.tag_configure("grey", foreground="#64748b", justify="center")

footer_det = tk.Frame(frame_detail, bg="#f1f5f9", height=80, bd=1, relief="solid", highlightbackground="#cbd5e1")
footer_det.pack(side="bottom", fill="x")
footer_det.pack_propagate(False)

btn_back_det = tk.Button(footer_det, text="BACK TO DASHBOARD", font=("Helvetica", 11, "bold"), bg="#64748b", fg="white", width=20, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: show(frame_main))
btn_back_det.pack(side="left", padx=12, pady=10)

btn_set_det = tk.Button(footer_det, text="SETPOINTS & TIMERS", font=("Helvetica", 11, "bold"), bg="#0284c7", fg="white", width=22, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: check_pin_and_proceed("Configure Setpoints & Timers", lambda: open_setpoints(active_detail_port)))
btn_set_det.pack(side="left", padx=12, pady=10)

btn_rename_det = tk.Button(footer_det, text="RENAME", font=("Helvetica", 11, "bold"), bg="#d97706", fg="white", width=14, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: edit_active_polyhouse_name())
btn_rename_det.pack(side="left", padx=12, pady=10)

lbl_clock_det = tk.Label(footer_det, text="Day, YYYY-MM-DD\n hh:mm:ss AM/PM (IST)", font=("Helvetica", 10, "bold"), fg="#00897b", bg="#f1f5f9", justify="right")
lbl_clock_det.pack(side="right", padx=15, pady=5)
clock_labels.append(lbl_clock_det)

def open_sensor_detail(port):
    global active_detail_port, active_detail_skey
    active_detail_port = port
    active_detail_skey = next((k for k, v in SENSOR_MAP.items() if v == port), "PH-01")
    if active_detail_skey == "PH-06":
        lbl_detail_title.config(text=f"{get_sensor_display_name(active_detail_skey)} — ENVIRONMENTAL MONITORING")
        btn_set_det.config(text="LIMITS")
    else:
        lbl_detail_title.config(text=f"{get_sensor_display_name(active_detail_skey)} — DETAILED MONITORING")
        btn_set_det.pack(side="left", padx=12, pady=10, after=btn_back_det)
        btn_rename_det.pack(side="left", padx=12, pady=10, after=btn_set_det)
        btn_set_det.config(text="SETPOINTS & TIMERS")
    show(frame_detail)

def edit_active_polyhouse_name():
    curr_name = get_sensor_display_name(active_detail_skey)
    def on_confirm(new_name):
        if new_name and new_name.strip():
            system_config.setdefault("sensor_names", {})[active_detail_skey] = new_name.strip()
            save_config()
            lbl_detail_title.config(text=f"{new_name.strip()} — DETAILED CONTROL")
            update_ui()
    open_almora_keypad(f"Rename ({active_detail_skey})", curr_name, on_confirm, is_alphanumeric=True)

# -----------------------------------------------------------------------------
# SCREEN 10 & 11: UNIFIED SETPOINTS & CYCLIC TIMERS (MONIT.PY DESIGN)
# -----------------------------------------------------------------------------
active_setup_skey = "PH-01"

lbl_set_title = tk.Label(frame_set, text="SYSTEM SETPOINTS & CYCLIC TIMERS CONFIGURATION", font=big, fg="#1565c0", bg="#ffffff")
lbl_set_title.pack(pady=(35, 4))

set_ph_bar = tk.Frame(frame_set, bg="#ffffff")
set_ph_bar.pack(pady=4)

tk.Label(set_ph_bar, text="SELECT POLYHOUSE:", font=("Arial", 11, "bold"), bg="#ffffff", fg="#475569").pack(side="left", padx=6)

set_ph_buttons = {}
for ph in ALL_POLYHOUSES:
    b_ph = tk.Button(set_ph_bar, text=ph, font=("Arial", 10, "bold"), bg="#e2e8f0", fg="#1e293b",
                     width=9, height=1, relief="flat", bd=0, cursor="hand2")
    b_ph.config(command=lambda p=ph: switch_setpoint_house(p))
    b_ph.pack(side="left", padx=3)
    set_ph_buttons[ph] = b_ph

# Footer packed at bottom
footer_set = tk.Frame(frame_set, bg="#ffffff", height=50)
footer_set.pack(side="bottom", fill="x")
footer_set.pack_propagate(False)

tk.Button(footer_set, text="SAVE & RETURN", font=BTN_FONT_MAIN, bg="#0284c7", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2",
          command=lambda: (save_setpoints(), show(frame_main))).pack(side="left", padx=15, pady=6)
tk.Button(footer_set, text="BACK TO DASHBOARD", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2",
          command=lambda: show(frame_main)).pack(side="left", padx=10, pady=6)

# Scrollable Canvas for Setpoints & Cyclic Timers (monit.py style)
sp_canvas = tk.Canvas(frame_set, bg="#ffffff", highlightthickness=0)
sp_scrollbar = tk.Scrollbar(frame_set, orient="vertical", command=sp_canvas.yview, width=22, bd=2, relief="raised")
sp_container = tk.Frame(sp_canvas, bg="#ffffff")

sp_canvas_win = sp_canvas.create_window((0, 0), window=sp_container, anchor="nw")

def _on_sp_container_cfg(e):
    sp_canvas.configure(scrollregion=sp_canvas.bbox("all"))

def _on_sp_canvas_resize(e):
    sp_canvas.itemconfig(sp_canvas_win, width=e.width)

sp_container.bind("<Configure>", _on_sp_container_cfg)
sp_canvas.bind("<Configure>", _on_sp_canvas_resize)
sp_canvas.configure(yscrollcommand=sp_scrollbar.set)

sp_scrollbar.pack(side="right", fill="y", pady=(10, 0))
sp_canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(10, 0))

def switch_setpoint_house(ph):
    global active_setup_skey
    active_setup_skey = ph
    for p, b in set_ph_buttons.items():
        if p == active_setup_skey: b.config(bg="#0284c7", fg="white")
        else: b.config(bg="#e2e8f0", fg="#1e293b")
    render_unified_setpoints_view()

def open_setpoints(port_or_skey):
    global active_setup_skey
    if port_or_skey in ALL_POLYHOUSES:
        found_skey = port_or_skey
    else:
        found_skey = "PH-01"
        for k, v in SENSOR_MAP.items():
            if v == port_or_skey: found_skey = k; break

    active_setup_skey = found_skey
    for p, b in set_ph_buttons.items():
        if p == active_setup_skey: b.config(bg="#0284c7", fg="white")
        else: b.config(bg="#e2e8f0", fg="#1e293b")
    render_unified_setpoints_view()
    show(frame_set)

def open_schedule_editor(skey):
    open_setpoints(skey)

def make_sp_cell(parent, ph, key, label_text=None, width_lbl=11, default_val=0.0):
    sp = get_setpoints(ph)
    if key not in sp:
        sp[key] = default_val
    lbl_txt = label_text if label_text else key
    cell = tk.Frame(parent, bg="#ffffff")

    tk.Label(cell, text=lbl_txt, font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", anchor="w", width=width_lbl).pack(side="left", padx=2)
    val_lbl = tk.Label(cell, text=str(sp[key]), font=("Arial", 10, "bold"), fg="#e65100", bg="#f8fafc", width=6, anchor="center", relief="sunken", bd=1)
    val_lbl.pack(side="left", padx=(2, 4))

    def _on_confirm(val):
        try:
            fval = round(float(val), 1)
            sp[key] = fval
            val_lbl.config(text=str(fval))
            save_setpoints()
        except Exception: pass

    btn = tk.Button(cell, text="EDIT", font=("Arial", 9, "bold"), width=5, bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="raised", pady=1, padx=3,
                    command=lambda: open_almora_keypad(f"Set {ph} {lbl_txt}", val_lbl.cget("text"), _on_confirm))
    btn.pack(side="right", padx=2)
    return cell

def render_unified_setpoints_view():
    for w in sp_container.winfo_children(): w.destroy()

    ph = active_setup_skey
    sp = get_setpoints(ph)
    disp_name = get_sensor_display_name(ph)

    lbl_set_title.config(text=f"SETPOINTS & CYCLIC TIMERS : {disp_name}")

    if ph == "PH-06":
        # Monitoring-Only Zone Card (PH-06)
        card_m = tk.LabelFrame(sp_container, text=f" {disp_name} — ENVIRONMENTAL MONITORING THRESHOLDS ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
        card_m.pack(fill="x", pady=10, padx=10)

        grid_m = tk.Frame(card_m, bg="#ffffff")
        grid_m.pack(pady=10, padx=15, fill="x")
        grid_m.columnconfigure(0, weight=1)
        grid_m.columnconfigure(1, weight=1)

        make_sp_cell(grid_m, ph, "temp_high_limit", "Temp High Max (°C):", width_lbl=20, default_val=32.0).grid(row=0, column=0, padx=10, pady=6, sticky="ew")
        make_sp_cell(grid_m, ph, "temp_low_limit", "Temp Low Min (°C):", width_lbl=20, default_val=15.0).grid(row=0, column=1, padx=10, pady=6, sticky="ew")
        make_sp_cell(grid_m, ph, "humi_high_limit", "RH High Max (%):", width_lbl=20, default_val=85.0).grid(row=1, column=0, padx=10, pady=6, sticky="ew")
        make_sp_cell(grid_m, ph, "humi_low_limit", "RH Low Min (%):", width_lbl=20, default_val=35.0).grid(row=1, column=1, padx=10, pady=6, sticky="ew")
        return

    # TOP SECTION: Climate Control (Full Width)
    card_climate = tk.LabelFrame(sp_container, text=f" {disp_name} CLIMATE CONTROL ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
    card_climate.pack(fill="x", side="top", pady=(0, 6), padx=4)

    grid_climate = tk.Frame(card_climate, bg="#ffffff")
    grid_climate.pack(pady=4, padx=6, fill="x")

    # Left Column: Temperature Setpoints
    temp_section = tk.Frame(grid_climate, bg="#ffffff")
    temp_section.pack(side="left", fill="both", expand=True, padx=4)
    tk.Label(temp_section, text="TEMPERATURE SETPOINTS", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff").pack(anchor="w", pady=(1, 3))
    make_sp_cell(temp_section, ph, "temp_low", "Temp Min:").pack(fill="x", pady=2)
    make_sp_cell(temp_section, ph, "temp_target", "Temp Set:").pack(fill="x", pady=2)
    make_sp_cell(temp_section, ph, "temp_high", "Temp Max:").pack(fill="x", pady=2)
    make_sp_cell(temp_section, ph, "temp_hysteresis", "Hysteresis:").pack(fill="x", pady=2)

    # Vertical Separator
    tk.Frame(grid_climate, bg="#cbd5e1", width=1).pack(side="left", fill="y", padx=8, pady=2)

    # Right Column: Humidity Setpoints
    humi_section = tk.Frame(grid_climate, bg="#ffffff")
    humi_section.pack(side="right", fill="both", expand=True, padx=4)
    tk.Label(humi_section, text="HUMIDITY SETPOINTS", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff").pack(anchor="w", pady=(1, 3))
    make_sp_cell(humi_section, ph, "humi_low", "RH Min:").pack(fill="x", pady=2)
    make_sp_cell(humi_section, ph, "humi_target", "RH Set:").pack(fill="x", pady=2)
    make_sp_cell(humi_section, ph, "humi_high", "RH Max:").pack(fill="x", pady=2)
    make_sp_cell(humi_section, ph, "humi_hysteresis", "Hysteresis:").pack(fill="x", pady=2)

    # BOTTOM SECTION: CYCLIC TIMERS (Exact control122.py make_tabular_timers_card design)
    sp_bottom_container = tk.Frame(sp_container, bg="#ffffff")
    sp_bottom_container.pack(fill="x", side="top", pady=(4, 6), padx=4)

    card_font = ("Arial", 11, "bold")
    color = "#1565c0"
    card_timers_1 = tk.LabelFrame(sp_bottom_container, text=f" {disp_name} CYCLIC TIMERS ", font=card_font, fg=color, bg="white", bd=2, relief="groove")
    card_timers_1.pack(fill="x", pady=(3, 6), padx=4)

    cols = [
        {"name": "Timer 1 (ACF)", "keys": {
            "Name": "Timer1 Name", "Start": "Timer1 Start", "Stop": "Timer1 Stop", "ON Min": "Timer1 ON Min", "OFF Min": "Timer1 OFF Min"
        }},
        {"name": "Timer 2 (Sprinkler)", "keys": {
            "Name": "Timer2 Name", "Start": "Timer2 Start", "Stop": "Timer2 Stop", "ON Min": "Timer2 ON Min", "OFF Min": "Timer2 OFF Min"
        }},
        {"name": "Timer 3 (Fogger)", "keys": {
            "Name": "Timer3 Name", "Start": "Timer3 Start", "Stop": "Timer3 Stop", "ON Min": "Timer3 ON Min", "OFF Min": "Timer3 OFF Min"
        }},
    ]

    lbl_font = ("Arial", 10, "bold")
    btn_font = ("Arial", 9, "bold")

    header_frame = tk.Frame(card_timers_1, bg="#f5f5f5")
    header_frame.pack(fill="x", pady=2, padx=2)
    tk.Label(header_frame, text="Setting", font=lbl_font, fg="#555", bg="#f5f5f5", width=12, anchor="w").pack(side="left", padx=2)
    for col in cols:
        tk.Label(header_frame, text=col["name"], font=lbl_font, fg=color, bg="#f5f5f5", width=15, anchor="center").pack(side="left", expand=True)

    row_keys = [("Name", "Name:"), ("Start", "Start:"), ("Stop", "Stop:"), ("ON Min", "ON Min:"), ("OFF Min", "OFF Min:")]

    for r_key, r_lbl in row_keys:
        r_frame = tk.Frame(card_timers_1, bg="white")
        r_frame.pack(fill="x", pady=3, padx=2)

        tk.Label(r_frame, text=r_lbl, font=lbl_font, fg="#555", bg="white", width=12, anchor="w").pack(side="left", padx=2)

        for col in cols:
            col_frame = tk.Frame(r_frame, bg="white")
            col_frame.pack(side="left", expand=True, fill="x")

            full_key = col["keys"][r_key]
            val_lbl = tk.Label(col_frame, text=str(sp.get(full_key, "")),
                               font=lbl_font, fg="#e65100" if r_key != "Name" else "#333", bg="white", width=10, anchor="center")
            val_lbl.pack(side="left", expand=True)

            def _make_timer_edit(k=full_key, l=val_lbl, rk=r_key, ph_name=ph):
                def _confirm(val):
                    try:
                        if rk in ["ON Min", "OFF Min"]:
                            iv = int(float(val))
                            sp[k] = iv
                            if k == "Timer1 ON Min": sp["acf_on_min"] = iv
                            elif k == "Timer1 OFF Min": sp["acf_off_min"] = iv
                            elif k == "Timer2 ON Min": sp["sprinkler_duration_sec"] = iv * 60
                            elif k == "Timer2 OFF Min": sp["sprinkler_interval_min"] = iv
                            elif k == "Timer3 ON Min": sp["fogger_min_on_sec"] = iv * 60
                            elif k == "Timer3 OFF Min": sp["fogger_min_off_sec"] = iv * 60
                        else:
                            sp[k] = str(val).strip()
                        l.config(text=str(sp[k]))
                        save_setpoints()
                    except Exception: pass

                is_alpha = (rk == "Name")
                kmode = "alphanumeric" if is_alpha else ("time" if rk in ["Start", "Stop"] else "numeric")
                open_almora_keypad(f"Edit {ph_name} {k}", str(l.cget("text")), _confirm, is_alphanumeric=is_alpha, mode=kmode)

            btn = tk.Button(col_frame, text="EDIT", font=btn_font, bg="#f5f5f5", fg="#333",
                            activebackground=color, activeforeground="white", bd=1, relief="groove",
                            command=_make_timer_edit)
            btn.pack(side="right", padx=2)



# -----------------------------------------------------------------------------
# SCREEN 17: SYSTEM SETTINGS MODAL
# -----------------------------------------------------------------------------
def open_system_settings_modal():
    modal = tk.Toplevel(root)
    modal.configure(bg="white")
    modal.attributes("-fullscreen", True)
    add_logo(modal)
    add_top_left_exit(modal)
    add_bottom_right_clock(modal)

    m_main = tk.Frame(modal, bg="white")
    m_main.pack(fill="both", expand=True, pady=(50, 40))

    tk.Label(m_main, text="SCREEN 17 : SYSTEM CONFIGURATION & INTERLOCK SETTINGS", font=big, fg="#0891b2", bg="white").pack(pady=10)

    cfg_container = tk.Frame(m_main, bg="white")
    cfg_container.pack(pady=10)

    params = [
        ("Cloud Upload Frequency (min)", "upload_frequency_min", system_config.get("upload_frequency_min", 1.0)),
        ("Temp High Alarm Offset (°C)", "temp_alarm_offset", system_config.get("temp_alarm_offset", 5.0)),
        ("RH High Alarm Offset (%)", "humi_alarm_offset", system_config.get("humi_alarm_offset", 5.0)),
        ("System Security PIN", "system_password", system_config.get("system_password", "1234")),
        ("Pump Start Delay (sec)", "pump_start_delay_sec", system_config.get("pump_start_delay_sec", 3.0)),
        ("Pump Stop/Post-Run Delay (sec)", "pump_post_run_delay_sec", system_config.get("pump_post_run_delay_sec", 3.0)),
        ("Buzzer Auto-Silence Limit (sec)", "buzzer_auto_silence_sec", system_config.get("buzzer_auto_silence_sec", 30))
    ]

    for label_t, k_name, val_curr in params:
        row = tk.Frame(cfg_container, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=10, pady=6)
        row.pack(pady=4, fill="x")

        tk.Label(row, text=label_t, font=("Helvetica", 11, "bold"), width=30, bg="white", fg="#1e293b", anchor="w").pack(side="left")
        lbl_v = tk.Label(row, text=str(val_curr), font=("Helvetica", 11, "bold"), fg="#0891b2", bg="#f1f5f9", width=10, relief="sunken", bd=1)
        lbl_v.pack(side="left", padx=10)

        def _edit(k=k_name, l=lbl_v, t=label_t):
            def _confirm(new_val):
                try:
                    if k == "system_password":
                        val_s = str(new_val).strip()
                        if val_s:
                            system_config[k] = val_s
                            l.config(text=val_s)
                            save_config()
                    else:
                        fval = float(new_val)
                        system_config[k] = fval
                        l.config(text=str(fval))
                        save_config()
                except Exception: pass
            open_almora_keypad(f"Edit {t}", l.cget("text"), _confirm)

        tk.Button(row, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", width=8, command=_edit).pack(side="left")

    # Pump Arbitration Mode Selector
    arb_row = tk.Frame(cfg_container, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=10, pady=8)
    arb_row.pack(pady=6, fill="x")
    tk.Label(arb_row, text="Pump Arbitration Mode:", font=("Helvetica", 11, "bold"), width=30, bg="white", fg="#1e293b", anchor="w").pack(side="left")

    curr_arb = system_config.get("pump_arbitration_mode", "sequential").upper()
    lbl_arb = tk.Label(arb_row, text=curr_arb, font=("Helvetica", 11, "bold"), fg="#ea580c", bg="#f1f5f9", width=16, relief="sunken", bd=1)
    lbl_arb.pack(side="left", padx=10)

    def _toggle_arb():
        curr = system_config.get("pump_arbitration_mode", "sequential").lower()
        new_arb = "parallel" if curr == "sequential" else "sequential"
        system_config["pump_arbitration_mode"] = new_arb
        lbl_arb.config(text=new_arb.upper())
        save_config()

    tk.Button(arb_row, text="TOGGLE MODE", font=BTN_FONT_INLINE, bg="#cbd5e1", width=12, command=_toggle_arb).pack(side="left")

    tk.Button(m_main, text="SAVE & CLOSE", font=BTN_FONT_MAIN, bg="#0891b2", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=modal.destroy).pack(pady=20)

# -----------------------------------------------------------------------------
# SCREEN 15: ALARM HISTORY MODAL
# -----------------------------------------------------------------------------
def open_alarm_history_modal():
    modal = tk.Toplevel(root)
    modal.configure(bg="white")
    modal.attributes("-fullscreen", True)
    add_logo(modal)
    add_top_left_exit(modal)
    add_bottom_right_clock(modal)

    m_main = tk.Frame(modal, bg="white")
    m_main.pack(fill="both", expand=True, pady=(50, 40), padx=30)

    tk.Label(m_main, text="SCREEN 15 : ALARM LOGS & EVENT HISTORY", font=big, fg="#c62828", bg="white").pack(pady=6)

    txt_logs = tk.Text(m_main, font=("Courier", 10), bg="#f8fafc", bd=1, relief="solid", highlightbackground="#cbd5e1", height=20)
    txt_logs.pack(fill="both", expand=True, pady=10)

    if os.path.exists(ALARM_LOG_FILE):
        try:
            with open(ALARM_LOG_FILE, "r") as f:
                lines = f.readlines()
                for l in reversed(lines[-50:]):
                    try:
                        item = json.loads(l)
                        ts = item.get("timestamp", "").split(".")[0].replace("T", " ")
                        txt_logs.insert("end", f"[{ts}] {item.get('sensor_name')}: {item.get('message')}\n")
                    except Exception:
                        txt_logs.insert("end", l)
        except Exception as e:
            txt_logs.insert("end", f"Log read error: {e}")
    else:
        txt_logs.insert("end", "No logged alarm events.")

    txt_logs.config(state="disabled")
    tk.Button(m_main, text="CLOSE", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=modal.destroy).pack(pady=10)

# -----------------------------------------------------------------------------
# SCREEN 16: COMMUNICATION & DEVICE HEALTH DIAGNOSTICS MODAL
# -----------------------------------------------------------------------------
def open_comm_health_modal():
    modal = tk.Toplevel(root)
    modal.configure(bg="white")
    modal.attributes("-fullscreen", True)
    add_logo(modal)
    add_top_left_exit(modal)
    add_bottom_right_clock(modal)

    m_main = tk.Frame(modal, bg="white")
    m_main.pack(fill="both", expand=True, pady=(50, 40), padx=30)

    tk.Label(m_main, text="SCREEN 16 : COMMUNICATION & DEVICE HEALTH DIAGNOSTICS", font=big, fg="#0d9488", bg="white").pack(pady=6)

    cards_f = tk.Frame(m_main, bg="white")
    cards_f.pack(fill="both", expand=True, pady=10)

    # Left: Hardware Serial Ports
    left_card = tk.LabelFrame(cards_f, text="RS485 SENSOR & RELAY HARDWARE PORTS", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white", padx=10, pady=8)
    left_card.pack(side="left", fill="both", expand=True, padx=8)

    for ph, port in SENSOR_MAP.items():
        exists = os.path.exists(port)
        rf = tk.Frame(left_card, bg="white"); rf.pack(fill="x", pady=2)
        tk.Label(rf, text=f"{ph} Temp/RH Port:", font=("Helvetica", 10, "bold"), width=18, anchor="w", bg="white", fg="#1e293b").pack(side="left")
        tk.Label(rf, text=f"{'CONNECTED' if exists else 'NOT DETECTED'}", font=("Helvetica", 9, "bold"), fg="#16a34a" if exists else "#dc2626", bg="white").pack(side="left")

    r_port = system_config.get("relay_port", RELAY_PORT_FIXED)
    r_exists = os.path.exists(r_port)
    rf_rel = tk.Frame(left_card, bg="white"); rf_rel.pack(fill="x", pady=(6, 2))
    tk.Label(rf_rel, text="32-Ch Relay Port:", font=("Helvetica", 10, "bold"), width=18, anchor="w", bg="white", fg="#1e293b").pack(side="left")
    tk.Label(rf_rel, text=f"{'CONNECTED (ID ' + str(working_relay_id or 'Scan') + ')' if r_exists else 'NOT DETECTED'}", font=("Helvetica", 9, "bold"), fg="#16a34a" if r_exists else "#dc2626", bg="white").pack(side="left")

    # Right: Cloud Link & Subsystems
    right_card = tk.LabelFrame(cards_f, text="NETWORK, CLOUD & PERSISTENCE SUBSYSTEMS", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white", padx=10, pady=8)
    right_card.pack(side="right", fill="both", expand=True, padx=8)

    net_items = [
        ("Cloud Broker Link:", f"Mosquitto VPS ({CONTROL_BROKER})", "ONLINE" if is_mqtt_connected else "DISCONNECTED", "#16a34a" if is_mqtt_connected else "#dc2626"),
        ("MQTT Client ID:", DEVICE_NAME, "ACTIVE", "#1565c0"),
        ("Bluetooth Serial SPP:", f"Inhydro_{DEVICE_NAME} (Ch 1)", "LISTENING", "#16a34a"),
        ("System Local IP:", get_system_ip_summary().split()[0] if get_system_ip_summary() else "N/A", "ACTIVE", "#0284c7"),
        ("Telemetry Upload Topic:", CURRENT_SETP_TOPIC, "READY", "#1565c0"),
        ("Pump Arbitration Mode:", system_config.get("pump_arbitration_mode", "sequential").upper(), "ACTIVE", "#ea580c"),
        ("Alarm Log File:", os.path.basename(ALARM_LOG_FILE), f"{os.path.getsize(ALARM_LOG_FILE) if os.path.exists(ALARM_LOG_FILE) else 0} bytes", "#475569"),
        ("Offline Buffer File:", os.path.basename(ACTIVE_LOG_FILE), f"{os.path.getsize(ACTIVE_LOG_FILE) if os.path.exists(ACTIVE_LOG_FILE) else 0} bytes", "#475569")
    ]
    for lbl_n, val_n, st_n, col_n in net_items:
        rf = tk.Frame(right_card, bg="white"); rf.pack(fill="x", pady=4)
        tk.Label(rf, text=lbl_n, font=("Helvetica", 10, "bold"), width=22, anchor="w", bg="white", fg="#1e293b").pack(side="left")
        tk.Label(rf, text=val_n, font=("Helvetica", 9), anchor="w", bg="white", fg="#475569").pack(side="left", padx=4)
        tk.Label(rf, text=st_n, font=("Helvetica", 9, "bold"), fg=col_n, bg="white").pack(side="right")

    tk.Button(m_main, text="CLOSE", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=modal.destroy).pack(pady=10)

# -----------------------------------------------------------------------------
# SCREEN 14: HISTORICAL TRENDS & SENSOR ANALYTICS MODAL
# -----------------------------------------------------------------------------
trends_modal = None

def open_trends_modal(default_skey="PH-01"):
    global trends_modal
    if trends_modal and trends_modal.winfo_exists():
        try: trends_modal.destroy()
        except Exception: pass

    trends_modal = tk.Toplevel(root)
    make_modal_fullscreen(trends_modal)
    add_logo(trends_modal)
    add_top_left_exit(trends_modal)
    add_bottom_right_clock(trends_modal)

    current_ph = default_skey if default_skey in ALL_POLYHOUSES else "PH-01"
    current_metric = "temp"

    m_main = tk.Frame(trends_modal, bg="white")
    m_main.pack(fill="both", expand=True, pady=(45, 12), padx=20)

    lbl_head = tk.Label(m_main, text="SCREEN 14 : HISTORICAL PARAMETER TRENDS & SENSOR ANALYTICS", font=big, fg="#7c3aed", bg="white")
    lbl_head.pack(pady=(0, 4))

    # Control Bar: Polyhouse Selector & Metric Selector
    ctrl_bar = tk.Frame(m_main, bg="white")
    ctrl_bar.pack(fill="x", pady=2)

    ph_bar = tk.Frame(ctrl_bar, bg="white")
    ph_bar.pack(side="left", padx=5)
    tk.Label(ph_bar, text="POLYHOUSE:", font=("Helvetica", 10, "bold"), bg="white", fg="#475569").pack(side="left", padx=4)

    ph_btn_map = {}
    for p in ALL_POLYHOUSES:
        b = tk.Button(ph_bar, text=p, font=("Helvetica", 9, "bold"), width=7, relief="flat", bd=0, bg="#e2e8f0", fg="#1e293b", cursor="hand2")
        b.config(command=lambda ph_target=p: select_ph(ph_target))
        b.pack(side="left", padx=2)
        ph_btn_map[p] = b

    metric_bar = tk.Frame(ctrl_bar, bg="white")
    metric_bar.pack(side="right", padx=5)
    tk.Label(metric_bar, text="METRIC:", font=("Helvetica", 10, "bold"), bg="white", fg="#475569").pack(side="left", padx=4)

    metrics_def = [
        ("temp", "TEMPERATURE (°C)", "#fb923c"),
        ("humi", "HUMIDITY (%)", "#38bdf8"),
        ("co2",  "CO₂ (ppm)", "#c084fc"),
        ("par",  "PAR (µmol)", "#facc15"),
        ("dli",  "DLI (mol)", "#34d399")
    ]
    metric_btn_map = {}
    for m_key, m_lbl, m_col in metrics_def:
        b = tk.Button(metric_bar, text=m_lbl, font=("Helvetica", 9, "bold"), width=15, relief="flat", bd=0, bg="#e2e8f0", fg="#1e293b", cursor="hand2")
        b.config(command=lambda mk=m_key: select_metric(mk))
        b.pack(side="left", padx=2)
        metric_btn_map[m_key] = b

    # Stats Ribbon
    stats_ribbon = tk.Frame(m_main, bg="#f8fafc", bd=1, relief="solid", highlightbackground="#e2e8f0", padx=10, pady=4)
    stats_ribbon.pack(fill="x", pady=4)

    lbl_chart_title = tk.Label(stats_ribbon, text="", font=("Helvetica", 11, "bold"), fg="#1e293b", bg="#f8fafc")
    lbl_chart_title.pack(side="left", padx=6)

    lbl_stat_latest = tk.Label(stats_ribbon, text="LATEST: --", font=("Helvetica", 10, "bold"), fg="#1565c0", bg="#f8fafc")
    lbl_stat_latest.pack(side="left", padx=10)

    lbl_stat_min = tk.Label(stats_ribbon, text="MIN: --", font=("Helvetica", 10, "bold"), fg="#059669", bg="#f8fafc")
    lbl_stat_min.pack(side="left", padx=10)

    lbl_stat_max = tk.Label(stats_ribbon, text="MAX: --", font=("Helvetica", 10, "bold"), fg="#dc2626", bg="#f8fafc")
    lbl_stat_max.pack(side="left", padx=10)

    lbl_stat_avg = tk.Label(stats_ribbon, text="AVG: --", font=("Helvetica", 10, "bold"), fg="#475569", bg="#f8fafc")
    lbl_stat_avg.pack(side="left", padx=10)

    lbl_samples_cnt = tk.Label(stats_ribbon, text="SAMPLES: 0", font=("Helvetica", 9), fg="#64748b", bg="#f8fafc")
    lbl_samples_cnt.pack(side="right", padx=6)

    # Graph Canvas (Dark Industrial Theme)
    chart_canvas = tk.Canvas(m_main, bg="#0f172a", highlightthickness=1, highlightbackground="#334155", height=320)
    chart_canvas.pack(fill="both", expand=True, pady=4)

    def select_ph(p):
        nonlocal current_ph
        current_ph = p
        for pk, b in ph_btn_map.items():
            if pk == current_ph: b.config(bg="#7c3aed", fg="white")
            else: b.config(bg="#e2e8f0", fg="#1e293b")
        redraw_chart()

    def select_metric(mk):
        nonlocal current_metric
        current_metric = mk
        for k, b in metric_btn_map.items():
            if k == current_metric: b.config(bg="#7c3aed", fg="white")
            else: b.config(bg="#e2e8f0", fg="#1e293b")
        redraw_chart()

    def redraw_chart():
        if not trends_modal or not trends_modal.winfo_exists(): return
        chart_canvas.delete("all")

        cw = chart_canvas.winfo_width()
        ch = chart_canvas.winfo_height()
        if cw < 200 or ch < 100:
            cw, ch = 960, 320

        m_dict = dict(metrics_def)
        m_color = next((col for k, lbl, col in metrics_def if k == current_metric), "#38bdf8")
        unit_str = "°C" if current_metric == "temp" else ("%" if current_metric == "humi" else ("ppm" if current_metric == "co2" else ("µmol/m²/s" if current_metric == "par" else "mol/m²/d")))

        disp_ph = get_sensor_display_name(current_ph)
        lbl_chart_title.config(text=f"{disp_ph} — {m_dict.get(current_metric, '').upper()}")

        with trend_lock:
            raw_hist = list(trend_data_history.get(current_ph, []))

        valid_pts = []
        for item in raw_hist:
            v = item.get(current_metric)
            if v is not None:
                try: valid_pts.append((item.get("time", ""), float(v)))
                except Exception: pass

        if not valid_pts:
            chart_canvas.create_text(cw // 2, ch // 2, text=f"No trend telemetry points recorded yet for {disp_ph} ({m_dict.get(current_metric)})\nWaiting for periodic telemetry logging stream...", fill="#94a3b8", font=("Helvetica", 13, "bold"), justify="center")
            lbl_stat_latest.config(text="LATEST: --")
            lbl_stat_min.config(text="MIN: --")
            lbl_stat_max.config(text="MAX: --")
            lbl_stat_avg.config(text="AVG: --")
            lbl_samples_cnt.config(text="SAMPLES: 0")
            return

        vals = [v for _, v in valid_pts]
        latest_v = vals[-1]
        min_v = min(vals)
        max_v = max(vals)
        avg_v = sum(vals) / len(vals)

        lbl_stat_latest.config(text=f"LATEST: {latest_v:.1f} {unit_str}")
        lbl_stat_min.config(text=f"MIN: {min_v:.1f} {unit_str}")
        lbl_stat_max.config(text=f"MAX: {max_v:.1f} {unit_str}")
        lbl_stat_avg.config(text=f"AVG: {avg_v:.1f} {unit_str}")
        lbl_samples_cnt.config(text=f"SAMPLES: {len(vals)}")

        left_m = 70
        right_m = 30
        top_m = 30
        bot_m = 40
        pw = cw - left_m - right_m
        ph_h = ch - top_m - bot_m

        y_min = min_v
        y_max = max_v
        if y_max == y_min:
            y_min -= 1.0; y_max += 1.0
        y_padding = 0.12 * (y_max - y_min)
        plot_min = y_min - y_padding
        plot_max = y_max + y_padding

        steps = 4
        for i in range(steps + 1):
            frac = i / float(steps)
            gy = top_m + ph_h - (frac * ph_h)
            g_val = plot_min + frac * (plot_max - plot_min)
            chart_canvas.create_line(left_m, gy, left_m + pw, gy, fill="#1e293b", dash=(4, 4), width=1)
            chart_canvas.create_text(left_m - 8, gy, text=f"{g_val:.1f}", fill="#94a3b8", font=("Helvetica", 9), anchor="e")

        sp_eval = get_active_setpoints(current_ph)
        if current_metric == "temp":
            t_set = sp_eval.get("target_temp")
            if t_set and plot_min <= t_set <= plot_max:
                sy = top_m + ph_h - ((t_set - plot_min) / (plot_max - plot_min)) * ph_h
                chart_canvas.create_line(left_m, sy, left_m + pw, sy, fill="#22c55e", dash=(6, 4), width=1)
                chart_canvas.create_text(left_m + pw - 5, sy - 8, text=f"TARGET: {t_set:.1f}°C", fill="#22c55e", font=("Helvetica", 9, "bold"), anchor="e")
        elif current_metric == "humi":
            h_set = sp_eval.get("target_humi")
            if h_set and plot_min <= h_set <= plot_max:
                sy = top_m + ph_h - ((h_set - plot_min) / (plot_max - plot_min)) * ph_h
                chart_canvas.create_line(left_m, sy, left_m + pw, sy, fill="#22c55e", dash=(6, 4), width=1)
                chart_canvas.create_text(left_m + pw - 5, sy - 8, text=f"TARGET: {h_set:.1f}%", fill="#22c55e", font=("Helvetica", 9, "bold"), anchor="e")

        coords = []
        n = len(valid_pts)
        time_step = max(1, n // 6)

        for i, (t_stamp, v) in enumerate(valid_pts):
            x = left_m + (i / float(n - 1)) * pw if n > 1 else left_m + pw / 2
            y = top_m + ph_h - ((v - plot_min) / (plot_max - plot_min)) * ph_h
            coords.extend([x, y])

            if i % time_step == 0 or i == n - 1:
                chart_canvas.create_line(x, top_m + ph_h, x, top_m + ph_h + 5, fill="#64748b", width=1)
                chart_canvas.create_text(x, top_m + ph_h + 14, text=t_stamp, fill="#94a3b8", font=("Helvetica", 8), anchor="center")

        if len(coords) >= 4:
            chart_canvas.create_line(coords, fill=m_color, width=3, smooth=True)

        for i in range(0, len(coords), 2):
            cx, cy = coords[i], coords[i + 1]
            if i == len(coords) - 2:
                chart_canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill="#ffffff", outline=m_color, width=2)
                chart_canvas.create_text(cx, cy - 14, text=f"{valid_pts[-1][1]:.1f} {unit_str}", fill="#ffffff", font=("Helvetica", 10, "bold"), anchor="s")
            elif n <= 30:
                chart_canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=m_color, outline="")

    select_ph(current_ph)
    select_metric(current_metric)

    def auto_refresh_trends():
        if trends_modal and trends_modal.winfo_exists():
            redraw_chart()
            trends_modal.after(4000, auto_refresh_trends)

    trends_modal.after(4000, auto_refresh_trends)

    btn_bar = tk.Frame(m_main, bg="white")
    btn_bar.pack(side="bottom", pady=4)
    tk.Button(btn_bar, text="REFRESH GRAPH", font=BTN_FONT_MAIN, bg="#7c3aed", fg="white", width=16, height=1, cursor="hand2", command=redraw_chart).pack(side="left", padx=8)
    tk.Button(btn_bar, text="CLOSE", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=16, height=1, cursor="hand2", command=trends_modal.destroy).pack(side="left", padx=8)

# -----------------------------------------------------------------------------
# SCREEN 12: IRRIGATION & FOGGING AUTOMATION SCHEDULE MODAL
# -----------------------------------------------------------------------------
irrig_sched_modal = None

def open_irrigation_schedule_modal(default_skey="PH-01"):
    global irrig_sched_modal
    if irrig_sched_modal and irrig_sched_modal.winfo_exists():
        try: irrig_sched_modal.destroy()
        except Exception: pass

    current_ph = default_skey if default_skey in ACTIVE_POLYHOUSES else "PH-01"

    irrig_sched_modal = tk.Toplevel(root)
    make_modal_fullscreen(irrig_sched_modal)
    add_logo(irrig_sched_modal)
    add_top_left_exit(irrig_sched_modal)
    add_bottom_right_clock(irrig_sched_modal)

    m_main = tk.Frame(irrig_sched_modal, bg="white")
    m_main.pack(fill="both", expand=True, pady=(45, 15), padx=25)

    tk.Label(m_main, text="SCREEN 12 : IRRIGATION & FOGGING AUTOMATION SCHEDULE", font=big, fg="#059669", bg="white").pack(pady=(0, 6))

    ph_bar = tk.Frame(m_main, bg="white")
    ph_bar.pack(pady=4)

    tk.Label(ph_bar, text="SELECT POLYHOUSE:", font=("Helvetica", 11, "bold"), bg="white", fg="#475569").pack(side="left", padx=6)

    ph_buttons = {}
    for p in ACTIVE_POLYHOUSES:
        b = tk.Button(ph_bar, text=p, font=("Helvetica", 10, "bold"), width=9, relief="flat", bd=0, bg="#e2e8f0", fg="#1e293b", cursor="hand2")
        b.config(command=lambda ph_target=p: select_house(ph_target))
        b.pack(side="left", padx=4)
        ph_buttons[p] = b

    slots_container = tk.Frame(m_main, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=10, pady=10)
    slots_container.pack(fill="both", expand=True, pady=8)

    lbl_house_title = tk.Label(slots_container, text="", font=("Helvetica", 12, "bold"), fg="#1565c0", bg="white")
    lbl_house_title.pack(anchor="w", pady=(0, 6))

    slots_frame = tk.Frame(slots_container, bg="white")
    slots_frame.pack(fill="both", expand=True)

    def select_house(p):
        nonlocal current_ph
        current_ph = p
        for pk, b in ph_buttons.items():
            if pk == current_ph: b.config(bg="#059669", fg="white")
            else: b.config(bg="#e2e8f0", fg="#1e293b")
        render_slots_table()

    def render_slots_table():
        for w in slots_frame.winfo_children(): w.destroy()

        disp_name = get_sensor_display_name(current_ph)
        lbl_house_title.config(text=f"{disp_name} — SCHEDULED IRRIGATION & FOGGING CYCLES")

        sp = get_setpoints(current_ph)
        slots = sp.setdefault("irrigation_slots", [])

        hdr = tk.Frame(slots_frame, bg="#f1f5f9", bd=1, relief="solid", highlightbackground="#e2e8f0")
        hdr.pack(fill="x", pady=(0, 4))
        tk.Label(hdr, text="SLOT #", font=("Helvetica", 10, "bold"), fg="#1e293b", bg="#f1f5f9", width=8, anchor="center").pack(side="left", padx=4, pady=6)
        tk.Label(hdr, text="START TIME", font=("Helvetica", 10, "bold"), fg="#1e293b", bg="#f1f5f9", width=16, anchor="center").pack(side="left", padx=4)
        tk.Label(hdr, text="EQUIPMENT TYPE", font=("Helvetica", 10, "bold"), fg="#1e293b", bg="#f1f5f9", width=18, anchor="center").pack(side="left", padx=4)
        tk.Label(hdr, text="RUN DURATION", font=("Helvetica", 10, "bold"), fg="#1e293b", bg="#f1f5f9", width=16, anchor="center").pack(side="left", padx=4)
        tk.Label(hdr, text="STATUS", font=("Helvetica", 10, "bold"), fg="#1e293b", bg="#f1f5f9", width=14, anchor="center").pack(side="left", padx=4)
        tk.Label(hdr, text="ACTIONS", font=("Helvetica", 10, "bold"), fg="#1e293b", bg="#f1f5f9", width=12, anchor="center").pack(side="left", padx=4)

        if not slots:
            tk.Label(slots_frame, text="No scheduled irrigation/fogging slots configured. Click '+ ADD NEW SLOT' below.", font=("Helvetica", 11), fg="#64748b", bg="white", pady=20).pack()
            return

        for idx, slot in enumerate(slots):
            row = tk.Frame(slots_frame, bg="white", bd=1, relief="solid", highlightbackground="#f1f5f9")
            row.pack(fill="x", pady=2)

            s_id = slot.get("id", idx + 1)
            tk.Label(row, text=f"Slot {s_id}", font=("Helvetica", 10, "bold"), fg="#1565c0", bg="white", width=8, anchor="center").pack(side="left", padx=4, pady=4)

            st_val = format_time_12h(slot.get("start", "07:00 AM"))
            btn_t = tk.Button(row, text=st_val, font=("Helvetica", 10, "bold"), bg="#f8fafc", fg="#0f172a", width=14, relief="sunken", bd=1, cursor="hand2")
            def _edit_t(s=slot, b=btn_t):
                def _confirm_t(new_t):
                    s["start"] = format_time_12h(new_t)
                    b.config(text=s["start"])
                    save_setpoints("SCHEDULE_TIME")
                open_almora_keypad("Set Irrigation Start Time", s.get("start", "07:00 AM"), _confirm_t, mode="time")
            btn_t.config(command=_edit_t)
            btn_t.pack(side="left", padx=10)

            t_val = str(slot.get("type", "sprinkler")).upper()
            btn_type = tk.Button(row, text=f"✔ {t_val}", font=("Helvetica", 9, "bold"),
                                 bg="#e0f2fe" if t_val == "SPRINKLER" else "#fef3c7",
                                 fg="#0369a1" if t_val == "SPRINKLER" else "#b45309",
                                 width=16, relief="flat", cursor="hand2")
            def _toggle_type(s=slot, b=btn_type):
                new_t = "fogger" if s.get("type", "sprinkler").lower() == "sprinkler" else "sprinkler"
                s["type"] = new_t
                up_t = new_t.upper()
                b.config(text=f"✔ {up_t}", bg="#e0f2fe" if up_t == "SPRINKLER" else "#fef3c7", fg="#0369a1" if up_t == "SPRINKLER" else "#b45309")
                save_setpoints("SCHEDULE_TYPE")
            btn_type.config(command=_toggle_type)
            btn_type.pack(side="left", padx=10)

            dur_val = int(slot.get("duration_sec", 120))
            btn_dur = tk.Button(row, text=f"{dur_val} sec", font=("Helvetica", 10, "bold"), bg="#f8fafc", fg="#e65100", width=14, relief="sunken", bd=1, cursor="hand2")
            def _edit_dur(s=slot, b=btn_dur):
                def _confirm_d(new_d):
                    try:
                        iv = int(float(new_d))
                        if iv > 0:
                            s["duration_sec"] = iv
                            b.config(text=f"{iv} sec")
                            save_setpoints("SCHEDULE_DURATION")
                    except Exception: pass
                open_almora_keypad("Set Run Duration (Sec)", str(s.get("duration_sec", 120)), _confirm_d, mode="numeric")
            btn_dur.config(command=_edit_dur)
            btn_dur.pack(side="left", padx=10)

            en_val = bool(slot.get("enabled", True))
            btn_en = tk.Button(row, text="ENABLED" if en_val else "DISABLED", font=("Helvetica", 9, "bold"),
                               bg="#dcfce7" if en_val else "#f1f5f9", fg="#15803d" if en_val else "#64748b",
                               width=12, relief="flat", cursor="hand2")
            def _toggle_en(s=slot, b=btn_en):
                s["enabled"] = not s.get("enabled", True)
                cur_en = s["enabled"]
                b.config(text="ENABLED" if cur_en else "DISABLED", bg="#dcfce7" if cur_en else "#f1f5f9", fg="#15803d" if cur_en else "#64748b")
                save_setpoints("SCHEDULE_STATUS")
            btn_en.config(command=_toggle_en)
            btn_en.pack(side="left", padx=8)

            btn_del = tk.Button(row, text="🗑 DELETE", font=("Helvetica", 9, "bold"), bg="#fee2e2", fg="#b91c1c", width=10, relief="flat", cursor="hand2")
            def _del_slot(i_del=idx):
                del slots[i_del]
                for r_i, s_item in enumerate(slots):
                    s_item["id"] = r_i + 1
                save_setpoints("DELETE_SLOT")
                render_slots_table()
            btn_del.config(command=_del_slot)
            btn_del.pack(side="left", padx=6)

    def add_new_slot():
        sp = get_setpoints(current_ph)
        slots = sp.setdefault("irrigation_slots", [])
        new_id = len(slots) + 1
        slots.append({
            "id": new_id,
            "start": "08:00 AM",
            "duration_sec": 120,
            "type": "sprinkler",
            "enabled": True
        })
        save_setpoints("ADD_SLOT")
        render_slots_table()

    actions_bar = tk.Frame(m_main, bg="white")
    actions_bar.pack(side="bottom", pady=8)

    tk.Button(actions_bar, text="+ ADD NEW SLOT", font=BTN_FONT_MAIN, bg="#0284c7", fg="white", width=18, height=FRAME_BTN_HEIGHT, cursor="hand2", command=add_new_slot).pack(side="left", padx=8)
    tk.Button(actions_bar, text="✔ SAVE & APPLY", font=BTN_FONT_MAIN, bg="#059669", fg="white", width=18, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: (save_setpoints("IRRIGATION_SCHEDULE"), irrig_sched_modal.destroy())).pack(side="left", padx=8)
    tk.Button(actions_bar, text="CLOSE", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=14, height=FRAME_BTN_HEIGHT, cursor="hand2", command=irrig_sched_modal.destroy).pack(side="left", padx=8)

    select_house(current_ph)

# -----------------------------------------------------------------------------
# FULLSCREEN TOUCH KEYPAD & PIN MODAL (NUMERIC, TIME, CALENDAR, ALPHANUMERIC)
# -----------------------------------------------------------------------------
keypad_modal = None
pin_modal = None

def make_modal_fullscreen(win):
    win.configure(bg="white")
    win.transient(root)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    win.geometry(f"{sw}x{sh}+0+0")
    try: win.overrideredirect(True)
    except Exception: pass
    try: win.attributes("-fullscreen", True)
    except Exception: pass
    win.update_idletasks()
    win.grab_set()
    win.focus_force()

def log_auth_event(user_idx, user_name, status):
    try:
        log_dir = os.path.join(BASE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        event = {
            "timestamp": datetime.datetime.now().isoformat(),
            "user_index": user_idx,
            "user_name": user_name,
            "status": status
        }
        with open(os.path.join(log_dir, "auth_events.jsonl"), "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        print(f"Error logging auth event: {e}")

def check_pin_and_proceed(action_title, on_success):
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    win = tk.Toplevel(root)
    win.title("Security Authentication")
    win.configure(bg="#ffffff")
    win.geometry(f"{sw}x{sh}+0+0")
    win.focus_force()
    win.update()
    win.attributes("-fullscreen", True)
    win.grab_set()

    lbl_auth_clock = tk.Label(win, text="", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff", justify="left")
    lbl_auth_clock.place(x=15, y=10, anchor="nw")
    def update_auth_clock():
        if win.winfo_exists():
            lbl_auth_clock.config(text=datetime.datetime.now().strftime("%A, %d %b %Y\n%I:%M:%S %p"))
            win.after(1000, update_auth_clock)
    update_auth_clock()

    def close_win():
        win.destroy()
        try:
            root.geometry(f"{sw}x{sh}+0+0")
            root.attributes("-fullscreen", True)
            root.focus_force()
        except Exception:
            pass

    password_entered = ""
    selected_user = 1
    error_active = False
    show_password = False

    main_container = tk.Frame(win, bg="#ffffff")
    main_container.place(relx=0.5, rely=0.5, anchor="center")

    header_frame = tk.Frame(main_container, bg="#ffffff")
    header_frame.pack(fill="x", padx=20, pady=(15, 5))

    title_sub_frame = tk.Frame(header_frame, bg="#ffffff")
    title_sub_frame.pack(side="left")

    tk.Label(title_sub_frame, text="SECURITY LOCK", font=("Arial", 16, "bold"), fg="#1565c0", bg="#ffffff").pack(anchor="w")
    desc_txt = f"Select user and enter authorization PIN to unlock {action_title}:" if action_title else "Select user and enter authorization PIN to unlock setpoints:"
    tk.Label(title_sub_frame, text=desc_txt, font=("Arial", 10), fg="#64748b", bg="#ffffff").pack(anchor="w", pady=2)

    try:
        if os.path.exists(LOGO_PATH):
            logo_img_modal = ImageTk.PhotoImage(Image.open(LOGO_PATH).resize((120, 75), Image.LANCZOS))
            win.logo_img_modal = logo_img_modal
            tk.Label(header_frame, image=logo_img_modal, bg="#ffffff").pack(side="right", padx=10)
    except Exception: pass

    # TWO USER SELECTION BUTTONS ONLY (Exact monit.py design)
    user_frame = tk.Frame(main_container, bg="#ffffff")
    user_frame.pack(pady=10)

    user_btns = []

    def show_error_in_display(msg):
        nonlocal error_active, password_entered
        password_entered = ""
        color = "#000000" if "4-8" in msg else "#dc2626"
        display_lbl.config(text=msg, fg=color, font=("serif", 13, "bold"))
        error_active = True

    def rename_user_popup():
        nonlocal selected_user
        pop = tk.Toplevel(win)
        pop.title("Rename Operator")
        pop.configure(bg="#ffffff")
        pop.geometry(f"{sw}x{sh}+0+0")
        pop.focus_force()
        pop.update()
        pop.attributes("-fullscreen", True)
        pop.grab_set()

        lbl_pop_clock = tk.Label(pop, text="", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff", justify="left")
        lbl_pop_clock.place(x=15, y=10, anchor="nw")
        def update_pop_clock():
            if pop.winfo_exists():
                lbl_pop_clock.config(text=datetime.datetime.now().strftime("%A, %d %b %Y\n%I:%M:%S %p"))
                pop.after(1000, update_pop_clock)
        update_pop_clock()

        def close_pop():
            pop.destroy()
            try:
                win.geometry(f"{sw}x{sh}+0+0")
                win.attributes("-fullscreen", True)
                win.focus_force()
                win.grab_set()
            except Exception:
                pass

        name_entered = system_config.get(f"USER {selected_user} Name", f"Operator {selected_user}")
        container = tk.Frame(pop, bg="#ffffff")
        container.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(container, text="RENAME OPERATOR", font=("Arial", 14, "bold"), fg="#1565c0", bg="#ffffff").pack(pady=10)
        tk.Label(container, text=f"Edit name for User {selected_user}:", font=("Arial", 10), fg="#64748b", bg="#ffffff").pack(pady=2)

        display_lbl_rename = tk.Label(container, text=name_entered, font=("Arial", 16, "bold"), fg="#e65100", bg="#f1f5f9", width=22, relief="sunken", bd=2)
        display_lbl_rename.pack(pady=10)

        def char_press(c):
            nonlocal name_entered
            if len(name_entered) < 20:
                name_entered += c
                display_lbl_rename.config(text=name_entered)
        def char_back():
            nonlocal name_entered
            name_entered = name_entered[:-1]
            display_lbl_rename.config(text=name_entered)
        def char_clear():
            nonlocal name_entered
            name_entered = ""
            display_lbl_rename.config(text="")
        def char_save():
            if not name_entered.strip(): return
            system_config[f"USER {selected_user} Name"] = name_entered.strip()
            save_config()
            user_btns[selected_user - 1].config(text=name_entered.strip())
            close_pop()

        kb_frame = tk.Frame(container, bg="#ffffff")
        kb_frame.pack(pady=10)
        for ri, row_k in enumerate([list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL:"), list("ZXCVBNM._ ")]):
            for ci, ch in enumerate(row_k):
                lbl = ch if ch != ' ' else 'SPC'
                tk.Button(kb_frame, text=lbl, font=("Arial", 11, "bold"), width=4, height=1, bg="#f1f5f9", fg="#0f172a", activebackground="#0284c7", activeforeground="white",
                          command=lambda x=ch: char_press(x)).grid(row=ri, column=ci, padx=2, pady=2)

        action_frame = tk.Frame(container, bg="#ffffff")
        action_frame.pack(fill="x", pady=15)
        tk.Button(action_frame, text="CANCEL", font=("Arial", 10, "bold"), bg="#64748b", fg="white", width=8, height=2, command=close_pop).pack(side="left", padx=10)
        tk.Button(action_frame, text="CLEAR", font=("Arial", 10, "bold"), bg="#dc2626", fg="white", width=8, height=2, command=char_clear).pack(side="left", padx=10)
        tk.Button(action_frame, text="BACK", font=("Arial", 10, "bold"), bg="#f97316", fg="white", width=10, height=2, command=char_back).pack(side="left", padx=10)
        tk.Button(action_frame, text="SAVE", font=("Arial", 10, "bold"), bg="#0284c7", fg="white", width=10, height=2, command=char_save).pack(side="right", padx=10)

    def change_pin_popup():
        nonlocal selected_user
        pop = tk.Toplevel(win)
        pop.title("Change Operator PIN")
        pop.configure(bg="#ffffff")
        pop.geometry(f"{sw}x{sh}+0+0")
        pop.focus_force()
        pop.update()
        pop.attributes("-fullscreen", True)
        pop.grab_set()

        lbl_pop_clock = tk.Label(pop, text="", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff", justify="left")
        lbl_pop_clock.place(x=15, y=10, anchor="nw")
        def update_pop_clock():
            if pop.winfo_exists():
                lbl_pop_clock.config(text=datetime.datetime.now().strftime("%A, %d %b %Y\n%I:%M:%S %p"))
                pop.after(1000, update_pop_clock)
        update_pop_clock()

        def close_pop():
            pop.destroy()
            try:
                win.geometry(f"{sw}x{sh}+0+0")
                win.attributes("-fullscreen", True)
                win.focus_force()
                win.grab_set()
            except Exception:
                pass

        step = 1
        old_pin = ""; new_pin = ""; input_value = ""
        show_pin = False; pop_error_active = False

        container = tk.Frame(pop, bg="#ffffff")
        container.place(relx=0.5, rely=0.5, anchor="center")

        step_lbl = tk.Label(container, text="STEP 1: ENTER OLD PIN", font=("Arial", 12, "bold"), fg="#1565c0", bg="#ffffff")
        step_lbl.pack(pady=10)

        display_frame = tk.Frame(container, bg="#ffffff")
        display_frame.pack(pady=10)

        display_lbl_pin = tk.Label(display_frame, text="", font=("Arial", 20, "bold"), fg="#2e7d32", bg="#f1f5f9", width=12, relief="sunken", bd=2, anchor="center")
        display_lbl_pin.pack(side="left", padx=5)

        def show_pop_err(msg):
            nonlocal pop_error_active, input_value
            input_value = ""
            color = "#000000" if "4-8" in msg else "#dc2626"
            display_lbl_pin.config(text=msg, fg=color, font=("serif", 13, "bold"))
            pop_error_active = True

        def update_pin_display():
            if pop_error_active: return
            display_lbl_pin.config(fg="#2e7d32", font=("Arial", 20, "bold"))
            display_lbl_pin.config(text=input_value if show_pin else "●" * len(input_value))

        def toggle_pin_show():
            nonlocal show_pin
            show_pin = not show_pin
            eye_btn.config(text="HIDE" if show_pin else "SHOW", bg="#0284c7" if show_pin else "#64748b", fg="white")
            update_pin_display()

        eye_btn = tk.Button(display_frame, text="SHOW", font=("Arial", 10, "bold"), width=6, bg="#64748b", fg="white", bd=1, relief="raised", command=toggle_pin_show)
        eye_btn.pack(side="left", padx=5)

        def num_press(num):
            nonlocal input_value, pop_error_active
            if pop_error_active: pop_error_active = False; input_value = ""
            if len(input_value) < 8:
                input_value += str(num)
                update_pin_display()

        def num_back():
            nonlocal input_value, pop_error_active
            if pop_error_active: pop_error_active = False; input_value = ""
            input_value = input_value[:-1]
            update_pin_display()

        def num_clear():
            nonlocal input_value, pop_error_active
            pop_error_active = False; input_value = ""
            update_pin_display()

        def num_confirm():
            nonlocal step, old_pin, new_pin, input_value
            if pop_error_active: return
            correct_old = str(system_config.get(f"USER {selected_user} PASSWORD", f"{selected_user}{selected_user}{selected_user}{selected_user}"))
            if step == 1:
                if input_value != correct_old and input_value != str(system_config.get("system_password", "1234")).strip():
                    show_pop_err("WRONG PIN")
                    return
                old_pin = input_value; input_value = ""; step = 2
                step_lbl.config(text="STEP 2: ENTER NEW PIN (4-8 DIGITS)")
                update_pin_display()
            elif step == 2:
                if not input_value.isdigit() or len(input_value) < 4 or len(input_value) > 8:
                    show_pop_err("4-8 DIGITS")
                    return
                new_pin = input_value; input_value = ""; step = 3
                step_lbl.config(text="STEP 3: CONFIRM NEW PIN")
                update_pin_display()
            elif step == 3:
                if input_value != new_pin:
                    show_pop_err("MISMATCH")
                    input_value = ""; step = 2
                    step_lbl.config(text="STEP 2: ENTER NEW PIN (4-8 DIGITS)")
                    return
                system_config[f"USER {selected_user} PASSWORD"] = new_pin
                save_config()
                close_pop()

        kp_frame = tk.Frame(container, bg="#ffffff")
        kp_frame.pack(pady=10)
        buttons = [
            ('1', 0, 0), ('2', 0, 1), ('3', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('7', 2, 0), ('8', 2, 1), ('9', 2, 2),
            ('CLR', 3, 0), ('0', 3, 1), ('DEL', 3, 2)
        ]
        for text, r, c in buttons:
            if text == 'DEL': cmd = num_back; bg, fg = "#f97316", "white"
            elif text == 'CLR': cmd = num_clear; bg, fg = "#dc2626", "white"
            else: cmd = lambda x=text: num_press(x); bg, fg = "#f1f5f9", "#0f172a"
            tk.Button(kp_frame, text=text, font=("Arial", 12, "bold"), width=6, height=2, bg=bg, fg=fg, bd=1, relief="raised", command=cmd).grid(row=r, column=c, padx=4, pady=4)

        action_frame = tk.Frame(container, bg="#ffffff")
        action_frame.pack(fill="x", pady=15)
        tk.Button(action_frame, text="CANCEL", font=("Arial", 10, "bold"), bg="#64748b", fg="white", width=12, height=2, command=close_pop).pack(side="left", padx=15)
        tk.Button(action_frame, text="CONFIRM / NEXT", font=("Arial", 10, "bold"), bg="#0284c7", fg="white", width=16, height=2, command=num_confirm).pack(side="right", padx=15)

    def select_user(idx):
        nonlocal selected_user
        selected_user = idx
        for i, btn in enumerate(user_btns, 1):
            if i == idx:
                btn.config(bg="#0284c7", fg="white", relief="sunken")
            else:
                btn.config(bg="#cbd5e1", fg="#0f172a", relief="raised")
        kp_clear()

    # User 1 Button
    u1_name = system_config.get("USER 1 Name", "Operator 1")
    btn_u1 = tk.Button(user_frame, text=u1_name, font=("Arial", 11, "bold"), width=16, height=1, bd=1)
    btn_u1.config(command=lambda: select_user(1))
    btn_u1.pack(side="left", padx=10)
    user_btns.append(btn_u1)

    # User 2 Button
    u2_name = system_config.get("USER 2 Name", "Operator 2")
    btn_u2 = tk.Button(user_frame, text=u2_name, font=("Arial", 11, "bold"), width=16, height=1, bd=1)
    btn_u2.config(command=lambda: select_user(2))
    btn_u2.pack(side="left", padx=10)
    user_btns.append(btn_u2)

    # Operator Sub-actions
    ops_frame = tk.Frame(main_container, bg="#ffffff")
    ops_frame.pack(pady=5)
    tk.Button(ops_frame, text=" RENAME USER", font=("Arial", 9, "bold"), bg="#64748b", fg="white", width=14, height=1, bd=1, relief="raised", command=rename_user_popup).pack(side="left", padx=5)
    tk.Button(ops_frame, text=" CHANGE PIN", font=("Arial", 9, "bold"), bg="#64748b", fg="white", width=14, height=1, bd=1, relief="raised", command=change_pin_popup).pack(side="left", padx=5)

    # Display entry for password
    display_container = tk.Frame(main_container, bg="#ffffff")
    display_container.pack(pady=10)

    display_lbl = tk.Label(display_container, text="", font=("Arial", 20, "bold"), fg="#2e7d32", bg="#f1f5f9", width=12, relief="sunken", bd=2, anchor="center")
    display_lbl.pack(side="left", padx=5)

    def update_display():
        if error_active: return
        display_lbl.config(fg="#2e7d32", font=("Arial", 20, "bold"))
        display_lbl.config(text=password_entered if show_password else "●" * len(password_entered))

    def toggle_show_password():
        nonlocal show_password
        show_password = not show_password
        eye_btn.config(text="HIDE" if show_password else "SHOW", bg="#0284c7" if show_password else "#64748b", fg="white")
        update_display()

    eye_btn = tk.Button(display_container, text="SHOW", font=("Arial", 10, "bold"), width=6, bg="#64748b", fg="white", bd=1, relief="raised", command=toggle_show_password)
    eye_btn.pack(side="left", padx=5)

    def kp_press(char):
        nonlocal password_entered, error_active
        if error_active: error_active = False; password_entered = ""
        if len(password_entered) < 12:
            password_entered += str(char)
            update_display()

    def kp_back():
        nonlocal password_entered, error_active
        if error_active: error_active = False; password_entered = ""
        password_entered = password_entered[:-1]
        update_display()

    def kp_clear():
        nonlocal password_entered, error_active
        error_active = False; password_entered = ""
        update_display()

    def kp_confirm():
        nonlocal password_entered, selected_user
        if error_active: return
        user_name = system_config.get(f"USER {selected_user} Name", f"Operator {selected_user}")
        correct_password = str(system_config.get(f"USER {selected_user} PASSWORD", f"{selected_user}{selected_user}{selected_user}{selected_user}"))
        master_pin = str(system_config.get("system_password", "1234")).strip()
        if password_entered == correct_password or (master_pin and password_entered == master_pin):
            log_auth_event(selected_user, user_name, "SUCCESS")
            close_win()
            on_success()
        else:
            log_auth_event(selected_user, user_name, "FAILED")
            show_error_in_display("WRONG PIN")

    kp_frame = tk.Frame(main_container, bg="#ffffff")
    kp_frame.pack(pady=10)
    buttons = [
        ('1', 0, 0), ('2', 0, 1), ('3', 0, 2),
        ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
        ('7', 2, 0), ('8', 2, 1), ('9', 2, 2),
        ('CLR', 3, 0), ('0', 3, 1), ('DEL', 3, 2)
    ]
    for text, r, c in buttons:
        if text == 'DEL': cmd = kp_back; bg, fg = "#f97316", "white"
        elif text == 'CLR': cmd = kp_clear; bg, fg = "#dc2626", "white"
        else: cmd = lambda x=text: kp_press(x); bg, fg = "#f1f5f9", "#0f172a"
        tk.Button(kp_frame, text=text, font=("Arial", 12, "bold"), width=6, height=2, bg=bg, fg=fg, bd=1, relief="raised", command=cmd).grid(row=r, column=c, padx=4, pady=4)

    action_frame = tk.Frame(main_container, bg="#ffffff")
    action_frame.pack(fill="x", side="bottom", pady=15, padx=20)
    tk.Button(action_frame, text="CANCEL", font=("Arial", 10, "bold"), bg="#64748b", fg="white", width=12, height=2, bd=1, relief="raised", command=close_win).pack(side="left", padx=15)
    tk.Button(action_frame, text="AUTHENTICATE", font=("Arial", 10, "bold"), bg="#0284c7", fg="white", width=14, height=2, bd=1, relief="raised", command=kp_confirm).pack(side="right", padx=15)

    select_user(1)

# -----------------------------------------------------------------------------
# ALMORA KEYPAD & KEYBOARD (EXACT SENSOR_MONITOR2_ALMORA.PY IMPLEMENTATION)
# -----------------------------------------------------------------------------
def open_almora_keypad(title_text, initial_value, callback_on_confirm, is_alphanumeric=False, mode=None):
    global keypad_modal
    if keypad_modal and keypad_modal.winfo_exists():
        keypad_modal.destroy()

    # Auto-detect keypad mode if not explicitly specified
    if mode is None:
        if is_alphanumeric:
            mode = "alphanumeric"
        elif "Time" in title_text or "time" in title_text:
            mode = "time"
        elif "Date" in title_text or "date" in title_text:
            mode = "calendar"
        else:
            mode = "numeric"

    keypad_modal = tk.Toplevel(root)
    make_modal_fullscreen(keypad_modal)

    kp_main = tk.Frame(keypad_modal, bg="white")
    kp_main.pack(fill="both", expand=True, pady=(50, 35))

    add_logo(keypad_modal)
    add_top_left_exit(keypad_modal)
    add_bottom_right_clock(keypad_modal)

    entered_val = str(initial_value)

    type_badge = {
        "numeric": "NUMERIC KEYPAD",
        "time": "TIME KEYPAD (12-HR AM/PM)",
        "calendar": "CALENDAR DATE KEYPAD (YYYY-MM-DD)",
        "alphanumeric": "ALPHANUMERIC KEYBOARD"
    }.get(mode, "NUMERIC KEYPAD")

    lbl_badge = tk.Label(kp_main, text=type_badge, font=("Helvetica", 10, "bold"), fg="#64748b", bg="#f8fafc", padx=12, pady=3, bd=1, relief="solid")
    lbl_badge.pack(pady=(4, 2))

    lbl_modal_title = tk.Label(kp_main, text=title_text, font=big, fg="#1565c0", bg="white")
    lbl_modal_title.pack(pady=(2, 4))

    lbl_modal_disp = tk.Label(kp_main, text=entered_val, font=("Arial", 22, "bold"), fg="#0f172a", bg="#f1f5f9", width=24, relief="sunken", bd=2)
    lbl_modal_disp.pack(pady=4)

    def kp_press(ch):
        nonlocal entered_val
        if len(entered_val) < 30:
            entered_val += str(ch)
            lbl_modal_disp.config(text=entered_val)

    def kp_set_val(new_val):
        nonlocal entered_val
        entered_val = str(new_val)
        lbl_modal_disp.config(text=entered_val)

    def kp_back():
        nonlocal entered_val
        entered_val = entered_val[:-1]
        lbl_modal_disp.config(text=entered_val)

    def kp_clear():
        nonlocal entered_val
        entered_val = ""
        lbl_modal_disp.config(text="")

    def kp_confirm():
        keypad_modal.destroy()
        callback_on_confirm(entered_val.strip())

    def kp_cancel():
        keypad_modal.destroy()

    kp_buttons_frame = tk.Frame(kp_main, bg="white")
    kp_buttons_frame.pack(pady=4)

    # --- 1. NUMERIC KEYPAD MODE ---
    if mode == "numeric":
        num_grid = [
            ('7', 0, 0), ('8', 0, 1), ('9', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('1', 2, 0), ('2', 2, 1), ('3', 2, 2),
            ('-', 3, 0), ('0', 3, 1), ('.', 3, 2)
        ]
        for t, r, c in num_grid:
            tk.Button(kp_buttons_frame, text=t, font=("Arial", 16, "bold"), width=7, height=1, bg="#f1f5f9", fg="#0f172a",
                      activebackground="#0284c7", activeforeground="white", relief="flat", bd=1, cursor="hand2",
                      command=lambda x=t: kp_press(x)).grid(row=r, column=c, padx=6, pady=4)

    # --- 2. TIME KEYPAD MODE (12-HR AM/PM) ---
    elif mode == "time":
        shortcut_f = tk.Frame(kp_buttons_frame, bg="white")
        shortcut_f.grid(row=0, column=0, columnspan=4, pady=(0, 4))

        time_shortcuts = ["06:00 AM", "08:00 AM", "12:00 PM", "05:00 PM", "08:00 PM", "12:00 AM"]
        for ts in time_shortcuts:
            tk.Button(shortcut_f, text=ts, font=("Helvetica", 9, "bold"), bg="#e0f2fe", fg="#0369a1", relief="flat", bd=0, padx=6, pady=4, cursor="hand2",
                      command=lambda x=ts: kp_set_val(x)).pack(side="left", padx=3)

        time_grid = [
            ('7', 1, 0), ('8', 1, 1), ('9', 1, 2), (':', 1, 3),
            ('4', 2, 0), ('5', 2, 1), ('6', 2, 2), ('AM', 2, 3),
            ('1', 3, 0), ('2', 3, 1), ('3', 3, 2), ('PM', 3, 3),
            ('0', 4, 0), ('00', 4, 1), (' ', 4, 2), ('CLR', 4, 3)
        ]
        for t, r, c in time_grid:
            if t == 'CLR':
                btn_b = tk.Button(kp_buttons_frame, text="CLR", font=("Arial", 12, "bold"), bg="#dc2626", fg="white", width=6, height=1, relief="flat", bd=0, cursor="hand2", command=kp_clear)
            elif t in ['AM', 'PM']:
                btn_b = tk.Button(kp_buttons_frame, text=t, font=("Arial", 13, "bold"), bg="#0284c7", fg="white", width=6, height=1, relief="flat", bd=0, cursor="hand2",
                                  command=lambda x=t: (kp_press(' ' + x) if 'AM' not in entered_val and 'PM' not in entered_val else None))
            elif t == ' ':
                btn_b = tk.Button(kp_buttons_frame, text="SPACE", font=("Arial", 10, "bold"), bg="#cbd5e1", fg="#1e293b", width=6, height=1, relief="flat", bd=0, cursor="hand2", command=lambda: kp_press(' '))
            else:
                btn_b = tk.Button(kp_buttons_frame, text=t, font=("Arial", 15, "bold"), bg="#f1f5f9", fg="#0f172a", width=6, height=1, relief="flat", bd=0, cursor="hand2", command=lambda x=t: kp_press(x))
            btn_b.grid(row=r, column=c, padx=4, pady=3)

    # --- 3. CALENDAR / DATE KEYPAD MODE (YYYY-MM-DD) ---
    elif mode == "calendar":
        shortcut_f = tk.Frame(kp_buttons_frame, bg="white")
        shortcut_f.grid(row=0, column=0, columnspan=3, pady=(0, 4))

        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        today_dt = datetime.datetime.now(ist_tz)

        d_today = today_dt.strftime("%Y-%m-%d")
        d_7 = (today_dt + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        d_14 = (today_dt + datetime.timedelta(days=14)).strftime("%Y-%m-%d")
        d_30 = (today_dt + datetime.timedelta(days=30)).strftime("%Y-%m-%d")

        date_shortcuts = [("TODAY", d_today), ("+7 DAYS", d_7), ("+14 DAYS", d_14), ("+30 DAYS", d_30)]
        for lbl, val in date_shortcuts:
            tk.Button(shortcut_f, text=f"{lbl}", font=("Helvetica", 9, "bold"), bg="#dcfce7", fg="#15803d", relief="flat", bd=0, padx=6, pady=4, cursor="hand2",
                      command=lambda x=val: kp_set_val(x)).pack(side="left", padx=3)

        date_grid = [
            ('7', 1, 0), ('8', 1, 1), ('9', 1, 2),
            ('4', 2, 0), ('5', 2, 1), ('6', 2, 2),
            ('1', 3, 0), ('2', 3, 1), ('3', 3, 2),
            ('-', 4, 0), ('0', 4, 1), (':', 4, 2)
        ]
        for t, r, c in date_grid:
            tk.Button(kp_buttons_frame, text=t, font=("Arial", 15, "bold"), width=7, height=1, bg="#f1f5f9", fg="#0f172a",
                      activebackground="#0284c7", activeforeground="white", relief="flat", bd=1, cursor="hand2",
                      command=lambda x=t: kp_press(x)).grid(row=r, column=c, padx=6, pady=4)

    # --- 4. ALPHANUMERIC KEYBOARD MODE ---
    else:
        rows = [list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL:"), list("ZXCVBNM._- ")]
        for ri, row_k in enumerate(rows):
            r_f = tk.Frame(kp_buttons_frame, bg="white")
            r_f.pack(pady=2)
            for ch in row_k:
                tk.Button(r_f, text=ch if ch != " " else "SPACE", font=("Arial", 12, "bold"), width=4 if ch != " " else 8, bg="#f1f5f9", fg="#0f172a",
                          command=lambda x=ch: kp_press(x)).pack(side="left", padx=2)

    kp_actions_frame = tk.Frame(kp_main, bg="white")
    kp_actions_frame.pack(pady=8)

    tk.Button(kp_actions_frame, text="DEL", font=BTN_FONT_MAIN, bg="#f97316", fg="white", width=10, height=2, cursor="hand2", command=kp_back).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CLEAR", font=BTN_FONT_MAIN, bg="#dc2626", fg="white", width=10, height=2, cursor="hand2", command=kp_clear).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CONFIRM", font=BTN_FONT_MAIN, bg="#0284c7", fg="white", width=12, height=2, cursor="hand2", command=kp_confirm).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CANCEL", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=10, height=2, cursor="hand2", command=kp_cancel).pack(side="left", padx=6)

# -----------------------------------------------------------------------------
# MAIN UI REFRESH LOOP
# -----------------------------------------------------------------------------
def update_ui():
    if not running: return
    try:
        grid_changed = False
        for skey in ALL_POLYHOUSES:
            if skey not in sensor_widgets:
                port = SENSOR_MAP[skey]
                disp_name = get_sensor_display_name(skey)
                b_room = tk.Button(sensors_grid, bg="#1565c0", bd=3, relief="raised",
                                   text=f"{disp_name}\n[INITIALIZING]", font=font.Font(size=10, weight="bold"),
                                   fg="white", width=25, height=9,
                                   command=lambda p=port: open_sensor_detail(p))
                sensor_widgets[skey] = b_room
                grid_changed = True

        if grid_changed: rebuild_grid()

        with sensor_data_lock: snap = dict(sensor_data)

        # 1. Update Polyhouse Tiles on Screen 02 Dashboard
        for skey, port in SENSOR_MAP.items():
            if skey in sensor_widgets:
                btn_room = sensor_widgets[skey]
                d = snap.get(port)
                disp_name = get_sensor_display_name(skey)
                sp_eval = get_active_setpoints(skey)
                mode_badge = sp_eval.get("mode", "AUTO").upper()

                if d and d.get('status') == 'OK':
                    t, h = d['temp'], d['humi']

                    if skey in ACTIVE_POLYHOUSES:
                        c_val = d.get('co2')
                        p_val = d.get('par')
                        d_val = d.get('dli')
                        co2_str = f"{c_val} ppm" if (c_val is not None) else "N/A"
                        dli_str = f"{d_val:.2f} mol" if (d_val is not None) else "0.00"

                        acf_st = "ON" if relay_states.get(RELAY_CH_ACF[skey]) else "OFF"
                        spr_st = "ON" if relay_states.get(RELAY_CH_SPRINKLER[skey]) else "OFF"
                        fog_st = "ON" if relay_states.get(RELAY_CH_FOGGER[skey]) else "OFF"

                        box_text = (
                            f"{disp_name}  [{mode_badge}]\n"
                            f"Temp: {t:.1f}°C (Set: {sp_eval['target_temp']:.1f}°C)\n"
                            f"Humi: {h:.1f}%  (Set: {sp_eval['target_humi']:.1f}%)\n"
                            f"CO2: {co2_str} | DLI: {dli_str}\n"
                            f"ACF: {acf_st} (24 Fans)\n"
                            f"Sprinkler: {spr_st} | Fogger: {fog_st}"
                        )
                        is_ok = (sp_eval['T MIN'] <= t <= sp_eval['T MAX']) and (sp_eval['H MIN'] <= h <= sp_eval['H MAX'])
                        btn_room.config(text=box_text, bg="#2e7d32" if is_ok else "#c62828")
                    else:
                        # PH-06 Monitoring Zone Tile
                        sp6 = get_setpoints("PH-06")
                        t_max_limit = float(sp6.get("temp_high_limit", 32.0))
                        h_max_limit = float(sp6.get("humi_high_limit", 85.0))
                        is_ok = (t <= t_max_limit and h <= h_max_limit)

                        box_text = (
                            f"{disp_name}\n"
                            f"[MONITORING ZONE ONLY]\n"
                            f"Temp: {t:.1f}°C (Max: {t_max_limit:.1f}°C)\n"
                            f"Humi: {h:.1f}%  (Max: {h_max_limit:.1f}%)\n"
                            f"Status: {'NORMAL' if is_ok else 'ALARM TRIGGERED'}"
                        )
                        btn_room.config(text=box_text, bg="#2e7d32" if is_ok else "#c62828")

                elif d and d.get('status') == 'ERROR':
                    btn_room.config(text=f"{disp_name}\n[SENSOR ERROR]", bg="#b71c1c")
                else:
                    btn_room.config(text=f"{disp_name}\n[OFFLINE]", bg="#424242")

        # 2. Update Main Dashboard Warning & Status Banner
        if active_warnings:
            lbl_warning_bar.config(
                text=" ⚠ ALARM: " + " | ".join(active_warnings[:2]),
                bg="#c62828", fg="white"
            )
        elif time.time() < setpoint_toast_expiry:
            lbl_warning_bar.config(
                text=f" {setpoint_toast_message} ",
                bg="#0284c7", fg="white"
            )
        else:
            pump_str = "RUNNING" if relay_states.get(RELAY_CH_COMMON_PUMP) else "IDLE"
            lbl_warning_bar.config(
                text=f" SYSTEM NORMAL — COMMON PUMP: {pump_str} | ACTIVE WATER DEMAND: {active_water_zone or 'NONE'} ",
                bg="#2e7d32", fg="white"
            )

        # 3. Update Detailed Screen (frame_detail) if open
        if frame_detail.winfo_ismapped() and active_detail_port in snap:
            d = snap[active_detail_port]
            skey = active_detail_skey
            sp_eval = get_active_setpoints(skey)

            txt_detail_data.config(state="normal")
            txt_detail_data.delete("1.0", "end")

            txt_detail_data.insert("end", f"{get_sensor_display_name(skey)} — DETAILED STATUS\n\n", "black")

            if skey == "PH-06":
                # PH-06 Environmental Monitoring View
                sp6 = get_setpoints("PH-06")
                t_max_limit = float(sp6.get("temp_high_limit", 32.0))
                h_max_limit = float(sp6.get("humi_high_limit", 85.0))

                txt_detail_data.insert("end", "[DESIGNATED MONITORING ZONE - NO ACTUATORS]\n\n", "grey")
                if d and d.get('status') == 'OK':
                    txt_detail_data.insert("end", "LIVE TEMPERATURE: ", "black")
                    txt_detail_data.insert("end", f"{d['temp']:.1f} °C\n", "blue")
                    txt_detail_data.insert("end", "LIVE HUMIDITY:    ", "black")
                    txt_detail_data.insert("end", f"{d['humi']:.1f} %\n\n", "blue")
                else:
                    txt_detail_data.insert("end", "SENSOR OFFLINE\n\n", "red")

                txt_detail_data.insert("end", f"CRITICAL ALARM HIGH TEMP LIMIT : {t_max_limit:.1f} °C\n", "black")
                txt_detail_data.insert("end", f"CRITICAL ALARM HIGH HUMI LIMIT : {h_max_limit:.1f} %\n\n", "black")

            else:
                # PH-01 to PH-05 Full Automated View
                if d and d.get('status') == 'OK':
                    txt_detail_data.insert("end", "TEMPERATURE : ", "black")
                    txt_detail_data.insert("end", f"{d['temp']:.1f} °C    ", "blue")
                    txt_detail_data.insert("end", "HUMIDITY : ", "black")
                    txt_detail_data.insert("end", f"{d['humi']:.1f} %\n", "blue")

                    c_val = d.get('co2')
                    p_val = d.get('par')
                    d_val = d.get('dli')
                    txt_detail_data.insert("end", "CO2 LEVEL   : ", "black")
                    txt_detail_data.insert("end", f"{c_val} ppm    " if c_val else "N/A    ", "blue" if c_val else "red")
                    txt_detail_data.insert("end", "PAR / PPFD : ", "black")
                    txt_detail_data.insert("end", f"{p_val:.1f} µmol/m²/s\n", "blue" if p_val else "red")

                    txt_detail_data.insert("end", "DLI INTEGRAL: ", "black")
                    txt_detail_data.insert("end", f"{d_val:.2f} mol/m²/day (Daily Integrated)\n\n", "blue" if d_val else "grey")
                else:
                    txt_detail_data.insert("end", "INSTRUMENTATION OFFLINE\n\n", "red")

                txt_detail_data.insert("end", f"TEMP TARGET: {sp_eval['target_temp']:.1f} °C  (Range: {sp_eval['T MIN']:.1f} - {sp_eval['T MAX']:.1f} °C)\n", "black")
                txt_detail_data.insert("end", f"HUMI TARGET: {sp_eval['target_humi']:.1f} %   (Range: {sp_eval['H MIN']:.1f} - {sp_eval['H MAX']:.1f} %)\n\n", "black")

                acf_s = "ON" if relay_states.get(RELAY_CH_ACF[skey]) else "OFF"
                spr_s = "ON" if relay_states.get(RELAY_CH_SPRINKLER[skey]) else "OFF"
                fog_s = "ON" if relay_states.get(RELAY_CH_FOGGER[skey]) else "OFF"
                pump_s = "ON" if relay_states.get(RELAY_CH_COMMON_PUMP) else "OFF"

                txt_detail_data.insert("end", "Air Circulation Fans (24 ACFs): ", "black")
                txt_detail_data.insert("end", f"{acf_s}\n", "green" if acf_s == "ON" else "red")
                txt_detail_data.insert("end", "Sprinkler Solenoid Valve:      ", "black")
                txt_detail_data.insert("end", f"{spr_s}\n", "green" if spr_s == "ON" else "red")
                txt_detail_data.insert("end", "Fogger Solenoid Valve:         ", "black")
                txt_detail_data.insert("end", f"{fog_s}\n", "green" if fog_s == "ON" else "red")
                txt_detail_data.insert("end", "Common Water Pump Motor:       ", "black")
                txt_detail_data.insert("end", f"{pump_s}\n", "green" if pump_s == "ON" else "red")

            txt_detail_data.config(state="disabled")

    except Exception as e:
        print(f"UI Update Error: {e}")

    root.after(1000, update_ui)

# -----------------------------------------------------------------------------
# STARTUP INITIALIZATION
# -----------------------------------------------------------------------------
load_config()
load_setpoints()
load_dli_history()
load_trend_history_from_logs()

if __name__ == "__main__":
    # Start background automation thread
    reader_thread = threading.Thread(target=sensor_reader, daemon=True)
    reader_thread.start()

    # Start background offline telemetry backfill sync thread (Sections 16 & 17)
    sync_thread = threading.Thread(target=sync_offline_thread, daemon=True)
    sync_thread.start()

    # Start Bluetooth serial terminal server & auto-trust daemon (WiFi provisioning)
    bt_trust_thread = threading.Thread(target=auto_trust_devices, daemon=True)
    bt_trust_thread.start()
    bt_server_thread = threading.Thread(target=start_bluetooth_server, daemon=True)
    bt_server_thread.start()

    # Build and start UI
    rebuild_grid()
    show(frame_main)
    root.after(500, update_clock_display)
    root.after(1000, update_ui)
    print("[APP] Entering root.mainloop()...")
    try:
        root.mainloop()
        print("[APP] root.mainloop returned normally.")
    except KeyboardInterrupt:
        print("[APP] KeyboardInterrupt received.")
        quit_app()
    except Exception as e:
        print(f"[APP] Mainloop crashed: {e}")
    finally:
        print("[APP] Application exiting.")
