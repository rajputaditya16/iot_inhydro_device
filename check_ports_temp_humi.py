#!/usr/bin/env python3
"""
Standalone Diagnostic Tool: Scan Laptop Serial Ports for Temperature & Humidity Sensors
Device: MD02 / SHT20 / TH Modbus RTU Sensors
"""

import os
import glob
import time
import serial
import struct

def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if (crc & 0x0001) != 0:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return struct.pack('<H', crc)

def read_md02_direct(port_name, baudrate=9600, slave_id=1, timeout=0.3):
    """
    Attempts to read 2 registers (Temp & Humi) from MD02 Modbus RTU sensor.
    FC 0x04 or FC 0x03.
    """
    try:
        ser = serial.Serial(
            port=port_name,
            baudrate=baudrate,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=timeout
        )
        
        # 1. Test Function Code 4 (Read Input Registers, Reg 0x0000, 2 registers)
        req_fc4 = bytes([slave_id, 0x04, 0x00, 0x00, 0x00, 0x02])
        req_fc4 += crc16(req_fc4)
        
        ser.reset_input_buffer()
        ser.write(req_fc4)
        time.sleep(0.08)
        resp = ser.read(9)
        
        if len(resp) == 9 and resp[0] == slave_id and resp[1] == 0x04:
            raw_temp = (resp[3] << 8) | resp[4]
            raw_humi = (resp[5] << 8) | resp[6]
            
            if raw_temp > 32767:
                raw_temp -= 65536
                
            temp = raw_temp / 10.0
            humi = raw_humi / 10.0
            
            if -40.0 <= temp <= 80.0 and 0.0 <= humi <= 100.0:
                ser.close()
                return {"success": True, "fc": 4, "temp": temp, "humi": humi}
                
        # 2. Test Function Code 3 (Read Holding Registers, Reg 0x0000, 2 registers)
        req_fc3 = bytes([slave_id, 0x03, 0x00, 0x00, 0x00, 0x02])
        req_fc3 += crc16(req_fc3)
        
        ser.reset_input_buffer()
        ser.write(req_fc3)
        time.sleep(0.08)
        resp = ser.read(9)
        
        if len(resp) == 9 and resp[0] == slave_id and resp[1] == 0x03:
            raw_temp = (resp[3] << 8) | resp[4]
            raw_humi = (resp[5] << 8) | resp[6]
            
            if raw_temp > 32767:
                raw_temp -= 65536
                
            temp = raw_temp / 10.0
            humi = raw_humi / 10.0
            
            if -40.0 <= temp <= 80.0 and 0.0 <= humi <= 100.0:
                ser.close()
                return {"success": True, "fc": 3, "temp": temp, "humi": humi}

        # 3. Test Function Code 3 at Reg 0x0001 (Some SHT20 variants start at reg 1)
        req_fc3_reg1 = bytes([slave_id, 0x03, 0x00, 0x01, 0x00, 0x02])
        req_fc3_reg1 += crc16(req_fc3_reg1)

        ser.reset_input_buffer()
        ser.write(req_fc3_reg1)
        time.sleep(0.08)
        resp = ser.read(9)

        if len(resp) == 9 and resp[0] == slave_id and resp[1] == 0x03:
            raw_temp = (resp[3] << 8) | resp[4]
            raw_humi = (resp[5] << 8) | resp[6]

            if raw_temp > 32767:
                raw_temp -= 65536

            temp = raw_temp / 10.0
            humi = raw_humi / 10.0

            if -40.0 <= temp <= 80.0 and 0.0 <= humi <= 100.0:
                ser.close()
                return {"success": True, "fc": 3, "temp": temp, "humi": humi}
                
        ser.close()
    except Exception:
        pass
    return {"success": False}

def scan_all_ports():
    print("=" * 65)
    print("🔍 SCANNING LAPTOP SERIAL PORTS FOR TEMP & HUMIDITY SENSORS")
    print("=" * 65)
    
    candidates = []
    candidates.extend(glob.glob("/dev/ttyUSB*"))
    candidates.extend(glob.glob("/dev/ttyACM*"))
    by_path = glob.glob("/dev/serial/by-path/*")
    for bp in by_path:
        try:
            real_p = os.path.realpath(bp)
            if real_p not in candidates:
                candidates.append(real_p)
        except Exception: pass
            
    if not candidates:
        print("❌ No serial ports found on laptop/system! (/dev/ttyUSB*, /dev/ttyACM*)")
        print("=" * 65)
        return

    print(f"Found candidate ports: {candidates}\n")

    baud_rates = [9600, 4800, 19200]
    slave_ids = list(range(1, 16)) # Test slave IDs 1 through 15
    
    found_sensors = []
    
    for port in candidates:
        print(f"🔎 Scanning Port: {port}...")
        port_found = False
        
        for baud in baud_rates:
            for slave in slave_ids:
                res = read_md02_direct(port, baudrate=baud, slave_id=slave)
                if res["success"]:
                    print(f"  ✅ SENSOR DETECTED on {port} | Baud: {baud} | Slave ID: {slave} (FC{res['fc']})")
                    print(f"     ➔ Temperature : {res['temp']:.1f} °C")
                    print(f"     ➔ Humidity    : {res['humi']:.1f} %")
                    print("-" * 55)
                    found_sensors.append({
                        "port": port,
                        "baud": baud,
                        "slave": slave,
                        "temp": res['temp'],
                        "humi": res['humi']
                    })
                    port_found = True
                    break
            if port_found:
                break
                
        if not port_found:
            print(f"  ❌ No active MD02 / Temp-Humi sensor responding on {port}")
            print("-" * 55)

    print("\n" + "=" * 65)
    print("📋 SCAN SUMMARY RESULTS:")
    if found_sensors:
        for s in found_sensors:
            print(f" • Port: {s['port']} | Baud: {s['baud']} | ID: {s['slave']} => {s['temp']:.1f}°C, {s['humi']:.1f}%")
    else:
        print(" ❌ No Temperature/Humidity sensors detected on any tested port.")
    print("=" * 65)

if __name__ == "__main__":
    scan_all_ports()
