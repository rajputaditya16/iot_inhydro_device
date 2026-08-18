#!/usr/bin/env python3
"""
Sensor Data Reader for RS485 / Modbus Sensors
(Supports Temperature, Humidity, EC, pH and general Modbus RTU devices)
"""

import time
import glob
import os
import sys
import minimalmodbus

def print_header(title):
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)

def find_serial_ports():
    ports = []
    by_path = "/dev/serial/by-path"
    if os.path.exists(by_path):
        for f in os.listdir(by_path):
            full_p = os.path.join(by_path, f)
            real_p = os.path.realpath(full_p)
            if real_p not in ports:
                ports.append(real_p)
    
    usb_ports = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    for p in usb_ports:
        if p not in ports:
            ports.append(p)
            
    return ports

def scan_and_read_sensor():
    print_header("INHYDRO RS485 SENSOR SCANNER & READER")
    ports = find_serial_ports()
    
    if not ports:
        print("❌ No serial ports found (e.g. /dev/ttyUSB0). Check USB-RS485 adapter.")
        return None
    
    print(f"📡 Detected Serial Ports: {ports}\n")
    
    baud_rates = [9600, 4800, 19200]
    # Standard slave IDs used in InHydro devices: 1 (pH / MD02), 2 (Temp/Humi), 3 (EC), 247, 255
    slave_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 31, 32, 247, 254, 255]
    
    found_device = None
    
    for port in ports:
        print(f"🔍 Scanning port: {port}...")
        for baud in baud_rates:
            for slave in slave_ids:
                try:
                    inst = minimalmodbus.Instrument(port, slave)
                    inst.serial.baudrate = baud
                    inst.serial.timeout = 0.15
                    inst.mode = minimalmodbus.MODE_RTU
                    inst.clear_buffers_before_each_transaction = True
                    
                    # Test common register ranges (0-5, 32-35)
                    for fc in [3, 4]:
                        for reg in [0, 1, 2, 3, 4, 32]:
                            try:
                                values = inst.read_registers(reg, 2, functioncode=fc)
                                if values and len(values) >= 2:
                                    raw0, raw1 = values[0], values[1]
                                    if raw0 != 0 or raw1 != 0:
                                        print(f"\n✅ SENSOR FOUND!")
                                        print(f"   • Port:       {port}")
                                        print(f"   • Baudrate:   {baud}")
                                        print(f"   • Slave ID:   {slave}")
                                        print(f"   • Function:   0x{fc:02X}")
                                        print(f"   • Start Reg:  {reg}")
                                        print(f"   • Raw Values: {values}")
                                        
                                        found_device = {
                                            "port": port,
                                            "baud": baud,
                                            "slave": slave,
                                            "fc": fc,
                                            "start_reg": reg
                                        }
                                        inst.serial.close()
                                        return found_device
                            except Exception:
                                pass
                    inst.serial.close()
                except Exception:
                    pass
                    
    # If standard scan didn't find, scan all slave IDs 1..247 on port
    print("\n🔍 Extended scan across all slave IDs (1 to 247)...")
    for port in ports:
        for baud in [9600, 4800]:
            for slave in range(1, 248):
                try:
                    inst = minimalmodbus.Instrument(port, slave)
                    inst.serial.baudrate = baud
                    inst.serial.timeout = 0.08
                    inst.mode = minimalmodbus.MODE_RTU
                    
                    try:
                        val = inst.read_register(0, 0, functioncode=3)
                        print(f"\n✅ SENSOR RESPONDED! Port: {port}, Baud: {baud}, Slave: {slave}, FC: 3, Reg 0: {val}")
                        found_device = {"port": port, "baud": baud, "slave": slave, "fc": 3, "start_reg": 0}
                        inst.serial.close()
                        return found_device
                    except Exception:
                        try:
                            val = inst.read_register(0, 0, functioncode=4)
                            print(f"\n✅ SENSOR RESPONDED! Port: {port}, Baud: {baud}, Slave: {slave}, FC: 4, Reg 0: {val}")
                            found_device = {"port": port, "baud": baud, "slave": slave, "fc": 4, "start_reg": 0}
                            inst.serial.close()
                            return found_device
                        except Exception:
                            pass
                    inst.serial.close()
                except Exception:
                    pass
                    
    return None

def start_continuous_reading(dev):
    print_header(f"CONTINUOUS SENSOR TELEMETRY (Port: {dev['port']} | Slave: {dev['slave']} | Baud: {dev['baud']})")
    print("Press Ctrl+C to stop.\n")
    
    port = dev['port']
    slave = dev['slave']
    baud = dev['baud']
    fc = dev['fc']
    start_reg = dev['start_reg']
    
    try:
        inst = minimalmodbus.Instrument(port, slave)
        inst.serial.baudrate = baud
        inst.serial.timeout = 0.3
        inst.mode = minimalmodbus.MODE_RTU
        
        while True:
            t_now = time.strftime("%Y-%m-%d %H:%M:%S")
            try:
                # Read 2 registers starting from start_reg
                values = inst.read_registers(start_reg, 2, functioncode=fc)
                val0, val1 = values[0], values[1]
                
                # Check for negative temp (16-bit signed)
                s_val0 = val0 - 65536 if val0 > 32767 else val0
                s_val1 = val1 - 65536 if val1 > 32767 else val1
                
                # Decode temperature / humidity interpretations
                # MD02 / SHT20 / Renke usually: Reg 0 = Temp/Humi or Reg 1 = Humi/Temp (scaled by 10)
                d0_div10 = round(s_val0 / 10.0, 1)
                d1_div10 = round(s_val1 / 10.0, 1)
                d0_div100 = round(s_val0 / 100.0, 2)
                d1_div100 = round(s_val1 / 100.0, 2)
                
                print(f"[{t_now}] Raw Reg[{start_reg}]: {val0} ({s_val0}) | Reg[{start_reg+1}]: {val1} ({s_val1})")
                
                # Identify standard ranges
                if -20 <= d0_div10 <= 80 and 0 <= d1_div10 <= 100:
                    print(f"    ➜ Temperature: {d0_div10} °C  |  Humidity: {d1_div10} %RH")
                elif -20 <= d1_div10 <= 80 and 0 <= d0_div10 <= 100:
                    print(f"    ➜ Humidity: {d0_div10} %RH  |  Temperature: {d1_div10} °C")
                elif 0 <= d0_div100 <= 14:
                    print(f"    ➜ pH Value: {d0_div100}")
                elif 0 <= d0_div10 <= 5000:
                    print(f"    ➜ EC Value: {d0_div10} uS/cm")
                
            except Exception as e:
                print(f"[{t_now}] ⚠️ Error reading sensor: {e}")
                
            time.sleep(1.0)
            
    except KeyboardInterrupt:
        print("\nStopped continuous reading.")
    finally:
        try: inst.serial.close()
        except: pass

if __name__ == "__main__":
    device = scan_and_read_sensor()
    if device:
        start_continuous_reading(device)
    else:
        print("\n❌ Could not read any sensor data automatically.")
        print("💡 Troubleshooting Tips:")
        print(" 1. Check A and B wiring (Try swapping A and B wires).")
        print(" 2. Ensure 10-30V DC power supply is connected to + and - terminals.")
        print(" 3. Verify USB-RS485 adapter is detected.")
