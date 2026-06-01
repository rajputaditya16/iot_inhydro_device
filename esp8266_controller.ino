#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h> // Make sure to install ArduinoJson library (v6 or v7)
#include <LittleFS.h>
#include <time.h>

// Global Configuration
char ssid[64] = "";
char password[64] = "";
float tz_offset = 5.5;
char mqtt_broker[128] = "broker.hivemq.com";
char mqtt_cmd_topic[128] = "inhydro/device1/command";
char mqtt_status_topic[128] = "inhydro/device1/status";
String unique_clientId;

// Relay Data Structure
struct RelayState {
    String name;
    int pin;
    String mode;
    int manual_state;
    String start_time;
    String end_time;
    int st_h, st_m;
    int end_h, end_m;
    int on_min;
    int off_min;
    int days[7]; // Monday=0, Sunday=6 (Matches Python's weekday index)
    
    // Runtime properties
    unsigned long timer_ref;
    bool is_cycling_on;
};

// Default Relay Configuration
const int num_relays = 3;
RelayState relays[3] = {
    {"light", 4, "auto", 0, "08:00", "20:00", 8, 0, 20, 0, 0, 0, {1,1,1,1,1,1,1}, 0, false},
    {"motor", 12, "auto", 0, "09:00", "12:00", 9, 0, 12, 0, 15, 30, {1,1,1,1,1,1,1}, 0, false},
    {"pump", 5, "manual", 0, "10:00", "15:00", 10, 0, 15, 0, 5, 10, {1,1,1,1,1,1,1}, 0, false}
};

WiFiClient espClient;
PubSubClient mqtt_client(espClient);
unsigned long last_mqtt_check = 0;

void parseTimeStr(String timeStr, int &h, int &m) {
    int colonIdx = timeStr.indexOf(':');
    if (colonIdx > 0) {
        h = timeStr.substring(0, colonIdx).toInt();
        m = timeStr.substring(colonIdx + 1).toInt();
    } else {
        h = 0; m = 0;
    }
}

void applyRelayConfig() {
    for (int i = 0; i < num_relays; i++) {
        pinMode(relays[i].pin, OUTPUT);
        parseTimeStr(relays[i].start_time, relays[i].st_h, relays[i].st_m);
        parseTimeStr(relays[i].end_time, relays[i].end_h, relays[i].end_m);
        
        if (relays[i].mode == "manual") {
            digitalWrite(relays[i].pin, relays[i].manual_state);
        }
    }
}

void saveConfig() {
    File f = LittleFS.open("/config.json", "w");
    if (!f) {
        Serial.println("Failed to open config file for writing");
        return;
    }
    
    DynamicJsonDocument doc(2048);
    doc["ssid"] = ssid;
    doc["password"] = password;
    doc["tz_offset"] = tz_offset;
    doc["mqtt_broker"] = mqtt_broker;
    doc["mqtt_cmd_topic"] = mqtt_cmd_topic;
    doc["mqtt_status_topic"] = mqtt_status_topic;
    
    JsonObject r_obj = doc.createNestedObject("relays");
    for (int i = 0; i < num_relays; i++) {
        JsonObject r = r_obj.createNestedObject(relays[i].name);
        r["pin"] = relays[i].pin;
        r["mode"] = relays[i].mode;
        r["manual_state"] = relays[i].manual_state;
        r["start_time"] = relays[i].start_time;
        r["end_time"] = relays[i].end_time;
        r["on_min"] = relays[i].on_min;
        r["off_min"] = relays[i].off_min;
        JsonArray daysArray = r.createNestedArray("days");
        for (int d = 0; d < 7; d++) {
            daysArray.add(relays[i].days[d]);
        }
    }
    
    serializeJson(doc, f);
    f.close();
    Serial.println("Config saved!");
}

void loadConfig() {
    if (!LittleFS.begin()) {
        Serial.println("Failed to mount file system");
        return;
    }
    
    File f = LittleFS.open("/config.json", "r");
    if (!f) {
        Serial.println("No config.json found. Creating default...");
        saveConfig();
        return;
    }
    
    DynamicJsonDocument doc(2048);
    DeserializationError error = deserializeJson(doc, f);
    f.close();
    
    if (error) {
        Serial.println("Failed to read config, using default");
        return;
    }
    
    strlcpy(ssid, doc["ssid"] | "", sizeof(ssid));
    strlcpy(password, doc["password"] | "", sizeof(password));
    tz_offset = doc["tz_offset"] | 5.5;
    strlcpy(mqtt_broker, doc["mqtt_broker"] | "broker.hivemq.com", sizeof(mqtt_broker));
    strlcpy(mqtt_cmd_topic, doc["mqtt_cmd_topic"] | "inhydro/device1/command", sizeof(mqtt_cmd_topic));
    strlcpy(mqtt_status_topic, doc["mqtt_status_topic"] | "inhydro/device1/status", sizeof(mqtt_status_topic));
    
    JsonObject r_obj = doc["relays"];
    if (!r_obj.isNull()) {
        for (int i = 0; i < num_relays; i++) {
            if (r_obj.containsKey(relays[i].name)) {
                JsonObject r = r_obj[relays[i].name];
                relays[i].pin = r["pin"] | relays[i].pin;
                relays[i].mode = r["mode"] | relays[i].mode;
                relays[i].manual_state = r["manual_state"] | relays[i].manual_state;
                relays[i].start_time = r["start_time"].as<String>();
                relays[i].end_time = r["end_time"].as<String>();
                relays[i].on_min = r["on_min"] | relays[i].on_min;
                relays[i].off_min = r["off_min"] | relays[i].off_min;
                
                JsonArray daysArr = r["days"];
                if (!daysArr.isNull() && daysArr.size() == 7) {
                    for (int d = 0; d < 7; d++) {
                        relays[i].days[d] = daysArr[d].as<int>();
                    }
                }
            }
        }
    }
    
    applyRelayConfig();
}

void sendMqttStatus() {
    if (!mqtt_client.connected()) return;
    
    DynamicJsonDocument doc(1024);
    doc["status"] = "online";
    JsonObject r_obj = doc.createNestedObject("relays");
    
    for (int i = 0; i < num_relays; i++) {
        JsonObject r = r_obj.createNestedObject(relays[i].name);
        r["mode"] = relays[i].mode;
        r["hardware_state"] = digitalRead(relays[i].pin);
        r["manual_state"] = relays[i].manual_state;
    }
    
    String payload;
    serializeJson(doc, payload);
    mqtt_client.publish(mqtt_status_topic, payload.c_str());
    Serial.println("Published System Status to Cloud.");
}

void onCloudMessage(char* topic, byte* payload, unsigned int length) {
    Serial.println("Cloud Command Received!");
    String message;
    for (unsigned int i = 0; i < length; i++) message += (char)payload[i];
    
    DynamicJsonDocument doc(2048);
    DeserializationError error = deserializeJson(doc, message);
    if (error) {
        Serial.println("Error parsing cloud message");
        return;
    }
    
    if (doc.containsKey("relays")) {
        JsonObject r_obj = doc["relays"];
        for (int i = 0; i < num_relays; i++) {
            if (r_obj.containsKey(relays[i].name)) {
                JsonObject r = r_obj[relays[i].name];
                if (r.containsKey("mode")) relays[i].mode = r["mode"].as<String>();
                if (r.containsKey("manual_state")) relays[i].manual_state = r["manual_state"].as<int>();
                if (r.containsKey("start_time")) relays[i].start_time = r["start_time"].as<String>();
                if (r.containsKey("end_time")) relays[i].end_time = r["end_time"].as<String>();
                if (r.containsKey("on_min")) relays[i].on_min = r["on_min"].as<int>();
                if (r.containsKey("off_min")) relays[i].off_min = r["off_min"].as<int>();
                
                if (r.containsKey("days")) {
                    JsonArray daysArr = r["days"];
                    for (int d = 0; d < 7; d++) relays[i].days[d] = daysArr[d].as<int>();
                }
            }
        }
        applyRelayConfig();
        saveConfig();
        sendMqttStatus();
    }
}

void connectWiFi() {
    Serial.println("Starting AP Mode");
    WiFi.softAP("ESP8266_Setup");
    
    if (strlen(ssid) > 0) {
        Serial.print("Connecting to WiFi: ");
        Serial.println(ssid);
        WiFi.begin(ssid, password);
        
        unsigned long startWait = millis();
        while (WiFi.status() != WL_CONNECTED && millis() - startWait < 15000) {
            delay(1000);
            Serial.print(".");
        }
        
        if (WiFi.status() == WL_CONNECTED) {
            Serial.println("\nWiFi Connected! IP: " + WiFi.localIP().toString());
            configTime(tz_offset * 3600, 0, "pool.ntp.org", "time.nist.gov");
        } else {
            Serial.println("\nWiFi Failed to connect within 15s");
        }
    }
}

void reconnectCloud() {
    if (WiFi.status() != WL_CONNECTED) return;
    
    Serial.println("Establishing Global Cloud Connection...");
    mqtt_client.setServer(mqtt_broker, 1883);
    mqtt_client.setCallback(onCloudMessage);
    
    if (mqtt_client.connect(unique_clientId.c_str())) {
        mqtt_client.subscribe(mqtt_cmd_topic);
        Serial.print("Listening globally on topic: ");
        Serial.println(mqtt_cmd_topic);
        sendMqttStatus();
    } else {
        Serial.print("Could not connect to MQTT Cloud, rc=");
        Serial.println(mqtt_client.state());
    }
}

void processRelayLogic() {
    time_t now = time(nullptr);
    struct tm* timeinfo = localtime(&now);
    
    if (timeinfo->tm_year < (2020 - 1900)) return; // Don't run logic if NTP sync hasn't happened
    
    int hour = timeinfo->tm_hour;
    int minute = timeinfo->tm_min;
    
    // Convert 0=Sun, 1=Mon...6=Sat to Python style 0=Mon, 6=Sun
    // tm_wday is days since Sunday (0-6)
    int weekday = timeinfo->tm_wday - 1;
    if (weekday < 0) weekday = 6;
    
    int current_mins = hour * 60 + minute;
    unsigned long current_time_sec = now;

    for (int i = 0; i < num_relays; i++) {
        if (relays[i].mode == "manual") {
            digitalWrite(relays[i].pin, relays[i].manual_state);
            continue;
        }
        
        int start_mins = relays[i].st_h * 60 + relays[i].st_m;
        int end_mins = relays[i].end_h * 60 + relays[i].end_m;
        
        bool is_active_day = (relays[i].days[weekday] == 1);
        bool is_active_window = (current_mins >= start_mins && current_mins < end_mins);
        
        if (is_active_day && is_active_window) {
            if (relays[i].on_min > 0 && relays[i].off_min > 0) {
                unsigned long elapsed = current_time_sec - relays[i].timer_ref;
                unsigned long on_sec = relays[i].on_min * 60;
                unsigned long off_sec = relays[i].off_min * 60;
                
                if (relays[i].is_cycling_on) {
                    if (elapsed >= on_sec) {
                        relays[i].is_cycling_on = false;
                        digitalWrite(relays[i].pin, LOW);
                        relays[i].timer_ref = current_time_sec;
                    }
                } else {
                    if (elapsed >= off_sec) {
                        relays[i].is_cycling_on = true;
                        digitalWrite(relays[i].pin, HIGH);
                        relays[i].timer_ref = current_time_sec;
                    }
                }
                
                // Anti-desync fallback
                if (elapsed > max(on_sec, off_sec) + 10) {
                    relays[i].is_cycling_on = true;
                    digitalWrite(relays[i].pin, HIGH);
                    relays[i].timer_ref = current_time_sec;
                }
            } else {
                digitalWrite(relays[i].pin, HIGH);
                relays[i].is_cycling_on = true;
            }
        } else {
            digitalWrite(relays[i].pin, LOW);
            relays[i].is_cycling_on = false;
            relays[i].timer_ref = current_time_sec;
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\nCore Controller Engine Initializing...");
    
    unique_clientId = "esp_" + String(ESP.getChipId(), HEX);
    
    loadConfig();
    connectWiFi();
    reconnectCloud();
}

void loop() {
    if (WiFi.status() == WL_CONNECTED) {
        if (!mqtt_client.connected()) {
            if (millis() - last_mqtt_check > 10000) {
                reconnectCloud();
                last_mqtt_check = millis();
            }
        } else {
            mqtt_client.loop();
        }
    }
    
    processRelayLogic();
    delay(100);
}
