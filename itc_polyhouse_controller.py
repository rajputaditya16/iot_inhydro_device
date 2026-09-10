#!/usr/bin/env python3
import time
import minimalmodbus
import threading
import json
import os
import datetime
import copy
import re
import tkinter as tk
from tkinter import font, ttk, messagebox
import sys
import paho.mqtt.client as mqtt
from PIL import Image, ImageTk

# -----------------------------------------------------------------------------
# BASE PATHS & DEVICE IDENTITY
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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

# Sprinkler Cyclic Timers (for CYCLIC mode)
sprinkler_cyclic_timers = {ph: {"state": "OFF", "switch_time": time.time()} for ph in ACTIVE_POLYHOUSES}

# Buzzer & Alarm State
buzzer_active = False
buzzer_start_time = 0
buzzer_silenced_for_current_alarm = False
buzzer_lock = threading.Lock()
active_warnings = []

# Sync & Upload Trackers
last_upload_time = 0
last_dli_calc_time = time.time()

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

def save_setpoints():
    try:
        os.makedirs(os.path.dirname(os.path.abspath(SETPOINTS_FILE)), exist_ok=True)
        with open(SETPOINTS_FILE, 'w') as f:
            json.dump(sensor_setpoints, f, indent=4)
        print(f"[STORAGE] Setpoints saved to {SETPOINTS_FILE}")
        broadcast_current_state()
    except Exception as e:
        print(f"Save Setpoints Error: {e}")

def get_setpoints(skey):
    if skey not in sensor_setpoints:
        sensor_setpoints[skey] = generate_default_itc_schedule(skey)
    return sensor_setpoints[skey]

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
        "acf_off_min": int(sp_data.get("acf_off_min", 30))
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
# HARDWARE RELAY CONTROL & BUZZER ROUTINES
# -----------------------------------------------------------------------------
def set_relay(channel, state):
    global working_relay_id
    if channel < 1 or channel > 32: return
    relay_states[channel] = bool(state)

    port = system_config.get("relay_port", RELAY_PORT_FIXED)
    if not os.path.exists(port): return

    slave_ids_to_try = [working_relay_id] if working_relay_id is not None else POSSIBLE_RELAY_IDS
    for s_id in slave_ids_to_try:
        if s_id is None: continue
        try:
            inst = minimalmodbus.Instrument(port, s_id)
            inst.serial.baudrate = RELAY_BAUD
            inst.serial.timeout = 0.2
            inst.close_port_after_each_call = True
            inst.write_bit(channel - 1, 1 if state else 0, functioncode=5)
            working_relay_id = s_id
            return
        except Exception: pass

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
    for ch in range(1, 33):
        set_relay(ch, False)
    print("[EMERGENCY] All 32 relays de-energized. System paused.")

# -----------------------------------------------------------------------------
# MQTT REMOTE SYNCHRONIZATION & TELEMETRY GATEWAY
# -----------------------------------------------------------------------------
CONTROL_TOPIC = f"inhydro/{DEVICE_NAME}/control"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"

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
            save_setpoints()
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
# MAIN AUTOMATION & SENSOR ACQUISITION THREAD
# -----------------------------------------------------------------------------
def sensor_reader():
    global running, system_paused, active_warnings, last_upload_time, last_dli_calc_time
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

        last_dli_calc_time = now

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
                current_warnings.append(f"{get_sensor_display_name(skey)} OFFLINE")
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
                # ACF Cyclic Timer
                timer_acf = acf_timers[skey]
                t_on_sec = float(sp_eval.get("acf_on_min", 15)) * 60.0
                t_off_sec = float(sp_eval.get("acf_off_min", 30)) * 60.0
                if timer_acf["state"] == "ON" and (now - timer_acf["switch_time"]) >= t_on_sec:
                    timer_acf["state"] = "OFF"; timer_acf["switch_time"] = now
                elif timer_acf["state"] == "OFF" and (now - timer_acf["switch_time"]) >= t_off_sec:
                    timer_acf["state"] = "ON"; timer_acf["switch_time"] = now
                set_relay(RELAY_CH_ACF[skey], timer_acf["state"] == "ON")

                # Sprinkler Cyclic Timer
                spr_cyc = sprinkler_cyclic_timers[skey]
                dur_s = float(sp_eval.get("sprinkler_duration_sec", 120))
                int_s = float(sp_eval.get("sprinkler_interval_min", 30)) * 60.0
                if spr_cyc["state"] == "ON" and (now - spr_cyc["switch_time"]) >= dur_s:
                    spr_cyc["state"] = "OFF"; spr_cyc["switch_time"] = now
                elif spr_cyc["state"] == "OFF" and (now - spr_cyc["switch_time"]) >= int_s:
                    spr_cyc["state"] = "ON"; spr_cyc["switch_time"] = now
                if spr_cyc["state"] == "ON":
                    water_requests.append(("SPRINKLER", skey))

            elif mode in ["AUTO", "SCHEDULE"]:
                # Check scheduled irrigation slots
                raw_sp = get_setpoints(skey)
                for islot in raw_sp.get("irrigation_slots", []):
                    if islot.get("enabled", True):
                        st_slot = format_time_24h(islot.get("start", "00:00"))
                        if st_slot == current_time_str:
                            req_type = str(islot.get("type", "sprinkler")).upper()
                            water_requests.append((req_type, skey))

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

        time.sleep(1.0)

# -----------------------------------------------------------------------------
# TKINTER GRAPHICAL USER INTERFACE (HMI)
# -----------------------------------------------------------------------------
root = tk.Tk()
root.title("INHYDRO ITC Polyhouse Automation System")
root.attributes("-fullscreen", True)
root.configure(bg="white")
root.geometry("1024x600")

big = font.Font(family="Helvetica", size=14, weight="bold")
med = font.Font(family="Helvetica", size=10, weight="bold")
small = font.Font(family="Helvetica", size=9)

FRAME_BTN_WIDTH = 18
FRAME_BTN_HEIGHT = 2
BTN_FONT_MAIN = ("Helvetica", 10, "bold")
BTN_FONT_INLINE = ("Helvetica", 8, "bold")

def quit_app():
    global running
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
frame_manual = tk.Frame(root, bg="white")

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
    for f in [frame_main, frame_detail, frame_set, frame_schedule, frame_manual]:
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

btn_cyclic_timers = tk.Button(footer_main, text="CYCLIC TIMERS", font=BTN_FONT_MAIN, width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, bg="#0284c7", fg="white", cursor="hand2", command=lambda: open_schedule_editor("PH-01"))
btn_cyclic_timers.pack(side="left", padx=10, pady=10)

btn_sys_settings = tk.Button(footer_main, text="SYSTEM SETTINGS", font=BTN_FONT_MAIN, width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, bg="#0891b2", fg="white", cursor="hand2", command=lambda: open_system_settings_modal())
btn_sys_settings.pack(side="left", padx=10, pady=10)

btn_restart_app = tk.Button(footer_main, text="RESTART", font=BTN_FONT_MAIN, width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, bg="#1565c0", fg="white", cursor="hand2", command=lambda: restart_program())
btn_restart_app.pack(side="left", padx=10, pady=10)

btn_pause = tk.Button(footer_main, text="STOP ALL", font=BTN_FONT_MAIN, width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, bg="#c62828", fg="white", cursor="hand2", command=lambda: toggle_pause())
btn_pause.pack(side="left", padx=10, pady=10)

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
        btn_pause.config(text="RESUME RUN", bg="#2e7d32")
    else:
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

# Operating Mode Switcher Bar
mode_frame = tk.Frame(frame_detail, bg="white")
mode_frame.pack(pady=4)

tk.Label(mode_frame, text="OPERATING MODE:", font=("Helvetica", 11, "bold"), bg="white", fg="#475569").pack(side="left", padx=8)

mode_buttons = {}
for m_name in ["AUTO", "MANUAL", "SCHEDULE", "CYCLIC"]:
    btn_m = tk.Button(mode_frame, text=m_name, font=("Helvetica", 10, "bold"), bg="#e2e8f0", fg="#1e293b",
                      width=10, height=1, relief="flat", bd=0, cursor="hand2")
    btn_m.config(command=lambda m=m_name: set_polyhouse_mode(m))
    btn_m.pack(side="left", padx=4)
    mode_buttons[m_name] = btn_m

def set_polyhouse_mode(new_mode):
    global active_detail_skey
    if active_detail_skey == "PH-06":
        messagebox.showinfo("Monitoring Zone", "PH-06 is a designated monitoring-only zone without actuator control.")
        return
    sp = get_setpoints(active_detail_skey)
    sp["mode"] = new_mode
    save_setpoints()
    update_mode_buttons_highlight()
    update_ui()

def update_mode_buttons_highlight():
    curr_mode = get_setpoints(active_detail_skey).get("mode", "AUTO").upper()
    for m, btn in mode_buttons.items():
        if m == curr_mode:
            btn.config(bg="#1565c0", fg="white")
        else:
            btn.config(bg="#e2e8f0", fg="#1e293b")

txt_detail_data = tk.Text(frame_detail, font=font.Font(size=11, weight="bold"), bg="white", bd=0, highlightthickness=0, height=18, width=75)
txt_detail_data.pack(pady=5, expand=True, fill="both")
txt_detail_data.tag_configure("black", foreground="#000000", justify="center")
txt_detail_data.tag_configure("blue", foreground="#1565c0", justify="center")
txt_detail_data.tag_configure("green", foreground="#16a34a", justify="center")
txt_detail_data.tag_configure("red", foreground="#c62828", justify="center")
txt_detail_data.tag_configure("grey", foreground="#64748b", justify="center")

btn_f_det = tk.Frame(frame_detail, bg="white")
btn_f_det.pack(side="bottom", pady=25)

btn_back_det = tk.Button(btn_f_det, text="BACK TO DASHBOARD", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: show(frame_main))
btn_back_det.pack(side="left", padx=6)

btn_set_det = tk.Button(btn_f_det, text="CONFIGURE SETPOINTS", font=BTN_FONT_MAIN, bg="#1565c0", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: open_setpoints(active_detail_port))
btn_set_det.pack(side="left", padx=6)

btn_sched_det = tk.Button(btn_f_det, text="CYCLIC TIMERS", font=BTN_FONT_MAIN, bg="#0284c7", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: open_schedule_editor(active_detail_skey))
btn_sched_det.pack(side="left", padx=6)

btn_manual_det = tk.Button(btn_f_det, text="MANUAL OVERRIDE", font=BTN_FONT_MAIN, bg="#ea580c", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: open_manual_control_for_house(active_detail_skey))
btn_manual_det.pack(side="left", padx=6)

btn_rename_det = tk.Button(btn_f_det, text="RENAME", font=BTN_FONT_MAIN, bg="#d97706", fg="white", width=12, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: edit_active_polyhouse_name())
btn_rename_det.pack(side="left", padx=6)

def open_sensor_detail(port):
    global active_detail_port, active_detail_skey
    active_detail_port = port
    active_detail_skey = next((k for k, v in SENSOR_MAP.items() if v == port), "PH-01")
    if active_detail_skey == "PH-06":
        lbl_detail_title.config(text=f"{get_sensor_display_name(active_detail_skey)} — ENVIRONMENTAL MONITORING")
        mode_frame.pack_forget()
        btn_sched_det.pack_forget()
        btn_manual_det.pack_forget()
        btn_set_det.config(text="CONFIGURE LIMITS")
    else:
        lbl_detail_title.config(text=f"{get_sensor_display_name(active_detail_skey)} — DETAILED CONTROL")
        mode_frame.pack(pady=4, before=txt_detail_data)
        btn_sched_det.pack(side="left", padx=6, after=btn_set_det)
        btn_manual_det.pack(side="left", padx=6, after=btn_sched_det)
        btn_set_det.config(text="CONFIGURE SETPOINTS")
        update_mode_buttons_highlight()
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
# SCREEN 13: MANUAL CONTROL & INDEPENDENT TESTING FRAME (frame_manual)
# -----------------------------------------------------------------------------
selected_manual_house = "PH-01"

lbl_man_title = tk.Label(frame_manual, text="SCREEN 13 : MANUAL CONTROL & TESTING (SAFETY INTERLOCKED)", font=big, fg="#ea580c", bg="white")
lbl_man_title.pack(pady=(35, 4))

man_house_bar = tk.Frame(frame_manual, bg="white")
man_house_bar.pack(pady=4)

tk.Label(man_house_bar, text="SELECT POLYHOUSE:", font=("Helvetica", 11, "bold"), bg="white", fg="#475569").pack(side="left", padx=6)

man_house_buttons = {}
for ph in ACTIVE_POLYHOUSES:
    b_ph = tk.Button(man_house_bar, text=ph, font=("Helvetica", 10, "bold"), bg="#e2e8f0", fg="#1e293b",
                     width=9, height=1, relief="flat", bd=0, cursor="hand2")
    b_ph.config(command=lambda p=ph: select_manual_house(p))
    b_ph.pack(side="left", padx=3)
    man_house_buttons[ph] = b_ph

def select_manual_house(ph):
    global selected_manual_house
    selected_manual_house = ph
    for p, b in man_house_buttons.items():
        if p == selected_manual_house: b.config(bg="#ea580c", fg="white")
        else: b.config(bg="#e2e8f0", fg="#1e293b")
    refresh_manual_card()

def open_manual_control_for_house(ph):
    if ph in ACTIVE_POLYHOUSES:
        select_manual_house(ph)
    show(frame_manual)

manual_cards_frame = tk.Frame(frame_manual, bg="white")
manual_cards_frame.pack(pady=10, padx=20, fill="both", expand=True)

# Polyhouse Actuators Card (Left)
man_left_card = tk.LabelFrame(manual_cards_frame, text="POLYHOUSE FIELD ACTUATORS", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white", padx=15, pady=15, bd=2, relief="solid")
man_left_card.pack(side="left", fill="both", expand=True, padx=10)

lbl_man_acf_stat = tk.Label(man_left_card, text="ACF (24 Fans): OFF", font=med, bg="white", fg="#c62828")
lbl_man_acf_stat.pack(pady=4)
btn_man_acf = tk.Button(man_left_card, text="TOGGLE ACF (24 FANS)", font=BTN_FONT_MAIN, bg="#1565c0", fg="white", width=24, height=2, cursor="hand2")
btn_man_acf.pack(pady=4)

lbl_man_spr_stat = tk.Label(man_left_card, text="Sprinkler Valve: CLOSED", font=med, bg="white", fg="#c62828")
lbl_man_spr_stat.pack(pady=4)
btn_man_spr = tk.Button(man_left_card, text="TOGGLE SPRINKLER VALVE", font=BTN_FONT_MAIN, bg="#0284c7", fg="white", width=24, height=2, cursor="hand2")
btn_man_spr.pack(pady=4)

lbl_man_fog_stat = tk.Label(man_left_card, text="Fogger Valve: CLOSED", font=med, bg="white", fg="#c62828")
lbl_man_fog_stat.pack(pady=4)
btn_man_fog = tk.Button(man_left_card, text="TOGGLE FOGGER VALVE", font=BTN_FONT_MAIN, bg="#0891b2", fg="white", width=24, height=2, cursor="hand2")
btn_man_fog.pack(pady=4)

# Global Common Equipment Card (Right)
man_right_card = tk.LabelFrame(manual_cards_frame, text="COMMON WATER PUMP & SAFETY INTERLOCKS", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white", padx=15, pady=15, bd=2, relief="solid")
man_right_card.pack(side="right", fill="both", expand=True, padx=10)

lbl_man_pump_stat = tk.Label(man_right_card, text="Common Water Pump: STOPPED", font=med, bg="white", fg="#c62828")
lbl_man_pump_stat.pack(pady=6)

lbl_pump_interlock_msg = tk.Label(man_right_card, text="Safety Rule: Pump requires at least 1 open valve\nto prevent deadhead pressure or dry running.", font=("Helvetica", 9), bg="#f8fafc", fg="#475569", relief="solid", bd=1, padx=8, pady=4)
lbl_pump_interlock_msg.pack(pady=4)

btn_man_pump = tk.Button(man_right_card, text="TOGGLE COMMON PUMP", font=BTN_FONT_MAIN, bg="#16a34a", fg="white", width=24, height=2, cursor="hand2")
btn_man_pump.pack(pady=6)

btn_test_buzzer = tk.Button(man_right_card, text="TEST HARDWARE BUZZER (5s)", font=BTN_FONT_MAIN, bg="#d97706", fg="white", width=24, height=1, cursor="hand2", command=lambda: trigger_buzzer_pulse(5.0))
btn_test_buzzer.pack(pady=6)

btn_emergency_stop = tk.Button(man_right_card, text="EMERGENCY ALL RELAYS OFF", font=BTN_FONT_MAIN, bg="#dc2626", fg="white", width=24, height=2, cursor="hand2", command=emergency_stop_all)
btn_emergency_stop.pack(pady=6)

def toggle_manual_acf():
    ch = RELAY_CH_ACF[selected_manual_house]
    new_state = not relay_states.get(ch, False)
    set_relay(ch, new_state)
    refresh_manual_card()

def toggle_manual_sprinkler():
    ch = RELAY_CH_SPRINKLER[selected_manual_house]
    new_state = not relay_states.get(ch, False)
    set_relay(ch, new_state)
    refresh_manual_card()

def toggle_manual_fogger():
    ch = RELAY_CH_FOGGER[selected_manual_house]
    new_state = not relay_states.get(ch, False)
    set_relay(ch, new_state)
    refresh_manual_card()

def toggle_manual_pump():
    global pump_active
    curr_pump = relay_states.get(RELAY_CH_COMMON_PUMP, False)
    if not curr_pump:
        # Safety Check: Is any water valve open?
        open_valves = [ph for ph in ACTIVE_POLYHOUSES if relay_states.get(RELAY_CH_SPRINKLER[ph]) or relay_states.get(RELAY_CH_FOGGER[ph])]
        if not open_valves:
            # Auto-open current sprinkler to protect pump
            set_relay(RELAY_CH_SPRINKLER[selected_manual_house], True)
            messagebox.showinfo("Safety Interlock", f"Auto-opened {selected_manual_house} sprinkler valve before starting pump to prevent deadhead overpressure.")
        set_relay(RELAY_CH_COMMON_PUMP, True)
        pump_active = True
    else:
        set_relay(RELAY_CH_COMMON_PUMP, False)
        pump_active = False
    refresh_manual_card()

btn_man_acf.config(command=toggle_manual_acf)
btn_man_spr.config(command=toggle_manual_sprinkler)
btn_man_fog.config(command=toggle_manual_fogger)
btn_man_pump.config(command=toggle_manual_pump)

def refresh_manual_card():
    ph = selected_manual_house
    ch_acf = RELAY_CH_ACF[ph]
    ch_spr = RELAY_CH_SPRINKLER[ph]
    ch_fog = RELAY_CH_FOGGER[ph]

    acf_st = relay_states.get(ch_acf, False)
    spr_st = relay_states.get(ch_spr, False)
    fog_st = relay_states.get(ch_fog, False)
    pump_st = relay_states.get(RELAY_CH_COMMON_PUMP, False)

    lbl_man_acf_stat.config(text=f"{ph} ACF (24 Fans): {'RUNNING (ON)' if acf_st else 'STOPPED (OFF)'}", fg="#16a34a" if acf_st else "#c62828")
    lbl_man_spr_stat.config(text=f"{ph} Sprinkler: {'OPEN' if spr_st else 'CLOSED'}", fg="#16a34a" if spr_st else "#c62828")
    lbl_man_fog_stat.config(text=f"{ph} Fogger: {'OPEN' if fog_st else 'CLOSED'}", fg="#16a34a" if fog_st else "#c62828")
    lbl_man_pump_stat.config(text=f"Common Water Pump: {'RUNNING' if pump_st else 'STOPPED'}", fg="#16a34a" if pump_st else "#c62828")

man_footer = tk.Frame(frame_manual, bg="white")
man_footer.pack(side="bottom", pady=20)
tk.Button(man_footer, text="BACK TO DASHBOARD", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: show(frame_main)).pack(side="left", padx=10)
tk.Button(man_footer, text="VIEW DETAILS", font=BTN_FONT_MAIN, bg="#1565c0", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: open_sensor_detail(SENSOR_MAP[selected_manual_house])).pack(side="left", padx=10)

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

    # TOP SECTION: 2 Equal Columns (Left: Climate Control, Right: Equipment Limits)
    sp_top_container = tk.Frame(sp_container, bg="#ffffff")
    sp_top_container.pack(fill="x", side="top", pady=(0, 4))

    left_sp_pane = tk.Frame(sp_top_container, bg="#ffffff")
    left_sp_pane.pack(side="left", fill="both", expand=True, padx=4)

    right_sp_pane = tk.Frame(sp_top_container, bg="#ffffff")
    right_sp_pane.pack(side="right", fill="both", expand=True, padx=4)

    # Card 1 (LEFT PANE): Climate Control
    card_climate = tk.LabelFrame(left_sp_pane, text=f" {disp_name} CLIMATE CONTROL ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
    card_climate.pack(fill="both", expand=True, pady=4, padx=4)

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
    tk.Frame(grid_climate, bg="#cbd5e1", width=1).pack(side="left", fill="y", padx=4, pady=2)

    # Right Column: Humidity Setpoints
    humi_section = tk.Frame(grid_climate, bg="#ffffff")
    humi_section.pack(side="right", fill="both", expand=True, padx=4)
    tk.Label(humi_section, text="HUMIDITY SETPOINTS", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff").pack(anchor="w", pady=(1, 3))
    make_sp_cell(humi_section, ph, "humi_low", "RH Min:").pack(fill="x", pady=2)
    make_sp_cell(humi_section, ph, "humi_target", "RH Set:").pack(fill="x", pady=2)
    make_sp_cell(humi_section, ph, "humi_high", "RH Max:").pack(fill="x", pady=2)
    make_sp_cell(humi_section, ph, "humi_hysteresis", "Hysteresis:").pack(fill="x", pady=2)

    # Card 2 (RIGHT PANE): Equipment Run/Rest Limits
    card_limits = tk.LabelFrame(right_sp_pane, text=f" {disp_name} EQUIPMENT RUN/REST LIMITS ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
    card_limits.pack(fill="both", expand=True, pady=4, padx=4)

    grid_limits = tk.Frame(card_limits, bg="#ffffff")
    grid_limits.pack(pady=4, padx=6, fill="x")

    make_sp_cell(grid_limits, ph, "fogger_min_on_sec", "Fogger Min ON (Sec):", width_lbl=20, default_val=60).pack(fill="x", pady=2)
    make_sp_cell(grid_limits, ph, "fogger_min_off_sec", "Fogger Min OFF (Sec):", width_lbl=20, default_val=120).pack(fill="x", pady=2)
    make_sp_cell(grid_limits, ph, "sprinkler_duration_sec", "Sprinkler Spray (Sec):", width_lbl=20, default_val=120).pack(fill="x", pady=2)
    make_sp_cell(grid_limits, ph, "sprinkler_interval_min", "Sprinkler Rest (Min):", width_lbl=20, default_val=30).pack(fill="x", pady=2)

    # BOTTOM SECTION: CYCLIC TIMERS (Exact monit.py design with build_timer_grid_box)
    sp_bottom_container = tk.Frame(sp_container, bg="#ffffff")
    sp_bottom_container.pack(fill="x", side="top", pady=(4, 6), padx=4)

    card_timers_1 = tk.LabelFrame(sp_bottom_container, text=f" {disp_name} CYCLIC TIMERS ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
    card_timers_1.pack(fill="x", pady=(3, 6), padx=4)

    cols_group = [
        {"name": "ACF Fans (24 Fans)", "load": "24 ACFs Group", "on_k": "acf_on_min", "on_unit": "Min", "off_k": "acf_off_min", "off_unit": "Min", "en_k": "acf_cycle_enabled"},
        {"name": "Sprinkler Valve",    "load": "Solenoid Ch " + str(RELAY_CH_SPRINKLER.get(ph, 6)), "on_k": "sprinkler_duration_sec", "on_unit": "Sec", "off_k": "sprinkler_interval_min", "off_unit": "Min", "en_k": None},
        {"name": "Fogger Valve",       "load": "Solenoid Ch " + str(RELAY_CH_FOGGER.get(ph, 11)), "on_k": "fogger_min_on_sec", "on_unit": "Sec", "off_k": "fogger_min_off_sec", "off_unit": "Sec", "en_k": None}
    ]

    header_frame = tk.Frame(card_timers_1, bg="#f1f5f9")
    header_frame.pack(fill="x", pady=4, padx=6)
    tk.Label(header_frame, text="Setting", font=("Arial", 10, "bold"), fg="#64748b", bg="#f1f5f9", width=12, anchor="w").pack(side="left", padx=2)

    for col in cols_group:
        col_hdr = tk.Frame(header_frame, bg="#f1f5f9")
        col_hdr.pack(side="left", expand=True, fill="x", padx=3)
        tk.Label(col_hdr, text=col["name"].upper(), font=("Arial", 10, "bold"), fg="#1565c0", bg="#f1f5f9", anchor="center").pack(side="left", expand=True, padx=2)

    # Row 1: Load Description
    r_load = tk.Frame(card_timers_1, bg="#ffffff"); r_load.pack(fill="x", pady=3, padx=6)
    tk.Label(r_load, text="Actuator Load:", font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", width=12, anchor="w").pack(side="left", padx=2)
    for col in cols_group:
        col_f = tk.Frame(r_load, bg="#ffffff"); col_f.pack(side="left", expand=True, fill="x", padx=3)
        tk.Label(col_f, text=col["load"], font=("Arial", 9), fg="#475569", bg="#ffffff", anchor="center").pack(side="left", expand=True)

    # Row 2: Status / Enable
    r_stat = tk.Frame(card_timers_1, bg="#ffffff"); r_stat.pack(fill="x", pady=3, padx=6)
    tk.Label(r_stat, text="Cyclic Status:", font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", width=12, anchor="w").pack(side="left", padx=2)
    for col in cols_group:
        col_f = tk.Frame(r_stat, bg="#ffffff"); col_f.pack(side="left", expand=True, fill="x", padx=3)
        if col["en_k"]:
            en_v = tk.BooleanVar(value=sp.get(col["en_k"], True))
            def _tog(k=col["en_k"], v=en_v):
                sp[k] = v.get(); save_setpoints()
            tk.Checkbutton(col_f, text="Cyclic Active", variable=en_v, font=("Arial", 9, "bold"), bg="#ffffff", fg="#1565c0", command=_tog).pack(anchor="center")
        else:
            tk.Label(col_f, text="Active in CYCLIC", font=("Arial", 9, "bold"), fg="#16a34a", bg="#ffffff").pack(anchor="center")

    # Row 3: ON Duration
    r_on = tk.Frame(card_timers_1, bg="#ffffff"); r_on.pack(fill="x", pady=3, padx=6)
    tk.Label(r_on, text="ON Duration:", font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", width=12, anchor="w").pack(side="left", padx=2)
    for col in cols_group:
        col_f = tk.Frame(r_on, bg="#ffffff"); col_f.pack(side="left", expand=True, fill="x", padx=3)
        on_k = col["on_k"]
        val_lbl = tk.Label(col_f, text=f"{sp.get(on_k, 0)} {col['on_unit']}", font=("Arial", 10, "bold"), fg="#e65100", bg="#f8fafc", width=8, anchor="center", relief="sunken", bd=1)
        val_lbl.pack(side="left", expand=True, padx=2)
        def _edit_on(k=on_k, l=val_lbl, u=col["on_unit"], nm=col["name"]):
            def _set(v):
                try:
                    iv = int(float(v))
                    sp[k] = iv
                    l.config(text=f"{iv} {u}")
                    save_setpoints()
                except Exception: pass
            open_almora_keypad(f"Set {ph} {nm} ON ({u})", str(sp.get(k, 0)), _set)
        tk.Button(col_f, text="EDIT", font=("Arial", 9, "bold"), width=5, bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="raised", pady=1, padx=3,
                  command=_edit_on).pack(side="right", padx=2)

    # Row 4: OFF Duration / Interval
    r_off = tk.Frame(card_timers_1, bg="#ffffff"); r_off.pack(fill="x", pady=3, padx=6)
    tk.Label(r_off, text="OFF Interval:", font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", width=12, anchor="w").pack(side="left", padx=2)
    for col in cols_group:
        col_f = tk.Frame(r_off, bg="#ffffff"); col_f.pack(side="left", expand=True, fill="x", padx=3)
        off_k = col["off_k"]
        val_lbl2 = tk.Label(col_f, text=f"{sp.get(off_k, 0)} {col['off_unit']}", font=("Arial", 10, "bold"), fg="#e65100", bg="#f8fafc", width=8, anchor="center", relief="sunken", bd=1)
        val_lbl2.pack(side="left", expand=True, padx=2)
        def _edit_off(k=off_k, l=val_lbl2, u=col["off_unit"], nm=col["name"]):
            def _set(v):
                try:
                    iv = int(float(v))
                    sp[k] = iv
                    l.config(text=f"{iv} {u}")
                    save_setpoints()
                except Exception: pass
            open_almora_keypad(f"Set {ph} {nm} OFF ({u})", str(sp.get(k, 0)), _set)
        tk.Button(col_f, text="EDIT", font=("Arial", 9, "bold"), width=5, bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="raised", pady=1, padx=3,
                  command=_edit_off).pack(side="right", padx=2)

    # Quick Matrix: All 5 Polyhouses ACF Fans
    card_all = tk.LabelFrame(sp_bottom_container, text=" ALL 5 POLYHOUSES ACF CYCLIC TIMERS QUICK VIEW ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
    card_all.pack(fill="x", pady=(6, 12), padx=4)

    grid_all = tk.Frame(card_all, bg="#ffffff")
    grid_all.pack(fill="x", pady=4, padx=6)

    for idx, p_house in enumerate(ACTIVE_POLYHOUSES):
        p_sp = get_setpoints(p_house)
        b_box = tk.Frame(grid_all, bg="#f8fafc", bd=1, relief="solid", padx=6, pady=4)
        b_box.grid(row=0, column=idx, padx=4, pady=2, sticky="nsew")
        grid_all.columnconfigure(idx, weight=1)

        tk.Label(b_box, text=p_house, font=("Arial", 10, "bold"), fg="#1565c0", bg="#f8fafc").pack(anchor="center")
        tk.Label(b_box, text=f"ON: {p_sp.get('acf_on_min', 15)} Min", font=("Arial", 9), fg="#334155", bg="#f8fafc").pack(anchor="center")
        tk.Label(b_box, text=f"OFF: {p_sp.get('acf_off_min', 30)} Min", font=("Arial", 9), fg="#334155", bg="#f8fafc").pack(anchor="center")
        st_t = "Active" if p_sp.get("acf_cycle_enabled", True) else "Disabled"
        tk.Label(b_box, text=st_t, font=("Arial", 9, "bold"), fg="#16a34a" if st_t == "Active" else "#dc2626", bg="#f8fafc").pack(anchor="center")

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
# FULLSCREEN TOUCH KEYPAD MODAL (NUMERIC, TIME, CALENDAR, ALPHANUMERIC)
# -----------------------------------------------------------------------------
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

    if mode is None:
        if is_alphanumeric: mode = "alphanumeric"
        elif "Time" in title_text or "time" in title_text: mode = "time"
        elif "Date" in title_text or "date" in title_text: mode = "calendar"
        else: mode = "numeric"

    keypad_modal = tk.Toplevel(root)
    make_modal_fullscreen(keypad_modal)

    kp_main = tk.Frame(keypad_modal, bg="white")
    kp_main.pack(fill="both", expand=True, pady=(45, 30))

    add_logo(keypad_modal)
    add_top_left_exit(keypad_modal)
    add_bottom_right_clock(keypad_modal)

    entered_val = str(initial_value)

    lbl_modal_title = tk.Label(kp_main, text=title_text, font=big, fg="#1565c0", bg="white")
    lbl_modal_title.pack(pady=4)

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

    kp_buttons_frame = tk.Frame(kp_main, bg="white")
    kp_buttons_frame.pack(pady=4)

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

    elif mode == "time":
        shortcut_f = tk.Frame(kp_buttons_frame, bg="white")
        shortcut_f.grid(row=0, column=0, columnspan=4, pady=(0, 4))
        for ts in ["06:00 AM", "08:00 AM", "12:00 PM", "04:00 PM", "08:00 PM"]:
            tk.Button(shortcut_f, text=ts, font=("Helvetica", 9, "bold"), bg="#e0f2fe", fg="#0369a1", relief="flat", padx=6, pady=3,
                      command=lambda x=ts: kp_set_val(x)).pack(side="left", padx=2)

        time_grid = [
            ('7', 1, 0), ('8', 1, 1), ('9', 1, 2), (':', 1, 3),
            ('4', 2, 0), ('5', 2, 1), ('6', 2, 2), ('AM', 2, 3),
            ('1', 3, 0), ('2', 3, 1), ('3', 3, 2), ('PM', 3, 3),
            ('0', 4, 0), ('00', 4, 1), (' ', 4, 2), ('CLR', 4, 3)
        ]
        for t, r, c in time_grid:
            cmd = kp_clear if t == 'CLR' else (lambda x=t: kp_press(x))
            tk.Button(kp_buttons_frame, text=t, font=("Arial", 14, "bold"), width=6, height=1, bg="#f1f5f9", fg="#0f172a",
                      activebackground="#0284c7", activeforeground="white", relief="flat", bd=1, cursor="hand2", command=cmd).grid(row=r, column=c, padx=4, pady=3)

    elif mode == "calendar":
        try:
            curr_d = datetime.datetime.strptime(entered_val, "%Y-%m-%d")
        except Exception:
            curr_d = datetime.datetime.now()

        cal_year, cal_month = curr_d.year, curr_d.month

        cal_header = tk.Frame(kp_buttons_frame, bg="white")
        cal_header.grid(row=0, column=0, columnspan=7, pady=(0, 4))
        lbl_month_year = tk.Label(cal_header, text=f"{datetime.date(cal_year, cal_month, 1).strftime('%B %Y')}", font=("Helvetica", 12, "bold"), fg="#1565c0", bg="white", width=18)

        def change_month(delta):
            nonlocal cal_year, cal_month
            cal_month += delta
            if cal_month > 12: cal_month = 1; cal_year += 1
            elif cal_month < 1: cal_month = 12; cal_year -= 1
            lbl_month_year.config(text=f"{datetime.date(cal_year, cal_month, 1).strftime('%B %Y')}")
            render_days()

        tk.Button(cal_header, text="◀ PREV", font=BTN_FONT_INLINE, bg="#cbd5e1", command=lambda: change_month(-1)).pack(side="left", padx=5)
        lbl_month_year.pack(side="left", padx=5)
        tk.Button(cal_header, text="NEXT ▶", font=BTN_FONT_INLINE, bg="#cbd5e1", command=lambda: change_month(1)).pack(side="left", padx=5)

        days_frame = tk.Frame(kp_buttons_frame, bg="white")
        days_frame.grid(row=1, column=0, columnspan=7, pady=2)

        def render_days():
            for w in days_frame.winfo_children(): w.destroy()
            for ci, day_n in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
                tk.Label(days_frame, text=day_n, font=("Helvetica", 9, "bold"), fg="#64748b", bg="white", width=4).grid(row=0, column=ci, padx=2, pady=1)

            first_day = datetime.date(cal_year, cal_month, 1)
            start_weekday = first_day.weekday()
            next_m = datetime.date(cal_year + (1 if cal_month == 12 else 0), 1 if cal_month == 12 else cal_month + 1, 1)
            num_days = (next_m - first_day).days

            row_i, col_i = 1, start_weekday
            for d_num in range(1, num_days + 1):
                d_str = f"{cal_year:04d}-{cal_month:02d}-{d_num:02d}"
                tk.Button(days_frame, text=str(d_num), font=("Helvetica", 10, "bold"), width=4, height=1, bg="#f1f5f9", relief="flat",
                          command=lambda s=d_str: kp_set_val(s)).grid(row=row_i, column=col_i, padx=2, pady=2)
                col_i += 1
                if col_i > 6: col_i = 0; row_i += 1

        render_days()

    else:
        # Alphanumeric Keyboard
        keys_rows = [
            list("1234567890-"),
            list("QWERTYUIOP"),
            list("ASDFGHJKL"),
            list("ZXCVBNM_")
        ]
        for ri, row_keys in enumerate(keys_rows):
            rf = tk.Frame(kp_buttons_frame, bg="white"); rf.pack(pady=2)
            for k in row_keys:
                tk.Button(rf, text=k, font=("Arial", 12, "bold"), width=3, bg="#f1f5f9", relief="flat", command=lambda x=k: kp_press(x)).pack(side="left", padx=2)
        rf_sp = tk.Frame(kp_buttons_frame, bg="white"); rf_sp.pack(pady=2)
        tk.Button(rf_sp, text="SPACE", font=("Arial", 10, "bold"), width=15, bg="#f1f5f9", relief="flat", command=lambda: kp_press(" ")).pack(side="left", padx=2)

    # Action Controls Bottom
    actions_f = tk.Frame(kp_main, bg="white")
    actions_f.pack(pady=6)

    tk.Button(actions_f, text="⌫ BACKSPACE", font=BTN_FONT_MAIN, width=14, height=1, bg="#94a3b8", fg="white", relief="flat", command=kp_back).pack(side="left", padx=4)
    tk.Button(actions_f, text="CLEAR", font=BTN_FONT_MAIN, width=10, height=1, bg="#64748b", fg="white", relief="flat", command=kp_clear).pack(side="left", padx=4)
    tk.Button(actions_f, text="CANCEL", font=BTN_FONT_MAIN, width=10, height=1, bg="#dc2626", fg="white", relief="flat", command=keypad_modal.destroy).pack(side="left", padx=4)
    tk.Button(actions_f, text="✔ CONFIRM", font=BTN_FONT_MAIN, width=14, height=1, bg="#16a34a", fg="white", relief="flat", command=kp_confirm).pack(side="left", padx=4)

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

                txt_detail_data.insert("end", f"OPERATING MODE : {sp_eval.get('mode', 'AUTO')}\n", "blue")
                txt_detail_data.insert("end", f"TEMP TARGET: {sp_eval['target_temp']:.1f} °C  (Range: {sp_eval['T MIN']:.1f} - {sp_eval['T MAX']:.1f} °C)\n", "black")
                txt_detail_data.insert("end", f"HUMI TARGET: {sp_eval['target_humi']:.1f} %   (Range: {sp_eval['H MIN']:.1f} - {sp_eval['H MAX']:.1f} %)\n\n", "black")

                acf_s = "ON" if relay_states.get(RELAY_CH_ACF[skey]) else "OFF"
                spr_s = "OPEN" if relay_states.get(RELAY_CH_SPRINKLER[skey]) else "CLOSED"
                fog_s = "OPEN" if relay_states.get(RELAY_CH_FOGGER[skey]) else "CLOSED"
                pump_s = "RUNNING" if relay_states.get(RELAY_CH_COMMON_PUMP) else "IDLE"

                txt_detail_data.insert("end", "Air Circulation Fans (24 ACFs): ", "black")
                txt_detail_data.insert("end", f"{acf_s}\n", "green" if acf_s == "ON" else "red")
                txt_detail_data.insert("end", "Sprinkler Solenoid Valve:      ", "black")
                txt_detail_data.insert("end", f"{spr_s}\n", "green" if spr_s == "OPEN" else "red")
                txt_detail_data.insert("end", "Fogger Solenoid Valve:         ", "black")
                txt_detail_data.insert("end", f"{fog_s}\n", "green" if fog_s == "OPEN" else "red")
                txt_detail_data.insert("end", "Common Water Pump Motor:       ", "black")
                txt_detail_data.insert("end", f"{pump_s}\n", "green" if pump_s == "RUNNING" else "grey")

            txt_detail_data.config(state="disabled")

        # 4. Update Manual Screen if open
        if frame_manual.winfo_ismapped():
            refresh_manual_card()

    except Exception as e:
        print(f"UI Update Error: {e}")

    root.after(1000, update_ui)

# -----------------------------------------------------------------------------
# STARTUP INITIALIZATION
# -----------------------------------------------------------------------------
load_config()
load_setpoints()
load_dli_history()

if __name__ == "__main__":
    # Start background automation thread
    reader_thread = threading.Thread(target=sensor_reader, daemon=True)
    reader_thread.start()

    # Build and start UI
    rebuild_grid()
    show(frame_main)
    root.after(500, update_clock_display)
    root.after(1000, update_ui)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        quit_app()
