import os, sys, json, time, datetime, socket, glob, fcntl
import subprocess, threading
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import font
import minimalmodbus
import serial
import paho.mqtt.client as mqtt


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                val = f.read().strip()
                if val: return val
        except Exception: pass
    return "monit" # Default fallback device identity

DEVICE_NAME = get_device_id()
print(f" Device Identity Loaded: {DEVICE_NAME}")

SETPOINT_FILE = os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}.json")
print(f" Using setpoint file: {SETPOINT_FILE}")

# Remove legacy config to prevent sync issues
OLD_FILE = os.path.join(BASE_DIR, "setpoints.json")
if os.path.exists(OLD_FILE):
    try:
        os.remove(OLD_FILE)
        print(" Removed legacy setpoints.json...")
    except Exception: pass

# Strict Fixed Persistent Serial By-Path Links (Zero /dev/ttyUSB* fallback)
SERIAL_PORT_WATER = "/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.0-port0"  # Dedicated Combined EC & pH Port
SERIAL_PORT_EC    = SERIAL_PORT_WATER
SERIAL_PORT_PH    = SERIAL_PORT_WATER
SERIAL_PORT_MD02  = "/dev/serial/by-path/pci-0000:00:14.0-usb-0:4:1.0-port0"
SERIAL_PORT_RELAY = "/dev/serial/by-path/pci-0000:00:14.0-usb-0:1:1.0-port0"

DEVICE_ID_EC   = 31
DEVICE_ID_PH   = 32
DEVICE_ID_MD02 = 1

RELAY_SLAVE_ID = 1

import queue
relay_cmd_queue = queue.Queue()

def relay_worker_loop():
    while True:
        try:
            cmd = relay_cmd_queue.get()
            if cmd is None: break
            channel, state = cmd

            inst = None
            try:
                inst = minimalmodbus.Instrument(SERIAL_PORT_RELAY, RELAY_SLAVE_ID)
                inst.serial.baudrate = 9600
                inst.serial.timeout = 0.2
                inst.mode = minimalmodbus.MODE_RTU
                inst.clear_buffers_before_each_transaction = True
                inst.write_bit(channel, 1 if state else 0, functioncode=5)
            except Exception as e:
                print(f"⚠️ Relay Write Error on {SERIAL_PORT_RELAY}: {e}")
            finally:
                if inst and hasattr(inst, 'serial') and inst.serial and getattr(inst.serial, 'is_open', False):
                    try: inst.serial.close()
                    except Exception: pass
            relay_cmd_queue.task_done()
        except Exception:
            pass

threading.Thread(target=relay_worker_loop, daemon=True).start()

def send_modbus_relay_cmd(channel, state):
    relay_cmd_queue.put((channel, state))
    return True

class ModbusRelay:
    def __init__(self, channel, name=""):
        self.channel = channel
        self.name = name
        self.is_active = False

    def on(self):
        self.is_active = True
        send_modbus_relay_cmd(self.channel, True)

    def off(self):
        self.is_active = False
        send_modbus_relay_cmd(self.channel, False)

# Modbus RTU Relays (Slave ID 1, Channels 0-12)
relay_ec1        = ModbusRelay(0, "EC1 ")
relay_ec2        = ModbusRelay(1, "EC2 ")
relay_ph         = ModbusRelay(2, "pH ")
relay_solenoid   = ModbusRelay(12, "S-Tank Solenoid")
relay_fan1       = ModbusRelay(3, "1. Fan ")
relay_fan2       = ModbusRelay(4, "2. Fan ")
relay_pad        = ModbusRelay(5, "Cooling Pad ")
relay_fogger     = ModbusRelay(6, "Fogger ")
relay_acf        = ModbusRelay(7, "Air Circulation Fan")
relay_sprinkler  = ModbusRelay(8, "Sprinkler")
relay_irrigation = ModbusRelay(9, "Irrigation ")
relay_timer1     = ModbusRelay(10, "Cyclic Timer 1")
relay_timer2     = ModbusRelay(11, "Cyclic Timer 2")

# Alias for backwards compatibility
relay_temp = relay_fan1
relay_humi = relay_fogger

def all_relays_off():
    for r in [relay_ec1, relay_ec2, relay_ph, relay_solenoid, relay_fan1, relay_fan2, relay_pad, relay_fogger, relay_acf, relay_sprinkler, relay_irrigation, relay_timer1, relay_timer2]:
        try: r.off()
        except: pass

all_relays_off()

ec_active      = False
ph_active      = False
solenoid_active = False
temp_active    = False
humi_active    = False
humi_logic_active = False

last_ec        = 0
last_ph        = 0
ec_start_time  = 0
ph_start_time  = 0

timer_state = {
    1: {"state": "OFF", "last": 0.0},
    2: {"state": "OFF", "last": 0.0},
    "humi": {"state": "OFF", "last": 0.0},
    "PAD": {"state": "OFF", "last": 0.0},
    "ACF": {"state": "OFF", "last": 0.0},
    "Sprinkler": {"state": "OFF", "last": 0.0},
    "Irrigation": {"state": "OFF", "last": 0.0}
}

# DEFAULT SETPOINTS
setpoints = {
    # Nutrients & pH
    "EC MIN": 1.2,
    "EC MAX": 1.8,
    "PH LOW": 5.8,
    "PH HIGH": 6.5,
    "S_TANK": 2.0,
    
    # Climate Control (MD02 Temp & Humidity)
    "TEMP MIN": 22.0,
    "TEMP MED": 25.0,
    "TEMP MAX": 28.0,
    "HUMI MIN": 50.0,
    "HUMI MAX": 70.0,
    "TEMP Hyst": 0.5,
    
    # Cooling Pad Pump
    "PAD Start": "06:00",
    "PAD Stop": "18:00",
    "PAD ON Min": 5,
    "PAD OFF Min": 15,

    # Air Circulation Fan (ACF)
    "ACF Name": "AIR CIRCULATION FAN",
    "ACF Start": "06:00",
    "ACF Stop": "22:00",
    "ACF ON Min": 10,
    "ACF OFF Min": 20,

    # Overhead Sprinkler
    "Sprinkler Name": " SPRINKLER",
    "Sprinkler Start": "08:00",
    "Sprinkler Stop": "17:00",
    "Sprinkler ON Min": 2,
    "Sprinkler OFF Min": 30,

    # Daytime Irrigation
    "Irrigation Name": " IRRIGATION",
    "Irrigation Start": "06:00",
    "Irrigation Stop": "18:00",
    "Irrigation ON Min": 15,
    "Irrigation OFF Min": 45,

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

    # Cyclic Timer 1 (Water Mixing Pump)
    "Timer1 Name": "WATER MIXING PUMP",
    "Timer1 Start": "06:00",
    "Timer1 Stop": "18:00",
    "Timer1 ON Min": 5,
    "Timer1 OFF Min": 15,
    
    # Cyclic Timer 2
    "Timer2 Name": "CYCLIC TIMER 2",
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
    except Exception:
        pass

# Legacy auto-migration from uS/cm (1200/1800)D to mS/cm (1.2/1.8)
if float(setpoints.get("EC MIN", 1.2)) > 100:
    setpoints["EC MIN"] = round(float(setpoints["EC MIN"]) / 1000.0, 2)
if float(setpoints.get("EC MAX", 1.8)) > 100:
    setpoints["EC MAX"] = round(float(setpoints["EC MAX"]) / 1000.0, 2)

def save_setpoints():
    try:
        with open(SETPOINT_FILE, "w") as f:
            json.dump(setpoints, f, indent=4)
        if 'control_client' in globals() and control_client.is_connected():
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
            print(" Pushed setpoints to cloud broker.")
    except Exception as e:
        print(f"Error saving setpoints: {e}")

def open_modbus_instrument(port, slave_id, baudrate=9600):
    try:
        inst = minimalmodbus.Instrument(port, slave_id)
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

ec_instrument   = open_modbus_instrument(SERIAL_PORT_EC, DEVICE_ID_EC)
ph_instrument   = open_modbus_instrument(SERIAL_PORT_PH, DEVICE_ID_PH)
md02_instrument = open_modbus_instrument(SERIAL_PORT_MD02, DEVICE_ID_MD02)

# Read Dedicated EC Meter (Slave ID 31 -> Reg 3) STRICTLY via SERIAL_PORT_WATER
def read_ec_meter():
    inst = None
    try:
        inst = minimalmodbus.Instrument(SERIAL_PORT_WATER, DEVICE_ID_EC)
        inst.serial.baudrate = 9600
        inst.serial.timeout = 0.3
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True

        for fc in [3, 4]:
            try:
                data = inst.read_registers(1, 3, functioncode=fc) # [55 (SP), 0 (HYSt), 643 (Live EC)]
                raw_ec = data[2] if len(data) >= 3 else inst.read_register(3, 0, functioncode=fc)
                ec_val = round(raw_ec / 1000.0, 3)
                return {"ec": ec_val, "raw_ec": raw_ec, "ph": None}
            except Exception:
                pass
    except Exception:
        pass
    finally:
        if inst and hasattr(inst, 'serial') and inst.serial and getattr(inst.serial, 'is_open', False):
            try: inst.serial.close()
            except Exception: pass
    return None

# Read Dedicated pH Meter (Slave ID 32 -> Reg 2) STRICTLY via SERIAL_PORT_WATER
def read_ph_meter():
    inst = None
    try:
        inst = minimalmodbus.Instrument(SERIAL_PORT_WATER, DEVICE_ID_PH)
        inst.serial.baudrate = 9600
        inst.serial.timeout = 0.3
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True

        for fc in [3, 4]:
            try:
                data = inst.read_registers(0, 3, functioncode=fc) # [580, 604, 790 (Live pH)]
                ph_raw = data[2]
                ph_val = round(ph_raw / 100.0, 2)
                return {"ph": ph_val}
            except Exception:
                pass
    except Exception:
        pass
    finally:
        if inst and hasattr(inst, 'serial') and inst.serial and getattr(inst.serial, 'is_open', False):
            try: inst.serial.close()
            except Exception: pass
    return None

# Combined Water Sensor Reader combining EC and pH meter readings
def read_water_sensor():
    ec_data = read_ec_meter()
    time.sleep(0.08)
    ph_data = read_ph_meter()

    if ec_data is not None or ph_data is not None:
        ec_val = ec_data["ec"] if (ec_data and "ec" in ec_data) else 0.0
        raw_ec = ec_data.get("raw_ec", 0) if ec_data else 0
        ph_val = ph_data["ph"] if (ph_data and "ph" in ph_data) else 0.0

        if ec_val > 0 or ph_val > 0:
            return {
                "ec": ec_val,
                "raw_ec": raw_ec,
                "ph": ph_val
            }
    return None

# Read MD02 Temperature & Humidity Transmitter (Slave ID 1) STRICTLY via SERIAL_PORT_MD02
def read_md02_sensor():
    inst = None
    try:
        inst = minimalmodbus.Instrument(SERIAL_PORT_MD02, DEVICE_ID_MD02)
        inst.serial.baudrate = 9600
        inst.serial.timeout = 0.2
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True

        for reg in [1, 0]:
            for fc in [4, 3]:
                try:
                    rt_raw = inst.read_register(reg, 0, signed=True, functioncode=fc)
                    rh_raw = inst.read_register(reg + 1, 0, functioncode=fc)
                    if rt_raw is not None and rh_raw is not None:
                        rt = round(rt_raw / 10.0, 1) if rt_raw > 100 else round(float(rt_raw), 1)
                        rh = round(rh_raw / 10.0, 1) if rh_raw > 100 else round(float(rh_raw), 1)
                        if -10 <= rt <= 75 and 0 <= rh <= 100:
                            return {"room_temp": rt, "room_humi": rh}
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        if inst and hasattr(inst, 'serial') and inst.serial and getattr(inst.serial, 'is_open', False):
            try: inst.serial.close()
            except Exception: pass
    return None

cached_water_data = None
cached_md02_data  = None

def sensor_polling_loop():
    global cached_water_data, cached_md02_data
    while True:
        try:
            cached_water_data = read_water_sensor()
        except Exception:
            cached_water_data = None

        try:
            cached_md02_data = read_md02_sensor()
        except Exception:
            cached_md02_data = None

        time.sleep(1.0)

# Launch non-blocking background sensor polling thread
threading.Thread(target=sensor_polling_loop, daemon=True).start()

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
control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, f"Monit_Device_{DEVICE_NAME}")
control_client.on_message = on_control_message

def on_control_connect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        client.subscribe(CONTROL_TOPIC)
        client.subscribe(CONTROL_SYNC_TOPIC)
        client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
        print(f" Connected to Private VPS Mosquitto Broker ({CONTROL_BROKER})")
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
    print(f" VPS Control MQTT Error: {e}")


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

def process_generic_cyclic_timer(prefix, relay_obj):
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

    if prefix not in timer_state:
        timer_state[prefix] = {"state": "OFF", "last": 0.0}

    ts = timer_state[prefix]
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

def process_cyclic_timer(timer_num, relay_obj):
    process_generic_cyclic_timer(f"Timer{timer_num}", relay_obj)

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
    else:
        ts["state"] = "OFF"
        ts["last"] = 0.0

    if room_humi is None:
        humi_logic_active = False
        status_msg = f"{mode} (SENSOR ERR)"
    elif room_humi >= h_max:
        humi_logic_active = False
        status_msg = f"{mode} (CUTOFF ≥{h_max:.0f}%)"
    elif room_humi <= h_min:
        humi_logic_active = True
        status_msg = f"{mode} ({ts['state']})"
    else:
        status_msg = f"{mode} ({ts['state']})"

    if in_window and ts["state"] == "ON" and humi_logic_active:
        relay_obj.on()
    else:
        relay_obj.off()

    return status_msg

_pad_humi_allowed = True

def control_system(water_data, md02_data):
    warnings = []
    global ec_active, ph_active, solenoid_active, temp_active, humi_active, last_ec, last_ph, ec_start_time, ph_start_time, _pad_humi_allowed

    now = time.time()
    # 1. WATER SENSOR DOSING LOGIC (EC & pH & S-Tank Solenoid)
    if water_data:
        ec_val = water_data["ec"]
        ph_val = water_data["ph"]

        ec_min = float(setpoints.get("EC MIN", 1.2))
        ec_max = float(setpoints.get("EC MAX", 1.8))
        ph_low = float(setpoints.get("PH LOW", 5.5))
        ph_high = float(setpoints.get("PH HIGH", 6.5))
        s_tank = float(setpoints.get("S_TANK", 2.0))

        # Solenoid Control: Turns ON when EC >= S_TANK, stays ON until EC <= EC_MIN
        if not solenoid_active and ec_val >= s_tank:
            solenoid_active = True
            relay_solenoid.on()
            warnings.append(f"S-TANK SOLENOID ON (EC >= {s_tank})")
        elif solenoid_active:
            if ec_val <= ec_min:
                solenoid_active = False
                relay_solenoid.off()
                warnings.append(f"S-TANK SOLENOID OFF (EC <= {ec_min})")
            else:
                relay_solenoid.on()
                warnings.append(f"S-TANK SOLENOID ACTIVE (EC: {ec_val})")
        else:
            relay_solenoid.off()

        # EC Control (Doses for max 60s, then waits 180s / 3 min for mixing before re-evaluating)
        if not ec_active and ec_val < ec_min:
            if now - last_ec >= 180 or last_ec == 0:
                ec_active = True
                ec_start_time = now
                relay_ec1.on()
                relay_ec2.on()
                last_ec = now
                warnings.append("EC LOW - DOSING EC1 & EC2")
            else:
                rem = int(180 - (now - last_ec))
                warnings.append(f"EC MIXING PAUSE ({rem}s remaining)")
        elif ec_active:
            if ec_val >= ec_max or (now - ec_start_time >= 60):
                ec_active = False
                relay_ec1.off()
                relay_ec2.off()
                last_ec = now
            else:
                relay_ec1.on()
                relay_ec2.on()
                warnings.append("EC DOSING ACTIVE")

        # pH Control (Doses for max 60s, then waits 180s / 3 min for mixing before re-evaluating)
        if not ph_active and ph_val > ph_high:
            if now - last_ph >= 180 or last_ph == 0:
                ph_active = True
                ph_start_time = now
                relay_ph.on()
                last_ph = now
                warnings.append("PH HIGH - DOSING PH MINUS")
            else:
                rem = int(180 - (now - last_ph))
                warnings.append(f"PH MIXING PAUSE ({rem}s remaining)")
        elif ph_active:
            if ph_val <= ph_low or (now - ph_start_time >= 60):
                ph_active = False
                relay_ph.off()
                last_ph = now
            else:
                relay_ph.on()
                warnings.append("PH DOSING ACTIVE")
    else:
        ec_active = False
        ph_active = False
        solenoid_active = False
        relay_ec1.off()
        relay_ec2.off()
        relay_ph.off()
        relay_solenoid.off()
        warnings.append("WATER SENSOR ERR - DOSING DISABLED")

    # 2. CLIMATE CONTROL (2-Stage Fan & Cooling Pad)
    if md02_data:
        room_temp = md02_data["room_temp"]
        room_humi = md02_data["room_humi"]

        t_min    = float(setpoints.get("TEMP MIN", 22.0))
        t_med    = float(setpoints.get("TEMP MED", 25.0))
        t_max    = float(setpoints.get("TEMP MAX", 28.0))
        t_buffer = float(setpoints.get("TEMP BUFFER", setpoints.get("TEMP Hyst", 0.5)))
        t_hyst   = t_buffer
        # Determine active Day vs Night humidity cutoff for Cooling Pad Safety Interlock
        d_start = str(setpoints.get("HUMI D_Start", "06:00"))
        d_stop  = str(setpoints.get("HUMI D_Stop", "18:00"))
        n_start = str(setpoints.get("HUMI N_Start", "18:00"))
        n_stop  = str(setpoints.get("HUMI N_Stop", "06:00"))

        cur_time = datetime.datetime.now().time()
        def _is_window_active(s_str, e_str):
            try:
                ts = datetime.datetime.strptime(s_str, "%H:%M").time()
                te = datetime.datetime.strptime(e_str, "%H:%M").time()
                if ts <= te: return (ts <= cur_time <= te)
                else: return (cur_time >= ts or cur_time <= te)
            except Exception:
                return False

        in_day_win   = _is_window_active(d_start, d_stop)
        in_night_win = _is_window_active(n_start, n_stop)

        if in_night_win and not in_day_win:
            h_max = float(setpoints.get("HUMI N_Max", 80.0))
        else:
            h_max = float(setpoints.get("HUMI D_Max", 75.0))

        h_buffer = float(setpoints.get("HUMI BUFFER", setpoints.get("HUMI Hyst", 2.0)))
        h_hyst   = h_buffer

        # 2-Stage Exhaust Fan Logic:
        # Rising (Heat Up): 
        #   - Fan 1 (1st Relay) turns ON at >= t_med
        #   - Fan 2 (2nd Relay) turns ON at >= t_max (Both ON)
        # Falling (Cool Down):
        #   - Fan 2 (2nd Relay) turns OFF at < (t_med - t_buffer)
        #   - Fan 1 (1st Relay) turns OFF at <= t_min
        
        # Fan 1 (1st Relay) State:
        if room_temp >= t_med:
            fan1_on = True
        elif room_temp <= t_min:
            fan1_on = False
        else:
            fan1_on = relay_fan1.is_active

        # Fan 2 (2nd Relay) State:
        if room_temp >= t_max:
            fan2_on = True
        elif room_temp < (t_med - t_buffer):
            fan2_on = False
        else:
            fan2_on = relay_fan2.is_active

        if fan1_on: relay_fan1.on()
        else: relay_fan1.off()

        if fan2_on: relay_fan2.on()
        else: relay_fan2.off()

        if fan1_on and fan2_on:
            warnings.append("TEMP HIGH (STAGE 2: ALL FANS ON)")
        elif fan1_on:
            warnings.append("TEMP MED (STAGE 1: FAN 1 ON)")

        # Cooling Pad Pump Automation + Humidity Safety Interlock with Hysteresis
        # Cutoff ON when room_humi >= h_max; Pad re-enabled when room_humi < (h_max - h_buffer)
        if room_humi >= h_max:
            _pad_humi_allowed = False
        elif room_humi < (h_max - h_buffer):
            _pad_humi_allowed = True

        pad_humi_allowed = _pad_humi_allowed

        if room_temp >= t_max and pad_humi_allowed:
            process_generic_cyclic_timer("PAD", relay_pad)
            if relay_pad.is_active:
                warnings.append("COOLING PAD PUMP ON")
        else:
            relay_pad.off()
            if not pad_humi_allowed:
                warnings.append("PAD CUTOFF (HUMIDITY HIGH)")
    else:
        relay_fan1.off()
        relay_fan2.off()
        relay_pad.off()
        warnings.append("ROOM SENSOR ERROR")

    # 3. FOGGER AUTOMATION (Day/Night + Humi Threshold)
    humi_mode = process_humi_day_night_timer(relay_fogger, md02_data["room_humi"] if md02_data else None)
    if relay_fogger.is_active:
        warnings.append(f"FOGGER ON ({humi_mode})")

    # 4. SOW CYCLIC TIMERS
    process_generic_cyclic_timer("ACF", relay_acf)
    process_generic_cyclic_timer("Sprinkler", relay_sprinkler)
    process_generic_cyclic_timer("Irrigation", relay_irrigation)
    process_cyclic_timer(1, relay_timer1)
    process_cyclic_timer(2, relay_timer2)

    return warnings

def manual_stop():
    all_relays_off()
    global ec_active, ph_active, solenoid_active, temp_active, humi_active, humi_logic_active
    ec_active = ph_active = solenoid_active = temp_active = humi_active = humi_logic_active = False
    for ts in timer_state.values():
        ts["state"] = "OFF"
        ts["last"] = 0.0
    if 'warn_box_frame' in globals():
        for child in warn_box_frame.winfo_children():
            child.destroy()
        tk.Label(warn_box_frame, text="MANUAL STOP ALL RELAYS", font=("Arial", 9, "bold"), fg="#dc2626", bg="#e0e0e0", anchor="w", justify="left").pack(anchor="w")

def restart_program():
    manual_stop()
    for inst in [ec_instrument, ph_instrument, md02_instrument]:
        if inst:
            try: inst.serial.close()
            except: pass
    os.execl(sys.executable, sys.executable, *sys.argv)

def set_wifi(ssid, password):
    try:
        subprocess.run(['nmcli', 'connection', 'delete', ssid], capture_output=True)
        command = ['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password]
        result = subprocess.run(command, capture_output=True, text=True)
        if "key-mgmt" in result.stderr:
            fallback_cmd = ['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password, 'wifi-sec.key-mgmt', 'wpa-psk']
            result_fallback = subprocess.run(fallback_cmd, capture_output=True, text=True)
            if result_fallback.returncode == 0:
                return f"SUCCESS: Connected to '{ssid}'!"
            else:
                return f"FAILED: {result_fallback.stderr.strip()}"
        if result.returncode == 0:
            return f"SUCCESS: Connected to '{ssid}'!"
        else:
            return f"FAILED: {result.stderr.strip()}"
    except Exception as e:
        return f"ERROR: {str(e)}"

def scan_wifi():
    try:
        command = ['nmcli', '-t', '-f', 'SSID,SIGNAL', 'dev', 'wifi', 'list']
        result = subprocess.run(command, capture_output=True, text=True, timeout=8)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            found = {}
            for line in lines:
                if ':' in line:
                    parts = line.rsplit(':', 1)
                    ssid = parts[0].strip()
                    sig = parts[1].strip()
                    if ssid and ssid not in found:
                        found[ssid] = sig
            if not found:
                return "\r\n[NO WIFI NETWORKS FOUND]\r\n"
            response = "\r\n--- NEARBY WIFI NETWORKS ---\r\n"
            for i, (ssid, sig) in enumerate(found.items(), 1):
                response += f"{i}. {ssid} ({sig}% Signal)\r\n"
            response += "\r\nUse command [4.] to connnect another wifi\r\n"
            return response
        else:
            return f"SCAN FAILED: {result.stderr.strip()}"
    except Exception as e:
        return f"SCAN ERROR: {str(e)}"

active_bt_fds = set()

def handle_bt_client_fd(fd_int):
    active_bt_fds.add(fd_int)
    try:
        print(f" 📱 Bluetooth Client Connected (FD: {fd_int})")
        welcome_msg = (
            "\r\n--- INHYDRO CONTROLLER MENU ---\r\n\r\n"
            #f"Device ID: {DEVICE_NAME}\r\n\r\n"
            "COMMAND MENU:\r\n"
            "1. PING\r\n"
            "2. SCAN\r\n"
            "3. STATUS\r\n"
            "4. WIFI:SSID:PASSWORD\r\n\r\n"
            #"5. ID:new_device_id\r\n\r\n"
        )
        os.write(fd_int, welcome_msg.encode('utf-8'))

        buf = ""
        while True:
            raw = os.read(fd_int, 1024)
            if not raw:
                print(f" 📱 Bluetooth Client Disconnected (FD: {fd_int})")
                break
            buf += raw.decode('utf-8', errors='ignore')

            lines = []
            while "\n" in buf or "\r" in buf:
                if "\r\n" in buf:
                    line, buf = buf.split("\r\n", 1)
                elif "\n" in buf:
                    line, buf = buf.split("\n", 1)
                else:
                    line, buf = buf.split("\r", 1)
                lines.append(line)

            if not lines and buf.strip():
                lines.append(buf)
                buf = ""

            for line in lines:
                text = line.strip()
                if not text: continue
                print(f" 📩 BT Received Command: '{text}'")

                if text.startswith("WIFI:") or text.startswith("4:"):
                    raw_cmd = text[5:] if text.startswith("WIFI:") else text[2:]
                    parts = raw_cmd.split(":")
                    if len(parts) >= 2:
                        ssid = parts[0].strip()
                        passw = ":".join(parts[1:]).strip()
                        os.write(fd_int, f"\r\nCONNECTING TO WIFI '{ssid}'...\r\n".encode('utf-8'))
                        resp = set_wifi(ssid, passw)
                        os.write(fd_int, f"\r\n{resp}\r\n\r\n".encode('utf-8'))
                    else:
                        os.write(fd_int, b"\r\nERROR: Format is WIFI:SSID:PASSWORD or 4:SSID:PASSWORD\r\n\r\n")
                elif text.startswith("ID:") or text.startswith("5:"):
                    raw_id = text[3:] if text.startswith("ID:") else text[2:]
                    new_id = raw_id.strip()
                    if new_id:
                        with open(ID_FILE, "w") as f: f.write(new_id)
                        os.write(fd_int, f"\r\nSUCCESS: Device ID set to {new_id}. Restarting...\r\n\r\n".encode('utf-8'))
                        root.after(2000, restart_program)
                elif text.upper() in ["SCAN", "2"]:
                    os.write(fd_int, b"\r\nSCANNING NEARBY WIFI NETWORKS...\r\n")
                    scan_res = scan_wifi()
                    os.write(fd_int, f"{scan_res}\r\n".encode('utf-8'))
                elif text.upper() in ["PING", "1"]:
                    os.write(fd_int, b"\r\nPONG - System Alive & Ready!\r\n\r\n")
                elif text.upper() in ["STATUS", "INFO", "3"]:
                    if cached_water_data:
                        w_ec = f"{cached_water_data.get('ec', 'SENSOR ERR')}"
                        w_ph = f"{cached_water_data.get('ph', 'SENSOR ERR')}"
                    else:
                        w_ec = "SENSOR ERR"
                        w_ph = "SENSOR ERR"

                    if cached_md02_data:
                        r_t = f"{cached_md02_data.get('room_temp', 'SENSOR ERR')} C"
                        r_h = f"{cached_md02_data.get('room_humi', 'SENSOR ERR')} %"
                    else:
                        r_t = "SENSOR ERR"
                        r_h = "SENSOR ERR"

                    st_msg = (
                        f"--- SYSTEM STATUS ---\r\n"
                        f"Water EC  : {w_ec}\r\n"
                        f"Water PH  : {w_ph}\r\n"
                        f"Room Temp : {r_t}\r\n"
                        f"Room Humi : {r_h}"
                    )
                    os.write(fd_int, f"\r\n{st_msg}\r\n\r\n".encode('utf-8'))
                else:
                    fallback_msg = f"\r\nACK: Received '{text}'\r\nCmds: 1.PING | 2.SCAN | 3.STATUS | 4.WIFI:SSID:PASS \r\n\r\n"
                    os.write(fd_int, fallback_msg.encode('utf-8'))
    except Exception as e:
        print(f" Bluetooth FD Exception: {e}")
    finally:
        active_bt_fds.discard(fd_int)
        try: os.close(fd_int)
        except: pass

def register_spp_dbus():
    global dbus_spp_active
    try:
        import sys, glob
        for path in glob.glob('/usr/lib/python3*/dist-packages'):
            if path not in sys.path:
                sys.path.append(path)
        import dbus, dbus.service
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib

        DBusGMainLoop(set_as_default=True)

        class BluetoothAgent(dbus.service.Object):
            @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
            def Release(self): pass

            @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
            def AuthorizeService(self, device, uuid): return

            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='s')
            def RequestPinCode(self, device): return '0000'

            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='u')
            def RequestPasskey(self, device): return dbus.UInt32(123456)

            @dbus.service.method('org.bluez.Agent1', in_signature='ouq', out_signature='')
            def DisplayPasskey(self, device, passkey, entered): pass

            @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
            def DisplayPinCode(self, device, pincode): pass

            @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='')
            def RequestConfirmation(self, device, passkey): return

            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
            def RequestAuthorization(self, device): return

            @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
            def Cancel(self): pass

        class BluezProfile(dbus.service.Object):
            @dbus.service.method('org.bluez.Profile1', in_signature='oha{sv}', out_signature='')
            def NewConnection(self, path, fd, properties):
                fd_int = fd.take()
                flags = fcntl.fcntl(fd_int, fcntl.F_GETFL)
                fcntl.fcntl(fd_int, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
                threading.Thread(target=handle_bt_client_fd, args=(fd_int,), daemon=True).start()

            @dbus.service.method('org.bluez.Profile1', in_signature='o', out_signature='')
            def RequestDisconnection(self, path): pass

        bus = dbus.SystemBus(mainloop=DBusGMainLoop())
        agent_path = '/inhydro/auto_agent'
        try:
            agent = BluetoothAgent(bus, agent_path)
            obj = bus.get_object('org.bluez', '/org/bluez')
            manager = dbus.Interface(obj, 'org.bluez.AgentManager1')
            manager.RegisterAgent(agent_path, 'NoInputNoOutput')
            manager.RequestDefaultAgent(agent_path)
            print(" ✅ Headless Auto-Pairing Bluetooth Agent Active (No PIN required)")
        except Exception:
            pass

        profile_path = '/inhydro/spp_profile'
        profile = BluezProfile(bus, profile_path)
        manager_p = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.ProfileManager1')
        opts = {
            'AutoConnect': dbus.Boolean(True),
            'Role': 'server',
            'Name': f'Inhydro_{DEVICE_NAME}',
            'Service': '00001101-0000-1000-8000-00805F9B34FB',
            'Channel': dbus.UInt16(1),
            'RequireAuthentication': dbus.Boolean(False),
            'RequireAuthorization': dbus.Boolean(False)
        }
        manager_p.RegisterProfile(profile_path, '00001101-0000-1000-8000-00805F9B34FB', opts)
        print(" ✅ DBus SPP Profile1 Registered with Full SDP Record!")

        # Spin GLib MainLoop in background thread to process DBus signals/methods
        mainloop = GLib.MainLoop()
        threading.Thread(target=mainloop.run, daemon=True).start()
        print(" ✅ GLib DBus Event Dispatcher Thread Started!")
        dbus_spp_active = True
    except Exception as e:
        print(f" Notice: DBus Bluetooth setup fallback: {e}")
        dbus_spp_active = False

def auto_trust_devices():
    try:
        subprocess.run(["bluetoothctl", "power", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "discoverable-timeout", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "pairable-timeout", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "discoverable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "pairable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception: pass

    while True:
        try:
            output = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True)
            for line in output.split('\n'):
                if line.startswith('Device '):
                    mac = line.split(" ")[1]
                    subprocess.run(["bluetoothctl", "trust", mac], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception: pass
        time.sleep(15)

def start_bluetooth_server():
    # Enforce Bluetooth Power, Discoverable and Pairable state via DBus Adapter
    try:
        import sys, glob
        for path in glob.glob('/usr/lib/python3*/dist-packages'):
            if path not in sys.path: sys.path.append(path)
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()
        adapter_obj = bus.get_object('org.bluez', '/org/bluez/hci0')
        adapter_props = dbus.Interface(adapter_obj, 'org.freedesktop.DBus.Properties')
        adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
        adapter_props.Set('org.bluez.Adapter1', 'Discoverable', dbus.Boolean(True))
        adapter_props.Set('org.bluez.Adapter1', 'Pairable', dbus.Boolean(True))
        adapter_props.Set('org.bluez.Adapter1', 'DiscoverableTimeout', dbus.UInt32(0))
        adapter_props.Set('org.bluez.Adapter1', 'PairableTimeout', dbus.UInt32(0))
        print(" ✅ Bluetooth Adapter Permanently Powered, Discoverable & Pairable (No Timeout)!")
    except Exception as e:
        print(f" Notice: Bluetooth adapter prop setup: {e}")

    register_spp_dbus()

    while True:
        time.sleep(3600)


LOG_DIR = os.path.join(BASE_DIR, "local_logs")
ACTIVE_LOG_FILE = os.path.join(LOG_DIR, "active.jsonl")
local_log_lock = threading.Lock()
last_local_save_time = 0

COLUMNS = [
    "timestamp", "temp", "moist", "ec", "ph",
    "room_temp", "room_humi", "timer1", "timer2",
    "relay_temp", "relay_humi", "relay_ec1", "relay_ec2",
    "relay_ph", "relay_solenoid", "relay_fan1", "relay_fan2", "relay_pad",
    "relay_fogger", "relay_acf", "relay_sprinkler", "relay_irrigation"
]

def publish_live_telemetry(water_data, md02_data):
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
            "relay_humi": relay_humi.is_active,
            "relay_ec1": relay_ec1.is_active,
            "relay_ec2": relay_ec2.is_active,
            "relay_ph": relay_ph.is_active,
            "relay_solenoid": relay_solenoid.is_active,
            "relay_fan1": relay_fan1.is_active,
            "relay_fan2": relay_fan2.is_active,
            "relay_pad": relay_pad.is_active,
            "relay_fogger": relay_fogger.is_active,
            "relay_acf": relay_acf.is_active,
            "relay_sprinkler": relay_sprinkler.is_active,
            "relay_irrigation": relay_irrigation.is_active
        }
        control_client.publish(f"inhydro/{DEVICE_NAME}/telemetry/live", json.dumps(payload), retain=False)
        control_client.publish(f"inhydro/{DEVICE_NAME}/room1/telemetry/live", json.dumps(payload), retain=False)
    except Exception as e:
        pass

def save_local_telemetry(water_data, md02_data):
    global last_local_save_time
    try: connected = is_mqtt_connected and control_client.is_connected()
    except: connected = False

    # Store locally ONLY when device is disconnected from cloud broker
    if connected:
        return

    cur_time = time.time()
    if cur_time - last_local_save_time < 1:
        return

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
        1 if relay_timer1.is_active else 0,
        1 if relay_timer2.is_active else 0,
        1 if relay_temp.is_active else 0,
        1 if relay_humi.is_active else 0,
        1 if relay_ec1.is_active else 0,
        1 if relay_ec2.is_active else 0,
        1 if relay_ph.is_active else 0,
        1 if relay_solenoid.is_active else 0,
        1 if relay_fan1.is_active else 0,
        1 if relay_fan2.is_active else 0,
        1 if relay_pad.is_active else 0,
        1 if relay_fogger.is_active else 0,
        1 if relay_acf.is_active else 0,
        1 if relay_sprinkler.is_active else 0,
        1 if relay_irrigation.is_active else 0
    ]

    last_local_save_time = cur_time

    # Non-blocking lock acquire to prevent thread stacking / app freezing
    if not local_log_lock.acquire(blocking=False):
        return

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        write_header = not os.path.exists(ACTIVE_LOG_FILE) or os.path.getsize(ACTIVE_LOG_FILE) == 0
        with open(ACTIVE_LOG_FILE, "a") as f:
            if write_header:
                f.write(json.dumps(COLUMNS) + "\n")
            f.write(json.dumps(row) + "\n")

        # Rotate file if active log exceeds ~1.5MB (10,000 entries)
        if os.path.exists(ACTIVE_LOG_FILE) and os.path.getsize(ACTIVE_LOG_FILE) > 1500000:
            rot_name = os.path.join(LOG_DIR, f"log_{int(time.time())}.jsonl")
            os.rename(ACTIVE_LOG_FILE, rot_name)
    except Exception as e:
        print(f"Offline log save error: {e}")
    finally:
        local_log_lock.release()

def unpack_row(r):
    if not isinstance(r, list) or len(r) < 7:
        return None
    return {
        "device": DEVICE_NAME,
        "timestamp": r[0],
        "temp": r[1] if len(r) > 1 else None,
        "moist": r[2] if len(r) > 2 else None,
        "ec": r[3] if len(r) > 3 else None,
        "ph": r[4] if len(r) > 4 else None,
        "room_temp": r[5] if len(r) > 5 else None,
        "room_humi": r[6] if len(r) > 6 else None,
        "timer1": bool(r[7]) if len(r) > 7 and r[7] is not None else False,
        "timer2": bool(r[8]) if len(r) > 8 and r[8] is not None else False,
        "relay_temp": bool(r[9]) if len(r) > 9 and r[9] is not None else False,
        "relay_humi": bool(r[10]) if len(r) > 10 and r[10] is not None else False,
        "relay_ec1": bool(r[11]) if len(r) > 11 and r[11] is not None else False,
        "relay_ec2": bool(r[12]) if len(r) > 12 and r[12] is not None else False,
        "relay_ph": bool(r[13]) if len(r) > 13 and r[13] is not None else False,
        "relay_solenoid": bool(r[14]) if len(r) > 14 and r[14] is not None else False,
        "relay_fan1": bool(r[15]) if len(r) > 15 and r[15] is not None else False,
        "relay_fan2": bool(r[16]) if len(r) > 16 and r[16] is not None else False,
        "relay_pad": bool(r[17]) if len(r) > 17 and r[17] is not None else False,
        "relay_fogger": bool(r[18]) if len(r) > 18 and r[18] is not None else False,
        "relay_acf": bool(r[19]) if len(r) > 19 and r[19] is not None else False,
        "relay_sprinkler": bool(r[20]) if len(r) > 20 and r[20] is not None else False,
        "relay_irrigation": bool(r[21]) if len(r) > 21 and r[21] is not None else False
    }

def sync_offline_data_worker():
    while True:
        try:
            try: connected = is_mqtt_connected and control_client.is_connected()
            except: connected = False

            if connected and os.path.exists(LOG_DIR):
                files = [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl") or f == "active.jsonl"]
                if "active.jsonl" in files and os.path.exists(ACTIVE_LOG_FILE) and os.path.getsize(ACTIVE_LOG_FILE) > 0:
                    with local_log_lock:
                        rot_name = os.path.join(LOG_DIR, f"log_{int(time.time())}.jsonl")
                        try: os.rename(ACTIVE_LOG_FILE, rot_name)
                        except: pass
                    files = [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl")]

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
                        try: os.remove(fpath)
                        except: pass
                        continue

                    print(f"[OfflineSync] Syncing segment {fname} with {len(rows)} entries...")
                    remaining_rows = list(rows)
                    success = True

                    batch_size = 500
                    for idx in range(0, len(rows), batch_size):
                        batch = rows[idx:idx+batch_size]

                        try: conn = is_mqtt_connected and control_client.is_connected()
                        except: conn = False
                        if not conn:
                            print("[OfflineSync] Connection lost during sync. Pausing.")
                            success = False
                            break

                        batch_payload = []
                        for row in batch:
                            entry = unpack_row(row)
                            if entry: batch_payload.append(entry)

                        try:
                            if batch_payload:
                                control_client.publish(f"inhydro/{DEVICE_NAME}/telemetry/live", json.dumps(batch_payload), qos=1)
                                control_client.publish(f"inhydro/{DEVICE_NAME}/room1/telemetry/live", json.dumps(batch_payload), qos=1)
                            time.sleep(0.05)
                        except Exception as pe:
                            print(f"[OfflineSync] Publish batch failed: {pe}")
                            success = False
                            break

                        remaining_rows = remaining_rows[len(batch):]

                    # Update or remove the log segment file
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


root = tk.Tk()
root.update()
root.attributes("-fullscreen", True)
root.configure(bg="#ffffff")
root.bind("<Escape>", lambda e: root.destroy())

FONT_BIG   = ("Arial", 14, "bold")
FONT_MED   = ("Arial", 11, "bold")
FONT_SML   = ("Arial", 10, "bold")
FONT_TINY  = ("Arial", 9)

frame_main = tk.Frame(root, bg="#ffffff")
frame_set  = tk.Frame(root, bg="#ffffff")

def show(frame):
    frame_main.pack_forget()
    frame_set.pack_forget()
    frame.pack(fill="both", expand=True)
    try:
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"{sw}x{sh}+0+0")
        root.attributes("-fullscreen", True)
        root.focus_force()
    except Exception:
        pass
    if 'lbl_logo' in globals():
        lbl_logo.lift()
    if 'lbl_clock' in globals():
        lbl_clock.lift()

show(frame_main)

# LOGO & CLOCK HEADER
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
try:
    logo_img_raw = Image.open(LOGO_PATH).resize((130, 85), Image.LANCZOS)
    logo_img = ImageTk.PhotoImage(logo_img_raw)
    lbl_logo = tk.Label(root, image=logo_img, bg="#ffffff")
    lbl_logo.image = logo_img
    lbl_logo.place(relx=0.98, y=6, anchor="ne")
except Exception:
    lbl_logo = tk.Label(root, text="INHYDRO", fg="#1565c0", bg="#ffffff", font=("Arial", 14, "bold"))
    lbl_logo.place(relx=0.98, y=6, anchor="ne")

lbl_clock = tk.Label(root, text="", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff", justify="left")
lbl_clock.place(x=10, y=8, anchor="nw")


tk.Label(frame_main, text=f"MONNET GROUP FARM AUTOMATION", font=FONT_BIG, fg="#1565c0", bg="#ffffff").pack(pady=(4, 2))

# Pack Footer FIRST at bottom with increased height
footer_main = tk.Frame(frame_main, bg="#ffffff", height=45)
footer_main.pack(side="bottom", fill="x", pady=4)
footer_main.pack_propagate(False)

tk.Button(footer_main, text="SETPOINTS", font=FONT_MED, bg="#0284c7", fg="white", width=12, command=lambda: request_setpoints_access()).pack(side="left", padx=10, pady=3)
tk.Button(footer_main, text="STOP", font=FONT_MED, bg="#dc2626", fg="white", width=10, command=manual_stop).pack(side="left", padx=10, pady=3)
tk.Button(footer_main, text="RESTART", font=FONT_MED, bg="#64748b", fg="white", width=10, command=restart_program).pack(side="left", padx=10, pady=3)
tk.Button(footer_main, text="EXIT", font=FONT_MED, bg="#334155", fg="white", width=10, command=root.destroy).pack(side="right", padx=10, pady=3)

content_grid = tk.Frame(frame_main, bg="#ffffff")
content_grid.pack(expand=True, fill="both", padx=10, pady=(63, 6))

# Column 1 (LEFT COLUMN - SENSORS DATA)
col_sensors = tk.Frame(content_grid, bg="#e0e0e0")
col_sensors.pack(side="left", fill="both", expand=True, padx=4)

# Section 1: Water Sensor
tk.Label(col_sensors, text="WATER SENSOR", font=("Arial", 11, "bold"), fg="#1565c0", bg="#e0e0e0").pack(anchor="w", pady=(4, 1))

def create_sensor_row(parent, label_text, is_ec=False):
    f = tk.Frame(parent, bg="#e0e0e0")
    f.pack(fill="x", pady=1)
    tk.Label(f, text=label_text, font=FONT_SML, fg="#333333", bg="#e0e0e0", width=11, anchor="w").pack(side="left")
    val_w = 20 if is_ec else 14
    lbl_val = tk.Label(f, text="---", font=("Arial", 11, "bold"), fg="#0d47a1", bg="#e0e0e0", width=val_w, anchor="e")
    lbl_val.pack(side="right")
    return lbl_val

lbl_val_ec         = create_sensor_row(col_sensors, "EC", is_ec=True)
lbl_val_ph         = create_sensor_row(col_sensors, "pH")

tk.Frame(col_sensors, bg="black", height=1).pack(fill="x", pady=4)

# Section 2: Room Sensor (MD02)
tk.Label(col_sensors, text="ROOM SENSOR", font=("Arial", 11, "bold"), fg="#1565c0", bg="#e0e0e0").pack(anchor="w", pady=(2, 1))

lbl_val_room_temp = create_sensor_row(col_sensors, "Room Temp")
lbl_val_room_humi = create_sensor_row(col_sensors, "Room Humi")

# Warning / Status Container at bottom of Column 1
warn_box_frame = tk.Frame(col_sensors, bg="#e0e0e0")
warn_box_frame.pack(pady=4, anchor="w", fill="x")

# Sleek Divider Line 1 (Sleeker 2px thickness)
sep1 = tk.Frame(content_grid, bg="black", width=2)
sep1.pack(side="left", fill="y", pady=4)

# Column 2 (MIDDLE COLUMN - RELAY STATUS)
col_relays = tk.Frame(content_grid, bg="#e0e0e0")
col_relays.pack(side="left", fill="both", expand=True, padx=4)

tk.Label(col_relays, text="RELAY STATUS", font=("Arial", 11, "bold"), fg="#1565c0", bg="#e0e0e0").pack(pady=(4, 2))

labels_relays = {}
relay_items = [
    ("EC1 ",        "ec1"),
    ("EC2 ",        "ec2"),
    ("pH ",         "ph"),
    ("S-Tank Solenoid", "solenoid"),
    ("Fan(1st 50%)",       "fan1"),
    ("Fan(2nd 50%)",       "fan2"),
    ("Cooling Pad", "pad"),
    ("Fogger ",     "fogger"),
    ("ACF Fan",     "acf"),
    ("Sprinkler",   "sprinkler"),
    ("Irrigation Pump",   "irrigation"),
    ("Cyclic Timer 1",    "timer1"),
    ("Cyclic Timer 2",    "timer2"),
]
for lbl_txt, r_key in relay_items:
    f = tk.Frame(col_relays, bg="#e0e0e0")
    f.pack(fill="x", pady=0)
    tk.Label(f, text=lbl_txt, font=("Arial", 9, "bold"), fg="#333333", bg="#e0e0e0", width=15, anchor="w").pack(side="left")
    lbl_st = tk.Label(f, text="OFF", font=("Arial", 9, "bold"), fg="#c62828", bg="#e0e0e0", anchor="e")
    lbl_st.pack(side="right")
    labels_relays[r_key] = lbl_st

# Sleek Divider Line 2 (Sleeker 2px thickness)
sep2 = tk.Frame(content_grid, bg="black", width=2)
sep2.pack(side="left", fill="y", pady=4)

# Column 3 (RIGHT COLUMN - CYCLIC TIMERS TOP-TO-BOTTOM FILLING RIGHT SIDE SPACE)
col_timers = tk.Frame(content_grid, bg="#e0e0e0")
col_timers.pack(side="left", fill="both", expand=True, padx=4)

tk.Label(col_timers, text="CYCLIC TIMERS", font=("Arial", 11, "bold"), fg="#1565c0", bg="#e0e0e0").pack(pady=(4, 2))

labels_timers = {}

def create_timer_widget(parent, prefix, default_name):
    t_name = setpoints.get(f"{prefix} Name", default_name)

    card = tk.LabelFrame(parent, text="", bg="#ffffff", bd=1, relief="groove")
    card.pack(fill="x", pady=3, padx=2)

    lbl_tname = tk.Label(card, text=str(t_name).upper(), font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff")
    lbl_tname.pack(pady=(3, 2))
    labels_timers[f"tname_{prefix}"] = lbl_tname

    sub_lbl_font = ("Arial", 9, "bold")
    sub_val_font = ("Arial", 9, "bold")

    t_sub_labels = {}
    for sub_key, sub_lbl in [("status", "Status"), ("window", "Window"), ("cycle", "Cycle")]:
        f = tk.Frame(card, bg="#f1f5f9")
        f.pack(fill="x", pady=1, padx=4)
        tk.Label(f, text=sub_lbl, font=sub_lbl_font, fg="#475569", bg="#f1f5f9", width=10, anchor="w").pack(side="left", padx=4, pady=1)
        lbl_v = tk.Label(f, text="---", font=sub_val_font, fg="#0f172a", bg="#f1f5f9", anchor="e")
        lbl_v.pack(side="right", padx=4, pady=1)
        t_sub_labels[sub_key] = lbl_v

    labels_timers[prefix] = t_sub_labels

def create_humi_timer_widget(parent):
    h_name = setpoints.get("HUMI Name", "FOGGER TIMER")

    card = tk.LabelFrame(parent, text="", bg="#ffffff", bd=1, relief="groove")
    card.pack(fill="x", pady=3, padx=2)

    lbl_tname = tk.Label(card, text=str(h_name).upper(), font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff")
    lbl_tname.pack(pady=(3, 2))
    labels_timers["tname_humi"] = lbl_tname

    sub_lbl_font = ("Arial", 9, "bold")
    sub_val_font = ("Arial", 9, "bold")

    t_sub_labels = {}
    for sub_key, sub_lbl in [("status", "Status"), ("day_cycle", "Day Cycle"), ("night_cycle", "Night Cycle")]:
        f = tk.Frame(card, bg="#f1f5f9")
        f.pack(fill="x", pady=1, padx=4)
        tk.Label(f, text=sub_lbl, font=sub_lbl_font, fg="#475569", bg="#f1f5f9", width=11, anchor="w").pack(side="left", padx=4, pady=1)
        lbl_v = tk.Label(f, text="---", font=sub_val_font, fg="#0f172a", bg="#f1f5f9", anchor="e")
        lbl_v.pack(side="right", padx=4, pady=1)
        t_sub_labels[sub_key] = lbl_v

    labels_timers["humi"] = t_sub_labels[sub_key] = lbl_v

    labels_timers["humi"] = t_sub_labels

timer_canvas = tk.Canvas(col_timers, bg="#e0e0e0", highlightthickness=0)
timer_scrollbar = tk.Scrollbar(col_timers, orient="vertical", command=timer_canvas.yview, width=32, bd=2, relief="raised")
scroll_timers_frame = tk.Frame(timer_canvas, bg="#e0e0e0")

canvas_window = timer_canvas.create_window((0, 0), window=scroll_timers_frame, anchor="nw")

def _on_canvas_configure(event):
    timer_canvas.itemconfig(canvas_window, width=event.width)

timer_canvas.bind("<Configure>", _on_canvas_configure)
scroll_timers_frame.bind("<Configure>", lambda e: timer_canvas.configure(scrollregion=timer_canvas.bbox("all")))

timer_canvas.configure(yscrollcommand=timer_scrollbar.set)

timer_canvas.pack(side="left", fill="both", expand=True)
timer_scrollbar.pack(side="right", fill="y")

# Render 7 Equipment Timers Top-to-Bottom, Filling Full Right Side Width (Identical to almora2.py)
create_humi_timer_widget(scroll_timers_frame)
create_timer_widget(scroll_timers_frame, "PAD",        "COOLING PAD PUMP")
create_timer_widget(scroll_timers_frame, "ACF",        "AIR CIRCULATION FAN")
create_timer_widget(scroll_timers_frame, "Sprinkler",  "OVERHEAD SPRINKLER")
create_timer_widget(scroll_timers_frame, "Irrigation", "DAYTIME IRRIGATION")
create_timer_widget(scroll_timers_frame, "Timer1",     "CYCLIC TIMER 1")
create_timer_widget(scroll_timers_frame, "Timer2",     "CYCLIC TIMER 2")


def request_setpoints_access():
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    win = tk.Toplevel(root)
    win.title("Security Authentication")
    win.configure(bg="#ffffff")
    win.geometry(f"{sw}x{sh}+0+0")
    win.focus_force()
    win.update()
    win.attributes("-fullscreen", True)
    win.grab_set()

    lbl_auth_clock = tk.Label(win, text="", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff", justify="left")
    lbl_auth_clock.place(x=15, y=10, anchor="nw")
    def update_auth_clock():
        if win.winfo_exists():
            lbl_auth_clock.config(text=datetime.datetime.now().strftime("%A, %d %b %Y\n%I:%M:%S %p"))
            win.after(1000, update_auth_clock)
    update_auth_clock()

    def close_win():
        win.destroy()
        try:
            root.geometry(f"{sw}x{sh}+0+0")
            root.attributes("-fullscreen", True)
            root.focus_force()
        except Exception:
            pass

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
        pop.geometry(f"{sw}x{sh}+0+0")
        pop.focus_force()
        pop.update()
        pop.attributes("-fullscreen", True)
        pop.grab_set()

        lbl_pop_clock = tk.Label(pop, text="", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff", justify="left")
        lbl_pop_clock.place(x=15, y=10, anchor="nw")
        def update_pop_clock():
            if pop.winfo_exists():
                lbl_pop_clock.config(text=datetime.datetime.now().strftime("%A, %d %b %Y\n%I:%M:%S %p"))
                pop.after(1000, update_pop_clock)
        update_pop_clock()

        def close_pop():
            pop.destroy()
            try:
                win.geometry(f"{sw}x{sh}+0+0")
                win.attributes("-fullscreen", True)
                win.focus_force()
                win.grab_set()
            except Exception:
                pass

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
            close_pop()

        kb_frame = tk.Frame(container, bg="#ffffff")
        kb_frame.pack(pady=10)
        for ri, row_k in enumerate([list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL:"), list("ZXCVBNM._ ")]):
            for ci, ch in enumerate(row_k):
                lbl = ch if ch != ' ' else 'SPC'
                tk.Button(kb_frame, text=lbl, font=("Arial", 11, "bold"), width=4, height=1, bg="#f1f5f9", fg="#0f172a", activebackground="#0284c7", activeforeground="white",
                          command=lambda x=ch: char_press(x)).grid(row=ri, column=ci, padx=2, pady=2)

        action_frame = tk.Frame(container, bg="#ffffff")
        action_frame.pack(fill="x", pady=15)
        tk.Button(action_frame, text="CANCEL", font=("Arial", 10, "bold"), bg="#64748b", fg="white", width=8, height=2, command=close_pop).pack(side="left", padx=10)
        tk.Button(action_frame, text="CLEAR", font=("Arial", 10, "bold"), bg="#dc2626", fg="white", width=8, height=2, command=char_clear).pack(side="left", padx=10)
        tk.Button(action_frame, text="BACK", font=("Arial", 10, "bold"), bg="#f97316", fg="white", width=10, height=2, command=char_back).pack(side="left", padx=10)
        tk.Button(action_frame, text="SAVE", font=("Arial", 10, "bold"), bg="#0284c7", fg="white", width=10, height=2, command=char_save).pack(side="right", padx=10)

    def change_pin_popup():
        nonlocal selected_user
        pop = tk.Toplevel(win)
        pop.title("Change Operator PIN")
        pop.configure(bg="#ffffff")
        pop.geometry(f"{sw}x{sh}+0+0")
        pop.focus_force()
        pop.update()
        pop.attributes("-fullscreen", True)
        pop.grab_set()

        lbl_pop_clock = tk.Label(pop, text="", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff", justify="left")
        lbl_pop_clock.place(x=15, y=10, anchor="nw")
        def update_pop_clock():
            if pop.winfo_exists():
                lbl_pop_clock.config(text=datetime.datetime.now().strftime("%A, %d %b %Y\n%I:%M:%S %p"))
                pop.after(1000, update_pop_clock)
        update_pop_clock()

        def close_pop():
            pop.destroy()
            try:
                win.geometry(f"{sw}x{sh}+0+0")
                win.attributes("-fullscreen", True)
                win.focus_force()
                win.grab_set()
            except Exception:
                pass

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
                close_pop()

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
        tk.Button(action_frame, text="CANCEL", font=("Arial", 10, "bold"), bg="#64748b", fg="white", width=12, height=2, command=close_pop).pack(side="left", padx=15)
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
            close_win()
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
    tk.Button(action_frame, text="CANCEL", font=("Arial", 10, "bold"), bg="#64748b", fg="white", width=12, height=2, bd=1, relief="raised", command=close_win).pack(side="left", padx=15)
    tk.Button(action_frame, text="AUTHENTICATE", font=("Arial", 10, "bold"), bg="#0284c7", fg="white", width=14, height=2, bd=1, relief="raised", command=kp_confirm).pack(side="right", padx=15)

    select_user(1)

tk.Label(frame_set, text="SYSTEM SETPOINTS CONFIGURATION", font=FONT_BIG, fg="#1565c0", bg="#ffffff").pack(pady=(4, 1))

# Setpoint Footer (Packed FIRST at side="bottom" like control121.py)
footer_set = tk.Frame(frame_set, bg="#ffffff", height=45)
footer_set.pack(side="bottom", fill="x")
footer_set.pack_propagate(False)

tk.Button(footer_set, text="SAVE & RETURN", font=FONT_MED, bg="#0284c7", fg="white", width=18,
          command=lambda: (save_setpoints(), show(frame_main))).pack(pady=4)

# Setpoints Scrollable Canvas & Vertical Touch Slider (Fits Full Width of 7-inch Display)
sp_canvas = tk.Canvas(frame_set, bg="#ffffff", highlightthickness=0)
sp_scrollbar = tk.Scrollbar(frame_set, orient="vertical", command=sp_canvas.yview, width=28, bd=2, relief="raised")
sp_container = tk.Frame(sp_canvas, bg="#ffffff")

sp_canvas_win = sp_canvas.create_window((0, 0), window=sp_container, anchor="nw")

def _on_sp_container_cfg(e):
    sp_canvas.configure(scrollregion=sp_canvas.bbox("all"))

def _on_sp_canvas_resize(e):
    sp_canvas.itemconfig(sp_canvas_win, width=e.width)

sp_container.bind("<Configure>", _on_sp_container_cfg)
sp_canvas.bind("<Configure>", _on_sp_canvas_resize)
sp_canvas.configure(yscrollcommand=sp_scrollbar.set)

sp_scrollbar.pack(side="right", fill="y", pady=(32, 0))
sp_canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(32, 0))

# Top Section: 2 Equal Columns (Left: Dosing & Climate, Right: Humidifier)
sp_top_container = tk.Frame(sp_container, bg="#ffffff")
sp_top_container.pack(fill="x", side="top", pady=(0, 4))

left_sp_pane = tk.Frame(sp_top_container, bg="#ffffff")
left_sp_pane.pack(side="left", fill="both", expand=True, padx=4)

right_sp_pane = tk.Frame(sp_top_container, bg="#ffffff")
right_sp_pane.pack(side="right", fill="both", expand=True, padx=4)

# Bottom Section: 2 Vertical Stacked Cards for Equipment Cyclic Timers
sp_bottom_container = tk.Frame(sp_container, bg="#ffffff")
sp_bottom_container.pack(fill="x", side="top", pady=(4, 6), padx=4)

sp_labels = {}
sp_selected_key = None
sp_entered_value = ""

def make_sp_cell(parent, key, label_text=None, width_lbl=10, default_val=0.0):
    if key not in setpoints:
        setpoints[key] = default_val
    lbl_txt = label_text if label_text else key
    cell = tk.Frame(parent, bg="#ffffff")

    tk.Label(cell, text=lbl_txt, font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", anchor="w", width=width_lbl).pack(side="left", padx=2)
    val_lbl = tk.Label(cell, text=str(setpoints[key]), font=("Arial", 10, "bold"), fg="#e65100", bg="#f8fafc", width=6, anchor="center", relief="sunken", bd=1)
    val_lbl.pack(side="left", padx=(2, 4))

    btn = tk.Button(cell, text="EDIT", font=("Arial", 10, "bold"), width=6, bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="raised", pady=2, padx=4,
                    command=lambda k=key: open_keypad_sp(k))
    btn.pack(side="right", padx=2)
    sp_labels[key] = val_lbl
    return cell

# Card 1 (LEFT PANE): Nutrients & pH
card_dosing = tk.LabelFrame(left_sp_pane, text=" NUTRIENTS & PH ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
card_dosing.pack(fill="x", pady=4, padx=4)
grid_dosing = tk.Frame(card_dosing, bg="#ffffff")
grid_dosing.pack(pady=4, padx=6, fill="x")
grid_dosing.columnconfigure(0, weight=1)
grid_dosing.columnconfigure(1, weight=1)

make_sp_cell(grid_dosing, "EC MIN", "EC Min:").grid(row=0, column=0, padx=4, pady=3, sticky="ew")
make_sp_cell(grid_dosing, "EC MAX", "EC Max:").grid(row=0, column=1, padx=4, pady=3, sticky="ew")
make_sp_cell(grid_dosing, "PH LOW", "pH Low:").grid(row=1, column=0, padx=4, pady=3, sticky="ew")
make_sp_cell(grid_dosing, "PH HIGH", "pH High:").grid(row=1, column=1, padx=4, pady=3, sticky="ew")
make_sp_cell(grid_dosing, "S_TANK", "S Tank:").grid(row=2, column=0, padx=4, pady=3, sticky="ew")

# Card 3 (LEFT PANE): Climate Control
card_climate_sp = tk.LabelFrame(left_sp_pane, text=" CLIMATE CONTROL ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
card_climate_sp.pack(fill="x", pady=4, padx=4)
grid_climate_sp = tk.Frame(card_climate_sp, bg="#ffffff")
grid_climate_sp.pack(pady=4, padx=6, fill="x")

# Left Section: Temperature Setpoints (Top to Bottom)
temp_section = tk.Frame(grid_climate_sp, bg="#ffffff")
temp_section.pack(side="left", fill="both", expand=True, padx=4)
tk.Label(temp_section, text="TEMPERATURE SETPOINTS", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff").pack(anchor="w", pady=(1, 3))
make_sp_cell(temp_section, "TEMP MIN", "Temp Min:").pack(fill="x", pady=3)
make_sp_cell(temp_section, "TEMP MED", "Temp Med:").pack(fill="x", pady=3)
make_sp_cell(temp_section, "TEMP MAX", "Temp Max:").pack(fill="x", pady=3)
make_sp_cell(temp_section, "TEMP Hyst", "Safety:").pack(fill="x", pady=3)

# Vertical Separator Line
tk.Frame(grid_climate_sp, bg="#cbd5e1", width=1).pack(side="left", fill="y", padx=4, pady=2)

# Right Section: Humidity Setpoints (Day & Night Independent Thresholds + Safety)
humi_section = tk.Frame(grid_climate_sp, bg="#ffffff")
humi_section.pack(side="right", fill="both", expand=True, padx=4)
tk.Label(humi_section, text="HUMIDITY SETPOINTS", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff").pack(anchor="w", pady=(1, 3))
make_sp_cell(humi_section, "HUMI D_Min", "Day Min:  ").pack(fill="x", pady=3)
make_sp_cell(humi_section, "HUMI D_Max", "Day Max:  ").pack(fill="x", pady=3)
make_sp_cell(humi_section, "HUMI N_Min", "Night Min:").pack(fill="x", pady=3)
make_sp_cell(humi_section, "HUMI N_Max", "Night Max:").pack(fill="x", pady=3)
make_sp_cell(humi_section, "HUMI BUFFER", "Safety:").pack(fill="x", pady=3)

# Card 2 (RIGHT PANE): Humidifier Day/Night Cyclic Timer
card_humi_sp = tk.LabelFrame(right_sp_pane, text=f" {str(setpoints.get('HUMI Name', 'HUMIDIFIER')).upper()} DAY/NIGHT TIMER ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
card_humi_sp.pack(fill="x", pady=(45, 2), padx=4)

humi_hdr = tk.Frame(card_humi_sp, bg="#f1f5f9")
humi_hdr.pack(fill="x", pady=4, padx=6)
tk.Label(humi_hdr, text="Setting", font=("Arial", 10, "bold"), fg="#64748b", bg="#f1f5f9", width=10, anchor="w").pack(side="left", padx=2)
tk.Label(humi_hdr, text="DAY WINDOW", font=("Arial", 10, "bold"), fg="#1565c0", bg="#f1f5f9", width=15, anchor="center").pack(side="left", expand=True)
tk.Label(humi_hdr, text="NIGHT WINDOW", font=("Arial", 10, "bold"), fg="#1565c0", bg="#f1f5f9", width=15, anchor="center").pack(side="left", expand=True)

r_name = tk.Frame(card_humi_sp, bg="#ffffff")
r_name.pack(fill="x", pady=4, padx=6)
tk.Label(r_name, text="Timer Name", font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", width=10, anchor="w").pack(side="left", padx=2)
v_name = tk.Label(r_name, text=str(setpoints.get("HUMI Name", "HUMIDIFIER")), font=("Arial", 10, "bold"), fg="#0f172a", bg="#f8fafc", anchor="center", relief="sunken", bd=1)
v_name.pack(side="left", expand=True, fill="x", padx=4)
btn_name = tk.Button(r_name, text="EDIT", font=("Arial", 10, "bold"), width=6, bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="raised", pady=2, padx=4,
                     command=lambda: open_keypad_sp("HUMI Name"))
btn_name.pack(side="right", padx=2)
sp_labels["HUMI Name"] = v_name

humi_rows = [
    ("Start Time", "HUMI D_Start",  "HUMI N_Start"),
    ("Stop Time",  "HUMI D_Stop",   "HUMI N_Stop"),
    ("ON Min",     "HUMI D_ON Min",  "HUMI N_ON Min"),
    ("OFF Min",    "HUMI D_OFF Min", "HUMI N_OFF Min"),
]

for r_lbl, d_k, n_k in humi_rows:
    r_f = tk.Frame(card_humi_sp, bg="#ffffff")
    r_f.pack(fill="x", pady=4, padx=6)
    tk.Label(r_f, text=r_lbl, font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", width=10, anchor="w").pack(side="left", padx=2)

    c_day = tk.Frame(r_f, bg="#ffffff")
    c_day.pack(side="left", expand=True, fill="x")
    v_d = tk.Label(c_day, text=str(setpoints.get(d_k, "")), font=("Arial", 10, "bold"), fg="#e65100", bg="#f8fafc", width=6, anchor="center", relief="sunken", bd=1)
    v_d.pack(side="left", expand=True, padx=2)
    tk.Button(c_day, text="EDIT", font=("Arial", 10, "bold"), width=6, bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="raised", pady=2, padx=4,
              command=lambda k=d_k: open_keypad_sp(k)).pack(side="right", padx=2)
    sp_labels[d_k] = v_d

    c_night = tk.Frame(r_f, bg="#ffffff")
    c_night.pack(side="left", expand=True, fill="x")
    v_n = tk.Label(c_night, text=str(setpoints.get(n_k, "")), font=("Arial", 10, "bold"), fg="#e65100", bg="#f8fafc", width=6, anchor="center", relief="sunken", bd=1)
    v_n.pack(side="left", expand=True, padx=2)
    tk.Button(c_night, text="EDIT", font=("Arial", 10, "bold"), width=6, bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="raised", pady=2, padx=4,
              command=lambda k=n_k: open_keypad_sp(k)).pack(side="right", padx=2)
    sp_labels[n_k] = v_n

# Bottom Section: 2 Vertical Stacked Cards (Top & Bottom) for Equipment Cyclic Timers
# Grid Box 1: Top Card (3 Equipment Timers: Pad Pump, ACF Fan, Sprinkler)
card_timers_1 = tk.LabelFrame(sp_bottom_container, text=" CYCLIC TIMERS 1 - 3 ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
card_timers_1.pack(fill="x", pady=(3, 6), padx=4)

cols_group1 = [
    {"name": "Pad Pump",   "keys": {"Name": "PAD Name", "Start": "PAD Start", "Stop": "PAD Stop", "ON Min": "PAD ON Min", "OFF Min": "PAD OFF Min"}},
    {"name": "ACF Fan",    "keys": {"Name": "ACF Name", "Start": "ACF Start", "Stop": "ACF Stop", "ON Min": "ACF ON Min", "OFF Min": "ACF OFF Min"}},
    {"name": "Sprinkler",  "keys": {"Name": "Sprinkler Name", "Start": "Sprinkler Start", "Stop": "Sprinkler Stop", "ON Min": "Sprinkler ON Min", "OFF Min": "Sprinkler OFF Min"}}
]

# Grid Box 2: Bottom Card (3 Equipment Timers: Irrigation, Timer 1, Timer 2)
card_timers_2 = tk.LabelFrame(sp_bottom_container, text=" CYCLIC TIMERS 4 - 6 ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
card_timers_2.pack(fill="x", pady=(3, 6), padx=4)

cols_group2 = [
    {"name": "Irrigation", "keys": {"Name": "Irrigation Name", "Start": "Irrigation Start", "Stop": "Irrigation Stop", "ON Min": "Irrigation ON Min", "OFF Min": "Irrigation OFF Min"}},
    {"name": "Timer 1",    "keys": {"Name": "Timer1 Name", "Start": "Timer1 Start", "Stop": "Timer1 Stop", "ON Min": "Timer1 ON Min", "OFF Min": "Timer1 OFF Min"}},
    {"name": "Timer 2",    "keys": {"Name": "Timer2 Name", "Start": "Timer2 Start", "Stop": "Timer2 Stop", "ON Min": "Timer2 ON Min", "OFF Min": "Timer2 OFF Min"}}
]

def build_timer_grid_box(parent_card, cols_group):
    header_frame = tk.Frame(parent_card, bg="#f1f5f9")
    header_frame.pack(fill="x", pady=4, padx=6)
    tk.Label(header_frame, text="Setting", font=("Arial", 10, "bold"), fg="#64748b", bg="#f1f5f9", width=10, anchor="w").pack(side="left", padx=2)

    for col in cols_group:
        col_hdr = tk.Frame(header_frame, bg="#f1f5f9")
        col_hdr.pack(side="left", expand=True, fill="x", padx=3)
        name_k = col["keys"]["Name"]
        cur_name = str(setpoints.get(name_k, col["name"])).upper()

        lbl_n = tk.Label(col_hdr, text=cur_name, font=("Arial", 10, "bold"), fg="#1565c0", bg="#f1f5f9", anchor="center")
        lbl_n.pack(side="left", expand=True, padx=2)
        sp_labels[name_k] = lbl_n

        btn_edit_name = tk.Button(col_hdr, text="EDIT", font=("Arial", 10, "bold"), width=6, bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="raised", pady=2, padx=4,
                                  command=lambda k=name_k: open_keypad_sp(k))
        btn_edit_name.pack(side="right", padx=2)

    row_keys = [("Start", "Start:"), ("Stop", "Stop:"), ("ON Min", "ON Min:"), ("OFF Min", "OFF Min:")]

    for r_key, r_lbl in row_keys:
        r_frame = tk.Frame(parent_card, bg="#ffffff")
        r_frame.pack(fill="x", pady=4, padx=6)
        tk.Label(r_frame, text=r_lbl, font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", width=10, anchor="w").pack(side="left", padx=2)
        for col in cols_group:
            col_frame = tk.Frame(r_frame, bg="#ffffff")
            col_frame.pack(side="left", expand=True, fill="x", padx=3)
            full_key = col["keys"].get(r_key)
            if full_key and full_key in setpoints:
                val_lbl = tk.Label(col_frame, text=str(setpoints[full_key]), font=("Arial", 10, "bold"), fg="#e65100", bg="#f8fafc", width=6, anchor="center", relief="sunken", bd=1)
                val_lbl.pack(side="left", expand=True, padx=2)
                btn = tk.Button(col_frame, text="EDIT", font=("Arial", 10, "bold"), width=6, bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="raised", pady=2, padx=4,
                                command=lambda k=full_key: open_keypad_sp(k))
                btn.pack(side="right", padx=2)
                sp_labels[full_key] = val_lbl

build_timer_grid_box(card_timers_1, cols_group1)
build_timer_grid_box(card_timers_2, cols_group2)

def open_keypad_sp(key):
    global sp_selected_key, sp_entered_value
    sp_selected_key = key
    sp_entered_value = ""

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()

    pop = tk.Toplevel(root)
    pop.title(f"Editing {key}")
    pop.configure(bg="#ffffff")
    pop.geometry(f"{sw}x{sh}+0+0")
    pop.focus_force()
    pop.update()
    pop.attributes("-fullscreen", True)
    pop.grab_set()

    lbl_pop_clock = tk.Label(pop, text="", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff", justify="left")
    lbl_pop_clock.place(x=15, y=10, anchor="nw")
    def update_pop_clock():
        if pop.winfo_exists():
            lbl_pop_clock.config(text=datetime.datetime.now().strftime("%A, %d %b %Y\n%I:%M:%S %p"))
            pop.after(1000, update_pop_clock)
    update_pop_clock()

    def close_pop():
        pop.destroy()

    container = tk.Frame(pop, bg="#ffffff")
    container.place(relx=0.5, rely=0.5, anchor="center")

    kp_sp_title = tk.Label(container, text=f"EDIT {key.upper()}", font=("Arial", 16, "bold"), fg="#1565c0", bg="#ffffff")
    kp_sp_title.pack(pady=8)

    kp_sp_display = tk.Label(container, text="", font=("Arial", 22, "bold"), fg="#2e7d32", bg="#f1f5f9", width=18, relief="sunken", bd=2)
    kp_sp_display.pack(pady=10)

    kp_sp_buttons = tk.Frame(container, bg="#ffffff")
    kp_sp_buttons.pack(pady=10)

    kp_sp_actions = tk.Frame(container, bg="#ffffff")
    kp_sp_actions.pack(pady=10)

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
            if sp_selected_key in sp_labels:
                sp_labels[sp_selected_key].config(text=str(val))
            close_pop()
        except Exception:
            kp_sp_display.config(text="INVALID INPUT")

    if key.endswith("Name"):
        for ri, row_k in enumerate([list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL:"), list("ZXCVBNM._ ")]):
            for ci, ch in enumerate(row_k):
                tk.Button(kp_sp_buttons, text=ch if ch!=' ' else 'SPC', font=("Arial", 12, "bold"), width=4, bg="#f1f5f9", fg="#0f172a",
                          command=lambda x=ch: kp_sp_press(x)).grid(row=ri, column=ci, padx=3, pady=3)
        w_btn = 8
    else:
        for text, ri, ci in [('1',0,0),('2',0,1),('3',0,2),('4',1,0),('5',1,1),('6',1,2),
                            ('7',2,0),('8',2,1),('9',2,2),('.',3,0),('0',3,1),(':',3,2)]:
            tk.Button(kp_sp_buttons, text=text, font=("Arial", 18, "bold"), width=6, height=1, bg="#f1f5f9", fg="#0f172a",
                      command=lambda x=text: kp_sp_press(x)).grid(row=ri, column=ci, padx=5, pady=5)
        w_btn = 7

    for txt, bg, fg, cmd in [("DEL", "#f97316", "white", kp_sp_back), ("CLR", "#dc2626", "white", kp_sp_clear),
                             ("CONFIRM", "#0284c7", "white", kp_sp_confirm), ("CANCEL", "#64748b", "white", close_pop)]:
        tk.Button(kp_sp_actions, text=txt, font=("Arial", 12, "bold"), bg=bg, fg=fg, width=w_btn+2, pady=6, command=cmd).pack(side="left", padx=8)


def update():
    water_data = cached_water_data
    md02_data  = cached_md02_data

    warnings = control_system(water_data, md02_data)

    # 1. Update Water Sensor Labels
    if water_data:
        tds = water_data['ec'] * 500
        lbl_val_ec.config(text=f"{water_data['ec']:.3f} mS/cm ({tds:.0f} ppm)", fg="#0d47a1")
        lbl_val_ph.config(text=f"{water_data['ph']:.2f}", fg="#0d47a1")
    else:
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
        "solenoid": relay_solenoid.is_active,
        "fan1": relay_fan1.is_active,
        "fan2": relay_fan2.is_active,
        "pad": relay_pad.is_active,
        "fogger": relay_fogger.is_active,
        "acf": relay_acf.is_active,
        "sprinkler": relay_sprinkler.is_active,
        "irrigation": relay_irrigation.is_active,
        "timer1": relay_timer1.is_active,
        "timer2": relay_timer2.is_active,
    }
    for r_key, is_on in relay_states.items():
        lbl_st = labels_relays.get(r_key)
        if lbl_st:
            if is_on:
                lbl_st.config(text="ON", fg="#2e7d32")
            else:
                lbl_st.config(text="OFF", fg="#c62828")

    # 4. Update Equipment Cyclic Timers Widgets on Home Screen (Original 3-Row Format)
    for pfx, name_k, def_title, relay_obj, start_k, stop_k, on_k, off_k in [
        ("PAD",        "PAD Name",        "COOLING PAD PUMP",    relay_pad,        "PAD Start",    "PAD Stop",    "PAD ON Min",    "PAD OFF Min"),
        ("ACF",        "ACF Name",        "AIR CIRCULATION FAN", relay_acf,        "ACF Start",    "ACF Stop",    "ACF ON Min",    "ACF OFF Min"),
        ("Sprinkler",  "Sprinkler Name",  "OVERHEAD SPRINKLER",  relay_sprinkler,  "Sprinkler Start","Sprinkler Stop","Sprinkler ON Min","Sprinkler OFF Min"),
        ("Irrigation", "Irrigation Name", "DAYTIME IRRIGATION",  relay_irrigation, "Irrigation Start","Irrigation Stop","Irrigation ON Min","Irrigation OFF Min"),
        ("Timer1",     "Timer1 Name",     "WATER MIXING PUMP",   relay_timer1,     "Timer1 Start", "Timer1 Stop", "Timer1 ON Min", "Timer1 OFF Min"),
        ("Timer2",     "Timer2 Name",     "CYCLIC TIMER 2",      relay_timer2,     "Timer2 Start", "Timer2 Stop", "Timer2 ON Min", "Timer2 OFF Min"),
    ]:
        lbl_tname = labels_timers.get(f"tname_{pfx}")
        if lbl_tname:
            lbl_tname.config(text=str(setpoints.get(name_k, def_title)).upper())

        t_spec = labels_timers.get(pfx)
        if t_spec:
            start_t = setpoints.get(start_k, "06:00")
            stop_t = setpoints.get(stop_k, "18:00")
            window_str = f"{start_t} – {stop_t}"

            try: on_min = int(float(setpoints.get(on_k, 5)))
            except: on_min = 5
            try: off_min = int(float(setpoints.get(off_k, 15)))
            except: off_min = 15
            cycle_str = f"{on_min}m ON / {off_min}m OFF"

            t_st = timer_state.get(pfx, {"state": "OFF"})
            state_str = t_st.get("state", "OFF")
            is_active = relay_obj.is_active

            if is_active or state_str == "ON":
                status_str = f"ON ({state_str})"
                status_fg = "#16a34a"
            else:
                status_str = f"OFF ({state_str})"
                status_fg = "#dc2626"

            t_spec["status"].config(text=status_str, fg=status_fg)
            t_spec["window"].config(text=window_str, fg="#0f172a")
            t_spec["cycle"].config(text=cycle_str, fg="#0f172a")

    # 5. Update Humidifier (Fogger) Day/Night Timer Widget
    lbl_hname = labels_timers.get("tname_humi")
    if lbl_hname:
        lbl_hname.config(text=str(setpoints.get("HUMI Name", "FOGGER TIMER")).upper())

    h_spec = labels_timers.get("humi")
    if h_spec:
        d_str = f"{setpoints.get('HUMI D_ON Min',10)}m/{setpoints.get('HUMI D_OFF Min',20)}m ({setpoints.get('HUMI D_Start','06:00')}-{setpoints.get('HUMI D_Stop','18:00')})"
        n_str = f"{setpoints.get('HUMI N_ON Min',5)}m/{setpoints.get('HUMI N_OFF Min',40)}m ({setpoints.get('HUMI N_Start','18:00')}-{setpoints.get('HUMI N_Stop','06:00')})"

        is_active = relay_fogger.is_active
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

    # Render Warning & Status Messages with Categorized Colors (Label Reuse - Zero Blinking)
    if 'warn_box_frame' in globals():
        existing_labels = list(warn_box_frame.winfo_children())
        num_existing = len(existing_labels)
        num_needed = len(warnings)

        # Update existing labels only if text or color changed
        for i in range(min(num_existing, num_needed)):
            w_text = warnings[i]
            m = w_text.upper()
            if "ERR" in m or "CUTOFF" in m or "DISABLED" in m:
                fg_col = "#dc2626"
            elif "ON" in m or "ACTIVE" in m:
                fg_col = "#15803d"
            else:
                fg_col = "#92400e"

            lbl = existing_labels[i]
            if lbl.cget("text") != w_text or lbl.cget("fg") != fg_col:
                lbl.config(text=w_text, fg=fg_col)

        # Create new labels for new messages
        for i in range(num_existing, num_needed):
            w_text = warnings[i]
            m = w_text.upper()
            if "ERR" in m or "CUTOFF" in m or "DISABLED" in m:
                fg_col = "#dc2626"
            elif "ON" in m or "ACTIVE" in m:
                fg_col = "#15803d"
            else:
                fg_col = "#92400e"

            tk.Label(warn_box_frame, text=w_text, font=("Arial", 9, "bold"), fg=fg_col, bg="#e0e0e0", anchor="w", justify="left").pack(anchor="w")

        # Remove extra labels if count decreased
        for i in range(num_needed, num_existing):
            existing_labels[i].destroy()

    # Update Header Clock (Day, Date, Time)
    if 'lbl_clock' in globals():
        lbl_clock.config(text=datetime.datetime.now().strftime("%A, %d %b %Y\n%I:%M:%S %p"))

    # Live Telemetry and Offline Sync Logging (1 Second Frequency)
    publish_live_telemetry(water_data, md02_data)
    save_local_telemetry(water_data, md02_data)

    root.after(1000, update)

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

