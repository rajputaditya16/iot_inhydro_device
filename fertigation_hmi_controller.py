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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(BASE_DIR, "device_id.txt")

def get_device_id():
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                val = f.read().strip()
                if val: return val
        except Exception: pass
    try:
        with open(ID_FILE, "w") as f:
            f.write("control123\n")
    except Exception: pass
    return "control123"

DEVICE_NAME = get_device_id()
RECIPE_FILE = os.path.join(BASE_DIR, "crop_recipes.json")
CONFIG_FILE = os.path.join(BASE_DIR, f"config_{DEVICE_NAME}.json")
CONFIG_FALLBACK_FILE = os.path.join(BASE_DIR, "config_system.json")
TIMERS_FILE = os.path.join(BASE_DIR, "config_irrigation_timers.json")
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")
running = True

class ActuatorMap:
    EC_VALVE_1              = 1
    EC_VALVE_2              = 2
    PH_DOWN_VALVE           = 3
    PH_UP_VALVE             = 4
    SPARE_VALVE             = 5
    RO_WATER_PUMP           = 6
    TANK_RETURN_VALVE       = 7
    MAIN_PUMP               = 8
    PUMP_OUTLET_VALVE       = 9
    FERTIGATION_LOOP_VALVE  = 10
    IRRIGATION_MASTER_VALVE = 11
    ZONE_1_VALVE            = 12
    ZONE_2_VALVE            = 13

    PH_VALVE          = PH_DOWN_VALVE
    EC_VALVE_3        = PH_DOWN_VALVE
    EC_VALVE_4        = PH_UP_VALVE
    FERTIGATION_VALVE = FERTIGATION_LOOP_VALVE
    IRRIGATION_VALVE  = IRRIGATION_MASTER_VALVE
    ZONE_VALVE        = ZONE_1_VALVE

ACTUATOR_NAMES = {
    1:  "EC1",
    2:  "EC2",
    3:  "pH Down",
    4:  "pH Up",
    5:  "Relay 5",
    6:  "RO Pump",
    7:  "S.V 7",
    8:  "Main Pump",
    9:  "S.V 9",
    10: "S.V 10",
    11: "S.V 11",
    12: "Zone 1",
    13: "Zone 2",
}

DEFAULT_RECIPES = {
    "tomato": {
        "crop_name": "Tomato",
        "ec_min": 2.00,
        "ec_max": 2.50,
        "ph_min": 5.50,
        "ph_target": 6.00,
        "ph_max": 6.50,
        "ec1_safety_max": 2.80,
        "ec2_safety_max": 2.80,
        "ph_down_safety_min": 4.80,
        "ph_up_safety_max": 7.50,
        "timer_enabled": True,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 5.0,
        "off_min": 60.0
    },
    "cucumber": {
        "crop_name": "Cucumber",
        "ec_min": 1.80,
        "ec_max": 2.20,
        "ph_min": 5.40,
        "ph_target": 5.80,
        "ph_max": 6.40,
        "ec1_safety_max": 2.50,
        "ec2_safety_max": 2.50,
        "ph_down_safety_min": 4.60,
        "ph_up_safety_max": 7.20,
        "timer_enabled": True,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 5.0,
        "off_min": 60.0
    },
    "capsicum": {
        "crop_name": "Capsicum / Bell Pepper",
        "ec_min": 1.80,
        "ec_max": 2.20,
        "ph_min": 5.80,
        "ph_target": 6.20,
        "ph_max": 6.60,
        "ec1_safety_max": 2.50,
        "ec2_safety_max": 2.50,
        "ph_down_safety_min": 5.00,
        "ph_up_safety_max": 7.50,
        "timer_enabled": True,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 5.0,
        "off_min": 60.0
    },
    "strawberry": {
        "crop_name": "Strawberry",
        "ec_min": 1.20,
        "ec_max": 1.60,
        "ph_min": 5.40,
        "ph_target": 5.80,
        "ph_max": 6.30,
        "ec1_safety_max": 1.90,
        "ec2_safety_max": 1.90,
        "ph_down_safety_min": 4.80,
        "ph_up_safety_max": 7.00,
        "timer_enabled": True,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 5.0,
        "off_min": 60.0
    },
    "lettuce": {
        "crop_name": "Lettuce / Leafy Greens",
        "ec_min": 1.10,
        "ec_max": 1.40,
        "ph_min": 5.40,
        "ph_target": 5.80,
        "ph_max": 6.30,
        "ec1_safety_max": 1.70,
        "ec2_safety_max": 1.70,
        "ph_down_safety_min": 4.80,
        "ph_up_safety_max": 7.00,
        "timer_enabled": True,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 5.0,
        "off_min": 60.0
    }
}

DEFAULT_CYCLIC_TIMERS = {
    "zone_1": {
        "name": "Zone 1 Drip Line",
        "enabled": True,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 5.0,
        "off_min": 15.0
    },
    "zone_2": {
        "name": "Zone 2 Drip Line",
        "enabled": True,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 5.0,
        "off_min": 15.0
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
    "selected_fert_zone": "both",
    "active_crop": "cucumber"
}

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
            print(f"[JSON] Error reading {filepath}: {e}. Regenerating defaults...")
    else:
        print(f"[JSON] File {filepath} does not exist. Creating default file...")

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

crop_recipes = load_json(RECIPE_FILE, DEFAULT_RECIPES)
_recipes_modified = False
for k, rec in crop_recipes.items():
    d_rec = DEFAULT_RECIPES.get(k, DEFAULT_RECIPES["tomato"])
    if "ec_min" not in rec or "ec_max" not in rec:
        t_ec = float(rec.get("target_ec", d_rec["ec_max"]))
        rec["ec_min"] = round(max(0.4, t_ec - 0.3), 2)
        rec["ec_max"] = round(t_ec, 2)
        _recipes_modified = True
    if "ph_min" not in rec or "ph_target" not in rec or "ph_max" not in rec:
        t_ph = float(rec.get("target_ph", d_rec["ph_target"]))
        rec["ph_min"] = round(max(4.5, t_ph - 0.4), 2)
        rec["ph_target"] = round(t_ph, 2)
        rec["ph_max"] = round(min(8.0, t_ph + 0.5), 2)
        _recipes_modified = True
    if "ec1_safety_max" not in rec:
        rec["ec1_safety_max"] = round(float(rec["ec_max"]) + 0.4, 2)
        rec["ec2_safety_max"] = round(float(rec["ec_max"]) + 0.4, 2)
        _recipes_modified = True
    if "ph_down_safety_min" not in rec:
        rec["ph_down_safety_min"] = 4.80
        rec["ph_up_safety_max"] = 7.50
        _recipes_modified = True
    if "timer_enabled" not in rec:
        rec["timer_enabled"] = bool(d_rec.get("timer_enabled", True))
        rec["start_time"] = str(d_rec.get("start_time", "06:00"))
        rec["stop_time"] = str(d_rec.get("stop_time", "18:00"))
        rec["on_min"] = float(d_rec.get("on_min", 5.0))
        rec["off_min"] = float(d_rec.get("off_min", 60.0))
        _recipes_modified = True

    base_zone_cfg = {
        "crop_name": rec.get("crop_name", k.title()),
        "ec_min": float(rec.get("ec_min", 1.80)),
        "ec_max": float(rec.get("ec_max", 2.20)),
        "ph_min": float(rec.get("ph_min", 5.40)),
        "ph_target": float(rec.get("ph_target", 5.80)),
        "ph_max": float(rec.get("ph_max", 6.40)),
        "ec1_safety_max": float(rec.get("ec1_safety_max", 2.50)),
        "ec2_safety_max": float(rec.get("ec2_safety_max", 2.50)),
        "ph_down_safety_min": float(rec.get("ph_down_safety_min", 4.60)),
        "ph_up_safety_max": float(rec.get("ph_up_safety_max", 7.20)),
        "timer_enabled": bool(rec.get("timer_enabled", True)),
        "start_time": str(rec.get("start_time", "06:00")),
        "stop_time": str(rec.get("stop_time", "18:00")),
        "on_min": float(rec.get("on_min", 5.0)),
        "off_min": float(rec.get("off_min", 60.0))
    }

    if "zones" not in rec or not isinstance(rec["zones"], dict):
        rec["zones"] = {
            "both": dict(base_zone_cfg),
            "zone_1": dict(base_zone_cfg),
            "zone_2": dict(base_zone_cfg)
        }
        _recipes_modified = True
    else:
        for zk in ["both", "zone_1", "zone_2"]:
            if zk not in rec["zones"]:
                rec["zones"][zk] = dict(base_zone_cfg)
                _recipes_modified = True
            else:
                z_obj = rec["zones"][zk]
                for p_key, p_val in [
                    ("timer_enabled", bool(rec.get("timer_enabled", True))),
                    ("start_time", str(rec.get("start_time", "06:00"))),
                    ("stop_time", str(rec.get("stop_time", "18:00"))),
                    ("on_min", float(rec.get("on_min", 5.0))),
                    ("off_min", float(rec.get("off_min", 60.0)))
                ]:
                    if p_key not in z_obj:
                        z_obj[p_key] = p_val
                        _recipes_modified = True

if _recipes_modified:
    save_json(RECIPE_FILE, crop_recipes)

def get_zone_recipe(crop_key: str, zone_key: str = "both") -> dict:
    rec = crop_recipes.get(crop_key, DEFAULT_RECIPES.get("tomato", {}))
    zones = rec.get("zones", {})
    if isinstance(zones, dict) and zone_key in zones:
        return zones[zone_key]
    return {
        "crop_name": rec.get("crop_name", crop_key.title()),
        "ec_min": float(rec.get("ec_min", 1.80)),
        "ec_max": float(rec.get("ec_max", 2.20)),
        "ph_min": float(rec.get("ph_min", 5.40)),
        "ph_target": float(rec.get("ph_target", 5.80)),
        "ph_max": float(rec.get("ph_max", 6.40)),
        "ec1_safety_max": float(rec.get("ec1_safety_max", 2.50)),
        "ec2_safety_max": float(rec.get("ec2_safety_max", 2.50)),
        "ph_down_safety_min": float(rec.get("ph_down_safety_min", 4.60)),
        "ph_up_safety_max": float(rec.get("ph_up_safety_max", 7.20)),
        "timer_enabled": bool(rec.get("timer_enabled", True)),
        "start_time": str(rec.get("start_time", "06:00")),
        "stop_time": str(rec.get("stop_time", "18:00")),
        "on_min": float(rec.get("on_min", 5.0)),
        "off_min": float(rec.get("off_min", 60.0))
    }

_raw_t = load_json(TIMERS_FILE, DEFAULT_CYCLIC_TIMERS)
if "zone_1" not in _raw_t:
    cyclic_timer_cfg = {
        "zone_1": {
            "name": _raw_t.get("name", "Zone 1 Drip Line"),
            "enabled": _raw_t.get("enabled", True),
            "start_time": _raw_t.get("start_time", "06:00"),
            "stop_time": _raw_t.get("stop_time", "18:00"),
            "on_min": _raw_t.get("on_min", 5.0),
            "off_min": _raw_t.get("off_min", 15.0)
        },
        "zone_2": {
            "name": "Zone 2 Drip Line",
            "enabled": True,
            "start_time": "06:00",
            "stop_time": "18:00",
            "on_min": 5.0,
            "off_min": 15.0
        }
    }
    save_json(TIMERS_FILE, cyclic_timer_cfg)
else:
    cyclic_timer_cfg = _raw_t
if os.path.exists(CONFIG_FILE):
    system_config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    save_json(CONFIG_FALLBACK_FILE, system_config)
elif os.path.exists(CONFIG_FALLBACK_FILE):
    system_config = load_json(CONFIG_FALLBACK_FILE, DEFAULT_CONFIG)
    save_json(CONFIG_FILE, system_config)
else:
    system_config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    save_json(CONFIG_FALLBACK_FILE, system_config)

_relay_lock = threading.Lock()
_sensor_lock = threading.Lock()

class HardwareController:
    def __init__(self):
        self.relays = {i: False for i in range(1, 14)}
        self.relay_queue = queue.Queue()

        self.pv_ec = None
        self.pv_ph = None
        self.pv_water_temp = None
        self.is_real_sensor = False
        self.sensor_error = True
        self.ec_last_seen = 0.0
        self.ph_last_seen = 0.0

        self.worker_thread = threading.Thread(target=self._relay_worker, daemon=True)
        self.worker_thread.start()

        self.sensor_thread = threading.Thread(target=self._sensor_worker, daemon=True)
        self.sensor_thread.start()

    def set_relay(self, ch: int, state: bool):
        if self.relays.get(ch) == state:
            return

        if state:
            if ch == ActuatorMap.PH_DOWN_VALVE and self.relays.get(ActuatorMap.PH_UP_VALVE):
                self.set_relay(ActuatorMap.PH_UP_VALVE, False)
            elif ch == ActuatorMap.PH_UP_VALVE and self.relays.get(ActuatorMap.PH_DOWN_VALVE):
                self.set_relay(ActuatorMap.PH_DOWN_VALVE, False)

        self.relays[ch] = state
        self.relay_queue.put((ch, state))

    def get_relay(self, ch: int) -> bool:
        return self.relays.get(ch, False)

    def emergency_all_off(self):
        while not self.relay_queue.empty():
            try:
                self.relay_queue.get_nowait()
                self.relay_queue.task_done()
            except Exception:
                break
        for ch in range(1, 14):
            self.relays[ch] = False

        self.relay_queue.put(("ALL_OFF", False))

    def _relay_worker(self):
        while True:
            try:
                ch, state = self.relay_queue.get()
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
                                    try:
                                        inst.write_bit(coil_i, 0, functioncode=5)
                                    except Exception:
                                        pass
                                print(f"[RELAY] ALL OFF: All 16 relay channels set to OFF on {port} (Slave {slave_id})")
                            else:
                                inst.write_bit(ch - 1, 1 if state else 0, functioncode=5)
                                print(f"[RELAY] Ch {ch} set to {'ON' if state else 'OFF'} on {port} (Slave {slave_id})")
                except Exception as err:
                    print(f"[RELAY ERROR] Failed to set Ch {ch} to {state} on {port} (Slave {slave_id}): {err}")
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
                    except Exception:
                        pass
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
                    except Exception:
                        pass
                    finally:
                        if inst_ph and hasattr(inst_ph, "serial") and inst_ph.serial and getattr(inst_ph.serial, "is_open", False):
                            try: inst_ph.serial.close()
                            except Exception: pass

                if read_ec_ok:
                    self.ec_last_seen = time.time()
                if read_ph_ok:
                    self.ph_last_seen = time.time()

                now = time.time()

                if now - self.ec_last_seen > 15.0:
                    self.pv_ec = None

                if now - self.ph_last_seen > 15.0:
                    self.pv_ph = None
                    self.pv_water_temp = None

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

class CyclicIrrigationEngine:
    def __init__(self, hardware: HardwareController):
        self.hw = hardware
        self.timer_states = {
            "zone_1": {"state": "OFF", "last_toggle": 0.0, "time_left": 0.0, "manual_stopped": False},
            "zone_2": {"state": "OFF", "last_toggle": 0.0, "time_left": 0.0, "manual_stopped": False}
        }
        self.was_irrigating = False

    def stop_irrigation(self):
        for z in ["zone_1", "zone_2"]:
            ts = self.timer_states[z]
            ts["state"] = "STOPPED"
            ts["manual_stopped"] = True
            ts["last_toggle"] = time.time()
            ts["time_left"] = 0.0
        self.hw.set_relay(ActuatorMap.ZONE_1_VALVE, False)
        self.hw.set_relay(ActuatorMap.ZONE_2_VALVE, False)
        self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
        self.hw.set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, False)
        self.hw.set_relay(ActuatorMap.RO_WATER_PUMP, False)
        self.was_irrigating = False

    def stop_zone(self, zone_key: str):
        if zone_key in self.timer_states:
            ts = self.timer_states[zone_key]
            ts["state"] = "STOPPED"
            ts["manual_stopped"] = True
            ts["last_toggle"] = time.time()
            ts["time_left"] = 0.0
            ch = ActuatorMap.ZONE_1_VALVE if zone_key == "zone_1" else ActuatorMap.ZONE_2_VALVE
            self.hw.set_relay(ch, False)

        other_key = "zone_2" if zone_key == "zone_1" else "zone_1"
        if self.timer_states.get(other_key, {}).get("state") != "ON":
            self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
            self.hw.set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, False)
            self.hw.set_relay(ActuatorMap.RO_WATER_PUMP, False)
            self.was_irrigating = False

    def start_zone(self, zone_key: str):
        if 'engine' in globals() and getattr(engine, 'is_running', False):
            engine.stop_cycle()
            self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
            self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
            self.hw.set_relay(ActuatorMap.PH_DOWN_VALVE, False)
            self.hw.set_relay(ActuatorMap.PH_UP_VALVE, False)
            self.hw.set_relay(ActuatorMap.TANK_RETURN_VALVE, False)
            self.hw.set_relay(ActuatorMap.PUMP_OUTLET_VALVE, False)
            engine.active_venturis = {1: False, 2: False, 3: False, 4: False}
            engine.state = "INTERRUPTED BY IRRIGATION"
            engine.status_msg = f" Fertigation aborted: Cyclic Irrigation ({zone_key}) started!"

        if zone_key in self.timer_states:
            ts = self.timer_states[zone_key]
            ts["manual_stopped"] = False
            ts["state"] = "ON"
            ts["last_toggle"] = time.time()
            cfg = cyclic_timer_cfg.get(zone_key, {})
            ts["time_left"] = float(cfg.get("on_min", 5.0)) * 60.0
            ch = ActuatorMap.ZONE_1_VALVE if zone_key == "zone_1" else ActuatorMap.ZONE_2_VALVE
            self.hw.set_relay(ch, True)
            self.hw.set_relay(ActuatorMap.RO_WATER_PUMP, True)
            self.hw.set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, True)
            self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, True)
            self.hw.set_relay(ActuatorMap.MAIN_PUMP, False)

            self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
            self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
            self.hw.set_relay(ActuatorMap.PH_DOWN_VALVE, False)
            self.hw.set_relay(ActuatorMap.PH_UP_VALVE, False)
            self.was_irrigating = True

    def process_tick(self):
        if engine.is_running:
            return

        now_dt = datetime.datetime.now()
        cur_time = now_dt.time()
        now_sec = time.time()

        any_zone_on = False

        for z_key, ch_valve in [("zone_1", ActuatorMap.ZONE_1_VALVE), ("zone_2", ActuatorMap.ZONE_2_VALVE)]:
            cfg = cyclic_timer_cfg.get(z_key, {})
            ts = self.timer_states[z_key]

            if not cfg.get("enabled", True) or ts.get("manual_stopped", False):
                if ts.get("manual_stopped", False):
                    ts["state"] = "STOPPED"
                else:
                    ts["state"] = "DISABLED"
                ts["time_left"] = 0.0
                if self.hw.get_relay(ch_valve):
                    self.hw.set_relay(ch_valve, False)
                continue

            try:
                t_start = datetime.datetime.strptime(cfg.get("start_time", "06:00"), "%H:%M").time()
                t_stop  = datetime.datetime.strptime(cfg.get("stop_time", "18:00"), "%H:%M").time()
            except Exception:
                t_start = datetime.time(0, 0)
                t_stop  = datetime.time(23, 59)

            in_window = (t_start <= cur_time <= t_stop) if t_start <= t_stop else (cur_time >= t_start or cur_time <= t_stop)

            on_sec = float(cfg.get("on_min", 5.0)) * 60.0
            off_sec = float(cfg.get("off_min", 15.0)) * 60.0

            if in_window:
                if ts["state"] in ["OFF", "WINDOW_CLOSED", "DISABLED", "STOPPED"]:

                    if ts["last_toggle"] == 0.0 or (now_sec - ts["last_toggle"] >= off_sec):
                        ts["state"] = "ON"
                        ts["last_toggle"] = now_sec
                        self.hw.set_relay(ch_valve, True)
                        any_zone_on = True
                    else:
                        ts["state"] = "OFF"
                        if self.hw.get_relay(ch_valve):
                            self.hw.set_relay(ch_valve, False)
                elif ts["state"] == "ON":
                    if now_sec - ts["last_toggle"] >= on_sec:
                        ts["state"] = "OFF"
                        ts["last_toggle"] = now_sec
                        self.hw.set_relay(ch_valve, False)
                    else:
                        if not self.hw.get_relay(ch_valve):
                            self.hw.set_relay(ch_valve, True)
                        any_zone_on = True

                dur = on_sec if ts["state"] == "ON" else off_sec
                ts["time_left"] = max(0.0, dur - (now_sec - ts["last_toggle"]))
            else:
                ts["state"] = "WINDOW_CLOSED"
                ts["last_toggle"] = 0.0
                ts["time_left"] = 0.0
                if self.hw.get_relay(ch_valve):
                    self.hw.set_relay(ch_valve, False)

        if any_zone_on:

            self.hw.set_relay(ActuatorMap.RO_WATER_PUMP, True)
            self.hw.set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, True)
            self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, True)
            self.hw.set_relay(ActuatorMap.MAIN_PUMP, False)

            self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
            self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
            self.hw.set_relay(ActuatorMap.PH_DOWN_VALVE, False)
            self.hw.set_relay(ActuatorMap.PH_UP_VALVE, False)
            self.was_irrigating = True
        else:
            if self.was_irrigating:
                self.hw.set_relay(ActuatorMap.RO_WATER_PUMP, False)
                self.hw.set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, False)
                self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
                self.was_irrigating = False

irrigation_engine = CyclicIrrigationEngine(hw)

class FertigationAutomationEngine:
    def __init__(self, hardware: HardwareController):
        self.hw = hardware
        self.is_running = False
        self.active_recipe_key = "cucumber"
        self.state = "IDLE"
        self.stop_event = threading.Event()
        self.status_msg = "System Ready"

        self.baseline_ec = 0.60
        self.baseline_ph = 7.20

        self.active_venturis = {1: False, 2: False, 3: False, 4: False}
        self.venturi_safety_status = {1: "OK", 2: "OK", 3: "OK", 4: "OK"}
        self.dosing_time_remaining = 0.0
        self.delivery_target = "both"
        self.last_cycle_finish_time = 0.0

    def start_cycle(self, recipe_key: str, delivery_target: str = "both") -> tuple:
        if self.is_running:
            return False, "A fertigation cycle is already in progress!"

        if getattr(self.hw, "sensor_error", False) or self.hw.pv_ec is None or self.hw.pv_ph is None:
            return False, "Cannot start Fertigation: SENSOR ERROR!\nReal live sensor data required. Check probe connection."

        if delivery_target == "zone_1":
            target_recipe = get_zone_recipe(recipe_key, "zone_1")
        elif delivery_target == "zone_2":
            target_recipe = get_zone_recipe(recipe_key, "zone_2")
        else:
            target_recipe = get_zone_recipe(recipe_key, "both")

        ec_min = float(target_recipe.get("ec_min", 1.80))
        ec_max = float(target_recipe.get("ec_max", 2.20))
        ph_min = float(target_recipe.get("ph_min", 5.40))
        ph_target = float(target_recipe.get("ph_target", 5.80))
        ph_max = float(target_recipe.get("ph_max", 6.40))

        current_ec = round(self.hw.pv_ec, 3)
        current_ph = round(self.hw.pv_ph, 2)

        ec_needs_dosing = (current_ec <= ec_min)
        ph_needs_dosing = (current_ph >= ph_max or current_ph <= ph_min)

        if not ec_needs_dosing and not ph_needs_dosing and delivery_target != "sequential":
            self.state = "SETPOINTS SATISFIED"
            self.status_msg = (
                f"EC ({current_ec:.3f}) > Min ({ec_min:.2f}) & pH ({current_ph:.2f}) in range ({ph_min:.2f}-{ph_max:.2f}). "
                f"Fertigation not needed. Main Pump remains OFF."
            )
            return False, (
                f"Fertigation Standby:\n"
                f"Current EC ({current_ec:.3f} mS/cm) is already above Min ({ec_min:.2f} mS/cm).\n"
                f"Current pH ({current_ph:.2f}) is in target range ({ph_min:.2f} - {ph_max:.2f}).\n"
                f"Main Pump will start when EC <= {ec_min:.2f} or pH triggers."
            )

        if self.hw.get_relay(ActuatorMap.RO_WATER_PUMP):
            self.hw.set_relay(ActuatorMap.RO_WATER_PUMP, False)

        self.active_recipe_key = recipe_key
        self.delivery_target = delivery_target
        self.is_running = True
        self.stop_event.clear()
        threading.Thread(target=self._run_loop, daemon=True).start()
        return True, "Fertigation started."

    def stop_cycle(self):
        self.stop_event.set()
        self.is_running = False
        self.active_venturis = {1: False, 2: False, 3: False, 4: False}
        self.hw.emergency_all_off()
        self.state = "STOPPED"
        self.status_msg = "Fertigation Cycle Aborted / Emergency Stop"

    def _execute_single_batch(self, recipe: dict, target_zones: list, stage_prefix: str = "") -> bool:
        ec_min = float(recipe.get("ec_min", 1.80))
        ec_max = float(recipe.get("ec_max", 2.20))
        ph_min = float(recipe.get("ph_min", 5.40))
        ph_target = float(recipe.get("ph_target", 5.80))
        ph_max = float(recipe.get("ph_max", 6.40))

        ec1_safety_max = float(recipe.get("ec1_safety_max", ec_max + 0.30))
        ec2_safety_max = float(recipe.get("ec2_safety_max", ec_max + 0.30))
        ph_down_safety_min = float(recipe.get("ph_down_safety_min", 4.60))
        ph_up_safety_max = float(recipe.get("ph_up_safety_max", 7.20))

        if getattr(self.hw, "sensor_error", False) or self.hw.pv_ec is None or self.hw.pv_ph is None:
            self.state = "SENSOR ERROR"
            self.status_msg = "⚠ Aborted: Live sensor communication lost!"
            self.hw.emergency_all_off()
            return False

        cur_ec = round(self.hw.pv_ec, 3)
        cur_ph = round(self.hw.pv_ph, 2)

        needs_ec_dosing = (cur_ec <= ec_min)
        needs_ph_down   = (cur_ph >= ph_max)
        needs_ph_up     = (cur_ph <= ph_min)

        needs_conditioning = needs_ec_dosing or needs_ph_down or needs_ph_up

        if needs_conditioning:

            self.state = f"{stage_prefix}STARTING PUMP"
            self.status_msg = f"{stage_prefix}Step 1: Main Pump (Ch 8) ON..."
            self.hw.set_relay(ActuatorMap.MAIN_PUMP, True)
            time.sleep(0.8)
            if self.stop_event.is_set(): return False

            self.status_msg = f"{stage_prefix}Step 2: Pump Outlet Valve (Ch 9) ON..."
            self.hw.set_relay(ActuatorMap.PUMP_OUTLET_VALVE, True)
            time.sleep(0.5)
            if self.stop_event.is_set(): return False

            self.status_msg = f"{stage_prefix}Step 3: Fertigation Loop Valve (Ch 10) ON..."
            self.hw.set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, True)
            time.sleep(0.5)
            if self.stop_event.is_set(): return False

            self.status_msg = f"{stage_prefix}Step 4: Tank Return Valve (Ch 7) ON (Loop established)..."
            self.hw.set_relay(ActuatorMap.TANK_RETURN_VALVE, True)
            time.sleep(0.5)
            if self.stop_event.is_set(): return False

            self.hw.set_relay(ActuatorMap.RO_WATER_PUMP, False)
            self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
            self.hw.set_relay(ActuatorMap.ZONE_1_VALVE, False)
            self.hw.set_relay(ActuatorMap.ZONE_2_VALVE, False)

            # Record initial values when fertigation starts
            initial_start_ec = round(self.hw.pv_ec, 3) if self.hw.pv_ec is not None else 0.0
            initial_start_ph = round(self.hw.pv_ph, 2) if self.hw.pv_ph is not None else 0.0
            prev_loop_ec = initial_start_ec
            prev_loop_ph = initial_start_ph
            stagnant_loops = 0
            max_dosing_timeout = float(recipe.get("dosing_timeout_sec", 180.0))
            mix_seconds = float(recipe.get("mixing_time_sec", 30.0))
            loop_idx = 0
            target_reached = False

            while not self.stop_event.is_set():
                loop_idx += 1
                self.state = f"{stage_prefix}RECIRCULATION & DOSING (Loop {loop_idx})"
                dosing_start_time = time.time()
                sensor_err_start = 0.0

                while not self.stop_event.is_set():
                    if self.hw.get_relay(ActuatorMap.IRRIGATION_MASTER_VALVE) or \
                       self.hw.get_relay(ActuatorMap.ZONE_1_VALVE) or \
                       self.hw.get_relay(ActuatorMap.ZONE_2_VALVE) or \
                       self.hw.get_relay(ActuatorMap.RO_WATER_PUMP):
                        self.status_msg = "⚠ Fertigation aborted: Irrigation valve became active during dosing!"
                        self.stop_event.set()
                        break

                    if getattr(self.hw, "sensor_error", False) or self.hw.pv_ec is None or self.hw.pv_ph is None:
                        if sensor_err_start == 0.0:
                            sensor_err_start = time.time()
                        if time.time() - sensor_err_start > 12.0:
                            self.status_msg = "⚠ Sensor communication lost for >12s during dosing! Aborting cycle."
                            self.hw.emergency_all_off()
                            return False
                        time.sleep(0.5)
                        continue
                    else:
                        sensor_err_start = 0.0

                    cur_ec = round(self.hw.pv_ec, 3)
                    cur_ph = round(self.hw.pv_ph, 2)

                    if cur_ec <= ec_min and not self.active_venturis.get(1):
                        self.hw.set_relay(ActuatorMap.EC_VALVE_1, True)
                        self.hw.set_relay(ActuatorMap.EC_VALVE_2, True)
                        self.active_venturis[1] = True
                        self.active_venturis[2] = True
                        self.venturi_safety_status[1] = "DOSING"
                        self.venturi_safety_status[2] = "DOSING"
                    elif cur_ec >= ec_max and self.active_venturis.get(1):
                        self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
                        self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
                        self.active_venturis[1] = False
                        self.active_venturis[2] = False
                        self.venturi_safety_status[1] = "AT SETPOINT"
                        self.venturi_safety_status[2] = "AT SETPOINT"

                    if cur_ec >= ec1_safety_max or cur_ec >= ec2_safety_max:
                        if self.active_venturis.get(1):
                            self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
                            self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
                            self.active_venturis[1] = False
                            self.active_venturis[2] = False
                            self.venturi_safety_status[1] = f"TRIPPED (EC >= {ec1_safety_max:.2f})"
                            self.venturi_safety_status[2] = f"TRIPPED (EC >= {ec2_safety_max:.2f})"

                    if cur_ph >= ph_max and not self.active_venturis.get(3) and not self.active_venturis.get(4):
                        self.hw.set_relay(ActuatorMap.PH_DOWN_VALVE, True)
                        self.active_venturis[3] = True
                        self.venturi_safety_status[3] = "DOSING"
                    elif cur_ph <= ph_target and self.active_venturis.get(3):
                        self.hw.set_relay(ActuatorMap.PH_DOWN_VALVE, False)
                        self.active_venturis[3] = False
                        self.venturi_safety_status[3] = "AT SETPOINT"

                    if cur_ph <= ph_min and not self.active_venturis.get(4) and not self.active_venturis.get(3):
                        self.hw.set_relay(ActuatorMap.PH_UP_VALVE, True)
                        self.active_venturis[4] = True
                        self.venturi_safety_status[4] = "DOSING"
                    elif cur_ph >= ph_target and self.active_venturis.get(4):
                        self.hw.set_relay(ActuatorMap.PH_UP_VALVE, False)
                        self.active_venturis[4] = False
                        self.venturi_safety_status[4] = "AT SETPOINT"

                    if cur_ph <= ph_down_safety_min and self.active_venturis.get(3):
                        self.hw.set_relay(ActuatorMap.PH_DOWN_VALVE, False)
                        self.active_venturis[3] = False
                        self.venturi_safety_status[3] = f"TRIPPED (pH <= {ph_down_safety_min:.2f})"

                    if cur_ph >= ph_up_safety_max and self.active_venturis.get(4):
                        self.hw.set_relay(ActuatorMap.PH_UP_VALVE, False)
                        self.active_venturis[4] = False
                        self.venturi_safety_status[4] = f"TRIPPED (pH >= {ph_up_safety_max:.2f})"

                    ec_favourable = (not self.active_venturis.get(1)) and (cur_ec >= ec_min)
                    ph_favourable = (not self.active_venturis.get(3)) and (not self.active_venturis.get(4)) and (ph_min <= cur_ph <= ph_max)

                    active_dosing_txt = []
                    if self.active_venturis.get(1): active_dosing_txt.append("EC1+EC2 (Tandem)")
                    if self.active_venturis.get(3): active_dosing_txt.append(f"pH Down ➔ {ph_target:.2f}")
                    if self.active_venturis.get(4): active_dosing_txt.append(f"pH Up ➔ {ph_target:.2f}")

                    if active_dosing_txt:
                        self.status_msg = f"{stage_prefix}[Loop {loop_idx}] Dosing: EC={cur_ec:.3f}, pH={cur_ph:.2f} | {', '.join(active_dosing_txt)}"
                    else:
                        self.status_msg = f"{stage_prefix}[Loop {loop_idx}] Monitoring: EC={cur_ec:.3f} (Req >= {ec_min:.2f}), pH={cur_ph:.2f} (Req {ph_min:.2f}..{ph_max:.2f})"

                    if ec_favourable and ph_favourable:
                        self.status_msg = f"✔ Values Favourable! EC={cur_ec:.3f} mS/cm, pH={cur_ph:.2f} ➔ Commencing 30s Circulation & Mixing..."
                        break

                    if time.time() - dosing_start_time > max_dosing_timeout:
                        break

                    time.sleep(0.4)

                # Dosing phase over (either matched or 180s expired) -> Immediately turn OFF nutrient relays (Ch 1, 2, 3, 4)
                self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
                self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
                self.hw.set_relay(ActuatorMap.PH_DOWN_VALVE, False)
                self.hw.set_relay(ActuatorMap.PH_UP_VALVE, False)
                self.active_venturis = {1: False, 2: False, 3: False, 4: False}

                if self.stop_event.is_set():
                    return False

                # 30-Second Circulation & Mixing stage: Ch 1, 2, 3, 4 OFF; Ch 7, 8, 9, 10 remain ON
                self.state = f"{stage_prefix}CIRCULATION & MIXING (Loop {loop_idx})"
                mix_start = time.time()
                while (time.time() - mix_start < mix_seconds) and not self.stop_event.is_set():
                    rem_m = max(0.0, mix_seconds - (time.time() - mix_start))
                    cur_ec_m = self.hw.pv_ec if self.hw.pv_ec is not None else 0.0
                    cur_ph_m = self.hw.pv_ph if self.hw.pv_ph is not None else 0.0
                    self.status_msg = f"{stage_prefix}Mixing (Loop {loop_idx}): {rem_m:.0f}s left (EC={cur_ec_m:.3f}, pH={cur_ph_m:.2f})..."
                    time.sleep(0.5)

                if self.stop_event.is_set():
                    return False

                # After 30s mixing completes, check final live EC and pH
                cur_ec_after = round(self.hw.pv_ec, 3) if self.hw.pv_ec is not None else 0.0
                cur_ph_after = round(self.hw.pv_ph, 2) if self.hw.pv_ph is not None else 0.0
                ec_ok = (ec_min <= cur_ec_after <= ec_max)
                ph_ok = (ph_min <= cur_ph_after <= ph_max)

                if ec_ok and ph_ok:
                    target_reached = True
                    break

                # Progress evaluation after 30s mixing:
                # 1. EC must go UP by at least +0.2 each loop if EC is below ec_min
                ec_step = cur_ec_after - prev_loop_ec
                ec_progress = False
                if prev_loop_ec < ec_min:
                    if ec_step >= 0.2:
                        ec_progress = True
                else:
                    ec_progress = True

                # 2. pH can go +0.2 (if pH Up needed) or -0.2 (if pH Down needed)
                ph_progress = False
                ph_step = cur_ph_after - prev_loop_ph
                if prev_loop_ph > ph_max:
                    # pH Down needed -> pH must decrease by at least 0.2 (-0.2 or lower)
                    if (prev_loop_ph - cur_ph_after) >= 0.2:
                        ph_progress = True
                elif prev_loop_ph < ph_min:
                    # pH Up needed -> pH must increase by at least 0.2 (+0.2 or higher)
                    if (cur_ph_after - prev_loop_ph) >= 0.2:
                        ph_progress = True
                else:
                    ph_progress = True

                # If values progressed in the needed direction (EC up >= 0.2 or pH +/- >= 0.2):
                if ec_progress or ph_progress:
                    stagnant_loops = 0
                    print(f"[FERTIGATION PROGRESS] Loop {loop_idx}: Values progressing (EC step={ec_step:+.3f}, pH step={ph_step:+.2f}). Keeping Ch 7, 8, 9, 10 ON.")
                else:
                    stagnant_loops += 1
                    print(f"[FERTIGATION STAGNANT] Loop {loop_idx}: No progress (EC step={ec_step:+.3f} < +0.2, pH step={ph_step:+.2f}). Stagnant Count={stagnant_loops}/3")

                # Update previous loop reference for next iteration
                prev_loop_ec = cur_ec_after
                prev_loop_ph = cur_ph_after

                if stagnant_loops >= 3:
                    # 3 consecutive loops with no progress: SHUT DOWN ALL RELAYS
                    self.state = "DELIVERY BLOCKED: STAGNANT (3 LOOPS)"
                    self.status_msg = f"⚠ Fertigation Aborted! Values stagnant for 3 loops (EC didn't increase >= 0.2 or pH didn't change >= 0.2). All relays OFF."
                    print(f"[FERTIGATION STOPPED] {self.status_msg}")
                    self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
                    self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
                    self.hw.set_relay(ActuatorMap.PH_DOWN_VALVE, False)
                    self.hw.set_relay(ActuatorMap.PH_UP_VALVE, False)
                    self.hw.set_relay(ActuatorMap.MAIN_PUMP, False)
                    self.hw.set_relay(ActuatorMap.PUMP_OUTLET_VALVE, False)
                    self.hw.set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, False)
                    self.hw.set_relay(ActuatorMap.TANK_RETURN_VALVE, False)
                    self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
                    self.hw.set_relay(ActuatorMap.ZONE_1_VALVE, False)
                    self.hw.set_relay(ActuatorMap.ZONE_2_VALVE, False)
                    return False

        else:

            self.status_msg = f"{stage_prefix}Live values already match setpoints (EC={cur_ec:.3f}, pH={cur_ph:.2f}). Starting Main Pump..."
            self.hw.set_relay(ActuatorMap.MAIN_PUMP, True)
            time.sleep(0.5)
            self.hw.set_relay(ActuatorMap.PUMP_OUTLET_VALVE, True)
            time.sleep(0.5)

        # STRICT HARD SAFETY GATE: Verify final live EC and pH strictly match required setpoint range!
        final_ec = round(self.hw.pv_ec, 3) if self.hw.pv_ec is not None else None
        final_ph = round(self.hw.pv_ph, 2) if self.hw.pv_ph is not None else None

        if final_ec is None or final_ph is None or getattr(self.hw, "sensor_error", False):
            self.state = "DELIVERY BLOCKED: SENSOR ERROR"
            self.status_msg = "⚠ Field delivery blocked: Sensor communication lost after mixing! SV 11, 12, 13 kept OFF."
            print(f"[FERTIGATION BLOCKED] {self.status_msg}")
            self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
            self.hw.set_relay(ActuatorMap.ZONE_1_VALVE, False)
            self.hw.set_relay(ActuatorMap.ZONE_2_VALVE, False)
            return False

        ec_ok = (ec_min <= final_ec <= ec_max)
        ph_ok = (ph_min <= final_ph <= ph_max)

        if not ec_ok or not ph_ok:
            fail_reasons = []
            if not ec_ok:
                fail_reasons.append(f"EC={final_ec:.2f} mS/cm (Req {ec_min:.2f}..{ec_max:.2f})")
            if not ph_ok:
                fail_reasons.append(f"pH={final_ph:.2f} (Req {ph_min:.2f}..{ph_max:.2f})")
            self.state = "DELIVERY BLOCKED: UNMATCHED VALUES"
            self.status_msg = f"⚠ Field delivery blocked! {', '.join(fail_reasons)} not matching required setpoints! SV 11, 12, 13 kept OFF."
            print(f"[FERTIGATION BLOCKED] {self.status_msg}")
            self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
            self.hw.set_relay(ActuatorMap.ZONE_1_VALVE, False)
            self.hw.set_relay(ActuatorMap.ZONE_2_VALVE, False)
            return False

        if target_zones:
            zone_names = " & ".join([f"Zone {z - 11} (Room {z - 11})" for z in target_zones])
            self.state = f"{stage_prefix}DELIVERING"

            self.hw.set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, False)

            self.hw.set_relay(ActuatorMap.TANK_RETURN_VALVE, False)

            self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, True)

            for z_pin in [ActuatorMap.ZONE_1_VALVE, ActuatorMap.ZONE_2_VALVE]:
                if z_pin in target_zones:
                    self.hw.set_relay(z_pin, True)
                else:
                    self.hw.set_relay(z_pin, False)

            self.hw.set_relay(ActuatorMap.MAIN_PUMP, True)
            self.hw.set_relay(ActuatorMap.PUMP_OUTLET_VALVE, True)

            self.status_msg = f"{stage_prefix}Delivering nutrient solution to {zone_names} (Ch 11, Ch {', '.join([str(z) for z in target_zones])} ON; Ch 10 OFF)..."

            deliv_start = time.time()
            deliv_dur = max(5.0, float(recipe.get("on_min", 5.0)) * 60.0)
            while time.time() - deliv_start < deliv_dur and not self.stop_event.is_set():
                rem_del = max(0.0, deliv_dur - (time.time() - deliv_start))
                self.status_msg = f"{stage_prefix}Delivering to {zone_names}: {rem_del:.0f}s left..."
                time.sleep(0.5)

            self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
            for z_pin in target_zones:
                self.hw.set_relay(z_pin, False)

        return True

    def _run_loop(self):
        crop_k = self.active_recipe_key
        try:
            if self.delivery_target == "sequential":

                rec_z1 = get_zone_recipe(crop_k, "zone_1")
                ok1 = self._execute_single_batch(rec_z1, target_zones=[ActuatorMap.ZONE_1_VALVE], stage_prefix="[Room 1] ")
                if ok1 and not self.stop_event.is_set():
                    self.state = "[Refill] PREPARING ROOM 2"
                    self.status_msg = "Batch 1 (Room 1) Delivered! Waiting for solution before Room 2 batch..."
                    time.sleep(3.0)

                    rec_z2 = get_zone_recipe(crop_k, "zone_2")
                    self._execute_single_batch(rec_z2, target_zones=[ActuatorMap.ZONE_2_VALVE], stage_prefix="[Room 2] ")
            elif self.delivery_target == "zone_1":
                rec_z1 = get_zone_recipe(crop_k, "zone_1")
                self._execute_single_batch(rec_z1, target_zones=[ActuatorMap.ZONE_1_VALVE], stage_prefix="[Room 1] ")
            elif self.delivery_target == "zone_2":
                rec_z2 = get_zone_recipe(crop_k, "zone_2")
                self._execute_single_batch(rec_z2, target_zones=[ActuatorMap.ZONE_2_VALVE], stage_prefix="[Room 2] ")
            else:
                rec_both = get_zone_recipe(crop_k, "both")
                self._execute_single_batch(rec_both, target_zones=[ActuatorMap.ZONE_1_VALVE, ActuatorMap.ZONE_2_VALVE], stage_prefix="[Common Rooms 1 & 2] ")

            self.hw.set_relay(ActuatorMap.EC_VALVE_1, False)
            self.hw.set_relay(ActuatorMap.EC_VALVE_2, False)
            self.hw.set_relay(ActuatorMap.PH_DOWN_VALVE, False)
            self.hw.set_relay(ActuatorMap.PH_UP_VALVE, False)
            self.hw.set_relay(ActuatorMap.ZONE_1_VALVE, False)
            self.hw.set_relay(ActuatorMap.ZONE_2_VALVE, False)
            self.hw.set_relay(ActuatorMap.IRRIGATION_MASTER_VALVE, False)
            self.hw.set_relay(ActuatorMap.FERTIGATION_LOOP_VALVE, False)
            self.hw.set_relay(ActuatorMap.TANK_RETURN_VALVE, False)
            self.hw.set_relay(ActuatorMap.PUMP_OUTLET_VALVE, False)
            self.hw.set_relay(ActuatorMap.MAIN_PUMP, False)

            if not self.stop_event.is_set():
                if "BLOCKED" in self.state or "TIMEOUT" in self.state or "ERROR" in self.state:
                    pass
                else:
                    self.state = "COMPLETED"
                    self.status_msg = f"✔ Fertigation Complete. Target reached and delivered. Main Pump OFF."
            else:
                self.state = "STOPPED"
                self.status_msg = "Fertigation Cycle Aborted by User."

        except Exception as err:
            self.hw.emergency_all_off()
            self.state = "ERROR"
            self.status_msg = f"Error during fertigation sequence: {err}"
        finally:
            self.last_cycle_finish_time = time.time()
            self.is_running = False
            self.active_venturis = {1: False, 2: False, 3: False, 4: False}
            self.hw.set_relay(ActuatorMap.MAIN_PUMP, False)

engine = FertigationAutomationEngine(hw)

keypad_modal = None

def add_logo(parent):
    try:
        if PIL_AVAILABLE and os.path.exists(LOGO_PATH):
            img = Image.open(LOGO_PATH)
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
        try: root_window = app
        except Exception: root_window = None
    if root_window is None:
        root_window = tk._default_root

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
        try: root_window = app
        except Exception: root_window = None
    if root_window is None:
        root_window = tk._default_root

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
    kp_actions_frame.pack(pady=8)

    btn_act_w = 11
    btn_act_font = ("Helvetica", 12, "bold")

    tk.Button(kp_actions_frame, text="DEL", font=btn_act_font, bg="#f97316", fg="white", width=btn_act_w, height=1, cursor="hand2", relief="raised", bd=1, command=kp_back).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CLEAR", font=btn_act_font, bg="#dc2626", fg="white", width=btn_act_w, height=1, cursor="hand2", relief="raised", bd=1, command=kp_clear).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="SAVE", font=btn_act_font, bg="#2e7d32", fg="white", width=btn_act_w, height=1, cursor="hand2", relief="raised", bd=1, command=kp_confirm).pack(side="left", padx=6)
    tk.Button(kp_actions_frame, text="CANCEL", font=btn_act_font, bg="#64748b", fg="white", width=btn_act_w, height=1, cursor="hand2", relief="raised", bd=1, command=kp_cancel).pack(side="left", padx=6)

open_keypad = open_almora_keypad

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
    except Exception:
        pass
    try:
        res = subprocess.run(['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show', '--active'], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            for line in res.stdout.strip().split('\n'):
                if ':802-11-wireless' in line or ':wifi' in line:
                    return line.split(':')[0]
    except Exception:
        pass
    try:
        res = subprocess.run(['iwgetid', '-r'], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None

def get_system_ip_summary():
    try:
        res = subprocess.run(['hostname', '-I'], capture_output=True, text=True)
        ips = res.stdout.strip()
        return ips if ips else "127.0.0.1"
    except Exception:
        return "Unknown"

def get_bluetooth_live_status() -> str:
    try:
        curr_ssid = get_connected_wifi_ssid()
        wifi_str = f"CONNECTED ({curr_ssid})" if curr_ssid else "DISCONNECTED"
        lines = [
            f"INHYDRO FERTIGATION & CYCLIC IRRIGATION CONTROLLER",

            f"Timestamp: {time.strftime('%d-%m-%Y %H:%M:%S')}",
            f"WiFi Status: {wifi_str}",

            "",
            "[LIVE TANK SENSORS]",
            f"  EC        : {f'{hw.pv_ec:.2f} mS/cm' if (hw.pv_ec is not None and not getattr(hw, 'sensor_error', False)) else 'Sensor Error / Offline'}",
            f"  pH        : {f'{hw.pv_ph:.2f}' if (hw.pv_ph is not None and not getattr(hw, 'sensor_error', False)) else 'Sensor Error / Offline'}",
            f"  Water Temp: {f'{hw.pv_water_temp:.1f} °C' if (hw.pv_water_temp is not None and not getattr(hw, 'sensor_error', False)) else 'Sensor Error / Offline'}",
            "",
            "[FERTIGATION STATE]",
            f"  Running : {'YES' if engine.is_running else 'NO (IDLE)'}",
            f"  Phase   : {engine.state}",
            f"  Crop    : {getattr(active_app_instance, 'var_recipe', tk.StringVar(value='cucumber')).get() if active_app_instance else 'Cucumber'}",
            "",
            "[CYCLIC IRRIGATION TIMERS]",
            f"  Zone 1: State={irrigation_engine.timer_states.get('zone_1', {}).get('state', 'OFF')} (Rem: {irrigation_engine.timer_states.get('zone_1', {}).get('time_left', 0):.0f}s)",
            f"  Zone 2: State={irrigation_engine.timer_states.get('zone_2', {}).get('state', 'OFF')} (Rem: {irrigation_engine.timer_states.get('zone_2', {}).get('time_left', 0):.0f}s)",
            "",
            "[Status]",
            f"  Dosing    : EC1={'ON' if hw.get_relay(1) else 'OFF'}, EC2={'ON' if hw.get_relay(2) else 'OFF'}, pH Down={'ON' if hw.get_relay(3) else 'OFF'}, pH Up={'ON' if hw.get_relay(4) else 'OFF'}",
            f"  Pumps/Loop: Spare={'ON' if hw.get_relay(5) else 'OFF'}, RO Pump={'ON' if hw.get_relay(6) else 'OFF'}, Return={'ON' if hw.get_relay(7) else 'OFF'}, Main Pump={'ON' if hw.get_relay(8) else 'OFF'}, Outlet={'ON' if hw.get_relay(9) else 'OFF'}",
            f"  Valves  : Fert Loop={'ON' if hw.get_relay(10) else 'OFF'}, Master={'ON' if hw.get_relay(11) else 'OFF'}, Zone 1={'ON' if hw.get_relay(12) else 'OFF'}, Zone 2={'ON' if hw.get_relay(13) else 'OFF'}",

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
                    "ssid": curr_ssid or "",
                    "ip": ip_addr,
                    "device": DEVICE_NAME
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
                return json.dumps({"status": "success", "message": "Setpoints saved to JSON & synced"}) + "\r\n"

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
        return f"\r\n[PONG] InHydro Fertigation Controller ({DEVICE_NAME}) is Online & Ready!\r\n\r\n"

    elif txt_upper in ["WIFI", "WIFISTATUS", "CURRENTWIFI", "CHECKWIFI", "6", "WIFI?"]:
        curr_ssid = get_connected_wifi_ssid()
        ip_addr = get_system_ip_summary()
        if curr_ssid:
            resp = (
                "\r\n--- WI-FI CONNECTIVITY STATUS ---\r\n"
                "STATUS     : CONNECTED\r\n"
                f"NETWORK    : {curr_ssid}\r\n"

            )
        else:
            resp = (
                "\r\n--- WI-FI CONNECTIVITY STATUS ---\r\n"
                "STATUS     : Not Connected\r\n"
                "Note       : Send 'SCAN' or '1' to search networks,\r\n"
                "             or 'WIFI:SSID:PASSWORD' to connect.\r\n"

            )
        return resp

    elif txt_upper in ["HELP", "5", "?", "MENU"]:
        return (
            "\r\n--- INHYDRO CONTROLLER COMMAND MENU ---\r\n"
            "1. SCAN\r\n"
            "2. WIFI:SSID:PASSWORD\r\n"
            "3. STATUS\r\n"
            "4. PING\r\n"
            "5. HELP\r\n"

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
            f"\r\n  INHYDRO FERTIGATION & CYCLIC IRRIGATION CONTROLLER  \r\n"

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
                        f"\r\n  INHYDRO FERTIGATION & CYCLIC IRRIGATION CONTROLLER  \r\n"

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
                except Exception:
                    pass
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
        time.sleep(4)

def network_watchdog():
    consecutive_failures = 0
    time.sleep(10)
    while running:
        time.sleep(12)
        if not running: break
        wifi_connected = False
        try:
            dev_out = subprocess.check_output(['nmcli', '-t', '-f', 'TYPE,STATE', 'dev'], text=True, timeout=5)
            for line in dev_out.splitlines():
                parts = line.strip().split(':')
                if len(parts) >= 2 and parts[0] == 'wifi' and parts[1] == 'connected':
                    wifi_connected = True
                    break
        except Exception: pass

        saved_conns = []
        try:
            out = subprocess.check_output(['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show'], text=True, timeout=5)
            for line in out.splitlines():
                if ':802-11-wireless' in line:
                    saved_conns.append(line.split(':')[0].strip())
        except Exception: pass

        if not wifi_connected or consecutive_failures >= 2:
            reconnected = False
            for cname in saved_conns:
                try:
                    res_up = subprocess.run(["nmcli", "connection", "up", "id", cname], capture_output=True, text=True, timeout=12)
                    if res_up.returncode == 0:
                        reconnected = True
                        consecutive_failures = 0
                        break
                except Exception: pass
            if not reconnected:
                consecutive_failures += 1

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
            "active_crop": getattr(active_app_instance, "var_recipe", tk.StringVar(value="cucumber")).get() if active_app_instance else "cucumber",
            "delivery_zone": getattr(active_app_instance, "var_fert_delivery_zone", tk.StringVar(value="both")).get() if active_app_instance else "both"
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
                    active_app_instance.after(500, active_app_instance.restart_application)
            elif action in ["start_fertigation", "start_fert"]:
                crop = str(new_data.get("crop", getattr(active_app_instance, "var_recipe", tk.StringVar(value="cucumber")).get() if active_app_instance else "cucumber")).lower()
                z_target = str(new_data.get("delivery_target", "both")).lower()
                engine.start_cycle(crop, delivery_target=z_target)
            elif action in ["stop_fertigation", "stop_fert", "abort_fert"]:
                engine.stop_cycle()
            elif action in ["start_zone_1", "start_z1"]:
                irrigation_engine.start_zone("zone_1")
            elif action in ["stop_zone_1", "stop_z1"]:
                irrigation_engine.stop_zone("zone_1")
            elif action in ["start_zone_2", "start_z2"]:
                irrigation_engine.start_zone("zone_2")
            elif action in ["stop_zone_2", "stop_z2"]:
                irrigation_engine.stop_zone("zone_2")
            elif action in ["stop_all_irrigation", "stop_irrigation"]:
                irrigation_engine.stop_irrigation()
            elif action == "relay_toggle":
                ch = int(new_data.get("channel", 0))
                st = bool(new_data.get("state", False))
                if 1 <= ch <= 13:
                    if ch in [ActuatorMap.ZONE_1_VALVE, ActuatorMap.ZONE_2_VALVE, ActuatorMap.RO_WATER_PUMP, ActuatorMap.IRRIGATION_MASTER_VALVE] and st:
                        if engine.is_running:
                            engine.stop_cycle()
                            hw.set_relay(ActuatorMap.EC_VALVE_1, False)
                            hw.set_relay(ActuatorMap.EC_VALVE_2, False)
                            hw.set_relay(ActuatorMap.PH_DOWN_VALVE, False)
                            hw.set_relay(ActuatorMap.PH_UP_VALVE, False)
                            hw.set_relay(ActuatorMap.TANK_RETURN_VALVE, False)
                            hw.set_relay(ActuatorMap.PUMP_OUTLET_VALVE, False)
                            engine.active_venturis = {1: False, 2: False, 3: False, 4: False}
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
            elif "zone_1" in new_data or "zone_2" in new_data:
                if "zone_1" in new_data and isinstance(new_data["zone_1"], dict):
                    cyclic_timer_cfg["zone_1"].update(new_data["zone_1"])
                    updated_timers = True
                if "zone_2" in new_data and isinstance(new_data["zone_2"], dict):
                    cyclic_timer_cfg["zone_2"].update(new_data["zone_2"])
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
        print(f"[MQTT] Connected & subscribed to private broker for {DEVICE_NAME}")
        broadcast_current_state()
    else:
        is_mqtt_connected = False

def on_control_disconnect(client, userdata, *args, **kwargs):
    global is_mqtt_connected
    is_mqtt_connected = False
    print("[MQTT] Disconnected from broker. Auto-reconnecting in background...")

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
        print(f"[MQTT] Private broker client loop started for {DEVICE_NAME}")
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
    time.sleep(4)
    while running:
        try:
            time.sleep(3)
            if not running: break
            if control_client and control_client.is_connected():
                telemetry = {
                    "source": "device",
                    "device": DEVICE_NAME,
                    "device_id": DEVICE_NAME,
                    "timestamp": datetime.datetime.now().isoformat(),
                    "ec": round(hw.pv_ec, 2) if (hw.pv_ec is not None and not getattr(hw, "sensor_error", False)) else None,
                    "ph": round(hw.pv_ph, 2) if (hw.pv_ph is not None and not getattr(hw, "sensor_error", False)) else None,
                    "water_temp": round(hw.pv_water_temp, 1) if (hw.pv_water_temp is not None and not getattr(hw, "sensor_error", False)) else None,
                    "sensor_online": not getattr(hw, "sensor_error", False),
                    "fertigation": {
                        "is_running": engine.is_running,
                        "phase": engine.state,
                        "log": engine.status_msg,
                        "crop": getattr(active_app_instance, "var_recipe", tk.StringVar(value="cucumber")).get() if active_app_instance else "cucumber",
                        "delivery_target": getattr(active_app_instance, "var_fert_delivery_zone", tk.StringVar(value="both")).get() if active_app_instance else "both"
                    },
                    "irrigation": {
                        "is_running": any(irrigation_engine.timer_states.get(z, {}).get("state") == "ON" for z in ["zone_1", "zone_2"]),
                        "zone_1": irrigation_engine.timer_states.get("zone_1", {}),
                        "zone_2": irrigation_engine.timer_states.get("zone_2", {})
                    },
                    "relays": {
                        f"ch_{ch}": hw.get_relay(ch) for ch in range(1, 14)
                    }
                }
                msg_str = json.dumps(telemetry)
                control_client.publish(f"inhydro/{DEVICE_NAME}/telemetry", msg_str, retain=False)
                control_client.publish(f"inhydro/{DEVICE_NAME.lower()}/telemetry", msg_str, retain=False)
        except Exception:
            pass

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
            "font": ("Helvetica", 13, "bold"),
            "bg": "#f1f5f9",
            "fg": "#0f172a",
            "activebackground": "#cbd5e1",
            "activeforeground": "#0f172a",
            "bd": 2,
            "relief": "groove",
            "padx": 14,
            "pady": 6,
            "cursor": "hand2",
            "command": self.toggle
        }
        if btn_width:
            btn_kw["width"] = btn_width

        self.btn = tk.Button(parent, **btn_kw)

        self.menu_frame = tk.Frame(
            self.root,
            bg="white",
            bd=2,
            relief="solid",
            highlightbackground="#1565c0",
            highlightthickness=2,
            padx=6,
            pady=6
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
            try:
                self.root._active_grid_dropdown.close()
            except Exception:
                pass
        self.root._active_grid_dropdown = self

        for w in self.menu_frame.winfo_children():
            w.destroy()

        effective_cols = self.cols
        if len(self.values) <= 4 and self.cols > 2:
            effective_cols = 2
        effective_cols = min(effective_cols, len(self.values)) if self.values else 1

        curr_val = self.var.get()
        display_texts = [self.display_map.get(v, str(v).replace("_", " ").title()) for v in self.values]
        longest_len = max(len(t) for t in display_texts) if display_texts else 10

        col_w = max(115, min(220, longest_len * 9 + 30))
        menu_w = col_w * effective_cols + 16

        for idx, val in enumerate(self.values):
            r = idx // effective_cols
            c = idx % effective_cols
            disp = self.display_map.get(val, str(val).replace("_", " ").title())
            is_active = (str(val).lower() == str(curr_val).lower())

            btn_bg = "#1565c0" if is_active else "#f8fafc"
            btn_fg = "white" if is_active else "#1e293b"
            active_bg = "#0d47a1" if is_active else "#e2e8f0"
            prefix = "✔  " if is_active else ""

            b = tk.Button(
                self.menu_frame,
                text=f"{prefix}{disp}",
                font=("Helvetica", 11, "bold"),
                wraplength=col_w - 12,
                justify="center",
                bg=btn_bg,
                fg=btn_fg,
                activebackground=active_bg,
                activeforeground=btn_fg,
                bd=1,
                relief="raised",
                padx=6,
                pady=6,
                cursor="hand2",
                command=lambda v=val: self._select(v)
            )
            b.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")

        for c in range(effective_cols):
            self.menu_frame.columnconfigure(c, weight=1, minsize=col_w, uniform="gcol")

        self.root.update_idletasks()
        bx = self.btn.winfo_rootx() - self.root.winfo_rootx()
        by = self.btn.winfo_rooty() - self.root.winfo_rooty() + self.btn.winfo_height() + 2

        if bx + menu_w > 1000:
            bx = max(10, 1000 - menu_w)

        self.menu_frame.place(x=bx, y=by, width=menu_w)
        self.menu_frame.lift()
        self.btn.config(bg="#e2e8f0")
        self.is_open = True

    def close(self):
        self.menu_frame.place_forget()
        self.btn.config(bg="#f1f5f9")
        self.is_open = False
        if getattr(self.root, "_active_grid_dropdown", None) == self:
            self.root._active_grid_dropdown = None

    def _select(self, val):
        self.var.set(val)
        self.update_label()
        self.close()
        if self.on_select:
            self.on_select()

class InHydroFertigationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("INHYDRO - 5-Venturi Fertigation & Irrigation Controller")
        self.geometry("1024x600")
        self.minsize(800, 480)
        self.configure(bg="white")

        try:
            self.attributes("-fullscreen", True)
        except Exception:
            pass

        self.COLOR_BG = "white"
        self.COLOR_CARD_BG = "#f8fafc"
        self.COLOR_PRIMARY = "#1565c0"
        self.COLOR_ACCENT = "#0284c7"
        self.COLOR_TEXT_MAIN = "#0f172a"
        self.COLOR_TEXT_SUB = "#475569"
        self.COLOR_SUCCESS = "#16a34a"
        self.COLOR_OFF = "#64748b"
        self.COLOR_DANGER = "#dc2626"

        self.font_title = font.Font(family="Helvetica", size=15, weight="bold")
        self.font_h2 = font.Font(family="Helvetica", size=13, weight="bold")
        self.font_body = font.Font(family="Helvetica", size=11)
        self.font_body_bold = font.Font(family="Helvetica", size=11, weight="bold")
        self.font_sub = font.Font(family="Helvetica", size=10)
        self.font_sub_bold = font.Font(family="Helvetica", size=10, weight="bold")
        self.font_val_big = font.Font(family="Helvetica", size=22, weight="bold")

        style = ttk.Style()
        try: style.theme_use('clam')
        except Exception: pass
        style.configure('TCombobox', font=('Helvetica', 14, 'bold'), padding=8)
        self.option_add('*TCombobox*Listbox.font', ('Helvetica', 14, 'bold'))
        self.option_add('*TCombobox*Listbox.selectBackground', '#1565c0')
        self.option_add('*TCombobox*Listbox.selectForeground', 'white')

        self.logo_img = None
        self._load_logo()

        self._active_grid_dropdown = None
        fresh_cfg = load_json(CONFIG_FILE, DEFAULT_CONFIG)
        saved_crop = fresh_cfg.get("active_crop", "cucumber")
        self.var_recipe = tk.StringVar(value=saved_crop)
        saved_zone = fresh_cfg.get("selected_fert_zone", "both")
        self.var_fert_delivery_zone = tk.StringVar(value=saved_zone)
        self.var_auto_fertigation = tk.BooleanVar(value=True)
        self.fert_last_cycle_time = {"both": 0.0, "zone_1": 0.0, "zone_2": 0.0}
        self.fert_cyclic_status_msg = ""
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

        self.show_screen("dashboard")

        def _on_click_outside_dropdowns(event):
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

        self.bind("<Button-1>", _on_click_outside_dropdowns, add="+")

        self.bind("<Escape>", lambda e: self.exit_application())
        self.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.bind("<Home>", lambda e: self.show_screen("dashboard"))

        global active_app_instance
        active_app_instance = self

        self.after(100, self._periodic_tick)

    def sync_ui_from_cloud(self):
        try:
            if hasattr(self, "dd_fert_crop"):
                self.dd_fert_crop.values = list(crop_recipes.keys())
                self.dd_fert_crop.display_map = {k: crop_recipes[k].get("crop_name", k.title()) for k in crop_recipes}
                self.dd_fert_crop.update_label()
            if hasattr(self, "dd_set_crop"):
                self.dd_set_crop.values = list(crop_recipes.keys())
                self.dd_set_crop.display_map = {k: crop_recipes[k].get("crop_name", k.title()) for k in crop_recipes}
                self.dd_set_crop.update_label()

            self._load_recipe_into_fert_screen()
            if hasattr(self, "_load_crop_into_settings_tab"):
                self._load_crop_into_settings_tab()

            if hasattr(self, "lbl_t_z1_start"):
                z1_cfg = cyclic_timer_cfg.get("zone_1", {})
                z2_cfg = cyclic_timer_cfg.get("zone_2", {})
                self.lbl_t_z1_name.config(text=str(z1_cfg.get("name", "Zone 1 Drip Line")))
                self.var_z1_en.set(z1_cfg.get("enabled", True))
                self.lbl_t_z1_start.config(text=str(z1_cfg.get("start_time", "06:00")))
                self.lbl_t_z1_stop.config(text=str(z1_cfg.get("stop_time", "18:00")))
                self.lbl_t_z1_on.config(text=str(z1_cfg.get("on_min", 5.0)))
                self.lbl_t_z1_off.config(text=str(z1_cfg.get("off_min", 15.0)))

                self.lbl_t_z2_name.config(text=str(z2_cfg.get("name", "Zone 2 Drip Line")))
                self.var_z2_en.set(z2_cfg.get("enabled", True))
                self.lbl_t_z2_start.config(text=str(z2_cfg.get("start_time", "06:00")))
                self.lbl_t_z2_stop.config(text=str(z2_cfg.get("stop_time", "18:00")))
                self.lbl_t_z2_on.config(text=str(z2_cfg.get("on_min", 5.0)))
                self.lbl_t_z2_off.config(text=str(z2_cfg.get("off_min", 15.0)))
            print("[CLOUD SYNC] Local UI refreshed with newly received cloud setpoints.")
        except Exception as e:
            print(f"[UI SYNC ERROR] {e}")

    def _load_logo(self):
        if PIL_AVAILABLE and os.path.exists(LOGO_PATH):
            try:
                img = Image.open(LOGO_PATH)
                img.thumbnail((120, 36), Image.Resampling.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(img)
            except Exception:
                pass

    def toggle_fullscreen(self):
        cur = self.attributes("-fullscreen")
        self.attributes("-fullscreen", not cur)

    def exit_application(self):
        if messagebox.askyesno("Exit Application", "Exit InHydro Controller? All relays will be turned OFF."):
            hw.emergency_all_off()
            engine.stop_cycle()
            irrigation_engine.stop_irrigation()
            self.destroy()
            sys.exit(0)

    def restart_application(self):
        hw.emergency_all_off()
        engine.stop_cycle()
        irrigation_engine.stop_irrigation()
        try:
            if hasattr(self, "var_fert_delivery_zone"):
                system_config["selected_fert_zone"] = self.var_fert_delivery_zone.get()
            if hasattr(self, "var_recipe"):
                system_config["active_crop"] = self.var_recipe.get()
            save_json(CONFIG_FILE, system_config)
            save_json(CONFIG_FALLBACK_FILE, system_config)
        except Exception as e:
            print(f"[RESTART] Failed saving state before restart: {e}")
        try:
            self.destroy()
        except Exception:
            pass
        python = sys.executable
        os.execv(python, [python] + sys.argv)

    PAGE_SEQUENCE = ["dashboard", "monitoring", "fertigation", "irrigation", "settings"]

    PAGE_DISPLAY_NAMES = {
        "dashboard":   "DASHBOARD",
        "monitoring":  "LIVE MONITORING",
        "fertigation": "FERTIGATION",
        "irrigation":  "CYCLIC IRRIGATION",
        "settings":    "SETTINGS & SAFETY",
    }

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
            h,
            text="INHYDRO FERTIGATION & CYCLIC IRRIGATION SYSTEM",
            font=("Helvetica", 16, "bold"),
            fg="#1565c0",
            bg="white"
        )
        lbl_title.place(relx=0.5, rely=0.5, anchor="center")

        if self.logo_img:
            lbl_logo = tk.Label(h, image=self.logo_img, bg="white")
            lbl_logo.place(relx=1.0, rely=0.5, anchor="e", x=-16)
        else:
            lbl_logo = tk.Label(h, text="INHYDRO", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="white")
            lbl_logo.place(relx=1.0, rely=0.5, anchor="e", x=-16)

    def _build_bottom_dock(self):
        self.dock = tk.Frame(self, bg="#eeeeee", height=60, bd=1, relief="solid", padx=12)
        self.dock.pack(fill="x", side="bottom")
        self.dock.pack_propagate(False)

        self.btn_dock_restart = tk.Button(
            self.dock, text="🔄 RESTART ", font=("Helvetica", 13, "bold"),
            bg="#1565c0", fg="white", activebackground="#0d47a1", activeforeground="white",
            bd=2, relief="raised", padx=28, pady=6, cursor="hand2",
            command=self.restart_application
        )
        self.dock_nav_frame = tk.Frame(self.dock, bg="#eeeeee")

        self.btn_dock_prev = tk.Button(
            self.dock_nav_frame, text="◀ PREV", font=("Helvetica", 13, "bold"),
            bg="#475569", fg="white", activebackground="#334155", activeforeground="white",
            bd=2, relief="raised", padx=20, pady=6, cursor="hand2",
            command=self.prev_screen
        )

        self.btn_dock_dash = tk.Button(
            self.dock_nav_frame, text="🏠 DASHBOARD", font=("Helvetica", 13, "bold"),
            bg="#0891b2", fg="white", activebackground="#0e7490", activeforeground="white",
            bd=2, relief="raised", padx=24, pady=6, cursor="hand2",
            command=lambda: self.show_screen("dashboard")
        )

        self.btn_dock_next = tk.Button(
            self.dock_nav_frame, text="NEXT ▶", font=("Helvetica", 13, "bold"),
            bg="#1565c0", fg="white", activebackground="#0d47a1", activeforeground="white",
            bd=2, relief="raised", padx=20, pady=6, cursor="hand2",
            command=self.next_screen
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
            try:
                self._active_grid_dropdown.close()
            except Exception:
                pass

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
            if hasattr(self, "_load_crop_into_settings_tab"):
                self._load_crop_into_settings_tab()

    def _create_dashboard_screen(self, parent):
        f = tk.Frame(parent, bg="white")

        grid_frame = tk.Frame(f, bg="white")
        grid_frame.pack(fill="both", expand=True, padx=10, pady=8)

        for i in range(2):
            grid_frame.columnconfigure(i, weight=1, uniform="dash_col")
            grid_frame.rowconfigure(i, weight=1, uniform="dash_row")

        dashboard_modules = [
            ("monitoring",  "LIVE MONITORING"),
            ("fertigation", "FERTIGATION"),
            ("irrigation",  "CYCLIC IRRIGATION"),
            ("settings",    "SETTINGS & SAFETY"),
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

        for idx, (key, title_text) in enumerate(dashboard_modules):
            r = idx // 2
            c = idx % 2

            card = tk.Frame(grid_frame, bg="#1565c0", bd=6, relief="raised", cursor="hand2")
            card.grid(row=r, column=c, padx=10, pady=8, sticky="nsew")

            lbl_name = tk.Label(
                card,
                text=title_text,
                font=("Helvetica", 22, "bold"),
                fg="white",
                bg="#1565c0",
                anchor="center",
                cursor="hand2"
            )
            lbl_name.pack(expand=True, fill="both")

            bind_card_hover_and_click(card, lbl_name, key)

        return f

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

        card_ec = tk.LabelFrame(
            top_live_row, text=" EC VALUE (mS/cm) ", font=("Helvetica", 11, "bold"),
            fg="#1565c0", bg="white", bd=2, relief="groove", padx=12, pady=4
        )
        card_ec.grid(row=0, column=0, padx=4, pady=2, sticky="nsew")
        self.lbl_mon_ec_val = tk.Label(card_ec, text="--", font=("Helvetica", 22, "bold"), fg="#1565c0", bg="white")
        self.lbl_mon_ec_val.pack(anchor="center", pady=1)
        self.lbl_mon_ec_target = tk.Label(card_ec, text="Target: 2.20 mS/cm", font=("Helvetica", 10, "bold"), fg=self.COLOR_TEXT_SUB, bg="white")
        self.lbl_mon_ec_target.pack(anchor="center")

        card_ph = tk.LabelFrame(
            top_live_row, text=" pH VALUE ", font=("Helvetica", 11, "bold"),
            fg="#1565c0", bg="white", bd=2, relief="groove", padx=12, pady=4
        )
        card_ph.grid(row=0, column=1, padx=4, pady=2, sticky="nsew")
        self.lbl_mon_ph_val = tk.Label(card_ph, text="--", font=("Helvetica", 22, "bold"), fg="#0891b2", bg="white")
        self.lbl_mon_ph_val.pack(anchor="center", pady=1)
        self.lbl_mon_ph_target = tk.Label(card_ph, text="Target: 5.80", font=("Helvetica", 10, "bold"), fg=self.COLOR_TEXT_SUB, bg="white")
        self.lbl_mon_ph_target.pack(anchor="center")

        card_temp = tk.LabelFrame(
            top_live_row, text=" WATER TEMPERATURE ", font=("Helvetica", 11, "bold"),
            fg="#1565c0", bg="white", bd=2, relief="groove", padx=12, pady=4
        )
        card_temp.grid(row=0, column=2, padx=4, pady=2, sticky="nsew")
        self.lbl_mon_temp = tk.Label(card_temp, text="--", font=("Helvetica", 22, "bold"), fg="#0f172a", bg="white")
        self.lbl_mon_temp.pack(anchor="center", pady=1)
        tk.Label(card_temp, text="Tank Sensor", font=("Helvetica", 10, "bold"), fg=self.COLOR_TEXT_SUB, bg="white").pack(anchor="center")

        col_relays = tk.LabelFrame(
            center_container,
            text=" 13-CHANNEL HARDWARE RELAYS ",
            font=("Helvetica", 12, "bold"),
            fg="#1565c0",
            bg="white",
            bd=2,
            relief="groove",
            padx=12,
            pady=4
        )
        col_relays.pack(side="top", anchor="center", pady=(3, 2))

        top_info = tk.Frame(col_relays, bg="white")
        top_info.pack(fill="x", pady=(0, 4))
        tk.Label(top_info, text=" STATUS", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="white").pack(side="left")

        def do_all_off():
            if hasattr(self, "var_auto_fertigation") and self.var_auto_fertigation is not None:
                self.var_auto_fertigation.set(False)
                if hasattr(self, "_update_auto_fert_ui") and callable(self._update_auto_fert_ui):
                    self._update_auto_fert_ui()
            engine.stop_cycle()
            irrigation_engine.stop_irrigation()
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
            (1,  0, 0), (2,  0, 1), (3,  0, 2),
            (4,  1, 0), (5,  1, 1), (6,  1, 2),
            (7,  2, 0), (8,  2, 1), (9,  2, 2),
            (10, 3, 0), (11, 3, 1), (12, 3, 2),
            (13, 4, 1)
        ]

        for ch, r_idx, c_idx in ch_order:
            name = ACTUATOR_NAMES.get(ch, f"Relay {ch}")
            card_v = tk.Frame(grid_frame, bg="#f8fafc", bd=1, relief="solid", padx=8, pady=3)
            card_v.grid(row=r_idx, column=c_idx, padx=4, pady=2, sticky="ew")

            tk.Label(card_v, text=name, font=("Helvetica", 10, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc").pack(side="left")

            def make_toggle(target_ch=ch):
                def do_toggle():
                    cur = hw.get_relay(target_ch)
                    new_st = not cur

                    if target_ch in [ActuatorMap.ZONE_1_VALVE, ActuatorMap.ZONE_2_VALVE]:
                        z_k = "zone_1" if target_ch == ActuatorMap.ZONE_1_VALVE else "zone_2"
                        if new_st:

                            if engine.is_running:
                                engine.stop_cycle()
                                hw.set_relay(ActuatorMap.EC_VALVE_1, False)
                                hw.set_relay(ActuatorMap.EC_VALVE_2, False)
                                hw.set_relay(ActuatorMap.PH_DOWN_VALVE, False)
                                hw.set_relay(ActuatorMap.PH_UP_VALVE, False)
                                hw.set_relay(ActuatorMap.TANK_RETURN_VALVE, False)
                                hw.set_relay(ActuatorMap.PUMP_OUTLET_VALVE, False)
                                engine.active_venturis = {1: False, 2: False, 3: False, 4: False}
                            irrigation_engine.start_zone(z_k)
                        else:
                            irrigation_engine.stop_zone(z_k)
                    elif target_ch in [ActuatorMap.RO_WATER_PUMP, ActuatorMap.IRRIGATION_MASTER_VALVE] and new_st:

                        if engine.is_running:
                            engine.stop_cycle()
                            hw.set_relay(ActuatorMap.EC_VALVE_1, False)
                            hw.set_relay(ActuatorMap.EC_VALVE_2, False)
                            hw.set_relay(ActuatorMap.PH_DOWN_VALVE, False)
                            hw.set_relay(ActuatorMap.PH_UP_VALVE, False)
                            hw.set_relay(ActuatorMap.TANK_RETURN_VALVE, False)
                            hw.set_relay(ActuatorMap.PUMP_OUTLET_VALVE, False)
                            engine.active_venturis = {1: False, 2: False, 3: False, 4: False}
                        hw.set_relay(target_ch, True)
                    elif target_ch in [ActuatorMap.EC_VALVE_1, ActuatorMap.EC_VALVE_2, ActuatorMap.PH_DOWN_VALVE, ActuatorMap.PH_UP_VALVE] and new_st:

                        if irrigation_engine.was_irrigating or any(
                            irrigation_engine.timer_states[z]["state"] == "ON" for z in ["zone_1", "zone_2"]
                        ):
                            irrigation_engine.stop_irrigation()
                        hw.set_relay(target_ch, True)
                    elif target_ch == ActuatorMap.RO_WATER_PUMP and not new_st:

                        if irrigation_engine.was_irrigating or any(
                            irrigation_engine.timer_states[z]["state"] == "ON" for z in ["zone_1", "zone_2"]
                        ):
                            irrigation_engine.stop_irrigation()
                        hw.set_relay(target_ch, False)
                    elif target_ch == ActuatorMap.IRRIGATION_MASTER_VALVE and not new_st:

                        if irrigation_engine.was_irrigating or any(
                            irrigation_engine.timer_states[z]["state"] == "ON" for z in ["zone_1", "zone_2"]
                        ):
                            irrigation_engine.stop_irrigation()
                        hw.set_relay(target_ch, False)
                    elif target_ch == ActuatorMap.MAIN_PUMP and not new_st:

                        if engine.is_running:
                            engine.stop_cycle()
                        hw.set_relay(target_ch, False)
                    elif target_ch == ActuatorMap.MAIN_PUMP and new_st:

                        if irrigation_engine.was_irrigating:
                            irrigation_engine.stop_irrigation()
                        hw.set_relay(target_ch, True)
                    elif not new_st and engine.is_running and target_ch in [
                        ActuatorMap.EC_VALVE_1, ActuatorMap.EC_VALVE_2, ActuatorMap.EC_VALVE_3,
                        ActuatorMap.EC_VALVE_4, ActuatorMap.PH_VALVE, ActuatorMap.FERTIGATION_LOOP_VALVE,
                        ActuatorMap.TANK_RETURN_VALVE, ActuatorMap.PUMP_OUTLET_VALVE
                    ]:
                        hw.set_relay(target_ch, False)
                    else:
                        hw.set_relay(target_ch, new_st)

                    for b_ch, b_btn in self.mon_valve_badges.items():
                        st_now = hw.get_relay(b_ch)
                        b_btn.config(
                            text="ON" if st_now else "OFF",
                            bg=self.COLOR_SUCCESS if st_now else self.COLOR_OFF,
                            relief="sunken" if st_now else "raised"
                        )
                return do_toggle

            btn_toggle = tk.Button(
                card_v, text="OFF", font=("Helvetica", 10, "bold"), fg="white", bg=self.COLOR_OFF,
                activebackground="#15803d", activeforeground="white", width=6, relief="raised", bd=1,
                padx=8, pady=2, cursor="hand2", command=make_toggle(ch)
            )
            btn_toggle.pack(side="right")
            self.mon_valve_badges[ch] = btn_toggle

        return f

    def _create_fertigation_screen(self, parent):
        f = tk.Frame(parent, bg="white")

        top_bar = tk.Frame(f, bg="#f8fafc", bd=1, relief="groove", padx=8, pady=3)
        top_bar.pack(fill="x", pady=(0, 2))

        tk.Label(top_bar, text="Select Crop :", font=("Helvetica", 12, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc").pack(side="left", padx=(4, 2))

        recipe_names = list(crop_recipes.keys())

        def on_fert_crop_selected():
            c = self.var_recipe.get()
            system_config["active_crop"] = c
            try:
                save_json(CONFIG_FILE, system_config)
                save_json(CONFIG_FALLBACK_FILE, system_config)
            except Exception as e:
                print(f"[CONFIG] Error saving crop: {e}")
            self._load_recipe_into_fert_screen()
            if hasattr(self, "dd_set_crop"):
                self.dd_set_crop.update_label()
            if hasattr(self, "_load_crop_into_settings_tab"):
                self._load_crop_into_settings_tab()

        self.dd_fert_crop = GridTouchDropdown(
            parent=top_bar,
            root=self,
            var=self.var_recipe,
            values=recipe_names,
            display_map={k: crop_recipes[k].get("crop_name", k.title()) for k in crop_recipes},
            on_select=on_fert_crop_selected,
            cols=3
        )
        self.dd_fert_crop.btn.config(font=("Helvetica", 12, "bold"), padx=10, pady=4)
        self.dd_fert_crop.btn.pack(side="left", padx=4)

        tk.Label(top_bar, text="Delivery Zone :", font=("Helvetica", 12, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc").pack(side="left", padx=(10, 2))
        if not hasattr(self, "var_fert_delivery_zone"):
            self.var_fert_delivery_zone = tk.StringVar(value=system_config.get("selected_fert_zone", "both"))

        def on_fert_zone_selected():
            z = self.var_fert_delivery_zone.get()
            system_config["selected_fert_zone"] = z
            try:
                save_json(CONFIG_FILE, system_config)
                save_json(CONFIG_FALLBACK_FILE, system_config)
            except Exception as e:
                print(f"[CONFIG] Error saving zone: {e}")
            self._load_recipe_into_fert_screen()

        self.dd_fert_delivery = GridTouchDropdown(
            parent=top_bar,
            root=self,
            var=self.var_fert_delivery_zone,
            values=["both", "zone_1", "zone_2", "sequential"],
            display_map={
                "both": "Both Zones (Common)",
                "zone_1": "Zone 1 (Room 1)",
                "zone_2": "Zone 2 (Room 2)",
                "sequential": "Sequential (Z1 ➔ Z2)"
            },
            on_select=on_fert_zone_selected,
            cols=2
        )
        self.dd_fert_delivery.btn.config(font=("Helvetica", 12, "bold"), padx=10, pady=4)
        self.dd_fert_delivery.btn.pack(side="left", padx=4)

        if not hasattr(self, "var_auto_fertigation"):
            self.var_auto_fertigation = tk.BooleanVar(value=True)

        def toggle_auto_fert():
            new_st = not self.var_auto_fertigation.get()
            self.var_auto_fertigation.set(new_st)
            _update_auto_fert_ui()

        def _update_auto_fert_ui():
            if self.var_auto_fertigation.get():
                self.btn_auto_fert.config(
                    text="AUTO FERTIGATION ",
                    bg="#15803d", fg="white",
                    activebackground="#166534", activeforeground="white",
                    relief="sunken"
                )
                if hasattr(self, "btn_start_fert"):
                    self.btn_start_fert.config(
                        text="AUTO ACTIVE (STANDBY)",
                        state="disabled",
                        bg="#64748b", fg="#cbd5e1",
                        cursor="arrow"
                    )
            else:
                self.btn_auto_fert.config(
                    text="MANUAL FERTIGATION ",
                    bg="#fee2e2", fg="#991b1b",
                    activebackground="#fecaca", activeforeground="#7f1d1d",
                    relief="raised"
                )
                if hasattr(self, "btn_start_fert"):
                    self.btn_start_fert.config(
                        text="▶ START FERTIGATION",
                        state="normal",
                        bg="#1565c0", fg="white",
                        activebackground="#0d47a1", activeforeground="white",
                        cursor="hand2"
                    )
        self._update_auto_fert_ui = _update_auto_fert_ui

        self.btn_auto_fert = tk.Button(
            top_bar,
            font=("Helvetica", 13, "bold"),
            bd=2, padx=12, pady=4, cursor="hand2",
            command=toggle_auto_fert
        )
        self.btn_auto_fert.pack(side="right", padx=4)
        _update_auto_fert_ui()

        center_wrap = tk.Frame(f, bg="white")
        center_wrap.pack(anchor="center", pady=1)

        top_card = tk.LabelFrame(
            center_wrap,
            text=" ACTIVE CROP SETPOINTS & MULTI-INJECTOR SYSTEM ",
            font=("Helvetica", 12, "bold"),
            fg="#1565c0",
            bg="white",
            bd=2,
            relief="groove",
            padx=5,
            pady=1
        )
        top_card.pack(fill="x", pady=1)

        sp_frame = tk.LabelFrame(
            top_card,
            text=" ACTIVE CROP TARGET SETPOINTS ",
            font=("Helvetica", 10, "bold"),
            fg="#1e293b",
            bg="#f8fafc",
            bd=1,
            relief="solid",
            padx=3,
            pady=1
        )
        sp_frame.pack(fill="x", pady=(0, 1))

        def make_sp_disp(parent_row, label_text, default_v, val_fg="#1565c0"):
            cell = tk.Frame(parent_row, bg="white", bd=1, relief="solid", padx=3, pady=1)
            cell.pack(side="left", expand=True, fill="x", padx=2)
            tk.Label(cell, text=label_text, font=("Helvetica", 11, "bold"), fg="#475569", bg="white").pack(anchor="w")
            lbl_val = tk.Label(cell, text=str(default_v), font=("Helvetica", 13, "bold"), fg=val_fg, bg="white", justify="center")
            lbl_val.pack(anchor="center")
            return lbl_val

        row1 = tk.Frame(sp_frame, bg="#f8fafc")
        row1.pack(fill="x", pady=0)
        self.lbl_fert_crop_name = make_sp_disp(row1, "Crop Name:", "Cucumber", val_fg="#0f172a")
        self.lbl_fert_ec_min    = make_sp_disp(row1, "EC Min (Start):", "1.80 mS/cm", val_fg="#1565c0")
        self.lbl_fert_ec_max    = make_sp_disp(row1, "EC Max (Stop):", "2.20 mS/cm", val_fg="#1565c0")
        self.lbl_fert_ph_min    = make_sp_disp(row1, "pH Min (Up):", "5.40", val_fg="#0891b2")
        self.lbl_fert_ph_target = make_sp_disp(row1, "pH Target:", "5.80", val_fg="#1565c0")
        self.lbl_fert_ph_max    = make_sp_disp(row1, "pH Max (Down):", "6.40", val_fg="#dc2626")

        row2 = tk.Frame(sp_frame, bg="#f8fafc")
        row2.pack(fill="x", pady=0)
        self.lbl_fert_timer_window = make_sp_disp(row2, "Timer Window:", "06:00 - 18:00", val_fg="#1565c0")
        self.lbl_fert_timer_on     = make_sp_disp(row2, "Delivery (ON):", "5.0 min", val_fg="#0891b2")
        self.lbl_fert_timer_off    = make_sp_disp(row2, "Interval (OFF):", "60.0 min", val_fg="#1565c0")

        v_frame = tk.LabelFrame(
            top_card,
            text=" 4-VENTURI SOLUTION DOSING ENGINE ",
            font=("Helvetica", 10, "bold"),
            fg="#1565c0",
            bg="white",
            bd=1,
            relief="solid",
            padx=3,
            pady=1
        )
        v_frame.pack(fill="x", pady=(1, 0))

        v_grid = tk.Frame(v_frame, bg="white")
        v_grid.pack(fill="x")
        v_grid.columnconfigure(0, weight=4, uniform="vcol")
        v_grid.columnconfigure(1, weight=3, uniform="vcol")
        v_grid.columnconfigure(2, weight=3, uniform="vcol")
        v_grid.columnconfigure(3, weight=2, uniform="vcol")

        vh_bg = "#e2e8f0"
        tk.Label(v_grid, text="Venturi Channel", font=("Helvetica", 11, "bold"), fg="#0f172a", bg=vh_bg, anchor="center").grid(row=0, column=0, sticky="ew", padx=1, pady=0)
        tk.Label(v_grid, text="Dosing Trigger", font=("Helvetica", 11, "bold"), fg="#0f172a", bg=vh_bg, anchor="center").grid(row=0, column=1, sticky="ew", padx=1, pady=0)
        tk.Label(v_grid, text="Target Cutoff", font=("Helvetica", 11, "bold"), fg="#0f172a", bg=vh_bg, anchor="center").grid(row=0, column=2, sticky="ew", padx=1, pady=0)
        tk.Label(v_grid, text=" Status", font=("Helvetica", 11, "bold"), fg="#0f172a", bg=vh_bg, anchor="center").grid(row=0, column=3, sticky="ew", padx=1, pady=0)

        self.labels_fert_v_status = {}
        self.labels_fert_v_safety = {}

        tk.Label(v_grid, text="EC 1 ", font=("Helvetica", 13, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc", anchor="center", bd=1, relief="solid").grid(row=1, column=0, sticky="ew", padx=1, pady=0)
        self.lbl_v1_trig = tk.Label(v_grid, text="EC <= 1.80", font=("Helvetica", 13, "bold"), fg="#1e293b", bg="#f8fafc", anchor="center", bd=1, relief="solid")
        self.lbl_v1_trig.grid(row=1, column=1, sticky="ew", padx=1, pady=0)
        self.lbl_v1_cut = tk.Label(v_grid, text="EC >= 2.20 ", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="#e0f2fe", anchor="center", bd=1, relief="solid")
        self.lbl_v1_cut.grid(row=1, column=2, sticky="ew", padx=1, pady=0)
        lbl_v1_st = tk.Label(v_grid, text="OFF", font=("Helvetica", 13, "bold"), fg="white", bg=self.COLOR_OFF, anchor="center", relief="raised", bd=1)
        lbl_v1_st.grid(row=1, column=3, sticky="ew", padx=1, pady=0)
        self.labels_fert_v_status[1] = lbl_v1_st

        tk.Label(v_grid, text="EC 2", font=("Helvetica", 13, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc", anchor="center", bd=1, relief="solid").grid(row=2, column=0, sticky="ew", padx=1, pady=0)
        self.lbl_v2_trig = tk.Label(v_grid, text="EC <= 1.80", font=("Helvetica", 13, "bold"), fg="#1e293b", bg="#f8fafc", anchor="center", bd=1, relief="solid")
        self.lbl_v2_trig.grid(row=2, column=1, sticky="ew", padx=1, pady=0)
        self.lbl_v2_cut = tk.Label(v_grid, text="EC >= 2.20 ", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="#e0f2fe", anchor="center", bd=1, relief="solid")
        self.lbl_v2_cut.grid(row=2, column=2, sticky="ew", padx=1, pady=0)
        lbl_v2_st = tk.Label(v_grid, text="OFF", font=("Helvetica", 13, "bold"), fg="white", bg=self.COLOR_OFF, anchor="center", relief="raised", bd=1)
        lbl_v2_st.grid(row=2, column=3, sticky="ew", padx=1, pady=0)
        self.labels_fert_v_status[2] = lbl_v2_st

        tk.Label(v_grid, text="pH Down", font=("Helvetica", 13, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc", anchor="center", bd=1, relief="solid").grid(row=3, column=0, sticky="ew", padx=1, pady=0)
        self.lbl_v3_trig = tk.Label(v_grid, text="pH >= 6.40", font=("Helvetica", 13, "bold"), fg="#1e293b", bg="#f8fafc", anchor="center", bd=1, relief="solid")
        self.lbl_v3_trig.grid(row=3, column=1, sticky="ew", padx=1, pady=0)
        self.lbl_v3_cut = tk.Label(v_grid, text="pH <= 5.80", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="#e0f2fe", anchor="center", bd=1, relief="solid")
        self.lbl_v3_cut.grid(row=3, column=2, sticky="ew", padx=1, pady=0)
        lbl_v3_st = tk.Label(v_grid, text="OFF", font=("Helvetica", 13, "bold"), fg="white", bg=self.COLOR_OFF, anchor="center", relief="raised", bd=1)
        lbl_v3_st.grid(row=3, column=3, sticky="ew", padx=1, pady=0)
        self.labels_fert_v_status[3] = lbl_v3_st

        tk.Label(v_grid, text="pH Up", font=("Helvetica", 13, "bold"), fg=self.COLOR_TEXT_MAIN, bg="#f8fafc", anchor="center", bd=1, relief="solid").grid(row=4, column=0, sticky="ew", padx=1, pady=0)
        self.lbl_v4_trig = tk.Label(v_grid, text="pH <= 5.40", font=("Helvetica", 13, "bold"), fg="#1e293b", bg="#f8fafc", anchor="center", bd=1, relief="solid")
        self.lbl_v4_trig.grid(row=4, column=1, sticky="ew", padx=1, pady=0)
        self.lbl_v4_cut = tk.Label(v_grid, text="pH >= 5.80", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="#e0f2fe", anchor="center", bd=1, relief="solid")
        self.lbl_v4_cut.grid(row=4, column=2, sticky="ew", padx=1, pady=0)
        lbl_v4_st = tk.Label(v_grid, text="OFF", font=("Helvetica", 13, "bold"), fg="white", bg=self.COLOR_OFF, anchor="center", relief="raised", bd=1)
        lbl_v4_st.grid(row=4, column=3, sticky="ew", padx=1, pady=0)
        self.labels_fert_v_status[4] = lbl_v4_st

        bottom_card = tk.LabelFrame(
            center_wrap,
            text=" AUTOMATION SEQUENCE & PROCESS MONITOR ",
            font=("Helvetica", 12, "bold"),
            fg="#1565c0",
            bg="white",
            bd=2,
            relief="groove",
            padx=5,
            pady=1
        )
        bottom_card.pack(fill="x", pady=1)

        b_body = tk.Frame(bottom_card, bg="white")
        b_body.pack(fill="x")
        b_body.columnconfigure(0, weight=5, uniform="bcol")
        b_body.columnconfigure(1, weight=6, uniform="bcol")

        self.frame_live_m_frame = tk.LabelFrame(
            b_body,
            text=" LIVE TANK SENSORS ",
            font=("Helvetica", 10, "bold"),
            fg="#1e293b",
            bg="#f8fafc",
            bd=1,
            relief="solid",
            padx=3,
            pady=1
        )
        self.frame_live_m_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 3), pady=1)

        live_row = tk.Frame(self.frame_live_m_frame, bg="#f8fafc")
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

        self.btn_start_fert = tk.Button(
            btn_action_box, text="▶ START FERTIGATION", font=("Helvetica", 15, "bold"), bg="#1565c0", fg="white",
            activebackground="#0d47a1", activeforeground="white", bd=2, relief="raised", padx=8, pady=3, cursor="hand2", command=self._on_start_batch
        )
        self.btn_start_fert.pack(side="left", expand=True, fill="x", padx=2)

        self.btn_abort_fert = tk.Button(
            btn_action_box, text="⏹ STOP / ABORT", font=("Helvetica", 15, "bold"), bg="#dc2626", fg="white",
            activebackground="#b91c1c", activeforeground="white", bd=2, relief="raised", padx=8, pady=3, cursor="hand2", command=self._on_reset_batch
        )
        self.btn_abort_fert.pack(side="left", expand=True, fill="x", padx=2)

        _update_auto_fert_ui()

        self._load_recipe_into_fert_screen()
        return f

    def _load_recipe_into_fert_screen(self):
        k = self.var_recipe.get()
        target_z = self._get_delivery_target_key()
        if target_z == "zone_1":
            recipe = get_zone_recipe(k, "zone_1")
            zone_tag = "Zone 1 (Room 1)"
        elif target_z == "zone_2":
            recipe = get_zone_recipe(k, "zone_2")
            zone_tag = "Zone 2 (Room 2)"
        elif target_z == "sequential":
            recipe = get_zone_recipe(k, "both")
            zone_tag = "Sequential (Z1 ➔ Z2)"
        else:
            recipe = get_zone_recipe(k, "both")
            zone_tag = "Both Zones (Common)"

        crop_title = recipe.get("crop_name", k.title())

        ec_min = float(recipe.get("ec_min", 1.80))
        ec_max = float(recipe.get("ec_max", 2.20))
        ph_min = float(recipe.get("ph_min", 5.40))
        ph_target = float(recipe.get("ph_target", 5.80))
        ph_max = float(recipe.get("ph_max", 6.40))

        if hasattr(self, "lbl_fert_crop_badge"):
            self.lbl_fert_crop_badge.config(text=f"{crop_title} [{zone_tag}]")
        if hasattr(self, "lbl_dash_crop"):
            self.lbl_dash_crop.config(text=f"Active Crop: {crop_title} [{zone_tag}]")

        if hasattr(self, "lbl_fert_crop_name"):
            self.lbl_fert_crop_name.config(text=f"{crop_title} [{zone_tag}]")
        if hasattr(self, "lbl_fert_ec_min"):
            self.lbl_fert_ec_min.config(text=f"{ec_min:.2f} mS/cm")
        if hasattr(self, "lbl_fert_ec_max"):
            self.lbl_fert_ec_max.config(text=f"{ec_max:.2f} mS/cm")
        if hasattr(self, "lbl_fert_ph_min"):
            self.lbl_fert_ph_min.config(text=f"{ph_min:.2f}")
        if hasattr(self, "lbl_fert_ph_target"):
            self.lbl_fert_ph_target.config(text=f"{ph_target:.2f}")
        if hasattr(self, "lbl_fert_ph_max"):
            self.lbl_fert_ph_max.config(text=f"{ph_max:.2f}")

        t_start = str(recipe.get("start_time", "06:00"))
        t_stop  = str(recipe.get("stop_time", "18:00"))
        t_on    = float(recipe.get("on_min", 5.0))
        t_off   = float(recipe.get("off_min", 60.0))

        if hasattr(self, "lbl_fert_timer_window"):
            self.lbl_fert_timer_window.config(text=f"{t_start} - {t_stop}")
        if hasattr(self, "lbl_fert_timer_on"):
            self.lbl_fert_timer_on.config(text=f"{t_on:.1f} min")
        if hasattr(self, "lbl_fert_timer_off"):
            self.lbl_fert_timer_off.config(text=f"{t_off:.1f} min")

        if hasattr(self, "lbl_v1_trig"):
            self.lbl_v1_trig.config(text=f"EC <= {ec_min:.2f}")
            self.lbl_v1_cut.config(text=f"EC >= {ec_max:.2f}")
        if hasattr(self, "lbl_v2_trig"):
            self.lbl_v2_trig.config(text=f"EC <= {ec_min:.2f}")
            self.lbl_v2_cut.config(text=f"EC >= {ec_max:.2f}")
        if hasattr(self, "lbl_v3_trig"):
            self.lbl_v3_trig.config(text=f"pH >= {ph_max:.2f}")
            self.lbl_v3_cut.config(text=f"pH <= {ph_target:.2f}")
        if hasattr(self, "lbl_v4_trig"):
            self.lbl_v4_trig.config(text=f"pH <= {ph_min:.2f}")
            self.lbl_v4_cut.config(text=f"pH >= {ph_target:.2f}")

        if hasattr(self, "lbl_fert_sp_ec_band"):
            self.lbl_fert_sp_ec_band.config(text=f"EC: {ec_min:.2f} - {ec_max:.2f} mS/cm")
        if hasattr(self, "lbl_fert_sp_ph_band"):
            self.lbl_fert_sp_ph_band.config(text=f"pH: {ph_target:.2f} ({ph_min:.2f}-{ph_max:.2f})")

        if hasattr(self, "lbl_fert_targ_ec"):
            self.lbl_fert_targ_ec.config(text=f"EC: {ec_min:.2f} - {ec_max:.2f}")
            self.lbl_fert_targ_ph.config(text=f"pH: {ph_target:.2f}")

        if hasattr(self, "lbl_mon_ec_target"):
            self.lbl_mon_ec_target.config(text=f"Range: {ec_min:.2f} - {ec_max:.2f} mS/cm")
        if hasattr(self, "lbl_mon_ph_target"):
            self.lbl_mon_ph_target.config(text=f"Target: {ph_target:.2f} ({ph_min:.2f}-{ph_max:.2f})")

    def _get_delivery_target_key(self) -> str:
        z_sel = getattr(self, "var_fert_delivery_zone", tk.StringVar(value="both")).get().strip().lower()
        if "sequential" in z_sel:
            return "sequential"
        elif "zone_1" in z_sel or "zone 1" in z_sel or "room 1" in z_sel:
            return "zone_1"
        elif "zone_2" in z_sel or "zone 2" in z_sel or "room 2" in z_sel:
            return "zone_2"
        return "both"

    def _on_start_batch(self):
        if getattr(self, "var_auto_fertigation", None) and self.var_auto_fertigation.get():
            messagebox.showinfo(
                "Auto Mode Active",
                "System is currently in AUTO FERTIGATION mode.\n\n"
                "In Auto mode, fertigation cycles trigger automatically based on live sensor readings.\n"
                "Switch to MANUAL FERTIGATION if you wish to trigger a batch manually."
            )
            return

        if engine.is_running:
            messagebox.showinfo("Process Busy", "A fertigation cycle is already in progress!")
            return
        target_z = self._get_delivery_target_key()
        started, msg = engine.start_cycle(self.var_recipe.get(), delivery_target=target_z)
        if not started:
            messagebox.showwarning("Fertigation Standby", msg)

    def _on_reset_batch(self):
        if hasattr(self, "var_auto_fertigation") and self.var_auto_fertigation is not None:
            self.var_auto_fertigation.set(False)
            if hasattr(self, "_update_auto_fert_ui") and callable(self._update_auto_fert_ui):
                self._update_auto_fert_ui()
        engine.stop_cycle()
        hw.emergency_all_off()

    def _create_irrigation_screen(self, parent):
        f = tk.Frame(parent, bg="white")

        top_info = tk.Frame(f, bg="#f8fafc", bd=1, relief="groove", padx=10, pady=4)
        top_info.pack(fill="x", pady=(0, 2))

        tk.Label(top_info, text="AUTOMATED CYCLIC IRRIGATION (2-ZONE CONTROLLER)", font=("Helvetica", 12, "bold"), fg="#1565c0", bg="#f8fafc").pack(side="left")

        body = tk.Frame(f, bg="white")
        body.pack(fill="both", expand=True, padx=10, pady=2)

        center_wrap = tk.Frame(body, bg="white")
        center_wrap.pack(anchor="center", pady=1)

        card = tk.LabelFrame(
            center_wrap,
            text=" FIELD IRRIGATION CYCLIC TIMERS (2 INDEPENDENT ZONES) ",
            font=("Helvetica", 12, "bold"),
            fg="#1565c0",
            bg="white",
            bd=2,
            relief="groove",
            padx=10,
            pady=2
        )
        card.pack(anchor="center", pady=1)

        t_grid = tk.Frame(card, bg="white")
        t_grid.pack(anchor="center", pady=1)
        t_grid.columnconfigure(0, minsize=210)
        t_grid.columnconfigure(1, minsize=265)
        t_grid.columnconfigure(2, minsize=265)

        vh_bg = "#e2e8f0"
        tk.Label(t_grid, text="Setting Parameter", font=("Helvetica", 11, "bold"), fg="#1e293b", bg=vh_bg, anchor="w", padx=8, pady=3).grid(row=0, column=0, sticky="ew", padx=2, pady=1)
        tk.Label(t_grid, text="ZONE 1 (S.V 12)", font=("Helvetica", 11, "bold"), fg="#1565c0", bg=vh_bg, anchor="center", pady=3).grid(row=0, column=1, sticky="ew", padx=2, pady=1)
        tk.Label(t_grid, text="ZONE 2 (S.V 13)", font=("Helvetica", 11, "bold"), fg="#0891b2", bg=vh_bg, anchor="center", pady=3).grid(row=0, column=2, sticky="ew", padx=2, pady=1)

        z1_cfg = cyclic_timer_cfg.get("zone_1", {})
        z2_cfg = cyclic_timer_cfg.get("zone_2", {})

        tk.Label(t_grid, text="Timer Line Name:", font=("Helvetica", 11, "bold"), fg="#334155", bg="#f8fafc", anchor="w", padx=8, pady=3).grid(row=1, column=0, sticky="ew", padx=2, pady=1)

        f_z1_n = tk.Frame(t_grid, bg="#f8fafc", bd=1, relief="solid")
        f_z1_n.grid(row=1, column=1, sticky="ew", padx=2, pady=1)
        f_z1_n_in = tk.Frame(f_z1_n, bg="#f8fafc")
        f_z1_n_in.pack(anchor="center", pady=2)
        self.lbl_t_z1_name = tk.Label(f_z1_n_in, text=str(z1_cfg.get("name", "Zone 1 Drip Line")), font=("Helvetica", 12, "bold"), fg="#0f172a", bg="white", relief="groove", bd=2, width=13, anchor="center", padx=6, pady=3, cursor="hand2")
        self.lbl_t_z1_name.pack(side="left", padx=4)
        def edit_z1_name():
            open_almora_keypad("Edit Zone 1 Name", self.lbl_t_z1_name.cget("text"), lambda v: self.lbl_t_z1_name.config(text=v), is_alphanumeric=True, root_window=self)
        self.lbl_t_z1_name.bind("<Button-1>", lambda e: edit_z1_name())
        tk.Button(f_z1_n_in, text="EDIT", font=("Helvetica", 11, "bold"), bg="#0284c7", fg="white", activebackground="#0369a1", activeforeground="white", bd=2, relief="raised", padx=16, pady=3, cursor="hand2", command=edit_z1_name).pack(side="left", padx=4)

        f_z2_n = tk.Frame(t_grid, bg="#f8fafc", bd=1, relief="solid")
        f_z2_n.grid(row=1, column=2, sticky="ew", padx=2, pady=1)
        f_z2_n_in = tk.Frame(f_z2_n, bg="#f8fafc")
        f_z2_n_in.pack(anchor="center", pady=2)
        self.lbl_t_z2_name = tk.Label(f_z2_n_in, text=str(z2_cfg.get("name", "Zone 2 Drip Line")), font=("Helvetica", 12, "bold"), fg="#0f172a", bg="white", relief="groove", bd=2, width=13, anchor="center", padx=6, pady=3, cursor="hand2")
        self.lbl_t_z2_name.pack(side="left", padx=4)
        def edit_z2_name():
            open_almora_keypad("Edit Zone 2 Name", self.lbl_t_z2_name.cget("text"), lambda v: self.lbl_t_z2_name.config(text=v), is_alphanumeric=True, root_window=self)
        self.lbl_t_z2_name.bind("<Button-1>", lambda e: edit_z2_name())
        tk.Button(f_z2_n_in, text="EDIT", font=("Helvetica", 11, "bold"), bg="#0284c7", fg="white", activebackground="#0369a1", activeforeground="white", bd=2, relief="raised", padx=16, pady=3, cursor="hand2", command=edit_z2_name).pack(side="left", padx=4)

        tk.Label(t_grid, text="Timer Automation:", font=("Helvetica", 11, "bold"), fg="#334155", bg="white", anchor="w", padx=8, pady=3).grid(row=2, column=0, sticky="ew", padx=2, pady=1)

        f_z1_en = tk.Frame(t_grid, bg="white", bd=1, relief="solid")
        f_z1_en.grid(row=2, column=1, sticky="ew", padx=2, pady=1)
        self.var_z1_en = tk.BooleanVar(value=z1_cfg.get("enabled", True))

        def toggle_z1_enable():
            new_st = not self.var_z1_en.get()
            self.var_z1_en.set(new_st)
            _update_z1_en_btn()
            if "zone_1" in cyclic_timer_cfg:
                cyclic_timer_cfg["zone_1"]["enabled"] = new_st
                save_json(TIMERS_FILE, cyclic_timer_cfg)

        def _update_z1_en_btn():
            if self.var_z1_en.get():
                self.btn_z1_en.config(
                    text="ENABLED", bg="#15803d", fg="white",
                    activebackground="#166534", activeforeground="white", relief="sunken"
                )
            else:
                self.btn_z1_en.config(
                    text="DISABLED", bg="#fee2e2", fg="#991b1b",
                    activebackground="#fecaca", activeforeground="#7f1d1d", relief="raised"
                )

        self.btn_z1_en = tk.Button(
            f_z1_en, font=("Helvetica", 11, "bold"), bd=2, padx=14, pady=3, cursor="hand2",
            command=toggle_z1_enable
        )
        self.btn_z1_en.pack(anchor="center", pady=2)
        _update_z1_en_btn()

        f_z2_en = tk.Frame(t_grid, bg="white", bd=1, relief="solid")
        f_z2_en.grid(row=2, column=2, sticky="ew", padx=2, pady=1)
        self.var_z2_en = tk.BooleanVar(value=z2_cfg.get("enabled", True))

        def toggle_z2_enable():
            new_st = not self.var_z2_en.get()
            self.var_z2_en.set(new_st)
            _update_z2_en_btn()
            if "zone_2" in cyclic_timer_cfg:
                cyclic_timer_cfg["zone_2"]["enabled"] = new_st
                save_json(TIMERS_FILE, cyclic_timer_cfg)

        def _update_z2_en_btn():
            if self.var_z2_en.get():
                self.btn_z2_en.config(
                    text="ENABLED", bg="#15803d", fg="white",
                    activebackground="#166534", activeforeground="white", relief="sunken"
                )
            else:
                self.btn_z2_en.config(
                    text="DISABLED", bg="#fee2e2", fg="#991b1b",
                    activebackground="#fecaca", activeforeground="#7f1d1d", relief="raised"
                )

        self.btn_z2_en = tk.Button(
            f_z2_en, font=("Helvetica", 11, "bold"), bd=2, padx=14, pady=3, cursor="hand2",
            command=toggle_z2_enable
        )
        self.btn_z2_en.pack(anchor="center", pady=2)
        _update_z2_en_btn()

        def make_2zone_param_row(r_idx, label_text, z1_val, z2_val, kmode="numeric", bg_clr="white"):
            tk.Label(t_grid, text=label_text, font=("Helvetica", 11, "bold"), fg="#334155", bg=bg_clr, anchor="w", padx=8, pady=3).grid(row=r_idx, column=0, sticky="ew", padx=2, pady=1)

            f1 = tk.Frame(t_grid, bg=bg_clr, bd=1, relief="solid")
            f1.grid(row=r_idx, column=1, sticky="ew", padx=2, pady=1)
            f1_in = tk.Frame(f1, bg=bg_clr)
            f1_in.pack(anchor="center", pady=2)
            lbl1 = tk.Label(f1_in, text=str(z1_val), font=("Helvetica", 12, "bold"), fg="#1565c0", bg="white", relief="groove", bd=2, width=10, anchor="center", padx=4, pady=3, cursor="hand2")
            lbl1.pack(side="left", padx=3)
            def do_e1():
                open_almora_keypad(f"Zone 1: {label_text}", lbl1.cget("text"), lambda v: lbl1.config(text=v), mode=kmode, root_window=self)
            lbl1.bind("<Button-1>", lambda e: do_e1())
            tk.Button(f1_in, text="EDIT", font=("Helvetica", 11, "bold"), bg="#0284c7", fg="white", activebackground="#0369a1", activeforeground="white", bd=2, relief="raised", padx=16, pady=3, cursor="hand2", command=do_e1).pack(side="left", padx=3)

            f2 = tk.Frame(t_grid, bg=bg_clr, bd=1, relief="solid")
            f2.grid(row=r_idx, column=2, sticky="ew", padx=2, pady=1)
            f2_in = tk.Frame(f2, bg=bg_clr)
            f2_in.pack(anchor="center", pady=2)
            lbl2 = tk.Label(f2_in, text=str(z2_val), font=("Helvetica", 12, "bold"), fg="#0891b2", bg="white", relief="groove", bd=2, width=10, anchor="center", padx=4, pady=3, cursor="hand2")
            lbl2.pack(side="left", padx=3)
            def do_e2():
                open_almora_keypad(f"Zone 2: {label_text}", lbl2.cget("text"), lambda v: lbl2.config(text=v), mode=kmode, root_window=self)
            lbl2.bind("<Button-1>", lambda e: do_e2())
            tk.Button(f2_in, text="EDIT", font=("Helvetica", 11, "bold"), bg="#0284c7", fg="white", activebackground="#0369a1", activeforeground="white", bd=2, relief="raised", padx=16, pady=3, cursor="hand2", command=do_e2).pack(side="left", padx=3)

            return lbl1, lbl2

        self.lbl_t_z1_start, self.lbl_t_z2_start = make_2zone_param_row(3, "Start Window Time:", z1_cfg.get("start_time", "06:00"), z2_cfg.get("start_time", "06:00"), kmode="time", bg_clr="#f8fafc")
        self.lbl_t_z1_stop,  self.lbl_t_z2_stop  = make_2zone_param_row(4, "Stop Window Time:",  z1_cfg.get("stop_time", "18:00"),  z2_cfg.get("stop_time", "18:00"),  kmode="time", bg_clr="white")
        self.lbl_t_z1_on,    self.lbl_t_z2_on    = make_2zone_param_row(5, "ON Duration (Min):",  z1_cfg.get("on_min", 5.0),         z2_cfg.get("on_min", 5.0),         kmode="numeric", bg_clr="#f8fafc")
        self.lbl_t_z1_off,   self.lbl_t_z2_off   = make_2zone_param_row(6, "OFF Interval (Min):", z1_cfg.get("off_min", 15.0),       z2_cfg.get("off_min", 15.0),       kmode="numeric", bg_clr="white")

        tk.Label(t_grid, text="Live Operation Status:", font=("Helvetica", 11, "bold"), fg="#1565c0", bg="#f1f5f9", anchor="w", padx=8, pady=3).grid(row=7, column=0, sticky="ew", padx=2, pady=1)

        f1_live = tk.Frame(t_grid, bg="#f1f5f9", bd=1, relief="solid")
        f1_live.grid(row=7, column=1, sticky="ew", padx=2, pady=1)
        f1_live_in = tk.Frame(f1_live, bg="#f1f5f9")
        f1_live_in.pack(anchor="center", pady=2)
        self.lbl_z1_state = tk.Label(f1_live_in, text="OFF", font=("Helvetica", 11, "bold"), fg="white", bg=self.COLOR_OFF, padx=10, pady=3, relief="raised", bd=2)
        self.lbl_z1_state.pack(side="left", padx=3)
        self.lbl_z1_rem = tk.Label(f1_live_in, text="Rem: 00:00", font=("Helvetica", 12, "bold"), fg="#1565c0", bg="#e0f2fe", padx=8, pady=3, relief="groove", bd=2)
        self.lbl_z1_rem.pack(side="left", padx=3)

        f2_live = tk.Frame(t_grid, bg="#f1f5f9", bd=1, relief="solid")
        f2_live.grid(row=7, column=2, sticky="ew", padx=2, pady=1)
        f2_live_in = tk.Frame(f2_live, bg="#f1f5f9")
        f2_live_in.pack(anchor="center", pady=2)
        self.lbl_z2_state = tk.Label(f2_live_in, text="OFF", font=("Helvetica", 11, "bold"), fg="white", bg=self.COLOR_OFF, padx=10, pady=3, relief="raised", bd=2)
        self.lbl_z2_state.pack(side="left", padx=3)
        self.lbl_z2_rem = tk.Label(f2_live_in, text="Rem: 00:00", font=("Helvetica", 12, "bold"), fg="#0891b2", bg="#e0f2fe", padx=8, pady=3, relief="groove", bd=2)
        self.lbl_z2_rem.pack(side="left", padx=3)

        act_box = tk.Frame(center_wrap, bg="white")
        act_box.pack(anchor="center", pady=4)

        tk.Button(
            act_box, text="💾 Save Both Zone Settings", font=("Helvetica", 11, "bold"), bg="#2e7d32", fg="white",
            activebackground="#15803d", activeforeground="white", bd=2, relief="raised", padx=14, pady=4, cursor="hand2", command=self._save_cyclic_timer_settings
        ).pack(side="left", padx=4)

        self.btn_z1_run = tk.Button(
            act_box, text="⏹ Stop Zone 1 (12)", font=("Helvetica", 11, "bold"), bg="#fee2e2", fg="#b91c1c",
            activebackground="#fecaca", activeforeground="#991b1b", bd=2, relief="raised", padx=12, pady=4, cursor="hand2", command=lambda: self._toggle_zone_run("zone_1")
        )
        self.btn_z1_run.pack(side="left", padx=4)

        self.btn_z2_run = tk.Button(
            act_box, text="⏹ Stop Zone 2 (13)", font=("Helvetica", 11, "bold"), bg="#fee2e2", fg="#b91c1c",
            activebackground="#fecaca", activeforeground="#991b1b", bd=2, relief="raised", padx=12, pady=4, cursor="hand2", command=lambda: self._toggle_zone_run("zone_2")
        )
        self.btn_z2_run.pack(side="left", padx=4)

        tk.Button(
            act_box, text="⏹ Stop All Irrigation", font=("Helvetica", 11, "bold"), bg="#dc2626", fg="white",
            activebackground="#b91c1c", activeforeground="white", bd=2, relief="raised", padx=14, pady=4, cursor="hand2", command=self._on_stop_all_irrigation
        ).pack(side="left", padx=4)

        return f

    def _toggle_zone_run(self, zone_key: str):
        ts = irrigation_engine.timer_states.get(zone_key, {})
        if ts.get("state") == "ON":
            irrigation_engine.stop_zone(zone_key)
        else:
            irrigation_engine.start_zone(zone_key)

    def _on_stop_all_irrigation(self):
        irrigation_engine.stop_irrigation()

    def _save_cyclic_timer_settings(self):
        try:
            cyclic_timer_cfg["zone_1"] = {
                "name": self.lbl_t_z1_name.cget("text").strip(),
                "enabled": self.var_z1_en.get(),
                "start_time": self.lbl_t_z1_start.cget("text").strip(),
                "stop_time": self.lbl_t_z1_stop.cget("text").strip(),
                "on_min": float(self.lbl_t_z1_on.cget("text")),
                "off_min": float(self.lbl_t_z1_off.cget("text"))
            }
            cyclic_timer_cfg["zone_2"] = {
                "name": self.lbl_t_z2_name.cget("text").strip(),
                "enabled": self.var_z2_en.get(),
                "start_time": self.lbl_t_z2_start.cget("text").strip(),
                "stop_time": self.lbl_t_z2_stop.cget("text").strip(),
                "on_min": float(self.lbl_t_z2_on.cget("text")),
                "off_min": float(self.lbl_t_z2_off.cget("text"))
            }

            if self.var_z1_en.get():
                irrigation_engine.timer_states["zone_1"]["manual_stopped"] = False
            if self.var_z2_en.get():
                irrigation_engine.timer_states["zone_2"]["manual_stopped"] = False

            save_json(TIMERS_FILE, cyclic_timer_cfg)
            broadcast_current_state()
            messagebox.showinfo("Saved", "Both Zone 1 & Zone 2 timer settings saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save timer settings: {e}")

    def _create_settings_screen(self, parent):
        f = tk.Frame(parent, bg="white")

        top_sel = tk.Frame(f, bg="#f8fafc", bd=1, relief="groove", pady=5)
        top_sel.pack(fill="x", pady=(0, 2))

        sel_inner = tk.Frame(top_sel, bg="#f8fafc")
        sel_inner.pack(anchor="center")

        tk.Label(sel_inner, text="Select Crop:", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="#f8fafc").pack(side="left", padx=(0, 8))

        def on_set_crop_selected():
            self._load_crop_into_settings_tab()
            if hasattr(self, "dd_fert_crop"):
                self.dd_fert_crop.update_label()
            if hasattr(self, "_load_recipe_into_fert_screen"):
                self._load_recipe_into_fert_screen()

        self.dd_set_crop = GridTouchDropdown(
            parent=sel_inner,
            root=self,
            var=self.var_recipe,
            values=list(crop_recipes.keys()),
            display_map={k: crop_recipes[k].get("crop_name", k.title()) for k in crop_recipes},
            on_select=on_set_crop_selected,
            cols=3
        )
        self.dd_set_crop.btn.config(font=("Helvetica", 13, "bold"), padx=14, pady=5)
        self.dd_set_crop.btn.pack(side="left", padx=4)

        tk.Label(sel_inner, text="Target Zone / Room:", font=("Helvetica", 13, "bold"), fg="#1565c0", bg="#f8fafc").pack(side="left", padx=(18, 8))

        self.var_set_zone = tk.StringVar(value="both")
        self.dd_set_zone = GridTouchDropdown(
            parent=sel_inner,
            root=self,
            var=self.var_set_zone,
            values=["both", "zone_1", "zone_2"],
            display_map={
                "both": "Both Zones (Common)",
                "zone_1": "Zone 1 (Room 1)",
                "zone_2": "Zone 2 (Room 2)"
            },
            on_select=lambda: self._load_crop_into_settings_tab(),
            cols=3
        )
        self.dd_set_zone.btn.config(font=("Helvetica", 13, "bold"), padx=14, pady=5)
        self.dd_set_zone.btn.pack(side="left", padx=4)

        center_wrap = tk.Frame(f, bg="white")
        center_wrap.pack(anchor="center", pady=2)

        form_card = tk.LabelFrame(
            center_wrap,
            text="  CROP NUTRIENT TARGET SETPOINTS (EC & pH)  ",
            font=("Helvetica", 13, "bold"),
            fg="#1565c0",
            bg="white",
            bd=2,
            relief="groove",
            padx=8,
            pady=4
        )
        form_card.pack(fill="x", pady=2)

        sp_outer = tk.Frame(form_card, bg="#f8fafc", bd=1, relief="groove", padx=6, pady=4)
        sp_outer.pack(fill="x", pady=2)
        sp_outer.columnconfigure(0, weight=1, uniform="sp_col")
        sp_outer.columnconfigure(1, weight=1, uniform="sp_col")
        sp_outer.columnconfigure(2, weight=1, uniform="sp_col")

        def make_sp_field(parent_frame, r_idx, c_idx, label_text, default_v, val_fg="#1565c0", box_w=5, mode="numeric", btn_px=14):
            f_cell = tk.Frame(parent_frame, bg="#f8fafc", bd=1, relief="solid", padx=6, pady=7)
            f_cell.grid(row=r_idx, column=c_idx, sticky="nsew", padx=3, pady=3)
            tk.Label(f_cell, text=label_text, font=("Helvetica", 12, "bold"), fg="#0f172a", bg="#f8fafc").pack(side="left", padx=(0, 4))
            l_box = tk.Label(
                f_cell, text=str(default_v), font=("Helvetica", 14, "bold"), fg=val_fg,
                bg="white", relief="groove", bd=2, width=box_w, anchor="center", padx=4, pady=5, cursor="hand2"
            )
            l_box.pack(side="left", padx=2)
            def do_e():
                open_almora_keypad(f"Edit {label_text}", l_box.cget("text"), lambda v: l_box.config(text=v), mode=mode, root_window=self)
            l_box.bind("<Button-1>", lambda e: do_e())
            tk.Button(
                f_cell, text="EDIT", font=("Helvetica", 12, "bold"),
                bg="#0284c7", fg="white", activebackground="#0369a1", activeforeground="white",
                bd=2, relief="raised", padx=btn_px, pady=5, cursor="hand2", command=do_e
            ).pack(side="left", padx=2)
            return l_box

        f_name = tk.Frame(sp_outer, bg="#f8fafc", bd=1, relief="solid", padx=6, pady=7)
        f_name.grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
        tk.Label(f_name, text="Crop Name:", font=("Helvetica", 12, "bold"), fg="#0f172a", bg="#f8fafc").pack(side="left", padx=(0, 4))
        self.lbl_set_crop_name = tk.Label(
            f_name, text="Cucumber", font=("Helvetica", 14, "bold"), fg="#0f172a",
            bg="white", relief="groove", bd=2, padx=4, pady=5, width=8, anchor="center", cursor="hand2"
        )
        self.lbl_set_crop_name.pack(side="left", padx=2)
        def edit_crop_name():
            def on_crop_name_confirmed(new_val):
                new_val = str(new_val).strip()
                if not new_val:
                    return
                self.lbl_set_crop_name.config(text=new_val)
                k = self.var_recipe.get()
                if k in crop_recipes:
                    crop_recipes[k]["crop_name"] = new_val
                    if "zones" in crop_recipes[k] and isinstance(crop_recipes[k]["zones"], dict):
                        for zk in ["both", "zone_1", "zone_2"]:
                            if zk in crop_recipes[k]["zones"] and isinstance(crop_recipes[k]["zones"][zk], dict):
                                crop_recipes[k]["zones"][zk]["crop_name"] = new_val
                    save_json(RECIPE_FILE, crop_recipes)
                    new_disp_map = {rk: crop_recipes[rk].get("crop_name", rk.title()) for rk in crop_recipes}
                    if hasattr(self, "dd_fert_crop"):
                        self.dd_fert_crop.display_map = dict(new_disp_map)
                        self.dd_fert_crop.update_label()
                    if hasattr(self, "dd_set_crop"):
                        self.dd_set_crop.display_map = dict(new_disp_map)
                        self.dd_set_crop.update_label()
                    self._load_recipe_into_fert_screen()
                    broadcast_current_state()
            open_almora_keypad("Edit Crop Name", self.lbl_set_crop_name.cget("text"), on_crop_name_confirmed, is_alphanumeric=True, root_window=self)
        self.lbl_set_crop_name.bind("<Button-1>", lambda e: edit_crop_name())
        tk.Button(
            f_name, text="EDIT", font=("Helvetica", 12, "bold"),
            bg="#0284c7", fg="white", activebackground="#0369a1", activeforeground="white",
            bd=2, relief="raised", padx=14, pady=5, cursor="hand2", command=edit_crop_name
        ).pack(side="left", padx=2)

        self.lbl_set_ec_min = make_sp_field(sp_outer, 0, 1, "EC Min (Start):", "1.80", val_fg="#1565c0", box_w=5, btn_px=14)

        self.lbl_set_ec_max = make_sp_field(sp_outer, 0, 2, "EC Max (Stop):", "2.20", val_fg="#1565c0", box_w=5, btn_px=14)

        self.lbl_set_ph_min = make_sp_field(sp_outer, 1, 0, "pH Min (Up):", "5.40", val_fg="#0891b2", box_w=5, btn_px=14)

        self.lbl_set_ph_target = make_sp_field(sp_outer, 1, 1, "pH Target:", "5.80", val_fg="#1565c0", box_w=5, btn_px=14)

        self.lbl_set_ph_max = make_sp_field(sp_outer, 1, 2, "pH Max (Down):", "6.40", val_fg="#dc2626", box_w=5, btn_px=14)

        timer_card = tk.LabelFrame(
            center_wrap,
            text="  CYCLIC FERTIGATION TIMER CONFIGURATION  ",
            font=("Helvetica", 13, "bold"),
            fg="#1565c0",
            bg="white",
            bd=2,
            relief="groove",
            padx=8,
            pady=4
        )
        timer_card.pack(fill="x", pady=2)

        timer_outer = tk.Frame(timer_card, bg="#f8fafc", bd=1, relief="groove", padx=6, pady=4)
        timer_outer.pack(fill="x", pady=2)
        timer_outer.columnconfigure(0, weight=1, uniform="tm_col")
        timer_outer.columnconfigure(1, weight=1, uniform="tm_col")

        self.lbl_set_start_time = make_sp_field(timer_outer, 0, 0, "Window Start Time:", "06:00", val_fg="#1565c0", box_w=5, mode="time", btn_px=16)
        self.lbl_set_stop_time  = make_sp_field(timer_outer, 0, 1, "Window Stop Time:",  "18:00", val_fg="#1565c0", box_w=5, mode="time", btn_px=16)

        self.lbl_set_on_min  = make_sp_field(timer_outer, 1, 0, "Delivery ON (min):",  "5.0",  val_fg="#0891b2", box_w=5, mode="numeric", btn_px=16)
        self.lbl_set_off_min = make_sp_field(timer_outer, 1, 1, "Interval OFF (min):", "60.0", val_fg="#1565c0", box_w=5, mode="numeric", btn_px=16)

        f_save = tk.Frame(f, bg="white")
        f_save.pack(fill="x", pady=(3, 2))

        btn_save = tk.Button(
            f_save, text="💾 Save Crop Setpoints & Cyclic Timer", font=("Helvetica", 14, "bold"),
            bg="#2e7d32", fg="white", activebackground="#15803d", activeforeground="white",
            bd=2, relief="raised", padx=36, pady=7, cursor="hand2", command=self._save_crop_safety_settings
        )
        btn_save.pack(anchor="center")
        btn_save.pack(anchor="center")

        self._load_crop_into_settings_tab()
        return f

    def _load_crop_into_settings_tab(self):
        k = self.var_recipe.get()
        z_str = getattr(self, "var_set_zone", tk.StringVar(value="both")).get()
        z_lower = str(z_str).lower()
        if "zone_1" in z_lower or "room 1" in z_lower:
            z_key = "zone_1"
        elif "zone_2" in z_lower or "room 2" in z_lower:
            z_key = "zone_2"
        else:
            z_key = "both"

        recipe = get_zone_recipe(k, z_key)

        self.lbl_set_crop_name.config(text=str(recipe.get("crop_name", k.title())))
        self.lbl_set_ec_min.config(text=f"{recipe.get('ec_min', 1.80):.2f}")
        self.lbl_set_ec_max.config(text=f"{recipe.get('ec_max', 2.20):.2f}")
        self.lbl_set_ph_min.config(text=f"{recipe.get('ph_min', 5.40):.2f}")
        self.lbl_set_ph_target.config(text=f"{recipe.get('ph_target', 5.80):.2f}")
        self.lbl_set_ph_max.config(text=f"{recipe.get('ph_max', 6.40):.2f}")

        self.set_timer_enabled_val = bool(recipe.get("timer_enabled", True))
        if hasattr(self, "_update_timer_en_btn"):
            self._update_timer_en_btn()
        if hasattr(self, "lbl_set_start_time"):
            self.lbl_set_start_time.config(text=str(recipe.get("start_time", "06:00")))
        if hasattr(self, "lbl_set_stop_time"):
            self.lbl_set_stop_time.config(text=str(recipe.get("stop_time", "18:00")))
        if hasattr(self, "lbl_set_on_min"):
            self.lbl_set_on_min.config(text=f"{float(recipe.get('on_min', 5.0)):.1f}")
        if hasattr(self, "lbl_set_off_min"):
            self.lbl_set_off_min.config(text=f"{float(recipe.get('off_min', 60.0)):.1f}")

    def _save_crop_safety_settings(self):
        k = self.var_recipe.get()
        if k not in crop_recipes:
            return
        z_str = getattr(self, "var_set_zone", tk.StringVar(value="both")).get()
        z_lower = str(z_str).lower()
        if "zone_1" in z_lower or "room 1" in z_lower:
            z_key = "zone_1"
            z_title = "Zone 1 (Room 1)"
        elif "zone_2" in z_lower or "room 2" in z_lower:
            z_key = "zone_2"
            z_title = "Zone 2 (Room 2)"
        else:
            z_key = "both"
            z_title = "Both Zones (Common)"

        try:
            c_name = self.lbl_set_crop_name.cget("text").strip()
            ec_min_val = float(self.lbl_set_ec_min.cget("text"))
            ec_max_val = float(self.lbl_set_ec_max.cget("text"))
            ph_min_val = float(self.lbl_set_ph_min.cget("text"))
            ph_targ_val = float(self.lbl_set_ph_target.cget("text"))
            ph_max_val = float(self.lbl_set_ph_max.cget("text"))

            t_en = True
            t_start = self.lbl_set_start_time.cget("text").strip() if hasattr(self, "lbl_set_start_time") else "06:00"
            t_stop  = self.lbl_set_stop_time.cget("text").strip() if hasattr(self, "lbl_set_stop_time") else "18:00"
            t_on    = float(self.lbl_set_on_min.cget("text")) if hasattr(self, "lbl_set_on_min") else 5.0
            t_off   = float(self.lbl_set_off_min.cget("text")) if hasattr(self, "lbl_set_off_min") else 60.0

            if "zones" not in crop_recipes[k]:
                crop_recipes[k]["zones"] = {}

            data_dict = {
                "crop_name": c_name,
                "ec_min": ec_min_val,
                "ec_max": ec_max_val,
                "ph_min": ph_min_val,
                "ph_target": ph_targ_val,
                "ph_max": ph_max_val,
                "ec1_safety_max": round(ec_max_val + 0.30, 2),
                "ec2_safety_max": round(ec_max_val + 0.30, 2),
                "ph_down_safety_min": 4.60,
                "ph_up_safety_max": 7.20,
                "timer_enabled": t_en,
                "start_time": t_start,
                "stop_time": t_stop,
                "on_min": t_on,
                "off_min": t_off
            }

            crop_recipes[k]["crop_name"] = c_name
            if "zones" in crop_recipes[k] and isinstance(crop_recipes[k]["zones"], dict):
                for zk in ["both", "zone_1", "zone_2"]:
                    if zk in crop_recipes[k]["zones"] and isinstance(crop_recipes[k]["zones"][zk], dict):
                        crop_recipes[k]["zones"][zk]["crop_name"] = c_name

            if z_key == "both":
                crop_recipes[k]["zones"]["both"] = dict(data_dict)
                crop_recipes[k].update(data_dict)
                msg_txt = f"Common setpoints & Cyclic Timer saved for Both Zones under {c_name}!"
            else:
                crop_recipes[k]["zones"][z_key] = dict(data_dict)
                msg_txt = f"Setpoints & Cyclic Timer saved specifically for {z_title} under {c_name}!"

            save_json(RECIPE_FILE, crop_recipes)

            new_disp_map = {rk: crop_recipes[rk].get("crop_name", rk.title()) for rk in crop_recipes}
            if hasattr(self, "dd_fert_crop"):
                self.dd_fert_crop.display_map = dict(new_disp_map)
                self.dd_fert_crop.update_label()
            if hasattr(self, "dd_set_crop"):
                self.dd_set_crop.display_map = dict(new_disp_map)
                self.dd_set_crop.update_label()

            self._load_recipe_into_fert_screen()
            self._load_crop_into_settings_tab()
            broadcast_current_state()
            messagebox.showinfo("Saved", msg_txt)
        except Exception as err:
            messagebox.showerror("Error", f"Failed to save settings: {err}")

    def _periodic_tick(self):
        hw.simulate_step(0.1)
        irrigation_engine.process_tick()

        now_dt = datetime.datetime.now()
        cur_time = now_dt.time()
        now_sec = time.time()

        if getattr(self, "var_auto_fertigation", None) and self.var_auto_fertigation.get():
            target_z = self._get_delivery_target_key()
            z_key = target_z if target_z in ["zone_1", "zone_2"] else "both"
            crop_k = self.var_recipe.get()
            recipe = get_zone_recipe(crop_k, z_key)
            t_en = recipe.get("timer_enabled", True)

            if engine.is_running:

                self.fert_last_cycle_time[z_key] = now_sec
            else:
                if t_en:
                    try:
                        t_start = datetime.datetime.strptime(recipe.get("start_time", "06:00"), "%H:%M").time()
                        t_stop  = datetime.datetime.strptime(recipe.get("stop_time", "18:00"), "%H:%M").time()
                    except Exception:
                        t_start = datetime.time(0, 0)
                        t_stop  = datetime.time(23, 59)

                    in_window = (t_start <= cur_time <= t_stop) if t_start <= t_stop else (cur_time >= t_start or cur_time <= t_stop)
                    off_sec = float(recipe.get("off_min", 60.0)) * 60.0
                    last_run = self.fert_last_cycle_time.get(z_key, 0.0)

                    if in_window:
                        if last_run == 0.0 or (now_sec - last_run >= off_sec):
                            if not getattr(hw, "sensor_error", False):
                                print(f"[AUTO CYCLIC FERT TRIGGER] Window ({recipe.get('start_time')} - {recipe.get('stop_time')}). Starting cycle for {crop_k} ({target_z}) | Delivery: {recipe.get('on_min', 5.0)}m, Interval: {recipe.get('off_min', 60.0)}m...")
                                engine.start_cycle(crop_k, delivery_target=target_z)
                                self.fert_last_cycle_time[z_key] = now_sec
                        else:
                            rem_sec = max(0, int(off_sec - (now_sec - last_run)))
                            rem_m = rem_sec // 60
                            rem_s = rem_sec % 60
                            self.fert_cyclic_status_msg = f"Auto Cyclic Timer: Next cycle in {rem_m:02d}m {rem_s:02d}s (Interval: {recipe.get('off_min', 60.0):.0f}m)"
                    else:
                        self.fert_cyclic_status_msg = f"Auto Cyclic Timer: Outside Window ({recipe.get('start_time', '06:00')} - {recipe.get('stop_time', '18:00')})"
                        self.fert_last_cycle_time[z_key] = 0.0
                else:
                    self.fert_cyclic_status_msg = "Auto Fert: Cyclic Timer Disabled"
                    if not getattr(hw, "sensor_error", False) and hw.pv_ec is not None and hw.pv_ph is not None:
                        ec_min = float(recipe.get("ec_min", 1.80))
                        ph_min = float(recipe.get("ph_min", 5.40))
                        ph_max = float(recipe.get("ph_max", 6.40))
                        if hw.pv_ec <= ec_min or hw.pv_ph >= ph_max or hw.pv_ph <= ph_min:
                            print(f"[AUTO FERT SENSOR TRIGGER] PV EC={hw.pv_ec} (limit <= {ec_min}), PV pH={hw.pv_ph} (limits: {ph_min}..{ph_max}). Starting cycle for {crop_k} ({target_z})...")
                            engine.start_cycle(crop_k, delivery_target=target_z)

        now_dt = datetime.datetime.now()
        now_str = f"{now_dt.strftime('%d-%m-%Y')}\n{now_dt.strftime('%I:%M:%S %p')}"
        self.lbl_clock.config(text=now_str)

        if hasattr(self, "lbl_mon_ec_val"):
            if hw.pv_ec is None or getattr(hw, "sensor_error", False):
                self.lbl_mon_ec_val.config(text="SENSOR ERROR", fg="#dc2626", font=("Helvetica", 18, "bold"))
            else:
                self.lbl_mon_ec_val.config(text=f"{hw.pv_ec:.3f}", fg="#1565c0", font=("Helvetica", 26, "bold"))

            if hw.pv_ph is None or getattr(hw, "sensor_error", False):
                self.lbl_mon_ph_val.config(text="SENSOR ERROR", fg="#dc2626", font=("Helvetica", 18, "bold"))
            else:
                self.lbl_mon_ph_val.config(text=f"{hw.pv_ph:.2f}", fg="#0891b2", font=("Helvetica", 26, "bold"))

            if hw.pv_water_temp is None or getattr(hw, "sensor_error", False):
                self.lbl_mon_temp.config(text="SENSOR ERROR", fg="#dc2626", font=("Helvetica", 16, "bold"))
            else:
                self.lbl_mon_temp.config(text=f"{hw.pv_water_temp:.1f} °C", fg="#0f172a", font=("Helvetica", 22, "bold"))

            for ch, badge in self.mon_valve_badges.items():
                is_on = hw.get_relay(ch)
                badge.config(
                    text="ON" if is_on else "OFF",
                    bg=self.COLOR_SUCCESS if is_on else self.COLOR_OFF,
                    relief="sunken" if is_on else "raised"
                )

        if hasattr(self, "lbl_fert_phase_badge"):
            if hasattr(self, "lbl_fert_live_ec"):
                if hw.pv_ec is None or getattr(hw, "sensor_error", False):
                    self.lbl_fert_live_ec.config(text="SENSOR ERROR", fg="#dc2626", font=("Helvetica", 14, "bold"))
                else:
                    self.lbl_fert_live_ec.config(text=f"{hw.pv_ec:.3f} mS/cm", fg="#1565c0", font=("Helvetica", 19, "bold"))

            if hasattr(self, "lbl_fert_live_ph"):
                if hw.pv_ph is None or getattr(hw, "sensor_error", False):
                    self.lbl_fert_live_ph.config(text="SENSOR ERROR", fg="#dc2626", font=("Helvetica", 14, "bold"))
                else:
                    self.lbl_fert_live_ph.config(text=f"{hw.pv_ph:.2f}", fg="#0891b2", font=("Helvetica", 19, "bold"))

            if hasattr(self, "lbl_fert_live_temp"):
                if hw.pv_water_temp is None or getattr(hw, "sensor_error", False):
                    self.lbl_fert_live_temp.config(text="SENSOR ERROR", fg="#dc2626", font=("Helvetica", 14, "bold"))
                else:
                    self.lbl_fert_live_temp.config(text=f"{hw.pv_water_temp:.1f} °C", fg="#0f172a", font=("Helvetica", 19, "bold"))

            self.lbl_fert_phase_badge.config(
                text=f"PHASE: {engine.state}",
                fg="#10b981" if engine.state == "COMPLETED" else ("#38bdf8" if engine.is_running else "#ffffff")
            )
            self.lbl_fert_log.config(text=engine.status_msg)

            if engine.is_running:
                active_ch_names = []
                if engine.active_venturis.get(1): active_ch_names.append("EC1 (Ch 1)")
                if engine.active_venturis.get(2): active_ch_names.append("EC2 (Ch 2)")
                if engine.active_venturis.get(3): active_ch_names.append("pH Down (Ch 3)")
                if engine.active_venturis.get(4): active_ch_names.append("pH Up (Ch 4)")

                if active_ch_names:
                    self.lbl_fert_countdown.config(
                        text=f"Active Dosing: {', '.join(active_ch_names)}",
                        fg="#fbbf24"
                    )
                else:
                    self.lbl_fert_countdown.config(
                        text=f"Status: {engine.state}",
                        fg="#38bdf8"
                    )
            else:
                if getattr(self, "var_auto_fertigation", None) and self.var_auto_fertigation.get():
                    if getattr(self, "fert_cyclic_status_msg", None):
                        self.lbl_fert_countdown.config(
                            text=self.fert_cyclic_status_msg,
                            fg="#38bdf8"
                        )
                    else:
                        self.lbl_fert_countdown.config(
                            text="Status: AUTO MONITORING (Autonomous)",
                            fg="#34d399"
                        )
                else:
                    self.lbl_fert_countdown.config(
                        text="Dosing: Idle / Standby",
                        fg="#94a3b8"
                    )

            for v_num in [1, 2, 3, 4]:
                if v_num in self.labels_fert_v_status:
                    is_active = engine.active_venturis.get(v_num, False)
                    self.labels_fert_v_status[v_num].config(
                        text="DOSING" if is_active else "OFF",
                        bg=self.COLOR_SUCCESS if is_active else self.COLOR_OFF
                    )
                if v_num in self.labels_fert_v_safety:
                    saf_st = engine.venturi_safety_status.get(v_num, "OK")
                    self.labels_fert_v_safety[v_num].config(
                        text=saf_st,
                        fg=self.COLOR_DANGER if "TRIP" in saf_st else (self.COLOR_SUCCESS if saf_st in ["OK", "AT SETPOINT"] else "#1565c0")
                    )

            loop_on  = hw.get_relay(ActuatorMap.FERTIGATION_LOOP_VALVE)
            ret_on   = hw.get_relay(ActuatorMap.TANK_RETURN_VALVE)
            irr_on   = hw.get_relay(ActuatorMap.IRRIGATION_MASTER_VALVE)
            zone1_on = hw.get_relay(ActuatorMap.ZONE_1_VALVE)
            zone2_on = hw.get_relay(ActuatorMap.ZONE_2_VALVE)

            if hasattr(self, "lbl_deliv_loop"):
                self.lbl_deliv_loop.config(text=f"S.V 10: {'ON' if loop_on else 'OFF'}", fg=self.COLOR_SUCCESS if loop_on else self.COLOR_TEXT_SUB)
            if hasattr(self, "lbl_deliv_ret"):
                self.lbl_deliv_ret.config(text=f"S.V 7: {'ON' if ret_on else 'OFF'}", fg=self.COLOR_SUCCESS if ret_on else self.COLOR_TEXT_SUB)
            if hasattr(self, "lbl_deliv_irr"):
                self.lbl_deliv_irr.config(text=f"S.V 11: {'ON' if irr_on else 'OFF'}", fg=self.COLOR_SUCCESS if irr_on else self.COLOR_TEXT_SUB)
            if hasattr(self, "lbl_deliv_zone1"):
                self.lbl_deliv_zone1.config(text=f"Zone 1: {'ON' if zone1_on else 'OFF'}", fg=self.COLOR_SUCCESS if zone1_on else self.COLOR_TEXT_SUB)
            if hasattr(self, "lbl_deliv_zone2"):
                self.lbl_deliv_zone2.config(text=f"Zone 2: {'ON' if zone2_on else 'OFF'}", fg=self.COLOR_SUCCESS if zone2_on else self.COLOR_TEXT_SUB)

        if hasattr(self, "lbl_z1_state"):
            ts1 = irrigation_engine.timer_states.get("zone_1", {})
            st1 = ts1.get("state", "OFF")
            rem1 = ts1.get("time_left", 0.0)
            self.lbl_z1_state.config(
                text=st1,
                bg=self.COLOR_SUCCESS if st1 == "ON" else ("#1565c0" if st1 == "OFF" else self.COLOR_OFF)
            )
            m1, s1 = int(rem1 // 60), int(rem1 % 60)
            self.lbl_z1_rem.config(text=f"Rem: {m1:02d}:{s1:02d}")

            if hasattr(self, "btn_z1_run"):
                if st1 == "ON":
                    self.btn_z1_run.config(
                        text="⏹ Stop Zone 1 ",
                        bg="#fee2e2", fg="#b91c1c",
                        activebackground="#fecaca", activeforeground="#991b1b"
                    )
                else:
                    self.btn_z1_run.config(
                        text="▶ Start Zone 1 ",
                        bg="#dcfce7", fg="#15803d",
                        activebackground="#bbf7d0", activeforeground="#14532d"
                    )

        if hasattr(self, "lbl_z2_state"):
            ts2 = irrigation_engine.timer_states.get("zone_2", {})
            st2 = ts2.get("state", "OFF")
            rem2 = ts2.get("time_left", 0.0)
            self.lbl_z2_state.config(
                text=st2,
                bg=self.COLOR_SUCCESS if st2 == "ON" else ("#0891b2" if st2 == "OFF" else self.COLOR_OFF)
            )
            m2, s2 = int(rem2 // 60), int(rem2 % 60)
            self.lbl_z2_rem.config(text=f"Rem: {m2:02d}:{s2:02d}")

            if hasattr(self, "btn_z2_run"):
                if st2 == "ON":
                    self.btn_z2_run.config(
                        text="⏹ Stop Zone 2 ",
                        bg="#fee2e2", fg="#b91c1c",
                        activebackground="#fecaca", activeforeground="#991b1b"
                    )
                else:
                    self.btn_z2_run.config(
                        text="▶ Start Zone 2 ",
                        bg="#dcfce7", fg="#15803d",
                        activebackground="#bbf7d0", activeforeground="#14532d"
                    )

        if hasattr(self, "lbl_dash_status"):
            if engine.is_running:
                self.lbl_dash_status.config(text=f"ACTIVE: {engine.state}", bg="#0284c7")
            else:
                self.lbl_dash_status.config(text="SYSTEM READY", bg=self.COLOR_SUCCESS)

        self.after(100, self._periodic_tick)

if __name__ == "__main__":

    threading.Thread(target=start_bluetooth_server, daemon=True, name="BT_Server").start()
    threading.Thread(target=auto_trust_devices, daemon=True, name="BT_Trust").start()
    threading.Thread(target=network_watchdog, daemon=True, name="Net_Watchdog").start()

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
