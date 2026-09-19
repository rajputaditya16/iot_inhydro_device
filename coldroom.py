import time
import minimalmodbus
import glob
import threading
import json
import os
import datetime
import copy
import tkinter as tk
from tkinter import font, ttk, messagebox
import sys
import socket
import subprocess
import paho.mqtt.client as mqtt
from PIL import Image, ImageTk
import uuid as _uuid
import re as _re
import fcntl

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                val = f.read().strip()
                if val: return val
        except: pass
    try:
        with open(ID_FILE, "w") as f:
            f.write("cold_room\n")
    except: pass
    return "cold_room" # Default hardware identifier matching web dashboard

DEVICE_NAME = get_device_id()
CONFIG_FILE = os.path.join(BASE_DIR, f"config_{DEVICE_NAME}.json")
SETPOINTS_FILE = os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}.json")
CROP_PROGRAMS_FILE = os.path.join(BASE_DIR, "crop_programs.json")
ALARM_LOG_FILE = os.path.join(BASE_DIR, "alarm_history.jsonl")

# MODBUS SETTINGS
SLAVE_ID = 1
BAUDRATE = 4800
RELAY_BAUD = 9600
DELAY_BETWEEN_PORTS = 0.2

# Hardware Dictionary: Maps Web MQTT IDs directly to physical USB paths for Temp/Humi
SENSOR_MAP = {
    "S1": "/dev/serial/by-path/pci-0000:00:14.0-usb-0:1:1.0-port0",
    "S2": "/dev/serial/by-path/pci-0000:00:14.0-usb-0:4:1.0-port0",
    "S3": "/dev/serial/by-path/usb_PLACEHOLDER_S3",
    "S4": "/dev/serial/by-path/usb_PLACEHOLDER_S4",
    "S5": "/dev/serial/by-path/usb_PLACEHOLDER_S5",
    "S6": "/dev/serial/by-path/usb_PLACEHOLDER_S6",
    "S7": "/dev/serial/by-path/usb_PLACEHOLDER_S7"
}

# Dedicated CO2 Sensor Hardware Ports per Room (S1 to S7)
CO2_SENSOR_MAP = {
    "S1": "/dev/serial/by-path/pci-0000:00:14.0-usb-0:1.5:1.0-port0",
    "S2": "/dev/serial/by-path/usb_PLACEHOLDER_CO2_S2",
    "S3": "/dev/serial/by-path/usb_PLACEHOLDER_CO2_S3",
    "S4": "/dev/serial/by-path/usb_PLACEHOLDER_CO2_S4",
    "S5": "/dev/serial/by-path/usb_PLACEHOLDER_CO2_S5",
    "S6": "/dev/serial/by-path/usb_PLACEHOLDER_CO2_S6",
    "S7": "/dev/serial/by-path/usb_PLACEHOLDER_CO2_S7"
}
RELAY_PORT_FIXED = "/dev/serial/by-path/usb-0:1:2:1:0-port0"
BUZZER_CHANNEL = 22   # Dedicated relay channel for 30s hardware buzzer (after room 1-7 relays)

POSSIBLE_RELAY_IDS = [255, 1, 2, 0, 3]  
working_relay_id = None

# SYSTEM STATE
system_config = {
    'relay_port': RELAY_PORT_FIXED,
    'upload_hours': 0,
    'upload_mins': 0,
    'upload_secs': 0,
    'upload_frequency_min': 0,
    'upload_frequency_sec': 1,
    'temp_alarm_offset': 5.0,
    'humi_alarm_offset': 5.0,
    'room_paused': {}
}
sensor_data = {}
sensor_setpoints = {}
crop_programs = {}
sensor_data_lock = threading.Lock()
running = True
room_paused_states = {skey: False for skey in SENSOR_MAP.keys()}
relay_states = {}

# BUZZER & ALARM STATE
buzzer_active = False
buzzer_lock = threading.Lock()
active_warnings = []
silenced_alarm_keys = set()

# SYNC TRACKERS
ts_rotation_idx = 0
mqtt_timer = 0
last_upload_time = 0
last_local_save_time = 0

def is_room_paused(skey):
    return room_paused_states.get(skey, False)

def toggle_room_pause(skey):
    global room_paused_states
    room_paused_states[skey] = not room_paused_states.get(skey, False)
    is_paused = room_paused_states[skey]
    idx = int(skey.replace('S', '')) - 1
    ch_f = (idx * 3) + 1
    ch_h = (idx * 3) + 2
    ch_l = (idx * 3) + 3

    if is_paused:
        set_relay(ch_f, False); relay_states[ch_f] = False
        set_relay(ch_h, False); relay_states[ch_h] = False
        set_relay(ch_l, False); relay_states[ch_l] = False
        show_notification(f"{get_sensor_display_name(skey)} STOPPED", f"Manual stop activated for {get_sensor_display_name(skey)}. Relays turned OFF.", "warning", duration_ms=3000)
    else:
        show_notification(f"{get_sensor_display_name(skey)} RUNNING", f"Manual run activated for {get_sensor_display_name(skey)}. Automation resumed.", "success", duration_ms=3000)

    system_config.setdefault('room_paused', {})[skey] = is_paused
    save_config()
    update_ui()
    broadcast_current_state()

# --- CLOUD UPLOAD FREQUENCY HMS HELPERS ---
def get_upload_hms():
    h = int(system_config.get('upload_hours', 0))
    m = int(system_config.get('upload_mins', 0))
    s = int(system_config.get('upload_secs', 0))
    if h == 0 and m == 0 and s == 0 and 'upload_frequency_min' in system_config:
        try:
            total_sec = int(round(float(system_config.get('upload_frequency_min', 0)) * 60.0))
            if total_sec > 0:
                h = total_sec // 3600
                m = (total_sec % 3600) // 60
                s = total_sec % 60
        except Exception: pass
    return h, m, s

def normalize_upload_values(h_in, m_in, s_in):
    try: h = max(0, int(float(h_in)))
    except Exception: h = 0
    try: m = max(0, int(float(m_in)))
    except Exception: m = 0
    try: s = max(0, int(float(s_in)))
    except Exception: s = 0

    # 1. Seconds rollover to minutes
    if s >= 60:
        extra_m = s // 60
        s = s % 60
        m += extra_m

    # 2. Minutes rollover to hours
    if m >= 60:
        extra_h = m // 60
        m = m % 60
        h += extra_h

    return h, m, s

def format_upload_hms_display(h, m, s):
    try:
        h, m, s = int(h), int(m), int(s)
        total_sec = (h * 3600) + (m * 60) + s
        if total_sec <= 0 or (h == 0 and m == 0 and s == 0):
            return "1 Sec (Realtime Stream)"
        
        parts = []
        if h > 0:
            if h >= 24:
                days = h // 24
                rem_h = h % 24
                parts.append(f"{h}h ({days}d" + (f" {rem_h}h)" if rem_h > 0 else ")"))
            else:
                parts.append(f"{h} Hour{'s' if h > 1 else ''}")
        if m > 0:
            parts.append(f"{m} Min{'s' if m > 1 else ''}")
        if s > 0:
            parts.append(f"{s} Sec{'s' if s > 1 else ''}")
        
        return " : ".join(parts) + f"  ({total_sec}s Interval)"
    except Exception:
        return "1 Sec (Realtime Stream)"

# --- TIME FORMAT HELPERS (12-HOUR AM/PM <-> 24-HOUR) ---
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
        m = _re.search(r'(\d+):(\d+)\s*(AM|PM)', t_str, _re.IGNORECASE)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2))
            meridiem = m.group(3).upper()
            if meridiem == "PM" and hh < 12: hh += 12
            elif meridiem == "AM" and hh == 12: hh = 0
            return f"{hh:02d}:{mm:02d}"
    except Exception: pass
    return t_str

def parse_date_str(d_str):
    if not d_str:
        return None
    d_str = str(d_str).strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(d_str, fmt).date()
        except ValueError:
            pass
    return None

def format_date_dmy(d_val):
    if not d_val:
        return ""
    if isinstance(d_val, (datetime.date, datetime.datetime)):
        return d_val.strftime("%d-%m-%Y")
    d_obj = parse_date_str(d_val)
    if d_obj:
        return d_obj.strftime("%d-%m-%Y")
    return str(d_val).strip()

def generate_default_almora_schedule():
    stages = {}
    setting_keys = [
        ("Setting A", "Crop Stage 1", "01-07-2026", "15-07-2026"),
        ("Setting B", "Crop Stage 2", "16-07-2026", "31-07-2026"),
        ("Setting C", "Crop Stage 3", "01-08-2026", "15-08-2026"),
        ("Setting D", "Crop Stage 4", "16-08-2026", "31-08-2026"),
        ("Setting E", "Crop Stage 5", "01-09-2026", "15-09-2026"),
        ("Setting F", "Crop Stage 6", "16-09-2026", "30-09-2026"),
        ("Setting G", "Crop Stage 7", "01-10-2026", "15-10-2026"),
        ("Setting H", "Crop Stage 8", "16-10-2026", "31-10-2026"),
        ("Setting I", "Crop Stage 9", "01-11-2026", "15-11-2026"),
        ("Setting J", "Crop Stage 10", "16-11-2026", "30-11-2026")
    ]
    for key, name, sdate, edate in setting_keys:
        stages[key] = {
            "name": name,
            "start_date": sdate,
            "end_date": edate,
            "enabled": True,
            "photoperiod_on": "06:00 AM",
            "photoperiod_off": "08:00 PM",
            "lighting_enabled": True,
            "time_slots": [
                {"id": 1, "name": "Slot 1", "start": "12:00 AM", "stop": "05:00 AM", "t_set": 24.1, "t_max": 25.0, "t_min": 20.0, "h_set": 60.0, "h_max": 70.0, "h_min": 55.0, "enabled": True},
                {"id": 2, "name": "Slot 2", "start": "05:00 AM", "stop": "10:00 AM", "t_set": 25.0, "t_max": 26.0, "t_min": 21.0, "h_set": 65.0, "h_max": 70.0, "h_min": 60.0, "enabled": True},
                {"id": 3, "name": "Slot 3", "start": "10:00 AM", "stop": "03:00 PM", "t_set": 27.2, "t_max": 28.0, "t_min": 23.0, "h_set": 70.0, "h_max": 75.0, "h_min": 60.0, "enabled": True},
                {"id": 4, "name": "Slot 4", "start": "03:00 PM", "stop": "08:00 PM", "t_set": 26.0, "t_max": 27.0, "t_min": 22.0, "h_set": 68.0, "h_max": 72.0, "h_min": 60.0, "enabled": True},
                {"id": 5, "name": "Slot 5", "start": "08:00 PM", "stop": "12:00 AM", "t_set": 24.2, "t_max": 25.0, "t_min": 20.0, "h_set": 62.0, "h_max": 68.0, "h_min": 55.0, "enabled": True}
            ]
        }
    return {
        "mode": "SCHEDULED", # "STATIC" or "SCHEDULED"
        "active_setting": "Setting A",
        "program_name": "Default Program",
        "T MIN": 10.0,
        "T MAX": 30.0,
        "H MIN": 30.0,
        "H MAX": 80.0,
        "settings": stages
    }

def get_sensor_display_name(skey):
    custom_names = system_config.get("sensor_names", {})
    if skey in custom_names and custom_names[skey].strip():
        return custom_names[skey].strip()
    if skey == "S7": return "Greenhouse"
    return f"Cold Room {skey.replace('S', '')}"

def get_f_name(skey):
    if skey == "S7": return "Fanpad"
    return "AC"

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

def load_crop_programs():
    global crop_programs
    if os.path.exists(CROP_PROGRAMS_FILE):
        try:
            with open(CROP_PROGRAMS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    crop_programs = data
                else:
                    crop_programs = {}
        except Exception:
            crop_programs = {}
    else:
        crop_programs = {}

def get_all_crop_programs():
    load_crop_programs()
    all_progs = {}
    if isinstance(crop_programs, dict):
        # 1. Any flat keys that are valid program dictionaries (excluding room keys S1-S7)
        for k, v in crop_programs.items():
            if k not in SENSOR_MAP and isinstance(v, dict) and not k.startswith("Setting ") and not k.startswith("Stage "):
                all_progs[k] = v
        # 2. Any programs inside room keys S1-S7
        for skey in SENSOR_MAP.keys():
            if skey in crop_programs and isinstance(crop_programs[skey], dict):
                for p_name, p_val in crop_programs[skey].items():
                    if p_name and isinstance(p_val, dict) and p_name not in all_progs and not p_name.startswith("Setting ") and not p_name.startswith("Stage "):
                        all_progs[p_name] = p_val
    return all_progs

def get_room_crop_programs(skey=None):
    return get_all_crop_programs()

def save_crop_programs():
    global crop_programs
    try:
        with open(CROP_PROGRAMS_FILE, 'w') as f:
            json.dump(crop_programs, f, indent=4)
        broadcast_current_state()
    except Exception as e:
        print(f"Save Program Error: {e}")

def load_config():
    global system_config, room_paused_states
    if not os.path.exists(CONFIG_FILE):
        for fallback_name in ["cold_room", "cold_storage", "control123"]:
            alt_cfg = os.path.join(BASE_DIR, f"config_{fallback_name}.json")
            if os.path.exists(alt_cfg):
                try:
                    with open(alt_cfg, 'r') as f:
                        system_config = json.load(f)
                    with open(CONFIG_FILE, 'w') as f:
                        json.dump(system_config, f, indent=4)
                    break
                except Exception: pass
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                system_config = json.load(f)
        except Exception: pass

    if "sensor_names" not in system_config or not isinstance(system_config["sensor_names"], dict):
        system_config["sensor_names"] = {}
    default_sensor_names = {
        "S1": "Cold Room 1",
        "S2": "Cold Room 2",
        "S3": "Cold Room 3",
        "S4": "Cold Room 4",
        "S5": "Cold Room 5",
        "S6": "Cold Room 6",
        "S7": "Greenhouse"
    }
    for sk, def_nm in default_sensor_names.items():
        if sk not in system_config["sensor_names"] or not str(system_config["sensor_names"][sk]).strip():
            system_config["sensor_names"][sk] = def_nm

    if 'upload_frequency_min' not in system_config:
        system_config['upload_frequency_min'] = 0
    if 'upload_hours' not in system_config or 'upload_mins' not in system_config or 'upload_secs' not in system_config:
        total_sec = int(round(float(system_config.get('upload_frequency_min', 0)) * 60.0))
        if total_sec > 0:
            system_config['upload_hours'] = total_sec // 3600
            system_config['upload_mins'] = (total_sec % 3600) // 60
            system_config['upload_secs'] = total_sec % 60
        else:
            system_config['upload_hours'] = 0
            system_config['upload_mins'] = 0
            system_config['upload_secs'] = 0
    if 'temp_alarm_offset' not in system_config:
        system_config['temp_alarm_offset'] = 5.0
    if 'humi_alarm_offset' not in system_config:
        system_config['humi_alarm_offset'] = 5.0
    saved_paused = system_config.get('room_paused', {})
    for skey in SENSOR_MAP.keys():
        room_paused_states[skey] = bool(saved_paused.get(skey, False))

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(system_config, f, indent=4)
        broadcast_current_state()
    except Exception as e:
        print(f"Save Config Error: {e}")

def load_setpoints():
    global sensor_setpoints
    if not os.path.exists(SETPOINTS_FILE):
        for fallback_name in ["cold_room", "cold_storage", "control123"]:
            alt_setp = os.path.join(BASE_DIR, f"setpoints_{fallback_name}.json")
            if os.path.exists(alt_setp):
                try:
                    with open(alt_setp, 'r') as f:
                        sensor_setpoints = json.load(f)
                    with open(SETPOINTS_FILE, 'w') as f:
                        json.dump(sensor_setpoints, f, indent=4)
                    break
                except Exception: pass
    if os.path.exists(SETPOINTS_FILE):
        try:
            with open(SETPOINTS_FILE, 'r') as f:
                sensor_setpoints = json.load(f)
        except Exception as e:
            print(f"Error loading setpoints from {SETPOINTS_FILE}: {e}")
            sensor_setpoints = {}
    else:
        sensor_setpoints = {}
    
    load_crop_programs()

    for skey in SENSOR_MAP.keys():
        if skey not in sensor_setpoints or not isinstance(sensor_setpoints[skey], dict):
            sensor_setpoints[skey] = copy.deepcopy(generate_default_almora_schedule())
        else:
            if "program_name" not in sensor_setpoints[skey] or not str(sensor_setpoints[skey]["program_name"]).strip():
                sensor_setpoints[skey]["program_name"] = "Default Program"
            if "crop_name" not in sensor_setpoints[skey] or not str(sensor_setpoints[skey]["crop_name"]).strip():
                sensor_setpoints[skey]["crop_name"] = "Default Crop"
            if "setup_name" not in sensor_setpoints[skey] or not str(sensor_setpoints[skey]["setup_name"]).strip():
                sensor_setpoints[skey]["setup_name"] = f"Cold Room Setup {skey.replace('S', '')}"

            if "settings" not in sensor_setpoints[skey] or not isinstance(sensor_setpoints[skey]["settings"], dict):
                defaults = copy.deepcopy(generate_default_almora_schedule())
                defaults.update(sensor_setpoints[skey])
                sensor_setpoints[skey] = defaults
            else:
                defaults = copy.deepcopy(generate_default_almora_schedule())
                for k, v in defaults["settings"].items():
                    if k not in sensor_setpoints[skey]["settings"]:
                        sensor_setpoints[skey]["settings"][k] = copy.deepcopy(v)
            
            st_dict = sensor_setpoints[skey].get("settings", {})
            for k, st in st_dict.items():
                if "start_date" in st:
                    st["start_date"] = format_date_dmy(st["start_date"])
                if "end_date" in st:
                    st["end_date"] = format_date_dmy(st["end_date"])

            # Ensure that active saved program exists in crop_programs and settings are aligned
            prog_name = sensor_setpoints[skey].get("program_name")
            if prog_name and prog_name != "Default Program":
                if isinstance(crop_programs, dict):
                    if prog_name in crop_programs and not sensor_setpoints[skey].get("settings"):
                        sensor_setpoints[skey]["settings"] = copy.deepcopy(crop_programs[prog_name])
                    elif sensor_setpoints[skey].get("settings"):
                        crop_programs[prog_name] = copy.deepcopy(sensor_setpoints[skey]["settings"])
                        if skey in crop_programs and isinstance(crop_programs[skey], dict):
                            crop_programs[skey][prog_name] = copy.deepcopy(sensor_setpoints[skey]["settings"])

    # Ensure setpoints and crop programs are guaranteed on disk immediately upon startup
    try:
        with open(SETPOINTS_FILE, 'w') as f:
            json.dump(sensor_setpoints, f, indent=4)
        save_crop_programs()
        print(f"[SETPOINTS] Successfully loaded and persisted setpoints to disk: {SETPOINTS_FILE}")
    except Exception as e:
        print(f"Error persisting initial setpoints: {e}")

def save_setpoints():
    try:
        with open(SETPOINTS_FILE, 'w') as f:
            json.dump(sensor_setpoints, f, indent=4)
        broadcast_current_state()
    except Exception as e:
        print(f"Error saving setpoints: {e}")

def broadcast_current_state():
    if 'control_client' in globals() and control_client and control_client.is_connected():
        with sensor_data_lock:
            snap_sensor_data = dict(sensor_data)

        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ts_str = datetime.datetime.now(ist_tz).isoformat()

        norm_rooms = {}
        for idx, (skey, port) in enumerate(SENSOR_MAP.items()):
            d = snap_sensor_data.get(port)
            sp_eval = get_active_setpoints(skey)
            is_paused = is_room_paused(skey)
            norm_rooms[skey] = {
                "name": get_sensor_display_name(skey),
                "temp": d.get('temp') if d and d.get('status') == 'OK' else None,
                "humi": d.get('humi') if d and d.get('status') == 'OK' else None,
                "co2": d.get('co2') if d and d.get('status') == 'OK' else None,
                "status": d.get('status', 'OFFLINE') if d else 'OFFLINE',
                "paused": is_paused,
                "program_name": sp_eval.get("program_name", "Default Program"),
                "stage_name": sp_eval.get("stage_name") or sp_eval.get("setting_name", "Crop Stage 1"),
                "slot_name": sp_eval.get("slot_name", "Slot 1"),
                "slot_id": sp_eval.get("slot_id", 1),
                "target_temp": sp_eval.get("target_temp", 24.0),
                "target_humi": sp_eval.get("target_humi", 60.0),
                "cooling": bool(relay_states.get((idx * 3) + 1, False)),
                "humidifier": bool(relay_states.get((idx * 3) + 2, False)),
                "grow_lights": bool(relay_states.get((idx * 3) + 3, False)),
                "photoperiod_on": sp_eval.get("photoperiod_on", "06:00 AM"),
                "photoperiod_off": sp_eval.get("photoperiod_off", "08:00 PM"),
                "T MIN": sp_eval.get("T MIN", 10.0),
                "T MAX": sp_eval.get("T MAX", 30.0),
                "H MIN": sp_eval.get("H MIN", 30.0),
                "H MAX": sp_eval.get("H MAX", 80.0)
            }

        state_payload = {
            "device_id": DEVICE_NAME,
            "timestamp": ts_str,
            "source": "device",
            "rooms": norm_rooms,
            "sensor_setpoints": sensor_setpoints,
            "system_config": system_config,
            "crop_programs": crop_programs
        }
        try:
            control_client.publish(f"inhydro/{DEVICE_NAME}/state", json.dumps(state_payload), retain=True)
            control_client.publish(f"inhydro/{DEVICE_NAME}/setpoints/current", json.dumps(state_payload), retain=True)
        except Exception as e:
            print(f"[BROADCAST ERROR] {e}")

def get_setpoints(skey):
    global sensor_setpoints
    if skey not in sensor_setpoints:
        sensor_setpoints[skey] = copy.deepcopy(generate_default_almora_schedule())
    return sensor_setpoints[skey]

def get_active_setpoints(skey):
    sp_data = get_setpoints(skey)
    mode = sp_data.get("mode", "SCHEDULED")
    
    t_min = float(sp_data.get("T MIN", 10.0))
    t_max = float(sp_data.get("T MAX", 30.0))
    h_min = float(sp_data.get("H MIN", 30.0))
    h_max = float(sp_data.get("H MAX", 80.0))
    
    prog_name = sp_data.get("program_name") or "Default Program"
    crop_name = sp_data.get("crop_name") or "Default Crop"

    if mode == "STATIC":
        return {
            "skey": skey,
            "setting_name": "Static Mode",
            "stage_name": "Static Mode",
            "slot_name": "Static Setpoints",
            "slot_id": 1,
            "program_name": prog_name,
            "crop_name": crop_name,
            "start": "12:00 AM",
            "stop": "11:59 PM",
            "target_temp": round((t_min + t_max) / 2.0, 1),
            "target_humi": round((h_min + h_max) / 2.0, 1),
            "photoperiod_on": "06:00 AM",
            "photoperiod_off": "08:00 PM",
            "lighting_enabled": True,
            "T MIN": t_min,
            "T MAX": t_max,
            "H MIN": h_min,
            "H MAX": h_max
        }

    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist_tz)
    today_dt = now.date()
    current_time_str = now.strftime("%H:%M")

    settings = sp_data.get("settings", {})
    setting_keys = ["Setting A", "Setting B", "Setting C", "Setting D", "Setting E", 
                    "Setting F", "Setting G", "Setting H", "Setting I", "Setting J"]

    # 1. Stage Resolution: Find stage by date match, or fallback to active_setting / first enabled stage
    active_stage = None
    active_stage_key = None

    for set_key in setting_keys:
        st = settings.get(set_key)
        if not st or not st.get("enabled", True):
            continue
        s_date_obj = parse_date_str(st.get("start_date", ""))
        e_date_obj = parse_date_str(st.get("end_date", ""))
        if s_date_obj and e_date_obj:
            if s_date_obj <= today_dt <= e_date_obj:
                active_stage = st
                active_stage_key = set_key
                break

    # If no date match, fallback to configured active_setting if enabled
    if not active_stage:
        pref_key = sp_data.get("active_setting", "Setting A")
        if pref_key in settings and settings[pref_key].get("enabled", True):
            active_stage = settings[pref_key]
            active_stage_key = pref_key

    # If still none, fallback to first enabled stage
    if not active_stage:
        for set_key in setting_keys:
            st = settings.get(set_key)
            if st and st.get("enabled", True):
                active_stage = st
                active_stage_key = set_key
                break

    # If no stages enabled, fallback to Setting A or default
    if not active_stage:
        active_stage = settings.get("Setting A", {
            "name": "Crop Stage 1",
            "start_date": "01-01-2026",
            "end_date": "31-12-2026",
            "enabled": True,
            "photoperiod_on": "06:00 AM",
            "photoperiod_off": "08:00 PM",
            "lighting_enabled": True,
            "time_slots": [
                {"id": 1, "name": "Slot 1", "start": "12:00 AM", "stop": "11:59 PM", "t_set": 24.0, "t_max": 25.0, "t_min": 20.0, "h_set": 60.0, "h_max": 70.0, "h_min": 55.0, "enabled": True}
            ]
        })
        active_stage_key = "Setting A"

    stage_display_name = active_stage.get("name") or f"Crop Stage {setting_keys.index(active_stage_key) + 1 if active_stage_key in setting_keys else 1}"
    p_on = active_stage.get("photoperiod_on", "06:00 AM")
    p_off = active_stage.get("photoperiod_off", "08:00 PM")
    l_enabled = active_stage.get("lighting_enabled", True)

    # 2. Slot Resolution: Find slot matching current time, or fallback to first enabled slot
    time_slots = active_stage.get("time_slots", [])
    active_slot = None

    for slot in time_slots:
        if not slot.get("enabled", True):
            continue
        start_t = format_time_24h(slot.get("start", "00:00"))
        stop_t = format_time_24h(slot.get("stop", "23:59"))
        if start_t <= stop_t:
            is_in_slot = (start_t <= current_time_str <= stop_t)
        else:
            is_in_slot = (current_time_str >= start_t or current_time_str <= stop_t)
        if is_in_slot:
            active_slot = slot
            break

    # Fallback to first enabled slot
    if not active_slot:
        for slot in time_slots:
            if slot.get("enabled", True):
                active_slot = slot
                break

    # Absolute fallback slot if list is empty
    if not active_slot:
        active_slot = {
            "id": 1,
            "name": "Slot 1",
            "start": "12:00 AM",
            "stop": "11:59 PM",
            "t_set": (t_min + t_max) / 2.0,
            "t_max": t_max,
            "t_min": t_min,
            "h_set": (h_min + h_max) / 2.0,
            "h_max": h_max,
            "h_min": h_min,
            "enabled": True
        }

    slot_id = active_slot.get("id", 1)
    slot_display_name = active_slot.get("name") or f"Slot {slot_id}"

    t_set_v = float(active_slot.get("t_set", active_slot.get("temp_setpoint", 24.0)))
    h_set_v = float(active_slot.get("h_set", active_slot.get("humi_setpoint", 60.0)))
    t_max_v = float(active_slot.get("t_max", t_set_v + 1.0))
    t_min_v = float(active_slot.get("t_min", t_set_v - 1.0))
    h_max_v = float(active_slot.get("h_max", h_set_v + 5.0))
    h_min_v = float(active_slot.get("h_min", h_set_v - 5.0))

    return {
        "skey": skey,
        "setting_name": stage_display_name,
        "stage_name": stage_display_name,
        "slot_name": slot_display_name,
        "slot_id": slot_id,
        "program_name": prog_name,
        "crop_name": crop_name,
        "start": active_slot.get("start", "12:00 AM"),
        "stop": active_slot.get("stop", "11:59 PM"),
        "target_temp": round(t_set_v, 1),
        "target_humi": round(h_set_v, 1),
        "photoperiod_on": p_on,
        "photoperiod_off": p_off,
        "lighting_enabled": l_enabled,
        "T MIN": round(t_min_v, 1),
        "T MAX": round(t_max_v, 1),
        "H MIN": round(h_min_v, 1),
        "H MAX": round(h_max_v, 1)
    }

def trigger_buzzer_30s():
    global buzzer_active
    with buzzer_lock:
        if buzzer_active: return
        buzzer_active = True

    def _buzzer_worker():
        global buzzer_active
        print("[BUZZER] 30-second warning alarm triggered!")
        set_relay(BUZZER_CHANNEL, True)
        time.sleep(30)
        set_relay(BUZZER_CHANNEL, False)
        with buzzer_lock:
            buzzer_active = False
        print("[BUZZER] 30-second alarm ended.")

    threading.Thread(target=_buzzer_worker, daemon=True).start()

def disable_wifi_power_save():
    try:
        subprocess.run(["sudo", "iw", "dev", "wlan0", "set", "power_save", "off"], capture_output=True, timeout=5)
        subprocess.run(["sudo", "iwconfig", "wlan0", "power", "off"], capture_output=True, timeout=5)
        try:
            out = subprocess.check_output(['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show'], text=True, timeout=5)
            for line in out.splitlines():
                if ':802-11-wireless' in line:
                    cname = line.split(':')[0].strip()
                    subprocess.run(["sudo", "nmcli", "connection", "modify", cname, "802-11-wireless.powersave", "2"], capture_output=True, timeout=4)
                    subprocess.run(["sudo", "nmcli", "connection", "modify", cname, "connection.autoconnect", "yes"], capture_output=True, timeout=4)
                    subprocess.run(["sudo", "nmcli", "connection", "modify", cname, "connection.autoconnect-retries", "0"], capture_output=True, timeout=4)
        except Exception: pass
        print("[Network] Wi-Fi power-save successfully disabled & permanent auto-connect configured.")
    except Exception as e:
        print(f"[Network] Note on power-save disable: {e}")

def set_wifi(ssid, password):
    try:
        ssid = str(ssid).strip()
        password = str(password).strip()
        if not ssid:
            return "FAILED: Empty SSID"

        # 1. Unblock radio & ensure Wi-Fi subsystem is active
        try:
            subprocess.run(["sudo", "rfkill", "unblock", "wifi"], capture_output=True, timeout=3)
            subprocess.run(["sudo", "rfkill", "unblock", "all"], capture_output=True, timeout=3)
            subprocess.run(["sudo", "nmcli", "radio", "wifi", "on"], capture_output=True, timeout=3)
        except Exception: pass

        # 2. Delete any existing stale connection profile with this SSID to avoid credential conflict
        try:
            subprocess.run(['sudo', 'nmcli', 'connection', 'delete', 'id', ssid], capture_output=True, timeout=4)
            subprocess.run(['sudo', 'nmcli', 'connection', 'delete', ssid], capture_output=True, timeout=4)
        except Exception: pass

        # 3. Direct device connection attempt
        cmd = ['sudo', 'nmcli', '--wait', '15', 'device', 'wifi', 'connect', ssid]
        if password:
            cmd += ['password', password]

        dev_out = ""
        try:
            dev_out = subprocess.check_output(['nmcli', '-t', '-f', 'DEVICE,TYPE', 'dev'], text=True, timeout=4)
            if 'wlan0:wifi' in dev_out:
                cmd += ['ifname', 'wlan0']
        except Exception: pass

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=18)

        # 4. Fallback: Explicit profile creation with WPA-PSK
        if res.returncode != 0 and password:
            try:
                subprocess.run(['sudo', 'nmcli', 'connection', 'delete', 'id', ssid], capture_output=True, timeout=4)
                add_cmd = [
                    'sudo', 'nmcli', 'connection', 'add', 'type', 'wifi',
                    'con-name', ssid, 'ssid', ssid
                ]
                if 'wlan0' in dev_out:
                    add_cmd += ['ifname', 'wlan0']
                res_add = subprocess.run(add_cmd, capture_output=True, text=True, timeout=8)
                
                # Set WPA-PSK security using standard NetworkManager properties
                subprocess.run([
                    'sudo', 'nmcli', 'connection', 'modify', ssid,
                    '802-11-wireless-security.key-mgmt', 'wpa-psk',
                    '802-11-wireless-security.psk', password
                ], capture_output=True, timeout=6)
                
                res = subprocess.run(['sudo', 'nmcli', '--wait', '15', 'connection', 'up', 'id', ssid], capture_output=True, text=True, timeout=18)
            except Exception as ex:
                print(f"[Network] Profile fallback error: {ex}")

        # 5. Fallback 2: WPA Supplicant Append (Raspberry Pi OS native)
        if res.returncode != 0 and os.path.exists('/etc/wpa_supplicant/wpa_supplicant.conf'):
            try:
                if password:
                    wpa_block = f'\nnetwork={{\n    ssid="{ssid}"\n    psk="{password}"\n    key_mgmt=WPA-PSK\n}}\n'
                else:
                    wpa_block = f'\nnetwork={{\n    ssid="{ssid}"\n    key_mgmt=NONE\n}}\n'
                with open('/tmp/wpa_snippet.conf', 'w') as sf:
                    sf.write(wpa_block)
                subprocess.run(['sudo', 'sh', '-c', 'cat /tmp/wpa_snippet.conf >> /etc/wpa_supplicant/wpa_supplicant.conf'], capture_output=True, timeout=4)
                subprocess.run(['sudo', 'wpa_cli', '-i', 'wlan0', 'reconfigure'], capture_output=True, timeout=6)
            except Exception: pass

        if res.returncode == 0:
            print(f"[Network] Successfully connected to Wi-Fi SSID: {ssid}")
            try:
                subprocess.run(["sudo", "nmcli", "connection", "modify", ssid, "connection.autoconnect", "yes"], capture_output=True, timeout=4)
                subprocess.run(["sudo", "nmcli", "connection", "modify", ssid, "connection.autoconnect-priority", "10"], capture_output=True, timeout=4)
                subprocess.run(["sudo", "nmcli", "connection", "modify", ssid, "connection.autoconnect-retries", "0"], capture_output=True, timeout=4)
                subprocess.run(["sudo", "nmcli", "connection", "modify", ssid, "802-11-wireless.powersave", "2"], capture_output=True, timeout=4)
                subprocess.run(["sudo", "iw", "dev", "wlan0", "set", "power_save", "off"], capture_output=True, timeout=4)
            except Exception: pass
            return f"SUCCESS: Connected to '{ssid}'!"
        else:
            err_msg = res.stderr.strip() or res.stdout.strip() or "Connection failed"
            print(f"[Network] Wi-Fi connect failed: {err_msg}")
            return f"FAILED: {err_msg}"
    except subprocess.TimeoutExpired:
        return "FAILED: Connection attempt timed out (18s)."
    except Exception as e:
        return f"ERROR: {str(e)}"

def scan_wifi():
    try:
        # Trigger an active rescan so fresh APs appear in the cache
        try:
            subprocess.run(['sudo', 'nmcli', 'device', 'wifi', 'rescan'], capture_output=True, timeout=5)
        except Exception: pass

        res = subprocess.run(['sudo', 'nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list'], capture_output=True, text=True, timeout=8)
        if res.returncode == 0:
            lines = [n.strip() for n in res.stdout.split('\n') if n.strip()]
            seen = set()
            formatted = []
            for line in lines:
                parts = line.split(':')
                s_name = parts[0].strip()
                if not s_name or s_name == '--' or s_name in seen:
                    continue
                seen.add(s_name)
                sig = parts[1].strip() if len(parts) > 1 else ""
                sec = parts[2].strip() if len(parts) > 2 else ""
                info = f"{len(formatted)+1}. {s_name}"
                if sig: info += f" ({sig}% signal"
                if sec: info += f", {sec})"
                elif sig: info += ")"
                formatted.append(info)
            return "\r\n".join(formatted) if formatted else "No networks found"
        return "SCAN FAILED"
    except subprocess.TimeoutExpired:
        return "SCAN TIMEOUT"
    except Exception as e:
        return f"ERROR: {str(e)}"

def auto_trust_devices():
    try:
        import sys, glob
        for path in glob.glob('/usr/lib/python3*/dist-packages'):
            if path not in sys.path: sys.path.append(path)
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()
        adapter_obj = bus.get_object('org.bluez', '/org/bluez/hci0')
        adapter_props = dbus.Interface(adapter_obj, 'org.freedesktop.DBus.Properties')
        adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
        adapter_props.Set('org.bluez.Adapter1', 'Discoverable', dbus.Boolean(True))
        adapter_props.Set('org.bluez.Adapter1', 'Pairable', dbus.Boolean(True))
        adapter_props.Set('org.bluez.Adapter1', 'DiscoverableTimeout', dbus.UInt32(0))
        adapter_props.Set('org.bluez.Adapter1', 'PairableTimeout', dbus.UInt32(0))
        print("[BT] Bluetooth Adapter Powered (Always Discoverable & Pairable)")
    except Exception as e:
        print(f"[BT] DBus adapter prop setup note: {e}")

    last_disc_check = 0
    while running:
        now = time.time()
        if now - last_disc_check >= 25:
            try:
                subprocess.run(["sudo", "bluetoothctl", "power", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
                subprocess.run(["sudo", "bluetoothctl", "discoverable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
                subprocess.run(["sudo", "bluetoothctl", "pairable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
                subprocess.run(["sudo", "bluetoothctl", "agent", "NoInputNoOutput"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
                subprocess.run(["sudo", "bluetoothctl", "default-agent"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
                last_disc_check = now
            except Exception: pass
            
        try:
            out = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True, timeout=5)
            for line in out.split('\n'):
                if line.startswith('Device '):
                    mac = line.split(' ')[1].strip()
                    subprocess.run(["sudo", "bluetoothctl", "trust", mac], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
        except Exception: pass
        time.sleep(6)

def network_watchdog():
    """Background watchdog that continuously monitors network link, keeps Wi-Fi active, and auto-recovers Wi-Fi if dropped."""
    consecutive_failures = 0
    ticks = 0
    time.sleep(12)  # Initial grace period on boot
    while running:
        time.sleep(10)
        if not running: break
        ticks += 1

        # Periodically enforce power_save off (every 60s)
        if ticks % 6 == 0:
            try:
                subprocess.run(["sudo", "iw", "dev", "wlan0", "set", "power_save", "off"], capture_output=True, timeout=4)
            except Exception: pass
        
        # Test internet/broker connectivity
        is_online = False
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3.5)
            s.connect((CONTROL_BROKER, CONTROL_PORT))
            s.close()
            is_online = True
        except Exception:
            try:
                s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s2.settimeout(3.5)
                s2.connect(("8.8.8.8", 53))
                s2.close()
                is_online = True
            except Exception:
                try:
                    s3 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s3.settimeout(3.5)
                    s3.connect(("1.1.1.1", 53))
                    s3.close()
                    is_online = True
                except Exception:
                    is_online = False

        if is_online:
            consecutive_failures = 0
            if 'control_client' in globals() and control_client and not control_client.is_connected():
                try:
                    control_client.reconnect()
                except Exception: pass
            continue

        consecutive_failures += 1
        print(f"[NetworkWatchdog] Connection check failed ({consecutive_failures}/3)")

        # Check if Wi-Fi interface is disconnected
        wifi_connected = False
        try:
            dev_out = subprocess.check_output(['nmcli', '-t', '-f', 'TYPE,STATE', 'dev'], text=True, timeout=5)
            for line in dev_out.splitlines():
                parts = line.strip().split(':')
                if len(parts) >= 2 and parts[0] == 'wifi' and parts[1] == 'connected':
                    wifi_connected = True
                    break
        except Exception: pass

        # Get all saved Wi-Fi profiles
        saved_conns = []
        try:
            out = subprocess.check_output(['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show'], text=True, timeout=5)
            for line in out.splitlines():
                if ':802-11-wireless' in line:
                    saved_conns.append(line.split(':')[0].strip())
        except Exception: pass

        if not wifi_connected or consecutive_failures >= 2:
            print(f"[NetworkWatchdog] Wi-Fi link issue detected. Attempting immediate auto-reconnect (Saved profiles: {saved_conns})...")
            reconnected = False
            for cname in saved_conns:
                try:
                    res_up = subprocess.run(["sudo", "nmcli", "connection", "up", "id", cname], capture_output=True, text=True, timeout=12)
                    if res_up.returncode == 0:
                        print(f"[NetworkWatchdog] Reconnected successfully to '{cname}'")
                        reconnected = True
                        consecutive_failures = 0
                        break
                except Exception: pass

            if not reconnected and consecutive_failures >= 3:
                print("[NetworkWatchdog] Radio cycling wlan0 adapter...")
                try:
                    subprocess.run(["sudo", "nmcli", "radio", "wifi", "off"], capture_output=True, timeout=5)
                    time.sleep(2)
                    subprocess.run(["sudo", "nmcli", "radio", "wifi", "on"], capture_output=True, timeout=5)
                    time.sleep(3)
                    subprocess.run(["sudo", "iw", "dev", "wlan0", "set", "power_save", "off"], capture_output=True, timeout=4)
                    for cname in saved_conns:
                        res_up = subprocess.run(["sudo", "nmcli", "connection", "up", "id", cname], capture_output=True, text=True, timeout=12)
                        if res_up.returncode == 0:
                            print(f"[NetworkWatchdog] Reconnected after radio cycle to '{cname}'")
                            consecutive_failures = 0
                            break
                except Exception as ex:
                    print(f"[NetworkWatchdog] Radio cycle error: {ex}")
                time.sleep(8)

def restart_program():
    global running; running = False
    print("Restarting application...")
    try:
        relay_port = system_config.get('relay_port')
        if relay_port:
            for ch in range(1, 23):
                set_relay(ch, False)
    except Exception: pass
    os.execl(sys.executable, sys.executable, *sys.argv)

def get_bluetooth_live_status():
    try:
        with sensor_data_lock:
            snap = dict(sensor_data)

        lines = []
        lines.append(f"  INHYDRO COLD-ROOM CONTROLLER - LIVE DATA")
        lines.append(f"  Timestamp: {time.strftime('%d-%m-%Y %H:%M:%S')}")

        for idx, skey in enumerate(['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7']):
            if skey not in SENSOR_MAP:
                continue
            port = SENSOR_MAP[skey]
            disp_name = get_sensor_display_name(skey)
            d = snap.get(port)
            sp_eval = get_active_setpoints(skey)

            t_target = sp_eval.get('target_temp', 24.0)
            h_target = sp_eval.get('target_humi', 60.0)
            setting_nm = sp_eval.get('setting_name', 'Stage 1')
            paused = is_room_paused(skey)

            r_cool = "ON" if relay_states.get((idx * 3) + 1, False) else "OFF"
            r_humi = "ON" if relay_states.get((idx * 3) + 2, False) else "OFF"
            r_light = "ON" if relay_states.get((idx * 3) + 3, False) else "OFF"
            fan_label = get_f_name(skey)

            if paused:
                mode_str = "MANUAL STOPPED"
            else:
                mode_str = f"RUNNING [{setting_nm}]"

            lines.append(f"[{disp_name} - {skey}] -> {mode_str}")
            if d and d.get('status') == 'OK':
                t = d.get('temp', 0.0)
                h = d.get('humi', 0.0)
                c = d.get('co2')
                co2_str = f"{c:.1f} ppm" if (c is not None and c > 0) else "N/A"
                lines.append(f"  Temp: {t:.1f}°C (Set: {t_target:.1f}°C)")
                lines.append(f"  Humi: {h:.1f}%  (Set: {h_target:.1f}%)")
                lines.append(f"  CO2 : {co2_str}")
                lines.append(f"  Relays: {fan_label}={r_cool}, Humi={r_humi}, Light={r_light}")
            elif d and d.get('status') == 'ERROR':
                lines.append("  Sensor: ERROR (Read Failure)")
                lines.append(f"  Relays: {fan_label}={r_cool}, Humi={r_humi}, Light={r_light}")
            else:
                lines.append("  Sensor: OFFLINE")
                lines.append(f"  Relays: {fan_label}={r_cool}, Humi={r_humi}, Light={r_light}")
            lines.append("------------------------------------------")

        return "\r\n".join(lines) + "\r\n"
    except Exception as ex:
        return f"Error reading live room data: {ex}\r\n"

active_bt_fds = set()
dbus_spp_active = False

def process_bt_command(raw_cmd):
    """Parses and executes command from Bluetooth Serial Terminal and returns response string."""
    raw_cmd = raw_cmd.strip()
    if not raw_cmd:
        return ""
    txt_upper = raw_cmd.upper()
    print(f"[BT CMD] Executing command: '{raw_cmd}'")

    # 1. JSON Support (e.g. WiFi credentials, Setpoints, Config, Commands)
    if raw_cmd.startswith('{') and raw_cmd.endswith('}'):
        try:
            data = json.loads(raw_cmd)
            if 'sensor_setpoints' in data or 'setpoints' in data:
                sp_data = data.get('sensor_setpoints') or data.get('setpoints')
                if isinstance(sp_data, dict):
                    sensor_setpoints.update(sp_data)
                    save_setpoints()
            if 'system_config' in data:
                if isinstance(data['system_config'], dict):
                    system_config.update(data['system_config'])
                    save_config()
            if 'upload_frequency_min' in data or 'upload_hours' in data:
                if 'upload_frequency_min' in data: system_config['upload_frequency_min'] = data['upload_frequency_min']
                if 'upload_hours' in data: system_config['upload_hours'] = data['upload_hours']
                if 'upload_mins' in data: system_config['upload_mins'] = data['upload_mins']
                if 'upload_secs' in data: system_config['upload_secs'] = data['upload_secs']
                save_config()
            if 'sensor_setpoints' in data or 'setpoints' in data or 'system_config' in data or 'upload_frequency_min' in data:
                return json.dumps({"status": "success", "message": "Setpoints and configuration updated over Bluetooth"}) + "\r\n"

            ssid_in = data.get('ssid') or data.get('SSID') or data.get('wifi') or data.get('name') or ''
            pass_in = data.get('password') or data.get('pass') or data.get('PASSWORD') or data.get('pwd') or ''
            if ssid_in:
                res_msg = set_wifi(str(ssid_in).strip(), str(pass_in).strip())
                return json.dumps({"status": "success" if "SUCCESS" in res_msg else "error", "message": res_msg}) + "\r\n"
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)}) + "\r\n"

    # 2. Known Action Commands
    if txt_upper in ["SCAN", "1", "WIFI SCAN", "SCAN WIFI"]:
        scan_res = scan_wifi()
        return f"\r\n--- NEARBY WI-FI NETWORKS ---\r\n{scan_res}\r\n\r\n"

    elif txt_upper in ["STATUS", "LIVE", "DATA", "ROOMS", "3", "INFO"]:
        return f"\r\n{get_bluetooth_live_status()}\r\n"

    elif txt_upper in ["PING", "4"]:
        return "\r\n[PONG] InHydro Cold Room Controller is Online & Ready!\r\n\r\n"

    elif txt_upper in ["HELP", "5", "?", "MENU"]:
        return (
            "\r\n--- COMMAND MENU ---\r\n"
            "1. SCAN\r\n"
            "2. WIFI:SSID:PASSWORD\r\n"
            "3. STATUS\r\n"
            "4. PING\r\n"
            "5. HELP\r\n\r\n"
        )

    # 3. Wi-Fi Connection Parsing (Prefixes, Colon, Comma, Space, Key-Value)
    ssid_in = None
    pass_in = ""

    for pfx in ["WIFI:", "2:", "SET_WIFI:", "CONNECT:", "WIFI=", "SET_WIFI "]:
        if txt_upper.startswith(pfx):
            raw_body = raw_cmd[len(pfx):].strip()
            if ":" in raw_body:
                parts = raw_body.split(":", 1)
                ssid_in, pass_in = parts[0].strip(), parts[1].strip()
            elif "," in raw_body:
                parts = raw_body.split(",", 1)
                ssid_in, pass_in = parts[0].strip(), parts[1].strip()
            elif " " in raw_body:
                parts = raw_body.split(" ", 1)
                ssid_in, pass_in = parts[0].strip(), parts[1].strip()
            else:
                ssid_in, pass_in = raw_body, ""
            break

    # If no prefix matched, check direct delimiter formats like SSID:PASSWORD or SSID,PASSWORD
    if ssid_in is None:
        if ":" in raw_cmd:
            parts = raw_cmd.split(":", 1)
            ssid_in, pass_in = parts[0].strip(), parts[1].strip()
        elif "," in raw_cmd:
            parts = raw_cmd.split(",", 1)
            ssid_in, pass_in = parts[0].strip(), parts[1].strip()

    if ssid_in:
        # Strip bounding quotes
        if ssid_in.startswith('"') and ssid_in.endswith('"') and len(ssid_in) > 1:
            ssid_in = ssid_in[1:-1]
        if pass_in.startswith('"') and pass_in.endswith('"') and len(pass_in) > 1:
            pass_in = pass_in[1:-1]
        ssid_in = ssid_in.strip()
        pass_in = pass_in.strip()
        if ssid_in:
            res_msg = set_wifi(ssid_in, pass_in)
            return f"\r\n[Connecting to '{ssid_in}'...]\r\n{res_msg}\r\n\r\n"

    return f"\r\nACK: Received '{raw_cmd}'. Send HELP for command list.\r\n\r\n"

def handle_bt_client_fd(fd_int):
    global active_bt_fds
    active_bt_fds.add(fd_int)
    try:
        print(f"[BT] Terminal connected (DBus SPP FD: {fd_int})")
        banner = (
            f"\r\n  INHYDRO COLD ROOM CONTROLLER \r\n"
            
            "Commands:\r\n"
            "  1. SCAN\r\n"
            "  2. WIFI:SSID:PASSWORD\r\n"
            "  3. STATUS\r\n"
            "  4. PING\r\n"
            "  5. HELP\r\n"
        )
        os.write(fd_int, banner.encode('utf-8'))

        buf = ""
        while running:
            try:
                raw = os.read(fd_int, 1024)
            except Exception:
                break
            if not raw:
                print(f"[BT] Terminal disconnected (FD: {fd_int})")
                break
            buf += raw.decode('utf-8', errors='ignore')

            while "\n" in buf or "\r" in buf:
                if "\r\n" in buf:
                    line, buf = buf.split("\r\n", 1)
                elif "\n" in buf:
                    line, buf = buf.split("\n", 1)
                else:
                    line, buf = buf.split("\r", 1)

                cmd_line = line.strip()
                if cmd_line:
                    resp = process_bt_command(cmd_line)
                    if resp:
                        os.write(fd_int, resp.encode('utf-8'))
    except Exception as e:
        print(f"[BT] Client FD exception: {e}")
    finally:
        active_bt_fds.discard(fd_int)
        try: os.close(fd_int)
        except: pass

def register_spp_dbus():
    global dbus_spp_active
    try:
        import sys, glob
        for path in glob.glob('/usr/lib/python3*/dist-packages'):
            if path not in sys.path: sys.path.append(path)
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

        bus = dbus.SystemBus(mainloop=DBusGMainLoop())
        agent_path = '/inhydro/almora_agent'
        try:
            agent = BluetoothAgent(bus, agent_path)
            obj = bus.get_object('org.bluez', '/org/bluez')
            manager = dbus.Interface(obj, 'org.bluez.AgentManager1')
            try: manager.UnregisterAgent(agent_path)
            except: pass
            manager.RegisterAgent(agent_path, 'NoInputNoOutput')
            manager.RequestDefaultAgent(agent_path)
            print("[BT] Headless Auto-Pairing Bluetooth Agent Active (No PIN required)")
        except Exception as e:
            print(f"[BT] Agent registration note: {e}")

        profile_path = '/inhydro/almora_spp_profile'
        profile = BluezProfile(bus, profile_path)
        manager_p = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.ProfileManager1')
        try: manager_p.UnregisterProfile(profile_path)
        except: pass
        opts = {
            'AutoConnect': dbus.Boolean(True),
            'Role': 'server',
            'Name': f'InHydro_{DEVICE_NAME}',
            'Service': '00001101-0000-1000-8000-00805F9B34FB',
            'Channel': dbus.UInt16(1),
            'RequireAuthentication': dbus.Boolean(False),
            'RequireAuthorization': dbus.Boolean(False)
        }
        manager_p.RegisterProfile(profile_path, '00001101-0000-1000-8000-00805F9B34FB', opts)
        print("[BT] DBus SPP Profile1 (UUID 00001101-0000-1000-8000-00805F9B34FB) Registered with Full SDP Record!")

        mainloop = GLib.MainLoop()
        threading.Thread(target=mainloop.run, daemon=True).start()
        print("[BT] GLib DBus Event Dispatcher Thread Started!")
        dbus_spp_active = True
    except Exception as e:
        print(f"[BT] Notice: DBus Bluetooth setup note: {e}")
        dbus_spp_active = False

def start_bluetooth_server():
    register_spp_dbus()

    while running:
        srv = None
        try:
            os.system("sudo sdptool add SP >/dev/null 2>&1")
            time.sleep(0.5)
            srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            bound = False
            for attempt in range(15):
                if not running: return
                try:
                    srv.bind((socket.BDADDR_ANY, 1))
                    bound = True
                    break
                except OSError:
                    time.sleep(1.5)
            
            if not bound:
                print("[BT] Note: Raw RFCOMM port 1 bound to DBus SPP. Active via DBus Profile.")
                time.sleep(10)
                continue

            srv.listen(1)
            print("[BT] Bluetooth RFCOMM Server listening on channel 1 (Ready for Serial Terminal).")

            while running:
                client = None
                try:
                    client, client_info = srv.accept()
                    print(f"[BT] Raw RFCOMM Terminal connected from {client_info}")
                    banner = (
                        f"  INHYDRO COLD-ROOM CONTROLLER \r\n"
                    
                        "Commands:\r\n"
                        "  1. SCAN\r\n"
                        "  2. WIFI:SSID:PASSWORD\r\n"
                        "  3. STATUS\r\n"
                        "  4. PING\r\n"
                        "  5. HELP\r\n"
                    )
                    client.send(banner.encode())

                    rx_buffer = ""
                    while running:
                        chunk = client.recv(1024)
                        if not chunk:
                            print("[BT] Raw RFCOMM Terminal disconnected.")
                            break
                        rx_buffer += chunk.decode(errors='ignore')

                        while '\n' in rx_buffer or '\r' in rx_buffer:
                            if '\r\n' in rx_buffer:
                                line, rx_buffer = rx_buffer.split('\r\n', 1)
                            elif '\n' in rx_buffer:
                                line, rx_buffer = rx_buffer.split('\n', 1)
                            else:
                                line, rx_buffer = rx_buffer.split('\r', 1)

                            cmd_line = line.strip()
                            if cmd_line:
                                resp = process_bt_command(cmd_line)
                                if resp:
                                    client.send(resp.encode())

                except Exception as client_ex:
                    print(f"[BT] Raw RFCOMM Client note: {client_ex}")
                finally:
                    if client:
                        try: client.close()
                        except: pass

        except Exception as srv_ex:
            print(f"[BT] Server socket note: {srv_ex}")
            time.sleep(5)
        finally:
            if srv:
                try: srv.close()
                except: pass
            time.sleep(2)

CONTROL_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/update"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"
CONTROL_CMD_TOPIC = f"inhydro/{DEVICE_NAME}/command"

_safe_client_id = f"Almora_{DEVICE_NAME}_{_uuid.uuid4().hex[:8]}"
try:
    control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, _safe_client_id)
except AttributeError:
    control_client = mqtt.Client(_safe_client_id)

def on_control_message(client, userdata, msg):
    try:
        global system_config, sensor_setpoints, room_paused_states, sched_clean_snapshot, sched_dirty_flag

        topic = str(msg.topic)
        # 1. Ignore outbound / telemetry / heartbeat / self-echo topics immediately
        if (topic.endswith("/telemetry") or 
            topic.endswith("/telemetry/live") or 
            topic.endswith("/heartbeat") or 
            topic.endswith("/command/status") or 
            topic.endswith("/setpoints/current") or
            topic.endswith("/state")):
            return

        # Ignore stale retained messages so broker buffer never overwrites device disk files on restart
        if getattr(msg, 'retain', False):
            return

        try:
            payload_str = msg.payload.decode('utf-8')
            new_data = json.loads(payload_str)
        except Exception:
            new_data = {"raw": msg.payload.decode('utf-8', errors='ignore').strip()}

        # Discard any message originating from this device to prevent echo loops
        if isinstance(new_data, dict) and (new_data.get("source") == "device" or new_data.get("from") == "device"):
            return

        # 2. Hardware Command Handling (Remote Restart, Exit, Pause, Resume)
        if topic == CONTROL_CMD_TOPIC or topic.endswith("/command"):
            action = str(new_data.get("action", new_data.get("raw", ""))).lower().strip()
            print(f"[MQTT COMMAND] Received remote action: '{action}'")

            if action == "restart":
                print("[MQTT COMMAND] Remote restart triggered!")
                try:
                    client.publish(f"inhydro/{DEVICE_NAME}/command/status", json.dumps({"action": "restart", "status": "executing", "timestamp": time.time(), "source": "device"}), retain=False)
                except Exception: pass
                show_notification("REMOTE RESTART", "Remote restart command received. Restarting in 2 seconds...", "warning", duration_ms=4000)
                try: root.after(1500, restart_program)
                except: restart_program()
                return

            elif action in ["exit", "stop_app", "quit"]:
                print("[MQTT COMMAND] Remote exit triggered!")
                try:
                    client.publish(f"inhydro/{DEVICE_NAME}/command/status", json.dumps({"action": "exit", "status": "executing", "timestamp": time.time(), "source": "device"}), retain=False)
                except Exception: pass
                show_notification("REMOTE EXIT", "Remote exit command received. Shutting down system...", "error", duration_ms=4000)
                try: root.after(1500, quit_app)
                except: quit_app()
                return

            elif action in ["pause", "stop", "pause_room", "stop_room"]:
                target_room = new_data.get("room") or new_data.get("skey")
                if target_room and target_room in room_paused_states:
                    room_paused_states[target_room] = True
                    idx = int(target_room.replace('S', '')) - 1
                    set_relay((idx * 3) + 1, False)
                    set_relay((idx * 3) + 2, False)
                    set_relay((idx * 3) + 3, False)
                    system_config.setdefault('room_paused', {})[target_room] = True
                    save_config()
                    print(f"[MQTT COMMAND] Remote pause activated for {target_room}.")
                    show_notification(f"{get_sensor_display_name(target_room)} STOPPED", "Remote manual stop command activated.", "warning", duration_ms=3000)
                else:
                    for k in room_paused_states:
                        room_paused_states[k] = True
                        idx = int(k.replace('S', '')) - 1
                        set_relay((idx * 3) + 1, False)
                        set_relay((idx * 3) + 2, False)
                        set_relay((idx * 3) + 3, False)
                    system_config['room_paused'] = dict(room_paused_states)
                    save_config()
                    show_notification("ALL ROOMS STOPPED", "Remote manual stop command activated for all rooms.", "warning", duration_ms=3000)
                try:
                    client.publish(f"inhydro/{DEVICE_NAME}/command/status", json.dumps({"action": "pause", "status": "paused", "timestamp": time.time(), "source": "device"}), retain=False)
                except Exception: pass
                try: root.after(0, update_ui)
                except: pass
                return

            elif action in ["resume", "run", "start", "resume_room", "run_room"]:
                target_room = new_data.get("room") or new_data.get("skey")
                if target_room and target_room in room_paused_states:
                    room_paused_states[target_room] = False
                    system_config.setdefault('room_paused', {})[target_room] = False
                    save_config()
                    print(f"[MQTT COMMAND] Remote run/resume activated for {target_room}.")
                    show_notification(f"{get_sensor_display_name(target_room)} RUNNING", "Remote run command activated.", "success", duration_ms=3000)
                else:
                    for k in room_paused_states:
                        room_paused_states[k] = False
                    system_config['room_paused'] = dict(room_paused_states)
                    save_config()
                    show_notification("ALL ROOMS RUNNING", "Remote run command activated for all rooms.", "success", duration_ms=3000)
                try:
                    client.publish(f"inhydro/{DEVICE_NAME}/command/status", json.dumps({"action": "resume", "status": "running", "timestamp": time.time(), "source": "device"}), retain=False)
                except Exception: pass
                try: root.after(0, update_ui)
                except: pass
                return

        # 3. Sync Request Handling
        if topic == CONTROL_SYNC_TOPIC or topic.endswith("/setpoints/request_sync") or topic.endswith("/request_sync"):
            broadcast_current_state()
            return

        if not isinstance(new_data, dict):
            return

        # 4. Program Actions (Save / Delete / Apply)
        if "action" in new_data:
            p_action = str(new_data["action"]).lower().strip()
            if p_action in ["save_program", "add_program"]:
                p_room = new_data.get("room") or new_data.get("port") or "S1"
                p_name = str(new_data.get("program_name") or new_data.get("name") or "").strip()
                p_settings = new_data.get("settings")
                if p_room in SENSOR_MAP and p_name:
                    load_crop_programs()
                    if p_settings and isinstance(p_settings, dict):
                        prog_content = copy.deepcopy(p_settings)
                    else:
                        sp = get_setpoints(p_room)
                        prog_content = copy.deepcopy(sp.get("settings", {}))
                    crop_programs[p_name] = prog_content
                    if p_room not in crop_programs or not isinstance(crop_programs[p_room], dict):
                        crop_programs[p_room] = {}
                    crop_programs[p_room][p_name] = prog_content
                    save_crop_programs()

                    sp = get_setpoints(p_room)
                    sp["program_name"] = p_name
                    if p_settings and isinstance(p_settings, dict):
                        sp["settings"] = copy.deepcopy(p_settings)
                    save_setpoints()

                    sched_clean_snapshot = copy.deepcopy(sensor_setpoints)
                    sched_dirty_flag = False

                    print(f"[MQTT PROGRAM] Web saved and activated program '{p_name}' for {p_room}")
                    show_notification("Program Saved", f"Saved and activated '{p_name}' for {get_sensor_display_name(p_room)}", "success")
                    try:
                        root.after(0, update_ui)
                        root.after(0, update_preset_dropdown_text)
                        if frame_schedule.winfo_ismapped():
                            root.after(0, load_schedule_form)
                    except: pass
                    return

            elif p_action in ["delete_program", "remove_program"]:
                p_name = str(new_data.get("program_name") or new_data.get("name") or "").strip()
                if p_name:
                    load_crop_programs()
                    if p_name in crop_programs:
                        del crop_programs[p_name]
                    for rk in SENSOR_MAP.keys():
                        if rk in crop_programs and isinstance(crop_programs[rk], dict) and p_name in crop_programs[rk]:
                            del crop_programs[rk][p_name]
                    save_crop_programs()

                    for rk in SENSOR_MAP.keys():
                        sp = get_setpoints(rk)
                        if sp.get("program_name") == p_name:
                            sp["program_name"] = "Default Program"
                    save_setpoints()

                    sched_clean_snapshot = copy.deepcopy(sensor_setpoints)
                    sched_dirty_flag = False

                    print(f"[MQTT PROGRAM] Web deleted program '{p_name}'")
                    show_notification("Program Deleted", f"Deleted program '{p_name}'", "info")
                    try:
                        root.after(0, update_ui)
                        root.after(0, update_preset_dropdown_text)
                        if frame_schedule.winfo_ismapped():
                            root.after(0, load_schedule_form)
                    except: pass
                    return

            elif p_action in ["apply_program", "load_program"]:
                p_room = new_data.get("room") or new_data.get("port") or "S1"
                p_name = str(new_data.get("program_name") or new_data.get("name") or "").strip()
                if p_room in SENSOR_MAP and p_name:
                    all_progs = get_all_crop_programs()
                    p_settings = new_data.get("settings")
                    if p_settings and isinstance(p_settings, dict):
                        sensor_setpoints[p_room]["settings"] = copy.deepcopy(p_settings)
                        crop_programs[p_name] = copy.deepcopy(p_settings)
                        if p_room in crop_programs and isinstance(crop_programs[p_room], dict):
                            crop_programs[p_room][p_name] = copy.deepcopy(p_settings)
                        save_crop_programs()
                    elif p_name in all_progs:
                        sensor_setpoints[p_room]["settings"] = copy.deepcopy(all_progs[p_name])
                    
                    sensor_setpoints[p_room]["program_name"] = p_name
                    save_setpoints()
                    sched_clean_snapshot = copy.deepcopy(sensor_setpoints)
                    sched_dirty_flag = False
                    print(f"[MQTT PROGRAM] Web applied program '{p_name}' to {p_room}")
                    show_notification("Program Loaded", f"Applied and activated '{p_name}' for {get_sensor_display_name(p_room)}", "info")
                    try:
                        root.after(0, update_ui)
                        root.after(0, update_preset_dropdown_text)
                        if frame_schedule.winfo_ismapped():
                            root.after(0, load_schedule_form)
                    except: pass
                    return

            elif p_action == "stage_toggle":
                p_room = new_data.get("room") or new_data.get("port") or "S1"
                p_stage = new_data.get("stage") or "Setting A"
                p_enabled = new_data.get("enabled")
                if p_room in SENSOR_MAP and p_stage:
                    sp = get_setpoints(p_room)
                    st = sp.setdefault("settings", {}).setdefault(p_stage, {})
                    if p_enabled is not None:
                        st["enabled"] = bool(p_enabled)
                    else:
                        st["enabled"] = not st.get("enabled", True)
                    save_setpoints()
                    sched_clean_snapshot = copy.deepcopy(sensor_setpoints)
                    sched_dirty_flag = False
                    try:
                        root.after(0, update_ui)
                        if frame_schedule.winfo_ismapped():
                            root.after(0, load_schedule_form)
                    except: pass
                    broadcast_current_state()
                    print(f"[MQTT STAGE] Stage '{p_stage}' enabled={st['enabled']} for {p_room}")
                    return

        # 5. Setpoints, Programs & System Configuration Updates
        setpoints_modified = False

        # Check if full crop_programs map is passed from web
        if "crop_programs" in new_data and isinstance(new_data["crop_programs"], dict):
            load_crop_programs()
            crop_programs.update(new_data["crop_programs"])
            save_crop_programs()
            setpoints_modified = True

        # Check and apply system_config updates
        sys_config_updated = False
        if "system_config" in new_data and isinstance(new_data["system_config"], dict):
            system_config.update(new_data["system_config"])
            sys_config_updated = True
            
        for sc_k in ["upload_frequency_min", "upload_hours", "upload_mins", "upload_secs", "temp_alarm_offset", "humi_alarm_offset"]:
            if sc_k in new_data:
                try:
                    if sc_k in ["upload_hours", "upload_mins", "upload_secs"]:
                        system_config[sc_k] = int(float(new_data[sc_k]))
                    else:
                        system_config[sc_k] = float(new_data[sc_k])
                    sys_config_updated = True
                except Exception: pass

        if "sensor_names" in new_data and isinstance(new_data["sensor_names"], dict):
            system_config.setdefault("sensor_names", {}).update(new_data["sensor_names"])
            sys_config_updated = True

        if sys_config_updated:
            h = int(system_config.get("upload_hours", 0))
            m = int(system_config.get("upload_mins", 0))
            s = int(system_config.get("upload_secs", 0))
            if h == 0 and m == 0 and s == 0 and "upload_frequency_min" in system_config:
                total_sec = int(round(float(system_config.get("upload_frequency_min", 0)) * 60.0))
                if total_sec > 0:
                    h, m, s = total_sec // 3600, (total_sec % 3600) // 60, total_sec % 60
            h_norm, m_norm, s_norm = normalize_upload_values(h, m, s)
            total_sec = (h_norm * 3600) + (m_norm * 60) + s_norm
            system_config["upload_hours"] = h_norm
            system_config["upload_mins"] = m_norm
            system_config["upload_secs"] = s_norm
            system_config["upload_frequency_min"] = round(total_sec / 60.0, 4) if total_sec > 0 else 0
            system_config["upload_frequency_sec"] = total_sec if total_sec > 0 else 1
            save_config()
            print(f"[MQTT SYNC] Updated system_config from web: {system_config}")
            broadcast_current_state()

        # Check if sensor_setpoints map is passed
        if "sensor_setpoints" in new_data and isinstance(new_data["sensor_setpoints"], dict):
            for skey, s_val in new_data["sensor_setpoints"].items():
                if skey in SENSOR_MAP and isinstance(s_val, dict):
                    sp = get_setpoints(skey)
                    if "settings" in s_val:
                        sp["settings"] = s_val["settings"]
                    if "program_name" in s_val:
                        sp["program_name"] = str(s_val["program_name"]).strip()
                    if "crop_name" in s_val:
                        sp["crop_name"] = str(s_val["crop_name"]).strip()
                    if "setup_name" in s_val:
                        sp["setup_name"] = str(s_val["setup_name"]).strip()
                    for k in ["T MAX", "T MIN", "H MAX", "H MIN", "mode", "active_setting"]:
                        if k in s_val:
                            sp[k] = s_val[k]
                    setpoints_modified = True

        raw_port = str(new_data.get("port", "")).strip()
        m = _re.search(r'\d+', raw_port)
        if raw_port and m:
            target = f"S{m.group()}"
            skeys_to_update = [target] if target in SENSOR_MAP else []
        elif not raw_port and "sensor_setpoints" not in new_data and "settings" in new_data:
            skeys_to_update = list(SENSOR_MAP.keys())
        else:
            skeys_to_update = []

        for skey in skeys_to_update:
            sp = get_setpoints(skey)
            if "settings" in new_data:
                sp["settings"] = new_data["settings"]
                setpoints_modified = True
            if "program_name" in new_data:
                sp["program_name"] = str(new_data["program_name"]).strip()
                setpoints_modified = True
            if "crop_name" in new_data:
                sp["crop_name"] = str(new_data["crop_name"]).strip()
                setpoints_modified = True
            if "setup_name" in new_data:
                sp["setup_name"] = str(new_data["setup_name"]).strip()
                setpoints_modified = True
            for k in ["T MAX", "T MIN", "H MAX", "H MIN", "mode", "active_setting"]:
                if k in new_data:
                    sp[k] = new_data[k]
                    setpoints_modified = True

        if setpoints_modified:
            load_crop_programs()
            for skey in SENSOR_MAP.keys():
                sp = get_setpoints(skey)
                p_name = sp.get("program_name")
                if p_name and p_name != "Default Program" and sp.get("settings"):
                    crop_programs[p_name] = copy.deepcopy(sp["settings"])
                    if skey in crop_programs and isinstance(crop_programs[skey], dict):
                        crop_programs[skey][p_name] = copy.deepcopy(sp["settings"])
            save_crop_programs()
            save_setpoints()
            sched_clean_snapshot = copy.deepcopy(sensor_setpoints)
            sched_dirty_flag = False
            print(f"[MQTT SETPOINTS] Setpoints updated from web successfully")

            def _refresh():
                update_ui()
                update_preset_dropdown_text()
                if frame_schedule.winfo_ismapped():
                    load_schedule_form()
                elif frame_set.winfo_ismapped():
                    open_setpoints(active_detail_port)
            try: root.after(0, _refresh)
            except: pass
        elif sys_config_updated:
            try: root.after(0, update_ui)
            except: pass

    except Exception as e:
        print(f"[MQTT ERROR] {e}")

CONTROL_BROKER = "147.93.106.142"
CONTROL_PORT = 1883
CONTROL_USER = "Inhydro@5598"
CONTROL_PASS = "MGPL@5598"

is_mqtt_connected = False

def on_control_connect(client, userdata, flags, rc=0, properties=None, *args, **kwargs):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        for dev_id in list(set([DEVICE_NAME, DEVICE_NAME.lower(), "cold_room"])):
            client.subscribe(f"inhydro/{dev_id}/setpoints/update")
            client.subscribe(f"inhydro/{dev_id}/config/update")
            client.subscribe(f"inhydro/{dev_id}/command")
            client.subscribe(f"inhydro/{dev_id}/setpoints/request_sync")
            client.subscribe(f"inhydro/{dev_id}/request_sync")
            client.subscribe(f"inhydro/{dev_id}/programs/update")
        print(f"[MQTT] Connected & subscribed to incoming control topics for {DEVICE_NAME}")
        broadcast_current_state()
    else:
        is_mqtt_connected = False

def on_control_disconnect(client, userdata, *args, **kwargs):
    global is_mqtt_connected
    is_mqtt_connected = False
    print("[MQTT] Disconnected from broker. Auto-reconnecting in background...")

control_client.on_message = on_control_message
control_client.on_connect = on_control_connect
control_client.on_disconnect = on_control_disconnect
try:
    if CONTROL_USER and CONTROL_PASS:
        control_client.username_pw_set(CONTROL_USER, CONTROL_PASS)
    control_client.connect_async(CONTROL_BROKER, CONTROL_PORT, 60)
    control_client.loop_start()
except Exception as e: pass

def mqtt_heartbeat_worker():
    """Maintains 24/7 live MQTT connection and sends alive heartbeat every 10s so web can push setpoints anytime."""
    time.sleep(5)
    while running:
        try:
            time.sleep(10)
            if not running: break
            if 'control_client' in globals() and control_client and control_client.is_connected():
                now_dt = datetime.datetime.now(ist_tz)
                hb_payload = json.dumps({
                    "device": DEVICE_NAME,
                    "device_id": DEVICE_NAME,
                    "status": "online",
                    "timestamp": now_dt.isoformat(),
                    "time": now_dt.strftime("%Y-%m-%d %H:%M:%S")
                })
                control_client.publish(f"inhydro/{DEVICE_NAME}/heartbeat", hb_payload, retain=False)
                if DEVICE_NAME != DEVICE_NAME.lower():
                    control_client.publish(f"inhydro/{DEVICE_NAME.lower()}/heartbeat", hb_payload, retain=False)
                for fallback_id in ["cold_room", "cold_storage", "control123"]:
                    if DEVICE_NAME.lower() != fallback_id:
                        control_client.publish(f"inhydro/{fallback_id}/heartbeat", hb_payload, retain=False)
            elif 'control_client' in globals() and control_client and not control_client.is_connected():
                try:
                    control_client.reconnect()
                except Exception: pass
        except Exception:
            pass

threading.Thread(target=mqtt_heartbeat_worker, daemon=True).start()

cached_sensor_cfgs = {}

def set_relay(channel, state):
    global working_relay_id
    if relay_states.get(channel) == state:
        return True  # State already matches, skip redundant serial bus traffic

    relay_port = system_config.get('relay_port')
    if not relay_port or "PLACE" in relay_port or not os.path.exists(relay_port):
        return False
    
    ids_to_try = [working_relay_id] if working_relay_id is not None else POSSIBLE_RELAY_IDS
    for r_id in ids_to_try:
        if r_id is None: continue
        instrument = None
        try:
            instrument = minimalmodbus.Instrument(relay_port, r_id)
            instrument.serial.baudrate = RELAY_BAUD
            instrument.serial.timeout = 0.3
            instrument.serial.stopbits = 1
            instrument.serial.parity = minimalmodbus.serial.PARITY_NONE
            instrument.mode = minimalmodbus.MODE_RTU
            instrument.write_bit(channel - 1, 1 if state else 0, functioncode=5)
            working_relay_id = r_id
            relay_states[channel] = state
            return True 
        except Exception: pass
        finally:
            if instrument and hasattr(instrument, 'serial') and instrument.serial:
                try: instrument.serial.close()
                except: pass
    return False

def sensor_reader():
    global running, active_warnings, last_upload_time, last_local_save_time, working_relay_id, cached_sensor_cfgs, silenced_alarm_keys
    while running:
        system_config['relay_port'] = RELAY_PORT_FIXED
        
        # 1. READ ALL SENSORS (TEMP, HUMIDITY, CO2) WITH FAST CONFIG CACHE
        for skey, port in SENSOR_MAP.items():
            if not running: break
            sensor_id = int(skey.replace('S', ''))
            
            if not os.path.exists(port):
                with sensor_data_lock:
                    sensor_data[port] = {'id': sensor_id, 'status': 'OFFLINE'}
                continue

            time.sleep(DELAY_BETWEEN_PORTS)
            instrument = None
            try:
                values = None

                # A. Try known cached parameter first (fast path ~10ms)
                if port in cached_sensor_cfgs:
                    cfg = cached_sensor_cfgs[port]
                    try:
                        inst = minimalmodbus.Instrument(port, cfg['slave_id'])
                        inst.serial.baudrate = cfg['baud']
                        inst.serial.timeout = 0.2
                        inst.close_port_after_each_call = True
                        res = inst.read_registers(cfg['addr'], 2, functioncode=cfg['fc'])
                        if res and len(res) >= 2 and (res[0] > 0 or res[1] > 0):
                            values = res
                    except Exception:
                        cached_sensor_cfgs.pop(port, None)

                # B. Fallback auto-scan if not cached
                if not values:
                    for baud in [9600, 4800]:
                        for slave_id in [SLAVE_ID, 1, 2, 3, 255]:
                            try:
                                inst = minimalmodbus.Instrument(port, slave_id)
                                inst.serial.baudrate = baud
                                inst.serial.timeout = 0.15
                                inst.close_port_after_each_call = True
                                for fc in [4, 3]:
                                    for addr in [0, 1]:
                                        try:
                                            res = inst.read_registers(addr, 2, functioncode=fc)
                                            if res and len(res) >= 2 and (res[0] > 0 or res[1] > 0):
                                                values = res
                                                cached_sensor_cfgs[port] = {'baud': baud, 'slave_id': slave_id, 'fc': fc, 'addr': addr}
                                                break
                                        except Exception: pass
                                    if values: break
                                if values: break
                            except Exception: pass
                        if values: break

                if not values or len(values) < 2:
                    raise ValueError("MD02 Modbus Read Failed")

                val0 = values[0] / 10.0
                val1 = values[1] / 10.0
                if val0 > 999: val0 /= 10.0
                if val1 > 999: val1 /= 10.0

                # Intelligent Auto-Detection of Temp & Humidity Registers
                if val0 > val1 and val0 > 45.0:
                    humi, temp = val0, val1
                else:
                    temp, humi = val0, val1

                # Optional CO2 Sensor Read
                co2 = None
                co2_port = CO2_SENSOR_MAP.get(skey, "")
                if co2_port and "PLACEHOLDER" not in co2_port and os.path.exists(co2_port):
                    try:
                        co2_inst = minimalmodbus.Instrument(co2_port, SLAVE_ID)
                        co2_inst.serial.baudrate = BAUDRATE
                        co2_inst.serial.timeout = 0.3
                        try: co2_vals = co2_inst.read_registers(0, 2, functioncode=4)
                        except Exception: co2_vals = co2_inst.read_registers(1, 2, functioncode=4)
                        if co2_vals:
                            raw_co2 = float(co2_vals[0])
                            if raw_co2 > 5000: raw_co2 /= 10.0
                            co2 = raw_co2
                        co2_inst.serial.close()
                    except Exception: pass

                if skey == "S2": humi += 6.5
                if skey == "S3": humi -= 6.0
                if skey == "S4": humi += 2.8

                with sensor_data_lock:
                    sensor_data[port] = {
                        'id': sensor_id,
                        'temp': round(temp, 1),
                        'humi': round(humi, 1),
                        'co2': round(co2, 1) if co2 is not None else None,
                        'status': 'OK'
                    }
            except Exception:
                with sensor_data_lock:
                    sensor_data[port] = {'id': sensor_id, 'status': 'ERROR'}
            finally:
                if instrument and hasattr(instrument, 'serial') and instrument.serial:
                    try: instrument.serial.close()
                    except: pass
        
        # 2. EVALUATE RTC CALENDAR & TIME SLOTS FOR RELAYS & WARNINGS
        current_warnings = []
        current_alarm_keys = set()
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_str = datetime.datetime.now(ist_tz).strftime("%H:%M")
        
        if os.path.exists(RELAY_PORT_FIXED):
            temp_alarm_offset = float(system_config.get('temp_alarm_offset', 5.0))
            humi_alarm_offset = float(system_config.get('humi_alarm_offset', 5.0))

            for skey, port in SENSOR_MAP.items():
                idx = int(skey.replace('S', '')) - 1
                ch_f = (idx * 3) + 1        # S1→ch1, S2→ch4, S3→ch7, S4→ch10, S5→ch13, S6→ch16, S7→ch19
                ch_h = (idx * 3) + 2        # S1→ch2, S2→ch5, S3→ch8, S4→ch11, S5→ch14, S6→ch17, S7→ch20
                ch_l = (idx * 3) + 3        # S1→ch3, S2→ch6, S3→ch9, S4→ch12, S5→ch15, S6→ch18, S7→ch21

                # Check if this individual room is manually stopped
                if is_room_paused(skey):
                    set_relay(ch_f, False)
                    set_relay(ch_h, False)
                    set_relay(ch_l, False)
                    continue

                sp_eval = get_active_setpoints(skey)
                
                # Dedicated Photoperiod Lighting Relay Control for THIS Room
                p_on_24 = format_time_24h(sp_eval.get("photoperiod_on", "06:00 AM"))
                p_off_24 = format_time_24h(sp_eval.get("photoperiod_off", "08:00 PM"))
                l_enabled = sp_eval.get("lighting_enabled", True)
                
                room_light_state = l_enabled and ((p_on_24 <= now_str <= p_off_24) if p_on_24 <= p_off_24 else (now_str >= p_on_24 or now_str <= p_off_24))
                set_relay(ch_l, room_light_state)

                with sensor_data_lock:
                    data = sensor_data.get(port, {'status': 'OFFLINE'})

                if data.get('status') == 'OK':
                    t, h = data['temp'], data['humi']
                    t_target, h_target = sp_eval['target_temp'], sp_eval['target_humi']
                    t_min, t_max = sp_eval['T MIN'], sp_eval['T MAX']
                    h_min, h_max = sp_eval['H MIN'], sp_eval['H MAX']

                    if t >= t_max: set_relay(ch_f, True)
                    elif t <= t_min: set_relay(ch_f, False)

                    if h >= h_max: set_relay(ch_h, True)
                    elif h <= h_min: set_relay(ch_h, False)

                    # Temperature Alarms
                    if t >= (t_target + temp_alarm_offset):
                        msg = f"{get_sensor_display_name(skey)} High Temp ({t:.1f}°C > {t_target + temp_alarm_offset:.1f}°C)"
                        current_warnings.append(msg); current_alarm_keys.add(f"{skey}:HighTemp")
                        log_alarm_event(skey, msg, t, t_target)
                    elif t <= (t_target - temp_alarm_offset):
                        msg = f"{get_sensor_display_name(skey)} Low Temp ({t:.1f}°C < {t_target - temp_alarm_offset:.1f}°C)"
                        current_warnings.append(msg); current_alarm_keys.add(f"{skey}:LowTemp")
                        log_alarm_event(skey, msg, t, t_target)
                    
                    # Humidity Alarms
                    if h >= (h_target + humi_alarm_offset):
                        msg = f"{get_sensor_display_name(skey)} High Humidity ({h:.1f}% > {h_target + humi_alarm_offset:.1f}%)"
                        current_warnings.append(msg); current_alarm_keys.add(f"{skey}:HighHumi")
                        log_alarm_event(skey, msg, h, h_target)
                    elif h <= (h_target - humi_alarm_offset):
                        msg = f"{get_sensor_display_name(skey)} Low Humidity ({h:.1f}% < {h_target - humi_alarm_offset:.1f}%)"
                        current_warnings.append(msg); current_alarm_keys.add(f"{skey}:LowHumi")
                        log_alarm_event(skey, msg, h, h_target)
                else:
                    set_relay(ch_f, False)
                    set_relay(ch_h, False)

        # Buzzer Trigger with 30s Auto-Silence: only fires on new/distinct alarm occurrences
        if current_alarm_keys - silenced_alarm_keys:
            trigger_buzzer_30s()
        silenced_alarm_keys = set(current_alarm_keys)

        active_warnings = current_warnings
        
        # User Configurable Cloud Upload Frequency (HOUR : MIN : SEC)
        h = int(system_config.get('upload_hours', 0))
        m = int(system_config.get('upload_mins', 0))
        s = int(system_config.get('upload_secs', 0))
        upload_freq_sec = (h * 3600) + (m * 60) + s
        if upload_freq_sec <= 0:
            freq_min = system_config.get('upload_frequency_min', 0)
            try: upload_freq_sec = float(freq_min) * 60.0
            except Exception: upload_freq_sec = 1.0

        if upload_freq_sec <= 0:
            upload_freq_sec = 1.0  # Per-second real-time streaming

        curr_time = time.time()
        is_cloud_live = ('control_client' in globals() and control_client and control_client.is_connected())

        # When upload frequency is set to longer intervals (e.g. 1 hour) or when offline,
        # record continuous snapshot locally every 1 second so the entire timeline is preserved
        if upload_freq_sec > 1.0 or not is_cloud_live:
            if curr_time - last_local_save_time >= 1.0:
                save_local_telemetry()
                last_local_save_time = curr_time

        if curr_time - last_upload_time >= upload_freq_sec:
            broadcast_current_state()
            last_upload_time = curr_time

        time.sleep(1)

root = tk.Tk()
root.update()
root.attributes("-fullscreen", True)
root.configure(bg="white")
root.bind("<Escape>", lambda e: root.destroy())

big = font.Font(family="Arial", size=20, weight="bold")
med = font.Font(family="Arial", size=14, weight="bold")
small = font.Font(family="Arial", size=11, weight="bold")

# STANDARD UNIFORM BUTTON STYLES
BTN_FONT_MAIN = ("Helvetica", 12, "bold")
BTN_FONT_INLINE = ("Helvetica", 11, "bold")
BTN_FONT_CARD = ("Helvetica", 10, "bold")

FRAME_BTN_WIDTH = 18
FRAME_BTN_HEIGHT = 2

frame_main = tk.Frame(root, bg="white")
frame_set = tk.Frame(root, bg="white")
frame_schedule = tk.Frame(root, bg="white")
frame_detail = tk.Frame(root, bg="white")

def add_logo(parent):
    try:
        path = os.path.join(BASE_DIR, "logo.png")
        if os.path.exists(path):
            img = Image.open(path)
            width, height = 150, 60 
            img = img.resize((width, height), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(parent, image=photo, bg="white")
            lbl.image = photo 
            lbl.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=15)
            lbl.lift()
            return lbl
    except Exception as e: pass
    return None

def add_top_left_exit(parent):
    btn_exit = tk.Button(
        parent,
        text="✖ EXIT",
        font=("Helvetica", 12, "bold"),
        bg="#dc2626",
        fg="white",
        activebackground="#b91c1c",
        activeforeground="white",
        relief="flat",
        bd=0,
        padx=16,
        pady=12,
        cursor="hand2",
        command=quit_app
    )
    btn_exit.place(relx=0.0, rely=0.0, anchor="nw", x=20, y=15)
    btn_exit.lift()
    return btn_exit

clock_labels = []

def add_bottom_right_clock(parent, bg_color="white"):
    lbl = tk.Label(
        parent,
        text=" Day, DD-MM-YYYY\n hh:mm:ss AM/PM (IST)",
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

# ==========================================
# MODERN TOUCH NOTIFICATION & DIALOG SYSTEM
# ==========================================
active_notification_frame = None
notification_timer_id = None

def show_notification(title, message, ntype="success", duration_ms=3000):
    """
    Simple, clean touch notification popup with white background and black text.
    """
    global active_notification_frame, notification_timer_id

    if notification_timer_id is not None:
        try: root.after_cancel(notification_timer_id)
        except Exception: pass
        notification_timer_id = None

    if active_notification_frame and active_notification_frame.winfo_exists():
        try: active_notification_frame.destroy()
        except Exception: pass
        active_notification_frame = None

    icons = {
        "success": "✔",
        "warning": "⚠",
        "error": "✖",
        "info": "ℹ"
    }
    icon_sym = icons.get(ntype, "ℹ")

    # Simple white card with clean black border
    toast = tk.Frame(root, bg="#000000", bd=0, padx=2, pady=2)
    active_notification_frame = toast

    inner = tk.Frame(toast, bg="#ffffff", padx=18, pady=12)
    inner.pack(fill="both", expand=True)

    # Icon indicator in black
    badge_lbl = tk.Label(
        inner,
        text=f" {icon_sym} ",
        font=("Helvetica", 14, "bold"),
        bg="#ffffff",
        fg="#000000",
        padx=4,
        pady=2
    )
    badge_lbl.pack(side="left", padx=(0, 10))

    # Text Column in pure black
    text_f = tk.Frame(inner, bg="#ffffff")
    text_f.pack(side="left", fill="both", expand=True, padx=(0, 16))

    lbl_t = tk.Label(
        text_f,
        text=title.upper(),
        font=("Helvetica", 11, "bold"),
        fg="#000000",
        bg="#ffffff",
        anchor="w"
    )
    lbl_t.pack(anchor="w")

    lbl_m = tk.Label(
        text_f,
        text=message,
        font=("Helvetica", 10, "bold"),
        fg="#000000",
        bg="#ffffff",
        anchor="w",
        wraplength=480,
        justify="left"
    )
    lbl_m.pack(anchor="w", pady=(2, 0))

    def dismiss():
        global active_notification_frame, notification_timer_id
        if notification_timer_id is not None:
            try: root.after_cancel(notification_timer_id)
            except Exception: pass
            notification_timer_id = None
        if toast and toast.winfo_exists():
            try: toast.destroy()
            except Exception: pass
        active_notification_frame = None

    btn_close = tk.Button(
        inner,
        text="✖",
        font=("Helvetica", 11, "bold"),
        bg="#ffffff",
        fg="#000000",
        activebackground="#f1f5f9",
        activeforeground="#000000",
        relief="flat",
        bd=0,
        cursor="hand2",
        padx=8,
        pady=4,
        command=dismiss
    )
    btn_close.pack(side="right", padx=(4, 0))

    for w in (toast, inner, badge_lbl, text_f, lbl_t, lbl_m):
        w.bind("<Button-1>", lambda e: dismiss())

    toast.place(relx=0.5, rely=0.03, anchor="n")
    toast.lift()

    if duration_ms > 0:
        notification_timer_id = root.after(duration_ms, dismiss)

def show_confirm_dialog(title, message, on_confirm, on_cancel=None, parent=None, confirm_text="✔ YES, PROCEED", cancel_text="✖ CANCEL"):
    """
    Simple, clean confirmation dialog with white screen background and grey card box.
    """
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

    tk.Button(btns, text=confirm_text, font=("Helvetica", 11, "bold"), bg="#2e7d32" if ("OK" in confirm_text or "YES" in confirm_text or "SAVE" in confirm_text) else "#1e293b", fg="#ffffff",
              activebackground="#15803d", activeforeground="#ffffff", relief="flat", bd=0, padx=22, pady=10, cursor="hand2", command=_yes).pack(side="left", padx=12)

    tk.Button(btns, text=cancel_text, font=("Helvetica", 11, "bold"), bg="#64748b", fg="#ffffff",
              activebackground="#475569", activeforeground="#ffffff", relief="flat", bd=0, padx=22, pady=10, cursor="hand2", command=_no).pack(side="left", padx=12)

def show(frame):
    for f in [frame_main, frame_set, frame_schedule, frame_detail]:
        f.pack_forget()
    frame.pack(fill="both", expand=True)
    add_logo(frame)
    add_top_left_exit(frame)
    if frame != frame_main:
        add_bottom_right_clock(frame)
    if active_notification_frame and active_notification_frame.winfo_exists():
        active_notification_frame.lift()


# --- MAIN DASHBOARD HEADER ---
lbl_title = tk.Label(frame_main, text="INHYDRO COLD ROOM DASHBOARD", font=big, fg="#1565c0", bg="white")
lbl_title.pack(pady=(40, 8))

# Live Warning Bar
lbl_warning_bar = tk.Label(frame_main, text="SYSTEM NORMAL", font=med, bg="#2e7d32", fg="white", height=2)
lbl_warning_bar.pack(fill="x", padx=15, pady=5)

sensors_grid = tk.Frame(frame_main, bg="white")
sensors_grid.pack(pady=10)
sensor_widgets = {}

footer_main = tk.Frame(frame_main, bg="#eeeeee", height=80)
footer_main.pack(side="bottom", fill="x")
footer_main.pack_propagate(False)

btn_sched_slots = tk.Button(footer_main, text="SCHEDULE SLOTS", font=BTN_FONT_MAIN, width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, bg="#0284c7", fg="white", cursor="hand2", command=lambda: open_schedule_editor("S1"))
btn_sched_slots.pack(side="left", padx=15, pady=10)

btn_sys_settings = tk.Button(footer_main, text="SYSTEM SETTINGS", font=BTN_FONT_MAIN, width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, bg="#0891b2", fg="white", cursor="hand2", command=lambda: open_system_settings_modal())
btn_sys_settings.pack(side="left", padx=15, pady=10)

btn_restart_app = tk.Button(footer_main, text="RESTART", font=BTN_FONT_MAIN, width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, bg="#1565c0", fg="white", cursor="hand2", command=lambda: restart_program())
btn_restart_app.pack(side="left", padx=15, pady=10)

lbl_clock = tk.Label(footer_main, text="Day, DD-MM-YYYY\n hh:mm:ss AM/PM (IST)", font=("Helvetica", 11, "bold"), fg="#00897b", bg="#eeeeee", justify="right")
lbl_clock.pack(side="right", padx=15, pady=5)

def update_clock_display():
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist_tz)
    now_str = now.strftime(" %A, %d-%m-%Y\n %I:%M:%S %p (IST)")
    if 'lbl_clock' in globals() and lbl_clock.winfo_exists():
        lbl_clock.config(text=now_str)
    for lbl in list(clock_labels):
        try:
            if lbl.winfo_exists():
                lbl.config(text=now_str)
            else:
                clock_labels.remove(lbl)
        except Exception: pass
    root.after(1000, update_clock_display)

def rebuild_grid():
    for i in range(10): 
        sensors_grid.columnconfigure(i, weight=0)
        sensors_grid.rowconfigure(i, weight=0)
    idx = 0
    for skey in sorted(SENSOR_MAP.keys()):
        if skey in sensor_widgets:
            r, c = idx // 4, idx % 4
            sensor_widgets[skey].grid(row=r, column=c, padx=8, pady=8)
            idx += 1

# --- TELEMETRY & LOCAL LOGGING ---
LOG_DIR = os.path.join(BASE_DIR, "local_logs")
ACTIVE_LOG_FILE = os.path.join(LOG_DIR, "active.jsonl")
local_log_lock = threading.Lock()
last_local_save_time = 0

def save_local_telemetry():
    """Captures a complete snapshot of all rooms (S1-S7) and relays, persisting to local disk."""
    try:
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ts_str = datetime.datetime.now(ist_tz).strftime("%Y-%m-%d %H:%M:%S")

        with sensor_data_lock:
            snap_sensor_data = dict(sensor_data)

        norm_rooms = {}
        for idx, (skey, port) in enumerate(SENSOR_MAP.items()):
            d = snap_sensor_data.get(port)
            if d and d.get('status') == 'OK':
                norm_rooms[skey] = {
                    "id": idx + 1,
                    "t": d.get('temp', 0.0),
                    "h": d.get('humi', 0.0),
                    "co2": d.get('co2'),
                    "status": "OK"
                }
            elif d and d.get('status') == 'ERROR':
                norm_rooms[skey] = {"id": idx + 1, "t": 0.0, "h": 0.0, "co2": None, "status": "ERROR"}
            else:
                norm_rooms[skey] = {"id": idx + 1, "t": 0.0, "h": 0.0, "co2": None, "status": "OFFLINE"}

        record = {
            "device": DEVICE_NAME,
            "device_id": DEVICE_NAME,
            "timestamp": ts_str,
            "sensor_data": norm_rooms,
            "S1": norm_rooms.get("S1"),
            "S2": norm_rooms.get("S2"),
            "S3": norm_rooms.get("S3"),
            "S4": norm_rooms.get("S4"),
            "S5": norm_rooms.get("S5"),
            "S6": norm_rooms.get("S6"),
            "S7": norm_rooms.get("S7"),
            "relay_states": dict(relay_states)
        }

        def write_thread(rec):
            with local_log_lock:
                try:
                    os.makedirs(LOG_DIR, exist_ok=True)
                    with open(ACTIVE_LOG_FILE, "a") as f:
                        f.write(json.dumps(rec) + "\n")

                    # Rotate log file if exceeds ~1.5 MB
                    if os.path.exists(ACTIVE_LOG_FILE) and os.path.getsize(ACTIVE_LOG_FILE) > 1500000:
                        rot_name = os.path.join(LOG_DIR, f"log_{int(time.time())}.jsonl")
                        os.rename(ACTIVE_LOG_FILE, rot_name)
                except Exception as e:
                    print(f"[LocalLog] Save error: {e}")

        threading.Thread(target=write_thread, args=(record,), daemon=True).start()
    except Exception as e:
        print(f"[LocalLog] Exception: {e}")

def sync_offline_data_worker():
    """Background daemon that flushes locally recorded historical and offline telemetry to the cloud."""
    time.sleep(10)
    while running:
        try:
            time.sleep(12)
            if not running: break

            is_connected = False
            if 'control_client' in globals() and control_client:
                try: is_connected = control_client.is_connected()
                except Exception: is_connected = False

            if not is_connected or not os.path.exists(LOG_DIR):
                continue

            # Check if active.jsonl has data and rotate it for syncing
            if os.path.exists(ACTIVE_LOG_FILE) and os.path.getsize(ACTIVE_LOG_FILE) > 0:
                with local_log_lock:
                    rot_name = os.path.join(LOG_DIR, f"log_{int(time.time())}.jsonl")
                    try: os.rename(ACTIVE_LOG_FILE, rot_name)
                    except Exception: pass

            log_files = [f for f in os.listdir(LOG_DIR) if f.startswith("log_") and f.endswith(".jsonl")]
            log_files.sort()

            for fname in log_files:
                fpath = os.path.join(LOG_DIR, fname)
                rows = []
                with local_log_lock:
                    if os.path.exists(fpath):
                        try:
                            with open(fpath, "r") as f:
                                for line in f:
                                    line = line.strip()
                                    if line:
                                        try:
                                            parsed = json.loads(line)
                                            if isinstance(parsed, dict) and ("timestamp" in parsed or "sensor_data" in parsed):
                                                rows.append(parsed)
                                            elif isinstance(parsed, list) and len(parsed) == 2 and isinstance(parsed[1], dict):
                                                item = parsed[1]
                                                item["timestamp"] = parsed[0]
                                                rows.append(item)
                                        except Exception: pass
                        except Exception as re:
                            print(f"[OfflineSync] Error reading {fname}: {re}")

                if not rows:
                    try: os.remove(fpath)
                    except Exception: pass
                    continue

                print(f"[OfflineSync] Syncing {len(rows)} local historical records from {fname} to cloud database...")
                batch_size = 150
                all_sent = True

                for idx in range(0, len(rows), batch_size):
                    batch = rows[idx:idx+batch_size]
                    if not control_client.is_connected():
                        all_sent = False
                        break

                    try:
                        batch_json = json.dumps(batch)
                        control_client.publish(f"inhydro/{DEVICE_NAME}/telemetry/live", batch_json, qos=1)
                        if DEVICE_NAME != DEVICE_NAME.lower():
                            control_client.publish(f"inhydro/{DEVICE_NAME.lower()}/telemetry/live", batch_json, qos=1)
                        time.sleep(0.1)
                    except Exception as pe:
                        print(f"[OfflineSync] Batch publish error: {pe}")
                        all_sent = False
                        break

                if all_sent:
                    with local_log_lock:
                        if os.path.exists(fpath):
                            try: os.remove(fpath)
                            except Exception: pass
                    print(f"[OfflineSync] Successfully synced and cleared {fname}")

        except Exception as ex:
            print(f"[OfflineSync] Worker loop exception: {ex}")
            time.sleep(10)

# --- MAIN UI UPDATE LOOP ---
def update_ui():
    if not running: return
    try:
        grid_changed = False
        for skey, port in SENSOR_MAP.items():
            if skey not in sensor_widgets:
                disp_name = get_sensor_display_name(skey)
                
                b_room = tk.Button(sensors_grid, bg="#1565c0", bd=3, relief="raised",
                                   text=f"{disp_name}\n[INITIALIZING]", font=font.Font(size=10, weight="bold"), 
                                   fg="white", width=20, height=8,
                                   command=lambda p=port: open_sensor_detail(p))

                sensor_widgets[skey] = b_room
                grid_changed = True

        if grid_changed: rebuild_grid()

        with sensor_data_lock: snap = dict(sensor_data)

        # Update Unified Grid Box per Sensor / Room
        for skey, port in SENSOR_MAP.items():
            if skey in sensor_widgets:
                btn_room = sensor_widgets[skey]
                
                d = snap.get(port)
                disp_name = get_sensor_display_name(skey)
                sp_eval = get_active_setpoints(skey)
                
                prog_name = sp_eval.get('program_name') or 'Default Program'
                stage_name = sp_eval.get('stage_name') or sp_eval.get('setting_name') or 'Crop Stage 1'
                slot_name = sp_eval.get('slot_name') or f"Slot {sp_eval.get('slot_id', 1)}"
                slot_id = sp_eval.get('slot_id', 1)
                t_min, t_max = sp_eval['T MIN'], sp_eval['T MAX']
                h_min, h_max = sp_eval['H MIN'], sp_eval['H MAX']
                t_target = sp_eval['target_temp']
                h_target = sp_eval['target_humi']

                if is_room_paused(skey):
                    if d and d.get('status') == 'OK':
                        t, h = d['temp'], d['humi']
                        c_val = d.get('co2')
                        co2_str = f"{c_val:.1f} ppm" if (c_val is not None and c_val > 0) else "N/A"
                        box_text = (
                            f"{disp_name}\n"
                            f"● MANUAL STOPPED ●\n"
                            f"Temp: {t:.1f}°C\n"
                            f"Humi: {h:.1f}%\n"
                            f"CO2: {co2_str}\n"
                            f"[RELAYS OFF]"
                        )
                    elif d and d.get('status') == 'ERROR':
                        box_text = f"{disp_name}\n● MANUAL STOPPED ●\n[SENSOR ERROR]\n[RELAYS OFF]"
                    else:
                        box_text = f"{disp_name}\n● MANUAL STOPPED ●\n[OFFLINE]\n[RELAYS OFF]"
                    btn_room.config(text=box_text, bg="#b45309")

                elif d and d.get('status') == 'OK':
                    t, h = d['temp'], d['humi']
                    c_val = d.get('co2')
                    co2_str = f"{c_val:.1f} ppm" if (c_val is not None and c_val > 0) else "N/A"

                    box_text = (
                        f"{disp_name}\n"
                        f"{prog_name}\n"
                        f"[{stage_name} - {slot_name}]\n"
                        f"Temp: {t:.1f}°C (Set: {t_target:.1f}°C)\n"
                        f"Humi: {h:.1f}%  (Set: {h_target:.1f}%)\n"
                        f"CO2: {co2_str}"
                    )
                    
                    is_t_ok = (t_min <= t <= t_max)
                    is_h_ok = (h_min <= h <= h_max)

                    if is_t_ok and is_h_ok:
                        btn_room.config(text=box_text, bg="#2e7d32")
                    else:
                        btn_room.config(text=box_text, bg="#c62828")

                elif d and d.get('status') == 'ERROR':
                    btn_room.config(text=f"{disp_name}\n[SENSOR ERROR]", bg="#b71c1c")
                else:
                    btn_room.config(text=f"{disp_name}\n[OFFLINE]", bg="#424242")

        # Update Warning Bar
        if active_warnings:
            lbl_warning_bar.config(
                text=" WARNING: " + " | ".join(active_warnings[:2]),
                bg="#c62828", fg="white"
            )
        else:
            lbl_warning_bar.config(
                text=" SYSTEM NORMAL — ALL PARAMETERS WITHIN RTC SCHEDULED SETPOINTS",
                bg="#2e7d32", fg="white"
            )

        # Update Detail View if open
        if frame_detail.winfo_ismapped() and active_detail_port:
            d = snap.get(active_detail_port)
            skey = next((k for k, v in SENSOR_MAP.items() if v == active_detail_port), "S1")
            update_detail_pause_button(skey)
            sp_eval = get_active_setpoints(skey)
            idx = int(skey.replace('S', '')) - 1
            mapped_f, mapped_h, mapped_l = (idx * 3) + 1, (idx * 3) + 2, (idx * 3) + 3
            
            f_s = "ON" if relay_states.get(mapped_f) else "OFF"
            h_s = "ON" if relay_states.get(mapped_h) else "OFF"
            l_s = "ON" if relay_states.get(mapped_l) else "OFF"
            
            p_on = sp_eval.get('photoperiod_on', '06:00 AM')
            p_off = sp_eval.get('photoperiod_off', '08:00 PM')
            slot_start = format_time_12h(sp_eval.get('start', '08:00 AM'))
            slot_stop = format_time_12h(sp_eval.get('stop', '12:00 PM'))

            t_min, t_max = sp_eval['T MIN'], sp_eval['T MAX']
            h_min, h_max = sp_eval['H MIN'], sp_eval['H MAX']

            prog_name = sp_eval.get('program_name') or 'Default Program'
            stage_name = sp_eval.get('stage_name') or sp_eval.get('setting_name') or 'Crop Stage 1'
            slot_id = sp_eval.get('slot_id', 1)
            slot_name = sp_eval.get('slot_name') or f"Slot {slot_id}"

            txt_detail_data.config(state="normal")
            txt_detail_data.delete("1.0", "end")

            # 1. Room Name & Status (Black / Red)
            room_disp = get_sensor_display_name(skey)
            if is_room_paused(skey):
                txt_detail_data.insert("end", f"{room_disp}\n", "black")
                txt_detail_data.insert("end", "● MANUAL STOPPED (AUTOMATION PAUSED) ●\n\n", "red")
            else:
                txt_detail_data.insert("end", f"{room_disp}\n\n", "black")

            # 2. Live Data (Black label, Blue data value, Red error/NA)
            if d and d.get('status') == 'OK':
                txt_detail_data.insert("end", "TEMP: ", "black")
                txt_detail_data.insert("end", f"{d['temp']:.1f} °C\n", "blue")
                
                txt_detail_data.insert("end", "HUMI: ", "black")
                txt_detail_data.insert("end", f"{d['humi']:.1f} %\n", "blue")
                
                txt_detail_data.insert("end", "CO2:  ", "black")
                c_val = d.get('co2')
                if c_val is not None and c_val > 0:
                    txt_detail_data.insert("end", f"{c_val:.1f} ppm\n\n", "blue")
                else:
                    txt_detail_data.insert("end", "N/A\n\n", "red")
            else:
                txt_detail_data.insert("end", "TEMP: ", "black")
                txt_detail_data.insert("end", "OFFLINE\n", "red")
                txt_detail_data.insert("end", "HUMI: ", "black")
                txt_detail_data.insert("end", "OFFLINE\n", "red")
                txt_detail_data.insert("end", "CO2:  ", "black")
                txt_detail_data.insert("end", "N/A\n\n", "red")

            # 3. Program, Stage, Slot, Active Window (Black label, Blue value)
            txt_detail_data.insert("end", "Program: ", "black")
            txt_detail_data.insert("end", f"{prog_name}\n", "blue")
            
            txt_detail_data.insert("end", "Stage:   ", "black")
            txt_detail_data.insert("end", f"{stage_name}\n", "blue")

            txt_detail_data.insert("end", "Slot:    ", "black")
            txt_detail_data.insert("end", f"{slot_name}\n", "blue")
            
            txt_detail_data.insert("end", "Active Window: ", "black")
            txt_detail_data.insert("end", f"{slot_start} - {slot_stop}\n\n", "blue")

            # 4. Target, Min, Max (Black labels for TARGET, MIN, MAX; Blue for numeric values)
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

            # 5. Light Schedule (Black label, Blue value)
            txt_detail_data.insert("end", "Light Schedule: ", "black")
            txt_detail_data.insert("end", f"{p_on} - {p_off}\n\n", "blue")

            # 6. Relays Status (Black label, Green ON / Red OFF / Stopped)
            if is_room_paused(skey):
                txt_detail_data.insert("end", f"{get_f_name(skey)}: ", "black")
                txt_detail_data.insert("end", "STOPPED (OFF)\n", "red")
                txt_detail_data.insert("end", "Humidifier: ", "black")
                txt_detail_data.insert("end", "STOPPED (OFF)\n", "red")
                txt_detail_data.insert("end", "Grow Lights: ", "black")
                txt_detail_data.insert("end", "STOPPED (OFF)\n", "red")
            else:
                txt_detail_data.insert("end", f"{get_f_name(skey)}: ", "black")
                txt_detail_data.insert("end", f"{f_s}\n", "green" if f_s == "ON" else "red")
                txt_detail_data.insert("end", "Humidifier: ", "black")
                txt_detail_data.insert("end", f"{h_s}\n", "green" if h_s == "ON" else "red")
                txt_detail_data.insert("end", "Grow Lights: ", "black")
                txt_detail_data.insert("end", f"{l_s}\n", "green" if l_s == "ON" else "red")

            txt_detail_data.config(state="disabled")

    except Exception as e: print(f"UI Error: {e}")

    root.after(1000, update_ui)

# --- SENSOR DETAIL VIEW UI ---
active_detail_port = None
lbl_detail_title = tk.Label(frame_detail, text="COLD ROOM DATA", font=big, fg="#1565c0", bg="white")
lbl_detail_title.pack(pady=5)

txt_detail_data = tk.Text(frame_detail, font=font.Font(size=12, weight="bold"), bg="white", bd=0, highlightthickness=0, height=18, width=65)
txt_detail_data.pack(pady=5, expand=True, fill="both")
txt_detail_data.tag_configure("black", foreground="#000000", justify="center")
txt_detail_data.tag_configure("blue", foreground="#1565c0", justify="center")
txt_detail_data.tag_configure("green", foreground="#16a34a", justify="center")
txt_detail_data.tag_configure("red", foreground="#c62828", justify="center")

def update_detail_pause_button(skey):
    if 'btn_room_pause' in globals() and btn_room_pause.winfo_exists():
        if is_room_paused(skey):
            btn_room_pause.config(text="RESTART/RUN", bg="#2e7d32")
        else:
            btn_room_pause.config(text="MANUAL STOP", bg="#c62828")

def toggle_active_room_pause():
    if active_detail_port:
        skey = next((k for k, v in SENSOR_MAP.items() if v == active_detail_port), "S1")
        toggle_room_pause(skey)
        update_detail_pause_button(skey)

def open_sensor_detail(port):
    global active_detail_port; active_detail_port = port
    skey = next((k for k, v in SENSOR_MAP.items() if v == port), "S1")
    lbl_detail_title.config(text=get_sensor_display_name(skey))
    update_detail_pause_button(skey)
    show(frame_detail)

def edit_active_room_name_detail():
    skey = next((k for k, v in SENSOR_MAP.items() if v == active_detail_port), "S1")
    curr_name = get_sensor_display_name(skey)
    def on_confirm(new_name):
        if new_name and new_name.strip():
            system_config.setdefault("sensor_names", {})[skey] = new_name.strip()
            save_config()
            lbl_detail_title.config(text=new_name.strip())
            update_ui()
            show_notification("Room Renamed", f"Renamed {skey} to '{new_name.strip()}' successfully!", "success")
            
    open_almora_keypad(f"Rename Room ({skey})", curr_name, on_confirm, is_alphanumeric=True)

btn_f_det = tk.Frame(frame_detail, bg="white")
btn_f_det.pack(side="bottom", fill="x", padx=35, pady=30)
tk.Button(btn_f_det, text="BACK TO DASHBOARD", font=("Helvetica", 11, "bold"), bg="#757575", fg="white", width=20, height=2, cursor="hand2", command=lambda: show(frame_main)).pack(side="left", padx=(0, 8))
tk.Button(btn_f_det, text="EDIT ROOM NAME", font=("Helvetica", 11, "bold"), bg="#d97706", fg="white", width=16, height=2, cursor="hand2", command=edit_active_room_name_detail).pack(side="left", padx=8)
tk.Button(btn_f_det, text="EDIT SCHEDULES", font=("Helvetica", 11, "bold"), bg="#0284c7", fg="white", width=15, height=2, cursor="hand2", command=lambda: open_schedule_editor(next((k for k, v in SENSOR_MAP.items() if v == active_detail_port), "S1"))).pack(side="left", padx=8)
btn_room_pause = tk.Button(btn_f_det, text="MANUAL STOP", font=("Helvetica", 11, "bold"), bg="#c62828", fg="white", width=12, height=2, cursor="hand2", command=toggle_active_room_pause)
btn_room_pause.pack(side="left", padx=8)

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

    lbl_modal_title = tk.Label(kp_main, text=title_text, font=big, fg="#1565c0", bg="white")
    lbl_modal_title.pack(pady=(6, 4))

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

    # --- 3. CALENDAR / DATE KEYPAD MODE (DD-MM-YYYY) ---
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

def format_freq_display(minutes):
    try:
        m = float(minutes)
        if m <= 0:
            return "1 Sec (Realtime)"
        elif m < 1:
            sec = int(m * 60)
            return f"{sec} Sec"
        elif m < 60:
            return f"{int(m)} Min"
        elif m < 1440:
            hours = m / 60.0
            return f"{hours:.1f} Hours" if hours % 1 != 0 else f"{int(hours)} Hour{'s' if hours > 1 else ''}"
        elif m < 10080:
            days = m / 1440.0
            return f"{days:.1f} Days" if days % 1 != 0 else f"{int(days)} Day{'s' if days > 1 else ''}"
        else:
            weeks = m / 10080.0
            return f"{weeks:.1f} Weeks" if weeks % 1 != 0 else f"{int(weeks)} Week{'s' if weeks > 1 else ''}"
    except Exception:
        return "1 Sec (Realtime)"

# ==============================================================================
# DEDICATED 3-COLUMN (HOUR, MIN, SEC) CLOUD UPLOAD FREQUENCY KEYPAD MODAL
# ==============================================================================
def open_upload_frequency_keypad(init_h, init_m, init_s, callback_on_confirm, parent_win=None):
    kp_win = tk.Toplevel(parent_win if parent_win else root)
    make_modal_fullscreen(kp_win)

    add_logo(kp_win)
    add_top_left_exit(kp_win)
    add_bottom_right_clock(kp_win)

    # Top padding 85px ensures zero overlap with the 60px header logo (y=15..75)
    kp_main = tk.Frame(kp_win, bg="white")
    kp_main.pack(fill="both", expand=True, pady=(85, 10))

    tk.Label(kp_main, text="CLOUD UPLOAD FREQUENCY", font=big, fg="#1565c0", bg="white").pack(pady=(0, 6))

    # Working values for the 3 columns
    cur_h = int(init_h)
    cur_m = int(init_m)
    cur_s = int(init_s)

    # Active editing column: 'H', 'M', or 'S'
    active_col = 'M'
    active_str = str(cur_m)

    # 3 Boxes Container (Medium / Compact size, centered)
    boxes_frame = tk.Frame(kp_main, bg="white")
    boxes_frame.pack(anchor="center", pady=2)

    # Box 1: HOURS
    card_h = tk.Frame(boxes_frame, bg="#f8fafc", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=10, pady=4, cursor="hand2")
    card_h.pack(side="left", padx=8)
    lbl_h_title = tk.Label(card_h, text="HOURS (HH)", font=("Helvetica", 9, "bold"), fg="#475569", bg="#f8fafc")
    lbl_h_title.pack()
    lbl_h_box = tk.Label(card_h, text=f"{cur_h:02d} hrs", font=("Arial", 14, "bold"), fg="#1565c0", bg="#ffffff", width=7, relief="sunken", bd=1)
    lbl_h_box.pack(pady=2)
    lbl_h_badge = tk.Label(card_h, text="TAP TO EDIT", font=("Helvetica", 7, "bold"), fg="#94a3b8", bg="#f8fafc")
    lbl_h_badge.pack()

    # Box 2: MINUTES
    card_m = tk.Frame(boxes_frame, bg="#eff6ff", bd=1, relief="solid", highlightbackground="#0284c7", padx=10, pady=4, cursor="hand2")
    card_m.pack(side="left", padx=8)
    lbl_m_title = tk.Label(card_m, text="MINUTES (MM)", font=("Helvetica", 9, "bold"), fg="#0284c7", bg="#eff6ff")
    lbl_m_title.pack()
    lbl_m_box = tk.Label(card_m, text=f"{cur_m:02d} min", font=("Arial", 14, "bold"), fg="#1565c0", bg="#ffffff", width=7, relief="sunken", bd=1)
    lbl_m_box.pack(pady=2)
    lbl_m_badge = tk.Label(card_m, text="● EDITING ●", font=("Helvetica", 7, "bold"), fg="#0284c7", bg="#eff6ff")
    lbl_m_badge.pack()

    # Box 3: SECONDS
    card_s = tk.Frame(boxes_frame, bg="#f8fafc", bd=1, relief="solid", highlightbackground="#cbd5e1", padx=10, pady=4, cursor="hand2")
    card_s.pack(side="left", padx=8)
    lbl_s_title = tk.Label(card_s, text="SECONDS (SS)", font=("Helvetica", 9, "bold"), fg="#475569", bg="#f8fafc")
    lbl_s_title.pack()
    lbl_s_box = tk.Label(card_s, text=f"{cur_s:02d} sec", font=("Arial", 14, "bold"), fg="#1565c0", bg="#ffffff", width=7, relief="sunken", bd=1)
    lbl_s_box.pack(pady=2)
    lbl_s_badge = tk.Label(card_s, text="TAP TO EDIT", font=("Helvetica", 7, "bold"), fg="#94a3b8", bg="#f8fafc")
    lbl_s_badge.pack()

    # Summary Display
    lbl_summary = tk.Label(
        kp_main,
        text=f"Total Interval: {format_upload_hms_display(cur_h, cur_m, cur_s)}",
        font=("Helvetica", 10, "bold"),
        fg="#0f766e",
        bg="white"
    )
    lbl_summary.pack(pady=(2, 3))

    def update_boxes_ui():
        lbl_h_box.config(text=f"{cur_h:02d} hrs" if active_col != 'H' else f"{active_str} hrs")
        lbl_m_box.config(text=f"{cur_m:02d} min" if active_col != 'M' else f"{active_str} min")
        lbl_s_box.config(text=f"{cur_s:02d} sec" if active_col != 'S' else f"{active_str} sec")

        # Highlight active card
        for col_name, card, title, badge in [('H', card_h, lbl_h_title, lbl_h_badge), ('M', card_m, lbl_m_title, lbl_m_badge), ('S', card_s, lbl_s_title, lbl_s_badge)]:
            if active_col == col_name:
                card.config(highlightbackground="#0284c7", highlightthickness=2, bg="#eff6ff")
                title.config(fg="#0284c7", bg="#eff6ff")
                badge.config(text="● EDITING ●", fg="#0284c7", bg="#eff6ff")
            else:
                card.config(highlightbackground="#cbd5e1", highlightthickness=1, bg="#f8fafc")
                title.config(fg="#475569", bg="#f8fafc")
                badge.config(text="TAP TO EDIT", fg="#94a3b8", bg="#f8fafc")

        # Compute preview total
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

    # Quick Presets (2 Compact Rows of 4 buttons each, centered)
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
        tk.Button(row1, text=s_name, font=("Helvetica", 9, "bold"), bg="#e0f2fe", fg="#0369a1",
                  activebackground="#0284c7", activeforeground="white", relief="flat", bd=0,
                  width=9, pady=3, cursor="hand2", command=lambda h=sh, m=sm, s=ss: _apply_shortcut(h, m, s)).pack(side="left", padx=3)

    for s_name, sh, sm, ss in row2_shortcuts:
        tk.Button(row2, text=s_name, font=("Helvetica", 9, "bold"), bg="#e0f2fe", fg="#0369a1",
                  activebackground="#0284c7", activeforeground="white", relief="flat", bd=0,
                  width=9, pady=3, cursor="hand2", command=lambda h=sh, m=sm, s=ss: _apply_shortcut(h, m, s)).pack(side="left", padx=3)

    # Keypad Grid (Full size touch buttons)
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
            btn = tk.Button(kp_buttons_frame, text="CLR", font=("Arial", 14, "bold"), bg="#dc2626", fg="white", width=7, height=1, relief="flat", bd=0, cursor="hand2", command=kp_clr)
        elif t == 'DEL':
            btn = tk.Button(kp_buttons_frame, text="DEL", font=("Arial", 14, "bold"), bg="#f97316", fg="white", width=7, height=1, relief="flat", bd=0, cursor="hand2", command=kp_del)
        else:
            btn = tk.Button(kp_buttons_frame, text=t, font=("Arial", 15, "bold"), width=7, height=1, bg="#f1f5f9", fg="#0f172a",
                            activebackground="#0284c7", activeforeground="white", relief="flat", bd=1, cursor="hand2",
                            command=lambda x=t: kp_num(x))
        btn.grid(row=r, column=c, padx=6, pady=2)

    # Bottom Actions: CONFIRM / CANCEL
    kp_actions_frame = tk.Frame(kp_main, bg="white")
    kp_actions_frame.pack(pady=5)

    def on_apply_click():
        commit_active_val()
        h_norm, m_norm, s_norm = normalize_upload_values(cur_h, cur_m, cur_s)

        # Check if duration > 24 hours
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

    tk.Button(kp_actions_frame, text="CONFIRM & APPLY", font=BTN_FONT_MAIN, bg="#2e7d32", fg="white", width=16, height=2, cursor="hand2", command=on_apply_click).pack(side="left", padx=10)
    tk.Button(kp_actions_frame, text="CANCEL", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=12, height=2, cursor="hand2", command=kp_win.destroy).pack(side="left", padx=10)

    update_boxes_ui()


# SYSTEM SETTINGS MODAL (CONFIG FREQUENCY & ALARM DEVIATION OFFSETS)
def open_system_settings_modal():
    sett_win = tk.Toplevel(root)
    make_modal_fullscreen(sett_win)

    s_main = tk.Frame(sett_win, bg="white")
    s_main.pack(fill="both", expand=True, pady=(85, 30))

    add_logo(sett_win)
    add_top_left_exit(sett_win)
    add_bottom_right_clock(sett_win)

    tk.Label(s_main, text="SYSTEM CONFIGURATION & ALARM SETTINGS", font=big, fg="#1565c0", bg="white").pack(pady=(0, 20))

    body = tk.Frame(s_main, bg="white")
    body.pack(pady=10)

    cur_h, cur_m, cur_s = get_upload_hms()
    temp_h = cur_h
    temp_m = cur_m
    temp_s = cur_s

    # 1. Cloud Upload Frequency Row
    r1 = tk.Frame(body, bg="white"); r1.pack(fill="x", pady=12)
    tk.Label(r1, text="Cloud Upload Frequency :", font=("Helvetica", 12, "bold"), fg="#1e293b", bg="white", width=25, anchor="e").pack(side="left", padx=10)

    lbl_freq = tk.Label(r1, text=format_upload_hms_display(temp_h, temp_m, temp_s), font=("Helvetica", 12, "bold"), bg="#f1f5f9", fg="#1565c0", width=28, relief="sunken", bd=1)
    lbl_freq.pack(side="left", padx=10)

    def on_upload_hms_confirmed(h, m, s):
        nonlocal temp_h, temp_m, temp_s
        temp_h, temp_m, temp_s = h, m, s
        lbl_freq.config(text=format_upload_hms_display(temp_h, temp_m, temp_s))

    def edit_upload_hms():
        open_upload_frequency_keypad(temp_h, temp_m, temp_s, on_upload_hms_confirmed, parent_win=sett_win)

    tk.Button(r1, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_upload_hms).pack(side="left", padx=5)

    # 2. Temp Alarm Offset (+/- C)
    r2 = tk.Frame(body, bg="white"); r2.pack(fill="x", pady=12)
    tk.Label(r2, text="Temp Alarm Limit (± °C) :", font=("Helvetica", 12, "bold"), fg="#1e293b", bg="white", width=25, anchor="e").pack(side="left", padx=10)

    t_off_val = system_config.get("temp_alarm_offset", 5.0)
    lbl_toff = tk.Label(r2, text=f"± {t_off_val:.1f} °C", font=("Helvetica", 12, "bold"), bg="#f1f5f9", fg="#1565c0", width=28, relief="sunken", bd=1)
    lbl_toff.pack(side="left", padx=10)

    def edit_toff():
        open_almora_keypad("Edit Temp Alarm Deviation Limit (± °C)", str(system_config.get("temp_alarm_offset", 5.0)),
                           lambda v: (system_config.update({"temp_alarm_offset": float(v)}), lbl_toff.config(text=f"± {float(v):.1f} °C")))

    tk.Button(r2, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_toff).pack(side="left", padx=5)

    # 3. Humi Alarm Offset (+/- %)
    r3 = tk.Frame(body, bg="white"); r3.pack(fill="x", pady=12)
    tk.Label(r3, text="Humi Alarm Limit (± %) :", font=("Helvetica", 12, "bold"), fg="#1e293b", bg="white", width=25, anchor="e").pack(side="left", padx=10)

    h_off_val = system_config.get("humi_alarm_offset", 5.0)
    lbl_hoff = tk.Label(r3, text=f"± {h_off_val:.1f} %", font=("Helvetica", 12, "bold"), bg="#f1f5f9", fg="#1565c0", width=28, relief="sunken", bd=1)
    lbl_hoff.pack(side="left", padx=10)

    def edit_hoff():
        open_almora_keypad("Edit Humi Alarm Deviation Limit (± %)", str(system_config.get("humi_alarm_offset", 5.0)),
                           lambda v: (system_config.update({"humi_alarm_offset": float(v)}), lbl_hoff.config(text=f"± {float(v):.1f} %")))

    tk.Button(r3, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_hoff).pack(side="left", padx=5)

    def save_sys_settings():
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
        sett_win.destroy()
        show_notification("Settings Saved", f"Configuration saved! Upload interval: {format_upload_hms_display(h_norm, m_norm, s_norm)}", "success")

    btn_f = tk.Frame(s_main, bg="white"); btn_f.pack(pady=35)
    tk.Button(btn_f, text="SAVE SETTINGS", font=BTN_FONT_MAIN, bg="#2e7d32", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=save_sys_settings).pack(side="left", padx=15)
    tk.Button(btn_f, text="CANCEL", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=sett_win.destroy).pack(side="left", padx=15)



# ALMORA CALENDAR SLOTS & CROP STAGES EDITOR HMI
sched_entries = {}

sched_btn_frame = tk.Frame(frame_schedule, bg="white")
sched_btn_frame.pack(side="bottom", fill="x", pady=(4, 8))

sched_container = tk.Frame(frame_schedule, bg="white")
sched_container.pack(side="top", fill="both", expand=True)

sched_canvas = tk.Canvas(sched_container, bg="white", highlightthickness=0)
sched_scrollbar = ttk.Scrollbar(sched_container, orient="vertical", command=sched_canvas.yview)
sched_scroll_inner = tk.Frame(sched_canvas, bg="white")

sched_scroll_window = sched_canvas.create_window((0, 0), window=sched_scroll_inner, anchor="nw")

def _on_sched_inner_configure(event):
    sched_canvas.configure(scrollregion=sched_canvas.bbox("all"))

sched_scroll_inner.bind("<Configure>", _on_sched_inner_configure)

def _on_sched_canvas_configure(event):
    sched_canvas.itemconfig(sched_scroll_window, width=event.width)

sched_canvas.bind("<Configure>", _on_sched_canvas_configure)
sched_canvas.configure(yscrollcommand=sched_scrollbar.set)

sched_scrollbar.pack(side="right", fill="y")
sched_canvas.pack(side="left", fill="both", expand=True)

def _on_sched_mousewheel(event):
    try:
        if event.delta:
            sched_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif event.num == 4:
            sched_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            sched_canvas.yview_scroll(1, "units")
    except Exception: pass

sched_canvas.bind_all("<MouseWheel>", _on_sched_mousewheel)
sched_canvas.bind_all("<Button-4>", _on_sched_mousewheel)
sched_canvas.bind_all("<Button-5>", _on_sched_mousewheel)

lbl_sched_title = tk.Label(sched_scroll_inner, text="ALMORA CALENDAR & MULTI CROP STAGES SCHEDULE ", font=big, fg="#1565c0", bg="white")
lbl_sched_title.pack(pady=(35, 2))

sched_top_ctrl = tk.Frame(sched_scroll_inner, bg="white")
sched_top_ctrl.pack(pady=6)

# Style Combobox for large touch screen readability
combobox_style = ttk.Style()
combobox_style.theme_use('default')
combobox_style.configure("TCombobox", font=("Helvetica", 11, "bold"), padding=6)

# --- MIND.PY STYLE CUSTOM DROPDOWNS & BUTTONS ---

class ComboHelper:
    def __init__(self, val="S1"):
        self.val = val
    def get(self):
        return self.val
    def set(self, v):
        self.val = v

skey_combo = ComboHelper("S1")
setting_combo = ComboHelper("Setting A")

sched_clean_snapshot = None
sched_dirty_flag = False

def mark_schedule_dirty():
    global sched_dirty_flag
    sched_dirty_flag = True

def sync_schedule_form_to_memory():
    try:
        skey = skey_combo.get()
        setting_nm = setting_combo.get()
        if not skey or not setting_nm:
            return
        sp = get_setpoints(skey)
        st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
        if 'lbl_val_stagename' in globals() and lbl_val_stagename.winfo_exists():
            st["name"] = lbl_val_stagename.cget("text").strip()
        if 'lbl_val_sdate' in globals() and lbl_val_sdate.winfo_exists():
            st["start_date"] = format_date_dmy(lbl_val_sdate.cget("text").strip())
        if 'lbl_val_edate' in globals() and lbl_val_edate.winfo_exists():
            st["end_date"] = format_date_dmy(lbl_val_edate.cget("text").strip())
        if 'lbl_val_pon' in globals() and lbl_val_pon.winfo_exists():
            st["photoperiod_on"] = lbl_val_pon.cget("text").strip()
        if 'lbl_val_poff' in globals() and lbl_val_poff.winfo_exists():
            st["photoperiod_off"] = lbl_val_poff.cget("text").strip()
        
        if sched_entries:
            new_slots = []
            for idx in range(len(sched_entries)):
                if idx in sched_entries:
                    l_fname, l_tstart, l_tstop, l_tset_val, l_tmax_val, l_tmin_val, l_hset_val, l_hmax_val, l_hmin_val = sched_entries[idx]
                    t_set_val = round(float(l_tset_val.cget("text").strip()), 1)
                    h_set_val = round(float(l_hset_val.cget("text").strip()), 1)
                    new_slots.append({
                        "id": idx + 1,
                        "name": l_fname.cget("text").strip(),
                        "start": format_time_12h(l_tstart.cget("text").strip()),
                        "stop": format_time_12h(l_tstop.cget("text").strip()),
                        "t_set": t_set_val,
                        "t_max": round(float(l_tmax_val.cget("text").strip()), 1),
                        "t_min": round(float(l_tmin_val.cget("text").strip()), 1),
                        "h_set": h_set_val,
                        "h_max": round(float(l_hmax_val.cget("text").strip()), 1),
                        "h_min": round(float(l_hmin_val.cget("text").strip()), 1),
                        "enabled": True
                    })
            st["time_slots"] = new_slots
    except Exception as e:
        print(f"sync_schedule_form_to_memory error: {e}")

def has_unsaved_schedule_changes():
    sync_schedule_form_to_memory()
    if sched_clean_snapshot is None:
        return False
    curr_json = json.dumps(sensor_setpoints, sort_keys=True)
    snap_json = json.dumps(sched_clean_snapshot, sort_keys=True)
    return (curr_json != snap_json) or sched_dirty_flag

sensor_dropdown_open = False
profile_dropdown_open = False
preset_dropdown_open = False
stages_count_dropdown_open = False

sensor_menu_frame = tk.Frame(sched_scroll_inner, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", highlightthickness=1)
profile_menu_frame = tk.Frame(sched_scroll_inner, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", highlightthickness=1)
preset_menu_frame = tk.Frame(sched_scroll_inner, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", highlightthickness=1)
stages_count_menu_frame = tk.Frame(sched_scroll_inner, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1", highlightthickness=1)

sched_row1 = tk.Frame(sched_top_ctrl, bg="white")
sched_row1.pack(pady=(0, 4), anchor="center")

sched_row2 = tk.Frame(sched_top_ctrl, bg="white")
sched_row2.pack(pady=(4, 0), anchor="center")

# --- 1. SENSOR DROPDOWN (MIND.PY STYLE) ---
tk.Label(sched_row1, text="Sensor:", font=("Helvetica", 12, "bold"), fg="#475569", bg="white").pack(side="left", padx=(5, 4))

def toggle_sensor_dropdown():
    global sensor_dropdown_open, profile_dropdown_open, preset_dropdown_open
    profile_menu_frame.place_forget(); profile_dropdown_open = False
    preset_menu_frame.place_forget(); preset_dropdown_open = False
    if sensor_dropdown_open:
        sensor_menu_frame.place_forget()
        sensor_dropdown_open = False
    else:
        for w in sensor_menu_frame.winfo_children(): w.destroy()
        keys = sorted(SENSOR_MAP.keys())
        for idx, skey in enumerate(keys):
            dname = get_sensor_display_name(skey)
            btn = tk.Button(sensor_menu_frame, text=f"{skey} — {dname}", font=("Helvetica", 13, "bold"), bg="white", fg="#1e293b",
                            activebackground="#0284c7", activeforeground="white", relief="flat", bd=0, anchor="w", padx=15, pady=12, cursor="hand2")
            btn.config(command=lambda s=skey, d=dname: select_sensor(s, d))
            btn.pack(fill="x")
            if idx < len(keys) - 1:
                tk.Frame(sensor_menu_frame, bg="#cbd5e1", height=1).pack(fill="x")
        sensor_menu_frame.place(in_=sensor_dropdown_btn, relx=0.0, rely=1.0, y=2, width=300)
        sensor_menu_frame.lift()
        sensor_dropdown_open = True

def select_sensor(skey, dname):
    global sensor_dropdown_open
    sync_schedule_form_to_memory()
    skey_combo.set(skey)
    sensor_dropdown_btn.config(text=f"{skey} — {get_sensor_display_name(skey)} ▼")
    sensor_menu_frame.place_forget()
    sensor_dropdown_open = False
    load_schedule_form()

sensor_dropdown_btn = tk.Button(sched_row1, text="S1 — COLD ROOM 1 ▼", font=("Helvetica", 11, "bold"), bg="#cbd5e1", fg="#1e293b",
                                activebackground="#94a3b8", activeforeground="#1e293b", relief="flat", bd=0, padx=12, pady=6, cursor="hand2", command=toggle_sensor_dropdown)
sensor_dropdown_btn.pack(side="left", padx=(0, 6))

def edit_room_name():
    skey = skey_combo.get()
    curr_name = get_sensor_display_name(skey)
    def on_confirm(new_name):
        if new_name and new_name.strip():
            system_config.setdefault("sensor_names", {})[skey] = new_name.strip()
            save_config()
            sensor_dropdown_btn.config(text=f"{skey} — {new_name.strip()} ▼")
            update_ui()
            load_schedule_form()
            show_notification("Room Renamed", f"Renamed {skey} to '{new_name.strip()}' successfully!", "success")

    open_almora_keypad(f"Rename Room ({skey})", curr_name, on_confirm, is_alphanumeric=True)

btn_edit_room_name = tk.Button(sched_row1, text="EDIT NAME", font=BTN_FONT_INLINE, bg="#0284c7", fg="white",
                               width=8, height=1, relief="flat", bd=0, cursor="hand2", command=edit_room_name)
btn_edit_room_name.pack(side="left", padx=(0, 15))

# --- 2. CROP STAGE DROPDOWN (MIND.PY STYLE) ---
tk.Label(sched_row1, text="Crop Stage:", font=("Helvetica", 12, "bold"), fg="#475569", bg="white").pack(side="left", padx=(5, 4))

ALL_SETTINGS = ["Setting A", "Setting B", "Setting C", "Setting D", "Setting E", 
                "Setting F", "Setting G", "Setting H", "Setting I", "Setting J"]

def toggle_profile_dropdown():
    global sensor_dropdown_open, profile_dropdown_open, preset_dropdown_open
    sensor_menu_frame.place_forget(); sensor_dropdown_open = False
    preset_menu_frame.place_forget(); preset_dropdown_open = False
    if profile_dropdown_open:
        profile_menu_frame.place_forget()
        profile_dropdown_open = False
    else:
        for w in profile_menu_frame.winfo_children(): w.destroy()
        sp = get_setpoints(skey_combo.get())
        settings_dict = sp.get("settings", {})
        for idx, s_key in enumerate(ALL_SETTINGS):
            p_name = settings_dict.get(s_key, {}).get("name", s_key)
            btn_txt = p_name
            btn = tk.Button(profile_menu_frame, text=btn_txt, font=("Helvetica", 12, "bold"), bg="white", fg="#1e293b",
                            activebackground="#0284c7", activeforeground="white", relief="flat", bd=0, anchor="w", padx=12, pady=10, cursor="hand2")
            btn.config(command=lambda s=s_key, t=btn_txt: select_profile(s, t))
            btn.pack(fill="x")
            if idx < len(ALL_SETTINGS) - 1:
                tk.Frame(profile_menu_frame, bg="#cbd5e1", height=1).pack(fill="x")
        profile_menu_frame.place(in_=profile_dropdown_btn, relx=0.0, rely=1.0, y=2, width=300)
        profile_menu_frame.lift()
        profile_dropdown_open = True

def select_profile(s_name, btn_txt):
    global profile_dropdown_open
    sync_schedule_form_to_memory()
    setting_combo.set(s_name)
    profile_dropdown_btn.config(text=f"{btn_txt}▼")
    profile_menu_frame.place_forget()
    profile_dropdown_open = False
    load_schedule_form()

profile_dropdown_btn = tk.Button(sched_row1, text="Crop Stage 1▼", font=("Helvetica", 11, "bold"), bg="#cbd5e1", fg="#1e293b",
                                 activebackground="#94a3b8", activeforeground="#1e293b", relief="flat", bd=0, padx=12, pady=6, cursor="hand2", command=toggle_profile_dropdown)
profile_dropdown_btn.pack(side="left", padx=(0, 15))

# --- 3. STAGES COUNT SELECTOR DROPDOWN ---
tk.Label(sched_row1, text="No. of Stages:", font=("Helvetica", 12, "bold"), fg="#475569", bg="white").pack(side="left", padx=(5, 4))

def toggle_stages_count_dropdown():
    global stages_count_dropdown_open, sensor_dropdown_open, profile_dropdown_open, preset_dropdown_open
    sensor_menu_frame.place_forget(); sensor_dropdown_open = False
    profile_menu_frame.place_forget(); profile_dropdown_open = False
    preset_menu_frame.place_forget(); preset_dropdown_open = False
    
    if stages_count_dropdown_open:
        stages_count_menu_frame.place_forget()
        stages_count_dropdown_open = False
    else:
        for w in stages_count_menu_frame.winfo_children(): w.destroy()
        for num in range(1, len(ALL_SETTINGS) + 1):
            btn = tk.Button(stages_count_menu_frame, text=f"{num} Crop Stage{'s' if num > 1 else ''}", font=("Helvetica", 12, "bold"),
                            bg="white", fg="#1e293b", activebackground="#0284c7", activeforeground="white", relief="flat", bd=0, anchor="w", padx=12, pady=8, cursor="hand2")
            btn.config(command=lambda n=num: select_num_stages(n))
            btn.pack(fill="x")
            if num < len(ALL_SETTINGS):
                tk.Frame(stages_count_menu_frame, bg="#cbd5e1", height=1).pack(fill="x")
        stages_count_menu_frame.place(in_=stages_count_dropdown_btn, relx=0.0, rely=1.0, y=2, width=180)
        stages_count_menu_frame.lift()
        stages_count_dropdown_open = True

def select_num_stages(count):
    global stages_count_dropdown_open
    sync_schedule_form_to_memory()
    skey = skey_combo.get()
    sp = get_setpoints(skey)
    settings = sp.get("settings", {})
    
    for idx, s_key in enumerate(ALL_SETTINGS):
        st = settings.setdefault(s_key, {})
        if idx < count:
            st["enabled"] = True
        else:
            st["enabled"] = False
            
    mark_schedule_dirty()
    stages_count_dropdown_btn.config(text=f"{count} Stages ▼")
    stages_count_menu_frame.place_forget()
    stages_count_dropdown_open = False
    load_schedule_form()
    show_notification("Stages Updated", f"Set number of active crop stages for {get_sensor_display_name(skey)} to {count}!", "success")

stages_count_dropdown_btn = tk.Button(sched_row1, text="5 Stages ▼", font=("Helvetica", 11, "bold"), bg="#cbd5e1", fg="#1e293b",
                                      activebackground="#94a3b8", activeforeground="#1e293b", relief="flat", bd=0, padx=12, pady=6, cursor="hand2", command=toggle_stages_count_dropdown)
stages_count_dropdown_btn.pack(side="left", padx=(0, 4))

# --- 4. PROGRAM LIBRARY DROPDOWN (MIND.PY STYLE - LINE 2 CENTERED) ---
tk.Label(sched_row2, text="Program:", font=("Helvetica", 12, "bold"), fg="#475569", bg="white").pack(side="left", padx=(5, 4))

def update_preset_dropdown_text():
    skey = skey_combo.get()
    all_presets = get_all_crop_programs()
    count = len(all_presets)
    sp = get_setpoints(skey)
    active_p = sp.get("program_name", "Default Program")
    if active_p and (active_p in all_presets or active_p != "Default Program"):
        preset_dropdown_btn.config(text=f"{active_p} ▼", bg="#0284c7", fg="white")
    else:
        preset_dropdown_btn.config(text=f"Programs ({count}/20 Saved) ▼", bg="#cbd5e1", fg="#1e293b")

def toggle_preset_dropdown():
    global sensor_dropdown_open, profile_dropdown_open, preset_dropdown_open, stages_count_dropdown_open
    sensor_menu_frame.place_forget(); sensor_dropdown_open = False
    profile_menu_frame.place_forget(); profile_dropdown_open = False
    stages_count_menu_frame.place_forget(); stages_count_dropdown_open = False
    if preset_dropdown_open:
        preset_menu_frame.place_forget()
        preset_dropdown_open = False
    else:
        skey = skey_combo.get()
        all_presets = get_all_crop_programs()
        for w in preset_menu_frame.winfo_children(): w.destroy()
        p_items = list(all_presets.items())
        if not p_items:
            tk.Label(preset_menu_frame, text="No Saved Programs", font=("Helvetica", 11, "bold"), fg="#64748b", bg="white", padx=12, pady=10).pack()
        else:
            for idx, (p_name, p_data) in enumerate(p_items):
                item_f = tk.Frame(preset_menu_frame, bg="white")
                item_f.pack(fill="x")

                def _apply(name=p_name):
                    global preset_dropdown_open, sched_clean_snapshot, sched_dirty_flag
                    curr_skey = skey_combo.get()
                    all_p = get_all_crop_programs()
                    if name in all_p:
                        sensor_setpoints[curr_skey]["settings"] = copy.deepcopy(all_p[name])
                        sensor_setpoints[curr_skey]["program_name"] = name
                        save_setpoints()
                        sched_clean_snapshot = copy.deepcopy(sensor_setpoints)
                        sched_dirty_flag = False
                        preset_menu_frame.place_forget()
                        preset_dropdown_open = False
                        load_schedule_form()
                        update_preset_dropdown_text()
                        update_ui()
                        broadcast_current_state()
                        show_notification("Program Loaded", f"Applied and activated '{name}' for {get_sensor_display_name(curr_skey)}!", "info")

                def _delete(name=p_name):
                    curr_skey = skey_combo.get()
                    load_crop_programs()
                    if name in crop_programs:
                        del crop_programs[name]
                    for rk in SENSOR_MAP.keys():
                        if rk in crop_programs and isinstance(crop_programs[rk], dict) and name in crop_programs[rk]:
                            del crop_programs[rk][name]
                    save_crop_programs()
                    for rk in SENSOR_MAP.keys():
                        sp = get_setpoints(rk)
                        if sp.get("program_name") == name:
                            sp["program_name"] = "Default Program"
                    save_setpoints()
                    toggle_preset_dropdown()
                    update_preset_dropdown_text()
                    load_schedule_form()
                    update_ui()
                    broadcast_current_state()
                    show_notification("Program Deleted", f"Deleted program '{name}'", "info")

                btn_apply = tk.Button(item_f, text=f"{p_name}", font=("Helvetica", 11, "bold"), bg="white", fg="#1e293b",
                                      activebackground="#0284c7", activeforeground="white", relief="flat", bd=0, anchor="w", padx=12, pady=10, cursor="hand2", command=_apply)
                btn_apply.pack(side="left", fill="x", expand=True)

                btn_del = tk.Button(item_f, text="✖", font=("Helvetica", 12, "bold"), bg="#dc2626", fg="white",
                                    relief="flat", bd=0, padx=12, pady=10, cursor="hand2", command=_delete)
                btn_del.pack(side="right")

                if idx < len(p_items) - 1:
                    tk.Frame(preset_menu_frame, bg="#cbd5e1", height=1).pack(fill="x")

        preset_menu_frame.place(in_=preset_dropdown_btn, relx=0.0, rely=1.0, y=2, width=300)
        preset_menu_frame.lift()
        preset_dropdown_open = True

preset_dropdown_btn = tk.Button(sched_row2, text="Programs (0/20 Saved)  ▼", font=("Helvetica", 11, "bold"), bg="#cbd5e1", fg="#1e293b",
                                activebackground="#94a3b8", activeforeground="#1e293b", relief="flat", bd=0, padx=12, pady=6, cursor="hand2", command=toggle_preset_dropdown)
preset_dropdown_btn.pack(side="left", padx=(0, 12))

def save_current_as_preset_inline():
    skey = skey_combo.get()
    all_presets = get_all_crop_programs()
    if len(all_presets) >= 20:
        show_notification("Limit Reached", "Maximum 20 programs allowed. Delete a program first.", "warning")
        return
    default_name = f"Program {len(all_presets)+1}"
    def on_confirm_name(name):
        if name and name.strip():
            sync_schedule_form_to_memory()
            name = name.strip()
            curr_skey = skey_combo.get()
            sp = get_setpoints(curr_skey)
            st_content = copy.deepcopy(sp.get("settings", {}))
            
            load_crop_programs()
            crop_programs[name] = st_content
            if curr_skey not in crop_programs or not isinstance(crop_programs[curr_skey], dict):
                crop_programs[curr_skey] = {}
            crop_programs[curr_skey][name] = st_content
            save_crop_programs()
            
            sp["program_name"] = name
            save_setpoints()
            
            global sched_clean_snapshot, sched_dirty_flag
            sched_clean_snapshot = copy.deepcopy(sensor_setpoints)
            sched_dirty_flag = False
            
            update_preset_dropdown_text()
            load_schedule_form()
            update_ui()
            broadcast_current_state()
            show_notification("Program Saved", f"Saved and activated program '{name}' for {get_sensor_display_name(curr_skey)}!", "success")

    open_almora_keypad(f"Program Name ({get_sensor_display_name(skey)})", default_name, on_confirm_name, is_alphanumeric=True)

btn_save_preset = tk.Button(sched_row2, text="SAVE PROGRAM", font=("Helvetica", 11, "bold"), bg="#2e7d32", fg="white",
                            activebackground="#15803d", activeforeground="white", relief="flat", bd=0, padx=14, pady=6, cursor="hand2", command=save_current_as_preset_inline)
btn_save_preset.pack(side="left", padx=5)

def on_click_outside_sched_dropdowns(event):
    global sensor_dropdown_open, profile_dropdown_open, preset_dropdown_open, stages_count_dropdown_open
    w = event.widget
    for menu_frame, open_flag_name in [(sensor_menu_frame, 'sensor_dropdown_open'), (profile_menu_frame, 'profile_dropdown_open'), (preset_menu_frame, 'preset_dropdown_open'), (stages_count_menu_frame, 'stages_count_dropdown_open')]:
        if globals()[open_flag_name]:
            curr = w
            in_menu = False
            while curr:
                if curr in (sensor_menu_frame, profile_menu_frame, preset_menu_frame, stages_count_menu_frame, sensor_dropdown_btn, profile_dropdown_btn, preset_dropdown_btn, stages_count_dropdown_btn):
                    in_menu = True
                    break
                try: curr = curr.master
                except Exception: break
            if not in_menu:
                menu_frame.place_forget()
                globals()[open_flag_name] = False

root.bind("<Button-1>", on_click_outside_sched_dropdowns, add="+")

def auto_chain_crop_stage_dates(skey, updated_stage_key):
    try:
        sp = get_setpoints(skey)
        settings = sp.get("settings", {})
        
        stages = [s for s in ALL_SETTINGS if s in settings]
        if updated_stage_key not in stages:
            return
            
        idx = stages.index(updated_stage_key)
        curr_st = settings[updated_stage_key]
        
        c_start = parse_date_str(curr_st.get("start_date", ""))
        c_end = parse_date_str(curr_st.get("end_date", ""))
        if not c_start or not c_end:
            return
        if c_end < c_start:
            c_end = c_start
            curr_st["end_date"] = c_end.strftime("%d-%m-%Y")

        for i in range(idx, len(stages) - 1):
            curr_k = stages[i]
            next_k = stages[i+1]
            
            c_info = settings[curr_k]
            n_info = settings[next_k]
            
            try:
                c_e_date = parse_date_str(c_info.get("end_date", ""))
                n_s_orig = parse_date_str(n_info.get("start_date", ""))
                n_e_orig = parse_date_str(n_info.get("end_date", ""))
                
                if not c_e_date or not n_s_orig or not n_e_orig:
                    continue
                
                duration = max(datetime.timedelta(days=1), n_e_orig - n_s_orig + datetime.timedelta(days=1))
                
                new_n_s = c_e_date + datetime.timedelta(days=1)
                new_n_e = new_n_s + duration - datetime.timedelta(days=1)
                
                n_info["start_date"] = new_n_s.strftime("%d-%m-%Y")
                n_info["end_date"] = new_n_e.strftime("%d-%m-%Y")
            except Exception as ex:
                print(f"Date cascade error on {next_k}: {ex}")
    except Exception as e:
        print(f"auto_chain_crop_stage_dates err: {e}")

def check_time_slot_overlaps(time_slots):
    warnings = []
    parsed_slots = []
    
    for idx, slot in enumerate(time_slots):
        st_str = slot.get("start", "").strip()
        sp_str = slot.get("stop", "").strip()
        try:
            st_dt = datetime.datetime.strptime(st_str, "%I:%M %p" if ("AM" in st_str or "PM" in st_str) else "%H:%M")
            sp_dt = datetime.datetime.strptime(sp_str, "%I:%M %p" if ("AM" in sp_str or "PM" in sp_str) else "%H:%M")
            
            st_min = st_dt.hour * 60 + st_dt.minute
            sp_min = sp_dt.hour * 60 + sp_dt.minute
            
            if sp_min <= st_min:
                sp_min += 1440
                
            parsed_slots.append((idx + 1, slot.get("name", f"Slot {idx+1}"), st_min, sp_min))
        except Exception:
            pass

    for i in range(len(parsed_slots)):
        for j in range(i + 1, len(parsed_slots)):
            id1, name1, s1, e1 = parsed_slots[i]
            id2, name2, s2, e2 = parsed_slots[j]
            
            if max(s1, s2) < min(e1, e2):
                warnings.append(f"Slot {id1} ({name1}) and Slot {id2} ({name2}) overlap!")
                
    return warnings

# DATE RANGE & STAGE NAME ROW
date_frame = tk.Frame(sched_scroll_inner, bg="white")
date_frame.pack(pady=4, anchor="center")

tk.Label(date_frame, text="Stage Name:", font=("Helvetica", 11, "bold"), fg="#64748b", bg="white").grid(row=0, column=0, padx=3, pady=2)
lbl_val_stagename = tk.Label(date_frame, text="Crop Stage 1", font=("Helvetica", 11, "bold"), bg="#ffffff", fg="#1e293b", width=14, relief="sunken", bd=1)
lbl_val_stagename.grid(row=0, column=1, padx=3, pady=2)

def edit_stagename():
    skey = skey_combo.get()
    room_nm = get_sensor_display_name(skey)
    setting_nm = setting_combo.get()
    def _on_stagename(v):
        lbl_val_stagename.config(text=v)
        sp = get_setpoints(skey)
        sp.setdefault("settings", {}).setdefault(setting_nm, {})["name"] = v
        save_setpoints()
        act_prog = sp.get("program_name")
        if act_prog and act_prog != "Default Program":
            load_crop_programs()
            st_content = copy.deepcopy(sp.get("settings", {}))
            crop_programs[act_prog] = st_content
            if skey not in crop_programs or not isinstance(crop_programs[skey], dict):
                crop_programs[skey] = {}
            crop_programs[skey][act_prog] = st_content
            save_crop_programs()
        mark_schedule_dirty()
        load_schedule_form()
    open_almora_keypad(f"{room_nm}: Edit Crop Stage Name", lbl_val_stagename.cget("text"), _on_stagename, is_alphanumeric=True)

tk.Button(date_frame, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_stagename).grid(row=0, column=2, padx=3, pady=2)

tk.Label(date_frame, text="Start Date:", font=("Helvetica", 11, "bold"), fg="#64748b", bg="white").grid(row=0, column=3, padx=(10, 3), pady=2)
lbl_val_sdate = tk.Label(date_frame, text="01-07-2026", font=("Helvetica", 11, "bold"), bg="#ffffff", fg="#1e293b", width=12, relief="sunken", bd=1)
lbl_val_sdate.grid(row=0, column=4, padx=3, pady=2)

def on_sdate_changed(val):
    formatted = format_date_dmy(val.strip())
    lbl_val_sdate.config(text=formatted)
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
    st["start_date"] = formatted
    auto_chain_crop_stage_dates(skey, setting_nm)
    save_setpoints()
    act_prog = sp.get("program_name")
    if act_prog and act_prog != "Default Program":
        load_crop_programs()
        st_content = copy.deepcopy(sp.get("settings", {}))
        crop_programs[act_prog] = st_content
        if skey not in crop_programs or not isinstance(crop_programs[skey], dict):
            crop_programs[skey] = {}
        crop_programs[skey][act_prog] = st_content
        save_crop_programs()
    mark_schedule_dirty()
    load_schedule_form()

def edit_sdate():
    skey = skey_combo.get()
    room_nm = get_sensor_display_name(skey)
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.get("settings", {}).get(setting_nm, {})
    stage_disp = st.get("name", setting_nm)
    open_almora_keypad(f"{room_nm} [{stage_disp}]: Start Date ", lbl_val_sdate.cget("text"), on_sdate_changed)

tk.Button(date_frame, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_sdate).grid(row=0, column=5, padx=3, pady=2)

tk.Label(date_frame, text="End Date:", font=("Helvetica", 11, "bold"), fg="#64748b", bg="white").grid(row=0, column=6, padx=(10, 3), pady=2)
lbl_val_edate = tk.Label(date_frame, text="31-08-2026", font=("Helvetica", 11, "bold"), bg="#ffffff", fg="#1e293b", width=12, relief="sunken", bd=1)
lbl_val_edate.grid(row=0, column=7, padx=3, pady=2)

def on_edate_changed(val):
    formatted = format_date_dmy(val.strip())
    lbl_val_edate.config(text=formatted)
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
    st["end_date"] = formatted
    auto_chain_crop_stage_dates(skey, setting_nm)
    save_setpoints()
    act_prog = sp.get("program_name")
    if act_prog and act_prog != "Default Program":
        load_crop_programs()
        st_content = copy.deepcopy(sp.get("settings", {}))
        crop_programs[act_prog] = st_content
        if skey not in crop_programs or not isinstance(crop_programs[skey], dict):
            crop_programs[skey] = {}
        crop_programs[skey][act_prog] = st_content
        save_crop_programs()
    mark_schedule_dirty()
    load_schedule_form()

def edit_edate():
    skey = skey_combo.get()
    room_nm = get_sensor_display_name(skey)
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.get("settings", {}).get(setting_nm, {})
    stage_disp = st.get("name", setting_nm)
    open_almora_keypad(f"{room_nm} [{stage_disp}]: End Date ", lbl_val_edate.cget("text"), on_edate_changed)

tk.Button(date_frame, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_edate).grid(row=0, column=8, padx=3, pady=2)

def toggle_current_stage_activation():
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
    curr_enabled = st.get("enabled", True)
    st["enabled"] = not curr_enabled
    save_setpoints()
    sched_clean_snapshot = copy.deepcopy(sensor_setpoints)
    sched_dirty_flag = False
    load_schedule_form()
    broadcast_current_state()

# PHOTOPERIOD LIGHTING CONTROL ROW
light_frame = tk.Frame(sched_scroll_inner, bg="#f8fafc", bd=1, relief="solid")
light_frame.pack(pady=6, anchor="center", padx=10)

tk.Label(light_frame, text=" PHOTOPERIOD LIGHTING CYCLE:", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="#f8fafc").grid(row=0, column=0, padx=8, pady=4)

tk.Label(light_frame, text="Light ON:", font=("Helvetica", 11, "bold"), fg="#334155", bg="#f8fafc").grid(row=0, column=1, padx=4, pady=4)
lbl_val_pon = tk.Label(light_frame, text="06:00 AM", font=("Helvetica", 11, "bold"), bg="#ffffff", fg="#1e293b", width=10, relief="sunken", bd=1)
lbl_val_pon.grid(row=0, column=2, padx=4, pady=4)

def edit_pon():
    skey = skey_combo.get()
    room_nm = get_sensor_display_name(skey)
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.get("settings", {}).get(setting_nm, {})
    stage_disp = st.get("name", setting_nm)
    def _on_pon(v):
        formatted = format_time_12h(v)
        lbl_val_pon.config(text=formatted)
        sp.setdefault("settings", {}).setdefault(setting_nm, {})["photoperiod_on"] = formatted
        save_setpoints()
        act_prog = sp.get("program_name")
        if act_prog and act_prog != "Default Program":
            load_crop_programs()
            st_content = copy.deepcopy(sp.get("settings", {}))
            crop_programs[act_prog] = st_content
            if skey not in crop_programs or not isinstance(crop_programs[skey], dict):
                crop_programs[skey] = {}
            crop_programs[skey][act_prog] = st_content
            save_crop_programs()
        mark_schedule_dirty()
        load_schedule_form()
    open_almora_keypad(f"{room_nm} [{stage_disp}]: Light ON Time", lbl_val_pon.cget("text"), _on_pon)

tk.Button(light_frame, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_pon).grid(row=0, column=3, padx=4, pady=4)

tk.Label(light_frame, text="Light OFF:", font=("Helvetica", 11, "bold"), fg="#334155", bg="#f8fafc").grid(row=0, column=4, padx=(12, 4), pady=4)
lbl_val_poff = tk.Label(light_frame, text="08:00 PM", font=("Helvetica", 11, "bold"), bg="#ffffff", fg="#1e293b", width=10, relief="sunken", bd=1)
lbl_val_poff.grid(row=0, column=5, padx=4, pady=4)

def edit_poff():
    skey = skey_combo.get()
    room_nm = get_sensor_display_name(skey)
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.get("settings", {}).get(setting_nm, {})
    stage_disp = st.get("name", setting_nm)
    def _on_poff(v):
        formatted = format_time_12h(v)
        lbl_val_poff.config(text=formatted)
        sp.setdefault("settings", {}).setdefault(setting_nm, {})["photoperiod_off"] = formatted
        save_setpoints()
        act_prog = sp.get("program_name")
        if act_prog and act_prog != "Default Program":
            load_crop_programs()
            st_content = copy.deepcopy(sp.get("settings", {}))
            crop_programs[act_prog] = st_content
            if skey not in crop_programs or not isinstance(crop_programs[skey], dict):
                crop_programs[skey] = {}
            crop_programs[skey][act_prog] = st_content
            save_crop_programs()
        mark_schedule_dirty()
        load_schedule_form()
    open_almora_keypad(f"{room_nm} [{stage_disp}]: Light OFF Time", lbl_val_poff.cget("text"), _on_poff)

tk.Button(light_frame, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_poff).grid(row=0, column=6, padx=4, pady=4)

def save_current_schedule_to_file(show_feedback=True):
    global sched_clean_snapshot, sched_dirty_flag
    try:
        sync_schedule_form_to_memory()
        skey = skey_combo.get()
        setting_nm = setting_combo.get()
        sp = get_setpoints(skey)
        
        save_setpoints()
        print(f"Schedule for {skey} - {setting_nm} saved successfully!")
        
        # If an active program is saved, also sync changes into crop_programs master library
        act_prog = sp.get("program_name")
        if act_prog and act_prog != "Default Program":
            load_crop_programs()
            st_content = copy.deepcopy(sp.get("settings", {}))
            crop_programs[act_prog] = st_content
            if skey not in crop_programs or not isinstance(crop_programs[skey], dict):
                crop_programs[skey] = {}
            crop_programs[skey][act_prog] = st_content
            save_crop_programs()

        sched_clean_snapshot = copy.deepcopy(sensor_setpoints)
        sched_dirty_flag = False

        update_preset_dropdown_text()
        update_ui()
        if show_feedback:
            show_notification("Schedule Saved", f"Schedule for {get_sensor_display_name(skey)} ({setting_nm}) saved!", "success")
            if 'btn_save_sched' in globals() and btn_save_sched.winfo_exists():
                orig_txt = btn_save_sched.cget("text")
                orig_bg = btn_save_sched.cget("bg")
                btn_save_sched.config(text="SAVED ✔", bg="#15803d")
                def _reset_btn():
                    try:
                        if btn_save_sched.winfo_exists():
                            btn_save_sched.config(text=orig_txt, bg=orig_bg)
                    except Exception: pass
                root.after(1500, _reset_btn)
    except Exception as e:
        print(f"Schedule Save Error: {e}")

def add_new_time_slot():
    sync_schedule_form_to_memory()
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
    slots = st.setdefault("time_slots", [])
    
    new_id = len(slots) + 1
    slots.append({
        "id": new_id,
        "name": f"Slot {new_id}",
        "start": "12:00 PM",
        "stop": "04:00 PM",
        "t_set": 25.0, "t_max": 26.0, "t_min": 21.0,
        "h_set": 65.0, "h_max": 70.0, "h_min": 60.0,
        "enabled": True
    })
    mark_schedule_dirty()
    load_schedule_form()

def delete_time_slot(slot_idx):
    sync_schedule_form_to_memory()
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.get("settings", {}).get(setting_nm, {})
    slots = st.get("time_slots", [])
    if len(slots) <= 1:
        show_notification("Action Blocked", "At least one time slot is required!", "warning")
        return
    if 0 <= slot_idx < len(slots):
        slots.pop(slot_idx)
        for i, sl in enumerate(slots):
            sl["id"] = i + 1
            sl["name"] = f"Slot {i+1}"
        mark_schedule_dirty()
        load_schedule_form()

def delete_all_time_slots():
    sync_schedule_form_to_memory()
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
    slots = st.get("time_slots", [])
    if not slots:
        show_notification("Notice", "No time slots to delete!", "info")
        return
    def _do_clear():
        st["time_slots"] = []
        mark_schedule_dirty()
        load_schedule_form()
        show_notification("Cleared", "All time slots have been deleted!", "info")
    show_confirm_dialog("Delete All Slots", f"Are you sure you want to clear all {len(slots)} time slots for {setting_nm}?", _do_clear)

def on_sched_cancel_or_back():
    global sensor_setpoints, sched_dirty_flag
    if has_unsaved_schedule_changes():
        def _do_save_and_exit():
            save_current_schedule_to_file(show_feedback=True)
            show(frame_main)

        def _do_discard_and_exit():
            global sensor_setpoints, sched_dirty_flag
            if sched_clean_snapshot is not None:
                sensor_setpoints.clear()
                sensor_setpoints.update(copy.deepcopy(sched_clean_snapshot))
            sched_dirty_flag = False
            update_ui()
            show(frame_main)

        show_confirm_dialog(
            title="Unsaved Changes",
            message="Do you want to save your changes?",
            on_confirm=_do_save_and_exit,
            on_cancel=_do_discard_and_exit,
            confirm_text="✔ OK",
            cancel_text="✖ CANCEL"
        )
    else:
        show(frame_main)

# Populate permanently packed bottom action buttons
btn_save_sched = tk.Button(sched_btn_frame, text="SAVE SCHEDULE", font=BTN_FONT_MAIN, bg="#2e7d32", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: save_current_schedule_to_file(True))
btn_save_sched.pack(side="left", padx=10)

tk.Button(sched_btn_frame, text="ADD TIME SLOT", font=BTN_FONT_MAIN, bg="#ea580c", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=add_new_time_slot).pack(side="left", padx=10)

btn_toggle_stage_bottom = tk.Button(sched_btn_frame, text="DISABLE STAGE", font=BTN_FONT_MAIN, bg="#dc2626", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=toggle_current_stage_activation)
btn_toggle_stage_bottom.pack(side="left", padx=10)

tk.Button(sched_btn_frame, text="CANCEL / BACK", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=on_sched_cancel_or_back).pack(side="left", padx=10)

grids_wrapper = tk.Frame(sched_scroll_inner, bg="white")
grids_wrapper.pack(pady=2, anchor="center")

temp_grid_frame = tk.LabelFrame(grids_wrapper, text="TEMPERATURE SCHEDULE GRID ", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white", bd=2, relief="solid", highlightbackground="#94a3b8")
temp_grid_frame.pack(side="top", anchor="center", padx=8, pady=3)

humi_grid_frame = tk.LabelFrame(grids_wrapper, text="HUMIDITY SCHEDULE GRID ", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white", bd=2, relief="solid", highlightbackground="#94a3b8")
humi_grid_frame.pack(side="top", anchor="center", padx=8, pady=3)

def edit_slot_popup(idx):
    l_fname, l_tstart, l_tstop, l_tset_val, l_tmax_val, l_tmin_val, l_hset_val, l_hmax_val, l_hmin_val = sched_entries[idx]
    
    pop = tk.Toplevel(root)
    make_modal_fullscreen(pop)

    pop_main = tk.Frame(pop, bg="white")
    pop_main.pack(fill="both", expand=True, pady=(60, 45))

    add_logo(pop)
    add_top_left_exit(pop)
    add_bottom_right_clock(pop)

    header = tk.Frame(pop_main, bg="white")
    header.pack(pady=(5, 5))
    tk.Label(header, text=f"EDIT TIME SLOT {idx+1}", font=big, fg="#1565c0", bg="white").pack()

    body = tk.Frame(pop_main, bg="white")
    body.pack(pady=6, anchor="center")

    col1_f = tk.Frame(body, bg="white")
    col1_f.pack(side="left", padx=10, anchor="n")

    col2_f = tk.Frame(body, bg="white")
    col2_f.pack(side="left", padx=10, anchor="n")

    items = [
        ("Slot Name", l_fname, True),
        ("Start Time ", l_tstart, False),
        ("Stop Time ", l_tstop, False),
        ("TEMP SET ", l_tset_val, False),
        ("TEMP MAX ", l_tmax_val, False),
        ("TEMP MIN ", l_tmin_val, False),
        ("HUM SET ", l_hset_val, False),
        ("HUM MAX ", l_hmax_val, False),
        ("HUM MIN ", l_hmin_val, False),
    ]

    for i, (label, v_lbl, is_alpha) in enumerate(items):
        parent_col = col1_f if i < 5 else col2_f
        r_f = tk.Frame(parent_col, bg="white")
        r_f.pack(fill="x", pady=3)
        
        tk.Label(r_f, text=f"{label}:", font=("Helvetica", 10, "bold"), fg="#1e293b", bg="white", width=20, anchor="e").pack(side="left", padx=3)
        
        val_display = tk.Label(r_f, text=v_lbl.cget("text"), font=("Helvetica", 10, "bold"), bg="#f1f5f9", fg="#1565c0", width=12, relief="sunken", bd=1)
        val_display.pack(side="left", padx=3, ipady=2)

        def make_callback(orig_label, target_disp):
            def cb(new_val):
                orig_label.config(text=new_val)
                target_disp.config(text=new_val)
            return cb

        callback = make_callback(v_lbl, val_display)

        tk.Button(
            r_f,
            text="EDIT",
            font=BTN_FONT_INLINE,
            bg="#cbd5e1",
            fg="#1e293b",
            width=7,
            height=2,
            relief="flat",
            bd=0,
            cursor="hand2",
            command=lambda lbl=val_display, cb=callback, title=label, alpha=is_alpha: open_almora_keypad(
                f"Edit {title}", lbl.cget("text"), lambda v: (lbl.config(text=format_time_12h(v) if "Time" in title else v), cb(format_time_12h(v) if "Time" in title else v)), is_alphanumeric=alpha
            )
        ).pack(side="left", padx=3)

    def save_and_close_slot():
        skey = skey_combo.get()
        setting_nm = setting_combo.get()
        sp = get_setpoints(skey)
        st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
        slots = st.setdefault("time_slots", [])
        if 0 <= idx < len(slots):
            try:
                t_set_val = round(float(l_tset_val.cget("text").strip()), 1)
                h_set_val = round(float(l_hset_val.cget("text").strip()), 1)
                slots[idx] = {
                    "id": idx + 1,
                    "name": l_fname.cget("text").strip(),
                    "start": format_time_12h(l_tstart.cget("text").strip()),
                    "stop": format_time_12h(l_tstop.cget("text").strip()),
                    "t_set": t_set_val,
                    "t_max": round(float(l_tmax_val.cget("text").strip()), 1),
                    "t_min": round(float(l_tmin_val.cget("text").strip()), 1),
                    "h_set": h_set_val,
                    "h_max": round(float(l_hmax_val.cget("text").strip()), 1),
                    "h_min": round(float(l_hmin_val.cget("text").strip()), 1),
                    "enabled": True
                }
                save_setpoints()
                act_prog = sp.get("program_name")
                if act_prog and act_prog != "Default Program":
                    load_crop_programs()
                    st_content = copy.deepcopy(sp.get("settings", {}))
                    crop_programs[act_prog] = st_content
                    if skey not in crop_programs or not isinstance(crop_programs[skey], dict):
                        crop_programs[skey] = {}
                    crop_programs[skey][act_prog] = st_content
                    save_crop_programs()
            except Exception as e:
                print(f"Error updating slot: {e}")
        mark_schedule_dirty()
        pop.destroy()
        load_schedule_form()

    def cancel_slot():
        pop.destroy()
        load_schedule_form()

    btn_action_f = tk.Frame(pop_main, bg="white")
    btn_action_f.pack(side="bottom", pady=(10, 15))

    tk.Button(btn_action_f, text="SAVE & APPLY", font=BTN_FONT_MAIN, bg="#2e7d32", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=save_and_close_slot).pack(side="left", padx=15)
    tk.Button(btn_action_f, text="CANCEL/CLOSE", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=cancel_slot).pack(side="left", padx=15)

def load_schedule_form_refresh():
    load_schedule_form()

def load_schedule_form():
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    
    sp = get_setpoints(skey)
    st = sp.get("settings", {}).get(setting_nm, {})

    profile_disp_name = st.get("name", setting_nm)

    update_preset_dropdown_text()

    profile_dropdown_btn.config(text=f"{profile_disp_name}▼")
    lbl_val_stagename.config(text=profile_disp_name)
    lbl_val_sdate.config(text=format_date_dmy(st.get("start_date", "01-07-2026")))
    lbl_val_edate.config(text=format_date_dmy(st.get("end_date", "31-08-2026")))
    lbl_val_pon.config(text=format_time_12h(st.get("photoperiod_on", "06:00 AM")))
    lbl_val_poff.config(text=format_time_12h(st.get("photoperiod_off", "08:00 PM")))

    st_dict = sp.get("settings", {})
    active_count = sum(1 for sk in ALL_SETTINGS if st_dict.get(sk, {}).get("enabled", True))
    stages_count_dropdown_btn.config(text=f"{active_count} Stages ▼")

    stage_enabled = st.get("enabled", True)
    if stage_enabled:
        btn_toggle_stage_bottom.config(text="DISABLE STAGE", bg="#dc2626")
    else:
        btn_toggle_stage_bottom.config(text="ENABLE STAGE", bg="#16a34a")

    for widget in temp_grid_frame.winfo_children(): widget.destroy()
    for widget in humi_grid_frame.winfo_children(): widget.destroy()
    for widget in grids_wrapper.winfo_children():
        if widget not in (temp_grid_frame, humi_grid_frame):
            widget.destroy()
    sched_entries.clear()

    if not stage_enabled:
        dis_box = tk.Frame(grids_wrapper, bg="#fef2f2", bd=1, relief="solid", highlightbackground="#ef4444")
        dis_box.pack(fill="x", padx=10, pady=4)
        tk.Label(dis_box, text=f"THIS CROP STAGE ({profile_disp_name.upper()}) IS CURRENTLY DISABLED / OFF", font=("Helvetica", 11, "bold"), fg="#b91c1c", bg="#fef2f2").pack(padx=10, pady=6)

    time_slots = st.get("time_slots", [])

    overlaps = check_time_slot_overlaps(time_slots)
    if overlaps:
        w_box = tk.Frame(grids_wrapper, bg="#fef2f2", bd=1, relief="solid", highlightbackground="#ef4444")
        w_box.pack(fill="x", padx=10, pady=4)
        tk.Label(w_box, text=f" TIME SLOT OVERLAP DETECTED:\n" + "\n".join(overlaps), font=("Helvetica", 11, "bold"), fg="#b91c1c", bg="#fef2f2").pack(padx=10, pady=6)

    active_prog = sp.get("program_name", "Default Program")
    if 'lbl_sched_title' in globals() and lbl_sched_title.winfo_exists():
        lbl_sched_title.config(text=f"ALMORA SCHEDULE — PROGRAM: {active_prog.upper()}")
    temp_grid_frame.config(text=f"SCHEDULE TIME SLOTS — PROGRAM: {active_prog.upper()} [{profile_disp_name.upper()}]")
    humi_grid_frame.pack_forget()

    temp_inner = tk.Frame(temp_grid_frame, bg="white")
    temp_inner.pack(fill="x", expand=True, padx=8, pady=4)

    card_title_font = font.Font(size=13, weight="bold")
    card_time_font = font.Font(size=12, weight="bold")
    card_val_font = font.Font(size=12, weight="bold")
    btn_font_large = font.Font(size=11, weight="bold")

    num_slots = len(time_slots)

    for idx in range(num_slots):
        slot_data = time_slots[idx]
        
        frame_name_v = slot_data.get("name", f"Slot {idx+1}")
        t_set_v = slot_data.get("t_set", slot_data.get("temp_setpoint", 24.0))
        t_max_v = slot_data.get("t_max", t_set_v + 1.0)
        t_min_v = slot_data.get("t_min", t_set_v - 1.0)
        
        h_set_v = slot_data.get("h_set", slot_data.get("humi_setpoint", 60.0))
        h_max_v = slot_data.get("h_max", h_set_v + 5.0)
        h_min_v = slot_data.get("h_min", h_set_v - 5.0)
        
        start_v = format_time_12h(slot_data.get("start", "08:00 AM"))
        stop_v = format_time_12h(slot_data.get("stop", "12:00 PM"))

        l_fname = tk.Label(frame_schedule, text=frame_name_v)
        l_tstart = tk.Label(frame_schedule, text=start_v)
        l_tstop = tk.Label(frame_schedule, text=stop_v)
        l_tset_val = tk.Label(frame_schedule, text=str(t_set_v))
        l_tmax_val = tk.Label(frame_schedule, text=str(t_max_v))
        l_tmin_val = tk.Label(frame_schedule, text=str(t_min_v))
        l_hset_val = tk.Label(frame_schedule, text=str(h_set_v))
        l_hmax_val = tk.Label(frame_schedule, text=str(h_max_v))
        l_hmin_val = tk.Label(frame_schedule, text=str(h_min_v))

        sched_entries[idx] = (l_fname, l_tstart, l_tstop, l_tset_val, l_tmax_val, l_tmin_val, l_hset_val, l_hmax_val, l_hmin_val)

        # HORIZONTAL SLOT ROW: LEFT (NAME & TIME), MIDDLE (STACKED TEMP & HUMI), RIGHT (LARGE BUTTONS)
        row = tk.Frame(temp_inner, bg="#f8fafc", bd=2, relief="solid", highlightbackground="#cbd5e1", padx=12, pady=8)
        row.pack(fill="x", expand=True, pady=4)

        # LEFT SIDE: Slot Name & Time Window
        left_f = tk.Frame(row, bg="#f8fafc")
        left_f.pack(side="left", padx=(0, 15))

        tk.Label(left_f, text=f"{frame_name_v.upper()}", font=card_title_font, fg="#1565c0", bg="#f8fafc", anchor="w").pack(anchor="w")
        tk.Label(left_f, text=f"{start_v} - {stop_v}", font=card_time_font, fg="#334155", bg="#f8fafc", anchor="w").pack(anchor="w", pady=(2, 0))

        # RIGHT SIDE: Large Action Buttons (EDIT SLOT & DELETE)
        right_f = tk.Frame(row, bg="#f8fafc")
        right_f.pack(side="right", padx=(15, 0))

        tk.Button(right_f, text="EDIT SLOT", font=btn_font_large, bg="#cbd5e1", fg="#1e293b", width=13, height=2, relief="flat", bd=0, cursor="hand2", command=lambda i=idx: edit_slot_popup(i)).pack(side="left", padx=4)
        tk.Button(right_f, text="DELETE", font=btn_font_large, bg="#dc2626", fg="white", width=9, height=2, relief="flat", bd=0, cursor="hand2", command=lambda i=idx: delete_time_slot(i)).pack(side="left", padx=4)

        # MIDDLE SIDE: Stacked Temperature & Humidity Setpoints (TEMP, HUMI, MIN, MAX in Black)
        mid_f = tk.Frame(row, bg="#f8fafc")
        mid_f.pack(side="left", fill="both", expand=True, padx=10)

        # Temp Line (Names in Black, Values in Blue)
        t_row = tk.Frame(mid_f, bg="#f8fafc")
        t_row.pack(fill="x", anchor="w", pady=(0, 2))

        tk.Label(t_row, text="TEMP T : ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(t_row, text=f"{t_set_v:.1f}°C", font=card_val_font, fg="#1565c0", bg="#f8fafc").pack(side="left")
        tk.Label(t_row, text="   |   MIN: ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(t_row, text=f"{t_min_v:.1f}°C", font=card_val_font, fg="#1565c0", bg="#f8fafc").pack(side="left")
        tk.Label(t_row, text="   |   MAX: ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(t_row, text=f"{t_max_v:.1f}°C", font=card_val_font, fg="#1565c0", bg="#f8fafc").pack(side="left")

        # Humi Line (Names in Black, Values in Sky Blue)
        h_row = tk.Frame(mid_f, bg="#f8fafc")
        h_row.pack(fill="x", anchor="w", pady=(2, 0))

        tk.Label(h_row, text="HUMI T : ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(h_row, text=f"{h_set_v:.1f}%", font=card_val_font, fg="#0284c7", bg="#f8fafc").pack(side="left")
        tk.Label(h_row, text="   |   MIN: ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(h_row, text=f"{h_min_v:.1f}% ", font=card_val_font, fg="#0284c7", bg="#f8fafc").pack(side="left")
        tk.Label(h_row, text="   |   MAX: ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(h_row, text=f"{h_max_v:.1f}% ", font=card_val_font, fg="#0284c7", bg="#f8fafc").pack(side="left")

def open_schedule_editor(skey="S1"):
    global sched_clean_snapshot, sched_dirty_flag
    sched_clean_snapshot = copy.deepcopy(sensor_setpoints)
    sched_dirty_flag = False

    dname = get_sensor_display_name(skey)
    skey_combo.set(skey)
    sensor_dropdown_btn.config(text=f"{skey} — {dname}▼")
    setting_combo.set("Setting A")
    sp = get_setpoints(skey)
    settings_dict = sp.get("settings", {})
    p_name = settings_dict.get("Setting A", {}).get("name", "Crop Stage 1")
    profile_dropdown_btn.config(text=f"{p_name}▼")
    show(frame_schedule)
    load_schedule_form()

# --- SETPOINT STUDIO UI ---
active_setup_skey = "S1"
labels = {}
lbl_set_title = tk.Label(frame_set, text="SETPOINTS", font=big, fg="#1565c0", bg="white")
lbl_set_title.pack(pady=10)

setpoints_container = tk.Frame(frame_set, bg="white")
setpoints_container.pack(pady=15)

def open_setpoints(port):
    global active_setup_skey
    found_skey = "S1"
    for k, v in SENSOR_MAP.items():
        if v == port: found_skey = k; break
        
    active_setup_skey = found_skey
    lbl_set_title.config(text=f"SETPOINTS : {get_sensor_display_name(active_setup_skey)}")
    for widget in setpoints_container.winfo_children(): widget.destroy()
    labels.clear()
    sp = get_setpoints(active_setup_skey)
    for key in ["T MIN", "T MAX", "H MIN", "H MAX"]:
        row = tk.Frame(setpoints_container, bg="white"); row.pack(pady=5)
        tk.Label(row, text=key, font=med, width=10, bg="white", fg="#0f172a").pack(side="left")
        val_lbl = tk.Label(row, text=str(sp.get(key, 0)), font=med, fg="#e65100", bg="#f1f5f9", width=8, relief="sunken", bd=1)
        val_lbl.pack(side="left", padx=10)
        labels[key] = val_lbl
        
        tk.Button(row, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2",
                  command=lambda k=key, l=val_lbl: open_almora_keypad(f"Set {k}", l.cget("text"), lambda v: update_static_sp(k, v, l))).pack(side="left")
    show(frame_set)

def update_static_sp(key, value_str, label_widget):
    try:
        val = float(value_str)
        sp = get_setpoints(active_setup_skey)
        sp[key] = val
        label_widget.config(text=str(val))
        save_setpoints()
        update_ui()
        show_notification("Setpoint Updated", f"{key} set to {val} for {get_sensor_display_name(active_setup_skey)}", "success")
    except Exception as e: print(f"Set Error: {e}")

tk.Button(frame_set, text="SAVE & RETURN", font=BTN_FONT_MAIN, bg="#1565c0", fg="white", 
          width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: (save_setpoints(), show(frame_detail))).pack(side="bottom", pady=20)

# --- APP SHUTDOWN CLEANUP ---
def quit_app():
    global running
    running = False
    print("Saving setpoints & cleaning up relays before exit...")
    try:
        save_setpoints()
        save_crop_programs()
        save_config()
    except Exception as e:
        print(f"Quit save error: {e}")
    relay_port = system_config.get('relay_port')
    if relay_port:
        for ch in range(1, 23):
            set_relay(ch, False)
    root.destroy()

root.protocol("WM_DELETE_WINDOW", quit_app)

if __name__ == "__main__":
    print(f" STARTING ALMORA COLD ROOM MONITOR & CONTROLLER: {DEVICE_NAME} ")
    disable_wifi_power_save()
    load_config()
    load_crop_programs()
    load_setpoints()
    threading.Thread(target=auto_trust_devices, daemon=True).start()
    threading.Thread(target=start_bluetooth_server, daemon=True).start()
    threading.Thread(target=network_watchdog, daemon=True).start()
    threading.Thread(target=sync_offline_data_worker, daemon=True).start()
    threading.Thread(target=sensor_reader, daemon=True).start()
    show(frame_main)
    update_clock_display()
    update_ui()
    root.mainloop()
