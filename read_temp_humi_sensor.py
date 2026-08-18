#!/usr/bin/env python3
"""
===================================================================
 INHYDRO RS485 TEMPERATURE & HUMIDITY SENSOR READER
===================================================================
Device Type: RS485 Modbus RTU Temperature & Humidity Transmitter
Port:        /dev/ttyUSB0 (auto-detected)
Baud Rate:   4800
Slave ID:    1
Protocol:    Modbus RTU (FC3 / Holding Registers)
             • Register 0x0000 (0): Humidity (%RH * 10)
             • Register 0x0001 (1): Temperature (°C * 10)
===================================================================
"""

import os
import sys
import glob
import time
import minimalmodbus
import serial

# Sensor Configuration Parameters
SLAVE_ID = 1
BAUDRATE = 4800

def find_sensor_port():
    """Detect available USB serial ports on the system."""
    # Check by-path ports first for stability
    by_path = "/dev/serial/by-path"
    if os.path.exists(by_path):
        for f in os.listdir(by_path):
            return os.path.join(by_path, f)
            
    # Fallback to standard /dev/ttyUSB* ports
    ports = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    if ports:
        return ports[0]
        
    return "/dev/ttyUSB0"

def read_sensor_data(port):
    """Initializes Modbus instrument and reads temperature and humidity registers."""
    try:
        inst = minimalmodbus.Instrument(port, SLAVE_ID)
        inst.serial.baudrate = BAUDRATE
        inst.serial.bytesize = 8
        inst.serial.parity = serial.PARITY_NONE
        inst.serial.stopbits = 1
        inst.serial.timeout = 0.3
        inst.mode = minimalmodbus.MODE_RTU
        inst.clear_buffers_before_each_transaction = True

        # Read 2 registers starting at address 0 using Function Code 3
        # Register 0 = Relative Humidity (scale 10x)
        # Register 1 = Temperature in °C (scale 10x)
        raw_values = inst.read_registers(0, 2, functioncode=3)
        inst.serial.close()

        if raw_values and len(raw_values) >= 2:
            raw_humi = raw_values[0]
            raw_temp = raw_values[1]

            # Handle 16-bit signed integer for negative temperatures
            if raw_temp > 32767:
                raw_temp -= 65536

            humidity = round(raw_humi / 10.0, 1)
            temp_c = round(raw_temp / 10.0, 1)
            temp_f = round((temp_c * 9/5) + 32, 1)

            return True, temp_c, temp_f, humidity, raw_temp, raw_humi

    except Exception as e:
        return False, None, None, None, None, str(e)

    return False, None, None, None, None, "No data received"

def main():
    print("=" * 65)
    print(" 🌡️  INHYDRO RS485 TEMP & HUMIDITY SENSOR DATA MONITOR 💧")
    print("=" * 65)

    port = find_sensor_port()
    print(f"📡 Serial Port : {port}")
    print(f"⚙️  Baud Rate   : {BAUDRATE}")
    print(f"🆔 Slave ID    : {SLAVE_ID}")
    print("-" * 65)
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            success, temp_c, temp_f, humidity, raw_t, raw_h = read_sensor_data(port)

            if success:
                print(f"[{timestamp}] ✅ 🌡️ Temp: {temp_c:4.1f} °C ({temp_f:5.1f} °F)  |  💧 Humi: {humidity:4.1f} %RH  [Raw: T={raw_t}, H={raw_h}]", flush=True)
            else:
                print(f"[{timestamp}] ⚠️ Sensor Reading Error: {raw_h}", flush=True)

            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n\n🛑 Sensor monitoring stopped by user.")
        sys.exit(0)

if __name__ == "__main__":
    main()
