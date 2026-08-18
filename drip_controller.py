#!/usr/bin/env python3
"""
===============================================================================
InHydro Drip Controller Automation Software
===============================================================================
Statement of Work (SOW) Implementation for Single Tank 4-Solenoid System.

UI Design Specifications:
  - Pure White Background (#FFFFFF) across all screens & cards.
  - Color Palette: Gray (#475569, #CBD5E1, #F1F5F9) & Blue (#0284C7, #0284C7, #0EA5E9).
  - Optimized for 7-Inch Display (800x480 Resolution).
  - Top Right Corner Logo (logo.png) on each page without text/button overlap.
  - Live Date & Time Clock in Bottom Right Corner.
  - Integrated Restart & Exit Buttons in Footer.

Valve Configuration:
  - Valve 1 (GPIO 5)  : Fogger Valve (Cyclic ON/OFF Timer)
  - Valve 2 (GPIO 6)  : Sprinkler Valve (Cyclic ON/OFF Timer)
  - Valve 3 (GPIO 22) : EC Dosing Valve (Hysteresis + Cyclic Timer)
  - Valve 4 (GPIO 23) : Spare / Reserved

Operating Modes:
  - AUTOMATIC MODE: System runs automatic cyclic timing & EC dosing control loops.
  - STOP MODE     : Master safety state. Forces all 4 valves OFF immediately.

Author: InHydro Engineering Team
Date: 2026-08-17
===============================================================================
"""

import os
import sys
import json
import time
import datetime
import threading
import tkinter as tk
from tkinter import messagebox, font, ttk
from PIL import Image, ImageTk

# Hardware Relay Abstraction (gpiozero with failover factories)
from gpiozero import OutputDevice, DigitalInputDevice, Device

try:
    from gpiozero.pins.lgpio import LGPIOFactory
    Device.pin_factory = LGPIOFactory()
    print("📌 GPIO Backend: LGPIOFactory (Raspberry Pi 5 / Rock 4)")
except Exception:
    try:
        from gpiozero.pins.pigpio import PiGPIOFactory
        Device.pin_factory = PiGPIOFactory()
        print("📌 GPIO Backend: PiGPIOFactory")
    except Exception:
        try:
            from gpiozero.pins.mock import MockFactory
            Device.pin_factory = MockFactory()
            print("⚠️ Physical GPIO unavailable. Using MockFactory.")
        except Exception as e:
            print("Notice: GPIO pin factory initialization fallback:", e)

# Modbus for EC Sensor
import minimalmodbus
import serial

# -----------------------------------------------------------------------------
# PATHS & CONSTANTS
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETPOINT_FILE = os.path.join(BASE_DIR, "drip_setpoints.json")
LOG_DIR = os.path.join(BASE_DIR, "local_logs")
LOG_FILE = os.path.join(LOG_DIR, "drip_telemetry.jsonl")
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")

# Fixed Serial Port & Modbus ID for EC Sensor
SERIAL_PORT_WATER = "/dev/serial/by-path/pci-0000:00:14.0-usb-0:1:1.0-port0"
DEVICE_ID_EC = 1

# Helper to load & scale logo cleanly
def load_logo_image(max_w=110, max_h=35):
    if os.path.exists(LOGO_PATH):
        try:
            img = Image.open(LOGO_PATH)
            img.thumbnail((max_w, max_h), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception as e:
            print(f"⚠️ Logo load error: {e}")
    return None

# -----------------------------------------------------------------------------
# HARDWARE INITIALIZATION (RELAYS & TANK LEVEL SENSOR)
# -----------------------------------------------------------------------------
relay_v1 = OutputDevice(5, active_high=False, initial_value=False)   # Fogger
relay_v2 = OutputDevice(6, active_high=False, initial_value=False)   # Sprinkler
relay_v3 = OutputDevice(22, active_high=False, initial_value=False)  # EC Control
relay_v4 = OutputDevice(23, active_high=False, initial_value=False)  # Spare

try:
    tank_level_sensor = DigitalInputDevice(17, pull_up=True)
except Exception:
    tank_level_sensor = None

def all_valves_off():
    """Immediately force all 4 valves to OFF state."""
    for r in [relay_v1, relay_v2, relay_v3, relay_v4]:
        try:
            r.off()
        except Exception:
            pass

all_valves_off()

# -----------------------------------------------------------------------------
# DEFAULT SETPOINTS
# -----------------------------------------------------------------------------
DEFAULT_SETPOINTS = {
    "FOGGER_ENABLE": True,
    "FOGGER_ON_SEC": 30,
    "FOGGER_OFF_MIN": 5,

    "SPRINKLER_ENABLE": True,
    "SPRINKLER_ON_MIN": 2,
    "SPRINKLER_OFF_MIN": 20,

    "EC_ENABLE": True,
    "EC_MIN": 1.5,        # mS/cm
    "EC_MAX": 2.0,        # mS/cm
    "EC_CAPACITY": 10.0,   # L/hr
    "EC_ON_SEC": 30,      # Dosing duration
    "EC_OFF_MIN": 5,      # Mixing duration

    "VALVE4_RESERVED": "Disabled"
}

setpoints = dict(DEFAULT_SETPOINTS)

def load_setpoints():
    """Load setpoints from JSON file or create with defaults."""
    global setpoints
    if os.path.exists(SETPOINT_FILE):
        try:
            with open(SETPOINT_FILE, "r") as f:
                loaded = json.load(f)
                setpoints.update(loaded)
                print("📁 Setpoints loaded successfully.")
        except Exception as e:
            print(f"⚠️ Error loading setpoints: {e}")
    else:
        save_setpoints()

def save_setpoints():
    """Save current setpoints to JSON file with atomic write."""
    try:
        tmp_path = SETPOINT_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(setpoints, f, indent=4)
        os.replace(tmp_path, SETPOINT_FILE)
        print("💾 Setpoints saved to disk.")
        return True
    except Exception as e:
        print(f"❌ Failed to save setpoints: {e}")
        return False

load_setpoints()

# -----------------------------------------------------------------------------
# MODBUS RS485 SENSOR READING
# -----------------------------------------------------------------------------
ec_instrument = None

def open_modbus_instrument(port, slave_id):
    try:
        inst = minimalmodbus.Instrument(port, slave_id)
        inst.serial.baudrate = 9600
        inst.serial.bytesize = 8
        inst.serial.parity   = serial.PARITY_NONE
        inst.serial.stopbits = 1
        inst.serial.timeout  = 0.5
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True
        return inst
    except Exception:
        return None

def read_ec_sensor():
    """Read EC value (mS/cm) from Modbus RS485 sensor."""
    global ec_instrument
    if ec_instrument is None:
        ec_instrument = open_modbus_instrument(SERIAL_PORT_WATER, DEVICE_ID_EC)
    if ec_instrument is None:
        return None

    try:
        ec_instrument.serial.reset_input_buffer()
        try:
            data = ec_instrument.read_registers(registeraddress=18, number_of_registers=4, functioncode=3)
            raw_ec = data[2]
            ec = round((raw_ec * 0.85) / 1000.0, 2)
            return {"ec": ec, "raw_ec": raw_ec}
        except Exception:
            pass

        try:
            data = ec_instrument.read_registers(registeraddress=18, number_of_registers=4, functioncode=4)
            raw_ec = data[2]
            ec = round((raw_ec * 0.85) / 1000.0, 2)
            return {"ec": ec, "raw_ec": raw_ec}
        except Exception:
            pass

        raw_ec = ec_instrument.read_register(0x0015, 0)
        ec = round((raw_ec * 0.85) / 1000.0, 2)
        return {"ec": ec, "raw_ec": raw_ec}
    except Exception:
        return None

# -----------------------------------------------------------------------------
# CONTROL SYSTEM ENGINE
# -----------------------------------------------------------------------------
class SystemState:
    def __init__(self):
        self.mode = "AUTO"  # "AUTO" or "STOP"
        self.current_ec = None
        self.ec_sensor_ok = True
        self.tank_low = False

        self.fogger = {"state": "OFF", "last_change": time.time(), "remaining": 0}
        self.sprinkler = {"state": "OFF", "last_change": time.time(), "remaining": 0}
        self.ec_dosing = {"state": "OFF", "last_change": time.time(), "remaining": 0, "active": False}

        self.alarms = []
        self.lock = threading.Lock()

state = SystemState()

def process_fogger_timer(now):
    if not setpoints.get("FOGGER_ENABLE", True) or state.mode != "AUTO":
        if relay_v1.is_active:
            relay_v1.off()
        state.fogger["state"] = "DISABLED" if state.mode == "AUTO" else "STOPPED"
        state.fogger["remaining"] = 0
        return

    on_sec = float(setpoints.get("FOGGER_ON_SEC", 30))
    off_sec = float(setpoints.get("FOGGER_OFF_MIN", 5)) * 60.0

    st = state.fogger
    elapsed = now - st["last_change"]

    if st["state"] not in ["ON", "OFF"]:
        st["state"] = "ON"
        st["last_change"] = now
        relay_v1.on()

    if st["state"] == "ON":
        st["remaining"] = max(0, int(on_sec - elapsed))
        if elapsed >= on_sec:
            st["state"] = "OFF"
            st["last_change"] = now
            relay_v1.off()
        else:
            relay_v1.on()
    elif st["state"] == "OFF":
        st["remaining"] = max(0, int(off_sec - elapsed))
        if elapsed >= off_sec:
            st["state"] = "ON"
            st["last_change"] = now
            relay_v1.on()
        else:
            relay_v1.off()

def process_sprinkler_timer(now):
    if not setpoints.get("SPRINKLER_ENABLE", True) or state.mode != "AUTO":
        if relay_v2.is_active:
            relay_v2.off()
        state.sprinkler["state"] = "DISABLED" if state.mode == "AUTO" else "STOPPED"
        state.sprinkler["remaining"] = 0
        return

    on_sec = float(setpoints.get("SPRINKLER_ON_MIN", 2)) * 60.0
    off_sec = float(setpoints.get("SPRINKLER_OFF_MIN", 20)) * 60.0

    st = state.sprinkler
    elapsed = now - st["last_change"]

    if st["state"] not in ["ON", "OFF"]:
        st["state"] = "ON"
        st["last_change"] = now
        relay_v2.on()

    if st["state"] == "ON":
        st["remaining"] = max(0, int(on_sec - elapsed))
        if elapsed >= on_sec:
            st["state"] = "OFF"
            st["last_change"] = now
            relay_v2.off()
        else:
            relay_v2.on()
    elif st["state"] == "OFF":
        st["remaining"] = max(0, int(off_sec - elapsed))
        if elapsed >= off_sec:
            st["state"] = "ON"
            st["last_change"] = now
            relay_v2.off()
        else:
            relay_v2.off()

def process_ec_dosing_control(now, ec_val):
    st = state.ec_dosing

    if not setpoints.get("EC_ENABLE", True) or state.mode != "AUTO" or not state.ec_sensor_ok or ec_val is None:
        if relay_v3.is_active:
            relay_v3.off()
        st["active"] = False
        st["state"] = "IDLE"
        st["remaining"] = 0
        return

    ec_min = float(setpoints.get("EC_MIN", 1.5))
    ec_max = float(setpoints.get("EC_MAX", 2.0))
    on_sec = float(setpoints.get("EC_ON_SEC", 30))
    off_sec = float(setpoints.get("EC_OFF_MIN", 5)) * 60.0

    if ec_val < ec_min and not st["active"]:
        st["active"] = True
        st["state"] = "ON"
        st["last_change"] = now
    elif ec_val >= ec_max and st["active"]:
        st["active"] = False
        st["state"] = "IDLE"
        relay_v3.off()

    if st["active"]:
        elapsed = now - st["last_change"]
        if st["state"] == "ON":
            st["remaining"] = max(0, int(on_sec - elapsed))
            if elapsed >= on_sec:
                st["state"] = "MIXING"
                st["last_change"] = now
                relay_v3.off()
            else:
                relay_v3.on()
        elif st["state"] == "MIXING":
            st["remaining"] = max(0, int(off_sec - elapsed))
            if elapsed >= off_sec:
                st["state"] = "ON"
                st["last_change"] = now
                relay_v3.on()
            else:
                relay_v3.off()
    else:
        if relay_v3.is_active:
            relay_v3.off()
        st["state"] = "IDLE"
        st["remaining"] = 0

def control_loop_step():
    with state.lock:
        now = time.time()
        alarms = []

        if tank_level_sensor and not tank_level_sensor.is_active:
            state.tank_low = True
            alarms.append("TANK WATER LEVEL LOW")
        else:
            state.tank_low = False

        sensor_res = read_ec_sensor()
        if sensor_res:
            state.current_ec = sensor_res["ec"]
            state.ec_sensor_ok = True
            if state.current_ec < 0.1 or state.current_ec > 10.0:
                alarms.append(f"Invalid EC Value ({state.current_ec} mS/cm)")
        else:
            state.ec_sensor_ok = False
            alarms.append("EC Sensor Comm Error")

        if state.mode == "STOP":
            all_valves_off()
            state.fogger["state"] = "STOPPED"
            state.sprinkler["state"] = "STOPPED"
            state.ec_dosing["state"] = "STOPPED"
            state.fogger["remaining"] = 0
            state.sprinkler["remaining"] = 0
            state.ec_dosing["remaining"] = 0
            alarms.append("SYSTEM IN STOP MODE")
        elif state.mode == "AUTO":
            process_fogger_timer(now)
            process_sprinkler_timer(now)
            process_ec_dosing_control(now, state.current_ec)
            relay_v4.off()

        state.alarms = alarms
        log_telemetry()

def log_telemetry():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        record = {
            "timestamp": datetime.datetime.now().isoformat(),
            "mode": state.mode,
            "ec_val": state.current_ec,
            "v1_fogger": bool(relay_v1.is_active),
            "v2_sprinkler": bool(relay_v2.is_active),
            "v3_ec_dosing": bool(relay_v3.is_active),
            "v4_spare": bool(relay_v4.is_active),
            "alarms": state.alarms
        }
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass

def restart_program():
    """Safely shut off relays, close serial ports, and re-exec python process."""
    all_valves_off()
    if ec_instrument:
        try:
            ec_instrument.serial.close()
        except Exception:
            pass
    os.execl(sys.executable, sys.executable, *sys.argv)

def exit_program():
    """Safely shut off all hardware relays and exit process."""
    all_valves_off()
    os._exit(0)

# -----------------------------------------------------------------------------
# SETPOINTS DIALOG (WHITE BACKGROUND WITH BLUE/GRAY & TOP-RIGHT LOGO)
# -----------------------------------------------------------------------------
class SetpointsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("⚙️ Setpoints Configuration")
        self.geometry("640x460")
        self.configure(bg="#FFFFFF")
        self.resizable(False, False)

        self.transient(parent)
        self.grab_set()

        self.create_widgets()

    def create_widgets(self):
        # Top Header Frame with Top-Right Logo (Pure White BG)
        hdr_frame = tk.Frame(self, bg="#FFFFFF", highlightbackground="#E2E8F0", highlightthickness=1)
        hdr_frame.pack(fill="x", padx=12, pady=(10, 5))

        lbl_title = tk.Label(hdr_frame, text="⚙️ PARAMETER SETTINGS", font=("Inter", 13, "bold"), fg="#0284C7", bg="#FFFFFF")
        lbl_title.pack(side="left", padx=12, pady=10)

        # Top-Right Corner Logo on Setpoints Page
        self.logo_img = load_logo_image(105, 32)
        if self.logo_img:
            lbl_logo = tk.Label(hdr_frame, image=self.logo_img, bg="#FFFFFF")
            lbl_logo.image = self.logo_img
            lbl_logo.pack(side="right", padx=12, pady=5)
        else:
            lbl_logo = tk.Label(hdr_frame, text="INHYDRO", font=("Inter", 11, "bold"), fg="#0284C7", bg="#FFFFFF")
            lbl_logo.pack(side="right", padx=12, pady=5)

        main_frame = tk.Frame(self, bg="#FFFFFF")
        main_frame.pack(fill="both", expand=True, padx=12, pady=5)

        def make_section(title):
            sf = tk.LabelFrame(main_frame, text=f" {title} ", font=("Inter", 9, "bold"), 
                              fg="#0284C7", bg="#FFFFFF", bd=1, relief="solid", padx=10, pady=6)
            sf.pack(fill="x", pady=4)
            return sf

        # Fogger Section
        fog_sec = make_section("FOGGER CONTROL (VALVE 1)")
        self.var_fog_enable = tk.BooleanVar(value=setpoints.get("FOGGER_ENABLE", True))
        chk_fog = tk.Checkbutton(fog_sec, text="Enable Fogger", variable=self.var_fog_enable,
                                 font=("Inter", 9, "bold"), fg="#1E293B", bg="#FFFFFF", 
                                 selectcolor="#F1F5F9", activebackground="#FFFFFF", activeforeground="#0284C7")
        chk_fog.grid(row=0, column=0, columnspan=2, sticky="w", pady=1)

        tk.Label(fog_sec, text="ON Time (sec):", font=("Inter", 9), fg="#475569", bg="#FFFFFF").grid(row=0, column=2, sticky="w", padx=(15, 2))
        self.ent_fog_on = tk.Entry(fog_sec, font=("Inter", 9), width=8, bg="#F8FAFC", fg="#1E293B", insertbackground="#0284C7", bd=1, relief="solid")
        self.ent_fog_on.insert(0, str(setpoints.get("FOGGER_ON_SEC", 30)))
        self.ent_fog_on.grid(row=0, column=3, sticky="w", pady=1)

        tk.Label(fog_sec, text="OFF Time (min):", font=("Inter", 9), fg="#475569", bg="#FFFFFF").grid(row=0, column=4, sticky="w", padx=(15, 2))
        self.ent_fog_off = tk.Entry(fog_sec, font=("Inter", 9), width=8, bg="#F8FAFC", fg="#1E293B", insertbackground="#0284C7", bd=1, relief="solid")
        self.ent_fog_off.insert(0, str(setpoints.get("FOGGER_OFF_MIN", 5)))
        self.ent_fog_off.grid(row=0, column=5, sticky="w", pady=1)

        # Sprinkler Section
        spr_sec = make_section("SPRINKLER CONTROL (VALVE 2)")
        self.var_spr_enable = tk.BooleanVar(value=setpoints.get("SPRINKLER_ENABLE", True))
        chk_spr = tk.Checkbutton(spr_sec, text="Enable Sprinkler", variable=self.var_spr_enable,
                                 font=("Inter", 9, "bold"), fg="#1E293B", bg="#FFFFFF", 
                                 selectcolor="#F1F5F9", activebackground="#FFFFFF", activeforeground="#0284C7")
        chk_spr.grid(row=0, column=0, columnspan=2, sticky="w", pady=1)

        tk.Label(spr_sec, text="ON Time (min):", font=("Inter", 9), fg="#475569", bg="#FFFFFF").grid(row=0, column=2, sticky="w", padx=(15, 2))
        self.ent_spr_on = tk.Entry(spr_sec, font=("Inter", 9), width=8, bg="#F8FAFC", fg="#1E293B", insertbackground="#0284C7", bd=1, relief="solid")
        self.ent_spr_on.insert(0, str(setpoints.get("SPRINKLER_ON_MIN", 2)))
        self.ent_spr_on.grid(row=0, column=3, sticky="w", pady=1)

        tk.Label(spr_sec, text="OFF Time (min):", font=("Inter", 9), fg="#475569", bg="#FFFFFF").grid(row=0, column=4, sticky="w", padx=(15, 2))
        self.ent_spr_off = tk.Entry(spr_sec, font=("Inter", 9), width=8, bg="#F8FAFC", fg="#1E293B", insertbackground="#0284C7", bd=1, relief="solid")
        self.ent_spr_off.insert(0, str(setpoints.get("SPRINKLER_OFF_MIN", 20)))
        self.ent_spr_off.grid(row=0, column=5, sticky="w", pady=1)

        # EC Control Section
        ec_sec = make_section("EC DOSING CONTROL (VALVE 3)")
        self.var_ec_enable = tk.BooleanVar(value=setpoints.get("EC_ENABLE", True))
        chk_ec = tk.Checkbutton(ec_sec, text="Enable EC Dosing", variable=self.var_ec_enable,
                                font=("Inter", 9, "bold"), fg="#1E293B", bg="#FFFFFF", 
                                selectcolor="#F1F5F9", activebackground="#FFFFFF", activeforeground="#0284C7")
        chk_ec.grid(row=0, column=0, columnspan=2, sticky="w", pady=2)

        tk.Label(ec_sec, text="EC MIN (mS/cm):", font=("Inter", 9), fg="#475569", bg="#FFFFFF").grid(row=1, column=0, sticky="w", pady=2)
        self.ent_ec_min = tk.Entry(ec_sec, font=("Inter", 9), width=8, bg="#F8FAFC", fg="#1E293B", insertbackground="#0284C7", bd=1, relief="solid")
        self.ent_ec_min.insert(0, str(setpoints.get("EC_MIN", 1.5)))
        self.ent_ec_min.grid(row=1, column=1, sticky="w", pady=2)

        tk.Label(ec_sec, text="EC MAX (mS/cm):", font=("Inter", 9), fg="#475569", bg="#FFFFFF").grid(row=1, column=2, sticky="w", padx=(15, 2), pady=2)
        self.ent_ec_max = tk.Entry(ec_sec, font=("Inter", 9), width=8, bg="#F8FAFC", fg="#1E293B", insertbackground="#0284C7", bd=1, relief="solid")
        self.ent_ec_max.insert(0, str(setpoints.get("EC_MAX", 2.0)))
        self.ent_ec_max.grid(row=1, column=3, sticky="w", pady=2)

        tk.Label(ec_sec, text="Capacity (L/hr):", font=("Inter", 9), fg="#475569", bg="#FFFFFF").grid(row=1, column=4, sticky="w", padx=(15, 2), pady=2)
        self.ent_ec_cap = tk.Entry(ec_sec, font=("Inter", 9), width=8, bg="#F8FAFC", fg="#1E293B", insertbackground="#0284C7", bd=1, relief="solid")
        self.ent_ec_cap.insert(0, str(setpoints.get("EC_CAPACITY", 10.0)))
        self.ent_ec_cap.grid(row=1, column=5, sticky="w", pady=2)

        tk.Label(ec_sec, text="Dosing ON (sec):", font=("Inter", 9), fg="#475569", bg="#FFFFFF").grid(row=2, column=0, sticky="w", pady=2)
        self.ent_ec_on = tk.Entry(ec_sec, font=("Inter", 9), width=8, bg="#F8FAFC", fg="#1E293B", insertbackground="#0284C7", bd=1, relief="solid")
        self.ent_ec_on.insert(0, str(setpoints.get("EC_ON_SEC", 30)))
        self.ent_ec_on.grid(row=2, column=1, sticky="w", pady=2)

        tk.Label(ec_sec, text="Mixing OFF (min):", font=("Inter", 9), fg="#475569", bg="#FFFFFF").grid(row=2, column=2, sticky="w", padx=(15, 2), pady=2)
        self.ent_ec_off = tk.Entry(ec_sec, font=("Inter", 9), width=8, bg="#F8FAFC", fg="#1E293B", insertbackground="#0284C7", bd=1, relief="solid")
        self.ent_ec_off.insert(0, str(setpoints.get("EC_OFF_MIN", 5)))
        self.ent_ec_off.grid(row=2, column=3, sticky="w", pady=2)

        # Bottom Buttons
        btn_frame = tk.Frame(main_frame, bg="#FFFFFF")
        btn_frame.pack(fill="x", pady=8)

        btn_save = tk.Button(btn_frame, text="💾 Save Settings", font=("Inter", 10, "bold"),
                             fg="#FFFFFF", bg="#0284C7", activebackground="#0369A1", 
                             bd=0, relief="flat", padx=16, pady=6, cursor="hand2", command=self.save_and_close)
        btn_save.pack(side="right", padx=5)

        btn_cancel = tk.Button(btn_frame, text="Cancel", font=("Inter", 10),
                               fg="#1E293B", bg="#E2E8F0", activebackground="#CBD5E1", 
                               bd=0, relief="flat", padx=14, pady=6, cursor="hand2", command=self.destroy)
        btn_cancel.pack(side="right", padx=5)

    def validate_and_save(self):
        try:
            fog_on = float(self.ent_fog_on.get())
            fog_off = float(self.ent_fog_off.get())
            spr_on = float(self.ent_spr_on.get())
            spr_off = float(self.ent_spr_off.get())

            ec_min = float(self.ent_ec_min.get())
            ec_max = float(self.ent_ec_max.get())
            ec_cap = float(self.ent_ec_cap.get())
            ec_on = float(self.ent_ec_on.get())
            ec_off = float(self.ent_ec_off.get())

            if ec_min >= ec_max:
                messagebox.showerror("Validation Error", "EC MIN setpoint must be strictly LESS than EC MAX setpoint!", parent=self)
                return False

            if fog_on <= 0 or fog_off <= 0 or spr_on <= 0 or spr_off <= 0 or ec_on <= 0 or ec_off <= 0:
                messagebox.showerror("Validation Error", "All ON/OFF durations must be positive numbers (> 0)!", parent=self)
                return False

            if ec_cap <= 0:
                messagebox.showerror("Validation Error", "EC Pump capacity must be greater than zero!", parent=self)
                return False

            setpoints["FOGGER_ENABLE"] = self.var_fog_enable.get()
            setpoints["FOGGER_ON_SEC"] = fog_on
            setpoints["FOGGER_OFF_MIN"] = fog_off

            setpoints["SPRINKLER_ENABLE"] = self.var_spr_enable.get()
            setpoints["SPRINKLER_ON_MIN"] = spr_on
            setpoints["SPRINKLER_OFF_MIN"] = spr_off

            setpoints["EC_ENABLE"] = self.var_ec_enable.get()
            setpoints["EC_MIN"] = ec_min
            setpoints["EC_MAX"] = ec_max
            setpoints["EC_CAPACITY"] = ec_cap
            setpoints["EC_ON_SEC"] = ec_on
            setpoints["EC_OFF_MIN"] = ec_off

            return save_setpoints()

        except ValueError:
            messagebox.showerror("Validation Error", "Invalid numeric format!", parent=self)
            return False

    def save_and_close(self):
        if self.validate_and_save():
            messagebox.showinfo("Saved", "Setpoints updated successfully!", parent=self)
            self.destroy()

# -----------------------------------------------------------------------------
# MAIN HMI WINDOW (PURE WHITE BACKGROUND + GRAY/BLUE DESIGN FOR 7-INCH DISPLAY)
# -----------------------------------------------------------------------------
class InHydroDripApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("InHydro Drip Irrigation & Dosing Controller")
        # 800x480 resolution optimal for 7-inch Raspberry Pi / Rock Pi displays
        self.geometry("800x480")
        self.configure(bg="#FFFFFF")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.setup_ui()
        self.start_background_thread()

    def setup_ui(self):
        # ---------------------------------------------------------------------
        # TOP HEADER BAR (Pure White BG, Non-overlapping Layout + Top Right Logo)
        # ---------------------------------------------------------------------
        hdr = tk.Frame(self, bg="#FFFFFF", highlightbackground="#E2E8F0", highlightthickness=1)
        hdr.pack(fill="x", padx=10, pady=(6, 4))

        # Title & Mode Buttons Frame (Left Side)
        hdr_left = tk.Frame(hdr, bg="#FFFFFF")
        hdr_left.pack(side="left", padx=5, pady=4)

        lbl_app_name = tk.Label(hdr_left, text="🌱 INHYDRO DRIP AUTOMATION", 
                                font=("Inter", 12, "bold"), fg="#0284C7", bg="#FFFFFF")
        lbl_app_name.pack(side="left", padx=(5, 10))

        self.btn_auto = tk.Button(hdr_left, text="▶ AUTOMATIC", font=("Inter", 8, "bold"),
                                  fg="#FFFFFF", bg="#0284C7", activebackground="#0369A1",
                                  bd=0, relief="flat", padx=10, pady=4, cursor="hand2", command=self.set_auto_mode)
        self.btn_auto.pack(side="left", padx=2)

        self.btn_stop = tk.Button(hdr_left, text="🛑 STOP", font=("Inter", 8, "bold"),
                                  fg="#FFFFFF", bg="#DC2626", activebackground="#B91C1C",
                                  bd=0, relief="flat", padx=10, pady=4, cursor="hand2", command=self.set_stop_mode)
        self.btn_stop.pack(side="left", padx=2)

        btn_settings = tk.Button(hdr_left, text="⚙️ SETTINGS", font=("Inter", 8, "bold"),
                                 fg="#FFFFFF", bg="#475569", activebackground="#334155",
                                 bd=0, relief="flat", padx=10, pady=4, cursor="hand2", command=self.open_settings)
        btn_settings.pack(side="left", padx=2)

        # Top-Right Corner Logo Frame (Guaranteed No Overlap)
        self.main_logo_img = load_logo_image(110, 35)
        if self.main_logo_img:
            lbl_logo = tk.Label(hdr, image=self.main_logo_img, bg="#FFFFFF")
            lbl_logo.image = self.main_logo_img
            lbl_logo.pack(side="right", padx=10, pady=4)
        else:
            lbl_logo = tk.Label(hdr, text="INHYDRO", font=("Inter", 11, "bold"), fg="#0284C7", bg="#FFFFFF")
            lbl_logo.pack(side="right", padx=10, pady=4)

        # ---------------------------------------------------------------------
        # MAIN 2x2 GRID BOX CONTAINER (Compact for 7-Inch Screen)
        # ---------------------------------------------------------------------
        grid_container = tk.Frame(self, bg="#FFFFFF")
        grid_container.pack(fill="both", expand=True, padx=8, pady=2)

        grid_container.grid_rowconfigure(0, weight=1)
        grid_container.grid_rowconfigure(1, weight=1)
        grid_container.grid_columnconfigure(0, weight=1)
        grid_container.grid_columnconfigure(1, weight=1)

        def create_grid_box(parent, r, c, title):
            box = tk.Frame(parent, bg="#FFFFFF", highlightbackground="#CBD5E1", highlightthickness=1)
            box.grid(row=r, column=c, sticky="nsew", padx=4, pady=3)

            # Gray/Blue Sub-header bar
            sub_hdr = tk.Frame(box, bg="#F1F5F9", height=24)
            sub_hdr.pack(fill="x")

            title_lbl = tk.Label(sub_hdr, text=title, font=("Inter", 9, "bold"), fg="#0284C7", bg="#F1F5F9")
            title_lbl.pack(anchor="w", padx=10, pady=3)

            content = tk.Frame(box, bg="#FFFFFF")
            content.pack(fill="both", expand=True, padx=10, pady=4)
            return content

        # ---------------------------------------------------------------------
        # GRID BOX 1 (Top-Left): EC SENSOR & TANK MONITOR
        # ---------------------------------------------------------------------
        box1 = create_grid_box(grid_container, 0, 0, "EC SENSOR & TANK MONITOR")

        ec_readout_frame = tk.Frame(box1, bg="#F8FAFC", highlightbackground="#E2E8F0", highlightthickness=1)
        ec_readout_frame.pack(fill="x", pady=2)

        tk.Label(ec_readout_frame, text="CURRENT EC READING", font=("Inter", 8, "bold"), fg="#64748B", bg="#F8FAFC").pack(pady=(4, 0))

        self.lbl_ec_val = tk.Label(ec_readout_frame, text="--.-- mS/cm", font=("Inter", 20, "bold"), fg="#0284C7", bg="#F8FAFC")
        self.lbl_ec_val.pack(pady=1)

        self.lbl_ec_range = tk.Label(ec_readout_frame, text="Target Range: 1.50 - 2.00 mS/cm", font=("Inter", 8), fg="#475569", bg="#F8FAFC")
        self.lbl_ec_range.pack(pady=(0, 4))

        tank_info = tk.Frame(box1, bg="#FFFFFF")
        tank_info.pack(fill="x", pady=4)

        tk.Label(tank_info, text="Common Tank Level:", font=("Inter", 9), fg="#475569", bg="#FFFFFF").pack(side="left")
        self.lbl_tank_status = tk.Label(tank_info, text="NORMAL", font=("Inter", 8, "bold"), fg="#0284C7", bg="#E0F2FE", padx=6, pady=2)
        self.lbl_tank_status.pack(side="right")

        # ---------------------------------------------------------------------
        # GRID BOX 2 (Top-Right): SOLENOID VALVES STATUS (V1 - V4)
        # ---------------------------------------------------------------------
        box2 = create_grid_box(grid_container, 0, 1, "SOLENOID VALVES (V1 - V4)")

        self.valve_cards = {}
        valves_def = [
            ("V1", "Valve 1: Fogger"),
            ("V2", "Valve 2: Sprinkler"),
            ("V3", "Valve 3: EC Control"),
            ("V4", "Valve 4: Spare")
        ]

        v_grid = tk.Frame(box2, bg="#FFFFFF")
        v_grid.pack(fill="both", expand=True)

        for idx, (key, name) in enumerate(valves_def):
            row_idx = idx // 2
            col_idx = idx % 2

            v_cell = tk.Frame(v_grid, bg="#F8FAFC", highlightbackground="#E2E8F0", highlightthickness=1)
            v_cell.grid(row=row_idx, column=col_idx, sticky="nsew", padx=3, pady=2)
            v_grid.grid_rowconfigure(row_idx, weight=1)
            v_grid.grid_columnconfigure(col_idx, weight=1)

            tk.Label(v_cell, text=name, font=("Inter", 8, "bold"), fg="#1E293B", bg="#F8FAFC").pack(anchor="w", padx=6, pady=(4, 1))
            
            lbl_st = tk.Label(v_cell, text="OFF", font=("Inter", 8, "bold"), fg="#64748B", bg="#E2E8F0", padx=6, pady=1)
            lbl_st.pack(anchor="e", padx=6, pady=(0, 4))

            self.valve_cards[key] = {"cell": v_cell, "status": lbl_st}

        # ---------------------------------------------------------------------
        # GRID BOX 3 (Bottom-Left): CYCLIC TIMERS & COUNTDOWNS
        # ---------------------------------------------------------------------
        box3 = create_grid_box(grid_container, 1, 0, "CYCLIC TIMERS & COUNTDOWNS")

        timers_frame = tk.Frame(box3, bg="#FFFFFF")
        timers_frame.pack(fill="both", expand=True)

        # Fogger Row
        row_fog = tk.Frame(timers_frame, bg="#F8FAFC", highlightbackground="#E2E8F0", highlightthickness=1)
        row_fog.pack(fill="x", pady=2)
        tk.Label(row_fog, text="Fogger Cycle:", font=("Inter", 8, "bold"), fg="#1E293B", bg="#F8FAFC").pack(side="left", padx=8, pady=3)
        self.lbl_tmr_fog = tk.Label(row_fog, text="--:--", font=("Inter", 9, "bold"), fg="#0284C7", bg="#F8FAFC")
        self.lbl_tmr_fog.pack(side="right", padx=8)

        # Sprinkler Row
        row_spr = tk.Frame(timers_frame, bg="#F8FAFC", highlightbackground="#E2E8F0", highlightthickness=1)
        row_spr.pack(fill="x", pady=2)
        tk.Label(row_spr, text="Sprinkler Cycle:", font=("Inter", 8, "bold"), fg="#1E293B", bg="#F8FAFC").pack(side="left", padx=8, pady=3)
        self.lbl_tmr_spr = tk.Label(row_spr, text="--:--", font=("Inter", 9, "bold"), fg="#0284C7", bg="#F8FAFC")
        self.lbl_tmr_spr.pack(side="right", padx=8)

        # EC Dosing Row
        row_ec = tk.Frame(timers_frame, bg="#F8FAFC", highlightbackground="#E2E8F0", highlightthickness=1)
        row_ec.pack(fill="x", pady=2)
        tk.Label(row_ec, text="EC Dosing Cycle:", font=("Inter", 8, "bold"), fg="#1E293B", bg="#F8FAFC").pack(side="left", padx=8, pady=3)
        self.lbl_tmr_ec = tk.Label(row_ec, text="--:--", font=("Inter", 9, "bold"), fg="#0284C7", bg="#F8FAFC")
        self.lbl_tmr_ec.pack(side="right", padx=8)

        # ---------------------------------------------------------------------
        # GRID BOX 4 (Bottom-Right): SYSTEM STATUS & ALARMS
        # ---------------------------------------------------------------------
        box4 = create_grid_box(grid_container, 1, 1, "SYSTEM STATUS & ALARMS")

        status_top = tk.Frame(box4, bg="#FFFFFF")
        status_top.pack(fill="x", pady=(0, 3))

        tk.Label(status_top, text="Operating Mode:", font=("Inter", 8), fg="#475569", bg="#FFFFFF").pack(side="left")
        self.lbl_sys_mode = tk.Label(status_top, text="AUTOMATIC", font=("Inter", 8, "bold"), fg="#FFFFFF", bg="#0284C7", padx=6, pady=1)
        self.lbl_sys_mode.pack(side="right")

        alarm_container = tk.Frame(box4, bg="#F8FAFC", highlightbackground="#E2E8F0", highlightthickness=1)
        alarm_container.pack(fill="both", expand=True)

        tk.Label(alarm_container, text="ACTIVE ALARMS & NOTIFICATIONS", font=("Inter", 7, "bold"), fg="#64748B", bg="#F8FAFC").pack(anchor="w", padx=6, pady=(4, 1))

        self.lbl_alarm = tk.Label(alarm_container, text="System operating normally. All parameters nominal.",
                                  font=("Inter", 8), fg="#1E293B", bg="#F8FAFC", wraplength=320, justify="left")
        self.lbl_alarm.pack(anchor="w", padx=6, pady=(0, 4))

        # ---------------------------------------------------------------------
        # BOTTOM FOOTER BAR (Pure White BG, Restart/Exit + Date & Time in Bottom Right)
        # ---------------------------------------------------------------------
        ftr = tk.Frame(self, bg="#FFFFFF", highlightbackground="#E2E8F0", highlightthickness=1)
        ftr.pack(fill="x", padx=10, pady=(4, 6))

        # System Action Buttons (Restart & Exit as in almora2.py / monit.py)
        btn_restart = tk.Button(ftr, text="🔄 RESTART", font=("Inter", 8, "bold"),
                                fg="#FFFFFF", bg="#64748B", activebackground="#475569",
                                bd=0, relief="flat", padx=10, pady=4, cursor="hand2", command=restart_program)
        btn_restart.pack(side="left", padx=(10, 4), pady=4)

        btn_exit = tk.Button(ftr, text="❌ EXIT", font=("Inter", 8, "bold"),
                             fg="#FFFFFF", bg="#DC2626", activebackground="#B91C1C",
                             bd=0, relief="flat", padx=10, pady=4, cursor="hand2", command=exit_program)
        btn_exit.pack(side="left", padx=4, pady=4)

        lbl_ftr_info = tk.Label(ftr, text="● RUNNING", font=("Inter", 8, "bold"), fg="#0284C7", bg="#FFFFFF")
        lbl_ftr_info.pack(side="left", padx=10, pady=4)

        # Bottom Right Corner Date & Time Clock
        self.lbl_clock = tk.Label(ftr, text="", font=("Inter", 9, "bold"), fg="#475569", bg="#FFFFFF")
        self.lbl_clock.pack(side="right", padx=10, pady=4)

        # GUI Periodic Update Timer (Every 500 ms)
        self.after(500, self.update_gui)

    def set_auto_mode(self):
        with state.lock:
            state.mode = "AUTO"
        messagebox.showinfo("System Mode", "Switched to AUTOMATIC MODE.")

    def set_stop_mode(self):
        with state.lock:
            state.mode = "STOP"
            all_valves_off()
        messagebox.showwarning("System Mode", "STOP MODE activated! All valves shut OFF.")

    def open_settings(self):
        dialog = SetpointsDialog(self)

    def format_countdown(self, seconds):
        if seconds <= 0:
            return "--:--"
        mins, secs = divmod(seconds, 60)
        return f"{mins:02d}:{secs:02d}"

    def update_gui(self):
        """Update interface with live data and real-time clock."""
        now_dt = datetime.datetime.now()
        dt_str = now_dt.strftime("%A, %b %d, %Y  |  %H:%M:%S")
        self.lbl_clock.config(text=dt_str)

        with state.lock:
            if state.current_ec is not None:
                self.lbl_ec_val.config(text=f"{state.current_ec:.2f} mS/cm", fg="#0284C7" if state.ec_sensor_ok else "#DC2626")
            else:
                self.lbl_ec_val.config(text="--.-- mS/cm", fg="#DC2626")

            ec_min = setpoints.get("EC_MIN", 1.5)
            ec_max = setpoints.get("EC_MAX", 2.0)
            self.lbl_ec_range.config(text=f"Target Range: {ec_min:.2f} - {ec_max:.2f} mS/cm")

            if state.mode == "AUTO":
                self.lbl_sys_mode.config(text="AUTOMATIC", fg="#FFFFFF", bg="#0284C7")
                self.btn_auto.config(bg="#0284C7", fg="#FFFFFF")
                self.btn_stop.config(bg="#94A3B8", fg="#FFFFFF")
            else:
                self.lbl_sys_mode.config(text="STOPPED", fg="#FFFFFF", bg="#DC2626")
                self.btn_auto.config(bg="#94A3B8", fg="#FFFFFF")
                self.btn_stop.config(bg="#DC2626", fg="#FFFFFF")

            if state.tank_low:
                self.lbl_tank_status.config(text="LOW LEVEL ALARM", fg="#FFFFFF", bg="#DC2626")
            else:
                self.lbl_tank_status.config(text="NORMAL", fg="#0284C7", bg="#E0F2FE")

            # Solenoid Valves Status
            if relay_v1.is_active:
                self.valve_cards["V1"]["status"].config(text="ON", fg="#FFFFFF", bg="#0284C7")
            else:
                self.valve_cards["V1"]["status"].config(text="OFF", fg="#64748B", bg="#E2E8F0")
            self.lbl_tmr_fog.config(text=self.format_countdown(state.fogger['remaining']))

            if relay_v2.is_active:
                self.valve_cards["V2"]["status"].config(text="ON", fg="#FFFFFF", bg="#0284C7")
            else:
                self.valve_cards["V2"]["status"].config(text="OFF", fg="#64748B", bg="#E2E8F0")
            self.lbl_tmr_spr.config(text=self.format_countdown(state.sprinkler['remaining']))

            if relay_v3.is_active:
                self.valve_cards["V3"]["status"].config(text="DOSING", fg="#FFFFFF", bg="#0284C7")
            elif state.ec_dosing["state"] == "MIXING":
                self.valve_cards["V3"]["status"].config(text="MIXING", fg="#FFFFFF", bg="#D97706")
            else:
                self.valve_cards["V3"]["status"].config(text="OFF", fg="#64748B", bg="#E2E8F0")
            self.lbl_tmr_ec.config(text=self.format_countdown(state.ec_dosing['remaining']))

            self.valve_cards["V4"]["status"].config(text="RESERVED", fg="#94A3B8", bg="#F1F5F9")

            if state.alarms:
                self.lbl_alarm.config(text=" | ".join(state.alarms), fg="#DC2626")
            else:
                self.lbl_alarm.config(text="System operating normally. All parameters nominal.", fg="#0284C7")

        self.after(500, self.update_gui)

    def start_background_thread(self):
        self.running = True
        def worker():
            while self.running:
                try:
                    control_loop_step()
                except Exception as e:
                    print(f"Error in control loop step: {e}")
                time.sleep(1.0)

        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def on_close(self):
        self.running = False
        all_valves_off()
        self.destroy()

# -----------------------------------------------------------------------------
# MAIN ENTRY POINT
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app = InHydroDripApp()
    app.mainloop()
