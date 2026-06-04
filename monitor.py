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
                
    os.execl(sys.executable, sys.executable, *sys.argv)


# --- UI Setup ---
root = tk.Tk()
root.title("Sensor Monitor")
root.geometry("1280x720")
# root.attributes("-fullscreen", True)

header = tk.Frame(root)
header.pack(fill="x", pady=10, padx=20)

LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
try:
    logo_raw = Image.open(LOGO_PATH).resize((130, 82), Image.LANCZOS)
    logo_img = ImageTk.PhotoImage(logo_raw)
    lbl_logo = tk.Label(header, image=logo_img)
    lbl_logo.image = logo_img
    lbl_logo.pack(side="right", padx=10)
except Exception as e:
    print(f"Logo error: {e}")

"""tk.Label(
    header,
    text=f"Comprehensive Sensor Monitor - {DEVICE_NAME}",
    font=("Arial", 18, "bold"),
    fg="#2c3e50"
).pack(side="left", padx=10, pady=10)"""

footer = tk.Frame(root)
footer.pack(side="bottom", fill="x", pady=10)

btn_frame = tk.Frame(footer)
btn_frame.pack(side="right", padx=40)

tk.Button(
    btn_frame,
    text="RESTART",
    font=("Arial", 14, "bold"),
    bg="#f39c12",
    fg="white",
    activebackground="#d35400",
    activeforeground="white",
    bd=0,
    highlightthickness=0,
    command=restart_program,
    padx=20,
    pady=10
).pack(side="left", padx=10)

tk.Button(
    btn_frame,
    text="EXIT",
    font=("Arial", 14, "bold"),
    bg="#e74c3c",
    fg="white",
    activebackground="#c0392b",
    activeforeground="white",
    bd=0,
    highlightthickness=0,
    command=root.destroy,
    padx=20,
    pady=10
).pack(side="left", padx=10)

frame = tk.Frame(root)
frame.pack(expand=True, fill="both", padx=10, pady=10)

labels = {}
cols = 6
row, col = 0, 0

sensor_keys = [
    "Water Temp", "Water Moisture", "Water EC", "Water pH",
    "Room Temp", "Room Humidity", "ORP", "CO2",
    "VPD", "DLI", "Wind Speed", "Wind Direction",
    "DO", "PPFD", "Nitrogen", "Phosphorus", "Potassium"
]

for key in sensor_keys:
    box = tk.Frame(frame, bg="white", bd=2, relief="groove", width=170, height=90)
    box.pack_propagate(False)
    box.grid(row=row, column=col, padx=10, pady=10)
    
    lbl_title = tk.Label(
        box,
        text=key,
        font=("Arial", 11, "bold"),
        bg="white",
        fg="#7f8c8d"
    )
    lbl_title.pack(pady=(5, 2))
    
    lbl_val = tk.Label(
        box,
        text="Reading...",
        font=("Arial", 14, "bold"),
        bg="white",
        fg="#2980b9"
    )
    lbl_val.pack(pady=(2, 5))
    
    labels[key] = lbl_val
    
    col += 1
    if col >= cols:
        col = 0
        row += 1

for i in range(cols):
    frame.columnconfigure(i, weight=1)

def update_ui():
    for key, val in latest_data.items():
        if key in labels:
            if "N/A" in val:
                labels[key].config(text=val, fg="#e74c3c")
            else:
                labels[key].config(text=val, fg="#27ae60")
    
    publish_live_telemetry()
    publish_telemetry()
    save_local_telemetry()
    
    root.after(1000, update_ui)

root.bind("<Escape>", lambda e: root.destroy())
root.after(1000, update_ui)

if __name__ == "__main__":
    root.mainloop()
