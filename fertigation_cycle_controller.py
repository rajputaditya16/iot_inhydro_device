import os
import sys
import time
import json
import datetime
import threading
import queue
import tkinter as tk
from tkinter import font
from typing import Optional, Tuple, Dict, Any

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import minimalmodbus
    import serial
    MODBUS_AVAILABLE = True
except ImportError:
    MODBUS_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETPOINT_FILE = os.path.join(BASE_DIR, "config_fertigation.json")
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")

# Hardware Serial By-Path Ports
SERIAL_PORT_WATER   = "/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.0-port0"
SERIAL_PORT_EC      = SERIAL_PORT_WATER
SERIAL_PORT_PH      = SERIAL_PORT_WATER

SERIAL_PORT_WATER_1 = SERIAL_PORT_WATER
SERIAL_PORT_EC1     = SERIAL_PORT_WATER_1
SERIAL_PORT_PH1     = SERIAL_PORT_WATER_1

SERIAL_PORT_WATER_2 = SERIAL_PORT_WATER
SERIAL_PORT_EC2     = SERIAL_PORT_WATER_2
SERIAL_PORT_PH2     = SERIAL_PORT_WATER_2

DEVICE_ID_EC1 = 31
DEVICE_ID_PH1 = 32
DEVICE_ID_EC2 = 33
DEVICE_ID_PH2 = 34

SERIAL_PORT_RELAY = "/dev/serial/by-path/usb-0:1:2:1:0-port0"
RELAY_SLAVE_ID    = 1

DEFAULT_SETPOINTS = {
    "EC Setpoint": 1.6,
    "EC Tolerance": 0.1,
    "Channel Valve 1 (Normal)": 13,
    "Channel Valve 2 (Irrigation)": 10,
    "Channel Solution Dosing": 0,
    "Channel Mixing Pump": 8,
    "Valve1 Name": "Normal Valve (Valve 1)",
    "Valve1 Start": "00:00",
    "Valve1 Stop": "23:59",
    "Valve1 ON Min": 5.0,
    "Valve1 OFF Min": 15.0,
    "Irrigation Name": "Fertigation Delivery (Valve 2)",
    "Irrigation Start": "00:00",
    "Irrigation Stop": "23:59",
    "Irrigation ON Min": 5.0,
    "Irrigation OFF Min": 15.0,
    "Valve2 Run Sec": 45.0,
    "Dosing Pulse Sec": 3.0,
    "Mixing Duration Sec": 15.0,
    "Sensor Stabilize Sec": 5.0,
    "Max Mix Cycles": 6
}

setpoints = dict(DEFAULT_SETPOINTS)

def load_setpoints():
    global setpoints
    if os.path.exists(SETPOINT_FILE):
        try:
            with open(SETPOINT_FILE, "r") as f:
                setpoints.update(json.load(f))
        except Exception:
            pass
    else:
        save_setpoints()

def save_setpoints():
    try:
        with open(SETPOINT_FILE, "w") as f:
            json.dump(setpoints, f, indent=4)
    except Exception:
        pass

load_setpoints()

# Relay Command Queue & Worker
relay_cmd_queue = queue.Queue()

def relay_worker_loop():
    while True:
        try:
            cmd = relay_cmd_queue.get()
            if cmd is None:
                break
            channel, state = cmd
            inst = None
            try:
                if MODBUS_AVAILABLE and os.path.exists(SERIAL_PORT_RELAY) and not os.path.isdir(SERIAL_PORT_RELAY):
                    inst = minimalmodbus.Instrument(SERIAL_PORT_RELAY, RELAY_SLAVE_ID)
                    inst.serial.baudrate = 9600
                    inst.serial.timeout = 0.2
                    inst.mode = minimalmodbus.MODE_RTU
                    inst.clear_buffers_before_each_transaction = True
                    inst.write_bit(channel, 1 if state else 0, functioncode=5)
            except Exception:
                pass
            finally:
                if inst and hasattr(inst, "serial") and inst.serial and getattr(inst.serial, "is_open", False):
                    try:
                        inst.serial.close()
                    except Exception:
                        pass
            relay_cmd_queue.task_done()
        except Exception:
            pass

threading.Thread(target=relay_worker_loop, daemon=True).start()

def send_modbus_relay_cmd(channel: int, state: bool) -> bool:
    relay_cmd_queue.put((channel, state))
    return True

class ModbusRelay:
    def __init__(self, channel: int, name: str = ""):
        self.channel = channel
        self.name = name
        self.is_active = False

    def on(self):
        if not self.is_active:
            self.is_active = True
            send_modbus_relay_cmd(self.channel, True)

    def off(self):
        if self.is_active:
            self.is_active = False
            send_modbus_relay_cmd(self.channel, False)

ch_valve1   = int(setpoints.get("Channel Valve 1 (Normal)", 13))
ch_valve2   = int(setpoints.get("Channel Valve 2 (Irrigation)", 10))
ch_sol_dose = int(setpoints.get("Channel Solution Dosing", 0))
ch_mixing   = int(setpoints.get("Channel Mixing Pump", 8))

relay_valve1   = ModbusRelay(ch_valve1, "Normal Valve (Valve 1)")
relay_valve2   = ModbusRelay(ch_valve2, "Fertigation Delivery (Valve 2)")
relay_solution = ModbusRelay(ch_sol_dose, "Solution Dosing Pump")
relay_mixing   = ModbusRelay(ch_mixing, "Mixing Pump")

relay_solenoid   = relay_valve1
relay_irrigation = relay_valve2

ALL_RELAYS = [relay_valve1, relay_valve2, relay_solution, relay_mixing]

def all_relays_off():
    for r in ALL_RELAYS:
        try:
            r.off()
        except Exception:
            pass

all_relays_off()

# Cyclic Timer Engine
timer_state: Dict[str, Dict[str, Any]] = {
    "Valve1": {"state": "OFF", "last": 0.0},
    "Irrigation": {"state": "OFF", "last": 0.0}
}

def process_generic_cyclic_timer(prefix: str, relay_obj: ModbusRelay):
    t_start_str = str(setpoints.get(f"{prefix} Start", "00:00"))
    t_stop_str  = str(setpoints.get(f"{prefix} Stop", "23:59"))
    try:
        on_min = float(setpoints.get(f"{prefix} ON Min", 5))
    except Exception:
        on_min = 5.0
    try:
        off_min = float(setpoints.get(f"{prefix} OFF Min", 15))
    except Exception:
        off_min = 15.0

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

# Modbus Sensor Readers
def read_ec_meter(port: str, slave_id: int) -> Optional[Dict[str, Any]]:
    if not MODBUS_AVAILABLE or not os.path.exists(port):
        return None
    inst = None
    try:
        inst = minimalmodbus.Instrument(port, slave_id)
        inst.serial.baudrate = 9600
        inst.serial.timeout = 0.3
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True
        for fc in [3, 4]:
            try:
                data = inst.read_registers(1, 3, functioncode=fc)
                raw_ec = data[2] if len(data) >= 3 else inst.read_register(3, 0, functioncode=fc)
                return {"ec": round(raw_ec / 1000.0, 3), "raw_ec": raw_ec}
            except Exception:
                pass
    except Exception:
        pass
    finally:
        if inst and hasattr(inst, "serial") and inst.serial and getattr(inst.serial, "is_open", False):
            try:
                inst.serial.close()
            except Exception:
                pass
    return None

def read_ph_meter(port: str, slave_id: int) -> Optional[Dict[str, Any]]:
    if not MODBUS_AVAILABLE or not os.path.exists(port):
        return None
    inst = None
    try:
        inst = minimalmodbus.Instrument(port, slave_id)
        inst.serial.baudrate = 9600
        inst.serial.timeout = 0.3
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True
        for fc in [3, 4]:
            try:
                data = inst.read_registers(0, 3, functioncode=fc)
                return {"ph": round(data[2] / 100.0, 2)}
            except Exception:
                pass
    except Exception:
        pass
    finally:
        if inst and hasattr(inst, "serial") and inst.serial and getattr(inst.serial, "is_open", False):
            try:
                inst.serial.close()
            except Exception:
                pass
    return None

cached_stream_1: Optional[Dict[str, Any]] = None
cached_stream_2: Optional[Dict[str, Any]] = None

def sensor_polling_loop():
    global cached_stream_1, cached_stream_2
    while True:
        try:
            ec1 = read_ec_meter(SERIAL_PORT_WATER_1, DEVICE_ID_EC1)
            time.sleep(0.08)
            ph1 = read_ph_meter(SERIAL_PORT_WATER_1, DEVICE_ID_PH1)
            if ec1 or ph1:
                cached_stream_1 = {"ec": ec1["ec"] if ec1 else None, "ph": ph1["ph"] if ph1 else None}
            else:
                cached_stream_1 = None
        except Exception:
            cached_stream_1 = None

        time.sleep(0.08)

        try:
            ec2 = read_ec_meter(SERIAL_PORT_WATER_2, DEVICE_ID_EC2)
            time.sleep(0.08)
            ph2 = read_ph_meter(SERIAL_PORT_WATER_2, DEVICE_ID_PH2)
            if ec2 or ph2:
                cached_stream_2 = {"ec": ec2["ec"] if ec2 else None, "ph": ph2["ph"] if ph2 else None}
            else:
                cached_stream_2 = None
        except Exception:
            cached_stream_2 = None

        time.sleep(1.0)

threading.Thread(target=sensor_polling_loop, daemon=True).start()

def calculate_solution_dosing(ec1_val: float, target_sp: float) -> Tuple[float, float]:
    deficit = max(0.0, target_sp - ec1_val)
    base_pulse = float(setpoints.get("Dosing Pulse Sec", 3.0))
    if deficit <= 0:
        return 0.0, 0.0
    calc_pulse = round(base_pulse * (deficit / 0.5), 1)
    clamped_pulse = max(1.0, min(15.0, calc_pulse))
    return clamped_pulse, deficit

# Automation State Machine
fert_state = "IDLE"
fert_step_timer = 0
mix_attempt = 0
calculated_pulse_sec = 0.0
dosing_deficit_val = 0.0
gated_status_text = "VALVE 1 STANDBY"
warnings_list = []
system_paused = False

# GUI Setup
root = tk.Tk()
root.update()
root.attributes("-fullscreen", True)
root.configure(bg="#ffffff")
root.bind("<Escape>", lambda e: root.destroy())

FONT_BIG  = ("Arial", 14, "bold")
FONT_MED  = ("Arial", 11, "bold")
FONT_SML  = ("Arial", 10, "bold")
FONT_TINY = ("Arial", 9, "bold")

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

# Header Logo & Clock
try:
    if os.path.exists(LOGO_PATH) and PIL_AVAILABLE:
        logo_raw = Image.open(LOGO_PATH).resize((130, 85), Image.LANCZOS)
        logo_img = ImageTk.PhotoImage(logo_raw)
        lbl_logo = tk.Label(root, image=logo_img, bg="#ffffff")
        lbl_logo.image = logo_img
        lbl_logo.place(relx=0.98, y=6, anchor="ne")
    else:
        lbl_logo = tk.Label(root, text="INHYDRO", fg="#1565c0", bg="#ffffff", font=("Arial", 14, "bold"))
        lbl_logo.place(relx=0.98, y=6, anchor="ne")
except Exception:
    lbl_logo = tk.Label(root, text="INHYDRO", fg="#1565c0", bg="#ffffff", font=("Arial", 14, "bold"))
    lbl_logo.place(relx=0.98, y=6, anchor="ne")

lbl_clock = tk.Label(root, text="", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff", justify="left")
lbl_clock.place(x=10, y=8, anchor="nw")

tk.Label(frame_main, text=" FARM AUTOMATION - FERTIGATION CONTROLLER ", font=FONT_BIG, fg="#1565c0", bg="#ffffff").pack(pady=(4, 2))

# Footer Frame
footer_main = tk.Frame(frame_main, bg="#ffffff", height=45)
footer_main.pack(side="bottom", fill="x", pady=4)
footer_main.pack_propagate(False)

def manual_stop():
    global system_paused, fert_state, fert_step_timer, gated_status_text
    system_paused = True
    all_relays_off()
    for ts in timer_state.values():
        ts["state"] = "OFF"
        ts["last"] = 0.0
    fert_state = "IDLE"
    fert_step_timer = 0
    gated_status_text = "MANUAL STOP"

def manual_resume():
    global system_paused, fert_state, fert_step_timer, gated_status_text
    system_paused = False
    fert_state = "IDLE"
    fert_step_timer = 0
    gated_status_text = "RESUMED AUTOMATION"

def restart_program():
    manual_stop()
    os.execl(sys.executable, sys.executable, *sys.argv)

tk.Button(footer_main, text="SETPOINTS", font=FONT_MED, bg="#0284c7", fg="white", width=12, command=lambda: show(frame_set)).pack(side="left", padx=10, pady=3)
tk.Button(footer_main, text="STOP", font=FONT_MED, bg="#dc2626", fg="white", width=10, command=manual_stop).pack(side="left", padx=10, pady=3)
tk.Button(footer_main, text="RESUME", font=FONT_MED, bg="#2e7d32", fg="white", width=10, command=manual_resume).pack(side="left", padx=10, pady=3)
tk.Button(footer_main, text="RESTART", font=FONT_MED, bg="#64748b", fg="white", width=10, command=restart_program).pack(side="left", padx=10, pady=3)
tk.Button(footer_main, text="EXIT", font=FONT_MED, bg="#334155", fg="white", width=10, command=root.destroy).pack(side="right", padx=10, pady=3)

# 3-Column Content Grid
content_grid = tk.Frame(frame_main, bg="#ffffff")
content_grid.pack(expand=True, fill="both", padx=10, pady=(63, 6))

# COLUMN 1: SENSORS (INLET & TANK) & SETPOINT VERIFICATION
col_sensors = tk.Frame(content_grid, bg="#e0e0e0")
col_sensors.pack(side="left", fill="both", expand=True, padx=4)

tk.Label(col_sensors, text="INCOMING WATER (VALVE 1)", font=("Arial", 11, "bold"), fg="#1565c0", bg="#e0e0e0").pack(anchor="w", pady=(4, 1))

def create_sensor_row(parent, label_text, is_ec=False):
    f = tk.Frame(parent, bg="#e0e0e0")
    f.pack(fill="x", pady=1)
    tk.Label(f, text=label_text, font=FONT_SML, fg="#333333", bg="#e0e0e0", width=11, anchor="w").pack(side="left")
    val_w = 20 if is_ec else 14
    lbl_val = tk.Label(f, text="---", font=("Arial", 11, "bold"), fg="#0d47a1", bg="#e0e0e0", width=val_w, anchor="e")
    lbl_val.pack(side="right")
    return lbl_val

lbl_val_ec1 = create_sensor_row(col_sensors, "EC 1 (Inlet)", is_ec=True)
lbl_val_ph1 = create_sensor_row(col_sensors, "pH 1 (Inlet)")

tk.Frame(col_sensors, bg="black", height=1).pack(fill="x", pady=4)

tk.Label(col_sensors, text="TANK WATER (PRE-VALVE 2)", font=("Arial", 11, "bold"), fg="#1565c0", bg="#e0e0e0").pack(anchor="w", pady=(2, 1))

lbl_val_ec2 = create_sensor_row(col_sensors, "EC 2 (Tank)", is_ec=True)
lbl_val_ph2 = create_sensor_row(col_sensors, "pH 2 (Tank)")

tk.Frame(col_sensors, bg="black", height=1).pack(fill="x", pady=4)

tk.Label(col_sensors, text="TARGET SETPOINT & VERIFICATION", font=("Arial", 11, "bold"), fg="#1565c0", bg="#e0e0e0").pack(anchor="w", pady=(2, 1))

lbl_val_target = create_sensor_row(col_sensors, "EC Target")
lbl_val_gated  = create_sensor_row(col_sensors, "Valve 2 Gate")

tk.Frame(col_sensors, bg="black", height=1).pack(fill="x", pady=4)

warn_box_frame = tk.Frame(col_sensors, bg="#e0e0e0")
warn_box_frame.pack(pady=4, anchor="w", fill="x")

# Divider 1
tk.Frame(content_grid, bg="black", width=2).pack(side="left", fill="y", pady=4)

# COLUMN 2: RELAY STATUS & DOSING CALCULATION
col_relays = tk.Frame(content_grid, bg="#e0e0e0")
col_relays.pack(side="left", fill="both", expand=True, padx=4)

tk.Label(col_relays, text="RELAY STATUS", font=("Arial", 11, "bold"), fg="#1565c0", bg="#e0e0e0").pack(pady=(4, 2))

labels_relays = {}
relay_items = [
    ("Normal Valve (Valve 1)", "valve1"),
    ("Fertigation (Valve 2)",   "valve2"),
    ("Solution Dosing Pump",    "solution"),
    ("Solution Mixing Pump",    "mixing"),
]

for lbl_txt, r_key in relay_items:
    f = tk.Frame(col_relays, bg="#e0e0e0")
    f.pack(fill="x", pady=1)
    tk.Label(f, text=lbl_txt, font=("Arial", 9, "bold"), fg="#333333", bg="#e0e0e0", width=22, anchor="w").pack(side="left")
    lbl_st = tk.Label(f, text="OFF", font=("Arial", 9, "bold"), fg="#c62828", bg="#e0e0e0", anchor="e")
    lbl_st.pack(side="right")
    labels_relays[r_key] = lbl_st

tk.Frame(col_relays, bg="black", height=1).pack(fill="x", pady=6)

tk.Label(col_relays, text="STAGE 1 DOSING CALCULATION", font=("Arial", 11, "bold"), fg="#1565c0", bg="#e0e0e0").pack(anchor="w", pady=(2, 2))

def create_calc_row(parent, label_text):
    f = tk.Frame(parent, bg="#e0e0e0")
    f.pack(fill="x", pady=1)
    tk.Label(f, text=label_text, font=FONT_SML, fg="#333333", bg="#e0e0e0", width=18, anchor="w").pack(side="left")
    lbl_v = tk.Label(f, text="---", font=("Arial", 10, "bold"), fg="#0d47a1", bg="#e0e0e0", anchor="e")
    lbl_v.pack(side="right")
    return lbl_v

lbl_calc_deficit = create_calc_row(col_relays, "EC Deficit (SP-EC1)")
lbl_calc_pulse   = create_calc_row(col_relays, "Calculated Pulse")
lbl_calc_mix     = create_calc_row(col_relays, "Mixing Duration")
lbl_calc_attempt = create_calc_row(col_relays, "Dosing Attempt")

# Divider 2
tk.Frame(content_grid, bg="black", width=2).pack(side="left", fill="y", pady=4)

# COLUMN 3: CYCLIC TIMERS
col_timers = tk.Frame(content_grid, bg="#e0e0e0")
col_timers.pack(side="left", fill="both", expand=True, padx=4)

tk.Label(col_timers, text="CYCLIC TIMERS", font=("Arial", 11, "bold"), fg="#1565c0", bg="#e0e0e0").pack(pady=(4, 2))

# Card 1: Valve 1 Cyclic Timer
card_valve1_timer = tk.LabelFrame(col_timers, text="", bg="#ffffff", bd=1, relief="groove")
card_valve1_timer.pack(fill="x", pady=3, padx=2)

lbl_card_title1 = tk.Label(card_valve1_timer, text="NORMAL VALVE (VALVE 1)", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff")
lbl_card_title1.pack(pady=(3, 2))

labels_timer1_fields = {}
for sub_key, sub_name in [("status", "Status"), ("window", "Window"), ("cycle", "Cycle"), ("time_left", "Time Left")]:
    f = tk.Frame(card_valve1_timer, bg="#f1f5f9")
    f.pack(fill="x", pady=1, padx=4)
    tk.Label(f, text=sub_name, font=FONT_TINY, fg="#475569", bg="#f1f5f9", width=10, anchor="w").pack(side="left", padx=4, pady=1)
    lbl_v = tk.Label(f, text="---", font=FONT_TINY, fg="#0f172a", bg="#f1f5f9", anchor="e")
    lbl_v.pack(side="right", padx=4, pady=1)
    labels_timer1_fields[sub_key] = lbl_v

# Card 2: Valve 2 (Gated Delivery)
card_valve2_info = tk.LabelFrame(col_timers, text="", bg="#ffffff", bd=1, relief="groove")
card_valve2_info.pack(fill="x", pady=4, padx=2)

lbl_card_title2 = tk.Label(card_valve2_info, text="FERTIGATION VALVE (VALVE 2)", font=("Arial", 10, "bold"), fg="#1565c0", bg="#ffffff")
lbl_card_title2.pack(pady=(3, 2))

labels_timer2_fields = {}
for sub_key, sub_name, default_v in [
    ("status", "Status", "OFF"),
    ("condition", "Condition", "EC2 == Setpoint"),
    ("lock", "Gated Decision", "Locked (EC2 != SP)"),
    ("run_sec", "Delivery Run", f"{setpoints.get('Valve2 Run Sec', 45.0)}s")
]:
    f = tk.Frame(card_valve2_info, bg="#f1f5f9")
    f.pack(fill="x", pady=1, padx=4)
    tk.Label(f, text=sub_name, font=FONT_TINY, fg="#475569", bg="#f1f5f9", width=12, anchor="w").pack(side="left", padx=4, pady=1)
    lbl_v = tk.Label(f, text=default_v, font=FONT_TINY, fg="#0f172a", bg="#f1f5f9", anchor="e")
    lbl_v.pack(side="right", padx=4, pady=1)
    labels_timer2_fields[sub_key] = lbl_v

# Setpoints Screen
sp_labels = {}

tk.Label(frame_set, text=" FERTIGATION SETPOINTS ", font=FONT_BIG, fg="#1565c0", bg="#ffffff").pack(pady=(4, 2))

footer_set = tk.Frame(frame_set, bg="#ffffff", height=45)
footer_set.pack(side="bottom", fill="x", pady=4)
footer_set.pack_propagate(False)

tk.Button(footer_set, text="BACK", font=FONT_MED, bg="#64748b", fg="white", width=12, command=lambda: show(frame_main)).pack(side="left", padx=10, pady=3)
tk.Button(footer_set, text="SAVE", font=FONT_MED, bg="#0284c7", fg="white", width=12, command=save_setpoints).pack(side="left", padx=10, pady=3)

sp_content_frame = tk.Frame(frame_set, bg="#ffffff")
sp_content_frame.pack(expand=True, fill="both", padx=10, pady=6)

card_sp_ec = tk.LabelFrame(sp_content_frame, text=" EC SETPOINT & CALCULATION PARAMETERS ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
card_sp_ec.pack(fill="x", pady=4, padx=6)

def build_sp_row(parent, key_name, display_label):
    f = tk.Frame(parent, bg="#ffffff")
    f.pack(fill="x", pady=3, padx=8)
    tk.Label(f, text=display_label, font=("Arial", 10, "bold"), fg="#0f172a", bg="#ffffff", width=26, anchor="w").pack(side="left")
    val_lbl = tk.Label(f, text=str(setpoints.get(key_name, "")), font=("Arial", 10, "bold"), fg="#e65100", bg="#f8fafc", width=10, anchor="center", relief="sunken", bd=1)
    val_lbl.pack(side="left", padx=8)
    sp_labels[key_name] = val_lbl
    tk.Button(f, text="EDIT", font=("Arial", 9, "bold"), width=6, bg="#0284c7", fg="white", activebackground="#38bdf8", activeforeground="white", bd=1, relief="raised", command=lambda k=key_name: open_keypad_sp(k)).pack(side="right", padx=4)

build_sp_row(card_sp_ec, "EC Setpoint", "Target EC Setpoint (mS/cm):")
build_sp_row(card_sp_ec, "EC Tolerance", "EC Tolerance (± mS/cm):")
build_sp_row(card_sp_ec, "Dosing Pulse Sec", "Base Dosing Pulse (s / 0.5 EC):")
build_sp_row(card_sp_ec, "Mixing Duration Sec", "Mixing Pump Duration (s):")
build_sp_row(card_sp_ec, "Sensor Stabilize Sec", "Sensor Stabilize Duration (s):")
build_sp_row(card_sp_ec, "Valve2 Run Sec", "Valve 2 Irrigation Run (s):")
build_sp_row(card_sp_ec, "Max Mix Cycles", "Max Mixing Retry Cycles:")

card_sp_timer = tk.LabelFrame(sp_content_frame, text=" VALVE 1 CYCLIC TIMER SETTINGS ", font=("Arial", 11, "bold"), fg="#1565c0", bg="#ffffff", bd=2, relief="groove")
card_sp_timer.pack(fill="x", pady=4, padx=6)

build_sp_row(card_sp_timer, "Valve1 Start", "Start Time (HH:MM):")
build_sp_row(card_sp_timer, "Valve1 Stop", "Stop Time (HH:MM):")
build_sp_row(card_sp_timer, "Valve1 ON Min", "Valve 1 ON Minutes:")
build_sp_row(card_sp_timer, "Valve1 OFF Min", "Valve 1 OFF Minutes:")

sp_selected_key = ""
sp_entered_value = ""

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
    pop.attributes("-fullscreen", True)
    pop.focus_force()

    tk.Label(pop, text=f"ENTER VALUE FOR: {key.upper()}", font=FONT_BIG, fg="#1565c0", bg="#ffffff").pack(pady=(15, 6))

    lbl_disp = tk.Label(pop, text=str(setpoints.get(key, "")), font=("Arial", 22, "bold"), fg="#0d47a1", bg="#f1f5f9", width=18, relief="sunken", bd=2, pady=8)
    lbl_disp.pack(pady=8)

    def kp_click(ch):
        global sp_entered_value
        sp_entered_value += str(ch)
        lbl_disp.config(text=sp_entered_value)

    def kp_back():
        global sp_entered_value
        sp_entered_value = sp_entered_value[:-1]
        lbl_disp.config(text=sp_entered_value if sp_entered_value else "0")

    def kp_clear():
        global sp_entered_value
        sp_entered_value = ""
        lbl_disp.config(text="0")

    def kp_confirm():
        global sp_entered_value
        if sp_entered_value.strip():
            val = sp_entered_value.strip()
            try:
                if "." in val:
                    val = float(val)
                elif ":" not in val:
                    val = float(val) if "Min" in sp_selected_key or "Sec" in sp_selected_key else int(val)
            except Exception:
                pass
            setpoints[sp_selected_key] = val
            save_setpoints()
            if sp_selected_key in sp_labels:
                sp_labels[sp_selected_key].config(text=str(val))
        pop.destroy()

    kp_frame = tk.Frame(pop, bg="#ffffff")
    kp_frame.pack(pady=8)

    btn_layout = [
        ['1', '2', '3'],
        ['4', '5', '6'],
        ['7', '8', '9'],
        ['.', '0', ':']
    ]

    for row in btn_layout:
        r_f = tk.Frame(kp_frame, bg="#ffffff")
        r_f.pack(pady=2)
        for char in row:
            tk.Button(r_f, text=char, font=("Arial", 16, "bold"), width=7, height=2, bg="#f1f5f9", fg="#0f172a", command=lambda c=char: kp_click(c)).pack(side="left", padx=4)

    act_frame = tk.Frame(pop, bg="#ffffff")
    act_frame.pack(pady=10)

    tk.Button(act_frame, text="DEL", font=("Arial", 12, "bold"), bg="#f97316", fg="white", width=9, pady=6, command=kp_back).pack(side="left", padx=6)
    tk.Button(act_frame, text="CLR", font=("Arial", 12, "bold"), bg="#dc2626", fg="white", width=9, pady=6, command=kp_clear).pack(side="left", padx=6)
    tk.Button(act_frame, text="CONFIRM", font=("Arial", 12, "bold"), bg="#0284c7", fg="white", width=11, pady=6, command=kp_confirm).pack(side="left", padx=6)
    tk.Button(act_frame, text="CANCEL", font=("Arial", 12, "bold"), bg="#64748b", fg="white", width=9, pady=6, command=pop.destroy).pack(side="left", padx=6)

# Main 1000ms Automation Loop
def update():
    global fert_state, fert_step_timer, mix_attempt, calculated_pulse_sec, dosing_deficit_val, gated_status_text, warnings_list

    # 1. Header Clock
    now_dt = datetime.datetime.now()
    lbl_clock.config(text=now_dt.strftime("%A, %d %b %Y\n%I:%M:%S %p"))

    # 2. Update Sensor Pair 1 (Inlet / Valve 1)
    if cached_stream_1:
        ec1 = cached_stream_1.get("ec")
        ph1 = cached_stream_1.get("ph")
        if ec1 is not None:
            tds1 = int(ec1 * 500)
            lbl_val_ec1.config(text=f"{ec1:.3f} mS/cm ({tds1} ppm)", fg="#0d47a1")
        else:
            lbl_val_ec1.config(text="ERROR", fg="#c62828")

        if ph1 is not None:
            lbl_val_ph1.config(text=f"{ph1:.2f}", fg="#0d47a1")
        else:
            lbl_val_ph1.config(text="ERROR", fg="#c62828")
    else:
        lbl_val_ec1.config(text="ERROR", fg="#c62828")
        lbl_val_ph1.config(text="ERROR", fg="#c62828")

    # 3. Update Sensor Pair 2 (Tank / Pre-Valve 2)
    if cached_stream_2:
        ec2 = cached_stream_2.get("ec")
        ph2 = cached_stream_2.get("ph")
        if ec2 is not None:
            tds2 = int(ec2 * 500)
            lbl_val_ec2.config(text=f"{ec2:.3f} mS/cm ({tds2} ppm)", fg="#0d47a1")
        else:
            lbl_val_ec2.config(text="ERROR", fg="#c62828")

        if ph2 is not None:
            lbl_val_ph2.config(text=f"{ph2:.2f}", fg="#0d47a1")
        else:
            lbl_val_ph2.config(text="ERROR", fg="#c62828")
    else:
        if cached_stream_1 and cached_stream_1.get("ec") is not None:
            ec_fb = cached_stream_1["ec"]
            tds_fb = int(ec_fb * 500)
            lbl_val_ec2.config(text=f"{ec_fb:.3f} mS/cm (Pair 1)", fg="#0d47a1")
            lbl_val_ph2.config(text=f"{cached_stream_1.get('ph', 0.0):.2f}", fg="#0d47a1")
        else:
            lbl_val_ec2.config(text="OFFLINE", fg="#c62828")
            lbl_val_ph2.config(text="OFFLINE", fg="#c62828")

    # 4. Target Setpoint Label
    sp_val = float(setpoints.get("EC Setpoint", 1.6))
    tol_val = float(setpoints.get("EC Tolerance", 0.1))
    lbl_val_target.config(text=f"{sp_val:.2f} (±{tol_val:.2f})")

    # 5. Cyclic Timer (Valve 1)
    if not system_paused:
        process_generic_cyclic_timer("Valve1", relay_solenoid)

    ts1 = timer_state.get("Valve1", {})
    t1_st = ts1.get("state", "OFF")

    # 6. Fertigation Automation State Machine
    warnings = []

    if system_paused:
        fert_state = "IDLE"
        fert_step_timer = 0
        gated_status_text = "MANUAL STOP"
        warnings.append("MANUAL STOP ALL RELAYS")
    elif t1_st == "OFF":
        if fert_state != "IDLE":
            relay_valve2.off()
            relay_solution.off()
            relay_mixing.off()
            fert_state = "IDLE"
            fert_step_timer = 0
            mix_attempt = 0
        gated_status_text = "VALVE 1 STANDBY"
        warnings.append("VALVE 1 STANDBY - WAITING NEXT CYCLE")
    else:
        # Valve 1 is ON
        if fert_state == "IDLE":
            fert_state = "STAGE1_MEASURE"
            fert_step_timer = 0
            mix_attempt = 0
            gated_status_text = "READING INLET EC1"
            warnings.append("VALVE 1 ON: MEASURING INLET WATER")

        elif fert_state == "STAGE1_MEASURE":
            fert_step_timer += 1
            ec1_val = cached_stream_1.get("ec") if cached_stream_1 else None

            if ec1_val is None:
                gated_status_text = "SENSOR 1 OFFLINE"
                warnings.append("INLET SENSOR 1 OFFLINE - VALVE 2 LOCKED")
                relay_valve2.off()
            else:
                calc_pulse, deficit = calculate_solution_dosing(ec1_val, sp_val)
                calculated_pulse_sec = calc_pulse
                dosing_deficit_val = deficit

                if ec1_val < (sp_val - tol_val) and calculated_pulse_sec > 0:
                    mix_attempt = 1
                    fert_state = "DOSING"
                    fert_step_timer = 0
                    relay_solution.on()
                    gated_status_text = f"DOSING ({calculated_pulse_sec:.1f}s)"
                    warnings.append(f"EC1 LOW ({ec1_val:.2f} < {sp_val:.2f}) - DOSING {calculated_pulse_sec:.1f}s")
                else:
                    fert_state = "STAGE2_VERIFY"
                    fert_step_timer = 0
                    gated_status_text = "VERIFYING EC2"
                    warnings.append("EC1 OK - VERIFYING TANK EC2")

        elif fert_state == "DOSING":
            fert_step_timer += 1
            rem_d = max(0.0, calculated_pulse_sec - fert_step_timer)
            gated_status_text = f"DOSING ({rem_d:.0f}s left)"
            warnings.append(f"DOSING PUMP ACTIVE ({rem_d:.0f}s left)")

            if fert_step_timer >= calculated_pulse_sec:
                relay_solution.off()
                fert_state = "MIXING"
                fert_step_timer = 0
                relay_mixing.on()
                mix_dur = float(setpoints.get("Mixing Duration Sec", 15.0))
                gated_status_text = f"MIXING ({mix_dur:.0f}s)"
                warnings.append(f"MIXING PUMP ACTIVE ({mix_dur:.0f}s)")

        elif fert_state == "MIXING":
            fert_step_timer += 1
            mix_dur = float(setpoints.get("Mixing Duration Sec", 15.0))
            rem_m = max(0.0, mix_dur - fert_step_timer)
            gated_status_text = f"MIXING ({rem_m:.0f}s left)"
            warnings.append(f"MIXING PUMP ACTIVE ({rem_m:.0f}s left)")

            if fert_step_timer >= mix_dur:
                relay_mixing.off()
                fert_state = "STABILIZING"
                fert_step_timer = 0
                gated_status_text = "STABILIZING"
                warnings.append("STABILIZING TANK SENSORS...")

        elif fert_state == "STABILIZING":
            fert_step_timer += 1
            stab_dur = float(setpoints.get("Sensor Stabilize Sec", 5.0))
            gated_status_text = f"STABILIZING ({max(0.0, stab_dur - fert_step_timer):.0f}s)"
            warnings.append("STABILIZING TANK SENSORS...")

            if fert_step_timer >= stab_dur:
                fert_state = "STAGE2_VERIFY"
                fert_step_timer = 0

        elif fert_state == "STAGE2_VERIFY":
            max_mix = int(setpoints.get("Max Mix Cycles", 6))
            ec2_val = cached_stream_2.get("ec") if (cached_stream_2 and cached_stream_2.get("ec") is not None) else (cached_stream_1.get("ec") if cached_stream_1 else None)

            if ec2_val is None:
                gated_status_text = "SENSOR 2 OFFLINE"
                warnings.append("TANK SENSOR 2 OFFLINE - VALVE 2 LOCKED")
                relay_valve2.off()
            else:
                # STRICT GATED RULE:
                # If EC2 == Setpoint (within tolerance) -> OPEN VALVE 2
                # If EC2 != Setpoint (whether high or low) -> STRICTLY DO NOT OPEN VALVE 2
                if abs(ec2_val - sp_val) <= tol_val:
                    relay_valve2.on()
                    fert_state = "DELIVERING"
                    fert_step_timer = 0
                    gated_status_text = f"MATCHED ({ec2_val:.2f})"
                    warnings.append(f"EC2 MATCHED ({ec2_val:.2f} ≈ {sp_val:.2f}) - VALVE 2 OPEN")
                else:
                    relay_valve2.off()
                    if ec2_val < (sp_val - tol_val):
                        gated_status_text = f"EC2 LOW ({ec2_val:.2f})"
                        warnings.append(f"EC2 LOW ({ec2_val:.2f} < {sp_val:.2f}) - VALVE 2 LOCKED")

                        if mix_attempt < max_mix:
                            mix_attempt += 1
                            calc_pulse, deficit = calculate_solution_dosing(ec2_val, sp_val)
                            calculated_pulse_sec = calc_pulse
                            dosing_deficit_val = deficit
                            fert_state = "DOSING"
                            fert_step_timer = 0
                            relay_solution.on()
                        else:
                            fert_state = "LOCKED_MAX"
                            fert_step_timer = 0
                            warnings.append("MAX MIX ATTEMPTS REACHED - VALVE 2 LOCKED")
                    else:
                        gated_status_text = f"EC2 HIGH ({ec2_val:.2f})"
                        warnings.append(f"EC2 HIGH ({ec2_val:.2f} > {sp_val:.2f}) - VALVE 2 LOCKED")
                        fert_state = "LOCKED_HIGH"
                        fert_step_timer = 0

        elif fert_state == "DELIVERING":
            fert_step_timer += 1
            v2_limit = float(setpoints.get("Valve2 Run Sec", 45.0))
            rem_v2 = max(0.0, v2_limit - fert_step_timer)
            gated_status_text = f"IRRIGATING ({rem_v2:.0f}s)"
            warnings.append(f"VALVE 2 OPEN - IRRIGATING ({rem_v2:.0f}s left)")

            if fert_step_timer >= v2_limit:
                relay_valve2.off()
                fert_state = "CYCLE_COMPLETE"
                fert_step_timer = 0
                gated_status_text = "CYCLE COMPLETE"
                warnings.append("FERTIGATION DELIVERY COMPLETE")

        elif fert_state in ["CYCLE_COMPLETE", "LOCKED_MAX", "LOCKED_HIGH"]:
            relay_valve2.off()
            relay_solution.off()
            relay_mixing.off()
            if fert_state == "CYCLE_COMPLETE":
                gated_status_text = "CYCLE COMPLETE"
                warnings.append("CYCLE COMPLETE - WAITING NEXT CYCLE")
            elif fert_state == "LOCKED_HIGH":
                gated_status_text = "LOCKED (EC2 HIGH)"
                warnings.append("VALVE 2 LOCKED (EC2 HIGHER THAN SP)")
            else:
                gated_status_text = "LOCKED (MAX ATTEMPTS)"
                warnings.append("VALVE 2 LOCKED (MAX MIX ATTEMPTS)")

    # 7. Update Gated Label
    lbl_val_gated.config(text=gated_status_text)
    if "MATCHED" in gated_status_text or "IRRIGATING" in gated_status_text:
        lbl_val_gated.config(fg="#2e7d32")
    elif "LOW" in gated_status_text or "HIGH" in gated_status_text or "LOCKED" in gated_status_text or "OFFLINE" in gated_status_text or "STOP" in gated_status_text:
        lbl_val_gated.config(fg="#c62828")
    else:
        lbl_val_gated.config(fg="#0d47a1")

    # 8. Render Warning & Status Messages with Categorized Colors (from monit.py lines 2442-2479)
    if 'warn_box_frame' in globals():
        existing_labels = list(warn_box_frame.winfo_children())
        num_existing = len(existing_labels)
        num_needed = len(warnings)

        for i in range(min(num_existing, num_needed)):
            w_text = warnings[i]
            m = w_text.upper()
            if "ERR" in m or "LOCKED" in m or "OFFLINE" in m or "STOP" in m:
                fg_col = "#dc2626"
            elif "ON" in m or "ACTIVE" in m or "OPEN" in m or "MATCHED" in m or "COMPLETE" in m:
                fg_col = "#15803d"
            else:
                fg_col = "#92400e"

            lbl = existing_labels[i]
            if lbl.cget("text") != w_text or lbl.cget("fg") != fg_col:
                lbl.config(text=w_text, fg=fg_col)

        for i in range(num_existing, num_needed):
            w_text = warnings[i]
            m = w_text.upper()
            if "ERR" in m or "LOCKED" in m or "OFFLINE" in m or "STOP" in m:
                fg_col = "#dc2626"
            elif "ON" in m or "ACTIVE" in m or "OPEN" in m or "MATCHED" in m or "COMPLETE" in m:
                fg_col = "#15803d"
            else:
                fg_col = "#92400e"

            tk.Label(warn_box_frame, text=w_text, font=("Arial", 9, "bold"), fg=fg_col, bg="#e0e0e0", anchor="w", justify="left").pack(anchor="w")

        for i in range(num_needed, num_existing):
            existing_labels[i].destroy()

    # 9. Update Relay Status Indicators (Column 2)
    relay_states = {
        "valve1": relay_valve1.is_active,
        "valve2": relay_valve2.is_active,
        "solution": relay_solution.is_active,
        "mixing": relay_mixing.is_active
    }
    for r_key, is_on in relay_states.items():
        lbl = labels_relays.get(r_key)
        if lbl:
            lbl.config(text="ON" if is_on else "OFF", fg="#2e7d32" if is_on else "#c62828")

    # 10. Update Dosing Calculation Rows (Column 2)
    lbl_calc_deficit.config(text=f"{dosing_deficit_val:.2f} mS/cm")
    lbl_calc_pulse.config(text=f"{calculated_pulse_sec:.1f} s")
    lbl_calc_mix.config(text=f"{setpoints.get('Mixing Duration Sec', 15.0):.0f} s")
    lbl_calc_attempt.config(text=f"{mix_attempt} / {setpoints.get('Max Mix Cycles', 6)}")

    # 11. Update Cyclic Timer Card 1 (Valve 1)
    on_min = float(setpoints.get("Valve1 ON Min", 5.0))
    off_min = float(setpoints.get("Valve1 OFF Min", 15.0))
    run_sec = on_min * 60.0
    off_sec = off_min * 60.0
    now_sec = time.time()

    if labels_timer1_fields.get("status"):
        labels_timer1_fields["status"].config(text=t1_st, fg="#2e7d32" if t1_st == "ON" else "#c62828")

    if labels_timer1_fields.get("window"):
        labels_timer1_fields["window"].config(text=f"{setpoints.get('Valve1 Start', '00:00')} - {setpoints.get('Valve1 Stop', '23:59')}")

    if labels_timer1_fields.get("cycle"):
        labels_timer1_fields["cycle"].config(text=f"{on_min:.1f}m ON / {off_min:.1f}m OFF")

    if labels_timer1_fields.get("time_left"):
        last_t = ts1.get("last", now_sec)
        rem = max(0.0, (run_sec - (now_sec - last_t)) if t1_st == "ON" else (off_sec - (now_sec - last_t)))
        labels_timer1_fields["time_left"].config(text=f"{int(rem // 60):02d}:{int(rem % 60):02d} left")

    # 12. Update Valve 2 Card (Column 3)
    if labels_timer2_fields.get("status"):
        v2_on = relay_valve2.is_active
        labels_timer2_fields["status"].config(text="ON (IRRIGATING)" if v2_on else "OFF (CLOSED)", fg="#2e7d32" if v2_on else "#c62828")

    if labels_timer2_fields.get("lock"):
        labels_timer2_fields["lock"].config(
            text="PERMITTED (EC2 == SP)" if relay_valve2.is_active else "LOCKED (EC2 != SP)",
            fg="#2e7d32" if relay_valve2.is_active else "#c62828"
        )

    root.after(1000, update)

root.after(1000, update)

if __name__ == "__main__":
    try:
        root.mainloop()
    except KeyboardInterrupt:
        all_relays_off()
        root.destroy()
