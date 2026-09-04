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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                val = f.read().strip()
                if val: return val
        except: pass
    return "iot_monitor" # Default fallback

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
    'upload_frequency_min': 0,
    'temp_alarm_offset': 5.0,
    'humi_alarm_offset': 5.0
}
sensor_data = {}
sensor_setpoints = {}
crop_programs = {}
sensor_data_lock = threading.Lock()
running = True
system_paused = False
relay_states = {}

# BUZZER & ALARM STATE
buzzer_active = False
buzzer_lock = threading.Lock()
active_warnings = []

# SYNC TRACKERS
ts_rotation_idx = 0
mqtt_timer = 0
last_upload_time = 0

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

def generate_default_almora_schedule():
    stages = {}
    setting_keys = [
        ("Setting A", "Crop Stage 1", "2026-07-01", "2026-07-15"),
        ("Setting B", "Crop Stage 2", "2026-07-16", "2026-07-31"),
        ("Setting C", "Crop Stage 3", "2026-08-01", "2026-08-15"),
        ("Setting D", "Crop Stage 4", "2026-08-16", "2026-08-31"),
        ("Setting E", "Crop Stage 5", "2026-09-01", "2026-09-15"),
        ("Setting F", "Crop Stage 6", "2026-09-16", "2026-09-30"),
        ("Setting G", "Crop Stage 7", "2026-10-01", "2026-10-15"),
        ("Setting H", "Crop Stage 8", "2026-10-16", "2026-10-31"),
        ("Setting I", "Crop Stage 9", "2026-11-01", "2026-11-15"),
        ("Setting J", "Crop Stage 10", "2026-11-16", "2026-11-30")
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
        "T MIN": 10.0,
        "T MAX": 30.0,
        "H MIN": 30.0,
        "H MAX": 80.0,
        "settings": stages
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

def load_crop_programs():
    global crop_programs
    if os.path.exists(CROP_PROGRAMS_FILE):
        try:
            with open(CROP_PROGRAMS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    is_room_structured = any(k in SENSOR_MAP for k in data.keys())
                    if is_room_structured:
                        crop_programs = data
                    else:
                        crop_programs = {"S1": copy.deepcopy(data)}
                else:
                    crop_programs = {}
        except Exception: crop_programs = {}
    else:
        crop_programs = {}
        
    for skey in SENSOR_MAP.keys():
        if skey not in crop_programs or not isinstance(crop_programs[skey], dict):
            crop_programs[skey] = {}

def get_room_crop_programs(skey):
    load_crop_programs()
    if skey not in crop_programs or not isinstance(crop_programs[skey], dict):
        crop_programs[skey] = {}
    return crop_programs[skey]

def save_crop_programs():
    try:
        with open(CROP_PROGRAMS_FILE, 'w') as f:
            json.dump(crop_programs, f, indent=4)
    except Exception as e:
        print(f"Save Program Error: {e}")

def load_config():
    global system_config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                system_config = json.load(f)
        except Exception: pass
    if 'upload_frequency_min' not in system_config:
        system_config['upload_frequency_min'] = 0
    if 'temp_alarm_offset' not in system_config:
        system_config['temp_alarm_offset'] = 5.0
    if 'humi_alarm_offset' not in system_config:
        system_config['humi_alarm_offset'] = 5.0

def save_config():
    with open(CONFIG_FILE, 'w') as f:
        json.dump(system_config, f, indent=4)

def load_setpoints():
    global sensor_setpoints
    if os.path.exists(SETPOINTS_FILE):
        try:
            with open(SETPOINTS_FILE, 'r') as f:
                sensor_setpoints = json.load(f)
        except Exception: pass
    
    for skey in SENSOR_MAP.keys():
        if skey not in sensor_setpoints:
            sensor_setpoints[skey] = copy.deepcopy(generate_default_almora_schedule())
        else:
            if "settings" not in sensor_setpoints[skey]:
                defaults = copy.deepcopy(generate_default_almora_schedule())
                defaults.update(sensor_setpoints[skey])
                sensor_setpoints[skey] = defaults
            else:
                defaults = copy.deepcopy(generate_default_almora_schedule())
                for k, v in defaults["settings"].items():
                    if k not in sensor_setpoints[skey]["settings"]:
                        sensor_setpoints[skey]["settings"][k] = copy.deepcopy(v)

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
        payload = {
            "device_id": DEVICE_NAME,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "system_config": system_config,
            "sensor_setpoints": sensor_setpoints,
            "sensor_data": snap_sensor_data,
            "active_warnings": active_warnings,
            "relay_states": relay_states
        }
        try:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(payload), retain=True)
            print(f"[SYNC→WEB] Sent setpoints & telemetry update to {CURRENT_SETP_TOPIC[-20:]}")
        except Exception as e: print(f"Broadcast err: {e}")

def get_setpoints(skey):
    if skey not in sensor_setpoints:
        sensor_setpoints[skey] = generate_default_almora_schedule()
    return sensor_setpoints[skey]

def get_active_setpoints(skey):
    sp_data = get_setpoints(skey)
    mode = sp_data.get("mode", "SCHEDULED")
    
    t_min = float(sp_data.get("T MIN", 10.0))
    t_max = float(sp_data.get("T MAX", 30.0))
    h_min = float(sp_data.get("H MIN", 30.0))
    h_max = float(sp_data.get("H MAX", 80.0))
    
    active_info = {
        "skey": skey,
        "setting_name": "STATIC",
        "program_name": "Default Program",
        "stage_name": "Stage 1",
        "slot_id": 1,
        "start": "08:00 AM",
        "stop": "12:00 PM",
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

    if mode != "SCHEDULED":
        return active_info

    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist_tz)
    today_str = now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%H:%M")

    settings = sp_data.get("settings", {})
    setting_keys = ["Setting A", "Setting B", "Setting C", "Setting D", "Setting E", 
                    "Setting F", "Setting G", "Setting H", "Setting I", "Setting J"]

    for set_key in setting_keys:
        setting = settings.get(set_key)
        if not setting or not setting.get("enabled", True):
            continue

        s_date = setting.get("start_date", "")
        e_date = setting.get("end_date", "")

        if s_date and e_date:
            if not (s_date <= today_str <= e_date):
                continue

        p_on = setting.get("photoperiod_on", "06:00 AM")
        p_off = setting.get("photoperiod_off", "08:00 PM")
        l_enabled = setting.get("lighting_enabled", True)

        time_slots = setting.get("time_slots", [])
        for slot in time_slots:
            if not slot.get("enabled", True):
                continue

            start_t = format_time_24h(slot.get("start", "00:00"))
            stop_t = format_time_24h(slot.get("stop", "23:59"))

            is_in_slot = False
            if start_t <= stop_t:
                is_in_slot = (start_t <= current_time_str <= stop_t)
            else:
                is_in_slot = (current_time_str >= start_t or current_time_str <= stop_t)

            if is_in_slot:
                t_set_v = float(slot.get("t_set", slot.get("temp_setpoint", 24.0)))
                h_set_v = float(slot.get("h_set", slot.get("humi_setpoint", 60.0)))
                t_max_v = float(slot.get("t_max", t_set_v + 1.0))
                t_min_v = float(slot.get("t_min", t_set_v - 1.0))
                h_max_v = float(slot.get("h_max", h_set_v + 5.0))
                h_min_v = float(slot.get("h_min", h_set_v - 5.0))

                s_name = slot.get("name", slot.get("stage_name", f"Slot {slot.get('id', 1)}"))

                active_info.update({
                    "setting_name": setting.get("name", set_key),
                    "program_name": setting.get("name", set_key),
                    "stage_name": s_name,
                    "slot_id": slot.get("id", 1),
                    "start": slot.get("start", "08:00 AM"),
                    "stop": slot.get("stop", "12:00 PM"),
                    "target_temp": round(t_set_v, 1),
                    "target_humi": round(h_set_v, 1),
                    "photoperiod_on": p_on,
                    "photoperiod_off": p_off,
                    "lighting_enabled": l_enabled,
                    "T MIN": round(t_min_v, 1),
                    "T MAX": round(t_max_v, 1),
                    "H MIN": round(h_min_v, 1),
                    "H MAX": round(h_max_v, 1)
                })
                return active_info

    return active_info

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

def set_wifi(ssid, password):
    try:
        subprocess.run(['sudo', 'nmcli', 'connection', 'delete', ssid], capture_output=True)
        cmd = ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid, 'password', password]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if "key-mgmt" in res.stderr:
            res = subprocess.run(cmd + ['wifi-sec.key-mgmt', 'wpa-psk'], capture_output=True, text=True)
        return f"SUCCESS: Connected to {ssid}!" if res.returncode == 0 else f"FAILED: {res.stderr.strip()}"
    except Exception as e: return f"ERROR: {str(e)}"

def scan_wifi():
    try:
        res = subprocess.run(['sudo', 'nmcli', '-t', '-f', 'SSID', 'dev', 'wifi'], capture_output=True, text=True)
        if res.returncode == 0:
            names = sorted(list(set([n.strip() for n in res.stdout.split('\n') if n.strip()])))
            return "\r\n".join([f"{i+1}. {n}" for i, n in enumerate(names)]) if names else "No networks"
        return "SCAN FAILED"
    except Exception as e: return f"ERROR: {str(e)}"

def auto_trust_devices():
    try:
        btctl = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        for cmd in ["power on", "agent NoInputNoOutput", "default-agent", "discoverable on", "pairable on"]:
            btctl.stdin.write(cmd + "\n")
        btctl.stdin.flush()
    except: pass
    while True:
        try:
            out = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True)
            for line in out.split('\n'):
                if line.startswith('Device '): os.system(f"sudo bluetoothctl trust {line.split(' ')[1]} >/dev/null 2>&1")
        except: pass
        time.sleep(5)

def restart_program():
    global running; running = False
    os.execl(sys.executable, sys.executable, *sys.argv)

def start_bluetooth_server():
    try:
        os.system("sudo sdptool add SP >/dev/null 2>&1"); time.sleep(1)
        srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((socket.BDADDR_ANY, 1))
        except OSError:
            # Address already in use retry logic
            time.sleep(2)
            try: srv.bind((socket.BDADDR_ANY, 1))
            except: return
        srv.listen(1)
        while True:
            try:
                client, _ = srv.accept()
                client.send("\r\n Inhydro Cold Room Almora Controller \r\nCommands: WIFI:SSID:PASS, SCAN:NEARBY WiFi\r\n".encode())
                while True:
                    data = client.recv(1024)
                    if not data: break
                    txt = data.decode().strip()
                    if txt.startswith("WIFI:"):
                        p = txt.split(":")
                        if len(p) >= 3: client.send(f"{set_wifi(p[1], ':'.join(p[2:]))}\r\n".encode())
                    elif txt.startswith("ID:"):
                        with open(ID_FILE, "w") as f: f.write(txt.split(":")[1].strip())
                        client.send("ID Saved! Rebooting...\r\n".encode())
                        try: root.after(2000, restart_program)
                        except: pass
                    elif txt == "SCAN": client.send(f"{scan_wifi()}\r\n".encode())
            except: pass
            finally: 
                if 'client' in locals(): client.close()
    except Exception as e: print("BT Info:", e)



CONTROL_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/update"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"

_safe_client_id = f"Almora_{DEVICE_NAME}_{_uuid.uuid4().hex[:8]}"
try:
    control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, _safe_client_id)
except AttributeError:
    control_client = mqtt.Client(_safe_client_id)

def on_control_message(client, userdata, msg):
    try:
        global system_config, sensor_setpoints

        if msg.topic == CONTROL_SYNC_TOPIC:
            broadcast_current_state()
            return

        new_data = json.loads(msg.payload.decode())
        raw_port = str(new_data.get("port", "")).strip()
        m = _re.search(r'\d+', raw_port)
        if not raw_port or raw_port.lower() in ["default", "global", "null", "none"]:
            skeys_to_update = list(SENSOR_MAP.keys())
        elif m:
            target = f"S{m.group()}"
            skeys_to_update = [target] if target in SENSOR_MAP else []
        else:
            skeys_to_update = []

        for skey in skeys_to_update:
            sp = get_setpoints(skey)
            if "settings" in new_data:
                sp["settings"] = new_data["settings"]
            for k in ["T MAX", "T MIN", "H MAX", "H MIN", "mode"]:
                if k in new_data:
                    sp[k] = new_data[k]

        save_setpoints()

        def _refresh():
            if frame_schedule.winfo_ismapped():
                load_schedule_form()
            elif frame_set.winfo_ismapped():
                open_setpoints(active_detail_port)
        try: root.after(0, _refresh)
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
except Exception as e: pass

def set_relay(channel, state):
    global working_relay_id
    relay_port = system_config.get('relay_port')
    if not relay_port or "PLACE" in relay_port: return False
    
    ids_to_try = [working_relay_id] if working_relay_id is not None else POSSIBLE_RELAY_IDS
    for r_id in ids_to_try:
        if r_id is None: continue
        try:
            instrument = minimalmodbus.Instrument(relay_port, r_id)
            instrument.serial.baudrate = RELAY_BAUD
            instrument.serial.timeout = 0.5
            instrument.serial.stopbits = 1
            instrument.serial.parity = minimalmodbus.serial.PARITY_NONE
            instrument.mode = minimalmodbus.MODE_RTU
            instrument.write_bit(channel - 1, 1 if state else 0, functioncode=5)
            working_relay_id = r_id
            return True 
        except Exception: pass
        finally:
            if 'instrument' in locals() and hasattr(instrument, 'serial') and instrument.serial:
                try: instrument.serial.close()
                except: pass
    return False

def sensor_reader():
    global running, system_paused, active_warnings, last_upload_time
    while running:
        if system_paused:
            time.sleep(1.0); continue
            
        system_config['relay_port'] = RELAY_PORT_FIXED
        
        # 1. READ ALL SENSORS (TEMP, HUMIDITY, CO2)
        for skey, port in SENSOR_MAP.items():
            if not running or system_paused: break
            sensor_id = int(skey.replace('S', ''))
            
            if not os.path.exists(port):
                with sensor_data_lock: sensor_data[port] = {'id': sensor_id, 'status': 'OFFLINE'}
                continue

            time.sleep(DELAY_BETWEEN_PORTS)
            try:
                values = None
                for baud in [4800, 9600]:
                    for slave_id in [SLAVE_ID, 1, 2, 3, 255]:
                        try:
                            instrument = minimalmodbus.Instrument(port, slave_id)
                            instrument.serial.baudrate = baud
                            instrument.serial.timeout = 0.2
                            instrument.close_port_after_each_call = True
                            
                            for fc in [4, 3]:
                                for addr in [0, 1]:
                                    try:
                                        res = instrument.read_registers(addr, 2, functioncode=fc)
                                        if res and len(res) >= 2 and (res[0] > 0 or res[1] > 0):
                                            values = res
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
                if val0 > 150: val0 /= 10.0
                if val1 > 150: val1 /= 10.0

                # Intelligent Auto-Detection of Temp & Humidity Registers
                if val0 > val1 and val0 > 45.0:
                    humi = val0
                    temp = val1
                else:
                    temp = val0
                    humi = val1

                # 2. SEPARATE OPTIONAL CO2 READ (Isolated so absent CO2 never causes MD02 Error)
                co2 = None
                co2_port = CO2_SENSOR_MAP.get(skey, "")
                if co2_port and "PLACEHOLDER" not in co2_port and os.path.exists(co2_port):
                    try:
                        co2_inst = minimalmodbus.Instrument(co2_port, SLAVE_ID)
                        co2_inst.serial.baudrate = BAUDRATE
                        co2_inst.serial.timeout = 0.5
                        try:
                            co2_vals = co2_inst.read_registers(0, 2, functioncode=4)
                        except Exception:
                            co2_vals = co2_inst.read_registers(1, 2, functioncode=4)
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
                with sensor_data_lock: sensor_data[port] = {'id': sensor_id, 'status': 'ERROR'}
            finally:
                if 'instrument' in locals() and hasattr(instrument, 'serial') and instrument.serial:
                    try: instrument.serial.close()
                    except: pass
        
        # 2. EVALUATE RTC CALENDAR & TIME SLOTS FOR RELAYS & WARNINGS
        current_warnings = []
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

                sp_eval = get_active_setpoints(skey)
                
                # Dedicated Photoperiod Lighting Relay Control for THIS Room
                p_on_24 = format_time_24h(sp_eval.get("photoperiod_on", "06:00 AM"))
                p_off_24 = format_time_24h(sp_eval.get("photoperiod_off", "08:00 PM"))
                l_enabled = sp_eval.get("lighting_enabled", True)
                
                room_light_state = False
                if l_enabled:
                    if p_on_24 <= p_off_24:
                        if p_on_24 <= now_str <= p_off_24: room_light_state = True
                    else:
                        if now_str >= p_on_24 or now_str <= p_off_24: room_light_state = True

                set_relay(ch_l, room_light_state)
                relay_states[ch_l] = room_light_state

                with sensor_data_lock:
                    data = sensor_data.get(port, {'status': 'OFFLINE'})

                if data['status'] == 'OK':
                    t, h = data['temp'], data['humi']
                    t_target = sp_eval['target_temp']
                    h_target = sp_eval['target_humi']
                    t_min, t_max = sp_eval['T MIN'], sp_eval['T MAX']
                    h_min, h_max = sp_eval['H MIN'], sp_eval['H MAX']

                    if t >= t_max:
                        set_relay(ch_f, True); relay_states[ch_f] = True
                    elif t <= t_min:
                        set_relay(ch_f, False); relay_states[ch_f] = False

                    if t >= (t_target + temp_alarm_offset):
                        msg = f"{get_sensor_display_name(skey)} High Temp ({t:.1f}°C > {t_target + temp_alarm_offset:.1f}°C)"
                        current_warnings.append(msg)
                        log_alarm_event(skey, msg, t, t_target)
                    elif t <= (t_target - temp_alarm_offset):
                        msg = f"{get_sensor_display_name(skey)} Low Temp ({t:.1f}°C < {t_target - temp_alarm_offset:.1f}°C)"
                        current_warnings.append(msg)
                        log_alarm_event(skey, msg, t, t_target)
                    
                    if h >= h_max:
                        set_relay(ch_h, True); relay_states[ch_h] = True
                    elif h <= h_min:
                        set_relay(ch_h, False); relay_states[ch_h] = False

                    if h >= (h_target + humi_alarm_offset):
                        msg = f"{get_sensor_display_name(skey)} High Humidity ({h:.1f}% > {h_target + humi_alarm_offset:.1f}%)"
                        current_warnings.append(msg)
                        log_alarm_event(skey, msg, h, h_target)
                    elif h <= (h_target - humi_alarm_offset):
                        msg = f"{get_sensor_display_name(skey)} Low Humidity ({h:.1f}% < {h_target - humi_alarm_offset:.1f}%)"
                        current_warnings.append(msg)
                        log_alarm_event(skey, msg, h, h_target)
                else:
                    set_relay(ch_f, False); set_relay(ch_h, False)
                    relay_states[ch_f] = False; relay_states[ch_h] = False

        if current_warnings:
            trigger_buzzer_30s()

        active_warnings = current_warnings
        
        # User Configurable Cloud Upload Frequency (0 = 1 sec per-second upload, 1m, 5m, 10m, 30m, 1h, etc.)
        freq_min = system_config.get('upload_frequency_min', 0)
        try:
            freq_val = float(freq_min)
        except Exception:
            freq_val = 0.0

        if freq_val <= 0:
            upload_freq_sec = 1.0  # Per-second real-time streaming
        else:
            upload_freq_sec = freq_val * 60.0

        curr_time = time.time()
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
    for f in [frame_main, frame_set, frame_schedule, frame_detail]:
        f.pack_forget()
    frame.pack(fill="both", expand=True)
    add_logo(frame)
    add_top_left_exit(frame)
    if frame != frame_main:
        add_bottom_right_clock(frame)

def get_sensor_display_name(skey):
    custom_names = system_config.get("sensor_names", {})
    if skey in custom_names and custom_names[skey].strip():
        return custom_names[skey].strip()
    if skey == "S7": return "GREEN HOUSE"
    return f"COLD ROOM {skey.replace('S', '')}"

def get_f_name(skey):
    if skey == "S7": return "Fanpad"
    return "AC"

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

btn_pause = tk.Button(footer_main, text="MANUAL STOP", font=BTN_FONT_MAIN, width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, bg="#c62828", fg="white", cursor="hand2", command=lambda: toggle_pause())
btn_pause.pack(side="left", padx=10, pady=10)

btn_sched_slots = tk.Button(footer_main, text="SCHEDULE SLOTS", font=BTN_FONT_MAIN, width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, bg="#0284c7", fg="white", cursor="hand2", command=lambda: open_schedule_editor("S1"))
btn_sched_slots.pack(side="left", padx=10, pady=10)

btn_sys_settings = tk.Button(footer_main, text="SYSTEM SETTINGS", font=BTN_FONT_MAIN, width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, bg="#0891b2", fg="white", cursor="hand2", command=lambda: open_system_settings_modal())
btn_sys_settings.pack(side="left", padx=10, pady=10)

btn_restart_app = tk.Button(footer_main, text="RESTART", font=BTN_FONT_MAIN, width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, bg="#1565c0", fg="white", cursor="hand2", command=lambda: restart_program())
btn_restart_app.pack(side="left", padx=10, pady=10)

lbl_clock = tk.Label(footer_main, text="Day, YYYY-MM-DD\n hh:mm:ss AM/PM (IST)", font=("Helvetica", 11, "bold"), fg="#00897b", bg="#eeeeee", justify="right")
lbl_clock.pack(side="right", padx=15, pady=5)

def update_clock_display():
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist_tz)
    now_str = now.strftime(" %A, %Y-%m-%d\n %I:%M:%S %p (IST)")
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

def toggle_pause():
    global system_paused
    system_paused = not system_paused
    if system_paused:
        btn_pause.config(text="RESTART/RUN", bg="#2e7d32")
    else:
        btn_pause.config(text="MANUAL STOP", bg="#c62828")

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

def save_local_telemetry(data):
    global last_local_save_time
    try: connected = is_mqtt_connected and control_client.is_connected()
    except: connected = False
    if connected: return

    current_time = time.time()
    if current_time - last_local_save_time < 1: return

    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ts_str = datetime.datetime.now(ist_tz).isoformat()

    def write_thread():
        with local_log_lock:
            try:
                os.makedirs(LOG_DIR, exist_ok=True)
                write_header = not os.path.exists(ACTIVE_LOG_FILE) or os.path.getsize(ACTIVE_LOG_FILE) == 0
                with open(ACTIVE_LOG_FILE, "a") as f:
                    if write_header: f.write(json.dumps(["timestamp", "payload"]) + "\n")
                    f.write(json.dumps([ts_str, data]) + "\n")
            except Exception as e: pass

    threading.Thread(target=write_thread, daemon=True).start()
    last_local_save_time = current_time

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
                
                setting_nm = sp_eval['setting_name']
                slot_id = sp_eval['slot_id']
                t_min, t_max = sp_eval['T MIN'], sp_eval['T MAX']
                h_min, h_max = sp_eval['H MIN'], sp_eval['H MAX']
                t_target = sp_eval['target_temp']
                h_target = sp_eval['target_humi']

                if d and d.get('status') == 'OK':
                    t, h = d['temp'], d['humi']
                    c_val = d.get('co2')
                    co2_str = f"{c_val:.1f} ppm" if (c_val is not None and c_val > 0) else "N/A"

                    box_text = (
                        f"{disp_name}\n"
                        f"[{setting_nm} - Slot {slot_id}]\n"
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
        if frame_detail.winfo_ismapped() and active_detail_port in snap:
            d = snap[active_detail_port]
            skey = next((k for k, v in SENSOR_MAP.items() if v == active_detail_port), "S1")
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

            prog_name = sp_eval.get('program_name', sp_eval.get('setting_name', 'Default Program'))
            stage_name = sp_eval.get('stage_name', f"Slot {sp_eval.get('slot_id', 1)}")

            txt_detail_data.config(state="normal")
            txt_detail_data.delete("1.0", "end")

            # 1. Room Name (Black)
            txt_detail_data.insert("end", f"{get_sensor_display_name(skey)}\n\n", "black")

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

            # 3. Program, Stage, Active Window (Black label, Blue value)
            txt_detail_data.insert("end", "Program: ", "black")
            txt_detail_data.insert("end", f"{prog_name}\n", "blue")
            
            txt_detail_data.insert("end", "Stage:   ", "black")
            txt_detail_data.insert("end", f"{stage_name}\n", "blue")
            
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

            # 6. Relays Status (Black label, Green ON / Red OFF)
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

txt_detail_data = tk.Text(frame_detail, font=font.Font(size=12, weight="bold"), bg="white", bd=0, highlightthickness=0, height=16, width=65)
txt_detail_data.pack(pady=5, expand=True, fill="both")
txt_detail_data.tag_configure("black", foreground="#000000", justify="center")
txt_detail_data.tag_configure("blue", foreground="#1565c0", justify="center")
txt_detail_data.tag_configure("green", foreground="#16a34a", justify="center")
txt_detail_data.tag_configure("red", foreground="#c62828", justify="center")

def open_sensor_detail(port):
    global active_detail_port; active_detail_port = port
    skey = next((k for k, v in SENSOR_MAP.items() if v == port), "S1")
    lbl_detail_title.config(text=get_sensor_display_name(skey))
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
            messagebox.showinfo("Renamed", f"Renamed {skey} to '{new_name.strip()}' successfully!")
            
    open_almora_keypad(f"Rename Room ({skey})", curr_name, on_confirm, is_alphanumeric=True)

btn_f_det = tk.Frame(frame_detail, bg="white")
btn_f_det.pack(side="bottom", pady=40)
tk.Button(btn_f_det, text="BACK TO DASHBOARD", font=BTN_FONT_MAIN, bg="#757575", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: show(frame_main)).pack(side="left", padx=10)
tk.Button(btn_f_det, text="EDIT ROOM NAME", font=BTN_FONT_MAIN, bg="#d97706", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=edit_active_room_name_detail).pack(side="left", padx=10)
tk.Button(btn_f_det, text="EDIT SCHEDULE SLOTS", font=BTN_FONT_MAIN, bg="#0284c7", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: open_schedule_editor(next((k for k, v in SENSOR_MAP.items() if v == active_detail_port), "S1"))).pack(side="left", padx=10)

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

# SYSTEM SETTINGS MODAL (CONFIG FREQUENCY & ALARM DEVIATION OFFSETS)
def open_system_settings_modal():
    sett_win = tk.Toplevel(root)
    make_modal_fullscreen(sett_win)

    s_main = tk.Frame(sett_win, bg="white")
    s_main.pack(fill="both", expand=True, pady=(60, 45))

    add_logo(sett_win)
    add_top_left_exit(sett_win)
    add_bottom_right_clock(sett_win)

    tk.Label(s_main, text="SYSTEM CONFIGURATION & ALARM SETTINGS", font=big, fg="#1565c0", bg="white").pack(pady=(15, 20))

    body = tk.Frame(s_main, bg="white")
    body.pack(pady=10)

    # 1. Cloud Upload Frequency
    r1 = tk.Frame(body, bg="white"); r1.pack(fill="x", pady=10)
    tk.Label(r1, text="Cloud Upload Frequency:", font=("Helvetica", 12, "bold"), fg="#1e293b", bg="white", width=25, anchor="e").pack(side="left", padx=10)
    
    freq_val = system_config.get("upload_frequency_min", 0)
    lbl_freq = tk.Label(r1, text=format_freq_display(freq_val), font=("Helvetica", 12, "bold"), bg="#f1f5f9", fg="#1565c0", width=14, relief="sunken", bd=1)
    lbl_freq.pack(side="left", padx=10)

    def cycle_freq():
        curr = system_config.get("upload_frequency_min", 0)
        options = [0, 1, 2, 5, 10, 15, 30, 60, 120, 360, 720, 1440, 4320, 10080]
        idx = options.index(curr) if curr in options else 0
        nxt = options[(idx + 1) % len(options)]
        system_config["upload_frequency_min"] = nxt
        save_config()
        lbl_freq.config(text=format_freq_display(nxt))

    def edit_freq_custom():
        curr = str(system_config.get("upload_frequency_min", 0))
        def on_confirm(val):
            try:
                m = max(0, min(10080, float(val)))
                system_config["upload_frequency_min"] = m
                save_config()
                lbl_freq.config(text=format_freq_display(m))
            except Exception: pass
        open_almora_keypad("Edit Upload Frequency (Min: 0 for 1-Sec, 1 to 10080)", curr, on_confirm, is_alphanumeric=False)

    tk.Button(r1, text="CHANGE", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=7, height=2, relief="flat", bd=0, cursor="hand2", command=cycle_freq).pack(side="left", padx=3)
    tk.Button(r1, text="EDIT", font=BTN_FONT_INLINE, bg="#0284c7", fg="white", width=6, height=2, relief="flat", bd=0, cursor="hand2", command=edit_freq_custom).pack(side="left", padx=3)

    # 2. Temp Alarm Offset (+/- C)
    r2 = tk.Frame(body, bg="white"); r2.pack(fill="x", pady=10)
    tk.Label(r2, text="Temp Alarm Limit (± °C) :", font=("Helvetica", 12, "bold"), fg="#1e293b", bg="white", width=27, anchor="e").pack(side="left", padx=10)
    
    t_off_val = system_config.get("temp_alarm_offset", 5.0)
    lbl_toff = tk.Label(r2, text=f"± {t_off_val:.1f} °C", font=("Helvetica", 12, "bold"), bg="#f1f5f9", fg="#1565c0", width=14, relief="sunken", bd=1)
    lbl_toff.pack(side="left", padx=10)

    def edit_toff():
        open_almora_keypad("Edit Temp Alarm Deviation Limit (± °C)", str(system_config.get("temp_alarm_offset", 5.0)),
                           lambda v: (system_config.update({"temp_alarm_offset": float(v)}), lbl_toff.config(text=f"± {float(v):.1f} °C")))

    tk.Button(r2, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_toff).pack(side="left", padx=5)

    # 3. Humi Alarm Offset (+/- %)
    r3 = tk.Frame(body, bg="white"); r3.pack(fill="x", pady=10)
    tk.Label(r3, text="Humi Alarm Limit (± %) :", font=("Helvetica", 12, "bold"), fg="#1e293b", bg="white", width=27, anchor="e").pack(side="left", padx=10)
    
    h_off_val = system_config.get("humi_alarm_offset", 5.0)
    lbl_hoff = tk.Label(r3, text=f"± {h_off_val:.1f} %", font=("Helvetica", 12, "bold"), bg="#f1f5f9", fg="#1565c0", width=14, relief="sunken", bd=1)
    lbl_hoff.pack(side="left", padx=10)

    def edit_hoff():
        open_almora_keypad("Edit Humi Alarm Deviation Limit (± %)", str(system_config.get("humi_alarm_offset", 5.0)),
                           lambda v: (system_config.update({"humi_alarm_offset": float(v)}), lbl_hoff.config(text=f"± {float(v):.1f} %")))

    tk.Button(r3, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_hoff).pack(side="left", padx=5)

    def save_sys_settings():
        save_config()
        sett_win.destroy()

    btn_f = tk.Frame(s_main, bg="white"); btn_f.pack(pady=30)
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
            messagebox.showinfo("Renamed", f"Renamed {skey} to '{new_name.strip()}' successfully!")

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
    skey = skey_combo.get()
    sp = get_setpoints(skey)
    settings = sp.get("settings", {})
    
    for idx, s_key in enumerate(ALL_SETTINGS):
        st = settings.setdefault(s_key, {})
        if idx < count:
            st["enabled"] = True
        else:
            st["enabled"] = False
            
    save_setpoints()
    stages_count_dropdown_btn.config(text=f"{count} Stages ▼")
    stages_count_menu_frame.place_forget()
    stages_count_dropdown_open = False
    load_schedule_form()
    messagebox.showinfo("Stages Updated", f"Set number of active crop stages for {get_sensor_display_name(skey)} to {count}!")

stages_count_dropdown_btn = tk.Button(sched_row1, text="5 Stages ▼", font=("Helvetica", 11, "bold"), bg="#cbd5e1", fg="#1e293b",
                                      activebackground="#94a3b8", activeforeground="#1e293b", relief="flat", bd=0, padx=12, pady=6, cursor="hand2", command=toggle_stages_count_dropdown)
stages_count_dropdown_btn.pack(side="left", padx=(0, 4))

# --- 4. PROGRAM LIBRARY DROPDOWN (MIND.PY STYLE - LINE 2 CENTERED) ---
tk.Label(sched_row2, text="Program:", font=("Helvetica", 12, "bold"), fg="#475569", bg="white").pack(side="left", padx=(5, 4))

def update_preset_dropdown_text():
    skey = skey_combo.get()
    room_presets = get_room_crop_programs(skey)
    count = len(room_presets)
    preset_dropdown_btn.config(text=f" Programs ({count}/20 Saved)▼")

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
        room_presets = get_room_crop_programs(skey)
        for w in preset_menu_frame.winfo_children(): w.destroy()
        p_items = list(room_presets.items())
        if not p_items:
            tk.Label(preset_menu_frame, text=f"No Saved Programs for {get_sensor_display_name(skey)}", font=("Helvetica", 11, "bold"), fg="#64748b", bg="white", padx=12, pady=10).pack()
        else:
            for idx, (p_name, p_data) in enumerate(p_items):
                item_f = tk.Frame(preset_menu_frame, bg="white")
                item_f.pack(fill="x")

                def _apply(name=p_name):
                    global preset_dropdown_open
                    curr_skey = skey_combo.get()
                    r_presets = get_room_crop_programs(curr_skey)
                    if name in r_presets:
                        sensor_setpoints[curr_skey]["settings"] = copy.deepcopy(r_presets[name])
                        save_setpoints()
                        preset_menu_frame.place_forget()
                        preset_dropdown_open = False
                        preset_dropdown_btn.config(text=f"{name} ▼")
                        load_schedule_form()
                        messagebox.showinfo("Program Loaded", f"Applied program '{name}' to {get_sensor_display_name(curr_skey)}!")

                def _delete(name=p_name):
                    curr_skey = skey_combo.get()
                    r_presets = get_room_crop_programs(curr_skey)
                    if name in r_presets:
                        del r_presets[name]
                        save_crop_programs()
                        toggle_preset_dropdown()
                        update_preset_dropdown_text()

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
    room_presets = get_room_crop_programs(skey)
    if len(room_presets) >= 20:
        open_almora_keypad("Limit Reached! Maximum 20 programs allowed.", "Delete a program first", lambda v: None, is_alphanumeric=True)
        return
    default_name = f"Program {len(room_presets)+1}"
    def on_confirm_name(name):
        if name:
            curr_skey = skey_combo.get()
            r_presets = get_room_crop_programs(curr_skey)
            sp = get_setpoints(curr_skey)
            r_presets[name] = copy.deepcopy(sp.get("settings", {}))
            save_crop_programs()
            update_preset_dropdown_text()
            preset_dropdown_btn.config(text=f"{name} ▼")
            messagebox.showinfo("Saved", f"Saved schedule as program '{name}' for {get_sensor_display_name(curr_skey)}")

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
        
        try:
            c_start = datetime.datetime.strptime(curr_st.get("start_date", "").strip(), "%Y-%m-%d").date()
            c_end = datetime.datetime.strptime(curr_st.get("end_date", "").strip(), "%Y-%m-%d").date()
            if c_end < c_start:
                c_end = c_start
                curr_st["end_date"] = c_end.strftime("%Y-%m-%d")
        except Exception:
            return

        for i in range(idx, len(stages) - 1):
            curr_k = stages[i]
            next_k = stages[i+1]
            
            c_info = settings[curr_k]
            n_info = settings[next_k]
            
            try:
                c_e_date = datetime.datetime.strptime(c_info.get("end_date", "").strip(), "%Y-%m-%d").date()
                n_s_orig = datetime.datetime.strptime(n_info.get("start_date", "").strip(), "%Y-%m-%d").date()
                n_e_orig = datetime.datetime.strptime(n_info.get("end_date", "").strip(), "%Y-%m-%d").date()
                
                duration = max(datetime.timedelta(days=1), n_e_orig - n_s_orig + datetime.timedelta(days=1))
                
                new_n_s = c_e_date + datetime.timedelta(days=1)
                new_n_e = new_n_s + duration - datetime.timedelta(days=1)
                
                n_info["start_date"] = new_n_s.strftime("%Y-%m-%d")
                n_info["end_date"] = new_n_e.strftime("%Y-%m-%d")
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
    open_almora_keypad("Edit Crop Stage Name", lbl_val_stagename.cget("text"), lambda v: (lbl_val_stagename.config(text=v), save_current_schedule_to_file()), is_alphanumeric=True)

tk.Button(date_frame, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_stagename).grid(row=0, column=2, padx=3, pady=2)

tk.Label(date_frame, text="Start Date:", font=("Helvetica", 11, "bold"), fg="#64748b", bg="white").grid(row=0, column=3, padx=(10, 3), pady=2)
lbl_val_sdate = tk.Label(date_frame, text="2026-07-01", font=("Helvetica", 11, "bold"), bg="#ffffff", fg="#1e293b", width=11, relief="sunken", bd=1)
lbl_val_sdate.grid(row=0, column=4, padx=3, pady=2)

def on_sdate_changed(val):
    lbl_val_sdate.config(text=val.strip())
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
    st["start_date"] = val.strip()
    auto_chain_crop_stage_dates(skey, setting_nm)
    save_current_schedule_to_file(show_feedback=False)
    load_schedule_form()

def edit_sdate():
    open_almora_keypad("Edit Start Date (YYYY-MM-DD)", lbl_val_sdate.cget("text"), on_sdate_changed)

tk.Button(date_frame, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_sdate).grid(row=0, column=5, padx=3, pady=2)

tk.Label(date_frame, text="End Date:", font=("Helvetica", 11, "bold"), fg="#64748b", bg="white").grid(row=0, column=6, padx=(10, 3), pady=2)
lbl_val_edate = tk.Label(date_frame, text="2026-08-31", font=("Helvetica", 11, "bold"), bg="#ffffff", fg="#1e293b", width=11, relief="sunken", bd=1)
lbl_val_edate.grid(row=0, column=7, padx=3, pady=2)

def on_edate_changed(val):
    lbl_val_edate.config(text=val.strip())
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
    st["end_date"] = val.strip()
    auto_chain_crop_stage_dates(skey, setting_nm)
    save_current_schedule_to_file(show_feedback=False)
    load_schedule_form()

def edit_edate():
    open_almora_keypad("Edit End Date (YYYY-MM-DD)", lbl_val_edate.cget("text"), on_edate_changed)

tk.Button(date_frame, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_edate).grid(row=0, column=8, padx=3, pady=2)

def toggle_current_stage_activation():
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
    curr_enabled = st.get("enabled", True)
    st["enabled"] = not curr_enabled
    save_setpoints()
    load_schedule_form()

btn_toggle_stage = tk.Button(date_frame, text="STAGE ON 🟢", font=("Helvetica", 10, "bold"), bg="#16a34a", fg="white",
                             activebackground="#15803d", activeforeground="white", relief="flat", bd=0, padx=8, pady=3, cursor="hand2", command=toggle_current_stage_activation)
btn_toggle_stage.grid(row=0, column=9, padx=(12, 3), pady=2)

# PHOTOPERIOD LIGHTING CONTROL ROW
light_frame = tk.Frame(sched_scroll_inner, bg="#f8fafc", bd=1, relief="solid")
light_frame.pack(pady=6, anchor="center", padx=10)

tk.Label(light_frame, text=" PHOTOPERIOD LIGHTING CYCLE:", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="#f8fafc").grid(row=0, column=0, padx=8, pady=4)

tk.Label(light_frame, text="Light ON:", font=("Helvetica", 11, "bold"), fg="#334155", bg="#f8fafc").grid(row=0, column=1, padx=4, pady=4)
lbl_val_pon = tk.Label(light_frame, text="06:00 AM", font=("Helvetica", 11, "bold"), bg="#ffffff", fg="#1e293b", width=10, relief="sunken", bd=1)
lbl_val_pon.grid(row=0, column=2, padx=4, pady=4)

def edit_pon():
    open_almora_keypad("Edit Photoperiod Light ON Time (e.g. 06:00 AM)", lbl_val_pon.cget("text"), lambda v: (lbl_val_pon.config(text=format_time_12h(v)), save_current_schedule_to_file()))

tk.Button(light_frame, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_pon).grid(row=0, column=3, padx=4, pady=4)

tk.Label(light_frame, text="Light OFF:", font=("Helvetica", 11, "bold"), fg="#334155", bg="#f8fafc").grid(row=0, column=4, padx=(12, 4), pady=4)
lbl_val_poff = tk.Label(light_frame, text="08:00 PM", font=("Helvetica", 11, "bold"), bg="#ffffff", fg="#1e293b", width=10, relief="sunken", bd=1)
lbl_val_poff.grid(row=0, column=5, padx=4, pady=4)

def edit_poff():
    open_almora_keypad("Edit Photoperiod Light OFF Time (e.g. 08:00 PM)", lbl_val_poff.cget("text"), lambda v: (lbl_val_poff.config(text=format_time_12h(v)), save_current_schedule_to_file()))

tk.Button(light_frame, text="EDIT", font=BTN_FONT_INLINE, bg="#cbd5e1", fg="#1e293b", width=8, height=2, relief="flat", bd=0, cursor="hand2", command=edit_poff).grid(row=0, column=6, padx=4, pady=4)

def save_current_schedule_to_file(show_feedback=True):
    try:
        skey = skey_combo.get()
        setting_nm = setting_combo.get()
        sp = get_setpoints(skey)
        st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
        st["name"] = lbl_val_stagename.cget("text").strip()
        st["start_date"] = lbl_val_sdate.cget("text").strip()
        st["end_date"] = lbl_val_edate.cget("text").strip()
        st["photoperiod_on"] = lbl_val_pon.cget("text").strip()
        st["photoperiod_off"] = lbl_val_poff.cget("text").strip()
        st["enabled"] = st.get("enabled", True)

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
        save_setpoints()
        print(f"Schedule for {skey} - {setting_nm} saved successfully!")
        
        if show_feedback and 'btn_save_sched' in globals() and btn_save_sched.winfo_exists():
            orig_txt = btn_save_sched.cget("text")
            orig_bg = btn_save_sched.cget("bg")
            btn_save_sched.config(text="SAVED ", bg="#15803d")
            def _reset_btn():
                try:
                    if btn_save_sched.winfo_exists():
                        btn_save_sched.config(text=orig_txt, bg=orig_bg)
                except Exception: pass
            root.after(1500, _reset_btn)
    except Exception as e:
        print(f"Schedule Save Error: {e}")

def add_new_time_slot():
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
    save_setpoints()
    load_schedule_form()

def delete_time_slot(slot_idx):
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.get("settings", {}).get(setting_nm, {})
    slots = st.get("time_slots", [])
    if len(slots) <= 1:
        messagebox.showwarning("Warning", "At least one time slot is required!")
        return
    if 0 <= slot_idx < len(slots):
        slots.pop(slot_idx)
        for i, sl in enumerate(slots):
            sl["id"] = i + 1
            sl["name"] = f"Slot {i+1}"
        save_setpoints()
        load_schedule_form()

def delete_all_time_slots():
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    sp = get_setpoints(skey)
    st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
    slots = st.get("time_slots", [])
    if not slots:
        messagebox.showinfo("Info", "No time slots to delete!")
        return
    if messagebox.askyesno("Delete All Slots", f"Are you sure you want to clear all {len(slots)} time slots for {setting_nm}?"):
        st["time_slots"] = []
        save_setpoints()
        load_schedule_form()
        messagebox.showinfo("Cleared", "All time slots have been deleted!")

# Populate permanently packed bottom action buttons
btn_save_sched = tk.Button(sched_btn_frame, text="SAVE SCHEDULE", font=BTN_FONT_MAIN, bg="#2e7d32", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: save_current_schedule_to_file(True))
btn_save_sched.pack(side="left", padx=10)

tk.Button(sched_btn_frame, text="ADD TIME SLOT", font=BTN_FONT_MAIN, bg="#ea580c", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=add_new_time_slot).pack(side="left", padx=10)

btn_toggle_stage_bottom = tk.Button(sched_btn_frame, text="DISABLE STAGE", font=BTN_FONT_MAIN, bg="#dc2626", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=toggle_current_stage_activation)
btn_toggle_stage_bottom.pack(side="left", padx=10)

tk.Button(sched_btn_frame, text="CANCEL / BACK", font=BTN_FONT_MAIN, bg="#64748b", fg="white", width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: show(frame_main)).pack(side="left", padx=10)

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
    tk.Label(header, text=f"EDIT SCHEDULE FRAME {idx+1}", font=big, fg="#1565c0", bg="white").pack()

    body = tk.Frame(pop_main, bg="white")
    body.pack(pady=6, anchor="center")

    col1_f = tk.Frame(body, bg="white")
    col1_f.pack(side="left", padx=10, anchor="n")

    col2_f = tk.Frame(body, bg="white")
    col2_f.pack(side="left", padx=10, anchor="n")

    items = [
        ("Frame Name", l_fname, True),
        ("Start Time ", l_tstart, False),
        ("Stop Time ", l_tstop, False),
        ("T SETPOINT ", l_tset_val, False),
        ("T MAX ", l_tmax_val, False),
        ("T MIN ", l_tmin_val, False),
        ("H SETPOINT ", l_hset_val, False),
        ("H MAX ", l_hmax_val, False),
        ("H MIN ", l_hmin_val, False),
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
        save_current_schedule_to_file()
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
    lbl_val_sdate.config(text=st.get("start_date", "2026-07-01"))
    lbl_val_edate.config(text=st.get("end_date", "2026-08-31"))
    lbl_val_pon.config(text=format_time_12h(st.get("photoperiod_on", "06:00 AM")))
    lbl_val_poff.config(text=format_time_12h(st.get("photoperiod_off", "08:00 PM")))

    st_dict = sp.get("settings", {})
    active_count = sum(1 for sk in ALL_SETTINGS if st_dict.get(sk, {}).get("enabled", True))
    stages_count_dropdown_btn.config(text=f"{active_count} Stages ▼")

    stage_enabled = st.get("enabled", True)
    if stage_enabled:
        btn_toggle_stage.config(text="STAGE ON 🟢", bg="#16a34a")
        btn_toggle_stage_bottom.config(text="DISABLE STAGE", bg="#dc2626")
    else:
        btn_toggle_stage.config(text="STAGE OFF 🔴", bg="#dc2626")
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

    temp_grid_frame.config(text="SCHEDULE TIME SLOTS (TEMP & HUMIDITY SETPOINTS)")
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

        tk.Label(left_f, text=frame_name_v.upper(), font=card_title_font, fg="#1565c0", bg="#f8fafc", anchor="w").pack(anchor="w")
        tk.Label(left_f, text=f"{start_v} - {stop_v}", font=card_time_font, fg="#334155", bg="#f8fafc", anchor="w").pack(anchor="w", pady=(2, 0))

        # RIGHT SIDE: Large Action Buttons (EDIT FRAME & DELETE)
        right_f = tk.Frame(row, bg="#f8fafc")
        right_f.pack(side="right", padx=(15, 0))

        tk.Button(right_f, text="EDIT FRAME", font=btn_font_large, bg="#cbd5e1", fg="#1e293b", width=13, height=2, relief="flat", bd=0, cursor="hand2", command=lambda i=idx: edit_slot_popup(i)).pack(side="left", padx=4)
        tk.Button(right_f, text="DELETE", font=btn_font_large, bg="#dc2626", fg="white", width=9, height=2, relief="flat", bd=0, cursor="hand2", command=lambda i=idx: delete_time_slot(i)).pack(side="left", padx=4)

        # MIDDLE SIDE: Stacked Temperature & Humidity Setpoints (TEMP, HUMI, MIN, MAX in Black)
        mid_f = tk.Frame(row, bg="#f8fafc")
        mid_f.pack(side="left", fill="both", expand=True, padx=10)

        # Temp Line (Names in Black, Values in Blue)
        t_row = tk.Frame(mid_f, bg="#f8fafc")
        t_row.pack(fill="x", anchor="w", pady=(0, 2))

        tk.Label(t_row, text="TEMP: ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(t_row, text=f"{t_set_v:.1f}°C", font=card_val_font, fg="#1565c0", bg="#f8fafc").pack(side="left")
        tk.Label(t_row, text="   |   MIN: ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(t_row, text=f"{t_min_v:.1f}°C", font=card_val_font, fg="#1565c0", bg="#f8fafc").pack(side="left")
        tk.Label(t_row, text="   |   MAX: ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(t_row, text=f"{t_max_v:.1f}°C", font=card_val_font, fg="#1565c0", bg="#f8fafc").pack(side="left")

        # Humi Line (Names in Black, Values in Sky Blue)
        h_row = tk.Frame(mid_f, bg="#f8fafc")
        h_row.pack(fill="x", anchor="w", pady=(2, 0))

        tk.Label(h_row, text="HUMI: ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(h_row, text=f"{h_set_v:.1f}%", font=card_val_font, fg="#0284c7", bg="#f8fafc").pack(side="left")
        tk.Label(h_row, text="   |   MIN: ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(h_row, text=f"{h_min_v:.1f}%", font=card_val_font, fg="#0284c7", bg="#f8fafc").pack(side="left")
        tk.Label(h_row, text="   |   MAX: ", font=card_val_font, fg="black", bg="#f8fafc").pack(side="left")
        tk.Label(h_row, text=f"{h_max_v:.1f}%", font=card_val_font, fg="#0284c7", bg="#f8fafc").pack(side="left")

def open_schedule_editor(skey="S1"):
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
    except Exception as e: print(f"Set Error: {e}")

tk.Button(frame_set, text="SAVE & RETURN", font=BTN_FONT_MAIN, bg="#1565c0", fg="white", 
          width=FRAME_BTN_WIDTH, height=FRAME_BTN_HEIGHT, cursor="hand2", command=lambda: (save_setpoints(), show(frame_detail))).pack(side="bottom", pady=20)

# --- APP SHUTDOWN CLEANUP ---
def quit_app():
    global running
    running = False
    print("Cleaning up relays...")
    relay_port = system_config.get('relay_port')
    if relay_port:
        for ch in range(1, 17):
            set_relay(ch, False)
    root.destroy()

root.protocol("WM_DELETE_WINDOW", quit_app)

if __name__ == "__main__":
    print(f" STARTING ALMORA COLD ROOM MONITOR & CONTROLLER: {DEVICE_NAME} ")
    load_config()
    load_crop_programs()
    load_setpoints()
    threading.Thread(target=auto_trust_devices, daemon=True).start()
    threading.Thread(target=start_bluetooth_server, daemon=True).start()
    threading.Thread(target=sensor_reader, daemon=True).start()
    show(frame_main)
    update_clock_display()
    update_ui()
    root.mainloop()
