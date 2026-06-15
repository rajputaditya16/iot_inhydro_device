import os, sys, json, time
import subprocess, threading
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import font
import minimalmodbus
import serial
import paho.mqtt.client as mqtt
from gpiozero import OutputDevice, Device
try:
    from gpiozero.pins.pigpio import PiGPIOFactory
    Device.pin_factory = PiGPIOFactory()
except:
    pass

# CONFIG
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                return f.read().strip()
        except: pass
    return "sensor1" # Default fallback for this device

DEVICE_NAME = get_device_id()
print(f"Device Identity Loaded: {DEVICE_NAME}")

SETPOINT_FILE = os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}.json")
print(f"DEBUG: SETPOINT_FILE path: {SETPOINT_FILE}")
print(f" Using config: {SETPOINT_FILE}")

# DELETE LEGACY CONFIG TO PREVENT SYNC ERRORS
OLD_FILE = os.path.join(BASE_DIR, "config.json")
if os.path.exists(OLD_FILE):
    try:
        os.remove(OLD_FILE)
        print("Removed legacy config.json to ensure dynamic sync...")
    except: pass

SERIAL_PORT = "/dev/ttyUSB0"
DEVICE_ID = 1

#ThingSpeak MQTT Settings 
MQTT_BROKER = "mqtt3.thingspeak.com"

# ACTIVE LOW RELAYS 
relay_temp_heater = OutputDevice(17, active_high=False, initial_value=False)
relay_temp_cooler = OutputDevice(22, active_high=False, initial_value=False)
relay_hum_maker   = OutputDevice(27, active_high=False, initial_value=False)
relay_hum_dehum   = OutputDevice(23, active_high=False, initial_value=False)

relay_temp_heater.off()
relay_temp_cooler.off()
relay_hum_maker.off()
relay_hum_dehum.off()

# CONTROL STATE 
mqtt_timer = 0  
sim_co2 = 400

temp_heater_active = False
temp_cooler_active = False
hum_maker_active = False
hum_dehum_active = False

# SETPOINTS 
setpoints = {
    "T MIN": 10.0,
    "T MAX": 30.0,
    "H MIN": 30.0,
    "H MAX": 80.0,
    "PORT": 1883
}

if os.path.exists(SETPOINT_FILE):
    try:
        with open(SETPOINT_FILE) as f:
            setpoints.update(json.load(f))
    except:
        pass

def save_setpoints():
    with open(SETPOINT_FILE, "w") as f:
        json.dump(setpoints, f, indent=4)
    try:
        control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
        print(" Pushed setpoints to cloud.")
    except Exception as e:
        pass

# --- DYNAMIC HARDWARE REFRESH ---
instrument_sht = None
instrument_co2 = None

def init_sht():
    global instrument_sht
    try:
        if instrument_sht:
            try: instrument_sht.serial.close()
            except: pass
        instrument_sht = minimalmodbus.Instrument("/dev/ttyUSB0", 1)
        instrument_sht.serial.baudrate = 9600
        instrument_sht.serial.timeout = 0.5
        print("✅ SHT20 (USB0) System Refreshed")
    except:
        instrument_sht = None
        print("⚠️ SHT20 (USB0) not found. Waiting...")

def init_co2():
    global instrument_co2
    try:
        if instrument_co2:
            try: instrument_co2.serial.close()
            except: pass
        instrument_co2 = minimalmodbus.Instrument("/dev/ttyUSB1", 1)
        instrument_co2.serial.baudrate = 9600
        instrument_co2.serial.timeout = 0.5
        print("✅ CO2 (USB1) System Refreshed")
    except:
        instrument_co2 = None
        print("⚠️ CO2 (USB1) not found. Waiting...")

def init_instruments():
    init_sht()
    init_co2()

init_instruments()

# MQTT SETUP 
mqtt_client = None
MQTT_TOPIC = ""

def init_mqtt_client():
    global mqtt_client, MQTT_TOPIC
    
    if mqtt_client is not None:
        try:
            mqtt_client.disconnect()
            mqtt_client.loop_stop()
        except:
            pass

    client_id = str(setpoints.get("CLIENT ID", ""))
    username = str(setpoints.get("USERNAME", ""))
    password = str(setpoints.get("PASSWORD", ""))
    
    if not (client_id and username and password):
        print(" [!] ThingSpeak Cloud is offline. Currently waiting for Web Dashboard to send credentials...")
        return

    try:
        port = int(setpoints.get("PORT", 1883))
    except:
        port = 1883
    
    channel_id = str(setpoints.get("CHANNEL ID", ""))
    if not channel_id:
        return

    MQTT_TOPIC = f"channels/{channel_id}/publish"
    print(f"🔧 Starting ThingSpeak Cloud Link...")
    
    # We use a clean client ID for ThingSpeak as provided by their dashboard
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
    mqtt_client.username_pw_set(username, password)
    try:
        mqtt_client.connect(MQTT_BROKER, port, 60)
        mqtt_client.loop_start()
        print(f"✅ ThingSpeak Cloud Connected - Topic: {MQTT_TOPIC}")
        if 'lbl_cloud_status' in globals():
            lbl_cloud_status.config(fg="#007700")
    except Exception as e:
        print(f"❌ ThingSpeak Connection Failed: {e}")
        if 'lbl_cloud_status' in globals():
            lbl_cloud_status.config( fg="#CC0000")
        mqtt_client = None

init_mqtt_client()

# HiveMQ Two-Way Sync Control setup
CONTROL_BROKER = "broker.hivemq.com"
CONTROL_PORT = 1883
CONTROL_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/update"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"
TELEMETRY_TOPIC = f"inhydro/{DEVICE_NAME}/telemetry/live"

def on_control_message(client, userdata, msg):
    try:
        global setpoints
        
        print(f"Received message on topic: {msg.topic}")
        print(f"Payload: {msg.payload.decode()}")
        
        if msg.topic == CONTROL_SYNC_TOPIC:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
            return

        new_data = json.loads(msg.payload.decode())
        print(f"   Parsed JSON: {new_data}")
        
        # Map camelCase from dashboard to Internal Keys
        key_map = {
            "clientId": "CLIENT ID",
            "username": "USERNAME",
            "password": "PASSWORD",
            "channelId": "CHANNEL ID",
            "port": "PORT",
            
        }
        
        new_setpoints = {}
        for k, v in new_data.items():
            internal_key = key_map.get(k, k) 
            new_setpoints[internal_key] = v

        ts_changed = False
        for key in ["PORT", "CLIENT ID", "USERNAME", "PASSWORD", "CHANNEL ID"]:
            if key in new_setpoints and str(new_setpoints[key]) != str(setpoints.get(key)):
                ts_changed = True

        setpoints.update(new_setpoints)
        save_setpoints() # Keep save_setpoints here to ensure local file is updated

        if ts_changed:
            print(f"ThingSpeak settings for {DEVICE_NAME} changed. Reconnecting...")
            init_mqtt_client()
            
        def update_ui():
            for key in new_setpoints:
                if 'labels' in globals() and key in labels:
                    labels[key].config(text=str(setpoints[key]))
        
        if 'root' in globals():
            try: root.after(0, update_ui)
            except: pass
                
        print("Almora Setpoints remotely updated via Cloud MQTT!")
    except Exception as e:
        print(f"MQTT Update Error: {e}")

# --- UNIQUE CLIENT ID FIX ---
import random
client_suffix = random.randint(1000, 9999)
control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, f"{DEVICE_NAME}_Control_{client_suffix}")
control_client.on_message = on_control_message

is_mqtt_connected = False

def on_control_connect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        print(f" Web Dashboard Link Active! Silently listening for incoming credentials on channel: {CONTROL_TOPIC}")
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(CONTROL_SYNC_TOPIC)
        client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
    else:
        is_mqtt_connected = False

def on_control_disconnect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    is_mqtt_connected = False

control_client.on_connect = on_control_connect
control_client.on_disconnect = on_control_disconnect

try:
    control_client.connect(CONTROL_BROKER, CONTROL_PORT, 60)
    control_client.loop_start()
except Exception as e:
    print(f" Control MQTT Connection Error: {e}")

# SENSOR READ
def read_sensor():
    data = {"temp": "N/A", "hum": "N/A", "co2": "N/A"}
    success = False

    # 1. Read SHT20 from USB0
    if instrument_sht:
        try:
            instrument_sht.serial.reset_input_buffer()
            data["temp"] = instrument_sht.read_register(1, 1, functioncode=4, signed=True)
            data["hum"] = instrument_sht.read_register(2, 1, functioncode=4, signed=False)
            success = True
            print(f"DEBUG: USB0 OK -> T:{data['temp']} H:{data['hum']}")
        except:
            print("DEBUG: USB0 Error. Refreshing Port...")
            init_sht() # Dynamic Refresh

    # --- 0.5s DELAY GAP ---
    time.sleep(0.5)

    # 2. Read CO2 from USB1
    if instrument_co2:
        co2_found = False
        try:
            instrument_co2.serial.reset_input_buffer()
            # Scan registers 0, 2, 4, 5 with both functions
            for reg in [0, 2, 4, 5]:
                for func in [3, 4]:
                    try:
                        val = instrument_co2.read_register(reg, 0, functioncode=func, signed=False)
                        if val > 0 and val != 999:
                            data["co2"] = val
                            co2_found = True
                            success = True
                            print(f"DEBUG: USB1 OK -> CO2:{val}")
                            break
                    except: continue
                if co2_found: break
            
            if not co2_found:
                print("DEBUG: USB1 Read Empty. Refreshing Port...")
                init_co2()
        except:
            print("DEBUG: USB1 Error. Refreshing Port...")
            init_co2()

    # Final stabilize delay
    time.sleep(0.2)

    if success:
        return data
    return None

# CONTROL LOGIC
# CONTROL LOGIC: Hysteresis Cycle Logic
# AC (Pin 22): T >= T_MAX -> ON, T <= T_MIN -> OFF
# FANPAD (Pin 23): H >= H_MAX -> ON, H <= H_MIN -> OFF
def control(data):
    global temp_heater_active, temp_cooler_active, hum_maker_active, hum_dehum_active
    msgs = []

    t = data["temp"]
    h = data["hum"]

    # Safety: If N/A, skip control for this cycle
    if t == "N/A" or h == "N/A":
        return msgs # Return empty msgs like original loop

    # Setpoints load
    t_min = float(setpoints.get("T MIN", 10.0))
    t_max = float(setpoints.get("T MAX", 30.0))
    h_min = float(setpoints.get("H MIN", 30.0))
    h_max = float(setpoints.get("H MAX", 80.0))

    # 1. AC Control (Relay on Pin 22)
    # Logic: T_MAX par ON hoga, T_MIN par OFF hoga
    print(f"DEBUG: Testing AC Logic: Current T={t}, T_MAX={t_max}, T_MIN={t_min}, CurrentState={'ACTIVE' if temp_cooler_active else 'OFF'}")
    if t >= t_max:
        if not temp_cooler_active:
            print("TURNING ON Fanpad ")
            relay_temp_cooler.on()
            temp_cooler_active = True
        msgs.append("Fanpad: RUNNING ")
    elif t <= t_min:
        if temp_cooler_active:
            print("TURNING OFF Fanpad ")
            relay_temp_cooler.off()
            temp_cooler_active = False
        msgs.append("Fanpad: STANDBY ")
    else:
        # In Deadband: Maintain current state
        if temp_cooler_active:
            msgs.append("Fanpad: RUNNING ")
        else:
            msgs.append("Fanpad: STANDBY")

    # 2. FanPad Control (Relay on Pin 23)
    # Logic: H_MAX par ON hoga, H_MIN par OFF hoga
    print(f"DEBUG: Testing FanPad Logic: Current H={h}, H_MAX={h_max}, H_MIN={h_min}, CurrentState={'ACTIVE' if hum_dehum_active else 'OFF'}")
    if h >= h_max:
        if not hum_dehum_active:
            print("TURNING ON Humidifier ")
            relay_hum_dehum.on()
            hum_dehum_active = True
        msgs.append("Humidifier: RUNNING ")
    elif h <= h_min:
        if hum_dehum_active:
            print("TURNING OFF Humidifier ")
            relay_hum_dehum.off()
            hum_dehum_active = False
        msgs.append("Humidifier: STANDBY ")
    else:
        # In Deadband: Maintain current state
        if hum_dehum_active:
            msgs.append("Humidifier: RUNNING ")
        else:
            msgs.append("Humidifier: STANDBY")

    # Strict rule: Disable other pins (17, 27)
    relay_temp_heater.off()
    temp_heater_active = False
    relay_hum_maker.off()
    hum_maker_active = False

    return msgs

# SAFETY & RESTART 
def manual_stop():
    relay_temp_heater.off()
    relay_temp_cooler.off()
    relay_hum_maker.off()
    relay_hum_dehum.off()
    global temp_heater_active, temp_cooler_active, hum_maker_active, hum_dehum_active
    temp_heater_active = False
    temp_cooler_active = False
    hum_maker_active = False
    hum_dehum_active = False
    lbl_warn.config(text="SYSTEM PAUSED")

def restart_program():
    try:
        if instrument_sht: instrument_sht.serial.close()
        if instrument_co2: instrument_co2.serial.close()
    except: pass
    os.execl(sys.executable, sys.executable, *sys.argv)


def set_wifi(ssid, password):
    try:
        subprocess.run(['sudo', 'nmcli', 'connection', 'delete', ssid], capture_output=True)
        command = ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid, 'password', password]
        result = subprocess.run(command, capture_output=True, text=True)
        
        if "key-mgmt" in result.stderr:
            fallback_cmd = ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid, 'password', password, 'wifi-sec.key-mgmt', 'wpa-psk']
            result_fallback = subprocess.run(fallback_cmd, capture_output=True, text=True)
            if result_fallback.returncode == 0:
                return f"SUCCESS: Connected to {ssid} (Fallback mode)!"
            else:
                return f"FAILED: {result_fallback.stderr.strip()}"
                
        if result.returncode == 0:
            return f"SUCCESS: Connected to {ssid}!"
        else:
            return f"FAILED: {result.stderr.strip()}"
    except Exception as e:
        return f"ERROR: {str(e)}"

def scan_wifi():
    try:
        command = ['sudo', 'nmcli', '-t', '-f', 'SSID', 'dev', 'wifi']
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            raw_names = [n.strip() for n in result.stdout.split('\n') if n.strip()]
            unique_names = sorted(list(set(raw_names)))
            if not unique_names: return "No networks found..."
            response = "\r\n--- NEARBY WIFI ---\r\n"
            for i, name in enumerate(unique_names, 1):
                response += f"{i}. {name}\r\n"
            return response
        return f"SCAN FAILED: {result.stderr.strip()}"
    except Exception as e:
        return f"SCAN ERROR: {str(e)}"

def auto_trust_devices():
    try:
        btctl = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        btctl.stdin.write("agent NoInputNoOutput\ndefault-agent\ndiscoverable on\npairable on\n")
        btctl.stdin.flush()
    except: pass

    while True:
        try:
            out = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True)
            for line in out.split('\n'):
                if line.startswith('Device '):
                    mac = line.split(" ")[1]
                    os.system(f"sudo bluetoothctl trust {mac} >/dev/null 2>&1")
        except: pass
        time.sleep(5)

def start_bluetooth_server():
    try:
        import socket
        os.system("sudo sdptool add SP >/dev/null 2>&1")
        time.sleep(1)

        server_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        port = 1
        server_sock.bind((socket.BDADDR_ANY, port))
        server_sock.listen(1)

        while True:
            try:
                client_sock, info = server_sock.accept()
                client_sock.send("\r\nInhydro\r\nCommands: WIFI:Network Name:Password, \nSCAN: NEARBY WIFI\r\n".encode('utf-8'))

                while True:
                    data = client_sock.recv(1024)
                    if not data: break
                    
                    text = data.decode('utf-8').strip()
                    if text.startswith("WIFI:"):
                        parts = text.split(":")
                        if len(parts) >= 3:
                            client_sock.send(f"{set_wifi(parts[1], ':'.join(parts[2:]))}\r\n".encode('utf-8'))
                    elif text.startswith("ID:"):
                        new_id = text.split(":")[1].strip()
                        if new_id:
                            with open(ID_FILE, "w") as f: f.write(new_id)
                            client_sock.send(f"\r\nSUCCESS! Rebooting in 2s...\r\n".encode('utf-8'))
                            root.after(2000, restart_program)
                    elif text.upper() == "SCAN":
                        client_sock.send((scan_wifi() + "\r\n").encode('utf-8'))
            except: pass
            finally:
                if 'client_sock' in locals(): client_sock.close()
    except: pass

 
root = tk.Tk()
root.attributes("-fullscreen", True)
root.configure(bg="white")
root.bind("<Escape>", lambda e: root.destroy())

LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
lbl_logo = None

def load_logo():
    global lbl_logo, logo_img
    try:
        img_raw = Image.open(LOGO_PATH).resize((150, 95), Image.LANCZOS)
        logo_img = ImageTk.PhotoImage(img_raw)
        lbl_logo = tk.Label(root, image=logo_img, bg="white")
        lbl_logo.image = logo_img
        lbl_logo.place(relx=0.95, y=10, anchor="ne")
    except Exception as e:
        print(f"Logo fail: {e}")
        lbl_logo = tk.Label(root, text="LOGO MISSING", fg="#c62828", bg="white", font=("Arial", 12, "bold"))
        lbl_logo.place(relx=0.95, y=10, anchor="ne")

load_logo()

big = ("Arial", 20, "bold")
med = ("Arial", 15)
small = ("Arial", 13)

frame_main = tk.Frame(root, bg="white")
frame_set = tk.Frame(root, bg="white")

def show(frame):
    frame_main.pack_forget()
    frame_set.pack_forget()
    frame.pack(fill="both", expand=True)
    if 'lbl_logo' in globals() and lbl_logo is not None:
        lbl_logo.lift()

show(frame_main)

# DASHBOARD 
lbl_data = tk.Label(frame_main, font=big, fg="#007700", bg="white", justify="left")
lbl_data.pack(pady=20)

lbl_warn = tk.Label(frame_main, font=big, fg="red", bg="white")
lbl_warn.pack()

lbl_relay = tk.Label(frame_main, font=med, fg="#005588", bg="white")
lbl_relay.pack(pady=5)

lbl_cloud_status = tk.Label(frame_main, font=med, fg="gray", bg="white")
lbl_cloud_status.pack(pady=5)

def relay_status():
    return f"""
Fanpad : {'ON' if relay_temp_cooler.is_active else 'OFF'}
Humidifier : {'ON' if relay_hum_dehum.is_active else 'OFF'}"""

LOG_DIR = os.path.join(BASE_DIR, "local_logs")
ACTIVE_LOG_FILE = os.path.join(LOG_DIR, "active.jsonl")
local_log_lock = threading.Lock()
last_local_save_time = 0

COLUMNS = ["timestamp", "temp", "hum", "co2"]

def pack_entry(ts, raw):
    return [
        ts,
        raw.get("temp"),
        raw.get("hum"),
        raw.get("co2")
    ]

def unpack_row(row):
    if not isinstance(row, list) or len(row) < 4:
        return None
    raw = {
        "temp": row[1],
        "hum": row[2],
        "co2": row[3]
    }
    return {
        "telemetry": raw,
        "device": DEVICE_NAME,
        "timestamp": row[0]
    }

def save_local_telemetry(data):
    global last_local_save_time
    try:
        connected = is_mqtt_connected and control_client.is_connected()
    except Exception:
        connected = False

    # Store locally ONLY when device is not connected to internet/broker
    if connected:
        return

    current_time = time.time()
    if current_time - last_local_save_time < 45:
        return

    # Use Indian Standard Time (+05:30) offset for timestamping
    import datetime
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ts_str = datetime.datetime.now(ist_tz).isoformat()

    try:
        new_row = pack_entry(ts_str, data)
    except Exception as e:
        print(f"⚠️ Error packing local telemetry entry: {e}")
        last_local_save_time = current_time
        return

    print(f"📝 Saving local telemetry offline: {ts_str}")

    def write_thread():
        with local_log_lock:
            try:
                os.makedirs(LOG_DIR, exist_ok=True)
                write_header = not os.path.exists(ACTIVE_LOG_FILE) or os.path.getsize(ACTIVE_LOG_FILE) == 0
                with open(ACTIVE_LOG_FILE, "a") as f:
                    if write_header:
                        f.write(json.dumps(COLUMNS) + "\n")
                    f.write(json.dumps(new_row) + "\n")
                
                # Check if active log exceeds 10,000 entries (approx 1.5MB)
                if os.path.exists(ACTIVE_LOG_FILE) and os.path.getsize(ACTIVE_LOG_FILE) > 1500000:
                    rot_name = os.path.join(LOG_DIR, f"log_{int(time.time())}.jsonl")
                    os.rename(ACTIVE_LOG_FILE, rot_name)
                print(f"✅ Offline telemetry written successfully to {ACTIVE_LOG_FILE}")
            except Exception as e:
                print(f"Local JSON save error: {e}")

    threading.Thread(target=write_thread, daemon=True).start()
    last_local_save_time = current_time

def sync_offline_data_worker():
    while True:
        try:
            try:
                connected = is_mqtt_connected and control_client.is_connected()
            except Exception:
                connected = False

            if connected and os.path.exists(LOG_DIR):
                files = [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl") or f == "active.jsonl"]
                if "active.jsonl" in files and os.path.exists(ACTIVE_LOG_FILE) and os.path.getsize(ACTIVE_LOG_FILE) > 0:
                    with local_log_lock:
                        rot_name = os.path.join(LOG_DIR, f"log_{int(time.time())}.jsonl")
                        try:
                            os.rename(ACTIVE_LOG_FILE, rot_name)
                        except Exception:
                            pass
                    # Re-list files after rename
                    files = [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl")]
                
                # Filter out active.jsonl just in case, and sort chronologically
                files = [f for f in files if f != "active.jsonl"]
                files.sort()
                
                for fname in files:
                    fpath = os.path.join(LOG_DIR, fname)
                    rows = []
                    with local_log_lock:
                        if os.path.exists(fpath):
                            try:
                                with open(fpath, "r") as f:
                                    first_line = True
                                    for line in f:
                                        line = line.strip()
                                        if line:
                                            parsed = json.loads(line)
                                            if first_line and isinstance(parsed, list) and len(parsed) > 0 and parsed[0] == "timestamp":
                                                first_line = False
                                                continue
                                            rows.append(parsed)
                                            first_line = False
                            except Exception as re:
                                print(f"[OfflineSync] Error reading {fname}: {re}")

                    if not rows:
                        try:
                            os.remove(fpath)
                        except Exception:
                            pass
                        continue

                    print(f"[OfflineSync] Syncing segment {fname} with {len(rows)} entries...")
                    remaining_rows = list(rows)
                    success = True

                    batch_size = 500
                    for idx in range(0, len(rows), batch_size):
                        batch = rows[idx:idx+batch_size]

                        try:
                            conn = is_mqtt_connected and control_client.is_connected()
                        except Exception:
                            conn = False
                        if not conn:
                            print("[OfflineSync] Lost connection during sync. Pausing.")
                            success = False
                            break

                        batch_payload = []
                        for row in batch:
                            payload = unpack_row(row)
                            if payload:
                                batch_payload.append(payload)

                        try:
                            if batch_payload:
                                control_client.publish(TELEMETRY_TOPIC, json.dumps(batch_payload), qos=1)
                            # Small sleep to prevent network choke
                            time.sleep(0.05)
                        except Exception as pe:
                            print(f"[OfflineSync] Publish batch failed: {pe}")
                            success = False
                            break

                        remaining_rows = remaining_rows[len(batch):]

                    # Update the segment file
                    with local_log_lock:
                        try:
                            if remaining_rows:
                                with open(fpath, "w") as f:
                                    f.write(json.dumps(COLUMNS) + "\n")
                                    for r in remaining_rows:
                                        f.write(json.dumps(r) + "\n")
                            else:
                                if os.path.exists(fpath):
                                    os.remove(fpath)
                                print(f"[OfflineSync] Finished and removed log segment: {fname}")
                        except Exception as we:
                            print(f"[OfflineSync] Error updating log segment {fname}: {we}")
                            success = False

                    if not success:
                        break
        except Exception as e:
            print(f"[OfflineSync] General error: {e}")

        time.sleep(15)

def update():
    global mqtt_timer
    data = read_sensor()
    if data:
        warn = control(data)
        
        # Display logic with N/A safety
        temp_val = data['temp']
        hum_val = data['hum']
        try: co2_val = int(data['co2'])
        except: co2_val = data['co2']

        lbl_data.config(text=f"Temp : {temp_val} °C \nHumidity : {hum_val} % \nCO2 : {co2_val} ppm")
        lbl_warn.config(text="\n".join(warn))
        lbl_relay.config(text=relay_status())

        # Live Web Dashboard Sync (Fast Update over HiveMQ)
        try:
            import datetime
            ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            ts_str = datetime.datetime.now(ist_tz).isoformat()
            hive_payload = dict(data)
            hive_payload["device"] = DEVICE_NAME
            hive_payload["timestamp"] = ts_str
            control_client.publish(TELEMETRY_TOPIC, json.dumps(hive_payload), retain=False)
        except: pass

        # Save offline log if disconnected
        save_local_telemetry(data)

        # Cloud Sync (Every 15s to respect ThingSpeak rate limit)
        mqtt_timer += 2
        if mqtt_timer >= 15:
            try:
                if mqtt_client and mqtt_client.is_connected():
                    payload = f"field1={data['temp']}&field2={data['hum']}&field3={data['co2']}"
                    mqtt_client.publish(MQTT_TOPIC, payload)
                    print(f"Published Sensor Data to ThingSpeak: {payload}")
                elif not mqtt_client:
                    print("ThingSpeak MQTT Client not initialized. Configure credentials via web dashboard.")
                else:
                    print("ThingSpeak MQTT Client not connected. Check credentials and network.")
            except Exception as e:
                 print(f"Error publishing to ThingSpeak: {e}")
            mqtt_timer = 0
    else:
        lbl_data.config(text="SENSOR ERROR")
    root.after(2000, update)
 
footer = tk.Frame(frame_main, bg="white", height=80)
footer.pack(side="bottom", fill="x")
footer.pack_propagate(False)

tk.Button(footer, text="SETPOINTS", font=med, width=12, command=lambda: show(frame_set)).pack(side="left", padx=20, pady=10)
tk.Button(footer, text="RESTART", font=med, width=12, command=restart_program).pack(side="left", padx=20, pady=10)
tk.Button(footer, text="EXIT", font=med, width=12, command=root.destroy).pack(side="right", padx=20, pady=10)

# SETPOINT SCREEN 
tk.Label(frame_set, text="SETPOINTS", font=big, fg="#005588", bg="white").pack(pady=10)

labels = {}
selected_key = None
entered_value = ""

def open_keypad(key):
    global selected_key, entered_value
    selected_key = key
    entered_value = ""
    lbl_display.config(text="")
    lbl_title.config(text=f"Set {key}")
    keypad_frame.pack(pady=5)

def press(val):
    global entered_value
    entered_value += str(val)
    lbl_display.config(text=entered_value)

def clear():
    global entered_value
    entered_value = ""
    lbl_display.config(text="")

def confirm():
    try:
        val = float(entered_value)
        setpoints[selected_key] = val
        labels[selected_key].config(text=str(val))
        keypad_frame.pack_forget()
    except:
        lbl_display.config(text="ERROR")

def cancel():
    keypad_frame.pack_forget()

def create_row(key):
    row = tk.Frame(frame_set, bg="white")
    row.pack(pady=5)
    tk.Label(row, text=key, font=med, fg="black", bg="white", width=8).pack(side="left")
    labels[key] = tk.Label(row, text=str(setpoints.get(key, 0)), font=med, fg="#ef6c00", bg="#ffffff", width=8, relief="sunken")
    labels[key].pack(side="left", padx=10)
    tk.Button(row, text="EDIT", font=small, bg="#eeeeee", command=lambda k=key: open_keypad(k)).pack(side="left")

create_row("T MIN")
create_row("T MAX")
create_row("H MIN")
create_row("H MAX")

# COMPACT KEYPAD 
keypad_frame = tk.Frame(frame_set, bg="#eeeeee", bd=1, relief="solid")
lbl_title = tk.Label(keypad_frame, font=med, fg="#1565c0", bg="#eeeeee")
lbl_title.pack(pady=2)
lbl_display = tk.Label(keypad_frame, font=("Arial", 18, "bold"), fg="#2e7d32", bg="white", width=12)
lbl_display.pack(pady=2)

button_frame = tk.Frame(keypad_frame, bg="#eeeeee")
button_frame.pack(padx=5, pady=5)

buttons = [
    ('1',0,0), ('2',0,1), ('3',0,2),
    ('4',1,0), ('5',1,1), ('6',1,2),
    ('7',2,0), ('8',2,1), ('9',2,2),
    ('.',3,0), ('0',3,1), ('CLR',3,2),
]

for (text,r,c) in buttons:
    cmd = lambda x=text: press(x)
    if text == "CLR": cmd = clear
    tk.Button(button_frame, text=text, font=("Arial", 10), width=3, height=1, bg="white", command=cmd).grid(row=r, column=c, padx=2, pady=2)

tk.Button(button_frame, text="CONFIRM", font=("Arial", 10, "bold"), bg="#2e7d32", fg="white", width=8, command=confirm).grid(row=4, column=0, columnspan=2, pady=5)
tk.Button(button_frame, text="CANCEL", font=("Arial", 10, "bold"), bg="#c62828", fg="white", width=8, command=cancel).grid(row=4, column=2, pady=5)

# SETPOINT FOOTER 
footer_set = tk.Frame(frame_set, bg="#eeeeee", height=60)
footer_set.pack(side="bottom", fill="x")
footer_set.pack_propagate(False)

tk.Button(footer_set, text="SAVE & RETURN", font=med, bg="#1565c0", fg="white", width=18, 
          command=lambda: (save_setpoints(), show(frame_main))).pack(pady=10)

def main_loop():
    threading.Thread(target=auto_trust_devices, daemon=True).start()
    threading.Thread(target=start_bluetooth_server, daemon=True).start()
    threading.Thread(target=sync_offline_data_worker, daemon=True).start()
    update()
    root.mainloop()

if __name__ == "__main__":
    main_loop()
