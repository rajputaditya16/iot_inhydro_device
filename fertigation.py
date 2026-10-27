import os
import sys
import subprocess
import time
import json
import datetime
import threading
import queue
import socket
import fcntl
import uuid as _uuid
import tkinter as tk
from tkinter import font, messagebox, ttk
from typing import Optional, Dict, Any, List

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

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# ==============================================================================
# BASE DIRECTORIES & IDENTITY
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith("#"):
                        return s
        except Exception:
            pass
    try:
        with open(ID_FILE, "w") as f:
            f.write("fertigation\n")
    except Exception:
        pass
    return "fertigation"

DEVICE_NAME = get_device_id()
RECIPE_FILE = os.path.join(BASE_DIR, "crop_recipes.json")
CONFIG_FILE = os.path.join(BASE_DIR, f"config_{DEVICE_NAME}.json")
CONFIG_FALLBACK_FILE = os.path.join(BASE_DIR, "config_system.json")
TIMERS_FILE = os.path.join(BASE_DIR, "config_fertigation_timers.json")
TIMERS_LEGACY_FILE = os.path.join(BASE_DIR, "config_irrigation_timers.json")
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
running = True

# ==============================================================================
# RELAY CHANNELS: 3 DOSING + MIX PUMP M1 + VALVE 2 + VALVE 1 + INLET PUMP M2 (CH 1-7)
# ==============================================================================
class ActuatorMap:
    EC_VALVE_1       = 1  # Relay 1: Nutrient Dosing EC1 (Stock A)
    EC_VALVE_2       = 2  # Relay 2: Nutrient Dosing EC2 (Stock B)
    PH_VALVE         = 3  # Relay 3: pH Down Dosing (Acid)
    DOSING_MOTOR     = 4  # Relay 4: Tank Mixing/Recirculation Pump M1 (Cyclic Timer 1)
    VALVE_2          = 5  # Relay 5: Bypass / Irrigation Valve 2 (Cyclic Timer 2)
    IRRIGATION_VALVE = 5
    VALVE_1          = 6  # Relay 6: Tank Inlet Valve 1 (Cyclic Timer 3: Tank Filling)
    TANK_INLET_VALVE = 6
    INLET_MOTOR      = 7  # Relay 7: Water Inlet Pump M2 (Auto-activated when Ch 5 or Ch 6 is ON)
    PUMP_M2          = 7

    # Direct aliases
    EC1 = EC_VALVE_1
    EC2 = EC_VALVE_2
    PH = PH_VALVE
    MOTOR = DOSING_MOTOR
    TIMER_1 = DOSING_MOTOR
    IRRIG_1 = VALVE_2
    IRRIG_2 = VALVE_1
    IRRIGATION_1 = VALVE_2
    IRRIGATION_2 = VALVE_1

ACTUATOR_NAMES = {
    ActuatorMap.EC_VALVE_1:       "EC1 (Nutrient 1)",
    ActuatorMap.EC_VALVE_2:       "EC2 (Nutrient 2)",
    ActuatorMap.PH_VALVE:         "pH Down",
    ActuatorMap.DOSING_MOTOR:     "Fertigation Pump",
    ActuatorMap.IRRIGATION_VALVE: "Irrigation Pump",
    ActuatorMap.TANK_INLET_VALVE: "Tank Fill",
    ActuatorMap.INLET_MOTOR:      "Main Pump",
}

# ==============================================================================
# CROP RECIPES & DEFAULT CONFIGURATION (EXACTLY AS FERTIGATION_HMI_CONTROLLER)
# ==============================================================================
DEFAULT_RECIPES = {
    "cucumber": {
        "crop_name": "Cucumber",
        "ec_min": 1.80,
        "ec_max": 2.20,
        "ph_min": 5.40,
        "ph_max": 6.40,
        "dose_sec": 180.0,
        "mix_sec": 30.0
    },
    "tomato": {
        "crop_name": "Tomato",
        "ec_min": 2.00,
        "ec_max": 2.50,
        "ph_min": 5.50,
        "ph_max": 6.50,
        "dose_sec": 180.0,
        "mix_sec": 30.0
    },
    "capsicum": {
        "crop_name": "Capsicum / Bell Pepper",
        "ec_min": 1.80,
        "ec_max": 2.20,
        "ph_min": 5.80,
        "ph_max": 6.60,
        "dose_sec": 180.0,
        "mix_sec": 30.0
    },
    "strawberry": {
        "crop_name": "Strawberry",
        "ec_min": 1.20,
        "ec_max": 1.60,
        "ph_min": 5.40,
        "ph_max": 6.30,
        "dose_sec": 180.0,
        "mix_sec": 30.0
    },
    "lettuce": {
        "crop_name": "Lettuce / Leafy Greens",
        "ec_min": 1.10,
        "ec_max": 1.40,
        "ph_min": 5.40,
        "ph_max": 6.30,
        "dose_sec": 180.0,
        "mix_sec": 30.0
    }
}

# 3 CYCLIC TIMERS: 1 FOR MIX MOTOR M1 (CH 4), 1 FOR IRRIG V2 (CH 5), 1 FOR TANK V1 (CH 6)
DEFAULT_CYCLIC_TIMERS = {
    "dosing_motor": {
        "name": "Mix Motor",
        "enabled": True,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 5.0,
        "off_min": 15.0,
        "relay_ch": ActuatorMap.DOSING_MOTOR
    },
    "irrigation": {
        "name": "Irrigation ",
        "enabled": True,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 5.0,
        "off_min": 15.0,
        "relay_ch": ActuatorMap.VALVE_2
    },
    "tank_filling": {
        "name": "Tank Filling",
        "enabled": True,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 5.0,
        "off_min": 60.0,
        "relay_ch": ActuatorMap.VALVE_1
    }
}

DEFAULT_CONFIG = {
    "relay_port": "/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.0-port0",
    "relay_slave_id": 1,
    "relay_baudrate": 9600,
    "serial_port_sensor": "/dev/serial/by-path/pci-0000:00:14.0-usb-0:1:1.0-port0",
    "sensor_slave_ec": 1,
    "sensor_slave_ph": 2,
    "simulation_mode": False,
    "active_crop": "cucumber"
}

# ==============================================================================
# JSON PERSISTENCE
# ==============================================================================
def load_json(filepath, default_data):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(default_data, dict):
                    updated = False
                    for k, v in default_data.items():
                        if k not in data:
                            data[k] = v
                            updated = True
                    if updated:
                        save_json(filepath, data)
                return data
        except Exception as e:
            print(f"[JSON] Error reading {filepath}: {e}")
    save_json(filepath, default_data)
    import copy
    return copy.deepcopy(default_data)

def save_json(filepath, data):
    try:
        tmp = filepath + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, filepath)
        return True
    except Exception as e:
        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            return True
        except Exception as e2:
            print(f"[JSON ERROR] Failed to save {filepath}: {e2}")
            return False

# Load Crop Recipes
crop_recipes = load_json(RECIPE_FILE, DEFAULT_RECIPES)

def get_crop_setpoints(crop_key: str) -> dict:
    return crop_recipes.get(crop_key, DEFAULT_RECIPES.get("cucumber", {}))

# Initialize 2 Cyclic Timers (Dosing Motor & Dual-Relay Irrigation)
cyclic_timer_cfg = load_json(TIMERS_FILE, DEFAULT_CYCLIC_TIMERS)
if "dosing_motor" not in cyclic_timer_cfg or "irrigation" not in cyclic_timer_cfg:
    import copy
    cyclic_timer_cfg = copy.deepcopy(DEFAULT_CYCLIC_TIMERS)
    save_json(TIMERS_FILE, cyclic_timer_cfg)
else:
    for tk_key, def_cfg in DEFAULT_CYCLIC_TIMERS.items():
        for k_param, v_val in def_cfg.items():
            if k_param not in cyclic_timer_cfg[tk_key]:
                cyclic_timer_cfg[tk_key][k_param] = v_val
    save_json(TIMERS_FILE, cyclic_timer_cfg)

# Initialize System Config
if os.path.exists(CONFIG_FILE):
    system_config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
elif os.path.exists(CONFIG_FALLBACK_FILE):
    system_config = load_json(CONFIG_FALLBACK_FILE, DEFAULT_CONFIG)
    save_json(CONFIG_FILE, system_config)
else:
    system_config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    save_json(CONFIG_FALLBACK_FILE, system_config)

# ==============================================================================
# HARDWARE CONTROLLER (MODBUS RTU NON-BLOCKING ENGINE)
# ==============================================================================
_relay_lock = threading.Lock()
_sensor_lock = threading.Lock()

class HardwareController:
    def __init__(self):
        self.relays = {i: False for i in range(1, 17)}
        self.relay_queue = queue.Queue()

        self.pv_ec = None
        self.pv_ph = None
        self.pv_water_temp = None
        self.is_real_sensor = False
        self.sensor_error = True
        self.ec_last_seen = 0.0
        self.ph_last_seen = 0.0

        self.worker_thread = threading.Thread(target=self._relay_worker, daemon=True, name="HW_Relay_Worker")
        self.worker_thread.start()

        self.sensor_thread = threading.Thread(target=self._sensor_worker, daemon=True, name="HW_Sensor_Worker")
        self.sensor_thread.start()

    def set_relay(self, ch: int, state: bool):
        if not (1 <= ch <= 16):
            return

        # Strict interlock: Ch 5 (Valve 2) and Ch 6 (Valve 1) can NEVER be ON simultaneously
        if state:
            if ch == ActuatorMap.VALVE_2:  # Ch 5
                if self.relays.get(ActuatorMap.VALVE_1, False):
                    self.relays[ActuatorMap.VALVE_1] = False
                    self.relay_queue.put((ActuatorMap.VALVE_1, False))
            elif ch == ActuatorMap.VALVE_1:  # Ch 6
                if self.relays.get(ActuatorMap.VALVE_2, False):
                    self.relays[ActuatorMap.VALVE_2] = False
                    self.relay_queue.put((ActuatorMap.VALVE_2, False))

        if self.relays.get(ch) == state:
            return

        self.relays[ch] = state
        self.relay_queue.put((ch, state))

        # Dynamic auto-governance for Channel 7 (Inlet Motor M2):
        # M2 is ON whenever Valve 2 (Ch 5) or Valve 1 (Ch 6) is ON, and OFF when both are OFF
        if ch in (ActuatorMap.VALVE_2, ActuatorMap.VALVE_1):
            m2_needed = bool(self.relays.get(ActuatorMap.VALVE_2, False) or self.relays.get(ActuatorMap.VALVE_1, False))
            if self.relays.get(ActuatorMap.INLET_MOTOR, False) != m2_needed:
                self.relays[ActuatorMap.INLET_MOTOR] = m2_needed
                self.relay_queue.put((ActuatorMap.INLET_MOTOR, m2_needed))

    def get_relay(self, ch: int) -> bool:
        return self.relays.get(ch, False)

    def emergency_all_off(self):
        while not self.relay_queue.empty():
            try:
                self.relay_queue.get_nowait()
                self.relay_queue.task_done()
            except Exception:
                break
        for ch in range(1, 17):
            self.relays[ch] = False
        self.relay_queue.put(("ALL_OFF", False))

    def _relay_worker(self):
        while True:
            try:
                item = self.relay_queue.get()
                ch, state = item
                port = system_config.get("relay_port")
                slave_id = int(system_config.get("relay_slave_id", 1))
                baud = int(system_config.get("relay_baudrate", 9600))
                inst = None
                try:
                    if MODBUS_AVAILABLE and port and os.path.exists(port) and not os.path.isdir(port):
                        with _relay_lock:
                            inst = minimalmodbus.Instrument(port, slave_id)
                            inst.serial.baudrate = baud
                            inst.serial.timeout = 0.25
                            inst.mode = minimalmodbus.MODE_RTU
                            inst.clear_buffers_before_each_transaction = True
                            if ch == "ALL_OFF":
                                for coil_i in range(16):
                                    try: inst.write_bit(coil_i, 0, functioncode=5)
                                    except Exception: pass
                                print(f"[RELAY] ALL OFF executed on {port}")
                            else:
                                inst.write_bit(ch - 1, 1 if state else 0, functioncode=5)
                                print(f"[RELAY] Ch {ch} set to {'ON' if state else 'OFF'}")
                except Exception as err:
                    print(f"[RELAY ERROR] Failed to set Ch {ch} to {state}: {err}")
                finally:
                    if inst and hasattr(inst, "serial") and inst.serial and getattr(inst.serial, "is_open", False):
                        try: inst.serial.close()
                        except Exception: pass
                self.relay_queue.task_done()
            except Exception as e:
                print(f"[RELAY WORKER EXCEPTION] {e}")

    def _sensor_worker(self):
        while True:
            try:
                target_port = system_config.get("serial_port_sensor")
                read_ec_ok = False
                read_ph_ok = False

                if MODBUS_AVAILABLE and target_port and os.path.exists(target_port) and not os.path.isdir(target_port):
                    ec_slave = int(system_config.get("sensor_slave_ec", 1))
                    inst_ec = None
                    try:
                        with _sensor_lock:
                            inst_ec = minimalmodbus.Instrument(target_port, ec_slave)
                            inst_ec.serial.baudrate = 9600
                            inst_ec.serial.timeout = 0.35
                            inst_ec.mode = minimalmodbus.MODE_RTU
                            inst_ec.clear_buffers_before_each_transaction = True
                            d1 = inst_ec.read_registers(0, 4, functioncode=3)
                        if d1 and len(d1) >= 1:
                            raw_ec = d1[0]
                            ec_v = round(raw_ec / 1000.0, 3)
                            if 0.0 <= ec_v <= 25.0:
                                self.pv_ec = ec_v
                                read_ec_ok = True
                    except Exception: pass
                    finally:
                        if inst_ec and hasattr(inst_ec, "serial") and inst_ec.serial and getattr(inst_ec.serial, "is_open", False):
                            try: inst_ec.serial.close()
                            except Exception: pass

                    time.sleep(0.08)

                    ph_slave = int(system_config.get("sensor_slave_ph", 2))
                    inst_ph = None
                    try:
                        with _sensor_lock:
                            inst_ph = minimalmodbus.Instrument(target_port, ph_slave)
                            inst_ph.serial.baudrate = 9600
                            inst_ph.serial.timeout = 0.35
                            inst_ph.mode = minimalmodbus.MODE_RTU
                            inst_ph.clear_buffers_before_each_transaction = True
                            d2 = inst_ph.read_registers(0, 4, functioncode=3)
                        if d2 and len(d2) >= 4:
                            raw_ph = d2[2]
                            ph_v = round(raw_ph / 100.0, 2) if raw_ph > 50 else round(float(raw_ph), 2)
                            raw_temp = d2[3]
                            temp_v = float(raw_temp)
                            if 0.0 <= ph_v <= 14.0:
                                self.pv_ph = ph_v
                                read_ph_ok = True
                            if 0.0 <= temp_v <= 80.0:
                                self.pv_water_temp = temp_v
                    except Exception: pass
                    finally:
                        if inst_ph and hasattr(inst_ph, "serial") and inst_ph.serial and getattr(inst_ph.serial, "is_open", False):
                            try: inst_ph.serial.close()
                            except Exception: pass

                if read_ec_ok: self.ec_last_seen = time.time()
                if read_ph_ok: self.ph_last_seen = time.time()

                now = time.time()
                if now - self.ec_last_seen > 15.0: self.pv_ec = None
                if now - self.ph_last_seen > 15.0: self.pv_ph = None; self.pv_water_temp = None

                if self.pv_ec is not None and self.pv_ph is not None:
                    self.is_real_sensor = True
                    self.sensor_error = False
                else:
                    self.is_real_sensor = False
                    self.sensor_error = True

                time.sleep(0.4)
            except Exception:
                time.sleep(1.0)

    def simulate_step(self, dt: float = 0.1):
        return

hw = HardwareController()

# ==============================================================================
# 3 CYCLIC TIMERS ENGINE (MIX MOTOR M1 CH 4, IRRIG V2 CH 5, TANK V1 CH 6, AUTO M2 CH 7)
# ==============================================================================
class CyclicTimerEngine:
    def __init__(self, hardware: HardwareController):
        self.hw = hardware
        self.timer_keys = ["dosing_motor", "irrigation", "tank_filling"]
        self.timer_states = {
            "dosing_motor": {
                "state": "OFF",
                "last_toggle": 0.0,
                "time_left": 0.0,
                "manual_stopped": False,
                "active_relay": ActuatorMap.DOSING_MOTOR
            },
            "irrigation": {
                "state": "OFF",
                "last_toggle": 0.0,
                "time_left": 0.0,
                "manual_stopped": False,
                "active_relay": ActuatorMap.VALVE_2
            },
            "tank_filling": {
                "state": "OFF",
                "last_toggle": 0.0,
                "time_left": 0.0,
                "manual_stopped": False,
                "active_relay": ActuatorMap.VALVE_1
            }
        }

    def start_timer(self, timer_key: str, active_ch: int = None):
        if timer_key in self.timer_states:
            ts = self.timer_states[timer_key]
            cfg = cyclic_timer_cfg.get(timer_key, {})
            ts["manual_stopped"] = False
            ts["state"] = "ON"
            ts["last_toggle"] = time.time()
            on_min = float(cfg.get("on_min", 5.0))
            ts["time_left"] = on_min * 60.0

            if timer_key == "dosing_motor":
                ch = int(cfg.get("relay_ch", ActuatorMap.DOSING_MOTOR))
                ts["active_relay"] = ch
                self.hw.set_relay(ch, True)
            elif timer_key == "irrigation":
                # Strict interlock: Ch 5 ON, Ch 6 OFF
                self.hw.set_relay(ActuatorMap.VALVE_1, False)
                if "tank_filling" in self.timer_states:
                    self.timer_states["tank_filling"]["state"] = "OFF"
                ts["active_relay"] = ActuatorMap.VALVE_2
                self.hw.set_relay(ActuatorMap.VALVE_2, True)
            elif timer_key == "tank_filling":
                # Strict interlock: Ch 6 ON, Ch 5 OFF
                self.hw.set_relay(ActuatorMap.VALVE_2, False)
                if "irrigation" in self.timer_states:
                    self.timer_states["irrigation"]["state"] = "OFF"
                ts["active_relay"] = ActuatorMap.VALVE_1
                self.hw.set_relay(ActuatorMap.VALVE_1, True)

    def stop_timer(self, timer_key: str):
        if timer_key in self.timer_states:
            ts = self.timer_states[timer_key]
            cfg = cyclic_timer_cfg.get(timer_key, {})
            ts["state"] = "STOPPED"
            ts["manual_stopped"] = True
            ts["last_toggle"] = time.time()
            ts["time_left"] = 0.0
            if timer_key == "dosing_motor":
                ch = int(cfg.get("relay_ch", ActuatorMap.DOSING_MOTOR))
                self.hw.set_relay(ch, False)
            elif timer_key == "irrigation":
                self.hw.set_relay(ActuatorMap.VALVE_2, False)
            elif timer_key == "tank_filling":
                self.hw.set_relay(ActuatorMap.VALVE_1, False)

    def stop_all_timers(self):
        for k in self.timer_keys:
            self.stop_timer(k)

    def process_tick(self):
        now_dt = datetime.datetime.now()
        cur_time = now_dt.time()
        now_sec = time.time()

        for k in self.timer_keys:
            cfg = cyclic_timer_cfg.get(k, {})
            ts = self.timer_states[k]

            if not cfg.get("enabled", True) or ts.get("manual_stopped", False):
                ts["state"] = "STOPPED" if ts.get("manual_stopped", False) else "DISABLED"
                ts["time_left"] = 0.0
                if k == "dosing_motor":
                    ch = int(cfg.get("relay_ch", ActuatorMap.DOSING_MOTOR))
                    if self.hw.get_relay(ch): self.hw.set_relay(ch, False)
                elif k == "irrigation":
                    if self.hw.get_relay(ActuatorMap.VALVE_2): self.hw.set_relay(ActuatorMap.VALVE_2, False)
                elif k == "tank_filling":
                    if self.hw.get_relay(ActuatorMap.VALVE_1): self.hw.set_relay(ActuatorMap.VALVE_1, False)
                continue

            try:
                t_start = datetime.datetime.strptime(str(cfg.get("start_time", "06:00")), "%H:%M").time()
                t_stop  = datetime.datetime.strptime(str(cfg.get("stop_time", "18:00")), "%H:%M").time()
            except Exception:
                t_start = datetime.time(0, 0)
                t_stop  = datetime.time(23, 59)

            in_window = (t_start <= cur_time <= t_stop) if t_start <= t_stop else (cur_time >= t_start or cur_time <= t_stop)
            on_sec = max(1.0, float(cfg.get("on_min", 5.0)) * 60.0)
            off_sec = max(1.0, float(cfg.get("off_min", 15.0)) * 60.0)

            if in_window:
                if ts["state"] in ["OFF", "WINDOW_CLOSED", "DISABLED", "STOPPED", "WAITING_IRRIG"]:
                    if ts["last_toggle"] == 0.0 or (now_sec - ts["last_toggle"] >= off_sec):
                        # Strict interlock check before turning ON
                        if k == "tank_filling" and self.hw.get_relay(ActuatorMap.VALVE_2):
                            # Irrigation is running; Tank filling cannot turn ON Ch 6 simultaneously!
                            ts["state"] = "WAITING_IRRIG"
                        elif k == "irrigation" and self.hw.get_relay(ActuatorMap.VALVE_1):
                            # Irrigation takes priority: force Ch 6 OFF
                            self.hw.set_relay(ActuatorMap.VALVE_1, False)
                            ts["state"] = "ON"
                            ts["last_toggle"] = now_sec
                            self.hw.set_relay(ActuatorMap.VALVE_2, True)
                        else:
                            ts["state"] = "ON"
                            ts["last_toggle"] = now_sec
                            if k == "dosing_motor":
                                ch = int(cfg.get("relay_ch", ActuatorMap.DOSING_MOTOR))
                                self.hw.set_relay(ch, True)
                            elif k == "irrigation":
                                self.hw.set_relay(ActuatorMap.VALVE_1, False)
                                self.hw.set_relay(ActuatorMap.VALVE_2, True)
                            elif k == "tank_filling":
                                self.hw.set_relay(ActuatorMap.VALVE_2, False)
                                self.hw.set_relay(ActuatorMap.VALVE_1, True)
                    else:
                        ts["state"] = "OFF"
                        if k == "dosing_motor":
                            ch = int(cfg.get("relay_ch", ActuatorMap.DOSING_MOTOR))
                            if self.hw.get_relay(ch): self.hw.set_relay(ch, False)
                        elif k == "irrigation":
                            if self.hw.get_relay(ActuatorMap.VALVE_2): self.hw.set_relay(ActuatorMap.VALVE_2, False)
                        elif k == "tank_filling":
                            if self.hw.get_relay(ActuatorMap.VALVE_1): self.hw.set_relay(ActuatorMap.VALVE_1, False)

                elif ts["state"] == "ON":
                    if now_sec - ts["last_toggle"] >= on_sec:
                        ts["state"] = "OFF"
                        ts["last_toggle"] = now_sec
                        if k == "dosing_motor":
                            ch = int(cfg.get("relay_ch", ActuatorMap.DOSING_MOTOR))
                            self.hw.set_relay(ch, False)
                        elif k == "irrigation":
                            self.hw.set_relay(ActuatorMap.VALVE_2, False)
                        elif k == "tank_filling":
                            self.hw.set_relay(ActuatorMap.VALVE_1, False)
                    else:
                        if k == "dosing_motor":
                            ch = int(cfg.get("relay_ch", ActuatorMap.DOSING_MOTOR))
                            if not self.hw.get_relay(ch): self.hw.set_relay(ch, True)
                        elif k == "irrigation":
                            if not self.hw.get_relay(ActuatorMap.VALVE_2): self.hw.set_relay(ActuatorMap.VALVE_2, True)
                            if self.hw.get_relay(ActuatorMap.VALVE_1): self.hw.set_relay(ActuatorMap.VALVE_1, False)
                        elif k == "tank_filling":
                            if not self.hw.get_relay(ActuatorMap.VALVE_1): self.hw.set_relay(ActuatorMap.VALVE_1, True)
                            if self.hw.get_relay(ActuatorMap.VALVE_2): self.hw.set_relay(ActuatorMap.VALVE_2, False)

                dur = on_sec if ts["state"] == "ON" else off_sec
                ts["time_left"] = max(0.0, dur - (now_sec - ts["last_toggle"]))
            else:
                ts["state"] = "WINDOW_CLOSED"
                ts["last_toggle"] = 0.0
                ts["time_left"] = 0.0
                if k == "dosing_motor":
                    ch = int(cfg.get("relay_ch", ActuatorMap.DOSING_MOTOR))
                    if self.hw.get_relay(ch): self.hw.set_relay(ch, False)
                elif k == "irrigation":
                    if self.hw.get_relay(ActuatorMap.VALVE_2): self.hw.set_relay(ActuatorMap.VALVE_2, False)
                elif k == "tank_filling":
                    if self.hw.get_relay(ActuatorMap.VALVE_1): self.hw.set_relay(ActuatorMap.VALVE_1, False)

cyclic_engine = CyclicTimerEngine(hw)

class DosingEngine:
    def __init__(self, hardware: HardwareController):
        self.hw = hardware
        self.is_running = False
        self.state = "STANDBY"
        self.status_msg = "Dosing Ready (Standby)"

        # EC loop state: "STANDBY", "DOSING", "MIXING"
        self.ec_state = "STANDBY"
        self.ec_timer_start = 0.0
        self.ec_loop_count = 0

        # pH loop state: "STANDBY", "DOSING", "MIXING"
        self.ph_state = "STANDBY"
        self.ph_timer_start = 0.0
        self.ph_loop_count = 0

        self.dosing_time_remaining = 0
        self.mixing_time_remaining = 0

    @property
    def ec_active(self) -> bool:
        return self.ec_state == "DOSING"

    @property
    def ph_active(self) -> bool:
        return self.ph_state == "DOSING"

    def start_manual_dosing(self):
        self.is_running = True
        self.state = "RUNNING"
        self.status_msg = "Fertigation Dosing Started"

    def stop_manual_dosing(self):
        self.is_running = False
        self.ec_state = "STANDBY"
        self.ph_state = "STANDBY"
        self.ec_timer_start = 0.0
        self.ph_timer_start = 0.0
        self.dosing_time_remaining = 0
        self.mixing_time_remaining = 0
        self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
        self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
        self.hw.set_relay(ActuatorMap.PH_VALVE, False)
        self.state = "STOPPED"
        self.status_msg = "Fertigation Dosing Stopped / Standby"

    def reset(self):
        self.stop_manual_dosing()

    def process_tick(self, auto_enabled: bool, active_recipe: dict):
        now = time.time()

        if not auto_enabled and not self.is_running:
            if self.ec_state != "STANDBY" or self.ph_state != "STANDBY":
                self.stop_manual_dosing()
            return

        ec_val = self.hw.pv_ec
        ph_val = self.hw.pv_ph

        # STRICT SENSOR SAFETY INTERLOCK:
        # If real physical sensors are not connected, offline, or reporting error, NEVER start auto-fertigation!
        if getattr(self.hw, "sensor_error", False) or not getattr(self.hw, "is_real_sensor", False) or ec_val is None or ph_val is None or ec_val <= 0 or ph_val <= 0:
            if self.ec_state != "STANDBY" or self.ph_state != "STANDBY" or self.hw.get_relay(ActuatorMap.EC_VALVE_1) or self.hw.get_relay(ActuatorMap.EC_VALVE_2) or self.hw.get_relay(ActuatorMap.PH_VALVE):
                self.stop_manual_dosing()
            self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
            self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
            self.hw.set_relay(ActuatorMap.PH_VALVE, False)
            self.state = "SENSOR ERROR"
            self.status_msg = "⚠ Fertigation Paused: Sensors disconnected or offline!"
            return

        dose_duration = float(active_recipe.get("dose_sec", 180.0))
        mix_duration  = float(active_recipe.get("mix_sec", 30.0))
        ec_min = float(active_recipe.get("ec_min", 1.80))
        ec_max = float(active_recipe.get("ec_max", 2.20))
        ph_low = float(active_recipe.get("ph_min", 5.40))
        ph_high = float(active_recipe.get("ph_max", 6.40))

        active_actions = []

        # ----------------------------------------------------------------------
        # 1. EC DOSING LOOP (EC1 & EC2)
        # Both EC relays ON when live EC < ec_min; OFF when live EC >= ec_max.
        # Loop: 180s dosing -> 30s mixing -> re-check if < ec_max -> repeat.
        # Mid-loop cutoff: If live EC >= ec_max reached, immediately turn OFF.
        # ----------------------------------------------------------------------
        if self.ec_state == "STANDBY":
            if 0 < ec_val < ec_min:
                self.ec_state = "DOSING"
                self.ec_timer_start = now
                self.ec_loop_count += 1
                self.hw.set_relay(ActuatorMap.EC_VALVE_1, True)
                self.hw.set_relay(ActuatorMap.EC_VALVE_2, True)
                active_actions.append(f"EC LOW ({ec_val:.3f} < {ec_min:.2f}) - Dosing EC1 & EC2 [Loop {self.ec_loop_count}]")
            else:
                self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
                self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)

        elif self.ec_state == "DOSING":
            if ec_val >= ec_max:
                # EC max reached mid-loop -> cutoff both EC relays immediately & switch to 30s mixing
                self.ec_state = "MIXING"
                self.ec_timer_start = now
                self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
                self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
                active_actions.append(f"EC MAX REACHED ({ec_val:.3f} >= {ec_max:.2f}) - EC Cutoff ➔ Mixing")
            elif (now - self.ec_timer_start) >= dose_duration:
                # 180s dosing timeout completed -> turn both relays OFF & switch to 30s mixing
                self.ec_state = "MIXING"
                self.ec_timer_start = now
                self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
                self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
                active_actions.append(f"EC 180s Dose Complete ➔ Commencing 30s Mixing")
            else:
                rem_ec = max(0, int(dose_duration - (now - self.ec_timer_start)))
                self.dosing_time_remaining = rem_ec
                if not self.hw.get_relay(ActuatorMap.EC_VALVE_1): self.hw.set_relay(ActuatorMap.EC_VALVE_1, True)
                if not self.hw.get_relay(ActuatorMap.EC_VALVE_2): self.hw.set_relay(ActuatorMap.EC_VALVE_2, True)
                active_actions.append(f"EC Dosing ({rem_ec}s left) [Loop {self.ec_loop_count}]")

        elif self.ec_state == "MIXING":
            self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
            self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
            elapsed_ec = now - self.ec_timer_start
            if elapsed_ec >= mix_duration:
                # 30s mixing completed -> re-check EC
                if ec_val < ec_max:
                    # Still below ec_max -> restart 180s dosing loop
                    self.ec_state = "DOSING"
                    self.ec_timer_start = now
                    self.ec_loop_count += 1
                    self.hw.set_relay(ActuatorMap.EC_VALVE_1, True)
                    self.hw.set_relay(ActuatorMap.EC_VALVE_2, True)
                    active_actions.append(f"EC Still < {ec_max:.2f} ({ec_val:.3f}) - Next 180s Dosing [Loop {self.ec_loop_count}]")
                else:
                    self.ec_state = "STANDBY"
                    active_actions.append(f"EC Satisfied ({ec_val:.3f} >= {ec_max:.2f})")
            else:
                rem_ec_m = max(0, int(mix_duration - elapsed_ec))
                self.mixing_time_remaining = rem_ec_m
                active_actions.append(f"EC Mixing ({rem_ec_m}s left)")

        # ----------------------------------------------------------------------
        # 2. pH DOWN DOSING LOOP (pH Down Acid Valve)
        # pH Down relay ON when live pH >= ph_max; OFF when live pH <= ph_min.
        # Loop: 180s dosing -> 30s mixing -> re-check if still > ph_min -> repeat.
        # Mid-loop cutoff: If live pH <= ph_min reached, immediately turn OFF.
        # ----------------------------------------------------------------------
        if self.ph_state == "STANDBY":
            if ph_val >= ph_high and ph_val > 0:
                self.ph_state = "DOSING"
                self.ph_timer_start = now
                self.ph_loop_count += 1
                self.hw.set_relay(ActuatorMap.PH_VALVE, True)
                active_actions.append(f"pH HIGH ({ph_val:.2f} >= {ph_high:.2f}) - Dosing Acid [Loop {self.ph_loop_count}]")
            else:
                self.hw.set_relay(ActuatorMap.PH_VALVE, False)

        elif self.ph_state == "DOSING":
            if ph_val <= ph_low and ph_val > 0:
                # pH min reached mid-loop -> cutoff pH relay immediately & switch to 30s mixing
                self.ph_state = "MIXING"
                self.ph_timer_start = now
                self.hw.set_relay(ActuatorMap.PH_VALVE, False)
                active_actions.append(f"pH MIN REACHED ({ph_val:.2f} <= {ph_low:.2f}) - Acid Cutoff ➔ Mixing")
            elif (now - self.ph_timer_start) >= dose_duration:
                # 180s dosing timeout completed -> turn relay OFF & switch to 30s mixing
                self.ph_state = "MIXING"
                self.ph_timer_start = now
                self.hw.set_relay(ActuatorMap.PH_VALVE, False)
                active_actions.append(f"pH 180s Dose Complete ➔ Commencing 30s Mixing")
            else:
                rem_ph = max(0, int(dose_duration - (now - self.ph_timer_start)))
                if not self.hw.get_relay(ActuatorMap.PH_VALVE): self.hw.set_relay(ActuatorMap.PH_VALVE, True)
                active_actions.append(f"pH Dosing ({rem_ph}s left) [Loop {self.ph_loop_count}]")

        elif self.ph_state == "MIXING":
            self.hw.set_relay(ActuatorMap.PH_VALVE, False)
            elapsed_ph = now - self.ph_timer_start
            if elapsed_ph >= mix_duration:
                # 30s mixing completed -> re-check pH
                if ph_val > ph_low:
                    # Still above ph_min -> restart 180s dosing loop
                    self.ph_state = "DOSING"
                    self.ph_timer_start = now
                    self.ph_loop_count += 1
                    self.hw.set_relay(ActuatorMap.PH_VALVE, True)
                    active_actions.append(f"pH Still > {ph_low:.2f} ({ph_val:.2f}) - Next 180s Dosing [Loop {self.ph_loop_count}]")
                else:
                    self.ph_state = "STANDBY"
                    active_actions.append(f"pH Satisfied ({ph_val:.2f} <= {ph_low:.2f})")
            else:
                rem_ph_m = max(0, int(mix_duration - elapsed_ph))
                active_actions.append(f"pH Mixing ({rem_ph_m}s left)")

        # Overall Subsystem Status
        if self.ec_state == "DOSING" and self.ph_state == "DOSING":
            self.state = "EC & pH DOSING ACTIVE"
        elif self.ec_state == "DOSING":
            self.state = "EC DOSING ACTIVE"
        elif self.ph_state == "DOSING":
            self.state = "pH DOSING ACTIVE"
        elif self.ec_state == "MIXING" or self.ph_state == "MIXING":
            self.state = "CIRCULATION & MIXING"
        elif ec_val >= ec_min and ph_low <= ph_val <= ph_high:
            self.state = "SETPOINTS SATISFIED"
        else:
            self.state = "MONITORING"

        if active_actions:
            self.status_msg = " | ".join(active_actions)
        else:
            self.status_msg = f"{active_recipe.get('crop_name','Crop')}: EC ({ec_val:.3f}) & pH ({ph_val:.2f}) Satisfied. Standby."

dosing_engine = DosingEngine(hw)

# ==============================================================================
# ON-SCREEN ALMORA TOUCH KEYPAD (PRESERVED AS REQUESTED)
# ==============================================================================
keypad_modal = None

def make_modal_fullscreen(win, root_win=None):
    win.overrideredirect(True)
    w, h = 1024, 600
    x, y = 0, 0
    if root_win:
        try:
            w = root_win.winfo_width() or 1024
            h = root_win.winfo_height() or 600
            x = root_win.winfo_rootx() or 0
            y = root_win.winfo_rooty() or 0
        except Exception: pass
    win.geometry(f"{w}x{h}+{x}+{y}")
    win.configure(bg="white")
    try: win.attributes("-topmost", True)
    except Exception: pass
    win.lift()
    win.update_idletasks()
    try: win.grab_set()
    except Exception: pass
    win.focus_force()

def add_logo(win):
    if PIL_AVAILABLE and os.path.exists(LOGO_PATH):
        try:
            img = Image.open(LOGO_PATH)
            img.thumbnail((120, 36), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(win, image=photo, bg="white")
            lbl.image = photo
            lbl.place(x=16, y=14)
            return
        except Exception: pass
    tk.Label(win, text="INHYDRO", font=("Helvetica", 14, "bold"), fg="#1565c0", bg="white").place(x=16, y=14)

def add_bottom_right_clock(win):
    lbl = tk.Label(win, text="", font=("Helvetica", 12, "bold"), fg="#475569", bg="white", justify="right")
    lbl.place(relx=1.0, rely=1.0, anchor="se", x=-16, y=-14)
    def update_clock():
        if win.winfo_exists():
            now_dt = datetime.datetime.now()
            lbl.config(text=f"{now_dt.strftime('%d-%m-%Y')}  {now_dt.strftime('%I:%M:%S %p')}")
            win.after(1000, update_clock)
    update_clock()

def open_almora_keypad(title_text, initial_value, callback_on_confirm, is_alphanumeric=False, mode=None, root_window=None):
    global keypad_modal
    if root_window is None:
        try: root_window = app
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

    btn_grid = tk.Frame(kp_main, bg="white")
    btn_grid.pack(pady=6)

    if mode == "alphanumeric":
        rows = [
            list("1234567890"),
            list("QWERTYUIOP"),
            list("ASDFGHJKL"),
            list("ZXCVBNM-._")
        ]
        for r_i, row in enumerate(rows):
            rf = tk.Frame(btn_grid, bg="white")
            rf.pack(pady=2)
            for c in row:
                tk.Button(
                    rf, text=c, font=("Helvetica", 13, "bold"), width=3, height=1,
                    bg="#f8fafc", fg="#0f172a", activebackground="#cbd5e1",
                    bd=2, relief="raised", command=lambda ch=c: kp_press(ch)
                ).pack(side="left", padx=2)
        space_f = tk.Frame(btn_grid, bg="white")
        space_f.pack(pady=3)
        tk.Button(space_f, text="SPACE", font=("Helvetica", 12, "bold"), width=20, bg="#f8fafc", fg="#0f172a", command=lambda: kp_press(" ")).pack(side="left", padx=4)
        tk.Button(space_f, text="⌫ BACK", font=("Helvetica", 12, "bold"), width=10, bg="#fed7aa", fg="#9a3412", command=kp_back).pack(side="left", padx=4)
        tk.Button(space_f, text="CLEAR", font=("Helvetica", 12, "bold"), width=8, bg="#fee2e2", fg="#991b1b", command=kp_clear).pack(side="left", padx=4)
    else:
        keys = [
            ("7", "8", "9"),
            ("4", "5", "6"),
            ("1", "2", "3"),
            ("0", ":" if mode == "time" else ".", "⌫")
        ]
        for r_i, row in enumerate(keys):
            for c_i, k in enumerate(row):
                cmd = kp_back if k == "⌫" else (lambda ch=k: kp_press(ch))
                bg_c = "#fed7aa" if k == "⌫" else "#f8fafc"
                fg_c = "#9a3412" if k == "⌫" else "#0f172a"
                tk.Button(
                    btn_grid, text=k, font=("Helvetica", 16, "bold"), width=6, height=1,
                    bg=bg_c, fg=fg_c, activebackground="#cbd5e1",
                    bd=2, relief="raised", command=cmd
                ).grid(row=r_i, column=c_i, padx=5, pady=3)

    act_f = tk.Frame(kp_main, bg="white")
    act_f.pack(pady=8)
    tk.Button(
        act_f, text="CANCEL", font=("Helvetica", 13, "bold"), bg="#ef4444", fg="white",
        activebackground="#dc2626", bd=2, relief="raised", padx=24, pady=6, cursor="hand2",
        command=lambda: keypad_modal.destroy()
    ).pack(side="left", padx=12)
    tk.Button(
        act_f, text="CONFIRM ✔", font=("Helvetica", 13, "bold"), bg="#15803d", fg="white",
        activebackground="#166534", bd=2, relief="raised", padx=28, pady=6, cursor="hand2",
        command=kp_confirm
    ).pack(side="left", padx=12)

# ==============================================================================
# TOUCH DROPDOWN WIDGET (EXACTLY AS FERTIGATION_HMI_CONTROLLER)
# ==============================================================================
class GridTouchDropdown:
    def __init__(self, parent, root, var, values, on_select=None, cols=3, display_map=None, btn_width=None):
        self.parent = parent
        self.root = root
        self.var = var
        self.values = values
        self.on_select = on_select
        self.cols = cols
        self.display_map = display_map or {}
        self.is_open = False

        btn_kw = {
            "text": self._get_button_label(),
            "font": ("Helvetica", 12, "bold"),
            "bg": "#f1f5f9",
            "fg": "#0f172a",
            "activebackground": "#cbd5e1",
            "activeforeground": "#0f172a",
            "bd": 2,
            "relief": "groove",
            "padx": 14,
            "pady": 5,
            "cursor": "hand2",
            "command": self.toggle
        }
        if btn_width:
            btn_kw["width"] = btn_width

        self.btn = tk.Button(parent, **btn_kw)
        self.menu_frame = tk.Frame(
            self.root, bg="white", bd=2, relief="solid",
            highlightbackground="#1565c0", highlightthickness=2, padx=6, pady=6
        )

    def _get_button_label(self):
        val = self.var.get()
        disp = self.display_map.get(val, str(val).replace("_", " ").title())
        return f"{disp}  ▼"

    def update_label(self):
        self.btn.config(text=self._get_button_label())

    def toggle(self):
        if self.is_open:
            self.close()
        else:
            self.open()

    def open(self):
        if hasattr(self.root, "_active_grid_dropdown") and self.root._active_grid_dropdown:
            try: self.root._active_grid_dropdown.close()
            except Exception: pass
        self.root._active_grid_dropdown = self

        for w in self.menu_frame.winfo_children():
            w.destroy()

        effective_cols = min(self.cols, len(self.values)) if self.values else 1
        curr_val = self.var.get()
        col_w = 230

        for idx, val in enumerate(self.values):
            r = idx // effective_cols
            c = idx % effective_cols
            disp = self.display_map.get(val, str(val).replace("_", " ").title())
            is_active = (str(val).lower() == str(curr_val).lower())

            btn_bg = "#1565c0" if is_active else "#f8fafc"
            btn_fg = "white" if is_active else "#1e293b"
            prefix = "✔  " if is_active else ""

            b = tk.Button(
                self.menu_frame, text=f"{prefix}{disp}", font=("Helvetica", 12, "bold"),
                bg=btn_bg, fg=btn_fg, bd=1, relief="raised", padx=10, pady=8, cursor="hand2",
                wraplength=210, justify="center",
                command=lambda v=val: self._select(v)
            )
            b.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")

        for c in range(effective_cols):
            self.menu_frame.columnconfigure(c, weight=1, minsize=col_w)

        self.root.update_idletasks()
        bx = self.btn.winfo_rootx() - self.root.winfo_rootx()
        by = self.btn.winfo_rooty() - self.root.winfo_rooty() + self.btn.winfo_height() + 2
        menu_w = col_w * effective_cols + 16

        if bx + menu_w > 1010:
            bx = max(8, 1010 - menu_w)
        if bx < 8:
            bx = 8

        self.menu_frame.place(x=bx, y=by, width=menu_w)
        self.menu_frame.lift()
        self.btn.config(bg="#e2e8f0")
        self.is_open = True

    def close(self):
        self.menu_frame.place_forget()
        self.btn.config(bg="#f1f5f9")
        self.is_open = False

    def _select(self, val):
        self.var.set(val)
        self.update_label()
        self.close()
        if self.on_select:
            self.on_select()

# ==============================================================================
# BLUETOOTH SERIAL TERMINAL WI-FI CONNECTIVITY & PRIVATE BROKER TWO-WAY MQTT
# ==============================================================================
CONTROL_BROKER = "147.93.106.142"
CONTROL_PORT = 1883
CONTROL_USER = "Inhydro@5598"
CONTROL_PASS = "MGPL@5598"

is_mqtt_connected = False
control_client = None
active_app_instance = None
active_bt_fds = set()

def set_wifi(ssid: str, password: str) -> str:
    try:
        ssid = str(ssid).strip()
        password = str(password).strip()
        if not ssid:
            return "FAILED: Empty SSID"

        try:
            subprocess.run(["rfkill", "unblock", "wifi"], capture_output=True, timeout=3)
            subprocess.run(["rfkill", "unblock", "all"], capture_output=True, timeout=3)
            subprocess.run(["nmcli", "radio", "wifi", "on"], capture_output=True, timeout=3)
        except Exception: pass

        try:
            subprocess.run(['nmcli', 'connection', 'delete', 'id', ssid], capture_output=True, timeout=4)
            subprocess.run(['nmcli', 'connection', 'delete', ssid], capture_output=True, timeout=4)
        except Exception: pass

        cmd = ['nmcli', '--wait', '15', 'device', 'wifi', 'connect', ssid]
        if password:
            cmd += ['password', password]

        dev_out = ""
        try:
            dev_out = subprocess.check_output(['nmcli', '-t', '-f', 'DEVICE,TYPE', 'dev'], text=True, timeout=4)
            if 'wlan0:wifi' in dev_out:
                cmd += ['ifname', 'wlan0']
        except Exception: pass

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=18)

        if res.returncode != 0 and password:
            try:
                subprocess.run(['nmcli', 'connection', 'delete', 'id', ssid], capture_output=True, timeout=4)
                add_cmd = ['nmcli', 'connection', 'add', 'type', 'wifi', 'con-name', ssid, 'ssid', ssid]
                if 'wlan0' in dev_out:
                    add_cmd += ['ifname', 'wlan0']
                subprocess.run(add_cmd, capture_output=True, text=True, timeout=8)
                subprocess.run([
                    'nmcli', 'connection', 'modify', ssid,
                    '802-11-wireless-security.key-mgmt', 'wpa-psk',
                    '802-11-wireless-security.psk', password
                ], capture_output=True, timeout=6)
                res = subprocess.run(['nmcli', '--wait', '15', 'connection', 'up', 'id', ssid], capture_output=True, text=True, timeout=18)
            except Exception as ex:
                print(f"[Network] Profile fallback error: {ex}")

        if res.returncode == 0:
            print(f"[Network] Connected to Wi-Fi SSID: {ssid}")
            try:
                subprocess.run(["nmcli", "connection", "modify", ssid, "connection.autoconnect", "yes"], capture_output=True, timeout=4)
                subprocess.run(["nmcli", "connection", "modify", ssid, "connection.autoconnect-priority", "10"], capture_output=True, timeout=4)
                subprocess.run(["nmcli", "connection", "modify", ssid, "802-11-wireless.powersave", "2"], capture_output=True, timeout=4)
                subprocess.run(["iw", "dev", "wlan0", "set", "power_save", "off"], capture_output=True, timeout=4)
            except Exception: pass
            return f"SUCCESS: Connected to '{ssid}'!"
        else:
            err_msg = res.stderr.strip() or res.stdout.strip() or "Connection failed"
            return f"FAILED: {err_msg}"
    except subprocess.TimeoutExpired:
        return "FAILED: Connection attempt timed out (18s)."
    except Exception as e:
        return f"ERROR: {str(e)}"

def scan_wifi() -> str:
    try:
        try:
            subprocess.run(['nmcli', 'device', 'wifi', 'rescan'], capture_output=True, timeout=5)
        except Exception: pass

        res = subprocess.run(['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list'], capture_output=True, text=True, timeout=8)
        if res.returncode == 0:
            lines = [n.strip() for n in res.stdout.split('\n') if n.strip()]
            seen = set()
            formatted = []
            for line in lines:
                parts = line.split(':')
                s_name = parts[0].strip()
                if not s_name or s_name == '--' or s_name in seen:
                    continue
                seen.add(s_name)
                sig = parts[1].strip() if len(parts) > 1 else ""
                sec = parts[2].strip() if len(parts) > 2 else ""
                info = f"{len(formatted)+1}. {s_name}"
                if sig: info += f" ({sig}% signal"
                if sec: info += f", {sec})"
                elif sig: info += ")"
                formatted.append(info)
            return "\r\n".join(formatted) if formatted else "No networks found"
        return "SCAN FAILED"
    except subprocess.TimeoutExpired:
        return "SCAN TIMEOUT"
    except Exception as e:
        return f"ERROR: {str(e)}"

def get_connected_wifi_ssid():
    try:
        res = subprocess.run(['nmcli', '-t', '-f', 'active,ssid,signal', 'dev', 'wifi'], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            for line in res.stdout.strip().split('\n'):
                if line.startswith('yes:'):
                    parts = line.split(':')
                    ssid = parts[1]
                    sig = parts[2] if len(parts) > 2 else ''
                    return f"{ssid} (Signal: {sig}%)" if sig else ssid
    except Exception: pass
    try:
        res = subprocess.run(['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show', '--active'], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            for line in res.stdout.strip().split('\n'):
                if ':802-11-wireless' in line or ':wifi' in line:
                    return line.split(':')[0]
    except Exception: pass
    try:
        res = subprocess.run(['iwgetid', '-r'], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception: pass
    return None

def get_system_ip_summary():
    try:
        res = subprocess.run(['hostname', '-I'], capture_output=True, text=True)
        ips = res.stdout.strip()
        return ips if ips else "127.0.0.1"
    except Exception:
        return "Unknown"

# ------------------------------------------------------------------------------
# BLUETOOTH SERIAL TERMINAL APP STATUS & COMMAND HANDLER
# ------------------------------------------------------------------------------
def get_bluetooth_live_status() -> str:
    try:
        curr_ssid = get_connected_wifi_ssid()
        wifi_str = f"CONNECTED ({curr_ssid})" if curr_ssid else "DISCONNECTED"
        dm_ts = cyclic_engine.timer_states.get("dosing_motor", {})
        ir_ts = cyclic_engine.timer_states.get("irrigation", {})
        tf_ts = cyclic_engine.timer_states.get("tank_filling", {})

        lines = [
            f"INHYDRO FERTIGATION & IRRIGATION CONTROLLER",
            #f"Device ID: {DEVICE_NAME}",
            f"Timestamp: {time.strftime('%d-%m-%Y %H:%M:%S')}",
            f"WiFi Status: {wifi_str}",
            "",
            "[LIVE WATER SENSORS]",
            f"  EC        : {f'{hw.pv_ec:.3f} mS/cm' if (hw.pv_ec is not None and not getattr(hw, 'sensor_error', False)) else 'Sensor Error / Offline'}",
            f"  pH        : {f'{hw.pv_ph:.2f}' if (hw.pv_ph is not None and not getattr(hw, 'sensor_error', False)) else 'Sensor Error / Offline'}",
            f"  Water Temp: {f'{hw.pv_water_temp:.1f} °C' if (hw.pv_water_temp is not None and not getattr(hw, 'sensor_error', False)) else 'Sensor Error / Offline'}",
            "",
            "[FERTIGATION DOSING STATE]",
            f"  Phase   : {dosing_engine.state}",
            f"  Status  : {dosing_engine.status_msg}",
            f"  Active Crop: {system_config.get('active_crop', 'cucumber').title()}",
            "",
            "[CYCLIC TIMERS]",
            f"  1. Mix Motor     : State={dm_ts.get('state', 'OFF')} (Rem: {dm_ts.get('time_left', 0):.0f}s)",
            f"  2. Irrigation      : State={ir_ts.get('Tank Fillingstate', 'OFF')} [Ch 5 + Auto Ch 7] (Rem: {ir_ts.get('time_left', 0):.0f}s)",
            f"  3. Tank Filling    : State={tf_ts.get('state', 'OFF')} [Ch 6 + Auto Ch 7] (Rem: {tf_ts.get('time_left', 0):.0f}s)",
            "",
            "[HARDWARE RELAY CHANNELS (1-7)]",
            f"  Ch 1 [Stock A] : {'ON' if hw.get_relay(1) else 'OFF'}    |  Ch 4 [Mix Pump M1]   : {'ON' if hw.get_relay(4) else 'OFF'}",
            f"  Ch 2 [Stock B] : {'ON' if hw.get_relay(2) else 'OFF'}    |  Ch 5 [Bypass V2 (Irr)]: {'ON' if hw.get_relay(5) else 'OFF'}",
            f"  Ch 3 [pH Down] : {'ON' if hw.get_relay(3) else 'OFF'}    |  Ch 6 [Tank V1 (Fill)] : {'ON' if hw.get_relay(6) else 'OFF'}",
            f"                                    |  Ch 7 [Inlet Pump M2] : {'ON' if hw.get_relay(7) else 'OFF'}"
        ]
        return "\r\n".join(lines) + "\r\n"
    except Exception as ex:
        return f"Error reading controller status: {ex}\r\n"

def process_bt_command(raw_cmd: str) -> str:
    raw_cmd = raw_cmd.strip()
    if not raw_cmd:
        return ""
    txt_upper = raw_cmd.upper()
    print(f"[BT CMD] Executing: '{raw_cmd}'")

    if raw_cmd.startswith('{') and raw_cmd.endswith('}'):
        try:
            data = json.loads(raw_cmd)
            if data.get('cmd') in ['wifi', 'wifistatus', 'status', 'check_wifi'] or data.get('action') in ['wifi', 'get_wifi']:
                curr_ssid = get_connected_wifi_ssid()
                ip_addr = get_system_ip_summary()
                return json.dumps({
                    "status": "connected" if curr_ssid else "disconnected",
                    "ssid": curr_ssid or ""
                    #"ip": ip_addr,
                    #"device": DEVICE_NAME
                }) + "\r\n"

            updated_any = False
            if 'crop_recipes' in data or 'recipes' in data:
                sp_data = data.get('crop_recipes') or data.get('recipes')
                if isinstance(sp_data, dict):
                    crop_recipes.update(sp_data)
                    save_json(RECIPE_FILE, crop_recipes)
                    updated_any = True
            if 'cyclic_timers' in data or 'timers' in data:
                tm_data = data.get('cyclic_timers') or data.get('timers')
                if isinstance(tm_data, dict):
                    cyclic_timer_cfg.update(tm_data)
                    save_json(TIMERS_FILE, cyclic_timer_cfg)
                    updated_any = True

            if updated_any:
                if active_app_instance:
                    active_app_instance.after(0, active_app_instance.sync_ui_from_cloud)
                broadcast_current_state()
                return json.dumps({"status": "success", "message": "Setpoints saved & synced"}) + "\r\n"

            ssid_in = data.get('ssid') or data.get('SSID') or data.get('wifi') or data.get('name') or ''
            pass_in = data.get('password') or data.get('pass') or data.get('PASSWORD') or data.get('pwd') or ''
            if ssid_in:
                res_msg = set_wifi(str(ssid_in).strip(), str(pass_in).strip())
                return json.dumps({"status": "success" if "SUCCESS" in res_msg else "error", "message": res_msg}) + "\r\n"
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)}) + "\r\n"

    if txt_upper in ["SCAN", "1", "WIFI SCAN", "SCAN WIFI"]:
        scan_res = scan_wifi()
        return f"\r\n--- NEARBY WI-FI NETWORKS ---\r\n{scan_res}\r\n\r\n"

    elif txt_upper in ["STATUS", "LIVE", "DATA", "3", "INFO"]:
        return f"\r\n{get_bluetooth_live_status()}\r\n"

    elif txt_upper in ["PING", "4"]:
        return f"\r\n[PONG] InHydro Fertigation Controller is Online & Ready!\r\n\r\n"

    elif txt_upper in ["WIFI", "WIFISTATUS", "CURRENTWIFI", "CHECKWIFI", "6", "WIFI?"]:
        curr_ssid = get_connected_wifi_ssid()
        ip_addr = get_system_ip_summary()
        if curr_ssid:
            resp = (
                "\r\n--- WI-FI CONNECTIVITY STATUS ---\r\n"
                f"STATUS     : CONNECTED\r\n"
                f"NETWORK    : {curr_ssid}\r\n"
                #f"IP ADDRESS : {ip_addr}\r\n\r\n"
            )
        else:
            resp = (
                "\r\n--- WI-FI CONNECTIVITY STATUS ---\r\n"
                "STATUS     : Not Connected\r\n"
                "Note       : Send 'SCAN' or '1' to search networks,\r\n"
                "             or 'WIFI:SSID:PASSWORD' to connect.\r\n\r\n"
            )
        return resp

    elif txt_upper in ["HELP", "5", "?", "MENU"]:
        return (
            "\r\n--- INHYDRO CONTROLLER COMMAND MENU ---\r\n"
            "1. SCAN                  (Scan nearby WiFi networks)\r\n"
            "2. WIFI:SSID:PASSWORD    (Connect to WiFi)\r\n"
            "3. STATUS                (Live sensors & state)\r\n"
            "4. PING                  (Ping test)\r\n"
            "5. HELP                  (Command menu)\r\n"
            "6. WIFI                  (Check WiFi status & IP)\r\n\r\n"
        )

    ssid_in = None
    pass_in = ""

    for pfx in ["WIFI:", "2:", "SET_WIFI:", "CONNECT:", "WIFI=", "SET_WIFI "]:
        if txt_upper.startswith(pfx):
            raw_body = raw_cmd[len(pfx):].strip()
            if ":" in raw_body:
                parts = raw_body.split(":", 1)
                ssid_in, pass_in = parts[0].strip(), parts[1].strip()
            elif "," in raw_body:
                parts = raw_body.split(",", 1)
                ssid_in, pass_in = parts[0].strip(), parts[1].strip()
            elif " " in raw_body:
                parts = raw_body.split(" ", 1)
                ssid_in, pass_in = parts[0].strip(), parts[1].strip()
            else:
                ssid_in, pass_in = raw_body, ""
            break

    if ssid_in is None:
        if ":" in raw_cmd:
            parts = raw_cmd.split(":", 1)
            ssid_in, pass_in = parts[0].strip(), parts[1].strip()
        elif "," in raw_cmd:
            parts = raw_cmd.split(",", 1)
            ssid_in, pass_in = parts[0].strip(), parts[1].strip()

    if ssid_in:
        if ssid_in.startswith('"') and ssid_in.endswith('"') and len(ssid_in) > 1:
            ssid_in = ssid_in[1:-1]
        if pass_in.startswith('"') and pass_in.endswith('"') and len(pass_in) > 1:
            pass_in = pass_in[1:-1]
        ssid_in = ssid_in.strip()
        pass_in = pass_in.strip()
        if ssid_in:
            res_msg = set_wifi(ssid_in, pass_in)
            return f"\r\n[Connecting to '{ssid_in}'...]\r\n{res_msg}\r\n\r\n"

    return f"\r\nACK: Received '{raw_cmd}'. Send HELP for command list.\r\n\r\n"

def handle_bt_client_fd(fd_int):
    global active_bt_fds
    active_bt_fds.add(fd_int)
    try:
        banner = (
            f"\r\n  INHYDRO FERTIGATION & IRRIGATION CONTROLLER  \r\n"
            "Commands:\r\n"
            "  1. SCAN                  (Scan nearby WiFi networks)\r\n"
            "  2. WIFI:SSID:PASSWORD    (Connect to WiFi)\r\n"
            "  3. STATUS                (Live sensors & state)\r\n"
            "  4. PING                  (Ping test)\r\n"
            "  5. HELP                  (Command menu)\r\n"
            "  6. WIFI                  (Check WiFi status & IP)\r\n\r\n"
        )
        os.write(fd_int, banner.encode('utf-8'))
        buf = ""
        while running:
            try:
                raw = os.read(fd_int, 1024)
            except Exception:
                break
            if not raw:
                break
            buf += raw.decode('utf-8', errors='ignore')
            while "\n" in buf or "\r" in buf:
                if "\r\n" in buf:
                    line, buf = buf.split("\r\n", 1)
                elif "\n" in buf:
                    line, buf = buf.split("\n", 1)
                else:
                    line, buf = buf.split("\r", 1)
                cmd_line = line.strip()
                if cmd_line:
                    resp = process_bt_command(cmd_line)
                    if resp:
                        os.write(fd_int, resp.encode('utf-8'))
    except Exception as e:
        print(f"[BT] Client FD note: {e}")
    finally:
        active_bt_fds.discard(fd_int)
        try: os.close(fd_int)
        except Exception: pass

def register_spp_dbus():
    try:
        import dbus, dbus.service
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib

        DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()

        class BluetoothAgent(dbus.service.Object):
            @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
            def Release(self): pass

            @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
            def AuthorizeService(self, device, uuid):
                self._auto_trust(device)
                return

            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='s')
            def RequestPinCode(self, device):
                self._auto_trust(device)
                return '0000'

            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='u')
            def RequestPasskey(self, device):
                self._auto_trust(device)
                return dbus.UInt32(123456)

            @dbus.service.method('org.bluez.Agent1', in_signature='ouq', out_signature='')
            def DisplayPasskey(self, device, passkey, entered): pass

            @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
            def DisplayPinCode(self, device, pincode): pass

            @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='')
            def RequestConfirmation(self, device, passkey):
                self._auto_trust(device)
                return

            @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
            def RequestAuthorization(self, device):
                self._auto_trust(device)
                return

            @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
            def Cancel(self): pass

            def _auto_trust(self, dev_path):
                try:
                    d_obj = bus.get_object('org.bluez', dev_path)
                    d_props = dbus.Interface(d_obj, 'org.freedesktop.DBus.Properties')
                    d_props.Set('org.bluez.Device1', 'Trusted', dbus.Boolean(True))
                except Exception: pass

        class BluezProfile(dbus.service.Object):
            @dbus.service.method('org.bluez.Profile1', in_signature='oha{sv}', out_signature='')
            def NewConnection(self, path, fd, properties):
                fd_int = fd.take()
                flags = fcntl.fcntl(fd_int, fcntl.F_GETFL)
                fcntl.fcntl(fd_int, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
                threading.Thread(target=handle_bt_client_fd, args=(fd_int,), daemon=True).start()

            @dbus.service.method('org.bluez.Profile1', in_signature='o', out_signature='')
            def RequestDisconnection(self, path): pass

        agent_path = '/inhydro/fert_agent'
        try:
            agent = BluetoothAgent(bus, agent_path)
            obj = bus.get_object('org.bluez', '/org/bluez')
            manager = dbus.Interface(obj, 'org.bluez.AgentManager1')
            try: manager.UnregisterAgent(agent_path)
            except Exception: pass
            manager.RegisterAgent(agent_path, 'NoInputNoOutput')
            manager.RequestDefaultAgent(agent_path)
        except Exception as e:
            print(f"[BT] Agent registration note: {e}")

        profile_path = '/inhydro/fert_spp_profile'
        profile = BluezProfile(bus, profile_path)
        manager_p = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'), 'org.bluez.ProfileManager1')
        try: manager_p.UnregisterProfile(profile_path)
        except Exception: pass

        spp_uuid = "00001101-0000-1000-8000-00805f9b34fb"
        opts = {
            'AutoConnect': dbus.Boolean(True),
            'Role': 'server',
            'Name': f'InHydro_{DEVICE_NAME}',
            'Channel': dbus.UInt16(1),
            'RequireAuthentication': dbus.Boolean(False),
            'RequireAuthorization': dbus.Boolean(False)
        }
        manager_p.RegisterProfile(profile_path, spp_uuid, opts)

        mainloop = GLib.MainLoop()
        threading.Thread(target=mainloop.run, daemon=True).start()
    except Exception as e:
        print(f"[BT] DBus setup note: {e}")

def start_bluetooth_server():
    register_spp_dbus()
    while running:
        srv = None
        try:
            os.system("sudo -n sdptool add SP >/dev/null 2>&1 || sdptool add SP >/dev/null 2>&1")
            time.sleep(0.5)
            srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            bound = False
            for attempt in range(10):
                if not running: return
                try:
                    srv.bind((socket.BDADDR_ANY, 1))
                    bound = True
                    break
                except OSError:
                    time.sleep(1.0)

            if not bound:
                time.sleep(10)
                continue

            srv.listen(1)
            print("[BT] Bluetooth RFCOMM Server listening on channel 1 (Ready for Serial Terminal).")
            while running:
                client = None
                try:
                    client, client_info = srv.accept()
                    print(f"[BT] Raw RFCOMM Terminal connected from {client_info}")
                    banner = (
                        f"\r\n  INHYDRO FERTIGATION & CYCLIC TIMERS CONTROLLER  \r\n"
                        "Commands:\r\n"
                        "  1. SCAN\r\n"
                        "  2. WIFI:SSID:PASSWORD\r\n"
                        "  3. STATUS\r\n"
                        "  4. PING\r\n"
                        "  5. HELP\r\n\r\n"
                    )
                    client.sendall(banner.encode('utf-8'))
                    buf = ""
                    while running:
                        data = client.recv(1024)
                        if not data: break
                        buf += data.decode('utf-8', errors='ignore')
                        while "\n" in buf or "\r" in buf:
                            if "\r\n" in buf:
                                line, buf = buf.split("\r\n", 1)
                            elif "\n" in buf:
                                line, buf = buf.split("\n", 1)
                            else:
                                line, buf = buf.split("\r", 1)
                            cmd_line = line.strip()
                            if cmd_line:
                                resp = process_bt_command(cmd_line)
                                if resp:
                                    client.sendall(resp.encode('utf-8'))
                except Exception: pass
                finally:
                    if client:
                        try: client.close()
                        except Exception: pass
        except Exception:
            time.sleep(5)
        finally:
            if srv:
                try: srv.close()
                except Exception: pass
            time.sleep(2)

def auto_trust_devices():
    dev_alias = f"Inhydro_{DEVICE_NAME}"
    try:
        subprocess.run(["bluetoothctl", "power", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "system-alias", dev_alias], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "discoverable-timeout", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "pairable-timeout", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "discoverable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["bluetoothctl", "pairable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception: pass

    while running:
        try:
            subprocess.run(["bluetoothctl", "discoverable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            subprocess.run(["bluetoothctl", "pairable", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            out = subprocess.check_output(['bluetoothctl', 'devices'], text=True, timeout=3)
            for line in out.split('\n'):
                if line.startswith('Device '):
                    mac = line.split(' ')[1].strip()
                    subprocess.run(["bluetoothctl", "trust", mac], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except Exception: pass
        time.sleep(10)

# ------------------------------------------------------------------------------
# TWO-WAY MQTT ON PRIVATE BROKER (MATCHING FERTIGATION_HMI_CONTROLLER)
# ------------------------------------------------------------------------------
def broadcast_current_state():
    if not is_mqtt_connected or not control_client:
        return
    try:
        now_iso = datetime.datetime.now().isoformat()
        payload = {
            "source": "device",
            "device": DEVICE_NAME,
            "device_id": DEVICE_NAME,
            "timestamp": now_iso,
            "crop_recipes": crop_recipes,
            "cyclic_timers": cyclic_timer_cfg,
            "active_crop": system_config.get("active_crop", "cucumber"),
            "relays": {f"ch_{ch}": hw.get_relay(ch) for ch in range(1, 7)}
        }
        msg_str = json.dumps(payload)
        control_client.publish(f"inhydro/{DEVICE_NAME}/setpoints/current", msg_str, retain=True)
        control_client.publish(f"inhydro/{DEVICE_NAME.lower()}/setpoints/current", msg_str, retain=True)
        print(f"[MQTT SYNC] Broadcasted current setpoints state to inhydro/{DEVICE_NAME}/setpoints/current")
    except Exception as e:
        print(f"[MQTT SYNC ERROR] {e}")

def on_control_message(client, userdata, msg):
    try:
        topic = str(msg.topic)
        if topic.endswith(("/telemetry", "/heartbeat", "/command/status", "/setpoints/current", "/state")):
            return
        if getattr(msg, 'retain', False):
            return

        try:
            payload_str = msg.payload.decode('utf-8')
            new_data = json.loads(payload_str)
        except Exception:
            new_data = {"raw": msg.payload.decode('utf-8', errors='ignore').strip()}

        if isinstance(new_data, dict) and (new_data.get("source") == "device" or new_data.get("from") == "device"):
            return

        if topic.endswith("/command"):
            action = str(new_data.get("action", new_data.get("raw", ""))).lower().strip()
            print(f"[MQTT CMD] Received remote action: '{action}'")

            if action == "restart":
                if active_app_instance:
                    active_app_instance.after(500, active_app_instance.exit_application)
            elif action in ["start_fertigation", "start_fert"]:
                if active_app_instance:
                    active_app_instance.var_auto_dosing.set(True)
                    active_app_instance._update_auto_dosing_ui()
            elif action in ["stop_fertigation", "stop_fert", "abort_fert"]:
                if active_app_instance:
                    active_app_instance.var_auto_dosing.set(False)
                    active_app_instance._update_auto_dosing_ui()
                dosing_engine.reset()
            elif action in ["start_dosing_motor", "start_motor"]:
                cyclic_engine.start_timer("dosing_motor")
            elif action in ["stop_dosing_motor", "stop_motor"]:
                cyclic_engine.stop_timer("dosing_motor")
            elif action in ["start_irrigation", "start_zone_1", "start_z1", "start_irrigation_1"]:
                cyclic_engine.start_timer("irrigation")
            elif action in ["stop_irrigation", "stop_all_irrigation"]:
                cyclic_engine.stop_timer("irrigation")
            elif action in ["start_tank_filling", "start_filling", "start_tf"]:
                cyclic_engine.start_timer("tank_filling")
            elif action in ["stop_tank_filling", "stop_filling", "stop_tf"]:
                cyclic_engine.stop_timer("tank_filling")
            elif action == "relay_toggle":
                ch = int(new_data.get("channel", 0))
                st = bool(new_data.get("state", False))
                if 1 <= ch <= 7:
                    hw.set_relay(ch, st)

            cmd_ack = {"device": DEVICE_NAME, "action": action, "status": "executed", "timestamp": time.time()}
            client.publish(f"inhydro/{DEVICE_NAME}/command/status", json.dumps(cmd_ack), retain=False)

        elif topic.endswith("/setpoints/update") or topic.endswith("/config/update"):
            print(f"[MQTT SYNC] Cloud update received: {new_data}")
            updated_recipes = False
            updated_timers = False

            if "crop_recipes" in new_data and isinstance(new_data["crop_recipes"], dict):
                crop_recipes.update(new_data["crop_recipes"])
                updated_recipes = True
            elif "recipes" in new_data and isinstance(new_data["recipes"], dict):
                crop_recipes.update(new_data["recipes"])
                updated_recipes = True
            elif "crop_name" in new_data or "ec_min" in new_data:
                crop_k = str(new_data.get("crop", new_data.get("crop_key", "cucumber"))).lower()
                if crop_k in crop_recipes:
                    crop_recipes[crop_k].update(new_data)
                    updated_recipes = True

            if "cyclic_timers" in new_data and isinstance(new_data["cyclic_timers"], dict):
                cyclic_timer_cfg.update(new_data["cyclic_timers"])
                updated_timers = True
            elif "timers" in new_data and isinstance(new_data["timers"], dict):
                cyclic_timer_cfg.update(new_data["timers"])
                updated_timers = True

            if updated_recipes:
                save_json(RECIPE_FILE, crop_recipes)
                print(f"[MQTT SYNC] Saved updated crop recipes to {RECIPE_FILE}")
            if updated_timers:
                save_json(TIMERS_FILE, cyclic_timer_cfg)
                print(f"[MQTT SYNC] Saved updated timers to {TIMERS_FILE}")

            if active_app_instance:
                active_app_instance.after(0, active_app_instance.sync_ui_from_cloud)

            broadcast_current_state()

        elif topic.endswith("/request_sync"):
            broadcast_current_state()
    except Exception as e:
        print(f"[MQTT MSG ERROR] {e}")

def on_control_connect(client, userdata, flags, rc=0, properties=None, *args, **kwargs):
    global is_mqtt_connected
    if rc == 0:
        is_mqtt_connected = True
        for dev_id in list(set([DEVICE_NAME, DEVICE_NAME.lower()])):
            client.subscribe(f"inhydro/{dev_id}/setpoints/update")
            client.subscribe(f"inhydro/{dev_id}/config/update")
            client.subscribe(f"inhydro/{dev_id}/command")
            client.subscribe(f"inhydro/{dev_id}/setpoints/request_sync")
            client.subscribe(f"inhydro/{dev_id}/request_sync")
        print(f"[MQTT] Connected & subscribed to private broker ({CONTROL_BROKER}) for {DEVICE_NAME}")
        broadcast_current_state()
    else:
        is_mqtt_connected = False
        print(f"[MQTT] Connect failed with code {rc}")

def on_control_disconnect(client, userdata, *args, **kwargs):
    global is_mqtt_connected
    is_mqtt_connected = False
    print("[MQTT] Disconnected from private broker. Reconnecting...")

def start_mqtt_client():
    global control_client
    if not MQTT_AVAILABLE:
        print("[MQTT] paho-mqtt not available.")
        return

    _client_id = f"Fertigation_{DEVICE_NAME}_{_uuid.uuid4().hex[:6]}"
    try:
        control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, _client_id)
    except AttributeError:
        control_client = mqtt.Client(_client_id)

    control_client.on_message = on_control_message
    control_client.on_connect = on_control_connect
    control_client.on_disconnect = on_control_disconnect

    try:
        if CONTROL_USER and CONTROL_PASS:
            control_client.username_pw_set(CONTROL_USER, CONTROL_PASS)
        control_client.connect_async(CONTROL_BROKER, CONTROL_PORT, 60)
        control_client.loop_start()
        print(f"[MQTT] Private broker client loop started for {DEVICE_NAME} on {CONTROL_BROKER}:{CONTROL_PORT}")
    except Exception as e:
        print(f"[MQTT] Connection start error: {e}")

def mqtt_heartbeat_worker():
    time.sleep(5)
    while running:
        try:
            time.sleep(10)
            if not running: break
            if control_client and control_client.is_connected():
                now_dt = datetime.datetime.now()
                hb_payload = json.dumps({
                    "device": DEVICE_NAME,
                    "device_id": DEVICE_NAME,
                    "status": "online",
                    "timestamp": now_dt.isoformat(),
                    "time": now_dt.strftime("%Y-%m-%d %H:%M:%S")
                })
                control_client.publish(f"inhydro/{DEVICE_NAME}/heartbeat", hb_payload, retain=False)
                control_client.publish(f"inhydro/{DEVICE_NAME.lower()}/heartbeat", hb_payload, retain=False)
            elif control_client and not control_client.is_connected():
                try: control_client.reconnect()
                except Exception: pass
        except Exception:
            pass

def mqtt_telemetry_worker():
    time.sleep(3)
    while running:
        try:
            time.sleep(3)
            if not running: break
            if control_client and control_client.is_connected():
                dm_ts = cyclic_engine.timer_states.get("dosing_motor", {})
                ir_ts = cyclic_engine.timer_states.get("irrigation", {})
                tf_ts = cyclic_engine.timer_states.get("tank_filling", {})
                telemetry = {
                    "source": "device",
                    "device": DEVICE_NAME,
                    "device_id": DEVICE_NAME,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "active_crop": system_config.get("active_crop", "cucumber"),
                    "ec": round(hw.pv_ec, 3) if (hw.pv_ec is not None and not getattr(hw, "sensor_error", False)) else None,
                    "ph": round(hw.pv_ph, 2) if (hw.pv_ph is not None and not getattr(hw, "sensor_error", False)) else None,
                    "water_temp": round(hw.pv_water_temp, 1) if (hw.pv_water_temp is not None and not getattr(hw, "sensor_error", False)) else None,
                    "sensor_online": not getattr(hw, "sensor_error", False),
                    "dosing": {
                        "state": dosing_engine.state,
                        "status_msg": dosing_engine.status_msg,
                        "ec_active": dosing_engine.ec_active,
                        "ph_active": dosing_engine.ph_active
                    },
                    "timers": {
                        "dosing_motor": {
                            "name": cyclic_timer_cfg.get("dosing_motor", {}).get("name", "Mix Motor "),
                            "state": dm_ts.get("state", "OFF"),
                            "time_left": round(dm_ts.get("time_left", 0.0), 1),
                            "relay": ActuatorMap.DOSING_MOTOR
                        },
                        "irrigation": {
                            "name": cyclic_timer_cfg.get("irrigation", {}).get("name", "Irrigation"),
                            "state": ir_ts.get("state", "OFF"),
                            "time_left": round(ir_ts.get("time_left", 0.0), 1),
                            "relay": ActuatorMap.VALVE_2,
                            "inlet_motor": ActuatorMap.INLET_MOTOR
                        },
                        "tank_filling": {
                            "name": cyclic_timer_cfg.get("tank_filling", {}).get("name", "Tank Filling"),
                            "state": tf_ts.get("state", "OFF"),
                            "time_left": round(tf_ts.get("time_left", 0.0), 1),
                            "relay": ActuatorMap.VALVE_1,
                            "inlet_motor": ActuatorMap.INLET_MOTOR
                        }
                    },
                    "relays": {f"ch_{ch}": hw.get_relay(ch) for ch in range(1, 8)}
                }
                msg_str = json.dumps(telemetry)
                control_client.publish(f"inhydro/{DEVICE_NAME}/telemetry", msg_str, retain=False)
                control_client.publish(f"inhydro/{DEVICE_NAME.lower()}/telemetry", msg_str, retain=False)
        except Exception:
            pass

# ==============================================================================
# MAIN HMI GRAPHICS & GUI (MATCHING FERTIGATION_HMI_CONTROLLER EXACT SIZES & STYLES)
# ==============================================================================
class InHydroFertigationApp(tk.Tk):
    COLOR_PRIMARY     = "#1565c0"
    COLOR_PRIMARY_DARK= "#0d47a1"
    COLOR_ACCENT      = "#0891b2"
    COLOR_BG_MAIN     = "#ffffff"
    COLOR_BG_CARD     = "#f8fafc"
    COLOR_TEXT_MAIN   = "#0f172a"
    COLOR_TEXT_SUB    = "#475569"
    COLOR_SUCCESS     = "#15803d"
    COLOR_OFF         = "#94a3b8"
    COLOR_DANGER      = "#dc2626"

    PAGE_SEQUENCE = ["dashboard", "monitoring", "fertigation", "irrigation", "settings"]

    PAGE_DISPLAY_NAMES = {
        "dashboard":   "DASHBOARD",
        "monitoring":  "LIVE MONITORING",
        "fertigation": "FERTIGATION",
        "irrigation":  "CYCLIC IRRIGATION",
        "settings":    "SETTINGS & SAFETY",
    }

    def __init__(self):
        super().__init__()
        global active_app_instance
        active_app_instance = self
        self.title("InHydro Fertigation & Cyclic Controller")
        self.geometry("1024x600")
        self.minsize(800, 480)
        self.configure(bg=self.COLOR_BG_MAIN)

        try:
            self.attributes("-fullscreen", True)
        except Exception:
            try:
                self.state("zoomed")
            except Exception:
                pass

        self.logo_img = None
        self._load_logo()
        self._active_grid_dropdown = None

        saved_crop = system_config.get("active_crop", "cucumber")
        if saved_crop not in crop_recipes:
            saved_crop = "cucumber"
        self.var_recipe = tk.StringVar(value=saved_crop)

        self.var_auto_dosing = tk.BooleanVar(value=True)

        self.screens = {}
        self.current_screen_key = "dashboard"

        self._build_header()
        self._build_bottom_dock()

        self.container = tk.Frame(self, bg="white")
        self.container.pack(fill="both", expand=True, padx=8, pady=2)

        self.screens["dashboard"]   = self._create_dashboard_screen(self.container)
        self.screens["monitoring"]  = self._create_monitoring_screen(self.container)
        self.screens["fertigation"] = self._create_fertigation_screen(self.container)
        self.screens["irrigation"]  = self._create_irrigation_screen(self.container)
        self.screens["settings"]    = self._create_settings_screen(self.container)

        self._load_recipe_into_fert_screen()
        self._load_crop_into_settings_tab()

        self.show_screen("dashboard")

        # Global click to close active touch dropdown
        self.bind("<Button-1>", self._on_global_click, add="+")
        self.bind("<Escape>", lambda e: self.exit_application())
        self.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.bind("<Home>", lambda e: self.show_screen("dashboard"))

        self.after(100, self._periodic_tick)

    def sync_ui_from_cloud(self):
        try:
            self._load_recipe_into_fert_screen()
            self._load_crop_into_settings_tab()
            if hasattr(self, "dd_fert_crop"):
                self.dd_fert_crop.display_map = {k: crop_recipes[k].get("crop_name", k.title()) for k in crop_recipes}
                self.dd_fert_crop.update_label()
            if hasattr(self, "dd_set_crop"):
                self.dd_set_crop.display_map = {k: crop_recipes[k].get("crop_name", k.title()) for k in crop_recipes}
                self.dd_set_crop.update_label()
        except Exception as e:
            print(f"[UI SYNC ERROR] {e}")

    def _load_logo(self):
        if PIL_AVAILABLE and os.path.exists(LOGO_PATH):
            try:
                img = Image.open(LOGO_PATH)
                img.thumbnail((120, 36), Image.Resampling.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(img)
            except Exception: pass

    def _on_global_click(self, event):
        active_dd = getattr(self, "_active_grid_dropdown", None)
        if active_dd and active_dd.is_open:
            w = event.widget
            curr = w
            in_dd = False
            while curr:
                if curr in (active_dd.menu_frame, active_dd.btn):
                    in_dd = True
                    break
                try: curr = curr.master
                except Exception: break
            if not in_dd:
                active_dd.close()

    def toggle_fullscreen(self):
        cur = self.attributes("-fullscreen")
        self.attributes("-fullscreen", not cur)

    def exit_application(self):
        if messagebox.askyesno("Exit Application", "Exit InHydro Controller? All relays will be turned OFF."):
            hw.emergency_all_off()
            dosing_engine.stop_manual_dosing()
            cyclic_engine.stop_all_timers()
            self.destroy()
            sys.exit(0)

    def restart_application(self):
        hw.emergency_all_off()
        dosing_engine.stop_manual_dosing()
        cyclic_engine.stop_all_timers()
        try:
            system_config["active_crop"] = self.var_recipe.get()
            save_json(CONFIG_FILE, system_config)
            save_json(CONFIG_FALLBACK_FILE, system_config)
        except Exception: pass
        try: self.destroy()
        except Exception: pass
        python = sys.executable
        os.execv(python, [python] + sys.argv)

    def _build_header(self):
        h = tk.Frame(self, bg="white", height=52)
        h.pack(fill="x", side="top", pady=(4, 2))
        h.pack_propagate(False)

        self.lbl_clock = tk.Label(
            h, text="", font=("Helvetica", 12, "bold"),
            fg="#0f172a", bg="white", justify="left"
        )
        self.lbl_clock.place(relx=0.0, rely=0.5, anchor="w", x=16)

        lbl_title = tk.Label(
            h, text="INHYDRO FERTIGATION & CYCLIC IRRIGATION SYSTEM",
            font=("Helvetica", 16, "bold"), fg=self.COLOR_PRIMARY, bg="white"
        )
        lbl_title.place(relx=0.5, rely=0.5, anchor="center")

        if self.logo_img:
            lbl_logo = tk.Label(h, image=self.logo_img, bg="white")
            lbl_logo.place(relx=1.0, rely=0.5, anchor="e", x=-16)
        else:
            lbl_logo = tk.Label(h, text="INHYDRO", font=("Helvetica", 13, "bold"), fg=self.COLOR_PRIMARY, bg="white")
            lbl_logo.place(relx=1.0, rely=0.5, anchor="e", x=-16)

    def _build_bottom_dock(self):
        self.dock = tk.Frame(self, bg="#eeeeee", height=60, bd=1, relief="solid", padx=12)
        self.dock.pack(fill="x", side="bottom")
        self.dock.pack_propagate(False)

        self.btn_dock_restart = tk.Button(
            self.dock, text="🔄 RESTART ", font=("Helvetica", 13, "bold"),
            bg=self.COLOR_PRIMARY, fg="white", activebackground=self.COLOR_PRIMARY_DARK, activeforeground="white",
            bd=2, relief="raised", padx=28, pady=6, cursor="hand2", command=self.restart_application
        )
        self.dock_nav_frame = tk.Frame(self.dock, bg="#eeeeee")

        self.btn_dock_prev = tk.Button(
            self.dock_nav_frame, text="◀ PREV", font=("Helvetica", 13, "bold"),
            bg="#475569", fg="white", activebackground="#334155", activeforeground="white",
            bd=2, relief="raised", padx=20, pady=6, cursor="hand2", command=self.prev_screen
        )
        self.btn_dock_dash = tk.Button(
            self.dock_nav_frame, text="🏠 DASHBOARD", font=("Helvetica", 13, "bold"),
            bg=self.COLOR_ACCENT, fg="white", activebackground="#0e7490", activeforeground="white",
            bd=2, relief="raised", padx=24, pady=6, cursor="hand2",
            command=lambda: self.show_screen("dashboard")
        )
        self.btn_dock_next = tk.Button(
            self.dock_nav_frame, text="NEXT ▶", font=("Helvetica", 13, "bold"),
            bg=self.COLOR_PRIMARY, fg="white", activebackground=self.COLOR_PRIMARY_DARK, activeforeground="white",
            bd=2, relief="raised", padx=20, pady=6, cursor="hand2", command=self.next_screen
        )

    def prev_screen(self):
        try:
            curr_idx = self.PAGE_SEQUENCE.index(self.current_screen_key)
            prev_idx = (curr_idx - 1) % len(self.PAGE_SEQUENCE)
            self.show_screen(self.PAGE_SEQUENCE[prev_idx])
        except Exception:
            self.show_screen("dashboard")

    def next_screen(self):
        try:
            curr_idx = self.PAGE_SEQUENCE.index(self.current_screen_key)
            next_idx = (curr_idx + 1) % len(self.PAGE_SEQUENCE)
            self.show_screen(self.PAGE_SEQUENCE[next_idx])
        except Exception:
            self.show_screen("dashboard")

    def show_screen(self, screen_key: str):
        if screen_key not in self.screens:
            return

        if hasattr(self, "_active_grid_dropdown") and self._active_grid_dropdown:
            try: self._active_grid_dropdown.close()
            except Exception: pass

        for s in self.screens.values():
            s.pack_forget()

        self.screens[screen_key].pack(fill="both", expand=True)
        self.current_screen_key = screen_key

        self.btn_dock_restart.pack_forget()
        self.dock_nav_frame.pack_forget()
        self.btn_dock_prev.pack_forget()
        self.btn_dock_dash.pack_forget()
        self.btn_dock_next.pack_forget()

        if screen_key == "dashboard":
            self.btn_dock_restart.pack(anchor="center", pady=6)
        else:
            self.dock_nav_frame.pack(anchor="center", pady=6)
            self.btn_dock_prev.pack(side="left", padx=14)
            self.btn_dock_dash.pack(side="left", padx=14)
            self.btn_dock_next.pack(side="left", padx=14)

        if screen_key == "fertigation":
            self._load_recipe_into_fert_screen()
        elif screen_key == "settings":
            self._load_crop_into_settings_tab()

    # ==========================================================================
    # SCREEN 1: DASHBOARD (EXACT FERTIGATION_HMI_CONTROLLER TILES)
    # ==========================================================================
    def _create_dashboard_screen(self, parent):
        f = tk.Frame(parent, bg="white")

        grid_frame = tk.Frame(f, bg="white")
        grid_frame.pack(fill="both", expand=True, padx=10, pady=8)

        for i in range(2):
            grid_frame.columnconfigure(i, weight=1, uniform="dash_col")
            grid_frame.rowconfigure(i, weight=1, uniform="dash_row")

        modules = [
            ("monitoring",  "LIVE MONITORING"),
            ("fertigation", "FERTIGATION"),
            ("irrigation",  "CYCLIC IRRIGATION"),
            ("settings",    "SETTINGS & SAFETY")
        ]

        def bind_card_hover_and_click(card_widget, label_widget, target_key):
            def on_enter(e):
                card_widget.config(bg="#0d47a1")
                label_widget.config(bg="#0d47a1")
            def on_leave(e):
                card_widget.config(bg="#1565c0")
                label_widget.config(bg="#1565c0")
            def on_click(e):
                self.show_screen(target_key)

            card_widget.bind("<Enter>", on_enter)
            card_widget.bind("<Leave>", on_leave)
            label_widget.bind("<Enter>", on_enter)
            label_widget.bind("<Leave>", on_leave)
            card_widget.bind("<Button-1>", on_click)
            label_widget.bind("<Button-1>", on_click)

        for idx, (key, title_text) in enumerate(modules):
            r = idx // 2
            c = idx % 2
            card = tk.Frame(grid_frame, bg="#1565c0", bd=6, relief="raised", cursor="hand2")
            card.grid(row=r, column=c, padx=10, pady=8, sticky="nsew")

            lbl_name = tk.Label(
                card, text=title_text, font=("Helvetica", 22, "bold"),
                fg="white", bg="#1565c0", anchor="center", cursor="hand2"
            )
            lbl_name.pack(expand=True, fill="both")
            bind_card_hover_and_click(card, lbl_name, key)

        return f

    # ==========================================================================
    # SCREEN 2: LIVE MONITORING (EXACT FERTIGATION_HMI_CONTROLLER LAYOUT)
    # ==========================================================================
    def _create_monitoring_screen(self, parent):
        f = tk.Frame(parent, bg="white")
        body = tk.Frame(f, bg="white")
        body.pack(fill="both", expand=True, padx=10, pady=2)

        center_container = tk.Frame(body, bg="white")
        center_container.pack(anchor="center", pady=(2, 4))

        top_live_row = tk.Frame(center_container, bg="white")
        top_live_row.pack(side="top", anchor="center", pady=(0, 4))

        for col_i in range(3):
            top_live_row.columnconfigure(col_i, minsize=295, weight=1, uniform="live_col")

        card_ec = tk.LabelFrame(top_live_row, text=" EC VALUE (mS/cm) ", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white", bd=2, relief="groove", padx=12, pady=4)
        card_ec.grid(row=0, column=0, padx=4, pady=2, sticky="nsew")
        self.lbl_mon_ec_val = tk.Label(card_ec, text="--", font=("Helvetica", 22, "bold"), fg="#1565c0", bg="white")
        self.lbl_mon_ec_val.pack(anchor="center", pady=1)
        self.lbl_mon_ec_target = tk.Label(card_ec, text="Target: 1.80 - 2.20 mS/cm", font=("Helvetica", 10, "bold"), fg=self.COLOR_TEXT_SUB, bg="white")
        self.lbl_mon_ec_target.pack(anchor="center")

        card_ph = tk.LabelFrame(top_live_row, text=" pH VALUE ", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white", bd=2, relief="groove", padx=12, pady=4)
        card_ph.grid(row=0, column=1, padx=4, pady=2, sticky="nsew")
        self.lbl_mon_ph_val = tk.Label(card_ph, text="--", font=("Helvetica", 22, "bold"), fg="#0891b2", bg="white")
        self.lbl_mon_ph_val.pack(anchor="center", pady=1)
        self.lbl_mon_ph_target = tk.Label(card_ph, text="Target: 5.40 - 6.40", font=("Helvetica", 10, "bold"), fg=self.COLOR_TEXT_SUB, bg="white")
        self.lbl_mon_ph_target.pack(anchor="center")

        card_temp = tk.LabelFrame(top_live_row, text=" WATER TEMPERATURE ", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white", bd=2, relief="groove", padx=12, pady=4)
        card_temp.grid(row=0, column=2, padx=4, pady=2, sticky="nsew")
        self.lbl_mon_temp = tk.Label(card_temp, text="--", font=("Helvetica", 22, "bold"), fg="#0f172a", bg="white")
        self.lbl_mon_temp.pack(anchor="center", pady=1)
        tk.Label(card_temp, text="Tank Sensor Probe", font=("Helvetica", 10, "bold"), fg=self.COLOR_TEXT_SUB, bg="white").pack(anchor="center")

        col_relays = tk.LabelFrame(center_container, text=" HARDWARE RELAYS (CH 1-8) ", font=("Helvetica", 12, "bold"), fg="#1565c0", bg="white", bd=2, relief="groove", padx=12, pady=4)
        col_relays.pack(side="top", anchor="center", pady=(3, 2))

        top_info = tk.Frame(col_relays, bg="white")
        top_info.pack(fill="x", pady=(0, 4))
        tk.Label(top_info, text=" STATUS OVERVIEW & TOUCH OVERRIDE", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white").pack(side="left")

        def do_all_off():
            self.var_auto_dosing.set(False)
            self._update_auto_dosing_ui()
            dosing_engine.stop_manual_dosing()
            cyclic_engine.stop_all_timers()
            hw.emergency_all_off()
            for ch_idx, badge_btn in self.mon_valve_badges.items():
                badge_btn.config(text="OFF", bg=self.COLOR_OFF, relief="raised")

        tk.Button(
            top_info, text="ALL OFF", font=("Helvetica", 11, "bold"),
            bg="#dc2626", fg="white", activebackground="#b91c1c", activeforeground="white",
            bd=2, relief="raised", padx=14, pady=2, cursor="hand2", command=do_all_off
        ).pack(side="right")

        grid_frame = tk.Frame(col_relays, bg="white")
        grid_frame.pack(anchor="center", pady=2)

        for col_i in range(3):
            grid_frame.columnconfigure(col_i, minsize=295, weight=1, uniform="rcol")

        self.mon_valve_badges = {}
        ch_order = [
            (1, 0, 0), (2, 0, 1), (3, 0, 2),
            (4, 1, 0), (5, 1, 1), (6, 1, 2),
            (7, 2, 0)
        ]

        for ch, r_idx, c_idx in ch_order:
            name = ACTUATOR_NAMES.get(ch, f"Relay {ch}")
            card_v = tk.Frame(grid_frame, bg="#f8fafc", bd=1, relief="solid", padx=8, pady=4)
            card_v.grid(row=r_idx, column=c_idx, padx=4, pady=3, sticky="ew")

            tk.Label(card_v, text=name, font=("Helvetica", 10, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc").pack(side="left")

            def make_toggle(target_ch=ch):
                def do_toggle():
                    cur = hw.get_relay(target_ch)
                    hw.set_relay(target_ch, not cur)
                return do_toggle

            badge_btn = tk.Button(
                card_v, text="OFF", font=("Helvetica", 10, "bold"),
                fg="white", bg=self.COLOR_OFF, bd=1, relief="raised",
                padx=14, pady=2, cursor="hand2", command=make_toggle(ch)
            )
            badge_btn.pack(side="right")
            self.mon_valve_badges[ch] = badge_btn

        return f

    # ==========================================================================
    # SCREEN 3: FERTIGATION (CROP SELECTION + 3 DOSING RELAYS + DOSING MOTOR)
    # ==========================================================================
    def _create_fertigation_screen(self, parent):
        f = tk.Frame(parent, bg="white")

        top_bar = tk.Frame(f, bg="#f8fafc", bd=1, relief="groove", padx=8, pady=3)
        top_bar.pack(fill="x", pady=(0, 2))

        tk.Label(top_bar, text="Select Crop :", font=("Helvetica", 12, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc").pack(side="left", padx=(4, 2))

        recipe_names = list(crop_recipes.keys())

        def on_fert_crop_selected():
            c = self.var_recipe.get()
            system_config["active_crop"] = c
            save_json(CONFIG_FILE, system_config)
            save_json(CONFIG_FALLBACK_FILE, system_config)
            self._load_recipe_into_fert_screen()
            if hasattr(self, "dd_set_crop"):
                self.dd_set_crop.update_label()
            if hasattr(self, "_load_crop_into_settings_tab"):
                self._load_crop_into_settings_tab()
            elif hasattr(self, "_load_crop_into_settings"):
                self._load_crop_into_settings()

        self.dd_fert_crop = GridTouchDropdown(
            parent=top_bar,
            root=self,
            var=self.var_recipe,
            values=recipe_names,
            display_map={k: crop_recipes[k].get("crop_name", k.title()) for k in crop_recipes},
            on_select=on_fert_crop_selected,
            cols=3
        )
        self.dd_fert_crop.btn.config(font=("Helvetica", 12, "bold"), padx=12, pady=4)
        self.dd_fert_crop.btn.pack(side="left", padx=4)

        def toggle_auto_fert():
            new_st = not self.var_auto_dosing.get()
            self.var_auto_dosing.set(new_st)
            dosing_engine.stop_manual_dosing()
            self._update_auto_dosing_ui()

        toggle_auto_dosing = toggle_auto_fert

        def _update_auto_dosing_ui():
            if self.var_auto_dosing.get():
                self.btn_auto_dosing.config(
                    text="AUTO FERTIGATION ",
                    bg="#15803d", fg="white",
                    activebackground="#166534", activeforeground="white",
                    relief="sunken"
                )
                if hasattr(self, "btn_start_fert") and self.btn_start_fert.winfo_exists():
                    self.btn_start_fert.pack_forget()
            else:
                self.btn_auto_dosing.config(
                    text="MANUAL FERTIGATION ",
                    bg="#fee2e2", fg="#991b1b",
                    activebackground="#fecaca", activeforeground="#7f1d1d",
                    relief="raised"
                )
                if hasattr(self, "btn_start_fert") and self.btn_start_fert.winfo_exists():
                    if hasattr(self, "btn_abort_fert") and self.btn_abort_fert.winfo_exists() and self.btn_abort_fert.winfo_ismapped():
                        self.btn_start_fert.pack(side="left", expand=True, fill="x", padx=2, before=self.btn_abort_fert)
                    else:
                        self.btn_start_fert.pack(side="left", expand=True, fill="x", padx=2)
                    self.btn_start_fert.config(
                        text="▶ START FERTIGATION",
                        state="normal",
                        bg="#1565c0", fg="white",
                        activebackground="#0d47a1", activeforeground="white",
                        cursor="hand2"
                    )
        self._update_auto_dosing_ui = _update_auto_dosing_ui
        self._update_auto_fert_ui = _update_auto_dosing_ui

        self.btn_auto_dosing = tk.Button(
            top_bar, font=("Helvetica", 13, "bold"),
            bd=2, padx=12, pady=4, cursor="hand2", command=toggle_auto_fert
        )
        self.btn_auto_fert = self.btn_auto_dosing
        self.btn_auto_dosing.pack(side="right", padx=4)
        _update_auto_dosing_ui()

        center_wrap = tk.Frame(f, bg="white")
        center_wrap.pack(anchor="center", pady=1)

        # CARD 1: ACTIVE SETPOINTS & DOSING ACTUATOR VALVES
        top_card = tk.LabelFrame(
            center_wrap,
            text=" ACTIVE CROP TARGET SETPOINTS & INJECTOR VALVES ",
            font=("Helvetica", 12, "bold"), fg="#1565c0", bg="white", bd=2, relief="groove",
            padx=5, pady=1
        )
        top_card.pack(fill="x", pady=1)

        sp_frame = tk.LabelFrame(
            top_card,
            text=" NUTRIENTS & pH CONTROL SETPOINTS ",
            font=("Helvetica", 10, "bold"), fg="#1e293b", bg="#f8fafc", bd=1, relief="solid",
            padx=3, pady=1
        )
        sp_frame.pack(fill="x", pady=(0, 1))

        def make_sp_disp(parent_row, label_text, default_v, val_fg="#1565c0", wraplen=None):
            cell = tk.Frame(parent_row, bg="white", bd=1, relief="solid", padx=4, pady=2)
            cell.pack(side="left", expand=True, fill="both", padx=2)
            tk.Label(cell, text=label_text, font=("Helvetica", 11, "bold"), fg="#475569", bg="white").pack(anchor="w")
            lbl_val = tk.Label(cell, text=str(default_v), font=("Helvetica", 13, "bold"), fg=val_fg, bg="white", justify="center", wraplength=wraplen)
            lbl_val.pack(anchor="center")
            return lbl_val

        row1 = tk.Frame(sp_frame, bg="#f8fafc")
        row1.pack(fill="x", pady=0)
        self.lbl_fert_crop_name = make_sp_disp(row1, "Active Crop:", "Cucumber", val_fg=self.COLOR_TEXT_MAIN, wraplen=210)
        self.lbl_fert_ec_min = make_sp_disp(row1, "EC Min (Dose Start):", "1.80 mS/cm", val_fg="#1565c0")
        self.lbl_fert_ec_max = make_sp_disp(row1, "EC Max (Dose Stop):", "2.20 mS/cm", val_fg="#1565c0")
        self.lbl_fert_ph_low = make_sp_disp(row1, "pH Low (Acid Stop):", "5.40", val_fg="#0891b2")
        self.lbl_fert_ph_high = make_sp_disp(row1, "pH High (Acid Start):", "6.40", val_fg="#dc2626")

        def on_fert_crop_name_click():
            def on_confirmed(new_val):
                new_val = str(new_val).strip()
                if not new_val: return
                k = self.var_recipe.get()
                if k in crop_recipes:
                    crop_recipes[k]["crop_name"] = new_val
                    save_json(RECIPE_FILE, crop_recipes)
                    new_disp = {rk: crop_recipes[rk].get("crop_name", rk.title()) for rk in crop_recipes}
                    if hasattr(self, "dd_fert_crop"):
                        self.dd_fert_crop.display_map = dict(new_disp)
                        self.dd_fert_crop.update_label()
                    if hasattr(self, "dd_set_crop"):
                        self.dd_set_crop.display_map = dict(new_disp)
                        self.dd_set_crop.update_label()
                    self._load_recipe_into_fert_screen()
                    if hasattr(self, "_load_crop_into_settings_tab"):
                        self._load_crop_into_settings_tab()
            open_almora_keypad("Edit Crop Name", self.lbl_fert_crop_name.cget("text"), on_confirmed, is_alphanumeric=True, root_window=self)

        self.lbl_fert_crop_name.config(cursor="hand2")
        self.lbl_fert_crop_name.bind("<Button-1>", lambda e: on_fert_crop_name_click())

        # 3 DOSING VALVES + DOSING MOTOR (CH 1 - CH 4)
        v_frame = tk.LabelFrame(
            top_card,
            text="DOSING STATUS",
            font=("Helvetica", 10, "bold"), fg="#1565c0", bg="white", bd=1, relief="solid",
            padx=3, pady=1
        )
        v_frame.pack(fill="x", pady=(1, 0))

        v_grid = tk.Frame(v_frame, bg="white")
        v_grid.pack(fill="x")
        v_grid.columnconfigure(0, weight=4, uniform="vcol")
        v_grid.columnconfigure(1, weight=3, uniform="vcol")
        v_grid.columnconfigure(2, weight=3, uniform="vcol")
        v_grid.columnconfigure(3, weight=2, uniform="vcol")

        vh_bg = "#e2e8f0"
        tk.Label(v_grid, text="Dosing Channel", font=("Helvetica", 11, "bold"), fg="#0f172a", bg=vh_bg, anchor="center").grid(row=0, column=0, sticky="ew", padx=1, pady=0)
        tk.Label(v_grid, text="Dosing Trigger", font=("Helvetica", 11, "bold"), fg="#0f172a", bg=vh_bg, anchor="center").grid(row=0, column=1, sticky="ew", padx=1, pady=0)
        tk.Label(v_grid, text="Target Cutoff", font=("Helvetica", 11, "bold"), fg="#0f172a", bg=vh_bg, anchor="center").grid(row=0, column=2, sticky="ew", padx=1, pady=0)
        tk.Label(v_grid, text=" Status", font=("Helvetica", 11, "bold"), fg="#0f172a", bg=vh_bg, anchor="center").grid(row=0, column=3, sticky="ew", padx=1, pady=0)

        self.labels_fert_v_status = {}

        # 1. EC 1
        tk.Label(v_grid, text="EC 1 ", font=("Helvetica", 13, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc", anchor="center", bd=1, relief="solid").grid(row=1, column=0, sticky="ew", padx=1, pady=0)
        self.lbl_v1_trig = tk.Label(v_grid, text="EC <= 1.80", font=("Helvetica", 13, "bold"), fg="#1e293b", bg="#f8fafc", anchor="center", bd=1, relief="solid")
        self.lbl_v1_trig.grid(row=1, column=1, sticky="ew", padx=1, pady=0)
        self.lbl_v1_cut = tk.Label(v_grid, text="EC >= 2.20 ", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="#e0f2fe", anchor="center", bd=1, relief="solid")
        self.lbl_v1_cut.grid(row=1, column=2, sticky="ew", padx=1, pady=0)
        lbl_v1_st = tk.Label(v_grid, text="OFF", font=("Helvetica", 13, "bold"), fg="white", bg=self.COLOR_OFF, anchor="center", relief="raised", bd=1)
        lbl_v1_st.grid(row=1, column=3, sticky="ew", padx=1, pady=0)
        self.labels_fert_v_status[ActuatorMap.EC_VALVE_1] = lbl_v1_st

        # 2. EC 2
        tk.Label(v_grid, text="EC 2 ", font=("Helvetica", 13, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc", anchor="center", bd=1, relief="solid").grid(row=2, column=0, sticky="ew", padx=1, pady=0)
        self.lbl_v2_trig = tk.Label(v_grid, text="EC <= 1.80", font=("Helvetica", 13, "bold"), fg="#1e293b", bg="#f8fafc", anchor="center", bd=1, relief="solid")
        self.lbl_v2_trig.grid(row=2, column=1, sticky="ew", padx=1, pady=0)
        self.lbl_v2_cut = tk.Label(v_grid, text="EC >= 2.20 ", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="#e0f2fe", anchor="center", bd=1, relief="solid")
        self.lbl_v2_cut.grid(row=2, column=2, sticky="ew", padx=1, pady=0)
        lbl_v2_st = tk.Label(v_grid, text="OFF", font=("Helvetica", 13, "bold"), fg="white", bg=self.COLOR_OFF, anchor="center", relief="raised", bd=1)
        lbl_v2_st.grid(row=2, column=3, sticky="ew", padx=1, pady=0)
        self.labels_fert_v_status[ActuatorMap.EC_VALVE_2] = lbl_v2_st

        # 3. pH Down
        tk.Label(v_grid, text="pH ", font=("Helvetica", 13, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc", anchor="center", bd=1, relief="solid").grid(row=3, column=0, sticky="ew", padx=1, pady=0)
        self.lbl_v3_trig = tk.Label(v_grid, text="pH >= 6.40", font=("Helvetica", 13, "bold"), fg="#1e293b", bg="#f8fafc", anchor="center", bd=1, relief="solid")
        self.lbl_v3_trig.grid(row=3, column=1, sticky="ew", padx=1, pady=0)
        self.lbl_v3_cut = tk.Label(v_grid, text="pH <= 5.40 ", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="#e0f2fe", anchor="center", bd=1, relief="solid")
        self.lbl_v3_cut.grid(row=3, column=2, sticky="ew", padx=1, pady=0)
        lbl_v3_st = tk.Label(v_grid, text="OFF", font=("Helvetica", 13, "bold"), fg="white", bg=self.COLOR_OFF, anchor="center", relief="raised", bd=1)
        lbl_v3_st.grid(row=3, column=3, sticky="ew", padx=1, pady=0)
        self.labels_fert_v_status[ActuatorMap.PH_VALVE] = lbl_v3_st

        # 4. DOSING MOTOR (CH 4) - CYCLIC TIMER CONTROLLED
        tk.Label(v_grid, text="Fertigation Motor ", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="#f8fafc", anchor="center", bd=1, relief="solid").grid(row=4, column=0, sticky="ew", padx=1, pady=0)
        self.lbl_motor_trig = tk.Label(v_grid, text="Timer Schedule", font=("Helvetica", 13, "bold"), fg="#1e293b", bg="#f8fafc", anchor="center", bd=1, relief="solid")
        self.lbl_motor_trig.grid(row=4, column=1, sticky="ew", padx=1, pady=0)
        self.lbl_motor_cut = tk.Label(v_grid, text="Interval Pause", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="#e0f2fe", anchor="center", bd=1, relief="solid")
        self.lbl_motor_cut.grid(row=4, column=2, sticky="ew", padx=1, pady=0)
        lbl_motor_st = tk.Label(v_grid, text="OFF", font=("Helvetica", 13, "bold"), fg="white", bg=self.COLOR_OFF, anchor="center", relief="raised", bd=1)
        lbl_motor_st.grid(row=4, column=3, sticky="ew", padx=1, pady=0)
        self.labels_fert_v_status[ActuatorMap.DOSING_MOTOR] = lbl_motor_st

        # CARD 2: AUTOMATION SEQUENCE & PROCESS MONITOR
        bottom_card = tk.LabelFrame(
            center_wrap,
            text=" AUTOMATION SEQUENCE & PROCESS MONITOR ",
            font=("Helvetica", 12, "bold"), fg="#1565c0", bg="white", bd=2, relief="groove",
            padx=5, pady=1
        )
        bottom_card.pack(fill="x", pady=1)

        b_body = tk.Frame(bottom_card, bg="white")
        b_body.pack(fill="x")
        b_body.columnconfigure(0, weight=5, uniform="bcol")
        b_body.columnconfigure(1, weight=6, uniform="bcol")

        frame_live = tk.LabelFrame(
            b_body,
            text=" LIVE TANK SENSORS ",
            font=("Helvetica", 10, "bold"), fg="#1e293b", bg="#f8fafc", bd=1, relief="solid",
            padx=3, pady=1
        )
        frame_live.grid(row=0, column=0, sticky="nsew", padx=(0, 3), pady=1)

        live_row = tk.Frame(frame_live, bg="#f8fafc")
        live_row.pack(fill="both", expand=True, pady=1)

        c_ec = tk.Frame(live_row, bg="white", bd=1, relief="solid", padx=3, pady=1)
        c_ec.pack(side="left", expand=True, fill="both", padx=1)
        tk.Label(c_ec, text="LIVE EC", font=("Helvetica", 12, "bold"), fg="#475569", bg="white").pack()
        self.lbl_fert_live_ec = tk.Label(c_ec, text="--", font=("Helvetica", 20, "bold"), fg="#1565c0", bg="white")
        self.lbl_fert_live_ec.pack()

        c_ph = tk.Frame(live_row, bg="white", bd=1, relief="solid", padx=3, pady=1)
        c_ph.pack(side="left", expand=True, fill="both", padx=1)
        tk.Label(c_ph, text="LIVE pH", font=("Helvetica", 12, "bold"), fg="#475569", bg="white").pack()
        self.lbl_fert_live_ph = tk.Label(c_ph, text="--", font=("Helvetica", 20, "bold"), fg="#0891b2", bg="white")
        self.lbl_fert_live_ph.pack()

        c_tp = tk.Frame(live_row, bg="white", bd=1, relief="solid", padx=3, pady=1)
        c_tp.pack(side="left", expand=True, fill="both", padx=1)
        tk.Label(c_tp, text="WATER TEMP", font=("Helvetica", 12, "bold"), fg="#475569", bg="white").pack()
        self.lbl_fert_live_temp = tk.Label(c_tp, text="--", font=("Helvetica", 20, "bold"), fg="#0f172a", bg="white")
        self.lbl_fert_live_temp.pack()

        r_panel = tk.Frame(b_body, bg="white")
        r_panel.grid(row=0, column=1, sticky="nsew", padx=(3, 0), pady=1)

        st_box = tk.Frame(r_panel, bg="#0f172a", bd=1, relief="solid", padx=5, pady=2)
        st_box.pack(fill="x", pady=(0, 1))

        self.lbl_fert_phase_badge = tk.Label(
            st_box, text="PHASE: IDLE / READY", font=("Helvetica", 15, "bold"),
            fg="#38bdf8", bg="#0f172a", anchor="w"
        )
        self.lbl_fert_phase_badge.pack(fill="x")

        self.lbl_fert_log = tk.Label(
            st_box, text="System Ready",
            font=("Helvetica", 13, "bold"), fg="#e2e8f0", bg="#0f172a", anchor="w", wraplength=480, justify="left"
        )
        self.lbl_fert_log.pack(fill="x", pady=0)

        self.lbl_fert_countdown = tk.Label(
            st_box, text="Status: Ready", font=("Helvetica", 15, "bold"),
            fg="#fbbf24", bg="#0f172a", anchor="w"
        )
        self.lbl_fert_countdown.pack(fill="x")

        btn_action_box = tk.Frame(r_panel, bg="white")
        btn_action_box.pack(fill="x", pady=(1, 0))

        def on_start_click():
            if self.var_auto_dosing.get():
                return  # Strict restriction: START FERTIGATION works in MANUAL FERTIGATION only!
            dosing_engine.start_manual_dosing()

        def on_reset_click():
            dosing_engine.stop_manual_dosing()

        self._on_start_batch = on_start_click
        self._on_reset_batch = on_reset_click

        self.btn_start_fert = tk.Button(
            btn_action_box, text="▶ START FERTIGATION", font=("Helvetica", 15, "bold"), bg="#1565c0", fg="white",
            activebackground="#0d47a1", activeforeground="white", bd=2, relief="raised", padx=8, pady=3, cursor="hand2", command=on_start_click
        )
        self.btn_start_dosing = self.btn_start_fert

        self.btn_abort_fert = tk.Button(
            btn_action_box, text="⏹ STOP / ABORT", font=("Helvetica", 15, "bold"), bg="#dc2626", fg="white",
            activebackground="#b91c1c", activeforeground="white", bd=2, relief="raised", padx=8, pady=3, cursor="hand2", command=on_reset_click
        )
        self.btn_abort_fert.pack(side="left", expand=True, fill="x", padx=2)

        _update_auto_dosing_ui()

        return f

    def _load_recipe_into_fert_screen(self):
        c_key = self.var_recipe.get()
        rec = get_crop_setpoints(c_key)
        ec_min = float(rec.get("ec_min", 1.80))
        ec_max = float(rec.get("ec_max", 2.20))
        ph_low = float(rec.get("ph_min", 5.40))
        ph_high = float(rec.get("ph_max", 6.40))

        if hasattr(self, "lbl_fert_crop_name"):
            self.lbl_fert_crop_name.config(text=rec.get("crop_name", c_key.title()))
            self.lbl_fert_ec_min.config(text=f"{ec_min:.2f} mS/cm")
            self.lbl_fert_ec_max.config(text=f"{ec_max:.2f} mS/cm")
            self.lbl_fert_ph_low.config(text=f"{ph_low:.2f}")
            self.lbl_fert_ph_high.config(text=f"{ph_high:.2f}")

            self.lbl_v1_trig.config(text=f"EC <= {ec_min:.2f}")
            self.lbl_v1_cut.config(text=f"EC >= {ec_max:.2f} (or 180s)")
            self.lbl_v2_trig.config(text=f"EC <= {ec_min:.2f}")
            self.lbl_v2_cut.config(text=f"EC >= {ec_max:.2f} (or 180s)")
            self.lbl_v3_trig.config(text=f"pH >= {ph_high:.2f}")
            self.lbl_v3_cut.config(text=f"pH <= {ph_low:.2f} (or 180s)")

        if hasattr(self, "lbl_mon_ec_target"):
            self.lbl_mon_ec_target.config(text=f"Target: {ec_min:.2f} - {ec_max:.2f} mS/cm")
        if hasattr(self, "lbl_mon_ph_target"):
            self.lbl_mon_ph_target.config(text=f"Target: {ph_low:.2f} - {ph_high:.2f}")

    def _create_irrigation_screen(self, parent):
        f = tk.Frame(parent, bg="white")

        top_info = tk.Frame(f, bg="#f8fafc", bd=1, relief="groove", padx=10, pady=4)
        top_info.pack(fill="x", pady=(0, 2))
        tk.Label(
            top_info, text="AUTOMATED CYCLIC TIMERS (FERTIGATION MOTOR, IRRIGATION & TANK FILLING)",
            font=("Helvetica", 12, "bold"), fg="#1565c0", bg="#f8fafc"
        ).pack(side="left")

        body = tk.Frame(f, bg="white")
        body.pack(fill="both", expand=True, padx=10, pady=2)

        center_wrap = tk.Frame(body, bg="white")
        center_wrap.pack(anchor="center", pady=1)

        card = tk.LabelFrame(
            center_wrap,
            text=" CYCLIC TIMERS CONFIGURATION ",
            font=("Helvetica", 12, "bold"), fg="#1565c0", bg="white", bd=2, relief="groove",
            padx=10, pady=2
        )
        card.pack(anchor="center", pady=1)

        t_grid = tk.Frame(card, bg="white")
        t_grid.pack(anchor="center", pady=1)
        t_grid.columnconfigure(0, minsize=190)
        t_grid.columnconfigure(1, minsize=265)
        t_grid.columnconfigure(2, minsize=265)
        t_grid.columnconfigure(3, minsize=265)

        vh_bg = "#e2e8f0"
        tk.Label(t_grid, text="Setting Parameter", font=("Helvetica", 11, "bold"), fg="#1e293b", bg=vh_bg, anchor="w", padx=6, pady=3).grid(row=0, column=0, sticky="ew", padx=2, pady=1)
        tk.Label(t_grid, text="TIMER 1: MIX MOTOR ", font=("Helvetica", 11, "bold"), fg="#1565c0", bg=vh_bg, anchor="center", pady=3).grid(row=0, column=1, sticky="ew", padx=2, pady=1)
        tk.Label(t_grid, text="TIMER 2: IRRIGATION ", font=("Helvetica", 11, "bold"), fg="#0891b2", bg=vh_bg, anchor="center", pady=3).grid(row=0, column=2, sticky="ew", padx=2, pady=1)
        tk.Label(t_grid, text="TIMER 3: TANK FILLING ", font=("Helvetica", 11, "bold"), fg="#0d9488", bg=vh_bg, anchor="center", pady=3).grid(row=0, column=3, sticky="ew", padx=2, pady=1)

        self.timer_ui = {"dosing_motor": {}, "irrigation": {}, "tank_filling": {}}
        timer_keys = ["dosing_motor", "irrigation", "tank_filling"]

        # ROW 1: Timer Line Name
        tk.Label(t_grid, text="Timer Name:", font=("Helvetica", 11, "bold"), fg="#334155", bg="#f8fafc", anchor="w", padx=8, pady=3).grid(row=1, column=0, sticky="ew", padx=2, pady=1)
        for c_idx, k in enumerate(timer_keys, start=1):
            f_n = tk.Frame(t_grid, bg="#f8fafc", bd=1, relief="solid")
            f_n.grid(row=1, column=c_idx, sticky="ew", padx=2, pady=1)
            f_in = tk.Frame(f_n, bg="#f8fafc")
            f_in.pack(anchor="center", pady=2)
            default_nm = "Mix Motor " if k == "dosing_motor" else ("Irrigation (Bypass)" if k == "irrigation" else "Tank Filling")
            name_val = str(cyclic_timer_cfg.get(k, {}).get("name", default_nm))
            lbl_n = tk.Label(f_in, text=name_val, font=("Helvetica", 12, "bold"), fg="#0f172a", bg="white", relief="groove", bd=2, width=13, anchor="center", padx=6, pady=3, cursor="hand2")
            lbl_n.pack(side="left", padx=3)

            def make_edit_name(tk_k=k, lbl=lbl_n):
                def do_edit():
                    def on_confirm(v):
                        lbl.config(text=v)
                        cyclic_timer_cfg[tk_k]["name"] = v
                        save_json(TIMERS_FILE, cyclic_timer_cfg)
                    open_almora_keypad(f"Edit {tk_k.replace('_',' ').title()} Name", lbl.cget("text"), on_confirm, is_alphanumeric=True, root_window=self)
                return do_edit

            lbl_n.bind("<Button-1>", lambda e, tk_k=k, lbl=lbl_n: make_edit_name(tk_k, lbl)())
            tk.Button(f_in, text="EDIT", font=("Helvetica", 11, "bold"), bg="#0284c7", fg="white", activebackground="#0369a1", activeforeground="white", bd=2, relief="raised", padx=16, pady=3, cursor="hand2", command=make_edit_name(k, lbl_n)).pack(side="left", padx=3)
            self.timer_ui[k]["lbl_name"] = lbl_n

        # ROW 2: Timer Automation Enable/Disable
        tk.Label(t_grid, text="Timer Automation:", font=("Helvetica", 11, "bold"), fg="#334155", bg="white", anchor="w", padx=8, pady=3).grid(row=2, column=0, sticky="ew", padx=2, pady=1)
        for c_idx, k in enumerate(timer_keys, start=1):
            f_en = tk.Frame(t_grid, bg="white", bd=1, relief="solid")
            f_en.grid(row=2, column=c_idx, sticky="ew", padx=2, pady=1)
            btn_en = tk.Button(f_en, font=("Helvetica", 11, "bold"), bd=2, padx=16, pady=3, cursor="hand2")
            btn_en.pack(anchor="center", pady=2)

            def make_toggle(tk_k=k, btn=btn_en):
                def do_toggle():
                    cur = cyclic_timer_cfg.get(tk_k, {}).get("enabled", True)
                    cyclic_timer_cfg[tk_k]["enabled"] = not cur
                    save_json(TIMERS_FILE, cyclic_timer_cfg)
                    self._update_timer_en_btn(tk_k)
                return do_toggle

            btn_en.config(command=make_toggle(k, btn_en))
            self.timer_ui[k]["btn_en"] = btn_en
            self._update_timer_en_btn(k)

        # Helper for parameter rows (Window Start, Window Stop, ON Duration, OFF Interval)
        def make_param_row(r_idx, label_text, param_key, default_val, kmode="numeric", bg_clr="white"):
            tk.Label(t_grid, text=label_text, font=("Helvetica", 11, "bold"), fg="#334155", bg=bg_clr, anchor="w", padx=8, pady=3).grid(row=r_idx, column=0, sticky="ew", padx=2, pady=1)
            for c_idx, k in enumerate(timer_keys, start=1):
                f_c = tk.Frame(t_grid, bg=bg_clr, bd=1, relief="solid")
                f_c.grid(row=r_idx, column=c_idx, sticky="ew", padx=2, pady=1)
                f_in = tk.Frame(f_c, bg=bg_clr)
                f_in.pack(anchor="center", pady=2)

                val_p = str(cyclic_timer_cfg.get(k, {}).get(param_key, default_val))
                lbl_val = tk.Label(f_in, text=val_p, font=("Helvetica", 12, "bold"), fg="#1565c0", bg="white", relief="groove", bd=2, width=10, anchor="center", padx=4, pady=3, cursor="hand2")
                lbl_val.pack(side="left", padx=3)

                def make_edit_p(tk_k=k, pk=param_key, lbl=lbl_val, km=kmode, title=label_text):
                    def do_edit():
                        def on_confirm(v):
                            lbl.config(text=v)
                            try:
                                cyclic_timer_cfg[tk_k][pk] = float(v) if km == "numeric" else v
                            except Exception:
                                cyclic_timer_cfg[tk_k][pk] = v
                            save_json(TIMERS_FILE, cyclic_timer_cfg)
                        open_almora_keypad(f"{tk_k.replace('_',' ').title()}: {title}", lbl.cget("text"), on_confirm, mode=km, root_window=self)
                    return do_edit

                lbl_val.bind("<Button-1>", lambda e, tk_k=k, pk=param_key, lbl=lbl_val, km=kmode, title=label_text: make_edit_p(tk_k, pk, lbl, km, title)())
                tk.Button(f_in, text="EDIT", font=("Helvetica", 11, "bold"), bg="#0284c7", fg="white", activebackground="#0369a1", activeforeground="white", bd=2, relief="raised", padx=16, pady=3, cursor="hand2", command=make_edit_p(k, param_key, lbl_val, kmode, label_text)).pack(side="left", padx=3)
                self.timer_ui[k][f"lbl_{param_key}"] = lbl_val

        make_param_row(3, "Window Start Time:", "start_time", "06:00", kmode="time", bg_clr="#f8fafc")
        make_param_row(4, "Window Stop Time:", "stop_time", "18:00", kmode="time", bg_clr="white")
        make_param_row(5, "Cycle Run Interval:", "on_min", 5.0, kmode="numeric", bg_clr="#f8fafc")
        make_param_row(6, "Cycle Pause Interval:", "off_min", 15.0, kmode="numeric", bg_clr="white")

        # ROW 7: LIVE STATUS & COUNTDOWN
        tk.Label(t_grid, text="Live Operation Status:", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="#f1f5f9", anchor="w", padx=8, pady=3).grid(row=7, column=0, sticky="ew", padx=2, pady=1)

        # 7a: Dosing Motor Live Display
        f_st_dm = tk.Frame(t_grid, bg="#f1f5f9", bd=1, relief="solid")
        f_st_dm.grid(row=7, column=1, sticky="ew", padx=2, pady=1)
        f_in_dm = tk.Frame(f_st_dm, bg="#f1f5f9")
        f_in_dm.pack(anchor="center", pady=2)
        lbl_st_dm = tk.Label(f_in_dm, text="OFF", font=("Helvetica", 11, "bold"), fg="white", bg=self.COLOR_OFF, padx=12, pady=3, relief="raised", bd=2)
        lbl_st_dm.pack(side="left", padx=3)
        lbl_rem_dm = tk.Label(f_in_dm, text="Rem: 00:00", font=("Helvetica", 12, "bold"), fg="#1565c0", bg="#e0f2fe", padx=10, pady=3, relief="groove", bd=2)
        lbl_rem_dm.pack(side="left", padx=3)
        self.timer_ui["dosing_motor"]["lbl_st"] = lbl_st_dm
        self.timer_ui["dosing_motor"]["lbl_rem"] = lbl_rem_dm

        # 7b: Irrigation Live Display (Ch 5 + Auto Ch 7)
        f_st_ir = tk.Frame(t_grid, bg="#f1f5f9", bd=1, relief="solid")
        f_st_ir.grid(row=7, column=2, sticky="ew", padx=2, pady=1)
        f_in_ir = tk.Frame(f_st_ir, bg="#f1f5f9")
        f_in_ir.pack(anchor="center", pady=2)
        lbl_st_ir = tk.Label(f_in_ir, text="OFF", font=("Helvetica", 11, "bold"), fg="white", bg=self.COLOR_OFF, padx=12, pady=3, relief="raised", bd=2)
        lbl_st_ir.pack(side="left", padx=3)
        lbl_rem_ir = tk.Label(f_in_ir, text="Rem: 00:00", font=("Helvetica", 12, "bold"), fg="#0891b2", bg="#e0f2fe", padx=10, pady=3, relief="groove", bd=2)
        lbl_rem_ir.pack(side="left", padx=3)
        self.timer_ui["irrigation"]["lbl_st"] = lbl_st_ir
        self.timer_ui["irrigation"]["lbl_rem"] = lbl_rem_ir

        # 7c: Tank Filling Live Display (Ch 6 + Auto Ch 7)
        f_st_tf = tk.Frame(t_grid, bg="#f1f5f9", bd=1, relief="solid")
        f_st_tf.grid(row=7, column=3, sticky="ew", padx=2, pady=1)
        f_in_tf = tk.Frame(f_st_tf, bg="#f1f5f9")
        f_in_tf.pack(anchor="center", pady=2)
        lbl_st_tf = tk.Label(f_in_tf, text="OFF", font=("Helvetica", 11, "bold"), fg="white", bg=self.COLOR_OFF, padx=12, pady=3, relief="raised", bd=2)
        lbl_st_tf.pack(side="left", padx=3)
        lbl_rem_tf = tk.Label(f_in_tf, text="Rem: 00:00", font=("Helvetica", 12, "bold"), fg="#0d9488", bg="#e0f2fe", padx=10, pady=3, relief="groove", bd=2)
        lbl_rem_tf.pack(side="left", padx=3)
        self.timer_ui["tank_filling"]["lbl_st"] = lbl_st_tf
        self.timer_ui["tank_filling"]["lbl_rem"] = lbl_rem_tf

        # ROW 8: MANUAL RUN / OVERRIDE BUTTONS
        tk.Label(t_grid, text="Manual Control:", font=("Helvetica", 11, "bold"), fg="#334155", bg="white", anchor="w", padx=8, pady=3).grid(row=8, column=0, sticky="ew", padx=2, pady=1)

        # 8a: Dosing Motor manual button
        f_btn_dm = tk.Frame(t_grid, bg="white", bd=1, relief="solid")
        f_btn_dm.grid(row=8, column=1, sticky="ew", padx=2, pady=1)
        btn_run_dm = tk.Button(f_btn_dm, font=("Helvetica", 11, "bold"), bd=2, relief="raised", padx=16, pady=4, cursor="hand2")
        btn_run_dm.pack(anchor="center", pady=2)

        def do_run_dm():
            ts = cyclic_engine.timer_states.get("dosing_motor", {})
            if ts.get("state") == "ON":
                cyclic_engine.stop_timer("dosing_motor")
            else:
                cyclic_engine.start_timer("dosing_motor")

        btn_run_dm.config(command=do_run_dm)
        self.timer_ui["dosing_motor"]["btn_run"] = btn_run_dm

        # 8b: Irrigation manual run button (Ch 5 ON & Ch 7 Auto ON; Ch 6 locked OFF)
        f_btn_ir = tk.Frame(t_grid, bg="white", bd=1, relief="solid")
        f_btn_ir.grid(row=8, column=2, sticky="ew", padx=2, pady=1)
        btn_run_ir = tk.Button(f_btn_ir, font=("Helvetica", 11, "bold"), bd=2, relief="raised", padx=16, pady=4, cursor="hand2")
        btn_run_ir.pack(anchor="center", pady=2)

        def do_run_ir():
            ts = cyclic_engine.timer_states.get("irrigation", {})
            if ts.get("state") == "ON":
                cyclic_engine.stop_timer("irrigation")
            else:
                cyclic_engine.start_timer("irrigation")

        btn_run_ir.config(command=do_run_ir)
        self.timer_ui["irrigation"]["btn_run"] = btn_run_ir

        # 8c: Tank Filling manual run button (Ch 6 ON & Ch 7 Auto ON; Ch 5 locked OFF)
        f_btn_tf = tk.Frame(t_grid, bg="white", bd=1, relief="solid")
        f_btn_tf.grid(row=8, column=3, sticky="ew", padx=2, pady=1)
        btn_run_tf = tk.Button(f_btn_tf, font=("Helvetica", 11, "bold"), bd=2, relief="raised", padx=16, pady=4, cursor="hand2")
        btn_run_tf.pack(anchor="center", pady=2)

        def do_run_tf():
            ts = cyclic_engine.timer_states.get("tank_filling", {})
            if ts.get("state") == "ON":
                cyclic_engine.stop_timer("tank_filling")
            else:
                cyclic_engine.start_timer("tank_filling")

        btn_run_tf.config(command=do_run_tf)
        self.timer_ui["tank_filling"]["btn_run"] = btn_run_tf

        # Master Controls Bar (Aligned directly under the grid box)
        m_bar = tk.Frame(center_wrap, bg="white")
        m_bar.pack(fill="x", pady=(6, 2))
        tk.Button(
            m_bar, text="💾 SAVE ALL TIMER SETTINGS", font=("Helvetica", 12, "bold"),
            bg="#2e7d32", fg="white", activebackground="#15803d", activeforeground="white",
            bd=2, relief="raised", padx=18, pady=5, cursor="hand2",
            command=lambda: save_json(TIMERS_FILE, cyclic_timer_cfg)
        ).pack(side="left", expand=True, fill="x", padx=4)

        tk.Button(
            m_bar, text="⏹ STOP ALL CYCLIC TIMERS", font=("Helvetica", 12, "bold"),
            bg="#dc2626", fg="white", activebackground="#b91c1c", activeforeground="white",
            bd=2, relief="raised", padx=18, pady=5, cursor="hand2",
            command=cyclic_engine.stop_all_timers
        ).pack(side="right", expand=True, fill="x", padx=4)

        return f

    def _update_timer_en_btn(self, k):
        is_en = cyclic_timer_cfg.get(k, {}).get("enabled", True)
        btn = self.timer_ui.get(k, {}).get("btn_en")
        if btn:
            if is_en:
                btn.config(text="ENABLED ", bg="#15803d", fg="white", activebackground="#166534", activeforeground="white", relief="sunken")
            else:
                btn.config(text="DISABLED", bg="#fee2e2", fg="#991b1b", activebackground="#fecaca", activeforeground="#7f1d1d", relief="raised")

    # ==========================================================================
    # SCREEN 5: SETTINGS & SAFETY (EXACT SIZES & STYLING FROM FERTIGATION_HMI)
    # ==========================================================================
    def _create_settings_screen(self, parent):
        f = tk.Frame(parent, bg="white")

        top_bar = tk.Frame(f, bg="#f8fafc", bd=1, relief="groove", padx=8, pady=3)
        top_bar.pack(fill="x", pady=(0, 2))

        tk.Label(top_bar, text="Select Crop to Configure :", font=("Helvetica", 12, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc").pack(side="left", padx=(4, 2))

        recipe_names = list(crop_recipes.keys())

        def on_settings_crop_selected():
            c = self.var_recipe.get()
            system_config["active_crop"] = c
            save_json(CONFIG_FILE, system_config)
            save_json(CONFIG_FALLBACK_FILE, system_config)
            if hasattr(self, "dd_fert_crop"):
                self.dd_fert_crop.update_label()
            self._load_recipe_into_fert_screen()
            self._load_crop_into_settings()

        self.dd_set_crop = GridTouchDropdown(
            parent=top_bar,
            root=self,
            var=self.var_recipe,
            values=recipe_names,
            display_map={k: crop_recipes[k].get("crop_name", k.title()) for k in crop_recipes},
            on_select=on_settings_crop_selected,
            cols=3
        )
        self.dd_set_crop.btn.config(font=("Helvetica", 12, "bold"), padx=12, pady=4)
        self.dd_set_crop.btn.pack(side="left", padx=4)

        center_wrap = tk.Frame(f, bg="white")
        center_wrap.pack(anchor="center", pady=2)

        form_card = tk.LabelFrame(
            center_wrap,
            text="  CROP NUTRIENT & pH DOSING SETPOINTS  ",
            font=("Helvetica", 13, "bold"), fg="#1565c0", bg="white", bd=2, relief="groove",
            padx=8, pady=4
        )
        form_card.pack(fill="x", pady=2)

        sp_outer = tk.Frame(form_card, bg="#f8fafc", bd=1, relief="groove", padx=6, pady=4)
        sp_outer.pack(fill="x", pady=2)
        sp_outer.columnconfigure(0, weight=1, uniform="sp_col")
        sp_outer.columnconfigure(1, weight=1, uniform="sp_col")
        sp_outer.columnconfigure(2, weight=1, uniform="sp_col")

        self.setpoint_boxes = {}

        def make_sp_field(parent_frame, r_idx, c_idx, label_text, sp_key, val_fg="#1565c0", box_w=6, btn_px=14):
            f_cell = tk.Frame(parent_frame, bg="#f8fafc", bd=1, relief="solid", padx=6, pady=6)
            f_cell.grid(row=r_idx, column=c_idx, sticky="nsew", padx=3, pady=3)
            tk.Label(f_cell, text=label_text, font=("Helvetica", 12, "bold"), fg="#0f172a", bg="#f8fafc").pack(side="left", padx=(0, 4))
            l_box = tk.Label(
                f_cell, text="--", font=("Helvetica", 14, "bold"), fg=val_fg,
                bg="white", relief="groove", bd=2, width=box_w, anchor="center", padx=4, pady=4, cursor="hand2"
            )
            l_box.pack(side="left", padx=2)

            def do_edit():
                def on_confirm(v):
                    try:
                        fval = float(v)
                        c_key = self.var_recipe.get()
                        if c_key in crop_recipes:
                            crop_recipes[c_key][sp_key] = fval
                            save_json(RECIPE_FILE, crop_recipes)
                        l_box.config(text=str(fval))
                        self._load_recipe_into_fert_screen()
                    except Exception as err:
                        print(f"Error setting {sp_key}: {err}")
                open_almora_keypad(f"Edit {label_text}", l_box.cget("text"), on_confirm, mode="numeric", root_window=self)

            l_box.bind("<Button-1>", lambda e: do_edit())
            tk.Button(
                f_cell, text="EDIT", font=("Helvetica", 12, "bold"),
                bg="#0284c7", fg="white", activebackground="#0369a1", activeforeground="white",
                bd=2, relief="raised", padx=btn_px, pady=4, cursor="hand2", command=do_edit
            ).pack(side="left", padx=2)
            self.setpoint_boxes[sp_key] = l_box

        # Row 0: Crop Name | EC Min | EC Max
        f_name = tk.Frame(sp_outer, bg="#f8fafc", bd=1, relief="solid", padx=6, pady=6)
        f_name.grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
        tk.Label(f_name, text="Crop Name:", font=("Helvetica", 12, "bold"), fg="#0f172a", bg="#f8fafc").pack(side="left", padx=(0, 4))
        self.lbl_set_crop_name = tk.Label(
            f_name, text="Cucumber", font=("Helvetica", 13, "bold"), fg="#0f172a",
            bg="white", relief="groove", bd=2, padx=6, pady=4, wraplength=180, anchor="center", cursor="hand2"
        )
        self.lbl_set_crop_name.pack(side="left", padx=2, expand=True, fill="x")

        def edit_crop_name():
            def on_crop_name_confirmed(new_val):
                new_val = str(new_val).strip()
                if not new_val: return
                self.lbl_set_crop_name.config(text=new_val)
                k = self.var_recipe.get()
                if k in crop_recipes:
                    crop_recipes[k]["crop_name"] = new_val
                    save_json(RECIPE_FILE, crop_recipes)
                    new_disp = {rk: crop_recipes[rk].get("crop_name", rk.title()) for rk in crop_recipes}
                    if hasattr(self, "dd_fert_crop"):
                        self.dd_fert_crop.display_map = dict(new_disp)
                        self.dd_fert_crop.update_label()
                    if hasattr(self, "dd_set_crop"):
                        self.dd_set_crop.display_map = dict(new_disp)
                        self.dd_set_crop.update_label()
                    self._load_recipe_into_fert_screen()
            open_almora_keypad("Edit Crop Name", self.lbl_set_crop_name.cget("text"), on_crop_name_confirmed, is_alphanumeric=True, root_window=self)

        self.lbl_set_crop_name.bind("<Button-1>", lambda e: edit_crop_name())
        tk.Button(
            f_name, text="EDIT", font=("Helvetica", 12, "bold"),
            bg="#0284c7", fg="white", activebackground="#0369a1", activeforeground="white",
            bd=2, relief="raised", padx=12, pady=4, cursor="hand2", command=edit_crop_name
        ).pack(side="right", padx=2)

        make_sp_field(sp_outer, 0, 1, "EC Min (Start):", "ec_min", val_fg="#1565c0", box_w=5)
        make_sp_field(sp_outer, 0, 2, "EC Max (Stop):", "ec_max", val_fg="#1565c0", box_w=5)

        # Row 1: pH Min (Acid Stop) | pH Max (Acid Start) | Dosing Duration (sec)
        make_sp_field(sp_outer, 1, 0, "pH Min (Acid Stop):", "ph_min", val_fg="#0891b2", box_w=5)
        make_sp_field(sp_outer, 1, 1, "pH Max (Acid Start):", "ph_max", val_fg="#dc2626", box_w=5)
        make_sp_field(sp_outer, 1, 2, "Dose Time (sec):", "dose_sec", val_fg="#1565c0", box_w=5)

        # Row 2: Mixing Pause (sec)
        make_sp_field(sp_outer, 2, 0, "Mixing Pause (sec):", "mix_sec", val_fg="#475569", box_w=5)

        # Save Button Bar (Directly below form_card in exact alignment with grid box)
        f_save = tk.Frame(center_wrap, bg="white")
        f_save.pack(fill="x", pady=(4, 2))

        btn_save = tk.Button(
            f_save, text="💾 SAVE CROP SETPOINTS", font=("Helvetica", 13, "bold"),
            bg="#2e7d32", fg="white", activebackground="#15803d", activeforeground="white",
            bd=2, relief="raised", padx=36, pady=5, cursor="hand2", command=self._save_crop_safety_settings
        )
        btn_save.pack(fill="x", padx=4, pady=2)
        return f

    def _save_crop_safety_settings(self):
        k = self.var_recipe.get()
        if k not in crop_recipes:
            return
        try:
            c_name = self.lbl_set_crop_name.cget("text").strip()
            crop_recipes[k]["crop_name"] = c_name
            for sp_k, box in self.setpoint_boxes.items():
                try:
                    crop_recipes[k][sp_k] = float(box.cget("text"))
                except Exception: pass
            save_json(RECIPE_FILE, crop_recipes)
            system_config["active_crop"] = k
            save_json(CONFIG_FILE, system_config)
            save_json(CONFIG_FALLBACK_FILE, system_config)
            self._load_recipe_into_fert_screen()
            messagebox.showinfo("Saved", f"Crop '{c_name}' setpoints saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed saving crop setpoints: {e}")

    def _load_crop_into_settings_tab(self):
        c_key = self.var_recipe.get()
        rec = get_crop_setpoints(c_key)
        if hasattr(self, "lbl_set_crop_name"):
            self.lbl_set_crop_name.config(text=str(rec.get("crop_name", c_key.title())))
        for sp_k, box in self.setpoint_boxes.items():
            box.config(text=str(rec.get(sp_k, "--")))

    def _load_crop_into_settings(self):
        self._load_crop_into_settings_tab()

    # ==========================================================================
    # PERIODIC TICK LOOP (100ms)
    # ==========================================================================
    def _periodic_tick(self):
        hw.simulate_step(0.1)
        cyclic_engine.process_tick()

        c_key = self.var_recipe.get()
        rec = get_crop_setpoints(c_key)
        dosing_engine.process_tick(self.var_auto_dosing.get(), rec)

        now_dt = datetime.datetime.now()
        self.lbl_clock.config(text=f"{now_dt.strftime('%d-%m-%Y')}\n{now_dt.strftime('%I:%M:%S %p')}")

        # Update Monitoring Screen
        if hasattr(self, "lbl_mon_ec_val"):
            if hw.pv_ec is None or hw.sensor_error:
                self.lbl_mon_ec_val.config(text="SENSOR ERROR", fg=self.COLOR_DANGER, font=("Helvetica", 18, "bold"))
            else:
                self.lbl_mon_ec_val.config(text=f"{hw.pv_ec:.3f}", fg="#1565c0", font=("Helvetica", 26, "bold"))

            if hw.pv_ph is None or hw.sensor_error:
                self.lbl_mon_ph_val.config(text="SENSOR ERROR", fg=self.COLOR_DANGER, font=("Helvetica", 18, "bold"))
            else:
                self.lbl_mon_ph_val.config(text=f"{hw.pv_ph:.2f}", fg="#0891b2", font=("Helvetica", 26, "bold"))

            if hw.pv_water_temp is None or hw.sensor_error:
                self.lbl_mon_temp.config(text="--", fg=self.COLOR_DANGER, font=("Helvetica", 16, "bold"))
            else:
                self.lbl_mon_temp.config(text=f"{hw.pv_water_temp:.1f} °C", fg="#0f172a", font=("Helvetica", 22, "bold"))

            for ch, badge in self.mon_valve_badges.items():
                is_on = hw.get_relay(ch)
                badge.config(
                    text="ON" if is_on else "OFF",
                    bg=self.COLOR_SUCCESS if is_on else self.COLOR_OFF,
                    relief="sunken" if is_on else "raised"
                )

        # Update Fertigation Screen
        if hasattr(self, "lbl_fert_live_ec"):
            if hw.pv_ec is None or hw.sensor_error:
                self.lbl_fert_live_ec.config(text="ERR", fg=self.COLOR_DANGER, font=("Helvetica", 14, "bold"))
            else:
                self.lbl_fert_live_ec.config(text=f"{hw.pv_ec:.3f}", fg="#1565c0", font=("Helvetica", 19, "bold"))

            if hw.pv_ph is None or hw.sensor_error:
                self.lbl_fert_live_ph.config(text="ERR", fg=self.COLOR_DANGER, font=("Helvetica", 14, "bold"))
            else:
                self.lbl_fert_live_ph.config(text=f"{hw.pv_ph:.2f}", fg="#0891b2", font=("Helvetica", 19, "bold"))

            if hw.pv_water_temp is None or hw.sensor_error:
                self.lbl_fert_live_temp.config(text="--", fg=self.COLOR_DANGER, font=("Helvetica", 14, "bold"))
            else:
                self.lbl_fert_live_temp.config(text=f"{hw.pv_water_temp:.1f} °C", fg="#0f172a", font=("Helvetica", 19, "bold"))

            self.lbl_fert_phase_badge.config(
                text=f"PHASE: {dosing_engine.state}",
                fg="#10b981" if dosing_engine.state == "SETPOINTS SATISFIED" else ("#38bdf8" if dosing_engine.is_running or "DOSING" in dosing_engine.state else "#ffffff")
            )
            self.lbl_fert_log.config(text=dosing_engine.status_msg)

            if dosing_engine.ec_active or dosing_engine.ph_active:
                rem_dose = dosing_engine.dosing_time_remaining
                self.lbl_fert_countdown.config(text=f"Active Dosing: {rem_dose}s remaining", fg="#fbbf24")
            elif "MIXING" in dosing_engine.state:
                rem_mix = dosing_engine.mixing_time_remaining
                self.lbl_fert_countdown.config(text=f"Mixing Pause: {rem_mix}s remaining", fg="#38bdf8")
            else:
                self.lbl_fert_countdown.config(text=f"Status: {dosing_engine.state}", fg="#34d399")

            for ch_num, lbl in self.labels_fert_v_status.items():
                is_on = hw.get_relay(ch_num)
                lbl.config(
                    text="DOSING" if is_on else "OFF",
                    bg=self.COLOR_SUCCESS if is_on else self.COLOR_OFF
                )

            if hasattr(self, "btn_start_fert") and self.btn_start_fert.winfo_exists():
                if self.var_auto_dosing.get():
                    if self.btn_start_fert.winfo_ismapped():
                        self.btn_start_fert.pack_forget()
                else:
                    if not self.btn_start_fert.winfo_ismapped():
                        if hasattr(self, "btn_abort_fert") and self.btn_abort_fert.winfo_exists() and self.btn_abort_fert.winfo_ismapped():
                            self.btn_start_fert.pack(side="left", expand=True, fill="x", padx=2, before=self.btn_abort_fert)
                        else:
                            self.btn_start_fert.pack(side="left", expand=True, fill="x", padx=2)
                    if dosing_engine.is_running:
                        self.btn_start_fert.config(text="FERTIGATION RUNNING", state="disabled", bg="#059669")
                    else:
                        self.btn_start_fert.config(text="▶ START FERTIGATION", state="normal", bg="#1565c0", cursor="hand2")

        # Update 3 Cyclic Timers Screen
        # 1. Mix Motor M1 (Ch 4)
        dm_ui = self.timer_ui.get("dosing_motor")
        if dm_ui:
            ts_dm = cyclic_engine.timer_states.get("dosing_motor", {})
            st_dm = ts_dm.get("state", "OFF")
            rem_dm = ts_dm.get("time_left", 0.0)
            dm_ui["lbl_st"].config(
                text=st_dm,
                bg=self.COLOR_SUCCESS if st_dm == "ON" else ("#1565c0" if st_dm == "OFF" else self.COLOR_OFF)
            )
            m, s = int(rem_dm // 60), int(rem_dm % 60)
            dm_ui["lbl_rem"].config(text=f"Rem: {m:02d}:{s:02d}")
            btn_dm = dm_ui.get("btn_run")
            if btn_dm:
                if st_dm == "ON":
                    btn_dm.config(text="⏹ Stop Motor", bg="#fee2e2", fg="#b91c1c", activebackground="#fecaca", activeforeground="#991b1b")
                else:
                    btn_dm.config(text="▶ Start Motor", bg="#dcfce7", fg="#15803d", activebackground="#bbf7d0", activeforeground="#14532d")

        # 2. Irrigation (Ch 5 Bypass V2 + Auto Ch 7 Inlet Pump M2)
        ir_ui = self.timer_ui.get("irrigation")
        if ir_ui:
            ts_ir = cyclic_engine.timer_states.get("irrigation", {})
            st_ir = ts_ir.get("state", "OFF")
            rem_ir = ts_ir.get("time_left", 0.0)
            ir_ui["lbl_st"].config(
                text=st_ir,
                bg=self.COLOR_SUCCESS if st_ir == "ON" else ("#0891b2" if st_ir == "OFF" else self.COLOR_OFF)
            )
            m, s = int(rem_ir // 60), int(rem_ir % 60)
            ir_ui["lbl_rem"].config(text=f"Rem: {m:02d}:{s:02d}")

            # Update manual toggle button
            btn_ir = ir_ui.get("btn_run")
            if btn_ir:
                if st_ir == "ON":
                    btn_ir.config(text="⏹ Stop Irrig", bg="#fed7aa", fg="#9a3412", activebackground="#fdba74", activeforeground="#7c2d12")
                else:
                    btn_ir.config(text="▶ Start Irrig", bg="#dcfce7", fg="#15803d", activebackground="#bbf7d0", activeforeground="#14532d")

        # 3. Tank Filling (Ch 6 Tank V1 + Auto Ch 7 Inlet Pump M2)
        tf_ui = self.timer_ui.get("tank_filling")
        if tf_ui:
            ts_tf = cyclic_engine.timer_states.get("tank_filling", {})
            st_tf = ts_tf.get("state", "OFF")
            rem_tf = ts_tf.get("time_left", 0.0)
            tf_ui["lbl_st"].config(
                text=st_tf,
                bg=self.COLOR_SUCCESS if st_tf == "ON" else ("#f59e0b" if "WAIT" in st_tf else ("#0d9488" if st_tf == "OFF" else self.COLOR_OFF))
            )
            m, s = int(rem_tf // 60), int(rem_tf % 60)
            tf_ui["lbl_rem"].config(text=f"Rem: {m:02d}:{s:02d}")

            # Update manual toggle button
            btn_tf = tf_ui.get("btn_run")
            if btn_tf:
                if st_tf == "ON":
                    btn_tf.config(text="⏹ Stop Fill", bg="#fed7aa", fg="#9a3412", activebackground="#fdba74", activeforeground="#7c2d12")
                else:
                    btn_tf.config(text="▶ Start Fill", bg="#dcfce7", fg="#15803d", activebackground="#bbf7d0", activeforeground="#14532d")

        self.after(100, self._periodic_tick)

# ==============================================================================
# ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    threading.Thread(target=start_bluetooth_server, daemon=True, name="BT_Server").start()
    threading.Thread(target=auto_trust_devices, daemon=True, name="BT_Trust").start()
    threading.Thread(target=start_mqtt_client, daemon=True, name="MQTT_Client").start()
    threading.Thread(target=mqtt_heartbeat_worker, daemon=True, name="MQTT_Heartbeat").start()
    threading.Thread(target=mqtt_telemetry_worker, daemon=True, name="MQTT_Telemetry").start()

    app = InHydroFertigationApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        hw.emergency_all_off()
        sys.exit(0)
    except Exception as e:
        import traceback
        traceback.print_exc()
        hw.emergency_all_off()
        sys.exit(1)
