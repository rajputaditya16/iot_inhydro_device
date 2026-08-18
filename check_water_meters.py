#!/usr/bin/env python3
import os
import sys
import glob
import time
import minimalmodbus

def print_header(title):
    print("=" * 60)
    print(f" {title}")
    print("=" * 60)

print_header("INHYDRO WATER SENSOR DIAGNOSTIC TOOL (EC: ID 3 | pH: ID 1)")

# 1. List all available USB serial ports
print("\n[1] SCANNING AVAILABLE SERIAL PORTS ON SYSTEM:")
by_path_dir = "/dev/serial/by-path"
by_path_ports = []
if os.path.exists(by_path_dir):
    for f in os.listdir(by_path_dir):
        full_p = os.path.join(by_path_dir, f)
        by_path_ports.append(full_p)
        print(f"  • BY-PATH: {full_p} -> {os.path.realpath(full_p)}")
else:
    print("  ⚠️ /dev/serial/by-path directory not found!")

tty_ports = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
for p in tty_ports:
    print(f"  • TTY PORT: {p}")

all_ports = by_path_ports + [p for p in tty_ports if p not in [os.path.realpath(x) for x in by_path_ports]]

if not all_ports:
    print("\n❌ NO USB SERIAL PORTS DETECTED ON THIS COMPUTER!")
    print("Please check that your USB-to-RS485 converters are plugged in firmly.")
    sys.exit(1)

# 2. Configured Slave IDs: EC = 3, pH = 1
DEVICE_ID_EC = 3
DEVICE_ID_PH = 1

def read_ec(port):
    inst = None
    try:
        inst = minimalmodbus.Instrument(port, DEVICE_ID_EC)
        inst.serial.baudrate = 9600
        inst.serial.timeout = 0.25
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True

        for fc in [3, 4]:
            for reg in [3, 0, 1]:
                try:
                    raw_ec = inst.read_register(reg, 0, functioncode=fc)
                    if raw_ec is not None and raw_ec > 0:
                        ec_val = round(raw_ec / 1000.0, 3) if raw_ec > 10 else round(float(raw_ec), 3)
                        return True, ec_val, raw_ec
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        if inst and hasattr(inst, 'serial') and inst.serial and getattr(inst.serial, 'is_open', False):
            try: inst.serial.close()
            except Exception: pass
    return False, None, None

def read_ph(port):
    inst = None
    try:
        inst = minimalmodbus.Instrument(port, DEVICE_ID_PH)
        inst.serial.baudrate = 9600
        inst.serial.timeout = 0.25
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True

        for fc in [3, 4]:
            for reg in range(0, 5):
                try:
                    ph_raw = inst.read_register(reg, 0, functioncode=fc)
                    if ph_raw is not None and ph_raw > 0:
                        ph_val = round(ph_raw / 100.0, 2) if ph_raw > 50 else round(float(ph_raw), 2)
                        if 0 <= ph_val <= 14:
                            return True, ph_val, ph_raw
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        if inst and hasattr(inst, 'serial') and inst.serial and getattr(inst.serial, 'is_open', False):
            try: inst.serial.close()
            except Exception: pass
    return False, None, None

print("\n[2] TESTING WATER METERS ACROSS ALL DETECTED PORTS:")

working_water_port = None

for port in all_ports:
    print(f"\n🔍 Testing Port: {port}")
    ec_ok, ec_val, raw_ec = read_ec(port)
    ph_ok, ph_val, raw_ph = read_ph(port)

    if ec_ok or ph_ok:
        working_water_port = port
        print(f"  ✅ SUCCESS on port: {port}")
        if ec_ok:
            print(f"     • LIVE EC (ID {DEVICE_ID_EC}) : {ec_val} mS/cm  (Raw: {raw_ec})")
        else:
            print(f"     • EC (ID {DEVICE_ID_EC})       : No Response")
        if ph_ok:
            print(f"     • LIVE pH (ID {DEVICE_ID_PH}) : {ph_val}  (Raw: {raw_ph})")
        else:
            print(f"     • pH (ID {DEVICE_ID_PH})       : No Response")
    else:
        print(f"  ❌ No EC/pH response on {port}")

# 3. Continuous Monitoring Loop if a working port was found
if working_water_port:
    print_header(f"CONTINUOUS LIVE MONITORING ON {working_water_port} (Press Ctrl+C to Stop)")
    try:
        while True:
            ec_ok, ec_val, raw_ec = read_ec(working_water_port)
            ph_ok, ph_val, raw_ph = read_ph(working_water_port)
            
            t_now = time.strftime("%H:%M:%S")
            ec_str = f"{ec_val:.3f} mS/cm ({raw_ec})" if ec_ok else "NO DATA"
            ph_str = f"{ph_val:.2f} ({raw_ph})" if ph_ok else "NO DATA"
            
            print(f"[{t_now}]  EC (ID 3): {ec_str:22s} | pH (ID 1): {ph_str}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n\nStopped continuous monitoring.")
else:
    print("\n❌ Could not find EC or pH meter on any active serial port.")
    print("Please verify RS485 wiring (+ and -), 12V power supply, and baud rate.")
