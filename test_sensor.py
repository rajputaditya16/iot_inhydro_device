#!/usr/bin/env python3
"""
Renke RS-WS-N01-8-EX Modbus RTU Temperature & Humidity Sensor Reader
Datasheet URL: https://www.renkeer.com/product/modbus-rtu-temperature-sensor/
"""

import time
import minimalmodbus

PORT = "/dev/ttyUSB1"

def test_renke_sensor():
    print("=" * 65)
    print(" 🌡️ RENKE RS-WS-N01-8-EX SENSOR READER (MODBUS RTU) ")
    print("=" * 65)
    print(f"Connecting to Serial Port: {PORT}")
    print("Renke Protocol: Function Code 0x03 | Reg 0x0000=Humi, Reg 0x0001=Temp\n")

    while True:
        success = False
        # Try both 9600 and 4800 baudrate (Renke defaults)
        for baud in [9600, 4800]:
            # Try Slave ID 1, 2, 247
            for sid in [1, 2, 247]:
                try:
                    instrument = minimalmodbus.Instrument(PORT, sid)
                    instrument.serial.baudrate = baud
                    instrument.serial.bytesize = 8
                    instrument.serial.parity = minimalmodbus.serial.PARITY_NONE
                    instrument.serial.stopbits = 1
                    instrument.serial.timeout = 0.3

                    # Renke Official Command: Function Code 3, Register 0, Count 2
                    values = instrument.read_registers(0, 2, functioncode=3)
                    instrument.serial.close()

                    if values:
                        raw_humi = values[0]
                        raw_temp = values[1]

                        # Handle signed temperature (negative values)
                        if raw_temp > 32767:
                            raw_temp -= 65536

                        humi = raw_humi / 10.0
                        temp = raw_temp / 10.0

                        timestamp = time.strftime("%H:%M:%S")
                        print(f"[{timestamp}] ✅ [Baud {baud}] [Slave {sid}] 🌡️ Temp: {temp:.1f} °C  |  💧 Humidity: {humi:.1f} %RH", flush=True)
                        success = True
                        break
                except Exception:
                    pass
            if success:
                break

        if not success:
            timestamp = time.strftime("%H:%M:%S")
            print(f"[{timestamp}] ⚠️ No response (0 bytes). Check 12V Power & Wires: Pin 3=RS485-A(Red), Pin 4=RS485-B(Black)", flush=True)

        time.sleep(1.0)

if __name__ == "__main__":
    test_renke_sensor()