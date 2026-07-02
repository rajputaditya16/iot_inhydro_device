import sys
import select
from machine import Pin, DAC

# Initialize DAC on Pin 25 (DAC Channel 1)
dac = DAC(Pin(25))

# Set initial output to 0V
dac.write(0)

print("==================================================")
print("ESP32 DevKitV1 Serial DAC Controller Initialized")
print("Using Pin 25 (DAC Channel 1) for Analog Output")
print("Listening for command inputs (0-100)...")
print("==================================================")

# Create a poll object to listen to standard input (serial port)
poll_obj = select.poll()
poll_obj.register(sys.stdin, select.POLLIN)

buffer = ""

while True:
    # Check if there is data available to read from the serial port (wait up to 100ms)
    poll_results = poll_obj.poll(100)
    if poll_results:
        # Read available character
        char = sys.stdin.read(1)
        if char == '\n' or char == '\r':
            # Process the command once a newline is received
            command = buffer.strip()
            buffer = ""
            
            if command:
                try:
                    # Parse percentage value from command
                    percentage = float(command)
                    percentage = max(0.0, min(100.0, percentage))
                    
                    # Convert 0-100% to 8-bit DAC range (0-255)
                    dac_value = int((percentage / 100.0) * 255)
                    dac.write(dac_value)
                    
                    # Calculate output voltage (assuming 3.3V reference)
                    voltage = (dac_value / 255.0) * 3.3
                    
                    # Print feedback back to the serial console
                    print("ACK: Set brightness to {:.1f}% | DAC Value: {} | Voltage: {:.2f}V".format(percentage, dac_value, voltage))
                except ValueError:
                    print("ERR: Invalid command. Please send a numeric value between 0 and 100.")
        else:
            buffer += char