import os, sys, json, time, datetime, atexit, socket
import subprocess, threading
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import font
import minimalmodbus
import serial
import paho.mqtt.client as mqtt

# ==============================================================================
# GPIO BACKEND SETUP (Supports Pi 5, Pi 4, Rock Pi, and Mock failover)
# ==============================================================================
try:
    from gpiozero import OutputDevice, Device
    gpio_initialized = False

    # 1. Try LGPIO (Raspberry Pi 5 / Debian Bookworm standard)
    try:
        from gpiozero.pins.lgpio import LGPIOFactory
        Device.pin_factory = LGPIOFactory()
        print("📌 GPIO Backend Active: LGPIOFactory (Raspberry Pi 5 / Debian Bookworm)")
        gpio_initialized = True
    except Exception:
        pass

    # 2. Try RPi.GPIO (Raspberry Pi 4 / Pi 3 / Bullseye standard)
    if not gpio_initialized:
        try:
            from gpiozero.pins.rpigpio import RPiGPIOFactory
            Device.pin_factory = RPiGPIOFactory()
            print("📌 GPIO Backend Active: RPiGPIOFactory (Raspberry Pi 4 / Pi 3)")
            gpio_initialized = True
        except Exception:
            pass

    # 3. Try Native direct GPIO driver
    if not gpio_initialized:
        try:
            from gpiozero.pins.native import NativeFactory
            Device.pin_factory = NativeFactory()
            print("📌 GPIO Backend Active: NativeFactory (Direct Hardware GPIO)")
            gpio_initialized = True
        except Exception:
            pass

    # 4. Try pigpio daemon (if pigpiod service is running)
    if not gpio_initialized:
        try:
            from gpiozero.pins.pigpio import PiGPIOFactory
            Device.pin_factory = PiGPIOFactory()
            print("📌 GPIO Backend Active: PiGPIOFactory (pigpiod Daemon)")
            gpio_initialized = True
        except Exception:
            pass

    # 5. Fallback for non-Pi / Laptop / Development x86 environment
    if not gpio_initialized:
        try:
            from gpiozero.pins.mock import MockFactory
            Device.pin_factory = MockFactory()
            print("⚠️ Running on PC/Laptop (x86 Hardware) -> Physical GPIO unavailable. Using MockFactory.")
        except Exception as e:
            print("Notice: GPIO pin factory initialization fallback:", e)

except ImportError:
    print("⚠️ gpiozero not installed. Running with simulated mock GPIO.")
    class OutputDevice:
        def __init__(self, pin, active_high=False, initial_value=False):
            self.pin = pin
            self.active_high = active_high
            self._state = initial_value
        @property
        def is_active(self):
            return self._state
        def on(self):
            self._state = True
            print(f"⚡ [MOCK RELAY Pin {self.pin}] -> ON")
        def off(self):
            self._state = False
            print(f"⚪ [MOCK RELAY Pin {self.pin}] -> OFF")
        def close(self):
            pass
    class Device:
        pin_factory = None

# ==============================================================================
# DEVICE IDENTITY & CONFIGURATION
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                val = f.read().strip()
                if val:
                    return val
        except Exception:
            pass
    return "system2"

DEVICE_NAME = get_device_id()
print(f"🚀 Device Identity Loaded: {DEVICE_NAME}")

SETPOINT_FILE = os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}.json")
print(f"📄 Using config: {SETPOINT_FILE}")

# Remove legacy config to prevent sync conflicts
OLD_FILE = os.path.join(BASE_DIR, "setpoints.json")
if os.path.exists(OLD_FILE):
    try:
        os.remove(OLD_FILE)
        print("🗑️ Removed legacy setpoints.json to ensure dynamic sync...")
    except Exception:
        pass

# ==============================================================================
# RELAY HARDWARE (ACTIVE LOW)
# ==============================================================================
# Dosing Relays
relay_ec1 = OutputDevice(22, active_high=False, initial_value=False)
relay_ec2 = OutputDevice(23, active_high=False, initial_value=False)
relay_ph  = OutputDevice(24, active_high=False, initial_value=False)

# CYCLIC TIMER RELAYS (Hardcoded GPIO Pins 5, 6, 13, 19)
timer_relay_1 = OutputDevice(5, active_high=False, initial_value=False)
timer_relay_2 = OutputDevice(6, active_high=False, initial_value=False)
timer_relay_3 = OutputDevice(13, active_high=False, initial_value=False)
timer_relay_4 = OutputDevice(19, active_high=False, initial_value=False)
timer_relays = [timer_relay_1, timer_relay_2, timer_relay_3, timer_relay_4]

def all_relays_off():
    for r in [relay_ec1, relay_ec2, relay_ph, timer_relay_1, timer_relay_2, timer_relay_3, timer_relay_4]:
        try:
            r.off()
        except Exception:
            pass

all_relays_off()

# Control state flags
ec_active = False
ph_active = False
last_ec_dose_time = 0.0
last_ph_dose_time = 0.0
last_ec = 0.0
last_ph = 0.0

# ==============================================================================
# SETPOINTS (WITH FULL CYCLIC TIMERS CONFIG)
# ==============================================================================
setpoints = {
    "EC MIN": 1200,
    "EC MAX": 1800,
    "PH LOW": 5.8,
    "PH HIGH": 6.5,
    "DOSE ON SEC": 5,
    "DOSE OFF SEC": 20,
    "Timer1 Name": "TIMER 1",
    "Timer1 Start": "10:00",
    "Timer1 Stop": "17:00",
    "Timer1 ON Min": 15,
    "Timer1 OFF Min": 30,
    "Timer2 Name": "TIMER 2",
    "Timer2 Start": "10:00",
    "Timer2 Stop": "17:00",
    "Timer2 ON Min": 15,
    "Timer2 OFF Min": 30,
    "Timer3 Name": "TIMER 3",
    "Timer3 Start": "10:00",
    "Timer3 Stop": "17:00",
    "Timer3 ON Min": 15,
    "Timer3 OFF Min": 30,
    "PORT": 1883
}

def load_setpoints():
    global setpoints
    if os.path.exists(SETPOINT_FILE):
        try:
            with open(SETPOINT_FILE, "r") as f:
                loaded = json.load(f)
                setpoints.update(loaded)
            print("✅ Configuration loaded from disk")
        except Exception as e:
            print(f"⚠️ Error reading setpoints: {e}")

load_setpoints()

def save_setpoints():
    try:
        with open(SETPOINT_FILE, "w") as f:
            json.dump(setpoints, f, indent=4)
        if 'control_client' in globals() and is_mqtt_connected:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
            print("📤 Pushed current setpoints to cloud.")
    except Exception as e:
        print(f"⚠️ Error saving setpoints: {e}")

# ==============================================================================
# CYCLIC TIMER LOGIC
# ==============================================================================
timer_cycle_state = ["OFF", "OFF", "OFF"]
timer_last_switch = [0.0, 0.0, 0.0]

def is_within_time_window(start_str, stop_str):
    now = datetime.datetime.now().time()
    try:
        start_t = datetime.datetime.strptime(str(start_str).strip(), "%H:%M").time()
        end_t = datetime.datetime.strptime(str(stop_str).strip(), "%H:%M").time()
    except Exception:
        return False
    
    if start_t <= end_t:
        return start_t <= now <= end_t
    else:
        return now >= start_t or now <= end_t

def turn_timer_relay_on(i):
    if i < len(timer_relays) and timer_relays[i] and not timer_relays[i].is_active:
        timer_relays[i].on()
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Timer {i+1} ({setpoints.get(f'Timer{i+1} Name', f'T{i+1}')}) -> Relay ON")

def turn_timer_relay_off(i):
    if i < len(timer_relays) and timer_relays[i] and timer_relays[i].is_active:
        timer_relays[i].off()
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Timer {i+1} ({setpoints.get(f'Timer{i+1} Name', f'T{i+1}')}) -> Relay OFF")

def run_cycle():
    global timer_cycle_state, timer_last_switch
    now = time.time()
    configs = [
        ("Timer1 Start", "Timer1 Stop", "Timer1 ON Min", "Timer1 OFF Min"),
        ("Timer2 Start", "Timer2 Stop", "Timer2 ON Min", "Timer2 OFF Min"),
        ("Timer3 Start", "Timer3 Stop", "Timer3 ON Min", "Timer3 OFF Min")
    ]
    
    for i in range(3):
        start_str = setpoints.get(configs[i][0], "10:00")
        stop_str = setpoints.get(configs[i][1], "17:00")
        try:
            run_sec = float(setpoints.get(configs[i][2], 15)) * 60.0
        except Exception:
            run_sec = 900.0
        try:
            stop_sec = float(setpoints.get(configs[i][3], 30)) * 60.0
        except Exception:
            stop_sec = 1800.0
        
        if is_within_time_window(start_str, stop_str):
            if timer_cycle_state[i] == "OFF":
                if now - timer_last_switch[i] >= stop_sec or timer_last_switch[i] == 0:
                    turn_timer_relay_on(i)
                    timer_cycle_state[i] = "ON"
                    timer_last_switch[i] = now
            elif timer_cycle_state[i] == "ON":
                if now - timer_last_switch[i] >= run_sec:
                    turn_timer_relay_off(i)
                    timer_cycle_state[i] = "OFF"
                    timer_last_switch[i] = now
        else:
            if timer_cycle_state[i] == "ON" or (i < len(timer_relays) and timer_relays[i] and timer_relays[i].is_active):
                turn_timer_relay_off(i)
                timer_cycle_state[i] = "OFF"
                timer_last_switch[i] = 0.0

def safe_exit():
    print("Performing safe GPIO cleanup... All relays OFF on exit")
    all_relays_off()

atexit.register(safe_exit)

# ==============================================================================
# DYNAMIC RS485 / MODBUS SENSOR READER
# ==============================================================================
DEVICE_ID_WATER = 1
_water_inst_cache = None
_active_water_port = None

import glob

def get_candidate_ports():
    found = []
    found.extend(sorted(glob.glob("/dev/serial/by-path/*")))
    found.extend(sorted(glob.glob("/dev/serial/by-id/*")))
    found.extend(sorted(glob.glob("/dev/ttyUSB*")))
    for p in ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyUSB2", "/dev/ttyAMA0", "/dev/serial0"]:
        if p not in found and os.path.exists(p):
            found.append(p)
    return found

def open_modbus_instrument(port, device_id=1, baudrate=9600):
    try:
        inst = minimalmodbus.Instrument(port, device_id)
        inst.serial.baudrate = baudrate
        inst.serial.bytesize = 8
        inst.serial.parity   = serial.PARITY_NONE
        inst.serial.stopbits = 1
        inst.serial.timeout  = 0.5
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True
        return inst
    except Exception:
        return None

def get_water_instrument(force_reopen=False):
    global _water_inst_cache, _active_water_port
    if force_reopen and _water_inst_cache:
        try:
            if hasattr(_water_inst_cache, 'serial') and _water_inst_cache.serial:
                _water_inst_cache.serial.close()
        except Exception:
            pass
        _water_inst_cache = None

    if _water_inst_cache is not None:
        try:
            if _water_inst_cache.serial and getattr(_water_inst_cache.serial, 'is_open', False):
                return _water_inst_cache
        except Exception:
            _water_inst_cache = None

    ports_to_try = []
    if _active_water_port and os.path.exists(_active_water_port):
        ports_to_try.append(_active_water_port)
    for p in get_candidate_ports():
        if os.path.exists(p) and p not in ports_to_try:
            ports_to_try.append(p)

    for port in ports_to_try:
        inst = open_modbus_instrument(port, DEVICE_ID_WATER)
        if inst:
            _water_inst_cache = inst
            _active_water_port = port
            return inst
    return None

def read_sensor():
    global _water_inst_cache, _active_water_port
    inst = get_water_instrument()
    if not inst:
        return None

    register_maps = [
        {"desc": "Standard Soil/Water Map", "moist": 0x0012, "temp": 0x0013, "ec": 0x0015, "ph": 0x0006},
        {"desc": "Direct Offset Map",       "moist": 0,      "temp": 1,      "ec": 2,      "ph": 3}
    ]

    for rmap in register_maps:
        for fc in [3, 4]:
            try:
                moist = round(inst.read_register(rmap["moist"], 1, functioncode=fc), 1)
                temp  = round(inst.read_register(rmap["temp"], 1, signed=True, functioncode=fc), 1)
                raw_ec = inst.read_register(rmap["ec"], 0, functioncode=fc)
                ph    = round(inst.read_register(rmap["ph"], 2, functioncode=fc), 2)

                if (0 <= moist <= 100) and (-20 <= temp <= 80) and (0 <= raw_ec <= 20000) and (0 <= ph <= 14):
                    ec_val = round(raw_ec / 1000.0, 2) if raw_ec > 100 else round(float(raw_ec), 2)
                    return {
                        "temp": temp,
                        "moist": moist,
                        "ec": ec_val,
                        "raw_ec": raw_ec,
                        "ph": ph
                    }
            except Exception:
                pass

    get_water_instrument(force_reopen=True)
    return None

# ==============================================================================
# DOSING CONTROL LOGIC (HYSTERESIS + PULSE DOSING)
# ==============================================================================
def control(data):
    global ec_active, ph_active, last_ec_dose_time, last_ph_dose_time
    now = time.time()
    warnings = []

    ec_val = data["ec"]
    raw_ec = data.get("raw_ec", ec_val * 1000 if ec_val < 100 else ec_val)
    ph_val = data["ph"]

    ec_min = float(setpoints.get("EC MIN", 1200))
    ec_max = float(setpoints.get("EC MAX", 1800))
    if ec_min < 100: ec_min *= 1000.0
    if ec_max < 100: ec_max *= 1000.0

    ph_low  = float(setpoints.get("PH LOW", 5.8))
    ph_high = float(setpoints.get("PH HIGH", 6.5))
    dose_on_sec  = float(setpoints.get("DOSE ON SEC", 5))
    dose_off_sec = float(setpoints.get("DOSE OFF SEC", 20))

    # EC Dosing Control
    if raw_ec < ec_min:
        ec_active = True
        warnings.append(f"⚠️ EC LOW ({raw_ec:.0f} uS) -> Dosing EC1 & EC2")
    elif raw_ec >= ec_max:
        ec_active = False

    if ec_active:
        cycle_pos = (now - last_ec_dose_time) % (dose_on_sec + dose_off_sec)
        if cycle_pos < dose_on_sec:
            if not relay_ec1.is_active: relay_ec1.on()
            if not relay_ec2.is_active: relay_ec2.on()
        else:
            if relay_ec1.is_active: relay_ec1.off()
            if relay_ec2.is_active: relay_ec2.off()
    else:
        if relay_ec1.is_active: relay_ec1.off()
        if relay_ec2.is_active: relay_ec2.off()
        last_ec_dose_time = now

    # pH Minus Dosing Control
    if ph_val > ph_high:
        ph_active = True
        warnings.append(f"⚠️ pH HIGH ({ph_val:.2f}) -> Dosing pH-")
    elif ph_val <= ph_low:
        ph_active = False

    if ph_active:
        cycle_pos = (now - last_ph_dose_time) % (dose_on_sec + dose_off_sec)
        if cycle_pos < dose_on_sec:
            if not relay_ph.is_active: relay_ph.on()
        else:
            if relay_ph.is_active: relay_ph.off()
    else:
        if relay_ph.is_active: relay_ph.off()
        last_ph_dose_time = now

    return warnings

# ==============================================================================
# PRIVATE MOSQUITTO MQTT CLIENT SETUP (147.93.106.142)
# ==============================================================================
MQTT_BROKER = "147.93.106.142"
MQTT_PORT = 1883
MQTT_USER = "Inhydro@5598"
MQTT_PASS = "MGPL@5598"

CONTROL_TOPIC       = f"inhydro/{DEVICE_NAME}/setpoints/update"
CURRENT_SETP_TOPIC  = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC  = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"
LIVE_TELEMETRY      = f"inhydro/{DEVICE_NAME}/telemetry/live"
STATUS_TOPIC        = f"inhydro/{DEVICE_NAME}/status"

is_mqtt_connected = False
control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, f"Inhydro_System2_{DEVICE_NAME}_{int(time.time())}")

# Set MQTT Last Will & Testament (LWT)
control_client.will_set(STATUS_TOPIC, json.dumps({"status": "offline", "device": DEVICE_NAME}), qos=1, retain=True)

def on_control_connect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        print("✅ Connected to Private Mosquitto Broker (147.93.106.142:1883)")
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(CONTROL_SYNC_TOPIC)
        # Broadcast online status & current setpoints immediately
        client.publish(STATUS_TOPIC, json.dumps({"status": "online", "device": DEVICE_NAME}), retain=True)
        client.publish(LIVE_TELEMETRY, json.dumps({"status": "online", "device": DEVICE_NAME, "heartbeat": True}), retain=False)
        client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
    else:
        is_mqtt_connected = False

def on_control_disconnect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    is_mqtt_connected = False

def on_control_message(client, userdata, msg):
    try:
        global setpoints
        if msg.topic == CONTROL_SYNC_TOPIC:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
            return

        new_data = json.loads(msg.payload.decode())
        setpoints.update(new_data)
        save_setpoints()

        def update_ui():
            for key in new_data:
                if 'labels' in globals() and key in labels:
                    labels[key].config(text=str(setpoints[key]))

        if 'root' in globals():
            try: root.after(0, update_ui)
            except Exception: pass

        print(f"✅ Setpoints remotely updated via Private MQTT!")
    except Exception as e:
        print(f"⚠️ MQTT Update Error: {e}")

control_client.on_connect = on_control_connect
control_client.on_disconnect = on_control_disconnect
control_client.on_message = on_control_message

if MQTT_USER and MQTT_PASS:
    control_client.username_pw_set(MQTT_USER, MQTT_PASS)

try:
    control_client.connect_async(MQTT_BROKER, MQTT_PORT, 60)
    control_client.loop_start()
except Exception as e:
    print(f"⚠️ MQTT Connect exception: {e}")

# ==============================================================================
# LOCAL STORAGE BUFFER
# ==============================================================================
LOCAL_LOG_DIR = os.path.join(BASE_DIR, "local_logs")
LOCAL_LOG_FILE = os.path.join(LOCAL_LOG_DIR, "offline_telemetry.jsonl")
os.makedirs(LOCAL_LOG_DIR, exist_ok=True)

def save_local_telemetry(data):
    try:
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ts_str = datetime.datetime.now(ist_tz).isoformat()
        rec = dict(data)
        rec["device"] = DEVICE_NAME
        rec["timestamp"] = ts_str
        with open(LOCAL_LOG_FILE, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass

def sync_offline_worker():
    while True:
        try:
            if is_mqtt_connected and os.path.exists(LOCAL_LOG_FILE):
                with open(LOCAL_LOG_FILE, "r") as f:
                    lines = f.readlines()
                if lines:
                    remaining = []
                    for line in lines:
                        if not line.strip(): continue
                        try:
                            item = json.loads(line.strip())
                            control_client.publish(LIVE_TELEMETRY, json.dumps(item), retain=False)
                            time.sleep(0.05)
                        except Exception:
                            remaining.append(line)
                    with open(LOCAL_LOG_FILE, "w") as f:
                        f.writelines(remaining)
        except Exception:
            pass
        time.sleep(15)

# ==============================================================================
# BLUETOOTH / WIFI SETUP LOGIC
# ==============================================================================
def set_wifi(ssid, password):
    try:
        ssid = str(ssid).strip()
        password = str(password).strip()
        if not ssid: return "FAILED: Empty SSID"
        try:
            subprocess.run(['sudo', 'rfkill', 'unblock', 'wifi'], capture_output=True, timeout=3)
            subprocess.run(['sudo', 'nmcli', 'radio', 'wifi', 'on'], capture_output=True, timeout=3)
        except Exception: pass
        cmd = ['sudo', 'nmcli', '--wait', '15', 'device', 'wifi', 'connect', ssid]
        if password: cmd += ['password', password]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=18)
        if res.returncode == 0:
            return f"SUCCESS: Connected to '{ssid}'!"
        return f"FAILED: {res.stderr.strip() or res.stdout.strip() or 'Connection failed'}"
    except Exception as e: return f"ERROR: {str(e)}"

def scan_wifi():
    try:
        command = ['sudo', 'nmcli', '-t', '-f', 'SSID', 'dev', 'wifi']
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            names = sorted(list(set([n.strip() for n in result.stdout.split('\n') if n.strip()])))
            if not names: return "No networks found."
            return "\r\n--- NEARBY NETWORKS ---\r\n" + "\r\n".join(f"{i+1}. {n}" for i, n in enumerate(names))
        return f"SCAN FAILED: {result.stderr.strip()}"
    except Exception as e: return f"SCAN ERROR: {str(e)}"

def auto_trust_devices():
    try:
        btctl = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        btctl.stdin.write("agent NoInputNoOutput\ndefault-agent\ndiscoverable on\npairable on\n")
        btctl.stdin.flush()
    except Exception: pass
    while True:
        try:
            out = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True)
            for line in out.split('\n'):
                if line.startswith('Device '):
                    mac = line.split(" ")[1]
                    os.system(f"sudo bluetoothctl trust {mac} >/dev/null 2>&1")
        except Exception: pass
        time.sleep(6)

def start_bluetooth_server():
    try:
        os.system("sudo sdptool add SP >/dev/null 2>&1")
        time.sleep(1)
        server_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        server_sock.bind((socket.BDADDR_ANY, 1))
        server_sock.listen(1)
        while True:
            try:
                client_sock, info = server_sock.accept()
                client_sock.send(f"\r\n--- INHYDRO SYSTEM2 ({DEVICE_NAME}) ---\r\nCommands: WIFI:SSID:PASS | ID:NEW_NAME | SCAN\r\n".encode('utf-8'))
                while True:
                    data = client_sock.recv(1024)
                    if not data: break
                    msg = data.decode('utf-8', errors='ignore').strip()
                    if msg.startswith("WIFI:"):
                        parts = msg.split(":")
                        if len(parts) >= 3:
                            client_sock.send(f"\r\nConnecting to {parts[1]}...\r\n".encode('utf-8'))
                            client_sock.send(f"{set_wifi(parts[1], ':'.join(parts[2:]))}\r\n".encode('utf-8'))
                    elif msg.startswith("ID:"):
                        nid = msg.split(":")[1].strip()
                        if nid:
                            with open(ID_FILE, "w") as f: f.write(nid)
                            client_sock.send(f"\r\nDevice ID set to {nid}. Rebooting...\r\n".encode('utf-8'))
                            root.after(2000, restart_program)
                    elif msg.upper() == "SCAN":
                        client_sock.send((scan_wifi() + "\r\n").encode('utf-8'))
            except Exception: pass
            finally:
                if 'client_sock' in locals(): client_sock.close()
    except Exception as e:
        print(f"⚠️ Bluetooth server notice: {e}")

# ==============================================================================
# UI SETUP (ORIGINAL CLEAN WHITE THEME WITH SPLIT DASHBOARD)
# ==============================================================================
root = tk.Tk()
root.update()
root.attributes("-fullscreen", True)
root.configure(bg="white")
root.bind("<Escape>", lambda e: root.destroy())

# CLOCK (TOP LEFT - DATE & TIME IN BLUE)
lbl_clock = tk.Label(root, text="", font=("Arial", 12, "bold"), fg="#1565c0", bg="white", justify="left")
lbl_clock.place(x=15, y=10, anchor="nw")

def update_clock():
    now = datetime.datetime.now()
    date_str = now.strftime("%d %b %Y (%A)")
    time_str = now.strftime("%I:%M:%S %p")
    lbl_clock.config(text=f"{date_str}\n{time_str}")
    root.after(1000, update_clock)

update_clock()

# LOGO (TOP RIGHT)
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
try:
    logo_img_raw = Image.open(LOGO_PATH)
    logo_img_raw = logo_img_raw.resize((150, 95), Image.LANCZOS)
    logo_img = ImageTk.PhotoImage(logo_img_raw)
    lbl_logo = tk.Label(root, image=logo_img, bg="white")
    lbl_logo.image = logo_img
    lbl_logo.place(relx=0.98, y=10, anchor="ne")
except Exception as e:
    lbl_logo = tk.Label(root, text="LOGO MISSING", fg="#c62828", bg="white", font=("Arial", 12, "bold"))
    lbl_logo.place(relx=0.98, y=10, anchor="ne")

big = ("Arial", 20, "bold")
med = ("Arial", 14)

frame_main = tk.Frame(root, bg="white")
frame_set = tk.Frame(root, bg="white")

def show(frame):
    frame_main.pack_forget()
    frame_set.pack_forget()
    frame.pack(fill="both", expand=True)
    if 'lbl_logo' in globals():
        lbl_logo.lift()
    if 'lbl_clock' in globals():
        lbl_clock.lift()

show(frame_main)

# DASHBOARD (SPLIT HORIZONTALLY INTO SENSORS/RELAYS LEFT & CYCLIC TIMERS RIGHT)
dash_container = tk.Frame(frame_main, bg="white")
dash_container.pack(pady=(45, 2), fill="both", expand=True)

left_frame = tk.Frame(dash_container, bg="white")
left_frame.pack(side="left", fill="both", expand=True, padx=20)

separator = tk.Frame(dash_container, bg="#cccccc", width=2)
separator.pack(side="left", fill="y", pady=10)

right_frame = tk.Frame(dash_container, bg="white")
right_frame.pack(side="left", fill="both", expand=True, padx=20)

lbl_data = tk.Label(left_frame, font=big, fg="#1a237e", bg="white", justify="left")
lbl_data.pack(pady=20)

lbl_warn = tk.Label(left_frame, font=med, fg="#c62828", bg="white")
lbl_warn.pack()

lbl_relay_left = tk.Label(left_frame, font=med, fg="#006064", bg="white", justify="left")
lbl_relay_left.pack(pady=10)

lbl_timer_title = tk.Label(right_frame, font=("Arial", 18, "bold"), fg="#1565c0", bg="white", text="CYCLIC TIMERS")
lbl_timer_title.pack(pady=10)

lbl_timer_right = tk.Label(right_frame, font=med, fg="#006064", bg="white", justify="left")
lbl_timer_right.pack(pady=10)

def relay_status_left():
    return f"""
EC MODE : {'ON' if ec_active else 'OFF'}
pH MODE : {'ON' if ph_active else 'OFF'}

EC1 : {'ON' if relay_ec1.is_active else 'OFF'}
EC2 : {'ON' if relay_ec2.is_active else 'OFF'}
pH  : {'ON' if relay_ph.is_active else 'OFF'}
"""

def timer_status_right():
    return f"""
{setpoints.get('Timer1 Name', 'TIMER 1')}
Status : {'ON' if timer_relays[0].is_active else 'OFF'} (State: {timer_cycle_state[0]})
Window : {setpoints.get('Timer1 Start', '10:00')} - {setpoints.get('Timer1 Stop', '17:00')}
Cycles : {setpoints.get('Timer1 ON Min', 15)}m ON / {setpoints.get('Timer1 OFF Min', 30)}m OFF

{setpoints.get('Timer2 Name', 'TIMER 2')}
Status : {'ON' if timer_relays[1].is_active else 'OFF'} (State: {timer_cycle_state[1]})
Window : {setpoints.get('Timer2 Start', '10:00')} - {setpoints.get('Timer2 Stop', '17:00')}
Cycles : {setpoints.get('Timer2 ON Min', 15)}m ON / {setpoints.get('Timer2 OFF Min', 30)}m OFF

{setpoints.get('Timer3 Name', 'TIMER 3')}
Status : {'ON' if timer_relays[2].is_active else 'OFF'} (State: {timer_cycle_state[2]})
Window : {setpoints.get('Timer3 Start', '10:00')} - {setpoints.get('Timer3 Stop', '17:00')}
Cycles : {setpoints.get('Timer3 ON Min', 15)}m ON / {setpoints.get('Timer3 OFF Min', 30)}m OFF
"""

def manual_stop():
    all_relays_off()
    global ec_active, ph_active, timer_cycle_state
    ec_active = False
    ph_active = False
    for i in range(len(timer_cycle_state)):
        timer_cycle_state[i] = "OFF"
    lbl_warn.config(text="🛑 MANUAL STOP")
    lbl_relay_left.config(text=relay_status_left())
    lbl_timer_right.config(text=timer_status_right())

def restart_program():
    manual_stop()
    if _water_inst_cache:
        try: _water_inst_cache.serial.close()
        except Exception: pass
    os.execl(sys.executable, sys.executable, *sys.argv)

# MAIN FOOTER
footer = tk.Frame(frame_main, bg="#eeeeee", height=60)
footer.pack(side="bottom", fill="x")
footer.pack_propagate(False)

tk.Button(footer, text="SETPOINTS", font=med, bg="#1565c0", fg="white", width=12,
          command=lambda: show(frame_set)).pack(side="left", padx=20, pady=10)

tk.Button(footer, text="STOP", font=med, bg="#c62828", fg="white", width=12,
          command=manual_stop).pack(side="left", padx=20, pady=10)

tk.Button(footer, text="RESTART", font=med, bg="#455a64", fg="white", width=12,
          command=restart_program).pack(side="left", padx=20, pady=10)

tk.Button(footer, text="EXIT", font=med, bg="#333333", fg="white", width=12,
          command=root.destroy).pack(side="right", padx=20, pady=10)

# ==============================================================================
# SETPOINT SCREEN (WITH FULL NUMERIC & QWERTY KEYBOARDS)
# ==============================================================================
tk.Label(frame_set, text="SYSTEM SETPOINTS", font=big, fg="#1565c0", bg="white").pack(pady=10)

labels = {}
selected_key = None
entered_value = ""

def open_keypad(key):
    global selected_key, entered_value
    selected_key = key
    entered_value = ""
    lbl_display.config(text="")
    lbl_title.config(text=f"Set {key}")

    for widget in button_frame.winfo_children():
        widget.destroy()
    for widget in action_frame.winfo_children():
        widget.destroy()

    if key.endswith("Name"):
        build_qwerty_keyboard()
    else:
        build_numeric_keypad()

    settings_container.pack_forget()
    keypad_frame.pack(pady=5)

def press(val):
    global entered_value
    entered_value += str(val)
    lbl_display.config(text=entered_value)

def clear():
    global entered_value
    entered_value = ""
    lbl_display.config(text="")

def backspace():
    global entered_value
    entered_value = entered_value[:-1]
    lbl_display.config(text=entered_value)

def confirm():
    global entered_value
    try:
        if selected_key.endswith("Name"):
            value = str(entered_value)
        elif ":" in entered_value:
            value = str(entered_value)
        else:
            value = float(entered_value)
        setpoints[selected_key] = value
        labels[selected_key].config(text=str(value))
        save_setpoints()
        keypad_frame.pack_forget()
        settings_container.pack(pady=5)
    except Exception:
        lbl_display.config(text="ERROR")

def cancel():
    keypad_frame.pack_forget()
    settings_container.pack(pady=5)

settings_container = tk.Frame(frame_set, bg="white")
settings_container.pack(pady=5)

current_row_idx = 0
current_col_idx = 0

def create_row(key):
    global current_row_idx, current_col_idx
    if key not in setpoints:
        return

    cell = tk.Frame(settings_container, bg="white")
    cell.grid(row=current_row_idx, column=current_col_idx, padx=10, pady=2)

    tk.Label(cell, text=key, font=("Arial", 12), fg="#333333", bg="white", width=14, anchor="w").pack(side="left")
    labels[key] = tk.Label(cell, text=str(setpoints[key]), font=("Arial", 12, "bold"), fg="#ef6c00", bg="white", width=8, relief="sunken")
    labels[key].pack(side="left", padx=5)

    tk.Button(cell, text="EDIT", font=("Arial", 10), bg="#eeeeee", command=lambda k=key: open_keypad(k)).pack(side="left")

    current_col_idx += 1
    if current_col_idx > 1:
        current_col_idx = 0
        current_row_idx += 1

settings_keys = [
    "EC MIN", "EC MAX", "PH LOW", "PH HIGH",
    "Timer1 Name", "Timer1 Start", "Timer1 Stop", "Timer1 ON Min", "Timer1 OFF Min",
    "Timer2 Name", "Timer2 Start", "Timer2 Stop", "Timer2 ON Min", "Timer2 OFF Min",
    "Timer3 Name", "Timer3 Start", "Timer3 Stop", "Timer3 ON Min", "Timer3 OFF Min"
]

for k in settings_keys:
    create_row(k)

# COMPACT KEYPAD
keypad_frame = tk.Frame(frame_set, bg="white")

lbl_title = tk.Label(keypad_frame, font=med, fg="#1565c0", bg="white")
lbl_title.pack()

lbl_display = tk.Label(keypad_frame, font=("Arial", 18, "bold"), fg="#2e7d32", bg="white")
lbl_display.pack()

button_frame = tk.Frame(keypad_frame, bg="white")
button_frame.pack()

action_frame = tk.Frame(keypad_frame, bg="white")
action_frame.pack(pady=5)

def build_numeric_keypad():
    buttons = [
        ('1',0,0), ('2',0,1), ('3',0,2),
        ('4',1,0), ('5',1,1), ('6',1,2),
        ('7',2,0), ('8',2,1), ('9',2,2),
        ('.',3,0), ('0',3,1), (':',3,2),
    ]

    for (text,r,c) in buttons:
        cmd = lambda x=text: press(x)
        tk.Button(button_frame, text=text, font=med, width=4, height=1, command=cmd).grid(row=r, column=c, padx=3, pady=3)

    tk.Button(action_frame, text="DEL", font=med, bg="orange", fg="black", width=4, command=backspace).pack(side="left", padx=5)
    tk.Button(action_frame, text="CLR", font=med, bg="#d9534f", fg="white", width=4, command=clear).pack(side="left", padx=5)
    tk.Button(action_frame, text="OK", font=med, bg="green", fg="white", width=4, command=confirm).pack(side="left", padx=5)
    tk.Button(action_frame, text="CAN", font=med, bg="red", fg="white", width=4, command=cancel).pack(side="left", padx=5)

def build_qwerty_keyboard():
    keyboard_layouts = [
        ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
        ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
        ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', ':'],
        ['Z', 'X', 'C', 'V', 'B', 'N', 'M', '.', '_', ' ']
    ]

    for r, row in enumerate(keyboard_layouts):
        for c, char in enumerate(row):
            cmd = lambda x=char: press(x)
            tk.Button(button_frame,
                      text=char if char != ' ' else 'SPC',
                      font=("Arial", 14, "bold"),
                      width=3,
                      height=1,
                      command=cmd
                      ).grid(row=r, column=c, padx=2, pady=2)

    tk.Button(action_frame, text="DEL", font=med, bg="orange", fg="black", width=6, command=backspace).pack(side="left", padx=5)
    tk.Button(action_frame, text="CLR", font=med, bg="#d9534f", fg="white", width=6, command=clear).pack(side="left", padx=5)
    tk.Button(action_frame, text="OK", font=med, bg="green", fg="white", width=6, command=confirm).pack(side="left", padx=5)
    tk.Button(action_frame, text="CAN", font=med, bg="red", fg="white", width=6, command=cancel).pack(side="left", padx=5)

# SETPOINT FOOTER
footer_set = tk.Frame(frame_set, bg="#eeeeee", height=60)
footer_set.pack(side="bottom", fill="x")
footer_set.pack_propagate(False)

tk.Button(footer_set, text="SAVE & EXIT", font=med, bg="#1e90ff", fg="white", width=15,
          command=lambda: (save_setpoints(), show(frame_main))).pack(pady=10)

# ==============================================================================
# MAIN CONTROL & TELEMETRY UPDATE LOOP
# ==============================================================================
def update():
    try:
        data = read_sensor()
        run_cycle()
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ts_str = datetime.datetime.now(ist_tz).isoformat()

        if data:
            warn = control(data)
            ec_display = f"{data['ec']} mS/cm ({data.get('raw_ec', 0)} us/cm)"
            lbl_data.config(
                text=f"Temp  : {data['temp']} °C\nEC    : {ec_display}\npH    : {data['ph']}\nMoist : {data['moist']} %",
                fg="#1a237e"
            )
            lbl_warn.config(text="\n".join(warn) if warn else "")
            lbl_relay_left.config(text=relay_status_left())
            lbl_timer_right.config(text=timer_status_right())

            # Realtime Dispatch over Private Mosquitto Broker
            if is_mqtt_connected:
                try:
                    payload = dict(data)
                    payload["status"] = "online"
                    payload["device"] = DEVICE_NAME
                    payload["timestamp"] = ts_str
                    payload["relays"] = {
                        "ec1": relay_ec1.is_active,
                        "ec2": relay_ec2.is_active,
                        "ph":  relay_ph.is_active,
                        "t1":  timer_relay_1.is_active,
                        "t2":  timer_relay_2.is_active,
                        "t3":  timer_relay_3.is_active,
                        "t4":  timer_relay_4.is_active
                    }
                    payload["timers"] = {
                        "t1_state": timer_cycle_state[0],
                        "t2_state": timer_cycle_state[1],
                        "t3_state": timer_cycle_state[2]
                    }
                    control_client.publish(LIVE_TELEMETRY, json.dumps(payload), retain=False)
                    control_client.publish(STATUS_TOPIC, json.dumps({"status": "online", "device": DEVICE_NAME, "timestamp": ts_str}), retain=True)
                except Exception as pe:
                    print(f"⚠️ Telemetry publish note: {pe}")

            save_local_telemetry(data)
        else:
            lbl_data.config(text="⚠️ SENSOR ERROR", fg="#c62828")
            lbl_warn.config(text="Check connections / Serial Port")
            lbl_relay_left.config(text=relay_status_left())
            lbl_timer_right.config(text=timer_status_right())

            # Continuous Online Heartbeat Dispatch even if sensor is disconnected
            if is_mqtt_connected:
                try:
                    payload = {
                        "status": "online",
                        "device": DEVICE_NAME,
                        "timestamp": ts_str,
                        "sensor_error": True,
                        "relays": {
                            "ec1": relay_ec1.is_active,
                            "ec2": relay_ec2.is_active,
                            "ph":  relay_ph.is_active,
                            "t1":  timer_relay_1.is_active,
                            "t2":  timer_relay_2.is_active,
                            "t3":  timer_relay_3.is_active,
                            "t4":  timer_relay_4.is_active
                        },
                        "timers": {
                            "t1_state": timer_cycle_state[0],
                            "t2_state": timer_cycle_state[1],
                            "t3_state": timer_cycle_state[2]
                        }
                    }
                    control_client.publish(LIVE_TELEMETRY, json.dumps(payload), retain=False)
                    control_client.publish(STATUS_TOPIC, json.dumps({"status": "online", "device": DEVICE_NAME, "timestamp": ts_str}), retain=True)
                except Exception as pe:
                    pass
    except Exception as e:
        print(f"⚠️ Update loop exception: {e}")

    root.after(2000, update)

# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
def main():
    try:
        threading.Thread(target=auto_trust_devices, daemon=True).start()
    except Exception: pass

    try:
        threading.Thread(target=start_bluetooth_server, daemon=True).start()
        print("✅ Background Bluetooth Automated Setup Agent started")
    except Exception as e:
        print(f"Failed to start Bluetooth thread: {e}")

    try:
        threading.Thread(target=sync_offline_worker, daemon=True).start()
        print("✅ Background Offline Telemetry Sync Worker started")
    except Exception as e:
        print(f"Failed to start Offline Sync thread: {e}")

    update()
    root.mainloop()

if __name__ == "__main__":
    main()
