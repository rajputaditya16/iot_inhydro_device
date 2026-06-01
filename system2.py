import os, sys, json, time, datetime, atexit
import socket, subprocess, threading
import tkinter as tk
from PIL import Image, ImageTk
from tkinter import font
from gpiozero import OutputDevice, Device
import minimalmodbus
import serial
import paho.mqtt.client as mqtt

# GPIO BACKEND
try: 
    from gpiozero.pins.pigpio import PiGPIOFactory
    Device.pin_factory = PiGPIOFactory() 
except:
    pass

# CONFIG
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                return f.read().strip()
        except: pass
    return "system2" # Default fallback

DEVICE_NAME = get_device_id()
print(f"🚀 Device Identity Loaded: {DEVICE_NAME}")

SETPOINT_FILE = os.path.join(BASE_DIR, f"setpoints_{DEVICE_NAME}.json")
print(f"📄 Using config: {SETPOINT_FILE}")

# DELETE LEGACY CONFIG TO PREVENT SYNC ERRORS
OLD_FILE = os.path.join(BASE_DIR, "setpoints.json")
if os.path.exists(OLD_FILE):
    try:
        os.remove(OLD_FILE)
        print("🗑️ Removed legacy setpoints.json to ensure dynamic sync...")
    except: pass

SERIAL_PORT = "/dev/ttyUSB0"
DEVICE_ID = 1

#ThingSpeak MQTT Settings 
MQTT_BROKER = "mqtt3.thingspeak.com"

# ACTIVE LOW RELAYS 
relay_ec1 = OutputDevice(22, active_high=False, initial_value=False)
relay_ec2 = OutputDevice(23, active_high=False, initial_value=False)
relay_ph  = OutputDevice(24, active_high=False, initial_value=False)

# CYCLIC TIMER RELAYS (Hardcoded)
timer_relay_1 = OutputDevice(5, active_high=False, initial_value=False)
timer_relay_2 = OutputDevice(6, active_high=False, initial_value=False)
timer_relay_3 = OutputDevice(13, active_high=False, initial_value=False)
timer_relay_4 = OutputDevice(19, active_high=False, initial_value=False)
timer_relays = [timer_relay_1, timer_relay_2, timer_relay_3, timer_relay_4]

relay_ec1.off()
relay_ec2.off()
relay_ph.off()

# CONTROL STATE 
ec_active = False
ph_active = False
last_ec = 0
last_ph = 0
mqtt_timer = 0  # To track 20s cloud updates

# SETPOINTS 
setpoints = {
    "EC MIN": 1200,
    "EC MAX": 1800,
    "PH LOW": 5.8,
    "PH HIGH": 6.5,
    "Timer1 Name": "TIMER 1",
    "Timer1 Pin": 17,
    "Timer1 Start": "10:00",
    "Timer1 Stop": "17:00",
    "Timer1 ON Min": 15,
    "Timer1 OFF Min": 30,
    "Timer2 Name": "TIMER 2",
    "Timer2 Pin": 27,
    "Timer2 Start": "10:00",
    "Timer2 Stop": "17:00",
    "Timer2 ON Min": 15,
    "Timer2 OFF Min": 30,
    "Timer3 Name": "TIMER 3",
    "Timer3 Pin": 25,
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
            with open(SETPOINT_FILE) as f:
                setpoints.update(json.load(f))
            print("Configuration loaded")
        except:
            pass

load_setpoints()

def save_setpoints():
    with open(SETPOINT_FILE, "w") as f:
        json.dump(setpoints, f, indent=4)
    # Publish to cloud as soon as we save so the web has the latest true values
    try:
        control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
        print("✅ Pushed current setpoints to cloud.")
    except Exception as e:
        pass

# CYCLIC TIMER LOGIC
timer_cycle_state = ["OFF", "OFF", "OFF"]
timer_last_switch = [0, 0, 0]

def is_within_time_window(start_str, stop_str):
    now = datetime.datetime.now().time()
    try:
        start_t = datetime.datetime.strptime(str(start_str), "%H:%M").time()
        end_t = datetime.datetime.strptime(str(stop_str), "%H:%M").time()
    except Exception as e:
        return False
    
    if start_t <= end_t:
        return start_t <= now <= end_t
    else:
        return now >= start_t or now <= end_t

def turn_relay_on(i):
    if timer_relays[i] and not timer_relays[i].is_active:
        timer_relays[i].on()
        print(f"Current time: {datetime.datetime.now().strftime('%H:%M')} - Timer {i+1} Relay ON")

def turn_relay_off(i):
    if timer_relays[i] and timer_relays[i].is_active:
        timer_relays[i].off()
        print(f"Current time: {datetime.datetime.now().strftime('%H:%M')} - Timer {i+1} Relay OFF")

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
        run_sec = float(setpoints.get(configs[i][2], 15)) * 60
        stop_sec = float(setpoints.get(configs[i][3], 30)) * 60
        
        if is_within_time_window(start_str, stop_str):
            if timer_cycle_state[i] == "OFF":
                if now - timer_last_switch[i] >= stop_sec or timer_last_switch[i] == 0:
                    print(f"Timer {i+1}: Inside active window")
                    turn_relay_on(i)
                    timer_cycle_state[i] = "ON"
                    timer_last_switch[i] = now
            elif timer_cycle_state[i] == "ON":
                if now - timer_last_switch[i] >= run_sec:
                    turn_relay_off(i)
                    timer_cycle_state[i] = "OFF"
                    timer_last_switch[i] = now
                    print(f"Timer {i+1}: Cycle completed")
        else:
            if timer_cycle_state[i] == "ON" or (timer_relays[i] and timer_relays[i].is_active):
                turn_relay_off(i)
                timer_cycle_state[i] = "OFF"
                timer_last_switch[i] = 0
                print(f"Timer {i+1}: Outside active window - Waiting for next window")

def safe_exit():
    print("Performing safe GPIO cleanup... All timer relays OFF on exit")
    for i in range(3):
        turn_relay_off(i)

atexit.register(safe_exit)

# ==========================================
# BLUETOOTH / WIFI SETUP LOGIC
# ==========================================
def set_wifi(ssid, password):
    try:
        print(f"Attempting to connect to SSID: {ssid}")
        
        # 1. First, delete any existing saved profile with this name to avoid the key-mgmt caching bug 
        subprocess.run(['sudo', 'nmcli', 'connection', 'delete', ssid], capture_output=True)
        
        # 2. Try normal connection
        command = ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid, 'password', password]
        result = subprocess.run(command, capture_output=True, text=True)
        
        # 3. If that failed because of the key-mgmt bug, force standard WPA2 security manually
        if "key-mgmt" in result.stderr:
            print("Detected key-mgmt bug. Forcing WPA2-PSK connection...")
            fallback_cmd = ['sudo', 'nmcli', 'device', 'wifi', 'connect', ssid, 'password', password, 'wifi-sec.key-mgmt', 'wpa-psk']
            result_fallback = subprocess.run(fallback_cmd, capture_output=True, text=True)
            if result_fallback.returncode == 0:
                return f"SUCCESS: Connected to {ssid} (Fallback mode)!"
            else:
                return f"FAILED: {result_fallback.stderr.strip()}"
                
        if result.returncode == 0:
            return f"SUCCESS: Connected to {ssid}!"
        else:
            return f"FAILED: {result.stderr.strip()}"
    except Exception as e:
        return f"ERROR: {str(e)}"

def scan_wifi():
    try:
        command = ['sudo', 'nmcli', '-t', '-f', 'SSID', 'dev', 'wifi']
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            raw_names = [name.strip() for name in result.stdout.split('\n') if name.strip()]
            unique_names = sorted(list(set(raw_names)))
            if len(unique_names) == 0:
                return "No networks found... (Check if hotspot is 5GHz instead of 2.4GHz!)"
            response = "\r\n--- NEARBY WIFI NETWORKS ---\r\n"
            for i, name in enumerate(unique_names, 1):
                response += f"{i}. {name}\r\n"
            response += "----------------------------"
            return response
        else:
            return f"SCAN FAILED: {result.stderr.strip()}"
    except Exception as e:
        return f"SCAN ERROR: {str(e)}"

def auto_trust_devices():
    print("Security Agent loaded: Auto-Accepting and Auto-Trusting all paired phones...")
    
    # 1. Spawn a permanent background Bluetooth controller
    # This acts as a robotic "human" that automatically clicks "Yes/Accept" to all pairing PIN requests
    # so you NEVER have to touch the Raspberry Pi Keyboard or Mouse!
    try:
        btctl = subprocess.Popen(['bluetoothctl'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        
        # Override the Desktop GUI and tell Linux to forcefully auto-accept passwords
        btctl.stdin.write("power on\n")
        btctl.stdin.write("agent NoInputNoOutput\n")
        btctl.stdin.write("default-agent\n")
        btctl.stdin.write("discoverable on\n")
        btctl.stdin.write("pairable on\n")
        btctl.stdin.flush()
    except Exception as e:
        print("Agent spawn failed:", e)

    while True:
        try:
            # Look at all devices successfully paired to the Raspberry Pi
            output = subprocess.check_output(['bluetoothctl', 'paired-devices'], text=True)
            for line in output.split('\n'):
                if line.startswith('Device '):
                    mac = line.split(" ")[1]
                    # Automatically whitelist/trust them instantly!
                    os.system(f"sudo bluetoothctl trust {mac} >/dev/null 2>&1")
        except:
            pass
        time.sleep(5)

def start_bluetooth_server():
    try:
        # 🚨 CRITICAL FIX for Automated Headless reboots:
        # Tell Linux to re-broadcast the "Serial Profile" UUID so the Phone app can find the doorway!
        os.system("sudo sdptool add SP >/dev/null 2>&1")
        time.sleep(1)

        server_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        port = 1
        server_sock.bind((socket.BDADDR_ANY, port))
        server_sock.listen(1)

        print(f"Bluetooth Serial Server Output started.")
        print(f"Waiting for connection on RFCOMM channel {port} from Serial Terminal App...")

        while True:
            try:
                client_sock, client_info = server_sock.accept()
                print(f"✅ Accepted connection from Phone Address: {client_info}")
                
                welcome_msg = "\r\n Inhydro Cyclic \r\nCommands:\r\n1. WIFI:Network:Password\r\n2. SCAN - (Find nearby networks)\r\n"
                client_sock.send(welcome_msg.encode('utf-8'))

                while True:
                    data = client_sock.recv(1024)
                    if not data:
                        break
                    
                    received_text = data.decode('utf-8').strip()
                    print(f"Received from Phone: {received_text}")

                    if received_text.startswith("WIFI:"):
                        parts = received_text.split(":")
                        if len(parts) >= 3:
                            ssid = parts[1]
                            password = ":".join(parts[2:])
                            client_sock.send(f"\r\nAttempting to connect to {ssid}...\r\n".encode('utf-8'))
                            response = set_wifi(ssid, password)
                            client_sock.send(f"{response}\r\n".encode('utf-8'))
                        else:
                            client_sock.send("\r\nERROR: Invalid format. Must be WIFI:SSID:PASSWORD\r\n".encode('utf-8'))
                    
                    elif received_text.startswith("ID:"):
                        new_id = received_text.split(":")[1].strip()
                        if new_id:
                            try:
                                with open(ID_FILE, "w") as f:
                                    f.write(new_id)
                                client_sock.send(f"\r\nSUCCESS: DEVICE ID set to {new_id}!\r\nSystem will RESTART to apply changes.\r\n".encode('utf-8'))
                                root.after(2000, restart_program)
                            except Exception as e:
                                client_sock.send(f"\r\nERROR: {str(e)}\r\n".encode('utf-8'))
                        else:
                            client_sock.send("\r\nERROR: Invalid format. Must be ID:DEVICE_NAME\r\n".encode('utf-8'))
                    
                    elif received_text.upper() == "SCAN":
                        client_sock.send("\r\nScanning for nearby WiFi networks... Please wait\r\n".encode('utf-8'))
                        networks_list = scan_wifi()
                        client_sock.send((networks_list + "\r\n").encode('utf-8'))
                        
                    elif received_text.upper() == "PING":
                        client_sock.send("\r\nPONG - System is Alive!\r\n".encode('utf-8'))
                    else:
                        client_sock.send(f"\r\nUnknown command: {received_text}\r\n".encode('utf-8'))

            except Exception as e:
                print(f"Connection lost or error: {e}")
            finally:
                if 'client_sock' in locals():
                    client_sock.close()
                print("Client disconnected. Waiting for a new connection...")
    except Exception as e:
        print(f"Bluetooth Setup Failed: {e}")


# MODBUS (minimalmodbus) 
instrument = minimalmodbus.Instrument(SERIAL_PORT, DEVICE_ID)
instrument.serial.baudrate = 9600
instrument.serial.bytesize = 8
instrument.serial.parity   = serial.PARITY_NONE
instrument.serial.stopbits = 1
instrument.serial.timeout  = 1
instrument.mode = minimalmodbus.MODE_RTU

# MQTT SETUP (ThingSpeak - Telemetry Out)
mqtt_client = None
MQTT_TOPIC = ""

def init_mqtt_client():
    global mqtt_client, MQTT_TOPIC
    
    if mqtt_client is not None:
        try:
            mqtt_client.disconnect()
            mqtt_client.loop_stop()
        except:
            pass

    client_id = str(setpoints.get("CLIENT ID", ""))
    username = str(setpoints.get("USERNAME", ""))
    password = str(setpoints.get("PASSWORD", ""))
    
    if not (client_id and username and password):
        print("⚠️ ThingSpeak MQTT credentials not set. Waiting for web dashboard configuration...")
        return

    try:
        port = int(setpoints.get("PORT", 1883))
    except (ValueError, TypeError):
        port = 1883
    
    channel_id = str(setpoints.get("CHANNEL ID", ""))
    if not channel_id:
        print("⚠️ ThingSpeak Channel ID not set. Waiting for web dashboard configuration...")
        return

    MQTT_TOPIC = f"channels/{channel_id}/publish"
    
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
    mqtt_client.username_pw_set(username, password)
    try:
        mqtt_client.connect(MQTT_BROKER, port, 60)
        mqtt_client.loop_start()
        print("Connected to ThingSpeak MQTT Cloud")
    except:
        print("MQTT Cloud Offline")

init_mqtt_client()

# CONTROL MQTT SETUP (HiveMQ Public Broker - Remote Control In)
CONTROL_BROKER = "broker.hivemq.com"
CONTROL_PORT = 1883
CONTROL_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/update"
CURRENT_SETP_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/current"
CONTROL_SYNC_TOPIC = f"inhydro/{DEVICE_NAME}/setpoints/request_sync"

def on_control_message(client, userdata, msg):
    try:
        global setpoints
        
        if msg.topic == CONTROL_SYNC_TOPIC:
            control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
            return
            
        new_data = json.loads(msg.payload.decode())
        
        # Map camelCase from dashboard to Internal Keys
        key_map = {
            "clientId": "CLIENT ID",
            "username": "USERNAME",
            "password": "PASSWORD",
            "channelId": "CHANNEL ID",
            "port": "PORT"
        }
        
        new_setpoints = {}
        for k, v in new_data.items():
            internal_key = key_map.get(k, k) # Use mapping or original key
            new_setpoints[internal_key] = v

        ts_changed = False
        for key in ["PORT", "CLIENT ID", "USERNAME", "PASSWORD", "CHANNEL ID"]:
            if key in new_setpoints and str(new_setpoints[key]) != str(setpoints.get(key)):
                ts_changed = True

        setpoints.update(new_setpoints)
        save_setpoints()
        
        if ts_changed:
            print(f"ThingSpeak settings for {DEVICE_NAME} changed. Reconnecting...")
            init_mqtt_client()
            
        # Safely update UI from the MAIN thread instead of the background thread!
        # This prevents Tkinter from crashing the entire app (making it vanish)
        def update_ui():
            for key in new_setpoints:
                if 'labels' in globals() and key in labels:
                    labels[key].config(text=str(setpoints[key]))
        
        if 'root' in globals():
            try: root.after(0, update_ui)
            except: pass
                
        print("✅ Setpoints remotely updated via Cloud MQTT!")
    except Exception as e:
        print("MQTT Update Error:", e)

control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "Inhydro_Device_Client_001")
control_client.on_message = on_control_message
try:
    control_client.connect(CONTROL_BROKER, CONTROL_PORT, 60)
    control_client.subscribe(CONTROL_TOPIC)
    control_client.subscribe(CONTROL_SYNC_TOPIC)
    control_client.loop_start()
    print("Connected to Control MQTT Broker")
    
    # Push initial values right away on connect
    control_client.publish(CURRENT_SETP_TOPIC, json.dumps(setpoints), retain=True)
except:
    print("Control MQTT Offline")

# SENSOR READ (Registers 1-4) 
def read_sensor():
    try:
        moist = instrument.read_register(0x0012, 1)   # 0.1 %
        temp = instrument.read_register(0x0013, 1, signed=True)  # 0.1 °C
        ec = instrument.read_register(0x0015, 0)  # us/cm
        ph = instrument.read_register(0x0006, 2)  # 0.01 pH

        return {
            "temp": temp,
            "moist": moist,
            "ec": ec,
            "ph": ph,
        }
    except Exception as e:
        print("Sensor error:", e)
        return None

# CONTROL LOGIC 
def control(data):
    global ec_active, ph_active, last_ec, last_ph
    now = time.time()
    warnings = []

    ec = data["ec"]
    ph = data["ph"]

    # EC CONTROL
    if not ec_active and ec < setpoints["EC MIN"]:
        ec_active = True
        relay_ec1.on()
        relay_ec2.on()
        last_ec = now
        warnings.append("⚠ EC LOW  DOSING")

    if ec_active:
        if ec >= setpoints["EC MAX"]:
            relay_ec1.off()
            relay_ec2.off()
            ec_active = False
        elif now - last_ec >= 10:
            relay_ec1.on(); relay_ec2.on()
            last_ec = now

    # PH CONTROL
    if not ph_active and ph > setpoints["PH HIGH"]:
        ph_active = True
        relay_ph.on()
        last_ph = now
        warnings.append("⚠ pH HIGH  CORRECTING")

    if ph_active:
        if ph <= setpoints["PH LOW"]:
            relay_ph.off()
            ph_active = False
        elif now - last_ph >= 10:
            relay_ph.on()
            last_ph = now

    return warnings

# SAFETY & RESTART 
def manual_stop():
    relay_ec1.off(); relay_ec2.off(); relay_ph.off()
    global ec_active, ph_active, timer_cycle_state
    ec_active = False; ph_active = False
    for i in range(3):
        turn_relay_off(i)
        timer_cycle_state[i] = "OFF"
    lbl_warn.config(text="🛑 MANUAL STOP")

def restart_program():
    manual_stop()
    try: instrument.serial.close()
    except: pass
    os.execl(sys.executable, sys.executable, *sys.argv)

# UI SETUP 
root = tk.Tk()
root.attributes("-fullscreen", True)
root.configure(bg="white")
root.bind("<Escape>", lambda e: root.destroy())

# LOGO (TOP RIGHT) 
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
try:
    logo_img_raw = Image.open(LOGO_PATH)
    logo_img_raw = logo_img_raw.resize((150,95), Image.LANCZOS)
    logo_img = ImageTk.PhotoImage(logo_img_raw)
    lbl_logo = tk.Label(root, image=logo_img, bg="white")
    lbl_logo.image = logo_img   
    lbl_logo.place(relx=0.98, y=10, anchor="ne")
except Exception as e:
    print("Logo load error:", e)

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

show(frame_main)

# DASHBOARD 
dash_container = tk.Frame(frame_main, bg="white")
dash_container.pack(pady=20, fill="both", expand=True)

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

lbl_timer_title = tk.Label(right_frame, font=("Arial", 18, "bold"), fg="#1565c0", bg="white")
lbl_timer_title.pack(pady=10)
lbl_timer_title.config(text="CYCLIC TIMERS")

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

def update():
    global mqtt_timer
    data = read_sensor()
    if data:
        warn = control(data)
        lbl_data.config(text=f"""
Temp : {data['temp']} °C
EC   : {data['ec']}  us/cm
pH   : {data['ph']}
""")
        lbl_warn.config(text="\n".join(warn))
        lbl_relay_left.config(text=relay_status_left())
        lbl_timer_right.config(text=timer_status_right())

        # Cloud Sync (Every 2s)
        mqtt_timer += 2
        if mqtt_timer >= 2:
            try:
                payload = f"field1={data['temp']}&field2={data['moist']}&field3={data['ph']}&field4={data['ec']}"
                if mqtt_client:
                    mqtt_client.publish(MQTT_TOPIC, payload)
            except: pass
            mqtt_timer = 0
    else:
        lbl_data.config(text="⚠ SENSOR ERROR")
        lbl_warn.config(text="")
        lbl_relay_left.config(text="")
        lbl_timer_right.config(text=timer_status_right())
        
    run_cycle()
    root.after(2000, update)

# MAIN FOOTER 
footer = tk.Frame(frame_main, bg="#eeeeee", height=60)
footer.pack(side="bottom", fill="x")
footer.pack_propagate(False)

tk.Button(footer, text="SETPOINTS", font=med, width=12,
          command=lambda: show(frame_set)).pack(side="left", padx=20)

tk.Button(footer, text="STOP", font=med, width=12,
          command=manual_stop).pack(side="left", padx=20)

tk.Button(footer, text="RESTART", font=med, width=12,
          command=restart_program).pack(side="left", padx=20)

tk.Button(footer, text="EXIT", font=med, width=12,
          command=root.destroy).pack(side="right", padx=20)

# SETPOINT SCREEN 
tk.Label(frame_set, text="SETPOINTS",
         font=big, fg="#1565c0", bg="white").pack(pady=10)

labels = {}
selected_key = None
entered_value = ""

def open_keypad(key):
    global selected_key, entered_value
    selected_key = key
    entered_value = ""
    lbl_display.config(text="")
    lbl_title.config(text=f"Set {key}")
    
    # Clear previous buttons
    for widget in button_frame.winfo_children():
        widget.destroy()
    for widget in action_frame.winfo_children():
        widget.destroy()

    if key.endswith("Name"):
        build_qwerty_keyboard()
    else:
        build_numeric_keypad()
    
    # Hide the settings map to fit the keypad on screen
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
        keypad_frame.pack_forget()
        settings_container.pack(pady=5)
    except:
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

    tk.Label(cell, text=key, font=("Arial", 12),
             fg="#333333", bg="white", width=14).pack(side="left")

    labels[key] = tk.Label(cell,
                           text=str(setpoints[key]),
                           font=("Arial", 12, "bold"),
                           fg="#ef6c00",
                           bg="white",
                           width=6)
    labels[key].pack(side="left", padx=5)

    tk.Button(cell, text="EDIT",
              font=("Arial", 10),
              command=lambda k=key: open_keypad(k)
              ).pack(side="left")

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

lbl_title = tk.Label(keypad_frame, font=med,
                     fg="#1565c0", bg="white")
lbl_title.pack()

lbl_display = tk.Label(keypad_frame,
                       font=("Arial", 18, "bold"),
                       fg="#2e7d32", bg="white")
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
        tk.Button(button_frame,
                  text=text,
                  font=med,
                  width=4,
                  height=1,
                  command=cmd
                  ).grid(row=r, column=c, padx=3, pady=3)

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
footer_set = tk.Frame(frame_set, bg="#eeeeee", height=50)
footer_set.pack(side="bottom", fill="x")
footer_set.pack_propagate(False)

tk.Button(footer_set,
          text="SAVE & EXIT",
          font=med,
          bg="#1e90ff",
          fg="white",
          width=15,
          command=lambda: (save_setpoints(), show(frame_main))
          ).pack(pady=5)

# START LOOP 
def main_loop():
    try:
        # 1. Start the Trust Agent to auto-handle pairing PINs
        trust_thread = threading.Thread(target=auto_trust_devices, daemon=True)
        trust_thread.start()
        
        # 2. Start the Bluetooth Setup Server
        bt_thread = threading.Thread(target=start_bluetooth_server, daemon=True)
        bt_thread.start()
        print("✅ Background Bluetooth Automated Setup Agent started")
    except Exception as e:
        print(f"Failed to start Bluetooth thread: {e}")

    update()
    root.mainloop()

if __name__ == "__main__":
    main_loop()
