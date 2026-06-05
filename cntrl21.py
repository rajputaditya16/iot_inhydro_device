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
                R2_CH_EC1, R2_CH_EC2, R2_CH_PH, R2_CH_AC, R2_CH_HUMI, R2_CH_TMR1, R2_CH_TMR2, R2_CH_TMR3]

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


def default_setpoints():
    return {
        "EC MIN": 1.2, "EC MAX": 1.8,
        "PH LOW": 5.8,  "PH HIGH": 6.5,
        "D T Max": 35.0, "DT Min": 15.0,
        "N T Max": 35.0, "N T Min": 15.0,
        "H Max": 80.0, "H Min": 30.0,
        "Timer1 Name": "TIMER 1",
        "Timer1 Start": "10:00", "Timer1 Stop": "17:00",
        "Timer1 ON Min": 15,     "Timer1 OFF Min": 30,
        "Timer2 Name": "TIMER 2",
        "Timer2 Start": "10:00", "Timer2 Stop": "17:00",
        "Timer2 ON Min": 15,     "Timer2 OFF Min": 30,
        "Timer3 Name": "TIMER 3",
        "Timer3 Start": "10:00", "Timer3 Stop": "17:00",
        "Timer3 ON Min": 15,     "Timer3 OFF Min": 30,
        "Timer4 Name": "AC TIMER",
        "Timer4 D_Start": "10:00", "Timer4 D_Stop": "17:00",
        "Timer4 D_ON Min": 15,     "Timer4 D_OFF Min": 30,
        "Timer4 N_Start": "10:00", "Timer4 N_Stop": "17:00",
        "Timer4 N_ON Min": 15,     "Timer4 N_OFF Min": 30,
        "CLIENT ID": "", "USERNAME": "", "PASSWORD": "",
        "CHANNEL ID": "", "PORT": 1883,
        "READ API KEY": "", "WRITE API KEY": "",
    }

setpoints = {1: default_setpoints(), 2: default_setpoints()}

def load_setpoints(room):
    f = SP_FILE[room]
    if os.path.exists(f):
        try:
            with open(f) as fp: setpoints[room].update(json.load(fp))
            print(f"✅ Room {room} setpoints loaded")
        except: pass

load_setpoints(1)
load_setpoints(2)

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

def publish_telemetry(d1, d2):
    """d1 = Room1 sensor dict, d2 = Room2 sensor dict. Each field = JSON array."""
    global last_cloud_publish_time
    current_time = time.time()
    if current_time - last_cloud_publish_time < 35:
        return
        
    def arr(a, b): return json.dumps([a, b])
    s1 = d1.get("soil"); s2 = d2.get("soil")
    r1 = d1.get("room"); r2 = d2.get("room")
    fields = {
        "field1": arr(_v(s1['soil_temp'] if s1 else None), _v(s2['soil_temp'] if s2 else None)),
        "field2": arr(_v(s1['moisture']  if s1 else None), _v(s2['moisture']  if s2 else None)),
        "field3": arr(_v((s1['ec'] * 0.85)/1000 if s1 and s1.get('ec') is not None else None), _v((s2['ec'] * 0.85)/1000 if s2 and s2.get('ec') is not None else None)),
        "field4": arr(_v(s1['ph']        if s1 else None), _v(s2['ph']        if s2 else None)),
        "field5": arr(_v(r1['room_temp'] if r1 else None), _v(r2['room_temp'] if r2 else None)),
        "field6": arr(_v(r1['room_humi'] if r1 else None), _v(r2['room_humi'] if r2 else None)),
        "field7": arr(_v(d1.get('orp')), _v(d2.get('orp'))),
        "field8": arr(_v(d1.get('co2')), _v(d2.get('co2'))),
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

        # Validate day/night timer bounds for Timer 4 to avoid conflicts
        d_start = new_sp.get("Timer4 D_Start", setpoints[room].get("Timer4 D_Start", "10:00"))
        d_stop  = new_sp.get("Timer4 D_Stop", setpoints[room].get("Timer4 D_Stop", "17:00"))
        n_start = new_sp.get("Timer4 N_Start", setpoints[room].get("Timer4 N_Start", "17:01"))
        n_stop  = new_sp.get("Timer4 N_Stop", setpoints[room].get("Timer4 N_Stop", "09:59"))
        
        # Also validate formatting of any updated time values
        time_keys = [
            "Timer1 Start", "Timer1 Stop",
            "Timer2 Start", "Timer2 Stop",
            "Timer3 Start", "Timer3 Stop",
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

        if d_stop == n_start or n_stop == d_start:
            print(f"⚠️ Remote setpoint reject: Day/Night timer conflict")
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

import uuid
client_id = f"Inhydro_Dual_{DEVICE_NAME.strip()}_{uuid.uuid4().hex[:6]}"
control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
control_client.on_message = on_control_message
try:
    control_client.connect(CONTROL_BROKER, CONTROL_PORT, 60)
    for room in [1, 2]:
        control_client.subscribe(f"inhydro/{DEVICE_NAME}/room{room}/setpoints/update")
        control_client.subscribe(f"inhydro/{DEVICE_NAME}/room{room}/setpoints/request_sync")
        control_client.publish(
            f"inhydro/{DEVICE_NAME}/room{room}/setpoints/current",
            json.dumps(setpoints[room]), retain=True)
    control_client.loop_start()
    print("✅ Control MQTT (HiveMQ) connected")
except:
    print("⚠️  Control MQTT offline")



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
    else:
        return {
            "soil": read_soil(R2_soil, "R2 Soil"),
            "room": read_md02(R2_md02, "R2 MD02"),
            "orp": read_orp(R2_orp, "R2 ORP"),
            "co2": read_co2(R2_co2, "R2 CO2"),
        }



state = {
    1: {"ec_active": False, "ph_active": False, "ac_active": False,
        "humi_active": False, "last_ec": 0.0, "last_ph": 0.0},
    2: {"ec_active": False, "ph_active": False, "ac_active": False,
        "humi_active": False, "last_ec": 0.0, "last_ph": 0.0},
}

ROOM_CHANNELS = {
    1: {"ec1": R1_CH_EC1, "ec2": R1_CH_EC2, "ph": R1_CH_PH,
        "ac": R1_CH_AC,   "humi": R1_CH_HUMI},
    2: {"ec1": R2_CH_EC1, "ec2": R2_CH_EC2, "ph": R2_CH_PH,
        "ac": R2_CH_AC,   "humi": R2_CH_HUMI},
}

def control_room(room, data):
    st  = state[room]
    sp  = setpoints[room]
    ch  = ROOM_CHANNELS[room]
    now = time.time()
    warnings = []

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
    1: [{"state": "OFF", "last": 0.0}, {"state": "OFF", "last": 0.0}, {"state": "OFF", "last": 0.0}, {"state": "OFF", "last": 0.0}],
    2: [{"state": "OFF", "last": 0.0}, {"state": "OFF", "last": 0.0}, {"state": "OFF", "last": 0.0}, {"state": "OFF", "last": 0.0}],
}

TIMER_CHANNELS = {
    1: [R1_CH_TMR1, R1_CH_TMR2, R1_CH_TMR3, R1_CH_AC],
    2: [R2_CH_TMR1, R2_CH_TMR2, R2_CH_TMR3, R2_CH_AC],
}

TIMER_KEYS = [
    ("Timer1 Start","Timer1 Stop","Timer1 ON Min","Timer1 OFF Min"),
    ("Timer2 Start","Timer2 Stop","Timer2 ON Min","Timer2 OFF Min"),
    ("Timer3 Start","Timer3 Stop","Timer3 ON Min","Timer3 OFF Min"),
    ("Timer4 D_Start","Timer4 D_Stop","Timer4 D_ON Min","Timer4 D_OFF Min"),
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
    for i, (sk, ek, onk, offk) in enumerate(TIMER_KEYS):
        ch       = TIMER_CHANNELS[room][i]
        ts       = timer_state[room][i]
        is_ac_timer = (ch == ROOM_CHANNELS[room]["ac"])

        if is_ac_timer:
            in_day = is_within_window(sp.get("Timer4 D_Start", "10:00"), sp.get("Timer4 D_Stop", "17:00"))
            in_night = is_within_window(sp.get("Timer4 N_Start", "10:00"), sp.get("Timer4 N_Stop", "17:00"))
            in_window = in_day or in_night
            
            if in_night and not in_day:
                run_sec  = float(sp.get("Timer4 N_ON Min", 15)) * 60
                stop_sec = float(sp.get("Timer4 N_OFF Min", 30)) * 60
            else:
                run_sec  = float(sp.get("Timer4 D_ON Min", 15)) * 60
                stop_sec = float(sp.get("Timer4 D_OFF Min", 30)) * 60
        else:
            run_sec  = float(sp.get(onk,  15)) * 60
            stop_sec = float(sp.get(offk, 30)) * 60
            in_window = is_within_window(sp.get(sk,"10:00"), sp.get(ek,"17:00"))

        if in_window:
            if ts["state"] == "OFF":
                if now - ts["last"] >= stop_sec or ts["last"] == 0:
                    ts["state"] = "ON"; ts["last"] = now
                    print(f"Room{room} Timer{i+1} ON {datetime.datetime.now().strftime('%H:%M')}")
            elif ts["state"] == "ON":
                if now - ts["last"] >= run_sec:
                    ts["state"] = "OFF"; ts["last"] = now
                    print(f"Room{room} Timer{i+1} OFF — cycle complete")
                    
            # Enforce ON state (retry if modbus failed previously)
            if ts["state"] == "ON" and not is_ac_timer:
                if not relay_is_on(ch):
                    relay_on(ch)
            # Enforce OFF state 
            elif ts["state"] == "OFF" and not is_ac_timer:
                if relay_is_on(ch):
                    relay_off(ch)
        else:
            if ts["state"] == "ON" or (not is_ac_timer and relay_is_on(ch)):
                ts["state"] = "OFF"; ts["last"] = 0.0
                if not is_ac_timer:
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
    while True:
        try:
            out = subprocess.check_output(['bluetoothctl','paired-devices'], text=True)
            for line in out.split('\n'):
                if line.startswith('Device '):
                    os.system(f"sudo bluetoothctl trust {line.split()[1]} >/dev/null 2>&1")
        except: pass
        time.sleep(5)

def start_bluetooth_server():
    try:
        os.system("sudo sdptool add SP >/dev/null 2>&1"); time.sleep(1)
        srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        srv.bind((socket.BDADDR_ANY, 1)); srv.listen(1)
        print("Bluetooth RFCOMM server listening")
        while True:
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
            except Exception as e: print(f"BT error: {e}")
            finally:
                try: cli.close()
                except: pass
    except Exception as e: print(f"BT server failed: {e}")


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
frame_room   = {1: tk.Frame(root, bg="white"), 2: tk.Frame(root, bg="white")}
frame_set    = {1: tk.Frame(root, bg="white"), 2: tk.Frame(root, bg="white")}

active_room  = 1   # which room detail / setpoint screen is open

def show(frame):
    for f in [frame_home, frame_room[1], frame_room[2],
              frame_set[1], frame_set[2]]:
        f.pack_forget()
    frame.pack(fill="both", expand=True)
    try: lbl_logo.lift()
    except: pass



tk.Label(frame_home, text="INHYDRO — DUAL ROOM CONTROLLER",
         font=BIG, fg="#1565c0", bg="white").pack(pady=(10,4))

home_grid = tk.Frame(frame_home, bg="white")
home_grid.pack(fill="both", expand=True, padx=20, pady=8)

room_summary = {}   

def make_home_box(room):
    color = "#2e7d32"  # Green Border
    box = tk.Frame(home_grid, bg="#e0e0e0", bd=5, relief="groove", highlightbackground=color, highlightthickness=5)
    box.grid(row=0, column=room-1, sticky="nsew", padx=12, pady=4)
    home_grid.columnconfigure(room-1, weight=1)

    tk.Label(box, text=f"ROOM {room}", font=("Arial",18,"bold"),
             fg=color, bg="#e0e0e0").pack(pady=(12,2))

    inner = tk.Frame(box, bg="#e0e0e0")
    inner.pack(fill="both", expand=True, padx=10, pady=4)

    keys = ["soil_temp","moisture","ec","ph","room_temp","room_humi","orp","co2"]
    labels_map = {}
    display = {
        "soil_temp": "Water Temp", "moisture": "Moisture",
        "ec":        "Water EC",  "ph":       "Water pH",
        "room_temp": "Room Temp", "room_humi":"Room Humi",
        "orp":       "ORP",       "co2":      "CO2",
    }
    for k in keys:
        row_f = tk.Frame(inner, bg="#e0e0e0")
        # Increased pady to 3 for a thicker partition look
        row_f.pack(fill="x", pady=4)
        tk.Label(row_f, text=display[k], font=SML, fg="#333",
                 bg="#e0e0e0", width=12, anchor="w").pack(side="left")
        lbl = tk.Label(row_f, text="---", font=("Arial",16,"bold"),
                       fg="#0d47a1", bg="#e0e0e0", width=15, anchor="e")
        lbl.pack(side="right")
        labels_map[k] = lbl

    tk.Button(box, text=f"OPEN ROOM {room}", font=MED,
              bg=color, fg="white", bd=0,
              command=lambda r=room: open_room(r)).pack(pady=8, ipadx=8, ipady=4)

    room_summary[room] = labels_map

make_home_box(1)
make_home_box(2)

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
    color = "#1565c0" if room == 1 else "#6a1b9a"
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
        lbl = tk.Label(f, text="---", font=("Arial",13,"bold"),
                       fg="#0d47a1", bg="#e0e0e0", anchor="e")
        lbl.pack(side="right")
        labels_d[key] = lbl

    tk.Label(col_L, text="WATER SENSOR", font=("Arial",12,"bold"),
             fg="black", bg="#e0e0e0").pack(pady=(6,2))
    srow(col_L, "soil_temp", "Water Temp")
    srow(col_L, "moisture",  "Moisture")
    srow(col_L, "ec",        "EC")
    srow(col_L, "ph",        "pH")

    tk.Frame(col_L, bg="black", height=2).pack(fill="x", pady=8)
    tk.Label(col_L, text="ROOM SENSOR", font=("Arial",12,"bold"),
             fg="#6a1b9a", bg="#e0e0e0").pack(pady=(2,2))
    srow(col_L, "room_temp", "Room Temp")
    srow(col_L, "room_humi", "Room Humi")

    tk.Frame(col_L, bg="black", height=2).pack(fill="x", pady=8)
    tk.Label(col_L, text="CLIMATE SENSORS", font=("Arial",12,"bold"),
             fg="#004d40", bg="#e0e0e0").pack(pady=(2,2))
    srow(col_L, "orp",       "ORP Level")
    srow(col_L, "co2",       "CO2 Level")

    lbl_warn = tk.Label(col_L, text="", font=("Arial",10,"bold"), fg="#c62828",
                        bg="white", justify="left")
    lbl_warn.pack(pady=10)
    labels_d["warn"] = lbl_warn

    # MIDDLE — relay status
    tk.Label(col_M, text="RELAY STATUS", font=("Arial",14,"bold"),
             fg="#1565c0", bg="#e0e0e0").pack(pady=(6,4))

    ch = ROOM_CHANNELS[room]
    tmr_ch = TIMER_CHANNELS[room]
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
        tk.Label(f, text=lbl_text, font=SML, fg="#333",
                 bg="#e0e0e0", width=12, anchor="w").pack(side="left")
        lbl = tk.Label(f, text="OFF", font=("Arial",12,"bold"),
                       fg="#c62828", bg="#e0e0e0", anchor="e")
        lbl.pack(side="right")
        labels_d[key] = lbl

    # RIGHT — timers
    tk.Label(col_R, text="CYCLIC TIMERS", font=("Arial",14,"bold"),
             fg="#1565c0", bg="#e0e0e0").pack(pady=(45,2))

    for i in range(4):
        tname_key = f"Timer{i+1} Name"
        lbl_tname = tk.Label(col_R, text=setpoints[room].get(tname_key, f"TIMER {i+1}"),
                             font=("Arial",11,"bold"), fg="#1565c0", bg="#e0e0e0")
        lbl_tname.pack(pady=(2,0))
        labels_d[f"tname{i+1}"] = lbl_tname

        for sub_key, sub_lbl in [
            (f"t{i+1}_status", "Status"),
            (f"t{i+1}_window", "Window"),
            (f"t{i+1}_cycle",  "Cycle"),
        ]:
            f = tk.Frame(col_R, bg="white"); f.pack(fill="x", pady=0)
            tk.Label(f, text=sub_lbl, font=("Arial", 9), fg="#666",
                     bg="white", width=8, anchor="w").pack(side="left")
            lbl = tk.Label(f, text="---", font=("Arial", 9), fg="#333", bg="white", anchor="e")
            lbl.pack(side="right")
            labels_d[sub_key] = lbl

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



sp_labels = {}      
sp_selected_key   = None
sp_entered_value  = ""
sp_active_room    = 1

def build_setpoint_screen(room):
    fr     = frame_set[room]
    color  = "#1565c0" if room == 1 else "#6a1b9a"
    labels_s = {}

    tk.Label(fr, text=f"ROOM {room} — SETPOINTS CONFIGURATION",
             font=BIG, fg=color, bg="white").pack(pady=(45, 8))

    container = tk.Frame(fr, bg="white")
    container.pack(pady=4, fill="both", expand=True)

    # Left and Right Panes
    left_pane = tk.Frame(container, bg="white")
    left_pane.pack(side="left", fill="both", expand=True, padx=15)

    right_pane = tk.Frame(container, bg="white")
    right_pane.pack(side="right", fill="both", expand=True, padx=15)

    # Helper function to create an inline editable parameter cell
    def make_cell(parent, key, label_text=None, width_lbl=12):
        if key not in setpoints[room]: return
        lbl_txt = label_text if label_text else key
        
        cell = tk.Frame(parent, bg="white")
        
        tk.Label(cell, text=lbl_txt, font=("Arial", 9, "bold"), fg="#444",
                 bg="white", anchor="w", width=width_lbl).pack(side="left", padx=1)
        
        val_lbl = tk.Label(cell, text=str(setpoints[room][key]),
                           font=("Arial", 9, "bold"), fg="#e65100", bg="white", width=6, anchor="center")
        val_lbl.pack(side="left", padx=2)
        
        btn = tk.Button(cell, text="EDIT", font=("Arial", 8, "bold"), bg="#f5f5f5", fg="#333",
                        activebackground=color, activeforeground="white", bd=1, relief="groove",
                        command=lambda k=key, r=room: open_keypad_room(r, k))
        btn.pack(side="left", padx=1)
        
        labels_s[key] = val_lbl
        return cell

    # Nutrients & pH Card (Left Pane)
    card_dosing = tk.LabelFrame(left_pane, text=" NUTRIENTS & PH ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
    card_dosing.pack(fill="x", pady=4, padx=5)
    
    grid_dosing = tk.Frame(card_dosing, bg="white")
    grid_dosing.pack(pady=4, padx=5)
    
    make_cell(grid_dosing, "EC MIN", "EC Min:").grid(row=0, column=0, padx=6, pady=2)
    make_cell(grid_dosing, "EC MAX", "EC Max:").grid(row=0, column=1, padx=6, pady=2)
    make_cell(grid_dosing, "PH LOW", "pH Low:").grid(row=1, column=0, padx=6, pady=2)
    make_cell(grid_dosing, "PH HIGH", "pH High:").grid(row=1, column=1, padx=6, pady=2)

    # Climate Control Card (Left Pane)
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

    # AC Cyclic Timer Card (Left Pane, Down/Bottom)
    card_ac = tk.LabelFrame(left_pane, text=" AC TIMER (CYCLIC) ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
    card_ac.pack(fill="x", pady=4, padx=5)
    
    # AC Name Row
    f_ac_name = tk.Frame(card_ac, bg="white")
    f_ac_name.pack(fill="x", pady=2, padx=4)
    make_cell(f_ac_name, "Timer4 Name", "Name:", width_lbl=8)
    
    grid_ac = tk.Frame(card_ac, bg="white")
    grid_ac.pack(pady=2, padx=4)
    
    # Grid Headers
    tk.Label(grid_ac, text="Setting", font=("Arial", 9, "bold"), fg="#555", bg="white", width=8, anchor="w").grid(row=0, column=0, padx=2)
    tk.Label(grid_ac, text="Day", font=("Arial", 9, "bold"), fg=color, bg="white", width=10, anchor="center").grid(row=0, column=1, padx=2)
    tk.Label(grid_ac, text="Night", font=("Arial", 9, "bold"), fg=color, bg="white", width=10, anchor="center").grid(row=0, column=2, padx=2)
    
    ac_rows = [
        ("Start", "Timer4 D_Start", "Timer4 N_Start", "Start:"),
        ("Stop", "Timer4 D_Stop", "Timer4 N_Stop", "Stop:"),
        ("ON Min", "Timer4 D_ON Min", "Timer4 N_ON Min", "ON Min:"),
        ("OFF Min", "Timer4 D_OFF Min", "Timer4 N_OFF Min", "OFF Min:"),
    ]
    
    for r_idx, (r_key, d_key, n_key, r_lbl) in enumerate(ac_rows, 1):
        tk.Label(grid_ac, text=r_lbl, font=("Arial", 9, "bold"), fg="#555", bg="white", width=8, anchor="w").grid(row=r_idx, column=0, padx=2, pady=1)
        
        # Day cell
        c_day = tk.Frame(grid_ac, bg="white")
        c_day.grid(row=r_idx, column=1, padx=2, pady=1)
        val_lbl_d = tk.Label(c_day, text=str(setpoints[room][d_key]), font=("Arial", 9, "bold"), fg="#e65100", bg="white", width=6, anchor="center")
        val_lbl_d.pack(side="left")
        tk.Button(c_day, text="EDIT", font=("Arial", 8, "bold"), bg="#f5f5f5", fg="#333", bd=1, relief="groove",
                  command=lambda k=d_key, r=room: open_keypad_room(r, k)).pack(side="right")
        labels_s[d_key] = val_lbl_d
        
        # Night cell
        c_night = tk.Frame(grid_ac, bg="white")
        c_night.grid(row=r_idx, column=2, padx=2, pady=1)
        val_lbl_n = tk.Label(c_night, text=str(setpoints[room][n_key]), font=("Arial", 9, "bold"), fg="#e65100", bg="white", width=6, anchor="center")
        val_lbl_n.pack(side="left")
        tk.Button(c_night, text="EDIT", font=("Arial", 8, "bold"), bg="#f5f5f5", fg="#333", bd=1, relief="groove",
                  command=lambda k=n_key, r=room: open_keypad_room(r, k)).pack(side="right")
        labels_s[n_key] = val_lbl_n

    # Timers 1-3 Card (Right Pane)
    card_timers = tk.LabelFrame(right_pane, text=" CYCLIC TIMERS ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
    card_timers.pack(fill="both", expand=True, pady=4, padx=5)
    
    cols = [
        {"name": "Timer 1", "keys": {
            "Name": "Timer1 Name", "Start": "Timer1 Start", "Stop": "Timer1 Stop", "ON Min": "Timer1 ON Min", "OFF Min": "Timer1 OFF Min"
        }},
        {"name": "Timer 2", "keys": {
            "Name": "Timer2 Name", "Start": "Timer2 Start", "Stop": "Timer2 Stop", "ON Min": "Timer2 ON Min", "OFF Min": "Timer2 OFF Min"
        }},
        {"name": "Timer 3", "keys": {
            "Name": "Timer3 Name", "Start": "Timer3 Start", "Stop": "Timer3 Stop", "ON Min": "Timer3 ON Min", "OFF Min": "Timer3 OFF Min"
        }},
    ]
    
    # Tabular layout header
    header_frame = tk.Frame(card_timers, bg="#f5f5f5")
    header_frame.pack(fill="x", pady=2, padx=2)
    tk.Label(header_frame, text="Setting", font=("Arial", 9, "bold"), fg="#555", bg="#f5f5f5", width=12, anchor="w").pack(side="left", padx=2)
    for col in cols:
        tk.Label(header_frame, text=col["name"], font=("Arial", 9, "bold"), fg=color, bg="#f5f5f5", width=15, anchor="center").pack(side="left", expand=True)
        
    row_keys = [("Name", "Name:"), ("Start", "Start:"), ("Stop", "Stop:"), ("ON Min", "ON Min:"), ("OFF Min", "OFF Min:")]
    
    for r_key, r_lbl in row_keys:
        r_frame = tk.Frame(card_timers, bg="white")
        r_frame.pack(fill="x", pady=3, padx=2)
        
        tk.Label(r_frame, text=r_lbl, font=("Arial", 9, "bold"), fg="#555", bg="white", width=12, anchor="w").pack(side="left", padx=2)
        
        for col in cols:
            col_frame = tk.Frame(r_frame, bg="white")
            col_frame.pack(side="left", expand=True, fill="x")
            
            full_key = col["keys"][r_key]
            if full_key in setpoints[room]:
                val_lbl = tk.Label(col_frame, text=str(setpoints[room][full_key]),
                                   font=("Arial", 9, "bold"), fg="#e65100" if r_key != "Name" else "#333", bg="white", width=10, anchor="center")
                val_lbl.pack(side="left", expand=True)
                
                btn = tk.Button(col_frame, text="EDIT", font=("Arial", 8, "bold"), bg="#f5f5f5", fg="#333",
                                activebackground=color, activeforeground="white", bd=1, relief="groove",
                                command=lambda k=full_key, r=room: open_keypad_room(r, k))
                btn.pack(side="right", padx=2)
                labels_s[full_key] = val_lbl

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

            # Validate Day/Night AC timers: day stop != night start, and night stop != day start
            if sp_selected_key in ["Timer4 D_Start", "Timer4 D_Stop", "Timer4 N_Start", "Timer4 N_Stop"]:
                d_start = val if sp_selected_key == "Timer4 D_Start" else setpoints[room].get("Timer4 D_Start", "10:00")
                d_stop  = val if sp_selected_key == "Timer4 D_Stop" else setpoints[room].get("Timer4 D_Stop", "17:00")
                n_start = val if sp_selected_key == "Timer4 N_Start" else setpoints[room].get("Timer4 N_Start", "17:01")
                n_stop  = val if sp_selected_key == "Timer4 N_Stop" else setpoints[room].get("Timer4 N_Stop", "09:59")
                
                if d_stop == n_start or n_stop == d_start:
                    kp_display.config(text="TIME CONFLICT")
                    return

            setpoints[room][sp_selected_key] = val
            sp_labels[room][sp_selected_key].config(text=str(val))
            kp_frame.pack_forget(); container.pack(pady=4)
        except: kp_display.config(text="ERROR")
    def kp_cancel():
        kp_frame.pack_forget(); container.pack(pady=4)

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

        container.pack_forget(); kp_frame.pack(pady=4)

    # Setpoint footer
    foot = tk.Frame(fr, bg="#eeeeee", height=50)
    foot.pack(side="bottom", fill="x")
    foot.pack_propagate(False)
    tk.Button(foot, text="← ROOM",    font=MED, width=10,
              command=lambda r=room: (save_setpoints(r), show(frame_room[r]))).pack(side="left", padx=14, pady=6)
    tk.Button(foot, text="SAVE & EXIT", font=MED, bg="#1e90ff", fg="white", width=14,
              command=lambda r=room: (save_setpoints(r), show(frame_home))).pack(side="left", padx=8, pady=6)

build_setpoint_screen(1)
build_setpoint_screen(2)

def stop_room(room):
    ch  = ROOM_CHANNELS[room]
    tch = TIMER_CHANNELS[room]
    for c in [ch["ec1"],ch["ec2"],ch["ph"],ch["ac"],ch["humi"],tch[0],tch[1],tch[2]]:
        relay_off(c)
    st = state[room]
    st["ec_active"] = st["ph_active"] = st["ac_active"] = st["humi_active"] = False
    for ts in timer_state[room]: ts["state"] = "OFF"; ts["last"] = 0.0
    if room in room_detail_labels:
        room_detail_labels[room]["warn"].config(text=" ROOM STOPPED")

def restart_program():
    all_relays_off()
    for inst in [R1_soil,R1_md02,R1_orp,R1_co2,R2_soil,R2_md02,R2_orp,R2_co2]:
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
        d[lbl_key].config(text=text, fg=fg)

    if soil:
        sv("soil_temp", f"{soil['soil_temp']} °C")
        sv("moisture",  f"{soil['moisture']} %")
        disp_ec = (soil['ec'] * 0.85) / 1000
        sv("ec",        f"{disp_ec:.2f} µS/cm")
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

    st = state[room]; ch = ROOM_CHANNELS[room]; tch = TIMER_CHANNELS[room]
    for key, is_on in [
        ("ec_mode",  st["ec_active"]),   ("ph_mode",  st["ph_active"]),
        ("ac_mode",  st["ac_active"]),   ("humi_mode",st["humi_active"]),
        ("r_ec1",    relay_is_on(ch["ec1"])), ("r_ec2", relay_is_on(ch["ec2"])),
        ("r_ph",     relay_is_on(ch["ph"])),  ("r_ac",  relay_is_on(ch["ac"])),
        ("r_humi",   relay_is_on(ch["humi"])),
        ("r_tmr1",   relay_is_on(tch[0])),    ("r_tmr2", relay_is_on(tch[1])),
        ("r_tmr3",   relay_is_on(tch[2])),    ("r_tmr4", (timer_state[room][3]["state"] == "ON")),
    ]:
        fg, txt = _on_off_color(is_on)
        d[key].config(text=txt, fg=fg)

    sp = setpoints[room]
    for i in range(4):
        d[f"tname{i+1}"].config(text=sp.get(f"Timer{i+1} Name", f"TIMER {i+1}"))
        ts = timer_state[room][i]
        d[f"t{i+1}_status"].config(
            text=f"{'ON' if relay_is_on(tch[i]) else 'OFF'} ({ts['state']})")
        if i == 3:
            d[f"t{i+1}_window"].config(
                text=f"D:{sp.get('Timer4 D_Start','10:00')}-{sp.get('Timer4 D_Stop','17:00')} N:{sp.get('Timer4 N_Start','10:00')}-{sp.get('Timer4 N_Stop','17:00')}")
            d[f"t{i+1}_cycle"].config(
                text=f"D:{sp.get('Timer4 D_ON Min',15)}m/D:{sp.get('Timer4 D_OFF Min',30)}m N:{sp.get('Timer4 N_ON Min',15)}m/N:{sp.get('Timer4 N_OFF Min',30)}m")
        else:
            d[f"t{i+1}_window"].config(
                text=f"{sp.get(f'Timer{i+1} Start','10:00')} – {sp.get(f'Timer{i+1} Stop','17:00')}")
            d[f"t{i+1}_cycle"].config(
                text=f"{sp.get(f'Timer{i+1} ON Min',15)}m ON / {sp.get(f'Timer{i+1} OFF Min',30)}m OFF")

def update_home_summary(room, data):
    sm = room_summary.get(room)
    if not sm: return
    soil = data.get("soil"); rm = data.get("room")
    orp  = data.get("orp");  co2 = data.get("co2")

    def sv(key, text, err=False):
        fg = "#c62828" if err else "#1a237e"
        sm[key].config(text=text, fg=fg)

    if soil:
        sv("soil_temp", f"{soil['soil_temp']} °C")
        sv("moisture",  f"{soil['moisture']} %")
        disp_ec = (soil['ec'] * 0.85) / 1000
        sv("ec",        f"{disp_ec:.2f} µS/cm")
        sv("ph",        f"{soil['ph']}")
    else:
        for k in ["soil_temp","moisture","ec","ph"]: sv(k, "SENSOR ERROR", err=True)

    if rm:
        sv("room_temp", f"{rm['room_temp']} °C")
        sv("room_humi", f"{rm['room_humi']} %")
    else:
        sv("room_temp", "SENSOR ERROR", err=True)
        sv("room_humi", "SENSOR ERROR", err=True)

    if orp is not None:
        sv("orp", f"{orp} mV")
    else:
        sv("orp", " SENSOR ERROR", err=True)

    if co2 is not None:
        sv("co2", f"{co2} ppm")
    else:
        sv("co2", " SENSOR ERROR", err=True)


# Global cache for sensor readings
sensor_data_cache = {
    1: {"soil": None, "room": None, "orp": None, "co2": None},
    2: {"soil": None, "room": None, "orp": None, "co2": None}
}

def sensor_polling_worker():
    """Background thread: Polling sensors at their own pace."""
    while True:
        try:
            sensor_data_cache[1] = read_all_sensors(1)
            time.sleep(0.5)
            sensor_data_cache[2] = read_all_sensors(2)
            time.sleep(1.0)
        except Exception as e:
            time.sleep(2)

def publish_live_telemetry(d1, d2):
    try:
        # We assume control_client is globally available as it is defined at the module level.
        for room, d in [(1, d1), (2, d2)]:
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
                }
            }
            control_client.publish(f"inhydro/{DEVICE_NAME}/room{room}/telemetry/live", json.dumps(payload))
    except Exception as e:
        pass

last_local_save_time = 0
LOCAL_LOG_FILE = os.path.join(BASE_DIR, "local_data_log.json")

def save_local_telemetry(d1, d2):
    global last_local_save_time
    current_time = time.time()
    if current_time - last_local_save_time < 45:
        return
        
    s1 = d1.get("soil"); s2 = d2.get("soil")
    r1 = d1.get("room"); r2 = d2.get("room")
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def _v(v): return round(v, 2) if isinstance(v, (int, float)) else None
    
    record = {
        "timestamp": timestamp,
        "room1": {
            "water_temp": _v(s1['soil_temp'] if s1 else None),
            "moisture": _v(s1['moisture'] if s1 else None),
            "ec": _v((s1['ec'] * 0.85)/1000 if s1 and s1.get('ec') is not None else None),
            "ph": _v(s1['ph'] if s1 else None),
            "room_temp": _v(r1['room_temp'] if r1 else None),
            "room_humi": _v(r1['room_humi'] if r1 else None),
            "orp": _v(d1.get('orp')),
            "co2": _v(d1.get('co2'))
        },
        "room2": {
            "water_temp": _v(s2['soil_temp'] if s2 else None),
            "moisture": _v(s2['moisture'] if s2 else None),
            "ec": _v((s2['ec'] * 0.85)/1000 if s2 and s2.get('ec') is not None else None),
            "ph": _v(s2['ph'] if s2 else None),
            "room_temp": _v(r2['room_temp'] if r2 else None),
            "room_humi": _v(r2['room_humi'] if r2 else None),
            "orp": _v(d2.get('orp')),
            "co2": _v(d2.get('co2'))
        }
    }
    
    def write_thread():
        try:
            buffer = []
            if os.path.exists(LOCAL_LOG_FILE):
                try:
                    with open(LOCAL_LOG_FILE, "r") as f:
                        buffer = json.load(f)
                except:
                    buffer = []
                    
            if not isinstance(buffer, list):
                buffer = []
                
            buffer.append(record)
            if len(buffer) > 20000:
                buffer = buffer[-20000:]
                
            lines = ["  " + json.dumps(item) for item in buffer]
            with open(LOCAL_LOG_FILE, "w") as f:
                f.write("[\n" + ",\n".join(lines) + "\n]")
        except Exception as e:
            print(f"Local JSON save error: {e}")
            
    threading.Thread(target=write_thread, daemon=True).start()
    last_local_save_time = current_time

def update():
    """Main UI Thread: Handles Timers and Relay Control (Never blocks)."""
    d1 = sensor_data_cache[1]
    d2 = sensor_data_cache[2]

    w1 = control_room(1, d1)
    w2 = control_room(2, d2)

    run_timers(1)
    run_timers(2)

    update_home_summary(1, d1)
    update_home_summary(2, d2)
    update_room_detail(1, d1, w1)
    update_room_detail(2, d2, w2)

    publish_telemetry(d1, d2)
    publish_live_telemetry(d1, d2)
    save_local_telemetry(d1, d2)

    root.after(1000, update)


def main_loop():
    threading.Thread(target=auto_trust_devices,     daemon=True).start()
    threading.Thread(target=start_bluetooth_server, daemon=True).start()
    threading.Thread(target=sensor_polling_worker, daemon=True).start()

    
    show(frame_home)
    
    print(" System Online — All functionalities active & Multi-threaded")
    update()
    root.mainloop()

if __name__ == "__main__":
    main_loop()
   