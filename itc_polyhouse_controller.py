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

# Serial USB Ports for Temp & Humi Sensors
SENSOR_MAP = {
    "PH-01": "/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.0-port0",
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

RELAY_CH_ACF = {"PH-01": 1, "PH-02": 5, "PH-03": 9, "PH-04": 13, "PH-05": 17}
RELAY_CH_SPRINKLER = {"PH-01": 2, "PH-02": 6, "PH-03": 10, "PH-04": 14, "PH-05": 18}
RELAY_CH_FOGGER = {"PH-01": 3, "PH-02": 7, "PH-03": 11, "PH-04": 15, "PH-05": 19}
RELAY_CH_COMMON_PUMP = 21
BUZZER_CHANNEL = 22
# All rooms share the single common water pump
RELAY_CH_PUMP = {ph: RELAY_CH_COMMON_PUMP for ph in ACTIVE_POLYHOUSES}
WATER_VALVE_CHANNELS = set(RELAY_CH_SPRINKLER.values()) | set(RELAY_CH_FOGGER.values())

system_config = {
    'relay_port': RELAY_PORT_FIXED,
    'upload_frequency_min': 1.0,
    'temp_alarm_offset': 5.0,
    'humi_alarm_offset': 5.0,
    'system_password': '1234',
    'USER 1 Name': 'Operator 1',
    'USER 1 PASSWORD': '1111',
    'USER 2 Name': 'Operator 2',
    'USER 2 PASSWORD': '2222',
    'room_paused': {ph: False for ph in ALL_POLYHOUSES},
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

room_paused_states = {ph: False for ph in ALL_POLYHOUSES}
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

def is_room_paused(skey):
    return room_paused_states.get(skey, False)

def toggle_room_pause(skey):
    global room_paused_states, relay_states
    room_paused_states[skey] = not room_paused_states.get(skey, False)
    is_paused = room_paused_states[skey]

    if skey in ACTIVE_POLYHOUSES:
        ch_acf = RELAY_CH_ACF.get(skey)
        ch_spr = RELAY_CH_SPRINKLER.get(skey)
        ch_fog = RELAY_CH_FOGGER.get(skey)
        if is_paused:
            if ch_acf: set_relay(ch_acf, False)
            if ch_spr: set_relay(ch_spr, False)
            if ch_fog: set_relay(ch_fog, False)
            set_ui_toast(f" {get_sensor_display_name(skey)} MANUAL STOPPED", duration_sec=4)
        else:
            set_ui_toast(f" {get_sensor_display_name(skey)} RUNNING (RESUMED)", duration_sec=4)

    system_config.setdefault('room_paused', {})[skey] = is_paused
    save_config()
    update_ui()
    broadcast_current_state()

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

# Scheduled Irrigation / Fogging Slots Active Tracker
active_scheduled_irrigation = {}

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

def get_upload_hms():
    h = int(system_config.get('upload_hours', 0))
    m = int(system_config.get('upload_mins', 0))
    s = int(system_config.get('upload_secs', 0))
    if h == 0 and m == 0 and s == 0 and 'upload_frequency_min' in system_config:
        try:
            total_sec = int(round(float(system_config.get('upload_frequency_min', 0)) * 60.0))
            h = total_sec // 3600
            m = (total_sec % 3600) // 60
            s = total_sec % 60
        except Exception:
            h, m, s = 0, 1, 0
    if h == 0 and m == 0 and s == 0:
        s = 1  # minimum 1 sec
    return h, m, s

def normalize_upload_values(h_in, m_in, s_in):
    try: h = int(h_in)
    except Exception: h = 0
    try: m = int(m_in)
    except Exception: m = 0
    try: s = int(s_in)
    except Exception: s = 0
    total_sec = (h * 3600) + (m * 60) + s
    if total_sec <= 0:
        total_sec = 1
    norm_h = total_sec // 3600
    norm_m = (total_sec % 3600) // 60
    norm_s = total_sec % 60
    return norm_h, norm_m, norm_s

def format_upload_hms_display(h, m, s):
    try:
        h, m, s = normalize_upload_values(h, m, s)
        total_sec = (h * 3600) + (m * 60) + s
        if total_sec < 60:
            return f"{total_sec} Sec" if total_sec > 1 else "1 Sec (Realtime)"
        elif total_sec < 3600:
            if s == 0:
                return f"{m} Min"
            return f"{m}m {s}s"
        elif total_sec < 86400:
            parts = [f"{h} Hr" if h == 1 else f"{h} Hrs"]
            if m > 0: parts.append(f"{m} Min")
            if s > 0: parts.append(f"{s} Sec")
            return " ".join(parts)
        else:
            days = total_sec / 86400.0
            if days < 7:
                return f"{days:.1f} Days" if days % 1 != 0 else f"{int(days)} Day{'s' if days > 1 else ''}"
            weeks = days / 7.0
            return f"{weeks:.1f} Weeks" if weeks % 1 != 0 else f"{int(weeks)} Week{'s' if weeks > 1 else ''}"
    except Exception:
        return "1 Sec (Realtime)"

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

    return {
        "name": system_config.get("sensor_names", {}).get(skey, skey),
        "mode": "AUTO",  # "AUTO", "MANUAL", "CYCLIC"
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
        # Section 20A Note: Tabular Cyclic Timers
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
        "irrigation_slots": [
            {"id": 1, "start": "07:00 AM", "duration_sec": 120, "type": "sprinkler", "enabled": True},
            {"id": 2, "start": "12:30 PM", "duration_sec": 120, "type": "sprinkler", "enabled": True},
            {"id": 3, "start": "04:30 PM", "duration_sec": 120, "type": "fogger", "enabled": True}
        ]
    }

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

    global RELAY_CH_COMMON_PUMP
    if 'common_pump_channel' in system_config:
        RELAY_CH_COMMON_PUMP = int(system_config['common_pump_channel'])
    else:
        system_config['common_pump_channel'] = RELAY_CH_COMMON_PUMP
        need_save = True

    if 'room_paused' in system_config:
        room_paused_states.update(system_config['room_paused'])
    else:
        system_config['room_paused'] = copy.deepcopy(room_paused_states)
        need_save = True

    if 'USER 1 Name' not in system_config:
        system_config['USER 1 Name'] = 'Operator 1'
        need_save = True
    if 'USER 1 PASSWORD' not in system_config:
        system_config['USER 1 PASSWORD'] = '1111'
        need_save = True
    if 'USER 2 Name' not in system_config:
        system_config['USER 2 Name'] = 'Operator 2'
        need_save = True
    if 'USER 2 PASSWORD' not in system_config:
        system_config['USER 2 PASSWORD'] = '2222'
        need_save = True

    if 'upload_frequency_min' not in system_config: 
        system_config['upload_frequency_min'] = 1.0
        need_save = True
    if 'upload_hours' not in system_config or 'upload_mins' not in system_config or 'upload_secs' not in system_config:
        try:
            total_sec = int(round(float(system_config.get('upload_frequency_min', 1.0)) * 60.0))
            if total_sec <= 0: total_sec = 60
            system_config['upload_hours'] = total_sec // 3600
            system_config['upload_mins'] = (total_sec % 3600) // 60
            system_config['upload_secs'] = total_sec % 60
        except Exception:
            system_config['upload_hours'] = 0
            system_config['upload_mins'] = 1
            system_config['upload_secs'] = 0
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
                if "temp_high" not in sensor_setpoints[skey] or "Timer1 Name" not in sensor_setpoints[skey]:
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
        set_ui_toast(f" SETPOINTS UPDATED ({source})")
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

    return active_info

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
    state_bool = bool(state)
    relay_states[channel] = state_bool
    relay_cmd_queue.put((channel, state_bool))

    # Automatic Common Pump Interlock:
    # Whenever ANY room's fogger or sprinkler turns ON, the common pump relay turns ON at that exact same time!
    # When no foggers or sprinklers are ON across all rooms, the common pump turns OFF.
    if channel in WATER_VALVE_CHANNELS:
        any_water_on = any(relay_states.get(ch, False) for ch in WATER_VALVE_CHANNELS)
        if any_water_on and not relay_states.get(RELAY_CH_COMMON_PUMP, False):
            relay_states[RELAY_CH_COMMON_PUMP] = True
            relay_cmd_queue.put((RELAY_CH_COMMON_PUMP, True))
        elif not any_water_on and relay_states.get(RELAY_CH_COMMON_PUMP, False):
            relay_states[RELAY_CH_COMMON_PUMP] = False
            relay_cmd_queue.put((RELAY_CH_COMMON_PUMP, False))

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

CONTROL_TOPIC = f"inhydro/{DEVICE_NAME}/control"
CONTROL_CMD_TOPIC = f"inhydro/{DEVICE_NAME}/command"
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
            "active_water_zone": active_water_zone,
            "room_paused_states": room_paused_states
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
        "pump_active": pump_st,
        "room_paused_states": room_paused_states
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
        topic = str(msg.topic)
        if (topic.endswith("/telemetry") or 
            topic.endswith("/telemetry/live") or 
            topic.endswith("/heartbeat") or 
            topic.endswith("/command/status") or 
            topic.endswith("/setpoints/current")):
            return

        if getattr(msg, 'retain', False):
            return

        try:
            payload_str = msg.payload.decode('utf-8')
            new_data = json.loads(payload_str)
        except Exception:
            new_data = {"raw": msg.payload.decode('utf-8', errors='ignore').strip()}

        if isinstance(new_data, dict) and (new_data.get("source") == "device" or new_data.get("from") == "device"):
            return

        # Remote Hardware Commands (Restart, Exit, Pause, Resume)
        if topic == CONTROL_CMD_TOPIC or topic.endswith("/command"):
            action = str(new_data.get("action", new_data.get("raw", ""))).lower().strip()
            print(f"[MQTT COMMAND] Received remote action: '{action}'")

            if action == "restart":
                print("[MQTT COMMAND] Remote restart triggered!")
                try:
                    client.publish(f"inhydro/{DEVICE_NAME}/command/status", json.dumps({"action": "restart", "status": "executing", "timestamp": time.time(), "source": "device"}), retain=False)
                except Exception: pass
                set_ui_toast("⚠ REMOTE RESTART TRIGGERED FROM CLOUD", duration_sec=4)
                try: root.after(1500, restart_program)
                except: restart_program()
                return

            elif action in ["exit", "stop_app", "quit"]:
                print("[MQTT COMMAND] Remote exit triggered!")
                try:
                    client.publish(f"inhydro/{DEVICE_NAME}/command/status", json.dumps({"action": "exit", "status": "executing", "timestamp": time.time(), "source": "device"}), retain=False)
                except Exception: pass
                set_ui_toast("⚠ REMOTE SHUTDOWN TRIGGERED FROM CLOUD", duration_sec=4)
                try: root.after(1500, quit_app)
                except: quit_app()
                return

            elif action in ["pause", "stop", "pause_room", "stop_room"]:
                target_room = new_data.get("polyhouse") or new_data.get("room") or new_data.get("skey")
                if target_room and target_room in room_paused_states:
                    room_paused_states[target_room] = True
                    ch_acf = RELAY_CH_ACF.get(target_room)
                    ch_spr = RELAY_CH_SPRINKLER.get(target_room)
                    ch_fog = RELAY_CH_FOGGER.get(target_room)
                    if ch_acf: set_relay(ch_acf, False)
                    if ch_spr: set_relay(ch_spr, False)
                    if ch_fog: set_relay(ch_fog, False)
                    system_config.setdefault('room_paused', {})[target_room] = True
                    save_config()
                    set_ui_toast(f" {get_sensor_display_name(target_room)} REMOTE STOPPED", duration_sec=4)
                else:
                    for k in room_paused_states:
                        room_paused_states[k] = True
                        ch_acf = RELAY_CH_ACF.get(k)
                        ch_spr = RELAY_CH_SPRINKLER.get(k)
                        ch_fog = RELAY_CH_FOGGER.get(k)
                        if ch_acf: set_relay(ch_acf, False)
                        if ch_spr: set_relay(ch_spr, False)
                        if ch_fog: set_relay(ch_fog, False)
                    system_config['room_paused'] = dict(room_paused_states)
                    save_config()
                    set_ui_toast("⚠ ALL POLYHOUSES REMOTE STOPPED", duration_sec=4)
                try:
                    client.publish(f"inhydro/{DEVICE_NAME}/command/status", json.dumps({"action": "pause", "status": "paused", "timestamp": time.time(), "source": "device"}), retain=False)
                except Exception: pass
                broadcast_current_state()
                return

            elif action in ["resume", "run", "start", "resume_room", "run_room"]:
                target_room = new_data.get("polyhouse") or new_data.get("room") or new_data.get("skey")
                if target_room and target_room in room_paused_states:
                    room_paused_states[target_room] = False
                    system_config.setdefault('room_paused', {})[target_room] = False
                    save_config()
                    set_ui_toast(f" {get_sensor_display_name(target_room)} REMOTE RESUMED", duration_sec=4)
                else:
                    for k in room_paused_states:
                        room_paused_states[k] = False
                    system_config['room_paused'] = dict(room_paused_states)
                    save_config()
                    set_ui_toast("✔ ALL POLYHOUSES REMOTE RUNNING", duration_sec=4)
                try:
                    client.publish(f"inhydro/{DEVICE_NAME}/command/status", json.dumps({"action": "resume", "status": "running", "timestamp": time.time(), "source": "device"}), retain=False)
                except Exception: pass
                broadcast_current_state()
                return

        # Remote Setpoints & Sync Handling
        if topic == CONTROL_SYNC_TOPIC or topic.endswith("/request_sync"):
            broadcast_current_state()
            return

        if isinstance(new_data, dict):
            target_ph = str(new_data.get("polyhouse", "")).strip().upper()
            if target_ph in ALL_POLYHOUSES:
                sp = get_setpoints(target_ph)
                sp.update(new_data)
                save_setpoints(source="CLOUD_MQTT")
                print(f"[MQTT] Setpoints updated for {target_ph} from Cloud")
    except Exception as e:
        print(f"[MQTT Error] {e}")

def on_control_connect(client, userdata, flags, rc=0, *args, **kwargs):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(CONTROL_CMD_TOPIC)
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


def set_wifi(ssid, password):
    try:
        ssid = str(ssid).strip()
        password = str(password).strip()
        if not ssid:
            return "FAILED: Empty SSID"
        try:
            subprocess.run(['rfkill', 'unblock', 'wifi'], capture_output=True, timeout=3)
            subprocess.run(['nmcli', 'radio', 'wifi', 'on'], capture_output=True, timeout=3)
        except Exception: pass
        try:
            subprocess.run(['nmcli', 'connection', 'delete', 'id', ssid], capture_output=True, timeout=4)
            subprocess.run(['nmcli', 'connection', 'delete', ssid], capture_output=True, timeout=4)
        except Exception: pass
        
        cmd = ['nmcli', '--wait', '15', 'device', 'wifi', 'connect', ssid]
        if password:
            cmd += ['password', password]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        
        if res.returncode != 0 and password:
            try:
                subprocess.run(['nmcli', 'connection', 'delete', 'id', ssid], capture_output=True, timeout=4)
                subprocess.run(['nmcli', 'connection', 'add', 'type', 'wifi', 'con-name', ssid, 'ifname', '*', 'ssid', ssid], capture_output=True, timeout=8)
                subprocess.run(['nmcli', 'connection', 'modify', ssid, 'wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', password], capture_output=True, timeout=6)
                res = subprocess.run(['nmcli', '--wait', '15', 'connection', 'up', 'id', ssid], capture_output=True, text=True, timeout=20)
            except Exception: pass

        if res.returncode == 0:
            return f"SUCCESS: Connected to '{ssid}'!"
        err_msg = res.stderr.strip() or res.stdout.strip() or "Connection failed"
        return f"FAILED: {err_msg}"
    except Exception as e: return f"ERROR: {str(e)}"

def scan_wifi():
    try:
        try:
            subprocess.Popen(['nmcli', 'dev', 'wifi', 'rescan'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception: pass

        command = ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'dev', 'wifi']
        result = subprocess.run(command, capture_output=True, text=True, timeout=4)
        if result.returncode != 0:
            command = ['nmcli', '-t', '-f', 'SSID,SIGNAL', 'dev', 'wifi']
            result = subprocess.run(command, capture_output=True, text=True, timeout=4)

        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            found = {}
            for line in lines:
                if not line.strip(): continue
                parts = line.split(':')
                if len(parts) >= 2:
                    s_name = parts[0].strip()
                    sig = parts[1].strip()
                    sec = parts[2].strip() if len(parts) > 2 else ""
                    if s_name and s_name not in found:
                        found[s_name] = f"{sig}% Signal" + (f" [{sec}]" if sec else " [OPEN]")
            if not found:
                return "\r\n[NO WIFI NETWORKS FOUND]\r\n"
            response = "\r\n--- NEARBY WIFI NETWORKS ---\r\n"
            for i, (s_name, s_info) in enumerate(found.items(), 1):
                response += f"{i}. {s_name} ({s_info})\r\n"
            response += "\r\nUse command: WIFI:SSID:PASSWORD\r\n"
            return response
        else:
            return f"SCAN FAILED: {result.stderr.strip() or result.stdout.strip()}"
    except Exception as e:
        return f"SCAN ERROR: {str(e)}"

def get_connected_wifi_ssid():
    try:
        res = subprocess.run(['nmcli', '-t', '-f', 'active,ssid,signal', 'dev', 'wifi'], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            for line in res.stdout.strip().split('\n'):
                if line.startswith('yes:'):
                    parts = line.split(':')
                    ssid = parts[1]
                    sig = parts[2] if len(parts) > 2 else ''
                    return f"{ssid} (Signal: {sig}%)" if sig else ssid
    except Exception:
        pass
    try:
        res = subprocess.run(['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show', '--active'], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            for line in res.stdout.strip().split('\n'):
                if ':802-11-wireless' in line or ':wifi' in line:
                    return line.split(':')[0]
    except Exception:
        pass
    try:
        res = subprocess.run(['iwgetid', '-r'], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None

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

    elif cmd.upper() in ["WIFI", "WIFISTATUS", "CURRENTWIFI", "CHECKWIFI", "6"]:
        curr_ssid = get_connected_wifi_ssid()
        ip_addr = get_system_ip_summary()
        if curr_ssid:
            resp = (
                "WIFI STATUS    : CONNECTED\r\n"
                f"CONNECTED SSID : {curr_ssid}\r\n"
            )
        else:
            resp = (
                "WIFI STATUS    : NOT CONNECTED (DISCONNECTED)\r\n"
                "Note           : Send 'SCAN' to view networks or 'WIFI:SSID:PASSWORD' to connect.\r\n"
            )
        write_fn(resp)

    elif cmd.upper() in ["STATUS", "INFO", "3"]:
        with sensor_data_lock: snap = dict(sensor_data)
        curr_ssid = get_connected_wifi_ssid()
        wifi_str = f"CONNECTED ({curr_ssid})" if curr_ssid else "DISCONNECTED"
        lines = [
            "--- ITC POLYHOUSE CONTROLLER STATUS ---",
            f"WiFi Status : {wifi_str}",
            f"Water Pump  : {'RUNNING' if pump_active else 'IDLE'} (Zone: {active_water_zone or 'None'})",
            "-----------------------------------------"
        ]
        for ph in ACTIVE_POLYHOUSES:
            port = SENSOR_MAP.get(ph)
            d = snap.get(ph) or snap.get(port) or {}
            st_acf = "ON" if relay_states.get(RELAY_CH_ACF[ph]) else "OFF"
            st_spr = "ON" if relay_states.get(RELAY_CH_SPRINKLER[ph]) else "OFF"
            st_fog = "ON" if relay_states.get(RELAY_CH_FOGGER[ph]) else "OFF"

            if d.get("status") == "OK":
                t_str = f"{d.get('temp', '--'):.1f}C"
                h_str = f"{d.get('humi', '--'):.1f}%"
                c_str = f", CO2: {d.get('co2')}ppm" if d.get('co2') else ""
                lines.append(f"{ph}: Temp {t_str}, Humi {h_str}{c_str}")
            else:
                lines.append(f"{ph}: SENSOR OFFLINE")
            lines.append(f"       ACF: {st_acf} | Sprinkler: {st_spr} | Fogger: {st_fog}")
            lines.append("")

        port6 = SENSOR_MAP.get("PH-06")
        d6 = snap.get("PH-06") or snap.get(port6) or {}
        if d6.get("status") == "OK":
            lines.append(f"PH-06: Temp {d6.get('temp', '--'):.1f}C, Humi {d6.get('humi', '--'):.1f}% (Monitoring Only)")
        else:
            lines.append("PH-06: SENSOR OFFLINE (Monitoring Only)")
        lines.append("")

        lines.append("-----------------------------------------")
        st_common_pump = "RUNNING (ON)" if relay_states.get(RELAY_CH_COMMON_PUMP) else "IDLE (OFF)"
        st_buzzer = "ACTIVE (ON)" if relay_states.get(BUZZER_CHANNEL) else "OFF"
        lines.append(f"Common Master Pump : {st_common_pump} (Zone: {active_water_zone or 'None'})")
        lines.append(f"Hardware Buzzer    : {st_buzzer}")
        lines.append(f"Active Warnings    : {', '.join(active_warnings) if active_warnings else 'None'}")
        write_fn("\r\n" + "\r\n".join(lines))

    else:
        fallback = f"\r\nACK: Received '{cmd}'\r\nAvailable Commands: 1.PING | 2.SCAN | 3.STATUS | 4.WIFI:SSID:PASSWORD | 5.ID:new_id | 6.WIFI\r\n\r\n"
        write_fn(fallback)

def handle_bt_client_fd(fd_int):
    try:
        print(f"[BLUETOOTH] Client Connected (FD: {fd_int})")
        curr_ssid = get_connected_wifi_ssid()
        wifi_str = f"CONNECTED ({curr_ssid})" if curr_ssid else "DISCONNECTED"
        welcome_msg = (
            "--- INHYDRO ITC POLYHOUSE AUTOMATION SYSTEM ---\r\n"
            #f"Device ID   : {DEVICE_NAME}\r\n"
            #f"WiFi Status : {wifi_str}\r\n"

            "COMMAND MENU:\r\n"
            "1. PING\r\n"
            "2. SCAN\r\n"
            "3. STATUS\r\n"
            "4. WIFI:SSID:PASSWORD\r\n"
            #"5. ID:new_device_id\r\n"
            "5. WIFI (Check connected WiFi SSID)\r\n"
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
        curr_ssid = get_connected_wifi_ssid()
        welcome_msg = (
            "--- INHYDRO ITC POLYHOUSE AUTOMATION SYSTEM ---\r\n"
           
            "COMMAND MENU:\r\n"
            "1. PING\r\n"
            "2. SCAN\r\n"
            "3. STATUS\r\n"
            "4. WIFI:SSID:PASSWORD\r\n"
            #"5. ID:new_device_id\r\n"
            "6. WIFI (Check connected WiFi SSID)\r\n"
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
    dev_alias = f"Inhydro_{DEVICE_NAME}"
    try:
        subprocess.run(["bluetoothctl", "power", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "system-alias", dev_alias], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "discoverable-timeout", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "pairable-timeout", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "discoverable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "pairable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception: pass

    while running:
        try:
            # Re-ensure pairable and discoverable stay on continuously
            subprocess.run(["bluetoothctl", "discoverable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            subprocess.run(["bluetoothctl", "pairable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)

            output = subprocess.check_output(['bluetoothctl', 'devices'], text=True, timeout=3)
            for line in output.split('\n'):
                if line.startswith('Device '):
                    mac = line.split(" ")[1].strip()
                    subprocess.run(["bluetoothctl", "trust", mac], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except Exception: pass
        time.sleep(4)

def register_spp_dbus():
    try:
        for p_path in glob.glob('/usr/lib/python3*/dist-packages'):
            if p_path not in sys.path: sys.path.append(p_path)
        import dbus, dbus.service
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib

        DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()

        class BluetoothAgent(dbus.service.Object):
            @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
            def Release(self): pass

            @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
            def AuthorizeService(self, device, uuid):
                self._auto_trust(device)
                return

            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='s')
            def RequestPinCode(self, device):
                self._auto_trust(device)
                return '0000'

            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='u')
            def RequestPasskey(self, device):
                self._auto_trust(device)
                return dbus.UInt32(123456)

            @dbus.service.method('org.bluez.Agent1', in_signature='ouq', out_signature='')
            def DisplayPasskey(self, device, passkey, entered): pass

            @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
            def DisplayPinCode(self, device, pincode): pass

            @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='')
            def RequestConfirmation(self, device, passkey):
                self._auto_trust(device)
                return

            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
            def RequestAuthorization(self, device):
                self._auto_trust(device)
                return

            @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
            def Cancel(self): pass

            def _auto_trust(self, dev_path):
                try:
                    d_obj = bus.get_object('org.bluez', dev_path)
                    d_props = dbus.Interface(d_obj, 'org.freedesktop.DBus.Properties')
                    d_props.Set('org.bluez.Device1', 'Trusted', dbus.Boolean(True))
                except Exception: pass

        class BluezProfile(dbus.service.Object):
            @dbus.service.method('org.bluez.Profile1', in_signature='oha{sv}', out_signature='')
            def NewConnection(self, path, fd, properties):
                fd_int = fd.take()
                flags = fcntl.fcntl(fd_int, fcntl.F_GETFL)
                fcntl.fcntl(fd_int, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
                threading.Thread(target=handle_bt_client_fd, args=(fd_int,), daemon=True).start()

            @dbus.service.method('org.bluez.Profile1', in_signature='o', out_signature='')
            def RequestDisconnection(self, path): pass

        agent_path = '/inhydro/auto_agent'
        try:
            agent = BluetoothAgent(bus, agent_path)
            obj = bus.get_object('org.bluez', '/org/bluez')
            manager = dbus.Interface(obj, 'org.bluez.AgentManager1')
            try: manager.UnregisterAgent(agent_path)
            except Exception: pass
            manager.RegisterAgent(agent_path, 'NoInputNoOutput')
            manager.RequestDefaultAgent(agent_path)
        except Exception as e:
            print(f"[BLUETOOTH] Agent notice: {e}")

        profile_path = '/inhydro/spp_profile'
        profile = BluezProfile(bus, profile_path)
        manager_p = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.ProfileManager1')
        try: manager_p.UnregisterProfile(profile_path)
        except Exception: pass

        spp_uuid = "00001101-0000-1000-8000-00805f9b34fb"
        opts = {
            'AutoConnect': dbus.Boolean(True),
            'Role': 'server',
            'Name': f'Inhydro_{DEVICE_NAME}',
            'Channel': dbus.UInt16(1),
            'RequireAuthentication': dbus.Boolean(False),
            'RequireAuthorization': dbus.Boolean(False)
        }
        manager_p.RegisterProfile(profile_path, spp_uuid, opts)

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

def read_md02(port_path, label="", slave_id=1):
    """
    Direct, robust MinimalModbus reader with full 16-bit signed decoding,
    0.01/0.1 auto-scaling resolution, supporting both individual USB ports
    and shared RS485 multi-drop buses.
    """
    if not port_path or not os.path.exists(port_path) or os.path.isdir(port_path) or "PLACE" in port_path:
        return None

    # Try requested room slave ID first, and fallback to ID 1 if different
    slave_ids_to_try = [slave_id] if slave_id == 1 else [slave_id, 1]

    for s_id in slave_ids_to_try:
        inst = None
        try:
            inst = minimalmodbus.Instrument(port_path, s_id)
            inst.serial.baudrate = BAUDRATE
            inst.serial.timeout = 0.2
            inst.mode = minimalmodbus.MODE_RTU
            inst.close_port_after_each_call = True

            values = None
            for fc in [4, 3]:
                for reg in [0, 1]:
                    try:
                        res = inst.read_registers(reg, 2, functioncode=fc)
                        if res and len(res) >= 2 and (res[0] > 0 or res[1] > 0):
                            values = res
                            break
                    except Exception:
                        pass
                if values:
                    break

            if not values:
                # Instant fallback to 9600 baud
                inst.serial.baudrate = 9600
                for fc in [4, 3]:
                    for reg in [0, 1]:
                        try:
                            res = inst.read_registers(reg, 2, functioncode=fc)
                            if res and len(res) >= 2 and (res[0] > 0 or res[1] > 0):
                                values = res
                                break
                        except Exception:
                            pass
                    if values:
                        break

            if not values or len(values) < 2:
                continue

            # Signed 16-bit integer decoding
            raw0 = values[0]
            if raw0 > 32767: raw0 -= 65536
            raw1 = values[1]
            if raw1 > 32767: raw1 -= 65536

            # Auto-scaling: handles 0.01 resolution & 0.1 resolution
            val0 = raw0 / 100.0 if abs(raw0) > 1000 else raw0 / 10.0
            val1 = raw1 / 100.0 if abs(raw1) > 1000 else raw1 / 10.0

            if val0 > val1 and val0 > 40.0:
                humi = round(val0, 1)
                temp = round(val1, 1)
            else:
                temp = round(val0, 1)
                humi = round(val1, 1)

            return {"temp": temp, "humi": humi}
        except Exception:
            continue
        finally:
            if inst and hasattr(inst, "serial") and inst.serial:
                try: inst.serial.close()
                except Exception: pass

    return None

def sensor_reader():
    global running, system_paused, active_warnings, last_upload_time, last_dli_calc_time, last_trend_sample_time
    global pump_active, pump_start_time, pump_stop_scheduled_time, active_water_zone, active_water_zone_start
    global buzzer_active, buzzer_start_time, buzzer_silenced_for_current_alarm, active_scheduled_irrigation

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

        # 1. READ ALL PHYSICAL SENSORS INDIVIDUALLY (ROOM-WISE & SENSOR-WISE INDEPENDENT)
        for skey, port in SENSOR_MAP.items():
            if not running or system_paused: break
            time.sleep(0.01)

            temp, humi, co2, par = None, None, None, None

            # Resolve actual port (either configured by-path or ttyUSB fallback)
            real_port = port if (port and os.path.exists(port)) else None
            if not real_port:
                s_idx = int(skey.replace("PH-0", "").replace("PH-", "")) - 1
                cand = f"/dev/ttyUSB{s_idx}"
                if os.path.exists(cand) and cand != RELAY_PORT_FIXED:
                    real_port = cand

            if real_port:
                s_id = int(skey.replace("PH-0", "").replace("PH-", ""))
                md_res = read_md02(real_port, skey, slave_id=s_id)
                if md_res:
                    temp = md_res['temp']
                    humi = md_res['humi']

            if skey in ACTIVE_POLYHOUSES:
                c_port = CO2_SENSOR_MAP.get(skey)
                if c_port and os.path.exists(c_port) and "PLACE" not in c_port:
                    try:
                        inst_c = minimalmodbus.Instrument(c_port, 1)
                        inst_c.serial.baudrate = 9600
                        inst_c.serial.timeout = 0.15
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
                if p_port and os.path.exists(p_port) and "PLACE" not in p_port:
                    try:
                        inst_p = minimalmodbus.Instrument(p_port, 1)
                        inst_p.serial.baudrate = 9600
                        inst_p.serial.timeout = 0.15
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

            # Store sensor telemetry dual-keyed by skey ("PH-01") and port for 100% fail-safe lookup
            sensor_entry = {
                'skey': skey,
                'temp': temp,
                'humi': humi,
                'co2': co2,
                'par': par,
                'dli': dli_val,
                'status': 'OK' if (temp is not None and humi is not None) else 'OFFLINE'
            }
            with sensor_data_lock:
                sensor_data[port] = sensor_entry
                sensor_data[skey] = sensor_entry
                if real_port:
                    sensor_data[real_port] = sensor_entry

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
                    with sensor_data_lock: sd = sensor_data.get(p_key) or sensor_data.get(p_port, {})
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
            # Per-Room Manual Stop Check
            if is_room_paused(skey):
                set_relay(RELAY_CH_ACF[skey], False)
                set_relay(RELAY_CH_FOGGER[skey], False)
                set_relay(RELAY_CH_SPRINKLER[skey], False)
                continue

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
        if p6_port and not is_room_paused("PH-06"):
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

        # 3. SHARED COMMON PUMP ROUTINE & INTERLOCK
        # Whenever fogger or sprinkler is ON in any room, common pump relay turns ON immediately at that same time!
        arb_mode = system_config.get("pump_arbitration_mode", "parallel")

        if not water_requests:
            # No water demand: turn off all solenoids and common pump immediately
            for ph in ACTIVE_POLYHOUSES:
                set_relay(RELAY_CH_FOGGER[ph], False)
                set_relay(RELAY_CH_SPRINKLER[ph], False)
            set_relay(RELAY_CH_COMMON_PUMP, False)
            pump_active = False
            pump_stop_scheduled_time = 0
            active_water_zone = None
        else:
            pump_stop_scheduled_time = 0
            if arb_mode == "parallel":
                # Open all requested valves & common pump immediately at the exact same time
                for ph in ACTIVE_POLYHOUSES:
                    f_req = ("FOGGER", ph) in water_requests and not is_room_paused(ph)
                    s_req = ("SPRINKLER", ph) in water_requests and not is_room_paused(ph)
                    set_relay(RELAY_CH_FOGGER[ph], f_req)
                    set_relay(RELAY_CH_SPRINKLER[ph], s_req)

                set_relay(RELAY_CH_COMMON_PUMP, True)
                pump_active = True
                active_water_zone = "PARALLEL (ALL ACTIVE)"
            else:
                # Sequential Priority Arbitration: run one zone at a time
                valid_requests = [(t, p) for t, p in water_requests if not is_room_paused(p)]
                if valid_requests:
                    req_keys = [f"{t}:{p}" for t, p in valid_requests]
                    if active_water_zone not in req_keys:
                        active_water_zone = req_keys[0]
                        active_water_zone_start = now
                    elif now - active_water_zone_start > 120.0:
                        idx = (req_keys.index(active_water_zone) + 1) % len(req_keys)
                        active_water_zone = req_keys[idx]
                        active_water_zone_start = now

                    act_type, act_ph = active_water_zone.split(":")
                    for ph in ACTIVE_POLYHOUSES:
                        is_this_ph = (ph == act_ph)
                        set_relay(RELAY_CH_FOGGER[ph], (act_type == "FOGGER" and is_this_ph))
                        set_relay(RELAY_CH_SPRINKLER[ph], (act_type == "SPRINKLER" and is_this_ph))

                    set_relay(RELAY_CH_COMMON_PUMP, True)
                    pump_active = True
                else:
                    for ph in ACTIVE_POLYHOUSES:
                        set_relay(RELAY_CH_FOGGER[ph], False)
                        set_relay(RELAY_CH_SPRINKLER[ph], False)
                    set_relay(RELAY_CH_COMMON_PUMP, False)
                    pump_active = False
                    active_water_zone = None

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

        # 5. CLOUD MQTT PUBLISH AT CONFIGURABLE INTERVAL (HOUR : MIN : SEC)
        u_h, u_m, u_s = get_upload_hms()
        upload_freq_sec = (u_h * 3600) + (u_m * 60) + u_s
        if upload_freq_sec <= 0: upload_freq_sec = 1
        if (now - last_upload_time) >= upload_freq_sec:
            broadcast_current_state()
            last_upload_time = now

        # 6. LOCAL OFFLINE DATA BUFFERING (Sections 16 & 17)
        with sensor_data_lock: snap_sensor = dict(sensor_data)
        with dli_lock: snap_dli = dict(dli_data)
        save_local_telemetry_if_offline(snap_sensor, snap_dli, relay_states, pump_active)

        time.sleep(1.0)

root = tk.Tk()
root.update()
root.title("INHYDRO ITC Polyhouse Automation System")
root.attributes("-fullscreen", True)
root.geometry("1024x600")

def quit_app():
    global running
    print("[APP] Shutting down ITC Polyhouse Controller gracefully...")
    running = False
    emergency_stop_all()
    try: root.destroy()
    except Exception: pass
    sys.exit(0)

root.bind("<Escape>", lambda event: quit_app())
root.bind("<F11>", lambda event: root.attributes("-fullscreen", not bool(root.attributes("-fullscreen"))))
root.protocol("WM_DELETE_WINDOW", lambda: quit_app())
root.configure(bg="white")

big = font.Font(family="Helvetica", size=18, weight="bold")
med = font.Font(family="Helvetica", size=14, weight="bold")
small = font.Font(family="Helvetica", size=12, weight="bold")

FRAME_BTN_WIDTH = 20
FRAME_BTN_HEIGHT = 2
BTN_FONT_MAIN = ("Helvetica", 13, "bold")
BTN_FONT_INLINE = ("Helvetica", 12, "bold")

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
            width, height = 130, 45
            img = img.resize((width, height), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(parent, image=photo, bg="white")
            lbl.image = photo
            lbl.place(relx=1.0, rely=0.0, anchor="ne", x=-15, y=10)
            lbl.lift()
            return lbl
    except Exception: pass
    return None

def add_top_left_exit(parent):
    return None

clock_labels = []

def add_bottom_right_clock(parent, bg_color="white"):
    lbl = tk.Label(
        parent,
        text=" Day, DD-MM-YYYY\n hh:mm:ss AM/PM (IST)",
        font=("Helvetica", 12, "bold"),
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
    if frame != frame_main:
        add_bottom_right_clock(frame)

header_main = tk.Frame(frame_main, bg="white")
header_main.pack(side="top", fill="x", pady=(10, 0))

lbl_dash_title = tk.Label(
    header_main,
    text="INHYDRO ITC POLYHOUSE AUTOMATION SYSTEM",
    font=("Helvetica", 18, "bold"),
    fg="#1565c0",
    bg="white"
)
lbl_dash_title.pack(anchor="center", pady=(0, 2))

sensors_grid = tk.Frame(frame_main, bg="white")
sensors_grid.pack(pady=(4, 4), expand=True)
sensor_widgets = {}

footer_main = tk.Frame(frame_main, bg="#eeeeee", height=85)
footer_main.pack(side="bottom", fill="x")
footer_main.pack_propagate(False)

btn_sys_settings = tk.Button(footer_main, text="SYSTEM SETTINGS", font=BTN_FONT_MAIN, width=20, height=FRAME_BTN_HEIGHT, bg="#0891b2", fg="white", cursor="hand2", command=lambda: check_pin_and_proceed("System Settings", open_system_settings_modal))
btn_sys_settings.pack(side="left", padx=15, pady=10)

btn_restart_app = tk.Button(footer_main, text="RESTART", font=BTN_FONT_MAIN, width=14, height=FRAME_BTN_HEIGHT, bg="#1565c0", fg="white", cursor="hand2", command=lambda: restart_program())
btn_restart_app.pack(side="left", padx=15, pady=10)

lbl_clock = tk.Label(footer_main, text="Day, DD-MM-YYYY\n hh:mm:ss AM/PM (IST)", font=("Helvetica", 12, "bold"), fg="#00897b", bg="#eeeeee", justify="right")
lbl_clock.pack(side="right", padx=15, pady=5)

def update_clock_display():
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist_tz)
    now_str = now.strftime(" %A, %d-%m-%Y\n %I:%M:%S %p (IST)")
    if 'lbl_clock' in globals() and lbl_clock.winfo_exists():
        lbl_clock.config(text=now_str)
    for lbl in list(clock_labels):
        try:
            if lbl.winfo_exists(): lbl.config(text=now_str)
            else: clock_labels.remove(lbl)
        except Exception: pass
    root.after(1000, update_clock_display)

def rebuild_grid():
    for i in range(10):
        sensors_grid.columnconfigure(i, weight=0)
        sensors_grid.rowconfigure(i, weight=0)
    idx = 0
    for skey in ALL_POLYHOUSES:
        if skey in sensor_widgets:
            r, c = idx // 3, idx % 3
            sensor_widgets[skey]['card'].grid(row=r, column=c, padx=12, pady=6)
            idx += 1

active_detail_port = None
active_detail_skey = "PH-01"
font_detail_title = font.Font(family="Arial", size=26, weight="bold")
font_detail_data = font.Font(family="Arial", size=16, weight="bold")

lbl_detail_title = tk.Label(frame_detail, text="POLYHOUSE DATA", font=font_detail_title, fg="#1565c0", bg="white")
lbl_detail_title.pack(pady=(14, 4))

txt_detail_data = tk.Text(frame_detail, font=font_detail_data, bg="white", bd=0, highlightthickness=0, height=15, width=60)
txt_detail_data.pack(pady=4, expand=True, fill="both")
txt_detail_data.tag_configure("black", foreground="#000000", justify="center")
txt_detail_data.tag_configure("blue", foreground="#1565c0", justify="center")
txt_detail_data.tag_configure("green", foreground="#16a34a", justify="center")
txt_detail_data.tag_configure("red", foreground="#c62828", justify="center")
txt_detail_data.tag_configure("grey", foreground="#64748b", justify="center")

def update_detail_pause_button(skey):
    if 'btn_room_pause' in globals() and btn_room_pause.winfo_exists():
        if is_room_paused(skey):
            btn_room_pause.config(text="RESTART/RUN", bg="#2e7d32", fg="white")
        else:
            btn_room_pause.config(text="STOP ROOM", bg="#c62828", fg="white")

def toggle_active_room_pause():
    global active_detail_skey
    skey = active_detail_skey or "PH-01"
    toggle_room_pause(skey)
    update_detail_pause_button(skey)
    update_ui()

def open_sensor_detail(port_or_skey):
    global active_detail_port, active_detail_skey
    if port_or_skey in ALL_POLYHOUSES:
        active_detail_skey = port_or_skey
        active_detail_port = SENSOR_MAP.get(port_or_skey)
    else:
        active_detail_port = port_or_skey
        active_detail_skey = next((k for k, v in SENSOR_MAP.items() if v == port_or_skey), "PH-01")

    lbl_detail_title.config(text=get_sensor_display_name(active_detail_skey))
    update_detail_pause_button(active_detail_skey)
    update_ui()
    show(frame_detail)

def edit_active_room_name_detail():
    global active_detail_skey
    skey = active_detail_skey or "PH-01"
    curr_name = get_sensor_display_name(skey)
    def on_confirm(new_name):
        if new_name and new_name.strip():
            system_config.setdefault("sensor_names", {})[skey] = new_name.strip()
            save_config()
            lbl_detail_title.config(text=new_name.strip())
            update_sensor_dropdown_label()
            update_ui()
    open_almora_keypad(f"Rename Room ({skey})", curr_name, on_confirm, is_alphanumeric=True)

btn_f_det = tk.Frame(frame_detail, bg="white")
btn_f_det.pack(side="bottom", fill="x", padx=20, pady=(6, 12))

tk.Button(btn_f_det, text="BACK", font=BTN_FONT_MAIN, bg="#757575", fg="white", width=10, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: show(frame_main)).pack(side="left", padx=(0, 6))
tk.Button(btn_f_det, text="EDIT NAME", font=BTN_FONT_MAIN, bg="#d97706", fg="white", width=14, height=FRAME_BTN_HEIGHT, cursor="hand2", command=edit_active_room_name_detail).pack(side="left", padx=6)
btn_detail_setpoints = tk.Button(btn_f_det, text="SETPOINTS & TIMERS", font=BTN_FONT_MAIN, bg="#0284c7", fg="white", width=22, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: check_pin_and_proceed("Setpoints & Timers", lambda: open_setpoints(active_detail_skey)))
btn_detail_setpoints.pack(side="left", padx=6)
btn_room_pause = tk.Button(btn_f_det, text="STOP ROOM", font=BTN_FONT_MAIN, bg="#c62828", fg="white", width=16, height=FRAME_BTN_HEIGHT, cursor="hand2", command=toggle_active_room_pause)
btn_room_pause.pack(side="left", padx=6)


active_setup_skey = "PH-01"
sensor_dropdown_open = False

lbl_set_title = tk.Label(frame_set, text="SETPOINTS & TIMERS CONFIGURATION", font=big, fg="#1565c0", bg="#ffffff")
lbl_set_title.pack(pady=(12, 2))

sched_row = tk.Frame(frame_set, bg="#ffffff")
sched_row.pack(pady=(2, 4))

tk.Label(sched_row, text="Polyhouse:", font=("Helvetica", 14, "bold"), fg="#334155", bg="#ffffff").pack(side="left", padx=(4, 6))

sensor_menu_frame = tk.Frame(frame_set, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", highlightthickness=1)

def toggle_sensor_dropdown():
    global sensor_dropdown_open
    if sensor_dropdown_open:
        sensor_menu_frame.place_forget()
        sensor_dropdown_open = False
    else:
        for w in sensor_menu_frame.winfo_children(): w.destroy()
        keys = ALL_POLYHOUSES
        for idx, skey in enumerate(keys):
            dname = get_sensor_display_name(skey)
            btn = tk.Button(sensor_menu_frame, text=f"{skey} — {dname}", font=("Helvetica", 13, "bold"), bg="white", fg="#1e293b",
                            activebackground="#0284c7", activeforeground="white", relief="flat", bd=0, anchor="w", padx=14, pady=10, cursor="hand2")
            btn.config(command=lambda s=skey: select_setup_polyhouse(s))
            btn.pack(fill="x")
            if idx < len(keys) - 1:
                tk.Frame(sensor_menu_frame, bg="#cbd5e1", height=1).pack(fill="x")
        sensor_menu_frame.place(in_=sensor_dropdown_btn, relx=0.0, rely=1.0, y=2, width=320)
        sensor_menu_frame.lift()
        sensor_dropdown_open = True

def update_sensor_dropdown_label():
    global active_setup_skey
    skey = active_setup_skey or "PH-01"
    sensor_dropdown_btn.config(text=f"{skey} — {get_sensor_display_name(skey)} ▼")

def select_setup_polyhouse(skey):
    global active_setup_skey, sensor_dropdown_open
    active_setup_skey = skey
    sensor_menu_frame.place_forget()
    sensor_dropdown_open = False
    update_sensor_dropdown_label()
    render_unified_setpoints_view()

sensor_dropdown_btn = tk.Button(sched_row, text="PH-01 — Polyhouse 1 ▼", font=("Helvetica", 13, "bold"), bg="#cbd5e1", fg="#1e293b",
                                activebackground="#94a3b8", activeforeground="#1e293b", relief="flat", bd=0, padx=14, pady=6, cursor="hand2", command=toggle_sensor_dropdown)
sensor_dropdown_btn.pack(side="left", padx=(0, 10))

# Footer packed at bottom of frame_set
footer_set = tk.Frame(frame_set, bg="#ffffff", height=60)
footer_set.pack(side="bottom", fill="x")
footer_set.pack_propagate(False)

tk.Button(footer_set, text="SAVE & RETURN", font=BTN_FONT_MAIN, bg="#0284c7", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2",
          command=lambda: (save_setpoints(), open_sensor_detail(SENSOR_MAP.get(active_setup_skey, "PH-01")))).pack(side="left", padx=15, pady=4)
tk.Button(footer_set, text="BACK", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=12, height=FRAME_BTN_HEIGHT, cursor="hand2",
          command=lambda: open_sensor_detail(SENSOR_MAP.get(active_setup_skey, "PH-01"))).pack(side="left", padx=10, pady=4)

# Scrollable Canvas for Setpoints & Cyclic Timers
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

sp_scrollbar.pack(side="right", fill="y", pady=(4, 0))
sp_canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(4, 0))

def open_setpoints(port_or_skey):
    global active_setup_skey, sensor_dropdown_open
    if sensor_dropdown_open:
        sensor_menu_frame.place_forget()
        sensor_dropdown_open = False
    if port_or_skey in ALL_POLYHOUSES:
        active_setup_skey = port_or_skey
    else:
        active_setup_skey = next((k for k, v in SENSOR_MAP.items() if v == port_or_skey), "PH-01")

    update_sensor_dropdown_label()
    render_unified_setpoints_view()
    show(frame_set)

def make_sp_cell(parent, ph, key, label_text=None, width_lbl=14, default_val=0.0):
    sp = get_setpoints(ph)
    if key not in sp:
        sp[key] = default_val
    lbl_txt = label_text if label_text else key
    cell = tk.Frame(parent, bg="#ffffff")

    tk.Label(cell, text=lbl_txt, font=("Arial", 13, "bold"), fg="#0f172a", bg="#ffffff", anchor="w", width=width_lbl).pack(side="left", padx=2)
    val_lbl = tk.Label(cell, text=str(sp[key]), font=("Arial", 14, "bold"), fg="#e65100", bg="#f8fafc", width=7, anchor="center", relief="sunken", bd=1)
    val_lbl.pack(side="left", padx=(2, 6))

    def _on_confirm(val):
        try:
            fval = round(float(val), 1)
            sp[key] = fval
            val_lbl.config(text=str(fval))
            save_setpoints()
        except Exception: pass

    btn = tk.Button(cell, text="EDIT", font=("Arial", 12, "bold"), width=6, bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="raised", pady=3, padx=6,
                    command=lambda: open_almora_keypad(f"Set {ph} {lbl_txt}", val_lbl.cget("text"), _on_confirm))
    btn.pack(side="right", padx=2)
    return cell

def render_unified_setpoints_view():
    for w in sp_container.winfo_children(): w.destroy()

    ph = active_setup_skey
    sp = get_setpoints(ph)
    disp_name = get_sensor_display_name(ph)

    lbl_set_title.config(text=f"SETPOINTS & TIMERS : {disp_name}")

    if ph == "PH-06":
        card_m = tk.LabelFrame(sp_container, text=f" {disp_name} — ENVIRONMENTAL MONITORING THRESHOLDS ", font=("Arial", 14, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
        card_m.pack(fill="x", pady=10, padx=10)

        grid_m = tk.Frame(card_m, bg="#ffffff")
        grid_m.pack(pady=10, padx=15, fill="x")
        grid_m.columnconfigure(0, weight=1)
        grid_m.columnconfigure(1, weight=1)

        make_sp_cell(grid_m, ph, "temp_high_limit", "Temp High Max (°C):", width_lbl=22, default_val=32.0).grid(row=0, column=0, padx=10, pady=8, sticky="ew")
        make_sp_cell(grid_m, ph, "temp_low_limit", "Temp Low Min (°C):", width_lbl=22, default_val=15.0).grid(row=0, column=1, padx=10, pady=8, sticky="ew")
        make_sp_cell(grid_m, ph, "humi_high_limit", "Humi High Max (%):", width_lbl=22, default_val=85.0).grid(row=1, column=0, padx=10, pady=8, sticky="ew")
        make_sp_cell(grid_m, ph, "humi_low_limit", "Humi Low Min (%):", width_lbl=22, default_val=35.0).grid(row=1, column=1, padx=10, pady=8, sticky="ew")
        return

    # TOP SECTION: Climate Control (Full Width)
    card_climate = tk.LabelFrame(sp_container, text=f" {disp_name} CLIMATE CONTROL ", font=("Arial", 14, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
    card_climate.pack(fill="x", side="top", pady=(0, 4), padx=4)

    grid_climate = tk.Frame(card_climate, bg="#ffffff")
    grid_climate.pack(pady=4, padx=6, fill="x")

    # Left Column: Temperature Setpoints
    temp_section = tk.Frame(grid_climate, bg="#ffffff")
    temp_section.pack(side="left", fill="both", expand=True, padx=6)
    tk.Label(temp_section, text="TEMPERATURE SETPOINTS", font=("Arial", 13, "bold"), fg="#1565c0", bg="#ffffff").pack(anchor="w", pady=(1, 4))
    make_sp_cell(temp_section, ph, "temp_low", "Temp Min:").pack(fill="x", pady=3)
    make_sp_cell(temp_section, ph, "temp_target", "Temp Set:").pack(fill="x", pady=3)
    make_sp_cell(temp_section, ph, "temp_high", "Temp Max:").pack(fill="x", pady=3)
    make_sp_cell(temp_section, ph, "temp_hysteresis", "Hysteresis:").pack(fill="x", pady=3)

    # Vertical Separator
    tk.Frame(grid_climate, bg="#cbd5e1", width=2).pack(side="left", fill="y", padx=10, pady=2)

    # Right Column: Humidity Setpoints
    humi_section = tk.Frame(grid_climate, bg="#ffffff")
    humi_section.pack(side="right", fill="both", expand=True, padx=6)
    tk.Label(humi_section, text="HUMIDITY SETPOINTS", font=("Arial", 13, "bold"), fg="#1565c0", bg="#ffffff").pack(anchor="w", pady=(1, 4))
    make_sp_cell(humi_section, ph, "humi_low", "Humi Min:").pack(fill="x", pady=3)
    make_sp_cell(humi_section, ph, "humi_target", "Humi Set:").pack(fill="x", pady=3)
    make_sp_cell(humi_section, ph, "humi_high", "Humi Max:").pack(fill="x", pady=3)
    make_sp_cell(humi_section, ph, "humi_hysteresis", "Hysteresis:").pack(fill="x", pady=3)

    # BOTTOM SECTION: CYCLIC TIMERS
    sp_bottom_container = tk.Frame(sp_container, bg="#ffffff")
    sp_bottom_container.pack(fill="x", side="top", pady=(4, 4), padx=4)

    card_font = ("Arial", 14, "bold")
    color = "#1565c0"
    card_timers_1 = tk.LabelFrame(sp_bottom_container, text=f" {disp_name} CYCLIC TIMERS ", font=card_font, fg=color, bg="white", bd=2, relief="groove")
    card_timers_1.pack(fill="x", pady=(2, 4), padx=4)

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

    lbl_font = ("Arial", 13, "bold")
    btn_font = ("Arial", 12, "bold")

    header_frame = tk.Frame(card_timers_1, bg="#f5f5f5")
    header_frame.pack(fill="x", pady=3, padx=2)
    tk.Label(header_frame, text="Setting", font=lbl_font, fg="#555", bg="#f5f5f5", width=12, anchor="w").pack(side="left", padx=2)
    for col in cols:
        tk.Label(header_frame, text=col["name"], font=lbl_font, fg=color, bg="#f5f5f5", width=16, anchor="center").pack(side="left", expand=True)

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
                               font=lbl_font, fg="#e65100" if r_key != "Name" else "#333", bg="white", width=11, anchor="center")
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

def open_system_settings_modal():
    modal = tk.Toplevel(root)
    modal.configure(bg="white")
    make_modal_fullscreen(modal)
    add_logo(modal)
    add_top_left_exit(modal)
    add_bottom_right_clock(modal)

    m_main = tk.Frame(modal, bg="white")
    m_main.pack(fill="both", expand=True, pady=(35, 20))

    tk.Label(m_main, text="SYSTEM CONFIGURATION & SETTINGS", font=big, fg="#1565c0", bg="white").pack(pady=(0, 10))

    cfg_container = tk.Frame(m_main, bg="white")
    cfg_container.pack(pady=4)

    cur_h, cur_m, cur_s = get_upload_hms()
    temp_h = cur_h
    temp_m = cur_m
    temp_s = cur_s

    # 1. Cloud Upload Frequency Row (HH : MM : SS)
    r1 = tk.Frame(cfg_container, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=12, pady=6)
    r1.pack(pady=3, fill="x")
    tk.Label(r1, text="Cloud Upload Frequency :", font=("Helvetica", 13, "bold"), width=34, bg="white", fg="#1e293b", anchor="w").pack(side="left")

    lbl_freq = tk.Label(r1, text=format_upload_hms_display(temp_h, temp_m, temp_s), font=("Helvetica", 14, "bold"), bg="#f1f5f9", fg="#1565c0", width=18, relief="sunken", bd=1)
    lbl_freq.pack(side="left", padx=10)

    def on_upload_hms_confirmed(h, m, s):
        nonlocal temp_h, temp_m, temp_s
        temp_h, temp_m, temp_s = h, m, s
        lbl_freq.config(text=format_upload_hms_display(temp_h, temp_m, temp_s))

    def edit_upload_hms():
        open_upload_frequency_keypad(temp_h, temp_m, temp_s, on_upload_hms_confirmed, parent_win=modal)

    tk.Button(r1, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=10, height=1, pady=3, command=edit_upload_hms).pack(side="left", padx=5)

    # 2. Temp Alarm Offset (± °C)
    r2 = tk.Frame(cfg_container, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=12, pady=6)
    r2.pack(pady=3, fill="x")
    tk.Label(r2, text="Temp Alarm Limit (± °C) :", font=("Helvetica", 13, "bold"), width=34, bg="white", fg="#1e293b", anchor="w").pack(side="left")
    t_off_val = system_config.get("temp_alarm_offset", 5.0)
    lbl_toff = tk.Label(r2, text=f"± {t_off_val:.1f} °C", font=("Helvetica", 14, "bold"), bg="#f1f5f9", fg="#1565c0", width=18, relief="sunken", bd=1)
    lbl_toff.pack(side="left", padx=10)

    def edit_toff():
        open_almora_keypad("Edit Temp Alarm Limit (± °C)", str(system_config.get("temp_alarm_offset", 5.0)),
                           lambda v: (system_config.update({"temp_alarm_offset": float(v)}), lbl_toff.config(text=f"± {float(v):.1f} °C"), save_config()))
    tk.Button(r2, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", width=10, height=1, pady=3, command=edit_toff).pack(side="left", padx=5)

    # 3. Humi Alarm Offset (± %)
    r3 = tk.Frame(cfg_container, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=12, pady=6)
    r3.pack(pady=3, fill="x")
    tk.Label(r3, text="Humi Alarm Limit (± %) :", font=("Helvetica", 13, "bold"), width=34, bg="white", fg="#1e293b", anchor="w").pack(side="left")
    h_off_val = system_config.get("humi_alarm_offset", 5.0)
    lbl_hoff = tk.Label(r3, text=f"± {h_off_val:.1f} %", font=("Helvetica", 14, "bold"), bg="#f1f5f9", fg="#1565c0", width=18, relief="sunken", bd=1)
    lbl_hoff.pack(side="left", padx=10)

    def edit_hoff():
        open_almora_keypad("Edit Humi Alarm Limit (± %)", str(system_config.get("humi_alarm_offset", 5.0)),
                           lambda v: (system_config.update({"humi_alarm_offset": float(v)}), lbl_hoff.config(text=f"± {float(v):.1f} %"), save_config()))
    tk.Button(r3, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", width=10, height=1, pady=3, command=edit_hoff).pack(side="left", padx=5)

    # 4. Pump Start Delay (sec)
    r4 = tk.Frame(cfg_container, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=12, pady=6)
    r4.pack(pady=3, fill="x")
    tk.Label(r4, text="Pump Start Delay (sec) :", font=("Helvetica", 13, "bold"), width=34, bg="white", fg="#1e293b", anchor="w").pack(side="left")
    p_start_val = system_config.get("pump_start_delay_sec", 3.0)
    lbl_pstart = tk.Label(r4, text=f"{p_start_val:.1f} sec", font=("Helvetica", 14, "bold"), bg="#f1f5f9", fg="#1565c0", width=18, relief="sunken", bd=1)
    lbl_pstart.pack(side="left", padx=10)

    def edit_pstart():
        open_almora_keypad("Edit Pump Start Delay (sec)", str(system_config.get("pump_start_delay_sec", 3.0)),
                           lambda v: (system_config.update({"pump_start_delay_sec": float(v)}), lbl_pstart.config(text=f"{float(v):.1f} sec"), save_config()))
    tk.Button(r4, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", width=10, height=1, pady=3, command=edit_pstart).pack(side="left", padx=5)

    # 5. Pump Stop / Post-Run Delay (sec)
    r5 = tk.Frame(cfg_container, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=12, pady=6)
    r5.pack(pady=3, fill="x")
    tk.Label(r5, text="Pump Stop/Post-Run Delay (sec) :", font=("Helvetica", 13, "bold"), width=34, bg="white", fg="#1e293b", anchor="w").pack(side="left")
    p_stop_val = system_config.get("pump_post_run_delay_sec", 3.0)
    lbl_pstop = tk.Label(r5, text=f"{p_stop_val:.1f} sec", font=("Helvetica", 14, "bold"), bg="#f1f5f9", fg="#1565c0", width=18, relief="sunken", bd=1)
    lbl_pstop.pack(side="left", padx=10)

    def edit_pstop():
        open_almora_keypad("Edit Pump Stop/Post-Run Delay (sec)", str(system_config.get("pump_post_run_delay_sec", 3.0)),
                           lambda v: (system_config.update({"pump_post_run_delay_sec": float(v)}), lbl_pstop.config(text=f"{float(v):.1f} sec"), save_config()))
    tk.Button(r5, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", width=10, height=1, pady=3, command=edit_pstop).pack(side="left", padx=5)

    # 6. Buzzer Auto-Silence Limit (sec)
    r6 = tk.Frame(cfg_container, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=12, pady=6)
    r6.pack(pady=3, fill="x")
    tk.Label(r6, text="Buzzer Auto-Silence Limit (sec) :", font=("Helvetica", 13, "bold"), width=34, bg="white", fg="#1e293b", anchor="w").pack(side="left")
    buz_val = system_config.get("buzzer_auto_silence_sec", 30)
    lbl_buz = tk.Label(r6, text=f"{buz_val} sec", font=("Helvetica", 14, "bold"), bg="#f1f5f9", fg="#1565c0", width=18, relief="sunken", bd=1)
    lbl_buz.pack(side="left", padx=10)

    def edit_buz():
        open_almora_keypad("Edit Buzzer Auto-Silence Limit (sec)", str(system_config.get("buzzer_auto_silence_sec", 30)),
                           lambda v: (system_config.update({"buzzer_auto_silence_sec": int(float(v))}), lbl_buz.config(text=f"{int(float(v))} sec"), save_config()))
    tk.Button(r6, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", width=10, height=1, pady=3, command=edit_buz).pack(side="left", padx=5)

    # 7. Pump Arbitration Mode Selector
    arb_row = tk.Frame(cfg_container, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=12, pady=6)
    arb_row.pack(pady=3, fill="x")
    tk.Label(arb_row, text="Pump Arbitration Mode :", font=("Helvetica", 13, "bold"), width=34, bg="white", fg="#1e293b", anchor="w").pack(side="left")

    curr_arb = system_config.get("pump_arbitration_mode", "sequential").upper()
    lbl_arb = tk.Label(arb_row, text=curr_arb, font=("Helvetica", 14, "bold"), fg="#ea580c", bg="#f1f5f9", width=18, relief="sunken", bd=1)
    lbl_arb.pack(side="left", padx=10)

    def _toggle_arb():
        curr = system_config.get("pump_arbitration_mode", "sequential").lower()
        new_arb = "parallel" if curr == "sequential" else "sequential"
        system_config["pump_arbitration_mode"] = new_arb
        lbl_arb.config(text=new_arb.upper())
        save_config()

    tk.Button(arb_row, text="TOGGLE MODE", font=BTN_FONT_INLINE, bg="#cbd5e1", width=10, height=1, pady=3, command=_toggle_arb).pack(side="left", padx=5)

    def save_and_close_modal():
        nonlocal temp_h, temp_m, temp_s
        h_norm, m_norm, s_norm = normalize_upload_values(temp_h, temp_m, temp_s)
        total_sec = (h_norm * 3600) + (m_norm * 60) + s_norm

        system_config["upload_hours"] = h_norm
        system_config["upload_mins"] = m_norm
        system_config["upload_secs"] = s_norm
        system_config["upload_frequency_min"] = round(total_sec / 60.0, 4) if total_sec > 0 else 0
        system_config["upload_frequency_sec"] = total_sec if total_sec > 0 else 1

        save_config()
        broadcast_current_state()
        set_ui_toast(" System Settings Saved Successfully", duration_sec=3)
        modal.destroy()

    tk.Button(m_main, text="SAVE & CLOSE", font=BTN_FONT_MAIN, bg="#1565c0", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=save_and_close_modal).pack(pady=10)

def open_alarm_history_modal():
    modal = tk.Toplevel(root)
    modal.configure(bg="white")
    make_modal_fullscreen(modal)
    add_logo(modal)
    add_top_left_exit(modal)
    add_bottom_right_clock(modal)

    m_main = tk.Frame(modal, bg="white")
    m_main.pack(fill="both", expand=True, pady=(45, 20), padx=25)

    tk.Label(m_main, text="ALARM LOGS & EVENT HISTORY", font=big, fg="#c62828", bg="white").pack(pady=4)

    txt_logs = tk.Text(m_main, font=("Courier", 10), bg="#f8fafc", bd=1, relief="solid", highlightbackground="#cbd5e1", height=18)
    txt_logs.pack(fill="both", expand=True, pady=8)

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
    tk.Button(m_main, text="CLOSE", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=14, height=1, cursor="hand2", command=modal.destroy).pack(pady=6)

def open_comm_health_modal():
    modal = tk.Toplevel(root)
    modal.configure(bg="white")
    make_modal_fullscreen(modal)
    add_logo(modal)
    add_top_left_exit(modal)
    add_bottom_right_clock(modal)

    m_main = tk.Frame(modal, bg="white")
    m_main.pack(fill="both", expand=True, pady=(45, 20), padx=25)

    tk.Label(m_main, text="COMMUNICATION & DEVICE HEALTH DIAGNOSTICS", font=big, fg="#0d9488", bg="white").pack(pady=4)

    cards_f = tk.Frame(m_main, bg="white")
    cards_f.pack(fill="both", expand=True, pady=8)

    left_card = tk.LabelFrame(cards_f, text="RS485 SENSOR & RELAY HARDWARE PORTS", font=("Helvetica", 10, "bold"), fg="#1565c0", bg="white", padx=10, pady=6)
    left_card.pack(side="left", fill="both", expand=True, padx=6)

    for ph, port in SENSOR_MAP.items():
        exists = os.path.exists(port)
        rf = tk.Frame(left_card, bg="white"); rf.pack(fill="x", pady=2)
        tk.Label(rf, text=f"{ph} Temp/Humi Port:", font=("Helvetica", 9, "bold"), width=18, anchor="w", bg="white", fg="#1e293b").pack(side="left")
        tk.Label(rf, text=f"{'CONNECTED' if exists else 'NOT DETECTED'}", font=("Helvetica", 9, "bold"), fg="#16a34a" if exists else "#dc2626", bg="white").pack(side="left")

    r_port = system_config.get("relay_port", RELAY_PORT_FIXED)
    r_exists = os.path.exists(r_port)
    rf_rel = tk.Frame(left_card, bg="white"); rf_rel.pack(fill="x", pady=(4, 2))
    tk.Label(rf_rel, text="32-Ch Relay Port:", font=("Helvetica", 9, "bold"), width=18, anchor="w", bg="white", fg="#1e293b").pack(side="left")
    tk.Label(rf_rel, text=f"{'CONNECTED (ID ' + str(working_relay_id or 'Scan') + ')' if r_exists else 'NOT DETECTED'}", font=("Helvetica", 9, "bold"), fg="#16a34a" if r_exists else "#dc2626", bg="white").pack(side="left")

    right_card = tk.LabelFrame(cards_f, text="NETWORK, CLOUD & PERSISTENCE SUBSYSTEMS", font=("Helvetica", 10, "bold"), fg="#1565c0", bg="white", padx=10, pady=6)
    right_card.pack(side="right", fill="both", expand=True, padx=6)

    net_items = [
        ("Cloud Broker Link:", f"Mosquitto VPS ({CONTROL_BROKER})", "ONLINE" if is_mqtt_connected else "DISCONNECTED", "#16a34a" if is_mqtt_connected else "#dc2626"),
        ("MQTT Client ID:", DEVICE_NAME, "ACTIVE", "#1565c0"),
        ("Bluetooth Serial SPP:", f"Inhydro_{DEVICE_NAME} (Ch 1)", "LISTENING", "#16a34a"),
        ("System Local IP:", get_system_ip_summary().split()[0] if get_system_ip_summary() else "N/A", "ACTIVE", "#0284c7"),
        ("Pump Arbitration Mode:", system_config.get("pump_arbitration_mode", "sequential").upper(), "ACTIVE", "#ea580c")
    ]
    for lbl_n, val_n, st_n, col_n in net_items:
        rf = tk.Frame(right_card, bg="white"); rf.pack(fill="x", pady=3)
        tk.Label(rf, text=lbl_n, font=("Helvetica", 9, "bold"), width=20, anchor="w", bg="white", fg="#1e293b").pack(side="left")
        tk.Label(rf, text=val_n, font=("Helvetica", 9), anchor="w", bg="white", fg="#475569").pack(side="left", padx=4)
        tk.Label(rf, text=st_n, font=("Helvetica", 9, "bold"), fg=col_n, bg="white").pack(side="right")

    tk.Button(m_main, text="CLOSE", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=14, height=1, cursor="hand2", command=modal.destroy).pack(pady=6)

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

    lbl_head = tk.Label(m_main, text="HISTORICAL TRENDS & SENSOR ANALYTICS", font=big, fg="#7c3aed", bg="white")
    lbl_head.pack(pady=(0, 4))

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

    chart_canvas = tk.Canvas(m_main, bg="#0f172a", highlightthickness=1, highlightbackground="#334155", height=300)
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
        if cw < 200 or ch < 100: cw, ch = 960, 300

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
            chart_canvas.create_text(cw // 2, ch // 2, text=f"No trend telemetry points recorded yet for {disp_ph} ({m_dict.get(current_metric)})\nWaiting for periodic telemetry stream...", fill="#94a3b8", font=("Helvetica", 13, "bold"), justify="center")
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

        left_m = 60
        right_m = 25
        top_m = 25
        bot_m = 35
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
                chart_canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="#ffffff", outline=m_color, width=2)
                chart_canvas.create_text(cx, cy - 12, text=f"{valid_pts[-1][1]:.1f} {unit_str}", fill="#ffffff", font=("Helvetica", 9, "bold"), anchor="s")
            elif n <= 30:
                chart_canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=m_color, outline="")

    select_ph(current_ph)
    select_metric(current_metric)

    btn_bar = tk.Frame(m_main, bg="white")
    btn_bar.pack(side="bottom", pady=4)
    tk.Button(btn_bar, text="REFRESH GRAPH", font=BTN_FONT_MAIN, bg="#7c3aed", fg="white", width=16, height=1, cursor="hand2", command=redraw_chart).pack(side="left", padx=8)
    tk.Button(btn_bar, text="CLOSE", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=14, height=1, cursor="hand2", command=trends_modal.destroy).pack(side="left", padx=8)

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

    tk.Label(m_main, text="IRRIGATION & FOGGING AUTOMATION SCHEDULE", font=big, fg="#059669", bg="white").pack(pady=(0, 6))

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
        tk.Label(hdr, text="EQUIPMENT", font=("Helvetica", 10, "bold"), fg="#1e293b", bg="#f1f5f9", width=18, anchor="center").pack(side="left", padx=4)
        tk.Label(hdr, text="DURATION", font=("Helvetica", 10, "bold"), fg="#1e293b", bg="#f1f5f9", width=16, anchor="center").pack(side="left", padx=4)
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

keypad_modal = None

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

def show_confirm_dialog(title, message, on_confirm, on_cancel=None, parent=None, confirm_text="✔ OK / SAVE", cancel_text="✖ CANCEL"):
    win_parent = parent if parent is not None else root
    overlay = tk.Toplevel(win_parent)
    overlay.configure(bg="#ffffff")
    overlay.transient(win_parent)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    overlay.geometry(f"{sw}x{sh}+0+0")
    try: overlay.overrideredirect(True)
    except Exception: pass
    try: overlay.attributes("-fullscreen", True)
    except Exception: pass
    overlay.grab_set()
    overlay.lift()

    card_border = tk.Frame(overlay, bg="#94a3b8", bd=2, relief="solid")
    card_border.place(relx=0.5, rely=0.5, anchor="center")

    card = tk.Frame(card_border, bg="#f1f5f9", padx=42, pady=30)
    card.pack()

    tk.Label(card, text="⚠", font=("Helvetica", 32, "bold"), fg="#b45309", bg="#f1f5f9").pack(pady=(0, 6))
    tk.Label(card, text=title.upper(), font=("Helvetica", 14, "bold"), fg="#0f172a", bg="#f1f5f9").pack(pady=(0, 8))
    tk.Label(card, text=message, font=("Helvetica", 12, "bold"), fg="#334155", bg="#f1f5f9", wraplength=480, justify="center").pack(pady=(0, 24))

    btns = tk.Frame(card, bg="#f1f5f9")
    btns.pack()

    def _yes():
        overlay.destroy()
        if on_confirm: on_confirm()

    def _no():
        overlay.destroy()
        if on_cancel: on_cancel()

    tk.Button(btns, text=confirm_text, font=("Helvetica", 12, "bold"), bg="#2e7d32" if ("OK" in confirm_text or "YES" in confirm_text or "SAVE" in confirm_text) else "#1e293b", fg="#ffffff",
              activebackground="#15803d", activeforeground="#ffffff", relief="flat", bd=0, padx=22, pady=10, cursor="hand2", command=_yes).pack(side="left", padx=12)

    if cancel_text:
        tk.Button(btns, text=cancel_text, font=("Helvetica", 12, "bold"), bg="#64748b", fg="#ffffff",
                  activebackground="#475569", activeforeground="#ffffff", relief="flat", bd=0, padx=22, pady=10, cursor="hand2", command=_no).pack(side="left", padx=12)


def log_auth_event(skey_or_room, user_idx, user_name, status):
    try:
        log_dir = os.path.join(BASE_DIR, "local_logs")
        os.makedirs(log_dir, exist_ok=True)
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ts_str = datetime.datetime.now(ist_tz).isoformat()
        event = {
            "timestamp": ts_str,
            "room": skey_or_room,
            "user_index": user_idx,
            "user_name": user_name,
            "status": status
        }
        with open(os.path.join(log_dir, "auth_events.jsonl"), "a") as f:
            f.write(json.dumps(event) + "\n")
        print(f"[AUTH] Event logged: {event}")
    except Exception as e:
        print(f"Error logging auth event: {e}")

def check_pin_and_proceed(action_title, on_success):
    win = tk.Toplevel(root)
    win.title("Security Authentication")
    make_modal_fullscreen(win)

    def close_win():
        win.destroy()
        try: root.focus_force()
        except Exception: pass

    password_entered = ""
    selected_user = 1
    error_active = False
    show_password = False

    main_container = tk.Frame(win, bg="#ffffff")
    main_container.place(relx=0.5, rely=0.5, anchor="center")

    header_frame = tk.Frame(main_container, bg="#ffffff")
    header_frame.pack(fill="x", padx=10, pady=(6, 2))

    title_sub_frame = tk.Frame(header_frame, bg="#ffffff")
    title_sub_frame.pack(side="left")

    tk.Label(title_sub_frame, text="SECURITY LOCK", font=("Arial", 18, "bold"), fg="#1565c0", bg="#ffffff").pack(anchor="w")
    tk.Label(title_sub_frame, text=f"Select operator and enter authorization PIN to unlock {action_title}:", font=("Arial", 13, "bold"), fg="#64748b", bg="#ffffff").pack(anchor="w", pady=2)

    try:
        LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
        if os.path.exists(LOGO_PATH):
            logo_raw = Image.open(LOGO_PATH).resize((115, 38), Image.Resampling.LANCZOS)
            logo_img = ImageTk.PhotoImage(logo_raw)
            win.logo_img = logo_img
            lbl_logo = tk.Label(header_frame, image=logo_img, bg="#ffffff")
            lbl_logo.pack(side="right", padx=10)
    except Exception: pass

    # User Selection Layout (2 Operators)
    user_frame = tk.Frame(main_container, bg="#ffffff")
    user_frame.pack(pady=4)

    user_btns = []

    def show_error_in_display(msg):
        nonlocal error_active, password_entered
        password_entered = ""
        color = "#000000" if "4-8" in msg else "#dc2626"
        display_lbl.config(text=msg, fg=color, font=("Arial", 18, "bold"))
        error_active = True

    def rename_user_popup():
        nonlocal selected_user
        pop = tk.Toplevel(win)
        pop.title("Rename Operator")
        make_modal_fullscreen(pop)

        def close_pop():
            pop.destroy()
            try:
                win.focus_force()
                win.grab_set()
            except Exception: pass

        name_entered = system_config.get(f"USER {selected_user} Name", f"Operator {selected_user}")
        container = tk.Frame(pop, bg="#ffffff")
        container.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(container, text="RENAME OPERATOR", font=("Arial", 18, "bold"), fg="#1565c0", bg="#ffffff").pack(pady=4)
        tk.Label(container, text=f"Edit name for Operator {selected_user}:", font=("Arial", 13, "bold"), fg="#64748b", bg="#ffffff").pack(pady=2)

        display_lbl_rename = tk.Label(container, text=name_entered, font=("Arial", 22, "bold"), fg="#e65100", bg="#f1f5f9", width=22, relief="sunken", bd=2)
        display_lbl_rename.pack(pady=4)

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
        kb_frame.pack(pady=4)
        rows = [list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL:"), list("ZXCVBNM._ ")]
        for ri, row_k in enumerate(rows):
            for ci, ch in enumerate(row_k):
                lbl = ch if ch != ' ' else 'SPC'
                tk.Button(kb_frame, text=lbl, font=("Arial", 15, "bold"), width=5 if ch != ' ' else 7, height=1, bg="#f1f5f9", fg="#0f172a",
                          activebackground="#0284c7", activeforeground="white", relief="raised", bd=1, cursor="hand2", command=lambda x=ch: char_press(x)).grid(row=ri, column=ci, padx=3, pady=2)

        action_frame = tk.Frame(container, bg="#ffffff")
        action_frame.pack(fill="x", pady=8)
        tk.Button(action_frame, text="CANCEL", font=("Arial", 13, "bold"), bg="#64748b", fg="white", width=11, height=1, cursor="hand2", relief="raised", bd=1, command=close_pop).pack(side="left", padx=6)
        tk.Button(action_frame, text="CLEAR", font=("Arial", 13, "bold"), bg="#dc2626", fg="white", width=11, height=1, cursor="hand2", relief="raised", bd=1, command=char_clear).pack(side="left", padx=6)
        tk.Button(action_frame, text="BACK", font=("Arial", 13, "bold"), bg="#f97316", fg="white", width=11, height=1, cursor="hand2", relief="raised", bd=1, command=char_back).pack(side="left", padx=6)
        tk.Button(action_frame, text="SAVE", font=("Arial", 13, "bold"), bg="#2e7d32", fg="white", width=11, height=1, cursor="hand2", relief="raised", bd=1, command=char_save).pack(side="right", padx=6)

    def change_pin_popup():
        nonlocal selected_user
        pop = tk.Toplevel(win)
        pop.title("Change Operator PIN")
        make_modal_fullscreen(pop)

        def close_pop():
            pop.destroy()
            try:
                win.focus_force()
                win.grab_set()
            except Exception: pass

        step = 1
        old_pin = ""; new_pin = ""; confirm_pin = ""; input_value = ""
        show_pin = False; pop_error_active = False

        container = tk.Frame(pop, bg="#ffffff")
        container.place(relx=0.5, rely=0.5, anchor="center")

        step_lbl = tk.Label(container, text="STEP 1: ENTER OLD PIN", font=("Arial", 16, "bold"), fg="#1565c0", bg="#ffffff")
        step_lbl.pack(pady=4)

        display_frame = tk.Frame(container, bg="#ffffff")
        display_frame.pack(pady=4)

        display_lbl_pin = tk.Label(display_frame, text="", font=("Arial", 28, "bold"), fg="#2e7d32", bg="#f1f5f9", width=12, relief="sunken", bd=2, anchor="center")
        display_lbl_pin.pack(side="left", padx=5)

        def show_pop_err(msg):
            nonlocal pop_error_active, input_value
            input_value = ""
            color = "#000000" if "4-8" in msg else "#dc2626"
            display_lbl_pin.config(text=msg, fg=color, font=("Arial", 18, "bold"))
            pop_error_active = True

        def update_pin_display():
            if pop_error_active: return
            display_lbl_pin.config(fg="#2e7d32", font=("Arial", 28, "bold"))
            display_lbl_pin.config(text=input_value if show_pin else "●" * len(input_value))

        def toggle_pin_show():
            nonlocal show_pin
            show_pin = not show_pin
            eye_btn_p.config(text="HIDE" if show_pin else "SHOW", bg="#0284c7" if show_pin else "#64748b", fg="white")
            update_pin_display()

        eye_btn_p = tk.Button(display_frame, text="SHOW", font=("Arial", 13, "bold"), width=7, bg="#64748b", fg="white", bd=1, relief="raised", cursor="hand2", command=toggle_pin_show)
        eye_btn_p.pack(side="left", padx=5)

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
            nonlocal step, old_pin, new_pin, confirm_pin, input_value
            if pop_error_active: return
            correct_old = str(system_config.get(f"USER {selected_user} PASSWORD", f"{selected_user}{selected_user}{selected_user}{selected_user}"))
            master_pin = str(system_config.get("system_password", "1234")).strip()

            if step == 1:
                if input_value != correct_old and input_value != master_pin:
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
                confirm_pin = input_value
                system_config[f"USER {selected_user} PASSWORD"] = new_pin
                save_config()
                close_pop()

        kp_frame_p = tk.Frame(container, bg="#ffffff")
        kp_frame_p.pack(pady=4)
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
            tk.Button(kp_frame_p, text=text, font=("Arial", 22, "bold"), width=8, height=1, bg=bg, fg=fg, bd=1, relief="raised", cursor="hand2", command=cmd).grid(row=r, column=c, padx=6, pady=3)

        action_frame_p = tk.Frame(container, bg="#ffffff")
        action_frame_p.pack(fill="x", pady=8)
        tk.Button(action_frame_p, text="CANCEL", font=("Arial", 14, "bold"), bg="#64748b", fg="white", width=14, height=1, cursor="hand2", relief="raised", bd=1, command=close_pop).pack(side="left", padx=10)
        tk.Button(action_frame_p, text="SAVE / NEXT", font=("Arial", 14, "bold"), bg="#2e7d32", fg="white", width=14, height=1, cursor="hand2", relief="raised", bd=1, command=num_confirm).pack(side="right", padx=10)

    def select_user(idx):
        nonlocal selected_user
        selected_user = idx
        for i, btn in enumerate(user_btns, 1):
            if i == idx:
                btn.config(bg="#0284c7", fg="white", relief="sunken")
            else:
                btn.config(bg="#cbd5e1", fg="#0f172a", relief="raised")
        kp_clear()

    # User 1 button
    u1_name = system_config.get("USER 1 Name", "Operator 1")
    btn_u1 = tk.Button(user_frame, text=u1_name, font=("Arial", 15, "bold"), width=16, height=1, bd=1, relief="raised", cursor="hand2", command=lambda: select_user(1))
    btn_u1.pack(side="left", padx=8)
    user_btns.append(btn_u1)

    # User 2 button
    u2_name = system_config.get("USER 2 Name", "Operator 2")
    btn_u2 = tk.Button(user_frame, text=u2_name, font=("Arial", 15, "bold"), width=16, height=1, bd=1, relief="raised", cursor="hand2", command=lambda: select_user(2))
    btn_u2.pack(side="left", padx=8)
    user_btns.append(btn_u2)

    # Operator Sub-actions
    ops_frame = tk.Frame(main_container, bg="#ffffff")
    ops_frame.pack(pady=3)
    tk.Button(ops_frame, text="RENAME OPERATOR", font=("Arial", 12, "bold"), bg="#64748b", fg="white", width=18, height=1, bd=1, relief="raised", cursor="hand2", command=rename_user_popup).pack(side="left", padx=6)
    tk.Button(ops_frame, text="CHANGE PIN", font=("Arial", 12, "bold"), bg="#64748b", fg="white", width=16, height=1, bd=1, relief="raised", cursor="hand2", command=change_pin_popup).pack(side="left", padx=6)

    # Display entry for password
    display_container = tk.Frame(main_container, bg="#ffffff")
    display_container.pack(pady=4)

    display_lbl = tk.Label(display_container, text="", font=("Arial", 28, "bold"), fg="#2e7d32", bg="#f1f5f9", width=12, relief="sunken", bd=2, anchor="center")
    display_lbl.pack(side="left", padx=5)

    def update_display():
        if error_active: return
        display_lbl.config(fg="#2e7d32", font=("Arial", 28, "bold"))
        display_lbl.config(text=password_entered if show_password else "●" * len(password_entered))

    def toggle_show_password():
        nonlocal show_password
        show_password = not show_password
        eye_btn.config(text="HIDE" if show_password else "SHOW", bg="#0284c7" if show_password else "#64748b", fg="white")
        update_display()

    eye_btn = tk.Button(display_container, text="SHOW", font=("Arial", 13, "bold"), width=7, bg="#64748b", fg="white", bd=1, relief="raised", cursor="hand2", command=toggle_show_password)
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
            log_auth_event(action_title, selected_user, user_name, "SUCCESS")
            close_win()
            on_success()
        else:
            log_auth_event(action_title, selected_user, user_name, "FAILED")
            show_error_in_display("WRONG PIN")

    kp_frame = tk.Frame(main_container, bg="#ffffff")
    kp_frame.pack(pady=4)
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
        tk.Button(kp_frame, text=text, font=("Arial", 22, "bold"), width=8, height=1, bg=bg, fg=fg, bd=1, relief="raised", cursor="hand2", command=cmd).grid(row=r, column=c, padx=6, pady=3)

    action_frame = tk.Frame(main_container, bg="#ffffff")
    action_frame.pack(fill="x", side="bottom", pady=6, padx=10)
    tk.Button(action_frame, text="CANCEL", font=("Arial", 14, "bold"), bg="#64748b", fg="white", width=15, height=1, bd=1, relief="raised", cursor="hand2", command=close_win).pack(side="left", padx=10, anchor="s")
    tk.Button(action_frame, text="AUTHENTICATE", font=("Arial", 14, "bold"), bg="#2e7d32", fg="white", width=16, height=1, bd=1, relief="raised", cursor="hand2", command=kp_confirm).pack(side="right", padx=10, anchor="s")

    select_user(1)

def open_almora_keypad(title_text, initial_value, callback_on_confirm, is_alphanumeric=False, mode=None):
    global keypad_modal
    if keypad_modal and keypad_modal.winfo_exists():
        try: keypad_modal.destroy()
        except Exception: pass

    if mode is None:
        if is_alphanumeric: mode = "alphanumeric"
        elif "Time" in title_text or "time" in title_text: mode = "time"
        elif "Date" in title_text or "date" in title_text: mode = "calendar"
        else: mode = "numeric"

    keypad_modal = tk.Toplevel(root)
    make_modal_fullscreen(keypad_modal)

    kp_main = tk.Frame(keypad_modal, bg="white")
    kp_main.pack(fill="both", expand=True, pady=(15, 6))

    add_logo(keypad_modal)
    add_top_left_exit(keypad_modal)
    add_bottom_right_clock(keypad_modal)

    entered_val = str(initial_value)

    lbl_modal_title = tk.Label(kp_main, text=title_text, font=("Helvetica", 18, "bold"), fg="#1565c0", bg="white")
    lbl_modal_title.pack(pady=(2, 2))

    lbl_modal_disp = tk.Label(kp_main, text=entered_val, font=("Arial", 26, "bold"), fg="#0f172a", bg="#f1f5f9", width=22, relief="sunken", bd=2)
    lbl_modal_disp.pack(pady=3)

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
    kp_buttons_frame.pack(pady=3)

    if mode == "numeric":
        num_grid = [
            ('7', 0, 0), ('8', 0, 1), ('9', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('1', 2, 0), ('2', 2, 1), ('3', 2, 2),
            ('-', 3, 0), ('0', 3, 1), ('.', 3, 2)
        ]
        for t, r, c in num_grid:
            tk.Button(kp_buttons_frame, text=t, font=("Arial", 22, "bold"), width=8, height=1, bg="#f1f5f9", fg="#0f172a",
                      activebackground="#0284c7", activeforeground="white", relief="raised", bd=1, cursor="hand2",
                      command=lambda x=t: kp_press(x)).grid(row=r, column=c, padx=8, pady=3)

    elif mode == "time":
        shortcut_f = tk.Frame(kp_buttons_frame, bg="white")
        shortcut_f.grid(row=0, column=0, columnspan=4, pady=(0, 4))
        time_shortcuts = ["06:00 AM", "08:00 AM", "12:00 PM", "05:00 PM", "08:00 PM", "12:00 AM"]
        for ts in time_shortcuts:
            tk.Button(shortcut_f, text=ts, font=("Helvetica", 12, "bold"), bg="#e0f2fe", fg="#0369a1", relief="flat", bd=0, padx=10, pady=5, cursor="hand2",
                      command=lambda x=ts: kp_set_val(x)).pack(side="left", padx=3)

        time_grid = [
            ('7', 1, 0), ('8', 1, 1), ('9', 1, 2), (':', 1, 3),
            ('4', 2, 0), ('5', 2, 1), ('6', 2, 2), ('AM', 2, 3),
            ('1', 3, 0), ('2', 3, 1), ('3', 3, 2), ('PM', 3, 3),
            ('0', 4, 0), ('00', 4, 1), (' ', 4, 2), ('CLR', 4, 3)
        ]
        for t, r, c in time_grid:
            if t == 'CLR':
                btn_b = tk.Button(kp_buttons_frame, text="CLR", font=("Arial", 16, "bold"), bg="#dc2626", fg="white", width=7, height=1, relief="raised", bd=1, cursor="hand2", command=kp_clear)
            elif t in ['AM', 'PM']:
                btn_b = tk.Button(kp_buttons_frame, text=t, font=("Arial", 16, "bold"), bg="#0284c7", fg="white", width=7, height=1, relief="raised", bd=1, cursor="hand2",
                                  command=lambda x=t: (kp_press(' ' + x) if 'AM' not in entered_val and 'PM' not in entered_val else None))
            elif t == ' ':
                btn_b = tk.Button(kp_buttons_frame, text="SPACE", font=("Arial", 12, "bold"), bg="#cbd5e1", fg="#1e293b", width=7, height=1, relief="raised", bd=1, cursor="hand2", command=lambda: kp_press(' '))
            else:
                btn_b = tk.Button(kp_buttons_frame, text=t, font=("Arial", 18, "bold"), bg="#f1f5f9", fg="#0f172a", width=7, height=1, relief="raised", bd=1, cursor="hand2", command=lambda x=t: kp_press(x))
            btn_b.grid(row=r, column=c, padx=6, pady=3)

    elif mode == "calendar":
        shortcut_f = tk.Frame(kp_buttons_frame, bg="white")
        shortcut_f.grid(row=0, column=0, columnspan=3, pady=(0, 4))
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        today_dt = datetime.datetime.now(ist_tz)
        d_today = today_dt.strftime("%d-%m-%Y")
        d_7 = (today_dt + datetime.timedelta(days=7)).strftime("%d-%m-%Y")
        d_14 = (today_dt + datetime.timedelta(days=14)).strftime("%d-%m-%Y")
        d_30 = (today_dt + datetime.timedelta(days=30)).strftime("%d-%m-%Y")
        date_shortcuts = [("TODAY", d_today), ("+7 DAYS", d_7), ("+14 DAYS", d_14), ("+30 DAYS", d_30)]
        for lbl, val in date_shortcuts:
            tk.Button(shortcut_f, text=f"{lbl}", font=("Helvetica", 12, "bold"), bg="#dcfce7", fg="#15803d", relief="flat", bd=0, padx=10, pady=5, cursor="hand2",
                      command=lambda x=val: kp_set_val(x)).pack(side="left", padx=3)

        date_grid = [
            ('7', 1, 0), ('8', 1, 1), ('9', 1, 2),
            ('4', 2, 0), ('5', 2, 1), ('6', 2, 2),
            ('1', 3, 0), ('2', 3, 1), ('3', 3, 2),
            ('-', 4, 0), ('0', 4, 1), (':', 4, 2)
        ]
        for t, r, c in date_grid:
            tk.Button(kp_buttons_frame, text=t, font=("Arial", 18, "bold"), width=8, height=1, bg="#f1f5f9", fg="#0f172a",
                      activebackground="#0284c7", activeforeground="white", relief="raised", bd=1, cursor="hand2",
                      command=lambda x=t: kp_press(x)).grid(row=r, column=c, padx=8, pady=3)

    else:
        rows = [list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL:"), list("ZXCVBNM._ ")]
        for ri, row_k in enumerate(rows):
            r_f = tk.Frame(kp_buttons_frame, bg="white")
            r_f.pack(pady=2)
            for ch in row_k:
                lbl = ch if ch != ' ' else 'SPC'
                tk.Button(r_f, text=lbl, font=("Arial", 15, "bold"), width=5 if ch != ' ' else 7, height=1, bg="#f1f5f9", fg="#0f172a",
                          activebackground="#0284c7", activeforeground="white", relief="raised", bd=1, cursor="hand2",
                          command=lambda x=ch: kp_press(x)).pack(side="left", padx=3)

    kp_actions_frame = tk.Frame(kp_main, bg="white")
    kp_actions_frame.pack(pady=6)
    tk.Button(kp_actions_frame, text="CANCEL", font=("Arial", 14, "bold"), bg="#64748b", fg="white", width=12, height=1, cursor="hand2", relief="raised", bd=1, command=kp_cancel).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CLEAR", font=("Arial", 14, "bold"), bg="#dc2626", fg="white", width=12, height=1, cursor="hand2", relief="raised", bd=1, command=kp_clear).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="BACK", font=("Arial", 14, "bold"), bg="#f97316", fg="white", width=12, height=1, cursor="hand2", relief="raised", bd=1, command=kp_back).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CONFIRM", font=("Arial", 14, "bold"), bg="#2e7d32", fg="white", width=14, height=1, cursor="hand2", relief="raised", bd=1, command=kp_confirm).pack(side="left", padx=6)

def open_upload_frequency_keypad(init_h, init_m, init_s, callback_on_confirm, parent_win=None):
    kp_win = tk.Toplevel(parent_win if parent_win else root)
    make_modal_fullscreen(kp_win)

    add_logo(kp_win)
    add_top_left_exit(kp_win)
    add_bottom_right_clock(kp_win)

    kp_main = tk.Frame(kp_win, bg="white")
    kp_main.pack(fill="both", expand=True, pady=(25, 8))

    tk.Label(kp_main, text="CLOUD UPLOAD FREQUENCY", font=("Helvetica", 16, "bold"), fg="#1565c0", bg="white").pack(pady=(0, 4))

    cur_h = int(init_h)
    cur_m = int(init_m)
    cur_s = int(init_s)

    active_col = 'M'
    active_str = str(cur_m)

    boxes_frame = tk.Frame(kp_main, bg="white")
    boxes_frame.pack(anchor="center", pady=2)

    # Box 1: HOURS
    card_h = tk.Frame(boxes_frame, bg="#f8fafc", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=10, pady=4, cursor="hand2")
    card_h.pack(side="left", padx=8)
    lbl_h_title = tk.Label(card_h, text="HOURS (HH)", font=("Helvetica", 10, "bold"), fg="#475569", bg="#f8fafc")
    lbl_h_title.pack()
    lbl_h_box = tk.Label(card_h, text=f"{cur_h:02d} hrs", font=("Arial", 16, "bold"), fg="#1565c0", bg="#ffffff", width=7, relief="sunken", bd=1)
    lbl_h_box.pack(pady=2)
    lbl_h_badge = tk.Label(card_h, text="TAP TO EDIT", font=("Helvetica", 8, "bold"), fg="#94a3b8", bg="#f8fafc")
    lbl_h_badge.pack()

    # Box 2: MINUTES
    card_m = tk.Frame(boxes_frame, bg="#eff6ff", bd=1, relief="solid", highlightbackground="#0284c7", padx=10, pady=4, cursor="hand2")
    card_m.pack(side="left", padx=8)
    lbl_m_title = tk.Label(card_m, text="MINUTES (MM)", font=("Helvetica", 10, "bold"), fg="#0284c7", bg="#eff6ff")
    lbl_m_title.pack()
    lbl_m_box = tk.Label(card_m, text=f"{cur_m:02d} min", font=("Arial", 16, "bold"), fg="#1565c0", bg="#ffffff", width=7, relief="sunken", bd=1)
    lbl_m_box.pack(pady=2)
    lbl_m_badge = tk.Label(card_m, text="● EDITING ●", font=("Helvetica", 8, "bold"), fg="#0284c7", bg="#eff6ff")
    lbl_m_badge.pack()

    # Box 3: SECONDS
    card_s = tk.Frame(boxes_frame, bg="#f8fafc", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=10, pady=4, cursor="hand2")
    card_s.pack(side="left", padx=8)
    lbl_s_title = tk.Label(card_s, text="SECONDS (SS)", font=("Helvetica", 10, "bold"), fg="#475569", bg="#f8fafc")
    lbl_s_title.pack()
    lbl_s_box = tk.Label(card_s, text=f"{cur_s:02d} sec", font=("Arial", 16, "bold"), fg="#1565c0", bg="#ffffff", width=7, relief="sunken", bd=1)
    lbl_s_box.pack(pady=2)
    lbl_s_badge = tk.Label(card_s, text="TAP TO EDIT", font=("Helvetica", 8, "bold"), fg="#94a3b8", bg="#f8fafc")
    lbl_s_badge.pack()

    lbl_summary = tk.Label(
        kp_main,
        text=f"Total Interval: {format_upload_hms_display(cur_h, cur_m, cur_s)}",
        font=("Helvetica", 12, "bold"),
        fg="#0f766e",
        bg="white"
    )
    lbl_summary.pack(pady=(2, 3))

    def update_boxes_ui():
        lbl_h_box.config(text=f"{cur_h:02d} hrs" if active_col != 'H' else f"{active_str} hrs")
        lbl_m_box.config(text=f"{cur_m:02d} min" if active_col != 'M' else f"{active_str} min")
        lbl_s_box.config(text=f"{cur_s:02d} sec" if active_col != 'S' else f"{active_str} sec")

        for col_name, card, title, badge in [('H', card_h, lbl_h_title, lbl_h_badge), ('M', card_m, lbl_m_title, lbl_m_badge), ('S', card_s, lbl_s_title, lbl_s_badge)]:
            if active_col == col_name:
                card.config(highlightbackground="#0284c7", highlightthickness=2, bg="#eff6ff")
                title.config(fg="#0284c7", bg="#eff6ff")
                badge.config(text="● EDITING ●", fg="#0284c7", bg="#eff6ff")
            else:
                card.config(highlightbackground="#cbd5e1", highlightthickness=1, bg="#f8fafc")
                title.config(fg="#475569", bg="#f8fafc")
                badge.config(text="TAP TO EDIT", fg="#94a3b8", bg="#f8fafc")

        try:
            val_in = int(active_str) if active_str else 0
        except Exception:
            val_in = 0
        p_h, p_m, p_s = cur_h, cur_m, cur_s
        if active_col == 'H': p_h = val_in
        elif active_col == 'M': p_m = val_in
        elif active_col == 'S': p_s = val_in
        norm_h, norm_m, norm_s = normalize_upload_values(p_h, p_m, p_s)
        lbl_summary.config(text=f"Total Interval: {format_upload_hms_display(norm_h, norm_m, norm_s)}")

    def commit_active_val():
        nonlocal cur_h, cur_m, cur_s, active_str
        try:
            val = int(active_str) if active_str else 0
        except Exception:
            val = 0
        if active_col == 'H': cur_h = val
        elif active_col == 'M': cur_m = val
        elif active_col == 'S': cur_s = val
        cur_h, cur_m, cur_s = normalize_upload_values(cur_h, cur_m, cur_s)

    def select_col(col_target):
        nonlocal active_col, active_str
        commit_active_val()
        active_col = col_target
        if active_col == 'H': active_str = str(cur_h)
        elif active_col == 'M': active_str = str(cur_m)
        elif active_col == 'S': active_str = str(cur_s)
        update_boxes_ui()

    for w in (card_h, lbl_h_title, lbl_h_box, lbl_h_badge):
        w.bind("<Button-1>", lambda e: select_col('H'))
    for w in (card_m, lbl_m_title, lbl_m_box, lbl_m_badge):
        w.bind("<Button-1>", lambda e: select_col('M'))
    for w in (card_s, lbl_s_title, lbl_s_box, lbl_s_badge):
        w.bind("<Button-1>", lambda e: select_col('S'))

    presets_container = tk.Frame(kp_main, bg="white")
    presets_container.pack(anchor="center", pady=2)

    row1 = tk.Frame(presets_container, bg="white")
    row1.pack(pady=1)
    row2 = tk.Frame(presets_container, bg="white")
    row2.pack(pady=1)

    row1_shortcuts = [
        ("1s Live", 0, 0, 1),
        ("10 Sec", 0, 0, 10),
        ("30 Sec", 0, 0, 30),
        ("1 Min", 0, 1, 0)
    ]
    row2_shortcuts = [
        ("5 Min", 0, 5, 0),
        ("15 Min", 0, 15, 0),
        ("1 Hour", 1, 0, 0),
        ("24 Hours", 24, 0, 0)
    ]

    def _apply_shortcut(sh, sm, ss):
        nonlocal cur_h, cur_m, cur_s, active_str
        cur_h, cur_m, cur_s = normalize_upload_values(sh, sm, ss)
        if active_col == 'H': active_str = str(cur_h)
        elif active_col == 'M': active_str = str(cur_m)
        elif active_col == 'S': active_str = str(cur_s)
        update_boxes_ui()

    for s_name, sh, sm, ss in row1_shortcuts:
        tk.Button(row1, text=s_name, font=("Helvetica", 10, "bold"), bg="#e0f2fe", fg="#0369a1",
                  activebackground="#0284c7", activeforeground="white", relief="flat", bd=0,
                  width=10, pady=3, cursor="hand2", command=lambda h=sh, m=sm, s=ss: _apply_shortcut(h, m, s)).pack(side="left", padx=3)

    for s_name, sh, sm, ss in row2_shortcuts:
        tk.Button(row2, text=s_name, font=("Helvetica", 10, "bold"), bg="#e0f2fe", fg="#0369a1",
                  activebackground="#0284c7", activeforeground="white", relief="flat", bd=0,
                  width=10, pady=3, cursor="hand2", command=lambda h=sh, m=sm, s=ss: _apply_shortcut(h, m, s)).pack(side="left", padx=3)

    kp_buttons_frame = tk.Frame(kp_main, bg="white")
    kp_buttons_frame.pack(pady=3)

    def kp_num(ch):
        nonlocal active_str
        if len(active_str) < 6:
            if active_str == "0":
                active_str = str(ch)
            else:
                active_str += str(ch)
            update_boxes_ui()

    def kp_del():
        nonlocal active_str
        active_str = active_str[:-1]
        if not active_str: active_str = "0"
        update_boxes_ui()

    def kp_clr():
        nonlocal active_str
        active_str = "0"
        update_boxes_ui()

    num_grid = [
        ('7', 0, 0), ('8', 0, 1), ('9', 0, 2),
        ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
        ('1', 2, 0), ('2', 2, 1), ('3', 2, 2),
        ('CLR', 3, 0), ('0', 3, 1), ('DEL', 3, 2)
    ]
    for t, r, c in num_grid:
        if t == 'CLR':
            btn = tk.Button(kp_buttons_frame, text="CLR", font=("Arial", 16, "bold"), bg="#dc2626", fg="white", width=8, height=1, relief="raised", bd=1, cursor="hand2", command=kp_clr)
        elif t == 'DEL':
            btn = tk.Button(kp_buttons_frame, text="DEL", font=("Arial", 16, "bold"), bg="#f97316", fg="white", width=8, height=1, relief="raised", bd=1, cursor="hand2", command=kp_del)
        else:
            btn = tk.Button(kp_buttons_frame, text=t, font=("Arial", 16, "bold"), width=8, height=1, bg="#f1f5f9", fg="#0f172a",
                            activebackground="#0284c7", activeforeground="white", relief="raised", bd=1, cursor="hand2",
                            command=lambda x=t: kp_num(x))
        btn.grid(row=r, column=c, padx=6, pady=3)

    kp_actions_frame = tk.Frame(kp_main, bg="white")
    kp_actions_frame.pack(pady=4)

    def on_apply_click():
        commit_active_val()
        h_norm, m_norm, s_norm = normalize_upload_values(cur_h, cur_m, cur_s)

        if h_norm >= 24:
            days = h_norm // 24
            rem_h = h_norm % 24
            day_str = f"{days} Day{'s' if days > 1 else ''}" + (f", {rem_h} Hour{'s' if rem_h > 0 else ''}" if rem_h > 0 else "")
            msg = f"The entered upload duration exceeds 24 Hours:\n\n{h_norm} Hours ({day_str}), {m_norm} Min, {s_norm} Sec.\n\nDo you want to proceed with this interval?"

            def _on_proceed():
                kp_win.destroy()
                callback_on_confirm(h_norm, m_norm, s_norm)

            show_confirm_dialog("Upload Duration > 24 Hours", msg, _on_proceed, parent=kp_win)
        else:
            kp_win.destroy()
            callback_on_confirm(h_norm, m_norm, s_norm)

    tk.Button(kp_actions_frame, text="SAVE & APPLY", font=("Helvetica", 12, "bold"), bg="#2e7d32", fg="white", width=14, height=1, cursor="hand2", relief="raised", bd=1, command=on_apply_click).pack(side="left", padx=10)
    tk.Button(kp_actions_frame, text="CANCEL", font=("Helvetica", 12, "bold"), bg="#64748b", fg="white", width=14, height=1, cursor="hand2", relief="raised", bd=1, command=kp_win.destroy).pack(side="left", padx=10)

    update_boxes_ui()


def update_ui():
    if not running: return
    try:
        grid_changed = False
        for skey in ALL_POLYHOUSES:
            if skey not in sensor_widgets:
                port = SENSOR_MAP[skey]
                disp_name = get_sensor_display_name(skey)

                card = tk.Frame(sensors_grid, bg="#1565c0", bd=4, relief="raised", cursor="hand2", padx=14, pady=6)

                lbl_name = tk.Label(card, text=disp_name, font=font.Font(family="Arial", size=18, weight="bold"), fg="white", bg="#1565c0", width=20, anchor="center")
                lbl_name.pack(anchor="center", pady=(1, 1))

                lbl_prog = tk.Label(card, text="[INITIALIZING]", font=font.Font(family="Arial", size=13, weight="bold"), fg="white", bg="#1565c0", width=20, anchor="center")
                lbl_prog.pack(anchor="center", pady=(1, 1))

                lbl_temp = tk.Label(card, text="Temp: --", font=font.Font(family="Arial", size=16, weight="bold"), fg="white", bg="#1565c0", width=20, anchor="center")
                lbl_temp.pack(anchor="center", pady=(1, 1))

                lbl_humi = tk.Label(card, text="Humi: --", font=font.Font(family="Arial", size=16, weight="bold"), fg="white", bg="#1565c0", width=20, anchor="center")
                lbl_humi.pack(anchor="center", pady=(1, 1))

                lbl_co2 = tk.Label(card, text="CO2: --", font=font.Font(family="Arial", size=14, weight="bold"), fg="white", bg="#1565c0", width=20, anchor="center")
                lbl_co2.pack(anchor="center", pady=(1, 1))

                lbl_warn = tk.Label(card, text="● NORMAL ●", font=font.Font(family="Arial", size=14, weight="bold"), fg="#bbf7d0", bg="#1565c0", width=20, anchor="center")
                lbl_warn.pack(anchor="center", pady=(2, 1))

                for w in [card, lbl_name, lbl_prog, lbl_temp, lbl_humi, lbl_co2, lbl_warn]:
                    w.bind("<Button-1>", lambda e, p=port: open_sensor_detail(p))

                sensor_widgets[skey] = {
                    'card': card,
                    'lbl_name': lbl_name,
                    'lbl_prog': lbl_prog,
                    'lbl_temp': lbl_temp,
                    'lbl_humi': lbl_humi,
                    'lbl_co2': lbl_co2,
                    'lbl_warn': lbl_warn
                }
                grid_changed = True

        if grid_changed: rebuild_grid()

        with sensor_data_lock: snap = dict(sensor_data)

        temp_alarm_offset = float(system_config.get('temp_alarm_offset', 5.0))
        humi_alarm_offset = float(system_config.get('humi_alarm_offset', 5.0))

        # 1. Update Polyhouse Tiles on Screen 02 Dashboard (Per-Room Representation & Warnings)
        for skey, port in SENSOR_MAP.items():
            if skey in sensor_widgets:
                w_dict = sensor_widgets[skey]
                card = w_dict['card']
                lbl_name = w_dict['lbl_name']
                lbl_prog = w_dict['lbl_prog']
                lbl_temp = w_dict['lbl_temp']
                lbl_humi = w_dict['lbl_humi']
                lbl_co2 = w_dict['lbl_co2']
                lbl_warn = w_dict['lbl_warn']

                d = snap.get(skey) or snap.get(port)
                disp_name = get_sensor_display_name(skey)
                sp_eval = get_active_setpoints(skey)

                prog_name = sp_eval.get('mode', 'AUTO').upper()
                lbl_name.config(text=disp_name)
                lbl_prog.config(text=f"[{prog_name}]")

                if is_room_paused(skey):
                    bg_color = "#1e3a8a"
                    lbl_name.config(text=disp_name, fg="white")
                    if d and d.get('status') == 'OK':
                        t, h = d['temp'], d['humi']
                        c_val = d.get('co2')
                        co2_str = f"{c_val:.1f} ppm" if (c_val is not None and c_val > 0) else "N/A"
                        lbl_prog.config(text="[MANUAL STOPPED]", fg="white")
                        lbl_temp.config(text=f"Temp: {t:.1f}°C", fg="white")
                        lbl_humi.config(text=f"Humi: {h:.1f}%", fg="white")
                        lbl_co2.config(text=f"CO2: {co2_str}", fg="white")
                        lbl_warn.config(text="● MANUAL STOPPED ●", fg="#ffffff")
                    elif d and d.get('status') == 'ERROR':
                        lbl_prog.config(text="", fg="white")
                        lbl_temp.config(text="", fg="white")
                        lbl_humi.config(text="SENSOR ERROR", fg="white")
                        lbl_co2.config(text="", fg="white")
                        lbl_warn.config(text="● MANUAL STOPPED ●", fg="#ffffff")
                    else:
                        lbl_prog.config(text="", fg="white")
                        lbl_temp.config(text="", fg="white")
                        lbl_humi.config(text="OFFLINE", fg="white")
                        lbl_co2.config(text="", fg="white")
                        lbl_warn.config(text="● MANUAL STOPPED ●", fg="#ffffff")

                elif d and d.get('status') == 'OK':
                    t, h = d['temp'], d['humi']
                    c_val = d.get('co2')
                    co2_str = f"{c_val:.1f} ppm" if (c_val is not None and c_val > 0) else "N/A"

                    lbl_name.config(text=disp_name, fg="white")
                    lbl_temp.config(text=f"Temp: {t:.1f}°C", fg="white")
                    lbl_humi.config(text=f"Humi: {h:.1f}%", fg="white")

                    if skey == "PH-06":
                        sp6 = get_setpoints("PH-06")
                        t_max_limit = float(sp6.get("temp_high_limit", 32.0))
                        h_max_limit = float(sp6.get("humi_high_limit", 85.0))
                        lbl_prog.config(text="[MONITORING ZONE]", fg="white")
                        lbl_co2.config(text=f"Limit: {t_max_limit:.1f}°C / {h_max_limit:.1f}%", fg="white")

                        room_warnings = []
                        if t >= t_max_limit:
                            room_warnings.append(f"⚠ HIGH TEMP ({t:.1f}°C)")
                        if h >= h_max_limit:
                            room_warnings.append(f"⚠ HIGH HUMI ({h:.1f}%)")

                        if room_warnings:
                            bg_color = "#c62828"
                            lbl_warn.config(text=room_warnings[0], fg="#fef08a")
                        else:
                            bg_color = "#2e7d32"
                            lbl_warn.config(text="● NORMAL ●", fg="#bbf7d0")
                    else:
                        lbl_prog.config(text=f"[{prog_name}]", fg="white")
                        lbl_co2.config(text=f"CO2: {co2_str}", fg="white")

                        t_min, t_max = sp_eval['T MIN'], sp_eval['T MAX']
                        h_min, h_max = sp_eval['H MIN'], sp_eval['H MAX']
                        t_target = sp_eval['target_temp']
                        h_target = sp_eval['target_humi']

                        room_warnings = []
                        if t >= (t_target + temp_alarm_offset):
                            room_warnings.append(f"⚠ HIGH TEMP ({t:.1f}°C)")
                        elif t <= (t_target - temp_alarm_offset):
                            room_warnings.append(f"⚠ LOW TEMP ({t:.1f}°C)")

                        if h >= (h_target + humi_alarm_offset):
                            room_warnings.append(f"⚠ HIGH HUMI ({h:.1f}%)")
                        elif h <= (h_target - humi_alarm_offset):
                            room_warnings.append(f"⚠ LOW HUMI ({h:.1f}%)")

                        if not room_warnings and not (t_min <= t <= t_max):
                            room_warnings.append("⚠ TEMP RANGE")
                        if not room_warnings and not (h_min <= h <= h_max):
                            room_warnings.append("⚠ HUMI RANGE")

                        if room_warnings:
                            bg_color = "#c62828"
                            lbl_warn.config(text=room_warnings[0], fg="#fef08a")
                        else:
                            bg_color = "#2e7d32"
                            lbl_warn.config(text="● NORMAL ●", fg="#bbf7d0")

                elif d and d.get('status') == 'ERROR':
                    bg_color = "#c62828"
                    lbl_name.config(text=disp_name, fg="white")
                    lbl_prog.config(text="")
                    lbl_temp.config(text="")
                    lbl_humi.config(text="SENSOR ERROR", fg="white")
                    lbl_co2.config(text="")
                    lbl_warn.config(text="⚠ SENSOR ERROR", fg="#fef08a")

                else:
                    bg_color = "#424242"
                    lbl_name.config(text=disp_name, fg="white")
                    lbl_prog.config(text="")
                    lbl_temp.config(text="")
                    lbl_humi.config(text="OFFLINE", fg="white")
                    lbl_co2.config(text="")
                    lbl_warn.config(text="● OFFLINE ●", fg="#ffffff")

                card.config(bg=bg_color)
                lbl_name.config(bg=bg_color)
                lbl_prog.config(bg=bg_color)
                lbl_temp.config(bg=bg_color)
                lbl_humi.config(bg=bg_color)
                lbl_co2.config(bg=bg_color)
                lbl_warn.config(bg=bg_color)

        # 2. Update Detailed Screen (frame_detail) if open
        if frame_detail.winfo_ismapped() and active_detail_skey:
            skey = active_detail_skey
            port = SENSOR_MAP.get(skey)
            d = snap.get(skey) or snap.get(port)
            update_detail_pause_button(skey)
            sp_eval = get_active_setpoints(skey)
            prog_name = sp_eval.get('mode', 'AUTO').upper()

            txt_detail_data.config(state="normal")
            txt_detail_data.delete("1.0", "end")

            room_disp = get_sensor_display_name(skey)
            txt_detail_data.insert("end", f"{room_disp}  [{prog_name}]\n", "black")

            # --- ROOM-SPECIFIC ACTIVE WARNINGS & ALARMS BANNER ---
            room_active_warnings = []
            if is_room_paused(skey):
                room_active_warnings.append("● MANUAL STOPPED (AUTOMATION PAUSED) ●")
            elif not d or d.get('status') == 'OFFLINE':
                room_active_warnings.append("⚠ SENSOR OFFLINE (NO SIGNAL)")
            elif d.get('status') == 'ERROR':
                room_active_warnings.append("⚠ SENSOR COMMUNICATION ERROR")
            else:
                t_val = d.get('temp')
                h_val = d.get('humi')
                if skey == "PH-06":
                    sp6 = get_setpoints("PH-06")
                    t_max_limit = float(sp6.get("temp_high_limit", 32.0))
                    h_max_limit = float(sp6.get("humi_high_limit", 85.0))
                    if t_val is not None and t_val >= t_max_limit:
                        room_active_warnings.append(f"⚠ CRITICAL HIGH TEMP ALARM ({t_val:.1f}°C >= {t_max_limit:.1f}°C)")
                    if h_val is not None and h_val >= h_max_limit:
                        room_active_warnings.append(f"⚠ CRITICAL HIGH HUMIDITY ALARM ({h_val:.1f}% >= {h_max_limit:.1f}%)")
                else:
                    t_min, t_max = sp_eval['T MIN'], sp_eval['T MAX']
                    h_min, h_max = sp_eval['H MIN'], sp_eval['H MAX']
                    t_target = sp_eval['target_temp']
                    h_target = sp_eval['target_humi']

                    if t_val is not None:
                        if t_val >= (t_target + temp_alarm_offset):
                            room_active_warnings.append(f"⚠ HIGH TEMP DEVIATION ({t_val:.1f}°C > {t_target + temp_alarm_offset:.1f}°C)")
                        elif t_val <= (t_target - temp_alarm_offset):
                            room_active_warnings.append(f"⚠ LOW TEMP DEVIATION ({t_val:.1f}°C < {t_target - temp_alarm_offset:.1f}°C)")
                        elif not (t_min <= t_val <= t_max):
                            room_active_warnings.append(f"⚠ TEMP OUT OF SETPOINT RANGE ({t_min:.1f}°C - {t_max:.1f}°C)")

                    if h_val is not None:
                        if h_val >= (h_target + humi_alarm_offset):
                            room_active_warnings.append(f"⚠ HIGH HUMIDITY DEVIATION ({h_val:.1f}% > {h_target + humi_alarm_offset:.1f}%)")
                        elif h_val <= (h_target - humi_alarm_offset):
                            room_active_warnings.append(f"⚠ LOW HUMIDITY DEVIATION ({h_val:.1f}% < {h_target - humi_alarm_offset:.1f}%)")
                        elif not (h_min <= h_val <= h_max):
                            room_active_warnings.append(f"⚠ HUMIDITY OUT OF SETPOINT RANGE ({h_min:.1f}% - {h_max:.1f}%)")

            if room_active_warnings:
                for w_msg in room_active_warnings:
                    txt_detail_data.insert("end", f"{w_msg}\n", "red")
                txt_detail_data.insert("end", "\n", "black")
            else:
                txt_detail_data.insert("end", "● STATUS: ALL PARAMETERS NORMAL ●\n\n", "green")

            if skey == "PH-06":
                sp6 = get_setpoints("PH-06")
                t_max_limit = float(sp6.get("temp_high_limit", 32.0))
                h_max_limit = float(sp6.get("humi_high_limit", 85.0))

                txt_detail_data.insert("end", "[DESIGNATED MONITORING ZONE - NO ACTUATORS]\n\n", "grey")
                if d and d.get('status') == 'OK':
                    txt_detail_data.insert("end", "TEMP: ", "black")
                    txt_detail_data.insert("end", f"{d['temp']:.1f} °C\n", "blue")
                    txt_detail_data.insert("end", "HUMI: ", "black")
                    txt_detail_data.insert("end", f"{d['humi']:.1f} %\n\n", "blue")
                else:
                    txt_detail_data.insert("end", "TEMP: ", "black")
                    txt_detail_data.insert("end", "OFFLINE\n", "red")
                    txt_detail_data.insert("end", "HUMI: ", "black")
                    txt_detail_data.insert("end", "OFFLINE\n\n", "red")

                txt_detail_data.insert("end", "CRITICAL ALARM HIGH TEMP LIMIT: ", "black")
                txt_detail_data.insert("end", f"{t_max_limit:.1f} °C\n", "blue")
                txt_detail_data.insert("end", "CRITICAL ALARM HIGH HUMI LIMIT: ", "black")
                txt_detail_data.insert("end", f"{h_max_limit:.1f} %\n\n", "blue")

            else:
                if d and d.get('status') == 'OK':
                    txt_detail_data.insert("end", "TEMP: ", "black")
                    txt_detail_data.insert("end", f"{d['temp']:.1f} °C\n", "blue")

                    txt_detail_data.insert("end", "HUMI: ", "black")
                    txt_detail_data.insert("end", f"{d['humi']:.1f} %\n", "blue")

                    c_val = d.get('co2')
                    txt_detail_data.insert("end", "CO2:  ", "black")
                    if c_val is not None and c_val > 0:
                        txt_detail_data.insert("end", f"{c_val:.1f} ppm\n", "blue")
                    else:
                        txt_detail_data.insert("end", "N/A\n", "red")

                    p_val = d.get('par')
                    txt_detail_data.insert("end", "PAR / PPFD: ", "black")
                    if p_val is not None and p_val > 0:
                        txt_detail_data.insert("end", f"{p_val:.1f} µmol/m²/s\n", "blue")
                    else:
                        txt_detail_data.insert("end", "N/A\n", "red")

                    d_val = d.get('dli')
                    txt_detail_data.insert("end", "DLI INTEGRAL: ", "black")
                    if d_val is not None and d_val > 0:
                        txt_detail_data.insert("end", f"{d_val:.2f} mol/m²/day\n\n", "blue")
                    else:
                        txt_detail_data.insert("end", "0.00 mol/m²/day\n\n", "grey")
                else:
                    txt_detail_data.insert("end", "TEMP: ", "black")
                    txt_detail_data.insert("end", "OFFLINE\n", "red")
                    txt_detail_data.insert("end", "HUMI: ", "black")
                    txt_detail_data.insert("end", "OFFLINE\n", "red")
                    txt_detail_data.insert("end", "CO2:  ", "black")
                    txt_detail_data.insert("end", "N/A\n", "red")
                    txt_detail_data.insert("end", "PAR / PPFD: ", "black")
                    txt_detail_data.insert("end", "N/A\n\n", "red")

                t_min, t_max = sp_eval['T MIN'], sp_eval['T MAX']
                h_min, h_max = sp_eval['H MIN'], sp_eval['H MAX']

                txt_detail_data.insert("end", "TEMP TARGET: ", "black")
                txt_detail_data.insert("end", f"{sp_eval['target_temp']:.1f} °C  |  ", "blue")
                txt_detail_data.insert("end", "MIN: ", "black")
                txt_detail_data.insert("end", f"{t_min:.1f} °C  |  ", "blue")
                txt_detail_data.insert("end", "MAX: ", "black")
                txt_detail_data.insert("end", f"{t_max:.1f} °C\n", "blue")

                txt_detail_data.insert("end", "HUMI TARGET: ", "black")
                txt_detail_data.insert("end", f"{sp_eval['target_humi']:.1f} %   |  ", "blue")
                txt_detail_data.insert("end", "MIN: ", "black")
                txt_detail_data.insert("end", f"{h_min:.1f} %  |  ", "blue")
                txt_detail_data.insert("end", "MAX: ", "black")
                txt_detail_data.insert("end", f"{h_max:.1f} %\n\n", "blue")

                ch_acf = RELAY_CH_ACF.get(skey)
                ch_spr = RELAY_CH_SPRINKLER.get(skey)
                ch_fog = RELAY_CH_FOGGER.get(skey)

                acf_s = "ON" if relay_states.get(ch_acf) else "OFF"
                spr_s = "ON" if relay_states.get(ch_spr) else "OFF"
                fog_s = "ON" if relay_states.get(ch_fog) else "OFF"
                pmp_s = "ON" if relay_states.get(RELAY_CH_COMMON_PUMP) else "OFF"

                if is_room_paused(skey):
                    txt_detail_data.insert("end", "ACF: ", "black")
                    txt_detail_data.insert("end", "STOPPED\n", "red")
                    txt_detail_data.insert("end", "Sprinkler: ", "black")
                    txt_detail_data.insert("end", "STOPPED\n", "red")
                    txt_detail_data.insert("end", "Fogger: ", "black")
                    txt_detail_data.insert("end", "STOPPED\n", "red")
                    txt_detail_data.insert("end", "Common Pump: ", "black")
                    txt_detail_data.insert("end", f"{pmp_s}\n", "green" if pmp_s == "ON" else "red")
                else:
                    txt_detail_data.insert("end", "ACF: ", "black")
                    txt_detail_data.insert("end", f"{acf_s}\n", "green" if acf_s == "ON" else "red")
                    txt_detail_data.insert("end", "Sprinkler: ", "black")
                    txt_detail_data.insert("end", f"{spr_s}\n", "green" if spr_s == "ON" else "red")
                    txt_detail_data.insert("end", "Fogger: ", "black")
                    txt_detail_data.insert("end", f"{fog_s}\n", "green" if fog_s == "ON" else "red")
                    txt_detail_data.insert("end", "Common Pump: ", "black")
                    txt_detail_data.insert("end", f"{pmp_s}\n", "green" if pmp_s == "ON" else "red")

            txt_detail_data.config(state="disabled")

    except Exception as e:
        print(f"UI Update Error: {e}")

    root.after(1000, update_ui)

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
