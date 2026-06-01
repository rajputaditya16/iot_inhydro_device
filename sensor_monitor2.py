import time
import minimalmodbus
import glob
import threading
import json
import os
import tkinter as tk
from tkinter import font
import sys
import socket
import subprocess
import paho.mqtt.client as mqtt
from PIL import Image, ImageTk

# CONFIG & IDENTITY
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                return f.read().strip()
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

# Use 'ls -l /dev/serial/by-path/' to find your specific USB port strings.
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

# SYNC TRACKERS
ts_rotation_idx = 0
mqtt_timer = 0

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

def save_setpoints():
    try:
        with open(SETPOINTS_FILE, 'w') as f:
            json.dump(sensor_setpoints, f, indent=4)
        broadcast_current_state() # Trigger immediate two-way web sync
    except: pass

def broadcast_current_state():
    """Broadcasts current setpoints (S1-S7 keys) to web. No conversion needed."""
    if 'control_client' in globals():
        payload = {
            "system_config": system_config,
            "sensor_setpoints": sensor_setpoints
        }
        try:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(payload), retain=True)
            print(f"[SYNC→WEB] Sent to topic {CURRENT_SETP_TOPIC[-20:]}")
        except Exception as e: print(f"Broadcast err: {e}")

def get_setpoints(skey):
    """skey must be 'S1','S2',...,'S7' or 'default'. NEVER a hardware path."""
    if skey not in sensor_setpoints:
        sensor_setpoints[skey] = {
            'T MAX': 30.0,
            'T MIN': 10.0,
            'H MAX': 80.0,
            'H MIN': 30.0
        }
    return sensor_setpoints[skey]

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
                client.send("\r\n Inhydro Cold Room \r\nCommands: WIFI:SSID:PASS, SCAN:NEARBY WiFi\r\n".encode())
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



# THINGSPEAK MQTT (Single Channel Rotation)
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
    """Re-initialise SINGLE ThingSpeak MQTT connection from system_config."""
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
    print(f"[MQTT] ThingSpeak Active: {TS_MQTT_TOPIC or 'NOT SET'}")


CONTROL_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/update"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"

import uuid as _uuid
_safe_client_id = f"Inh_{DEVICE_NAME}_{_uuid.uuid4().hex[:8]}"
try:
    control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, _safe_client_id)
except AttributeError:
    control_client = mqtt.Client(_safe_client_id)

import re as _re

def on_control_message(client, userdata, msg):
    print(f"[MQTT←] Topic: {msg.topic} | Payload: {msg.payload.decode()[:120]}")
    try:
        global system_config, sensor_setpoints

        if msg.topic == CONTROL_SYNC_TOPIC:
            broadcast_current_state()
            return

        new_data = json.loads(msg.payload.decode())

        # ── 1. SETPOINT UPDATE ──────────────────────────────────
        # Determine which S-keys to update (S1-S7 or default)
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
            changed = False
            for k in ["T MAX", "T MIN", "H MAX", "H MIN"]:
                if k in new_data:
                    try:
                        v = float(str(new_data[k]).strip())
                        if sp[k] != v:
                            sp[k] = v
                            changed = True
                            print(f"[SET] {skey}.{k} = {v}")
                    except: pass

        save_setpoints()  # persists + broadcasts back to web

        # 2. triggring relay
        for skey in skeys_to_update:
            if skey not in SENSOR_MAP: continue
            port = SENSOR_MAP[skey]
            idx = int(skey.replace('S', '')) - 1
            
            with sensor_data_lock:
                d = sensor_data.get(port, {})
            if d.get('status') == 'OK':
                sp = sensor_setpoints[skey]
                ch_f, ch_h = (idx * 2) + 1, (idx * 2) + 2
                if d['temp'] >= sp['T MAX']:   set_relay(ch_f, True);  relay_states[ch_f] = True
                elif d['temp'] <= sp['T MIN']: set_relay(ch_f, False); relay_states[ch_f] = False
                if d['humi'] >= sp['H MAX']:   set_relay(ch_h, True);  relay_states[ch_h] = True
                elif d['humi'] <= sp['H MIN']: set_relay(ch_h, False); relay_states[ch_h] = False
                print(f"[RELAY] {skey} → T={d['temp']} H={d['humi']} | ch{ch_f}+ch{ch_h}")

        # ── 3. CREDENTIALS UPDATE (ThingSpeak) ───────────────────
        # Web sends: channelId, readApiKey, writeApiKey, port, username, password, clientId
        # Device uses: TS CHANNEL ID, TS READ KEY, TS WRITE KEY, PORT, TS USERNAME, TS PASSWORD, TS CLIENT ID
        
        mapping = {
            "channelId": "TS CHANNEL ID",
            "readApiKey": "TS READ KEY",
            "writeApiKey": "TS WRITE KEY",
            "port": "PORT",
            "username": "TS USERNAME",
            "password": "TS PASSWORD",
            "clientId": "TS CLIENT ID"
        }
        
        ts_chg = False
        for web_key, internal_key in mapping.items():
            if web_key in new_data:
                val = str(new_data[web_key])
                if str(system_config.get(internal_key)) != val:
                    system_config[internal_key] = val
                    ts_chg = True
        
        # Also check for direct matches (legacy/manual MQTT compatibility)
        TS_KEYS = ["TS CLIENT ID", "TS USERNAME", "TS PASSWORD", "TS CHANNEL ID", "TS READ KEY", "TS WRITE KEY", "PORT"]
        for k in TS_KEYS:
            if k in new_data:
                val = str(new_data[k])
                if str(system_config.get(k)) != val:
                    system_config[k] = val
                    ts_chg = True

        if ts_chg:
            print("\n" + "="*50)
            print("CREDENTIALS UPDATED FROM WEB")
            for k in TS_KEYS: print(f"  {k}: {system_config.get(k)}")
            print("="*50 + "\n")
            save_config()  # CRITICAL: Persist to config_{DEVICE_NAME}.json
            init_mqtt_client()
            broadcast_current_state()

        # ── 4. REFRESH GUI IF SETPOINT SCREEN IS OPEN ───────────
        def _refresh():
            skey = globals().get('active_setup_skey')
            if skey and skey in sensor_setpoints:
                sp = sensor_setpoints[skey]
                for k in ["T MIN", "T MAX", "H MIN", "H MAX"]:
                    if k in labels: labels[k].config(text=str(sp.get(k, '')))
        try: root.after(0, _refresh)
        except: pass

    except Exception as e:
        print(f"[MQTT ERROR] {e}")

def on_control_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(CONTROL_SYNC_TOPIC)
        print(f"[MQTT] Connected and subscribed to HiveMQ sync.")

control_client.on_message = on_control_message
control_client.on_connect = on_control_connect
try:
    control_client.connect_async("broker.hivemq.com", 1883, 60)
    control_client.loop_start()
except Exception as e:
    print(f"[MQTT] Warning: Could not start sync client: {e}")


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
        except Exception:
            pass 
        finally:
            if 'instrument' in locals() and hasattr(instrument, 'serial') and instrument.serial:
                try: instrument.serial.close()
                except: pass
    return False

def sensor_reader():
    global running, system_paused
    while running:
        if system_paused:
            time.sleep(1.0); continue
            
        system_config['relay_port'] = RELAY_PORT_FIXED
        
        # 1. READ ALL SENSORS SEQUENTIALLY
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
                # Auto-scaling for sensors with 0.01 resolution or different scaling factors
                if temp > 150: temp /= 10.0
                if humi > 150: humi /= 10.0

                # Custom humidity calibration for specific cold rooms
                if skey == "S2":
                    humi += 6.5
                if skey == "S3":
                    humi -= 6.0
                if skey == "S4":
                    humi += 2.8

                with sensor_data_lock:
                    sensor_data[port] = {'id': sensor_id, 'temp': temp, 'humi': humi, 'status': 'OK'}
            except Exception:
                with sensor_data_lock: sensor_data[port] = {'id': sensor_id, 'status': 'ERROR'}
            finally:
                if 'instrument' in locals() and hasattr(instrument, 'serial') and instrument.serial:
                    try: instrument.serial.close()
                    except: pass
        
        # 2. APPLY RELAY LOGIC (Ch 1-14) — uses S1-S7 keys for setpoints
        if os.path.exists(RELAY_PORT_FIXED):
            for skey, port in SENSOR_MAP.items():
                idx = int(skey.replace('S', '')) - 1
                ch_f = (idx * 2) + 1        # S1→ch1, S2→ch3, ...
                ch_h = (idx * 2) + 2        # S1→ch2, S2→ch4, ...

                sp = get_setpoints(skey)    # always uses S-key
                with sensor_data_lock:
                    data = sensor_data.get(port, {'status': 'OFFLINE'})

                if data['status'] == 'OK':
                    t, h = data['temp'], data['humi']
                    if t >= sp['T MAX']:   set_relay(ch_f, True);  relay_states[ch_f] = True
                    elif t <= sp['T MIN']: set_relay(ch_f, False); relay_states[ch_f] = False
                    if h >= sp['H MAX']:   set_relay(ch_h, True);  relay_states[ch_h] = True
                    elif h <= sp['H MIN']: set_relay(ch_h, False); relay_states[ch_h] = False
                else:
                    set_relay(ch_f, False); set_relay(ch_h, False)
                    relay_states[ch_f] = False; relay_states[ch_h] = False
        
        time.sleep(1)

root = tk.Tk()
root.attributes("-fullscreen", True)
root.configure(bg="white")

big = font.Font(family="Arial", size=20, weight="bold")
med = font.Font(family="Arial", size=15)
small = font.Font(family="Arial", size=12, weight="bold")

frame_main = tk.Frame(root, bg="white")
frame_set = tk.Frame(root, bg="white")
frame_config = tk.Frame(root, bg="white")
frame_detail = tk.Frame(root, bg="white")

# Helper to load and display logo at top right
def add_logo(parent):
    try:
        path = os.path.join(BASE_DIR, "logo.png")
        if os.path.exists(path):
            img = Image.open(path)
            # Yahan hum height aur width define kar sakte hain:
            width, height = 150, 60 
            img = img.resize((width, height), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(parent, image=photo, bg="white")
            lbl.image = photo 
            lbl.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=20)
    except Exception as e: 
        print(f"Logo error: {e}")

def show(frame):
    for f in [frame_main, frame_set, frame_detail]:
        f.pack_forget()
    frame.pack(fill="both", expand=True)
    add_logo(frame)

def get_sensor_display_name(skey):
    if skey == "S7": return "GREEN HOUSE"
    return f"COLD ROOM {skey.replace('S', '')}"

def get_f_name(skey):
    if skey == "S7": return "Fanpad"
    return "AC"

# --- DASHBOARD UI ---
tk.Label(frame_main, text="INHYDRO COLD ROOM DASHBOARD", font=big, fg="#1565c0", bg="white").pack(pady=10)
lbl_board_status = tk.Label(frame_main, text="", font=med, bg="white", fg="#c62828")
lbl_board_status.pack(pady=5)

sensors_grid = tk.Frame(frame_main, bg="white")
# Don't use weight=1 on row/column to keep boxes small
sensors_grid.pack(pady=20)

sensor_widgets = {}

def open_config():
    show(frame_config)
    update_config_list()

footer_main = tk.Frame(frame_main, bg="#eeeeee", height=80)
footer_main.pack(side="bottom", fill="x")
footer_main.pack_propagate(False)

btn_pause = tk.Button(footer_main, text="MANUAL STOP", font=med, width=15, bg="#c62828", fg="white", command=lambda: toggle_pause())
btn_pause.pack(side="left", padx=10, pady=10)
tk.Button(footer_main, text="RESTART", font=med, width=12, bg="#1565c0", fg="white", command=lambda: restart_program()).pack(side="left", padx=10, pady=10)
tk.Button(footer_main, text="EXIT", font=med, width=12, command=lambda: quit_app()).pack(side="right", padx=20, pady=10)

def toggle_pause():
    global system_paused
    system_paused = not system_paused
    if system_paused:
        btn_pause.config(text="RESTART/RUN", bg="#2e7d32")
    else:
        btn_pause.config(text="MANUAL STOP", bg="#c62828")

def rebuild_grid():
    """Re-grid all existing sensor frames so positions are correct after add/remove."""
    # Reset existing weight configs to avoid old leftovers
    for i in range(10): 
        sensors_grid.columnconfigure(i, weight=0)
        sensors_grid.rowconfigure(i, weight=0)

    for idx, p in enumerate(sorted(sensor_widgets.keys())):
        r, c = idx // 4, idx % 4
        # Remove sticky="nsew" so buttons stay their defined width/height
        sensor_widgets[p]['frame'].grid(row=r, column=c, padx=10, pady=10)

def update_ui():
    if not running: return
    try:
        # --- FIXED UI MAPPING ---
        grid_changed = False
        for skey, port in SENSOR_MAP.items():
            if port not in sensor_widgets:
                # Square large boxes
                f = tk.Button(sensors_grid, bg="#1565c0", bd=4, relief="raised",
                              text=get_sensor_display_name(skey), font=font.Font(size=14, weight="bold"), 
                              fg="white", width=14, height=5,
                              command=lambda p=port: open_sensor_detail(p))
                sensor_widgets[port] = {'frame': f}
                grid_changed = True

        if grid_changed: rebuild_grid()

        # Create a safe snapshot of data for UI updates
        with sensor_data_lock: 
            snap = dict(sensor_data)

        # Update Grid Buttons with Live Data
        for skey, port in SENSOR_MAP.items():
            if port in sensor_widgets:
                btn = sensor_widgets[port]['frame']
                d = snap.get(port)
                disp_name = get_sensor_display_name(skey)
                sp = get_setpoints(skey)
                if d and d.get('status') == 'OK':
                    btn_text = f"{disp_name}\nTemp: {d['temp']:.1f}°C\nHum: {d['humi']:.1f}%"
                    try:
                        t_min = float(sp.get('T MIN', 10.0) if sp.get('T MIN') not in [None, ""] else 10.0)
                        t_max = float(sp.get('T MAX', 30.0) if sp.get('T MAX') not in [None, ""] else 30.0)
                        h_min = float(sp.get('H MIN', 30.0) if sp.get('H MIN') not in [None, ""] else 30.0)
                        h_max = float(sp.get('H MAX', 80.0) if sp.get('H MAX') not in [None, ""] else 80.0)
                        
                        if t_min <= d['temp'] <= t_max and h_min <= d['humi'] <= h_max:
                            btn.config(text=btn_text, bg="green")
                        else:
                            btn.config(text=btn_text, bg="red")
                    except Exception:
                        btn.config(text=btn_text, bg="red")
                elif d and d.get('status') == 'ERROR':
                    btn.config(text=f"{disp_name}\n[ERROR]", bg="red")
                else:
                    btn.config(text=f"{disp_name}\n[OFFLINE]", bg="red")

        # Update live data only for active detail
        if frame_detail.winfo_ismapped() and active_detail_port in snap:
            d = snap[active_detail_port]
            if d['status'] == 'OK':
                # Find S-key for this port
                skey = next((k for k, v in SENSOR_MAP.items() if v == active_detail_port), "S?")
                idx = int(skey.replace('S', '')) - 1
                mapped_f, mapped_h = (idx * 2) + 1, (idx * 2) + 2
                f_s = "[ON]" if relay_states.get(mapped_f) else "[OFF]"
                h_s = "[ON]" if relay_states.get(mapped_h) else "[OFF]"
                txt = f"{get_sensor_display_name(skey)}\nTEMP: {d['temp']:.1f} °C\nHUM: {d['humi']:.1f} %\n\n{get_f_name(skey)}: {f_s}\nHumidifier: {h_s}"
                lbl_detail_data.config(text=txt, fg="#1a237e")
            else:
                lbl_detail_data.config(text="OFFLINE", fg="red")
    except Exception as e: print(f"UI Error: {e}")
        
    global mqtt_timer, ts_rotation_idx
    mqtt_timer += 1
    
    # 1. LIVE MONITORING JSON PACKET (HiveMQ)
    with sensor_data_lock: snap = dict(sensor_data)
    try:
        live_data_payload = {}
        for skey, port in SENSOR_MAP.items():
            d = snap.get(port, {'status': 'OFFLINE'})
            live_data_payload[skey] = {
                't': d.get('temp', 0),
                'h': d.get('humi', 0),
                'status': d.get('status')
            }
        # Publish all 7 sensors in one burst
        control_client.publish(f"inhydro/{DEVICE_NAME}/telemetry/live", json.dumps(live_data_payload))
    except: pass

    # 2. HISTORICAL LOGGING (ThingSpeak ARRAY transmission for all 7 sensors)
    if mqtt_timer >= 20: 
        mqtt_timer = 0
        t_arr, h_arr = [], []
        # Build strict 7-element arrays matching S1 to S7
        for i in range(1, 8):
            skey = f"S{i}"
            if skey in SENSOR_MAP:
                d = snap.get(SENSOR_MAP[skey])
                if d and d.get('status') == 'OK':
                    t_arr.append(round(d.get('temp', 0), 1))
                    h_arr.append(round(d.get('humi', 0), 1))
                    continue
            t_arr.append(0.0)
            h_arr.append(0.0)
        
        payload = f"field1={json.dumps(t_arr)}&field2={json.dumps(h_arr)}&status=MultiSensor_S1-S7"
        if mqtt_ts_client:
            try: mqtt_ts_client.publish(TS_MQTT_TOPIC, payload)
            except: pass
    
    root.after(1000, update_ui)

# (frame_config UI and helper functions removed because relay is fixed on USB0)

# --- SENSOR DETAIL VIEW UI ---
active_detail_port = None
lbl_detail_title = tk.Label(frame_detail, text="COLD ROOM DATA", font=big, fg="#1565c0", bg="white")
lbl_detail_title.pack(pady=30)
lbl_detail_data = tk.Label(frame_detail, text="--", font=font.Font(size=25, weight="bold"), bg="white", fg="black")
lbl_detail_data.pack(pady=40)

def open_sensor_detail(port):
    global active_detail_port; active_detail_port = port
    skey = next((k for k, v in SENSOR_MAP.items() if v == port), "S?")
    lbl_detail_title.config(text=get_sensor_display_name(skey) if skey != "S?" else "UNKNOWN")
    show(frame_detail)

btn_f_det = tk.Frame(frame_detail, bg="white")
btn_f_det.pack(side="bottom", pady=50)
tk.Button(btn_f_det, text="BACK TO GRID", font=med, bg="#757575", fg="white", width=20, command=lambda: show(frame_main)).pack(side="left", padx=20)
tk.Button(btn_f_det, text="SETPOINTS", font=med, bg="#2e7d32", fg="white", width=20, command=lambda: open_setpoints(active_detail_port)).pack(side="left", padx=20)

# --- SETPOINT STUDIO UI ---
active_setup_sensor = None
labels, selected_key, entered_value = {}, None, ""
lbl_set_title = tk.Label(frame_set, text="SETPOINTS", font=big, fg="#005588", bg="white")
lbl_set_title.pack(pady=10)
setpoints_container = tk.Frame(frame_set, bg="white")
setpoints_container.pack(pady=5)

# active_setup_skey: 'S1', 'S2', etc. (NOT hardware path)
active_setup_skey = None

def open_setpoints(port):
    """port is the hardware path; we derive the S-key from SENSOR_MAP."""
    global active_setup_skey
    
    found_skey = "S1"
    for k, v in SENSOR_MAP.items():
        if v == port: found_skey = k; break
        
    active_setup_skey = found_skey
    lbl_set_title.config(text=f"SETPOINTS : {get_sensor_display_name(active_setup_skey)}")
    keypad_frame.pack_forget()
    for widget in setpoints_container.winfo_children(): widget.destroy()
    labels.clear()
    sp = get_setpoints(active_setup_skey)
    for key in ["T MIN", "T MAX", "H MIN", "H MAX"]:
        row = tk.Frame(setpoints_container, bg="white"); row.pack(pady=3)
        tk.Label(row, text=key, font=med, width=8).pack(side="left")
        labels[key] = tk.Label(row, text=str(sp.get(key, 0)), font=med, fg="#ef6c00", width=8, relief="sunken")
        labels[key].pack(side="left", padx=10)
        tk.Button(row, text="EDIT", command=lambda k=key: open_keypad(k)).pack(side="left")
    show(frame_set)

def open_keypad(key):
    global selected_key, entered_value; selected_key = key; entered_value = ""
    lbl_display.config(text=""); lbl_keypad_title.config(text=f"Set {key}"); keypad_frame.pack(pady=15)

def press(v): global entered_value; entered_value += str(v); lbl_display.config(text=entered_value)
def clr(): global entered_value; entered_value = ""; lbl_display.config(text="")

def confirm():
    global entered_value
    try:
        val = float(entered_value)
        # 1. Save the new value under the correct S-key
        sp = get_setpoints(active_setup_skey)
        sp[selected_key] = val
        labels[selected_key].config(text=str(val))
        keypad_frame.pack_forget()
        save_setpoints()  # saves file + broadcasts to web
        print(f"[GUI] {active_setup_skey}.{selected_key} = {val}")

        # 2. Instant relay trigger
        if active_setup_skey in SENSOR_MAP:
            port = SENSOR_MAP[active_setup_skey]
            idx = int(active_setup_skey.replace('S', '')) - 1
            with sensor_data_lock:
                d = sensor_data.get(port, {})
            if d.get('status') == 'OK':
                    sp2 = sensor_setpoints[active_setup_skey]
                    ch_f, ch_h = (idx * 2) + 1, (idx * 2) + 2
                    if d['temp'] >= sp2['T MAX']:   set_relay(ch_f, True);  relay_states[ch_f] = True
                    elif d['temp'] <= sp2['T MIN']: set_relay(ch_f, False); relay_states[ch_f] = False
                    if d['humi'] >= sp2['H MAX']:   set_relay(ch_h, True);  relay_states[ch_h] = True
                    elif d['humi'] <= sp2['H MIN']: set_relay(ch_h, False); relay_states[ch_h] = False
    except Exception as e:
        print(f"[GUI ERROR] {e}")
        lbl_display.config(text="ERR")
    finally:
        entered_value = ""

keypad_frame = tk.Frame(frame_set, bg="#eeeeee", bd=1, relief="solid")
lbl_keypad_title = tk.Label(keypad_frame, font=med, bg="#eeeeee"); lbl_keypad_title.pack()
lbl_display = tk.Label(keypad_frame, font=("Arial", 18, "bold"), bg="white", width=12); lbl_display.pack()
btn_f = tk.Frame(keypad_frame, bg="#eeeeee"); btn_f.pack(padx=10, pady=5)
for (t,r,c) in [('1',0,0),('2',0,1),('3',0,2),('4',1,0),('5',1,1),('6',1,2),('7',2,0),('8',2,1),('9',2,2),('.',3,0),('0',3,1),('CLR',3,2)]:
    tk.Button(btn_f, text=t, font=med, width=4, command=clr if t=='CLR' else lambda x=t: press(x)).grid(row=r, column=c, padx=2, pady=2)
tk.Button(btn_f, text="CONFIRM", bg="#2e7d32", fg="white", command=confirm).grid(row=4, column=0, columnspan=2, pady=5)
tk.Button(btn_f, text="CANCEL", bg="#c62828", fg="white", command=lambda: keypad_frame.pack_forget()).grid(row=4, column=2, pady=5)

tk.Button(frame_set, text="SAVE & RETURN", font=med, bg="#1565c0", fg="white", 
          width=25, command=lambda: (save_setpoints(), show(frame_detail))).pack(side="bottom", pady=20)

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
    print(f"--- STARTING COLD STORAGE MONITOR: {DEVICE_NAME} ---")
    load_config()
    load_setpoints()
    init_mqtt_client()
    threading.Thread(target=auto_trust_devices, daemon=True).start()
    threading.Thread(target=start_bluetooth_server, daemon=True).start()
    threading.Thread(target=sensor_reader, daemon=True).start()
    show(frame_main)
    update_ui()
    root.mainloop()
