import os, sys, json, time
import subprocess, threading
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import font
from gpiozero import OutputDevice, Device
import minimalmodbus
import serial
import paho.mqtt.client as mqtt
# GPIO BACKEND
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
    return "almora1" # Default fallback

DEVICE_NAME = get_device_id()
print(f" Device Identity Loaded: {DEVICE_NAME}")

SETPOINT_FILE = os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}.json")
print(f" Using config: {SETPOINT_FILE}")

# DELETE LEGACY CONFIG TO PREVENT SYNC ERRORS
OLD_FILE = os.path.join(BASE_DIR, "setpoints.json")
if os.path.exists(OLD_FILE):
    try:
        os.remove(OLD_FILE)
        print("🗑️ Removed legacy setpoints.json to ensure dynamic sync...")
    except: pass

SERIAL_PORT = "/dev/ttyUSB0"
DEVICE_ID = 1

#ThingSpeak MQTT Settings 
MQTT_BROKER = "mqtt3.thingspeak.com"

# ACTIVE LOW RELAYS 
relay_ec1 = OutputDevice(22, active_high=False, initial_value=False)
relay_ec2 = OutputDevice(23, active_high=False, initial_value=False)
relay_ph  = OutputDevice(24, active_high=False, initial_value=False)

relay_ec1.off()
relay_ec2.off()
relay_ph.off()

# CONTROL STATE 
ec_active = False
ph_active = False
last_ec = 0
last_ph = 0
mqtt_timer = 0  # To track 20s cloud updates

# SETPOINTS 
setpoints = {
    "EC MIN": 1200,
    "EC MAX": 1800,
    "PH LOW": 5.8,
    "PH HIGH": 6.5,
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
        print(" Pushed almora setpoints to cloud.")
    except Exception as e:
        pass

# MODBUS (minimalmodbus) 
instrument = minimalmodbus.Instrument(SERIAL_PORT, DEVICE_ID)
instrument.serial.baudrate = 9600
instrument.serial.bytesize = 8
instrument.serial.parity   = serial.PARITY_NONE
instrument.serial.stopbits = 1
instrument.serial.timeout  = 1
instrument.mode = minimalmodbus.MODE_RTU

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
        print("ThingSpeak MQTT credentials not set. Waiting for web dashboard configuration...")
        print(f"   Debug: CLIENT ID={client_id}, USERNAME={username}, PASSWORD={'*'*len(password) if password else 'empty'}")
        return

    try:
        port = int(setpoints.get("PORT", 1883))
    except (ValueError, TypeError):
        port = 1883
    
    channel_id = str(setpoints.get("CHANNEL ID", ""))
    if not channel_id:
        print("ThingSpeak Channel ID not set. Waiting for web dashboard configuration...")
        return

    MQTT_TOPIC = f"channels/{channel_id}/publish"
    print(f"🔧 Attempting ThingSpeak connection: broker={MQTT_BROKER}, port={port}, client_id={client_id}, channel={channel_id}")
    
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
    mqtt_client.username_pw_set(username, password)
    try:
        mqtt_client.connect(MQTT_BROKER, port, 60)
        mqtt_client.loop_start()
        print(f"✅ Connected to ThingSpeak MQTT Cloud - Publishing to topic: {MQTT_TOPIC}")
    except Exception as e:
        print(f"❌ MQTT Cloud Connection Failed: {e}")
        mqtt_client = None
        MQTT_TOPIC = ""

init_mqtt_client()

# HiveMQ Two-Way Sync Control setup
CONTROL_BROKER = "broker.hivemq.com"
CONTROL_PORT = 1883
CONTROL_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/update"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"

def on_control_message(client, userdata, msg):
    try:
        global setpoints
        
        print(f"📨 Received message on topic: {msg.topic}")
        print(f"   Payload: {msg.payload.decode()}")
        
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
            "port": "PORT"
        }
        
        new_setpoints = {}
        for k, v in new_data.items():
            internal_key = key_map.get(k, k) # Use mapping or original key
            new_setpoints[internal_key] = v
        
        print(f"   Mapped setpoints: {new_setpoints}")

        ts_changed = False
        for key in ["PORT", "CLIENT ID", "USERNAME", "PASSWORD", "CHANNEL ID"]:
            if key in new_setpoints and str(new_setpoints[key]) != str(setpoints.get(key)):
                print(f"   ✓ {key} changed: {setpoints.get(key)} → {new_setpoints[key]}")
                ts_changed = True

        setpoints.update(new_setpoints)
        save_setpoints()
        
        if ts_changed:
            print(f"🔄 ThingSpeak settings for {DEVICE_NAME} changed. Reconnecting...")
            init_mqtt_client()
            
        def update_ui():
            for key in new_setpoints:
                if 'labels' in globals() and key in labels:
                    labels[key].config(text=str(setpoints[key]))
        
        if 'root' in globals():
            try: root.after(0, update_ui)
            except: pass
                
        print("✅ Almora Setpoints remotely updated via Cloud MQTT!")
    except Exception as e:
        print(f"❌ MQTT Update Error: {e}")
        import traceback
        traceback.print_exc()

is_mqtt_connected = False
control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Almora1_Device_Client_001")
control_client.on_message = on_control_message

# Debug callbacks to track connection status
def on_control_connect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        print(f"✅ Connected to HiveMQ Control Broker (broker.hivemq.com:1883)")
        print(f"   Subscribing to: {CONTROL_TOPIC}")
        print(f"   Subscribing to: {CONTROL_SYNC_TOPIC}")
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(CONTROL_SYNC_TOPIC)
        # Publish current setpoints with retain flag
        client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
        print(f"   ✓ Ready to receive credential updates from web dashboard")
    else:
        is_mqtt_connected = False
        print(f"❌ Failed to connect to HiveMQ: rc={rc}")

def on_control_disconnect(client, userdata, rc, properties=None):
    global is_mqtt_connected
    is_mqtt_connected = False
    if rc != 0:
        print(f"⚠️ Unexpected disconnection from HiveMQ: rc={rc}")
    else:
        print(f"ℹ️ Disconnected from HiveMQ (normal)")

control_client.on_connect = on_control_connect
control_client.on_disconnect = on_control_disconnect

try:
    print("🔌 Attempting to connect to HiveMQ Control Broker (broker.hivemq.com)...")
    control_client.connect(CONTROL_BROKER, CONTROL_PORT, 60)
    control_client.loop_start()
    print("   Connection initiated...")
except Exception as e:
    print(f"❌ Control MQTT Connection Error: {e}")

# SENSOR READ (Registers 1-4) 
def read_sensor():
    try:
        moist = instrument.read_register(0x0012, 1)   # 0.1 %
        temp = instrument.read_register(0x0013, 1, signed=True)  # 0.1 °C
        ec = instrument.read_register(0x0015, 0)  # us/cm
        ph = instrument.read_register(0x0006, 2)  # 0.01 pH

        return {
            "temp": temp,
            "moist": moist,
            "ec": ec,
            "ph": ph,
        }
    except Exception as e:
        print("Sensor error:", e)
        return None

# CONTROL LOGIC 
def control(data):
    global ec_active, ph_active, last_ec, last_ph
    now = time.time()
    warnings = []

    ec = data["ec"]
    ph = data["ph"]

    # EC CONTROL
    if not ec_active and ec < setpoints["EC MIN"]:
        ec_active = True
        relay_ec1.on()
        relay_ec2.on()
        last_ec = now
        warnings.append("⚠ EC LOW – DOSING")

    if ec_active:
        if ec >= setpoints["EC MAX"]:
            relay_ec1.off()
            relay_ec2.off()
            ec_active = False
        elif now - last_ec >= 10:
            relay_ec1.on(); relay_ec2.on()
            last_ec = now

    # PH CONTROL
    if not ph_active and ph > setpoints["PH HIGH"]:
        ph_active = True
        relay_ph.on()
        last_ph = now
        warnings.append("⚠ pH HIGH – CORRECTING")

    if ph_active:
        if ph <= setpoints["PH LOW"]:
            relay_ph.off()
            ph_active = False
        elif now - last_ph >= 10:
            relay_ph.on()
            last_ph = now

    return warnings

# SAFETY & RESTART 
def manual_stop():
    relay_ec1.off(); relay_ec2.off(); relay_ph.off()
    global ec_active, ph_active
    ec_active = False; ph_active = False
    lbl_warn.config(text="🛑 MANUAL STOP")

def restart_program():
    manual_stop()
    try: instrument.serial.close()
    except: pass
    os.execl(sys.executable, sys.executable, *sys.argv)


def set_wifi(ssid, password):
    try:
        print(f"Attempting to connect to SSID: {ssid}")
        
        # 1. First, delete any existing saved profile with this name to avoid the key-mgmt caching bug 
        subprocess.run(['sudo', 'nmcli', 'connection', 'delete', ssid], capture_output=True)
        
        # 2. Try normal connection
        command = ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid, 'password', password]
        result = subprocess.run(command, capture_output=True, text=True)
        
        # 3. If that failed because of the key-mgmt bug, force standard WPA2 security manually
        if "key-mgmt" in result.stderr:
            print("Detected key-mgmt bug. Forcing WPA2-PSK connection...")
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
            raw_names = [name.strip() for name in result.stdout.split('\n') if name.strip()]
            unique_names = sorted(list(set(raw_names)))
            if len(unique_names) == 0:
                return "No networks found... (Check if hotspot is 5GHz instead of 2.4GHz!)"
            response = "\r\n--- NEARBY WIFI NETWORKS ---\r\n"
            for i, name in enumerate(unique_names, 1):
                response += f"{i}. {name}\r\n"
            response += "----------------------------"
            return response
        else:
            return f"SCAN FAILED: {result.stderr.strip()}"
    except Exception as e:
        return f"SCAN ERROR: {str(e)}"

def auto_trust_devices():
    print("Security Agent loaded: Auto-Accepting and Auto-Trusting all paired phones...")
    
    # 1. Spawn a permanent background Bluetooth controller
    # This acts as a robotic "human" that automatically clicks "Yes/Accept" to all pairing PIN requests
    # so you NEVER have to touch the Raspberry Pi Keyboard or Mouse!
    try:
        btctl = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        
        # Override the Desktop GUI and tell Linux to forcefully auto-accept passwords
        btctl.stdin.write("agent NoInputNoOutput\n")
        btctl.stdin.write("default-agent\n")
        btctl.stdin.write("discoverable on\n")
        btctl.stdin.write("pairable on\n")
        btctl.stdin.flush()
    except Exception as e:
        print("Agent spawn failed:", e)

    while True:
        try:
            # Look at all devices successfully paired to the Raspberry Pi
            output = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True)
            for line in output.split('\n'):
                if line.startswith('Device '):
                    mac = line.split(" ")[1]
                    # Automatically whitelist/trust them instantly!
                    os.system(f"sudo bluetoothctl trust {mac} >/dev/null 2>&1")
        except:
            pass
        time.sleep(5)

def start_bluetooth_server():
    try:
        import socket
        
        # 🚨 CRITICAL FIX for Automated Headless reboots:
        # Tell Linux to re-broadcast the "Serial Profile" UUID so the Phone app can find the doorway!
        os.system("sudo sdptool add SP >/dev/null 2>&1")
        time.sleep(1)

        server_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        port = 1
        server_sock.bind((socket.BDADDR_ANY, port))
        server_sock.listen(1)

        print(f"Native Python Bluetooth Server started.")
        print(f"Waiting for connection on port {port} from Phone...")

        while True:
            try:
                client_sock, client_info = server_sock.accept()
                print(f"✅ Accepted connection from Phone Address: {client_info}")
                
                welcome_msg = "\r\n--- RASPBERRY PI IOT CONFIG --- \r\nCommands:\r\n1. WIFI:Network:Password\r\n2. SCAN - (Find nearby networks)\r\n"
                client_sock.send(welcome_msg.encode('utf-8'))

                while True:
                    data = client_sock.recv(1024)
                    if not data:
                        break
                    
                    received_text = data.decode('utf-8').strip()
                    if not received_text:
                        continue
                        
                    print(f"Received from Phone: {received_text}")

                    if received_text.startswith("WIFI:"):
                        parts = received_text.split(":")
                        if len(parts) >= 3:
                            ssid = parts[1]
                            password = ":".join(parts[2:])
                            client_sock.send(f"\r\nAttempting to connect to {ssid}...\r\n".encode('utf-8'))
                            response = set_wifi(ssid, password)
                            client_sock.send(f"{response}\r\n".encode('utf-8'))
                        else:
                            client_sock.send("\r\nERROR: Invalid format. Must be WIFI:SSID:PASSWORD\r\n".encode('utf-8'))
                    
                    elif received_text.startswith("ID:"):
                        new_id = received_text.split(":")[1].strip()
                        if new_id:
                            try:
                                with open(ID_FILE, "w") as f:
                                    f.write(new_id)
                                client_sock.send(f"\r\nSUCCESS: DEVICE ID set to {new_id}!\r\nSystem will RESTART to apply changes.\r\n".encode('utf-8'))
                                root.after(2000, restart_program)
                            except Exception as e:
                                client_sock.send(f"\r\nERROR: {str(e)}\r\n".encode('utf-8'))
                        else:
                            client_sock.send("\r\nERROR: Invalid format. Must be ID:DEVICE_NAME\r\n".encode('utf-8'))
                    
                    elif received_text.upper() == "SCAN":
                        client_sock.send("\r\nScanning for nearby WiFi networks... Please wait\r\n".encode('utf-8'))
                        networks_list = scan_wifi()
                        client_sock.send((networks_list + "\r\n").encode('utf-8'))
                        
                    elif received_text.upper() == "PING":
                        client_sock.send("\r\nPONG - System is Alive!\r\n".encode('utf-8'))
                    else:
                        client_sock.send(f"\r\nUnknown command: {received_text}\r\n".encode('utf-8'))

            except Exception as e:
                print(f"Connection lost or error: {e}")
            finally:
                if 'client_sock' in locals():
                    client_sock.close()
                print("Client disconnected. Waiting for a new connection...")
    except Exception as e:
        print(f"Bluetooth Setup Failed: {e}")

# UI SETUP 
root = tk.Tk()
root.attributes("-fullscreen", True)
root.configure(bg="#f8f9fa")
root.bind("<Escape>", lambda e: root.destroy())

# LOGO (TOP RIGHT) 
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")

try:
    logo_img_raw = Image.open(LOGO_PATH)
    logo_img_raw = logo_img_raw.resize((150, 95), Image.LANCZOS)
    logo_img = ImageTk.PhotoImage(logo_img_raw)
    lbl_logo = tk.Label(root, image=logo_img, bg="#f8f9fa")
    lbl_logo.image = logo_img   
    lbl_logo.place(relx=0.98, y=10, anchor="ne")
except Exception as e:
    lbl_logo = tk.Label(root, text="LOGO MISSING", fg="#c62828", bg="#f8f9fa", font=("Arial", 12, "bold"))
    lbl_logo.place(relx=0.98, y=10, anchor="ne")

big = ("Arial", 20, "bold")
med = ("Arial", 15)
small = ("Arial", 13)

frame_main = tk.Frame(root, bg="#f8f9fa")
frame_set = tk.Frame(root, bg="#f8f9fa")

def show(frame):
    frame_main.pack_forget()
    frame_set.pack_forget()
    frame.pack(fill="both", expand=True)
    if 'lbl_logo' in globals():
        lbl_logo.lift()

show(frame_main)

# DASHBOARD 
lbl_data = tk.Label(frame_main, font=big, fg="#1a1a1a", bg="#f8f9fa", justify="left")
lbl_data.pack(pady=20)

lbl_warn = tk.Label(frame_main, font=med, fg="#c62828", bg="#f8f9fa")
lbl_warn.pack()

lbl_relay = tk.Label(frame_main, font=med, fg="#1565c0", bg="#f8f9fa")
lbl_relay.pack(pady=15)

def relay_status():
    return f"""
    EC MODE : {'ACTIVE' if ec_active else 'OFF'}
    pH MODE : {'ACTIVE' if ph_active else 'OFF'}
    
    EC1  : {'ON' if relay_ec1.is_active else 'OFF'}
    EC2  : {'ON' if relay_ec2.is_active else 'OFF'}
    pH   : {'ON' if relay_ph.is_active else 'OFF'}
    """

LOG_DIR = os.path.join(BASE_DIR, "local_logs")
ACTIVE_LOG_FILE = os.path.join(LOG_DIR, "active.jsonl")
local_log_lock = threading.Lock()
last_local_save_time = 0

COLUMNS = ["timestamp", "temp", "moist", "ec", "ph"]

def pack_entry(ts, raw):
    return [
        ts,
        raw.get("temp"),
        raw.get("moist"),
        raw.get("ec"),
        raw.get("ph")
    ]

def unpack_row(row):
    if not isinstance(row, list) or len(row) < 5:
        return None
    return {
        "temp": row[1],
        "moist": row[2],
        "ec": row[3],
        "ph": row[4],
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
                     # Batch loop
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
                                control_client.publish(f"inhydro/{DEVICE_NAME}/telemetry/live", json.dumps(batch_payload), qos=1)
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
        lbl_data.config(text=f"Temp  : {data['temp']} °C\nEC    : {data['ec']} us/cm\npH    : {data['ph']}")
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
            control_client.publish(f"inhydro/{DEVICE_NAME}/telemetry/live", json.dumps(hive_payload), retain=False)
        except:
            pass

        # Save offline log if disconnected
        save_local_telemetry(data)

        mqtt_timer += 2
        if mqtt_timer >= 2:
            try:
                if mqtt_client and mqtt_client.is_connected():
                    payload = f"field1={data['temp']}&field2={data['moist']}&field3={data['ph']}&field4={data['ec']}"
                    mqtt_client.publish(MQTT_TOPIC, payload)
            except: pass
            mqtt_timer = 0
    else:
        lbl_data.config(text="⚠️ SENSOR ERROR", fg="#c62828")
        lbl_warn.config(text="Check connections / Serial Port")
    root.after(2000, update)

# MAIN FOOTER 
footer = tk.Frame(frame_main, bg="#eeeeee", height=60)
footer.pack(side="bottom", fill="x")
footer.pack_propagate(False)

tk.Button(footer, text="SETPOINTS", font=med, bg="#1565c0", fg="white", width=10,
          command=lambda: show(frame_set)).pack(side="left", padx=10, pady=10)

tk.Button(footer, text="STOP", font=med, bg="#c62828", fg="white", width=10,
          command=manual_stop).pack(side="left", padx=10, pady=10)

tk.Button(footer, text="RESTART", font=med, bg="#455a64", fg="white", width=10,
          command=restart_program).pack(side="left", padx=10, pady=10)

tk.Button(footer, text="EXIT", font=med, bg="#333333", fg="white", width=10,
          command=root.destroy).pack(side="right", padx=10, pady=10)

# SETPOINT SCREEN 
tk.Label(frame_set, text="SYSTEM SETPOINTS", font=("Arial", 16, "bold"), fg="#1565c0", bg="#f8f9fa").pack(pady=10)

labels = {}
selected_key = None
entered_value = ""

def open_keypad(key):
    global selected_key, entered_value
    selected_key = key
    entered_value = ""
    lbl_display.config(text="")
    lbl_title.config(text=f"Editing {key}")
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
    global entered_value
    try:
        value = float(entered_value)
        setpoints[selected_key] = value
        labels[selected_key].config(text=str(value))
        keypad_frame.pack_forget()
    except:
        lbl_display.config(text="ERROR")

def cancel():
    keypad_frame.pack_forget()

def create_row(key):
    row = tk.Frame(frame_set, bg="#f8f9fa")
    row.pack(pady=4)
    tk.Label(row, text=key, font=med, fg="#1a1a1a", bg="#f8f9fa", width=10, anchor="w").pack(side="left")
    labels[key] = tk.Label(row, text=str(setpoints[key]), font=med, fg="#ef6c00", bg="#ffffff", width=8, relief="sunken")
    labels[key].pack(side="left", padx=10)
    tk.Button(row, text="EDIT", font=small, bg="#eeeeee", command=lambda k=key: open_keypad(k)).pack(side="left")

create_row("EC MIN")
create_row("EC MAX")
create_row("PH LOW")
create_row("PH HIGH")

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

# START LOOP 
def main_loop():
    # Start the Auto-Truster Agent in the background
    try:
        trust_thread = threading.Thread(target=auto_trust_devices, daemon=True)
        trust_thread.start()
    except:
        pass

    # Start the Bluetooth Setup Server in a background thread 
    try:
        bt_thread = threading.Thread(target=start_bluetooth_server, daemon=True)
        bt_thread.start()
        print("✅ Background Native Bluetooth Setup Server started")
    except Exception as e:
        print(f"Failed to start Bluetooth thread: {e}")

    # Start the Offline Sync Worker in a background thread
    try:
        sync_thread = threading.Thread(target=sync_offline_data_worker, daemon=True)
        sync_thread.start()
        print("✅ Background Offline Telemetry Sync Worker started")
    except Exception as e:
        print(f"Failed to start Offline Sync thread: {e}")

    update()
    root.mainloop()

if __name__ == "__main__":
    main_loop()
