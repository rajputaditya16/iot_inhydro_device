#!/usr/bin/env python3
"""
===============================================================================
INHYDRO AUTOMATION - FERTIGATION & CYCLIC IRRIGATION CYCLE CONTROLLER
===============================================================================
Optimized for 7-inch Touchscreen Display (1024x600 Resolution).
Styling & UI grids matching itc_polyhouse_controller.py & cold1.py.
Features:
- Completely removed all liters/volume measurement features and UI.
- Single Zone Irrigation (Zone 1 only; no secondary zone).
- Fullscreen Keyboards based on cold1.py (make_modal_fullscreen):
    * Numeric mode (Digits, decimal, minus, plus, colon, DEL, CLEAR, SAVE, CANCEL).
    * Alphanumeric mode (QWERTY layout for changing crop & timer names).
    * Time mode with quick presets.
- Real-time EC, pH & 10 Valve Status Badges in High-Contrast Colors.
- 5-Venturi Deficit Dosing with Individual Safety (+ / -) Decimal Cutoffs.
- Automated Cyclic Irrigation Timer for Single Irrigation Zone.
- Bottom-Left Functional Script Restart Button.
===============================================================================
"""

import os
import sys
import time
import json
import datetime
import threading
import queue
import tkinter as tk
from tkinter import font, messagebox, ttk
from typing import Optional, Dict, Any

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
RECIPE_FILE = os.path.join(BASE_DIR, "crop_recipes.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config_system.json")
TIMERS_FILE = os.path.join(BASE_DIR, "config_irrigation_timers.json")
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")

# -----------------------------------------------------------------------------
# HARDWARE PORTS & CHANNELS MAPPING (SINGLE ZONE)
# -----------------------------------------------------------------------------
SERIAL_PORT_RELAY = "/dev/serial/by-path/usb-0:1:2:1:0-port0"
RELAY_SLAVE_ID    = 1
RELAY_BAUDRATE    = 9600

SERIAL_PORT_WATER_1 = "/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.0-port0"
DEVICE_ID_EC1 = 31
DEVICE_ID_PH1 = 32

class ActuatorMap:
    EC_VALVE_1              = 1   # S.V 1 (EC 1 - Stock A: Calcium Nitrate / Iron)
    EC_VALVE_2              = 2   # S.V 2 (EC 2 - Stock B: NPK / Magnesium Sulphate)
    EC_VALVE_3              = 3   # S.V 3 (EC 3 - Stock C: Micronutrients)
    EC_VALVE_4              = 4   # S.V 4 (EC 4 - Stock D: Booster / Silica)
    PH_VALVE                = 5   # S.V 5 (pH Down: Acid Solution)
    RO_WATER_PUMP           = 6   # Pump 6 (RO Fresh Water Makeup Pump)
    TANK_RETURN_VALVE       = 7   # S.V 7 (Tank Return Loop Valve)
    MAIN_PUMP               = 8   # Pump 8 (1.5 HP Main Circulation & Delivery Pump)
    PUMP_OUTLET_VALVE       = 9   # S.V 9 (Pump Discharge / Main Line Valve)
    FERTIGATION_LOOP_VALVE  = 10  # S.V 10 (Recirculation Venturi Manifold Valve)
    IRRIGATION_MASTER_VALVE = 11  # S.V 11 (Irrigation Field Master Diverter Valve)
    ZONE_1_VALVE            = 12  # S.V 12 (Zone 1 Field Delivery Valve)
    ZONE_2_VALVE            = 13  # S.V 13 (Zone 2 Field Delivery Valve)

    # Aliases
    FERTIGATION_VALVE = FERTIGATION_LOOP_VALVE
    IRRIGATION_VALVE  = IRRIGATION_MASTER_VALVE
    ZONE_VALVE        = ZONE_1_VALVE

ACTUATOR_LABELS = {
    1:  "EC1",
    2:  "EC2",
    3:  "EC3",
    4:  "EC4",
    5:  "pH",
    6:  "RO Pump",
    7:  "S.V 7",
    8:  "Main Pump",
    9:  "S.V 9",
    10: "S.V 10",
    11: "S.V 11",
    12: "Zone 1",
    13: "Zone 2",
}

# -----------------------------------------------------------------------------
# MULTI-CROP DEFAULT RECIPES (NO LITERS)
# -----------------------------------------------------------------------------
DEFAULT_RECIPES = {
    "tomato": {
        "crop_name": "Tomato",
        "target_ec": 2.50, "target_ph": 6.00,
        "ec_tolerance": 0.15, "ph_tolerance": 0.20,
        "v1_ratio": 1.0, "v1_safety_up": 0.15, "v1_safety_down": -0.20,
        "v2_ratio": 1.0, "v2_safety_up": 0.15, "v2_safety_down": -0.20,
        "v3_ratio": 0.4, "v3_safety_up": 0.10, "v3_safety_down": -0.15,
        "v4_ratio": 0.1, "v4_safety_up": 0.05, "v4_safety_down": -0.10,
        "v5_ratio": 1.0, "v5_safety_up": 0.20, "v5_safety_down": -0.15,
        "mixing_time_sec": 30
    },
    "cucumber": {
        "crop_name": "Cucumber",
        "target_ec": 2.20, "target_ph": 5.80,
        "ec_tolerance": 0.10, "ph_tolerance": 0.20,
        "v1_ratio": 1.0, "v1_safety_up": 0.15, "v1_safety_down": -0.20,
        "v2_ratio": 1.0, "v2_safety_up": 0.15, "v2_safety_down": -0.20,
        "v3_ratio": 0.3, "v3_safety_up": 0.10, "v3_safety_down": -0.15,
        "v4_ratio": 0.0, "v4_safety_up": 0.05, "v4_safety_down": -0.10,
        "v5_ratio": 1.0, "v5_safety_up": 0.20, "v5_safety_down": -0.15,
        "mixing_time_sec": 30
    },
    "capsicum": {
        "crop_name": "Capsicum / Bell Pepper",
        "target_ec": 2.00, "target_ph": 6.20,
        "ec_tolerance": 0.10, "ph_tolerance": 0.20,
        "v1_ratio": 1.0, "v1_safety_up": 0.15, "v1_safety_down": -0.20,
        "v2_ratio": 1.0, "v2_safety_up": 0.15, "v2_safety_down": -0.20,
        "v3_ratio": 0.3, "v3_safety_up": 0.10, "v3_safety_down": -0.15,
        "v4_ratio": 0.0, "v4_safety_up": 0.05, "v4_safety_down": -0.10,
        "v5_ratio": 1.0, "v5_safety_up": 0.20, "v5_safety_down": -0.15,
        "mixing_time_sec": 30
    },
    "strawberry": {
        "crop_name": "Strawberry",
        "target_ec": 1.60, "target_ph": 5.70,
        "ec_tolerance": 0.10, "ph_tolerance": 0.15,
        "v1_ratio": 0.8, "v1_safety_up": 0.10, "v1_safety_down": -0.15,
        "v2_ratio": 0.8, "v2_safety_up": 0.10, "v2_safety_down": -0.15,
        "v3_ratio": 0.2, "v3_safety_up": 0.08, "v3_safety_down": -0.12,
        "v4_ratio": 0.0, "v4_safety_up": 0.05, "v4_safety_down": -0.10,
        "v5_ratio": 1.0, "v5_safety_up": 0.15, "v5_safety_down": -0.15,
        "mixing_time_sec": 25
    },
    "lettuce": {
        "crop_name": "Lettuce / Leafy Greens",
        "target_ec": 1.40, "target_ph": 5.80,
        "ec_tolerance": 0.10, "ph_tolerance": 0.15,
        "v1_ratio": 0.7, "v1_safety_up": 0.10, "v1_safety_down": -0.15,
        "v2_ratio": 0.7, "v2_safety_up": 0.10, "v2_safety_down": -0.15,
        "v3_ratio": 0.2, "v3_safety_up": 0.08, "v3_safety_down": -0.12,
        "v4_ratio": 0.0, "v4_safety_up": 0.05, "v4_safety_down": -0.10,
        "v5_ratio": 0.8, "v5_safety_up": 0.15, "v5_safety_down": -0.15,
        "mixing_time_sec": 20
    }
}

DEFAULT_CYCLIC_TIMER = {
    "name": "Field Irrigation Drip Line",
    "enabled": True,
    "start_time": "06:00",
    "stop_time": "18:00",
    "on_min": 5.0,
    "off_min": 15.0
}

def load_json(filepath, default_data):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            pass
    save_json(filepath, default_data)
    return dict(default_data)

def save_json(filepath, data):
    try:
        tmp = filepath + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=4)
        os.replace(tmp, filepath)
    except Exception:
        pass

crop_recipes = load_json(RECIPE_FILE, DEFAULT_RECIPES)
cyclic_timer_cfg = load_json(TIMERS_FILE, DEFAULT_CYCLIC_TIMER)

# -----------------------------------------------------------------------------
# MODBUS RELAY COMMAND QUEUE & WORKER
# -----------------------------------------------------------------------------
relay_cmd_queue = queue.Queue()
active_relay_states = {ch: False for ch in range(1, 14)}

def relay_worker_loop():
    while True:
        try:
            cmd = relay_cmd_queue.get()
            if cmd is None:
                break
            channel, state = cmd
            active_relay_states[channel] = state
            inst = None
            try:
                if MODBUS_AVAILABLE and os.path.exists(SERIAL_PORT_RELAY) and not os.path.isdir(SERIAL_PORT_RELAY):
                    inst = minimalmodbus.Instrument(SERIAL_PORT_RELAY, RELAY_SLAVE_ID)
                    inst.serial.baudrate = RELAY_BAUDRATE
                    inst.serial.timeout = 0.2
                    inst.mode = minimalmodbus.MODE_RTU
                    inst.clear_buffers_before_each_transaction = True
                    inst.write_bit(channel - 1, 1 if state else 0, functioncode=5)
            except Exception:
                pass
            finally:
                if inst and hasattr(inst, "serial") and inst.serial and getattr(inst.serial, "is_open", False):
                    try: inst.serial.close()
                    except Exception: pass
            relay_cmd_queue.task_done()
        except Exception:
            pass

threading.Thread(target=relay_worker_loop, daemon=True).start()

def set_relay(channel: int, state: bool):
    relay_cmd_queue.put((channel, state))

def all_relays_off():
    for ch in range(1, 14):
        set_relay(ch, False)

all_relays_off()

# -----------------------------------------------------------------------------
# SENSORS & SIMULATION
# -----------------------------------------------------------------------------
sensor_live_data = {
    "ec": 0.60,
    "ph": 7.20,
    "is_real_sensor": False
}

def read_modbus_ec(port: str, slave_id: int) -> Optional[float]:
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
                return round(raw_ec / 1000.0, 3)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        if inst and hasattr(inst, "serial") and inst.serial and getattr(inst.serial, "is_open", False):
            try: inst.serial.close()
            except Exception: pass
    return None

def read_modbus_ph(port: str, slave_id: int) -> Optional[float]:
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
                return round(data[2] / 100.0, 2)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        if inst and hasattr(inst, "serial") and inst.serial and getattr(inst.serial, "is_open", False):
            try: inst.serial.close()
            except Exception: pass
    return None

def sensor_worker_loop():
    while True:
        try:
            real_ec = read_modbus_ec(SERIAL_PORT_WATER_1, DEVICE_ID_EC1)
            time.sleep(0.08)
            real_ph = read_modbus_ph(SERIAL_PORT_WATER_1, DEVICE_ID_PH1)
            if real_ec is not None or real_ph is not None:
                sensor_live_data["is_real_sensor"] = True
                if real_ec is not None: sensor_live_data["ec"] = real_ec
                if real_ph is not None: sensor_live_data["ph"] = real_ph
            else:
                sensor_live_data["is_real_sensor"] = False
                if active_relay_states.get(ActuatorMap.EC_VALVE_1):
                    sensor_live_data["ec"] = min(4.5, round(sensor_live_data["ec"] + 0.04, 3))
                if active_relay_states.get(ActuatorMap.EC_VALVE_2):
                    sensor_live_data["ec"] = min(4.5, round(sensor_live_data["ec"] + 0.04, 3))
                if active_relay_states.get(ActuatorMap.EC_VALVE_3):
                    sensor_live_data["ec"] = min(4.5, round(sensor_live_data["ec"] + 0.015, 3))
                if active_relay_states.get(ActuatorMap.EC_VALVE_4):
                    sensor_live_data["ec"] = min(4.5, round(sensor_live_data["ec"] + 0.008, 3))
                if active_relay_states.get(ActuatorMap.PH_VALVE):
                    sensor_live_data["ph"] = max(4.5, round(sensor_live_data["ph"] - 0.03, 2))
                if active_relay_states.get(ActuatorMap.RO_WATER_PUMP):
                    sensor_live_data["ec"] = max(0.40, round(sensor_live_data["ec"] - 0.02, 3))
                    sensor_live_data["ph"] = min(7.50, round(sensor_live_data["ph"] + 0.01, 2))
        except Exception:
            pass
        time.sleep(0.3)

threading.Thread(target=sensor_worker_loop, daemon=True).start()

# -----------------------------------------------------------------------------
# CYCLIC IRRIGATION (SINGLE ZONE)
# -----------------------------------------------------------------------------
class CyclicIrrigationController:
    def __init__(self):
        self.timer_state = {"state": "OFF", "last_toggle": 0.0, "time_left": 0.0}

    def stop_all(self):
        self.timer_state["state"] = "OFF"
        self.timer_state["last_toggle"] = 0.0
        self.timer_state["time_left"] = 0.0
        set_relay(ActuatorMap.ZONE_1_VALVE, False)
        set_relay(ActuatorMap.ZONE_2_VALVE, False)
        set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
        set_relay(ActuatorMap.RO_WATER_PUMP, False)
        if not engine.is_running:
            set_relay(ActuatorMap.PUMP_OUTLET_VALVE, False)
            set_relay(ActuatorMap.MAIN_PUMP, False)

    def process_tick(self):
        if engine.is_running:
            return

        cfg = cyclic_timer_cfg
        if not cfg.get("enabled", True):
            self.timer_state["state"] = "DISABLED"
            set_relay(ActuatorMap.ZONE_1_VALVE, False)
            set_relay(ActuatorMap.ZONE_2_VALVE, False)
            set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
            set_relay(ActuatorMap.RO_WATER_PUMP, False)
            return

        now_dt = datetime.datetime.now()
        cur_time = now_dt.time()
        now_sec = time.time()

        try:
            t_start = datetime.datetime.strptime(cfg.get("start_time", "06:00"), "%H:%M").time()
            t_stop  = datetime.datetime.strptime(cfg.get("stop_time", "18:00"), "%H:%M").time()
        except Exception:
            t_start = datetime.time(0, 0)
            t_stop  = datetime.time(23, 59)

        in_window = (t_start <= cur_time <= t_stop) if t_start <= t_stop else (cur_time >= t_start or cur_time <= t_stop)

        on_sec = float(cfg.get("on_min", 5.0)) * 60.0
        off_sec = float(cfg.get("off_min", 15.0)) * 60.0
        ts = self.timer_state

        if in_window:
            if ts["state"] in ["OFF", "WINDOW_CLOSED", "DISABLED"]:
                if ts["last_toggle"] == 0.0 or (now_sec - ts["last_toggle"] >= off_sec):
                    ts["state"] = "ON"
                    ts["last_toggle"] = now_sec
                    # RO Water Cyclic Irrigation: RO Pump ON (6), S.V 11 ON (11), Zone 1 ON (12)
                    set_relay(ActuatorMap.RO_WATER_PUMP, True)           # 6 RO PUMP ON
                    set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, True) # 11 S.V 11 ON
                    set_relay(ActuatorMap.ZONE_1_VALVE, True)            # 12 Zone 1 ON
                    set_relay(ActuatorMap.MAIN_PUMP, False)              # 8 MAIN PUMP STRICTLY OFF
                    set_relay(ActuatorMap.PUMP_OUTLET_VALVE, False)      # 9 OFF
                    set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, False) # 10 OFF
                    set_relay(ActuatorMap.TANK_RETURN_VALVE, False)      # 7 OFF
                else:
                    ts["state"] = "OFF"
                    set_relay(ActuatorMap.ZONE_1_VALVE, False)
                    set_relay(ActuatorMap.ZONE_2_VALVE, False)
                    set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
                    set_relay(ActuatorMap.RO_WATER_PUMP, False)
            elif ts["state"] == "ON":
                if now_sec - ts["last_toggle"] >= on_sec:
                    ts["state"] = "OFF"
                    ts["last_toggle"] = now_sec
                    set_relay(ActuatorMap.ZONE_1_VALVE, False)
                    set_relay(ActuatorMap.ZONE_2_VALVE, False)
                    set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
                    set_relay(ActuatorMap.RO_WATER_PUMP, False)
                else:
                    set_relay(ActuatorMap.RO_WATER_PUMP, True)
                    set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, True)
                    set_relay(ActuatorMap.ZONE_1_VALVE, True)
                    set_relay(ActuatorMap.MAIN_PUMP, False)

            dur = on_sec if ts["state"] == "ON" else off_sec
            ts["time_left"] = max(0.0, dur - (now_sec - ts["last_toggle"]))
        else:
            ts["state"] = "WINDOW_CLOSED"
            ts["last_toggle"] = 0.0
            ts["time_left"] = 0.0
            set_relay(ActuatorMap.ZONE_1_VALVE, False)
            set_relay(ActuatorMap.ZONE_2_VALVE, False)
            set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
            set_relay(ActuatorMap.RO_WATER_PUMP, False)

irrigation_engine = CyclicIrrigationController()

# -----------------------------------------------------------------------------
# AUTOMATION ENGINE: 5-VENTURI DEFICIT + SAFETY LIMITS
# -----------------------------------------------------------------------------
class FertigationCycleEngine:
    def __init__(self):
        self.is_running = False
        self.stop_event = threading.Event()
        self.active_crop_key = "cucumber"
        self.state = "IDLE"
        self.status_msg = "System Ready"

        self.baseline_ec = 0.60
        self.baseline_ph = 7.20
        self.ec_deficit = 0.0
        self.ph_excess = 0.0

        self.venturi_pulse_times = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
        self.venturi_safety_status = {1: "OK", 2: "OK", 3: "OK", 4: "OK", 5: "OK"}
        self.active_dosing_ch = 0
        self.dosing_remaining = 0.0

    def start_cycle(self, crop_key: str):
        if self.is_running:
            return False, "Cycle already running"

        recipe = crop_recipes.get(crop_key, DEFAULT_RECIPES.get("tomato", {}))
        target_ec = float(recipe.get("target_ec", 2.2))
        current_ec = round(sensor_live_data.get("ec", 0.6), 2)

        # STRICT SAFETY RULE: Main pump turns ON ONLY when Fertigation starts,
        # which ONLY happens when measured EC is below target EC!
        if current_ec >= target_ec:
            self.state = "EC SATISFIED"
            self.status_msg = f"EC ({current_ec:.2f}) >= Target ({target_ec:.2f}): Fertigation not needed. Main Pump remains OFF."
            return False, f"Target EC ({target_ec:.2f}) satisfied. Main pump will not start."

        # Isolate RO Water pump if active
        if active_relay_states.get(ActuatorMap.RO_WATER_PUMP):
            set_relay(ActuatorMap.RO_WATER_PUMP, False)

        self.active_crop_key = crop_key
        self.is_running = True
        self.stop_event.clear()
        threading.Thread(target=self._run_sequence, daemon=True).start()
        return True, "Started"

    def stop_cycle(self):
        self.stop_event.set()
        self.is_running = False
        all_relays_off()
        self.state = "STOPPED"
        self.status_msg = "Fertigation Process Aborted / Emergency Stop"

    def _run_sequence(self):
        recipe = crop_recipes.get(self.active_crop_key, DEFAULT_RECIPES.get("tomato", {}))
        crop_title = recipe.get("crop_name", self.active_crop_key.title())
        target_ec = float(recipe.get("target_ec", 2.2))
        target_ph = float(recipe.get("target_ph", 5.8))
        ec_tol    = float(recipe.get("ec_tolerance", 0.1))
        ph_tol    = float(recipe.get("ph_tolerance", 0.15))

        try:
            # Re-verify EC < target_ec before energizing Main Pump
            if sensor_live_data["ec"] >= target_ec:
                self.state = "EC SATISFIED"
                self.status_msg = f"EC ({sensor_live_data['ec']:.2f}) >= Target ({target_ec:.2f}). Main Pump OFF."
                return

            # Main Pump starting means Fertigation has officially started
            self.state = "1/5 FERTIGATION RECIRCULATION"
            self.status_msg = f"EC ({sensor_live_data['ec']:.2f}) < Target ({target_ec:.2f}) ➔ Main Pump started for Fertigation..."
            set_relay(ActuatorMap.MAIN_PUMP, True)               # 8 MAIN PUMP ON
            set_relay(ActuatorMap.PUMP_OUTLET_VALVE, True)       # 9 S.V 9 ON
            set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, True)  # 10 S.V 10 ON
            set_relay(ActuatorMap.TANK_RETURN_VALVE, True)       # 7 S.V 7 ON
            set_relay(ActuatorMap.RO_WATER_PUMP, False)          # 6 RO PUMP OFF
            set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)# 11 S.V 11 OFF
            set_relay(ActuatorMap.ZONE_1_VALVE, False)           # 12 OFF
            set_relay(ActuatorMap.ZONE_2_VALVE, False)           # 13 OFF

            stab_start = time.time()
            while (time.time() - stab_start < 5.0) and not self.stop_event.is_set():
                time.sleep(0.5)

            if self.stop_event.is_set(): return

            self.baseline_ec = round(sensor_live_data["ec"], 2)
            self.baseline_ph = round(sensor_live_data["ph"], 2)
            self.status_msg = f"Water Baseline: EC = {self.baseline_ec:.2f} mS/cm | pH = {self.baseline_ph:.2f}"
            time.sleep(1.5)

            # Step 2: Dynamic Deficit & 5-Venturi Safety Pulse Calculation
            self.state = "2/5 CALCULATING DEFICIT"
            target_ec = float(recipe.get("target_ec", 2.2))
            target_ph = float(recipe.get("target_ph", 5.8))
            ec_tol    = float(recipe.get("ec_tolerance", 0.1))
            ph_tol    = float(recipe.get("ph_tolerance", 0.15))

            self.ec_deficit = max(0.0, round(target_ec - self.baseline_ec, 2))
            self.ph_excess  = max(0.0, round(self.baseline_ph - target_ph, 2))

            K_ec = 4.5
            K_ph = 3.0
            pulses = {}

            for v_num in range(1, 5):
                ratio = float(recipe.get(f"v{v_num}_ratio", 1.0 if v_num <= 2 else 0.0))
                s_up  = float(recipe.get(f"v{v_num}_safety_up", 0.15))

                if sensor_live_data["ec"] >= (target_ec + s_up):
                    pulses[v_num] = 0.0
                    self.venturi_safety_status[v_num] = f"TRIPPED (+{s_up} Limit Exceeded)"
                elif self.ec_deficit > ec_tol and ratio > 0:
                    pulses[v_num] = round(max(0.0, min(15.0, self.ec_deficit * K_ec * ratio)), 1)
                    self.venturi_safety_status[v_num] = "PERMITTED"
                else:
                    pulses[v_num] = 0.0
                    self.venturi_safety_status[v_num] = "AT SETPOINT"

            v5_r   = float(recipe.get("v5_ratio", 1.0))
            v5_sdn = float(recipe.get("v5_safety_down", -0.15))

            if sensor_live_data["ph"] <= (target_ph + v5_sdn):
                pulses[5] = 0.0
                self.venturi_safety_status[5] = f"TRIPPED (pH < {target_ph + v5_sdn:.2f})"
            elif self.ph_excess > ph_tol and v5_r > 0:
                pulses[5] = round(max(0.0, min(8.0, self.ph_excess * K_ph * v5_r)), 1)
                self.venturi_safety_status[5] = "PERMITTED"
            else:
                pulses[5] = 0.0
                self.venturi_safety_status[5] = "AT SETPOINT"

            self.venturi_pulse_times = pulses
            self.status_msg = f"Doses: V1:{pulses[1]}s, V2:{pulses[2]}s, V3:{pulses[3]}s, V4:{pulses[4]}s, V5:{pulses[5]}s"
            time.sleep(2.0)

            # Step 3: Actuate 5 Venturis Sequentially (with live safety watchdog)
            self.state = "3/5 DOSING 5 VENTURIS"
            venturi_dosing_list = [
                (1, ActuatorMap.EC_VALVE_1, "Venturi 1 (Stock A - Ca/Fe)", pulses[1]),
                (2, ActuatorMap.EC_VALVE_2, "Venturi 2 (Stock B - NPK)",   pulses[2]),
                (3, ActuatorMap.EC_VALVE_3, "Venturi 3 (Stock C - Micros)",pulses[3]),
                (4, ActuatorMap.EC_VALVE_4, "Venturi 4 (Stock D - Boost)", pulses[4]),
                (5, ActuatorMap.PH_VALVE,   "Venturi 5 (pH Down Acid)",    pulses[5]),
            ]

            for v_num, act_ch, act_name, p_time in venturi_dosing_list:
                if self.stop_event.is_set(): return
                if p_time > 0.0:
                    self.active_dosing_ch = v_num
                    set_relay(act_ch, True)
                    start_pulse = time.time()
                    while (time.time() - start_pulse < p_time) and not self.stop_event.is_set():
                        if v_num <= 4:
                            s_up = float(recipe.get(f"v{v_num}_safety_up", 0.15))
                            if sensor_live_data["ec"] >= (target_ec + s_up):
                                self.status_msg = f"⚠ Safety Cutoff: EC reached {sensor_live_data['ec']:.2f}! Stopping {act_name}."
                                break
                        else:
                            s_dn = float(recipe.get("v5_safety_down", -0.15))
                            if sensor_live_data["ph"] <= (target_ph + s_dn):
                                self.status_msg = f"⚠ Safety Cutoff: pH reached {sensor_live_data['ph']:.2f}! Stopping Acid."
                                break

                        rem = max(0.0, p_time - (time.time() - start_pulse))
                        self.dosing_remaining = rem
                        self.status_msg = f"Actuating {act_name}: {rem:.1f}s left..."
                        time.sleep(0.1)

                    set_relay(act_ch, False)
                    self.active_dosing_ch = 0
                    if not self.stop_event.is_set():
                        self.status_msg = "Flushing manifold before next channel..."
                        time.sleep(2.0)

            if self.stop_event.is_set(): return

            # Step 4: Circulation & Mixing Loop
            self.state = "4/5 CIRCULATION & MIXING"
            mix_seconds = int(recipe.get("mixing_time_sec", 30))
            mix_start = time.time()
            while (time.time() - mix_start < mix_seconds) and not self.stop_event.is_set():
                rem_m = max(0.0, mix_seconds - (time.time() - mix_start))
                self.status_msg = f"Homogenizing solution: {rem_m:.0f}s remaining..."
                time.sleep(0.5)

            if self.stop_event.is_set(): return

            # Step 5: Verification & Delivery
            # Handwritten P&ID Rule: "-> [ 11 ON ] [ 10 OFF ], 12/13"
            self.state = "5/5 DELIVERING IRRIGATION"
            final_ec = round(sensor_live_data["ec"], 2)
            final_ph = round(sensor_live_data["ph"], 2)
            self.status_msg = f"Verified: Final EC = {final_ec:.2f}, pH = {final_ph:.2f} ➔ Delivering to Field..."

            # [ 10 OFF ], 7 OFF
            set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, False)  # 10 OFF
            set_relay(ActuatorMap.TANK_RETURN_VALVE, False)       # 7 OFF

            # [ 11 ON ], 12 ON (and 13 if Zone 2)
            set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, True) # 11 ON
            set_relay(ActuatorMap.ZONE_1_VALVE, True)            # 12 ON
            set_relay(ActuatorMap.MAIN_PUMP, True)               # 8
            set_relay(ActuatorMap.PUMP_OUTLET_VALVE, True)       # 9

            deliv_start = time.time()
            while (time.time() - deliv_start < 30.0) and not self.stop_event.is_set():
                rem_z = max(0.0, 30.0 - (time.time() - deliv_start))
                self.status_msg = f"Delivering to Field: {rem_z:.0f}s..."
                time.sleep(0.5)

            set_relay(ActuatorMap.ZONE_1_VALVE, False)
            set_relay(ActuatorMap.ZONE_2_VALVE, False)
            set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
            set_relay(ActuatorMap.PUMP_OUTLET_VALVE, False)
            set_relay(ActuatorMap.MAIN_PUMP, False)

            self.state = "COMPLETED"
            self.status_msg = f"✔ Batch Complete: Delivered at EC {final_ec:.2f}, pH {final_ph:.2f}"

        except Exception as err:
            all_relays_off()
            self.state = "ERROR"
            self.status_msg = f"Sequence aborted on error: {err}"
        finally:
            self.is_running = False

engine = FertigationCycleEngine()

# -----------------------------------------------------------------------------
# FULLSCREEN TOUCH KEYPAD (EXACT COLD1.PY ARCHITECTURE)
# -----------------------------------------------------------------------------
keypad_modal = None

def add_logo(parent):
    try:
        path = os.path.join(BASE_DIR, "logo.png")
        if PIL_AVAILABLE and os.path.exists(path):
            img = Image.open(path)
            img.thumbnail((120, 36), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(parent, image=photo, bg="white")
            lbl.image = photo
            lbl.place(relx=1.0, rely=0.0, anchor="ne", x=-15, y=8)
            lbl.lift()
            return lbl
    except Exception:
        pass
    return None

def add_bottom_right_clock(parent, bg_color="white"):
    lbl = tk.Label(
        parent,
        text="",
        font=("Helvetica", 10, "bold"),
        fg="#00897b",
        bg=bg_color,
        justify="right",
        padx=10,
        pady=4
    )
    lbl.place(relx=1.0, rely=1.0, anchor="se", x=-15, y=-10)
    lbl.lift()
    def _tick():
        if lbl.winfo_exists():
            now_s = datetime.datetime.now().strftime("%a, %d-%m-%Y\n%I:%M:%S %p (IST)")
            lbl.config(text=now_s)
            lbl.after(1000, _tick)
    _tick()
    return lbl

def make_modal_fullscreen(win, root_window=None):
    if root_window is None:
        try: root_window = root
        except Exception: root_window = tk._default_root

    win.configure(bg="white")
    if root_window:
        try: win.transient(root_window)
        except Exception: pass

    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    win.geometry(f"{sw}x{sh}+0+0")
    try: win.overrideredirect(True)
    except Exception: pass
    try: win.attributes("-fullscreen", True)
    except Exception: pass
    try: win.attributes("-topmost", True)
    except Exception: pass
    win.lift()
    win.update_idletasks()
    try: win.grab_set()
    except Exception: pass
    win.focus_force()

def open_almora_keypad(title_text, initial_value, callback_on_confirm, is_alphanumeric=False, mode=None, root_window=None):
    global keypad_modal
    if root_window is None:
        try: root_window = root
        except Exception: root_window = tk._default_root

    if keypad_modal and keypad_modal.winfo_exists():
        try: keypad_modal.destroy()
        except Exception: pass

    if mode is None:
        if is_alphanumeric:
            mode = "alphanumeric"
        elif any(k in title_text.lower() for k in ["time", "start", "stop"]):
            mode = "time"
        else:
            mode = "numeric"

    keypad_modal = tk.Toplevel(root_window)
    make_modal_fullscreen(keypad_modal, root_window)

    kp_main = tk.Frame(keypad_modal, bg="white")
    kp_main.pack(fill="both", expand=True, pady=(15, 6))

    add_logo(keypad_modal)
    add_bottom_right_clock(keypad_modal)

    entered_val = str(initial_value)

    lbl_modal_title = tk.Label(kp_main, text=title_text.upper(), font=("Helvetica", 16, "bold"), fg="#1565c0", bg="white")
    lbl_modal_title.pack(pady=(4, 2))

    lbl_modal_disp = tk.Label(kp_main, text=entered_val, font=("Arial", 24, "bold"), fg="#0f172a", bg="#f1f5f9", width=22, relief="sunken", bd=2)
    lbl_modal_disp.pack(pady=4)

    def kp_press(ch):
        nonlocal entered_val
        if len(entered_val) < 30:
            entered_val += str(ch)
            lbl_modal_disp.config(text=entered_val)

    def kp_set_val(new_val):
        nonlocal entered_val
        entered_val = str(new_val)
        lbl_modal_disp.config(text=entered_val)

    def kp_back():
        nonlocal entered_val
        entered_val = entered_val[:-1]
        lbl_modal_disp.config(text=entered_val)

    def kp_clear():
        nonlocal entered_val
        entered_val = ""
        lbl_modal_disp.config(text="")

    def kp_confirm():
        if keypad_modal and keypad_modal.winfo_exists():
            keypad_modal.destroy()
        callback_on_confirm(entered_val.strip())

    def kp_cancel():
        if keypad_modal and keypad_modal.winfo_exists():
            keypad_modal.destroy()

    keypad_modal.bind("<Escape>", lambda e: kp_cancel())
    keypad_modal.bind("<Return>", lambda e: kp_confirm())

    kp_buttons_frame = tk.Frame(kp_main, bg="white")
    kp_buttons_frame.pack(pady=4)

    if mode == "numeric":
        num_grid = [
            ('7', 0, 0), ('8', 0, 1), ('9', 0, 2), ('+', 0, 3),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2), ('-', 1, 3),
            ('1', 2, 0), ('2', 2, 1), ('3', 2, 2), ('.', 2, 3),
            ('0', 3, 0), ('00', 3, 1), (':', 3, 2), ('CLR', 3, 3)
        ]
        for t, r, c in num_grid:
            if t == 'CLR':
                btn = tk.Button(kp_buttons_frame, text=t, font=("Arial", 16, "bold"), width=7, height=1, bg="#dc2626", fg="white",
                                activebackground="#b91c1c", activeforeground="white", relief="raised", bd=1, cursor="hand2", command=kp_clear)
            elif t == '+':
                btn = tk.Button(kp_buttons_frame, text=t, font=("Arial", 18, "bold"), width=7, height=1, bg="#e0f2fe", fg="#0369a1",
                                activebackground="#0284c7", activeforeground="white", relief="raised", bd=1, cursor="hand2",
                                command=lambda: kp_press('+'))
            elif t == '-':
                btn = tk.Button(kp_buttons_frame, text=t, font=("Arial", 18, "bold"), width=7, height=1, bg="#fee2e2", fg="#dc2626",
                                activebackground="#b91c1c", activeforeground="white", relief="raised", bd=1, cursor="hand2",
                                command=lambda: kp_press('-'))
            else:
                btn = tk.Button(kp_buttons_frame, text=t, font=("Arial", 18, "bold"), width=7, height=1, bg="#f1f5f9", fg="#0f172a",
                                activebackground="#0284c7", activeforeground="white", relief="raised", bd=1, cursor="hand2",
                                command=lambda x=t: kp_press(x))
            btn.grid(row=r, column=c, padx=6, pady=3)

    elif mode == "time":
        shortcut_f = tk.Frame(kp_buttons_frame, bg="white")
        shortcut_f.grid(row=0, column=0, columnspan=4, pady=(0, 4))
        for ts in ["06:00", "08:00", "12:00", "15:00", "18:00", "21:00"]:
            tk.Button(
                shortcut_f, text=ts, font=("Helvetica", 11, "bold"), bg="#e0f2fe", fg="#0369a1", relief="flat", bd=0, padx=8, pady=4, cursor="hand2",
                command=lambda x=ts: kp_set_val(x)
            ).pack(side="left", padx=3)

        time_grid = [
            ('7', 1, 0), ('8', 1, 1), ('9', 1, 2), (':', 1, 3),
            ('4', 2, 0), ('5', 2, 1), ('6', 2, 2), ('00', 2, 3),
            ('1', 3, 0), ('2', 3, 1), ('3', 3, 2), ('CLR', 3, 3),
            ('0', 4, 0), ('0', 4, 1), (':', 4, 2), ('DEL', 4, 3),
        ]
        for t, r, c in time_grid:
            if t == 'CLR':
                b = tk.Button(kp_buttons_frame, text="CLR", font=("Arial", 15, "bold"), bg="#dc2626", fg="white", width=7, height=1, relief="raised", bd=1, cursor="hand2", command=kp_clear)
            elif t == 'DEL':
                b = tk.Button(kp_buttons_frame, text="DEL", font=("Arial", 15, "bold"), bg="#f97316", fg="white", width=7, height=1, relief="raised", bd=1, cursor="hand2", command=kp_back)
            else:
                b = tk.Button(kp_buttons_frame, text=t, font=("Arial", 16, "bold"), bg="#f1f5f9", fg="#0f172a", width=7, height=1, relief="raised", bd=1, cursor="hand2", command=lambda x=t: kp_press(x))
            b.grid(row=r, column=c, padx=6, pady=3)

    else:
        rows = [list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL:"), list("ZXCVBNM._- ")]
        for ri, row_k in enumerate(rows):
            r_f = tk.Frame(kp_buttons_frame, bg="white")
            r_f.pack(pady=2)
            for ch in row_k:
                w_btn = 15 if ch == " " else 5
                lbl_btn = "SPACE" if ch == " " else ch
                tk.Button(
                    r_f, text=lbl_btn, font=("Arial", 14, "bold"), width=w_btn, height=1, bg="#f1f5f9", fg="#0f172a",
                    activebackground="#0284c7", activeforeground="white", relief="raised", bd=1, cursor="hand2",
                    command=lambda x=ch: kp_press(x)
                ).pack(side="left", padx=3)

    kp_actions_frame = tk.Frame(kp_main, bg="white")
    kp_actions_frame.pack(pady=6)

    btn_act_w = 11
    btn_act_font = ("Helvetica", 12, "bold")

    tk.Button(kp_actions_frame, text="DEL", font=btn_act_font, bg="#f97316", fg="white", width=btn_act_w, height=1, cursor="hand2", relief="raised", bd=1, command=kp_back).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CLEAR", font=btn_act_font, bg="#dc2626", fg="white", width=btn_act_w, height=1, cursor="hand2", relief="raised", bd=1, command=kp_clear).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="SAVE", font=btn_act_font, bg="#2e7d32", fg="white", width=btn_act_w, height=1, cursor="hand2", relief="raised", bd=1, command=kp_confirm).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CANCEL", font=btn_act_font, bg="#64748b", fg="white", width=btn_act_w, height=1, cursor="hand2", relief="raised", bd=1, command=kp_cancel).pack(side="left", padx=6)

open_keypad = open_almora_keypad

# -----------------------------------------------------------------------------
# GRAPHICAL OPERATOR INTERFACE (SINGLE ZONE, NO LITERS)
# -----------------------------------------------------------------------------
root = tk.Tk()
root.title("InHydro Automation - Fertigation & Cyclic Irrigation Cycle Controller")
root.geometry("1024x600")
root.minsize(980, 560)
root.configure(bg="white")

try:
    root.attributes("-fullscreen", True)
except Exception:
    pass

FONT_TITLE = font.Font(family="Helvetica", size=12, weight="bold")
FONT_H2    = font.Font(family="Helvetica", size=11, weight="bold")
FONT_BOLD  = font.Font(family="Helvetica", size=10, weight="bold")
FONT_SUB   = font.Font(family="Helvetica", size=9)
FONT_BIG   = font.Font(family="Helvetica", size=18, weight="bold")

COLOR_BG           = "white"
COLOR_SURFACE      = "#f8fafc"
COLOR_PRIMARY      = "#1565c0"
COLOR_PRIMARY_DARK = "#0d47a1"
COLOR_TEXT_MAIN    = "#0f172a"
COLOR_TEXT_SUB     = "#475569"
COLOR_SUCCESS      = "#16a34a"
COLOR_DANGER       = "#dc2626"
COLOR_OFF          = "#64748b"

# TOP HEADER BAR
header = tk.Frame(root, bg=COLOR_PRIMARY, height=42, padx=10)
header.pack(fill="x", side="top")
header.pack_propagate(False)

tk.Label(header, text="🌱 INHYDRO AUTOMATION", font=FONT_TITLE, fg="white", bg=COLOR_PRIMARY).pack(side="left")
tk.Label(header, text="|  5-Venturi Fertigation & Cyclic Irrigation (Single Zone)", font=FONT_SUB, fg="#bae6fd", bg=COLOR_PRIMARY).pack(side="left", padx=8)

def restart_script():
    all_relays_off()
    engine.stop_cycle()
    irrigation_engine.stop_all()
    try: root.destroy()
    except Exception: pass
    os.execv(sys.executable, ['python3'] + sys.argv)

def on_exit_request():
    if messagebox.askyesno("Exit", "Exit Fertigation Controller? All relays will be turned OFF."):
        all_relays_off()
        root.destroy()
        sys.exit(0)

root.bind("<Escape>", lambda e: on_exit_request())

tk.Button(header, text="✕ EXIT (ESC)", font=FONT_SUB, bg="#dc2626", fg="white", bd=0, padx=8, pady=2, cursor="hand2", command=on_exit_request).pack(side="right", padx=4)

lbl_clock = tk.Label(header, text="", font=FONT_SUB, fg="white", bg=COLOR_PRIMARY)
lbl_clock.pack(side="right", padx=10)

# CROP SELECTION BAR
crop_bar = tk.Frame(root, bg=COLOR_SURFACE, bd=1, relief="solid", padx=10, pady=4)
crop_bar.pack(fill="x", padx=10, pady=(6, 4))

tk.Label(crop_bar, text="Active Crop Profile :", font=FONT_BOLD, fg=COLOR_TEXT_MAIN, bg=COLOR_SURFACE).pack(side="left")

selected_crop_var = tk.StringVar(value="cucumber")
crop_combo = ttk.Combobox(crop_bar, values=list(crop_recipes.keys()), textvariable=selected_crop_var, font=FONT_BOLD, state="readonly", width=14)
crop_combo.pack(side="left", padx=8)

lbl_crop_title_badge = tk.Label(crop_bar, text="Cucumber", font=FONT_BOLD, fg="white", bg=COLOR_PRIMARY, padx=10, pady=2)
lbl_crop_title_badge.pack(side="left", padx=4)

# 3-COLUMN WORKSPACE
content_grid = tk.Frame(root, bg=COLOR_BG)
content_grid.pack(fill="both", expand=True, padx=10, pady=4)

# COLUMN 1: LIVE SENSORS & DYNAMIC DEFICIT (NO LITERS)
col1 = tk.LabelFrame(content_grid, text=" 📊 Step 1: Raw Water & Deficit ", font=FONT_H2, fg=COLOR_PRIMARY, bg=COLOR_BG, bd=1, relief="solid", padx=8, pady=6)
col1.pack(side="left", fill="both", expand=True, padx=(0, 4))

# Live Meters Box
box_live = tk.Frame(col1, bg=COLOR_SURFACE, bd=1, relief="solid", padx=8, pady=6)
box_live.pack(fill="x", pady=2)
tk.Label(box_live, text="Current Live Sensors", font=FONT_BOLD, fg=COLOR_TEXT_MAIN, bg=COLOR_SURFACE).pack(anchor="w")

meter_box = tk.Frame(box_live, bg=COLOR_SURFACE)
meter_box.pack(fill="x", pady=2)

m_ec = tk.Frame(meter_box, bg=COLOR_SURFACE)
m_ec.pack(side="left", expand=True)
tk.Label(m_ec, text="LIVE EC", font=FONT_SUB, fg=COLOR_TEXT_SUB, bg=COLOR_SURFACE).pack()
lbl_live_ec = tk.Label(m_ec, text="0.60", font=FONT_BIG, fg=COLOR_PRIMARY, bg=COLOR_SURFACE)
lbl_live_ec.pack()

m_ph = tk.Frame(meter_box, bg=COLOR_SURFACE)
m_ph.pack(side="right", expand=True)
tk.Label(m_ph, text="LIVE pH", font=FONT_SUB, fg=COLOR_TEXT_SUB, bg=COLOR_SURFACE).pack()
lbl_live_ph = tk.Label(m_ph, text="7.20", font=FONT_BIG, fg=COLOR_PRIMARY, bg=COLOR_SURFACE)
lbl_live_ph.pack()

# Baseline & Target Box
box_base = tk.Frame(col1, bg=COLOR_SURFACE, bd=1, relief="solid", padx=8, pady=6)
box_base.pack(fill="x", pady=4)

tk.Label(box_base, text="Baseline (Measured) vs Target", font=FONT_BOLD, fg=COLOR_TEXT_MAIN, bg=COLOR_SURFACE).pack(anchor="w")
lbl_base_row = tk.Label(box_base, text="Water Baseline: EC 0.60 | pH 7.20", font=FONT_SUB, fg=COLOR_TEXT_SUB, bg=COLOR_SURFACE)
lbl_base_row.pack(anchor="w", pady=1)
lbl_target_row = tk.Label(box_base, text="Crop Target:    EC 2.20 | pH 5.80", font=FONT_BOLD, fg=COLOR_PRIMARY, bg=COLOR_SURFACE)
lbl_target_row.pack(anchor="w", pady=1)

# Deficit Box
box_deficit = tk.Frame(col1, bg="#eff6ff", bd=1, relief="solid", padx=8, pady=6)
box_deficit.pack(fill="x", pady=4)
tk.Label(box_deficit, text="Calculated Deficit (Δ = Target - Baseline)", font=FONT_BOLD, fg=COLOR_PRIMARY, bg="#eff6ff").pack(anchor="w")
lbl_def_ec = tk.Label(box_deficit, text="ΔEC Deficit: +1.60 mS/cm", font=FONT_BOLD, fg=COLOR_SUCCESS, bg="#eff6ff")
lbl_def_ec.pack(anchor="w", pady=1)
lbl_def_ph = tk.Label(box_deficit, text="ΔpH Excess:  -1.40 (Acid Req)", font=FONT_BOLD, fg=COLOR_DANGER, bg="#eff6ff")
lbl_def_ph.pack(anchor="w", pady=1)

# Valves Status Grid
box_valves = tk.Frame(col1, bg=COLOR_SURFACE, bd=1, relief="solid", padx=6, pady=4)
box_valves.pack(fill="both", expand=True, pady=4)
tk.Label(box_valves, text="10-Channel Relays Status", font=FONT_BOLD, fg=COLOR_TEXT_MAIN, bg=COLOR_SURFACE).pack(anchor="w")

v_grid = tk.Frame(box_valves, bg=COLOR_SURFACE)
v_grid.pack(fill="both", expand=True, pady=2)
v_grid.columnconfigure(0, weight=1)
v_grid.columnconfigure(1, weight=1)

cycle_valve_badges = {}
for idx, (ch, name) in enumerate(ACTUATOR_LABELS.items()):
    r = idx // 2
    c = idx % 2
    f_badge = tk.Frame(v_grid, bg=COLOR_SURFACE)
    f_badge.grid(row=r, column=c, sticky="nsew", padx=2, pady=1)
    tk.Label(f_badge, text=name, font=FONT_SUB, fg=COLOR_TEXT_MAIN, bg=COLOR_SURFACE).pack(side="left")
    b_st = tk.Label(f_badge, text="OFF", font=FONT_SUB, fg="white", bg=COLOR_OFF, width=5)
    b_st.pack(side="right")
    cycle_valve_badges[ch] = b_st

# COLUMN 2: 5-VENTURI RATIOS & SAFETY (+ / -) THRESHOLDS
col2 = tk.LabelFrame(content_grid, text=" 🌱 Step 2: 5-Venturi Inputs & Safety (+ / -) ", font=FONT_H2, fg=COLOR_PRIMARY, bg=COLOR_BG, bd=1, relief="solid", padx=8, pady=6)
col2.pack(side="left", fill="both", expand=True, padx=4)

tk.Label(col2, text="Tap value box or EDIT to change values via Fullscreen Keypad.", font=FONT_SUB, fg=COLOR_TEXT_SUB, bg=COLOR_BG).pack(anchor="w", pady=(0, 4))

labels_v_ratios = {}
labels_v_safety_up = {}
labels_v_safety_down = {}
labels_v_pulse = {}

v_items = [
    (1, "V1: Stock A (Ca/Fe)", "v1_ratio", "v1_safety_up", "v1_safety_down"),
    (2, "V2: Stock B (NPK/Mg)", "v2_ratio", "v2_safety_up", "v2_safety_down"),
    (3, "V3: Stock C (Micros)", "v3_ratio", "v3_safety_up", "v3_safety_down"),
    (4, "V4: Stock D (Booster)", "v4_ratio", "v4_safety_up", "v4_safety_down"),
    (5, "V5: pH Down (Acid)",   "v5_ratio", "v5_safety_up", "v5_safety_down"),
]

# Header
hdr2 = tk.Frame(col2, bg="#e2e8f0", padx=4, pady=2)
hdr2.pack(fill="x", pady=(0, 3))
tk.Label(hdr2, text="Channel", font=FONT_SUB, fg=COLOR_TEXT_MAIN, bg="#e2e8f0", width=16, anchor="w").pack(side="left")
tk.Label(hdr2, text="Ratio", font=FONT_SUB, fg=COLOR_TEXT_MAIN, bg="#e2e8f0", width=6, anchor="center").pack(side="left")
tk.Label(hdr2, text="+Cutoff", font=FONT_SUB, fg=COLOR_DANGER, bg="#e2e8f0", width=7, anchor="center").pack(side="left")
tk.Label(hdr2, text="-Start", font=FONT_SUB, fg=COLOR_PRIMARY, bg="#e2e8f0", width=7, anchor="center").pack(side="left")
tk.Label(hdr2, text="Dose", font=FONT_SUB, fg=COLOR_TEXT_MAIN, bg="#e2e8f0", width=6, anchor="e").pack(side="right")

for v_num, v_title, r_k, sup_k, sdn_k in v_items:
    r_box = tk.Frame(col2, bg=COLOR_SURFACE, bd=1, relief="solid", padx=4, pady=3)
    r_box.pack(fill="x", pady=2)

    tk.Label(r_box, text=v_title, font=FONT_BOLD, fg=COLOR_TEXT_MAIN, bg=COLOR_SURFACE, width=16, anchor="w").pack(side="left")

    def create_edit_badge(parent, default_v, title, fg_col=COLOR_TEXT_MAIN):
        f_b = tk.Frame(parent, bg=COLOR_SURFACE)
        f_b.pack(side="left", padx=2)
        l = tk.Label(f_b, text=str(default_v), font=FONT_BOLD, fg=fg_col, bg="white", relief="sunken", bd=1, width=5, cursor="hand2")
        l.pack(side="left")
        def do_click():
            open_keypad(title, l.cget("text"), lambda v: l.config(text=v), mode="numeric")
        l.bind("<Button-1>", lambda e: do_click())
        return l

    lbl_r  = create_edit_badge(r_box, "1.0", f"{v_title} Ratio")
    lbl_up = create_edit_badge(r_box, "0.15", f"{v_title} Safety Up (+) Cutoff", fg_col=COLOR_DANGER)
    lbl_dn = create_edit_badge(r_box, "-0.20", f"{v_title} Safety Down (-) Threshold", fg_col=COLOR_PRIMARY)

    labels_v_ratios[r_k] = lbl_r
    labels_v_safety_up[sup_k] = lbl_up
    labels_v_safety_down[sdn_k] = lbl_dn

    lbl_p = tk.Label(r_box, text="0.0s", font=FONT_BOLD, fg=COLOR_PRIMARY, bg="#e0f2fe", width=6, anchor="center")
    lbl_p.pack(side="right", padx=2)
    labels_v_pulse[v_num] = lbl_p

def save_crop_params():
    k = selected_crop_var.get()
    if k not in crop_recipes: return
    try:
        for r_k in labels_v_ratios: crop_recipes[k][r_k] = float(labels_v_ratios[r_k].cget("text"))
        for sup_k in labels_v_safety_up: crop_recipes[k][sup_k] = float(labels_v_safety_up[sup_k].cget("text"))
        for sdn_k in labels_v_safety_down: crop_recipes[k][sdn_k] = float(labels_v_safety_down[sdn_k].cget("text"))
        save_json(RECIPE_FILE, crop_recipes)
        messagebox.showinfo("Saved", f"Safety setpoints saved for {crop_recipes[k]['crop_name']}!")
    except Exception as e:
        messagebox.showerror("Error", f"Invalid values: {e}")

tk.Button(
    col2, text="💾 Save Ratios & Safety Limits", font=FONT_SUB, bg=COLOR_PRIMARY, fg="white",
    bd=0, padx=8, pady=4, cursor="hand2", command=save_crop_params
).pack(fill="x", pady=(4, 0))

# COLUMN 3: CYCLIC IRRIGATION & AUTOMATION EXECUTION
col3 = tk.LabelFrame(content_grid, text=" ⚡ Step 3: Cyclic Irrigation & Dosing ", font=FONT_H2, fg=COLOR_PRIMARY, bg=COLOR_BG, bd=1, relief="solid", padx=8, pady=6)
col3.pack(side="left", fill="both", expand=True, padx=(4, 0))

# Fertigation Process Monitor
box_proc = tk.Frame(col3, bg="#0f172a", bd=1, relief="solid", padx=8, pady=6)
box_proc.pack(fill="x", pady=2)

lbl_proc_phase = tk.Label(box_proc, text="PHASE: IDLE", font=FONT_BOLD, fg="#38bdf8", bg="#0f172a", anchor="w")
lbl_proc_phase.pack(fill="x")
lbl_proc_log = tk.Label(box_proc, text="Select crop and press START CYCLE.", font=FONT_SUB, fg="#e2e8f0", bg="#0f172a", anchor="w", wraplength=280, justify="left")
lbl_proc_log.pack(fill="x", pady=1)
lbl_proc_countdown = tk.Label(box_proc, text="Dosing Timer: 0.0s", font=FONT_BOLD, fg="#fbbf24", bg="#0f172a", anchor="w")
lbl_proc_countdown.pack(fill="x")

# Action Buttons
btn_bar = tk.Frame(col3, bg=COLOR_BG)
btn_bar.pack(fill="x", pady=4)

def start_fertigation():
    save_crop_params()
    started, msg = engine.start_cycle(selected_crop_var.get())
    if not started:
        messagebox.showwarning("Fertigation Standby", msg)

tk.Button(btn_bar, text="▶ START CYCLE", font=FONT_BOLD, bg=COLOR_PRIMARY, fg="white", bd=0, padx=6, pady=6, cursor="hand2", command=start_fertigation).pack(side="left", expand=True, fill="x", padx=2)
tk.Button(btn_bar, text="⏹ STOP", font=FONT_BOLD, bg=COLOR_DANGER, fg="white", bd=0, padx=6, pady=6, cursor="hand2", command=engine.stop_cycle).pack(side="left", expand=True, fill="x", padx=2)

# Single Zone Cyclic Timer Box
box_cyclic = tk.LabelFrame(col3, text=" Single Irrigation Zone Cyclic Timer ", font=FONT_BOLD, fg=COLOR_PRIMARY, bg=COLOR_SURFACE, bd=1, relief="solid", padx=8, pady=6)
box_cyclic.pack(fill="both", expand=True, pady=4)

lbl_timer_line_name = tk.Label(box_cyclic, text=str(cyclic_timer_cfg.get("name", "Field Irrigation")), font=FONT_BOLD, fg=COLOR_TEXT_MAIN, bg=COLOR_SURFACE)
lbl_timer_line_name.pack(anchor="w")

lbl_timer_run_state = tk.Label(box_cyclic, text="State: OFF (00:00 remaining)", font=FONT_SUB, fg=COLOR_TEXT_SUB, bg=COLOR_SURFACE)
lbl_timer_run_state.pack(anchor="w", pady=2)

def toggle_timer_en():
    cyclic_timer_cfg["enabled"] = not cyclic_timer_cfg.get("enabled", True)
    save_json(TIMERS_FILE, cyclic_timer_cfg)

btn_cyclic_row = tk.Frame(box_cyclic, bg=COLOR_SURFACE)
btn_cyclic_row.pack(fill="x", pady=4)

tk.Button(btn_cyclic_row, text="Timer ON/OFF Toggle", font=FONT_SUB, bg=COLOR_PRIMARY, fg="white", bd=0, padx=6, pady=4, cursor="hand2", command=toggle_timer_en).pack(side="left", expand=True, fill="x", padx=2)
tk.Button(btn_cyclic_row, text="Stop Irrigation", font=FONT_SUB, bg=COLOR_DANGER, fg="white", bd=0, padx=6, pady=4, cursor="hand2", command=irrigation_engine.stop_all).pack(side="right", expand=True, fill="x", padx=2)

# BOTTOM DOCK (RESTART SCRIPT BUTTON AT BOTTOM-LEFT)
bottom_dock = tk.Frame(root, bg="#eeeeee", height=42, bd=1, relief="solid", padx=10)
bottom_dock.pack(fill="x", side="bottom")
bottom_dock.pack_propagate(False)

tk.Button(
    bottom_dock, text="↺ RESTART SCRIPT", font=FONT_BOLD,
    bg=COLOR_PRIMARY, fg="white", bd=0, padx=12, pady=4, cursor="hand2", command=restart_script
).pack(side="left", padx=2, pady=4)

lbl_dock_status = tk.Label(bottom_dock, text="● Process: IDLE | System Ready", font=FONT_SUB, fg=COLOR_TEXT_SUB, bg="#eeeeee", anchor="w")
lbl_dock_status.pack(side="left", padx=12, fill="x", expand=True)

# LOAD CROP INTO UI
def load_crop_into_ui():
    k = selected_crop_var.get()
    recipe = crop_recipes.get(k, DEFAULT_RECIPES.get("cucumber", {}))
    crop_title = recipe.get("crop_name", k.title())

    lbl_crop_title_badge.config(text=crop_title)
    lbl_target_row.config(text=f"Crop Target:    EC {recipe.get('target_ec', 2.2):.2f} | pH {recipe.get('target_ph', 5.8):.2f}")

    for r_k, l_w in labels_v_ratios.items():
        l_w.config(text=str(recipe.get(r_k, 1.0 if "v1" in r_k or "v2" in r_k or "v5" in r_k else 0.0)))

    for sup_k, l_w in labels_v_safety_up.items():
        l_w.config(text=str(recipe.get(sup_k, 0.15)))

    for sdn_k, l_w in labels_v_safety_down.items():
        l_w.config(text=str(recipe.get(sdn_k, -0.20)))

crop_combo.bind("<<ComboboxSelected>>", lambda e: load_crop_into_ui())
load_crop_into_ui()

# PERIODIC UPDATE LOOP
def periodic_tick():
    irrigation_engine.process_tick()

    lbl_clock.config(text=datetime.datetime.now().strftime("%Y-%m-%d  %I:%M:%S %p"))
    lbl_live_ec.config(text=f"{sensor_live_data['ec']:.2f}")
    lbl_live_ph.config(text=f"{sensor_live_data['ph']:.2f}")

    lbl_base_row.config(text=f"Water Baseline: EC {engine.baseline_ec:.2f} | pH {engine.baseline_ph:.2f}")
    lbl_def_ec.config(text=f"ΔEC Deficit: +{engine.ec_deficit:.2f} mS/cm")
    lbl_def_ph.config(text=f"ΔpH Excess:  -{engine.ph_excess:.2f} (Acid Req)")

    for ch, b_st in cycle_valve_badges.items():
        is_on = active_relay_states.get(ch, False)
        b_st.config(
            text="ON" if is_on else "OFF",
            bg=COLOR_SUCCESS if is_on else COLOR_OFF
        )

    for v_num, p_val in engine.venturi_pulse_times.items():
        if v_num in labels_v_pulse:
            labels_v_pulse[v_num].config(text=f"{p_val:.1f}s")

    lbl_proc_phase.config(
        text=f"PHASE: {engine.state}",
        fg=COLOR_SUCCESS if engine.state == "COMPLETED" else ("#38bdf8" if engine.is_running else "white")
    )
    lbl_proc_log.config(text=engine.status_msg)
    if engine.active_dosing_ch > 0:
        lbl_proc_countdown.config(
            text=f"Venturi {engine.active_dosing_ch} Active: {engine.dosing_remaining:.1f}s left",
            fg="#fbbf24"
        )
    else:
        lbl_proc_countdown.config(
            text=f"Dosing: {'Idle' if not engine.is_running else 'Flushing / Waiting'}",
            fg="#94a3b8"
        )

    ts = irrigation_engine.timer_state
    m, s = int(ts.get("time_left", 0) // 60), int(ts.get("time_left", 0) % 60)
    lbl_timer_run_state.config(
        text=f"State: {ts.get('state', 'OFF')} ({m:02d}:{s:02d} remaining)",
        fg=COLOR_SUCCESS if ts.get('state') == 'ON' else COLOR_TEXT_SUB
    )

    lbl_dock_status.config(text=f"● Process: {engine.state}  |  {engine.status_msg}")
    root.after(100, periodic_tick)

root.after(100, periodic_tick)

if __name__ == "__main__":
    try:
        root.mainloop()
    except KeyboardInterrupt:
        all_relays_off()
        root.destroy()
        sys.exit(0)
