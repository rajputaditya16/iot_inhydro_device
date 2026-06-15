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
LOG_DIR = os.path.join(BASE_DIR, "local_logs_monitor")
ACTIVE_LOG_FILE = os.path.join(LOG_DIR, "active.jsonl")

setpoints = {
    "CLIENT ID": "",
    "USERNAME": "",
    "PASSWORD": "",
    "CHANNEL ID": "",
    "PORT": 1883,
    "READ API KEY": "",
    "WRITE API KEY": "",
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

is_mqtt_connected = False

def on_control_connect(client, userdata, flags, rc, properties=None):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        print("✅ Control MQTT (HiveMQ) connected/reconnected")
        try:
            client.subscribe(f"inhydro/{DEVICE_NAME}/monitor/setpoints/update")
            client.subscribe(f"inhydro/{DEVICE_NAME}/monitor/setpoints/request_sync")
            client.publish(f"inhydro/{DEVICE_NAME}/monitor/setpoints/current", json.dumps(setpoints), retain=True)
        except Exception as e:
            print(f"⚠️ Error during control MQTT sub/pub: {e}")
    else:
        is_mqtt_connected = False
        print(f"⚠️ Control MQTT connection failed with code {rc}")

def on_control_disconnect(client, userdata, flags, rc, properties=None, *args, **kwargs):
    global is_mqtt_connected
    is_mqtt_connected = False
    print("⚠️ Control MQTT (HiveMQ) disconnected")

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
control_client.on_connect = on_control_connect
control_client.on_disconnect = on_control_disconnect

try:
    control_client.loop_start()
    control_client.connect_async(CONTROL_BROKER, CONTROL_PORT, 10)
    print("✅ Control MQTT (HiveMQ) loop started (connecting...)")
except Exception as e:
    print(f"⚠️ Error starting control MQTT client: {e}")


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
            except Exception:
                pass
            
        try:
            out = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True)
            for line in out.split('\n'):
                if line.startswith('Device '):
                    os.system(f"sudo bluetoothctl trust {line.split()[1]} >/dev/null 2>&1")
        except Exception:
            pass
        time.sleep(5)

def start_bluetooth_server():
    while True:
        srv = None
        try:
            os.system("sudo sdptool add --channel=3 SP >/dev/null 2>&1")
            time.sleep(1)
            srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            srv.bind((socket.BDADDR_ANY, 3))
            srv.listen(1)
            print("Bluetooth RFCOMM server listening on channel 3")
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
                    print(f"BT connection error: {e}")
                finally:
                    if cli:
                        try:
                            cli.close()
                        except Exception:
                            pass
        except Exception as e:
            print(f"BT server socket crashed, retrying in 5s: {e}")
            time.sleep(5)
        finally:
            if srv:
                try:
                    srv.close()
                except Exception:
                    pass

# Threads are started at the end of the file after all target functions are defined


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
            ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            ts_str = datetime.datetime.now(ist_tz).isoformat()
            payload = {
                "telemetry": latest_raw,
                "device": DEVICE_NAME,
                "timestamp": ts_str
            }
            control_client.publish(f"inhydro/{DEVICE_NAME}/monitor/telemetry/live", json.dumps(payload))
    except Exception:
        pass

local_log_lock = threading.Lock()

COLUMNS = [
    "timestamp",
    "water_temp", "moisture", "ec", "ph",
    "room_temp", "room_humi", "orp", "co2",
    "vpd", "dli", "wind_speed", "wind_dir", "do", "ppfd", "n", "p", "k"
]

def pack_entry(ts, raw):
    row = [ts]
    row.extend([
        raw.get("water_temp"),
        raw.get("moisture"),
        raw.get("ec"),
        raw.get("ph"),
        raw.get("room_temp"),
        raw.get("room_humi"),
        raw.get("orp"),
        raw.get("co2"),
        raw.get("vpd"),
        raw.get("dli"),
        raw.get("wind_speed"),
        raw.get("wind_dir"),
        raw.get("do"),
        raw.get("ppfd"),
        raw.get("n"),
        raw.get("p"),
        raw.get("k")
    ])
    return row

def unpack_row(row):
    if not isinstance(row, list) or len(row) < 18:
        return None
    ts = row[0]
    raw = {
        "water_temp": row[1],
        "moisture": row[2],
        "ec": row[3],
        "ph": row[4],
        "room_temp": row[5],
        "room_humi": row[6],
        "orp": row[7],
        "co2": row[8],
        "vpd": row[9],
        "dli": row[10],
        "wind_speed": row[11],
        "wind_dir": row[12],
        "do": row[13],
        "ppfd": row[14],
        "n": row[15],
        "p": row[16],
        "k": row[17]
    }
    payload = {
        "telemetry": raw,
        "device": DEVICE_NAME,
        "timestamp": ts
    }
    return payload

def save_local_telemetry():
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
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ts_str = datetime.datetime.now(ist_tz).isoformat()

    raw_data = latest_raw if latest_raw is not None else {}
    try:
        new_row = pack_entry(ts_str, raw_data)
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
                                control_client.publish(f"inhydro/{DEVICE_NAME}/monitor/telemetry/live", json.dumps(batch_payload), qos=1)
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

def restart_program():
    for inst in sensors.values():
        if inst:
            try:
                inst.serial.close()
            except Exception:
                pass
                
    os.execl(sys.executable, sys.executable, *sys.argv)


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
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
try:
    logo_raw = Image.open(LOGO_PATH).resize((100, 63), Image.LANCZOS)
    logo_img = ImageTk.PhotoImage(logo_raw)
    lbl_logo = tk.Label(header, image=logo_img, bg="#f8fafc")
    lbl_logo.image = logo_img
    lbl_logo.pack(side="right", padx=(30,10))
except Exception as e:
    print(f"Logo error: {e}")

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

btn_restart = tk.Button(
    btn_frame,
    text="RESTART ",
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
    text="EXIT ",
    font=("Helvetica", 10, "bold"),
    bg="#e11d48",
    fg="white",
    activebackground="#be123c",
    activeforeground="white",
    bd=0,
    highlightthickness=0,
    command=root.destroy,
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
            bg="#white",
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
    
    publish_live_telemetry()
    publish_telemetry()
    save_local_telemetry()
    
    root.after(1000, update_ui)

threading.Thread(target=auto_trust_devices, daemon=True).start()
threading.Thread(target=start_bluetooth_server, daemon=True).start()
threading.Thread(target=sync_offline_data_worker, daemon=True).start()

root.bind("<Escape>", lambda e: root.destroy())
root.after(1000, update_ui)

if __name__ == "__main__":
    root.mainloop()
