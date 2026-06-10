import os
import sys
import time
import datetime
import threading
import json
import uuid
import socket
import subprocess
import tkinter as tk
import minimalmodbus
import serial
import paho.mqtt.client as mqtt
from PIL import Image, ImageTk

BASE_DIR = os.path.dirname(os.path.realpath(sys.argv[0]))
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE) as f:
                return f.read().strip()
        except Exception:
            pass
    return "MONITOR_DEFAULT"

DEVICE_NAME = get_device_id()
SP_FILE = os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}_monitor.json")
LOCAL_LOG_FILE = os.path.join(BASE_DIR, "local_data_log_monitor.json")

setpoints = {
    "CLIENT ID": "",
    "USERNAME": "",
    "PASSWORD": "",
    "CHANNEL ID": "",
    "PORT": 1883,
    "READ API KEY": "",
    "WRITE API KEY": "",
    "EC MIN": 1.2,
    "EC MAX": 1.8,
    "PH LOW": 5.8,
    "PH HIGH": 6.5,
    "D T Max": 35.0,
    "DT Min": 15.0,
    "N T Max": 35.0,
    "N T Min": 15.0,
    "H Max": 80.0,
    "H Min": 30.0,
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
    "Timer4 Name": "AC TIMER",
    "Timer4 D_Start": "10:00",
    "Timer4 D_Stop": "17:00",
    "Timer4 D_ON Min": 15,
    "Timer4 D_OFF Min": 30,
    "Timer4 N_Start": "17:05",
    "Timer4 N_Stop": "09:55",
    "Timer4 N_ON Min": 15,
    "Timer4 N_OFF Min": 30,
    "Timer5 Name": "TIMER 5",
    "Timer5 Start": "10:00",
    "Timer5 Stop": "17:00",
    "Timer5 ON Min": 15,
    "Timer5 OFF Min": 30,
    "Timer6 Name": "TIMER 6",
    "Timer6 Start": "10:00",
    "Timer6 Stop": "17:00",
    "Timer6 ON Min": 15,
    "Timer6 OFF Min": 30,
    "Timer7 Name": "TIMER 7",
    "Timer7 Start": "10:00",
    "Timer7 Stop": "17:00",
    "Timer7 ON Min": 15,
    "Timer7 OFF Min": 30,
    "Timer8 Name": "TIMER 8",
    "Timer8 D_Start": "10:00",
    "Timer8 D_Stop": "17:00",
    "Timer8 D_ON Min": 15,
    "Timer8 D_OFF Min": 30,
    "Timer8 N_Start": "17:05",
    "Timer8 N_Stop": "09:55",
    "Timer8 N_ON Min": 15,
    "Timer8 N_OFF Min": 30,
    "Timer9 Name": "TIMER 9",
    "Timer9 D_Start": "10:00",
    "Timer9 D_Stop": "17:00",
    "Timer9 D_ON Min": 15,
    "Timer9 D_OFF Min": 30,
    "Timer9 N_Start": "17:05",
    "Timer9 N_Stop": "09:55",
    "Timer9 N_ON Min": 15,
    "Timer9 N_OFF Min": 30,
    "Timer10 Name": "TIMER 10",
    "Timer10 D_Start": "10:00",
    "Timer10 D_Stop": "17:00",
    "Timer10 D_ON Min": 15,
    "Timer10 D_OFF Min": 30,
    "Timer10 N_Start": "17:05",
    "Timer10 N_Stop": "09:55",
    "Timer10 N_ON Min": 15,
    "Timer10 N_OFF Min": 30,
}

if os.path.exists(SP_FILE):
    try:
        with open(SP_FILE) as fp:
            setpoints.update(json.load(fp))
    except Exception:
        pass

def save_setpoints():
    try:
        with open(SP_FILE, "w") as f:
            json.dump(setpoints, f, indent=4)
            
        topic = f"inhydro/{DEVICE_NAME}/monitor/setpoints/current"
        if control_client and control_client.is_connected():
            control_client.publish(topic, json.dumps(setpoints), retain=True)
    except Exception:
        pass


# --- ThingSpeak MQTT Setup ---
MQTT_BROKER = "mqtt3.thingspeak.com"
mqtt_client = None
MQTT_TOPIC = ""

def init_mqtt_client():
    global mqtt_client, MQTT_TOPIC
    if mqtt_client is not None:
        try:
            mqtt_client.disconnect()
            mqtt_client.loop_stop()
        except Exception:
            pass

    cid = str(setpoints.get("CLIENT ID", ""))
    user = str(setpoints.get("USERNAME", ""))
    pwd = str(setpoints.get("PASSWORD", ""))
    chid = str(setpoints.get("CHANNEL ID", ""))

    if not all([cid, user, pwd, chid]):
        return

    try:
        port = int(setpoints.get("PORT", 1883))
    except Exception:
        port = 1883

    MQTT_TOPIC = f"channels/{chid}/publish"
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, cid)
    mqtt_client.username_pw_set(user, pwd)
    
    try:
        mqtt_client.connect(MQTT_BROKER, port, 60)
        mqtt_client.loop_start()
    except Exception:
        pass

init_mqtt_client()


# --- Control MQTT Setup (HiveMQ) ---
CONTROL_BROKER = "broker.hivemq.com"
CONTROL_PORT = 1883

def on_control_message(client, userdata, msg):
    try:
        if "request_sync" in msg.topic:
            topic = f"inhydro/{DEVICE_NAME}/monitor/setpoints/current"
            control_client.publish(topic, json.dumps(setpoints), retain=True)
            return

        new_data = json.loads(msg.payload.decode())
        if not isinstance(new_data, dict):
            return
        
        key_map = {
            "clientId": "CLIENT ID",
            "username": "USERNAME",
            "password": "PASSWORD",
            "channelId": "CHANNEL ID",
            "port": "PORT",
            "readApiKey": "READ API KEY",
            "writeApiKey": "WRITE API KEY"
        }
        new_sp = {key_map.get(k, k): v for k, v in new_data.items()}

        # Validate time formats if updated
        time_keys = [
            "Timer1 Start", "Timer1 Stop",
            "Timer2 Start", "Timer2 Stop",
            "Timer3 Start", "Timer3 Stop",
            "Timer4 D_Start", "Timer4 D_Stop",
            "Timer4 N_Start", "Timer4 N_Stop",
            "Timer5 Start", "Timer5 Stop",
            "Timer6 Start", "Timer6 Stop",
            "Timer7 Start", "Timer7 Stop",
            "Timer8 D_Start", "Timer8 D_Stop",
            "Timer8 N_Start", "Timer8 N_Stop",
            "Timer9 D_Start", "Timer9 D_Stop",
            "Timer9 N_Start", "Timer9 N_Stop",
            "Timer10 D_Start", "Timer10 D_Stop",
            "Timer10 N_Start", "Timer10 N_Stop"
        ]
        for k in time_keys:
            if k in new_sp:
                try:
                    datetime.datetime.strptime(str(new_sp[k]), "%H:%M")
                except ValueError:
                    print(f"⚠️ Rejecting invalid time format for {k}: {new_sp[k]}")
                    return

        # Validate Day/Night conflict for Timers 4, 8, 9, 10
        for t_idx in [4, 8, 9, 10]:
            d_start = new_sp.get(f"Timer{t_idx} D_Start", setpoints.get(f"Timer{t_idx} D_Start", "10:00"))
            d_stop  = new_sp.get(f"Timer{t_idx} D_Stop", setpoints.get(f"Timer{t_idx} D_Stop", "17:00"))
            n_start = new_sp.get(f"Timer{t_idx} N_Start", setpoints.get(f"Timer{t_idx} N_Start", "17:05"))
            n_stop  = new_sp.get(f"Timer{t_idx} N_Stop", setpoints.get(f"Timer{t_idx} N_Stop", "09:55"))
            try:
                t_d_start = datetime.datetime.strptime(str(d_start), "%H:%M").time()
                t_d_stop  = datetime.datetime.strptime(str(d_stop),  "%H:%M").time()
                t_n_start = datetime.datetime.strptime(str(n_start), "%H:%M").time()
                t_n_stop  = datetime.datetime.strptime(str(n_stop),  "%H:%M").time()
                if (t_d_start >= t_d_stop or
                    t_n_start < t_d_stop or
                    t_d_start < t_n_stop or
                    t_n_start == t_n_stop):
                    print(f"⚠️ Rejecting setpoint update due to Timer{t_idx} Day/Night conflict")
                    return
            except Exception:
                return

        ts_changed = False
        for k in key_map.values():
            if k in new_sp and str(new_sp.get(k)) != str(setpoints.get(k)):
                ts_changed = True
                break

        setpoints.update(new_sp)
        save_setpoints()
        
        if ts_changed:
            init_mqtt_client()
    except Exception:
        pass

client_id = f"Inhydro_Mon_{DEVICE_NAME.strip()}_{uuid.uuid4().hex[:6]}"
control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
control_client.on_message = on_control_message

try:
    control_client.connect(CONTROL_BROKER, CONTROL_PORT, 60)
    control_client.subscribe(f"inhydro/{DEVICE_NAME}/monitor/setpoints/update")
    control_client.subscribe(f"inhydro/{DEVICE_NAME}/monitor/setpoints/request_sync")
    control_client.publish(f"inhydro/{DEVICE_NAME}/monitor/setpoints/current", json.dumps(setpoints), retain=True)
    control_client.loop_start()
except Exception:
    pass


# --- Modbus RTU Relay Setup ---
RELAY_PORT_FIXED = "/dev/serial/by-path/usb-0:1.11-port0"
RELAY_BAUD = 9600
POSSIBLE_RELAY_IDS = [255, 1, 2, 0, 3]
working_relay_id = None
_relay_state = {}

def set_relay(channel, state):
    global working_relay_id
    if not RELAY_PORT_FIXED:
        return False
    
    ids_to_try = [working_relay_id] if working_relay_id is not None else POSSIBLE_RELAY_IDS
    for r_id in ids_to_try:
        if r_id is None:
            continue
        try:
            instrument = minimalmodbus.Instrument(RELAY_PORT_FIXED, r_id)
            instrument.serial.baudrate = RELAY_BAUD
            instrument.serial.timeout = 0.5
            instrument.serial.stopbits = 1
            instrument.serial.parity = serial.PARITY_NONE
            instrument.mode = minimalmodbus.MODE_RTU
            instrument.write_bit(channel - 1, 1 if state else 0, functioncode=5)
            working_relay_id = r_id
            return True
        except Exception:
            pass
        finally:
            if 'instrument' in locals() and hasattr(instrument, 'serial') and instrument.serial:
                try:
                    instrument.serial.close()
                except Exception:
                    pass
    return False

def relay_on(ch):
    _relay_state[ch] = True
    set_relay(ch, True)

def relay_off(ch):
    _relay_state[ch] = False
    set_relay(ch, False)

def relay_is_on(ch):
    return _relay_state.get(ch, False)


# --- Cyclic Timers & Control Logic ---
state = {
    1: {"ec_active": False, "ph_active": False, "ac_active": False,
        "humi_active": False, "last_ec": 0.0, "last_ph": 0.0}
}

ROOM_CHANNELS = {
    1: {"ec1": 1, "ec2": 2, "ph": 3, "ac": 4, "humi": 5}
}

timer_state = {
    1: [{"state": "OFF", "last": 0.0} for _ in range(10)]
}

TIMER_CHANNELS = {
    1: [6, 7, 8, 4, 9, 10, 11, 12, 13, 14]
}

TIMER_KEYS = [
    ("Timer1 Start", "Timer1 Stop", "Timer1 ON Min", "Timer1 OFF Min"),
    ("Timer2 Start", "Timer2 Stop", "Timer2 ON Min", "Timer2 OFF Min"),
    ("Timer3 Start", "Timer3 Stop", "Timer3 ON Min", "Timer3 OFF Min"),
    ("Timer4 D_Start", "Timer4 D_Stop", "Timer4 D_ON Min", "Timer4 D_OFF Min"),
    ("Timer5 Start", "Timer5 Stop", "Timer5 ON Min", "Timer5 OFF Min"),
    ("Timer6 Start", "Timer6 Stop", "Timer6 ON Min", "Timer6 OFF Min"),
    ("Timer7 Start", "Timer7 Stop", "Timer7 ON Min", "Timer7 OFF Min"),
    ("Timer8 D_Start", "Timer8 D_Stop", "Timer8 D_ON Min", "Timer8 D_OFF Min"),
    ("Timer9 D_Start", "Timer9 D_Stop", "Timer9 D_ON Min", "Timer9 D_OFF Min"),
    ("Timer10 D_Start", "Timer10 D_Stop", "Timer10 D_ON Min", "Timer10 D_OFF Min")
]

def is_within_window(start_str, stop_str):
    now = datetime.datetime.now().time()
    try:
        st = datetime.datetime.strptime(str(start_str), "%H:%M").time()
        et = datetime.datetime.strptime(str(stop_str),  "%H:%M").time()
    except Exception:
        return False
    return (st <= now <= et) if st <= et else (now >= st or now <= et)

def run_timers(room):
    now = time.time()
    sp  = setpoints
    for i, (sk, ek, onk, offk) in enumerate(TIMER_KEYS):
        ch = TIMER_CHANNELS[room][i]
        ts = timer_state[room][i]
        is_ac_timer = (ch == ROOM_CHANNELS[room]["ac"])
        is_dn_timer = (i in [3, 7, 8, 9]) # Timer 4, 8, 9, 10
        
        if is_dn_timer:
            in_day = is_within_window(sp.get(f"Timer{i+1} D_Start", "10:00"), sp.get(f"Timer{i+1} D_Stop", "17:00"))
            in_night = is_within_window(sp.get(f"Timer{i+1} N_Start", "17:05"), sp.get(f"Timer{i+1} N_Stop", "09:55"))
            in_window = in_day or in_night
            
            if in_night and not in_day:
                run_sec = float(sp.get(f"Timer{i+1} N_ON Min", 15)) * 60
                stop_sec = float(sp.get(f"Timer{i+1} N_OFF Min", 30)) * 60
            else:
                run_sec = float(sp.get(f"Timer{i+1} D_ON Min", 15)) * 60
                stop_sec = float(sp.get(f"Timer{i+1} D_OFF Min", 30)) * 60
        else:
            run_sec = float(sp.get(onk, 15)) * 60
            stop_sec = float(sp.get(offk, 30)) * 60
            in_window = is_within_window(sp.get(sk, "10:00"), sp.get(ek, "17:00"))
            
        if in_window:
            if ts["state"] == "OFF":
                if now - ts["last"] >= stop_sec or ts["last"] == 0:
                    ts["state"] = "ON"
                    ts["last"] = now
                    print(f"Room{room} Timer {i+1} ON {datetime.datetime.now().strftime('%H:%M')}")
            elif ts["state"] == "ON":
                if now - ts["last"] >= run_sec:
                    ts["state"] = "OFF"
                    ts["last"] = now
                    print(f"Room{room} Timer {i+1} OFF — cycle complete")
                    
            if ts["state"] == "ON" and not is_ac_timer:
                if not relay_is_on(ch):
                    relay_on(ch)
            elif ts["state"] == "OFF" and not is_ac_timer:
                if relay_is_on(ch):
                    relay_off(ch)
        else:
            if ts["state"] == "ON" or (not is_ac_timer and relay_is_on(ch)):
                ts["state"] = "OFF"
                ts["last"] = 0.0
                if not is_ac_timer:
                    relay_off(ch)

def control_room(room, data):
    st  = state[room]
    sp  = setpoints
    ch  = ROOM_CHANNELS[room]
    now = time.time()
    warnings = []
    
    soil = data.get("soil")
    room_env = data.get("room")
    
    if soil:
        raw_ec = soil.get("ec")
        ec = (raw_ec * 0.85) / 1000 if raw_ec is not None else 0.0
        ph = soil.get("ph")
        
        # EC control
        if not st["ec_active"] and ec < sp.get("EC MIN", 1.2):
            st["ec_active"] = True
            relay_on(ch["ec1"])
            relay_on(ch["ec2"])
            st["last_ec"] = now
            warnings.append("⚠ EC LOW — DOSING")
            
        if st["ec_active"]:
            if ec >= sp.get("EC MAX", 1.8):
                relay_off(ch["ec1"])
                relay_off(ch["ec2"])
                st["ec_active"] = False
            elif now - st["last_ec"] >= 10:
                relay_on(ch["ec1"])
                relay_on(ch["ec2"])
                st["last_ec"] = now
                
        # pH control
        if not st["ph_active"] and ph > sp.get("PH HIGH", 6.5):
            st["ph_active"] = True
            relay_on(ch["ph"])
            st["last_ph"] = now
            warnings.append("⚠ pH HIGH — CORRECTING")
            
        if st["ph_active"]:
            if ph <= sp.get("PH LOW", 5.8):
                relay_off(ch["ph"])
                st["ph_active"] = False
            elif now - st["last_ph"] >= 10:
                relay_on(ch["ph"])
                st["last_ph"] = now
    else:
        if st["ec_active"] or st["ph_active"] or relay_is_on(ch["ec1"]) or relay_is_on(ch["ph"]):
            relay_off(ch["ec1"])
            relay_off(ch["ec2"])
            relay_off(ch["ph"])
            st["ec_active"] = False
            st["ph_active"] = False
        warnings.append(" WATER SENSOR ERROR")

    if room_env:
        rt = room_env.get("room_temp")
        rh = room_env.get("room_humi")
        
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
                st["ac_active"] = True
                relay_on(ch["ac"])
                warnings.append(f"⚠ TEMP HIGH ({mode_str} AC ON)")
                print(f"Room{room} AC ON — {rt}°C >= {t_max}°C ({mode_str})")
                
            if st["ac_active"] and rt <= t_min:
                st["ac_active"] = False
                relay_off(ch["ac"])
                print(f"Room{room} AC OFF — {rt}°C <= {t_min}°C ({mode_str})")
        else:
            if st["ac_active"] or relay_is_on(ch["ac"]):
                st["ac_active"] = False
                relay_off(ch["ac"])
                print(f"Room{room} AC OFF — Cyclic Timer window OFF")
                
        # Humidity control
        if not st["humi_active"] and rh >= sp.get("H Max", 80.0):
            st["humi_active"] = True
            relay_on(ch["humi"])
            warnings.append("⚠ HUMI HIGH (HUM ON)")
            print(f"Room{room} Humidifier ON — {rh}% >= {sp.get('H Max', 80.0)}%")
            
        if st["humi_active"] and rh <= sp.get("H Min", 30.0):
            st["humi_active"] = False
            relay_off(ch["humi"])
            print(f"Room{room} Humidifier OFF — {rh}% <= {sp.get('H Min', 30.0)}%")
    else:
        if st["ac_active"] or st["humi_active"] or relay_is_on(ch["ac"]) or relay_is_on(ch["humi"]):
            relay_off(ch["ac"])
            relay_off(ch["humi"])
            st["ac_active"] = False
            st["humi_active"] = False
        warnings.append(" ROOM SENSOR ERROR")
        
    return warnings



# --- Sensor Setup ---
PORTS = {
    "SOIL": "/dev/serial/by-path/usb-0:1.1-port0",
    "MD02": "/dev/serial/by-path/usb-0:1.2-port0",
    "ORP": "/dev/serial/by-path/usb-0:1.3-port0", 
    "CO2": "/dev/serial/by-path/usb-0:1.4-port0",
    "VPD": "/dev/serial/by-path/usb-0:1.5-port0", 
    "DLI": "/dev/serial/by-path/usb-0:1.6-port0",
    "ANEMO": "/dev/serial/by-path/usb-0:1.7-port0", 
    "DO": "/dev/serial/by-path/usb-0:1.8-port0",
    "PPFD": "/dev/serial/by-path/usb-0:1.9-port0", 
    "NPK": "/dev/serial/by-path/usb-0:1.10-port0",
}

def _open_sensor(port, baudrate=9600):
    try:
        inst = minimalmodbus.Instrument(port, 1)
        inst.serial.baudrate = baudrate
        inst.serial.bytesize = 8
        inst.serial.parity = serial.PARITY_NONE
        inst.serial.stopbits = 1
        inst.serial.timeout = 0.5
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True
        return inst
    except Exception:
        return None

sensors = {
    "SOIL": _open_sensor(PORTS["SOIL"], 9600),
    "MD02": _open_sensor(PORTS["MD02"], 9600),
    "ORP": _open_sensor(PORTS["ORP"], 4800),
    "CO2": _open_sensor(PORTS["CO2"], 9600),
    "VPD": _open_sensor(PORTS["VPD"], 9600),
    "DLI": _open_sensor(PORTS["DLI"], 9600),
    "ANEMO": _open_sensor(PORTS["ANEMO"], 9600),
    "DO": _open_sensor(PORTS["DO"], 9600),
    "PPFD": _open_sensor(PORTS["PPFD"], 9600),
    "NPK": _open_sensor(PORTS["NPK"], 9600),
}

latest_data = {
    "Water Temp": "N/A", "Water Moisture": "N/A", "Water EC": "N/A", "Water pH": "N/A",
    "Room Temp": "N/A", "Room Humidity": "N/A", "ORP": "N/A", "CO2": "N/A",
    "VPD": "N/A", "DLI": "N/A", "Wind Speed": "N/A", "Wind Direction": "N/A",
    "DO": "N/A", "PPFD": "N/A", "Nitrogen": "N/A", "Phosphorus": "N/A", "Potassium": "N/A"
}
latest_raw = {}

def poll_sensors():
    global latest_data, latest_raw
    while True:
        d = {}
        r = {}
        
        # Helper to safely parse and store
        def try_read(sensor_key, callback, fail_keys):
            inst = sensors[sensor_key]
            if inst:
                try:
                    callback(inst, d, r)
                except Exception: 
                    for k in fail_keys:
                        d[k] = "N/A"
            else:
                for k in fail_keys:
                    d[k] = "N/A"

        def _soil(i, dt, rw):
            moist = i.read_register(0x0012, 1)
            temp = i.read_register(0x0013, 1, signed=True)
            ec = i.read_register(0x0015, 0)
            ph = i.read_register(0x0006, 2)
            
            dt["Water Temp"] = f"{temp} °C"
            dt["Water Moisture"] = f"{moist} %"
            dt["Water EC"] = f"{ec} uS/cm"
            dt["Water pH"] = f"{ph}"
            
            rw["water_temp"] = temp
            rw["moisture"] = moist
            rw["ec"] = ec
            rw["ph"] = ph
            
        try_read("SOIL", _soil, ["Water Temp", "Water Moisture", "Water EC", "Water pH"])

        def _md02(i, dt, rw):
            try:
                rt = i.read_register(1, 1, signed=True)
                rh = i.read_register(2, 1)
            except Exception:
                rt = i.read_register(1, 1, signed=True, functioncode=4)
                rh = i.read_register(2, 1, functioncode=4)
                
            dt["Room Temp"] = f"{rt} °C"
            dt["Room Humidity"] = f"{rh} %"
            
            rw["room_temp"] = rt
            rw["room_humi"] = rh
            
        try_read("MD02", _md02, ["Room Temp", "Room Humidity"])

        def _orp(i, dt, rw):
            try:
                orp = i.read_register(0x0000, 1, signed=True)
            except Exception:
                orp = i.read_register(0x0000, 1, signed=True, functioncode=4)
                
            dt["ORP"] = f"{orp} mV"
            rw["orp"] = orp
            
        try_read("ORP", _orp, ["ORP"])

        def _co2(i, dt, rw):
            try:
                co2 = i.read_register(0x0000, 0)
            except Exception:
                co2 = i.read_register(0x0000, 0, functioncode=4)
                
            dt["CO2"] = f"{co2} ppm"
            rw["co2"] = co2
            
        try_read("CO2", _co2, ["CO2"])

        def _vpd(i, dt, rw):
            vpd = i.read_register(0x0000, 1)
            dt["VPD"] = f"{vpd} kPa"
            rw["vpd"] = vpd
            
        try_read("VPD", _vpd, ["VPD"])

        def _dli(i, dt, rw):
            dli = i.read_register(0x0000, 1)
            dt["DLI"] = f"{dli} mol/m2/d"
            rw["dli"] = dli
            
        try_read("DLI", _dli, ["DLI"])

        def _anemo(i, dt, rw):
            ws = i.read_register(0x0000, 1)
            wd = i.read_register(0x0001, 0)
            
            dt["Wind Speed"] = f"{ws} m/s"
            dt["Wind Direction"] = f"{wd}°"
            
            rw["wind_speed"] = ws
            rw["wind_dir"] = wd
            
        try_read("ANEMO", _anemo, ["Wind Speed", "Wind Direction"])

        def _do(i, dt, rw):
            do_val = i.read_register(0x0000, 1)
            dt["DO"] = f"{do_val} mg/L"
            rw["do"] = do_val
            
        try_read("DO", _do, ["DO"])

        def _ppfd(i, dt, rw):
            ppfd = i.read_register(0x0000, 0)
            dt["PPFD"] = f"{ppfd} umol/m2/s"
            rw["ppfd"] = ppfd
            
        try_read("PPFD", _ppfd, ["PPFD"])

        def _npk(i, dt, rw):
            n = i.read_register(0x001E, 0)
            p = i.read_register(0x001F, 0)
            k = i.read_register(0x0020, 0)
            
            dt["Nitrogen"] = f"{n} mg/kg"
            dt["Phosphorus"] = f"{p} mg/kg"
            dt["Potassium"] = f"{k} mg/kg"
            
            rw["n"] = n
            rw["p"] = p
            rw["k"] = k
            
        try_read("NPK", _npk, ["Nitrogen", "Phosphorus", "Potassium"])

        latest_data = d
        latest_raw = r
        time.sleep(1)

threading.Thread(target=poll_sensors, daemon=True).start()

# --- Bluetooth / WiFi Connectivity Setup ---

def set_wifi(ssid, password):
    try:
        subprocess.run(['sudo', 'nmcli', 'connection', 'delete', ssid], capture_output=True)
        result = subprocess.run(
            ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid, 'password', password],
            capture_output=True, text=True)
        if "key-mgmt" in result.stderr:
            result = subprocess.run(
                ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid,
                 'password', password, 'wifi-sec.key-mgmt', 'wpa-psk'],
                capture_output=True, text=True)
        return (f"SUCCESS: Connected to {ssid}!" if result.returncode == 0
                else f"FAILED: {result.stderr.strip()}")
    except Exception as e:
        return f"ERROR: {e}"

def scan_wifi():
    try:
        result = subprocess.run(['sudo', 'nmcli', '-t', '-f', 'SSID', 'dev', 'wifi'],
                                capture_output=True, text=True)
        if result.returncode != 0:
            return f"SCAN FAILED: {result.stderr.strip()}"
        names = sorted(set(n.strip() for n in result.stdout.split('\n') if n.strip()))
        if not names:
            return "No networks found"
        return ("\r\n--- WIFI NETWORKS ---\r\n" +
                "\r\n".join(f"{i}. {n}" for i, n in enumerate(names, 1)) +
                "\r\n---------------------")
    except Exception as e:
        return f"SCAN ERROR: {e}"

def auto_trust_devices():
    try:
        bt = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        for cmd in ["power on\n", "agent NoInputNoOutput\n", "default-agent\n",
                    "discoverable on\n", "pairable on\n"]:
            bt.stdin.write(cmd)
        bt.stdin.flush()
    except Exception as e:
        print("BT agent error:", e)
    while True:
        try:
            out = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True)
            for line in out.split('\n'):
                if line.startswith('Device '):
                    os.system(f"sudo bluetoothctl trust {line.split()[1]} >/dev/null 2>&1")
        except Exception:
            pass
        time.sleep(5)

def start_bluetooth_server():
    try:
        os.system("sudo sdptool add SP >/dev/null 2>&1")
        time.sleep(1)
        srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        srv.bind((socket.BDADDR_ANY, 1))
        srv.listen(1)
        print("Bluetooth RFCOMM server listening")
        while True:
            cli = None
            try:
                cli, info = srv.accept()
                print(f"BT connected: {info}")
                cli.send(b"\r\nInhydro Sensor Monitor\r\nCmds: WIFI:WiFi_Name:PASS | SCAN: Scanning nearby WiFi Networks\r\n")
                while True:
                    data = cli.recv(1024)
                    if not data:
                        break
                    cmd = data.decode('utf-8').strip()
                    if cmd.startswith("WIFI:"):
                        parts = cmd.split(":")
                        if len(parts) >= 3:
                            ssid = parts[1]
                            password = ':'.join(parts[2:])
                            cli.send(f"\r\n{set_wifi(ssid, password)}\r\n".encode())
                        else:
                            cli.send(b"\r\nERROR: WIFI:SSID:PASS\r\n")
                    elif cmd.upper() == "SCAN":
                        cli.send(("\r\n" + scan_wifi() + "\r\n").encode())
                    else:
                        cli.send(f"\r\nUnknown: {cmd}\r\n".encode())
            except Exception as e:
                print(f"BT error: {e}")
            finally:
                if cli:
                    try:
                        cli.close()
                    except Exception:
                        pass
    except Exception as e:
        print(f"BT server failed: {e}")

threading.Thread(target=auto_trust_devices, daemon=True).start()
threading.Thread(target=start_bluetooth_server, daemon=True).start()


# --- Publishing and Logging Logic ---
last_cloud_publish_time = 0
last_local_save_time = 0

def publish_telemetry():
    global last_cloud_publish_time
    current_time = time.time()
    
    if current_time - last_cloud_publish_time < 45:
        return

    try:
        if mqtt_client and mqtt_client.is_connected() and latest_raw:
            ec_val = 0
            if "ec" in latest_raw:
                ec_val = (latest_raw["ec"] * 0.85) / 1000

            fields = {
                "field1": str(latest_raw.get("water_temp", "")),
                "field2": str(latest_raw.get("moisture", "")),
                "field3": str(ec_val if ec_val else ""),
                "field4": str(latest_raw.get("ph", "")),
                "field5": str(latest_raw.get("room_temp", "")),
                "field6": str(latest_raw.get("room_humi", "")),
                "field7": str(latest_raw.get("co2", "")),
                "field8": str(latest_raw.get("orp", ""))
            }
            
            payload = "&".join(f"{k}={v}" for k, v in fields.items() if v)
            mqtt_client.publish(MQTT_TOPIC, payload)
    except Exception:
        pass
        
    last_cloud_publish_time = current_time

def publish_live_telemetry():
    try:
        if control_client and control_client.is_connected() and latest_raw:
            payload = {
                "telemetry": latest_raw,
                "device": DEVICE_NAME
            }
            control_client.publish(f"inhydro/{DEVICE_NAME}/monitor/telemetry/live", json.dumps(payload))
    except Exception:
        pass

def save_local_telemetry():
    global last_local_save_time
    current_time = time.time()
    
    if current_time - last_local_save_time < 45:
        return
    
    if not latest_raw:
        return
        
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "timestamp": timestamp,
        "data": latest_raw
    }

    def write_thread():
        try:
            buffer = []
            if os.path.exists(LOCAL_LOG_FILE):
                try:
                    with open(LOCAL_LOG_FILE, "r") as f:
                        buffer = json.load(f)
                except Exception:
                    buffer = []
                    
            if not isinstance(buffer, list):
                buffer = []
            
            buffer.append(record)
            if len(buffer) > 20000:
                buffer = buffer[-20000:]
            
            lines = ["  " + json.dumps(item) for item in buffer]
            
            with open(LOCAL_LOG_FILE, "w") as f:
                f.write("[\n" + ",\n".join(lines) + "\n]")
        except Exception:
            pass

    threading.Thread(target=write_thread, daemon=True).start()
    last_local_save_time = current_time

def restart_program():
    for inst in sensors.values():
        if inst:
            try:
                inst.serial.close()
            except Exception:
                pass
                
    for ch in range(1, 17):
        try:
            set_relay(ch, False)
        except Exception:
            pass
            
    os.execl(sys.executable, sys.executable, *sys.argv)

def quit_app():
    for inst in sensors.values():
        if inst:
            try:
                inst.serial.close()
            except Exception:
                pass
                
    for ch in range(1, 17):
        try:
            set_relay(ch, False)
        except Exception:
            pass
    try:
        root.destroy()
    except Exception:
        pass
    sys.exit(0)

logo_img = None

def get_logo_image():
    global logo_img
    if logo_img is not None:
        return logo_img
    LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
    try:
        logo_raw = Image.open(LOGO_PATH).resize((100, 63), Image.LANCZOS)
        logo_img = ImageTk.PhotoImage(logo_raw)
        return logo_img
    except Exception as e:
        print("Logo loading error:", e)
        return None

def open_setpoints_window():
    win = tk.Toplevel()
    win.title("System Configuration")
    win.geometry("1280x720")
    win.configure(bg="white")
    win.resizable(False, False)
    
    # Center the Toplevel window
    win.update_idletasks()
    x = (win.winfo_screenwidth() - 1280) // 2
    y = (win.winfo_screenheight() - 720) // 2
    win.geometry(f"+{x}+{y}")
    
    color = "#1565c0"
    labels_s = {}
    
    # Header Section (Static at the top)
    header = tk.Frame(win, bg="white")
    header.pack(fill="x", pady=(5, 2), padx=20)
    
    # Title
    tk.Label(header, text="SYSTEM — SETPOINTS & TIMERS CONFIGURATION",
             font=("Arial", 14, "bold"), fg=color, bg="white").pack(side="left", pady=10)
             
    # Logo
    logo = get_logo_image()
    if logo:
        lbl_logo = tk.Label(header, image=logo, bg="white")
        lbl_logo.image = logo
        lbl_logo.pack(side="right", padx=10)
             
    # Canvas Container for Scrollability
    canvas_container = tk.Frame(win, bg="white")
    canvas_container.pack(fill="both", expand=True, padx=10, pady=5)
    
    canvas = tk.Canvas(canvas_container, bg="white", highlightthickness=0)
    scrollbar = tk.Scrollbar(canvas_container, orient="vertical", command=canvas.yview)
    
    scrollable_frame = tk.Frame(canvas, bg="white")
    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    def on_canvas_configure(event):
        canvas.itemconfig(canvas_window, width=event.width)
    canvas.bind("<Configure>", on_canvas_configure)
    
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    
    # Bind MouseWheel for scrolling (including Linux support)
    def _on_mousewheel(event):
        if canvas.winfo_exists():
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    win.bind_all("<MouseWheel>", _on_mousewheel)
    win.bind_all("<Button-4>", _on_mousewheel)
    win.bind_all("<Button-5>", _on_mousewheel)
    win.bind("<Destroy>", lambda e: (
        win.unbind_all("<MouseWheel>"),
        win.unbind_all("<Button-4>"),
        win.unbind_all("<Button-5>")
    ))
    
    # Top container to hold Left and Right Panes for parallel layout
    top_container = tk.Frame(scrollable_frame, bg="white")
    top_container.pack(fill="x", expand=True)

    # Left and Right Panes inside top_container
    left_pane = tk.Frame(top_container, bg="white")
    left_pane.pack(side="left", fill="both", expand=True, padx=15)
    
    right_pane = tk.Frame(top_container, bg="white")
    right_pane.pack(side="right", fill="both", expand=True, padx=15)
    
    # Helper function to create an inline editable parameter cell
    def make_cell(parent, key, label_text=None, width_lbl=10):
        if key not in setpoints: return
        lbl_txt = label_text if label_text else key
        
        cell = tk.Frame(parent, bg="white")
        
        tk.Label(cell, text=lbl_txt, font=("Arial", 9, "bold"), fg="#444",
                 bg="white", anchor="w", width=width_lbl).pack(side="left", padx=1)
        
        is_name = key.endswith("Name")
        val_w = 12 if is_name else 6
        val_fg = "#333" if is_name else "#e65100"
        
        val_lbl = tk.Label(cell, text=str(setpoints[key]),
                           font=("Arial", 9, "bold"), fg=val_fg, bg="white", width=val_w, anchor="center")
        val_lbl.pack(side="left", padx=2)
        
        btn = tk.Button(cell, text="EDIT", font=("Arial", 8, "bold"), bg="#f5f5f5", fg="#333",
                        activebackground=color, activeforeground="white", bd=1, relief="groove",
                        command=lambda k=key: open_keypad(k))
        btn.pack(side="left", padx=1)
        
        labels_s[key] = val_lbl
        return cell

    # Helper function to create Day/Night Timer Cards (for Timers 4, 8, 9, 10)
    def make_dn_timer_card(parent, timer_idx, title_label):
        t_prefix = f"Timer{timer_idx}"
        card = tk.LabelFrame(parent, text=f" {title_label} (DAY/NIGHT CYCLIC) ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
        
        # Name editing row
        f_name = tk.Frame(card, bg="white")
        f_name.pack(fill="x", pady=2, padx=10)
        make_cell(f_name, f"{t_prefix} Name", "Name:", width_lbl=12).pack(side="left", padx=5)
        
        grid = tk.Frame(card, bg="white")
        grid.pack(pady=4, padx=10)
        
        tk.Label(grid, text="Setting", font=("Arial", 9, "bold"), fg="#555", bg="white", width=12, anchor="w").grid(row=0, column=0, padx=5)
        tk.Label(grid, text="Day Settings", font=("Arial", 9, "bold"), fg=color, bg="white", width=16, anchor="center").grid(row=0, column=1, padx=5)
        tk.Label(grid, text="Night Settings", font=("Arial", 9, "bold"), fg=color, bg="white", width=16, anchor="center").grid(row=0, column=2, padx=5)
        
        rows = [
            ("Start Time", f"{t_prefix} D_Start", f"{t_prefix} N_Start"),
            ("Stop Time", f"{t_prefix} D_Stop", f"{t_prefix} N_Stop"),
            ("ON Minutes", f"{t_prefix} D_ON Min", f"{t_prefix} N_ON Min"),
            ("OFF Minutes", f"{t_prefix} D_OFF Min", f"{t_prefix} N_OFF Min")
        ]
        
        for r_idx, (r_lbl, d_key, n_key) in enumerate(rows, 1):
            tk.Label(grid, text=r_lbl, font=("Arial", 9, "bold"), fg="#555", bg="white", width=12, anchor="w").grid(row=r_idx, column=0, padx=5, pady=2)
            
            c_day = tk.Frame(grid, bg="white")
            c_day.grid(row=r_idx, column=1, padx=5, pady=2)
            val_lbl_d = tk.Label(c_day, text=str(setpoints[d_key]), font=("Arial", 9, "bold"), fg="#e65100", bg="white", width=8, anchor="center")
            val_lbl_d.pack(side="left")
            tk.Button(c_day, text="EDIT", font=("Arial", 8, "bold"), bg="#f5f5f5", fg="#333", bd=1, relief="groove",
                      command=lambda k=d_key: open_keypad(k)).pack(side="right", padx=2)
            labels_s[d_key] = val_lbl_d
            
            c_night = tk.Frame(grid, bg="white")
            c_night.grid(row=r_idx, column=2, padx=5, pady=2)
            val_lbl_n = tk.Label(c_night, text=str(setpoints[n_key]), font=("Arial", 9, "bold"), fg="#e65100", bg="white", width=8, anchor="center")
            val_lbl_n.pack(side="left")
            tk.Button(c_night, text="EDIT", font=("Arial", 8, "bold"), bg="#f5f5f5", fg="#333", bd=1, relief="groove",
                      command=lambda k=n_key: open_keypad(k)).pack(side="right", padx=2)
            labels_s[n_key] = val_lbl_n
            
        return card

    # Nutrients & pH Card (Left Pane)
    card_dosing = tk.LabelFrame(left_pane, text=" NUTRIENTS & PH ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
    card_dosing.pack(fill="x", pady=5, padx=5)
    
    grid_dosing = tk.Frame(card_dosing, bg="white")
    grid_dosing.pack(pady=4, padx=5)
    
    make_cell(grid_dosing, "EC MIN", "EC Min:").grid(row=0, column=0, padx=10, pady=4)
    make_cell(grid_dosing, "EC MAX", "EC Max:").grid(row=0, column=1, padx=10, pady=4)
    make_cell(grid_dosing, "PH LOW", "pH Low:").grid(row=1, column=0, padx=10, pady=4)
    make_cell(grid_dosing, "PH HIGH", "pH High:").grid(row=1, column=1, padx=10, pady=4)

    # Climate Control Card (Left Pane)
    card_climate = tk.LabelFrame(left_pane, text=" CLIMATE CONTROL ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
    card_climate.pack(fill="x", pady=5, padx=5)
    
    grid_climate = tk.Frame(card_climate, bg="white")
    grid_climate.pack(pady=4, padx=5)
    
    make_cell(grid_climate, "D T Max", "Day T Max:").grid(row=0, column=0, padx=10, pady=4)
    make_cell(grid_climate, "DT Min", "Day T Min:").grid(row=0, column=1, padx=10, pady=4)
    make_cell(grid_climate, "N T Max", "Night T Max:").grid(row=1, column=0, padx=10, pady=4)
    make_cell(grid_climate, "N T Min", "Night T Min:").grid(row=1, column=1, padx=10, pady=4)
    make_cell(grid_climate, "H Max", "Humid Max:").grid(row=2, column=0, padx=10, pady=4)
    make_cell(grid_climate, "H Min", "Humid Min:").grid(row=2, column=1, padx=10, pady=4)

    # Day/Night Timer 4 (AC) (Left Pane)
    make_dn_timer_card(left_pane, 4, "TIMER 4 / AC").pack(fill="x", pady=8, padx=5)

    # Timers 1-3 Card (Right Pane)
    card_timers = tk.LabelFrame(right_pane, text=" CYCLIC TIMERS 1-3 ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
    card_timers.pack(fill="x", pady=5, padx=5)
    
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
    
    header_frame = tk.Frame(card_timers, bg="#f5f5f5")
    header_frame.pack(fill="x", pady=1, padx=2)
    tk.Label(header_frame, text="Setting", font=("Arial", 9, "bold"), fg="#555", bg="#f5f5f5", width=9, anchor="w").pack(side="left", padx=2)
    for col in cols:
        tk.Label(header_frame, text=col["name"], font=("Arial", 9, "bold"), fg=color, bg="#f5f5f5", width=12, anchor="center").pack(side="left", expand=True)
        
    row_keys = [("Name", "Name:"), ("Start", "Start:"), ("Stop", "Stop:"), ("ON Min", "ON:"), ("OFF Min", "OFF:")]
    
    for r_key, r_lbl in row_keys:
        r_frame = tk.Frame(card_timers, bg="white")
        r_frame.pack(fill="x", pady=1, padx=2)
        tk.Label(r_frame, text=r_lbl, font=("Arial", 9, "bold"), fg="#555", bg="white", width=9, anchor="w").pack(side="left", padx=2)
        
        for col in cols:
            col_frame = tk.Frame(r_frame, bg="white")
            col_frame.pack(side="left", expand=True, fill="x")
            full_key = col["keys"][r_key]
            if full_key in setpoints:
                val_lbl = tk.Label(col_frame, text=str(setpoints[full_key]),
                                   font=("Arial", 9, "bold"), fg="#e65100" if r_key != "Name" else "#333", bg="white", width=8, anchor="center")
                val_lbl.pack(side="left", expand=True)
                
                btn = tk.Button(col_frame, text="EDIT", font=("Arial", 8, "bold"), bg="#f5f5f5", fg="#333",
                                activebackground=color, activeforeground="white", bd=1, relief="groove",
                                command=lambda k=full_key: open_keypad(k))
                btn.pack(side="right", padx=1)
                labels_s[full_key] = val_lbl

    # Cyclic Timers 5-7 Card (Right Pane)
    card_timers_ext = tk.LabelFrame(right_pane, text=" CYCLIC TIMERS 5-7 ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
    card_timers_ext.pack(fill="x", pady=5, padx=5)
    
    cols_ext = [
        {"name": "Timer 5", "keys": {
            "Name": "Timer5 Name", "Start": "Timer5 Start", "Stop": "Timer5 Stop", "ON Min": "Timer5 ON Min", "OFF Min": "Timer5 OFF Min"
        }},
        {"name": "Timer 6", "keys": {
            "Name": "Timer6 Name", "Start": "Timer6 Start", "Stop": "Timer6 Stop", "ON Min": "Timer6 ON Min", "OFF Min": "Timer6 OFF Min"
        }},
        {"name": "Timer 7", "keys": {
            "Name": "Timer7 Name", "Start": "Timer7 Start", "Stop": "Timer7 Stop", "ON Min": "Timer7 ON Min", "OFF Min": "Timer7 OFF Min"
        }},
    ]
    
    header_frame_ext = tk.Frame(card_timers_ext, bg="#f5f5f5")
    header_frame_ext.pack(fill="x", pady=1, padx=2)
    tk.Label(header_frame_ext, text="Setting", font=("Arial", 9, "bold"), fg="#555", bg="#f5f5f5", width=9, anchor="w").pack(side="left", padx=2)
    for col in cols_ext:
        tk.Label(header_frame_ext, text=col["name"], font=("Arial", 9, "bold"), fg=color, bg="#f5f5f5", width=12, anchor="center").pack(side="left", expand=True)
        
    for r_key, r_lbl in row_keys:
        r_frame = tk.Frame(card_timers_ext, bg="white")
        r_frame.pack(fill="x", pady=1, padx=2)
        tk.Label(r_frame, text=r_lbl, font=("Arial", 9, "bold"), fg="#555", bg="white", width=9, anchor="w").pack(side="left", padx=2)
        
        for col in cols_ext:
            col_frame = tk.Frame(r_frame, bg="white")
            col_frame.pack(side="left", expand=True, fill="x")
            full_key = col["keys"][r_key]
            if full_key in setpoints:
                val_lbl = tk.Label(col_frame, text=str(setpoints[full_key]),
                                   font=("Arial", 9, "bold"), fg="#e65100" if r_key != "Name" else "#333", bg="white", width=8, anchor="center")
                val_lbl.pack(side="left", expand=True)
                
                btn = tk.Button(col_frame, text="EDIT", font=("Arial", 8, "bold"), bg="#f5f5f5", fg="#333",
                                activebackground=color, activeforeground="white", bd=1, relief="groove",
                                command=lambda k=full_key: open_keypad(k))
                btn.pack(side="right", padx=1)
                labels_s[full_key] = val_lbl

    # Bottom container for Day/Night cyclic timers 8-10 side-by-side
    bottom_container = tk.Frame(scrollable_frame, bg="white")
    bottom_container.pack(fill="x", expand=True, pady=10)

    card_dn_all = tk.LabelFrame(bottom_container, text=" DAY/NIGHT CYCLIC TIMERS 8 - 10 ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
    card_dn_all.pack(fill="x", pady=5, padx=20)

    grid_dn = tk.Frame(card_dn_all, bg="white")
    grid_dn.pack(fill="x", pady=5, padx=10)


    # ── Row 0: Timer Name cells ──────────────────────────────────────────────
    # Column 0 is the common Setting label column — leave it blank in row 0
    tk.Label(grid_dn, text="", bg="white", width=14).grid(row=0, column=0, padx=4, pady=4)

    for idx, num in enumerate([8, 9, 10]):
        col_day = 1 + idx * 2          # Day column for this timer
        col_night = col_day + 1        # Night column
        name_key = f"Timer{num} Name"

        # Name cell spans both Day and Night columns
        f_name = tk.Frame(grid_dn, bg="white")
        f_name.grid(row=0, column=col_day, columnspan=2, padx=5, pady=5)

        val_lbl_name = tk.Label(f_name, text=str(setpoints.get(name_key, f"TIMER {num}")),
                                font=("Arial", 9, "bold"), fg="#333", bg="white")
        val_lbl_name.pack(side="left")

        btn_name = tk.Button(f_name, text="EDIT", font=("Arial", 8, "bold"),
                             bg="#f5f5f5", fg="#333", activebackground=color, activeforeground="white",
                             bd=1, relief="groove", command=lambda k=name_key: open_keypad(k))
        btn_name.pack(side="left", padx=5)
        labels_s[name_key] = val_lbl_name

    # ── Row 1: Column headers ────────────────────────────────────────────────
    tk.Label(grid_dn, text="Setting", font=("Arial", 9, "bold"), fg="#555",
             bg="#f5f5f5", width=14, anchor="w").grid(row=1, column=0, padx=4, pady=2, sticky="ew")

    for idx, num in enumerate([8, 9, 10]):
        col_day = 1 + idx * 2
        tk.Label(grid_dn, text=f"T{num} Day", font=("Arial", 9, "bold"), fg=color,
                 bg="#f5f5f5", width=16, anchor="center").grid(row=1, column=col_day, padx=2, pady=2, sticky="ew")
        tk.Label(grid_dn, text=f"T{num} Night", font=("Arial", 9, "bold"), fg=color,
                 bg="#f5f5f5", width=16, anchor="center").grid(row=1, column=col_day+1, padx=2, pady=2, sticky="ew")

    # ── Rows 2-5: Setting rows ───────────────────────────────────────────────
    row_defs = [
        ("Start Time", "D_Start", "N_Start"),
        ("Stop Time",  "D_Stop",  "N_Stop"),
        ("ON Minutes", "D_ON Min","N_ON Min"),
        ("OFF Minutes","D_OFF Min","N_OFF Min"),
    ]

    for r_off, (r_lbl, d_suf, n_suf) in enumerate(row_defs):
        r_idx = 2 + r_off
        bg_row = "white" if r_off % 2 == 0 else "#fafafa"

        tk.Label(grid_dn, text=r_lbl, font=("Arial", 9, "bold"), fg="#555",
                 bg=bg_row, width=14, anchor="w").grid(row=r_idx, column=0, padx=4, pady=2, sticky="ew")

        for idx, num in enumerate([8, 9, 10]):
            col_day = 1 + idx * 2
            d_key = f"Timer{num} {d_suf}"
            n_key = f"Timer{num} {n_suf}"

            # Day cell
            c_day = tk.Frame(grid_dn, bg=bg_row)
            c_day.grid(row=r_idx, column=col_day, padx=3, pady=2)
            val_d = tk.Label(c_day, text=str(setpoints.get(d_key, "")),
                             font=("Arial", 9, "bold"), fg="#e65100", bg=bg_row, width=8, anchor="center")
            val_d.pack(side="left")
            tk.Button(c_day, text="EDIT", font=("Arial", 8, "bold"), bg="#f5f5f5", fg="#333",
                      bd=1, relief="groove", command=lambda k=d_key: open_keypad(k)).pack(side="right", padx=1)
            labels_s[d_key] = val_d

            # Night cell
            c_night = tk.Frame(grid_dn, bg=bg_row)
            c_night.grid(row=r_idx, column=col_day+1, padx=3, pady=2)
            val_n = tk.Label(c_night, text=str(setpoints.get(n_key, "")),
                             font=("Arial", 9, "bold"), fg="#e65100", bg=bg_row, width=8, anchor="center")
            val_n.pack(side="left")
            tk.Button(c_night, text="EDIT", font=("Arial", 8, "bold"), bg="#f5f5f5", fg="#333",
                      bd=1, relief="groove", command=lambda k=n_key: open_keypad(k)).pack(side="right", padx=1)
            labels_s[n_key] = val_n

    # Keypad frame (initially hidden)
    kp_frame = tk.Frame(win, bg="white")
    kp_title = tk.Label(kp_frame, font=("Arial", 12, "bold"), fg=color, bg="white")
    kp_title.pack()
    kp_display = tk.Label(kp_frame, font=("Arial", 18, "bold"), fg="#2e7d32", bg="white")
    kp_display.pack()
    kp_buttons = tk.Frame(kp_frame, bg="white")
    kp_buttons.pack()
    kp_actions = tk.Frame(kp_frame, bg="white")
    kp_actions.pack(pady=4)

    sp_entered_value = ""
    sp_selected_key = ""

    def kp_press(v):
        nonlocal sp_entered_value
        sp_entered_value += str(v)
        kp_display.config(text=sp_entered_value)

    def kp_clear():
        nonlocal sp_entered_value
        sp_entered_value = ""
        kp_display.config(text="")

    def kp_back():
        nonlocal sp_entered_value
        sp_entered_value = sp_entered_value[:-1]
        kp_display.config(text=sp_entered_value)

    def kp_confirm():
        nonlocal sp_entered_value, sp_selected_key
        try:
            val = (str(sp_entered_value)
                   if sp_selected_key.endswith("Name") or ":" in sp_entered_value
                   else float(sp_entered_value))
            
            # Format validation for times
            if ":" in str(val) and not sp_selected_key.endswith("Name"):
                try:
                    datetime.datetime.strptime(str(val), "%H:%M")
                except Exception:
                    kp_display.config(text="INVALID TIME")
                    return

            # Validate Day/Night conflict for timers 4, 8, 9, 10
            if sp_selected_key.startswith("Timer") and any(x in sp_selected_key for x in ["D_Start", "D_Stop", "N_Start", "N_Stop"]):
                import re
                m = re.match(r"Timer(\d+)", sp_selected_key)
                if m:
                    t_idx = m.group(1)
                    d_start = val if sp_selected_key == f"Timer{t_idx} D_Start" else setpoints.get(f"Timer{t_idx} D_Start", "10:00")
                    d_stop  = val if sp_selected_key == f"Timer{t_idx} D_Stop" else setpoints.get(f"Timer{t_idx} D_Stop", "17:00")
                    n_start = val if sp_selected_key == f"Timer{t_idx} N_Start" else setpoints.get(f"Timer{t_idx} N_Start", "17:05")
                    n_stop  = val if sp_selected_key == f"Timer{t_idx} N_Stop" else setpoints.get(f"Timer{t_idx} N_Stop", "09:55")
                    
                    try:
                        t_d_start = datetime.datetime.strptime(str(d_start), "%H:%M").time()
                        t_d_stop  = datetime.datetime.strptime(str(d_stop),  "%H:%M").time()
                        t_n_start = datetime.datetime.strptime(str(n_start), "%H:%M").time()
                        t_n_stop  = datetime.datetime.strptime(str(n_stop),  "%H:%M").time()
                        if (t_d_start >= t_d_stop or
                            t_n_start < t_d_stop or
                            t_d_start < t_n_stop or
                            t_n_start == t_n_stop):
                            kp_display.config(text="TIME CONFLICT")
                            return
                    except Exception:
                        kp_display.config(text="INVALID TIME")
                        return

            setpoints[sp_selected_key] = val
            if sp_selected_key in labels_s:
                labels_s[sp_selected_key].config(text=str(val))
            kp_frame.pack_forget()
            canvas_container.pack(fill="both", expand=True, padx=10, pady=5)
        except Exception:
            kp_display.config(text="ERROR")

    def kp_cancel():
        kp_frame.pack_forget()
        canvas_container.pack(fill="both", expand=True, padx=10, pady=5)

    def open_keypad(key):
        nonlocal sp_selected_key, sp_entered_value
        sp_selected_key = key
        sp_entered_value = ""
        kp_display.config(text="")
        kp_title.config(text=f"Set  {key}")
        for w in kp_buttons.winfo_children():
            w.destroy()
        for w in kp_actions.winfo_children():
            w.destroy()

        if key.endswith("Name"):
            for ri, row_k in enumerate([list("1234567890"), list("QWERTYUIOP"),
                                         list("ASDFGHJKL:"), list("ZXCVBNM._ ")]):
                for ci, ch in enumerate(row_k):
                    tk.Button(kp_buttons, text=ch if ch!=' ' else 'SPC',
                              font=("Arial", 11, "bold"), width=3,
                              command=lambda x=ch: kp_press(x)).grid(row=ri, column=ci, padx=2, pady=2)
            w_btn = 6
        else:
            for text, ri, ci in [('1',0,0), ('2',0,1), ('3',0,2), ('4',1,0), ('5',1,1), ('6',1,2),
                                 ('7',2,0), ('8',2,1), ('9',2,2), ('.',3,0), ('0',3,1), (':',3,2)]:
                tk.Button(kp_buttons, text=text, font=("Arial", 12, "bold"), width=4,
                          command=lambda x=text: kp_press(x)).grid(row=ri, column=ci, padx=3, pady=3)
            w_btn = 4

        for txt, bg, fg, cmd in [("DEL", "orange", "black", kp_back),
                                 ("CLR", "#d9534f", "white", kp_clear),
                                 ("OK", "green", "white", kp_confirm),
                                 ("CAN", "red", "white", kp_cancel)]:
            tk.Button(kp_actions, text=txt, font=("Arial", 11, "bold"), bg=bg, fg=fg,
                      width=w_btn, command=cmd).pack(side="left", padx=4)

        canvas_container.pack_forget()
        kp_frame.pack(pady=20)

    # Foot frame
    foot = tk.Frame(win, bg="#eeeeee", height=50)
    foot.pack(side="bottom", fill="x")
    foot.pack_propagate(False)
    
    btn_save = tk.Button(foot, text="SAVE & EXIT", font=("Arial", 10, "bold"), bg="#1e90ff", fg="white", width=14,
                         command=lambda: (save_setpoints(), init_mqtt_client(), win.destroy()))
    btn_save.pack(side="right", padx=15, pady=10)
    
    btn_cancel = tk.Button(foot, text="CANCEL", font=("Arial", 10, "bold"), bg="#cccccc", fg="black", width=10,
                           command=win.destroy)
    btn_cancel.pack(side="right", padx=10, pady=10)

    btn_timers_nav = tk.Button(foot, text="TIMERS", font=("Arial", 10, "bold"), bg="#059669", fg="white", width=10,
                               command=lambda: (win.destroy(), open_timers_status_window()))
    btn_timers_nav.pack(side="left", padx=15, pady=10)

timers_ui_labels = {}

def update_live_timers_ui():
    sp = setpoints
    def set_lbl_state(key, active, active_text="ACTIVE", inactive_text="INACTIVE"):
        if key in timers_ui_labels:
            try:
                lbl = timers_ui_labels[key]
                if lbl.winfo_exists():
                    if active:
                        lbl.config(text=active_text, fg="#2e7d32")
                    else:
                        lbl.config(text=inactive_text, fg="#c62828")
            except Exception:
                pass

    def set_lbl_text(key, text):
        if key in timers_ui_labels:
            try:
                lbl = timers_ui_labels[key]
                if lbl.winfo_exists():
                    lbl.config(text=text)
            except Exception:
                pass

    st = state[1]
    set_lbl_state("ec_mode", st["ec_active"])
    set_lbl_state("ph_mode", st["ph_active"])
    set_lbl_state("ac_mode", st["ac_active"])
    set_lbl_state("humi_mode", st["humi_active"])

    set_lbl_state("r_ec1", relay_is_on(1), "ON", "OFF")
    set_lbl_state("r_ec2", relay_is_on(2), "ON", "OFF")
    set_lbl_state("r_ph", relay_is_on(3), "ON", "OFF")
    set_lbl_state("r_ac", relay_is_on(4), "ON", "OFF")
    set_lbl_state("r_humi", relay_is_on(5), "ON", "OFF")
    
    timer_channels = [6, 7, 8, 4, 9, 10, 11, 12, 13, 14]
    for idx in range(10):
        ch = timer_channels[idx]
        set_lbl_state(f"r_tmr{idx+1}", relay_is_on(ch), "ON", "OFF")

    for i in range(10):
        tname = sp.get(f"Timer{i+1} Name", f"TIMER {i+1}")
        set_lbl_text(f"tname{i+1}", f"  {tname.upper()}  ")

        ts = timer_state[1][i]
        is_on = (ts["state"] == "ON")
        set_lbl_state(f"t{i+1}_status", is_on, "ON", "OFF")

        if i in [3, 7, 8, 9]:
            w_text = f"D:{sp.get(f'Timer{i+1} D_Start','10:00')}-{sp.get(f'Timer{i+1} D_Stop','17:00')} / N:{sp.get(f'Timer{i+1} N_Start','17:05')}-{sp.get(f'Timer{i+1} N_Stop','09:55')}"
            c_text = f"D:{sp.get(f'Timer{i+1} D_ON Min',15)}m/{sp.get(f'Timer{i+1} D_OFF Min',30)}m N:{sp.get(f'Timer{i+1} N_ON Min',15)}m/{sp.get(f'Timer{i+1} N_OFF Min',30)}m"
        else:
            w_text = f"{sp.get(f'Timer{i+1} Start','10:00')}-{sp.get(f'Timer{i+1} Stop','17:00')}"
            c_text = f"ON {sp.get(f'Timer{i+1} ON Min',15)}m / OFF {sp.get(f'Timer{i+1} OFF Min',30)}m"
        set_lbl_text(f"t{i+1}_window", w_text)
        set_lbl_text(f"t{i+1}_cycle", c_text)

def open_timers_status_window():
    global timers_ui_labels
    win = tk.Toplevel()
    win.title("Timers & Relays Live Dashboard")
    win.geometry("1280x720")
    win.configure(bg="white")
    win.resizable(False, False)
    
    win.update_idletasks()
    x = (win.winfo_screenwidth() - 1280) // 2
    y = (win.winfo_screenheight() - 720) // 2
    win.geometry(f"+{x}+{y}")
    
    color = "#1565c0"
    timers_ui_labels.clear()
    
    # Header Section (Static at top)
    header = tk.Frame(win, bg="white")
    header.pack(fill="x", pady=(5, 2), padx=20)
    
    tk.Label(
        header,
        text="SYSTEM — LIVE TIMERS & RELAYS MONITOR",
        font=("Arial", 16, "bold"),
        fg=color,
        bg="white"
    ).pack(side="left", pady=10)
    
    logo = get_logo_image()
    if logo:
        lbl_logo = tk.Label(header, image=logo, bg="white")
        lbl_logo.image = logo
        lbl_logo.pack(side="right", padx=10)
        
    # Canvas Container for Scrollability
    canvas_container = tk.Frame(win, bg="#f8fafc")
    canvas_container.pack(fill="both", expand=True, padx=10, pady=5)
    
    canvas = tk.Canvas(canvas_container, bg="#f8fafc", highlightthickness=0)
    scrollbar = tk.Scrollbar(canvas_container, orient="vertical", command=canvas.yview)
    
    scrollable_frame = tk.Frame(canvas, bg="#f8fafc")
    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    def on_canvas_configure(event):
        canvas.itemconfig(canvas_window, width=event.width)
    canvas.bind("<Configure>", on_canvas_configure)
    
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    
    # Bind MouseWheel for scrolling (including Linux support)
    def _on_mousewheel(event):
        if canvas.winfo_exists():
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    win.bind_all("<MouseWheel>", _on_mousewheel)
    win.bind_all("<Button-4>", _on_mousewheel)
    win.bind_all("<Button-5>", _on_mousewheel)
    win.bind("<Destroy>", lambda e: (
        win.unbind_all("<MouseWheel>"),
        win.unbind_all("<Button-4>"),
        win.unbind_all("<Button-5>")
    ))
    
    # Columns inside scrollable_frame
    col_L = tk.Frame(scrollable_frame, bg="#f8fafc")
    col_L.pack(side="left", fill="both", expand=True, padx=15)
    
    tk.Frame(scrollable_frame, bg="#cbd5e1", width=1).pack(side="left", fill="y", pady=10)
    
    col_M = tk.Frame(scrollable_frame, bg="#f8fafc")
    col_M.pack(side="left", fill="both", expand=True, padx=15)
    
    tk.Frame(scrollable_frame, bg="#cbd5e1", width=1).pack(side="left", fill="y", pady=10)
    
    col_R = tk.Frame(scrollable_frame, bg="#f8fafc")
    col_R.pack(side="left", fill="both", expand=True, padx=15)
    
    # Helper function to generate clean card for each timer
    def make_timer_status_card(parent, i):
        tname_key = f"Timer{i+1} Name"
        card = tk.LabelFrame(
            parent,
            text=f"  {setpoints.get(tname_key, f'TIMER {i+1}').upper()}  ",
            font=("Arial", 10, "bold"),
            fg=color,
            bg="white",
            bd=2,
            relief="groove"
        )
        card.pack(fill="x", pady=6, padx=5)
        timers_ui_labels[f"tname{i+1}"] = card
        
        # Row 1: Status
        r1 = tk.Frame(card, bg="white")
        r1.pack(fill="x", pady=2, padx=10)
        tk.Label(r1, text="State:", font=("Arial", 9, "bold"), fg="#475569", bg="white").pack(side="left")
        lbl_status = tk.Label(r1, text="OFF", font=("Arial", 9, "bold"), fg="#c62828", bg="white")
        lbl_status.pack(side="right")
        timers_ui_labels[f"t{i+1}_status"] = lbl_status
        
        # Row 2: Active Window
        r2 = tk.Frame(card, bg="white")
        r2.pack(fill="x", pady=2, padx=10)
        tk.Label(r2, text="Time Window:", font=("Arial", 9, "bold"), fg="#475569", bg="white").pack(side="left")
        lbl_window = tk.Label(r2, text="---", font=("Arial", 9, "bold"), fg="#1e293b", bg="white")
        lbl_window.pack(side="right")
        timers_ui_labels[f"t{i+1}_window"] = lbl_window
        
        # Row 3: Cycle
        r3 = tk.Frame(card, bg="white")
        r3.pack(fill="x", pady=2, padx=10)
        tk.Label(r3, text="Active Cycle:", font=("Arial", 9, "bold"), fg="#475569", bg="white").pack(side="left")
        lbl_cycle = tk.Label(r3, text="---", font=("Arial", 9, "bold"), fg="#e65100", bg="white")
        lbl_cycle.pack(side="right")
        timers_ui_labels[f"t{i+1}_cycle"] = lbl_cycle

    # Left Column: Timers 1 to 5
    tk.Label(col_L, text="CYCLIC TIMERS 1 - 5", font=("Arial", 12, "bold"), fg=color, bg="#f8fafc").pack(pady=(6, 4))
    for i in range(5):
        make_timer_status_card(col_L, i)
        
    # Right Column: Timers 6 to 10
    tk.Label(col_R, text="CYCLIC TIMERS 6 - 10", font=("Arial", 12, "bold"), fg=color, bg="#f8fafc").pack(pady=(6, 4))
    for i in range(5, 10):
        make_timer_status_card(col_R, i)
        
    # Middle Column: System Relays & Control Modes
    tk.Label(col_M, text="SYSTEM STATUS & RELAYS", font=("Arial", 12, "bold"), fg=color, bg="#f8fafc").pack(pady=(6, 4))
    
    # Mode Card
    card_modes = tk.LabelFrame(col_M, text="  DOSING CONTROL MODES  ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
    card_modes.pack(fill="x", pady=6, padx=5)
    
    modes_rows = [
        ("EC Control Mode", "ec_mode"),
        ("pH Control Mode", "ph_mode"),
        ("AC Control Mode", "ac_mode"),
        ("Humi Control Mode", "humi_mode"),
    ]
    for lbl_text, key in modes_rows:
        f = tk.Frame(card_modes, bg="white")
        f.pack(fill="x", pady=3, padx=10)
        tk.Label(f, text=lbl_text, font=("Arial", 9, "bold"), fg="#475569", bg="white").pack(side="left")
        lbl = tk.Label(f, text="INACTIVE", font=("Arial", 9, "bold"), fg="#c62828", bg="white")
        lbl.pack(side="right")
        timers_ui_labels[key] = lbl

    # Primary Dosing Relays Card
    card_primary = tk.LabelFrame(col_M, text="  PRIMARY DOSING RELAYS  ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
    card_primary.pack(fill="x", pady=6, padx=5)
    
    primary_rows = [
        ("EC1 Feed (Ch 1)", "r_ec1"),
        ("EC2 Feed (Ch 2)", "r_ec2"),
        ("pH Dose (Ch 3)", "r_ph"),
        ("AC Cooler (Ch 4)", "r_ac"),
        ("Humidifier (Ch 5)", "r_humi"),
    ]
    for lbl_text, key in primary_rows:
        f = tk.Frame(card_primary, bg="white")
        f.pack(fill="x", pady=3, padx=10)
        tk.Label(f, text=lbl_text, font=("Arial", 9, "bold"), fg="#475569", bg="white").pack(side="left")
        lbl = tk.Label(f, text="OFF", font=("Arial", 9, "bold"), fg="#c62828", bg="white")
        lbl.pack(side="right")
        timers_ui_labels[key] = lbl

    # Cyclic Timer Channels Card
    card_timer_ch = tk.LabelFrame(col_M, text="  CYCLIC RELAY CHANNELS  ", font=("Arial", 10, "bold"), fg=color, bg="white", bd=2, relief="groove")
    card_timer_ch.pack(fill="x", pady=6, padx=5)
    
    timer_ch_rows = [
        ("Timer 1 (Ch 6)", "r_tmr1"),
        ("Timer 2 (Ch 7)", "r_tmr2"),
        ("Timer 3 (Ch 8)", "r_tmr3"),
        ("Timer 5 (Ch 9)", "r_tmr5"),
        ("Timer 6 (Ch 10)", "r_tmr6"),
        ("Timer 7 (Ch 11)", "r_tmr7"),
        ("Timer 8 (Ch 12)", "r_tmr8"),
        ("Timer 9 (Ch 13)", "r_tmr9"),
        ("Timer 10 (Ch 14)", "r_tmr10"),
    ]
    for lbl_text, key in timer_ch_rows:
        f = tk.Frame(card_timer_ch, bg="white")
        f.pack(fill="x", pady=3, padx=10)
        tk.Label(f, text=lbl_text, font=("Arial", 9, "bold"), fg="#475569", bg="white").pack(side="left")
        lbl = tk.Label(f, text="OFF", font=("Arial", 9, "bold"), fg="#c62828", bg="white")
        lbl.pack(side="right")
        timers_ui_labels[key] = lbl
        
    # Foot frame
    foot = tk.Frame(win, bg="#eeeeee", height=50)
    foot.pack(side="bottom", fill="x")
    foot.pack_propagate(False)
    
    tk.Button(foot, text="BACK TO HOME", font=("Arial", 10, "bold"), bg="#64748b", fg="white", width=14,
              command=win.destroy).pack(side="right", padx=15, pady=10)
    
    tk.Button(foot, text="SETPOINTS", font=("Arial", 10, "bold"), bg="#1e90ff", fg="white", width=12,
              command=lambda: (win.destroy(), open_setpoints_window())).pack(side="left", padx=15, pady=10)

    update_live_timers_ui()

def open_timers_window():
    open_timers_status_window()



# --- UI Setup ---
root = tk.Tk()
root.title("Sensor Monitor")
root.geometry("1280x720")
root.config(bg="#f8fafc")

# Header Section (Reduced pady to bring it closer to boxes)
header = tk.Frame(root, bg="#f8fafc")
header.pack(fill="x", pady=(10, 2), padx=20)

# Left Side: Title & Subtitle
title_frame = tk.Frame(header, bg="#f8fafc")
title_frame.pack(side="left", padx=(10, 20))

tk.Label(
    title_frame,
    text="INHYDRO SMART MONITOR",
    font=("Helvetica", 24, "bold"),
    fg="#0f172a",
    bg="#f8fafc"
).pack(anchor="w")

"""tk.Label(
    title_frame,
    text=f"Device ID: {DEVICE_NAME.upper()}",
    font=("Helvetica", 10, "bold"),
    fg="#64748b",
    bg="#f8fafc"
).pack(anchor="w", pady=(2, 0))"""

# Right: Brand Image Logo in the last upside right corner (Scaled down to 100x63 for compact height)
logo_img_main = get_logo_image()
if logo_img_main:
    lbl_logo = tk.Label(header, image=logo_img_main, bg="#f8fafc")
    lbl_logo.image = logo_img_main
    lbl_logo.pack(side="right", padx=(30,10))

# Footer Section
footer = tk.Frame(root, bg="#f8fafc")
footer.pack(side="bottom", fill="x", pady=(5, 10), padx=20)

divider = tk.Frame(root, height=1, bg="#e2e8f0")
divider.pack(fill="x", side="bottom", pady=(2, 5))

# Clock & Date in the lower left side
clock_frame = tk.Frame(footer, bg="#f8fafc")
clock_frame.pack(side="left", padx=10)

lbl_clock = tk.Label(
    clock_frame,
    text="00:00:00",
    font=("Helvetica", 18, "bold"),
    fg="#0f172a",
    bg="#f8fafc"
)
lbl_clock.pack(anchor="w")

lbl_date = tk.Label(
    clock_frame,
    text="Loading date...",
    font=("Helvetica", 9, "bold"),
    fg="#64748b",
    bg="#f8fafc"
)
lbl_date.pack(anchor="w")

# Buttons in the footer right side
btn_frame = tk.Frame(footer, bg="#f8fafc")
btn_frame.pack(side="right", padx=20)

btn_setpoints = tk.Button(
    btn_frame,
    text="SETPOINTS",
    font=("Helvetica", 10, "bold"),
    bg="#0284c7",
    fg="white",
    activebackground="#0369a1",
    activeforeground="white",
    bd=0,
    highlightthickness=0,
    command=open_setpoints_window,
    padx=20,
    pady=8,
    cursor="hand2"
)
btn_setpoints.pack(side="left", padx=10)

btn_timers = tk.Button(
    btn_frame,
    text="TIMERS",
    font=("Helvetica", 10, "bold"),
    bg="#059669",
    fg="white",
    activebackground="#047857",
    activeforeground="white",
    bd=0,
    highlightthickness=0,
    command=open_timers_window,
    padx=20,
    pady=8,
    cursor="hand2"
)
btn_timers.pack(side="left", padx=10)

btn_restart = tk.Button(
    btn_frame,
    text="RESTART",
    font=("Helvetica", 10, "bold"),
    bg="#d97706",
    fg="white",
    activebackground="#b45309",
    activeforeground="white",
    bd=0,
    highlightthickness=0,
    command=restart_program,
    padx=20,
    pady=8,
    cursor="hand2"
)
btn_restart.pack(side="left", padx=10)

btn_exit = tk.Button(
    btn_frame,
    text="EXIT",
    font=("Helvetica", 10, "bold"),
    bg="#e11d48",
    fg="white",
    activebackground="#be123c",
    activeforeground="white",
    bd=0,
    highlightthickness=0,
    command=quit_app,
    padx=20,
    pady=8,
    cursor="hand2"
)
btn_exit.pack(side="left", padx=10)

# Main Grid Frame (Reduced vertical padding to fit screen)
frame = tk.Frame(root, bg="#f8fafc")
frame.pack(expand=True, fill="both", padx=20, pady=(2, 5))

labels = {}

# Column 1: Soil Sensors
col_soil = tk.Frame(frame, bg="#f8fafc")
col_soil.pack(side="left", expand=True, fill="both")

# Divider 1
sep1 = tk.Frame(frame, width=1, bg="#cbd5e1")
sep1.pack(side="left", fill="y", padx=10)

# Column 2: Room, CO2, ORP
col_room = tk.Frame(frame, bg="#f8fafc")
col_room.pack(side="left", expand=True, fill="both")

# Divider 2
sep2 = tk.Frame(frame, width=1, bg="#cbd5e1")
sep2.pack(side="left", fill="y", padx=10)

# Column 3: DO & NPK
col_do_npk = tk.Frame(frame, bg="#f8fafc")
col_do_npk.pack(side="left", expand=True, fill="both")

# Divider 3
sep3 = tk.Frame(frame, width=1, bg="#cbd5e1")
sep3.pack(side="left", fill="y", padx=10)

# Column 4: Rest of the Sensors
col_others = tk.Frame(frame, bg="#f8fafc")
col_others.pack(side="left", expand=True, fill="both")

soil_keys = ["Water Temp", "Water Moisture", "Water EC", "Water pH"]
room_keys = ["Room Temp", "Room Humidity", "CO2", "ORP"]
do_npk_keys = ["DO", "Nitrogen", "Phosphorus", "Potassium"]
others_keys = ["VPD", "DLI", "Wind Speed", "Wind Direction", "PPFD"]

def create_column_cards(parent_frame, keys):
    for key in keys:
        box = tk.Frame(
            parent_frame,
            bg="#f1f5f9",
            highlightthickness=1,
            highlightbackground="#e2e8f0",
            width=180,
            height=68
        )
        box.pack_propagate(False)
        box.pack(pady=3, anchor="center")
        
        lbl_title = tk.Label(
            box,
            text=key.upper(),
            font=("Helvetica", 8, "bold"),
            bg="white",
            fg="#64748b"
        )
        lbl_title.pack(pady=(8, 2))
        
        lbl_val = tk.Label(
            box,
            text="Reading...",
            font=("Helvetica", 12, "bold"),
            bg="white",
            fg="#475569"
        )
        lbl_val.pack(pady=(0, 8))
        
        labels[key] = lbl_val

create_column_cards(col_soil, soil_keys)
create_column_cards(col_room, room_keys)
create_column_cards(col_do_npk, do_npk_keys)
create_column_cards(col_others, others_keys)

def update_ui():
    # Update real-time clock
    now = datetime.datetime.now()
    lbl_clock.config(text=now.strftime("%H:%M:%S"))
    lbl_date.config(text=now.strftime("%A, %B %d, %Y"))

    # Update sensor cards
    for key, val in latest_data.items():
        if key in labels:
            labels[key].config(text=val)
            if "N/A" in val:
                labels[key].config(fg="#dc2626")  # Rose/Red-600
            else:
                labels[key].config(fg="#059669")  # Emerald-600
    
    # Prepare data dictionary structure for room 1 similar to cntrl21.py
    soil_data = {
        "temp": latest_raw.get("water_temp"),
        "moisture": latest_raw.get("moisture"),
        "ec": latest_raw.get("ec"),
        "ph": latest_raw.get("ph")
    } if any(latest_raw.get(k) is not None for k in ["water_temp", "moisture", "ec", "ph"]) else None

    room_data = {
        "room_temp": latest_raw.get("room_temp"),
        "room_humi": latest_raw.get("room_humi")
    } if any(latest_raw.get(k) is not None for k in ["room_temp", "room_humi"]) else None

    sensor_data_1 = {
        "soil": soil_data,
        "room": room_data
    }

    try:
        run_timers(1)
    except Exception as e:
        print("Error running timers:", e)

    try:
        control_room(1, sensor_data_1)
    except Exception as e:
        print("Error running control system:", e)

    try:
        update_live_timers_ui()
    except Exception as e:
        print("Error updating live timers UI:", e)

    publish_live_telemetry()
    publish_telemetry()
    save_local_telemetry()
    
    root.after(1000, update_ui)

root.bind("<Escape>", lambda e: quit_app())
root.protocol("WM_DELETE_WINDOW", quit_app)
root.after(1000, update_ui)

if __name__ == "__main__":
    root.mainloop()
