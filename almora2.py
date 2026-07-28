import os, sys, json, time, datetime, socket
import subprocess, threading
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import font
from gpiozero import OutputDevice, Device
import minimalmodbus
import serial
import paho.mqtt.client as mqtt

# ==========================================
# GPIO BACKEND SETUP
# ==========================================
try:
    from gpiozero.pins.pigpio import PiGPIOFactory
    Device.pin_factory = PiGPIOFactory()
except Exception as e:
    print("Notice: PiGPIOFactory not initialized, using default GPIO backend:", e)

# ==========================================
# DEVICE CONFIG & SETPOINT PATHS
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                val = f.read().strip()
                if val: return val
        except Exception: pass
    return "almora1" # Default fallback device identity

DEVICE_NAME = get_device_id()
print(f"📌 Device Identity Loaded: {DEVICE_NAME}")

SETPOINT_FILE = os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}.json")
print(f"📁 Using setpoint file: {SETPOINT_FILE}")

# Remove legacy config to prevent sync issues
OLD_FILE = os.path.join(BASE_DIR, "setpoints.json")
if os.path.exists(OLD_FILE):
    try:
        os.remove(OLD_FILE)
        print("🗑️ Removed legacy setpoints.json...")
    except Exception: pass

# Fixed Serial Ports with By-Path Mapping (Matching control121.py)
SERIAL_PORT_WATER = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.4.2:1.0-port0"
SERIAL_PORT_MD02  = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.4.1:1.0-port0"

DEVICE_ID_WATER = 1
DEVICE_ID_MD02  = 1

# ==========================================
# ACTIVE-LOW RELAY ALLOCATIONS
# ==========================================
# Water / Dosing Relays
relay_ec1 = OutputDevice(22, active_high=False, initial_value=False)
relay_ec2 = OutputDevice(23, active_high=False, initial_value=False)
relay_ph  = OutputDevice(24, active_high=False, initial_value=False)

# Dedicated MD02 Temperature & Humidity Relays
relay_temp = OutputDevice(27, active_high=False, initial_value=False) # Temp Relay (Cooling/AC)
relay_humi = OutputDevice(17, active_high=False, initial_value=False) # Humidity Relay (Dehumidification)

# Dedicated Cyclic Timers Relays
relay_timer1 = OutputDevice(5, active_high=False, initial_value=False) # Cyclic Timer 1 Relay
relay_timer2 = OutputDevice(6, active_high=False, initial_value=False) # Cyclic Timer 2 Relay

def all_relays_off():
    for r in [relay_ec1, relay_ec2, relay_ph, relay_temp, relay_humi, relay_timer1, relay_timer2]:
        try: r.off()
        except: pass

all_relays_off()

# ==========================================
# CONTROL STATE & SETPOINTS
# ==========================================
ec_active   = False
ph_active   = False
temp_active = False
humi_active = False
humi_logic_active = False

last_ec = 0
last_ph = 0

timer_state = {
    1: {"state": "OFF", "last": 0.0},
    2: {"state": "OFF", "last": 0.0},
    "humi": {"state": "OFF", "last": 0.0}
}

# DEFAULT SETPOINTS
setpoints = {
    # Nutrients & pH
    "EC MIN": 1200,
    "EC MAX": 1800,
    "PH LOW": 5.8,
    "PH HIGH": 6.5,
    
    # Climate Control (MD02 Temp & Humidity)
    "TEMP MAX": 28.0,
    "TEMP MIN": 22.0,
    "HUMI MAX": 70.0,
    "HUMI MIN": 50.0,
    
    # Humidifier Day/Night Cyclic Timer & Separate Day/Night Thresholds
    "HUMI Name": "FOGGER TIMER",
    "HUMI D_Start": "06:00",
    "HUMI D_Stop": "18:00",
    "HUMI D_ON Min": 10,
    "HUMI D_OFF Min": 20,
    "HUMI D_Max": 75.0,
    "HUMI D_Min": 55.0,

    "HUMI N_Start": "18:00",
    "HUMI N_Stop": "06:00",
    "HUMI N_ON Min": 5,
    "HUMI N_OFF Min": 40,
    "HUMI N_Max": 80.0,
    "HUMI N_Min": 60.0,

    # Cyclic Timer 1
    "Timer1 Name": "Timer 1",
    "Timer1 Start": "06:00",
    "Timer1 Stop": "18:00",
    "Timer1 ON Min": 5,
    "Timer1 OFF Min": 15,
    
    # Cyclic Timer 2
    "Timer2 Name": "Timer 2",
    "Timer2 Start": "00:00",
    "Timer2 Stop": "23:59",
    "Timer2 ON Min": 10,
    "Timer2 OFF Min": 20,
    
    # Two-User Authentication Credentials
    "USER 1 Name": "Operator 1",
    "USER 1 PASSWORD": "1111",
    "USER 2 Name": "Operator 2",
    "USER 2 PASSWORD": "2222",
    
    # Cloud Config
    "PORT": 1883
}

if os.path.exists(SETPOINT_FILE):
    try:
        with open(SETPOINT_FILE) as f:
            setpoints.update(json.load(f))
    except Exception as e:
        print(f"Error loading setpoint file: {e}")

def save_setpoints():
    try:
        with open(SETPOINT_FILE, "w") as f:
            json.dump(setpoints, f, indent=4)
        if 'control_client' in globals() and control_client.is_connected():
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
            print("📤 Pushed setpoints to cloud broker.")
    except Exception as e:
        print(f"Error saving setpoints: {e}")

# ==========================================
# MODBUS SENSOR INSTRUMENTS
# ==========================================
def open_modbus_instrument(port, device_id):
    try:
        inst = minimalmodbus.Instrument(port, device_id)
        inst.serial.baudrate = 9600
        inst.serial.bytesize = 8
        inst.serial.parity   = serial.PARITY_NONE
        inst.serial.stopbits = 1
        inst.serial.timeout  = 1.5
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True
        return inst
    except Exception:
        return None

water_instrument = open_modbus_instrument(SERIAL_PORT_WATER, DEVICE_ID_WATER)
md02_instrument  = open_modbus_instrument(SERIAL_PORT_MD02, DEVICE_ID_MD02)

# Read Water/Soil Sensor (Registers for Moist, Temp, EC, pH matching control121.py)
def read_water_sensor():
    global water_instrument
    if water_instrument is None:
        water_instrument = open_modbus_instrument(SERIAL_PORT_WATER, DEVICE_ID_WATER)
    if water_instrument is None:
        return None
    try:
        water_instrument.serial.reset_input_buffer()
        data = water_instrument.read_registers(registeraddress=18, number_of_registers=4, functioncode=3)
        moist  = round(data[0] / 10.0, 1)                  # %
        temp   = round(data[1] / 10.0, 1)                  # °C
        raw_ec = data[2]                                   # uS/cm
        ec     = round((raw_ec * 0.85) / 1000.0, 2)         # mS/cm
        ph     = round(data[3] / 100.0, 2)                 # pH
        return {"temp": temp, "moist": moist, "ec": ec, "raw_ec": raw_ec, "ph": ph}
    except Exception as e:
        print(f"⚠️ Water Sensor Read Failed: {e}")
        return None

# Read MD02 Temperature & Humidity Transmitter (Modbus RTU matching control121.py)
def read_md02_sensor():
    global md02_instrument
    if md02_instrument is None:
        md02_instrument = open_modbus_instrument(SERIAL_PORT_MD02, DEVICE_ID_MD02)
    if md02_instrument is None:
        return None
    try:
        md02_instrument.serial.reset_input_buffer()
        try:
            rt = md02_instrument.read_register(1, 1, signed=True, functioncode=4)
            rh = md02_instrument.read_register(2, 1, functioncode=4)
        except Exception:
            rt = md02_instrument.read_register(1, 1, signed=True, functioncode=3)
            rh = md02_instrument.read_register(2, 1, functioncode=3)
        return {"room_temp": round(rt, 1), "room_humi": round(rh, 1)}
    except Exception as e:
        print(f"⚠️ MD02 Sensor Read Failed: {e}")
        return None

# ==========================================
# PRIVATE VPS MOSQUITTO BROKER SETUP
# ==========================================
CONTROL_BROKER = "147.93.106.142"
CONTROL_PORT = 1883
CONTROL_USER = "Inhydro@5598"
CONTROL_PASS = "MGPL@5598"
CONTROL_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/update"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"
LIVE_TELEMETRY_TOPIC = f"inhydro/{DEVICE_NAME}/telemetry/live"

def on_control_message(client, userdata, msg):
    try:
        if msg.topic == CONTROL_SYNC_TOPIC:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
            return

        new_data = json.loads(msg.payload.decode())
        setpoints.update(new_data)
        save_setpoints()
            
        def update_ui():
            if 'sp_labels' in globals():
                for key in new_data:
                    if key in sp_labels:
                        sp_labels[key].config(text=str(setpoints[key]))
        if 'root' in globals():
            try: root.after(0, update_ui)
            except Exception: pass
    except Exception as e:
        print(f"❌ Private Control MQTT Update Error: {e}")

is_mqtt_connected = False
control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, f"Almora2_Device_{DEVICE_NAME}")
control_client.on_message = on_control_message

def on_control_connect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(CONTROL_SYNC_TOPIC)
        client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
        print(f"✅ Connected to Private VPS Mosquitto Broker ({CONTROL_BROKER})")
    else:
        is_mqtt_connected = False

def on_control_disconnect(client, userdata, rc, properties=None):
    global is_mqtt_connected
    is_mqtt_connected = False

control_client.on_connect = on_control_connect
control_client.on_disconnect = on_control_disconnect

try:
    if CONTROL_USER and CONTROL_PASS:
        control_client.username_pw_set(CONTROL_USER, CONTROL_PASS)
    control_client.connect(CONTROL_BROKER, CONTROL_PORT, 60)
    control_client.loop_start()
except Exception as e:
    print(f"❌ VPS Control MQTT Error: {e}")

# ==========================================
# AUTH EVENT LOGGING
# ==========================================
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

# ==========================================
# CYCLIC TIMER & ENVIRONMENT CONTROL LOGIC
# ==========================================
def process_cyclic_timer(timer_num, relay_obj):
    prefix = f"Timer{timer_num}"
    t_start_str = str(setpoints.get(f"{prefix} Start", "00:00"))
    t_stop_str  = str(setpoints.get(f"{prefix} Stop", "23:59"))
    try: on_min = float(setpoints.get(f"{prefix} ON Min", 5))
    except: on_min = 5.0
    try: off_min = float(setpoints.get(f"{prefix} OFF Min", 15))
    except: off_min = 15.0

    now_dt = datetime.datetime.now()
    cur_time = now_dt.time()

    try:
        t_start = datetime.datetime.strptime(t_start_str, "%H:%M").time()
        t_stop  = datetime.datetime.strptime(t_stop_str, "%H:%M").time()
    except Exception:
        t_start = datetime.time(0, 0)
        t_stop  = datetime.time(23, 59)

    if t_start <= t_stop:
        in_window = (t_start <= cur_time <= t_stop)
    else:
        in_window = (cur_time >= t_start or cur_time <= t_stop)

    ts = timer_state[timer_num]
    now_sec = time.time()

    if in_window:
        run_sec = on_min * 60.0
        off_sec = off_min * 60.0

        if ts["state"] == "OFF":
            if ts["last"] == 0.0 or (now_sec - ts["last"] >= off_sec):
                ts["state"] = "ON"
                ts["last"] = now_sec
                relay_obj.on()
            else:
                relay_obj.off()
        elif ts["state"] == "ON":
            if now_sec - ts["last"] >= run_sec:
                ts["state"] = "OFF"
                ts["last"] = now_sec
                relay_obj.off()
            else:
                relay_obj.on()
    else:
        if ts["state"] == "ON" or relay_obj.is_active:
            ts["state"] = "OFF"
            ts["last"] = 0.0
            relay_obj.off()

def process_humi_day_night_timer(relay_obj, room_humi=None):
    global humi_logic_active
    d_start = str(setpoints.get("HUMI D_Start", "06:00"))
    d_stop  = str(setpoints.get("HUMI D_Stop", "18:00"))
    n_start = str(setpoints.get("HUMI N_Start", "18:00"))
    n_stop  = str(setpoints.get("HUMI N_Stop", "06:00"))

    now_dt = datetime.datetime.now()
    cur_time = now_dt.time()

    def is_within(s_str, e_str):
        try:
            ts = datetime.datetime.strptime(s_str, "%H:%M").time()
            te = datetime.datetime.strptime(e_str, "%H:%M").time()
            if ts <= te: return (ts <= cur_time <= te)
            else: return (cur_time >= ts or cur_time <= te)
        except Exception:
            return False

    in_day   = is_within(d_start, d_stop)
    in_night = is_within(n_start, n_stop)
    in_window = in_day or in_night

    if in_night and not in_day:
        mode = "NIGHT"
        try: on_min  = float(setpoints.get("HUMI N_ON Min", 5))
        except: on_min = 5.0
        try: off_min = float(setpoints.get("HUMI N_OFF Min", 40))
        except: off_min = 40.0
        try: h_max   = float(setpoints.get("HUMI N_Max", setpoints.get("HUMI MAX", 80.0)))
        except: h_max = 80.0
        try: h_min   = float(setpoints.get("HUMI N_Min", setpoints.get("HUMI MIN", 60.0)))
        except: h_min = 60.0
    else:
        mode = "DAY"
        try: on_min  = float(setpoints.get("HUMI D_ON Min", 10))
        except: on_min = 10.0
        try: off_min = float(setpoints.get("HUMI D_OFF Min", 20))
        except: off_min = 20.0
        try: h_max   = float(setpoints.get("HUMI D_Max", setpoints.get("HUMI MAX", 75.0)))
        except: h_max = 75.0
        try: h_min   = float(setpoints.get("HUMI D_Min", setpoints.get("HUMI MIN", 55.0)))
        except: h_min = 55.0

    ts = timer_state["humi"]
    now_sec = time.time()

    # Humidity Threshold Logic Status
    if room_humi is not None:
        humi_logic_active = (room_humi < h_max)
    else:
        humi_logic_active = True

    # High Humidity Protection Cutoff: If live room humidity is at or above Max Threshold, turn OFF
    if room_humi is not None and room_humi >= h_max:
        ts["state"] = "OFF"
        ts["last"] = now_sec
        relay_obj.off()
        return f"{mode} (CUTOFF ≥{h_max:.0f}%)"

    if in_window:
        run_sec = on_min * 60.0
        off_sec = off_min * 60.0

        if ts["state"] == "OFF":
            if ts["last"] == 0.0 or (now_sec - ts["last"] >= off_sec):
                ts["state"] = "ON"
                ts["last"] = now_sec
        elif ts["state"] == "ON":
            if now_sec - ts["last"] >= run_sec:
                ts["state"] = "OFF"
                ts["last"] = now_sec

        # Single GPIO Pin (GPIO 17) Output Control:
        # Turn ON if and only if BOTH Cycle Timer is ON AND Threshold Logic permits
        if ts["state"] == "ON" and humi_logic_active:
            relay_obj.on()
        else:
            relay_obj.off()
    else:
        ts["state"] = "OFF"
        ts["last"] = 0.0
        relay_obj.off()

    return mode

def control_system(water_data, md02_data):
    warnings = []
    global ec_active, ph_active, temp_active, humi_active, last_ec, last_ph

    now = time.time()
    # 1. WATER SENSOR DOSING LOGIC
    if water_data:
        ec_val = water_data["ec"]
        ph_val = water_data["ph"]

        ec_min = float(setpoints.get("EC MIN", 1200))
        ec_max = float(setpoints.get("EC MAX", 1800))
        ph_low = float(setpoints.get("PH LOW", 5.5))
        ph_high = float(setpoints.get("PH HIGH", 6.5))

        # EC Control
        if not ec_active and ec_val < ec_min:
            if now - last_ec > 300:
                ec_active = True
                relay_ec1.on()
                relay_ec2.on()
                last_ec = now
                warnings.append("⚠ EC LOW – DOSING EC1 & EC2")
        elif ec_active:
            if ec_val >= ec_max or (now - last_ec > 15):
                ec_active = False
                relay_ec1.off()
                relay_ec2.off()
            else:
                warnings.append("⚠ EC DOSING ACTIVE")

        # pH Control
        if not ph_active and ph_val > ph_high:
            if now - last_ph > 300:
                ph_active = True
                relay_ph.on()
                last_ph = now
                warnings.append("⚠ PH HIGH – DOSING PH MINUS")
        elif ph_active:
            if ph_val <= ph_low or (now - last_ph > 10):
                ph_active = False
                relay_ph.off()
            else:
                warnings.append("⚠ PH DOSING ACTIVE")

    # 2. MD02 CLIMATE CONTROL
    if md02_data:
        room_temp = md02_data["room_temp"]

        t_max = float(setpoints.get("TEMP MAX", 28.0))
        t_min = float(setpoints.get("TEMP MIN", 22.0))

        # Temperature Control (Cooling Relay)
        if not temp_active and room_temp >= t_max:
            temp_active = True
            relay_temp.on()
            warnings.append("⚠ TEMP HIGH – COOLING ON")
        elif temp_active:
            if room_temp <= t_min:
                temp_active = False
                relay_temp.off()
            else:
                relay_temp.on()
                warnings.append("⚠ COOLING ACTIVE")

    # 3. HUMIDIFIER DAY/NIGHT CYCLIC TIMER (GPIO 17)
    humi_mode = process_humi_day_night_timer(relay_humi, md02_data["room_humi"] if md02_data else None)
    if relay_humi.is_active:
        warnings.append(f"⚠ HUMIDIFIER ON ({humi_mode})")

    # 4. CYCLIC TIMERS
    process_cyclic_timer(1, relay_timer1)
    process_cyclic_timer(2, relay_timer2)

    return warnings

def manual_stop():
    all_relays_off()
    global ec_active, ph_active, temp_active, humi_active, humi_logic_active
    ec_active = ph_active = temp_active = humi_active = humi_logic_active = False
    for ts in timer_state.values():
        ts["state"] = "OFF"
        ts["last"] = 0.0
    lbl_warn.config(text="🛑 MANUAL STOP ALL RELAYS")

def restart_program():
    manual_stop()
    if water_instrument:
        try: water_instrument.serial.close()
        except: pass
    os.execl(sys.executable, sys.executable, *sys.argv)

# ==========================================
# BLUETOOTH & WIFI PROVISIONING
# ==========================================
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
            raw_names = [name.strip() for name in result.stdout.split('\n') if name.strip()]
            unique_names = sorted(list(set(raw_names)))
            if not unique_names:
                return "No networks found..."
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
    try:
        btctl = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        for c in ["power on\n", "agent NoInputNoOutput\n", "default-agent\n", "discoverable on\n", "pairable on\n"]:
            btctl.stdin.write(c)
        btctl.stdin.flush()
    except Exception: pass

    last_check = 0
    while True:
        now = time.time()
        if now - last_check >= 60:
            try:
                subprocess.run(["bluetoothctl", "discoverable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["bluetoothctl", "pairable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                last_check = now
            except: pass
        try:
            output = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True)
            for line in output.split('\n'):
                if line.startswith('Device '):
                    mac = line.split(" ")[1]
                    os.system(f"sudo bluetoothctl trust {mac} >/dev/null 2>&1")
        except: pass
        time.sleep(5)

def start_bluetooth_server():
    while True:
        server_sock = None
        try:
            os.system("sudo sdptool add --channel=1 SP >/dev/null 2>&1")
            time.sleep(1)
            server_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            server_sock.bind((socket.BDADDR_ANY, 1))
            server_sock.listen(1)
            while True:
                client_sock = None
                try:
                    client_sock, client_info = server_sock.accept()
                    client_sock.send(b"\r\n--- RASPBERRY PI IOT CONFIG ---\r\nCmds: WIFI:SSID:PASS | SCAN | PING\r\n")
                    while True:
                        data = client_sock.recv(1024)
                        if not data: break
                        text = data.decode('utf-8').strip()
                        if text.startswith("WIFI:"):
                            parts = text.split(":")
                            if len(parts) >= 3:
                                resp = set_wifi(parts[1], ":".join(parts[2:]))
                                client_sock.send(f"\r\n{resp}\r\n".encode('utf-8'))
                        elif text.startswith("ID:"):
                            new_id = text.split(":", 1)[1].strip()
                            if new_id:
                                with open(ID_FILE, "w") as f: f.write(new_id)
                                client_sock.send(f"\r\nSUCCESS: ID set to {new_id}. Restarting...\r\n".encode('utf-8'))
                                root.after(2000, restart_program)
                        elif text.upper() == "SCAN":
                            client_sock.send((scan_wifi() + "\r\n").encode('utf-8'))
                        elif text.upper() == "PING":
                            client_sock.send(b"\r\nPONG - System Alive!\r\n")
                except Exception: pass
                finally:
                    if client_sock:
                        try: client_sock.close()
                        except: pass
        except Exception:
            time.sleep(5)
        finally:
            if server_sock:
                try: server_sock.close()
                except: pass

# ==========================================
# OFFLINE LOGGING & SYNC
# ==========================================
LOG_DIR = os.path.join(BASE_DIR, "local_logs")
ACTIVE_LOG_FILE = os.path.join(LOG_DIR, "active.jsonl")
local_log_lock = threading.Lock()
last_local_save_time = 0

COLUMNS = ["timestamp", "temp", "moist", "ec", "ph", "room_temp", "room_humi", "timer1", "timer2"]

def save_local_telemetry(water_data, md02_data):
    global last_local_save_time
    try: connected = is_mqtt_connected and control_client.is_connected()
    except: connected = False

    if connected: return

    cur_time = time.time()
    if cur_time - last_local_save_time < 45: return

    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ts_str = datetime.datetime.now(ist_tz).isoformat()

    row = [
        ts_str,
        water_data.get("temp") if water_data else None,
        water_data.get("moist") if water_data else None,
        water_data.get("ec") if water_data else None,
        water_data.get("ph") if water_data else None,
        md02_data.get("room_temp") if md02_data else None,
        md02_data.get("room_humi") if md02_data else None,
        relay_timer1.is_active,
        relay_timer2.is_active
    ]

    def write_thread():
        with local_log_lock:
            try:
                os.makedirs(LOG_DIR, exist_ok=True)
                header = not os.path.exists(ACTIVE_LOG_FILE) or os.path.getsize(ACTIVE_LOG_FILE) == 0
                with open(ACTIVE_LOG_FILE, "a") as f:
                    if header: f.write(json.dumps(COLUMNS) + "\n")
                    f.write(json.dumps(row) + "\n")
            except Exception as e:
                print(f"Offline log save error: {e}")

    threading.Thread(target=write_thread, daemon=True).start()
    last_local_save_time = cur_time

def sync_offline_data_worker():
    while True:
        try:
            try: connected = is_mqtt_connected and control_client.is_connected()
            except: connected = False

            if connected and os.path.exists(LOG_DIR):
                files = [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl") and f != "active.jsonl"]
                if os.path.exists(ACTIVE_LOG_FILE) and os.path.getsize(ACTIVE_LOG_FILE) > 0:
                    with local_log_lock:
                        rot_name = os.path.join(LOG_DIR, f"log_{int(time.time())}.jsonl")
                        try: os.rename(ACTIVE_LOG_FILE, rot_name)
                        except: pass
                    files = [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl") and f != "active.jsonl"]

                files.sort()
                for fname in files:
                    fpath = os.path.join(LOG_DIR, fname)
                    rows = []
                    with local_log_lock:
                        if os.path.exists(fpath):
                            try:
                                with open(fpath, "r") as f:
                                    first = True
                                    for line in f:
                                        if line.strip():
                                            parsed = json.loads(line.strip())
                                            if first and isinstance(parsed, list) and parsed and parsed[0] == "timestamp":
                                                first = False; continue
                                            rows.append(parsed)
                                            first = False
                            except: pass

                    if not rows:
                        try: os.remove(fpath)
                        except: pass
                        continue

                    batch_payload = []
                    for r in rows:
                        if len(r) >= 7:
                            payload_entry = {
                                "device": DEVICE_NAME,
                                "timestamp": r[0],
                                "temp": r[1],
                                "moist": r[2],
                                "ec": r[3],
                                "ph": r[4],
                                "room_temp": r[5],
                                "room_humi": r[6]
                            }
                            if len(r) >= 9:
                                payload_entry["timer1"] = r[7]
                                payload_entry["timer2"] = r[8]
                            batch_payload.append(payload_entry)
                    if batch_payload:
                        control_client.publish(f"inhydro/{DEVICE_NAME}/telemetry/live", json.dumps(batch_payload), qos=1)
                        os.remove(fpath)
        except Exception: pass
        time.sleep(15)

# ==========================================
# UI INITIALIZATION & STYLING (WHITE THEME)
# ==========================================
root = tk.Tk()
root.update()
root.attributes("-fullscreen", True)
root.configure(bg="#ffffff")
root.bind("<Escape>", lambda e: root.destroy())

FONT_BIG   = ("Arial", 18, "bold")
FONT_MED   = ("Arial", 14, "bold")
FONT_SML   = ("Arial", 11, "bold")
FONT_TINY  = ("Arial", 10)

frame_main = tk.Frame(root, bg="#ffffff")
frame_set  = tk.Frame(root, bg="#ffffff")

def show(frame):
    frame_main.pack_forget()
    frame_set.pack_forget()
    frame.pack(fill="both", expand=True)
    if 'lbl_logo' in globals():
        lbl_logo.lift()

show(frame_main)

# LOGO
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
try:
    logo_img_raw = Image.open(LOGO_PATH).resize((130, 85), Image.LANCZOS)
    logo_img = ImageTk.PhotoImage(logo_img_raw)
    lbl_logo = tk.Label(root, image=logo_img, bg="#ffffff")
    lbl_logo.image = logo_img
    lbl_logo.place(relx=0.98, y=8, anchor="ne")
except Exception:
    lbl_logo = tk.Label(root, text="INHYDRO", fg="#1565c0", bg="#ffffff", font=("Arial", 16, "bold"))
    lbl_logo.place(relx=0.98, y=8, anchor="ne")

# ==========================================
# ==========================================
# MAIN DASHBOARD SCREEN (GRAY #e0e0e0 THEME MATCHING control121.py ROOM 2)
# ==========================================
tk.Label(frame_main, text=f"DEVICE: {DEVICE_NAME.upper()} — CONTROLLER & MONITOR", font=FONT_BIG, fg="#1565c0", bg="#ffffff").pack(pady=(8, 2))

# Pack Footer FIRST at bottom so content_grid auto-fits remaining vertical space
footer_main = tk.Frame(frame_main, bg="#ffffff", height=55)
footer_main.pack(side="bottom", fill="x")
footer_main.pack_propagate(False)

tk.Button(footer_main, text="SETPOINTS", font=FONT_MED, bg="#0284c7", fg="white", width=12, command=lambda: request_setpoints_access()).pack(side="left", padx=15, pady=8)
tk.Button(footer_main, text="STOP", font=FONT_MED, bg="#dc2626", fg="white", width=10, command=manual_stop).pack(side="left", padx=15, pady=8)
tk.Button(footer_main, text="RESTART", font=FONT_MED, bg="#64748b", fg="white", width=10, command=restart_program).pack(side="left", padx=15, pady=8)
tk.Button(footer_main, text="EXIT", font=FONT_MED, bg="#334155", fg="white", width=10, command=root.destroy).pack(side="right", padx=15, pady=8)

content_grid = tk.Frame(frame_main, bg="#e0e0e0")
content_grid.pack(expand=True, fill="both", padx=10, pady=(45, 5))

# Column 1 (LEFT COLUMN - SENSORS DATA)
col_sensors = tk.Frame(content_grid, bg="#e0e0e0")
col_sensors.pack(side="left", fill="both", expand=True, padx=8)

# Section 1: Water Sensor
tk.Label(col_sensors, text="WATER SENSOR", font=("Arial", 12, "bold"), fg="#1565c0", bg="#e0e0e0").pack(anchor="w", pady=(6, 2))

def create_sensor_row(parent, label_text, is_ec=False):
    f = tk.Frame(parent, bg="#e0e0e0")
    f.pack(fill="x", pady=2)
    tk.Label(f, text=label_text, font=FONT_SML, fg="#333333", bg="#e0e0e0", width=12, anchor="w").pack(side="left")
    val_w = 23 if is_ec else 15
    lbl_val = tk.Label(f, text="---", font=("Arial", 13, "bold"), fg="#0d47a1", bg="#e0e0e0", width=val_w, anchor="e")
    lbl_val.pack(side="right")
    return lbl_val

lbl_val_water_temp = create_sensor_row(col_sensors, "Water Temp")
lbl_val_moist      = create_sensor_row(col_sensors, "Moisture")
lbl_val_ec         = create_sensor_row(col_sensors, "EC", is_ec=True)
lbl_val_ph         = create_sensor_row(col_sensors, "pH")

tk.Frame(col_sensors, bg="black", height=2).pack(fill="x", pady=8)

# Section 2: Room Sensor (MD02)
tk.Label(col_sensors, text="ROOM SENSOR", font=("Arial", 12, "bold"), fg="#1565c0", bg="#e0e0e0").pack(anchor="w", pady=(2, 2))

lbl_val_room_temp = create_sensor_row(col_sensors, "Room Temp")
lbl_val_room_humi = create_sensor_row(col_sensors, "Room Humi")

# Warning Banner at bottom of Column 1
lbl_warn = tk.Label(col_sensors, text="", font=("Arial", 10, "bold"), fg="#c62828", bg="#e0e0e0", justify="left")
lbl_warn.pack(pady=10, anchor="w")

# Thick Black Divider Line 1
sep1 = tk.Frame(content_grid, bg="black", width=8)
sep1.pack(side="left", fill="y", pady=10)

# Column 2 (MIDDLE COLUMN - RELAY STATUS)
col_relays = tk.Frame(content_grid, bg="#e0e0e0")
col_relays.pack(side="left", fill="both", expand=True, padx=8)

tk.Label(col_relays, text="RELAY STATUS", font=("Arial", 14, "bold"), fg="#1565c0", bg="#e0e0e0").pack(pady=(6, 4))

labels_relays = {}
relay_items = [
    ("EC1",              "ec1"),
    ("EC2",              "ec2"),
    ("pH",               "ph"),
    ("FAN",              "temp"),
    ("Humidifier",       "humi_logic"),
    ("Humidifier Timer", "humi_timer"),
    ("TIMER 1",          "tmr1"),
    ("TIMER 2",          "tmr2"),
]
for lbl_txt, r_key in relay_items:
    f = tk.Frame(col_relays, bg="#e0e0e0")
    f.pack(fill="x", pady=2)
    tk.Label(f, text=lbl_txt, font=FONT_SML, fg="#333333", bg="#e0e0e0", width=14, anchor="w").pack(side="left")
    lbl_st = tk.Label(f, text="OFF", font=("Arial", 12, "bold"), fg="#c62828", bg="#e0e0e0", anchor="e")
    lbl_st.pack(side="right")
    labels_relays[r_key] = lbl_st

# Thick Black Divider Line 2
sep2 = tk.Frame(content_grid, bg="black", width=8)
sep2.pack(side="left", fill="y", pady=10)

# Column 3 (RIGHT COLUMN - CYCLIC TIMERS)
col_timers = tk.Frame(content_grid, bg="#e0e0e0")
col_timers.pack(side="left", fill="both", expand=True, padx=8)

tk.Label(col_timers, text="CYCLIC TIMERS", font=("Arial", 14, "bold"), fg="#1565c0", bg="#e0e0e0").pack(pady=(6, 4))

labels_timers = {}

def create_timer_widget(parent, t_idx):
    prefix_nospace = f"Timer{t_idx}"
    prefix_space   = f"Timer {t_idx}"
    t_name = setpoints.get(f"{prefix_nospace} Name", setpoints.get(f"{prefix_space} Name", f"TIMER {t_idx}"))

    # Editable Title Header (Matching control121.py)
    lbl_tname = tk.Label(parent, text=str(t_name).upper(), font=("Arial", 12, "bold"), fg="#1565c0", bg="#e0e0e0")
    lbl_tname.pack(pady=(1, 0))
    labels_timers[f"tname_{t_idx}"] = lbl_tname

    sub_lbl_font = ("Arial", 10, "bold")
    sub_val_font = ("Arial", 10, "bold")

    t_sub_labels = {}
    for sub_key, sub_lbl in [("status", "Status"), ("window", "Window"), ("cycle", "Cycle")]:
        f = tk.Frame(parent, bg="white")
        f.pack(fill="x", pady=1)
        tk.Label(f, text=sub_lbl, font=sub_lbl_font, fg="#1565c0", bg="white", width=8, anchor="w").pack(side="left")
        lbl_v = tk.Label(f, text="---", font=sub_val_font, fg="#0f172a", bg="white", anchor="e")
        lbl_v.pack(side="right")
        t_sub_labels[sub_key] = lbl_v

    labels_timers[t_idx] = t_sub_labels

def create_humi_timer_widget(parent):
    h_name = setpoints.get("HUMI Name", "FOGGER TIMER")
    lbl_tname = tk.Label(parent, text=str(h_name).upper(), font=("Arial", 12, "bold"), fg="#1565c0", bg="#e0e0e0")
    lbl_tname.pack(pady=(4, 0))
    labels_timers["tname_humi"] = lbl_tname

    sub_lbl_font = ("Arial", 10, "bold")
    sub_val_font = ("Arial", 10, "bold")

    t_sub_labels = {}
    for sub_key, sub_lbl in [("status", "Status"), ("day_cycle", "Day Cycle"), ("night_cycle", "Night Cycle")]:
        f = tk.Frame(parent, bg="white")
        f.pack(fill="x", pady=1)
        tk.Label(f, text=sub_lbl, font=sub_lbl_font, fg="#1565c0", bg="white", width=10, anchor="w").pack(side="left")
        lbl_v = tk.Label(f, text="---", font=sub_val_font, fg="#0f172a", bg="white", anchor="e")
        lbl_v.pack(side="right")
        t_sub_labels[sub_key] = lbl_v

    labels_timers["humi"] = t_sub_labels

create_timer_widget(col_timers, 1)
create_timer_widget(col_timers, 2)
create_humi_timer_widget(col_timers)

# ==========================================
# PIN AUTHENTICATION MODAL (WHITE THEME)
# ==========================================
def request_setpoints_access():
    win = tk.Toplevel(root)
    win.title("Security Authentication")
    win.configure(bg="#ffffff")
    win.focus_force()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    win.geometry(f"{sw}x{sh}+0+0")
    win.attributes("-fullscreen", True)
    win.grab_set()

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
    tk.Label(title_sub_frame, text="Select user and enter authorization PIN to unlock setpoints:", font=("Arial", 10), fg="#64748b", bg="#ffffff").pack(anchor="w", pady=2)

    if os.path.exists(LOGO_PATH):
        try:
            logo_img_modal = ImageTk.PhotoImage(Image.open(LOGO_PATH).resize((120, 75), Image.LANCZOS))
            win.logo_img_modal = logo_img_modal
            tk.Label(header_frame, image=logo_img_modal, bg="#ffffff").pack(side="right", padx=10)
        except Exception: pass

    # TWO USER SELECTION BUTTONS ONLY
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
        pop.focus_force()
        pop.geometry(f"{sw}x{sh}+0+0")
        pop.attributes("-fullscreen", True)
        pop.grab_set()

        name_entered = setpoints.get(f"USER {selected_user} Name", f"Operator {selected_user}")
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
            setpoints[f"USER {selected_user} Name"] = name_entered.strip()
            save_setpoints()
            user_btns[selected_user - 1].config(text=name_entered.strip())
            pop.destroy()

        kb_frame = tk.Frame(container, bg="#ffffff")
        kb_frame.pack(pady=10)
        for ri, row_k in enumerate([list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL:"), list("ZXCVBNM._ ")]):
            for ci, ch in enumerate(row_k):
                lbl = ch if ch != ' ' else 'SPC'
                tk.Button(kb_frame, text=lbl, font=("Arial", 11, "bold"), width=4, height=1, bg="#f1f5f9", fg="#0f172a", activebackground="#0284c7", activeforeground="white",
                          command=lambda x=ch: char_press(x)).grid(row=ri, column=ci, padx=2, pady=2)

        action_frame = tk.Frame(container, bg="#ffffff")
        action_frame.pack(fill="x", pady=15)
        tk.Button(action_frame, text="CANCEL", font=("Arial", 10, "bold"), bg="#64748b", fg="white", width=8, height=2, command=pop.destroy).pack(side="left", padx=10)
        tk.Button(action_frame, text="CLEAR", font=("Arial", 10, "bold"), bg="#dc2626", fg="white", width=8, height=2, command=char_clear).pack(side="left", padx=10)
        tk.Button(action_frame, text="BACK", font=("Arial", 10, "bold"), bg="#f97316", fg="white", width=10, height=2, command=char_back).pack(side="left", padx=10)
        tk.Button(action_frame, text="SAVE", font=("Arial", 10, "bold"), bg="#0284c7", fg="white", width=10, height=2, command=char_save).pack(side="right", padx=10)

    def change_pin_popup():
        nonlocal selected_user
        pop = tk.Toplevel(win)
        pop.title("Change Operator PIN")
        pop.configure(bg="#ffffff")
        pop.focus_force()
        pop.geometry(f"{sw}x{sh}+0+0")
        pop.attributes("-fullscreen", True)
        pop.grab_set()

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
            correct_old = str(setpoints.get(f"USER {selected_user} PASSWORD", f"{selected_user}{selected_user}{selected_user}{selected_user}"))
            if step == 1:
                if input_value != correct_old:
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
                setpoints[f"USER {selected_user} PASSWORD"] = new_pin
                save_setpoints()
                pop.destroy()

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
        tk.Button(action_frame, text="CANCEL", font=("Arial", 10, "bold"), bg="#64748b", fg="white", width=12, height=2, command=pop.destroy).pack(side="left", padx=15)
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
    u1_name = setpoints.get("USER 1 Name", "Operator 1")
    btn_u1 = tk.Button(user_frame, text=u1_name, font=("Arial", 11, "bold"), width=16, height=1, bd=1)
    btn_u1.config(command=lambda: select_user(1))
    btn_u1.pack(side="left", padx=10)
    user_btns.append(btn_u1)

    # User 2 Button
    u2_name = setpoints.get("USER 2 Name", "Operator 2")
    btn_u2 = tk.Button(user_frame, text=u2_name, font=("Arial", 11, "bold"), width=16, height=1, bd=1)
    btn_u2.config(command=lambda: select_user(2))
    btn_u2.pack(side="left", padx=10)
    user_btns.append(btn_u2)

    # Operator Sub-actions
    ops_frame = tk.Frame(main_container, bg="#ffffff")
    ops_frame.pack(pady=5)
    tk.Button(ops_frame, text="✏️ RENAME USER", font=("Arial", 9, "bold"), bg="#64748b", fg="white", width=14, height=1, bd=1, relief="raised", command=rename_user_popup).pack(side="left", padx=5)
    tk.Button(ops_frame, text="🔒 CHANGE PIN", font=("Arial", 9, "bold"), bg="#64748b", fg="white", width=14, height=1, bd=1, relief="raised", command=change_pin_popup).pack(side="left", padx=5)

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
        user_name = setpoints.get(f"USER {selected_user} Name", f"Operator {selected_user}")
        correct_password = str(setpoints.get(f"USER {selected_user} PASSWORD", f"{selected_user}{selected_user}{selected_user}{selected_user}"))
        if password_entered == correct_password:
            log_auth_event(selected_user, user_name, "SUCCESS")
            win.destroy()
            show(frame_set)
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
    tk.Button(action_frame, text="CANCEL", font=("Arial", 10, "bold"), bg="#64748b", fg="white", width=12, height=2, bd=1, relief="raised", command=win.destroy).pack(side="left", padx=15)
    tk.Button(action_frame, text="AUTHENTICATE", font=("Arial", 10, "bold"), bg="#0284c7", fg="white", width=14, height=2, bd=1, relief="raised", command=kp_confirm).pack(side="right", padx=15)

    select_user(1)

# ==========================================
# SETPOINTS PAGE UI (FULL-LENGTH + WHITE THEME)
# ==========================================
tk.Label(frame_set, text="SYSTEM SETPOINTS CONFIGURATION", font=FONT_BIG, fg="#1565c0", bg="#ffffff").pack(pady=(8, 2))

# Setpoint Footer (Packed FIRST at side="bottom" like control121.py)
footer_set = tk.Frame(frame_set, bg="#ffffff", height=50)
footer_set.pack(side="bottom", fill="x")
footer_set.pack_propagate(False)

tk.Button(footer_set, text="SAVE & RETURN", font=FONT_MED, bg="#0284c7", fg="white", width=18,
          command=lambda: (save_setpoints(), show(frame_main))).pack(pady=8)

sp_container = tk.Frame(frame_set, bg="#ffffff")
sp_container.pack(fill="both", expand=True, padx=15, pady=(45, 2))

left_sp_pane = tk.Frame(sp_container, bg="#ffffff")
left_sp_pane.pack(side="left", fill="both", expand=True, padx=4)

right_sp_pane = tk.Frame(sp_container, bg="#ffffff")
right_sp_pane.pack(side="right", fill="both", expand=True, padx=4)

sp_labels = {}
sp_selected_key = None
sp_entered_value = ""

def make_sp_cell(parent, key, label_text=None, width_lbl=10):
    if key not in setpoints: return
    lbl_txt = label_text if label_text else key
    cell = tk.Frame(parent, bg="#ffffff")
    
    tk.Label(cell, text=lbl_txt, font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", anchor="w", width=width_lbl).pack(side="left", padx=2)
    val_lbl = tk.Label(cell, text=str(setpoints[key]), font=("Arial", 10, "bold"), fg="#e65100", bg="#f1f5f9", width=10, anchor="center", relief="sunken", bd=1)
    val_lbl.pack(side="left", padx=4)
    
    btn = tk.Button(cell, text="EDIT", font=("Arial", 9, "bold"), bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="groove",
                    command=lambda k=key: open_keypad_sp(k))
    btn.pack(side="left", padx=2)
    sp_labels[key] = val_lbl
    return cell

# Card 1 (LEFT PANE): Nutrients & pH
card_dosing = tk.LabelFrame(left_sp_pane, text=" NUTRIENTS & PH ", font=FONT_MED, fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
card_dosing.pack(fill="x", pady=4, padx=4)
grid_dosing = tk.Frame(card_dosing, bg="#ffffff")
grid_dosing.pack(pady=4, padx=6, fill="x")
make_sp_cell(grid_dosing, "EC MIN", "EC Min:").grid(row=0, column=0, padx=4, pady=4)
make_sp_cell(grid_dosing, "EC MAX", "EC Max:").grid(row=0, column=1, padx=4, pady=4)
make_sp_cell(grid_dosing, "PH LOW", "pH Low:").grid(row=1, column=0, padx=4, pady=4)
make_sp_cell(grid_dosing, "PH HIGH", "pH High:").grid(row=1, column=1, padx=4, pady=4)

# Card 2 (LEFT PANE): Humidifier Day/Night Cyclic Timer & Thresholds (Side-by-Side DAY / NIGHT Table)
card_humi_sp = tk.LabelFrame(left_sp_pane, text=f" {str(setpoints.get('HUMI Name', 'HUMIDIFIER')).upper()} DAY/NIGHT TIMER ", font=FONT_MED, fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
card_humi_sp.pack(fill="x", pady=4, padx=4)

# Side-by-Side Table Header
humi_hdr = tk.Frame(card_humi_sp, bg="#f1f5f9")
humi_hdr.pack(fill="x", pady=2, padx=4)
tk.Label(humi_hdr, text="Setting", font=("Arial", 9, "bold"), fg="#64748b", bg="#f1f5f9", width=10, anchor="w").pack(side="left", padx=4)
tk.Label(humi_hdr, text="DAY WINDOW", font=("Arial", 9, "bold"), fg="#1565c0", bg="#f1f5f9", width=16, anchor="center").pack(side="left", expand=True)
tk.Label(humi_hdr, text="NIGHT WINDOW", font=("Arial", 9, "bold"), fg="#1565c0", bg="#f1f5f9", width=16, anchor="center").pack(side="left", expand=True)

# Row 0: Timer Name (Editable Alphanumeric Keypad)
r_name = tk.Frame(card_humi_sp, bg="#ffffff")
r_name.pack(fill="x", pady=2, padx=4)
tk.Label(r_name, text="Timer Name", font=("Arial", 9, "bold"), fg="#0f172a", bg="#ffffff", width=10, anchor="w").pack(side="left", padx=4)
v_name = tk.Label(r_name, text=str(setpoints.get("HUMI Name", "HUMIDIFIER")), font=("Arial", 10, "bold"), fg="#0f172a", bg="#f1f5f9", anchor="center", relief="sunken", bd=1)
v_name.pack(side="left", expand=True, fill="x", padx=4)
btn_name = tk.Button(r_name, text="EDIT", font=("Arial", 8, "bold"), bg="#0284c7", fg="white", bd=1, relief="groove",
                     command=lambda: open_keypad_sp("HUMI Name"))
btn_name.pack(side="right", padx=2)
sp_labels["HUMI Name"] = v_name

humi_rows = [
    ("Start Time", "HUMI D_Start",  "HUMI N_Start"),
    ("Stop Time",  "HUMI D_Stop",   "HUMI N_Stop"),
    ("ON Min",     "HUMI D_ON Min",  "HUMI N_ON Min"),
    ("OFF Min",    "HUMI D_OFF Min", "HUMI N_OFF Min"),
    ("Max %",      "HUMI D_Max",     "HUMI N_Max"),
    ("Min %",      "HUMI D_Min",     "HUMI N_Min"),
]

for r_lbl, d_k, n_k in humi_rows:
    r_f = tk.Frame(card_humi_sp, bg="#ffffff")
    r_f.pack(fill="x", pady=1, padx=4)
    tk.Label(r_f, text=r_lbl, font=("Arial", 9, "bold"), fg="#0f172a", bg="#ffffff", width=10, anchor="w").pack(side="left", padx=4)

    # DAY cell
    c_day = tk.Frame(r_f, bg="#ffffff")
    c_day.pack(side="left", expand=True, fill="x")
    v_d = tk.Label(c_day, text=str(setpoints.get(d_k, "")), font=("Arial", 9, "bold"), fg="#e65100", bg="#f1f5f9", width=7, anchor="center", relief="sunken", bd=1)
    v_d.pack(side="left", expand=True)
    tk.Button(c_day, text="EDIT", font=("Arial", 8, "bold"), bg="#0284c7", fg="white", bd=1, relief="groove",
              command=lambda k=d_k: open_keypad_sp(k)).pack(side="right", padx=1)
    sp_labels[d_k] = v_d

    # NIGHT cell
    c_night = tk.Frame(r_f, bg="#ffffff")
    c_night.pack(side="left", expand=True, fill="x")
    v_n = tk.Label(c_night, text=str(setpoints.get(n_k, "")), font=("Arial", 9, "bold"), fg="#e65100", bg="#f1f5f9", width=7, anchor="center", relief="sunken", bd=1)
    v_n.pack(side="left", expand=True)
    tk.Button(c_night, text="EDIT", font=("Arial", 8, "bold"), bg="#0284c7", fg="white", bd=1, relief="groove",
              command=lambda k=n_k: open_keypad_sp(k)).pack(side="right", padx=1)
    sp_labels[n_k] = v_n

# Card 3 (RIGHT PANE): Climate Control (MD02 Temp Only)
card_climate_sp = tk.LabelFrame(right_sp_pane, text=" CLIMATE CONTROL ", font=FONT_MED, fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
card_climate_sp.pack(fill="x", pady=4, padx=4)
grid_climate_sp = tk.Frame(card_climate_sp, bg="#ffffff")
grid_climate_sp.pack(pady=4, padx=6, fill="x")
make_sp_cell(grid_climate_sp, "TEMP MAX", "Temp Max:").grid(row=0, column=0, padx=4, pady=4)
make_sp_cell(grid_climate_sp, "TEMP MIN", "Temp Min:").grid(row=0, column=1, padx=4, pady=4)

# Card 4 (RIGHT PANE): 2 Cyclic Timers Configuration
card_timers_sp = tk.LabelFrame(right_sp_pane, text=" CYCLIC TIMERS  ", font=FONT_MED, fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
card_timers_sp.pack(fill="x", pady=4, padx=4)

cols = [
    {"name": "Timer 1", "keys": {"Name": "Timer1 Name", "Start": "Timer1 Start", "Stop": "Timer1 Stop", "ON Min": "Timer1 ON Min", "OFF Min": "Timer1 OFF Min"}},
    {"name": "Timer 2", "keys": {"Name": "Timer2 Name", "Start": "Timer2 Start", "Stop": "Timer2 Stop", "ON Min": "Timer2 ON Min", "OFF Min": "Timer2 OFF Min"}}
]

header_frame = tk.Frame(card_timers_sp, bg="#f1f5f9")
header_frame.pack(fill="x", pady=3, padx=4)
tk.Label(header_frame, text="Setting", font=("Arial", 10, "bold"), fg="#64748b", bg="#f1f5f9", width=10, anchor="w").pack(side="left", padx=4)
for col in cols:
    tk.Label(header_frame, text=col["name"], font=("Arial", 10, "bold"), fg="#1565c0", bg="#f1f5f9", width=16, anchor="center").pack(side="left", expand=True)

row_keys = [("Name", "Name:"), ("Start", "Start:"), ("Stop", "Stop:"), ("ON Min", "ON Min:"), ("OFF Min", "OFF Min:")]

for r_key, r_lbl in row_keys:
    r_frame = tk.Frame(card_timers_sp, bg="#ffffff")
    r_frame.pack(fill="x", pady=2, padx=4)
    tk.Label(r_frame, text=r_lbl, font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", width=10, anchor="w").pack(side="left", padx=4)
    for col in cols:
        col_frame = tk.Frame(r_frame, bg="#ffffff")
        col_frame.pack(side="left", expand=True, fill="x")
        full_key = col["keys"][r_key]
        if full_key in setpoints:
            val_lbl = tk.Label(col_frame, text=str(setpoints[full_key]), font=("Arial", 10, "bold"), fg="#e65100" if r_key != "Name" else "#0f172a", bg="#f1f5f9", width=8, anchor="center", relief="sunken", bd=1)
            val_lbl.pack(side="left", expand=True)
            btn = tk.Button(col_frame, text="EDIT", font=("Arial", 8, "bold"), bg="#0284c7", fg="white", bd=1, relief="groove",
                            command=lambda k=full_key: open_keypad_sp(k))
            btn.pack(side="right", padx=2)
            sp_labels[full_key] = val_lbl

# Keypad Modal Frame for Setpoints Page
kp_sp_frame   = tk.Frame(frame_set, bg="#ffffff", bd=2, relief="solid")
kp_sp_title   = tk.Label(kp_sp_frame, font=FONT_MED, fg="#1565c0", bg="#ffffff")
kp_sp_title.pack(pady=4)
kp_sp_display = tk.Label(kp_sp_frame, font=("Arial", 18, "bold"), fg="#2e7d32", bg="#f1f5f9", width=16, relief="sunken")
kp_sp_display.pack(pady=4)
kp_sp_buttons = tk.Frame(kp_sp_frame, bg="#ffffff")
kp_sp_buttons.pack(pady=5)
kp_sp_actions = tk.Frame(kp_sp_frame, bg="#ffffff")
kp_sp_actions.pack(pady=5)

def kp_sp_press(v):
    global sp_entered_value
    sp_entered_value += str(v)
    kp_sp_display.config(text=sp_entered_value)

def kp_sp_clear():
    global sp_entered_value
    sp_entered_value = ""
    kp_sp_display.config(text="")

def kp_sp_back():
    global sp_entered_value
    sp_entered_value = sp_entered_value[:-1]
    kp_sp_display.config(text=sp_entered_value)

def kp_sp_confirm():
    global sp_entered_value
    try:
        if sp_selected_key.endswith("Name"):
            val = str(sp_entered_value).strip()
        elif ":" in str(sp_entered_value):
            val = str(sp_entered_value).strip()
            datetime.datetime.strptime(val, "%H:%M")
        else:
            val = float(sp_entered_value)
        setpoints[sp_selected_key] = val
        save_setpoints()
        sp_labels[sp_selected_key].config(text=str(val))
        kp_sp_frame.pack_forget()
        sp_container.pack(fill="both", expand=True, padx=15, pady=(45, 2))
    except Exception:
        kp_sp_display.config(text="INVALID INPUT")

def kp_sp_cancel():
    kp_sp_frame.pack_forget()
    sp_container.pack(fill="both", expand=True, padx=15, pady=(45, 2))

def open_keypad_sp(key):
    global sp_selected_key, sp_entered_value
    sp_selected_key = key
    sp_entered_value = ""
    kp_sp_display.config(text="")
    kp_sp_title.config(text=f"Editing {key}")
    for w in kp_sp_buttons.winfo_children(): w.destroy()
    for w in kp_sp_actions.winfo_children(): w.destroy()

    if key.endswith("Name"):
        for ri, row_k in enumerate([list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL:"), list("ZXCVBNM._ ")]):
            for ci, ch in enumerate(row_k):
                tk.Button(kp_sp_buttons, text=ch if ch!=' ' else 'SPC', font=("Arial", 11, "bold"), width=3, bg="#f1f5f9", fg="#0f172a",
                          command=lambda x=ch: kp_sp_press(x)).grid(row=ri, column=ci, padx=2, pady=2)
        w_btn = 6
    else:
        for text, ri, ci in [('1',0,0),('2',0,1),('3',0,2),('4',1,0),('5',1,1),('6',1,2),
                            ('7',2,0),('8',2,1),('9',2,2),('.',3,0),('0',3,1),(':',3,2)]:
            tk.Button(kp_sp_buttons, text=text, font=FONT_MED, width=4, bg="#f1f5f9", fg="#0f172a",
                      command=lambda x=text: kp_sp_press(x)).grid(row=ri, column=ci, padx=3, pady=3)
        w_btn = 4

    for txt, bg, fg, cmd in [("DEL", "#f97316", "white", kp_sp_back), ("CLR", "#dc2626", "white", kp_sp_clear),
                             ("CONFIRM", "#0284c7", "white", kp_sp_confirm), ("CANCEL", "#64748b", "white", kp_sp_cancel)]:
        tk.Button(kp_sp_actions, text=txt, font=("Arial", 10, "bold"), bg=bg, fg=fg, width=w_btn+2, command=cmd).pack(side="left", padx=4)

    sp_container.pack_forget()
    kp_sp_frame.pack(pady=20)



# ==========================================
# MAIN UPDATE LOOP
# ==========================================
def update():
    water_data = read_water_sensor()
    md02_data  = read_md02_sensor()

    warnings = control_system(water_data, md02_data)

    # 1. Update Water Sensor Labels
    if water_data:
        tds = water_data['ec'] * 500
        lbl_val_water_temp.config(text=f"{water_data['temp']} °C", fg="#0d47a1")
        lbl_val_moist.config(text=f"{water_data['moist']} %", fg="#0d47a1")
        lbl_val_ec.config(text=f"{water_data['ec']:.2f} mS/cm ({tds:.0f} ppm)", fg="#0d47a1")
        lbl_val_ph.config(text=f"{water_data['ph']:.2f}", fg="#0d47a1")
    else:
        lbl_val_water_temp.config(text="ERROR", fg="#c62828")
        lbl_val_moist.config(text="ERROR", fg="#c62828")
        lbl_val_ec.config(text="ERROR", fg="#c62828")
        lbl_val_ph.config(text="ERROR", fg="#c62828")

    # 2. Update Room (MD02) Sensor Labels
    if md02_data:
        lbl_val_room_temp.config(text=f"{md02_data['room_temp']} °C", fg="#0d47a1")
        lbl_val_room_humi.config(text=f"{md02_data['room_humi']} %", fg="#0d47a1")
    else:
        lbl_val_room_temp.config(text="ERROR", fg="#c62828")
        lbl_val_room_humi.config(text="ERROR", fg="#c62828")

    # 3. Update Relay Status Labels
    relay_states = {
        "ec1": relay_ec1.is_active,
        "ec2": relay_ec2.is_active,
        "ph": relay_ph.is_active,
        "temp": relay_temp.is_active,
        "humi_logic": humi_logic_active,
        "humi_timer": (timer_state.get("humi", {}).get("state") == "ON"),
        "tmr1": relay_timer1.is_active,
        "tmr2": relay_timer2.is_active,
    }
    for r_key, is_on in relay_states.items():
        lbl_st = labels_relays.get(r_key)
        if lbl_st:
            if is_on:
                lbl_st.config(text="ON", fg="#2e7d32")
            else:
                lbl_st.config(text="OFF", fg="#c62828")

    # 4. Update Cyclic Timers Widgets (Matching control121.py)
    for t_idx in [1, 2]:
        prefix_nospace = f"Timer{t_idx}"
        prefix_space   = f"Timer {t_idx}"

        # Editable Name Header
        t_name = setpoints.get(f"{prefix_nospace} Name", setpoints.get(f"{prefix_space} Name", f"TIMER {t_idx}"))
        lbl_tname = labels_timers.get(f"tname_{t_idx}")
        if lbl_tname:
            lbl_tname.config(text=str(t_name).upper())

        # Operating Window (Start – Stop)
        t_start = setpoints.get(f"{prefix_nospace} Start", setpoints.get(f"{prefix_space} Start", "06:00"))
        t_stop  = setpoints.get(f"{prefix_nospace} Stop",  setpoints.get(f"{prefix_space} Stop",  "18:00"))
        window_str = f"{t_start} – {t_stop}"

        # ON Min / OFF Min Cycle (In MINUTES matching control121.py)
        try: on_min = int(float(setpoints.get(f"{prefix_nospace} ON Min", setpoints.get(f"{prefix_space} ON Min", 5))))
        except: on_min = 5
        try: off_min = int(float(setpoints.get(f"{prefix_nospace} OFF Min", setpoints.get(f"{prefix_space} OFF Min", 15))))
        except: off_min = 15

        cycle_str = f"{on_min}m ON / {off_min}m OFF"

        # Relay Status (ON / OFF with state)
        relay_obj = relay_timer1 if t_idx == 1 else relay_timer2
        t_st = timer_state.get(t_idx, {"state": "OFF"})
        state_str = t_st.get("state", "OFF")
        is_active = relay_obj.is_active

        if is_active or state_str == "ON":
            status_str = f"ON ({state_str})"
            status_fg = "#16a34a"
        else:
            status_str = f"OFF ({state_str})"
            status_fg = "#dc2626"

        t_spec = labels_timers.get(t_idx)
        if t_spec:
            t_spec["status"].config(text=status_str, fg=status_fg)
            t_spec["window"].config(text=window_str, fg="#0f172a")
            t_spec["cycle"].config(text=cycle_str, fg="#0f172a")

    # 5. Update Humidifier Day/Night Timer Widget
    lbl_hname = labels_timers.get("tname_humi")
    if lbl_hname:
        lbl_hname.config(text=str(setpoints.get("HUMI Name", "HUMIDIFIER")).upper())

    h_spec = labels_timers.get("humi")
    if h_spec:
        d_str = f"{setpoints.get('HUMI D_ON Min',10)}m/{setpoints.get('HUMI D_OFF Min',20)}m ({setpoints.get('HUMI D_Start','06:00')}-{setpoints.get('HUMI D_Stop','18:00')})"
        n_str = f"{setpoints.get('HUMI N_ON Min',5)}m/{setpoints.get('HUMI N_OFF Min',40)}m ({setpoints.get('HUMI N_Start','18:00')}-{setpoints.get('HUMI N_Stop','06:00')})"

        is_active = relay_humi.is_active
        t_st = timer_state.get("humi", {"state": "OFF"})
        st_val = t_st.get("state", "OFF")

        if is_active:
            status_str = f"ON ({st_val})"
            status_fg = "#2e7d32"
        else:
            status_str = f"OFF ({st_val})"
            status_fg = "#c62828"

        h_spec["status"].config(text=status_str, fg=status_fg)
        h_spec["day_cycle"].config(text=d_str, fg="#0f172a")
        h_spec["night_cycle"].config(text=n_str, fg="#0f172a")

    lbl_warn.config(text="\n".join(warnings))

    # Live Cloud Telemetry Sync via VPS Mosquitto Broker
    try:
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ts_str = datetime.datetime.now(ist_tz).isoformat()
        payload = {
            "device": DEVICE_NAME,
            "timestamp": ts_str,
            "temp": water_data.get("temp") if water_data else None,
            "moist": water_data.get("moist") if water_data else None,
            "ec": water_data.get("ec") if water_data else None,
            "ph": water_data.get("ph") if water_data else None,
            "room_temp": md02_data.get("room_temp") if md02_data else None,
            "room_humi": md02_data.get("room_humi") if md02_data else None,
            "timer1": relay_timer1.is_active,
            "timer2": relay_timer2.is_active,
            "relay_temp": relay_temp.is_active,
            "relay_humi": relay_humi.is_active
        }
        control_client.publish(f"inhydro/{DEVICE_NAME}/telemetry/live", json.dumps(payload), retain=False)
    except: pass

    # Save offline log if disconnected
    save_local_telemetry(water_data, md02_data)

    root.after(2000, update)

# ==========================================
# MAIN APPLICATION THREADS & ENTRY POINT
# ==========================================
def main():
    try:
        t_trust = threading.Thread(target=auto_trust_devices, daemon=True)
        t_trust.start()
    except Exception as e:
        print(f"Failed to start auto-trust thread: {e}")

    try:
        t_bt = threading.Thread(target=start_bluetooth_server, daemon=True)
        t_bt.start()
        print("✅ Native Bluetooth Setup Server started")
    except Exception as e:
        print(f"Failed to start Bluetooth thread: {e}")

    try:
        t_sync = threading.Thread(target=sync_offline_data_worker, daemon=True)
        t_sync.start()
        print("✅ Offline Telemetry Sync Worker started")
    except Exception as e:
        print(f"Failed to start Offline Sync thread: {e}")

    update()
    root.mainloop()

if __name__ == "__main__":
    main()

