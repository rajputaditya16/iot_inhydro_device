import network
import socket
import time
import machine
import json
import ntptime
import gc

try:
    from umqtt.simple import MQTTClient
except ImportError:
    MQTTClient = None

CONFIG_FILE = 'config.json'

DEFAULT_CONFIG = {
    'ssid': '',
    'password': '',
    'device_id': '',
    'tz_offset': 5.5,
    'mqtt_broker': 'mqtt3.thingspeak.com',
    'mqtt_client_id': '',
    'mqtt_user': '',
    'mqtt_pass': '',
    'ts_channel_id': '',
    'ts_write_key': '',
    'ts_read_key': '',
    'mqtt_cmd_topic': '',
    'mqtt_status_topic': '',
    'relays': {
        'light': {
            'pin': 4, 'mode': 'auto', 'manual_state': 0,
            'start_time': '08:00', 'end_time': '20:00',
            'on_min': 0, 'off_min': 0, 'days': [1,1,1,1,1,1,1]
        },
        'motor': {
            'pin': 12, 'mode': 'auto', 'manual_state': 0,
            'start_time': '00:00', 'end_time': '23:59',
            'on_min': 15, 'off_min': 30, 'days': [1,1,1,1,1,1,1]
        },
        'pump': {
            'pin': 5, 'mode': 'manual', 'manual_state': 0,
            'start_time': '10:00', 'end_time': '15:00',
            'on_min': 5, 'off_min': 10, 'days': [1,1,1,1,1,1,1]
        }
    }
}

class RelayManager:
    def __init__(self, key_name, cfg):
        self.name = key_name
        self.pin_num = cfg.get('pin', 4)
        self.pin = machine.Pin(self.pin_num, machine.Pin.OUT, value=0)
        self.timer_ref = time.time()
        self.is_cycling_on = False
        self.update_config(cfg)

    def update_config(self, cfg):
        self.mode = cfg.get('mode', 'auto')
        self.manual_state = int(cfg.get('manual_state', 0))
        self.start_time = cfg.get('start_time', '00:00')
        self.end_time = cfg.get('end_time', '23:59')
        self.on_min = int(cfg.get('on_min', 0))
        self.off_min = int(cfg.get('off_min', 0))
        self.days = cfg.get('days', [1,1,1,1,1,1,1])
        if self.mode == 'manual':
            self.pin.value(self.manual_state)

    def get_status(self):
        return {
            "mode": self.mode,
            "hardware_state": self.pin.value(),
            "manual_state": self.manual_state
        }

    def process_logic(self, current_time_sec, weekday, current_mins):
        if self.mode == 'manual':
            self.pin.value(self.manual_state)
            return

        try:
            parts_s = self.start_time.split(':')
            parts_e = self.end_time.split(':')
            st_h = int(parts_s[0]); st_m = int(parts_s[1])
            end_h = int(parts_e[0]); end_m = int(parts_e[1])
        except:
            st_h, st_m, end_h, end_m = 0, 0, 23, 59

        start_mins = st_h * 60 + st_m
        end_mins   = end_h * 60 + end_m
        is_active_day    = (self.days[weekday] == 1) if (isinstance(self.days, list) and 0 <= weekday < len(self.days)) else True
        is_active_window = (start_mins <= current_mins < end_mins)

        if is_active_day and is_active_window:
            if self.on_min > 0 and self.off_min > 0:
                elapsed = current_time_sec - self.timer_ref
                on_sec  = self.on_min * 60
                off_sec = self.off_min * 60
                if self.is_cycling_on:
                    if elapsed >= on_sec:
                        self.is_cycling_on = False
                        self.pin.value(0)
                        self.timer_ref = current_time_sec
                else:
                    if elapsed >= off_sec:
                        self.is_cycling_on = True
                        self.pin.value(1)
                        self.timer_ref = current_time_sec
                if elapsed > max(on_sec, off_sec) + 10:
                    self.is_cycling_on = True
                    self.pin.value(1)
                    self.timer_ref = current_time_sec
            else:
                self.pin.value(1)
                self.is_cycling_on = True
        else:
            self.pin.value(0)
            self.is_cycling_on = False
            self.timer_ref = current_time_sec


def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            c = json.load(f)
            for k in DEFAULT_CONFIG['relays']:
                if 'relays' not in c:
                    c['relays'] = {}
                if k not in c['relays']:
                    c['relays'][k] = DEFAULT_CONFIG['relays'][k]
            return c
    except:
        return DEFAULT_CONFIG

def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f)
        print("[CONFIG] Saved to flash.")
    except Exception as e:
        print("[CONFIG] Save error:", e)

config        = load_config()
managed_relays = {}
for r_name in config['relays']:
    managed_relays[r_name] = RelayManager(r_name, config['relays'][r_name])

ap  = network.WLAN(network.AP_IF)
sta = network.WLAN(network.STA_IF)

last_ntp_sync = 0
ts_client     = None   
hive_client   = None   
UNIQUE_ID     = ''     

_wifi_reconnect_needed = False
_ts_reconnect_needed   = False

def on_web_config(topic, msg):
    """
    Unified HiveMQ callback for both subscribed topics:
      - inhydro/{id}/config/request  → web asking for current config (msg = '1')
      - inhydro/{id}/config/update   → web pushing a new config (msg = JSON)
    """
    global config, _wifi_reconnect_needed, _ts_reconnect_needed

    topic_str = topic.decode('utf-8') if isinstance(topic, bytes) else topic

    if topic_str.endswith('/config/request'):
        print("[WEB] Config sync requested by dashboard")
        _publish_current_config()
        return

    try:
        payload = json.loads(msg.decode('utf-8'))
        if not isinstance(payload, dict):
            print("[WEB] Ignored non-dict payload")
            return

        print("\n[WEB] Config update received from dashboard")

        wifi_changed = False
        ts_changed   = False

        top_keys = [
            'ssid', 'password', 'device_id', 'tz_offset',
            'mqtt_broker', 'mqtt_client_id', 'mqtt_user', 'mqtt_pass',
            'ts_channel_id', 'ts_write_key', 'ts_read_key',
            'mqtt_cmd_topic', 'mqtt_status_topic'
        ]
        for k in top_keys:
            if k in payload:
                if k in ('ssid', 'password') and payload[k] != config.get(k, ''):
                    wifi_changed = True
                if k in ('mqtt_broker', 'mqtt_client_id', 'mqtt_user', 'mqtt_pass',
                         'ts_channel_id', 'mqtt_cmd_topic') and payload[k] != config.get(k, ''):
                    ts_changed = True
                config[k] = payload[k]
                print("  [CFG] {} = {}".format(
                    k, '***' if k in ('password', 'mqtt_pass') else payload[k]
                ))

        if 'relays' in payload:
            for r_name in payload['relays']:
                if r_name in managed_relays:
                    config['relays'][r_name].update(payload['relays'][r_name])
                    managed_relays[r_name].update_config(config['relays'][r_name])
                    print("  [RELAY] Updated:", r_name)

        save_config(config)

        if wifi_changed:
            print("[WEB] WiFi credentials changed — will reconnect STA")
            _wifi_reconnect_needed = True
        if ts_changed:
            print("[WEB] ThingSpeak config changed — will reconnect TS")
            _ts_reconnect_needed = True

        _publish_current_config()

    except Exception as e:
        print("[WEB] Config parse error:", e)


def _publish_current_config():
    """Publish current config to config/current so the web can read device state."""
    global hive_client
    try:
        if hive_client:
            topic = "inhydro/{}/config/current".format(UNIQUE_ID)
            hive_client.publish(topic.encode(), json.dumps(config).encode())
            print("[WEB] Current config published back to dashboard")
    except Exception as e:
        print("[WEB] Publish error:", e)
        hive_client = None


def connect_hivemq():
    """Connect to HiveMQ public broker to receive web dashboard commands."""
    global hive_client, UNIQUE_ID
    if MQTTClient is None or not sta.isconnected():
        return False
    try:
        import ubinascii
        c_id = "hive_" + ubinascii.hexlify(machine.unique_id()).decode()
        hive_client = MQTTClient(
            c_id,
            'broker.hivemq.com',
            port=1883,
            keepalive=60
        )
        hive_client.set_callback(on_web_config)
        hive_client.connect()

        sub_topic = "inhydro/{}/config/update".format(UNIQUE_ID)
        hive_client.subscribe(sub_topic.encode())
        print("[HIVE] Connected. Listening on:", sub_topic)

        sync_topic = "inhydro/{}/config/request".format(UNIQUE_ID)
        hive_client.subscribe(sync_topic.encode())

        _publish_current_config()
        return True
    except Exception as e:
        print("[HIVE] Connect error:", e)
        hive_client = None
        return False

def on_ts_message(topic, msg):
    """Handle commands from ThingSpeak (relay-only, legacy support)."""
    try:
        payload = json.loads(msg.decode('utf-8'))
        if 'relays' in payload:
            for r_name in payload['relays']:
                if r_name in managed_relays:
                    config['relays'][r_name].update(payload['relays'][r_name])
                    managed_relays[r_name].update_config(config['relays'][r_name])
            save_config(config)
    except Exception as e:
        print("[TS] Message error:", e)


def connect_thingspeak():
    global ts_client
    if MQTTClient is None or not sta.isconnected():
        return False
    try:
        c_id = config.get('mqtt_client_id')
        if not c_id:
            import ubinascii
            c_id = "esp_" + ubinascii.hexlify(machine.unique_id()).decode()

        user = config.get('mqtt_user') or None
        pw   = config.get('mqtt_pass') or None

        ts_client = MQTTClient(c_id, config['mqtt_broker'], user=user, password=pw, keepalive=60)
        ts_client.set_callback(on_ts_message)
        ts_client.connect()

        cmd_topic = config.get('mqtt_cmd_topic')
        if not cmd_topic and config.get('ts_channel_id'):
            cmd_topic = "channels/{}/subscribe".format(config['ts_channel_id'])
        if cmd_topic:
            ts_client.subscribe(cmd_topic.encode())
            print("[TS] Connected. Subscribed to:", cmd_topic)
        return True
    except Exception as e:
        print("[TS] Connect error:", e)
        ts_client = None
        return False

def connect_wifi():
    ssid = config.get('ssid', '')
    pw   = config.get('password', '')
    if not ssid:
        print("[WIFI] No SSID configured — staying in AP-only mode")
        return False

    sta.active(True)
    sta.connect(ssid, pw)
    print("[WIFI] Connecting to:", ssid)

    # Wait up to 15 s
    for _ in range(150):
        if sta.isconnected():
            print("[WIFI] Connected. IP:", sta.ifconfig()[0])
            return True
        time.sleep(0.1)

    print("[WIFI] Connection failed — will retry later")
    return False

def run():
    global last_ntp_sync, ts_client, hive_client, UNIQUE_ID
    global _wifi_reconnect_needed, _ts_reconnect_needed

    import ubinascii
    UNIQUE_ID = config.get('device_id') or ubinascii.hexlify(machine.unique_id()).decode().upper()

    ap.active(True)
    ap.config(essid='ESP8266_{}'.format(UNIQUE_ID[-6:]))
    print("\n" + "="*32)
    print("DEVICE ID :", UNIQUE_ID)
    print("AP SSID   : ESP8266_{}".format(UNIQUE_ID[-6:]))
    print("="*32)

    # Initial WiFi connect
    connect_wifi()

    last_mqtt_check  = 0   # ThingSpeak reconnect timer
    last_hive_check  = 0   # HiveMQ reconnect timer
    last_status_tick = 0
    last_wifi_retry  = 0

    print("System Starting...\n")

    while True:
        try:
            cur = time.time()
            lt  = cur + int(config.get('tz_offset', 5.5) * 3600)
            tm  = time.localtime(lt)
            hour, minute, weekday = tm[3], tm[4], tm[6]

            if _wifi_reconnect_needed:
                _wifi_reconnect_needed = False
                ts_client  = None   # drop TS — will reconnect after WiFi
                hive_client = None
                sta.disconnect()
                time.sleep(1)
                connect_wifi()

            if _ts_reconnect_needed:
                _ts_reconnect_needed = False
                ts_client = None

            
            if cur - last_status_tick >= 5:
                last_status_tick = cur
                wifi_ok  = sta.isconnected()
                hive_ok  = bool(hive_client)
                ts_ok    = bool(ts_client)

                print("\n--- DASHBOARD [{:02d}:{:02d}] ---".format(hour, minute))
                print("WiFi   : {}  IP: {}".format(
                    "OK" if wifi_ok else "OFFLINE",
                    sta.ifconfig()[0] if wifi_ok else "---"
                ))
                print("HiveMQ : {}".format("OK" if hive_ok else "OFFLINE"))
                print("TS MQTT: {}".format("OK" if ts_ok  else "OFFLINE"))

                relay_states = {}
                for name in managed_relays:
                    r = managed_relays[name]
                    st_val  = r.pin.value()
                    st      = "ON " if st_val else "OFF"
                    rem_sec = 0
                    if r.mode == "auto":
                        if r.on_min > 0 and st_val:
                            rem_sec = int((r.on_min*60) - (cur - r.timer_ref))
                        elif r.off_min > 0 and not st_val:
                            rem_sec = int((r.off_min*60) - (cur - r.timer_ref))
                    print("  {}: {} {}".format(name.upper(), st, "(rem:{}s)".format(rem_sec) if rem_sec else ''))
                    relay_states[name] = {"state": st_val, "rem_sec": rem_sec, "mode": r.mode}

                # Publish telemetry to ThingSpeak if connected
                if ts_ok and wifi_ok:
                    try:
                        stat_topic = config.get('mqtt_status_topic')
                        if not stat_topic and config.get('ts_channel_id'):
                            stat_topic = "channels/{}/publish".format(config['ts_channel_id'])
                        if stat_topic:
                            status_payload = {
                                "device_id": UNIQUE_ID,
                                "wifi": "connected",
                                "cloud": "connected",
                                "ip_address": sta.ifconfig()[0],
                                "time": "{:02d}:{:02d}".format(hour, minute),
                                "relays": relay_states
                            }
                            ts_client.publish(stat_topic.encode(), json.dumps(status_payload).encode())
                    except Exception as e:
                        print("[TS] Publish error:", e)
                        ts_client = None

            if sta.isconnected():
                if hive_client:
                    try:
                        hive_client.check_msg()
                    except Exception as e:
                        print("[HIVE] check_msg error:", e)
                        hive_client = None
                elif cur - last_hive_check > 30:
                    last_hive_check = cur
                    connect_hivemq()

                if ts_client:
                    try:
                        ts_client.check_msg()
                    except Exception as e:
                        print("[TS] check_msg error:", e)
                        ts_client = None
                elif cur - last_mqtt_check > 30:
                    last_mqtt_check = cur
                    connect_thingspeak()

                # NTP sync every hour
                if cur - last_ntp_sync > 3600:
                    try:
                        ntptime.settime()
                        last_ntp_sync = cur
                        print("[NTP] Time synced")
                    except:
                        pass
            else:
                if cur - last_wifi_retry > 60:
                    last_wifi_retry = cur
                    connect_wifi()

            for name in managed_relays:
                managed_relays[name].process_logic(cur, weekday, hour * 60 + minute)

            time.sleep(0.1)
            gc.collect()

        except Exception as e:
            print("[MAIN] Loop error:", e)
            time.sleep(1)
            gc.collect()


run()
