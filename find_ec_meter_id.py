#!/usr/bin/env python3
"""
Deep Scanner to locate the dedicated EC Controller Modbus Slave ID & Registers
Scans Slave IDs 1 to 247 on both /dev/ttyUSB0 and /dev/ttyUSB1
"""

import sys
import time
import glob
import minimalmodbus

def scan_port_all_slaves(port):
    print(f"\n==================================================")
    print(f"🔍 Deep Scanning ALL Slave IDs (1..247) on {port}")
    print(f"==================================================")

    for baud in [9600, 4800, 19200]:
        for slave in range(30, 40):
            try:
                inst = minimalmodbus.Instrument(port, slave)
                inst.serial.baudrate = baud
                inst.serial.timeout = 0.15
                inst.mode = minimalmodbus.MODE_RTU
                inst.clear_buffers_before_each_transaction = True

                print(f"⚡ Testing {port} @ Baud {baud} | Slave ID {slave}...", end="\r", flush=True)

                # Try reading Reg 0, Reg 1, Reg 18 with FC3 and FC4
                for reg in [0, 1, 18]:
                    for fc in [3, 4]:
                        try:
                            val = inst.read_register(reg, 0, functioncode=fc)
                            print(f"\n🎉 FOUND MODBUS DEVICE on {port}!")
                            print(f"   ► Baud: {baud} | Slave ID: {slave} | FC: {fc} | Reg {reg}: {val}")
                            
                            # Read block if possible
                            try:
                                regs = inst.read_registers(reg, 3, functioncode=fc)
                                print(f"   ► Block Reg {reg}-{reg+2}: {regs}")
                            except Exception: pass
                        except Exception:
                            pass
            except Exception:
                pass
            finally:
                try: inst.serial.close()
                except: pass

    print(f"\nScan finished on {port}.")

def main():
    ports = sorted(glob.glob("/dev/ttyUSB*"))
    for p in ports:
        scan_port_all_slaves(p)

if __name__ == "__main__":
    main()
