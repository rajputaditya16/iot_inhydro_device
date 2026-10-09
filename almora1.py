import os, sys, json, time, datetime, socket
import subprocess, threading
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import font
import minimalmodbus
import serial
import paho.mqtt.client as mqtt
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
    return "almora1"

DEVICE_NAME = get_device_id()
print(f"📌 Device Identity Loaded: {DEVICE_NAME}")

SETPOINT_FILE = os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}.json")
print(f"📁 Using config file: {SETPOINT_FILE}")

# Remove legacy config to prevent sync conflicts
OLD_FILE = os.path.join(BASE_DIR, "setpoints.json")
if os.path.exists(OLD_FILE):
    try:
        os.remove(OLD_FILE)
        print("🗑️ Removed legacy setpoints.json...")
    except Exception:
        pass

# ==============================================================================
# RELAY HARDWARE (ACTIVE LOW)
# ==============================================================================
# Pin 22 = EC Dosing Pump 1 (Part A)
# Pin 23 = EC Dosing Pump 2 (Part B)
# Pin 24 = pH Minus Dosing Pump
relay_ec1 = OutputDevice(22, active_high=False, initial_value=False)
relay_ec2 = OutputDevice(23, active_high=False, initial_value=False)
relay_ph  = OutputDevice(24, active_high=False, initial_value=False)

def all_relays_off():
    for r in [relay_ec1, relay_ec2, relay_ph]:
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

# ==============================================================================
# DEFAULT SETPOINTS & NORMALIZATION
# ==============================================================================
setpoints = {
    "EC MIN": 1.2,        # Target EC Min (mS/cm or uS/cm auto-detected)
    "EC MAX": 1.8,        # Target EC Max
    "PH LOW": 5.8,        # Target pH Min
    "PH HIGH": 6.5,       # Target pH Max
    "DOSE ON SEC": 5,     # Pump active duration per dose burst
    "DOSE OFF SEC": 20,   # Water circulation & mixing pause
    "PORT": 1883
}

if os.path.exists(SETPOINT_FILE):
    try:
        with open(SETPOINT_FILE, "r") as f:
            loaded = json.load(f)
            setpoints.update(loaded)
    except Exception as e:
        print(f"⚠️ Error reading setpoints file: {e}")

# Normalize EC setpoints if loaded in uS/cm (>100) to mS/cm
if float(setpoints.get("EC MIN", 1.2)) > 100:
    setpoints["EC MIN"] = round(float(setpoints["EC MIN"]) / 1000.0, 2)
if float(setpoints.get("EC MAX", 1.8)) > 100:
    setpoints["EC MAX"] = round(float(setpoints["EC MAX"]) / 1000.0, 2)

def save_setpoints():
    try:
        with open(SETPOINT_FILE, "w") as f:
            json.dump(setpoints, f, indent=4)
        if 'control_client' in globals() and is_mqtt_connected:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
            print("📤 Pushed setpoints to Private Cloud Broker.")
    except Exception as e:
        print(f"⚠️ Error saving setpoints: {e}")

# ==============================================================================
# DYNAMIC RS485 / MODBUS SENSOR READER (AUTO-PORT DISCOVERY & RECONNECT)
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

    # Check previously active port first
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
            return _water_inst_cache

    return None

def read_sensor():
    """
    Reads Moisture, Temperature, EC, and pH with automatic register scanning,
    function code fallback (FC3/FC4), and dynamic reconnection.
    """
    global _water_inst_cache
    for attempt in range(2):
        inst = get_water_instrument(force_reopen=(attempt > 0))
        if inst is None:
            time.sleep(0.1)
            continue

        try:
            if hasattr(inst.serial, 'reset_input_buffer'):
                try: inst.serial.reset_input_buffer()
                except Exception: pass

            # Mode 1: Block read registers 18..21 via FC3
            try:
                data = inst.read_registers(registeraddress=18, number_of_registers=4, functioncode=3)
                moist  = round(data[0] / 10.0, 1)                  # %
                temp   = round(data[1] / 10.0, 1)                  # °C
                raw_ec = data[2]                                   # uS/cm
                ec     = round((raw_ec * 0.85) / 1000.0, 2)         # mS/cm
                ph     = round(data[3] / 100.0, 2)                 # pH
                if (ec > 0 or ph > 0 or temp > 0):
                    return {"temp": temp, "moist": moist, "ec": ec, "raw_ec": raw_ec, "ph": ph}
            except Exception:
                pass

            # Mode 2: Block read registers 18..21 via FC4
            try:
                data = inst.read_registers(registeraddress=18, number_of_registers=4, functioncode=4)
                moist  = round(data[0] / 10.0, 1)
                temp   = round(data[1] / 10.0, 1)
                raw_ec = data[2]
                ec     = round((raw_ec * 0.85) / 1000.0, 2)
                ph     = round(data[3] / 100.0, 2)
                if (ec > 0 or ph > 0 or temp > 0):
                    return {"temp": temp, "moist": moist, "ec": ec, "raw_ec": raw_ec, "ph": ph}
            except Exception:
                pass

            # Mode 3: Individual register reads (0x0012, 0x0013, 0x0015, 0x0006)
            try:
                moist_raw = inst.read_register(0x0012, 1)
                temp_raw  = inst.read_register(0x0013, 1, signed=True)
                raw_ec    = inst.read_register(0x0015, 0)
                ph_raw    = inst.read_register(0x0006, 2)

                moist = round(moist_raw / 10.0, 1)
                temp  = round(temp_raw / 10.0, 1)
                ec    = round((raw_ec * 0.85) / 1000.0, 2)
                ph    = round(ph_raw / 100.0, 2)
                return {"temp": temp, "moist": moist, "ec": ec, "raw_ec": raw_ec, "ph": ph}
            except Exception:
                pass

        except Exception as e:
            print(f"⚠️ Sensor communication error: {e}")

        # Invalidate cache to force clean reconnect on next retry
        if _water_inst_cache:
            try: _water_inst_cache.serial.close()
            except Exception: pass
            _water_inst_cache = None
        time.sleep(0.1)

    return None

# ==============================================================================
# RELAY CONTROL & DOSING LOGIC (ROBUST HYSTERESIS & PULSED DOSING)
# ==============================================================================
def control(data):
    global ec_active, ph_active, last_ec_dose_time, last_ph_dose_time
    now = time.time()
    warnings = []

    if not data or not isinstance(data, dict):
        all_relays_off()
        ec_active = False
        ph_active = False
        return ["⚠ SENSOR ERROR – DOSING DISABLED"]

    try:
        ec_val = float(data.get("ec", 0.0))    # mS/cm
        ph_val = float(data.get("ph", 7.0))    # pH
        raw_ec = float(data.get("raw_ec", ec_val * 1000))
    except (ValueError, TypeError):
        return ["⚠ INVALID SENSOR DATA"]

    # Safe Float Setpoint Parsing (immune to string setpoint TypeErrors)
    try:
        ec_min_sp = float(setpoints.get("EC MIN", 1.2))
        ec_max_sp = float(setpoints.get("EC MAX", 1.8))
        ph_low_sp = float(setpoints.get("PH LOW", 5.8))
        ph_high_sp = float(setpoints.get("PH HIGH", 6.5))
        dose_on_sec = float(setpoints.get("DOSE ON SEC", 5.0))
        dose_off_sec = float(setpoints.get("DOSE OFF SEC", 20.0))
    except (ValueError, TypeError):
        ec_min_sp, ec_max_sp = 1.2, 1.8
        ph_low_sp, ph_high_sp = 5.8, 6.5
        dose_on_sec, dose_off_sec = 5.0, 20.0

    # Handle setpoint unit auto-normalization (if user provided uS/cm vs mS/cm)
    if ec_min_sp > 100: ec_min_sp /= 1000.0
    if ec_max_sp > 100: ec_max_sp /= 1000.0

    # -------------------------------------------------------------------------
    # 1. EC NUTRIENT DOSING CONTROL (EC1 on Pin 22 & EC2 on Pin 23)
    # -------------------------------------------------------------------------
    if ec_val > 0.05:  # Valid sensor reading present
        if not ec_active and ec_val < ec_min_sp:
            ec_active = True
            last_ec_dose_time = now
            relay_ec1.on()
            relay_ec2.on()
            warnings.append(f"⚠ EC LOW ({ec_val:.2f} < {ec_min_sp:.2f}) – DOSING EC1 & EC2")
            print(f"🚀 [DOSING] EC Dosing STARTED: {ec_val:.2f} mS/cm < {ec_min_sp:.2f} mS/cm")

        elif ec_active:
            if ec_val >= ec_max_sp:
                ec_active = False
                relay_ec1.off()
                relay_ec2.off()
                print(f"✅ [DOSING] EC Target Reached: {ec_val:.2f} mS/cm >= {ec_max_sp:.2f} mS/cm")
            else:
                # Pulsed duty cycle to prevent over-concentration and pump burnout
                elapsed = now - last_ec_dose_time
                cycle_period = dose_on_sec + dose_off_sec
                cycle_pos = elapsed % cycle_period

                if cycle_pos < dose_on_sec:
                    relay_ec1.on()
                    relay_ec2.on()
                    warnings.append(f"⚠ EC DOSING ACTIVE (Pumping {dose_on_sec - cycle_pos:.0f}s)")
                else:
                    relay_ec1.off()
                    relay_ec2.off()
                    warnings.append(f"⏳ EC DOSING MIXING (Waiting {cycle_period - cycle_pos:.0f}s)")
    else:
        # Sensor unplugged or reading 0
        relay_ec1.off()
        relay_ec2.off()
        ec_active = False

    # -------------------------------------------------------------------------
    # 2. PH MINUS DOSING CONTROL (pH Pump on Pin 24)
    # -------------------------------------------------------------------------
    if ph_val > 2.0:  # Valid pH reading present
        if not ph_active and ph_val > ph_high_sp:
            ph_active = True
            last_ph_dose_time = now
            relay_ph.on()
            warnings.append(f"⚠ pH HIGH ({ph_val:.2f} > {ph_high_sp:.2f}) – DOSING pH MINUS")
            print(f"🚀 [DOSING] pH Dosing STARTED: {ph_val:.2f} > {ph_high_sp:.2f}")

        elif ph_active:
            if ph_val <= ph_low_sp:
                ph_active = False
                relay_ph.off()
                print(f"✅ [DOSING] pH Target Reached: {ph_val:.2f} <= {ph_low_sp:.2f}")
            else:
                # Pulsed duty cycle for pH correction
                elapsed = now - last_ph_dose_time
                cycle_period = dose_on_sec + dose_off_sec
                cycle_pos = elapsed % cycle_period

                if cycle_pos < dose_on_sec:
                    relay_ph.on()
                    warnings.append(f"⚠ pH DOSING ACTIVE (Pumping {dose_on_sec - cycle_pos:.0f}s)")
                else:
                    relay_ph.off()
                    warnings.append(f"⏳ pH DOSING MIXING (Waiting {cycle_period - cycle_pos:.0f}s)")
    else:
        relay_ph.off()
        ph_active = False

    return warnings

# ==============================================================================
# PRIVATE MOSQUITTO MQTT BROKER (100% PRIVATE BROKER INTEGRATION)
# ==============================================================================
CONTROL_BROKER = "147.93.106.142"
CONTROL_PORT   = 1883
CONTROL_USER   = "Inhydro@5598"
CONTROL_PASS   = "MGPL@5598"

CONTROL_TOPIC      = f"inhydro/{DEVICE_NAME}/setpoints/update"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"
CONTROL_CMD_TOPIC  = f"inhydro/{DEVICE_NAME}/command"
LIVE_TELEMETRY     = f"inhydro/{DEVICE_NAME}/telemetry/live"
STATUS_TOPIC       = f"inhydro/{DEVICE_NAME}/status"

is_mqtt_connected = False
control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, f"Almora1_{DEVICE_NAME}_{int(time.time())}")

# Set MQTT Last Will & Testament (LWT) so broker marks device offline on disconnect
control_client.will_set(STATUS_TOPIC, json.dumps({"status": "offline", "device": DEVICE_NAME}), qos=1, retain=True)

def on_control_message(client, userdata, msg):
    global setpoints
    try:
        topic = msg.topic
        payload_str = msg.payload.decode('utf-8', errors='ignore').strip()

        # Handle Remote Sync Request
        if topic == CONTROL_SYNC_TOPIC:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
            print("📤 [MQTT] Current setpoints broadcasted upon request.")
            return

        # Handle Remote Hardware Commands
        if topic == CONTROL_CMD_TOPIC:
            try:
                cmd_data = json.loads(payload_str)
                action = cmd_data.get("action") or cmd_data.get("command")
                if action == "RESTART":
                    print("🔄 [MQTT] Remote restart command received.")
                    root.after(1000, restart_program)
                elif action == "STOP":
                    print("🛑 [MQTT] Remote stop command received.")
                    root.after(0, manual_stop)
            except Exception as ce:
                print(f"⚠️ Command parse error: {ce}")
            return

        # Handle Setpoint Updates
        new_data = json.loads(payload_str)
        if not isinstance(new_data, dict):
            return

        key_map = {
            "ecMin": "EC MIN",
            "ecMax": "EC MAX",
            "phLow": "PH LOW",
            "phHigh": "PH HIGH",
            "ec_min": "EC MIN",
            "ec_max": "EC MAX",
            "ph_low": "PH LOW",
            "ph_high": "PH HIGH",
            "doseOnSec": "DOSE ON SEC",
            "doseOffSec": "DOSE OFF SEC"
        }

        updated = False
        for k, v in new_data.items():
            mapped_key = key_map.get(k, k)
            if mapped_key in setpoints:
                try:
                    setpoints[mapped_key] = float(v)
                    updated = True
                except (ValueError, TypeError):
                    setpoints[mapped_key] = v
                    updated = True

        if updated:
            save_setpoints()
            print("✅ [MQTT] Setpoints updated via Private Broker:", setpoints)

            def update_ui_labels():
                if 'labels' in globals():
                    for k in setpoints:
                        if k in labels:
                            labels[k].config(text=str(setpoints[k]))
            try:
                root.after(0, update_ui_labels)
            except Exception:
                pass

    except Exception as e:
        print(f"❌ [MQTT] Error processing incoming payload: {e}")

def on_control_connect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        print(f"✅ Connected to Private Mosquitto Broker ({CONTROL_BROKER}:{CONTROL_PORT})")
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(CONTROL_SYNC_TOPIC)
        client.subscribe(CONTROL_CMD_TOPIC)
        # Immediately broadcast online status and current setpoints
        client.publish(STATUS_TOPIC, json.dumps({"status": "online", "device": DEVICE_NAME}), retain=True)
        client.publish(LIVE_TELEMETRY, json.dumps({"status": "online", "device": DEVICE_NAME, "heartbeat": True}), retain=False)
        client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
    else:
        is_mqtt_connected = False
        print(f"⚠️ MQTT Broker Connection failed (code {rc})")

def on_control_disconnect(client, userdata, rc, properties=None):
    global is_mqtt_connected
    is_mqtt_connected = False
    print("⚠️ Disconnected from Private Broker. Auto-reconnecting in background...")

control_client.on_message = on_control_message
control_client.on_connect = on_control_connect
control_client.on_disconnect = on_control_disconnect

try:
    if CONTROL_USER and CONTROL_PASS:
        control_client.username_pw_set(CONTROL_USER, CONTROL_PASS)
    control_client.connect_async(CONTROL_BROKER, CONTROL_PORT, 60)
    control_client.loop_start()
except Exception as e:
    print(f"⚠️ Private MQTT startup error: {e}")

# ==============================================================================
# OFFLINE TELEMETRY LOGGING & AUTO-SYNC
# ==============================================================================
LOG_DIR = os.path.join(BASE_DIR, "local_logs")
ACTIVE_LOG_FILE = os.path.join(LOG_DIR, "active.jsonl")
local_log_lock = threading.Lock()
last_local_save_time = 0

def save_local_telemetry(data):
    global last_local_save_time
    if is_mqtt_connected:
        return  # Online, no need to buffer offline

    current_time = time.time()
    if current_time - last_local_save_time < 30:
        return

    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ts_str = datetime.datetime.now(ist_tz).isoformat()
    entry = {"timestamp": ts_str, "telemetry": data, "device": DEVICE_NAME}

    def write_worker():
        with local_log_lock:
            try:
                os.makedirs(LOG_DIR, exist_ok=True)
                with open(ACTIVE_LOG_FILE, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as e:
                print(f"⚠️ Offline log write error: {e}")

    threading.Thread(target=write_worker, daemon=True).start()
    last_local_save_time = current_time

def sync_offline_worker():
    while True:
        try:
            if is_mqtt_connected and os.path.exists(ACTIVE_LOG_FILE):
                rows = []
                with local_log_lock:
                    if os.path.exists(ACTIVE_LOG_FILE) and os.path.getsize(ACTIVE_LOG_FILE) > 0:
                        try:
                            with open(ACTIVE_LOG_FILE, "r") as f:
                                for line in f:
                                    line = line.strip()
                                    if line:
                                        rows.append(json.loads(line))
                            os.remove(ACTIVE_LOG_FILE)
                        except Exception:
                            pass

                if rows:
                    print(f"📤 [SYNC] Offloading {len(rows)} cached telemetry rows to Private Broker...")
                    for r in rows:
                        try:
                            control_client.publish(LIVE_TELEMETRY, json.dumps(r), qos=1)
                            time.sleep(0.02)
                        except Exception:
                            break
        except Exception as e:
            print(f"⚠️ Sync worker exception: {e}")
        time.sleep(20)

# ==============================================================================
# NATIVE BLUETOOTH & WIFI SETUP DAEMONS
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
                client_sock.send(f"\r\n--- INHYDRO ALMORA ({DEVICE_NAME}) ---\r\nCommands: WIFI:SSID:PASS | ID:NEW_NAME | SCAN\r\n".encode('utf-8'))
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
# UI SETUP (ORIGINAL CLEAN WHITE THEME)
# ==============================================================================
root = tk.Tk()
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
med = ("Arial", 15)
small = ("Arial", 13)

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

# DASHBOARD
lbl_data = tk.Label(frame_main, font=big, fg="#1a1a1a", bg="white", justify="left")
lbl_data.pack(pady=20)

lbl_warn = tk.Label(frame_main, font=med, fg="#c62828", bg="white")
lbl_warn.pack()

lbl_relay = tk.Label(frame_main, font=med, fg="#1565c0", bg="white")
lbl_relay.pack(pady=15)

def relay_status():
    return f"""
    EC MODE : {'ACTIVE' if ec_active else 'OFF'}
    pH MODE : {'ACTIVE' if ph_active else 'OFF'}
    
    EC1  : {'ON' if relay_ec1.is_active else 'OFF'}
    EC2  : {'ON' if relay_ec2.is_active else 'OFF'}
    pH   : {'ON' if relay_ph.is_active else 'OFF'}
    """

def manual_stop():
    all_relays_off()
    global ec_active, ph_active
    ec_active = False
    ph_active = False
    lbl_warn.config(text="🛑 MANUAL STOP")
    lbl_relay.config(text=relay_status())

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

tk.Button(footer, text="SETPOINTS", font=med, bg="#1565c0", fg="white", width=10,
          command=lambda: show(frame_set)).pack(side="left", padx=10, pady=10)

tk.Button(footer, text="STOP", font=med, bg="#c62828", fg="white", width=10,
          command=manual_stop).pack(side="left", padx=10, pady=10)

tk.Button(footer, text="RESTART", font=med, bg="#455a64", fg="white", width=10,
          command=restart_program).pack(side="left", padx=10, pady=10)

tk.Button(footer, text="EXIT", font=med, bg="#333333", fg="white", width=10,
          command=root.destroy).pack(side="right", padx=10, pady=10)

# SETPOINT SCREEN
tk.Label(frame_set, text="SYSTEM SETPOINTS", font=("Arial", 16, "bold"), fg="#1565c0", bg="white").pack(pady=10)

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
        save_setpoints()
        keypad_frame.pack_forget()
    except Exception:
        lbl_display.config(text="ERROR")

def cancel():
    keypad_frame.pack_forget()

def create_row(key):
    row = tk.Frame(frame_set, bg="white")
    row.pack(pady=4)
    tk.Label(row, text=key, font=med, fg="#1a1a1a", bg="white", width=10, anchor="w").pack(side="left")
    labels[key] = tk.Label(row, text=str(setpoints.get(key, "")), font=med, fg="#ef6c00", bg="#ffffff", width=8, relief="sunken")
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

# ==============================================================================
# MAIN CONTROL & TELEMETRY UPDATE LOOP
# ==============================================================================
def update():
    try:
        data = read_sensor()
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ts_str = datetime.datetime.now(ist_tz).isoformat()

        if data:
            warn = control(data)
            ec_display = f"{data['ec']} mS/cm ({data.get('raw_ec', 0)} us/cm)"
            lbl_data.config(
                text=f"Temp  : {data['temp']} °C\nEC    : {ec_display}\npH    : {data['ph']}\nMoist : {data['moist']} %",
                fg="#1a1a1a"
            )
            lbl_warn.config(text="\n".join(warn) if warn else "")
            lbl_relay.config(text=relay_status())

            # Realtime Telemetry to Private Mosquitto Broker
            if is_mqtt_connected:
                try:
                    payload = dict(data)
                    payload["status"] = "online"
                    payload["device"] = DEVICE_NAME
                    payload["timestamp"] = ts_str
                    payload["relays"] = {
                        "ec1": relay_ec1.is_active,
                        "ec2": relay_ec2.is_active,
                        "ph":  relay_ph.is_active
                    }
                    control_client.publish(LIVE_TELEMETRY, json.dumps(payload), retain=False)
                    control_client.publish(STATUS_TOPIC, json.dumps({"status": "online", "device": DEVICE_NAME, "timestamp": ts_str}), retain=True)
                except Exception as pe:
                    print(f"⚠️ Telemetry publish note: {pe}")

            # Local buffer if offline
            save_local_telemetry(data)
        else:
            all_relays_off()
            lbl_data.config(text="⚠️ SENSOR ERROR", fg="#c62828")
            lbl_warn.config(text="Check connections / Serial Port")
            lbl_relay.config(text=relay_status())

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
                            "ph":  relay_ph.is_active
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
        print("✅ Background Native Bluetooth Setup Server started")
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


