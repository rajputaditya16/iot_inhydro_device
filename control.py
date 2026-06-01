import os, sys, json, time, datetime, atexit
import socket, subprocess, threading
import tkinter as tk
from PIL import Image, ImageTk
import minimalmodbus
import serial
import paho.mqtt.client as mqtt


# Room 1 sensor ports
R1_PORT_SOIL = "/dev/serial/by-path/usb-0:1.1-port0"
R1_PORT_MD02 = "/dev/serial/by-path/usb-0:1.2-port0"
R1_PORT_ORP  = "/dev/serial/by-path/usb-0:1.3-port0"
R1_PORT_CO2  = "/dev/serial/by-path/usb-0:1.4-port0"

# Room 2 sensor ports
R2_PORT_SOIL = "/dev/serial/by-path/usb-0:1.5-port0"
R2_PORT_MD02 = "/dev/serial/by-path/usb-0:1.6-port0"
R2_PORT_ORP  = "/dev/serial/by-path/usb-0:1.7-port0"
R2_PORT_CO2  = "/dev/serial/by-path/usb-0:1.8-port0"

# MODBUS SETTINGS
RELAY_BAUD = 9600
RELAY_PORT_FIXED = "/dev/serial/by-path/usb-0:1:2:1:0-port0"
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
    if set_relay(ch, True):
        _relay_state[ch] = True

def relay_off(ch):
    if set_relay(ch, False):
        _relay_state[ch] = False

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
R1_orp  = _open_sensor(R1_PORT_ORP,  "R1 ORP",  baudrate=9600)
R1_co2  = _open_sensor(R1_PORT_CO2,  "R1 CO2",  baudrate=9600)

R2_soil = _open_sensor(R2_PORT_SOIL, "R2 Soil", baudrate=9600)
R2_md02 = _open_sensor(R2_PORT_MD02, "R2 MD02", baudrate=9600)
R2_orp  = _open_sensor(R2_PORT_ORP,  "R2 ORP",  baudrate=9600)
R2_co2  = _open_sensor(R2_PORT_CO2,  "R2 CO2",  baudrate=9600)


def default_setpoints():
    return {
        "EC MIN": 1200, "EC MAX": 1800,
        "PH LOW": 5.8,  "PH HIGH": 6.5,
        "R T Max": 35.0, "R T Min": 15.0,
        "R H Max": 80.0, "R H Min": 30.0,
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
        "Timer4 Start": "10:00", "Timer4 Stop": "17:00",
        "Timer4 ON Min": 15,     "Timer4 OFF Min": 30,
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

OFFLINE_FILE = os.path.join(BASE_DIR, "offline_telemetry.json")
offline_lock = threading.Lock()

def save_to_buffer(fields):
    with offline_lock:
        try:
            buffer = []
            if os.path.exists(OFFLINE_FILE):
                with open(OFFLINE_FILE, "r") as f:
                    buffer = json.load(f)
            
            record = {
                "created_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            record.update(fields)
            buffer.append(record)
            
            # Cap at 100,000 entries (approx. 29 days of continuous 24/7 logging)
            if len(buffer) > 100000:
                buffer = buffer[-100000:]
                
            with open(OFFLINE_FILE, "w") as f:
                json.dump(buffer, f)
            print(f"💾 Telemetry saved to offline buffer (backlog: {len(buffer)} entries / approx. {round(len(buffer)/3456, 1)} days)")
        except Exception as e:
            print(f"Error saving to offline buffer: {e}")

def send_bulk_update(channel_id, write_key, updates_batch):
    import urllib.request
    url = f"https://api.thingspeak.com/channels/{channel_id}/bulk_update.json"
    headers = {"Content-Type": "application/json"}
    data = {
        "write_api_key": write_key,
        "updates": updates_batch
    }
    req_body = json.dumps(data).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=req_body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read().decode("utf-8")
            print(f"🟢 ThingSpeak Bulk Update Success! Response: {res_body}")
            return True
    except Exception as e:
        print(f"❌ ThingSpeak Bulk Update Failed: {e}")
        return False

def offline_buffer_worker():
    while True:
        time.sleep(5)
        
        sp = setpoints[1]
        write_key = sp.get("WRITE API KEY")
        channel_id = sp.get("CHANNEL ID")
        
        if not write_key or not channel_id:
            continue
            
        backlog_count = 0
        batch_to_send = []
        
        with offline_lock:
            if os.path.exists(OFFLINE_FILE):
                try:
                    with open(OFFLINE_FILE, "r") as f:
                        buffer = json.load(f)
                    backlog_count = len(buffer)
                    if backlog_count > 0:
                        batch_to_send = buffer[:900]
                except Exception as e:
                    print(f"Error reading buffer file: {e}")
                    try: os.remove(OFFLINE_FILE)
                    except: pass
                    buffer = []
        
        if batch_to_send:
            print(f"📤 Internet Connection found! Syncing backlog: {backlog_count} records remaining...")
            success = send_bulk_update(channel_id, write_key, batch_to_send)
            if success:
                with offline_lock:
                    if os.path.exists(OFFLINE_FILE):
                        with open(OFFLINE_FILE, "r") as f:
                            buffer = json.load(f)
                        if len(buffer) >= len(batch_to_send):
                            buffer = buffer[len(batch_to_send):]
                            with open(OFFLINE_FILE, "w") as f:
                                json.dump(buffer, f)
                print(f"✅ Successfully synced {len(batch_to_send)} records. Remaining backlog: {backlog_count - len(batch_to_send)}")
                time.sleep(1.5)  # High-speed catchup (1.5 seconds delay)
            else:
                time.sleep(15)

def _v(val): return val if val is not None else ""

last_cloud_publish_time = 0

def publish_telemetry(d1, d2):
    """d1 = Room1 sensor dict, d2 = Room2 sensor dict. Each field = JSON array."""
    global last_cloud_publish_time
    current_time = time.time()
    if current_time - last_cloud_publish_time < 25:
        return
        
    def arr(a, b): return json.dumps([a, b])
    s1 = d1.get("soil"); s2 = d2.get("soil")
    r1 = d1.get("room"); r2 = d2.get("room")
    fields = {
        "field1": arr(_v(s1['soil_temp'] if s1 else None), _v(s2['soil_temp'] if s2 else None)),
        "field2": arr(_v(s1['moisture']  if s1 else None), _v(s2['moisture']  if s2 else None)),
        "field3": arr(_v(s1['ec']        if s1 else None), _v(s2['ec']        if s2 else None)),
        "field4": arr(_v(s1['ph']        if s1 else None), _v(s2['ph']        if s2 else None)),
        "field5": arr(_v(r1['room_temp'] if r1 else None), _v(r2['room_temp'] if r2 else None)),
        "field6": arr(_v(r1['room_humi'] if r1 else None), _v(r2['room_humi'] if r2 else None)),
        "field7": arr(_v(d1.get('orp')), _v(d2.get('orp'))),
        "field8": arr(_v(d1.get('co2')), _v(d2.get('co2'))),
    }

    has_backlog = False
    with offline_lock:
        if os.path.exists(OFFLINE_FILE):
            try:
                with open(OFFLINE_FILE, "r") as f:
                    has_backlog = len(json.load(f)) > 0
            except:
                pass

    try:
        connected = mqtt_client.is_connected() if mqtt_client else False
    except:
        connected = False

    if connected and not has_backlog:
        try:
            payload = "&".join(f"{k}={v}" for k, v in fields.items())
            mqtt_client.publish(MQTT_TOPIC, payload)
            last_cloud_publish_time = current_time
            print("🚀 Telemetry published directly to Cloud successfully.")
        except Exception as e:
            print(f"ThingSpeak publish error, buffering locally: {e}")
            save_to_buffer(fields)
            last_cloud_publish_time = current_time
    else:
        save_to_buffer(fields)
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

control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Inhydro_Dual_Room_001")
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
        rt = inst.read_register(1, 1, signed=True)
        rh = inst.read_register(2, 1)
        return {"room_temp": rt, "room_humi": rh}
    except Exception as e:
        print(f"⚠️ [{label} MD02] Read failed: {e}")
        return None

def read_orp(inst, label):
    if not inst: return None
    try:
        inst.serial.reset_input_buffer()
        return inst.read_register(0x0000, 1, signed=True)
    except Exception as e:
        print(f"⚠️ [{label} ORP] Read failed: {e}")
        return None

def read_co2(inst, label):
    if not inst: return None
    try:
        inst.serial.reset_input_buffer()
        return inst.read_register(0x0000, 0)
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
        ec = soil["ec"]; ph = soil["ph"]

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
            if not st["ac_active"] and rt >= sp["R T Max"]:
                st["ac_active"] = True; relay_on(ch["ac"])
                warnings.append(f"⚠ TEMP HIGH (AC ON)")
                print(f"Room{room} AC ON — {rt}°C ≥ {sp['R T Max']}°C")

            if st["ac_active"] and rt <= sp["R T Min"]:
                st["ac_active"] = False; relay_off(ch["ac"])
                print(f"Room{room} AC OFF — {rt}°C ≤ {sp['R T Min']}°C")
        else:
            if st["ac_active"] or relay_is_on(ch["ac"]):
                st["ac_active"] = False; relay_off(ch["ac"])
                print(f"Room{room} AC OFF — Cyclic Timer window OFF")

        if not st["humi_active"] and rh >= sp["R H Max"]:
            st["humi_active"] = True; relay_on(ch["humi"])
            warnings.append(f"⚠ HUMI HIGH (HUM ON)")
            print(f"Room{room} Humidifier ON — {rh}% ≥ {sp['R H Max']}%")

        if st["humi_active"] and rh <= sp["R H Min"]:
            st["humi_active"] = False; relay_off(ch["humi"])
            print(f"Room{room} Humidifier OFF — {rh}% ≤ {sp['R H Min']}%")
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
    ("Timer4 Start","Timer4 Stop","Timer4 ON Min","Timer4 OFF Min"),
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
        run_sec  = float(sp.get(onk,  15)) * 60
        stop_sec = float(sp.get(offk, 30)) * 60

        is_ac_timer = (ch == ROOM_CHANNELS[room]["ac"])

        if is_within_window(sp.get(sk,"10:00"), sp.get(ek,"17:00")):
            if ts["state"] == "OFF":
                if now - ts["last"] >= stop_sec or ts["last"] == 0:
                    ts["state"] = "ON"; ts["last"] = now
                    if not is_ac_timer:
                        relay_on(ch)
                    print(f"Room{room} Timer{i+1} ON {datetime.datetime.now().strftime('%H:%M')}")
            elif ts["state"] == "ON":
                if now - ts["last"] >= run_sec:
                    ts["state"] = "OFF"; ts["last"] = now
                    if not is_ac_timer:
                        relay_off(ch)
                    print(f"Room{room} Timer{i+1} OFF — cycle complete")
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
             fg="#1565c0", bg="#e0e0e0").pack(pady=(4,2))

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

    tk.Label(fr, text=f"ROOM {room} — SETPOINTS",
             font=BIG, fg=color, bg="white").pack(pady=8)

    container = tk.Frame(fr, bg="white")
    container.pack(pady=4)

    col_i = row_i = 0

    def create_row(key):
        nonlocal col_i, row_i
        if key not in setpoints[room]: return
        cell = tk.Frame(container, bg="white")
        cell.grid(row=row_i, column=col_i, padx=4, pady=2)
        tk.Label(cell, text=key, font=("Arial", 11, "bold"), fg="#333",
                 bg="white", width=13).pack(side="left")
        val_lbl = tk.Label(cell, text=str(setpoints[room][key]),
                           font=("Arial",11,"bold"), fg="#ef6c00", bg="white", width=7)
        val_lbl.pack(side="left", padx=4)
        tk.Button(cell, text="EDIT", font=("Arial",9),
                  command=lambda k=key, r=room: open_keypad_room(r, k)).pack(side="left")
        labels_s[key] = val_lbl
        col_i += 1
        if col_i > 2: col_i = 0; row_i += 1

    for k in ["EC MIN","EC MAX","PH LOW","PH HIGH",
              "R T Max","R T Min","R H Max","R H Min",
              "Timer1 Name","Timer1 Start","Timer1 Stop","Timer1 ON Min","Timer1 OFF Min",
              "Timer2 Name","Timer2 Start","Timer2 Stop","Timer2 ON Min","Timer2 OFF Min",
              "Timer3 Name","Timer3 Start","Timer3 Stop","Timer3 ON Min","Timer3 OFF Min",
              "Timer4 Name","Timer4 Start","Timer4 Stop","Timer4 ON Min","Timer4 OFF Min"]:
        create_row(k)

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
    for inst in [R1_soil,R1_md02,R1_orp,R1_co2,R2_soil,R2_md02,R2_orp,R2_co2,_relay_inst]:
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
        sv("ec",        f"{soil['ec']} µS/cm")
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
        ("r_tmr3",   relay_is_on(tch[2])),    ("r_tmr4", relay_is_on(tch[3])),
    ]:
        fg, txt = _on_off_color(is_on)
        d[key].config(text=txt, fg=fg)

    sp = setpoints[room]
    for i in range(4):
        d[f"tname{i+1}"].config(text=sp.get(f"Timer{i+1} Name", f"TIMER {i+1}"))
        ts = timer_state[room][i]
        d[f"t{i+1}_status"].config(
            text=f"{'ON' if relay_is_on(tch[i]) else 'OFF'} ({ts['state']})")
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
        sv("ec",        f"{soil['ec']} µS/cm")
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
            payload = {
                "soil": d.get("soil"),
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

    root.after(1000, update)


def main_loop():
    threading.Thread(target=auto_trust_devices,     daemon=True).start()
    threading.Thread(target=start_bluetooth_server, daemon=True).start()
    threading.Thread(target=sensor_polling_worker, daemon=True).start()
    threading.Thread(target=offline_buffer_worker, daemon=True).start()
    
    show(frame_home)
    
    print(" System Online — All functionalities active & Multi-threaded")
    update()
    root.mainloop()

if __name__ == "__main__":
    main_loop()
