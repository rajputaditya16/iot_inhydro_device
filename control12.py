import os, sys, json, time, datetime, atexit
import socket, subprocess, threading
import urllib.request, urllib.parse
from datetime import timezone
import tkinter as tk
from PIL import Image, ImageTk
import minimalmodbus
import serial
import paho.mqtt.client as mqtt


# Room 1 sensor ports
R1_PORT_SOIL = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.4.2:1.0-port0"
R1_PORT_MD02 = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.4.1:1.0-port0"
R1_PORT_ORP  = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.4.3:1.0-port0"
R1_PORT_CO2  = "/dev/serial/by-path/usb-0:1.4-port0"

# Room 2 sensor ports
R2_PORT_SOIL = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.4.6:1.0-port0"
R2_PORT_MD02 = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.4.5:1.0-port0"
R2_PORT_ORP  = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.4.4:1.0-port0"
R2_PORT_CO2  = "/dev/serial/by-path/platform-3f98000.usb-usb-0:1:2:1:0-port0"

# Room 3 sensor ports
R3_PORT_MD02_1 = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.4.9:1.0-port0"
R3_PORT_MD02_2 = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.4.10:1.0-port0"
R3_PORT_CO2    = "/dev/serial/by-path/platform-3f98000.usb-usb-0:1:2:2:0-port0"

# MODBUS SETTINGS
RELAY_BAUD = 9600
RELAY_PORT_FIXED = "/dev/serial/by-path/platform-3f980000.usb-usb-0:1.4.7:1.0-port0"
POSSIBLE_RELAY_IDS = [255, 1, 2, 0, 3]  
working_relay_id = None

# SYSTEM STATE
system_config = {'relay_port': RELAY_PORT_FIXED}
_relay_state = {}
SENSOR_SLAVE_ID = 1   

# Room 1 relay channels
R1_CH_EC1   = 1
R1_CH_EC2   = 2
R1_CH_PH    = 3
R1_CH_AC    = 4
R1_CH_HUMI  = 5
R1_CH_TMR1  = 6
R1_CH_TMR2  = 7
R1_CH_TMR3  = 8

# Room 2 relay channels
R2_CH_EC1   = 17
R2_CH_EC2   = 18
R2_CH_PH    = 19
R2_CH_AC    = 20
R2_CH_HUMI  = 21
R2_CH_TMR1  = 22
R2_CH_TMR2  = 23
R2_CH_TMR3  = 24

# Room 3 relay channels
R3_CH_AC1   = 25
R3_CH_AC2   = 26
R3_CH_HUMI1 = 27
R3_CH_HUMI2 = 28
R3_CH_TMR1  = 29
R3_CH_TMR2  = 30
R3_CH_TMR3  = 31
R3_CH_SPARE = 32




BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.realpath(sys.argv[0]))
ID_FILE  = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE) as f: return f.read().strip()
        except: pass
    return " "

DEVICE_NAME = get_device_id()
print(f"🚀 Device: {DEVICE_NAME}")

# Per-room setpoint files
SP_FILE = {
    1: os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}_room1.json"),
    2: os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}_room2.json"),
    3: os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}_room3.json"),
}

OLD_FILE = os.path.join(BASE_DIR, "setpoints.json")
if os.path.exists(OLD_FILE):
    try: os.remove(OLD_FILE)
    except: pass

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

def relay_on(ch):
    _relay_state[ch] = True
    set_relay(ch, True)

def relay_off(ch):
    _relay_state[ch] = False
    set_relay(ch, False)

def relay_is_on(ch):
    return _relay_state.get(ch, False)

ALL_CHANNELS = [R1_CH_EC1, R1_CH_EC2, R1_CH_PH, R1_CH_AC, R1_CH_HUMI, R1_CH_TMR1, R1_CH_TMR2, R1_CH_TMR3,
                R2_CH_EC1, R2_CH_EC2, R2_CH_PH, R2_CH_AC, R2_CH_HUMI, R2_CH_TMR1, R2_CH_TMR2, R2_CH_TMR3,
                R3_CH_AC1, R3_CH_AC2, R3_CH_HUMI1, R3_CH_HUMI2, R3_CH_TMR1, R3_CH_TMR2, R3_CH_TMR3, R3_CH_SPARE]

def all_relays_off():
    for ch in ALL_CHANNELS: relay_off(ch)

atexit.register(all_relays_off)

#
def read_md02(port):
    try:
        inst = minimalmodbus.Instrument(port, SENSOR_SLAVE_ID)
        inst.serial.baudrate = 9600
        inst.serial.timeout  = 1.0
        # Fix: Removing /10.0 as per user feedback (31 shows as 3.1)
        temp = inst.read_register(1) 
        humi = inst.read_register(2)
        return {"room_temp": temp, "room_humi": humi}
    except:
        return None

def _open_sensor(port, label, baudrate=9600):
    try:
        inst = minimalmodbus.Instrument(port, SENSOR_SLAVE_ID)
        inst.serial.baudrate = baudrate
        inst.serial.bytesize = 8
        inst.serial.parity   = serial.PARITY_NONE
        inst.serial.stopbits = 1
        inst.serial.timeout  = 1.5
        inst.mode            = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True

        inst.serial.reset_input_buffer()
        inst.serial.reset_output_buffer()
        print(f"✅ [{label}] initialized on {port} at {baudrate} baud")
        return inst
    except Exception as e:
        print(f"⚠️ [{label}] initialization error on {port} at {baudrate} baud: {e}")
        return None

R1_soil = _open_sensor(R1_PORT_SOIL, "R1 Soil", baudrate=9600)
R1_md02 = _open_sensor(R1_PORT_MD02, "R1 MD02", baudrate=9600)
R1_orp  = _open_sensor(R1_PORT_ORP,  "R1 ORP",  baudrate=4800)
R1_co2  = _open_sensor(R1_PORT_CO2,  "R1 CO2",  baudrate=9600)

R2_soil = _open_sensor(R2_PORT_SOIL, "R2 Soil", baudrate=9600)
R2_md02 = _open_sensor(R2_PORT_MD02, "R2 MD02", baudrate=9600)
R2_orp  = _open_sensor(R2_PORT_ORP,  "R2 ORP",  baudrate=4800)
R2_co2  = _open_sensor(R2_PORT_CO2,  "R2 CO2",  baudrate=9600)

R3_md02_1 = _open_sensor(R3_PORT_MD02_1, "R3 MD02 #1", baudrate=9600)
R3_md02_2 = _open_sensor(R3_PORT_MD02_2, "R3 MD02 #2", baudrate=9600)
R3_co2    = _open_sensor(R3_PORT_CO2,    "R3 CO2",     baudrate=9600)



def default_setpoints(room=1):
    sp = {
        "EC MIN": 1.2, "EC MAX": 1.8,
        "PH LOW": 5.8,  "PH HIGH": 6.5,
        "D T Max": 35.0, "DT Min": 15.0,
        "N T Max": 35.0, "N T Min": 15.0,
        "H Max": 80.0, "H Min": 30.0,
        "CLIENT ID": "", "USERNAME": "", "PASSWORD": "",
        "CHANNEL ID": "", "PORT": 1883,
        "READ API KEY": "", "WRITE API KEY": "",
    }
    if room == 3:
        sp.update({
            "Timer1 Name": "TIMER 1",
            "Timer1 Start": "10:00", "Timer1 Stop": "17:00",
            "Timer1 ON Min": 15,     "Timer1 OFF Min": 30,

            "Timer2 Name": "TIMER 2",
            "Timer2 Start": "10:00", "Timer2 Stop": "17:00",
            "Timer2 ON Min": 15,     "Timer2 OFF Min": 30,

            "Timer3 Name": "TIMER 3",
            "Timer3 D_Start": "10:00", "Timer3 D_Stop": "17:00",
            "Timer3 D_ON Min": 15,     "Timer3 D_OFF Min": 30,
            "Timer3 N_Start": "17:05", "Timer3 N_Stop": "09:55",
            "Timer3 N_ON Min": 15,     "Timer3 N_OFF Min": 30,

            "AC1 Name": "AC 1 TIMER",
            "AC1 D_Start": "10:00", "AC1 D_Stop": "17:00",
            "AC1 D_ON Min": 15,     "AC1 D_OFF Min": 30,
            "AC1 N_Start": "17:05", "AC1 N_Stop": "09:55",
            "AC1 N_ON Min": 15,     "AC1 N_OFF Min": 30,
            "AC1 D_T Max": 35.0,    "AC1 D_T Min": 15.0,
            "AC1 N_T Max": 35.0,    "AC1 N_T Min": 15.0,

            "AC2 Name": "AC 2 TIMER",
            "AC2 D_Start": "10:00", "AC2 D_Stop": "17:00",
            "AC2 D_ON Min": 15,     "AC2 D_OFF Min": 30,
            "AC2 N_Start": "17:05", "AC2 N_Stop": "09:55",
            "AC2 N_ON Min": 15,     "AC2 N_OFF Min": 30,
            "AC2 D_T Max": 35.0,    "AC2 D_T Min": 15.0,
            "AC2 N_T Max": 35.0,    "AC2 N_T Min": 15.0,

            "HUMI1 Name": "HUMI 1 TIMER",
            "HUMI1 D_Start": "10:00", "HUMI1 D_Stop": "17:00",
            "HUMI1 D_ON Min": 15,     "HUMI1 D_OFF Min": 30,
            "HUMI1 N_Start": "17:05", "HUMI1 N_Stop": "09:55",
            "HUMI1 N_ON Min": 15,     "HUMI1 N_OFF Min": 30,
            "HUMI1 D_H Max": 80.0,    "HUMI1 D_H Min": 30.0,
            "HUMI1 N_H Max": 80.0,    "HUMI1 N_H Min": 30.0,

            "HUMI2 Name": "HUMI 2 TIMER",
            "HUMI2 D_Start": "10:00", "HUMI2 D_Stop": "17:00",
            "HUMI2 D_ON Min": 15,     "HUMI2 D_OFF Min": 30,
            "HUMI2 N_Start": "17:05", "HUMI2 N_Stop": "09:55",
            "HUMI2 N_ON Min": 15,     "HUMI2 N_OFF Min": 30,
            "HUMI2 D_H Max": 80.0,    "HUMI2 D_H Min": 30.0,
            "HUMI2 N_H Max": 80.0,    "HUMI2 N_H Min": 30.0,
        })
    else:
        sp.update({
            "Timer1 Name": "TIMER 1",
            "Timer1 Start": "10:00", "Timer1 Stop": "17:00",
            "Timer1 ON Min": 15,     "Timer1 OFF Min": 30,
            "Timer2 Name": "TIMER 2",
            "Timer2 Start": "10:00", "Timer2 Stop": "17:00",
            "Timer2 ON Min": 15,     "Timer2 OFF Min": 30,
            "Timer3 Name": "TIMER 3",
            "Timer3 D_Start": "10:00", "Timer3 D_Stop": "17:00",
            "Timer3 D_ON Min": 15,     "Timer3 D_OFF Min": 30,
            "Timer3 N_Start": "17:05", "Timer3 N_Stop": "09:55",
            "Timer3 N_ON Min": 15,     "Timer3 N_OFF Min": 30,
            "Timer4 Name": "AC TIMER",
            "Timer4 D_Start": "10:00", "Timer4 D_Stop": "17:00",
            "Timer4 D_ON Min": 15,     "Timer4 D_OFF Min": 30,
            "Timer4 N_Start": "17:05", "Timer4 N_Stop": "09:55",
            "Timer4 N_ON Min": 15,     "Timer4 N_OFF Min": 30,
        })
    return sp

setpoints = {1: default_setpoints(1), 2: default_setpoints(2), 3: default_setpoints(3)}

def load_setpoints(room):
    f = SP_FILE[room]
    if os.path.exists(f):
        try:
            with open(f) as fp: setpoints[room].update(json.load(fp))
            print(f"✅ Room {room} setpoints loaded")
        except: pass

load_setpoints(1)
load_setpoints(2)
load_setpoints(3)

def save_setpoints(room):
    with open(SP_FILE[room], "w") as f:
        json.dump(setpoints[room], f, indent=4)
    try:
        topic = f"inhydro/{DEVICE_NAME}/room{room}/setpoints/current"
        control_client.publish(topic, json.dumps(setpoints[room]), retain=True)
        print(f"✅ Room {room} setpoints saved + pushed")
    except: pass


MQTT_BROKER = "mqtt3.thingspeak.com"
mqtt_client = None
MQTT_TOPIC  = ""

def init_mqtt_client():
    global mqtt_client, MQTT_TOPIC
    if mqtt_client is not None:
        try: mqtt_client.disconnect(); mqtt_client.loop_stop()
        except: pass
    sp = setpoints[1]
    cid  = str(sp.get("CLIENT ID",  ""))
    user = str(sp.get("USERNAME",   ""))
    pwd  = str(sp.get("PASSWORD",   ""))
    chid = str(sp.get("CHANNEL ID", ""))
    if not all([cid, user, pwd, chid]):
        print("⚠️  ThingSpeak credentials incomplete"); return
    try: port = int(sp.get("PORT", 1883))
    except: port = 1883
    MQTT_TOPIC  = f"channels/{chid}/publish"
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, cid)
    mqtt_client.username_pw_set(user, pwd)
    try:
        mqtt_client.connect(MQTT_BROKER, port, 60)
        mqtt_client.loop_start()
        print(f"✅ ThingSpeak MQTT → {MQTT_TOPIC}")
    except Exception as e:
        print(f"⚠️  ThingSpeak offline: {e}")

init_mqtt_client()



def _v(val): return val if val is not None else ""

last_cloud_publish_time = 0

def publish_telemetry(d1, d2, d3):
    """d1 = Room1 sensor dict, d2 = Room2 sensor dict, d3 = Room3 sensor dict. Each field = JSON array."""
    global last_cloud_publish_time
    current_time = time.time()
    if current_time - last_cloud_publish_time < 35:
        return
        
    def arr(a, b, c): return json.dumps([a, b, c])
    s1 = d1.get("soil"); s2 = d2.get("soil"); s3 = d3.get("soil")
    r1 = d1.get("room"); r2 = d2.get("room"); r3 = d3.get("room")
    if not r3 and d3.get("md02_1"):
        r3 = {"room_temp": d3["md02_1"].get("room_temp"), "room_humi": d3["md02_1"].get("room_humi")}
    fields = {
        "field1": arr(_v(s1['soil_temp'] if s1 else None), _v(s2['soil_temp'] if s2 else None), _v(s3['soil_temp'] if s3 else None)),
        "field2": arr(_v(s1['moisture']  if s1 else None), _v(s2['moisture']  if s2 else None), _v(s3['moisture']  if s3 else None)),
        "field3": arr(_v((s1['ec'] * 0.85)/1000 if s1 and s1.get('ec') is not None else None), _v((s2['ec'] * 0.85)/1000 if s2 and s2.get('ec') is not None else None), _v((s3['ec'] * 0.85)/1000 if s3 and s3.get('ec') is not None else None)),
        "field4": arr(_v(s1['ph']        if s1 else None), _v(s2['ph']        if s2 else None), _v(s3['ph']        if s3 else None)),
        "field5": arr(_v(r1['room_temp'] if r1 else None), _v(r2['room_temp'] if r2 else None), _v(r3['room_temp'] if r3 else None)),
        "field6": arr(_v(r1['room_humi'] if r1 else None), _v(r2['room_humi'] if r2 else None), _v(r3['room_humi'] if r3 else None)),
        "field7": arr(_v(d1.get('orp')), _v(d2.get('orp')), _v(d3.get('orp'))),
        "field8": arr(_v(d1.get('co2')), _v(d2.get('co2')), _v(d3.get('co2'))),
    }


    try:
        connected = mqtt_client.is_connected() if mqtt_client else False
    except:
        connected = False

    if connected:
        try:
            payload = "&".join(f"{k}={v}" for k, v in fields.items())
            mqtt_client.publish(MQTT_TOPIC, payload)
            last_cloud_publish_time = current_time
            print("🚀 Telemetry published directly to Cloud successfully.")
        except Exception as e:
            print(f"❌ ThingSpeak publish error: {e}")
            last_cloud_publish_time = current_time
    else:
        print("⚠️ ThingSpeak disconnected, skipping publish")
        last_cloud_publish_time = current_time



CONTROL_BROKER = "broker.hivemq.com"
CONTROL_PORT   = 1883

def on_control_message(client, userdata, msg):
    try:
        parts = msg.topic.split("/")
        room_part = [p for p in parts if p.startswith("room")]
        room = int(room_part[0][-1]) if room_part else 1

        if "request_sync" in msg.topic:
            topic = f"inhydro/{DEVICE_NAME}/room{room}/setpoints/current"
            control_client.publish(topic, json.dumps(setpoints[room]), retain=True)
            print(f"✅ Synced setpoints for Room {room} (requested)")
            return

        new_data = json.loads(msg.payload.decode())
        if not isinstance(new_data, dict):
            return

        key_map  = {
            "clientId": "CLIENT ID",
            "username": "USERNAME",
            "password": "PASSWORD",
            "channelId": "CHANNEL ID",
            "port": "PORT",
            "readApiKey": "READ API KEY",
            "writeApiKey": "WRITE API KEY"
        }
        new_sp   = {key_map.get(k, k): v for k, v in new_data.items()}

        # Also validate formatting of any updated time values
        time_keys = [
            "Timer1 Start", "Timer1 Stop",
            "Timer2 Start", "Timer2 Stop",
            "Timer3 D_Start", "Timer3 D_Stop",
            "Timer3 N_Start", "Timer3 N_Stop",
            "Timer4 D_Start", "Timer4 D_Stop",
            "Timer4 N_Start", "Timer4 N_Stop"
        ]
        for k in time_keys:
            if k in new_sp:
                try:
                    datetime.datetime.strptime(str(new_sp[k]), "%H:%M")
                except:
                    print(f"⚠️ Remote setpoint reject: invalid time format for {k}")
                    return

        # Validate day/night timer bounds for Timer 3 and Timer 4 to avoid conflicts
        for prefix in ["Timer3", "Timer4"]:
            d_start = new_sp.get(f"{prefix} D_Start", setpoints[room].get(f"{prefix} D_Start", "10:00"))
            d_stop  = new_sp.get(f"{prefix} D_Stop", setpoints[room].get(f"{prefix} D_Stop", "17:00"))
            n_start = new_sp.get(f"{prefix} N_Start", setpoints[room].get(f"{prefix} N_Start", "17:01"))
            n_stop  = new_sp.get(f"{prefix} N_Stop", setpoints[room].get(f"{prefix} N_Stop", "09:59"))
            
            try:
                t_d_start = datetime.datetime.strptime(str(d_start), "%H:%M").time()
                t_d_stop  = datetime.datetime.strptime(str(d_stop),  "%H:%M").time()
                t_n_start = datetime.datetime.strptime(str(n_start), "%H:%M").time()
                t_n_stop  = datetime.datetime.strptime(str(n_stop),  "%H:%M").time()
            except Exception as e:
                print(f"⚠️ Remote setpoint reject: invalid time format: {e}")
                return

            if (t_d_start >= t_d_stop or
                t_n_start < t_d_stop or
                t_d_start < t_n_stop or
                t_n_start == t_n_stop):
                print(f"⚠️ Remote setpoint reject: Day/Night timer conflict for {prefix}")
                return

        ts_changed = any(
            str(new_sp.get(k)) != str(setpoints[room].get(k))
            for k in ["PORT", "CLIENT ID", "USERNAME", "PASSWORD", "CHANNEL ID", "READ API KEY", "WRITE API KEY"]
            if k in new_sp
        )
        setpoints[room].update(new_sp)
        save_setpoints(room)
        if ts_changed: init_mqtt_client()

        if "root" in globals():
            try: root.after(0, lambda r=room, ns=new_sp: refresh_labels(r, ns))
            except: pass
        print(f"✅ Room {room} setpoints updated remotely")
    except Exception as e:
        print(f"Control MQTT error: {e}")

is_mqtt_connected = False

def on_control_connect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        print("✅ Control MQTT (HiveMQ) connected/reconnected")
        for room in [1, 2, 3]:
            client.subscribe(f"inhydro/{DEVICE_NAME}/room{room}/setpoints/update")
            client.subscribe(f"inhydro/{DEVICE_NAME}/room{room}/setpoints/request_sync")
            try:
                client.publish(
                    f"inhydro/{DEVICE_NAME}/room{room}/setpoints/current",
                    json.dumps(setpoints[room]), retain=True)
            except:
                pass
    else:
        is_mqtt_connected = False
        print(f"⚠️ Control MQTT connection failed with code {rc}")

def on_control_disconnect(client, userdata, flags, rc, properties=None, *args, **kwargs):
    global is_mqtt_connected
    is_mqtt_connected = False
    print("⚠️ Control MQTT (HiveMQ) disconnected")

import uuid
client_id = f"Inhydro_Dual_{DEVICE_NAME.strip()}_{uuid.uuid4().hex[:6]}"
control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
control_client.on_message = on_control_message
control_client.on_connect = on_control_connect
control_client.on_disconnect = on_control_disconnect

try:
    control_client.loop_start()
    control_client.connect_async(CONTROL_BROKER, CONTROL_PORT, 10)
    print("✅ Control MQTT (HiveMQ) loop started (connecting...)")
except Exception as e:
    print(f"⚠️  Control MQTT startup failed: {e}")



def read_soil(inst, label):
    if not inst: return None
    try:
        inst.serial.reset_input_buffer()
        moist = inst.read_register(0x0012, 1)
        temp  = inst.read_register(0x0013, 1, signed=True)
        ec    = inst.read_register(0x0015, 0)
        ph    = inst.read_register(0x0006, 2)
        return {"soil_temp": temp, "moisture": moist, "ec": ec, "ph": ph}
    except Exception as e:
        print(f"⚠️ [{label}] Soil read failed: {e}")
        return None

def read_md02(inst, label):
    if not inst: return None
    try:
        inst.serial.reset_input_buffer()
        try:
            rt = inst.read_register(1, 1, signed=True, functioncode=4)
            rh = inst.read_register(2, 1, functioncode=4)
        except Exception:
            rt = inst.read_register(1, 1, signed=True, functioncode=3)
            rh = inst.read_register(2, 1, functioncode=3)
        if rt is not None:
            rt = round(rt - 5.0, 1)
        if rh is not None:
            rh = round(rh - 3.0, 1)
        return {"room_temp": rt, "room_humi": rh}
    except Exception as e:
        print(f"⚠️ [{label} MD02] Read failed: {e}")
        return None

def read_orp(inst, label):
    if not inst: return None
    try:
        inst.serial.reset_input_buffer()
        try:
            return inst.read_register(0x0000, 1, signed=True, functioncode=4)
        except Exception:
            return inst.read_register(0x0000, 1, signed=True, functioncode=3)
    except Exception as e:
        print(f"⚠️ [{label} ORP] Read failed: {e}")
        return None

def read_co2(inst, label):
    if not inst: return None
    try:
        inst.serial.reset_input_buffer()
        try:
            return inst.read_register(0x0000, 0, functioncode=4)
        except Exception:
            return inst.read_register(0x0000, 0, functioncode=3)
    except Exception as e:
        print(f"⚠️ [{label} CO2] Read failed: {e}")
        return None

def read_all_sensors(room):
    """Read Soil, Room, ORP, and CO2 sensors as requested."""
    if room == 1:
        return {
            "soil": read_soil(R1_soil, "R1 Soil"),
            "room": read_md02(R1_md02, "R1 MD02"),
            "orp": read_orp(R1_orp, "R1 ORP"),
            "co2": read_co2(R1_co2, "R1 CO2"),
        }
    elif room == 2:
        return {
            "soil": read_soil(R2_soil, "R2 Soil"),
            "room": read_md02(R2_md02, "R2 MD02"),
            "orp": read_orp(R2_orp, "R2 ORP"),
            "co2": read_co2(R2_co2, "R2 CO2"),
        }
    else:
        return {
            "md02_1": read_md02(R3_md02_1, "R3 MD02 #1"),
            "md02_2": read_md02(R3_md02_2, "R3 MD02 #2"),
            "co2":    read_co2(R3_co2,     "R3 CO2"),
        }



state = {
    1: {"ec_active": False, "ph_active": False, "ac_active": False,
        "humi_active": False, "last_ec": 0.0, "last_ph": 0.0},
    2: {"ec_active": False, "ph_active": False, "ac_active": False,
        "humi_active": False, "last_ec": 0.0, "last_ph": 0.0},
    3: {"ec_active": False, "ph_active": False, "ac_active": False,
        "humi_active": False, "last_ec": 0.0, "last_ph": 0.0,
        "ac1_active": False, "ac2_active": False, "humi1_active": False, "humi2_active": False},
}

ROOM_CHANNELS = {
    1: {"ec1": R1_CH_EC1, "ec2": R1_CH_EC2, "ph": R1_CH_PH,
        "ac": R1_CH_AC,   "humi": R1_CH_HUMI},
    2: {"ec1": R2_CH_EC1, "ec2": R2_CH_EC2, "ph": R2_CH_PH,
        "ac": R2_CH_AC,   "humi": R2_CH_HUMI},
    3: {"ac1": R3_CH_AC1, "ac2": R3_CH_AC2,
        "humi1": R3_CH_HUMI1, "humi2": R3_CH_HUMI2},
}

def control_room(room, data):
    st  = state[room]
    sp  = setpoints[room]
    ch  = ROOM_CHANNELS[room]
    now = time.time()
    warnings = []

    if room == 3:
        m1 = data.get("md02_1")
        m2 = data.get("md02_2")
        co2 = data.get("co2")
        if not m1 and not m2:
            warnings.append("⚠️ MD02 SENSORS ERROR")
        if co2 is None:
            warnings.append("⚠️ CO2 SENSOR ERROR")

        # AC 1 & HUMI 1 (controls using Sensor 1: m1)
        if m1:
            rt1 = m1.get("room_temp")
            rh1 = m1.get("room_humi")

            # AC 1
            ac1_timer_on = (timer_state[3][3]["state"] == "ON")
            if ac1_timer_on and rt1 is not None:
                in_day = is_within_window(sp.get("AC1 D_Start", "10:00"), sp.get("AC1 D_Stop", "17:00"))
                in_night = is_within_window(sp.get("AC1 N_Start", "17:05"), sp.get("AC1 N_Stop", "09:55"))
                if in_night and not in_day:
                    t_max = sp.get("AC1 N_T Max", 35.0)
                    t_min = sp.get("AC1 N_T Min", 15.0)
                else:
                    t_max = sp.get("AC1 D_T Max", 35.0)
                    t_min = sp.get("AC1 D_T Min", 15.0)

                if not st["ac1_active"] and rt1 >= t_max:
                    st["ac1_active"] = True; relay_on(ch["ac1"])
                    warnings.append("⚠ AC1 ON (Temp High)")
                elif st["ac1_active"] and rt1 <= t_min:
                    st["ac1_active"] = False; relay_off(ch["ac1"])
            else:
                if st["ac1_active"] or relay_is_on(ch["ac1"]):
                    st["ac1_active"] = False; relay_off(ch["ac1"])

            # HUMI 1
            humi1_timer_on = (timer_state[3][5]["state"] == "ON")
            if humi1_timer_on and rh1 is not None:
                in_day = is_within_window(sp.get("HUMI1 D_Start", "10:00"), sp.get("HUMI1 D_Stop", "17:00"))
                in_night = is_within_window(sp.get("HUMI1 N_Start", "17:05"), sp.get("HUMI1 N_Stop", "09:55"))
                if in_night and not in_day:
                    h_max = sp.get("HUMI1 N_H Max", 80.0)
                    h_min = sp.get("HUMI1 N_H Min", 30.0)
                else:
                    h_max = sp.get("HUMI1 D_H Max", 80.0)
                    h_min = sp.get("HUMI1 D_H Min", 30.0)

                if not st["humi1_active"] and rh1 >= h_max:
                    st["humi1_active"] = True; relay_on(ch["humi1"])
                    warnings.append("⚠ HUMI1 ON (Humi High)")
                elif st["humi1_active"] and rh1 <= h_min:
                    st["humi1_active"] = False; relay_off(ch["humi1"])
            else:
                if st["humi1_active"] or relay_is_on(ch["humi1"]):
                    st["humi1_active"] = False; relay_off(ch["humi1"])
        else:
            if st["ac1_active"] or relay_is_on(ch["ac1"]):
                st["ac1_active"] = False; relay_off(ch["ac1"])
            if st["humi1_active"] or relay_is_on(ch["humi1"]):
                st["humi1_active"] = False; relay_off(ch["humi1"])

        # AC 2 & HUMI 2 (controls using Sensor 2: m2)
        if m2:
            rt2 = m2.get("room_temp")
            rh2 = m2.get("room_humi")

            # AC 2
            ac2_timer_on = (timer_state[3][4]["state"] == "ON")
            if ac2_timer_on and rt2 is not None:
                in_day = is_within_window(sp.get("AC2 D_Start", "10:00"), sp.get("AC2 D_Stop", "17:00"))
                in_night = is_within_window(sp.get("AC2 N_Start", "17:05"), sp.get("AC2 N_Stop", "09:55"))
                if in_night and not in_day:
                    t_max = sp.get("AC2 N_T Max", 35.0)
                    t_min = sp.get("AC2 N_T Min", 15.0)
                else:
                    t_max = sp.get("AC2 D_T Max", 35.0)
                    t_min = sp.get("AC2 D_T Min", 15.0)

                if not st["ac2_active"] and rt2 >= t_max:
                    st["ac2_active"] = True; relay_on(ch["ac2"])
                    warnings.append("⚠ AC2 ON (Temp High)")
                elif st["ac2_active"] and rt2 <= t_min:
                    st["ac2_active"] = False; relay_off(ch["ac2"])
            else:
                if st["ac2_active"] or relay_is_on(ch["ac2"]):
                    st["ac2_active"] = False; relay_off(ch["ac2"])

            # HUMI 2
            humi2_timer_on = (timer_state[3][6]["state"] == "ON")
            if humi2_timer_on and rh2 is not None:
                in_day = is_within_window(sp.get("HUMI2 D_Start", "10:00"), sp.get("HUMI2 D_Stop", "17:00"))
                in_night = is_within_window(sp.get("HUMI2 N_Start", "17:05"), sp.get("HUMI2 N_Stop", "09:55"))
                if in_night and not in_day:
                    h_max = sp.get("HUMI2 N_H Max", 80.0)
                    h_min = sp.get("HUMI2 N_H Min", 30.0)
                else:
                    h_max = sp.get("HUMI2 D_H Max", 80.0)
                    h_min = sp.get("HUMI2 D_H Min", 30.0)

                if not st["humi2_active"] and rh2 >= h_max:
                    st["humi2_active"] = True; relay_on(ch["humi2"])
                    warnings.append("⚠ HUMI2 ON (Humi High)")
                elif st["humi2_active"] and rh2 <= h_min:
                    st["humi2_active"] = False; relay_off(ch["humi2"])
            else:
                if st["humi2_active"] or relay_is_on(ch["humi2"]):
                    st["humi2_active"] = False; relay_off(ch["humi2"])
        else:
            if st["ac2_active"] or relay_is_on(ch["ac2"]):
                st["ac2_active"] = False; relay_off(ch["ac2"])
            if st["humi2_active"] or relay_is_on(ch["humi2"]):
                st["humi2_active"] = False; relay_off(ch["humi2"])

        return warnings

    soil = data.get("soil")
    room_env = data.get("room")

    if soil:
        raw_ec = soil["ec"]
        ec = (raw_ec * 0.85) / 1000 if raw_ec is not None else 0.0
        ph = soil["ph"]

        if not st["ec_active"] and ec < sp["EC MIN"]:
            st["ec_active"] = True
            relay_on(ch["ec1"]); relay_on(ch["ec2"])
            st["last_ec"] = now
            warnings.append("⚠ EC LOW — DOSING")

        if st["ec_active"]:
            if ec >= sp["EC MAX"]:
                relay_off(ch["ec1"]); relay_off(ch["ec2"])
                st["ec_active"] = False
            elif now - st["last_ec"] >= 10:
                relay_on(ch["ec1"]); relay_on(ch["ec2"])
                st["last_ec"] = now

        if not st["ph_active"] and ph > sp["PH HIGH"]:
            st["ph_active"] = True
            relay_on(ch["ph"])
            st["last_ph"] = now
            warnings.append("⚠ pH HIGH — CORRECTING")

        if st["ph_active"]:
            if ph <= sp["PH LOW"]:
                relay_off(ch["ph"]); st["ph_active"] = False
            elif now - st["last_ph"] >= 10:
                relay_on(ch["ph"]); st["last_ph"] = now
    else:
        # Safety: Sensor offline, turn off dosing ONLY if they were active
        if st["ec_active"] or st["ph_active"] or relay_is_on(ch["ec1"]):
            relay_off(ch["ec1"]); relay_off(ch["ec2"]); relay_off(ch["ph"])
            st["ec_active"] = False; st["ph_active"] = False
        warnings.append(" WATER SENSOR ERROR")

    if room_env:
        rt = room_env["room_temp"]; rh = room_env["room_humi"]

        ac_timer_on = (timer_state[room][3]["state"] == "ON")

        if ac_timer_on:
            in_day = is_within_window(sp.get("Timer4 D_Start", "10:00"), sp.get("Timer4 D_Stop", "17:00"))
            in_night = is_within_window(sp.get("Timer4 N_Start", "10:00"), sp.get("Timer4 N_Stop", "17:00"))
            
            if in_day:
                t_max = sp.get("D T Max", 35.0)
                t_min = sp.get("DT Min", 15.0)
                mode_str = "Day"
            elif in_night:
                t_max = sp.get("N T Max", 35.0)
                t_min = sp.get("N T Min", 15.0)
                mode_str = "Night"
            else:
                t_max = sp.get("D T Max", 35.0)
                t_min = sp.get("DT Min", 15.0)
                mode_str = "Day"

            if not st["ac_active"] and rt >= t_max:
                st["ac_active"] = True; relay_on(ch["ac"])
                warnings.append(f"⚠ TEMP HIGH ({mode_str} AC ON)")
                print(f"Room{room} AC ON — {rt}°C ≥ {t_max}°C ({mode_str})")

            if st["ac_active"] and rt <= t_min:
                st["ac_active"] = False; relay_off(ch["ac"])
                print(f"Room{room} AC OFF — {rt}°C ≤ {t_min}°C ({mode_str})")
        else:
            if st["ac_active"] or relay_is_on(ch["ac"]):
                st["ac_active"] = False; relay_off(ch["ac"])
                print(f"Room{room} AC OFF — Cyclic Timer window OFF")

        if not st["humi_active"] and rh >= sp.get("H Max", 80.0):
            st["humi_active"] = True; relay_on(ch["humi"])
            warnings.append(f"⚠ HUMI HIGH (HUM ON)")
            print(f"Room{room} Humidifier ON — {rh}% ≥ {sp.get('H Max', 80.0)}%")

        if st["humi_active"] and rh <= sp.get("H Min", 30.0):
            st["humi_active"] = False; relay_off(ch["humi"])
            print(f"Room{room} Humidifier OFF — {rh}% ≤ {sp.get('H Min', 30.0)}%")
    else:
        # Safety: Environment sensor offline, turn off AC/Humi ONLY if active
        if st["ac_active"] or st["humi_active"] or relay_is_on(ch["ac"]):
            relay_off(ch["ac"]); relay_off(ch["humi"])
            st["ac_active"] = False; st["humi_active"] = False
        warnings.append(" ROOM SENSOR ERROR")

    return warnings



timer_state = {
    1: [{"state": "OFF", "last": 0.0} for _ in range(4)],
    2: [{"state": "OFF", "last": 0.0} for _ in range(4)],
    3: [{"state": "OFF", "last": 0.0} for _ in range(7)],
}

TIMER_CHANNELS = {
    1: [R1_CH_TMR1, R1_CH_TMR2, R1_CH_TMR3, R1_CH_AC],
    2: [R2_CH_TMR1, R2_CH_TMR2, R2_CH_TMR3, R2_CH_AC],
    3: [R3_CH_TMR1, R3_CH_TMR2, R3_CH_TMR3, R3_CH_AC1, R3_CH_AC2, R3_CH_HUMI1, R3_CH_HUMI2],
}

def get_room_timer_specs(room):
    if room == 3:
        return [
            {"prefix": "Timer1", "type": "cyclic"},
            {"prefix": "Timer2", "type": "cyclic"},
            {"prefix": "Timer3", "type": "day_night"},
            {"prefix": "AC1",    "type": "day_night", "is_ac": True},
            {"prefix": "AC2",    "type": "day_night", "is_ac": True},
            {"prefix": "HUMI1",  "type": "day_night", "is_humi": True},
            {"prefix": "HUMI2",  "type": "day_night", "is_humi": True},
        ]
    else:
        return [
            {"prefix": "Timer1", "type": "cyclic"},
            {"prefix": "Timer2", "type": "cyclic"},
            {"prefix": "Timer3", "type": "day_night"},
            {"prefix": "Timer4", "type": "day_night", "is_ac": True},
        ]

def is_within_window(start_str, stop_str):
    now = datetime.datetime.now().time()
    try:
        st = datetime.datetime.strptime(str(start_str), "%H:%M").time()
        et = datetime.datetime.strptime(str(stop_str),  "%H:%M").time()
    except: return False
    return (st <= now <= et) if st <= et else (now >= st or now <= et)

def run_timers(room):
    now = time.time()
    sp  = setpoints[room]
    specs = get_room_timer_specs(room)
    for i, spec in enumerate(specs):
        ch = TIMER_CHANNELS[room][i]
        ts = timer_state[room][i]
        prefix = spec["prefix"]
        is_climate_timer = spec.get("is_ac", False) or spec.get("is_humi", False)
        is_day_night = (spec["type"] == "day_night")

        if is_day_night:
            in_day = is_within_window(sp.get(f"{prefix} D_Start", "10:00"), sp.get(f"{prefix} D_Stop", "17:00"))
            in_night = is_within_window(sp.get(f"{prefix} N_Start", "17:00"), sp.get(f"{prefix} N_Stop", "17:00"))
            in_window = in_day or in_night
            
            if in_night and not in_day:
                run_sec  = float(sp.get(f"{prefix} N_ON Min", 15)) * 60
                stop_sec = float(sp.get(f"{prefix} N_OFF Min", 30)) * 60
            else:
                run_sec  = float(sp.get(f"{prefix} D_ON Min", 15)) * 60
                stop_sec = float(sp.get(f"{prefix} D_OFF Min", 30)) * 60
        else:
            run_sec  = float(sp.get(f"{prefix} ON Min",  15)) * 60
            stop_sec = float(sp.get(f"{prefix} OFF Min", 30)) * 60
            in_window = is_within_window(sp.get(f"{prefix} Start","10:00"), sp.get(f"{prefix} Stop","17:00"))

        if in_window:
            if ts["state"] == "OFF":
                if now - ts["last"] >= stop_sec or ts["last"] == 0:
                    ts["state"] = "ON"; ts["last"] = now
                    print(f"Room{room} {prefix} ON {datetime.datetime.now().strftime('%H:%M')}")
            elif ts["state"] == "ON":
                if now - ts["last"] >= run_sec:
                    ts["state"] = "OFF"; ts["last"] = now
                    print(f"Room{room} {prefix} OFF — cycle complete")
                    
            if ts["state"] == "ON" and not is_climate_timer:
                if not relay_is_on(ch):
                    relay_on(ch)
            elif ts["state"] == "OFF" and not is_climate_timer:
                if relay_is_on(ch):
                    relay_off(ch)
        else:
            if ts["state"] == "ON" or (not is_climate_timer and relay_is_on(ch)):
                ts["state"] = "OFF"; ts["last"] = 0.0
                if not is_climate_timer:
                    relay_off(ch)



def set_wifi(ssid, password):
    try:
        subprocess.run(['sudo','nmcli','connection','delete',ssid], capture_output=True)
        result = subprocess.run(
            ['sudo','nmcli','device','wifi','connect',ssid,'password',password],
            capture_output=True, text=True)
        if "key-mgmt" in result.stderr:
            result = subprocess.run(
                ['sudo','nmcli','device','wifi','connect',ssid,
                 'password',password,'wifi-sec.key-mgmt','wpa-psk'],
                capture_output=True, text=True)
        return (f"SUCCESS: Connected to {ssid}!" if result.returncode == 0
                else f"FAILED: {result.stderr.strip()}")
    except Exception as e: return f"ERROR: {e}"

def scan_wifi():
    try:
        result = subprocess.run(['sudo','nmcli','-t','-f','SSID','dev','wifi'],
                                capture_output=True, text=True)
        if result.returncode != 0: return f"SCAN FAILED: {result.stderr.strip()}"
        names = sorted(set(n.strip() for n in result.stdout.split('\n') if n.strip()))
        if not names: return "No networks found"
        return ("\r\n--- WIFI NETWORKS ---\r\n" +
                "\r\n".join(f"{i}. {n}" for i,n in enumerate(names,1)) +
                "\r\n---------------------")
    except Exception as e: return f"SCAN ERROR: {e}"

def auto_trust_devices():
    try:
        bt = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        for cmd in ["power on\n","agent NoInputNoOutput\n","default-agent\n",
                    "discoverable on\n","pairable on\n"]:
            bt.stdin.write(cmd)
        bt.stdin.flush()
    except Exception as e: print("BT agent error:", e)
    
    last_discoverable_check = 0
    while True:
        now = time.time()
        # Re-enforce discoverable/pairable modes every 60 seconds to bypass OS timeout
        if now - last_discoverable_check >= 60:
            try:
                subprocess.run(["bluetoothctl", "discoverable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["bluetoothctl", "pairable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["bluetoothctl", "agent", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                last_discoverable_check = now
            except: pass
            
        try:
            out = subprocess.check_output(['bluetoothctl','paired-devices'], text=True)
            for line in out.split('\n'):
                if line.startswith('Device '):
                    os.system(f"sudo bluetoothctl trust {line.split()[1]} >/dev/null 2>&1")
        except: pass
        time.sleep(5)

def start_bluetooth_server():
    while True:
        srv = None
        try:
            os.system("sudo sdptool add --channel=3 SP >/dev/null 2>&1"); time.sleep(1)
            srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            srv.bind((socket.BDADDR_ANY, 3)); srv.listen(1)
            print("Bluetooth RFCOMM server listening")
            while True:
                cli = None
                try:
                    cli, info = srv.accept()
                    print(f"BT connected: {info}")
                    cli.send(b"\r\nInhydro Dual Room\r\nCmds: WIFI:WiFi_Name:PASS | SCAN: Scanning nearby WiFi Networks\r\n")
                    while True:
                        data = cli.recv(1024)
                        if not data: break
                        cmd = data.decode('utf-8').strip()
                        if cmd.startswith("WIFI:"):
                            parts = cmd.split(":")
                            cli.send(f"\r\n{set_wifi(parts[1],':'.join(parts[2:])) if len(parts)>=3 else 'ERROR: WIFI:SSID:PASS'}\r\n".encode())
                        elif cmd.startswith("ID:"):
                            new_id = cmd.split(":",1)[1].strip()
                            if new_id:
                                with open(ID_FILE,"w") as f: f.write(new_id)
                                cli.send(f"\r\nID set to {new_id}. Restarting...\r\n".encode())
                                root.after(2000, restart_program)
                            else: cli.send(b"\r\nERROR: ID:NAME\r\n")
                        elif cmd.upper() == "SCAN":
                            cli.send(("\r\n"+scan_wifi()+"\r\n").encode())
                        elif cmd.upper() == "PING":
                            cli.send(b"\r\nPONG\r\n")
                        else:
                            cli.send(f"\r\nUnknown: {cmd}\r\n".encode())
                except Exception as e:
                    print(f"BT connection error: {e}")
                finally:
                    if cli:
                        try: cli.close()
                        except: pass
        except Exception as e:
            print(f"BT server socket crashed, retrying in 5s: {e}")
            time.sleep(5)
        finally:
            if srv:
                try: srv.close()
                except: pass


root = tk.Tk()
root.attributes("-fullscreen", True)
root.configure(bg="white")
root.bind("<Escape>", lambda e: root.destroy())

LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
try:
    logo_raw = Image.open(LOGO_PATH).resize((130, 82), Image.LANCZOS)
    logo_img = ImageTk.PhotoImage(logo_raw)
    lbl_logo = tk.Label(root, image=logo_img, bg="white")
    lbl_logo.image = logo_img
    lbl_logo.place(relx=0.98, y=8, anchor="ne")
except Exception as e: print(f"Logo error: {e}")

BIG  = ("Arial", 26, "bold")
MED  = ("Arial", 18, "bold")
SML  = ("Arial", 14, "bold")
TINY = ("Arial", 12)

frame_home   = tk.Frame(root, bg="white")
frame_room   = {1: tk.Frame(root, bg="white"), 2: tk.Frame(root, bg="white"), 3: tk.Frame(root, bg="white")}
frame_set    = {1: tk.Frame(root, bg="white"), 2: tk.Frame(root, bg="white"), 3: tk.Frame(root, bg="white")}

active_room  = 1   # which room detail / setpoint screen is open

def show(frame):
    for f in [frame_home, frame_room[1], frame_room[2], frame_room[3],
              frame_set[1], frame_set[2], frame_set[3]]:
        f.pack_forget()
    frame.pack(fill="both", expand=True)
    try: lbl_logo.lift()
    except: pass



tk.Label(frame_home, text="INHYDRO — TRIPLE ROOM CONTROLLER",
         font=BIG, fg="#1565c0", bg="white").pack(pady=(10,4))

home_grid = tk.Frame(frame_home, bg="white")
home_grid.pack(expand=True, pady=30)
home_grid.columnconfigure(0, weight=1)
home_grid.columnconfigure(1, weight=1)

room_summary = {}   

def make_home_box(room, r, c, cspan=1):
    outer = tk.Frame(home_grid, bg="#2e7d32", bd=0, padx=3, pady=3)
    outer.grid(row=r, column=c, columnspan=cspan, padx=12, pady=8, sticky="nsew")

    w = 680 if room == 3 else 400
    h = 160 if room == 3 else 220
    box = tk.Frame(outer, bg="#e0e0e0", bd=2, relief="raised", cursor="hand2", width=w, height=h)
    box.pack_propagate(False)
    box.pack(fill="both", expand=True, padx=2, pady=2)

    lbl_title = tk.Label(box, text=f"ROOM {room}", font=("Arial", 15, "bold"),
                         fg="#1565c0", bg="#e0e0e0", cursor="hand2")
    lbl_title.pack(pady=(4, 2))

    data_frame = tk.Frame(box, bg="#e0e0e0", cursor="hand2")
    data_frame.pack(fill="both", expand=True, padx=12, pady=(0, 4))

    sm = {}

    def add_home_row(parent, row_idx, key, label_text, col_offset=0):
        tk.Label(parent, text=label_text, font=("Arial", 11, "bold"), fg="#444",
                 bg="#e0e0e0", anchor="w").grid(row=row_idx, column=col_offset*2, padx=4, pady=1, sticky="w")
        val_lbl = tk.Label(parent, text="NA", font=("Arial", 12, "bold"), fg="#1a237e",
                           bg="#e0e0e0", width=25, anchor="e")
        val_lbl.grid(row=row_idx, column=col_offset*2+1, padx=4, pady=1, sticky="e")
        sm[key] = val_lbl

    if room in [1, 2]:
        data_frame.columnconfigure(0, weight=1)
        data_frame.columnconfigure(1, weight=1)
        for r_idx in range(6):
            data_frame.rowconfigure(r_idx, weight=1)

        add_home_row(data_frame, 0, "ec",        "EC:",        col_offset=0)
        add_home_row(data_frame, 1, "ph",        "pH:",        col_offset=0)
        add_home_row(data_frame, 2, "room_temp", "Room Temp:", col_offset=0)
        add_home_row(data_frame, 3, "room_humi", "Room Humi:", col_offset=0)
        add_home_row(data_frame, 4, "orp",       "ORP:",       col_offset=0)
        add_home_row(data_frame, 5, "co2",       "CO2:",       col_offset=0)
    else:
        data_frame.columnconfigure(0, weight=1)
        data_frame.columnconfigure(1, weight=1)
        data_frame.columnconfigure(2, weight=1)
        data_frame.columnconfigure(3, weight=1)
        for r_idx in range(3):
            data_frame.rowconfigure(r_idx, weight=1)

        add_home_row(data_frame, 0, "md02_1_temp", "Temp 1:", col_offset=0)
        add_home_row(data_frame, 0, "md02_1_humi", "Humi 1:", col_offset=1)
        add_home_row(data_frame, 1, "md02_2_temp", "Temp 2:", col_offset=0)
        add_home_row(data_frame, 1, "md02_2_humi", "Humi 2:", col_offset=1)
        add_home_row(data_frame, 2, "co2",         "CO2:",    col_offset=0)

    def bind_click(widget):
        widget.bind("<Button-1>", lambda e, r_num=room: open_room(r_num))
        for child in widget.winfo_children():
            bind_click(child)

    bind_click(box)
    room_summary[room] = sm

make_home_box(1, r=0, c=0)
make_home_box(2, r=0, c=1)
make_home_box(3, r=1, c=0, cspan=2)

home_footer = tk.Frame(frame_home, bg="#eeeeee", height=50)
home_footer.pack(side="bottom", fill="x")
home_footer.pack_propagate(False)
tk.Button(home_footer, text="STOP ALL",    font=MED, width=12,
          command=lambda: (all_relays_off(), lbl_home_status.config(text="🛑 STOPPED"))).pack(side="left", padx=20, pady=8)
tk.Button(home_footer, text="RESTART",     font=MED, width=12,
          command=lambda: restart_program()).pack(side="left", padx=20, pady=8)
tk.Button(home_footer, text="EXIT",        font=MED, width=12,
          command=root.destroy).pack(side="right", padx=20, pady=8)
lbl_home_status = tk.Label(home_footer, text="", font=SML,
                            fg="#c62828", bg="#eeeeee")
lbl_home_status.pack(side="left", padx=10, pady=8)

def open_room(room):
    global active_room
    active_room = room
    show(frame_room[room])



room_detail_labels = {}   # {room: {widget_key: label}}

def build_room_screen(room):
    fr = frame_room[room]
    color = "#1565c0"
    labels_d = {}

    tk.Label(fr, text=f"ROOM {room} — LIVE DASHBOARD",
             font=BIG, fg=color, bg="white").pack(pady=(8,2))

    body = tk.Frame(fr, bg="#e0e0e0")
    body.pack(fill="both", expand=True, padx=10)

    # 3 columns with Thick Black Divider Lines
    col_L = tk.Frame(body, bg="#e0e0e0"); col_L.pack(side="left", fill="both", expand=True, padx=8)
    tk.Frame(body, bg="black", width=8).pack(side="left", fill="y", pady=10)
    col_M = tk.Frame(body, bg="#e0e0e0"); col_M.pack(side="left", fill="both", expand=True, padx=8)
    tk.Frame(body, bg="black", width=8).pack(side="left", fill="y", pady=10)
    col_R = tk.Frame(body, bg="#e0e0e0"); col_R.pack(side="left", fill="both", expand=True, padx=8)

    # LEFT — sensor data
    def srow(parent, key, lbl_text, unit=""):
        f = tk.Frame(parent, bg="#e0e0e0"); f.pack(fill="x", pady=2)
        tk.Label(f, text=lbl_text, font=SML, fg="#333", bg="#e0e0e0",
                 width=12, anchor="w").pack(side="left")
        val_width = 25 if key == "ec" else 15
        lbl = tk.Label(f, text="---", font=("Arial",13,"bold"),
                       fg="#0d47a1", bg="#e0e0e0", width=val_width, anchor="e")
        lbl.pack(side="right")
        labels_d[key] = lbl

    if room == 3:
        tk.Label(col_L, text="MD02 SENSOR 1", font=("Arial",12,"bold"),
                 fg="#1565c0", bg="#e0e0e0").pack(pady=(6,2))
        srow(col_L, "md02_1_temp", "Temp 1")
        srow(col_L, "md02_1_humi", "Humi 1")

        tk.Frame(col_L, bg="black", height=2).pack(fill="x", pady=8)
        tk.Label(col_L, text="MD02 SENSOR 2", font=("Arial",12,"bold"),
                 fg="#1565c0", bg="#e0e0e0").pack(pady=(2,2))
        srow(col_L, "md02_2_temp", "Temp 2")
        srow(col_L, "md02_2_humi", "Humi 2")

        tk.Frame(col_L, bg="black", height=2).pack(fill="x", pady=8)
        tk.Label(col_L, text="CLIMATE SENSORS", font=("Arial",12,"bold"),
                 fg="#1565c0", bg="#e0e0e0").pack(pady=(2,2))
        srow(col_L, "co2",       "CO2 Level")
    else:
        tk.Label(col_L, text="WATER SENSOR", font=("Arial",12,"bold"),
                 fg="#1565c0", bg="#e0e0e0").pack(pady=(6,2))
        srow(col_L, "soil_temp", "Water Temp")
        srow(col_L, "moisture",  "Moisture")
        srow(col_L, "ec",        "EC")
        srow(col_L, "ph",        "pH")

        tk.Frame(col_L, bg="black", height=2).pack(fill="x", pady=8)
        tk.Label(col_L, text="ROOM SENSOR", font=("Arial",12,"bold"),
                 fg="#1565c0", bg="#e0e0e0").pack(pady=(2,2))
        srow(col_L, "room_temp", "Room Temp")
        srow(col_L, "room_humi", "Room Humi")

        tk.Frame(col_L, bg="black", height=2).pack(fill="x", pady=8)
        tk.Label(col_L, text="CLIMATE SENSORS", font=("Arial",12,"bold"),
                 fg="#1565c0", bg="#e0e0e0").pack(pady=(2,2))
        srow(col_L, "orp",       "ORP Level")
        srow(col_L, "co2",       "CO2 Level")

    lbl_warn = tk.Label(col_L, text="", font=("Arial",10,"bold"), fg="#c62828",
                        bg="white", justify="left")
    lbl_warn.pack(pady=10)
    labels_d["warn"] = lbl_warn

    # MIDDLE — relay status
    tk.Label(col_M, text="RELAY STATUS", font=("Arial",14,"bold"),
             fg="#1565c0", bg="#e0e0e0").pack(pady=(6,4))

    if room == 3:
        relay_rows = [
            ("AC 1", "r_ac1"),
            ("AC 2", "r_ac2"),
            ("HUMIDIFIER 1", "r_humi1"),
            ("HUMIDIFIER 2", "r_humi2"),
            ("TIMER 1", "r_tmr1"),
            ("TIMER 2", "r_tmr2"),
            ("TIMER 3", "r_tmr3"),
        ]
    else:
        relay_rows = [
            ("EC MODE", "ec_mode"),
            ("pH MODE", "ph_mode"),
            ("AC MODE", "ac_mode"),
            ("HUMI MODE", "humi_mode"),
            ("EC1", "r_ec1"),
            ("EC2", "r_ec2"),
            ("pH", "r_ph"),
            ("AC", "r_ac"),
            ("HUMI", "r_humi"),
            ("TIMER 1",   "r_tmr1"),
            ("TIMER 2",   "r_tmr2"),
            ("TIMER 3",   "r_tmr3"),
            ("AC TIMER",  "r_tmr4"),
        ]
    for lbl_text, key in relay_rows:
        f = tk.Frame(col_M, bg="#e0e0e0"); f.pack(fill="x", pady=2)
        lbl_font = ("Arial", 9, "bold") if room == 3 else SML
        val_font = ("Arial", 9, "bold") if room == 3 else ("Arial", 12, "bold")
        tk.Label(f, text=lbl_text, font=lbl_font, fg="#333",
                 bg="#e0e0e0", width=14 if room == 3 else 12, anchor="w").pack(side="left")
        lbl = tk.Label(f, text="OFF", font=val_font,
                       fg="#c62828", bg="#e0e0e0", anchor="e")
        lbl.pack(side="right")
        labels_d[key] = lbl

    def add_timer_widget(parent, spec):
        prefix = spec["prefix"]
        tname_key = f"{prefix} Name"
        title_font = ("Arial", 12, "bold")
        lbl_tname = tk.Label(parent, text=setpoints[room].get(tname_key, f"{prefix.upper()}"),
                             font=title_font, fg="#1565c0", bg="#e0e0e0")
        lbl_tname.pack(pady=(1,0))
        labels_d[f"tname_{prefix}"] = lbl_tname

        sub_lbl_font = ("Arial", 10, "bold")
        sub_val_font = ("Arial", 10, "bold")

        for sub_key, sub_lbl in [
            (f"{prefix}_status", "Status"),
            (f"{prefix}_window", "Window"),
            (f"{prefix}_cycle",  "Cycle"),
        ]:
            f = tk.Frame(parent, bg="white"); f.pack(fill="x", pady=0)
            tk.Label(f, text=sub_lbl, font=sub_lbl_font, fg="#1565c0",
                     bg="white", width=8, anchor="w").pack(side="left")
            lbl = tk.Label(f, text="---", font=sub_val_font, fg="black", bg="white", anchor="e")
            lbl.pack(side="right")
            labels_d[sub_key] = lbl

    specs = get_room_timer_specs(room)
    if room == 3:
        tk.Frame(col_M, bg="black", height=2).pack(fill="x", pady=6)
        tk.Label(col_M, text="GENERAL TIMERS", font=("Arial",12,"bold"),
                 fg="#1565c0", bg="#e0e0e0").pack(pady=(2,2))
        for spec in specs[:3]:
            add_timer_widget(col_M, spec)

        tk.Label(col_R, text="EQUIPMENT TIMERS", font=("Arial",14,"bold"),
                 fg="#1565c0", bg="#e0e0e0").pack(pady=(45, 2))
        for spec in specs[3:]:
            add_timer_widget(col_R, spec)
    else:
        tk.Label(col_R, text="CYCLIC TIMERS", font=("Arial",14,"bold"),
                 fg="#1565c0", bg="#e0e0e0").pack(pady=(45, 2))
        for spec in specs:
            add_timer_widget(col_R, spec)

    room_detail_labels[room] = labels_d

    # Footer
    foot = tk.Frame(fr, bg="#eeeeee", height=52)
    foot.pack(side="bottom", fill="x")
    foot.pack_propagate(False)
    tk.Button(foot, text="← HOME",    font=MED, width=10,
              command=lambda: show(frame_home)).pack(side="left", padx=14, pady=8)
    tk.Button(foot, text="SETPOINTS", font=MED, width=12,
              command=lambda r=room: show(frame_set[r])).pack(side="left", padx=8, pady=8)
    tk.Button(foot, text="STOP ROOM", font=MED, width=12,
              command=lambda r=room: stop_room(r)).pack(side="left", padx=8, pady=8)
    tk.Button(foot, text="EXIT",      font=MED, width=10,
              command=root.destroy).pack(side="right", padx=14, pady=8)

build_room_screen(1)
build_room_screen(2)
build_room_screen(3)



sp_labels = {}      
sp_selected_key   = None
sp_entered_value  = ""
sp_active_room    = 1

def build_setpoint_screen(room):
    fr     = frame_set[room]
    color  = "#1565c0"
    labels_s = {}

    tk.Label(fr, text=f"ROOM {room} — SETPOINTS CONFIGURATION",
             font=BIG, fg=color, bg="white").pack(pady=(45, 8))

    # Setpoint footer
    foot = tk.Frame(fr, bg="#eeeeee", height=50)
    foot.pack(side="bottom", fill="x")
    foot.pack_propagate(False)
    tk.Button(foot, text="← ROOM",    font=MED, width=10,
              command=lambda r=room: (save_setpoints(r), show(frame_room[r]))).pack(side="left", padx=14, pady=6)
    tk.Button(foot, text="SAVE & EXIT", font=MED, bg="#1e90ff", fg="white", width=14,
              command=lambda r=room: (save_setpoints(r), show(frame_home))).pack(side="left", padx=8, pady=6)

    if room == 3:
        canvas = tk.Canvas(fr, bg="white", highlightthickness=0)
        scrollbar = tk.Scrollbar(fr, orient="vertical", command=canvas.yview)
        
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scroll_content = tk.Frame(canvas, bg="white")
        canvas_window = canvas.create_window((0, 0), window=scroll_content, anchor="nw")
        
        def on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        scroll_content.bind("<Configure>", on_configure)
        
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)
        
        def bind_mousewheel(event):
            canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        def unbind_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")
            
        canvas.bind("<Enter>", bind_mousewheel)
        canvas.bind("<Leave>", unbind_mousewheel)
        
        container = tk.Frame(scroll_content, bg="white")
        container.pack(pady=4, fill="both", expand=True)
        main_content_widget = canvas
    else:
        container = tk.Frame(fr, bg="white")
        container.pack(pady=4, fill="both", expand=True)
        main_content_widget = container

    # Helper function to create an inline editable parameter cell
    def make_cell(parent, key, label_text=None, width_lbl=12):
        if key not in setpoints[room]: return
        lbl_txt = label_text if label_text else key
        
        cell = tk.Frame(parent, bg="white")
        
        lbl_font = ("Arial", 11, "bold") if room == 3 else ("Arial", 9, "bold")
        val_font = ("Arial", 11, "bold") if room == 3 else ("Arial", 9, "bold")
        btn_font = ("Arial", 9, "bold") if room == 3 else ("Arial", 8, "bold")
        
        tk.Label(cell, text=lbl_txt, font=lbl_font, fg="#444",
                 bg="white", anchor="w", width=width_lbl + 2 if room == 3 else width_lbl).pack(side="left", padx=1)
        
        is_name = key.endswith("Name")
        val_lbl = tk.Label(cell, text=str(setpoints[room][key]),
                           font=val_font, fg="#333" if is_name else "#e65100",
                           bg="white", width=14 if is_name else 7 if room == 3 else 12 if is_name else 6, anchor="center")
        val_lbl.pack(side="left", padx=2)
        
        btn = tk.Button(cell, text="EDIT", font=btn_font, bg="#f5f5f5", fg="#333",
                        activebackground=color, activeforeground="white", bd=1, relief="groove",
                        command=lambda k=key, r=room: open_keypad_room(r, k))
        btn.pack(side="left", padx=1)
        
        labels_s[key] = val_lbl
        return cell

    def make_day_night_card(parent, prefix):
        title = setpoints[room].get(prefix+' Name', prefix.upper())
        card_font = ("Arial", 12, "bold") if room == 3 else ("Arial", 10, "bold")
        card = tk.LabelFrame(parent, text=f" {title} (CYCLIC) ",
                             font=card_font, fg=color, bg="white", bd=2, relief="groove")
        card.pack(fill="x", pady=4, padx=5)
        
        f_name = tk.Frame(card, bg="white")
        f_name.pack(fill="x", pady=4, padx=10)
        name_cell = make_cell(f_name, f"{prefix} Name", "Name:", width_lbl=8)
        if name_cell: name_cell.pack(side="left")

        grid_t = tk.Frame(card, bg="white")
        grid_t.pack(pady=4, padx=10, fill="x")
        grid_t.columnconfigure(0, weight=1, minsize=90 if room == 3 else 80)
        grid_t.columnconfigure(1, weight=2, minsize=130 if room == 3 else 120)
        grid_t.columnconfigure(2, weight=2, minsize=130 if room == 3 else 120)

        lbl_font = ("Arial", 11, "bold") if room == 3 else ("Arial", 9, "bold")
        btn_font = ("Arial", 9, "bold") if room == 3 else ("Arial", 8, "bold")

        tk.Label(grid_t, text="Setting", font=lbl_font, fg="#555", bg="white", width=10, anchor="w").grid(row=0, column=0, padx=2, pady=2)
        tk.Label(grid_t, text="Day", font=lbl_font, fg=color, bg="white", width=14, anchor="center").grid(row=0, column=1, padx=2, pady=2)
        tk.Label(grid_t, text="Night", font=lbl_font, fg=color, bg="white", width=14, anchor="center").grid(row=0, column=2, padx=2, pady=2)

        t_rows = [
            ("Start", f"{prefix} D_Start", f"{prefix} N_Start"),
            ("Stop", f"{prefix} D_Stop", f"{prefix} N_Stop"),
            ("ON Min", f"{prefix} D_ON Min", f"{prefix} N_ON Min"),
            ("OFF Min", f"{prefix} D_OFF Min", f"{prefix} N_OFF Min"),
        ]
        for r_idx, (r_lbl, d_key, n_key) in enumerate(t_rows, 1):
            tk.Label(grid_t, text=r_lbl+":", font=lbl_font, fg="#555", bg="white", width=10, anchor="w").grid(row=r_idx, column=0, padx=2, pady=2)
            
            c_day = tk.Frame(grid_t, bg="white")
            c_day.grid(row=r_idx, column=1, padx=2, pady=2, sticky="nsew")
            val_lbl_d = tk.Label(c_day, text=str(setpoints[room].get(d_key, "")), font=lbl_font, fg="#e65100", bg="white", width=8, anchor="center")
            val_lbl_d.pack(side="left", expand=True)
            tk.Button(c_day, text="EDIT", font=btn_font, bg="#f5f5f5", fg="#333", bd=1, relief="groove",
                      command=lambda k=d_key, r=room: open_keypad_room(r, k)).pack(side="right")
            labels_s[d_key] = val_lbl_d

            c_night = tk.Frame(grid_t, bg="white")
            c_night.grid(row=r_idx, column=2, padx=2, pady=2, sticky="nsew")
            val_lbl_n = tk.Label(c_night, text=str(setpoints[room].get(n_key, "")), font=lbl_font, fg="#e65100", bg="white", width=8, anchor="center")
            val_lbl_n.pack(side="left", expand=True)
            tk.Button(c_night, text="EDIT", font=btn_font, bg="#f5f5f5", fg="#333", bd=1, relief="groove",
                      command=lambda k=n_key, r=room: open_keypad_room(r, k)).pack(side="right")
            labels_s[n_key] = val_lbl_n

    def build_day_night_panel(parent, prefix):
        card = tk.Frame(parent, bg="white")
        title = setpoints[room].get(prefix+' Name', prefix.upper())
        title_font = ("Arial", 12, "bold") if room == 3 else ("Arial", 10, "bold")
        tk.Label(card, text=f" {title} ", font=title_font, fg=color, bg="white").pack(pady=2)
        
        f_name = tk.Frame(card, bg="white")
        f_name.pack(fill="x", pady=2, padx=5)
        name_cell = make_cell(f_name, f"{prefix} Name", "Name:", width_lbl=6)
        if name_cell: name_cell.pack(anchor="w")

        grid_t = tk.Frame(card, bg="white")
        grid_t.pack(pady=2, padx=5, fill="x")
        grid_t.columnconfigure(0, weight=1, minsize=60)
        grid_t.columnconfigure(1, weight=2, minsize=100)
        grid_t.columnconfigure(2, weight=2, minsize=100)

        lbl_font = ("Arial", 10, "bold") if room == 3 else ("Arial", 8, "bold")
        btn_font = ("Arial", 9, "bold") if room == 3 else ("Arial", 7, "bold")

        tk.Label(grid_t, text="Setting", font=lbl_font, fg="#555", bg="white", anchor="w").grid(row=0, column=0, padx=1, pady=1)
        tk.Label(grid_t, text="Day", font=lbl_font, fg=color, bg="white", anchor="center").grid(row=0, column=1, padx=1, pady=1)
        tk.Label(grid_t, text="Night", font=lbl_font, fg=color, bg="white", anchor="center").grid(row=0, column=2, padx=1, pady=1)

        t_rows = [
            ("Start", f"{prefix} D_Start", f"{prefix} N_Start"),
            ("Stop", f"{prefix} D_Stop", f"{prefix} N_Stop"),
            ("ON Min", f"{prefix} D_ON Min", f"{prefix} N_ON Min"),
            ("OFF Min", f"{prefix} D_OFF Min", f"{prefix} N_OFF Min"),
        ]
        if room == 3:
            if prefix.startswith("AC"):
                t_rows.append(("Temp Max", f"{prefix} D_T Max", f"{prefix} N_T Max"))
                t_rows.append(("Temp Min", f"{prefix} D_T Min", f"{prefix} N_T Min"))
            elif prefix.startswith("HUMI"):
                t_rows.append(("Humi Max", f"{prefix} D_H Max", f"{prefix} N_H Max"))
                t_rows.append(("Humi Min", f"{prefix} D_H Min", f"{prefix} N_H Min"))

        for r_idx, (r_lbl, d_key, n_key) in enumerate(t_rows, 1):
            tk.Label(grid_t, text=r_lbl+":", font=lbl_font, fg="#555", bg="white", anchor="w").grid(row=r_idx, column=0, padx=1, pady=1)
            
            c_day = tk.Frame(grid_t, bg="white")
            c_day.grid(row=r_idx, column=1, padx=1, pady=1, sticky="nsew")
            val_lbl_d = tk.Label(c_day, text=str(setpoints[room].get(d_key, "")), font=lbl_font, fg="#e65100", bg="white", width=6, anchor="center")
            val_lbl_d.pack(side="left", expand=True)
            tk.Button(c_day, text="EDIT", font=btn_font, bg="#f5f5f5", fg="#333", bd=1, relief="groove",
                      command=lambda k=d_key, r=room: open_keypad_room(r, k)).pack(side="right")
            labels_s[d_key] = val_lbl_d

            c_night = tk.Frame(grid_t, bg="white")
            c_night.grid(row=r_idx, column=2, padx=1, pady=1, sticky="nsew")
            val_lbl_n = tk.Label(c_night, text=str(setpoints[room].get(n_key, "")), font=lbl_font, fg="#e65100", bg="white", width=6, anchor="center")
            val_lbl_n.pack(side="left", expand=True)
            tk.Button(c_night, text="EDIT", font=btn_font, bg="#f5f5f5", fg="#333", bd=1, relief="groove",
                      command=lambda k=n_key, r=room: open_keypad_room(r, k)).pack(side="right")
            labels_s[n_key] = val_lbl_n
        return card

    def make_tabular_timers_card(parent):
        card_font = ("Arial", 12, "bold") if room == 3 else ("Arial", 10, "bold")
        card_timers = tk.LabelFrame(parent, text=" CYCLIC TIMERS ", font=card_font, fg=color, bg="white", bd=2, relief="groove")
        card_timers.pack(fill="x", pady=4, padx=5)
        
        cols = [
            {"name": "Timer 1", "keys": {
                "Name": "Timer1 Name", "Start": "Timer1 Start", "Stop": "Timer1 Stop", "ON Min": "Timer1 ON Min", "OFF Min": "Timer1 OFF Min"
            }},
            {"name": "Timer 2", "keys": {
                "Name": "Timer2 Name", "Start": "Timer2 Start", "Stop": "Timer2 Stop", "ON Min": "Timer2 ON Min", "OFF Min": "Timer2 OFF Min"
            }},
        ]
        
        lbl_font = ("Arial", 11, "bold") if room == 3 else ("Arial", 9, "bold")
        btn_font = ("Arial", 9, "bold") if room == 3 else ("Arial", 8, "bold")

        header_frame = tk.Frame(card_timers, bg="#f5f5f5")
        header_frame.pack(fill="x", pady=2, padx=2)
        tk.Label(header_frame, text="Setting", font=lbl_font, fg="#555", bg="#f5f5f5", width=12, anchor="w").pack(side="left", padx=2)
        for col in cols:
            tk.Label(header_frame, text=col["name"], font=lbl_font, fg=color, bg="#f5f5f5", width=15, anchor="center").pack(side="left", expand=True)
            
        row_keys = [("Name", "Name:"), ("Start", "Start:"), ("Stop", "Stop:"), ("ON Min", "ON Min:"), ("OFF Min", "OFF Min:")]
        
        for r_key, r_lbl in row_keys:
            r_frame = tk.Frame(card_timers, bg="white")
            r_frame.pack(fill="x", pady=3, padx=2)
            
            tk.Label(r_frame, text=r_lbl, font=lbl_font, fg="#555", bg="white", width=12, anchor="w").pack(side="left", padx=2)
            
            for col in cols:
                col_frame = tk.Frame(r_frame, bg="white")
                col_frame.pack(side="left", expand=True, fill="x")
                
                full_key = col["keys"][r_key]
                if full_key in setpoints[room]:
                    val_lbl = tk.Label(col_frame, text=str(setpoints[room][full_key]),
                                       font=lbl_font, fg="#e65100" if r_key != "Name" else "#333", bg="white", width=10, anchor="center")
                    val_lbl.pack(side="left", expand=True)
                    
                    btn = tk.Button(col_frame, text="EDIT", font=btn_font, bg="#f5f5f5", fg="#333",
                                    activebackground=color, activeforeground="white", bd=1, relief="groove",
                                    command=lambda k=full_key, r=room: open_keypad_room(r, k))
                    btn.pack(side="right", padx=2)
                    labels_s[full_key] = val_lbl

    if room == 3:
        top_container = tk.Frame(container, bg="white")
        top_container.pack(fill="x", expand=True)

        left_pane = tk.Frame(top_container, bg="white")
        left_pane.pack(side="left", fill="both", expand=True, padx=15)

        right_pane = tk.Frame(top_container, bg="white")
        right_pane.pack(side="right", fill="both", expand=True, padx=15)

        make_tabular_timers_card(left_pane)
        make_day_night_card(right_pane, "Timer3")

        bottom_container = tk.Frame(container, bg="white")
        bottom_container.pack(fill="x", expand=True, padx=15, pady=10)

        ac_card = tk.LabelFrame(bottom_container, text=" AC TIMERS (CYCLIC) ", 
                               font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
        ac_card.pack(fill="x", pady=6)
        ac_grid = tk.Frame(ac_card, bg="white")
        ac_grid.pack(fill="x", expand=True, padx=5, pady=5)
        ac_grid.columnconfigure(0, weight=1)
        ac_grid.columnconfigure(1, weight=0)
        ac_grid.columnconfigure(2, weight=1)
        build_day_night_panel(ac_grid, "AC1").grid(row=0, column=0, padx=10, pady=2, sticky="nsew")
        tk.Frame(ac_grid, bg="#bdbdbd", width=2).grid(row=0, column=1, sticky="ns", pady=5)
        build_day_night_panel(ac_grid, "AC2").grid(row=0, column=2, padx=10, pady=2, sticky="nsew")

        humi_card = tk.LabelFrame(bottom_container, text=" HUMIDIFIER TIMERS (CYCLIC) ", 
                                 font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
        humi_card.pack(fill="x", pady=6)
        humi_grid = tk.Frame(humi_card, bg="white")
        humi_grid.pack(fill="x", expand=True, padx=5, pady=5)
        humi_grid.columnconfigure(0, weight=1)
        humi_grid.columnconfigure(1, weight=0)
        humi_grid.columnconfigure(2, weight=1)
        build_day_night_panel(humi_grid, "HUMI1").grid(row=0, column=0, padx=10, pady=2, sticky="nsew")
        tk.Frame(humi_grid, bg="#bdbdbd", width=2).grid(row=0, column=1, sticky="ns", pady=5)
        build_day_night_panel(humi_grid, "HUMI2").grid(row=0, column=2, padx=10, pady=2, sticky="nsew")
    else:
        left_pane = tk.Frame(container, bg="white")
        left_pane.pack(side="left", fill="both", expand=True, padx=15)

        right_pane = tk.Frame(container, bg="white")
        right_pane.pack(side="right", fill="both", expand=True, padx=15)

        card_dosing = tk.LabelFrame(left_pane, text=" NUTRIENTS & PH ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
        card_dosing.pack(fill="x", pady=4, padx=5)
        
        grid_dosing = tk.Frame(card_dosing, bg="white")
        grid_dosing.pack(pady=4, padx=5)
        
        make_cell(grid_dosing, "EC MIN", "EC Min:").grid(row=0, column=0, padx=6, pady=2)
        make_cell(grid_dosing, "EC MAX", "EC Max:").grid(row=0, column=1, padx=6, pady=2)
        make_cell(grid_dosing, "PH LOW", "pH Low:").grid(row=1, column=0, padx=6, pady=2)
        make_cell(grid_dosing, "PH HIGH", "pH High:").grid(row=1, column=1, padx=6, pady=2)

        card_climate = tk.LabelFrame(left_pane, text=" CLIMATE CONTROL ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
        card_climate.pack(fill="x", pady=4, padx=5)
        
        grid_climate = tk.Frame(card_climate, bg="white")
        grid_climate.pack(pady=4, padx=5)
        
        make_cell(grid_climate, "D T Max", "Day T Max:").grid(row=0, column=0, padx=6, pady=2)
        make_cell(grid_climate, "DT Min", "Day T Min:").grid(row=0, column=1, padx=6, pady=2)
        make_cell(grid_climate, "N T Max", "Night T Max:").grid(row=1, column=0, padx=6, pady=2)
        make_cell(grid_climate, "N T Min", "Night T Min:").grid(row=1, column=1, padx=6, pady=2)
        make_cell(grid_climate, "H Max", "Humid Max:").grid(row=2, column=0, padx=6, pady=2)
        make_cell(grid_climate, "H Min", "Humid Min:").grid(row=2, column=1, padx=6, pady=2)

        make_day_night_card(left_pane, "Timer4")

        make_tabular_timers_card(right_pane)
        make_day_night_card(right_pane, "Timer3")

    sp_labels[room] = labels_s

    kp_frame    = tk.Frame(fr, bg="white")
    kp_title    = tk.Label(kp_frame, font=MED, fg=color, bg="white"); kp_title.pack()
    kp_display  = tk.Label(kp_frame, font=("Arial",18,"bold"), fg="#2e7d32", bg="white"); kp_display.pack()
    kp_buttons  = tk.Frame(kp_frame, bg="white"); kp_buttons.pack()
    kp_actions  = tk.Frame(kp_frame, bg="white"); kp_actions.pack(pady=4)

    def kp_press(v):
        global sp_entered_value
        sp_entered_value += str(v); kp_display.config(text=sp_entered_value)
    def kp_clear():
        global sp_entered_value
        sp_entered_value = ""; kp_display.config(text="")
    def kp_back():
        global sp_entered_value
        sp_entered_value = sp_entered_value[:-1]; kp_display.config(text=sp_entered_value)
    def kp_confirm():
        global sp_entered_value
        try:
            val = (str(sp_entered_value)
                   if sp_selected_key.endswith("Name") or ":" in sp_entered_value
                   else float(sp_entered_value))
            
            # Format validation for times
            if ":" in str(val) and not sp_selected_key.endswith("Name"):
                try:
                    datetime.datetime.strptime(str(val), "%H:%M")
                except:
                    kp_display.config(text="INVALID TIME")
                    return

            is_dn_key = False
            for p in ["Timer3", "Timer4", "AC1", "AC2", "HUMI1", "HUMI2"]:
                if sp_selected_key.startswith(p) and any(suffix in sp_selected_key for suffix in ["D_Start", "D_Stop", "N_Start", "N_Stop"]):
                    prefix = p
                    is_dn_key = True
                    break
            
            if is_dn_key:
                d_start = val if sp_selected_key == f"{prefix} D_Start" else setpoints[room].get(f"{prefix} D_Start", "10:00")
                d_stop  = val if sp_selected_key == f"{prefix} D_Stop" else setpoints[room].get(f"{prefix} D_Stop", "17:00")
                n_start = val if sp_selected_key == f"{prefix} N_Start" else setpoints[room].get(f"{prefix} N_Start", "17:01")
                n_stop  = val if sp_selected_key == f"{prefix} N_Stop" else setpoints[room].get(f"{prefix} N_Stop", "09:59")
                
                try:
                    t_d_start = datetime.datetime.strptime(str(d_start), "%H:%M").time()
                    t_d_stop  = datetime.datetime.strptime(str(d_stop),  "%H:%M").time()
                    t_n_start = datetime.datetime.strptime(str(n_start), "%H:%M").time()
                    t_n_stop  = datetime.datetime.strptime(str(n_stop),  "%H:%M").time()
                except:
                    kp_display.config(text="INVALID TIME")
                    return

                if (t_d_start >= t_d_stop or
                    t_n_start < t_d_stop or
                    t_d_start < t_n_stop or
                    t_n_start == t_n_stop):
                    kp_display.config(text="TIME CONFLICT")
                    return

            setpoints[room][sp_selected_key] = val
            sp_labels[room][sp_selected_key].config(text=str(val))
            kp_frame.pack_forget()
            if room == 3:
                main_content_widget.pack(side="left", fill="both", expand=True)
            else:
                main_content_widget.pack(pady=4)
        except: kp_display.config(text="ERROR")
    def kp_cancel():
        kp_frame.pack_forget()
        if room == 3:
            main_content_widget.pack(side="left", fill="both", expand=True)
        else:
            main_content_widget.pack(pady=4)

    def open_keypad_room(r, key):
        global sp_selected_key, sp_entered_value, sp_active_room
        sp_selected_key = key; sp_entered_value = ""; sp_active_room = r
        kp_display.config(text=""); kp_title.config(text=f"Set  {key}")
        for w in kp_buttons.winfo_children(): w.destroy()
        for w in kp_actions.winfo_children(): w.destroy()

        if key.endswith("Name"):
            for ri, row_k in enumerate([list("1234567890"),list("QWERTYUIOP"),
                                         list("ASDFGHJKL:"),list("ZXCVBNM._ ")]):
                for ci, ch in enumerate(row_k):
                    tk.Button(kp_buttons, text=ch if ch!=' ' else 'SPC',
                              font=("Arial",12,"bold"), width=3,
                              command=lambda x=ch: kp_press(x)).grid(row=ri,column=ci,padx=2,pady=2)
            w = 6
        else:
            for text,ri,ci in [('1',0,0),('2',0,1),('3',0,2),('4',1,0),('5',1,1),('6',1,2),
                                ('7',2,0),('8',2,1),('9',2,2),('.',3,0),('0',3,1),(':',3,2)]:
                tk.Button(kp_buttons, text=text, font=MED, width=4,
                          command=lambda x=text: kp_press(x)).grid(row=ri,column=ci,padx=3,pady=3)
            w = 4

        for txt,bg,fg,cmd in [("DEL","orange","black",kp_back),("CLR","#d9534f","white",kp_clear),
                               ("OK","green","white",kp_confirm),("CAN","red","white",kp_cancel)]:
            tk.Button(kp_actions, text=txt, font=MED, bg=bg, fg=fg,
                      width=w, command=cmd).pack(side="left", padx=4)

        main_content_widget.pack_forget()
        kp_frame.pack(pady=4)

    # Footer already packed at top of function

build_setpoint_screen(1)
build_setpoint_screen(2)
build_setpoint_screen(3)

def stop_room(room):
    if room == 3:
        for c in [R3_CH_AC1, R3_CH_AC2, R3_CH_HUMI1, R3_CH_HUMI2, R3_CH_TMR1, R3_CH_TMR2, R3_CH_TMR3, R3_CH_SPARE]:
            relay_off(c)
    else:
        ch  = ROOM_CHANNELS[room]
        tch = TIMER_CHANNELS[room]
        for c in [ch["ec1"],ch["ec2"],ch["ph"],ch["ac"],ch["humi"],tch[0],tch[1],tch[2]]:
            relay_off(c)
    st = state[room]
    st["ec_active"] = st["ph_active"] = st["ac_active"] = st["humi_active"] = False
    for ts in timer_state[room]: ts["state"] = "OFF"; ts["last"] = 0.0
    if room in room_detail_labels and "warn" in room_detail_labels[room]:
        room_detail_labels[room]["warn"].config(text=" ROOM STOPPED")

def restart_program():
    all_relays_off()
    for inst in [R1_soil,R1_md02,R1_orp,R1_co2,R2_soil,R2_md02,R2_orp,R2_co2,R3_md02_1,R3_md02_2,R3_co2]:
        try:
            if inst: inst.serial.close()
        except: pass
    os.execl(sys.executable, sys.executable, *sys.argv)

def refresh_labels(room, new_sp):
    if room in sp_labels:
        for k, v in new_sp.items():
            if k in sp_labels[room]:
                sp_labels[room][k].config(text=str(v))


def _on_off_color(is_on):
    return ("#2e7d32" if is_on else "#c62828"), ("ON" if is_on else "OFF")

def update_room_detail(room, data, warnings):
    d = room_detail_labels.get(room)
    if not d: return
    soil = data.get("soil"); rm = data.get("room")
    orp  = data.get("orp");  co2 = data.get("co2")

    def sv(lbl_key, text, err=False):
        # Deep Industrial Blue for values, Red for errors
        fg = "#c62828" if err else "#0d47a1"
        if lbl_key in d:
            d[lbl_key].config(text=text, fg=fg)

    if room == 3:
        m1 = data.get("md02_1")
        m2 = data.get("md02_2")
        co2 = data.get("co2")
        if m1:
            sv("md02_1_temp", f"{m1['room_temp']} °C")
            sv("md02_1_humi", f"{m1['room_humi']} %")
        else:
            sv("md02_1_temp", "SENSOR ERROR", err=True)
            sv("md02_1_humi", "SENSOR ERROR", err=True)
            
        if m2:
            sv("md02_2_temp", f"{m2['room_temp']} °C")
            sv("md02_2_humi", f"{m2['room_humi']} %")
        else:
            sv("md02_2_temp", "SENSOR ERROR", err=True)
            sv("md02_2_humi", "SENSOR ERROR", err=True)

        if co2 is not None:
            sv("co2", f"{co2} ppm")
        else:
            sv("co2", "SENSOR ERROR", err=True)

        d["warn"].config(text="\n".join(warnings))

        for key, is_on in [
            ("r_ac1",   relay_is_on(R3_CH_AC1)),
            ("r_ac2",   relay_is_on(R3_CH_AC2)),
            ("r_humi1", relay_is_on(R3_CH_HUMI1)),
            ("r_humi2", relay_is_on(R3_CH_HUMI2)),
            ("r_tmr1",  relay_is_on(R3_CH_TMR1)),
            ("r_tmr2",  relay_is_on(R3_CH_TMR2)),
            ("r_tmr3",  relay_is_on(R3_CH_TMR3)),
        ]:
            if key in d:
                fg, txt = _on_off_color(is_on)
                d[key].config(text=txt, fg=fg)
    else:
        soil = data.get("soil"); rm = data.get("room")
        orp  = data.get("orp");  co2 = data.get("co2")

        if soil:
            sv("soil_temp", f"{soil['soil_temp']} °C")
            sv("moisture",  f"{soil['moisture']} %")
            disp_ec = (soil['ec'] * 0.85) / 1000
            tds_ec = disp_ec * 500
            sv("ec",        f"{disp_ec:.2f} mS/cm ({tds_ec:.0f} ppm)")
            sv("ph",        f"{soil['ph']}")
        else:
            for k in ["soil_temp","moisture","ec","ph"]: sv(k, "SENSOR ERROR", err=True)

        if rm:
            sv("room_temp", f"{rm['room_temp']} °C")
            sv("room_humi", f"{rm['room_humi']} %")
        else:
            for k in ["room_temp", "room_humi"]: sv(k, "SENSOR ERROR", err=True)

        if orp is not None:
            sv("orp", f"{orp} mV")
        else:
            sv("orp", " SENSOR ERROR", err=True)

        if co2 is not None:
            sv("co2", f"{co2} ppm")
        else:
            sv("co2", " SENSOR ERROR", err=True)

        d["warn"].config(text="\n".join(warnings))

        st = state[room]; ch = ROOM_CHANNELS[room]
        for key, is_on in [
            ("ec_mode",  st["ec_active"]),   ("ph_mode",  st["ph_active"]),
            ("ac_mode",  st["ac_active"]),   ("humi_mode",st["humi_active"]),
            ("r_ec1",    relay_is_on(ch["ec1"])), ("r_ec2", relay_is_on(ch["ec2"])),
            ("r_ph",     relay_is_on(ch["ph"])),  ("r_ac",  relay_is_on(ch["ac"])),
            ("r_humi",   relay_is_on(ch["humi"])),
            ("r_tmr1",   relay_is_on(TIMER_CHANNELS[room][0])),
            ("r_tmr2",   relay_is_on(TIMER_CHANNELS[room][1])),
            ("r_tmr3",   relay_is_on(TIMER_CHANNELS[room][2])),
            ("r_tmr4",   (timer_state[room][3]["state"] == "ON")),
        ]:
            if key in d:
                fg, txt = _on_off_color(is_on)
                d[key].config(text=txt, fg=fg)

    sp = setpoints[room]
    specs = get_room_timer_specs(room)
    for i, spec in enumerate(specs):
        prefix = spec["prefix"]
        if f"tname_{prefix}" in d:
            d[f"tname_{prefix}"].config(text=sp.get(f"{prefix} Name", prefix.upper()))
        ts = timer_state[room][i]
        ch = TIMER_CHANNELS[room][i]
        if f"{prefix}_status" in d:
            d[f"{prefix}_status"].config(
                text=f"{'ON' if relay_is_on(ch) else 'OFF'} ({ts['state']})")
        if spec["type"] == "day_night":
            if f"{prefix}_window" in d:
                d[f"{prefix}_window"].config(
                    text=f"D:{sp.get(f'{prefix} D_Start','10:00')}-{sp.get(f'{prefix} D_Stop','17:00')} N:{sp.get(f'{prefix} N_Start','17:05')}-{sp.get(f'{prefix} N_Stop','09:55')}")
            if f"{prefix}_cycle" in d:
                d[f"{prefix}_cycle"].config(
                    text=f"D:{sp.get(f'{prefix} D_ON Min',15)}m/D:{sp.get(f'{prefix} D_OFF Min',30)}m N:{sp.get(f'{prefix} N_ON Min',15)}m/N:{sp.get(f'{prefix} N_OFF Min',30)}m")
        else:
            if f"{prefix}_window" in d:
                d[f"{prefix}_window"].config(
                    text=f"{sp.get(f'{prefix} Start','10:00')} – {sp.get(f'{prefix} Stop','17:00')}")
            if f"{prefix}_cycle" in d:
                d[f"{prefix}_cycle"].config(
                    text=f"{sp.get(f'{prefix} ON Min',15)}m ON / {sp.get(f'{prefix} OFF Min',30)}m OFF")

def update_home_summary(room, data):
    sm = room_summary.get(room)
    if not sm: return

    def sv(key, text, err=False):
        fg = "#c62828" if err else "#1a237e"
        if key in sm:
            sm[key].config(text=text, fg=fg)

    if room == 3:
        m1 = data.get("md02_1")
        m2 = data.get("md02_2")
        co2 = data.get("co2")

        if m1:
            sv("md02_1_temp", f"{m1['room_temp']} °C")
            sv("md02_1_humi", f"{m1['room_humi']} %")
        else:
            sv("md02_1_temp", "NA", err=True)
            sv("md02_1_humi", "NA", err=True)

        if m2:
            sv("md02_2_temp", f"{m2['room_temp']} °C")
            sv("md02_2_humi", f"{m2['room_humi']} %")
        else:
            sv("md02_2_temp", "NA", err=True)
            sv("md02_2_humi", "NA", err=True)

        if co2 is not None:
            sv("co2", f"{co2} ppm")
        else:
            sv("co2", "NA", err=True)
    else:
        soil = data.get("soil"); rm = data.get("room")
        orp  = data.get("orp");  co2 = data.get("co2")

        if soil:
            disp_ec = (soil['ec'] * 0.85) / 1000
            sv("ec", f"{disp_ec:.2f} mS/cm")
            sv("ph", f"{soil['ph']}")
        else:
            sv("ec", "NA", err=True)
            sv("ph", "NA", err=True)

        if rm:
            sv("room_temp", f"{rm['room_temp']} °C")
            sv("room_humi", f"{rm['room_humi']} %")
        else:
            sv("room_temp", "NA", err=True)
            sv("room_humi", "NA", err=True)

        if orp is not None:
            sv("orp", f"{orp} mV")
        else:
            sv("orp", "NA", err=True)

        if co2 is not None:
            sv("co2", f"{co2} ppm")
        else:
            sv("co2", "NA", err=True)


# Global cache for sensor readings
sensor_data_cache = {
    1: {"soil": None, "room": None, "orp": None, "co2": None},
    2: {"soil": None, "room": None, "orp": None, "co2": None},
    3: {"soil": None, "room": None, "orp": None, "co2": None}
}

def sensor_polling_worker():
    """Background thread: Polling sensors at their own pace."""
    while True:
        try:
            sensor_data_cache[1] = read_all_sensors(1)
            time.sleep(0.5)
            sensor_data_cache[2] = read_all_sensors(2)
            time.sleep(0.5)
            sensor_data_cache[3] = read_all_sensors(3)
            time.sleep(1.0)
        except Exception as e:
            time.sleep(2)

def publish_live_telemetry(d1, d2, d3):
    try:
        # We assume control_client is globally available as it is defined at the module level.
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ts_str = datetime.datetime.now(ist_tz).isoformat()
        
        for room, d in [(1, d1), (2, d2), (3, d3)]:
            if room == 3:
                payload = {
                    "md02_1": d.get("md02_1"),
                    "md02_2": d.get("md02_2"),
                    "co2": d.get("co2"),
                    "timer_state": timer_state[room],
                    "relay_status": {
                        "ac1": relay_is_on(ROOM_CHANNELS[room]["ac1"]),
                        "ac2": relay_is_on(ROOM_CHANNELS[room]["ac2"]),
                        "humi1": relay_is_on(ROOM_CHANNELS[room]["humi1"]),
                        "humi2": relay_is_on(ROOM_CHANNELS[room]["humi2"]),
                        "tmr1": relay_is_on(TIMER_CHANNELS[room][0]),
                        "tmr2": relay_is_on(TIMER_CHANNELS[room][1]),
                        "tmr3": relay_is_on(TIMER_CHANNELS[room][2])
                    },
                    "device": DEVICE_NAME,
                    "timestamp": ts_str
                }
            else:
                soil_data = dict(d.get("soil")) if d.get("soil") else None
                if soil_data and soil_data.get("ec") is not None:
                    soil_data["ec"] = round((soil_data["ec"] * 0.85) / 1000, 2)
                    
                payload = {
                    "soil": soil_data,
                    "room": d.get("room"),
                    "orp": d.get("orp"),
                    "co2": d.get("co2"),
                    "timer_state": timer_state[room],
                    "relay_status": {
                        "ec1": relay_is_on(ROOM_CHANNELS[room]["ec1"]),
                        "ec2": relay_is_on(ROOM_CHANNELS[room]["ec2"]),
                        "ph": relay_is_on(ROOM_CHANNELS[room]["ph"]),
                        "ac": relay_is_on(ROOM_CHANNELS[room]["ac"]),
                        "humi": relay_is_on(ROOM_CHANNELS[room]["humi"]),
                        "tmr1": relay_is_on(TIMER_CHANNELS[room][0]),
                        "tmr2": relay_is_on(TIMER_CHANNELS[room][1]),
                        "tmr3": relay_is_on(TIMER_CHANNELS[room][2])
                    },
                    "device": DEVICE_NAME,
                    "timestamp": ts_str
                }
            control_client.publish(f"inhydro/{DEVICE_NAME}/room{room}/telemetry/live", json.dumps(payload))
    except Exception as e:
        pass

local_log_lock = threading.Lock()
last_local_save_time = 0
LOCAL_LOG_FILE = os.path.join(BASE_DIR, "local_data_log.json")

COLUMNS = [
    "timestamp",
    # Room 1 Sensors
    "r1_soil_ec", "r1_soil_ph", "r1_soil_temp", "r1_soil_moisture",
    "r1_room_temp", "r1_room_humi", "r1_orp", "r1_co2",
    # Room 1 Relays
    "r1_ec1", "r1_ec2", "r1_ph", "r1_ac", "r1_humi", "r1_tmr1", "r1_tmr2", "r1_tmr3",
    # Room 1 Timers (4 timers: State, Last Execution Timestamp)
    "r1_t1_state", "r1_t1_last",
    "r1_t2_state", "r1_t2_last",
    "r1_t3_state", "r1_t3_last",
    "r1_t4_state", "r1_t4_last",
    
    # Room 2 Sensors
    "r2_soil_ec", "r2_soil_ph", "r2_soil_temp", "r2_soil_moisture",
    "r2_room_temp", "r2_room_humi", "r2_orp", "r2_co2",
    # Room 2 Relays
    "r2_ec1", "r2_ec2", "r2_ph", "r2_ac", "r2_humi", "r2_tmr1", "r2_tmr2", "r2_tmr3",
    # Room 2 Timers (4 timers)
    "r2_t1_state", "r2_t1_last",
    "r2_t2_state", "r2_t2_last",
    "r2_t3_state", "r2_t3_last",
    "r2_t4_state", "r2_t4_last",

    # Room 3 Sensors
    "r3_soil_ec", "r3_soil_ph", "r3_soil_temp", "r3_soil_moisture",
    "r3_room_temp", "r3_room_humi", "r3_orp", "r3_co2",
    # Room 3 Relays
    "r3_ec1", "r3_ec2", "r3_ph", "r3_ac", "r3_humi", "r3_tmr1", "r3_tmr2", "r3_tmr3",
    # Room 3 Timers (4 timers)
    "r3_t1_state", "r3_t1_last",
    "r3_t2_state", "r3_t2_last",
    "r3_t3_state", "r3_t3_last",
    "r3_t4_state", "r3_t4_last"
]

def pack_entry(ts, d1, d2, d3):
    row = [ts]
    # Pack Room 1 Sensors
    s1 = d1.get("soil") if d1 else None
    s1_ec = None
    if s1 and s1.get("ec") is not None:
        s1_ec = round((s1["ec"] * 0.85) / 1000, 2)
    s1_ph = s1.get("ph") if s1 else None
    s1_temp = s1.get("soil_temp") if s1 else None
    s1_moist = s1.get("moisture") if s1 else None
    
    r1 = d1.get("room") if d1 else None
    r1_temp = r1.get("room_temp") if r1 else None
    r1_humi = r1.get("room_humi") if r1 else None
    
    row.extend([
        s1_ec, s1_ph, s1_temp, s1_moist,
        r1_temp, r1_humi,
        d1.get("orp") if d1 else None,
        d1.get("co2") if d1 else None
    ])
    
    # Pack Room 1 Relays
    row.extend([
        1 if relay_is_on(ROOM_CHANNELS[1]["ec1"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[1]["ec2"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[1]["ph"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[1]["ac"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[1]["humi"]) else 0,
        1 if relay_is_on(TIMER_CHANNELS[1][0]) else 0,
        1 if relay_is_on(TIMER_CHANNELS[1][1]) else 0,
        1 if relay_is_on(TIMER_CHANNELS[1][2]) else 0
    ])
    
    # Pack Room 1 Timers (4 timers)
    for i in range(4):
        state_val = timer_state[1][i]["state"] if len(timer_state[1]) > i else "OFF"
        last_val = timer_state[1][i]["last"] if len(timer_state[1]) > i else 0.0
        row.extend([1 if state_val == "ON" else 0, last_val])
        
    # Pack Room 2 Sensors
    s2 = d2.get("soil") if d2 else None
    s2_ec = None
    if s2 and s2.get("ec") is not None:
        s2_ec = round((s2["ec"] * 0.85) / 1000, 2)
    s2_ph = s2.get("ph") if s2 else None
    s2_temp = s2.get("soil_temp") if s2 else None
    s2_moist = s2.get("moisture") if s2 else None
    
    r2 = d2.get("room") if d2 else None
    r2_temp = r2.get("room_temp") if r2 else None
    r2_humi = r2.get("room_humi") if r2 else None
    
    row.extend([
        s2_ec, s2_ph, s2_temp, s2_moist,
        r2_temp, r2_humi,
        d2.get("orp") if d2 else None,
        d2.get("co2") if d2 else None
    ])
    
    # Pack Room 2 Relays
    row.extend([
        1 if relay_is_on(ROOM_CHANNELS[2]["ec1"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[2]["ec2"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[2]["ph"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[2]["ac"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[2]["humi"]) else 0,
        1 if relay_is_on(TIMER_CHANNELS[2][0]) else 0,
        1 if relay_is_on(TIMER_CHANNELS[2][1]) else 0,
        1 if relay_is_on(TIMER_CHANNELS[2][2]) else 0
    ])
    
    # Pack Room 2 Timers (4 timers)
    for i in range(4):
        state_val = timer_state[2][i]["state"] if len(timer_state[2]) > i else "OFF"
        last_val = timer_state[2][i]["last"] if len(timer_state[2]) > i else 0.0
        row.extend([1 if state_val == "ON" else 0, last_val])
        
    # Pack Room 3 Sensors
    s3 = d3.get("soil") if d3 else None
    s3_ec = None
    if s3 and s3.get("ec") is not None:
        s3_ec = round((s3["ec"] * 0.85) / 1000, 2)
    s3_ph = s3.get("ph") if s3 else None
    s3_temp = s3.get("soil_temp") if s3 else None
    s3_moist = s3.get("moisture") if s3 else None
    
    r3 = d3.get("room") if d3 else None
    r3_temp = r3.get("room_temp") if r3 else None
    r3_humi = r3.get("room_humi") if r3 else None
    
    row.extend([
        s3_ec, s3_ph, s3_temp, s3_moist,
        r3_temp, r3_humi,
        d3.get("orp") if d3 else None,
        d3.get("co2") if d3 else None
    ])
    
    # Pack Room 3 Relays
    row.extend([
        1 if relay_is_on(ROOM_CHANNELS[3]["ec1"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[3]["ec2"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[3]["ph"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[3]["ac"]) else 0,
        1 if relay_is_on(ROOM_CHANNELS[3]["humi"]) else 0,
        1 if relay_is_on(TIMER_CHANNELS[3][0]) else 0,
        1 if relay_is_on(TIMER_CHANNELS[3][1]) else 0,
        1 if relay_is_on(TIMER_CHANNELS[3][2]) else 0
    ])
    
    # Pack Room 3 Timers (4 timers)
    for i in range(4):
        state_val = timer_state[3][i]["state"] if len(timer_state[3]) > i else "OFF"
        last_val = timer_state[3][i]["last"] if len(timer_state[3]) > i else 0.0
        row.extend([1 if state_val == "ON" else 0, last_val])
        
    return row

def unpack_row(row):
    if not isinstance(row, list) or len(row) < 73:
        return None, None, None
    ts = row[0]
    
    # Unpack Room 1 Sensors
    s1 = None
    if any(row[i] is not None for i in [1, 2, 3, 4]):
        s1 = {
            "ec": row[1],
            "ph": row[2],
            "soil_temp": row[3],
            "moisture": row[4]
        }
    rm1 = None
    if any(row[i] is not None for i in [5, 6]):
        rm1 = {
            "room_temp": row[5],
            "room_humi": row[6]
        }
    r1_timers = []
    for i in range(4):
        t_state = "ON" if row[17 + i*2] == 1 else "OFF"
        t_last = row[18 + i*2]
        r1_timers.append({"state": t_state, "last": t_last})
        
    p1 = {
        "timestamp": ts,
        "soil": s1,
        "room": rm1,
        "orp": row[7],
        "co2": row[8],
        "timer_state": r1_timers,
        "relay_status": {
            "ec1": bool(row[9]),
            "ec2": bool(row[10]),
            "ph": bool(row[11]),
            "ac": bool(row[12]),
            "humi": bool(row[13]),
            "tmr1": bool(row[14]),
            "tmr2": bool(row[15]),
            "tmr3": bool(row[16])
        }
    }
    
    # Unpack Room 2 Sensors
    s2 = None
    if any(row[i] is not None for i in [25, 26, 27, 28]):
        s2 = {
            "ec": row[25],
            "ph": row[26],
            "soil_temp": row[27],
            "moisture": row[28]
        }
    rm2 = None
    if any(row[i] is not None for i in [29, 30]):
        rm2 = {
            "room_temp": row[29],
            "room_humi": row[30]
        }
    r2_timers = []
    for i in range(4):
        t_state = "ON" if row[41 + i*2] == 1 else "OFF"
        t_last = row[42 + i*2]
        r2_timers.append({"state": t_state, "last": t_last})
        
    p2 = {
        "timestamp": ts,
        "soil": s2,
        "room": rm2,
        "orp": row[31],
        "co2": row[32],
        "timer_state": r2_timers,
        "relay_status": {
            "ec1": bool(row[33]),
            "ec2": bool(row[34]),
            "ph": bool(row[35]),
            "ac": bool(row[36]),
            "humi": bool(row[37]),
            "tmr1": bool(row[38]),
            "tmr2": bool(row[39]),
            "tmr3": bool(row[40])
        }
    }

    # Unpack Room 3 Sensors
    s3 = None
    if any(row[i] is not None for i in [49, 50, 51, 52]):
        s3 = {
            "ec": row[49],
            "ph": row[50],
            "soil_temp": row[51],
            "moisture": row[52]
        }
    rm3 = None
    if any(row[i] is not None for i in [53, 54]):
        rm3 = {
            "room_temp": row[53],
            "room_humi": row[54]
        }
    r3_timers = []
    for i in range(4):
        t_state = "ON" if row[65 + i*2] == 1 else "OFF"
        t_last = row[66 + i*2]
        r3_timers.append({"state": t_state, "last": t_last})
        
    p3 = {
        "timestamp": ts,
        "soil": s3,
        "room": rm3,
        "orp": row[55],
        "co2": row[56],
        "timer_state": r3_timers,
        "relay_status": {
            "ec1": bool(row[57]),
            "ec2": bool(row[58]),
            "ph": bool(row[59]),
            "ac": bool(row[60]),
            "humi": bool(row[61]),
            "tmr1": bool(row[62]),
            "tmr2": bool(row[63]),
            "tmr3": bool(row[64])
        }
    }
    return p1, p2, p3

LOG_DIR = os.path.join(BASE_DIR, "local_logs")
ACTIVE_LOG_FILE = os.path.join(LOG_DIR, "active.jsonl")

def save_local_telemetry(d1, d2, d3):
    global last_local_save_time
    try:
        connected = is_mqtt_connected and control_client.is_connected()
    except:
        connected = False

    # Store locally ONLY when device is not connected to internet/broker
    if connected:
        return

    current_time = time.time()
    if current_time - last_local_save_time < 45:
        return

    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ts_str = datetime.datetime.now(ist_tz).isoformat()

    try:
        new_row = pack_entry(ts_str, d1, d2, d3)
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
            except:
                connected = False

            if connected and os.path.exists(LOG_DIR):
                files = [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl") or f == "active.jsonl"]
                if "active.jsonl" in files and os.path.exists(ACTIVE_LOG_FILE) and os.path.getsize(ACTIVE_LOG_FILE) > 0:
                    with local_log_lock:
                        rot_name = os.path.join(LOG_DIR, f"log_{int(time.time())}.jsonl")
                        try:
                            os.rename(ACTIVE_LOG_FILE, rot_name)
                        except:
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
                        try: os.remove(fpath)
                        except: pass
                        continue

                    print(f"[OfflineSync] Syncing segment {fname} with {len(rows)} entries...")
                    remaining_rows = list(rows)
                    success = True

                    batch_size = 500
                    for idx in range(0, len(rows), batch_size):
                        batch = rows[idx:idx+batch_size]

                        try:
                            conn = is_mqtt_connected and control_client.is_connected()
                        except:
                            conn = False
                        if not conn:
                            print("[OfflineSync] Lost connection during sync. Pausing.")
                            success = False
                            break

                        p1_batch = []
                        p2_batch = []
                        p3_batch = []
                        for row in batch:
                            p1, p2, p3 = unpack_row(row)
                            if p1: p1_batch.append(p1)
                            if p2: p2_batch.append(p2)
                            if p3: p3_batch.append(p3)

                        try:
                            if p1_batch:
                                control_client.publish(f"inhydro/{DEVICE_NAME}/room1/telemetry/live", json.dumps(p1_batch), qos=1)
                            if p2_batch:
                                control_client.publish(f"inhydro/{DEVICE_NAME}/room2/telemetry/live", json.dumps(p2_batch), qos=1)
                            if p3_batch:
                                control_client.publish(f"inhydro/{DEVICE_NAME}/room3/telemetry/live", json.dumps(p3_batch), qos=1)
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
    """Main UI Thread: Handles Timers and Relay Control (Never blocks)."""
    d1 = sensor_data_cache[1]
    d2 = sensor_data_cache[2]
    d3 = sensor_data_cache[3]

    w1 = control_room(1, d1)
    w2 = control_room(2, d2)
    w3 = control_room(3, d3)

    run_timers(1)
    run_timers(2)
    run_timers(3)

    update_home_summary(1, d1)
    update_home_summary(2, d2)
    update_home_summary(3, d3)
    update_room_detail(1, d1, w1)
    update_room_detail(2, d2, w2)
    update_room_detail(3, d3, w3)

    publish_telemetry(d1, d2, d3)
    publish_live_telemetry(d1, d2, d3)
    save_local_telemetry(d1, d2, d3)

    root.after(1000, update)


def main_loop():
    threading.Thread(target=auto_trust_devices,     daemon=True).start()
    threading.Thread(target=start_bluetooth_server, daemon=True).start()
    threading.Thread(target=sensor_polling_worker, daemon=True).start()
    threading.Thread(target=sync_offline_data_worker, daemon=True).start()

    
    show(frame_home)
    
    print(" System Online — All functionalities active & Multi-threaded")
    update()
    root.mainloop()

if __name__ == "__main__":
    main_loop()
   