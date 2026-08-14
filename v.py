import time
import serial

# --- CONFIGURATION ---
# Check your USB-to-RS485 port name using 'ls /dev/tty*' in terminal. 
# It is usually /dev/ttyUSB0 or /dev/ttyACM0.
PORT_NAME = '/dev/ttyUSB0' 

try:
    # Initialize the serial port with Modbus factory settings
    ser = serial.Serial(
        port=PORT_NAME,
        baudrate=9600,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=1
    )
except serial.SerialException as e:
    print(f"Error: Could not open port {PORT_NAME}. Is the USB adapter plugged in?")
    print(f"Details: {e}")
    exit()

def get_modbus_data():
    # Factory Default Modbus Command Frame for XY-MD02:
    # [0x01: Slave] [0x04: Read Reg] [0x00, 0x01: Address] [0x00, 0x02: Count] [0x20, 0x0B: CRC]
    modbus_request = b'\x01\x04\x00\x01\x00\x02\x20\x0b'
    
    # Flush buffers to avoid reading old messy data
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    
    # Transmit raw binary Hex frame down the RS485 wire
    ser.write(modbus_request)
    time.sleep(0.1) # Brief pause for hardware turnaround time
    
    # Read incoming response packet
    if ser.in_waiting >= 9:
        response = ser.read(ser.in_waiting)
        
        # Verify valid Modbus framework response length and leading operational codes
        if len(response) >= 9 and response[0] == 0x01 and response[1] == 0x04:
            # Reconstruct high and low bytes into integers
            raw_temp = (response[3] << 8) | response[4]
            raw_hum = (response[5] << 8) | response[6]
            
            # Handle negative temperature validation (Two's Complement)
            if raw_temp > 0x7FFF:
                raw_temp -= 0x10000
                
            # Scale raw data down to decimal format
            temperature = raw_temp / 10.0
            humidity = raw_hum / 10.0
            
            return temperature, humidity
            
    return None, None

print(f"Starting Modbus Master loop on {PORT_NAME}...")
try:
    while True:
        temp, hum = get_modbus_data()
        
        print("\n--- Modbus Output ---")
        if temp is not None and hum is not None:
            print(f"Temperature : {temp:.1f} °C")
            print(f"Humidity    : {hum:.1f} %RH")
        else:
            print("Modbus Error: No response received.")
            print("Steps to fix:")
            print(" 1. Ensure sensor A & B pins are split and wired into adapter A & B pins.")
            print(" 2. Ensure your sensor is powered with external 10V-30V DC.")
            
        time.sleep(2)

except KeyboardInterrupt:
    print("\nExiting script...")
finally:
    ser.close()
