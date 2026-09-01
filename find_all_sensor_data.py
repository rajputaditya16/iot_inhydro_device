#!/usr/bin/env python3
"""
INHYDRO MODBUS SENSOR DATA SCANNER & REGISTER FINDER
This tool scans all serial ports, slave IDs (1..32), baud rates (4800/9600),
and registers (0..10) to pinpoint exactly where sensor data is located.
"""

import os
import sys
import glob
import time
import minimalmodbus

def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

print_header("INHYDRO MODBUS SENSOR DATA SCANNER")

# 1. Detect all available serial ports
by_path_dir = "/dev/serial/by-path"
ports = []

if os.path.exists(by_path_dir):
    for f in os.listdir(by_path_dir):
        p = os.path.join(by_path_dir, f)
        if not os.path.isdir(p):
            ports.append(p)

tty_ports = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
for p in tty_ports:
    if p not in [os.path.realpath(x) for x in ports if os.path.exists(x)]:
        ports.append(p)

print("\n📍 DETECTED SERIAL PORTS:")
for p in ports:
    target = os.path.realpath(p) if os.path.islink(p) else p
    print(f"  • {p} -> {target}")

if not ports:
    print("❌ No active serial ports found! Make sure USB-RS485 adapters are connected.")
    sys.exit(1)

SLAVE_IDS = [1, 2, 3, 11, 31, 32]
BAUDRATES = [9600, 4800]

found_sensors = []

for port in ports:
    print_header(f"SCANNING PORT: {port}")
    
    for baud in BAUDRATES:
        for slave in SLAVE_IDS:
            try:
                inst = minimalmodbus.Instrument(port, slave)
                inst.serial.baudrate = baud
                inst.serial.timeout = 0.25
                inst.mode = minimalmodbus.MODE_RTU
                inst.clear_buffers_before_each_transaction = True

                for fc in [3, 4]:
                    non_zero_regs = {}
                    for reg in range(0, 10):
                        try:
                            if hasattr(inst.serial, 'reset_input_buffer'):
                                try: inst.serial.reset_input_buffer()
                                except Exception: pass
                            val = inst.read_register(reg, 0, functioncode=fc)
                            if val is not None and val > 0:
                                non_zero_regs[reg] = val
                        except Exception:
                            pass
                    
                    if non_zero_regs:
                        print(f"  ✅ SENSOR FOUND -> Slave ID: {slave} | Baud: {baud} | FC: {fc}")
                        for reg, val in non_zero_regs.items():
                            guess = ""
                            val_div_10 = round(val / 10.0, 1)
                            val_div_100 = round(val / 100.0, 2)
                            val_div_1000 = round(val / 1000.0, 3)

                            if 0 <= val_div_10 <= 100 and val > 100:
                                guess += f" [Possible Temp/Humi: {val_div_10}]"
                            if 0 <= val_div_100 <= 14 and val > 50:
                                guess += f" [Possible pH: {val_div_100}]"
                            if 0.01 <= val_div_1000 <= 10.0:
                                guess += f" [Possible EC: {val_div_1000} mS/cm]"

                            print(f"     └─ Register {reg}: Raw = {val}{guess}")
                        
                        found_sensors.append({
                            "port": port,
                            "slave": slave,
                            "baud": baud,
                            "fc": fc,
                            "registers": non_zero_regs
                        })

                inst.serial.close()
            except Exception:
                pass

print_header("SCAN SUMMARY")
if found_sensors:
    print(f"Successfully located data for {len(found_sensors)} sensor configurations!")
    for s in found_sensors:
        print(f" • Port: {s['port']} | ID: {s['slave']} | Baud: {s['baud']} | FC: {s['fc']} | Regs: {s['registers']}")
else:
    print("❌ No Modbus sensors responded. Please check wiring, power (12V/24V), and connections.")

print("=" * 70 + "\n")
