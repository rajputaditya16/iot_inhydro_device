import time
import minimalmodbus
import glob
import threading
import json
import os
import datetime
import tkinter as tk
from tkinter import font, ttk
import sys
import socket
import subprocess
import paho.mqtt.client as mqtt
from PIL import Image, ImageTk

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

# MODBUS SETTINGS
SLAVE_ID = 1
BAUDRATE = 9600
RELAY_BAUD = 9600
DELAY_BETWEEN_PORTS = 0.2

# Hardware Dictionary: Maps Web MQTT IDs directly to physical USB paths
SENSOR_MAP = {
    "S1": "/dev/serial/by-path/usb-0:1:1:3:1:0-port0",
    "S2": "/dev/serial/by-path/usb_PLACEHOLDER_S2",
    "S3": "/dev/serial/by-path/usb_PLACEHOLDER_S3",
    "S4": "/dev/serial/by-path/usb_PLACEHOLDER_S4",
    "S5": "/dev/serial/by-path/usb_PLACEHOLDER_S5",
    "S6": "/dev/serial/by-path/usb_PLACEHOLDER_S6",
    "S7": "/dev/serial/by-path/usb_PLACEHOLDER_S7"
}
RELAY_PORT_FIXED = "/dev/serial/by-path/usb-0:1:2:1:0-port0"
BUZZER_CHANNEL = 15  # Dedicated relay channel for 30s hardware buzzer

POSSIBLE_RELAY_IDS = [255, 1, 2, 0, 3]  
working_relay_id = None

# SYSTEM STATE
system_config = {'relay_port': RELAY_PORT_FIXED}
sensor_data = {}
sensor_setpoints = {}
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

def generate_default_almora_schedule():
    return {
        "mode": "SCHEDULED", # "STATIC" or "SCHEDULED"
        "active_setting": "Setting A",
        "T MIN": 10.0,
        "T MAX": 30.0,
        "H MIN": 30.0,
        "H MAX": 80.0,
        "settings": {
            "Setting A": {
                "start_date": "2026-07-01",
                "end_date": "2026-08-31",
                "enabled": True,
                "time_slots": [
                    {"id": 1, "start": "06:00", "stop": "09:00", "t_max": 24.5, "t_min": 20.5, "h_max": 70.0, "h_min": 60.0, "enabled": True},
                    {"id": 2, "start": "09:00", "stop": "13:00", "t_max": 26.0, "t_min": 22.0, "h_max": 65.0, "h_min": 55.0, "enabled": True},
                    {"id": 3, "start": "13:00", "stop": "17:00", "t_max": 27.5, "t_min": 23.5, "h_max": 60.0, "h_min": 50.0, "enabled": True},
                    {"id": 4, "start": "17:00", "stop": "21:00", "t_max": 25.0, "t_min": 21.0, "h_max": 70.0, "h_min": 60.0, "enabled": True},
                    {"id": 5, "start": "21:00", "stop": "06:00", "t_max": 22.0, "t_min": 18.0, "h_max": 75.0, "h_min": 65.0, "enabled": True}
                ]
            },
            "Setting B": {
                "start_date": "2026-09-01",
                "end_date": "2026-10-31",
                "enabled": True,
                "time_slots": [
                    {"id": 1, "start": "06:00", "stop": "09:00", "t_max": 23.0, "t_min": 19.0, "h_max": 70.0, "h_min": 60.0, "enabled": True},
                    {"id": 2, "start": "09:00", "stop": "13:00", "t_max": 25.0, "t_min": 21.0, "h_max": 65.0, "h_min": 55.0, "enabled": True},
                    {"id": 3, "start": "13:00", "stop": "17:00", "t_max": 26.5, "t_min": 22.5, "h_max": 60.0, "h_min": 50.0, "enabled": True},
                    {"id": 4, "start": "17:00", "stop": "21:00", "t_max": 24.0, "t_min": 20.0, "h_max": 70.0, "h_min": 60.0, "enabled": True},
                    {"id": 5, "start": "21:00", "stop": "06:00", "t_max": 21.0, "t_min": 17.0, "h_max": 75.0, "h_min": 65.0, "enabled": True}
                ]
            },
            "Setting C": {
                "start_date": "2026-11-01",
                "end_date": "2026-12-31",
                "enabled": True,
                "time_slots": [
                    {"id": 1, "start": "06:00", "stop": "09:00", "t_max": 20.0, "t_min": 16.0, "h_max": 65.0, "h_min": 55.0, "enabled": True},
                    {"id": 2, "start": "09:00", "stop": "13:00", "t_max": 22.0, "t_min": 18.0, "h_max": 60.0, "h_min": 50.0, "enabled": True},
                    {"id": 3, "start": "13:00", "stop": "17:00", "t_max": 23.0, "t_min": 19.0, "h_max": 60.0, "h_min": 50.0, "enabled": True},
                    {"id": 4, "start": "17:00", "stop": "21:00", "t_max": 21.0, "t_min": 17.0, "h_max": 65.0, "h_min": 55.0, "enabled": True},
                    {"id": 5, "start": "21:00", "stop": "06:00", "t_max": 19.0, "t_min": 15.0, "h_max": 70.0, "h_min": 60.0, "enabled": True}
                ]
            },
            "Setting D": {
                "start_date": "2027-01-01",
                "end_date": "2027-03-31",
                "enabled": True,
                "time_slots": [
                    {"id": 1, "start": "06:00", "stop": "09:00", "t_max": 21.0, "t_min": 17.0, "h_max": 65.0, "h_min": 55.0, "enabled": True},
                    {"id": 2, "start": "09:00", "stop": "13:00", "t_max": 23.0, "t_min": 19.0, "h_max": 60.0, "h_min": 50.0, "enabled": True},
                    {"id": 3, "start": "13:00", "stop": "17:00", "t_max": 24.0, "t_min": 20.0, "h_max": 60.0, "h_min": 50.0, "enabled": True},
                    {"id": 4, "start": "17:00", "stop": "21:00", "t_max": 22.0, "t_min": 18.0, "h_max": 65.0, "h_min": 55.0, "enabled": True},
                    {"id": 5, "start": "21:00", "stop": "06:00", "t_max": 20.0, "t_min": 16.0, "h_max": 70.0, "h_min": 60.0, "enabled": True}
                ]
            },
            "Setting E": {
                "start_date": "2027-04-01",
                "end_date": "2027-06-30",
                "enabled": True,
                "time_slots": [
                    {"id": 1, "start": "06:00", "stop": "09:00", "t_max": 24.0, "t_min": 20.0, "h_max": 70.0, "h_min": 60.0, "enabled": True},
                    {"id": 2, "start": "09:00", "stop": "13:00", "t_max": 26.5, "t_min": 22.5, "h_max": 65.0, "h_min": 55.0, "enabled": True},
                    {"id": 3, "start": "13:00", "stop": "17:00", "t_max": 28.0, "t_min": 24.0, "h_max": 60.0, "h_min": 50.0, "enabled": True},
                    {"id": 4, "start": "17:00", "stop": "21:00", "t_max": 25.5, "t_min": 21.5, "h_max": 70.0, "h_min": 60.0, "enabled": True},
                    {"id": 5, "start": "21:00", "stop": "06:00", "t_max": 22.5, "t_min": 18.5, "h_max": 75.0, "h_min": 65.0, "enabled": True}
                ]
            }
        }
    }


def load_config():
    global system_config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                system_config = json.load(f)
        except Exception: pass

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
    
    # Ensure all S1 to S7 keys have Almora structure
    for skey in SENSOR_MAP.keys():
        if skey not in sensor_setpoints:
            sensor_setpoints[skey] = generate_default_almora_schedule()
        else:
            if "settings" not in sensor_setpoints[skey]:
                defaults = generate_default_almora_schedule()
                defaults.update(sensor_setpoints[skey])
                sensor_setpoints[skey] = defaults

def save_setpoints():
    try:
        with open(SETPOINTS_FILE, 'w') as f:
            json.dump(sensor_setpoints, f, indent=4)
        broadcast_current_state()
    except Exception as e:
        print(f"Error saving setpoints: {e}")

def broadcast_current_state():
    """Broadcasts current setpoints to cloud broker."""
    if 'control_client' in globals() and control_client and control_client.is_connected():
        payload = {
            "system_config": system_config,
            "sensor_setpoints": sensor_setpoints
        }
        try:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(payload), retain=True)
            print(f"[SYNC→WEB] Sent setpoints update to {CURRENT_SETP_TOPIC[-20:]}")
        except Exception as e: print(f"Broadcast err: {e}")

def get_setpoints(skey):
    """skey must be 'S1','S2',...,'S7'."""
    if skey not in sensor_setpoints:
        sensor_setpoints[skey] = generate_default_almora_schedule()
    return sensor_setpoints[skey]

def get_active_setpoints(skey):
    """
    Evaluates current RTC Date and Time against 5 Calendar Settings (Settings A-E)
    and 5 Time Frames per Setting. Returns active bounds & details.
    """
    sp_data = get_setpoints(skey)
    mode = sp_data.get("mode", "SCHEDULED")
    
    t_min = float(sp_data.get("T MIN", 10.0))
    t_max = float(sp_data.get("T MAX", 30.0))
    h_min = float(sp_data.get("H MIN", 30.0))
    h_max = float(sp_data.get("H MAX", 80.0))
    
    active_info = {
        "skey": skey,
        "setting_name": "STATIC",
        "slot_id": 0,
        "target_temp": round((t_min + t_max) / 2.0, 1),
        "target_humi": round((h_min + h_max) / 2.0, 1),
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
    setting_keys = ["Setting A", "Setting B", "Setting C", "Setting D", "Setting E"]

    for set_key in setting_keys:
        setting = settings.get(set_key)
        if not setting or not setting.get("enabled", True):
            continue

        s_date = setting.get("start_date", "")
        e_date = setting.get("end_date", "")

        if s_date and e_date:
            if not (s_date <= today_str <= e_date):
                continue

        time_slots = setting.get("time_slots", [])
        for slot in time_slots:
            if not slot.get("enabled", True):
                continue

            start_t = slot.get("start", "00:00")
            stop_t = slot.get("stop", "23:59")

            is_in_slot = False
            if start_t <= stop_t:
                is_in_slot = (start_t <= current_time_str <= stop_t)
            else:
                is_in_slot = (current_time_str >= start_t or current_time_str <= stop_t)

            if is_in_slot:
                t_max_v = float(slot.get("t_max", slot.get("temp_setpoint", 24.0) + slot.get("temp_tol", 2.0)))
                t_min_v = float(slot.get("t_min", slot.get("temp_setpoint", 24.0) - slot.get("temp_tol", 2.0)))
                h_max_v = float(slot.get("h_max", slot.get("humi_setpoint", 60.0) + slot.get("humi_tol", 5.0)))
                h_min_v = float(slot.get("h_min", slot.get("humi_setpoint", 60.0) - slot.get("humi_tol", 5.0)))

                active_info.update({
                    "setting_name": set_key,
                    "slot_id": slot.get("id", 1),
                    "target_temp": round((t_max_v + t_min_v) / 2, 1),
                    "target_humi": round((h_max_v + h_min_v) / 2, 1),
                    "T MIN": round(t_min_v, 1),
                    "T MAX": round(t_max_v, 1),
                    "H MIN": round(h_min_v, 1),
                    "H MAX": round(h_max_v, 1)
                })
                return active_info

    return active_info

def trigger_buzzer_30s():
    """Triggers physical hardware buzzer for 30 seconds in non-blocking thread."""
    global buzzer_active
    with buzzer_lock:
        if buzzer_active: return
        buzzer_active = True

    def _buzzer_worker():
        global buzzer_active
        print("🔔 [BUZZER] 30-second warning alarm triggered!")
        set_relay(BUZZER_CHANNEL, True)
        time.sleep(30)
        set_relay(BUZZER_CHANNEL, False)
        with buzzer_lock:
            buzzer_active = False
        print("🔕 [BUZZER] 30-second alarm ended.")

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
        srv.bind((socket.BDADDR_ANY, 1)); srv.listen(1)
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
    except Exception as e: print("BT Error:", e)

mqtt_ts_client = None
TS_MQTT_TOPIC = ""

def _make_ts_client(client_id, username, password, channel_id, port):
    if not (client_id and username and password and channel_id):
        return None, ""
    topic = f"channels/{channel_id}/publish"
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
    except AttributeError:
        c = mqtt.Client(client_id)
    c.username_pw_set(username, password)
    try:
        c.connect("mqtt3.thingspeak.com", int(port), 60)
        c.loop_start()
    except Exception as e:
        print(f"[MQTT] connect error: {e}")
        return None, ""
    return c, topic

def init_mqtt_client():
    global mqtt_ts_client, TS_MQTT_TOPIC
    if mqtt_ts_client:
        try: mqtt_ts_client.disconnect(); mqtt_ts_client.loop_stop()
        except: pass

    port = system_config.get("PORT", 1883)
    mqtt_ts_client, TS_MQTT_TOPIC = _make_ts_client(
        client_id = str(system_config.get("TS CLIENT ID", "")),
        username  = str(system_config.get("TS USERNAME", "")),
        password  = str(system_config.get("TS PASSWORD", "")),
        channel_id= str(system_config.get("TS CHANNEL ID", "")),
        port      = port
    )

CONTROL_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/update"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"

import uuid as _uuid
_safe_client_id = f"Almora_{DEVICE_NAME}_{_uuid.uuid4().hex[:8]}"
try:
    control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, _safe_client_id)
except AttributeError:
    control_client = mqtt.Client(_safe_client_id)

import re as _re

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

def on_control_connect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(CONTROL_SYNC_TOPIC)
    else: is_mqtt_connected = False

def on_control_disconnect(client, userdata, rc, properties=None):
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
    global running, system_paused, active_warnings
    while running:
        if system_paused:
            time.sleep(1.0); continue
            
        system_config['relay_port'] = RELAY_PORT_FIXED
        
        # 1. READ ALL SENSORS
        for skey, port in SENSOR_MAP.items():
            if not running or system_paused: break
            sensor_id = int(skey.replace('S', ''))
            
            if not os.path.exists(port):
                with sensor_data_lock: sensor_data[port] = {'id': sensor_id, 'status': 'OFFLINE'}
                continue

            time.sleep(DELAY_BETWEEN_PORTS)
            try:
                instrument = minimalmodbus.Instrument(port, SLAVE_ID)
                instrument.serial.baudrate = BAUDRATE
                instrument.serial.timeout = 1.0
                try: values = instrument.read_registers(1, 2, functioncode=4)
                except: values = instrument.read_registers(0, 2, functioncode=4)

                temp, humi = values[0]/10.0, values[1]/10.0
                if temp > 150: temp /= 10.0
                if humi > 150: humi /= 10.0

                if skey == "S2": humi += 6.5
                if skey == "S3": humi -= 6.0
                if skey == "S4": humi += 2.8

                with sensor_data_lock:
                    sensor_data[port] = {'id': sensor_id, 'temp': temp, 'humi': humi, 'status': 'OK'}
            except Exception:
                with sensor_data_lock: sensor_data[port] = {'id': sensor_id, 'status': 'ERROR'}
            finally:
                if 'instrument' in locals() and hasattr(instrument, 'serial') and instrument.serial:
                    try: instrument.serial.close()
                    except: pass
        
        # 2. EVALUATE RTC CALENDAR & TIME SLOTS FOR RELAYS & WARNINGS
        current_warnings = []
        if os.path.exists(RELAY_PORT_FIXED):
            for skey, port in SENSOR_MAP.items():
                idx = int(skey.replace('S', '')) - 1
                ch_f = (idx * 2) + 1        # S1→ch1, S2→ch3...
                ch_h = (idx * 2) + 2        # S1→ch2, S2→ch4...

                sp_eval = get_active_setpoints(skey)
                
                with sensor_data_lock:
                    data = sensor_data.get(port, {'status': 'OFFLINE'})

                if data['status'] == 'OK':
                    t, h = data['temp'], data['humi']
                    t_min, t_max = sp_eval['T MIN'], sp_eval['T MAX']
                    h_min, h_max = sp_eval['H MIN'], sp_eval['H MAX']

                    if t >= t_max:
                        set_relay(ch_f, True); relay_states[ch_f] = True
                        current_warnings.append(f"{get_sensor_display_name(skey)} High Temp ({t:.1f}°C > {t_max:.1f}°C)")
                    elif t <= t_min:
                        set_relay(ch_f, False); relay_states[ch_f] = False
                        if t < (t_min - 2.0):
                            current_warnings.append(f"{get_sensor_display_name(skey)} Low Temp ({t:.1f}°C < {t_min:.1f}°C)")
                    
                    if h >= h_max:
                        set_relay(ch_h, True); relay_states[ch_h] = True
                        current_warnings.append(f"{get_sensor_display_name(skey)} High Humidity ({h:.1f}% > {h_max:.1f}%)")
                    elif h <= h_min:
                        set_relay(ch_h, False); relay_states[ch_h] = False
                        if h < (h_min - 5.0):
                            current_warnings.append(f"{get_sensor_display_name(skey)} Low Humidity ({h:.1f}% < {h_min:.1f}%)")
                else:
                    set_relay(ch_f, False); set_relay(ch_h, False)
                    relay_states[ch_f] = False; relay_states[ch_h] = False

        if current_warnings:
            trigger_buzzer_30s()

        active_warnings = current_warnings
        time.sleep(1)


root = tk.Tk()
root.attributes("-fullscreen", True)
root.configure(bg="white")

big = font.Font(family="Arial", size=20, weight="bold")
med = font.Font(family="Arial", size=14, weight="bold")
small = font.Font(family="Arial", size=11, weight="bold")

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
    except Exception as e: pass

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

clock_labels = []

def add_bottom_right_clock(parent, bg_color="white"):
    lbl = tk.Label(
        parent,
        text="📅 Day, YYYY-MM-DD   ⏰ HH:MM:SS (IST)",
        font=("Helvetica", 11, "bold"),
        fg="#00897b",
        bg=bg_color,
        padx=10,
        pady=6
    )
    lbl.place(relx=1.0, rely=1.0, anchor="se", x=-20, y=-15)
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
sensors_grid.pack(pady=15)
sensor_widgets = {}

footer_main = tk.Frame(frame_main, bg="#eeeeee", height=80)
footer_main.pack(side="bottom", fill="x")
footer_main.pack_propagate(False)

btn_pause = tk.Button(footer_main, text="MANUAL STOP", font=med, width=14, bg="#c62828", fg="white", command=lambda: toggle_pause())
btn_pause.pack(side="left", padx=15, pady=10)
tk.Button(footer_main, text="SCHEDULE SLOTS", font=med, width=16, bg="#0284c7", fg="white", command=lambda: open_schedule_editor("S1")).pack(side="left", padx=10, pady=10)
tk.Button(footer_main, text="RESTART", font=med, width=12, bg="#1565c0", fg="white", command=lambda: restart_program()).pack(side="left", padx=10, pady=10)

# Date, Time and Day display in place of old exit button in bottom right footer
lbl_clock = tk.Label(footer_main, text="📅 Day, YYYY-MM-DD   ⏰ HH:MM:SS (IST)", font=("Helvetica", 12, "bold"), fg="#00897b", bg="#eeeeee")
lbl_clock.pack(side="right", padx=20, pady=10)

def update_clock_display():
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist_tz)
    now_str = now.strftime("📅 %A, %Y-%m-%d   ⏰ %H:%M:%S (IST)")
    if 'lbl_clock' in globals() and lbl_clock.winfo_exists():
        lbl_clock.config(text=now_str)
    for lbl in list(clock_labels):
        try:
            if lbl.winfo_exists():
                lbl.config(text=now_str)
            else:
                clock_labels.remove(lbl)
        except Exception:
            pass
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
    if current_time - last_local_save_time < 45: return

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
                
                b_room = tk.Button(sensors_grid, bg="#1565c0", bd=4, relief="raised",
                                   text=f"{disp_name}\n[INITIALIZING]", font=font.Font(size=11, weight="bold"), 
                                   fg="white", width=22, height=5,
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

                    box_text = (
                        f"{disp_name}\n"
                        f"[{setting_nm} - Frame {slot_id}]\n"
                        f"Temp: {t:.1f}°C (Set: {t_target:.1f}°C)\n"
                        f"Humi: {h:.1f}%  (Set: {h_target:.1f}%)"
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
                text="⚠️ WARNING: " + " | ".join(active_warnings[:2]),
                bg="#c62828", fg="white"
            )
        else:
            lbl_warning_bar.config(
                text="✅ SYSTEM NORMAL — ALL PARAMETERS WITHIN RTC SCHEDULED SETPOINTS",
                bg="#2e7d32", fg="white"
            )

        # Update Detail View if open
        if frame_detail.winfo_ismapped() and active_detail_port in snap:
            d = snap[active_detail_port]
            skey = next((k for k, v in SENSOR_MAP.items() if v == active_detail_port), "S1")
            sp_eval = get_active_setpoints(skey)
            if d['status'] == 'OK':
                idx = int(skey.replace('S', '')) - 1
                mapped_f, mapped_h = (idx * 2) + 1, (idx * 2) + 2
                f_s = "[ON]" if relay_states.get(mapped_f) else "[OFF]"
                h_s = "[ON]" if relay_states.get(mapped_h) else "[OFF]"
                txt = (
                    f"{get_sensor_display_name(skey)}\n"
                    f"Profile: {sp_eval['setting_name']} (Slot {sp_eval['slot_id']})\n\n"
                    f"LIVE TEMP: {d['temp']:.1f} °C  (Target: {sp_eval['target_temp']:.1f} °C)\n"
                    f"LIVE HUMI: {d['humi']:.1f} %   (Target: {sp_eval['target_humi']:.1f} %)\n\n"
                    f"{get_f_name(skey)}: {f_s}    Humidifier: {h_s}"
                )
                lbl_detail_data.config(text=txt, fg="#1565c0")
            else:
                lbl_detail_data.config(text="OFFLINE", fg="#c62828")

    except Exception as e: print(f"UI Error: {e}")

    root.after(1000, update_ui)

# --- SENSOR DETAIL VIEW UI ---
active_detail_port = None
lbl_detail_title = tk.Label(frame_detail, text="COLD ROOM DATA", font=big, fg="#1565c0", bg="white")
lbl_detail_title.pack(pady=20)
lbl_detail_data = tk.Label(frame_detail, text="--", font=font.Font(size=20, weight="bold"), bg="white", fg="#1565c0")
lbl_detail_data.pack(pady=25)

def open_sensor_detail(port):
    global active_detail_port; active_detail_port = port
    skey = next((k for k, v in SENSOR_MAP.items() if v == port), "S1")
    lbl_detail_title.config(text=get_sensor_display_name(skey))
    show(frame_detail)

btn_f_det = tk.Frame(frame_detail, bg="white")
btn_f_det.pack(side="bottom", pady=40)
tk.Button(btn_f_det, text="BACK TO DASHBOARD", font=med, bg="#757575", fg="white", width=18, command=lambda: show(frame_main)).pack(side="left", padx=15)
tk.Button(btn_f_det, text="EDIT SCHEDULE SLOTS", font=med, bg="#0284c7", fg="white", width=20, command=lambda: open_schedule_editor(next((k for k, v in SENSOR_MAP.items() if v == active_detail_port), "S1"))).pack(side="left", padx=15)

keypad_modal = None

def open_almora_keypad(title_text, initial_value, callback_on_confirm, is_alphanumeric=False):
    """
    Opens an almora2.py-styled Fullscreen Keypad or Keyboard modal popup.
    - is_alphanumeric=True: Full QWERTY Keyboard layout (for names / strings).
    - is_alphanumeric=False: Standard Numeric + Time/Date Keypad layout.
    Color Palette: DEL (#f97316), CLR (#dc2626), CONFIRM (#0284c7), CANCEL (#64748b).
    """
    global keypad_modal
    if keypad_modal and keypad_modal.winfo_exists():
        keypad_modal.destroy()

    keypad_modal = tk.Toplevel(root)
    keypad_modal.configure(bg="white")

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    keypad_modal.geometry(f"{sw}x{sh}+0+0")
    try:
        keypad_modal.attributes("-fullscreen", True)
    except Exception:
        pass
    keypad_modal.grab_set()
    keypad_modal.focus_force()

    add_logo(keypad_modal)
    add_top_left_exit(keypad_modal)
    add_bottom_right_clock(keypad_modal)

    # Centered container for Fullscreen Keypad Modal
    kp_main = tk.Frame(keypad_modal, bg="white")
    kp_main.pack(expand=True)

    entered_val = str(initial_value)

    lbl_modal_title = tk.Label(kp_main, text=title_text, font=big, fg="#1565c0", bg="white")
    lbl_modal_title.pack(pady=(10, 8))

    lbl_modal_disp = tk.Label(kp_main, text=entered_val, font=("Arial", 22, "bold"), fg="#0f172a", bg="#f1f5f9", width=22, relief="sunken", bd=2)
    lbl_modal_disp.pack(pady=8)

    def kp_press(ch):
        nonlocal entered_val
        if len(entered_val) < 25:
            entered_val += str(ch)
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
    kp_buttons_frame.pack(pady=10)

    if is_alphanumeric:
        rows = [list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL:"), list("ZXCVBNM._-")]
        for ri, row_k in enumerate(rows):
            r_f = tk.Frame(kp_buttons_frame, bg="white")
            r_f.pack(pady=3)
            for ch in row_k:
                tk.Button(r_f, text=ch, font=("Arial", 13, "bold"), width=3, bg="#f1f5f9", fg="#0f172a",
                          command=lambda x=ch: kp_press(x)).pack(side="left", padx=3)
    else:
        num_grid = [
            ('1', 0, 0), ('2', 0, 1), ('3', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('7', 2, 0), ('8', 2, 1), ('9', 2, 2),
            ('.', 3, 0), ('0', 3, 1), (':', 3, 2),
            ('-', 4, 1)
        ]
        for t, r, c in num_grid:
            tk.Button(kp_buttons_frame, text=t, font=("Arial", 16, "bold"), width=5, height=1, bg="#f1f5f9", fg="#0f172a",
                      command=lambda x=t: kp_press(x)).grid(row=r, column=c, padx=5, pady=5)

    kp_actions_frame = tk.Frame(kp_main, bg="white")
    kp_actions_frame.pack(pady=15)

    tk.Button(kp_actions_frame, text="DEL", font=("Arial", 13, "bold"), bg="#f97316", fg="white", width=8, pady=12, command=kp_back).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CLR", font=("Arial", 13, "bold"), bg="#dc2626", fg="white", width=8, pady=12, command=kp_clear).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CONFIRM", font=("Arial", 13, "bold"), bg="#0284c7", fg="white", width=12, pady=12, command=kp_confirm).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CANCEL", font=("Arial", 13, "bold"), bg="#64748b", fg="white", width=10, pady=12, command=kp_cancel).pack(side="left", padx=6)

# ALMORA CALENDAR SLOTS & 5 TIME FRAMES EDITOR HMI

sched_entries = {}

# Permanently packed bottom action buttons frame on schedule editor
sched_btn_frame = tk.Frame(frame_schedule, bg="white")
sched_btn_frame.pack(side="bottom", fill="x", pady=(4, 8))

# Main Scrollable Canvas Container for Schedule Page
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
    except Exception:
        pass

sched_canvas.bind_all("<MouseWheel>", _on_sched_mousewheel)
sched_canvas.bind_all("<Button-4>", _on_sched_mousewheel)
sched_canvas.bind_all("<Button-5>", _on_sched_mousewheel)

lbl_sched_title = tk.Label(sched_scroll_inner, text="ALMORA CALENDAR & SCHEDULE SLOTS EDITOR", font=big, fg="#1565c0", bg="white")
lbl_sched_title.pack(pady=(35, 2))

sched_top_ctrl = tk.Frame(sched_scroll_inner, bg="white")
sched_top_ctrl.pack(pady=2)

# 1. SENSOR & PROFILE DROPDOWNS (MIND.PY STYLED)
tk.Label(sched_top_ctrl, text="Sensor:", font=("Helvetica", 12, "bold"), fg="#475569", bg="white").pack(side="left", padx=(5, 4))

sensor_dropdown_open = False
sensor_dropdown_btn = None
sensor_menu_frame = tk.Frame(sched_scroll_inner, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1")

def toggle_sensor_dropdown():
    global sensor_dropdown_open
    if sensor_dropdown_open:
        sensor_menu_frame.place_forget()
        sensor_dropdown_open = False
    else:
        for w in sensor_menu_frame.winfo_children(): w.destroy()
        for skey in sorted(SENSOR_MAP.keys()):
            dname = get_sensor_display_name(skey)
            btn = tk.Button(sensor_menu_frame, text=f"{skey} — {dname}", font=("Helvetica", 12, "bold"), bg="white", fg="#1e293b",
                            activebackground="#0284c7", activeforeground="white", relief="flat", bd=0, anchor="w", padx=14, pady=10, cursor="hand2")
            btn.config(command=lambda s=skey: select_sensor(s))
            btn.pack(fill="x")
        sensor_menu_frame.place(in_=sensor_dropdown_btn, relx=0.0, rely=1.0, y=2, width=280)
        sensor_menu_frame.lift()
        sensor_dropdown_open = True

def select_sensor(skey):
    global sensor_dropdown_open
    skey_combo.set(skey)
    sensor_menu_frame.place_forget()
    sensor_dropdown_open = False
    load_schedule_form()

sensor_dropdown_btn = tk.Button(sched_top_ctrl, text="S1 — COLD ROOM 1  ▼", font=("Helvetica", 12, "bold"), bg="#f1f5f9", fg="#1e293b",
                                activebackground="#e2e8f0", relief="flat", bd=0, padx=16, pady=10, cursor="hand2", command=toggle_sensor_dropdown)
sensor_dropdown_btn.pack(side="left", padx=(0, 15))

skey_combo = ttk.Combobox(sched_top_ctrl, values=list(SENSOR_MAP.keys()), width=1)
skey_combo.set("S1")

tk.Label(sched_top_ctrl, text="Profile/Season:", font=("Helvetica", 12, "bold"), fg="#475569", bg="white").pack(side="left", padx=(5, 4))

profile_dropdown_open = False
profile_menu_frame = tk.Frame(sched_scroll_inner, bg="white", bd=1, relief="solid", highlightbackground="#cbd5e1")

def toggle_profile_dropdown():
    global profile_dropdown_open
    if profile_dropdown_open:
        profile_menu_frame.place_forget()
        profile_dropdown_open = False
    else:
        for w in profile_menu_frame.winfo_children(): w.destroy()
        sp = get_setpoints(skey_combo.get())
        settings_dict = sp.get("settings", {})
        for s_key in ["Setting A", "Setting B", "Setting C", "Setting D", "Setting E"]:
            p_name = settings_dict.get(s_key, {}).get("name", s_key)
            btn_txt = f"{s_key} ({p_name})" if p_name != s_key else s_key
            btn = tk.Button(profile_menu_frame, text=btn_txt, font=("Helvetica", 12, "bold"), bg="white", fg="#1e293b",
                            activebackground="#0284c7", activeforeground="white", relief="flat", bd=0, anchor="w", padx=14, pady=10, cursor="hand2")
            btn.config(command=lambda s=s_key: select_profile(s))
            btn.pack(fill="x")
        profile_menu_frame.place(in_=profile_dropdown_btn, relx=0.0, rely=1.0, y=2, width=280)
        profile_menu_frame.lift()
        profile_dropdown_open = True

def select_profile(s_name):
    global profile_dropdown_open
    setting_combo.set(s_name)
    profile_menu_frame.place_forget()
    profile_dropdown_open = False
    load_schedule_form()

profile_dropdown_btn = tk.Button(sched_top_ctrl, text="Setting A  ▼", font=("Helvetica", 12, "bold"), bg="#f1f5f9", fg="#1e293b",
                                 activebackground="#e2e8f0", relief="flat", bd=0, padx=16, pady=10, cursor="hand2", command=toggle_profile_dropdown)
profile_dropdown_btn.pack(side="left")

setting_combo = ttk.Combobox(sched_top_ctrl, values=["Setting A", "Setting B", "Setting C", "Setting D", "Setting E"], width=1)
setting_combo.set("Setting A")

def on_schedule_click_outside(event):
    global sensor_dropdown_open, profile_dropdown_open
    w = event.widget
    in_s_dp, in_p_dp = False, False
    while w:
        if w == sensor_menu_frame or w == sensor_dropdown_btn: in_s_dp = True; break
        if w == profile_menu_frame or w == profile_dropdown_btn: in_p_dp = True; break
        try: w = w.master
        except Exception: break
    if not in_s_dp and sensor_dropdown_open:
        sensor_menu_frame.place_forget(); sensor_dropdown_open = False
    if not in_p_dp and profile_dropdown_open:
        profile_menu_frame.place_forget(); profile_dropdown_open = False

frame_schedule.bind("<Button-1>", on_schedule_click_outside)

# 2. DATE RANGE ROW (CENTERED & BORDERLESS OUTSIDE GRID)
date_frame = tk.Frame(sched_scroll_inner, bg="white")
date_frame.pack(pady=2, anchor="center")

tk.Label(date_frame, text="Start Date (YYYY-MM-DD):", font=("Helvetica", 11, "bold"), fg="#64748b", bg="white").grid(row=0, column=0, padx=4, pady=2)
lbl_val_sdate = tk.Label(date_frame, text="2026-07-01", font=("Helvetica", 11, "bold"), bg="#ffffff", fg="#1e293b", width=11, relief="sunken", bd=1)
lbl_val_sdate.grid(row=0, column=1, padx=3, pady=2)

def edit_sdate():
    open_almora_keypad("Edit Start Date (YYYY-MM-DD)", lbl_val_sdate.cget("text"), lambda v: (lbl_val_sdate.config(text=v), save_current_schedule_to_file()))

tk.Button(date_frame, text="EDIT", font=("Helvetica", 12, "bold"), bg="#cbd5e1", fg="#1e293b", activebackground="#cbd5e1", relief="flat", bd=0, padx=18, pady=12, cursor="hand2", command=edit_sdate).grid(row=0, column=2, padx=3, pady=2)

tk.Label(date_frame, text="End Date (YYYY-MM-DD):", font=("Helvetica", 11, "bold"), fg="#64748b", bg="white").grid(row=0, column=3, padx=(18, 4), pady=2)
lbl_val_edate = tk.Label(date_frame, text="2026-08-31", font=("Helvetica", 11, "bold"), bg="#ffffff", fg="#1e293b", width=11, relief="sunken", bd=1)
lbl_val_edate.grid(row=0, column=4, padx=3, pady=2)

def edit_edate():
    open_almora_keypad("Edit End Date (YYYY-MM-DD)", lbl_val_edate.cget("text"), lambda v: (lbl_val_edate.config(text=v), save_current_schedule_to_file()))

tk.Button(date_frame, text="EDIT", font=("Helvetica", 12, "bold"), bg="#cbd5e1", fg="#1e293b", activebackground="#cbd5e1", relief="flat", bd=0, padx=18, pady=12, cursor="hand2", command=edit_edate).grid(row=0, column=5, padx=3, pady=2)

def save_current_schedule_to_file(show_feedback=True):
    try:
        skey = skey_combo.get()
        setting_nm = setting_combo.get()
        sp = get_setpoints(skey)
        st = sp.setdefault("settings", {}).setdefault(setting_nm, {})
        st["start_date"] = lbl_val_sdate.cget("text").strip()
        st["end_date"] = lbl_val_edate.cget("text").strip()
        st["enabled"] = True

        new_slots = []
        for idx in range(5):
            if idx in sched_entries:
                l_fname, l_tstart, l_tstop, l_tmax_val, l_tmin_val, l_hmax_val, l_hmin_val = sched_entries[idx]
                new_slots.append({
                    "id": idx + 1,
                    "name": l_fname.cget("text").strip(),
                    "start": l_tstart.cget("text").strip(),
                    "stop": l_tstop.cget("text").strip(),
                    "t_max": round(float(l_tmax_val.cget("text").strip()), 1),
                    "t_min": round(float(l_tmin_val.cget("text").strip()), 1),
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
            btn_save_sched.config(text="SAVED ✅", bg="#15803d")
            def _reset_btn():
                try:
                    if btn_save_sched.winfo_exists():
                        btn_save_sched.config(text=orig_txt, bg=orig_bg)
                except Exception:
                    pass
            root.after(1500, _reset_btn)
    except Exception as e:
        print(f"Schedule Save Error: {e}")

# Populate permanently packed bottom action buttons
btn_save_sched = tk.Button(sched_btn_frame, text="SAVE SCHEDULE", font=("Helvetica", 12, "bold"), bg="#2e7d32", fg="white", width=20, height=2, cursor="hand2", command=lambda: save_current_schedule_to_file(True))
btn_save_sched.pack(side="left", padx=15)
tk.Button(sched_btn_frame, text="CANCEL / BACK", font=("Helvetica", 12, "bold"), bg="#64748b", fg="white", width=20, height=2, cursor="hand2", command=lambda: show(frame_main)).pack(side="left", padx=15)

# 3. SEPARATE TEMPERATURE & HUMIDITY SCHEDULE GRIDS (CENTERED SQUARE CONTAINERS)
grids_wrapper = tk.Frame(sched_scroll_inner, bg="white")
grids_wrapper.pack(pady=2, anchor="center")

temp_grid_frame = tk.LabelFrame(grids_wrapper, text=" 🌡️ TEMPERATURE SCHEDULE GRID ", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white", bd=2, relief="solid", highlightbackground="#94a3b8")
temp_grid_frame.pack(side="top", anchor="center", padx=8, pady=3)

humi_grid_frame = tk.LabelFrame(grids_wrapper, text=" 💧 HUMIDITY SCHEDULE GRID ", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white", bd=2, relief="solid", highlightbackground="#94a3b8")
humi_grid_frame.pack(side="top", anchor="center", padx=8, pady=3)

def edit_slot_popup(idx):
    l_fname, l_tstart, l_tstop, l_tmax_val, l_tmin_val, l_hmax_val, l_hmin_val = sched_entries[idx]
    
    pop = tk.Toplevel(root)
    pop.configure(bg="white")

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    pop.geometry(f"{sw}x{sh}+0+0")
    try:
        pop.attributes("-fullscreen", True)
    except Exception:
        pass
    pop.grab_set()
    pop.focus_force()

    add_logo(pop)
    add_top_left_exit(pop)
    add_bottom_right_clock(pop)

    header = tk.Frame(pop, bg="white")
    header.pack(pady=(45, 10))
    tk.Label(header, text=f"EDIT SCHEDULE FRAME {idx+1}", font=big, fg="#1565c0", bg="white").pack()

    body = tk.Frame(pop, bg="white")
    body.pack(pady=15)

    items = [
        ("Frame Name", l_fname, True, False),
        ("Start Time", l_tstart, False, False),
        ("Stop Time", l_tstop, False, False),
        ("T MAX (ON °C)", l_tmax_val, False, False),
        ("T MIN (OFF °C)", l_tmin_val, False, False),
        ("H MAX (ON %)", l_hmax_val, False, False),
        ("H MIN (OFF %)", l_hmin_val, False, False),
    ]

    for label, v_lbl, is_alpha, is_float in items:
        r_f = tk.Frame(body, bg="white")
        r_f.pack(fill="x", pady=6)
        tk.Label(r_f, text=f"{label}:", font=("Helvetica", 13, "bold"), fg="#1e293b", bg="white", width=18, anchor="e").pack(side="left", padx=10)
        
        val_display = tk.Label(r_f, text=v_lbl.cget("text"), font=("Helvetica", 13, "bold"), bg="#f1f5f9", fg="#1565c0", width=16, relief="sunken", bd=1)
        val_display.pack(side="left", padx=10)

        def make_callback(orig_label, target_disp):
            def cb(new_val):
                orig_label.config(text=new_val)
                target_disp.config(text=new_val)
            return cb

        callback = make_callback(v_lbl, val_display)

        tk.Button(
            r_f,
            text="EDIT",
            font=("Helvetica", 13, "bold"),
            bg="#cbd5e1",
            fg="#1e293b",
            activebackground="#cbd5e1",
            relief="flat",
            bd=0,
            padx=24,
            pady=14,
            cursor="hand2",
            command=lambda lbl=val_display, cb=callback, title=label, alpha=is_alpha: open_almora_keypad(
                f"Edit {title}", lbl.cget("text"), lambda v: (lbl.config(text=v), cb(v)), is_alphanumeric=alpha
            )
        ).pack(side="left", padx=5)

    def save_and_close_slot():
        save_current_schedule_to_file()
        pop.destroy()
        load_schedule_form()

    def cancel_slot():
        pop.destroy()
        load_schedule_form()

    btn_action_f = tk.Frame(pop, bg="white")
    btn_action_f.pack(side="bottom", pady=30)

    tk.Button(btn_action_f, text="SAVE & APPLY", font=med, bg="#2e7d32", fg="white", width=20, height=2, command=save_and_close_slot).pack(side="left", padx=20)
    tk.Button(btn_action_f, text="CANCEL / CLOSE", font=med, bg="#64748b", fg="white", width=20, height=2, command=cancel_slot).pack(side="left", padx=20)

def load_schedule_form_refresh():
    load_schedule_form()

def load_schedule_form():
    skey = skey_combo.get()
    setting_nm = setting_combo.get()
    
    sp = get_setpoints(skey)
    st = sp.get("settings", {}).get(setting_nm, {})

    profile_disp_name = st.get("name", setting_nm)

    sensor_dropdown_btn.config(text=f"{skey} — {get_sensor_display_name(skey)}  ▼")
    profile_dropdown_btn.config(text=f"{setting_nm} ({profile_disp_name})  ▼" if profile_disp_name != setting_nm else f"{setting_nm}  ▼")

    lbl_val_sdate.config(text=st.get("start_date", "2026-07-01"))
    lbl_val_edate.config(text=st.get("end_date", "2026-08-31"))

    for widget in temp_grid_frame.winfo_children(): widget.destroy()
    for widget in humi_grid_frame.winfo_children(): widget.destroy()
    sched_entries.clear()

    time_slots = st.get("time_slots", [])

    temp_inner = tk.Frame(temp_grid_frame, bg="white")
    temp_inner.pack(anchor="center", padx=8, pady=4)

    humi_inner = tk.Frame(humi_grid_frame, bg="white")
    humi_inner.pack(anchor="center", padx=8, pady=4)
    
    for c in range(6):
        temp_inner.columnconfigure(c, weight=1)
        humi_inner.columnconfigure(c, weight=1)

    card_title_font = font.Font(size=11, weight="bold")
    card_time_font = font.Font(size=10, weight="bold")
    card_val_font = font.Font(size=10, weight="bold")

    for idx in range(5):
        slot_data = time_slots[idx] if idx < len(time_slots) else {"name": f"Frame {idx+1}", "start":"08:00", "stop":"12:00", "t_max":26.0, "t_min":20.0, "h_max":70.0, "h_min":55.0}
        
        frame_name_v = slot_data.get("name", f"Frame {idx+1}")
        t_max_v = slot_data.get("t_max", slot_data.get("temp_setpoint", 24.0) + slot_data.get("temp_tol", 2.0))
        t_min_v = slot_data.get("t_min", slot_data.get("temp_setpoint", 24.0) - slot_data.get("temp_tol", 2.0))
        h_max_v = slot_data.get("h_max", slot_data.get("humi_setpoint", 60.0) + slot_data.get("humi_tol", 5.0))
        h_min_v = slot_data.get("h_min", slot_data.get("humi_setpoint", 60.0) - slot_data.get("humi_tol", 5.0))
        
        start_v = slot_data.get("start", "08:00")
        stop_v = slot_data.get("stop", "12:00")

        l_fname = tk.Label(frame_schedule, text=frame_name_v)
        l_tstart = tk.Label(frame_schedule, text=start_v)
        l_tstop = tk.Label(frame_schedule, text=stop_v)
        l_tmax_val = tk.Label(frame_schedule, text=str(t_max_v))
        l_tmin_val = tk.Label(frame_schedule, text=str(t_min_v))
        l_hmax_val = tk.Label(frame_schedule, text=str(h_max_v))
        l_hmin_val = tk.Label(frame_schedule, text=str(h_min_v))

        sched_entries[idx] = (l_fname, l_tstart, l_tstop, l_tmax_val, l_tmin_val, l_hmax_val, l_hmin_val)

        if idx < 3:
            r_pos = 0
            c_pos = idx * 2
        else:
            r_pos = 1
            c_pos = 1 + (idx - 3) * 2

        # --- 1. TEMPERATURE FRAME SPACIOUS SQUARE CARD ---
        card_t = tk.Frame(temp_inner, bg="#f8fafc", bd=2, relief="solid", highlightbackground="#cbd5e1", width=230, height=175)
        card_t.pack_propagate(False)
        card_t.grid(row=r_pos, column=c_pos, columnspan=2, padx=8, pady=4)

        tk.Label(card_t, text=frame_name_v.upper(), font=card_title_font, fg="#1565c0", bg="#f8fafc").pack(pady=(4,2))
        tk.Label(card_t, text=f"⏰ {start_v} - {stop_v}", font=card_time_font, fg="#334155", bg="#f8fafc").pack(pady=1)
        tk.Label(card_t, text=f"T MAX (ON): {t_max_v:.1f}°C", font=card_val_font, fg="#b91c1c", bg="#f8fafc").pack(pady=1)
        tk.Label(card_t, text=f"T MIN (OFF): {t_min_v:.1f}°C", font=card_val_font, fg="#15803d", bg="#f8fafc").pack(pady=1)

        tk.Button(card_t, text="EDIT FRAME", font=("Helvetica", 11, "bold"), bg="#cbd5e1", fg="#1e293b", activebackground="#cbd5e1", relief="flat", bd=0, padx=20, pady=9, cursor="hand2",
                  command=lambda i=idx: edit_slot_popup(i)).pack(pady=(5, 2))

        # --- 2. HUMIDITY FRAME SPACIOUS SQUARE CARD ---
        card_h = tk.Frame(humi_inner, bg="#f8fafc", bd=2, relief="solid", highlightbackground="#cbd5e1", width=230, height=175)
        card_h.pack_propagate(False)
        card_h.grid(row=r_pos, column=c_pos, columnspan=2, padx=8, pady=4)

        tk.Label(card_h, text=frame_name_v.upper(), font=card_title_font, fg="#1565c0", bg="#f8fafc").pack(pady=(4,2))
        tk.Label(card_h, text=f"⏰ {start_v} - {stop_v}", font=card_time_font, fg="#334155", bg="#f8fafc").pack(pady=1)
        tk.Label(card_h, text=f"H MAX (ON): {h_max_v:.1f}%", font=card_val_font, fg="#b91c1c", bg="#f8fafc").pack(pady=1)
        tk.Label(card_h, text=f"H MIN (OFF): {h_min_v:.1f}%", font=card_val_font, fg="#15803d", bg="#f8fafc").pack(pady=1)

        tk.Button(card_h, text="EDIT FRAME", font=("Helvetica", 11, "bold"), bg="#cbd5e1", fg="#1e293b", activebackground="#cbd5e1", relief="flat", bd=0, padx=20, pady=9, cursor="hand2",
                  command=lambda i=idx: edit_slot_popup(i)).pack(pady=(5, 2))

def open_schedule_editor(skey="S1"):
    skey_combo.set(skey)
    setting_combo.set("Setting A")
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
        
        tk.Button(row, text="EDIT", font=("Arial", 9, "bold"), bg="#0284c7", fg="white", bd=1, relief="groove",
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

tk.Button(frame_set, text="SAVE & RETURN", font=med, bg="#1565c0", fg="white", 
          width=25, command=lambda: (save_setpoints(), show(frame_detail))).pack(side="bottom", pady=20)

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
    print(f"--- STARTING ALMORA COLD ROOM MONITOR & CONTROLLER: {DEVICE_NAME} ---")
    load_config()
    load_setpoints()
    init_mqtt_client()
    threading.Thread(target=auto_trust_devices, daemon=True).start()
    threading.Thread(target=start_bluetooth_server, daemon=True).start()
    threading.Thread(target=sensor_reader, daemon=True).start()
    show(frame_main)
    update_clock_display()
    update_ui()
    root.mainloop()
