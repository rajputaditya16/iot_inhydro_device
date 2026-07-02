import network
import machine
import time
import usocket
from umqtt.simple import MQTTClient


# --- DEVICE CONFIGURATION ---
# Change this ID to 1, 2, 3, 4, 5, 6, 7, or 8 depending on which physical light this ESP8266 controls.
LIGHT_ID = 1

# --- WI-FI SETTINGS ---
# Connects to the local Hotspot hosted by the Raspberry Pi or router
WIFI_SSID = "iqoo z7s"
WIFI_PASSWORD = "Adity@003"

# --- MQTT SETTINGS ---
# Change this to the IP address of your Raspberry Pi (hotspot gateway)
LOCAL_BROKER = "192.168.4.1"  
MQTT_PORT = 1883
MQTT_CLIENT_ID = f"esp8266_light_{LIGHT_ID}"

LOCAL_TOPIC = f"lights/intensity/{LIGHT_ID}".encode()
LOCAL_STATUS_TOPIC = f"lights/status/{LIGHT_ID}".encode()

# --- PWM LIGHT SETUP ---
# Pin 4 is D2 on most NodeMCU ESP8266 boards
pwm_pin = machine.Pin(4, machine.Pin.OUT)
led_pwm = machine.PWM(pwm_pin)

def set_brightness(percentage):
    """Sets the duty cycle and PWM frequency for the light channel"""
    percentage = max(0, min(100, percentage))
    
    # Maintain 2000Hz frequency for smooth PWM control
    led_pwm.freq(2000)
    freq_label = "2000Hz"
        
    # MicroPython ESP8266 PWM duty cycle is 10-bit (0 to 1023)
    duty_value = int((percentage / 100) * 1023)
    led_pwm.duty(duty_value)
    print("Light ID: {} | Brightness: {}% | Frequency: {} | Duty: {}".format(
        LIGHT_ID, percentage, freq_label, duty_value
    ))

# --- WI-FI CONNECTION ---
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f"Connecting to Local Hotspot Wi-Fi: {WIFI_SSID}...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
    
    if wlan.isconnected():
        print("Connected to Wi-Fi! IP Address:", wlan.ifconfig()[0])
        return True
    else:
        print("Failed to connect to Wi-Fi hotspot.")
        return False

# --- MQTT CALLBACK ---
def mqtt_callback(topic, msg):
    topic_str = topic.decode('utf-8')
    msg_str = msg.decode('utf-8')
    print(f"Received: {msg_str} on topic: {topic_str}")
    try:
        percentage = int(msg_str)
        set_brightness(percentage)
    except ValueError:
        print("Invalid message payload (must be integer percentage)")

# --- INITIAL BOOT ---
set_brightness(0)  # Start off

# Keep retrying Wi-Fi without hard resetting the chip (avoids boot loops and light blinking)
print("Initializing Wi-Fi connection...")
while not connect_wifi():
    print("Wi-Fi connection failed. Retrying in 5 seconds...")
    time.sleep(5)

local_client = None

# Connect to local broker (offline control)
try:
    print(f"Connecting to Local Pi Broker: {LOCAL_BROKER}...")
    local_client = MQTTClient(MQTT_CLIENT_ID, LOCAL_BROKER, port=MQTT_PORT, keepalive=60)
    local_client.set_callback(mqtt_callback)
    local_client.set_last_will(LOCAL_STATUS_TOPIC, b"offline", retain=True, qos=1)
    local_client.connect()
    local_client.subscribe(LOCAL_TOPIC)
    local_client.publish(LOCAL_STATUS_TOPIC, b"online", retain=True, qos=1)
    print(f"Connected Locally! Subscribed to {LOCAL_TOPIC.decode('utf-8')}")
except Exception as e:
    print(f"Local Broker ({LOCAL_BROKER}) connection failed: {e}")

# 3. Main processing and reconnection loop
last_local_reconnect = time.time()

print("Starting robust message and reconnection loop...")
try:
    while True:
        current_time = time.time()
        
        # --- WI-FI CONNECTION CHECK & RECOVERY ---
        wlan = network.WLAN(network.STA_IF)
        if not wlan.isconnected():
            print("Wi-Fi connection lost. Reconnecting...")
            connect_wifi()
            last_local_reconnect = current_time
            time.sleep_ms(100)
            continue
            
        # --- LOCAL CLIENT HANDLING ---
        if local_client is not None:
            try:
                local_client.check_msg()
            except Exception as e:
                print("Local broker disconnected, error:", e)
                try:
                    local_client.disconnect()
                except:
                    pass
                local_client = None
                last_local_reconnect = current_time
        else:
            # Retry local connection every 15 seconds
            if current_time - last_local_reconnect >= 15:
                print("Attempting to reconnect to Local Pi Broker...")
                try:
                    local_client = MQTTClient(MQTT_CLIENT_ID, LOCAL_BROKER, port=MQTT_PORT, keepalive=60)
                    local_client.set_callback(mqtt_callback)
                    local_client.set_last_will(LOCAL_STATUS_TOPIC, b"offline", retain=True, qos=1)
                    local_client.connect()
                    local_client.subscribe(LOCAL_TOPIC)
                    local_client.publish(LOCAL_STATUS_TOPIC, b"online", retain=True, qos=1)
                    print("Reconnected to Local Broker!")
                except Exception as ex:
                    print("Local Broker reconnection failed:", ex)
                    local_client = None
                last_local_reconnect = current_time
        
        time.sleep_ms(100)
except Exception as e:
    print("Fatal error in loop:", e)
    time.sleep(5)
    machine.reset()
