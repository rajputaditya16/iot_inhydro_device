import os
import sys
import time
import json
import datetime
import threading
import collections
import subprocess
import logging
import faulthandler
import signal
import uuid as _uuid
import queue
import copy
import tkinter as tk
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    mqtt = None
    MQTT_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Stability diagnostics: application log and Python thread-stack dump.
logging.basicConfig(
    filename="/tmp/inhydro_hmi.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
)
_thread_trace_file = None
try:
    _thread_trace_file = open("/tmp/inhydro_thread_trace.log", "a", buffering=1)
    faulthandler.enable(_thread_trace_file, all_threads=True)
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, file=_thread_trace_file,
                              all_threads=True, chain=False)
except Exception:
    logging.exception("Could not enable thread diagnostics")

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
CONFIG_FILE = os.path.join(BASE_DIR, f"config_{DEVICE_NAME}.json")
CLIMATE_CONFIG_FILE = os.path.join(BASE_DIR, "config_climate.json")
TIMERS_FILE = os.path.join(BASE_DIR, "config_timers.json")
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")

running = True

# MQTT/store-and-forward support. Network callbacks only enqueue messages;
# all control-state changes are applied by the HMI/control scheduler thread.
LOG_DIR = os.path.join(BASE_DIR, "local_logs")
ACTIVE_LOG_FILE = os.path.join(LOG_DIR, "active.jsonl")
os.makedirs(LOG_DIR, exist_ok=True)
local_log_lock = threading.Lock()
mqtt_inbound_queue = queue.Queue(maxsize=250)
is_mqtt_connected = False
control_client = None

CONTROL_BROKER = os.getenv("INHYDRO_MQTT_BROKER", "147.93.106.142")
CONTROL_PORT = int(os.getenv("INHYDRO_MQTT_PORT", "1883"))
CONTROL_USER = os.getenv("INHYDRO_MQTT_USER", "Inhydro@5598")
CONTROL_PASS = os.getenv("INHYDRO_MQTT_PASS", "MGPL@5598")

COLOR_INHYDRO_NAVY      = "#1E3A5F"
COLOR_INHYDRO_NAVY_DARK = "#14263E"
COLOR_INHYDRO_GREEN     = "#4CAF50"
COLOR_INHYDRO_GREEN_DARK= "#388E3C"
COLOR_INHYDRO_WATER     = "#42A5F5"
COLOR_INHYDRO_WATER_BG  = "#E3F2FD"
COLOR_BG_LIGHT          = "#F4F7FA"
COLOR_OFF               = "#64748B"
COLOR_DANGER            = "#DC2626"

class RelayMap:
    MASTER_CH0 = 0  
    SV1        = 1  
    SV2        = 2  
    SV4        = 3  
    SV3        = 4  
    ACF        = 5
    SV5        = 6

RELAY_NAMES = {
    0: "Ch 0 (Master)",
    1: "SV 1 (Valve 1)",
    2: "SV 2 (Irrigation)",
    3: "SV 4 (Fogger)",
    4: "SV 3 (Fertigation)",
    5: "ACF Fan",
    6: "SV 5 (Irrigation/Fertigation)"
}

DEFAULT_CONFIG = {
    "serial_port": "/dev/relayboard",
    "relay_slave_id": 1,
    "relay_baudrate": 9600,
    "sensor_port": "/dev/md02sensor",
    "sensor_slave_id": 1,
    "sensor_baudrate": 9600,
    "sv1_delay_sec": 10,
    "fert_duration_sec": 12,
    "irrig_duration_sec": 12,
    "simulation_mode": False,
    "active_crop": "cucumber"
}

DEFAULT_CYCLIC_TIMERS = {
    "fertigation": {
        "name": "Cyclic Fertigation",
        "enabled": False,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 2.0,
        "off_min": 60.0
    },
    "irrigation": {
        "name": "Cyclic Irrigation",
        "enabled": False,
        "start_time": "06:00",
        "stop_time": "18:00",
        "on_min": 2.0,
        "off_min": 30.0
    }
}

DEFAULT_CLIMATE_SETPOINTS = {
    "fogger_trigger_mode": "BOTH",
    "acf_trigger_mode": "SENSOR",
    "HUMI Name": "FOGGER TIMER",
    "HUMI D_Start": "06:00",
    "HUMI D_Stop": "18:00",
    "HUMI D_ON Min": 10.0,
    "HUMI D_OFF Min": 20.0,
    "HUMI D_Max": 75.0,
    "HUMI D_Min": 55.0,
    "HUMI N_Start": "18:00",
    "HUMI N_Stop": "06:00",
    "HUMI N_ON Min": 5.0,
    "HUMI N_OFF Min": 40.0,
    "HUMI N_Max": 80.0,
    "HUMI N_Min": 60.0,
    "ACF Name": "AIR CIRCULATION FAN",
    "ACF Start": "06:00",
    "ACF Stop": "22:00",
    "ACF ON Min": 10.0,
    "ACF OFF Min": 20.0,
    "ACF Temp Min": 22.0,
    "ACF Temp Max": 28.0
}

def load_json(filepath, default_data):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in default_data.items():
                        if k not in data: data[k] = v
                    return data
        except Exception: pass
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
        logging.exception("JSON save failed: %s", filepath)
        print(f"[JSON ERROR] {filepath}: {e}")
        return False

system_config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
cyclic_timer_cfg = load_json(TIMERS_FILE, DEFAULT_CYCLIC_TIMERS)
climate_setpoints = load_json(CLIMATE_CONFIG_FILE, DEFAULT_CLIMATE_SETPOINTS)

_serial_lock = threading.Lock()

def _calc_crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if (crc & 1) != 0:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])

class HardwareController:
    """Non-blocking hardware manager: one ordered relay worker and one sensor worker."""
    def __init__(self):
        self.relays = {i: False for i in range(7)}
        self._relay_state_lock = threading.Lock()
        self._relay_queue = queue.Queue()
        self._relay_worker_started = False
        self.pv_room_temp = None
        self.pv_room_humi = None
        self.md02_error = True
        self.md02_last_seen = 0.0
        self.room_temp_history = collections.deque(maxlen=3)
        self.room_humi_history = collections.deque(maxlen=3)
        self._sensor_lock = threading.Lock()
        self._last_sensor_error_log = 0.0
        self.started = False
        self.startup_all_off_done = threading.Event()
        self.relay_startup_ok = False
        self.relay_last_error = "Startup ALL-OFF has not completed"

    def start(self):
        """Start I/O workers and physically command every relay OFF first."""
        if self.started:
            return self.startup_all_off_done.wait(timeout=5.0) and self.relay_startup_ok
        self.started = True
        self._relay_worker_started = True
        # Queue the safe-state command before starting the worker. No automatic
        # control is armed at boot, so this is the first relay-board operation.
        self._relay_queue.put(("ALL_OFF", False))
        threading.Thread(target=self._relay_worker, daemon=False, name="RelayWorker").start()
        threading.Thread(target=self._sensor_polling_loop, daemon=True, name="SensorPoller").start()
        completed = self.startup_all_off_done.wait(timeout=5.0)
        if not completed:
            self.relay_last_error = "Timed out waiting for startup ALL-OFF"
            logging.error(self.relay_last_error)
            return False
        if not self.relay_startup_ok:
            logging.error("Startup ALL-OFF failed: %s", self.relay_last_error)
            return False
        logging.info("Hardware workers started; all seven relays commanded OFF")
        return True

    def set_relay(self, ch: int, state: bool):
        if not isinstance(ch, int) or not (0 <= ch <= 6):
            logging.error("Rejected invalid relay channel: %r", ch)
            return
        state = bool(state)
        if state and self.startup_all_off_done.is_set() and not self.relay_startup_ok:
            logging.error("Relay ON rejected: startup ALL-OFF/relay communication not confirmed (CH%s)", ch)
            return
        with self._relay_state_lock:
            if self.relays.get(ch) == state:
                return
            self.relays[ch] = state
        # Queue is unbounded; this call never waits for serial I/O.
        self._relay_queue.put((ch, state))

    def get_relay(self, ch: int) -> bool:
        with self._relay_state_lock:
            return bool(self.relays.get(ch, False))

    def emergency_all_off(self):
        with self._relay_state_lock:
            for ch in range(7):
                self.relays[ch] = False
        # Discard pending ON/OFF commands so ALL_OFF is the next operation.
        while True:
            try:
                self._relay_queue.get_nowait()
                self._relay_queue.task_done()
            except queue.Empty:
                break
        self._relay_queue.put(("ALL_OFF", False))
        logging.warning("Emergency ALL OFF queued")

    def _open_relay_serial(self):
        port = str(system_config.get("serial_port", "/dev/relayboard"))
        baud = int(system_config.get("relay_baudrate", 9600))
        if not SERIAL_AVAILABLE or not os.path.exists(port) or os.path.isdir(port):
            raise OSError(f"Relay serial port unavailable: {port}")
        return serial.Serial(port, baudrate=baud, bytesize=8, parity=serial.PARITY_NONE,
                             stopbits=1, timeout=0.15, write_timeout=0.25)

    def _write_coil(self, ser, slave_id, coil, state):
        value = 0xFF if state else 0x00
        frame = bytes([slave_id, 0x05, 0x00, coil, value, 0x00])
        request = frame + _calc_crc16(frame)
        ser.reset_input_buffer()
        ser.write(request)
        ser.flush()
        # FC05 must echo the exact request. Treat missing/bad echo as a
        # communication fault instead of assuming that a relay changed state.
        response = self._read_exact(ser, 8)
        if response != request:
            raise IOError(f"Relay CH{coil} acknowledgement mismatch: {response.hex()}")

    def _relay_worker(self):
        while True:
            try:
                cmd = self._relay_queue.get(timeout=0.5)
            except queue.Empty:
                if not running:
                    break
                continue
            ch, state = cmd if cmd is not None else (None, False)
            command_ok = False
            try:
                if cmd is None:
                    break
                slave_id = int(system_config.get("relay_slave_id", 1))
                with _serial_lock:
                    ser = self._open_relay_serial()
                    try:
                        if ch == "ALL_OFF":
                            all_off_ok = True
                            for coil in range(7):
                                try:
                                    self._write_coil(ser, slave_id, coil, False)
                                except Exception as coil_exc:
                                    all_off_ok = False
                                    logging.error("Startup ALL-OFF failed for CH%s: %s", coil, coil_exc)
                            command_ok = all_off_ok
                            if all_off_ok:
                                logging.warning("Relay board: all 7 channels acknowledged OFF")
                        else:
                            self._write_coil(ser, slave_id, int(ch), bool(state))
                            logging.info("Relay channel %s commanded %s", ch, "ON" if state else "OFF")
                        command_ok = True
                    finally:
                        ser.close()
                if ch == "ALL_OFF":
                    self.relay_startup_ok = command_ok
                    self.relay_last_error = "" if command_ok else "Startup ALL-OFF write failed"
            except Exception as exc:
                self.relay_last_error = str(exc)
                if ch == "ALL_OFF":
                    self.relay_startup_ok = False
                logging.exception("Relay command failed: %r", cmd)
            finally:
                if ch == "ALL_OFF":
                    self.startup_all_off_done.set()
                self._relay_queue.task_done()

    @staticmethod
    def _read_exact(ser, count):
        data = bytearray()
        deadline = time.monotonic() + max(0.5, float(getattr(ser, "timeout", 0.1)) * 3)
        while len(data) < count and time.monotonic() < deadline:
            chunk = ser.read(count - len(data))
            if chunk:
                data.extend(chunk)
        return bytes(data)

    def _read_sensor_registers(self, ser, slave_id, start_register=0):
        # WIN-SN-TNH-M: FC03, register 0 temperature, register 1 humidity.
        request = bytes([slave_id, 0x03, 0x00, start_register, 0x00, 0x02])
        ser.reset_input_buffer()
        ser.write(request + _calc_crc16(request))
        ser.flush()
        response = self._read_exact(ser, 9)
        if len(response) != 9:
            raise IOError(f"Incomplete Modbus response ({len(response)}/9 bytes)")
        if response[0] != slave_id or response[1] != 0x03 or response[2] != 4:
            raise IOError(f"Unexpected Modbus response header: {response.hex()}")
        if _calc_crc16(response[:-2]) != response[-2:]:
            raise IOError("WIN-SN-TNH-M response CRC mismatch")
        return [(response[3] << 8) | response[4], (response[5] << 8) | response[6]]

    def _sensor_polling_loop(self):
        while running:
            read_ok = False
            try:
                port = str(system_config.get("sensor_port", "/dev/md02sensor"))
                slave_id = int(system_config.get("sensor_slave_id", 1))
                baud = int(system_config.get("sensor_baudrate", 9600))
                if SERIAL_AVAILABLE and os.path.exists(port) and not os.path.isdir(port):
                    ser = None
                    try:
                        # Sensor has its own USB-RS485 adapter, independent of relay I/O.
                        ser = serial.Serial(port, baudrate=baud, bytesize=8,
                                            parity=serial.PARITY_NONE, stopbits=1,
                                            timeout=0.20, write_timeout=0.25)
                        with self._sensor_lock:
                            raw_t, raw_h = self._read_sensor_registers(ser, slave_id, 0)
                        if raw_t > 32767:
                            raw_t -= 65536
                        temp_c = raw_t / 10.0
                        humi_rh = raw_h / 10.0
                        if -40.0 <= temp_c <= 85.0 and 0.0 <= humi_rh <= 100.0:
                            self.room_temp_history.append(temp_c)
                            self.room_humi_history.append(humi_rh)
                            self.pv_room_temp = round(sum(self.room_temp_history) / len(self.room_temp_history), 1)
                            self.pv_room_humi = round(sum(self.room_humi_history) / len(self.room_humi_history), 1)
                            self.md02_last_seen = time.time()
                            self.md02_error = False
                            read_ok = True
                        else:
                            raise ValueError(f"Sensor value out of range: T={temp_c}, RH={humi_rh}")
                    finally:
                        if ser is not None:
                            try:
                                ser.close()
                            except Exception:
                                pass
                else:
                    raise OSError(f"Sensor serial port unavailable: {port}")
            except Exception as exc:
                now = time.time()
                if now - self._last_sensor_error_log >= 10:
                    logging.warning("WIN-SN-TNH-M read failed: %s", exc)
                    self._last_sensor_error_log = now

            if not read_ok and time.time() - self.md02_last_seen > 5.0:
                self.pv_room_temp = None
                self.pv_room_humi = None
                self.md02_error = True
            time.sleep(1.0)

hw = HardwareController()

class ProcessEngine:
    def __init__(self, hardware: HardwareController):
        self.hw = hardware
        self.current_mode = "IDLE"
        self.step = 0
        self.start_time = 0.0
        self.status_msg = "System Ready"

    def start_fertigation(self) -> tuple:
        if self.current_mode != "IDLE":
            return False, f"Cannot start: {self.current_mode} is active!"
        # Water process and fogging are mutually exclusive on the shared valve manifold.
        if 'climate_engine' in globals() and climate_engine.fogger_active:
            climate_engine.fogger_active = False
            for ch in (RelayMap.SV1, RelayMap.SV2, RelayMap.SV3, RelayMap.SV4):
                self.hw.set_relay(ch, False)
        self.current_mode = "FERTIGATION"
        self.start_time = time.time()
        self.step = 1
        self.hw.set_relay(RelayMap.MASTER_CH0, True)
        self.hw.set_relay(RelayMap.SV3, True)
        self.hw.set_relay(RelayMap.SV2, False)
        self.hw.set_relay(RelayMap.SV4, False)
        self.hw.set_relay(RelayMap.SV1, False)
        self.hw.set_relay(RelayMap.SV5, True)
        self.status_msg = "Fertigation: Line Active (Ch 0, SV3=ON, SV5=ON). Waiting for SV1 Delay..."
        return True, "Fertigation started"

    def start_irrigation(self) -> tuple:
        if self.current_mode != "IDLE":
            return False, f"Cannot start: {self.current_mode} is active!"
        # Water process and fogging are mutually exclusive on the shared valve manifold.
        if 'climate_engine' in globals() and climate_engine.fogger_active:
            climate_engine.fogger_active = False
            for ch in (RelayMap.SV1, RelayMap.SV2, RelayMap.SV3, RelayMap.SV4):
                self.hw.set_relay(ch, False)
        self.current_mode = "IRRIGATION"
        self.start_time = time.time()
        self.step = 1
        self.hw.set_relay(RelayMap.MASTER_CH0, True)
        self.hw.set_relay(RelayMap.SV2, True)
        self.hw.set_relay(RelayMap.SV3, False)
        self.hw.set_relay(RelayMap.SV4, False)
        self.hw.set_relay(RelayMap.SV1, False)
        self.hw.set_relay(RelayMap.SV5, True)
        self.status_msg = "Irrigation: Line Active (Ch 0, SV2=ON, SV5=ON). Waiting for SV1 Delay..."
        return True, "Irrigation started"

    def stop_cycle(self, user_aborted=False):
        self.hw.set_relay(RelayMap.MASTER_CH0, False)
        self.hw.set_relay(RelayMap.SV1, False)
        self.hw.set_relay(RelayMap.SV2, False)
        self.hw.set_relay(RelayMap.SV3, False)
        self.hw.set_relay(RelayMap.SV4, False)
        self.hw.set_relay(RelayMap.SV5, False)
        prev = self.current_mode
        self.current_mode = "IDLE"
        self.step = 0
        self.status_msg = f"{prev} aborted by operator." if user_aborted else f"{prev} cycle completed successfully."

    def process_tick(self):
        if self.current_mode == "IDLE":
            return
        now_sec = time.time()
        elapsed = now_sec - self.start_time
        delay_t = float(system_config.get("sv1_delay_sec", 10))

        if self.current_mode == "FERTIGATION":
            total_dur = float(system_config.get("fert_duration_sec", 12))
            if self.step == 1 and elapsed >= delay_t:
                self.hw.set_relay(RelayMap.SV1, True)
                self.step = 2
                self.status_msg = "Fertigation: SV1 ON (Full Delivery Active)"
            if elapsed >= total_dur:
                self.stop_cycle()
        elif self.current_mode == "IRRIGATION":
            total_dur = float(system_config.get("irrig_duration_sec", 12))
            if self.step == 1 and elapsed >= delay_t:
                self.hw.set_relay(RelayMap.SV1, True)
                self.step = 2
                self.status_msg = "Irrigation: SV1 ON (Full Delivery Active)"
            if elapsed >= total_dur:
                self.stop_cycle()

process_engine = ProcessEngine(hw)

class CyclicTimerEngine:
    def __init__(self, hardware: HardwareController, engine: ProcessEngine):
        self.hw = hardware
        self.engine = engine
        self.timer_state = {
            "fertigation": {"state": "OFF", "last_toggle": 0.0, "time_left": 0.0},
            "irrigation":  {"state": "OFF", "last_toggle": 0.0, "time_left": 0.0}
        }

    def process_tick(self):
        now_dt = datetime.datetime.now()
        cur_time = now_dt.time()
        now_sec = time.time()

        for mode_key in ["fertigation", "irrigation"]:
            cfg = cyclic_timer_cfg.get(mode_key, {})
            ts = self.timer_state[mode_key]

            if not cfg.get("enabled", False):
                ts["state"] = "DISABLED"
                ts["time_left"] = 0.0
                continue

            try:
                t_start = datetime.datetime.strptime(cfg.get("start_time", "06:00"), "%H:%M").time()
                t_stop  = datetime.datetime.strptime(cfg.get("stop_time", "18:00"), "%H:%M").time()
            except Exception:
                t_start, t_stop = datetime.time(0, 0), datetime.time(23, 59)

            in_window = (t_start <= cur_time <= t_stop) if t_start <= t_stop else (cur_time >= t_start or cur_time <= t_stop)
            on_sec = float(cfg.get("on_min", 2.0)) * 60.0
            off_sec = float(cfg.get("off_min", 30.0)) * 60.0

            if in_window:
                if ts["state"] in ["OFF", "WINDOW_CLOSED", "DISABLED"]:
                    if ts["last_toggle"] == 0.0 or (now_sec - ts["last_toggle"] >= off_sec):
                        if self.engine.current_mode == "IDLE":
                            ts["state"] = "ON"
                            ts["last_toggle"] = now_sec
                            if mode_key == "fertigation":
                                self.engine.start_fertigation()
                            else:
                                self.engine.start_irrigation()
                    else:
                        ts["state"] = "OFF"
                elif ts["state"] == "ON":
                    if now_sec - ts["last_toggle"] >= on_sec:
                        ts["state"] = "OFF"
                        ts["last_toggle"] = now_sec
                        if self.engine.current_mode.lower() == mode_key:
                            self.engine.stop_cycle()
                ts["time_left"] = max(0.0, (on_sec if ts["state"] == "ON" else off_sec) - (now_sec - ts["last_toggle"]))
            else:
                ts["state"] = "WINDOW_CLOSED"
                ts["last_toggle"] = 0.0
                ts["time_left"] = 0.0
                if self.engine.current_mode.lower() == mode_key:
                    self.engine.stop_cycle()

cyclic_engine = CyclicTimerEngine(hw, process_engine)

class ClimateAutomationEngine:
    def __init__(self, hardware: HardwareController):
        self.hw = hardware
        self.setpoints = climate_setpoints
        self.timer_state = {
            "fogger": {"state": "OFF", "last": 0.0},
            "acf": {"state": "OFF", "last": 0.0}
        }
        # Safe boot policy: both climate outputs start in MANUAL OFF.
        # Operator must explicitly select AUTO for each controller.
        self.humi_logic_active = False
        self.humi_logic_initialized = False
        self.acf_temp_state = False
        self.manual_fogger = False
        self.manual_acf = False
        self.fogger_active = False
        self.fogger_start_time = 0.0
        self.fogger_status_msg = "STARTUP SAFE: FOGGER OFF - SELECT AUTO TO ENABLE"
        self.acf_status_msg = "STARTUP SAFE: ACF OFF - SELECT AUTO TO ENABLE"

    def set_manual_fogger(self, state):
        # None means AUTO; True/False are explicit manual overrides.
        if state is None:
            self.timer_state["fogger"] = {"state": "OFF", "last": 0.0}
            self.humi_logic_initialized = False
        self.manual_fogger = state

    def set_manual_acf(self, state):
        if state is None:
            self.acf_temp_state = False
        self.manual_acf = state

    def process_tick(self):
        now_dt = datetime.datetime.now()
        cur_time = now_dt.time()
        now_sec = time.time()
        room_humi = self.hw.pv_room_humi
        room_temp = self.hw.pv_room_temp
        sensor_ok = (room_humi is not None and room_temp is not None
                     and not getattr(self.hw, "md02_error", True))

        # Do not run any automatic process before the physical startup ALL-OFF
        # command has completed successfully.
        if self.hw.started and (not self.hw.startup_all_off_done.is_set() or not self.hw.relay_startup_ok):
            self.fogger_active = False
            self.fogger_status_msg = "RELAY BOARD NOT READY - ALL OUTPUTS INHIBITED"
            self.acf_status_msg = "RELAY BOARD NOT READY - ACF OFF"
            return

        def is_within(s_str, e_str):
            try:
                ts = datetime.datetime.strptime(str(s_str).strip(), "%H:%M").time()
                te = datetime.datetime.strptime(str(e_str).strip(), "%H:%M").time()
                return (ts <= cur_time <= te) if ts <= te else (cur_time >= ts or cur_time <= te)
            except Exception:
                return False

        d_start = str(self.setpoints.get("HUMI D_Start", "06:00"))
        d_stop = str(self.setpoints.get("HUMI D_Stop", "18:00"))
        n_start = str(self.setpoints.get("HUMI N_Start", "18:00"))
        n_stop = str(self.setpoints.get("HUMI N_Stop", "06:00"))
        in_day = is_within(d_start, d_stop)
        in_night = is_within(n_start, n_stop)
        in_window = in_day or in_night

        if in_night and not in_day:
            mode = "NIGHT"
            on_min = float(self.setpoints.get("HUMI N_ON Min", 5.0))
            off_min = float(self.setpoints.get("HUMI N_OFF Min", 40.0))
            h_max = float(self.setpoints.get("HUMI N_Max", 80.0))
            h_min = float(self.setpoints.get("HUMI N_Min", 60.0))
        else:
            mode = "DAY"
            on_min = float(self.setpoints.get("HUMI D_ON Min", 10.0))
            off_min = float(self.setpoints.get("HUMI D_OFF Min", 20.0))
            h_max = float(self.setpoints.get("HUMI D_Max", 75.0))
            h_min = float(self.setpoints.get("HUMI D_Min", 55.0))

        # Hysteresis starts safely OFF on the first valid sensor sample.
        # It turns ON only when humidity is at/below Hmin and OFF at/above Hmax.
        humidity_setpoint_ok = h_min < h_max
        if not humidity_setpoint_ok:
            self.humi_logic_active = False
            self.fogger_status_msg = f"SETPOINT ERROR: {mode} HUMIDITY MIN MUST BE BELOW MAX"
        elif not sensor_ok:
            self.humi_logic_active = False
            self.fogger_status_msg = "SENSOR FAULT: FOGGER OFF"
        else:
            if not self.humi_logic_initialized:
                self.humi_logic_active = (room_humi <= h_min)
                self.humi_logic_initialized = True
            elif room_humi >= h_max:
                self.humi_logic_active = False
            elif room_humi <= h_min:
                self.humi_logic_active = True

        # BOTH is deliberately AND: humidity must request fogging AND the
        # cyclic timer must be in its ON phase. Timers are held while manual OFF.
        ts_fog = self.timer_state["fogger"]
        fogger_cyclic_on = False
        fogger_auto_selected = (self.manual_fogger is None)
        if not fogger_auto_selected:
            ts_fog["state"] = "OFF"
            ts_fog["last"] = 0.0
        elif on_min <= 0:
            ts_fog["state"] = "OFF"
            ts_fog["last"] = now_sec
        elif in_window and sensor_ok:
            run_sec = on_min * 60.0
            off_sec = max(0.0, off_min) * 60.0
            if ts_fog["state"] == "OFF":
                if ts_fog["last"] == 0.0 or (now_sec - ts_fog["last"] >= off_sec):
                    ts_fog["state"] = "ON"
                    ts_fog["last"] = now_sec
            elif ts_fog["state"] == "ON" and now_sec - ts_fog["last"] >= run_sec:
                ts_fog["state"] = "OFF"
                ts_fog["last"] = now_sec
            fogger_cyclic_on = (ts_fog["state"] == "ON")
        else:
            ts_fog["state"] = "OFF"
            ts_fog["last"] = now_sec

        fog_trigger_mode = str(self.setpoints.get("fogger_trigger_mode", "BOTH")).upper()
        if not sensor_ok:
            fogger_target = False
            self.fogger_status_msg = "SENSOR FAULT: FOGGER OFF (CHECK TEMP/HUMIDITY SENSOR)"
        elif not humidity_setpoint_ok:
            fogger_target = False
        elif self.manual_fogger is not None:
            fogger_target = bool(self.manual_fogger)
            self.fogger_status_msg = f"MANUAL {'ON' if fogger_target else 'OFF'}"
        elif not in_window:
            fogger_target = False
            self.fogger_status_msg = f"{mode} WINDOW CLOSED"
        elif fog_trigger_mode == "SENSOR":
            fogger_target = bool(self.humi_logic_active)
            self.fogger_status_msg = f"SENSOR MODE: {'ACTIVE' if fogger_target else 'STANDBY'}"
        elif fog_trigger_mode == "CYCLIC":
            fogger_target = bool(fogger_cyclic_on)
            self.fogger_status_msg = f"CYCLIC {ts_fog['state']}"
        else:
            # User-confirmed BOTH mode = humidity AND cyclic timer.
            fogger_target = bool(self.humi_logic_active and fogger_cyclic_on)
            self.fogger_status_msg = f"{mode} BOTH (HUMIDITY AND CYCLIC): {'ACTIVE' if fogger_target else 'STANDBY'}"

        # Irrigation/fertigation has priority over fogging. Keep the request
        # pending; when the process finishes the live sensor/timer conditions
        # are evaluated again before fogging starts.
        process_busy = process_engine.current_mode != "IDLE"
        if fogger_target and process_busy:
            self.fogger_status_msg = f"FOGGING WILL START AFTER {process_engine.current_mode}"
            if self.fogger_active:
                self.fogger_active = False
        elif fogger_target:
            if not self.fogger_active:
                self.fogger_active = True
                self.fogger_start_time = now_sec
                self.hw.set_relay(RelayMap.MASTER_CH0, True)
                self.hw.set_relay(RelayMap.SV2, True)
                self.hw.set_relay(RelayMap.SV4, True)
                self.hw.set_relay(RelayMap.SV3, False)
                self.hw.set_relay(RelayMap.SV1, False)
                self.hw.set_relay(RelayMap.SV5, False)
            delay_t = max(0.0, float(system_config.get("sv1_delay_sec", 10)))
            if now_sec - self.fogger_start_time >= delay_t:
                self.hw.set_relay(RelayMap.SV1, True)
                if self.fogger_status_msg.startswith("FOGGER STARTING"):
                    self.fogger_status_msg = "FOGGER ON"
            else:
                self.fogger_status_msg = f"FOGGER STARTING: SV1 DELAY {max(0, int(delay_t - (now_sec - self.fogger_start_time)))}s"
        else:
            if self.fogger_active:
                self.fogger_active = False
                if process_engine.current_mode == "IDLE":
                    self.hw.set_relay(RelayMap.MASTER_CH0, False)
                    self.hw.set_relay(RelayMap.SV1, False)
                    self.hw.set_relay(RelayMap.SV2, False)
                    self.hw.set_relay(RelayMap.SV4, False)
            # A manual OFF / idle automatic state also actively maintains OFF.
            if process_engine.current_mode == "IDLE":
                for ch in (RelayMap.SV1, RelayMap.SV2, RelayMap.SV4):
                    self.hw.set_relay(ch, False)
                if not self.fogger_active:
                    self.hw.set_relay(RelayMap.MASTER_CH0, False)

        acf_t_min = float(self.setpoints.get("ACF Temp Min", 22.0))
        acf_t_max = float(self.setpoints.get("ACF Temp Max", 28.0))
        acf_setpoint_ok = acf_t_min < acf_t_max
        if sensor_ok and acf_setpoint_ok:
            if room_temp >= acf_t_max:
                self.acf_temp_state = True
            elif room_temp <= acf_t_min:
                self.acf_temp_state = False
        else:
            self.acf_temp_state = False

        # Sensor failure is fail-safe OFF. Otherwise fogger takes priority over
        # manual ACF OFF and forces the fan ON. When fogging ends, AUTO resumes
        # its own independent temperature hysteresis state.
        if not sensor_ok:
            acf_target = False
            self.acf_status_msg = "SENSOR FAULT: ACF OFF"
        elif not acf_setpoint_ok:
            acf_target = False
            self.acf_status_msg = "SETPOINT ERROR: ACF TEMP MIN MUST BE BELOW MAX"
        elif self.fogger_active:
            acf_target = True
            self.acf_status_msg = "FOGGER INTERLOCK: ACF FORCED ON"
        elif self.manual_acf is not None:
            acf_target = bool(self.manual_acf)
            self.acf_status_msg = f"MANUAL {'ON' if acf_target else 'OFF'}"
        else:
            acf_target = bool(self.acf_temp_state)
            self.acf_status_msg = (
                f"AUTO: TEMP {room_temp:.1f}°C | ON at {acf_t_max:.1f}°C, "
                f"OFF at {acf_t_min:.1f}°C"
            )
        self.hw.set_relay(RelayMap.ACF, acf_target)

climate_engine = ClimateAutomationEngine(hw)

# ==============================================================================
# MQTT CLOUD TELEMETRY + OFFLINE STORE-AND-FORWARD
# ==============================================================================
def get_current_state_payload():
    now_dt = datetime.datetime.now()
    return {
        "source": "device", "device": DEVICE_NAME, "device_id": DEVICE_NAME,
        "timestamp": now_dt.isoformat(), "time": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "sensor_data": {"temp": hw.pv_room_temp if not hw.md02_error else None,
                        "humi": hw.pv_room_humi if not hw.md02_error else None,
                        "status": "OK" if not hw.md02_error else "OFFLINE"},
        "system_config": copy.deepcopy(system_config),
        "cyclic_timers": copy.deepcopy(cyclic_timer_cfg),
        "climate_setpoints": copy.deepcopy(climate_setpoints),
        "process_state": {"mode": process_engine.current_mode,
                           "status_msg": process_engine.status_msg,
                           "elapsed_sec": int(time.time() - process_engine.start_time) if process_engine.current_mode != "IDLE" else 0},
        "climate_state": {"fogger_active": climate_engine.fogger_active,
                          "fogger_status": climate_engine.fogger_status_msg,
                          "acf_active": hw.get_relay(RelayMap.ACF),
                          "acf_status": climate_engine.acf_status_msg},
        "relays": {f"ch_{i}": hw.get_relay(i) for i in range(7)}
    }

def broadcast_current_state():
    client = control_client
    if not is_mqtt_connected or client is None:
        return
    try:
        payload = json.dumps(get_current_state_payload(), separators=(",", ":"))
        client.publish(f"inhydro/{DEVICE_NAME}/state", payload, qos=1, retain=True)
        client.publish(f"inhydro/{DEVICE_NAME}/telemetry/live", payload, qos=0, retain=False)
    except Exception:
        logging.exception("MQTT state broadcast failed")

def save_local_telemetry():
    try:
        record = json.dumps(get_current_state_payload(), separators=(",", ":"))
        with local_log_lock:
            with open(ACTIVE_LOG_FILE, "a", encoding="utf-8") as stream:
                stream.write(record + "\n")
            if os.path.getsize(ACTIVE_LOG_FILE) >= 1_500_000:
                rotated = os.path.join(LOG_DIR, f"log_{int(time.time())}_{_uuid.uuid4().hex[:5]}.jsonl")
                os.replace(ACTIVE_LOG_FILE, rotated)
    except Exception:
        logging.exception("Local telemetry save failed")

def _mqtt_on_message(client, userdata, msg):
    # Never run actuator or Tkinter code on Paho's network thread.
    try:
        mqtt_inbound_queue.put_nowait((str(msg.topic), bytes(msg.payload), bool(getattr(msg, "retain", False))))
    except queue.Full:
        logging.error("MQTT inbound queue full; incoming message dropped: %s", msg.topic)

def _mqtt_on_connect(client, userdata, flags, reason_code, properties=None):
    global is_mqtt_connected
    try:
        rc = int(reason_code)
    except Exception:
        rc = 0 if str(reason_code).lower() in ("success", "0") else 1
    is_mqtt_connected = (rc == 0)
    if is_mqtt_connected:
        for suffix in ("command", "config/update", "setpoints/update", "request_sync"):
            client.subscribe(f"inhydro/{DEVICE_NAME}/{suffix}", qos=1)
        logging.info("MQTT connected; command/config topics subscribed")
        broadcast_current_state()
    else:
        logging.error("MQTT connection rejected: %s", reason_code)

def _mqtt_on_disconnect(client, userdata, *args):
    global is_mqtt_connected
    is_mqtt_connected = False
    logging.warning("MQTT disconnected")

def start_mqtt_client():
    global control_client
    if not MQTT_AVAILABLE:
        logging.error("paho-mqtt is not installed; cloud features disabled")
        return
    try:
        try:
            control_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                         client_id=f"InHydro_{DEVICE_NAME}_{_uuid.uuid4().hex[:6]}")
        except (AttributeError, TypeError):
            control_client = mqtt.Client(client_id=f"InHydro_{DEVICE_NAME}_{_uuid.uuid4().hex[:6]}")
        control_client.on_message = _mqtt_on_message
        control_client.on_connect = _mqtt_on_connect
        control_client.on_disconnect = _mqtt_on_disconnect
        if CONTROL_USER and CONTROL_PASS:
            control_client.username_pw_set(CONTROL_USER, CONTROL_PASS)
        control_client.reconnect_delay_set(min_delay=2, max_delay=60)
        control_client.connect_async(CONTROL_BROKER, CONTROL_PORT, keepalive=60)
        control_client.loop_start()
        logging.info("MQTT client loop started for broker %s:%s", CONTROL_BROKER, CONTROL_PORT)
    except Exception:
        logging.exception("Unable to start MQTT client")

def _apply_mqtt_message(topic, payload_bytes, retained):
    global system_config, cyclic_timer_cfg, climate_setpoints
    if retained:
        return
    if topic.endswith(("/telemetry", "/telemetry/live", "/heartbeat", "/command/status", "/state")):
        return
    try:
        raw = payload_bytes.decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"action": raw.strip()}
        if not isinstance(data, dict) or data.get("source") == "device":
            return

        if topic.endswith("/command"):
            action = str(data.get("action", "")).lower().strip()
            logging.info("MQTT command received: %s", action)
            if action in ("start_fertigation", "start_fert"):
                ok, detail = process_engine.start_fertigation()
            elif action in ("start_irrigation", "start_irrig"):
                ok, detail = process_engine.start_irrigation()
            elif action in ("stop", "stop_cycle", "abort"):
                process_engine.stop_cycle(user_aborted=True); ok, detail = True, "Stopped"
            elif action == "fogger_on":
                climate_engine.set_manual_fogger(True); ok, detail = True, "Fogger forced ON"
            elif action == "fogger_off":
                climate_engine.set_manual_fogger(False); ok, detail = True, "Fogger forced OFF"
            elif action == "fogger_auto":
                climate_engine.set_manual_fogger(None); ok, detail = True, "Fogger AUTO"
            elif action == "acf_on":
                climate_engine.set_manual_acf(True); ok, detail = True, "ACF forced ON"
            elif action == "acf_off":
                climate_engine.set_manual_acf(False); ok, detail = True, "ACF forced OFF"
            elif action == "acf_auto":
                climate_engine.set_manual_acf(None); ok, detail = True, "ACF AUTO"
            elif action == "all_off":
                process_engine.stop_cycle(user_aborted=True)
                climate_engine.set_manual_fogger(False)
                climate_engine.set_manual_acf(False)
                hw.emergency_all_off(); ok, detail = True, "All OFF queued"
            else:
                ok, detail = False, "Unknown command"
            ack = {"device": DEVICE_NAME, "action": action,
                   "status": "executed" if ok else "rejected", "detail": detail,
                   "timestamp": time.time()}
            if control_client:
                control_client.publish(f"inhydro/{DEVICE_NAME}/command/status", json.dumps(ack), qos=1)
            broadcast_current_state()

        elif topic.endswith("/config/update") or topic.endswith("/setpoints/update"):
            if isinstance(data.get("system_config"), dict):
                system_config.update(data["system_config"])
                save_json(CONFIG_FILE, system_config)
            if isinstance(data.get("cyclic_timers"), dict):
                for key, value in data["cyclic_timers"].items():
                    if key in cyclic_timer_cfg and isinstance(value, dict):
                        cyclic_timer_cfg[key].update(value)
                save_json(TIMERS_FILE, cyclic_timer_cfg)
            if isinstance(data.get("climate_setpoints"), dict):
                climate_setpoints.update(data["climate_setpoints"])
                save_json(CLIMATE_CONFIG_FILE, climate_setpoints)
            logging.info("MQTT configuration update applied")
            broadcast_current_state()
        elif topic.endswith("/request_sync"):
            broadcast_current_state()
    except Exception:
        logging.exception("MQTT message processing failed for topic %s", topic)

def process_mqtt_inbound_queue(max_messages=10):
    for _ in range(max_messages):
        try:
            item = mqtt_inbound_queue.get_nowait()
        except queue.Empty:
            break
        try:
            _apply_mqtt_message(*item)
        finally:
            mqtt_inbound_queue.task_done()

def mqtt_heartbeat_worker():
    while running:
        time.sleep(10)
        if not running:
            break
        if is_mqtt_connected and control_client:
            try:
                now = datetime.datetime.now()
                hb = {"device": DEVICE_NAME, "status": "online",
                      "timestamp": now.isoformat(), "time": now.strftime("%Y-%m-%d %H:%M:%S")}
                control_client.publish(f"inhydro/{DEVICE_NAME}/heartbeat", json.dumps(hb), qos=0)
            except Exception:
                logging.exception("MQTT heartbeat publish failed")

def mqtt_telemetry_streamer():
    last_local = 0.0
    while running:
        time.sleep(1)
        if not running:
            break
        if is_mqtt_connected:
            broadcast_current_state()
        elif time.monotonic() - last_local >= 5:
            save_local_telemetry()
            last_local = time.monotonic()

def sync_offline_data_worker():
    while running:
        time.sleep(15)
        if not running or not is_mqtt_connected or control_client is None:
            continue
        try:
            with local_log_lock:
                if os.path.exists(ACTIVE_LOG_FILE) and os.path.getsize(ACTIVE_LOG_FILE) > 0:
                    rotated = os.path.join(LOG_DIR, f"log_{int(time.time())}_{_uuid.uuid4().hex[:5]}.jsonl")
                    os.replace(ACTIVE_LOG_FILE, rotated)
            files = sorted(f for f in os.listdir(LOG_DIR) if f.startswith("log_") and f.endswith(".jsonl"))
            for filename in files:
                path = os.path.join(LOG_DIR, filename)
                sent_all = True
                with local_log_lock:
                    if not os.path.exists(path):
                        continue
                    with open(path, "r", encoding="utf-8") as stream:
                        while True:
                            lines = []
                            for _ in range(50):
                                line = stream.readline()
                                if not line:
                                    break
                                if line.strip():
                                    lines.append(line.strip())
                            if not lines:
                                break
                            if not is_mqtt_connected:
                                sent_all = False
                                break
                            try:
                                batch = [json.loads(line) for line in lines]
                                info = control_client.publish(
                                    f"inhydro/{DEVICE_NAME}/telemetry/live", json.dumps(batch), qos=1)
                                if hasattr(info, "wait_for_publish"):
                                    info.wait_for_publish(timeout=5)
                                if getattr(info, "rc", 0) != 0:
                                    sent_all = False
                                    break
                            except Exception:
                                logging.exception("Offline telemetry batch publish failed")
                                sent_all = False
                                break
                if sent_all:
                    with local_log_lock:
                        if os.path.exists(path):
                            os.remove(path)
                    logging.info("Offline telemetry synced: %s", filename)
        except Exception:
            logging.exception("Offline telemetry sync failed")

keypad_modal = None

def make_modal_fullscreen(win, root_win):
    win.configure(bg=COLOR_BG_LIGHT)
    if root_win:
        try: win.transient(root_win)
        except Exception: pass
    sw, sh = 1024, 600
    win.geometry(f"{sw}x{sh}+0+0")
    win.lift()
    win.update_idletasks()
    try: win.grab_set()
    except Exception: pass
    win.focus_force()

def open_almora_keypad(title_text, initial_value, callback_on_confirm, mode="numeric", root_window=None):
    global keypad_modal
    if root_window is None: root_window = app
    if keypad_modal and keypad_modal.winfo_exists():
        try: keypad_modal.destroy()
        except Exception: pass

    keypad_modal = tk.Toplevel(root_window)
    make_modal_fullscreen(keypad_modal, root_window)

    kp_main = tk.Frame(keypad_modal, bg=COLOR_BG_LIGHT)
    kp_main.pack(fill="both", expand=True, pady=(25, 10))
    entered_val = str(initial_value)

    tk.Label(kp_main, text=title_text.upper(), font=("Helvetica", 16, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_BG_LIGHT).pack(pady=(4, 2))
    lbl_disp = tk.Label(kp_main, text=entered_val, font=("Arial", 24, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_INHYDRO_WATER_BG, width=22, relief="sunken", bd=2)
    lbl_disp.pack(pady=4)

    def press(ch):
        nonlocal entered_val
        if len(entered_val) < 20: entered_val += str(ch); lbl_disp.config(text=entered_val)
    def back():
        nonlocal entered_val
        entered_val = entered_val[:-1]; lbl_disp.config(text=entered_val)
    def clear():
        nonlocal entered_val
        entered_val = ""; lbl_disp.config(text="")
    def set_time_value(value):
        nonlocal entered_val
        entered_val = str(value)
        lbl_disp.config(text=entered_val)
    def confirm():
        if keypad_modal and keypad_modal.winfo_exists(): keypad_modal.destroy()
        callback_on_confirm(entered_val.strip())
    def cancel():
        if keypad_modal and keypad_modal.winfo_exists(): keypad_modal.destroy()

    btns_f = tk.Frame(kp_main, bg=COLOR_BG_LIGHT)
    btns_f.pack(pady=6)

    if mode == "numeric":
        grid = [('7',0,0),('8',0,1),('9',0,2),('4',1,0),('5',1,1),('6',1,2),('1',2,0),('2',2,1),('3',2,2),('.',3,0),('0',3,1),('DEL',3,2)]
        for t, r, c in grid:
            cmd = back if t == 'DEL' else lambda x=t: press(x)
            bg_c = "#F97316" if t == 'DEL' else "white"
            tk.Button(btns_f, text=t, font=("Arial", 18, "bold"), width=7, height=1, bg=bg_c, fg="white" if t=='DEL' else COLOR_INHYDRO_NAVY, relief="raised", bd=1, command=cmd).grid(row=r, column=c, padx=6, pady=3)
    elif mode == "time":
        sf = tk.Frame(btns_f, bg=COLOR_BG_LIGHT); sf.grid(row=0, column=0, columnspan=4, pady=(0, 4))
        for ts in ["06:00", "08:00", "12:00", "15:00", "18:00", "21:00"]:
            tk.Button(sf, text=ts, font=("Helvetica", 11, "bold"), bg=COLOR_INHYDRO_WATER_BG, fg=COLOR_INHYDRO_NAVY, relief="flat", padx=8, pady=4, command=lambda x=ts: set_time_value(x)).pack(side="left", padx=3)
        time_grid = [('7',1,0),('8',1,1),('9',1,2),(':',1,3),('4',2,0),('5',2,1),('6',2,2),('00',2,3),('1',3,0),('2',3,1),('3',3,2),('CLR',3,3),('0',4,0),('0',4,1),(':',4,2),('DEL',4,3)]
        for t, r, c in time_grid:
            if t == 'CLR': cmd, bg, fg = clear, COLOR_DANGER, "white"
            elif t == 'DEL': cmd, bg, fg = back, "#F97316", "white"
            else: cmd, bg, fg = lambda x=t: press(x), "white", COLOR_INHYDRO_NAVY
            tk.Button(btns_f, text=t, font=("Arial", 16, "bold"), bg=bg, fg=fg, width=7, height=1, relief="raised", bd=1, command=cmd).grid(row=r, column=c, padx=6, pady=3)

    act_f = tk.Frame(kp_main, bg=COLOR_BG_LIGHT); act_f.pack(pady=10)
    tk.Button(act_f, text="CLEAR", font=("Helvetica", 12, "bold"), bg=COLOR_DANGER, fg="white", width=12, command=clear).pack(side="left", padx=6)
    tk.Button(act_f, text="SAVE", font=("Helvetica", 12, "bold"), bg=COLOR_INHYDRO_GREEN, fg="white", width=12, command=confirm).pack(side="left", padx=6)
    tk.Button(act_f, text="CANCEL", font=("Helvetica", 12, "bold"), bg=COLOR_OFF, fg="white", width=12, command=cancel).pack(side="left", padx=6)

def validate_climate_thresholds(values):
    """Return (ok, message) after checking min/max setpoint ordering."""
    checks = [
        ("Day humidity", "HUMI D_Min", "HUMI D_Max", "%"),
        ("Night humidity", "HUMI N_Min", "HUMI N_Max", "%"),
        ("ACF temperature", "ACF Temp Min", "ACF Temp Max", "°C"),
    ]
    for label, min_key, max_key, unit in checks:
        try:
            minimum = float(values[min_key])
            maximum = float(values[max_key])
        except (KeyError, TypeError, ValueError):
            return False, f"{label}: enter valid numeric minimum and maximum values."
        if minimum >= maximum:
            return False, (
                f"Invalid {label} range: minimum ({minimum:g}{unit}) must be "
                f"lower than maximum ({maximum:g}{unit})."
            )
    return True, ""


class IntegratedHMIApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("InHydro - Integrated Controller")
        self.configure(bg=COLOR_BG_LIGHT)
        
        # Always start the main application window in fullscreen mode.
        self.attributes("-fullscreen", True)

        # Keep the existing base geometry as a fallback for window managers.
        sw, sh = 1024, 600
        self.geometry(f"{sw}x{sh}+100+100")
        
        self.current_screen_key = "main_selector"
        self.screens = {}
        self._last_ui_refresh = 0.0
        self._tick_after_id = None
        self._closing = False

        self._build_header()
        self._build_bottom_dock()

        self.container = tk.Frame(self, bg=COLOR_BG_LIGHT)
        self.container.pack(fill="both", expand=True, padx=8, pady=2)

        self.screens["main_selector"]      = self._create_main_selector_screen(self.container)
        self.screens["fert_dashboard"]     = self._create_fert_dashboard_screen(self.container)
        self.screens["fert_settings"]      = self._create_fert_settings_screen(self.container)
        self.screens["sensor_settings"]    = self._create_sensor_settings_screen(self.container)
        self.screens["climate_dashboard"]  = self._create_climate_dashboard_screen(self.container)
        self.screens["climate_monitoring"] = self._create_climate_monitoring_screen(self.container)
        self.screens["climate_settings"]   = self._create_climate_settings_screen(self.container)

        self.show_screen("main_selector")
        self.after(200, self._tick)

    def _secret_exit_tap(self, event=None):
        now = time.time()
        if now - self._last_tap_time < 1.5:
            self._clock_taps += 1
        else:
            self._clock_taps = 1
        self._last_tap_time = now
        if self._clock_taps >= 5:
            self._clock_taps = 0
            try:
                subprocess.Popen(["sudo", "-n", "systemctl", "stop", "inhydro_hmi.service"])
            except Exception:
                pass
            os._exit(0)

    def _build_header(self):
        h = tk.Frame(self, bg="white", height=52); h.pack(fill="x", side="top", pady=(0, 2)); h.pack_propagate(False)
        self.lbl_clock = tk.Label(h, text="", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white", justify="left", padx=10, pady=6)
        self.lbl_clock.place(relx=0.0, rely=0.5, anchor="w", x=10)
        self._clock_taps = 0
        self._last_tap_time = 0.0
        self.lbl_clock.bind("<Button-1>", self._secret_exit_tap)

        self.lbl_header_title = tk.Label(h, text="INHYDRO AUTOMATION & CLIMATE CONTROL", font=("Helvetica", 15, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white")
        self.lbl_header_title.place(relx=0.5, rely=0.5, anchor="center")

        if PIL_AVAILABLE and os.path.exists(LOGO_PATH):
            try:
                img = Image.open(LOGO_PATH)
                img.thumbnail((120, 38), Image.Resampling.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(img)
                tk.Label(h, image=self.logo_img, bg="white").place(relx=1.0, rely=0.5, anchor="e", x=-16)
            except Exception: pass

    def _build_bottom_dock(self):
        self.dock = tk.Frame(self, bg="white", height=60, bd=1, relief="solid", padx=12); self.dock.pack(fill="x", side="bottom"); self.dock.pack_propagate(False)
        self.dock_nav_frame = tk.Frame(self.dock, bg="white")

        self.btn_dock_main = tk.Button(self.dock_nav_frame, text="🏠 MAIN MENU", font=("Helvetica", 12, "bold"), bg=COLOR_INHYDRO_NAVY, fg="white", padx=14, pady=5, command=lambda: self.show_screen("main_selector"))
        self.btn_dock_to_fert = tk.Button(self.dock_nav_frame, text="💧 FERT/IRRIGATION", font=("Helvetica", 12, "bold"), bg=COLOR_INHYDRO_GREEN, fg="white", padx=14, pady=5, command=lambda: self.show_screen("fert_dashboard"))
        self.btn_dock_to_fert_set = tk.Button(self.dock_nav_frame, text="⚙ FERT TIMERS", font=("Helvetica", 12, "bold"), bg=COLOR_INHYDRO_WATER, fg="white", padx=14, pady=5, command=lambda: self.show_screen("fert_settings"))
        self.btn_dock_to_sensor_set = tk.Button(self.dock_nav_frame, text="📡 SENSOR SETTINGS", font=("Helvetica", 12, "bold"), bg="#F59E0B", fg="white", padx=14, pady=5, command=lambda: self.show_screen("sensor_settings"))
        self.btn_dock_to_clim_dash = tk.Button(self.dock_nav_frame, text="◀ CLIMATE DASHBOARD", font=("Helvetica", 12, "bold"), bg=COLOR_INHYDRO_NAVY, fg="white", padx=14, pady=5, command=lambda: self.show_screen("climate_dashboard"))
        self.btn_dock_to_clim_mon = tk.Button(self.dock_nav_frame, text="📊 CLIMATE MONITOR", font=("Helvetica", 12, "bold"), bg=COLOR_INHYDRO_GREEN, fg="white", padx=14, pady=5, command=lambda: self.show_screen("climate_monitoring"))
        self.btn_dock_to_clim_set = tk.Button(self.dock_nav_frame, text="⚙ CLIMATE SETPOINTS", font=("Helvetica", 12, "bold"), bg=COLOR_INHYDRO_WATER, fg="white", padx=14, pady=5, command=lambda: self.show_screen("climate_settings"))

        self.btn_dock_stop = tk.Button(self.dock, text="🛑 ALL OFF", font=("Helvetica", 13, "bold"), bg=COLOR_DANGER, fg="white", padx=20, pady=5, command=self.emergency_stop)

    def emergency_stop(self):
        process_engine.stop_cycle(user_aborted=True)
        climate_engine.set_manual_fogger(False)
        climate_engine.set_manual_acf(False)
        hw.emergency_all_off()
        # Removed blocking messagebox.showwarning to prevent modal UI freezes!

    def show_screen(self, screen_key: str):
        if screen_key not in self.screens: return
        for s in self.screens.values(): s.pack_forget()
        self.screens[screen_key].pack(fill="both", expand=True)
        self.current_screen_key = screen_key

        self.dock_nav_frame.pack_forget()
        self.btn_dock_stop.pack_forget()
        for b in [self.btn_dock_main, self.btn_dock_to_fert, self.btn_dock_to_fert_set, self.btn_dock_to_sensor_set, self.btn_dock_to_clim_dash, self.btn_dock_to_clim_mon, self.btn_dock_to_clim_set]:
            b.pack_forget()

        if screen_key == "main_selector":
            self.lbl_header_title.config(text="INHYDRO AUTOMATION & CLIMATE CONTROL")
            self.btn_dock_stop.pack(anchor="center", pady=6)
        elif screen_key in ["fert_dashboard", "fert_settings", "sensor_settings"]:
            self.lbl_header_title.config(text="FERTIGATION & SENSOR CONFIGURATION")
            # Reserve the right-hand emergency-control area before packing navigation.
            self.btn_dock_stop.pack(side="right", padx=6, pady=5)
            self.dock_nav_frame.pack(side="left", anchor="w", fill="x", expand=True, padx=(4, 0), pady=4)
            for b in [self.btn_dock_main, self.btn_dock_to_fert, self.btn_dock_to_fert_set, self.btn_dock_to_sensor_set, self.btn_dock_to_clim_dash]:
                b.pack(side="left", padx=2, pady=2)
        else:
            self.lbl_header_title.config(text="CLIMATE CONTROLLER (FOGGER & ACF FAN)")
            # Reserve the right-hand emergency-control area before packing navigation.
            self.btn_dock_stop.pack(side="right", padx=6, pady=5)
            self.dock_nav_frame.pack(side="left", anchor="w", fill="x", expand=True, padx=(4, 0), pady=4)
            for b in [self.btn_dock_main, self.btn_dock_to_clim_dash, self.btn_dock_to_clim_mon, self.btn_dock_to_clim_set, self.btn_dock_to_fert]:
                b.pack(side="left", padx=2, pady=2)

    def _create_main_selector_screen(self, parent):
        f = tk.Frame(parent, bg=COLOR_BG_LIGHT)
        g = tk.Frame(f, bg=COLOR_BG_LIGHT); g.pack(fill="both", expand=True, padx=20, pady=16)
        g.columnconfigure(0, weight=1, uniform="sel"); g.columnconfigure(1, weight=1, uniform="sel"); g.rowconfigure(0, weight=1)

        c1 = tk.Frame(g, bg=COLOR_INHYDRO_NAVY, bd=5, relief="raised"); c1.grid(row=0, column=0, padx=14, pady=10, sticky="nsew")
        i1 = tk.Frame(c1, bg=COLOR_INHYDRO_NAVY); i1.pack(expand=True, fill="both", padx=20, pady=20)
        tk.Label(i1, text="FERTIGATION &\nIRRIGATION", font=("Helvetica", 26, "bold"), fg="white", bg=COLOR_INHYDRO_NAVY, justify="center").pack(anchor="center", pady=10)
        tk.Label(i1, text="• Valve Sequencing (Ch 0, SV1, SV2, SV3, SV4)\n• Automated SV1 Delay Window (Custom Sec)\n• Configurable Total Run Timers\n• Sensor Settings & Cyclic Interval Engine", font=("Helvetica", 12), fg=COLOR_INHYDRO_WATER_BG, bg=COLOR_INHYDRO_NAVY, justify="left").pack(anchor="center", pady=10)
        b1 = tk.Label(i1, text="ENTER FERTIGATION & SENSORS ▶", font=("Helvetica", 13, "bold"), fg="white", bg=COLOR_INHYDRO_GREEN, bd=2, relief="raised", padx=14, pady=8)
        b1.pack(side="bottom", fill="x")

        c2 = tk.Frame(g, bg=COLOR_INHYDRO_NAVY, bd=5, relief="raised"); c2.grid(row=0, column=1, padx=14, pady=10, sticky="nsew")
        i2 = tk.Frame(c2, bg=COLOR_INHYDRO_NAVY); i2.pack(expand=True, fill="both", padx=20, pady=20)
        tk.Label(i2, text="CLIMATE\nCONTROLLER", font=("Helvetica", 26, "bold"), fg="white", bg=COLOR_INHYDRO_NAVY, justify="center").pack(anchor="center", pady=(4, 6))

        m_box = tk.Frame(i2, bg=COLOR_INHYDRO_NAVY_DARK, bd=2, relief="sunken", padx=10, pady=6); m_box.pack(fill="x", pady=6)
        m_box.columnconfigure(0, weight=1, uniform="mcol"); m_box.columnconfigure(1, weight=1, uniform="mcol")

        tb = tk.Frame(m_box, bg=COLOR_INHYDRO_NAVY_DARK); tb.grid(row=0, column=0, padx=4, sticky="nsew")
        tk.Label(tb, text="TEMPERATURE", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_WATER, bg=COLOR_INHYDRO_NAVY_DARK).pack()
        self.lbl_main_temp = tk.Label(tb, text="-- °C", font=("Helvetica", 16, "bold"), fg="white", bg=COLOR_INHYDRO_NAVY_DARK)
        self.lbl_main_temp.pack()

        hb = tk.Frame(m_box, bg=COLOR_INHYDRO_NAVY_DARK); hb.grid(row=0, column=1, padx=4, sticky="nsew")
        tk.Label(hb, text="HUMIDITY", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_GREEN, bg=COLOR_INHYDRO_NAVY_DARK).pack()
        self.lbl_main_humi = tk.Label(hb, text="-- %", font=("Helvetica", 16, "bold"), fg="white", bg=COLOR_INHYDRO_NAVY_DARK)
        self.lbl_main_humi.pack()

        tk.Label(i2, text="• 3 Modes: Sensor Only | Cyclic Only | Both\n• Fogger & ACF Min/Max Threshold Controls\n• Smart Humidifier-ACF Forced Synchronization", font=("Helvetica", 11), fg=COLOR_INHYDRO_WATER_BG, bg=COLOR_INHYDRO_NAVY, justify="left").pack(anchor="center", pady=6)
        b2 = tk.Label(i2, text="ENTER CLIMATE CONTROLLER ▶", font=("Helvetica", 13, "bold"), fg="white", bg=COLOR_INHYDRO_GREEN, bd=2, relief="raised", padx=14, pady=8)
        b2.pack(side="bottom", fill="x")

        for w in [c1, i1, b1]: w.bind("<Button-1>", lambda e: self.show_screen("fert_dashboard"))
        for w in [c2, i2, b2, m_box, tb, hb, self.lbl_main_temp, self.lbl_main_humi]: w.bind("<Button-1>", lambda e: self.show_screen("climate_dashboard"))
        return f

    def _create_fert_dashboard_screen(self, parent):
        f = tk.Frame(parent, bg=COLOR_BG_LIGHT)
        b = tk.Frame(f, bg=COLOR_BG_LIGHT); b.pack(fill="both", expand=True, padx=10, pady=4)
        b.columnconfigure(0, weight=1, uniform="fcol"); b.columnconfigure(1, weight=1, uniform="fcol")

        col_l = tk.Frame(b, bg=COLOR_BG_LIGHT); col_l.grid(row=0, column=0, sticky="nsew", padx=6)
        c_status = tk.LabelFrame(col_l, text=" PROCESS MONITOR ", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white", bd=2)
        c_status.pack(fill="x", pady=4)

        self.lbl_fert_mode = tk.Label(c_status, text="MODE: IDLE", font=("Helvetica", 16, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white")
        self.lbl_fert_mode.pack(anchor="w", padx=10, pady=(6, 2))
        self.lbl_fert_desc = tk.Label(c_status, text="System Standby", font=("Helvetica", 11), fg=COLOR_INHYDRO_NAVY_DARK, bg="white", justify="left", wraplength=420)
        self.lbl_fert_desc.pack(anchor="w", padx=10, pady=(0, 2))
        self.lbl_fert_elapsed = tk.Label(c_status, text="Elapsed: 0s", font=("Helvetica", 14, "bold"), fg="#D97706", bg="white")
        self.lbl_fert_elapsed.pack(anchor="w", padx=10, pady=(0, 6))

        tk.Button(col_l, text="▶ START FERTIGATION", font=("Helvetica", 13, "bold"), bg=COLOR_INHYDRO_NAVY, fg="white", height=3, command=self._start_fert).pack(fill="x", pady=6)
        tk.Button(col_l, text="▶ START IRRIGATION", font=("Helvetica", 13, "bold"), bg=COLOR_INHYDRO_GREEN, fg="white", height=3, command=self._start_irrig).pack(fill="x", pady=6)
        tk.Button(col_l, text="⏹ STOP CURRENT CYCLE", font=("Helvetica", 13, "bold"), bg=COLOR_DANGER, fg="white", height=2, command=lambda: process_engine.stop_cycle(user_aborted=True)).pack(fill="x", pady=6)

        col_r = tk.Frame(b, bg=COLOR_BG_LIGHT); col_r.grid(row=0, column=1, sticky="nsew", padx=6)
        c_relays = tk.LabelFrame(col_r, text=" 7-CHANNEL RELAYS STATUS ", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white", bd=2)
        c_relays.pack(fill="both", expand=True, pady=4)

        self.valves_badges = {}
        valve_grid = tk.Frame(c_relays, bg="white"); valve_grid.pack(fill="both", expand=True, padx=8, pady=8)
        valve_grid.columnconfigure(0, weight=1); valve_grid.columnconfigure(1, weight=1)

        for i, ch_idx in enumerate([0, 1, 2, 3, 4, 5, 6]):
            box = tk.Frame(valve_grid, bg=COLOR_BG_LIGHT, bd=1, relief="solid", padx=8, pady=6)
            box.grid(row=i//2, column=i%2, padx=4, pady=4, sticky="nsew")
            tk.Label(box, text=RELAY_NAMES.get(ch_idx, f"Ch {ch_idx}"), font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_BG_LIGHT).pack(side="left")
            badge = tk.Label(box, text="OFF", font=("Helvetica", 10, "bold"), fg="white", bg=COLOR_OFF, width=6, relief="raised")
            badge.pack(side="right")
            self.valves_badges[ch_idx] = badge
        return f

    def _start_fert(self):
        ok, msg = process_engine.start_fertigation()
        if not ok: messagebox.showwarning("Notice", msg)

    def _start_irrig(self):
        ok, msg = process_engine.start_irrigation()
        if not ok: messagebox.showwarning("Notice", msg)

    def _create_fert_settings_screen(self, parent):
        f = tk.Frame(parent, bg=COLOR_BG_LIGHT)
        body = tk.Frame(f, bg=COLOR_BG_LIGHT); body.pack(fill="both", expand=True, padx=12, pady=6)
        body.columnconfigure(0, weight=1, uniform="scol"); body.columnconfigure(1, weight=1, uniform="scol")

        col_l = tk.LabelFrame(body, text=" SEQUENCE TIMERS ", font=("Helvetica", 12, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white", bd=2)
        col_l.grid(row=0, column=0, sticky="nsew", padx=6, pady=4)

        self.fert_timer_labels = {}
        for p_key, p_lbl, p_unit in [("sv1_delay_sec", "SV1 Delay Duration:", "sec"), ("fert_duration_sec", "Fertigation Run Duration:", "sec"), ("irrig_duration_sec", "Irrigation Run Duration:", "sec")]:
            box = tk.Frame(col_l, bg=COLOR_BG_LIGHT, bd=1, relief="solid", padx=10, pady=10); box.pack(fill="x", padx=8, pady=8)
            tk.Label(box, text=p_lbl, font=("Helvetica", 12, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_BG_LIGHT).pack(side="left")
            lbl_v = tk.Label(box, text=f"{system_config.get(p_key)} {p_unit}", font=("Helvetica", 13, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white", width=10, relief="groove")
            lbl_v.pack(side="right", padx=6)
            self.fert_timer_labels[p_key] = (lbl_v, p_unit)
            box.bind("<Button-1>", lambda e, k=p_key, l=p_lbl: open_almora_keypad(f"EDIT {l}", system_config.get(k), lambda v: self._save_param(k, v), mode="numeric", root_window=self))

        col_r = tk.LabelFrame(body, text=" AUTOMATED CYCLIC SCHEDULERS ", font=("Helvetica", 12, "bold"), fg=COLOR_INHYDRO_GREEN, bg="white", bd=2)
        col_r.grid(row=0, column=1, sticky="nsew", padx=6, pady=4)

        for mode_k, title_text in [("fertigation", "Cyclic Fertigation"), ("irrigation", "Cyclic Irrigation")]:
            sec = tk.LabelFrame(col_r, text=f" {title_text.upper()} ", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_GREEN, bg=COLOR_INHYDRO_WATER_BG)
            sec.pack(fill="x", padx=8, pady=6)
            cfg = cyclic_timer_cfg.get(mode_k, {})
            r_en = tk.Frame(sec, bg=COLOR_INHYDRO_WATER_BG); r_en.pack(fill="x", padx=8, pady=4)
            tk.Label(r_en, text="Automation Mode:", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_INHYDRO_WATER_BG).pack(side="left")
            btn_en = tk.Button(r_en, text="ENABLED" if cfg.get("enabled", False) else "DISABLED", font=("Helvetica", 11, "bold"), bg=COLOR_INHYDRO_GREEN if cfg.get("enabled", False) else COLOR_DANGER, fg="white", width=11)
            btn_en.config(command=lambda m=mode_k, b=btn_en: self._toggle_cyclic(m, b))
            btn_en.pack(side="right")

            def make_time_row(parent_f, lbl_txt, p_sub_key, is_time=True):
                r_w = tk.Frame(parent_f, bg=COLOR_INHYDRO_WATER_BG); r_w.pack(fill="x", padx=8, pady=3)
                tk.Label(r_w, text=lbl_txt, font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_INHYDRO_WATER_BG).pack(side="left")
                val_s = str(cfg.get(p_sub_key, "06:00" if is_time else "5.0"))
                l_cell = tk.Label(r_w, text=val_s, font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_GREEN, bg="white", width=8, relief="groove")
                l_cell.pack(side="right")
                l_cell.bind("<Button-1>", lambda e, m=mode_k, sk=p_sub_key, ls=val_s, lt=lbl_txt: open_almora_keypad(f"{title_text}: {lt}", ls, lambda nv: self._save_cyclic_param(m, sk, nv, l_cell), mode="time" if is_time else "numeric", root_window=self))

            make_time_row(sec, "Window Start Time:", "start_time", is_time=True)
            make_time_row(sec, "Window Stop Time:",  "stop_time",  is_time=True)
            make_time_row(sec, "Cycle ON (Min):",    "on_min",     is_time=False)
            make_time_row(sec, "Cycle OFF (Min):",   "off_min",    is_time=False)
        return f

    def _create_sensor_settings_screen(self, parent):
        f = tk.Frame(parent, bg=COLOR_BG_LIGHT)
        body = tk.LabelFrame(f, text=" SENSOR & MODBUS CONFIGURATION ", font=("Helvetica", 12, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white", bd=2)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        self.sensor_setting_labels = {}
        for p_key, p_lbl, p_mode in [("sensor_port", "Sensor Serial Port Path:", "text"), ("sensor_baudrate", "Sensor Baud Rate:", "numeric"), ("sensor_slave_id", "Sensor Modbus Slave ID:", "numeric"), ("serial_port", "Relay Board Serial Port Path:", "text"), ("relay_baudrate", "Relay Board Baud Rate:", "numeric"), ("relay_slave_id", "Relay Board Slave ID:", "numeric")]:
            box = tk.Frame(body, bg=COLOR_BG_LIGHT, bd=1, relief="solid", padx=12, pady=12); box.pack(fill="x", padx=12, pady=10)
            tk.Label(box, text=p_lbl, font=("Helvetica", 13, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_BG_LIGHT).pack(side="left")
            lbl_v = tk.Label(box, text=str(system_config.get(p_key, "")), font=("Helvetica", 14, "bold"), fg=COLOR_INHYDRO_GREEN, bg="white", width=14, relief="groove")
            lbl_v.pack(side="right", padx=6)
            self.sensor_setting_labels[p_key] = lbl_v
            box.bind("<Button-1>", lambda e, k=p_key, l=p_lbl, m=p_mode: open_almora_keypad(f"EDIT {l}", system_config.get(k), lambda v: self._save_sensor_param(k, v), mode=m, root_window=self))
        return f

    def _save_sensor_param(self, key, val_str):
        try:
            val = str(val_str).strip() if key in ("sensor_port", "serial_port") else int(val_str)
            system_config[key] = val
            save_json(CONFIG_FILE, system_config)
            if key in self.sensor_setting_labels: self.sensor_setting_labels[key].config(text=str(val))
            broadcast_current_state()
            messagebox.showinfo("Saved", f"Updated {key} to {val}")
        except Exception as e: messagebox.showerror("Error", f"Invalid value: {e}")

    def _save_param(self, key, val_str):
        try:
            val = int(val_str)
            system_config[key] = val
            save_json(CONFIG_FILE, system_config)
            lbl, unit = self.fert_timer_labels[key]
            lbl.config(text=f"{val} {unit}")
        except Exception: pass

    def _toggle_cyclic(self, mode_key, btn):
        cur = cyclic_timer_cfg.get(mode_key, {}).get("enabled", False)
        cyclic_timer_cfg[mode_key]["enabled"] = not cur
        save_json(TIMERS_FILE, cyclic_timer_cfg)
        btn.config(text="ENABLED" if not cur else "DISABLED", bg=COLOR_INHYDRO_GREEN if not cur else COLOR_DANGER)

    def _save_cyclic_param(self, mode_key, sub_key, val_str, lbl):
        try:
            val = str(val_str).strip() if "time" in sub_key else float(val_str)
            cyclic_timer_cfg[mode_key][sub_key] = val
            save_json(TIMERS_FILE, cyclic_timer_cfg)
            lbl.config(text=str(val))
        except Exception: pass

    def _create_climate_dashboard_screen(self, parent):
            f = tk.Frame(parent, bg=COLOR_BG_LIGHT)

            metric_bar = tk.Frame(f, bg="white", bd=2, relief="groove", padx=16, pady=8)
            metric_bar.pack(fill="x", padx=20, pady=(10, 6))

            tk.Label(metric_bar, text="LIVE ROOM ENVIRONMENT:", font=("Helvetica", 13, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white").pack(side="left")
            self.lbl_clim_dash_pv = tk.Label(metric_bar, text="Temp: -- °C  |  Humidity: -- %", font=("Helvetica", 15, "bold"), fg=COLOR_INHYDRO_GREEN, bg="white")
            self.lbl_clim_dash_pv.pack(side="right")

            g = tk.Frame(f, bg=COLOR_BG_LIGHT)
            g.pack(fill="both", expand=True, padx=20, pady=10)
            g.columnconfigure(0, weight=1, uniform="clim")
            g.columnconfigure(1, weight=1, uniform="clim")
            g.rowconfigure(0, weight=1)

            c1 = tk.Frame(g, bg=COLOR_INHYDRO_NAVY, bd=5, relief="raised", cursor="hand2")
            c1.grid(row=0, column=0, padx=14, pady=10, sticky="nsew")
            i1 = tk.Frame(c1, bg=COLOR_INHYDRO_NAVY)
            i1.pack(expand=True, fill="both", padx=24, pady=20)
            tk.Label(i1, text="LIVE CLIMATE\nMONITORING", font=("Helvetica", 26, "bold"), fg="white", bg=COLOR_INHYDRO_NAVY, justify="center").pack(anchor="center", pady=6)
            b1 = tk.Label(i1, text="OPEN LIVE MONITORING ▶", font=("Helvetica", 14, "bold"), fg="white", bg=COLOR_INHYDRO_GREEN, bd=2, relief="raised", padx=16, pady=10, cursor="hand2")
            b1.pack(side="bottom", fill="x", pady=8)

            c2 = tk.Frame(g, bg=COLOR_INHYDRO_NAVY_DARK, bd=5, relief="raised", cursor="hand2")
            c2.grid(row=0, column=1, padx=14, pady=10, sticky="nsew")
            i2 = tk.Frame(c2, bg=COLOR_INHYDRO_NAVY_DARK)
            i2.pack(expand=True, fill="both", padx=24, pady=20)
            tk.Label(i2, text="CLIMATE SETPOINTS\n& AUTO CONTROL", font=("Helvetica", 26, "bold"), fg="white", bg=COLOR_INHYDRO_NAVY_DARK, justify="center").pack(anchor="center", pady=6)
            b2 = tk.Label(i2, text="ENTER CLIMATE SETPOINTS ▶", font=("Helvetica", 14, "bold"), fg="white", bg=COLOR_INHYDRO_WATER, bd=2, relief="raised", padx=16, pady=10, cursor="hand2")
            b2.pack(side="bottom", fill="x", pady=8)

            c1.bind("<Button-1>", lambda e: self.show_screen("climate_monitoring"))
            c2.bind("<Button-1>", lambda e: self.show_screen("climate_settings"))
            for w in [i1, b1]: w.bind("<Button-1>", lambda e: self.show_screen("climate_monitoring"))
            for w in [i2, b2]: w.bind("<Button-1>", lambda e: self.show_screen("climate_settings"))
            return f

    def _create_climate_monitoring_screen(self, parent):
            f = tk.Frame(parent, bg=COLOR_BG_LIGHT)
            body = tk.Frame(f, bg=COLOR_BG_LIGHT)
            body.pack(fill="both", expand=True, padx=8, pady=2)
            body.columnconfigure(0, weight=1, uniform="cm")
            body.columnconfigure(1, weight=1, uniform="cm")

            col_l = tk.Frame(body, bg=COLOR_BG_LIGHT)
            col_l.grid(row=0, column=0, sticky="nsew", padx=6, pady=2)

            card_sensor = tk.LabelFrame(col_l, text=" CLIMATE LIVE ", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white", bd=2)
            card_sensor.pack(fill="x", pady=(0, 4))

            f_metrics = tk.Frame(card_sensor, bg="white")
            f_metrics.pack(fill="x", padx=6, pady=4)
            f_metrics.columnconfigure(0, weight=1, uniform="m")
            f_metrics.columnconfigure(1, weight=1, uniform="m")

            c_t = tk.Frame(f_metrics, bg=COLOR_INHYDRO_WATER_BG, bd=2, relief="sunken", padx=6, pady=6)
            c_t.grid(row=0, column=0, padx=4, sticky="nsew")
            tk.Label(c_t, text="ROOM TEMPERATURE", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_INHYDRO_WATER_BG).pack()
            self.lbl_clim_pv_temp = tk.Label(c_t, text="-- °C", font=("Helvetica", 22, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_INHYDRO_WATER_BG)
            self.lbl_clim_pv_temp.pack(pady=2)

            c_h = tk.Frame(f_metrics, bg="#E8F5E9", bd=2, relief="sunken", padx=6, pady=6)
            c_h.grid(row=0, column=1, padx=4, sticky="nsew")
            tk.Label(c_h, text="ROOM HUMIDITY", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_GREEN_DARK, bg="#E8F5E9").pack()
            self.lbl_clim_pv_humi = tk.Label(c_h, text="-- %", font=("Helvetica", 22, "bold"), fg=COLOR_INHYDRO_GREEN_DARK, bg="#E8F5E9")
            self.lbl_clim_pv_humi.pack(pady=2)

            self.lbl_clim_humi_band = tk.Label(card_sensor, text=f"Target Band: H_Min: {climate_setpoints.get('HUMI D_Min', 55.0):.0f}% (ON) | H_Max: {climate_setpoints.get('HUMI D_Max', 75.0):.0f}% (OFF)", font=("Helvetica", 9, "bold"), fg=COLOR_INHYDRO_WATER, bg="white")
            self.lbl_clim_humi_band.pack(pady=(2, 4))

            card_timers = tk.LabelFrame(col_l, text=" ACTIVE SCHEDULES & TIMERS ", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white", bd=2)
            card_timers.pack(fill="both", expand=True, pady=4)

            f_fog = tk.Frame(card_timers, bg=COLOR_BG_LIGHT, bd=1, relief="solid", padx=8, pady=4)
            f_fog.pack(fill="x", padx=6, pady=4)
            tk.Label(f_fog, text="FOGGER ACTIVE SCHEDULE", font=("Helvetica", 9, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_BG_LIGHT).pack(anchor="w")
            self.lbl_clim_timer_fog_phase = tk.Label(f_fog, text="IDLE / STANDBY", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_WATER, bg=COLOR_BG_LIGHT)
            self.lbl_clim_timer_fog_phase.pack(anchor="w", pady=(2, 0))

            f_acf = tk.Frame(card_timers, bg=COLOR_INHYDRO_WATER_BG, bd=1, relief="solid", padx=8, pady=4)
            f_acf.pack(fill="x", padx=6, pady=4)
            tk.Label(f_acf, text="AIR CIRCULATION FAN (ACF) SCHEDULE", font=("Helvetica", 9, "bold"), fg=COLOR_INHYDRO_GREEN_DARK, bg=COLOR_INHYDRO_WATER_BG).pack(anchor="w")
            self.lbl_clim_timer_acf_phase = tk.Label(f_acf, text="IDLE / STANDBY", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_GREEN_DARK, bg=COLOR_INHYDRO_WATER_BG)
            self.lbl_clim_timer_acf_phase.pack(anchor="w", pady=(2, 0))

            col_r = tk.Frame(body, bg=COLOR_BG_LIGHT)
            col_r.grid(row=0, column=1, sticky="nsew", padx=6, pady=2)

            card_fog_act = tk.LabelFrame(col_r, text=" FOGGER (MISTING VALVES) ", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white", bd=2)
            card_fog_act.pack(fill="x", pady=(0, 4))

            top_f = tk.Frame(card_fog_act, bg="white")
            top_f.pack(fill="x", padx=8, pady=4)
            tk.Label(top_f, text="STATE:", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white").pack(side="left")
            self.lbl_fog_badge = tk.Label(top_f, text="OFF", font=("Helvetica", 11, "bold"), bg=COLOR_OFF, fg="white", width=8, relief="raised")
            self.lbl_fog_badge.pack(side="right")

            self.lbl_fog_status = tk.Label(card_fog_act, text="IDLE", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_WATER, bg=COLOR_BG_LIGHT, relief="sunken", anchor="w")
            self.lbl_fog_status.pack(fill="x", padx=8, pady=4)

            f_fctrl = tk.Frame(card_fog_act, bg="white")
            f_fctrl.pack(fill="x", padx=8, pady=4)
            tk.Button(f_fctrl, text="AUTO", font=("Helvetica", 10, "bold"), bg=COLOR_INHYDRO_NAVY, fg="white", width=8, command=lambda: (climate_engine.set_manual_fogger(None), broadcast_current_state())).pack(side="left", padx=2)
            tk.Button(f_fctrl, text="FORCE ON", font=("Helvetica", 10, "bold"), bg=COLOR_INHYDRO_GREEN, fg="white", width=9, command=lambda: (climate_engine.set_manual_fogger(True), broadcast_current_state())).pack(side="left", padx=2)
            tk.Button(f_fctrl, text="FORCE OFF", font=("Helvetica", 10, "bold"), bg=COLOR_DANGER, fg="white", width=9, command=lambda: (climate_engine.set_manual_fogger(False), broadcast_current_state())).pack(side="left", padx=2)

            card_acf_act = tk.LabelFrame(col_r, text=" AIR CIRCULATION FAN (ACF) ", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_GREEN_DARK, bg="white", bd=2)
            card_acf_act.pack(fill="x", pady=4)

            top_a = tk.Frame(card_acf_act, bg="white")
            top_a.pack(fill="x", padx=8, pady=4)
            tk.Label(top_a, text="STATE:", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white").pack(side="left")
            self.lbl_acf_badge = tk.Label(top_a, text="OFF", font=("Helvetica", 11, "bold"), bg=COLOR_OFF, fg="white", width=8, relief="raised")
            self.lbl_acf_badge.pack(side="right")

            self.lbl_acf_status = tk.Label(card_acf_act, text="IDLE", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_GREEN_DARK, bg=COLOR_BG_LIGHT, relief="sunken", anchor="w")
            self.lbl_acf_status.pack(fill="x", padx=8, pady=4)

            f_actrl = tk.Frame(card_acf_act, bg="white")
            f_actrl.pack(fill="x", padx=8, pady=4)
            tk.Button(f_actrl, text="AUTO", font=("Helvetica", 10, "bold"), bg=COLOR_INHYDRO_NAVY, fg="white", width=8, command=lambda: (climate_engine.set_manual_acf(None), broadcast_current_state())).pack(side="left", padx=2)
            tk.Button(f_actrl, text="FORCE ON", font=("Helvetica", 10, "bold"), bg=COLOR_INHYDRO_GREEN, fg="white", width=9, command=lambda: (climate_engine.set_manual_acf(True), broadcast_current_state())).pack(side="left", padx=2)
            tk.Button(f_actrl, text="FORCE OFF", font=("Helvetica", 10, "bold"), bg=COLOR_DANGER, fg="white", width=9, command=lambda: (climate_engine.set_manual_acf(False), broadcast_current_state())).pack(side="left", padx=2)

            return f

    def _create_climate_settings_screen(self, parent):
            f = tk.Frame(parent, bg=COLOR_BG_LIGHT)
            body = tk.Frame(f, bg=COLOR_BG_LIGHT)
            body.pack(fill="both", expand=True, padx=8, pady=2)
            body.columnconfigure(0, weight=5, uniform="cset")
            body.columnconfigure(1, weight=4, uniform="cset")

            col_l = tk.LabelFrame(body, text=" FOGGER SETTINGS & 3-WAY TRIGGER MODE ", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white", bd=2)
            col_l.grid(row=0, column=0, sticky="nsew", padx=6, pady=2)

            f_fog_mode = tk.Frame(col_l, bg=COLOR_INHYDRO_WATER_BG, bd=1, relief="solid", padx=6, pady=6)
            f_fog_mode.pack(fill="x", padx=6, pady=4)
            tk.Label(f_fog_mode, text="Trigger Mode (BOTH = Humidity AND Cyclic):", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_INHYDRO_WATER_BG).pack(side="left", padx=4)

            self.btn_fog_modes = {}
            for m_val in ["SENSOR", "CYCLIC", "BOTH"]:
                btn_m = tk.Button(f_fog_mode, text=m_val, font=("Helvetica", 9, "bold"), width=8, relief="raised", cursor="hand2",
                                  command=lambda m=m_val: self._set_trigger_mode("fogger", m))
                btn_m.pack(side="left", padx=2)
                self.btn_fog_modes[m_val] = btn_m

            g_fog = tk.Frame(col_l, bg="white")
            g_fog.pack(fill="both", expand=True, padx=6, pady=4)
            g_fog.columnconfigure(0, weight=4)
            g_fog.columnconfigure(1, weight=3)
            g_fog.columnconfigure(2, weight=3)

            tk.Label(g_fog, text="Parameter", font=("Helvetica", 10, "bold"), fg=COLOR_OFF, bg="white", anchor="w").grid(row=0, column=0, padx=4, pady=3, sticky="w")
            tk.Label(g_fog, text="DAY WINDOW", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_INHYDRO_WATER_BG, relief="groove", bd=1).grid(row=0, column=1, padx=4, pady=3, sticky="ew")
            tk.Label(g_fog, text="NIGHT WINDOW", font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_NAVY_DARK, bg=COLOR_BG_LIGHT, relief="groove", bd=1).grid(row=0, column=2, padx=4, pady=3, sticky="ew")

            self.climate_sp_labels = {}

            def make_sp_row(parent_grid, row_idx, label_text, d_key, n_key, is_time=False):
                tk.Label(parent_grid, text=label_text, font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_NAVY, bg="white", anchor="w").grid(row=row_idx, column=0, padx=4, pady=3, sticky="w")

                f_d = tk.Frame(parent_grid, bg=COLOR_INHYDRO_WATER_BG, bd=1, relief="sunken", cursor="hand2")
                f_d.grid(row=row_idx, column=1, padx=4, pady=3, sticky="ew")
                v_d = str(climate_setpoints.get(d_key, ""))
                lbl_d = tk.Label(f_d, text=v_d, font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY, bg=COLOR_INHYDRO_WATER_BG)
                lbl_d.pack(side="left", fill="both", expand=True)
                self.climate_sp_labels[d_key] = lbl_d

                def on_click_d(e=None):
                    open_almora_keypad(f"DAY {label_text.upper()}", climate_setpoints.get(d_key), lambda nv: self._update_climate_sp(d_key, str(nv).strip() if is_time else float(nv)), mode="time" if is_time else "numeric", root_window=self)
                f_d.bind("<Button-1>", on_click_d)
                lbl_d.bind("<Button-1>", on_click_d)

                f_n = tk.Frame(parent_grid, bg=COLOR_BG_LIGHT, bd=1, relief="sunken", cursor="hand2")
                f_n.grid(row=row_idx, column=2, padx=4, pady=3, sticky="ew")
                v_n = str(climate_setpoints.get(n_key, ""))
                lbl_n = tk.Label(f_n, text=v_n, font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_NAVY_DARK, bg=COLOR_BG_LIGHT)
                lbl_n.pack(side="left", fill="both", expand=True)
                self.climate_sp_labels[n_key] = lbl_n

                def on_click_n(e=None):
                    open_almora_keypad(f"NIGHT {label_text.upper()}", climate_setpoints.get(n_key), lambda nv: self._update_climate_sp(n_key, str(nv).strip() if is_time else float(nv)), mode="time" if is_time else "numeric", root_window=self)
                f_n.bind("<Button-1>", on_click_n)
                lbl_n.bind("<Button-1>", on_click_n)

            make_sp_row(g_fog, 1, "Window Start", "HUMI D_Start",  "HUMI N_Start", is_time=True)
            make_sp_row(g_fog, 2, "Window Stop",  "HUMI D_Stop",   "HUMI N_Stop",  is_time=True)
            make_sp_row(g_fog, 3, "ON Min",       "HUMI D_ON Min", "HUMI N_ON Min", is_time=False)
            make_sp_row(g_fog, 4, "OFF Min",      "HUMI D_OFF Min","HUMI N_OFF Min", is_time=False)
            make_sp_row(g_fog, 5, "H_Min (% ON)", "HUMI D_Min",    "HUMI N_Min",     is_time=False)
            make_sp_row(g_fog, 6, "H_Max (% OFF)","HUMI D_Max",    "HUMI N_Max",     is_time=False)

            fogger_delay_frame = tk.Frame(col_l, bg=COLOR_INHYDRO_WATER_BG, bd=1, relief="solid", padx=8, pady=5)
            fogger_delay_frame.pack(fill="x", padx=6, pady=(2, 4))
            tk.Label(fogger_delay_frame, text="SV1 Start Delay (seconds):", font=("Helvetica", 10, "bold"),
                     fg=COLOR_INHYDRO_NAVY, bg=COLOR_INHYDRO_WATER_BG).pack(side="left", padx=4)
            self.fogger_delay_var = tk.StringVar(value=str(system_config.get("sv1_delay_sec", 10)))
            ent_fog_delay = tk.Entry(fogger_delay_frame, textvariable=self.fogger_delay_var, width=7,
                                     font=("Helvetica", 12, "bold"), justify="center")
            ent_fog_delay.pack(side="left", padx=5)
            ent_fog_delay.bind("<Button-1>", lambda e: open_almora_keypad(
                "FOGGER SV1 DELAY (SECONDS)", self.fogger_delay_var.get(),
                lambda nv: self.fogger_delay_var.set(str(nv).strip()), mode="numeric", root_window=self))
            tk.Label(fogger_delay_frame, text="(default 10 sec)", font=("Helvetica", 9),
                     fg=COLOR_OFF, bg=COLOR_INHYDRO_WATER_BG).pack(side="left", padx=4)

            btn_save_fogger = tk.Button(col_l, text="💾 SAVE FOGGER SETTINGS", font=("Helvetica", 12, "bold"),
                                        bg=COLOR_INHYDRO_GREEN, fg="white", activebackground=COLOR_INHYDRO_GREEN_DARK,
                                        activeforeground="white", pady=7, cursor="hand2",
                                        command=self._save_fogger_settings)
            btn_save_fogger.pack(fill="x", padx=6, pady=(2, 6))

            col_r = tk.Frame(body, bg=COLOR_BG_LIGHT)
            col_r.grid(row=0, column=1, sticky="nsew", padx=6, pady=2)

            card_acf_sp = tk.LabelFrame(col_r, text=" ACF SETTINGS & TEMPERATURE THRESHOLDS ", font=("Helvetica", 11, "bold"), fg=COLOR_INHYDRO_GREEN_DARK, bg="white", bd=2)
            card_acf_sp.pack(fill="x", pady=(0, 4))

            f_acf_mode = tk.Frame(card_acf_sp, bg="#E8F5E9", bd=1, relief="solid", padx=6, pady=6)
            f_acf_mode.pack(fill="x", padx=6, pady=4)
            tk.Label(f_acf_mode, text="AUTO CONTROL: Temperature Min / Max thresholds",
                     font=("Helvetica", 10, "bold"), fg=COLOR_INHYDRO_GREEN_DARK,
                     bg="#E8F5E9").pack(anchor="w", padx=4)

            g_acf = tk.Frame(card_acf_sp, bg="white")
            g_acf.pack(fill="x", padx=6, pady=4)
            g_acf.columnconfigure(0, weight=1)
            g_acf.columnconfigure(1, weight=1)

            def make_acf_cell(r, c, lbl_txt, p_key, is_time=False):
                bx = tk.Frame(g_acf, bg="#E8F5E9", bd=1, relief="sunken", padx=6, pady=4, cursor="hand2")
                bx.grid(row=r, column=c, padx=4, pady=3, sticky="ew")
                tk.Label(bx, text=lbl_txt, font=("Helvetica", 9, "bold"), fg=COLOR_INHYDRO_GREEN_DARK, bg="#E8F5E9").pack(anchor="w")
                lbl_v = tk.Label(bx, text=str(climate_setpoints.get(p_key, "")), font=("Helvetica", 12, "bold"), fg=COLOR_INHYDRO_NAVY, bg="#E8F5E9")
                lbl_v.pack(anchor="center", pady=1)
                self.climate_sp_labels[p_key] = lbl_v
                def on_c(e=None):
                    open_almora_keypad(f"ACF {lbl_txt.upper()}", climate_setpoints.get(p_key), lambda nv: self._update_climate_sp(p_key, str(nv).strip() if is_time else float(nv)), mode="time" if is_time else "numeric", root_window=self)
                bx.bind("<Button-1>", on_c)
                lbl_v.bind("<Button-1>", on_c)

            make_acf_cell(0, 0, "Temp Min (°C) - ACF OFF", "ACF Temp Min", is_time=False)
            make_acf_cell(0, 1, "Temp Max (°C) - ACF ON",  "ACF Temp Max", is_time=False)

            btn_save_all = tk.Button(col_r, text="💾 SAVE CLIMATE SETTINGS", font=("Helvetica", 12, "bold"), bg=COLOR_INHYDRO_GREEN, fg="white", activebackground=COLOR_INHYDRO_GREEN_DARK, activeforeground="white", pady=8, cursor="hand2", command=self._save_climate_settings)
            btn_save_all.pack(fill="x", pady=12)

            self._refresh_trigger_mode_buttons()
            return f

    def _update_climate_sp(self, key, val):
            candidate = copy.deepcopy(climate_setpoints)
            candidate[key] = val
            ok, error_text = validate_climate_thresholds(candidate)
            if not ok:
                messagebox.showerror("Invalid Climate Setpoint", error_text)
                return
            climate_setpoints[key] = val
            if not save_json(CLIMATE_CONFIG_FILE, climate_setpoints):
                messagebox.showerror("Save Failed", "Could not save climate settings. Check storage permissions.")
                return
            if key in self.climate_sp_labels:
                self.climate_sp_labels[key].config(text=str(val))
            broadcast_current_state()

    def _refresh_visible_screen(self):
        """Update only widgets on the currently visible screen."""
        now = datetime.datetime.now()
        self.lbl_clock.config(text=now.strftime("%d-%m-%Y\n%I:%M:%S %p"))
        screen = self.current_screen_key

        if screen == "main_selector":
            if hw.pv_room_temp is not None and not hw.md02_error:
                self.lbl_main_temp.config(text=f"{hw.pv_room_temp:.1f} °C", fg="white")
                self.lbl_main_humi.config(text=f"{hw.pv_room_humi:.1f} %", fg="white")
            else:
                self.lbl_main_temp.config(text="-- °C", fg="#FCA5A5")
                self.lbl_main_humi.config(text="-- %", fg="#FCA5A5")

        elif screen == "fert_dashboard":
            self.lbl_fert_mode.config(text=f"MODE: {process_engine.current_mode}")
            fert_desc = process_engine.status_msg
            if climate_engine.fogger_status_msg.startswith("FOGGING WILL START AFTER"):
                fert_desc += "\n" + climate_engine.fogger_status_msg.title()
            self.lbl_fert_desc.config(text=fert_desc)
            elapsed = int(time.time() - process_engine.start_time) if process_engine.current_mode != "IDLE" else 0
            self.lbl_fert_elapsed.config(
                text=f"Elapsed: {elapsed}s" if process_engine.current_mode != "IDLE" else "System Standby"
            )
            for ch_idx, badge in self.valves_badges.items():
                is_on = hw.get_relay(ch_idx)
                badge.config(text="ON" if is_on else "OFF",
                             bg=COLOR_INHYDRO_GREEN if is_on else COLOR_OFF)

        elif screen == "climate_dashboard":
            if hw.pv_room_temp is not None and not hw.md02_error:
                self.lbl_clim_dash_pv.config(
                    text=f"Temp: {hw.pv_room_temp:.1f} °C  |  Humidity: {hw.pv_room_humi:.1f} %",
                    fg=COLOR_INHYDRO_GREEN)
            else:
                self.lbl_clim_dash_pv.config(
                    text="Temp: -- °C  |  Humidity: -- % (Sensor Error)",
                    fg=COLOR_DANGER)

        elif screen == "climate_settings":
            for key, label in self.climate_sp_labels.items():
                label.config(text=str(climate_setpoints.get(key, "")))
            if hasattr(self, "fogger_delay_var"):
                self.fogger_delay_var.set(str(system_config.get("sv1_delay_sec", 10)))
            self._refresh_trigger_mode_buttons()

        elif screen == "climate_monitoring":
            is_fog = climate_engine.fogger_active
            self.lbl_fog_badge.config(text="ON" if is_fog else "OFF",
                                      bg=COLOR_INHYDRO_GREEN if is_fog else COLOR_OFF)
            self.lbl_fog_status.config(text=climate_engine.fogger_status_msg)
            self.lbl_clim_timer_fog_phase.config(
                text=f"Phase: {climate_engine.fogger_status_msg}")
            if hasattr(self, "lbl_acf_badge"):
                is_acf = hw.get_relay(RelayMap.ACF)
                self.lbl_acf_badge.config(text="ON" if is_acf else "OFF",
                                          bg=COLOR_INHYDRO_GREEN if is_acf else COLOR_OFF)
                self.lbl_acf_status.config(text=climate_engine.acf_status_msg)
                self.lbl_clim_timer_acf_phase.config(text=f"Phase: {climate_engine.acf_status_msg}")
            if hw.pv_room_temp is not None and not hw.md02_error:
                self.lbl_clim_pv_temp.config(text=f"{hw.pv_room_temp:.1f} °C",
                                             fg=COLOR_INHYDRO_NAVY)
                self.lbl_clim_pv_humi.config(text=f"{hw.pv_room_humi:.1f} %",
                                             fg=COLOR_INHYDRO_GREEN_DARK)
            else:
                self.lbl_clim_pv_temp.config(text="-- °C", fg=COLOR_DANGER)
                self.lbl_clim_pv_humi.config(text="-- %", fg=COLOR_DANGER)

    def _tick(self):
        """Exception-protected scheduler; control engines run on every tick."""
        try:
            try:
                process_mqtt_inbound_queue(max_messages=10)
            except Exception:
                logging.exception("MQTT inbound queue processing failed")
            for engine_name, engine_method in (
                ("process", process_engine.process_tick),
                ("cyclic", cyclic_engine.process_tick),
                ("climate", climate_engine.process_tick),
            ):
                try:
                    engine_method()
                except Exception:
                    logging.exception("%s engine tick failed", engine_name)

            now_mono = time.monotonic()
            if now_mono - self._last_ui_refresh >= 0.5:
                try:
                    self._refresh_visible_screen()
                    self._last_ui_refresh = now_mono
                except Exception:
                    logging.exception("Visible-screen refresh failed")

        finally:
            try:
                if not self._closing and self.winfo_exists():
                    self._tick_after_id = self.after(250, self._tick)
            except tk.TclError:
                logging.info("Tk window destroyed; stopping scheduler")
            except Exception:
                logging.exception("Failed to schedule next HMI tick")

    def shutdown(self):
        """Request all outputs OFF and close the HMI cleanly."""
        global running
        if self._closing:
            return
        self._closing = True
        running = False
        try:
            if self._tick_after_id is not None:
                self.after_cancel(self._tick_after_id)
        except Exception:
            pass
        try:
            hw.emergency_all_off()
        except Exception:
            logging.exception("Emergency all-off request failed")
        try:
            self.destroy()
        except Exception:
            logging.exception("Tk shutdown error")

    def _set_trigger_mode(self, dev_type, mode):
        key = "fogger_trigger_mode" if dev_type == "fogger" else "acf_trigger_mode"
        climate_setpoints[key] = mode
        save_json(CLIMATE_CONFIG_FILE, climate_setpoints)
        self._refresh_trigger_mode_buttons()
        broadcast_current_state()

    def _refresh_trigger_mode_buttons(self):
        f_mode = str(climate_setpoints.get("fogger_trigger_mode", "BOTH")).upper()
        if hasattr(self, "btn_fog_modes"):
            for m_key, btn in self.btn_fog_modes.items():
                is_sel = (m_key == f_mode)
                btn.config(bg=COLOR_INHYDRO_NAVY if is_sel else "white", fg="white" if is_sel else COLOR_INHYDRO_NAVY, relief="sunken" if is_sel else "raised")

        a_mode = str(climate_setpoints.get("acf_trigger_mode", "BOTH")).upper()
        if hasattr(self, "btn_acf_modes"):
            for m_key, btn in self.btn_acf_modes.items():
                is_sel = (m_key == a_mode)
                btn.config(bg=COLOR_INHYDRO_GREEN if is_sel else "white", fg="white" if is_sel else COLOR_INHYDRO_GREEN_DARK, relief="sunken" if is_sel else "raised")
    def _save_fogger_settings(self):
        valid, threshold_error = validate_climate_thresholds(climate_setpoints)
        if not valid:
            messagebox.showerror("Invalid Climate Setpoint", threshold_error)
            return
        try:
            delay = float(self.fogger_delay_var.get().strip())
            if delay < 0 or delay > 3600:
                raise ValueError("SV1 delay must be between 0 and 3600 seconds")
        except Exception as exc:
            messagebox.showerror("Invalid SV1 Delay", str(exc) if str(exc) else "Enter a valid delay in seconds.")
            return
        system_config["sv1_delay_sec"] = delay
        ok_climate = save_json(CLIMATE_CONFIG_FILE, climate_setpoints)
        ok_system = save_json(CONFIG_FILE, system_config)
        if ok_climate and ok_system:
            broadcast_current_state()
            messagebox.showinfo("Saved", "Fogger settings and SV1 delay saved successfully.")
        else:
            messagebox.showerror("Save Failed", "Could not save all fogger settings. Check storage and permissions.")

    def _save_climate_settings(self):
        valid, threshold_error = validate_climate_thresholds(climate_setpoints)
        if not valid:
            messagebox.showerror("Invalid Climate Setpoint", threshold_error)
            return
        if not save_json(CLIMATE_CONFIG_FILE, climate_setpoints):
            messagebox.showerror("Save Failed", "Could not save climate settings. Check storage permissions.")
            return
        broadcast_current_state()
        messagebox.showinfo("Saved", "Climate settings saved and synced successfully!")
if __name__ == "__main__":
    try:
        logging.info("Starting merged InHydro Raspberry Pi 5 controller")
        app = IntegratedHMIApp()
        app.protocol("WM_DELETE_WINDOW", app.shutdown)
        if not hw.start():
            logging.critical("Relay startup ALL-OFF was not confirmed; all relay ON commands will be inhibited")

        if MQTT_AVAILABLE:
            threading.Thread(target=start_mqtt_client, daemon=True, name="MQTTStarter").start()
            threading.Thread(target=mqtt_heartbeat_worker, daemon=True, name="MQTTHeartbeat").start()
            threading.Thread(target=mqtt_telemetry_streamer, daemon=True, name="MQTTTelemetry").start()
            threading.Thread(target=sync_offline_data_worker, daemon=True, name="MQTTOfflineSync").start()
        else:
            logging.error("MQTT requested but paho-mqtt is not installed")

        app.mainloop()
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received")
        try:
            hw.emergency_all_off()
        except Exception:
            logging.exception("Emergency all-off failed after keyboard interrupt")
    except Exception:
        logging.exception("Fatal application error")
        try:
            hw.emergency_all_off()
        except Exception:
            logging.exception("Emergency all-off failed after fatal error")
        sys.exit(1)
    finally:
        running = False
        try:
            if control_client is not None:
                control_client.disconnect()
                control_client.loop_stop()
        except Exception:
            logging.exception("MQTT shutdown failed")
        logging.info("Merged InHydro controller stopped")
