#!/usr/bin/env python3
"""
===============================================================================
InHydro Polyhouse Automation - Fertigation & Irrigation HMI Controller
===============================================================================
Complete Python & Raspberry Pi Controller with:
  - Fullscreen Touch Display Mode (with F11 toggle and Exit button)
  - Clean Exit on Escape (Esc) with Hardware De-energize
  - Built-in On-Screen Virtual Touch Keypad & Alphanumeric Keyboard for all inputs
  - Fully Functional Actuator Relays & Hardware Loops (ON/OFF work in real-time)
  - 6-Button Main Dashboard matching WECON HMI with Prev/Next/Home Navigation

Author: InHydro Engineering Team
===============================================================================
"""

import os
import sys
import time
import json
import datetime
import threading
import tkinter as tk
from tkinter import ttk, messagebox, font
from typing import Dict, Any, Optional

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

# -----------------------------------------------------------------------------
# FILE PATHS & SETUP
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config_fertigation_hmi.json")
RECIPE_FILE = os.path.join(BASE_DIR, "crop_recipes.json")
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
LOG_DIR = os.path.join(BASE_DIR, "local_logs")

os.makedirs(LOG_DIR, exist_ok=True)

SCREEN_SEQUENCE = [
    "dashboard",
    "monitoring",
    "fertigation",
    "irrigation",
    "manual",
    "data",
    "settings"
]

SCREEN_TITLES = {
    "dashboard":   "🏠 MAIN DASHBOARD MENU",
    "monitoring":  "📊 SCREEN 1: P&ID SCHEMATIC MONITORING",
    "fertigation": "🧪 SCREEN 2: FERTIGATION & DOSING RECIPES",
    "irrigation":  "💧 SCREEN 3: IRRIGATION & ZONE DELIVERY",
    "manual":      "⚡ SCREEN 4: MANUAL RELAY OVERRIDES",
    "data":        "📈 SCREEN 5: DATA RECORDS & TELEMETRY",
    "settings":    "⚙️ SCREEN 6: SYSTEM SETTINGS & CALIBRATION",
}

# -----------------------------------------------------------------------------
# DEFAULT RECIPES & CONFIGURATIONS
# -----------------------------------------------------------------------------
DEFAULT_RECIPES = {
    "cucumber": {
        "crop_name": "Cucumber",
        "target_ec": 2.2,
        "target_ph": 5.8,
        "ec_valve_1_liters": 1.5,
        "ec_valve_2_liters": 1.5,
        "ec_valve_3_liters": 0.5,
        "ec_valve_4_liters": 0.0,
        "ph_valve_enable": True,
        "zone_1_liters": 300,
        "zone_2_liters": 300,
        "mixing_time_sec": 30
    },
    "tomato": {
        "crop_name": "Tomato",
        "target_ec": 2.5,
        "target_ph": 6.0,
        "ec_valve_1_liters": 2.0,
        "ec_valve_2_liters": 2.0,
        "ec_valve_3_liters": 0.8,
        "ec_valve_4_liters": 0.2,
        "ph_valve_enable": True,
        "zone_1_liters": 450,
        "zone_2_liters": 450,
        "mixing_time_sec": 45
    },
    "capsicum": {
        "crop_name": "Capsicum / Bell Pepper",
        "target_ec": 2.0,
        "target_ph": 6.2,
        "ec_valve_1_liters": 1.2,
        "ec_valve_2_liters": 1.2,
        "ec_valve_3_liters": 0.4,
        "ec_valve_4_liters": 0.0,
        "ph_valve_enable": True,
        "zone_1_liters": 250,
        "zone_2_liters": 250,
        "mixing_time_sec": 30
    },
    "strawberry": {
        "crop_name": "Strawberry",
        "target_ec": 1.6,
        "target_ph": 5.7,
        "ec_valve_1_liters": 0.8,
        "ec_valve_2_liters": 0.8,
        "ec_valve_3_liters": 0.3,
        "ec_valve_4_liters": 0.0,
        "ph_valve_enable": True,
        "zone_1_liters": 150,
        "zone_2_liters": 150,
        "mixing_time_sec": 25
    }
}

DEFAULT_CONFIG = {
    "serial_port_relay": "/dev/ttyUSB0",
    "relay_slave_id": 1,
    "relay_baudrate": 9600,
    "simulation_mode": True,
    "min_tank_fill_liters": 250.0,
}

def load_json(filepath, default_data):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            pass
    save_json(filepath, default_data)
    return default_data

def save_json(filepath, data):
    try:
        tmp = filepath + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=4)
        os.replace(tmp, filepath)
    except Exception as e:
        print(f"Error saving {filepath}: {e}")

system_config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
crop_recipes = load_json(RECIPE_FILE, DEFAULT_RECIPES)

# -----------------------------------------------------------------------------
# HARDWARE RELAYS & SENSORS
# -----------------------------------------------------------------------------
class ActuatorMap:
    FERTIGATION_VALVE = 0
    EC_VALVE_1        = 1
    EC_VALVE_2        = 2
    EC_VALVE_3        = 3
    EC_VALVE_4        = 4
    PH_VALVE          = 5
    IRRIGATION_VALVE  = 6
    ZONE_1_VALVE      = 7
    ZONE_2_VALVE      = 8
    RO_WATER_PUMP     = 9
    MAIN_PUMP         = 10

ACTUATOR_NAMES = {
    ActuatorMap.FERTIGATION_VALVE: "Fertigation Valve",
    ActuatorMap.EC_VALVE_1:        "EC Valve-1",
    ActuatorMap.EC_VALVE_2:        "EC Valve-2",
    ActuatorMap.EC_VALVE_3:        "EC Valve-3",
    ActuatorMap.EC_VALVE_4:        "EC Valve-4",
    ActuatorMap.PH_VALVE:          "PH Valve",
    ActuatorMap.IRRIGATION_VALVE:  "Irrigation Valve",
    ActuatorMap.ZONE_1_VALVE:      "Zone-1 Valve",
    ActuatorMap.ZONE_2_VALVE:      "Zone-2 Valve",
    ActuatorMap.RO_WATER_PUMP:     "RO Water Pump",
    ActuatorMap.MAIN_PUMP:         "Main Pump",
}

class HardwareController:
    def __init__(self):
        self.lock = threading.Lock()
        self.relay_inst = None
        self.sim_mode = system_config.get("simulation_mode", True)
        self.relay_states = {ch: False for ch in ACTUATOR_NAMES.keys()}

        self.pv_tank_liters = 650.0
        self.pv_tank_percent = 65.0
        self.pv_ec = 1.85
        self.pv_ph = 6.05
        self.pv_water_temp = 24.2
        self.pv_total_flow = 0.0

        self.init_hardware()

    def init_hardware(self):
        if not MODBUS_AVAILABLE:
            self.sim_mode = True
            return

        try:
            port = system_config.get("serial_port_relay", "/dev/ttyUSB0")
            slave_id = system_config.get("relay_slave_id", 1)
            baud = system_config.get("relay_baudrate", 9600)

            if os.path.exists(port):
                self.relay_inst = minimalmodbus.Instrument(port, slave_id)
                self.relay_inst.serial.baudrate = baud
                self.relay_inst.serial.timeout = 0.3
                self.relay_inst.mode = minimalmodbus.MODE_RTU
                self.sim_mode = False
                print(f"Modbus Relay connected on {port} (Slave {slave_id})")
            else:
                self.sim_mode = True
        except Exception:
            self.sim_mode = True

    def set_relay(self, channel: int, state: bool):
        with self.lock:
            self.relay_states[channel] = state
            if not self.sim_mode and self.relay_inst:
                try:
                    self.relay_inst.write_bit(channel, state)
                except Exception as e:
                    print(f"Modbus write error on channel {channel}: {e}")

    def get_relay(self, channel: int) -> bool:
        with self.lock:
            return self.relay_states.get(channel, False)

    def emergency_all_off(self):
        with self.lock:
            for ch in self.relay_states:
                self.relay_states[ch] = False
                if not self.sim_mode and self.relay_inst:
                    try:
                        self.relay_inst.write_bit(ch, False)
                    except Exception:
                        pass

    def simulate_step(self, dt: float):
        with self.lock:
            if self.relay_states[ActuatorMap.RO_WATER_PUMP]:
                self.pv_tank_liters = min(1000.0, self.pv_tank_liters + (15.0 * dt))
                self.pv_ec = max(0.4, self.pv_ec - (0.01 * dt))

            for ch in [ActuatorMap.EC_VALVE_1, ActuatorMap.EC_VALVE_2, ActuatorMap.EC_VALVE_3]:
                if self.relay_states[ch]:
                    self.pv_ec = min(4.0, self.pv_ec + (0.05 * dt))

            if self.relay_states[ActuatorMap.PH_VALVE]:
                self.pv_ph = max(4.0, self.pv_ph - (0.04 * dt))

            if self.relay_states[ActuatorMap.MAIN_PUMP] and self.relay_states[ActuatorMap.IRRIGATION_VALVE]:
                if self.relay_states[ActuatorMap.ZONE_1_VALVE] or self.relay_states[ActuatorMap.ZONE_2_VALVE]:
                    flow_rate = 20.0 * dt
                    self.pv_tank_liters = max(0.0, self.pv_tank_liters - flow_rate)
                    self.pv_total_flow += flow_rate

            self.pv_tank_percent = round((self.pv_tank_liters / 1000.0) * 100.0, 1)
            self.pv_tank_liters = round(self.pv_tank_liters, 1)
            self.pv_ec = round(self.pv_ec, 2)
            self.pv_ph = round(self.pv_ph, 2)
            self.pv_total_flow = round(self.pv_total_flow, 1)

hw = HardwareController()

# -----------------------------------------------------------------------------
# AUTOMATION ENGINE
# -----------------------------------------------------------------------------
class CycleState:
    IDLE = "IDLE"
    FILLING_RO = "FILLING RO WATER"
    DOSING_NUTRIENTS = "DOSING NUTRIENTS"
    CIRCULATION_MIXING = "RECIRCULATION & MIXING"
    IRRIGATING_ZONE1 = "IRRIGATING ZONE-1"
    IRRIGATING_ZONE2 = "IRRIGATING ZONE-2"
    ABORTED = "ABORTED"
    COMPLETED = "COMPLETED"

class AutomationEngine:
    def __init__(self, hardware: HardwareController):
        self.hw = hardware
        self.state = CycleState.IDLE
        self.active_mode = "AUTO"
        self.active_recipe_key = "cucumber"
        self.is_running = False
        self.stop_event = threading.Event()
        self.status_msg = "System Ready"
        self.recent_batches = [
            {"time": "Today 10:15", "recipe": "Cucumber", "volume": "600 L", "status": "Completed", "ec": "2.20", "ph": "5.85"},
            {"time": "Yesterday 16:30", "recipe": "Tomato", "volume": "900 L", "status": "Completed", "ec": "2.48", "ph": "6.02"},
        ]

    def start_cycle(self, mode: str, recipe_key: str):
        if self.is_running:
            return
        self.active_mode = mode
        self.active_recipe_key = recipe_key
        self.is_running = True
        self.stop_event.clear()
        threading.Thread(target=self._run_loop, daemon=True).start()

    def stop_cycle(self):
        self.stop_event.set()
        self.is_running = False
        self.hw.emergency_all_off()
        self.state = CycleState.ABORTED
        self.status_msg = "Process Aborted / Emergency Stop"

    def _run_loop(self):
        recipe = crop_recipes.get(self.active_recipe_key, DEFAULT_RECIPES["cucumber"])
        try:
            self.status_msg = f"Starting {recipe['crop_name']} Cycle..."
            
            # Phase 1: Tank Refill Check
            self.state = CycleState.FILLING_RO
            min_fill = system_config.get("min_tank_fill_liters", 300.0)
            if self.hw.pv_tank_liters < min_fill:
                self.status_msg = "Filling RO Water into Mixing Tank..."
                self.hw.set_relay(ActuatorMap.RO_WATER_PUMP, True)
                while self.hw.pv_tank_liters < 800.0 and not self.stop_event.is_set():
                    time.sleep(0.5)
                self.hw.set_relay(ActuatorMap.RO_WATER_PUMP, False)

            if self.stop_event.is_set(): return

            # Phase 2: Dosing
            self.state = CycleState.DOSING_NUTRIENTS
            self.status_msg = "Dosing Fertilizers (EC Channels 1 to 4)..."
            valves_to_dose = [
                (ActuatorMap.EC_VALVE_1, recipe.get("ec_valve_1_liters", 1.0)),
                (ActuatorMap.EC_VALVE_2, recipe.get("ec_valve_2_liters", 1.0)),
                (ActuatorMap.EC_VALVE_3, recipe.get("ec_valve_3_liters", 0.5)),
                (ActuatorMap.EC_VALVE_4, recipe.get("ec_valve_4_liters", 0.0)),
            ]
            for ch, vol in valves_to_dose:
                if vol > 0.0 and not self.stop_event.is_set():
                    self.hw.set_relay(ch, True)
                    dose_time = max(1.0, vol * 2.0)
                    start = time.time()
                    while time.time() - start < dose_time and not self.stop_event.is_set():
                        time.sleep(0.1)
                    self.hw.set_relay(ch, False)

            if recipe.get("ph_valve_enable", True) and not self.stop_event.is_set():
                self.hw.set_relay(ActuatorMap.PH_VALVE, True)
                time.sleep(2.0)
                self.hw.set_relay(ActuatorMap.PH_VALVE, False)

            if self.stop_event.is_set(): return

            # Phase 3: Mixing
            self.state = CycleState.CIRCULATION_MIXING
            mix_seconds = recipe.get("mixing_time_sec", 30)
            self.status_msg = f"Mixing Solution ({mix_seconds}s) for Uniform EC & pH..."
            self.hw.set_relay(ActuatorMap.FERTIGATION_VALVE, True)
            self.hw.set_relay(ActuatorMap.MAIN_PUMP, True)

            start = time.time()
            while time.time() - start < mix_seconds and not self.stop_event.is_set():
                time.sleep(0.5)

            if self.stop_event.is_set(): return

            # Phase 4: Irrigation Delivery
            self.hw.set_relay(ActuatorMap.FERTIGATION_VALVE, False)
            self.hw.set_relay(ActuatorMap.IRRIGATION_VALVE, True)

            z1_liters = recipe.get("zone_1_liters", 200)
            if z1_liters > 0 and not self.stop_event.is_set():
                self.state = CycleState.IRRIGATING_ZONE1
                self.status_msg = f"Irrigating Zone-1 ({z1_liters} Liters)..."
                self.hw.set_relay(ActuatorMap.ZONE_1_VALVE, True)
                start = time.time()
                while time.time() - start < max(3.0, z1_liters * 0.04) and not self.stop_event.is_set():
                    time.sleep(0.5)
                self.hw.set_relay(ActuatorMap.ZONE_1_VALVE, False)

            z2_liters = recipe.get("zone_2_liters", 200)
            if z2_liters > 0 and not self.stop_event.is_set():
                self.state = CycleState.IRRIGATING_ZONE2
                self.status_msg = f"Irrigating Zone-2 ({z2_liters} Liters)..."
                self.hw.set_relay(ActuatorMap.ZONE_2_VALVE, True)
                start = time.time()
                while time.time() - start < max(3.0, z2_liters * 0.04) and not self.stop_event.is_set():
                    time.sleep(0.5)
                self.hw.set_relay(ActuatorMap.ZONE_2_VALVE, False)

            self.hw.set_relay(ActuatorMap.IRRIGATION_VALVE, False)
            self.hw.set_relay(ActuatorMap.MAIN_PUMP, False)
            self.state = CycleState.COMPLETED
            tot = z1_liters + z2_liters
            self.status_msg = f"Batch Complete: Delivered {tot} Liters."

            self.recent_batches.insert(0, {
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "recipe": recipe["crop_name"],
                "volume": f"{tot} L",
                "status": "Completed",
                "ec": f"{self.hw.pv_ec:.2f}",
                "ph": f"{self.hw.pv_ph:.2f}"
            })

        except Exception as err:
            self.hw.emergency_all_off()
            self.state = CycleState.ABORTED
            self.status_msg = f"Error during sequence: {err}"
        finally:
            self.is_running = False

engine = AutomationEngine(hw)

# -----------------------------------------------------------------------------
# TOUCH VIRTUAL KEYPAD & ALPHANUMERIC KEYBOARD POPUP MODAL
# -----------------------------------------------------------------------------
class TouchKeypadModal(tk.Toplevel):
    """Touch-friendly on-screen keyboard/keypad for Raspberry Pi touchscreens."""
    def __init__(self, parent, title_text: str, initial_value: str, callback_on_confirm, is_numeric: bool = True):
        super().__init__(parent)
        self.callback = callback_on_confirm
        self.is_numeric = is_numeric
        self.entered_value = str(initial_value)

        self.title(title_text)
        self.configure(bg="#0F172A")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Center on parent screen
        w = 460 if is_numeric else 660
        h = 420 if is_numeric else 380
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        cx = max(10, px + (pw - w) // 2)
        cy = max(10, py + (ph - h) // 2)
        self.geometry(f"{w}x{h}+{cx}+{cy}")

        # Header Frame
        hdr = tk.Frame(self, bg="#0284C7", height=40)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text=title_text, font=("Helvetica", 11, "bold"), fg="#FFFFFF", bg="#0284C7").pack(side="left", padx=12, pady=6)
        tk.Button(hdr, text="✕", font=("Helvetica", 11, "bold"), bg="#0284C7", fg="#FFFFFF", bd=0, cursor="hand2", command=self.destroy).pack(side="right", padx=10)

        # Input Value Display Box
        disp_frame = tk.Frame(self, bg="#0F172A", padx=16, pady=10)
        disp_frame.pack(fill="x")
        self.lbl_disp = tk.Label(disp_frame, text=self.entered_value, font=("Helvetica", 20, "bold"), fg="#38BDF8", bg="#1E293B", relief="solid", bd=1, padx=12, pady=6, anchor="e")
        self.lbl_disp.pack(fill="x")

        # Buttons Body
        btn_frame = tk.Frame(self, bg="#0F172A", padx=12, pady=4)
        btn_frame.pack(fill="both", expand=True)

        if self.is_numeric:
            self._build_numeric_grid(btn_frame)
        else:
            self._build_alphanumeric_grid(btn_frame)

        # Bottom Action Bar (DEL, CLEAR, CANCEL, CONFIRM)
        act_bar = tk.Frame(self, bg="#0F172A", padx=12, pady=10)
        act_bar.pack(fill="x", side="bottom")

        tk.Button(act_bar, text="⌫ DEL", font=("Helvetica", 11, "bold"), bg="#F97316", fg="#FFFFFF", activebackground="#EA580C", bd=0, padx=14, pady=8, cursor="hand2", command=self._backspace).pack(side="left", padx=3, expand=True, fill="x")
        tk.Button(act_bar, text="🗑 CLEAR", font=("Helvetica", 11, "bold"), bg="#EF4444", fg="#FFFFFF", activebackground="#DC2626", bd=0, padx=14, pady=8, cursor="hand2", command=self._clear).pack(side="left", padx=3, expand=True, fill="x")
        tk.Button(act_bar, text="✕ CANCEL", font=("Helvetica", 11, "bold"), bg="#64748B", fg="#FFFFFF", activebackground="#475569", bd=0, padx=14, pady=8, cursor="hand2", command=self.destroy).pack(side="left", padx=3, expand=True, fill="x")
        tk.Button(act_bar, text="✔ CONFIRM", font=("Helvetica", 11, "bold"), bg="#10B981", fg="#FFFFFF", activebackground="#059669", bd=0, padx=16, pady=8, cursor="hand2", command=self._confirm).pack(side="left", padx=3, expand=True, fill="x")

    def _append(self, char: str):
        if len(self.entered_value) < 30:
            self.entered_value += str(char)
            self.lbl_disp.config(text=self.entered_value)

    def _backspace(self):
        self.entered_value = self.entered_value[:-1]
        self.lbl_disp.config(text=self.entered_value)

    def _clear(self):
        self.entered_value = ""
        self.lbl_disp.config(text="")

    def _confirm(self):
        self.callback(self.entered_value.strip())
        self.destroy()

    def _build_numeric_grid(self, parent):
        grid = [
            ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
            ("-", 3, 0), ("0", 3, 1), (".", 3, 2),
        ]
        for i in range(4): parent.rowconfigure(i, weight=1)
        for j in range(3): parent.columnconfigure(j, weight=1)

        for text, r, c in grid:
            b = tk.Button(
                parent, text=text, font=("Helvetica", 15, "bold"), bg="#1E293B", fg="#FFFFFF",
                activebackground="#0284C7", activeforeground="#FFFFFF", bd=0, cursor="hand2",
                command=lambda t=text: self._append(t)
            )
            b.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")

    def _build_alphanumeric_grid(self, parent):
        rows = [
            list("1234567890"),
            list("QWERTYUIOP"),
            list("ASDFGHJKL:"),
            list("ZXCVBNM._- "),
        ]
        for row_chars in rows:
            r_frame = tk.Frame(parent, bg="#0F172A")
            r_frame.pack(fill="x", pady=2)
            for ch in row_chars:
                lbl = "SPACE" if ch == " " else ch
                w = 8 if ch == " " else 3
                b = tk.Button(
                    r_frame, text=lbl, font=("Helvetica", 11, "bold"), width=w, bg="#1E293B", fg="#FFFFFF",
                    activebackground="#0284C7", bd=0, cursor="hand2",
                    command=lambda c=ch: self._append(c)
                )
                b.pack(side="left", padx=2, expand=True, fill="both")

# -----------------------------------------------------------------------------
# GRAPHICAL USER INTERFACE
# -----------------------------------------------------------------------------
class InHydroFertigationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("InHydro Automation - Polyhouse Controller")
        self.geometry("1024x600")
        self.minsize(980, 560)
        self.configure(bg="#FFFFFF")

        # Fullscreen Mode Enable
        self.is_fullscreen = True
        try:
            self.attributes("-fullscreen", True)
        except Exception:
            pass

        # Color Theme: Pure White + Elegant Blue Accents
        self.COLOR_BG = "#FFFFFF"
        self.COLOR_SURFACE = "#F8FAFC"
        self.COLOR_CARD_BORDER = "#CBD5E1"
        self.COLOR_PRIMARY = "#0284C7"       # Sky Blue 600
        self.COLOR_PRIMARY_DARK = "#0369A1"  # Blue 700
        self.COLOR_TEXT_MAIN = "#0F172A"
        self.COLOR_TEXT_SUB = "#475569"
        self.COLOR_SUCCESS = "#10B981"
        self.COLOR_DANGER = "#EF4444"

        # Fonts
        self.font_title = font.Font(family="Helvetica", size=12, weight="bold")
        self.font_btn_big = font.Font(family="Helvetica", size=14, weight="bold")
        self.font_h2 = font.Font(family="Helvetica", size=11, weight="bold")
        self.font_body = font.Font(family="Helvetica", size=10)
        self.font_body_bold = font.Font(family="Helvetica", size=10, weight="bold")
        self.font_sub = font.Font(family="Helvetica", size=9)
        self.font_nav_arrow = font.Font(family="Helvetica", size=12, weight="bold")
        self.font_big_val = font.Font(family="Helvetica", size=16, weight="bold")

        self.logo_img = None
        self._load_logo()

        self.var_mode = tk.StringVar(value="Auto")
        self.var_recipe = tk.StringVar(value="cucumber")

        self.screens = {}
        self.current_screen_key = "dashboard"

        # 1. FIXED TOP HEADER
        self._build_header()

        # 2. FIXED TOP NAVIGATION BAR
        self._build_top_nav_bar()

        # 3. FIXED BOTTOM DOCK (Navigation Buttons)
        self._build_bottom_dock()

        # 4. CENTER CONTAINER
        self.container = tk.Frame(self, bg=self.COLOR_BG)
        self.container.pack(fill="both", expand=True, padx=12, pady=4)

        # Build each screen
        self.screens["dashboard"]   = self._create_dashboard_screen(self.container)
        self.screens["monitoring"]  = self._create_monitoring_screen(self.container)
        self.screens["fertigation"] = self._create_fertigation_screen(self.container)
        self.screens["irrigation"]  = self._create_irrigation_screen(self.container)
        self.screens["manual"]      = self._create_manual_screen(self.container)
        self.screens["data"]        = self._create_data_screen(self.container)
        self.screens["settings"]    = self._create_settings_screen(self.container)

        self.show_screen("dashboard")

        # Global Keyboard Shortcuts
        self.bind("<Escape>", lambda e: self.exit_application())
        self.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.bind("<Left>", lambda e: self.go_prev())
        self.bind("<Right>", lambda e: self.go_next())
        self.bind("<Home>", lambda e: self.go_home())

        # Periodic Loop
        self.after(100, self._periodic_tick)

    def _load_logo(self):
        if PIL_AVAILABLE and os.path.exists(LOGO_PATH):
            try:
                img = Image.open(LOGO_PATH)
                img.thumbnail((120, 36), Image.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(img)
            except Exception:
                pass

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        self.attributes("-fullscreen", self.is_fullscreen)

    def exit_application(self):
        """Clean shutdown on Escape or Exit button: turns off all relays safely."""
        if messagebox.askyesno("Exit Application", "Are you sure you want to exit the InHydro Controller?"):
            hw.emergency_all_off()
            engine.stop_cycle()
            self.destroy()
            sys.exit(0)

    # -------------------------------------------------------------------------
    # 1. HEADER (BRAND, MODES, CLOCK, FULLSCREEN, E-STOP, EXIT)
    # -------------------------------------------------------------------------
    def _build_header(self):
        hdr = tk.Frame(self, bg=self.COLOR_BG, height=44, bd=0)
        hdr.pack(fill="x", side="top", padx=12, pady=(6, 2))

        # Brand / Logo
        left_box = tk.Frame(hdr, bg=self.COLOR_BG)
        left_box.pack(side="left", fill="y")
        if self.logo_img:
            tk.Label(left_box, image=self.logo_img, bg=self.COLOR_BG).pack(side="left", padx=(0, 8))
        tk.Label(left_box, text="INHYDRO AUTOMATION", font=self.font_title, fg=self.COLOR_PRIMARY_DARK, bg=self.COLOR_BG).pack(side="left")

        # Mode Badges (Auto / Semi Auto / Manual)
        mode_box = tk.Frame(hdr, bg="#F1F5F9", bd=1, relief="solid")
        mode_box.pack(side="left", expand=True)
        self.mode_leds = {}
        for m in ["Auto", "Semi Auto", "Manual"]:
            btn_m = tk.Button(
                mode_box, text=f"●  {m}", font=self.font_sub, bg="#F1F5F9", fg=self.COLOR_TEXT_MAIN,
                bd=0, padx=10, pady=2, cursor="hand2", command=lambda mode=m: self._set_operating_mode(mode)
            )
            btn_m.pack(side="left", padx=2, pady=1)
            self.mode_leds[m] = btn_m
        self._refresh_mode_ui()

        # Right Actions: Clock, Fullscreen, E-Stop, Quit
        right_box = tk.Frame(hdr, bg=self.COLOR_BG)
        right_box.pack(side="right", fill="y")
        self.lbl_clock = tk.Label(right_box, text="--:--:--", font=self.font_sub, fg=self.COLOR_TEXT_SUB, bg=self.COLOR_BG)
        self.lbl_clock.pack(side="left", padx=6)

        # Fullscreen Toggle Button
        tk.Button(
            right_box, text="⛶", font=("Helvetica", 11, "bold"), bg="#E2E8F0", fg=self.COLOR_TEXT_MAIN,
            bd=0, padx=8, pady=2, cursor="hand2", command=self.toggle_fullscreen
        ).pack(side="left", padx=2)

        # Emergency Stop
        tk.Button(
            right_box, text="🛑 E-STOP", font=self.font_body_bold, bg=self.COLOR_DANGER, fg="#FFFFFF",
            bd=0, padx=10, pady=2, cursor="hand2", command=self._on_emergency_stop
        ).pack(side="left", padx=2)

        # Clean Exit Button (Esc equivalent)
        tk.Button(
            right_box, text="✕ EXIT", font=self.font_body_bold, bg="#475569", fg="#FFFFFF",
            bd=0, padx=10, pady=2, cursor="hand2", command=self.exit_application
        ).pack(side="left", padx=2)

    def _set_operating_mode(self, mode: str):
        self.var_mode.set(mode)
        engine.active_mode = mode.upper()
        self._refresh_mode_ui()

    def _refresh_mode_ui(self):
        curr = self.var_mode.get()
        for m, btn in self.mode_leds.items():
            if m == curr:
                btn.config(bg=self.COLOR_PRIMARY, fg="#FFFFFF", font=self.font_body_bold)
            else:
                btn.config(bg="#F1F5F9", fg=self.COLOR_TEXT_SUB, font=self.font_sub)

    # -------------------------------------------------------------------------
    # 2. TOP NAVIGATION BAR
    # -------------------------------------------------------------------------
    def _build_top_nav_bar(self):
        self.topnav_frame = tk.Frame(self, bg=self.COLOR_SURFACE, height=38, bd=1, relief="solid")
        self.topnav_frame.pack(fill="x", side="top", padx=12, pady=2)

        self.btn_top_home = tk.Button(
            self.topnav_frame, text="🏠 MENU", font=self.font_body_bold,
            bg=self.COLOR_PRIMARY_DARK, fg="#FFFFFF", bd=0, padx=12, pady=4,
            cursor="hand2", command=self.go_home
        )
        self.btn_top_home.pack(side="left", padx=4, pady=2)

        self.lbl_crumb_title = tk.Label(
            self.topnav_frame, text="MAIN DASHBOARD", font=self.font_h2,
            fg=self.COLOR_PRIMARY_DARK, bg=self.COLOR_SURFACE
        )
        self.lbl_crumb_title.pack(side="left", padx=8)

        self.tab_buttons = {}
        tab_list = [
            ("monitoring", "📊 Monitoring"),
            ("fertigation", "🧪 Fertigation"),
            ("irrigation", "💧 Irrigation"),
            ("manual", "⚡ Manual"),
            ("data", "📈 Data"),
            ("settings", "⚙️ Settings"),
        ]
        for skey, slbl in reversed(tab_list):
            b = tk.Button(
                self.topnav_frame, text=slbl, font=self.font_sub,
                bg=self.COLOR_SURFACE, fg=self.COLOR_TEXT_MAIN, bd=0, padx=8, pady=3,
                cursor="hand2", command=lambda k=skey: self.show_screen(k)
            )
            b.pack(side="right", padx=1, pady=3)
            self.tab_buttons[skey] = b

    def restart_application(self):
        """Full script restart: safely de-energizes hardware and cleanly re-executes Python."""
        if messagebox.askyesno("Restart Application", "Are you sure you want to fully restart the controller script?"):
            hw.emergency_all_off()
            engine.stop_cycle()
            self.destroy()
            python = sys.executable
            os.execl(python, python, *sys.argv)

    # -------------------------------------------------------------------------
    # 3. FIXED BOTTOM DOCK (RESTART, STATUS, PREV, HOME, NEXT)
    # -------------------------------------------------------------------------
    def _build_bottom_dock(self):
        self.bottom_dock = tk.Frame(self, bg="#0F172A", height=46, bd=0)
        self.bottom_dock.pack(fill="x", side="bottom")

        # BOTTOM-LEFT CORNER: FULL SCRIPT RESTART BUTTON
        self.btn_dock_restart = tk.Button(
            self.bottom_dock, text="🔄 RESTART", font=self.font_body_bold,
            bg="#D97706", fg="#FFFFFF", activebackground="#B45309", activeforeground="#FFFFFF",
            bd=0, padx=14, pady=4, cursor="hand2", command=self.restart_application
        )
        self.btn_dock_restart.pack(side="left", padx=(10, 6), pady=4)

        self.lbl_dock_status = tk.Label(
            self.bottom_dock, text="● Status: System Ready",
            font=self.font_sub, fg="#38BDF8", bg="#0F172A"
        )
        self.lbl_dock_status.pack(side="left", padx=10)

        self.lbl_dock_sim = tk.Label(
            self.bottom_dock, text="HARDWARE MODBUS" if not hw.sim_mode else "SIMULATION MODE",
            font=self.font_sub, fg="#94A3B8", bg="#0F172A"
        )
        self.lbl_dock_sim.pack(side="left", padx=8)

        nav_box = tk.Frame(self.bottom_dock, bg="#0F172A")
        nav_box.pack(side="right", padx=8, pady=4)

        self.btn_dock_prev = tk.Button(
            nav_box, text="◀◀  PREV (<<)", font=self.font_nav_arrow,
            bg=self.COLOR_PRIMARY, fg="#FFFFFF", activebackground=self.COLOR_PRIMARY_DARK,
            bd=0, padx=14, pady=4, cursor="hand2", command=self.go_prev
        )
        self.btn_dock_prev.pack(side="left", padx=4)

        self.btn_dock_home = tk.Button(
            nav_box, text="🏠 MAIN MENU", font=self.font_body_bold,
            bg="#334155", fg="#FFFFFF", activebackground="#475569",
            bd=0, padx=12, pady=4, cursor="hand2", command=self.go_home
        )
        self.btn_dock_home.pack(side="left", padx=4)

        self.btn_dock_next = tk.Button(
            nav_box, text="NEXT (>>)  ▶▶", font=self.font_nav_arrow,
            bg=self.COLOR_PRIMARY, fg="#FFFFFF", activebackground=self.COLOR_PRIMARY_DARK,
            bd=0, padx=14, pady=4, cursor="hand2", command=self.go_next
        )
        self.btn_dock_next.pack(side="left", padx=4)

    def go_prev(self):
        curr = self.current_screen_key
        if curr in SCREEN_SEQUENCE:
            idx = SCREEN_SEQUENCE.index(curr)
            prev_idx = (idx - 1) % len(SCREEN_SEQUENCE)
            self.show_screen(SCREEN_SEQUENCE[prev_idx])

    def go_next(self):
        curr = self.current_screen_key
        if curr in SCREEN_SEQUENCE:
            idx = SCREEN_SEQUENCE.index(curr)
            next_idx = (idx + 1) % len(SCREEN_SEQUENCE)
            self.show_screen(SCREEN_SEQUENCE[next_idx])

    def go_home(self):
        self.show_screen("dashboard")

    def show_screen(self, screen_key: str):
        self.current_screen_key = screen_key
        for k, frame in self.screens.items():
            frame.pack_forget()

        self.lbl_crumb_title.config(text=SCREEN_TITLES.get(screen_key, "INHYDRO AUTOMATION"))

        for k, btn in self.tab_buttons.items():
            if k == screen_key:
                btn.config(bg=self.COLOR_PRIMARY, fg="#FFFFFF", font=self.font_body_bold)
            else:
                btn.config(bg=self.COLOR_SURFACE, fg=self.COLOR_TEXT_MAIN, font=self.font_sub)

        if screen_key in self.screens:
            self.screens[screen_key].pack(fill="both", expand=True)

    # -------------------------------------------------------------------------
    # HELPER: ATTACH TOUCH KEYPAD TO ENTRIES
    # -------------------------------------------------------------------------
    def attach_keypad_to_entry(self, entry_widget: tk.Entry, title: str, is_numeric: bool = True, on_change_callback=None):
        """Opens Touch Keypad whenever the user clicks/taps on an Entry widget."""
        def open_kp(event=None):
            curr_val = entry_widget.get()
            def on_confirm(val):
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, str(val))
                if on_change_callback:
                    on_change_callback(val)
            TouchKeypadModal(self, title, curr_val, on_confirm, is_numeric=is_numeric)

        entry_widget.bind("<Button-1>", open_kp)

    # -------------------------------------------------------------------------
    # SCREEN: MAIN DASHBOARD (6-BUTTON GRID REPRODUCING IMAGE 5)
    # -------------------------------------------------------------------------
    def _create_dashboard_screen(self, parent):
        f = tk.Frame(parent, bg=self.COLOR_BG)

        info_strip = tk.Frame(f, bg="#F8FAFC", bd=1, relief="solid", padx=12, pady=6)
        info_strip.pack(fill="x", pady=(4, 8))

        tk.Label(
            info_strip, 
            text="INHYDRO TOUCH CONTROL SYSTEM  |  SELECT A MODULE OR USE PREV/NEXT", 
            font=self.font_body_bold, 
            fg=self.COLOR_PRIMARY_DARK, 
            bg="#F8FAFC"
        ).pack(side="left")

        self.lbl_dash_status_badge = tk.Label(
            info_strip, text="SYSTEM READY", font=self.font_sub,
            fg="#FFFFFF", bg=self.COLOR_SUCCESS, padx=8, pady=2
        )
        self.lbl_dash_status_badge.pack(side="right")

        grid_frame = tk.Frame(f, bg=self.COLOR_BG)
        grid_frame.pack(fill="both", expand=True, pady=4)

        grid_frame.columnconfigure(0, weight=1, uniform="dash_col")
        grid_frame.columnconfigure(1, weight=1, uniform="dash_col")
        grid_frame.columnconfigure(2, weight=1, uniform="dash_col")
        grid_frame.rowconfigure(0, weight=1, uniform="dash_row")
        grid_frame.rowconfigure(1, weight=1, uniform="dash_row")

        modules = [
            (0, 0, "monitoring", "Monitoring", "Plant P&ID Schematic & Sensors", "📊"),
            (0, 1, "fertigation", "Fertigation", "Crop Recipes, Dosing & EC/pH", "🧪"),
            (0, 2, "irrigation", "Irrigation", "Zone-1 & Zone-2 Water Delivery", "💧"),
            (1, 0, "manual", "Manual Operation", "11-Channel Direct Relay Overrides", "⚡"),
            (1, 1, "data", "Data Record", "Telemetry History & Batch Logs", "📈"),
            (1, 2, "settings", "Settings", "Crop Profiles, Calibration & Ports", "⚙️"),
        ]

        for row, col, skey, title, desc, icon in modules:
            card = tk.Frame(grid_frame, bg="#FFFFFF", bd=0)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

            btn = tk.Button(
                card,
                text=f"{icon}\n\n{title}",
                font=self.font_btn_big,
                fg="#FFFFFF",
                bg=self.COLOR_PRIMARY,
                activebackground=self.COLOR_PRIMARY_DARK,
                activeforeground="#FFFFFF",
                bd=2,
                relief="raised",
                cursor="hand2",
                command=lambda k=skey: self.show_screen(k)
            )
            btn.pack(fill="both", expand=True)

            lbl_desc = tk.Label(card, text=desc, font=self.font_sub, fg=self.COLOR_TEXT_SUB, bg="#FFFFFF")
            lbl_desc.pack(side="bottom", pady=(2, 0))

        return f

    def _add_corner_nav(self, parent_frame):
        bar = tk.Frame(parent_frame, bg=self.COLOR_BG)
        bar.pack(fill="x", side="bottom", pady=(4, 2))

        right_box = tk.Frame(bar, bg=self.COLOR_BG)
        right_box.pack(side="right")

        tk.Button(
            right_box, text="<<", font=("Helvetica", 11, "bold"),
            bg="#E2E8F0", fg=self.COLOR_PRIMARY_DARK, bd=1, relief="solid",
            padx=12, pady=2, cursor="hand2", command=self.go_prev
        ).pack(side="left", padx=3)

        tk.Button(
            right_box, text=">>", font=("Helvetica", 11, "bold"),
            bg="#E2E8F0", fg=self.COLOR_PRIMARY_DARK, bd=1, relief="solid",
            padx=12, pady=2, cursor="hand2", command=self.go_next
        ).pack(side="left", padx=3)

    # -------------------------------------------------------------------------
    # SCREEN 1: MONITORING (P&ID DIAGRAM REPRODUCING IMAGE 4)
    # -------------------------------------------------------------------------
    def _create_monitoring_screen(self, parent):
        f = tk.Frame(parent, bg=self.COLOR_BG)

        top_cards = tk.Frame(f, bg=self.COLOR_BG)
        top_cards.pack(fill="x", pady=(0, 4))

        def make_metric(parent, label, default_val):
            box = tk.Frame(parent, bg=self.COLOR_SURFACE, bd=1, relief="solid", padx=10, pady=4)
            box.pack(side="left", expand=True, fill="both", padx=3)
            tk.Label(box, text=label, font=self.font_sub, fg=self.COLOR_TEXT_SUB, bg=self.COLOR_SURFACE).pack(anchor="w")
            lbl_val = tk.Label(box, text=default_val, font=self.font_big_val, fg=self.COLOR_PRIMARY_DARK, bg=self.COLOR_SURFACE)
            lbl_val.pack(anchor="w")
            return lbl_val

        self.lbl_mon_tank_level = make_metric(top_cards, "TANK LEVEL", "650.0 L (65%)")
        self.lbl_mon_ec = make_metric(top_cards, "EC", "1.85 mS/cm")
        self.lbl_mon_ph = make_metric(top_cards, "pH", "6.05 pH")
        self.lbl_mon_temp = make_metric(top_cards, "WATER TEMP", "24.2 °C")
        self.lbl_mon_flow = make_metric(top_cards, "DELIVERED FLOW", "0.0 L")

        self.pid_canvas = tk.Canvas(f, bg="#FFFFFF", bd=1, relief="solid", highlightthickness=0)
        self.pid_canvas.pack(fill="both", expand=True, pady=2)
        self.pid_canvas.bind("<Configure>", lambda e: self._draw_pid_schematic())

        self._add_corner_nav(f)
        return f

    def _draw_pid_schematic(self):
        c = self.pid_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 100 or h < 100: return

        tanks = ["EC-1 Tank", "EC-2 Tank", "EC-3 Tank", "EC-4 Tank", "PH Tank"]
        valve_keys = [ActuatorMap.EC_VALVE_1, ActuatorMap.EC_VALVE_2, ActuatorMap.EC_VALVE_3, ActuatorMap.EC_VALVE_4, ActuatorMap.PH_VALVE]
        
        spacing = w / 6.5
        y_tank = h * 0.14
        manifold_y = y_tank + 50
        
        c.create_line(spacing * 0.9, manifold_y, spacing * 5.2, manifold_y, width=3, fill="#0284C7")
        c.create_line(spacing * 3.0, manifold_y, spacing * 3.0, h * 0.45, width=3, fill="#0284C7")

        for i, name in enumerate(tanks):
            x = spacing * (i + 1)
            c.create_rectangle(x - 28, y_tank - 30, x + 28, y_tank + 10, fill="#E2E8F0", outline="#94A3B8", width=1.5)
            c.create_text(x, y_tank - 12, text=name, font=("Helvetica", 8, "bold"), fill="#1E293B")
            c.create_line(x, y_tank + 10, x, manifold_y, width=2, fill="#0284C7")

            is_on = hw.get_relay(valve_keys[i])
            valv_color = self.COLOR_SUCCESS if is_on else "#94A3B8"
            c.create_oval(x - 9, manifold_y - 18, x + 9, manifold_y - 2, fill=valv_color, outline="#FFFFFF")
            c.create_text(x, manifold_y - 10, text="ON" if is_on else "OFF", font=("Helvetica", 6, "bold"), fill="#FFFFFF")

        ro_x, ro_y = spacing * 0.8, h * 0.65
        is_ro_on = hw.get_relay(ActuatorMap.RO_WATER_PUMP)
        c.create_oval(ro_x - 16, ro_y - 16, ro_x + 16, ro_y + 16, fill=self.COLOR_SUCCESS if is_ro_on else "#E2E8F0", outline="#0284C7", width=2)
        c.create_text(ro_x, ro_y, text="RO\nPUMP", font=("Helvetica", 7, "bold"), fill="#0F172A")
        c.create_line(ro_x + 16, ro_y, spacing * 2.2, ro_y, width=3, fill="#0284C7")

        tank_cx = spacing * 2.8
        tank_w = 90
        tank_top = h * 0.45
        tank_bot = h * 0.85
        c.create_rectangle(tank_cx - tank_w/2, tank_top, tank_cx + tank_w/2, tank_bot, fill="#F8FAFC", outline="#0369A1", width=2.5)

        pct = max(0.05, min(1.0, hw.pv_tank_percent / 100.0))
        fill_h = (tank_bot - tank_top) * pct
        c.create_rectangle(tank_cx - tank_w/2 + 2, tank_bot - fill_h, tank_cx + tank_w/2 - 2, tank_bot - 2, fill="#BAE6FD", outline="")
        c.create_text(tank_cx, tank_top + 20, text=f"MIXING TANK\n{hw.pv_tank_liters} L\n({hw.pv_tank_percent}%)", font=("Helvetica", 8, "bold"), fill="#0369A1", justify="center")

        pump_x = spacing * 4.0
        pump_y = h * 0.75
        is_main_on = hw.get_relay(ActuatorMap.MAIN_PUMP)
        c.create_line(tank_cx + tank_w/2, tank_bot - 15, pump_x - 16, pump_y, width=3, fill="#0284C7")
        c.create_oval(pump_x - 18, pump_y - 18, pump_x + 18, pump_y + 18, fill=self.COLOR_SUCCESS if is_main_on else "#E2E8F0", outline="#0369A1", width=2)
        c.create_text(pump_x, pump_y, text="MAIN\nPUMP", font=("Helvetica", 7, "bold"), fill="#0F172A")

        is_fert_on = hw.get_relay(ActuatorMap.FERTIGATION_VALVE)
        fert_color = self.COLOR_SUCCESS if is_fert_on else "#94A3B8"
        c.create_line(pump_x + 18, pump_y - 10, pump_x + 45, pump_y - 10, pump_x + 45, tank_top + 10, tank_cx + tank_w/2, tank_top + 10, width=3, fill="#0284C7")
        c.create_rectangle(pump_x + 35, h * 0.55 - 10, pump_x + 55, h * 0.55 + 10, fill=fert_color, outline="#FFFFFF")
        c.create_text(pump_x + 45, h * 0.55, text="FERT", font=("Helvetica", 6, "bold"), fill="#FFFFFF")

        is_irr_on = hw.get_relay(ActuatorMap.IRRIGATION_VALVE)
        irr_color = self.COLOR_SUCCESS if is_irr_on else "#94A3B8"
        c.create_line(pump_x + 18, pump_y + 10, spacing * 5.2, pump_y + 10, width=3, fill="#0284C7")
        c.create_rectangle(spacing * 4.6, pump_y - 2, spacing * 4.9, pump_y + 20, fill=irr_color, outline="#FFFFFF")
        c.create_text(spacing * 4.75, pump_y + 9, text="IRR", font=("Helvetica", 6, "bold"), fill="#FFFFFF")

        z1_y = pump_y - 28
        z2_y = pump_y + 32
        c.create_line(spacing * 5.2, pump_y + 10, spacing * 5.5, z1_y, spacing * 5.9, z1_y, width=3, fill="#0284C7")
        c.create_line(spacing * 5.2, pump_y + 10, spacing * 5.5, z2_y, spacing * 5.9, z2_y, width=3, fill="#0284C7")

        is_z1_on = hw.get_relay(ActuatorMap.ZONE_1_VALVE)
        is_z2_on = hw.get_relay(ActuatorMap.ZONE_2_VALVE)
        c.create_oval(spacing * 5.55 - 10, z1_y - 10, spacing * 5.55 + 10, z1_y + 10, fill=self.COLOR_SUCCESS if is_z1_on else "#94A3B8", outline="#FFFFFF")
        c.create_text(spacing * 5.55, z1_y, text="Z1", font=("Helvetica", 7, "bold"), fill="#FFFFFF")
        c.create_text(spacing * 6.0, z1_y, text="Zone 1", font=self.font_sub, fill="#0F172A", anchor="w")

        c.create_oval(spacing * 5.55 - 10, z2_y - 10, spacing * 5.55 + 10, z2_y + 10, fill=self.COLOR_SUCCESS if is_z2_on else "#94A3B8", outline="#FFFFFF")
        c.create_text(spacing * 5.55, z2_y, text="Z2", font=("Helvetica", 7, "bold"), fill="#FFFFFF")
        c.create_text(spacing * 6.0, z2_y, text="Zone 2", font=self.font_sub, fill="#0F172A", anchor="w")

    # -------------------------------------------------------------------------
    # SCREEN 2: FERTIGATION (REPRODUCING IMAGE 2)
    # -------------------------------------------------------------------------
    def _create_fertigation_screen(self, parent):
        f = tk.Frame(parent, bg=self.COLOR_BG)

        top_bar = tk.Frame(f, bg=self.COLOR_SURFACE, bd=1, relief="solid", padx=10, pady=4)
        top_bar.pack(fill="x", pady=(0, 6))

        tk.Label(top_bar, text="Programm :", font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_SURFACE).pack(side="left", padx=4)

        recipe_names = list(crop_recipes.keys())
        self.combo_fert_recipe = ttk.Combobox(top_bar, values=recipe_names, textvariable=self.var_recipe, font=self.font_body, state="readonly", width=14)
        self.combo_fert_recipe.pack(side="left", padx=6)
        self.combo_fert_recipe.bind("<<ComboboxSelected>>", lambda e: self._load_recipe_into_fert_screen())

        tk.Label(top_bar, text="Tank Level:", font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_SURFACE).pack(side="left", padx=(20, 4))
        self.lbl_fert_tank_l = tk.Label(top_bar, text="0.0 L", font=self.font_body_bold, fg=self.COLOR_PRIMARY_DARK, bg="#E0F2FE", padx=6, pady=1)
        self.lbl_fert_tank_l.pack(side="left")
        self.lbl_fert_tank_pct = tk.Label(top_bar, text="0.0 %", font=self.font_body_bold, fg=self.COLOR_PRIMARY_DARK, bg="#E0F2FE", padx=6, pady=1)
        self.lbl_fert_tank_pct.pack(side="left", padx=3)

        body = tk.Frame(f, bg=self.COLOR_BG)
        body.pack(fill="both", expand=True)

        left_card = tk.LabelFrame(body, text=" Fertigation Recipe & Dosing Volumes (Tap value to edit) ", font=self.font_h2, fg=self.COLOR_PRIMARY_DARK, bg=self.COLOR_BG, bd=1, relief="solid", padx=10, pady=8)
        left_card.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self.entries_dosing = {}
        self.vars_dosing_enable = {}

        dosing_rows = [
            ("ec_valve_1_liters", "EC Valve-1 (Stock A)", ActuatorMap.EC_VALVE_1),
            ("ec_valve_2_liters", "EC Valve-2 (Stock B)", ActuatorMap.EC_VALVE_2),
            ("ec_valve_3_liters", "EC Valve-3 (Stock C)", ActuatorMap.EC_VALVE_3),
            ("ec_valve_4_liters", "EC Valve-4 (Stock D)", ActuatorMap.EC_VALVE_4),
            ("ph_valve_enable",   "PH Valve (Acid/Base)", ActuatorMap.PH_VALVE),
        ]

        for key, title, act_id in dosing_rows:
            row = tk.Frame(left_card, bg=self.COLOR_BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=title, font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_BG, width=20, anchor="w").pack(side="left")

            if key != "ph_valve_enable":
                ent = tk.Entry(row, font=self.font_body_bold, width=7, justify="center", bd=1, relief="solid", bg="#F8FAFC", cursor="hand2")
                ent.pack(side="left", padx=6)
                tk.Label(row, text="L", font=self.font_body, fg=self.COLOR_TEXT_SUB, bg=self.COLOR_BG).pack(side="left")
                self.entries_dosing[key] = ent
                # Attach touch virtual keypad
                self.attach_keypad_to_entry(ent, f"Set {title} Volume (Liters)", is_numeric=True)

            var_en = tk.BooleanVar(value=True)
            chk = tk.Checkbutton(row, text="ENABLED", variable=var_en, font=self.font_sub, fg=self.COLOR_SUCCESS, bg=self.COLOR_BG, activebackground=self.COLOR_BG)
            chk.pack(side="right", padx=6)
            self.vars_dosing_enable[key] = var_en

        feedback_frame = tk.Frame(left_card, bg=self.COLOR_SURFACE, bd=1, relief="solid", padx=8, pady=6)
        feedback_frame.pack(fill="x", pady=(8, 0))

        ec_box = tk.Frame(feedback_frame, bg=self.COLOR_SURFACE)
        ec_box.pack(side="left", expand=True)
        tk.Label(ec_box, text="EC (mS/cm)", font=self.font_body_bold, fg=self.COLOR_PRIMARY_DARK, bg=self.COLOR_SURFACE).pack()
        self.lbl_ec_sv = tk.Label(ec_box, text="SV: 2.20", font=self.font_sub, fg=self.COLOR_TEXT_SUB, bg=self.COLOR_SURFACE)
        self.lbl_ec_sv.pack()
        self.lbl_ec_pv = tk.Label(ec_box, text="PV: 1.85", font=self.font_big_val, fg=self.COLOR_PRIMARY, bg=self.COLOR_SURFACE)
        self.lbl_ec_pv.pack()

        ph_box = tk.Frame(feedback_frame, bg=self.COLOR_SURFACE)
        ph_box.pack(side="right", expand=True)
        tk.Label(ph_box, text="pH Value", font=self.font_body_bold, fg=self.COLOR_PRIMARY_DARK, bg=self.COLOR_SURFACE).pack()
        self.lbl_ph_sv = tk.Label(ph_box, text="SV: 5.80", font=self.font_sub, fg=self.COLOR_TEXT_SUB, bg=self.COLOR_SURFACE)
        self.lbl_ph_sv.pack()
        self.lbl_ph_pv = tk.Label(ph_box, text="PV: 6.05", font=self.font_big_val, fg=self.COLOR_PRIMARY, bg=self.COLOR_SURFACE)
        self.lbl_ph_pv.pack()

        right_card = tk.LabelFrame(body, text=" Hardware Actuator Status ", font=self.font_h2, fg=self.COLOR_PRIMARY_DARK, bg=self.COLOR_BG, bd=1, relief="solid", padx=10, pady=8)
        right_card.pack(side="right", fill="both", expand=True, padx=(4, 0))

        self.fert_act_labels = {}
        for act_id, act_name in [
            (ActuatorMap.FERTIGATION_VALVE, "Fertigation Valve"),
            (ActuatorMap.IRRIGATION_VALVE,  "Irrigation Valve"),
            (ActuatorMap.MAIN_PUMP,         "Main Pump"),
            (ActuatorMap.RO_WATER_PUMP,     "RO Water Pump"),
        ]:
            r_box = tk.Frame(right_card, bg=self.COLOR_SURFACE, bd=1, relief="solid", padx=8, pady=4)
            r_box.pack(fill="x", pady=2)
            tk.Label(r_box, text=act_name, font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_SURFACE).pack(side="left")
            lbl_st = tk.Label(r_box, text="OFF", font=self.font_sub, fg="#FFFFFF", bg="#94A3B8", padx=8, pady=1)
            lbl_st.pack(side="right")
            self.fert_act_labels[act_id] = lbl_st

        btn_action_box = tk.Frame(right_card, bg=self.COLOR_BG)
        btn_action_box.pack(fill="x", side="bottom", pady=4)

        tk.Button(
            btn_action_box, text="📖 Read Recipe", font=self.font_body_bold, bg="#E2E8F0", fg=self.COLOR_TEXT_MAIN,
            bd=0, padx=8, pady=6, cursor="hand2", command=self._load_recipe_into_fert_screen
        ).pack(side="left", expand=True, fill="x", padx=2)

        tk.Button(
            btn_action_box, text="▶ Start Batch", font=self.font_body_bold, bg=self.COLOR_PRIMARY, fg="#FFFFFF",
            bd=0, padx=8, pady=6, cursor="hand2", command=self._on_start_batch
        ).pack(side="left", expand=True, fill="x", padx=2)

        tk.Button(
            btn_action_box, text="↺ Reset", font=self.font_body_bold, bg="#64748B", fg="#FFFFFF",
            bd=0, padx=8, pady=6, cursor="hand2", command=self._on_reset_batch
        ).pack(side="left", expand=True, fill="x", padx=2)

        self._load_recipe_into_fert_screen()
        self._add_corner_nav(f)
        return f

    def _load_recipe_into_fert_screen(self):
        k = self.var_recipe.get()
        recipe = crop_recipes.get(k, DEFAULT_RECIPES["cucumber"])
        for key in ["ec_valve_1_liters", "ec_valve_2_liters", "ec_valve_3_liters", "ec_valve_4_liters"]:
            if key in self.entries_dosing:
                self.entries_dosing[key].delete(0, tk.END)
                self.entries_dosing[key].insert(0, str(recipe.get(key, 0.0)))
        if hasattr(self, "lbl_ec_sv"):
            self.lbl_ec_sv.config(text=f"SV: {recipe.get('target_ec', 2.0):.2f}")
            self.lbl_ph_sv.config(text=f"SV: {recipe.get('target_ph', 5.8):.2f}")

    def _on_start_batch(self):
        if engine.is_running:
            messagebox.showinfo("Process Busy", "A cycle is already in progress!")
            return
        engine.start_cycle(self.var_mode.get(), self.var_recipe.get())

    def _on_reset_batch(self):
        engine.stop_cycle()

    # -------------------------------------------------------------------------
    # SCREEN 3: IRRIGATION (REPRODUCING IMAGE 1)
    # -------------------------------------------------------------------------
    def _create_irrigation_screen(self, parent):
        f = tk.Frame(parent, bg=self.COLOR_BG)

        top_bar = tk.Frame(f, bg=self.COLOR_SURFACE, bd=1, relief="solid", padx=10, pady=4)
        top_bar.pack(fill="x", pady=(0, 6))

        tk.Label(top_bar, text="Programm :", font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_SURFACE).pack(side="left", padx=4)
        tk.Label(top_bar, textvariable=self.var_recipe, font=self.font_body_bold, fg=self.COLOR_PRIMARY_DARK, bg="#E0F2FE", padx=6).pack(side="left")

        tk.Label(top_bar, text="Tank Level:", font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_SURFACE).pack(side="left", padx=(16, 4))
        self.lbl_irr_tank = tk.Label(top_bar, text="650.0 L (65%)", font=self.font_body_bold, fg=self.COLOR_PRIMARY_DARK, bg="#E0F2FE", padx=6)
        self.lbl_irr_tank.pack(side="left")

        tk.Label(top_bar, text="Total Flow:", font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_SURFACE).pack(side="left", padx=(16, 4))
        self.lbl_irr_total_flow = tk.Label(top_bar, text="0.0 L", font=self.font_body_bold, fg=self.COLOR_SUCCESS, bg="#ECFDF5", padx=6)
        self.lbl_irr_total_flow.pack(side="left")

        body = tk.Frame(f, bg=self.COLOR_BG)
        body.pack(fill="both", expand=True)

        left_card = tk.LabelFrame(body, text=" Irrigation Field Zones (Tap value to edit) ", font=self.font_h2, fg=self.COLOR_PRIMARY_DARK, bg=self.COLOR_BG, bd=1, relief="solid", padx=10, pady=8)
        left_card.pack(side="left", fill="both", expand=True, padx=(0, 4))

        for z_name in ["Zone-1 Valve", "Zone-2 Valve"]:
            z_box = tk.Frame(left_card, bg=self.COLOR_SURFACE, bd=1, relief="solid", padx=10, pady=8)
            z_box.pack(fill="x", pady=4)
            tk.Label(z_box, text=z_name, font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_SURFACE, width=14, anchor="w").pack(side="left")
            ent = tk.Entry(z_box, font=self.font_body_bold, width=7, justify="center", bd=1, relief="solid", bg="#F8FAFC", cursor="hand2")
            ent.insert(0, "300")
            ent.pack(side="left", padx=6)
            tk.Label(z_box, text="Liters", font=self.font_body, fg=self.COLOR_TEXT_SUB, bg=self.COLOR_SURFACE).pack(side="left")
            self.attach_keypad_to_entry(ent, f"Set {z_name} Target Volume (Liters)", is_numeric=True)

        right_card = tk.LabelFrame(body, text=" Hydraulic Circuit Status ", font=self.font_h2, fg=self.COLOR_PRIMARY_DARK, bg=self.COLOR_BG, bd=1, relief="solid", padx=10, pady=8)
        right_card.pack(side="right", fill="both", expand=True, padx=(4, 0))

        self.irr_act_labels = {}
        for act_id, act_name in [
            (ActuatorMap.FERTIGATION_VALVE, "Fertigation Valve"),
            (ActuatorMap.IRRIGATION_VALVE,  "Irrigation Valve"),
            (ActuatorMap.MAIN_PUMP,         "Main Pump"),
            (ActuatorMap.RO_WATER_PUMP,     "RO Water Pump"),
        ]:
            r_box = tk.Frame(right_card, bg=self.COLOR_SURFACE, bd=1, relief="solid", padx=8, pady=4)
            r_box.pack(fill="x", pady=2)
            tk.Label(r_box, text=act_name, font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_SURFACE).pack(side="left")
            lbl_st = tk.Label(r_box, text="OFF", font=self.font_sub, fg="#FFFFFF", bg="#94A3B8", padx=8, pady=1)
            lbl_st.pack(side="right")
            self.irr_act_labels[act_id] = lbl_st

        btn_box = tk.Frame(right_card, bg=self.COLOR_BG)
        btn_box.pack(fill="x", side="bottom", pady=4)

        tk.Button(
            btn_box, text="▶ Start Irrigation", font=self.font_body_bold, bg=self.COLOR_PRIMARY, fg="#FFFFFF",
            bd=0, padx=8, pady=6, cursor="hand2", command=self._on_start_batch
        ).pack(side="left", expand=True, fill="x", padx=2)

        tk.Button(
            btn_box, text="↺ Reset Counters", font=self.font_body_bold, bg="#64748B", fg="#FFFFFF",
            bd=0, padx=8, pady=6, cursor="hand2", command=lambda: setattr(hw, "pv_total_flow", 0.0)
        ).pack(side="left", expand=True, fill="x", padx=2)

        self._add_corner_nav(f)
        return f

    # -------------------------------------------------------------------------
    # SCREEN 4: MANUAL OPERATION (11 TACTILE FUNCTIONAL BUTTONS)
    # -------------------------------------------------------------------------
    def _create_manual_screen(self, parent):
        f = tk.Frame(parent, bg=self.COLOR_BG)

        grid_box = tk.Frame(f, bg=self.COLOR_BG)
        grid_box.pack(fill="both", expand=True)

        col_left = tk.Frame(grid_box, bg=self.COLOR_BG)
        col_left.pack(side="left", fill="both", expand=True, padx=(0, 4))

        col_right = tk.Frame(grid_box, bg=self.COLOR_BG)
        col_right.pack(side="right", fill="both", expand=True, padx=(4, 0))

        left_acts = [
            (ActuatorMap.FERTIGATION_VALVE, "Fertigation Valve"),
            (ActuatorMap.EC_VALVE_1,        "EC Valve-1"),
            (ActuatorMap.EC_VALVE_2,        "EC Valve-2"),
            (ActuatorMap.EC_VALVE_3,        "EC Valve-3"),
            (ActuatorMap.EC_VALVE_4,        "EC Valve-4"),
            (ActuatorMap.PH_VALVE,          "PH Valve"),
        ]

        right_acts = [
            (ActuatorMap.IRRIGATION_VALVE,  "Irrigation Valve"),
            (ActuatorMap.ZONE_1_VALVE,      "Zone-1 Valve"),
            (ActuatorMap.ZONE_2_VALVE,      "Zone-2 Valve"),
            (ActuatorMap.RO_WATER_PUMP,     "RO Water Pump"),
            (ActuatorMap.MAIN_PUMP,         "Main Pump"),
        ]

        self.manual_buttons = {}

        def build_switch_card(parent, act_id, act_name):
            card = tk.Frame(parent, bg=self.COLOR_SURFACE, bd=1, relief="solid", padx=10, pady=4)
            card.pack(fill="x", pady=2)
            tk.Label(card, text=act_name, font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_SURFACE).pack(side="left")
            btn = tk.Button(
                card, text="OFF", font=self.font_body_bold, bg="#94A3B8", fg="#FFFFFF",
                bd=0, padx=14, pady=3, cursor="hand2", command=lambda a=act_id: self._toggle_manual_relay(a)
            )
            btn.pack(side="right")
            self.manual_buttons[act_id] = btn

        for act_id, name in left_acts: build_switch_card(col_left, act_id, name)
        for act_id, name in right_acts: build_switch_card(col_right, act_id, name)

        self._add_corner_nav(f)
        return f

    def _toggle_manual_relay(self, act_id: int):
        new_st = not hw.get_relay(act_id)
        hw.set_relay(act_id, new_st)
        self._refresh_manual_buttons()

    def _refresh_manual_buttons(self):
        for act_id, btn in self.manual_buttons.items():
            st = hw.get_relay(act_id)
            if st: btn.config(text="ON", bg=self.COLOR_SUCCESS)
            else: btn.config(text="OFF", bg="#94A3B8")

    # -------------------------------------------------------------------------
    # SCREEN 5: DATA RECORD & TELEMETRY LOGS
    # -------------------------------------------------------------------------
    def _create_data_screen(self, parent):
        f = tk.Frame(parent, bg=self.COLOR_BG)

        cols = ("Time", "Recipe", "Delivered Volume", "EC (mS/cm)", "pH", "Status")
        self.tree_batches = ttk.Treeview(f, columns=cols, show="headings", height=10)
        for c in cols:
            self.tree_batches.heading(c, text=c)
            self.tree_batches.column(c, width=120, anchor="center")
        self.tree_batches.pack(fill="both", expand=True, pady=4)

        self._refresh_batch_tree()

        btn_box = tk.Frame(f, bg=self.COLOR_BG)
        btn_box.pack(fill="x", pady=2)
        tk.Button(btn_box, text="🔄 Refresh Logs", font=self.font_sub, bg=self.COLOR_PRIMARY, fg="#FFFFFF", bd=0, padx=12, pady=4, command=self._refresh_batch_tree).pack(side="left")

        self._add_corner_nav(f)
        return f

    def _refresh_batch_tree(self):
        if not hasattr(self, "tree_batches"): return
        for item in self.tree_batches.get_children():
            self.tree_batches.delete(item)
        for b in engine.recent_batches:
            self.tree_batches.insert("", "end", values=(b["time"], b["recipe"], b["volume"], b["ec"], b["ph"], b["status"]))

    # -------------------------------------------------------------------------
    # SCREEN 6: SETTINGS & RECIPES
    # -------------------------------------------------------------------------
    def _create_settings_screen(self, parent):
        f = tk.Frame(parent, bg=self.COLOR_BG)

        nb = ttk.Notebook(f)
        nb.pack(fill="both", expand=True)

        tab_recipe = tk.Frame(nb, bg=self.COLOR_BG, padx=10, pady=8)
        tab_modbus = tk.Frame(nb, bg=self.COLOR_BG, padx=10, pady=8)
        nb.add(tab_recipe, text="🌱 Crop Profiles (Tap any value to edit)")
        nb.add(tab_modbus, text="🔌 RS485 Modbus Setup")

        # Tab 1: Recipe Settings
        rec_table = tk.Frame(tab_recipe, bg=self.COLOR_BG)
        rec_table.pack(fill="both", expand=True)
        self.recipe_inputs = {}

        for crop_key, crop_data in crop_recipes.items():
            card = tk.LabelFrame(rec_table, text=f" {crop_data['crop_name']} ", font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_SURFACE, bd=1, relief="solid", padx=8, pady=4)
            card.pack(fill="x", pady=3)
            row = tk.Frame(card, bg=self.COLOR_SURFACE)
            row.pack(fill="x")

            def add_field(parent, label, val, is_num=True):
                tk.Label(parent, text=label, font=self.font_sub, fg=self.COLOR_TEXT_SUB, bg=self.COLOR_SURFACE).pack(side="left", padx=3)
                e = tk.Entry(parent, font=self.font_sub, width=6, justify="center", bd=1, relief="solid", bg="#FFFFFF", cursor="hand2")
                e.insert(0, str(val))
                e.pack(side="left", padx=2)
                self.attach_keypad_to_entry(e, f"Edit {crop_data['crop_name']}: {label}", is_numeric=is_num)
                return e

            e_ec = add_field(row, "EC:", crop_data.get("target_ec", 2.0))
            e_ph = add_field(row, "pH:", crop_data.get("target_ph", 5.8))
            e_mix = add_field(row, "Mix(s):", crop_data.get("mixing_time_sec", 30))
            e_z1 = add_field(row, "Zone1(L):", crop_data.get("zone_1_liters", 300))
            e_z2 = add_field(row, "Zone2(L):", crop_data.get("zone_2_liters", 300))
            self.recipe_inputs[crop_key] = {"ec": e_ec, "ph": e_ph, "mix": e_mix, "z1": e_z1, "z2": e_z2}

        tk.Button(tab_recipe, text="💾 Save Profiles", font=self.font_body_bold, bg=self.COLOR_PRIMARY, fg="#FFFFFF", bd=0, padx=14, pady=6, cursor="hand2", command=self._save_recipes_from_screen).pack(side="right", pady=4)

        # Tab 2: Modbus Settings
        fields = [
            ("serial_port_relay", "Relay USB Port:", system_config.get("serial_port_relay", "/dev/ttyUSB0"), False),
            ("relay_slave_id", "Relay Slave ID:", str(system_config.get("relay_slave_id", 1)), True),
            ("relay_baudrate", "Baud Rate:", str(system_config.get("relay_baudrate", 9600)), True),
        ]
        self.modbus_inputs = {}
        for key, lbl_text, default_v, is_num in fields:
            f_row = tk.Frame(tab_modbus, bg=self.COLOR_BG)
            f_row.pack(fill="x", pady=3)
            tk.Label(f_row, text=lbl_text, font=self.font_body_bold, fg=self.COLOR_TEXT_MAIN, bg=self.COLOR_BG, width=18, anchor="w").pack(side="left")
            e = tk.Entry(f_row, font=self.font_body, width=22, bd=1, relief="solid", bg="#F8FAFC", cursor="hand2")
            e.insert(0, default_v)
            e.pack(side="left", padx=6)
            self.attach_keypad_to_entry(e, f"Edit {lbl_text}", is_numeric=is_num)
            self.modbus_inputs[key] = e

        tk.Button(tab_modbus, text="💾 Save Configuration", font=self.font_body_bold, bg=self.COLOR_PRIMARY, fg="#FFFFFF", bd=0, padx=14, pady=6, cursor="hand2", command=self._save_config_from_screen).pack(side="left", pady=10)

        self._add_corner_nav(f)
        return f

    def _save_recipes_from_screen(self):
        try:
            for k, inputs in self.recipe_inputs.items():
                if k in crop_recipes:
                    crop_recipes[k]["target_ec"] = float(inputs["ec"].get())
                    crop_recipes[k]["target_ph"] = float(inputs["ph"].get())
                    crop_recipes[k]["mixing_time_sec"] = int(inputs["mix"].get())
                    crop_recipes[k]["zone_1_liters"] = float(inputs["z1"].get())
                    crop_recipes[k]["zone_2_liters"] = float(inputs["z2"].get())
            save_json(RECIPE_FILE, crop_recipes)
            messagebox.showinfo("Saved", "Crop recipes saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Invalid values: {e}")

    def _save_config_from_screen(self):
        try:
            for k, inp in self.modbus_inputs.items():
                val = inp.get()
                if val.isdigit(): system_config[k] = int(val)
                elif val.replace(".", "", 1).isdigit(): system_config[k] = float(val)
                else: system_config[k] = val
            save_json(CONFIG_FILE, system_config)
            messagebox.showinfo("Saved", "Configuration saved!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def _on_emergency_stop(self):
        engine.stop_cycle()
        messagebox.showwarning("EMERGENCY STOP", "All pumps and valves have been forced OFF immediately!")

    # -------------------------------------------------------------------------
    # PERIODIC UPDATE LOOP
    # -------------------------------------------------------------------------
    def _periodic_tick(self):
        hw.simulate_step(0.1)

        now_str = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        self.lbl_clock.config(text=now_str)

        self.lbl_dock_status.config(text=f"● Process: {engine.state}  |  {engine.status_msg}")

        if hasattr(self, "lbl_mon_tank_level"):
            self.lbl_mon_tank_level.config(text=f"{hw.pv_tank_liters} L ({hw.pv_tank_percent}%)")
            self.lbl_mon_ec.config(text=f"{hw.pv_ec:.2f} mS/cm")
            self.lbl_mon_ph.config(text=f"{hw.pv_ph:.2f}")
            self.lbl_mon_temp.config(text=f"{hw.pv_water_temp:.1f} °C")
            self.lbl_mon_flow.config(text=f"{hw.pv_total_flow:.1f} L")

        if hasattr(self, "lbl_fert_tank_l"):
            self.lbl_fert_tank_l.config(text=f"{hw.pv_tank_liters} L")
            self.lbl_fert_tank_pct.config(text=f"{hw.pv_tank_percent} %")
            self.lbl_ec_pv.config(text=f"PV: {hw.pv_ec:.2f}")
            self.lbl_ph_pv.config(text=f"PV: {hw.pv_ph:.2f}")
            for act_id, lbl in self.fert_act_labels.items():
                st = hw.get_relay(act_id)
                lbl.config(text="ON" if st else "OFF", bg=self.COLOR_SUCCESS if st else "#94A3B8")

        if hasattr(self, "lbl_irr_tank"):
            self.lbl_irr_tank.config(text=f"{hw.pv_tank_liters} L ({hw.pv_tank_percent}%)")
            self.lbl_irr_total_flow.config(text=f"{hw.pv_total_flow:.1f} L")
            for act_id, lbl in self.irr_act_labels.items():
                st = hw.get_relay(act_id)
                lbl.config(text="ON" if st else "OFF", bg=self.COLOR_SUCCESS if st else "#94A3B8")

        if hasattr(self, "manual_buttons"):
            self._refresh_manual_buttons()

        if hasattr(self, "lbl_dash_status_badge"):
            if engine.is_running:
                self.lbl_dash_status_badge.config(text=f"ACTIVE: {engine.state}", bg=self.COLOR_PRIMARY)
            else:
                self.lbl_dash_status_badge.config(text="SYSTEM READY", bg=self.COLOR_SUCCESS)

        if hasattr(self, "pid_canvas") and self.pid_canvas.winfo_ismapped():
            self._draw_pid_schematic()

        self.after(100, self._periodic_tick)

# -----------------------------------------------------------------------------
# APPLICATION ENTRYPOINT
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app = InHydroFertigationApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        hw.emergency_all_off()
        sys.exit(0)
