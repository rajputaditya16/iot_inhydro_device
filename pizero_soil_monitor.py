#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║         INHYDRO  —  Pi Zero Soil Sensor Monitor             ║
║   Hardware : Raspberry Pi Zero + MAX485 Module              ║
║   Sensor   : RS485 Soil Sensor (EC / pH / Temp / Moisture)  ║
║   Display  : HDMI via Tkinter  (fullscreen)                 ║
╚══════════════════════════════════════════════════════════════╝

─── STEP-BY-STEP SETUP (Do this ONCE before running) ───────────

STEP 1 — Enable the hardware UART on Pi Zero:
  sudo raspi-config
  → Interface Options → Serial Port
     "Login shell over serial?" → NO
     "Enable serial port hardware?" → YES
  → Finish → Reboot

STEP 2 — Install Python libraries:
  pip install minimalmodbus pyserial RPi.GPIO Pillow

STEP 3 — Wire MAX485 ↔ Pi Zero  (use BCM / GPIO numbers):

  MAX485 Pin          Pi Zero GPIO  Board-Pin
  ──────────────────────────────────────────
  DI  (Data In)    →  GPIO 14 (TXD)   Pin 8
  RO  (Data Out)   →  GPIO 15 (RXD)   Pin 10
  DE  ┐ tied        →  GPIO 18         Pin 12    ← DE/RE together
  RE  ┘ together   →  GPIO 18         Pin 12
  VCC              →  5V              Pin 2
  GND              →  GND             Pin 6

  MAX485 A+ ──────────→ Sensor RS485 A+
  MAX485 B- ──────────→ Sensor RS485 B-

STEP 4 — Run:
  python3 pizero_soil_monitor.py

─── HOW DE/RE WORKS ────────────────────────────────────────────
  DE=HIGH, RE=HIGH  →  MAX485 in TRANSMIT mode  (Pi → Sensor)
  DE=LOW,  RE=LOW   →  MAX485 in RECEIVE  mode  (Sensor → Pi)
  Both DE and RE are tied to the SAME GPIO  pin (GPIO 18),
  so one pin controls the full direction switch.

─── SENSOR REGISTERS (Same as almora1.py) ──────────────────────
  0x0012  Moisture     (× 0.1  %)
  0x0013  Temperature  (× 0.1  °C,  signed)
  0x0015  EC           (us/cm, no scale)
  0x0006  pH           (× 0.01)
"""

# ════════════════════════════════════════════════════════════════
#  IMPORTS
# ════════════════════════════════════════════════════════════════
import os, sys, time, threading, datetime
import tkinter as tk
from tkinter import font as tkfont

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("ERROR: RPi.GPIO not found. Run:  pip install RPi.GPIO")
    sys.exit(1)

try:
    import serial
    import minimalmodbus
except ImportError:
    print("ERROR: Install libs:  pip install minimalmodbus pyserial")
    sys.exit(1)

# ════════════════════════════════════════════════════════════════
#  HARDWARE CONFIG  ←── Change these if your wiring is different
# ════════════════════════════════════════════════════════════════
SERIAL_PORT = "/dev/ttyAMA0"   # Pi Zero hardware UART
                                # Try /dev/serial0 if this fails
DEVICE_ID   = 1                # Modbus address printed on sensor (default 1)
DE_RE_PIN   = 18               # BCM GPIO pin → MAX485 DE + RE  (tied together)

# ════════════════════════════════════════════════════════════════
#  GPIO  SETUP
# ════════════════════════════════════════════════════════════════
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(DE_RE_PIN, GPIO.OUT)
GPIO.output(DE_RE_PIN, GPIO.LOW)   # Start in RECEIVE mode

# ════════════════════════════════════════════════════════════════
#  CUSTOM RS485 SERIAL CLASS
#  — Wraps pyserial and auto-toggles DE/RE around every write()
#  — minimalmodbus calls write() internally, so this is transparent
# ════════════════════════════════════════════════════════════════
class RS485Serial(serial.Serial):
    """
    Drop-in replacement for serial.Serial that controls the MAX485
    DE/RE direction pin automatically on every write() call.

    Flow for every Modbus request:
      1) GPIO HIGH  → TX mode  (Pi Zero drives RS485 bus)
      2) write bytes (minimalmodbus request frame)
      3) flush()    → wait until last bit has left the UART FIFO
      4) sleep()    → exact byte-transmission time at 9600 baud
      5) GPIO LOW   → RX mode  (Pi Zero listens for sensor reply)
    """
    def __init__(self, de_re_gpio_pin, *args, **kwargs):
        self._pin = de_re_gpio_pin
        super().__init__(*args, **kwargs)

    def write(self, data):
        # ── TX mode ──
        GPIO.output(self._pin, GPIO.HIGH)
        time.sleep(0.0001)                           # 100 µs settling

        result = super().write(data)
        super().flush()                               # block until UART empty

        # 9600 baud: 10 bits/byte (1 start + 8 data + 1 stop)
        tx_duration = (len(data) * 10.0) / 9600.0
        time.sleep(tx_duration + 0.003)              # +3 ms safety margin

        # ── RX mode ── sensor will now reply
        GPIO.output(self._pin, GPIO.LOW)
        return result

# ════════════════════════════════════════════════════════════════
#  MINIMALMODBUS INSTRUMENT  (identical settings to almora1.py)
# ════════════════════════════════════════════════════════════════
def create_instrument():
    """Create and return a configured minimalmodbus Instrument."""

    # Open our custom RS485Serial port
    rs485 = RS485Serial(
        de_re_gpio_pin = DE_RE_PIN,
        port           = SERIAL_PORT,
        baudrate       = 9600,
        bytesize       = 8,
        parity         = serial.PARITY_NONE,
        stopbits       = 1,
        timeout        = 1
    )

    # Hand it to minimalmodbus — same as almora1.py
    instr = minimalmodbus.Instrument.__new__(minimalmodbus.Instrument)
    instr.serial       = rs485
    instr.address      = DEVICE_ID
    instr.mode         = minimalmodbus.MODE_RTU
    instr.debug        = False
    instr.close_port_after_each_call = False
    return instr

instrument = None   # Created inside __main__ after GPIO is ready

# ════════════════════════════════════════════════════════════════
#  SENSOR READ  — EXACTLY the same registers as almora1.py
# ════════════════════════════════════════════════════════════════
def read_sensor():
    """
    Reads 4 values from the RS485 soil sensor.
    Returns dict with temp, moist, ec, ph — or None on error.
    """
    try:
        moist = instrument.read_register(0x0012, 1)              # 0.1 %
        temp  = instrument.read_register(0x0013, 1, signed=True) # 0.1 °C
        ec    = instrument.read_register(0x0015, 0)              # us/cm
        ph    = instrument.read_register(0x0006, 2)              # 0.01 pH
        return {"temp": temp, "moist": moist, "ec": ec, "ph": ph}
    except Exception as e:
        log(f"Sensor error: {e}")
        return None

# ════════════════════════════════════════════════════════════════
#  SHARED STATE
# ════════════════════════════════════════════════════════════════
sensor_data  = {}
data_lock    = threading.Lock()
running      = True
log_queue    = []
log_lock     = threading.Lock()

# ════════════════════════════════════════════════════════════════
#  LOGGER  (thread-safe — feeds the Tkinter terminal panel)
# ════════════════════════════════════════════════════════════════
def log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}]  {msg}"
    print(line)
    with log_lock:
        log_queue.append(line)

# ════════════════════════════════════════════════════════════════
#  SENSOR READER THREAD
# ════════════════════════════════════════════════════════════════
def sensor_reader():
    global running
    log(f"Sensor thread started → {SERIAL_PORT}  Slave ID={DEVICE_ID}")
    while running:
        data = read_sensor()
        if data:
            with data_lock:
                sensor_data.update(data)
                sensor_data["status"] = "OK"
            log(f"T={data['temp']}°C  "
                f"Moist={data['moist']}%  "
                f"EC={data['ec']} us/cm  "
                f"pH={data['ph']}")
        else:
            with data_lock:
                sensor_data["status"] = "ERROR"
        time.sleep(2.0)

# ════════════════════════════════════════════════════════════════
#  TKINTER UI
# ════════════════════════════════════════════════════════════════
BG      = "#0d1b2a"
CARD_BG = "#132338"
ACCENT  = "#00d4ff"
GREEN   = "#00e676"
ORANGE  = "#ffab40"
RED     = "#ff5252"
PURPLE  = "#ce93d8"
GRAY    = "#7a8fa6"
WHITE   = "#ffffff"
TERM_BG = "#0a0f1a"
TERM_FG = "#39ff14"   # Classic green terminal text

root = tk.Tk()
root.title("Inhydro Pi Zero — Soil Monitor")
root.attributes("-fullscreen", True)
root.configure(bg=BG)
root.bind("<Escape>", lambda e: quit_app())

F_TITLE  = tkfont.Font(family="Arial", size=18, weight="bold")
F_LABEL  = tkfont.Font(family="Arial", size=11)
F_VALUE  = tkfont.Font(family="Arial", size=40, weight="bold")
F_UNIT   = tkfont.Font(family="Arial", size=13)
F_STATUS = tkfont.Font(family="Arial", size=12)
F_BTN    = tkfont.Font(family="Arial", size=12, weight="bold")
F_TERM   = tkfont.Font(family="Courier", size=10)

# ── HEADER ───────────────────────────────────────────────────
hdr = tk.Frame(root, bg=BG)
hdr.pack(fill="x", padx=18, pady=(14, 0))

tk.Label(hdr, text="INHYDRO  |  SOIL MONITOR  |  Pi Zero",
         font=F_TITLE, fg=ACCENT, bg=BG).pack(side="left")

lbl_clock = tk.Label(hdr, text="", font=F_LABEL, fg=GRAY, bg=BG)
lbl_clock.pack(side="right")

lbl_status = tk.Label(root, text="● STARTING...", font=F_STATUS, fg=ORANGE, bg=BG)
lbl_status.pack(pady=(3, 0))

tk.Frame(root, bg=ACCENT, height=2).pack(fill="x", padx=18, pady=(4, 4))

# ── MAIN BODY (cards left, terminal right) ───────────────────
body = tk.Frame(root, bg=BG)
body.pack(fill="both", expand=True, padx=18, pady=0)

# ── LEFT: 2×2 DATA CARDS ─────────────────────────────────────
cards_frame = tk.Frame(body, bg=BG)
cards_frame.pack(side="left", fill="both", expand=True)
cards_frame.columnconfigure(0, weight=1)
cards_frame.columnconfigure(1, weight=1)
cards_frame.rowconfigure(0, weight=1)
cards_frame.rowconfigure(1, weight=1)

card_val_labels = {}   # key → tk.Label (the big number)

def make_card(parent, row, col, key, icon, label, unit, color):
    outer = tk.Frame(parent, bg=color, bd=0)
    outer.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

    inner = tk.Frame(outer, bg=CARD_BG)
    inner.pack(fill="both", expand=True, padx=2, pady=2)
    inner.rowconfigure(1, weight=1)
    inner.columnconfigure(0, weight=1)

    # Icon + label
    top = tk.Frame(inner, bg=CARD_BG)
    top.pack(fill="x", padx=12, pady=(10, 0))
    tk.Label(top, text=icon,   font=tkfont.Font(size=20), bg=CARD_BG).pack(side="left")
    tk.Label(top, text=f"  {label}", font=F_LABEL, fg=GRAY, bg=CARD_BG).pack(side="left")

    # Big value
    lv = tk.Label(inner, text="---", font=F_VALUE, fg=color, bg=CARD_BG, anchor="center")
    lv.pack(fill="both", expand=True)

    # Unit
    tk.Label(inner, text=unit, font=F_UNIT, fg=GRAY, bg=CARD_BG).pack(pady=(0, 10))

    card_val_labels[key] = lv

make_card(cards_frame, 0, 0, "temp",  "🌡", "TEMPERATURE", "°C",      ACCENT)
make_card(cards_frame, 0, 1, "moist", "💧", "MOISTURE",    "%",       GREEN)
make_card(cards_frame, 1, 0, "ec",    "⚡", "EC",          "us/cm",   ORANGE)
make_card(cards_frame, 1, 1, "ph",    "🧪", "pH",          "",        PURPLE)

# ── RIGHT: TKINTER TERMINAL PANEL ────────────────────────────
term_frame = tk.Frame(body, bg=CARD_BG, bd=0,
                      highlightbackground=ACCENT, highlightthickness=1)
term_frame.pack(side="right", fill="both", padx=(8, 0), pady=8)
term_frame.pack_propagate(True)

tk.Label(term_frame, text="  SYSTEM LOG  ",
         font=F_LABEL, fg=ACCENT, bg="#0a0f1a").pack(fill="x")

# Scrollable text widget (the "terminal")
term_text = tk.Text(
    term_frame,
    bg=TERM_BG, fg=TERM_FG,
    font=F_TERM,
    width=38,           # characters wide
    wrap="word",
    state="disabled",   # read-only
    bd=0,
    relief="flat",
    cursor="arrow"
)
term_scroll = tk.Scrollbar(term_frame, command=term_text.yview,
                            bg=CARD_BG, troughcolor=CARD_BG)
term_text.configure(yscrollcommand=term_scroll.set)
term_scroll.pack(side="right", fill="y")
term_text.pack(side="left", fill="both", expand=True, padx=4, pady=4)

MAX_LOG_LINES = 200   # keep last 200 lines in terminal

def terminal_write(line: str):
    """Append a line to the Tkinter terminal widget."""
    term_text.config(state="normal")
    term_text.insert("end", line + "\n")

    # Trim to MAX_LOG_LINES to avoid memory bloat
    line_count = int(term_text.index("end-1c").split(".")[0])
    if line_count > MAX_LOG_LINES:
        term_text.delete("1.0", f"{line_count - MAX_LOG_LINES}.0")

    term_text.see("end")    # auto-scroll to bottom
    term_text.config(state="disabled")

# ── FOOTER ───────────────────────────────────────────────────
footer = tk.Frame(root, bg="#0a1525", height=58)
footer.pack(side="bottom", fill="x")
footer.pack_propagate(False)

def quit_app():
    global running
    running = False
    log("Shutting down...")
    try: GPIO.cleanup()
    except: pass
    root.after(500, root.destroy)

def restart_program():
    global running
    running = False
    try: GPIO.cleanup()
    except: pass
    os.execl(sys.executable, sys.executable, *sys.argv)

tk.Button(footer, text="RESTART", font=F_BTN, bg="#1565c0", fg=WHITE,
          bd=0, width=10, command=restart_program).pack(side="left", padx=14, pady=10)
tk.Button(footer, text="EXIT", font=F_BTN, bg="#c62828", fg=WHITE,
          bd=0, width=10, command=quit_app).pack(side="right", padx=14, pady=10)

# ════════════════════════════════════════════════════════════════
#  UI UPDATE LOOP  (runs every 1 second in main thread)
# ════════════════════════════════════════════════════════════════
def update_ui():
    if not running:
        return

    # ── Clock ──
    lbl_clock.config(text=time.strftime("%H:%M:%S   %d %b %Y"))

    # ── Drain log queue into terminal widget ──
    with log_lock:
        lines = list(log_queue)
        log_queue.clear()
    for line in lines:
        terminal_write(line)

    # ── Status dot ──
    with data_lock:
        snap = dict(sensor_data)

    st = snap.get("status", "STARTING")
    if st == "OK":
        lbl_status.config(text="●  LIVE  —  Reading OK", fg=GREEN)
    elif st == "ERROR":
        lbl_status.config(text="●  SENSOR ERROR  —  Check RS485 A/B wiring", fg=RED)
    else:
        lbl_status.config(text=f"●  {st}", fg=ORANGE)

    # ── Data cards ──
    card_spec = {
        "temp":  (snap.get("temp"),  "1"),
        "moist": (snap.get("moist"), "1"),
        "ec":    (snap.get("ec"),    "0"),
        "ph":    (snap.get("ph"),    "2"),
    }
    for key, (val, dec) in card_spec.items():
        lbl = card_val_labels[key]
        if val is not None and st == "OK":
            lbl.config(text=f"{val:.{dec}f}")
        else:
            lbl.config(text="---")

    root.after(1000, update_ui)

# ════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    log("=" * 45)
    log("  INHYDRO Pi Zero — Soil Sensor Monitor")
    log(f"  UART Port : {SERIAL_PORT}")
    log(f"  Slave ID  : {DEVICE_ID}")
    log(f"  DE/RE Pin : GPIO BCM {DE_RE_PIN}  (Pin 12)")
    log("=" * 45)
    log("Initialising Modbus instrument...")

    try:
        instrument = create_instrument()
        log(f"OK — Serial port open: {SERIAL_PORT}")
    except Exception as e:
        log(f"FAILED to open serial port: {e}")
        log("Did you enable UART?  sudo raspi-config → Interface → Serial")
        log("Exiting.")
        GPIO.cleanup()
        sys.exit(1)

    log("Starting background sensor reader thread...")
    t = threading.Thread(target=sensor_reader, daemon=True)
    t.start()
    log("Sensor thread running.  First reading in ~2 seconds...")

    update_ui()
    root.mainloop()

    running = False
    try: GPIO.cleanup()
    except: pass
    log("Clean exit. Goodbye.")
