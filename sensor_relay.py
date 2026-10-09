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

    try:
        from gpiozero.pins.lgpio import LGPIOFactory
        Device.pin_factory = LGPIOFactory()
        print("📌 GPIO Backend Active: LGPIOFactory (Raspberry Pi 5 / Debian Bookworm)")
        gpio_initialized = True
    except Exception:
        pass

    if not gpio_initialized:
        try:
            from gpiozero.pins.rpigpio import RPiGPIOFactory
            Device.pin_factory = RPiGPIOFactory()
            print("📌 GPIO Backend Active: RPiGPIOFactory (Raspberry Pi 4 / Pi 3)")
            gpio_initialized = True
        except Exception:
            pass

    if not gpio_initialized:
        try:
            from gpiozero.pins.native import NativeFactory
            Device.pin_factory = NativeFactory()
            print("📌 GPIO Backend Active: NativeFactory (Direct Hardware GPIO)")
            gpio_initialized = True
        except Exception:
            pass

    if not gpio_initialized:
        try:
            from gpiozero.pins.pigpio import PiGPIOFactory
            Device.pin_factory = PiGPIOFactory()
            print("📌 GPIO Backend Active: PiGPIOFactory (pigpiod Daemon)")
            gpio_initialized = True
        except Exception:
            pass

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
        def __init__(self, pin, active_high=True, initial_value=False):
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
    return "sensor1"

DEVICE_NAME = get_device_id()
print(f"📌 Device Identity Loaded: {DEVICE_NAME}")

SETPOINT_FILE = os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}.json")
print(f"📁 Using config file: {SETPOINT_FILE}")

OLD_FILE = os.path.join(BASE_DIR, "config.json")
if os.path.exists(OLD_FILE):
    try:
        os.remove(OLD_FILE)
        print("🗑️ Removed legacy config.json...")
    except Exception:
        pass

relay_temp_heater = OutputDevice(17, active_high=True, initial_value=False)
relay_temp_cooler = OutputDevice(22, active_high=True, initial_value=False)
relay_hum_maker   = OutputDevice(27, active_high=True, initial_value=False)
relay_hum_dehum   = OutputDevice(23, active_high=True, initial_value=False)

def all_relays_off():
    for r in [relay_temp_heater, relay_temp_cooler, relay_hum_maker, relay_hum_dehum]:
        try:
            r.off()
        except Exception:
            pass

all_relays_off()

temp_heater_active = False
temp_cooler_active = False
hum_maker_active   = False
hum_dehum_active   = False

setpoints = {
    "T MIN": 10.0,
    "T MAX": 30.0,
    "H MIN": 30.0,
    "H MAX": 80.0,
    "PORT": 1883
}

if os.path.exists(SETPOINT_FILE):
    try:
        with open(SETPOINT_FILE, "r") as f:
            loaded = json.load(f)
            setpoints.update(loaded)
    except Exception as e:
        print(f"⚠️ Error reading setpoints file: {e}")

def save_setpoints():
    try:
        with open(SETPOINT_FILE, "w") as f:
            json.dump(setpoints, f, indent=4)
        if 'control_client' in globals() and is_mqtt_connected:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
            print("📤 Pushed setpoints to Private Cloud Broker.")
    except Exception as e:
        print(f"⚠️ Error saving setpoints: {e}")

instrument_sht = None
instrument_co2 = None

def init_sht():
    global instrument_sht
    try:
        if instrument_sht:
            try: instrument_sht.serial.close()
            except Exception: pass
        instrument_sht = minimalmodbus.Instrument("/dev/ttyUSB0", 1)
        instrument_sht.serial.baudrate = 9600
        instrument_sht.serial.timeout = 0.5
        print("✅ SHT20 (USB0) System Refreshed")
    except Exception:
        instrument_sht = None
        print("⚠️ SHT20 (USB0) not found. Waiting...")

def init_co2():
    global instrument_co2
    try:
        if instrument_co2:
            try: instrument_co2.serial.close()
            except Exception: pass
        instrument_co2 = minimalmodbus.Instrument("/dev/ttyUSB1", 1)
        instrument_co2.serial.baudrate = 9600
        instrument_co2.serial.timeout = 0.5
        print("✅ CO2 (USB1) System Refreshed")
    except Exception:
        instrument_co2 = None
        print("⚠️ CO2 (USB1) not found. Waiting...")

def init_instruments():
    init_sht()
    init_co2()

init_instruments()

def read_sensor():
    data = {"temp": "N/A", "hum": "N/A", "co2": "N/A"}
    success = False

    # 1. Read SHT20 / MD02 Temperature & Humidity from USB0
    if instrument_sht:
        try:
            instrument_sht.serial.reset_input_buffer()
            # Standard SHT20 / XY-MD02 (FC4): Reg 1 = Temp, Reg 2 = Humidity
            data["temp"] = instrument_sht.read_register(1, 1, functioncode=4, signed=True)
            data["hum"]  = instrument_sht.read_register(2, 1, functioncode=4, signed=False)
            success = True
            print(f"DEBUG: USB0 OK (FC4) -> T:{data['temp']}°C H:{data['hum']}%")
        except Exception:
            # Fallback 1: FC3 (Holding Registers): Reg 1 = Temp, Reg 2 = Humidity
            try:
                data["temp"] = instrument_sht.read_register(1, 1, functioncode=3, signed=True)
                data["hum"]  = instrument_sht.read_register(2, 1, functioncode=3, signed=False)
                success = True
                print(f"DEBUG: USB0 OK (FC3) -> T:{data['temp']}°C H:{data['hum']}%")
            except Exception:
                # Fallback 2: Reg 0 = Humidity, Reg 1 = Temp (MD02 direct format)
                try:
                    for fc in [3, 4]:
                        raws = instrument_sht.read_registers(0, 2, functioncode=fc)
                        if raws and len(raws) >= 2:
                            data["hum"]  = round(raws[0] / 10.0, 1) if raws[0] > 100 else round(float(raws[0]), 1)
                            data["temp"] = round(raws[1] / 10.0, 1) if raws[1] > 100 else round(float(raws[1]), 1)
                            success = True
                            print(f"DEBUG: USB0 OK (Reg 0/1 FC{fc}) -> T:{data['temp']}°C H:{data['hum']}%")
                            break
                except Exception:
                    pass

        if not success:
            print("DEBUG: USB0 Read Empty. Refreshing Port...")
            init_sht()

    # --- 0.5s DELAY GAP ---
    time.sleep(0.5)

    # 2. Read CO2 from USB1
    if instrument_co2:
        co2_found = False
        try:
            instrument_co2.serial.reset_input_buffer()
            for reg in [0, 2, 4, 5]:
                for func in [3, 4]:
                    try:
                        val = instrument_co2.read_register(reg, 0, functioncode=func, signed=False)
                        if val > 0 and val != 999:
                            data["co2"] = val
                            co2_found = True
                            success = True
                            print(f"DEBUG: USB1 OK -> CO2:{val} ppm")
                            break
                    except Exception:
                        continue
                if co2_found:
                    break
            
            if not co2_found:
                print("DEBUG: USB1 Read Empty. Refreshing Port...")
                init_co2()
        except Exception:
            print("DEBUG: USB1 Error. Refreshing Port...")
            init_co2()

    time.sleep(0.2)

    if success:
        return data
    return None

def control(data):
    global temp_heater_active, temp_cooler_active, hum_maker_active, hum_dehum_active
    msgs = []

    t = data["temp"] if isinstance(data, dict) else "N/A"
    h = data["hum"] if isinstance(data, dict) else "N/A"

    if t == "N/A" or h == "N/A" or t is None or h is None:
        return msgs

    t_min = float(setpoints.get("T MIN", 10.0))
    t_max = float(setpoints.get("T MAX", 30.0))
    h_min = float(setpoints.get("H MIN", 30.0))
    h_max = float(setpoints.get("H MAX", 80.0))

    print(f"DEBUG: Testing AC Logic: Current T={t}, T_MAX={t_max}, T_MIN={t_min}, CurrentState={'ACTIVE' if temp_cooler_active else 'OFF'}")
    if t >= t_max:
        if not temp_cooler_active:
            print("TURNING ON Fanpad")
            relay_temp_cooler.on()
            temp_cooler_active = True
        msgs.append("Fanpad: RUNNING")
    elif t <= t_min:
        if temp_cooler_active:
            print("TURNING OFF Fanpad")
            relay_temp_cooler.off()
            temp_cooler_active = False
        msgs.append("Fanpad: STANDBY")
    else:
        if temp_cooler_active:
            msgs.append("Fanpad: RUNNING")
        else:
            msgs.append("Fanpad: STANDBY")

    print(f"DEBUG: Testing FanPad Logic: Current H={h}, H_MAX={h_max}, H_MIN={h_min}, CurrentState={'ACTIVE' if hum_dehum_active else 'OFF'}")
    if h >= h_max:
        if not hum_dehum_active:
            print("TURNING ON Humidifier")
            relay_hum_dehum.on()
            hum_dehum_active = True
        msgs.append("Humidifier: RUNNING")
    elif h <= h_min:
        if hum_dehum_active:
            print("TURNING OFF Humidifier")
            relay_hum_dehum.off()
            hum_dehum_active = False
        msgs.append("Humidifier: STANDBY")
    else:
        if hum_dehum_active:
            msgs.append("Humidifier: RUNNING")
        else:
            msgs.append("Humidifier: STANDBY")

    relay_temp_heater.off()
    temp_heater_active = False
    relay_hum_maker.off()
    hum_maker_active = False

    return msgs

    return msgs

CONTROL_BROKER = "147.93.106.142"
CONTROL_PORT   = 1883
CONTROL_USER   = "Inhydro@5598"
CONTROL_PASS   = "MGPL@5598"

CONTROL_TOPIC      = f"inhydro/{DEVICE_NAME}/setpoints/update"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"
CONTROL_CMD_TOPIC  = f"inhydro/{DEVICE_NAME}/command"
TELEMETRY_TOPIC    = f"inhydro/{DEVICE_NAME}/telemetry/live"
STATUS_TOPIC       = f"inhydro/{DEVICE_NAME}/status"

is_mqtt_connected = False
control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, f"SensorRelay_{DEVICE_NAME}_{int(time.time())}")
control_client.will_set(STATUS_TOPIC, json.dumps({"status": "offline", "device": DEVICE_NAME}), qos=1, retain=True)

def on_control_message(client, userdata, msg):
    global setpoints
    try:
        topic = msg.topic
        payload_str = msg.payload.decode('utf-8', errors='ignore').strip()

        if topic == CONTROL_SYNC_TOPIC:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
            print(" [MQTT] Broadcasted current setpoints upon request.")
            return

        if topic == CONTROL_CMD_TOPIC:
            try:
                cmd_data = json.loads(payload_str)
                action = cmd_data.get("action") or cmd_data.get("command")
                if action == "RESTART":
                    root.after(1000, restart_program)
                elif action == "STOP":
                    root.after(0, manual_stop)
            except Exception:
                pass
            return

        new_data = json.loads(payload_str)
        if not isinstance(new_data, dict):
            return

        key_map = {
            "tMin": "T MIN", "tMax": "T MAX",
            "hMin": "H MIN", "hMax": "H MAX",
            "t_min": "T MIN", "t_max": "T MAX",
            "h_min": "H MIN", "h_max": "H MAX",
            "TEMP MIN": "T MIN", "TEMP MAX": "T MAX",
            "HUMI MIN": "H MIN", "HUMI MAX": "H MAX",
            "temp_min": "T MIN", "temp_max": "T MAX",
            "humi_min": "H MIN", "humi_max": "H MAX"
        }

        updated = False
        for k, v in new_data.items():
            mapped_key = key_map.get(k, k)
            if mapped_key in setpoints:
                try:
                    num_val = float(v)
                    setpoints[mapped_key] = num_val
                    if mapped_key == "T MIN": setpoints["TEMP MIN"] = num_val
                    elif mapped_key == "T MAX": setpoints["TEMP MAX"] = num_val
                    elif mapped_key == "H MIN": setpoints["HUMI MIN"] = num_val
                    elif mapped_key == "H MAX": setpoints["HUMI MAX"] = num_val
                    updated = True
                except (ValueError, TypeError):
                    setpoints[mapped_key] = v
                    updated = True

        if updated:
            save_setpoints()
            print("✅ [MQTT] Setpoints updated via Private Broker:", setpoints)

            def update_ui():
                if 'labels' in globals():
                    for k in ["T MIN", "T MAX", "H MIN", "H MAX"]:
                        if k in labels:
                            labels[k].config(text=str(setpoints.get(k, "")))
            try:
                root.after(0, update_ui)
            except Exception:
                pass

    except Exception as e:
        print(f"❌ [MQTT] Error processing payload: {e}")

def on_control_connect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        print(f"✅ Connected to Private Mosquitto Broker ({CONTROL_BROKER}:{CONTROL_PORT})")
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(CONTROL_SYNC_TOPIC)
        client.subscribe(CONTROL_CMD_TOPIC)
        client.publish(STATUS_TOPIC, json.dumps({"status": "online", "device": DEVICE_NAME}), retain=True)
        client.publish(TELEMETRY_TOPIC, json.dumps({"status": "online", "device": DEVICE_NAME, "heartbeat": True}), retain=False)
        client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
    else:
        is_mqtt_connected = False
        print(f"⚠️ Private MQTT connection failed: rc={rc}")

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

LOG_DIR = os.path.join(BASE_DIR, "local_logs")
ACTIVE_LOG_FILE = os.path.join(LOG_DIR, "active.jsonl")
local_log_lock = threading.Lock()
last_local_save_time = 0

def save_local_telemetry(data):
    global last_local_save_time
    if is_mqtt_connected:
        return

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
            except Exception:
                pass

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
                            control_client.publish(TELEMETRY_TOPIC, json.dumps(r), qos=1)
                            time.sleep(0.02)
                        except Exception:
                            break
        except Exception as e:
            print(f"⚠️ Sync worker exception: {e}")
        time.sleep(20)

def set_wifi(ssid, password):
    try:
        ssid = str(ssid).strip()
        password = str(password).strip()
        if not ssid:
            return "FAILED: Empty SSID"
        try:
            subprocess.run(['sudo', 'rfkill', 'unblock', 'wifi'], capture_output=True, timeout=3)
            subprocess.run(['sudo', 'nmcli', 'radio', 'wifi', 'on'], capture_output=True, timeout=3)
        except Exception:
            pass
        cmd = ['sudo', 'nmcli', '--wait', '15', 'device', 'wifi', 'connect', ssid]
        if password:
            cmd += ['password', password]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=18)
        if res.returncode == 0:
            return f"SUCCESS: Connected to '{ssid}'!"
        return f"FAILED: {res.stderr.strip() or res.stdout.strip() or 'Connection failed'}"
    except Exception as e:
        return f"ERROR: {str(e)}"

def scan_wifi():
    try:
        command = ['sudo', 'nmcli', '-t', '-f', 'SSID', 'dev', 'wifi']
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            names = sorted(list(set([n.strip() for n in result.stdout.split('\n') if n.strip()])))
            if not names:
                return "No networks found."
            return "\r\n--- NEARBY NETWORKS ---\r\n" + "\r\n".join(f"{i+1}. {n}" for i, n in enumerate(names))
        return f"SCAN FAILED: {result.stderr.strip()}"
    except Exception as e:
        return f"SCAN ERROR: {str(e)}"

def auto_trust_devices():
    try:
        btctl = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        btctl.stdin.write("agent NoInputNoOutput\ndefault-agent\ndiscoverable on\npairable on\n")
        btctl.stdin.flush()
    except Exception:
        pass
    while True:
        try:
            out = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True)
            for line in out.split('\n'):
                if line.startswith('Device '):
                    mac = line.split(" ")[1]
                    os.system(f"sudo bluetoothctl trust {mac} >/dev/null 2>&1")
        except Exception:
            pass
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
                client_sock.send(f"\r\n--- INHYDRO ENVIRONMENTAL SENSOR ({DEVICE_NAME}) ---\r\nCommands: WIFI:SSID:PASS | ID:NEW_NAME | SCAN\r\n".encode('utf-8'))
                while True:
                    data = client_sock.recv(1024)
                    if not data:
                        break
                    msg = data.decode('utf-8', errors='ignore').strip()
                    if msg.startswith("WIFI:"):
                        parts = msg.split(":")
                        if len(parts) >= 3:
                            client_sock.send(f"{set_wifi(parts[1], ':'.join(parts[2:]))}\r\n".encode('utf-8'))
                    elif msg.startswith("ID:"):
                        nid = msg.split(":")[1].strip()
                        if nid:
                            with open(ID_FILE, "w") as f:
                                f.write(nid)
                            client_sock.send(f"\r\nDevice ID set to {nid}. Rebooting...\r\n".encode('utf-8'))
                            root.after(2000, restart_program)
                    elif msg.upper() == "SCAN":
                        client_sock.send((scan_wifi() + "\r\n").encode('utf-8'))
            except Exception:
                pass
            finally:
                if 'client_sock' in locals():
                    client_sock.close()
    except Exception:
        pass

root = tk.Tk()
root.update()
root.attributes("-fullscreen", True)
root.configure(bg="white")
root.bind("<Escape>", lambda e: root.destroy())

lbl_clock = tk.Label(root, text="", font=("Arial", 12, "bold"), fg="#1565c0", bg="white", justify="left")
lbl_clock.place(x=15, y=10, anchor="nw")

def update_clock():
    now = datetime.datetime.now()
    date_str = now.strftime("%d %b %Y (%A)")
    time_str = now.strftime("%I:%M:%S %p")
    lbl_clock.config(text=f"{date_str}\n{time_str}")
    root.after(1000, update_clock)

update_clock()

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
    if lbl_logo is not None:
        lbl_logo.lift()
    if 'lbl_clock' in globals():
        lbl_clock.lift()

show(frame_main)

lbl_data = tk.Label(frame_main, font=big, fg="#1a1a1a", bg="white", justify="left")
lbl_data.pack(pady=20)

lbl_warn = tk.Label(frame_main, font=med, fg="#c62828", bg="white")
lbl_warn.pack()

lbl_relay = tk.Label(frame_main, font=med, fg="#1565c0", bg="white")
lbl_relay.pack(pady=15)

def relay_status():
    return f"""
    FANPAD / COOLER : {'ON' if relay_temp_cooler.is_active else 'OFF'}
    DEHUMIDIFIER     : {'ON' if relay_hum_dehum.is_active else 'OFF'}
    """

def manual_stop():
    all_relays_off()
    global temp_cooler_active, hum_dehum_active
    temp_cooler_active = False
    hum_dehum_active = False
    lbl_warn.config(text="🛑 CLIMATE RELAYS STOPPED")
    lbl_relay.config(text=relay_status())

def restart_program():
    manual_stop()
    if instrument_sht:
        try: instrument_sht.serial.close()
        except Exception: pass
    if instrument_co2:
        try: instrument_co2.serial.close()
        except Exception: pass
    os.execl(sys.executable, sys.executable, *sys.argv)

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
        
        alias_map = {
            "T MIN": "TEMP MIN",
            "TEMP MIN": "T MIN",
            "T MAX": "TEMP MAX",
            "TEMP MAX": "T MAX",
            "H MIN": "HUMI MIN",
            "HUMI MIN": "H MIN",
            "H MAX": "HUMI MAX",
            "HUMI MAX": "H MAX"
        }
        if selected_key in alias_map:
            setpoints[alias_map[selected_key]] = value

        if selected_key in labels:
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

create_row("T MIN")
create_row("T MAX")
create_row("H MIN")
create_row("H MAX")

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

footer_set = tk.Frame(frame_set, bg="#eeeeee", height=60)
footer_set.pack(side="bottom", fill="x")
footer_set.pack_propagate(False)

tk.Button(footer_set, text="SAVE & RETURN", font=med, bg="#1565c0", fg="white", width=18,
          command=lambda: (save_setpoints(), show(frame_main))).pack(pady=10)

sensor_retry_counter = 0
last_good_reading = None

def update():
    global sensor_retry_counter, last_good_reading
    try:
        data = read_sensor()
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ts_str = datetime.datetime.now(ist_tz).isoformat()

        if data:
            sensor_retry_counter = 0
            last_good_reading = data
            warn = control(data)
            t_str   = f"{data['temp']} °C" if data.get('temp') not in [None, "N/A"] else "N/A"
            h_str   = f"{data['hum']} %"   if data.get('hum') not in [None, "N/A"] else "N/A"
            co2_str = f"{data['co2']} ppm" if data.get('co2') not in [None, "N/A"] else "N/A"

            lbl_data.config(
                text=f"Room Temp  : {t_str}\nRoom Humi  : {h_str}\nRoom CO2   : {co2_str}",
                fg="#1a1a1a"
            )
            lbl_warn.config(text="\n".join(warn) if warn else "")
            lbl_relay.config(text=relay_status())

            if is_mqtt_connected:
                try:
                    payload = dict(data)
                    payload["status"] = "online"
                    payload["device"] = DEVICE_NAME
                    payload["timestamp"] = ts_str
                    payload["relays"] = {
                        "cooler": relay_temp_cooler.is_active,
                        "dehum":  relay_hum_dehum.is_active
                    }
                    control_client.publish(TELEMETRY_TOPIC, json.dumps(payload), retain=False)
                    control_client.publish(STATUS_TOPIC, json.dumps({"status": "online", "device": DEVICE_NAME, "timestamp": ts_str}), retain=True)
                except Exception as pe:
                    print(f"⚠️ Telemetry publish note: {pe}")

            save_local_telemetry(data)
        else:
            sensor_retry_counter += 1
            if sensor_retry_counter <= 3 and last_good_reading is not None:
                warn = control(last_good_reading)
                lbl_warn.config(text="⚠ SENSOR RETRYING..." + ("\n" + "\n".join(warn) if warn else ""))
                lbl_relay.config(text=relay_status())
            else:
                all_relays_off()
                lbl_data.config(text="⚠️ SENSOR ERROR\nRoom CO2   : N/A", fg="#c62828")
                lbl_warn.config(text="Check connections / Serial Port")
                lbl_relay.config(text=relay_status())

            if is_mqtt_connected:
                try:
                    payload = {
                        "status": "online",
                        "device": DEVICE_NAME,
                        "timestamp": ts_str,
                        "sensor_error": True,
                        "temp": None,
                        "hum": None,
                        "co2": None,
                        "relays": {
                            "cooler": relay_temp_cooler.is_active,
                            "dehum":  relay_hum_dehum.is_active
                        }
                    }
                    control_client.publish(TELEMETRY_TOPIC, json.dumps(payload), retain=False)
                    control_client.publish(STATUS_TOPIC, json.dumps({"status": "online", "device": DEVICE_NAME, "timestamp": ts_str}), retain=True)
                except Exception as pe:
                    pass
    except Exception as e:
        print(f"⚠️ Update loop exception: {e}")

    root.after(2000, update)

def main():
    try:
        threading.Thread(target=auto_trust_devices, daemon=True).start()
    except Exception:
        pass

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
