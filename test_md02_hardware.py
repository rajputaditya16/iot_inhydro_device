#!/usr/bin/env python3
import glob, minimalmodbus, time

print("🔍 INHYDRO MD02 SENSOR HARDWARE DIAGNOSTIC TOOL")
print("===============================================")

ports = sorted(list(set(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/serial/by-path/pci-0000:00:14.0-usb-0:4:1.0-port0"))))
print(f"📡 Detected Serial Ports: {ports}\n")

found = False
for p in ports:
    print(f"Testing port: {p} ...")
    for baud in [9600, 4800, 19200]:
        for slave in [1, 2, 3, 255, 31, 32]:
            try:
                inst = minimalmodbus.Instrument(p, slave)
                inst.serial.baudrate = baud
                inst.serial.timeout = 0.15
                inst.mode = minimalmodbus.MODE_RTU

                for reg in [1, 0]:
                    for fc in [4, 3]:
                        try:
                            rt_raw = inst.read_register(reg, 0, signed=True, functioncode=fc)
                            rh_raw = inst.read_register(reg + 1, 0, functioncode=fc)
                            if rt_raw is not None and rh_raw is not None:
                                rt = round(rt_raw / 10.0, 1) if rt_raw > 100 else round(float(rt_raw), 1)
                                rh = round(rh_raw / 10.0, 1) if rh_raw > 100 else round(float(rh_raw), 1)
                                if -10 <= rt <= 75 and 0 <= rh <= 100:
                                    print(f"\n✅ SUCCESS! MD02 SENSOR FOUND:")
                                    print(f"   - Port:       {p}")
                                    print(f"   - Baudrate:   {baud}")
                                    print(f"   - Slave ID:   {slave}")
                                    print(f"   - Temp:       {rt} °C")
                                    print(f"   - Humidity:   {rh} %")
                                    found = True
                                    inst.serial.close()
                                    break
                        except Exception:
                            pass
                    if found: break
                inst.serial.close()
            except Exception:
                pass
            if found: break
        if found: break

if not found:
    print("\n❌ NO MD02 SENSOR DETECTED ON ANY PORT.")
    print("Possible Causes & Solutions:")
    print(" 1. RS485 Wiring Polarity: Swap A (Data+) and B (Data-) wires on the sensor.")
    print(" 2. Power Supply: Ensure MD02 has 12V/24V DC power connected.")
    print(" 3. USB Converter: Check if USB-RS485 adapter is firmly plugged into the Pi/PC.")
