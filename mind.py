import time
import json
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import paho.mqtt.client as mqtt

# --- CONFIGURATION FILE ---
CONFIG_FILE = "schedule_config.json"

# --- DEFAULT CONFIGURATION FOR 8 LIGHTS ---
DEFAULT_CONFIG = {
    "password": "1234",
    "lights": [
        {
            "id": i,
            "name": f"Light Channel {i}",
            "time_frames": [
                {"name": "Morning", "start": "06:00", "end": "11:55", "intensity": 80},
                {"name": "Noon", "start": "12:00", "end": "17:55", "intensity": 100},
                {"name": "Evening", "start": "18:00", "end": "21:55", "intensity": 50},
                {"name": "Night", "start": "22:00", "end": "05:55", "intensity": 10}
            ]
        } for i in range(1, 9)
    ]
}

# --- LOAD AND SAVE SETTINGS ---
def load_config():
    if not os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(DEFAULT_CONFIG, f, indent=4)
            return DEFAULT_CONFIG
        except Exception as e:
            print(f"Error creating default config: {e}")
            return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}. Using defaults.")
        return DEFAULT_CONFIG

def save_config(config_data):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

# Load settings at start
config = load_config()
active_config = config

# --- MQTT SETUP ---
LOCAL_BROKER = "localhost"
CLOUD_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883

esp_connected_states = {i: False for i in range(1, 9)}

def on_mqtt_message(client, userdata, msg):
    global esp_connected_states
    topic = msg.topic
    try:
        payload = msg.payload.decode('utf-8')
        parts = topic.split('/')
        if len(parts) >= 3 and parts[-2] == "status":
            idx = int(parts[-1])
            if 1 <= idx <= 8:
                esp_connected_states[idx] = (payload == "online")
                print(f"[ESP Connection] Light ESP {idx} is now {payload}")
    except Exception as e:
        print(f"Error parsing ESP status: {e}")

local_client = mqtt.Client()
local_client.on_message = on_mqtt_message

cloud_client = mqtt.Client()
cloud_client.on_message = on_mqtt_message

local_connected = False
cloud_connected = False

# Connect to Local Broker
print(f"Connecting to Local MQTT Broker at {LOCAL_BROKER}...")
try:
    local_client.connect(LOCAL_BROKER, MQTT_PORT, 60)
    local_client.subscribe("lights/status/#")
    local_client.loop_start()
    local_connected = True
    print("Successfully connected to Local Broker.")
except Exception as e:
    print(f"Could not connect to Local Broker: {e}")

# Connect to Cloud Broker (HiveMQ)
print(f"Connecting to Cloud MQTT Broker at {CLOUD_BROKER}...")
try:
    cloud_client.connect(CLOUD_BROKER, MQTT_PORT, 60)
    cloud_client.subscribe("mydevice_931d/lights/status/#")
    cloud_client.loop_start()
    cloud_connected = True
    print("Successfully connected to HiveMQ Cloud Broker.")
except Exception as e:
    print(f"Could not connect to Cloud Broker (No Internet?): {e}")

# Track current active state for each light
current_states = {
    i: {"frame_name": "None", "intensity": -1} for i in range(1, 9)
}

# --- SCHEDULING LOGIC ---
def is_time_in_frame(current_mins, start_str, end_str):
    try:
        sh, sm = map(int, start_str.split(':'))
        eh, em = map(int, end_str.split(':'))
        start_mins = sh * 60 + sm
        end_mins = eh * 60 + em
    except Exception:
        return False

    if start_mins < end_mins:
        return start_mins <= current_mins < end_mins
    elif start_mins > end_mins:
        return current_mins >= start_mins or current_mins < end_mins
    else:
        return current_mins == start_mins

def check_timeframes_conflict(time_frames):
    minute_map = [0] * 1440
    for idx, tf in enumerate(time_frames):
        try:
            sh, sm = map(int, tf["start"].split(':'))
            eh, em = map(int, tf["end"].split(':'))
            start_mins = sh * 60 + sm
            end_mins = eh * 60 + em
        except Exception:
            return True, f"Time Frame {idx+1} ({tf['name']}) has an invalid time format."

        if start_mins == end_mins:
            return True, f"Time Frame {idx+1} ({tf['name']}) start and end times cannot be equal."

        # To enforce at least a 5-minute delay between timeframes, we add a 5-minute buffer after end_mins
        if start_mins < end_mins:
            for m in range(start_mins, end_mins + 5):
                minute_map[m % 1440] += 1
        else:
            for m in range(start_mins, 1440):
                minute_map[m] += 1
            for m in range(0, end_mins + 5):
                minute_map[m % 1440] += 1

    for m in range(1440):
        if minute_map[m] > 1:
            h = m // 60
            mi = m % 60
            return True, f"Overlap or less than 5-minute delay detected around {h:02d}:{mi:02d}."

    return False, ""

def evaluate_scheduler():
    global config, active_config, current_states
    
    tm = time.localtime(time.time())
    hour, minute = tm.tm_hour, tm.tm_min
    current_mins = hour * 60 + minute

    for light in active_config["lights"]:
        l_id = light["id"]
        local_topic = f"lights/intensity/{l_id}"
        cloud_topic = f"mydevice_931d/lights/intensity/{l_id}"

        active_frame = "None"
        target_intensity = 0

        for frame in light["time_frames"]:
            if is_time_in_frame(current_mins, frame["start"], frame["end"]):
                active_frame = frame["name"]
                target_intensity = frame["intensity"]
                break

        old_frame = current_states[l_id]["frame_name"]
        old_intensity = current_states[l_id]["intensity"]

        if active_frame != old_frame or target_intensity != old_intensity:
            current_states[l_id]["frame_name"] = active_frame
            current_states[l_id]["intensity"] = target_intensity

            # Publish to local broker
            if local_connected:
                try:
                    local_client.publish(local_topic, str(target_intensity), qos=1, retain=True)
                except Exception as e:
                    print(f"Local publish error: {e}")
            
            # Publish to cloud broker in parallel
            if cloud_connected:
                try:
                    cloud_client.publish(cloud_topic, str(target_intensity), qos=1, retain=True)
                except Exception as e:
                    print(f"Cloud publish error: {e}")

            print(f"[Sync] Light {l_id} -> Frame: {active_frame} | Intensity: {target_intensity}%")

# --- UI COLORS AND THEME (Elite Light Theme) ---
BG_COLOR = "#f8fafc"         # Off-white background (from Adv_control.py)
CARD_BG = "#FFFFFF"          # Pure white cards
BORDER_COLOR = "#E2E8F0"     # Light slate border lines
TEXT_COLOR = "#1E293B"       # Deep charcoal/navy for prominent text
MUTED_TEXT = "#64748b"       # Muted gray for subtitles (from Adv_control.py)
ACCENT_BLUE = "#3B82F6"      # Sapphire blue for sliders & highlighted labels
ACCENT_GREEN = "#10B981"     # Soft active green for status lights
RED_ACCENT = "#EF4444"       # Clean crimson red for Exit
BTN_PRIMARY = "#0284c7"      # Sky/Sapphire blue for primary actions (from Adv_control.py)
BTN_SECONDARY = "#cbd5e1"    # slate grey (from Adv_control.py)
BTN_HOVER = "#cbd5e1"        # Hover grey
BTN_HOVER_PRIMARY = "#0369a1"

# --- CONTEXT-SENSITIVE POPUP KEYPAD (Reference: Adv_control.py) ---
# --- LOGO RENDERER HELPER ---
logo_images = []

def draw_logo(parent):
    """Displays the logo image cleanly scaled to 130x85, falling back to custom vector graphics."""
    logo_width = 130
    logo_height = 85
    logo_path = "logo.png"
    if os.path.exists(logo_path):
        try:
            from PIL import Image, ImageTk
            img = Image.open(logo_path)
            img = img.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
            logo_img = ImageTk.PhotoImage(img)
            logo_images.append(logo_img)
            lbl_logo = tk.Label(parent, image=logo_img, bg=BG_COLOR)
            lbl_logo.pack(side="right", padx=10)
            return
        except Exception:
            try:
                logo_img = tk.PhotoImage(file=logo_path)
                logo_images.append(logo_img)
                lbl_logo = tk.Label(parent, image=logo_img, bg=BG_COLOR)
                lbl_logo.pack(side="right", padx=10)
                return
            except Exception as e:
                print(f"Error loading logo: {e}")
    
    # Vector droplet canvas fallback
    logo_canvas = tk.Canvas(parent, width=logo_width, height=logo_height, bg=BG_COLOR, highlightthickness=0)
    logo_canvas.pack(side="right", padx=10)
    
    cx, cy = 65, 42.5
    logo_canvas.create_oval(cx - 32, cy - 32, cx + 32, cy + 32, fill=CARD_BG, outline=ACCENT_BLUE, width=1.5)
    points = [cx, cy - 22, cx + 16, cy + 8, cx - 16, cy + 8]
    logo_canvas.create_polygon(points, fill=ACCENT_BLUE, outline=ACCENT_BLUE, smooth=True)
    logo_canvas.create_oval(cx - 16, cy - 4, cx + 16, cy + 18, fill=ACCENT_BLUE, outline=ACCENT_BLUE)
    dia_points = [cx, cy - 6, cx + 6, cy + 2, cx, cy + 10, cx - 6, cy + 2]
    logo_canvas.create_polygon(dia_points, fill="#F59E0B", outline="#F59E0B")
    logo_canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=CARD_BG)


# --- CONTEXT-SENSITIVE POPUP KEYPAD (Reference: Adv_control.py) ---
class KeypadDialog(tk.Toplevel):
    def __init__(self, parent, title_text, initial_value, callback, is_numeric=False, show_masked=False):
        super().__init__(parent)
        self.callback = callback
        self.is_numeric = is_numeric
        self.show_masked = show_masked
        
        self.title(title_text)
        self.configure(bg=BG_COLOR)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        if is_numeric:
            self.geometry("480x520")
        else:
            self.geometry("720x460")
            
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (240 if is_numeric else 360)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (260 if is_numeric else 230)
        self.geometry(f"+{x}+{y}")
        
        self.entered_value = str(initial_value)
        self.display_var = tk.StringVar(value=self.entered_value)
        
        # Header frame with title and logo
        header_frame = tk.Frame(self, bg=BG_COLOR)
        header_frame.pack(fill="x", padx=15, pady=(10, 5))
        
        lbl_info = tk.Label(header_frame, text=title_text, fg=TEXT_COLOR, bg=BG_COLOR, font=("Helvetica", 14, "bold"))
        lbl_info.pack(side="left", anchor="center")
        
        draw_logo(header_frame)
        
        # Value Preview Card
        disp_frame = tk.Frame(self, bg=CARD_BG, bd=1, highlightbackground=BORDER_COLOR, highlightthickness=1)
        disp_frame.pack(fill="x", padx=15, pady=(5, 10))
        
        self.lbl_display = tk.Label(
            disp_frame,
            textvariable=self.display_var,
            bg=CARD_BG,
            fg=TEXT_COLOR,
            font=("Helvetica", 18, "bold"),
            anchor="center",
            height=1
        )
        if show_masked:
            self.display_var_obs = tk.StringVar(value="●" * len(self.entered_value))
            self.lbl_display.config(textvariable=self.display_var_obs)
            
        self.lbl_display.pack(fill="x", padx=10, pady=8)
        
        # Grid layout frame
        keys_frame = tk.Frame(self, bg=BG_COLOR)
        keys_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        if is_numeric:
            self.build_numeric_layout(keys_frame)
        else:
            self.build_qwerty_layout(keys_frame)

    def build_numeric_layout(self, parent):
        keys = [
            ('1', 0, 0), ('2', 0, 1), ('3', 0, 2), (':', 0, 3),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2), ('%', 1, 3),
            ('7', 2, 0), ('8', 2, 1), ('9', 2, 2), ('.', 2, 3),
            ('0', 3, 0)
        ]
        for val, r, c in keys:
            btn = tk.Button(
                parent,
                text=val,
                font=("Arial", 14, "bold"),
                bg=CARD_BG,
                fg=TEXT_COLOR,
                activebackground=BTN_HOVER,
                relief="flat",
                bd=1,
                command=lambda v=val: self.press_key(v)
            )
            btn.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
            
        btn_back = tk.Button(parent, text="⌫", font=("Arial", 12, "bold"), bg="#f97316", fg="white", activebackground="#ea580c", relief="flat", bd=1, command=self.press_back)
        btn_back.grid(row=3, column=1, padx=3, pady=3, sticky="nsew")
        
        btn_clear = tk.Button(parent, text="CLR", font=("Arial", 11, "bold"), bg="#dc2626", fg="white", activebackground="#b91c1c", relief="flat", bd=1, command=self.press_clear)
        btn_clear.grid(row=3, column=2, padx=3, pady=3, sticky="nsew")
        
        btn_cancel = tk.Button(parent, text="CAN", font=("Arial", 11, "bold"), bg="#64748b", fg="white", activebackground="#475569", relief="flat", bd=1, command=self.destroy)
        btn_cancel.grid(row=3, column=3, padx=3, pady=3, sticky="nsew")
        
        btn_ok = tk.Button(parent, text="OK", font=("Arial", 14, "bold"), bg="#10b981", fg="white", activebackground="#059669", relief="flat", bd=1, command=self.press_ok)
        btn_ok.grid(row=4, column=0, columnspan=4, padx=3, pady=3, sticky="nsew")
        
        for col in range(4):
            parent.columnconfigure(col, weight=1)
        for row in range(5):
            parent.rowconfigure(row, weight=1)

    def build_qwerty_layout(self, parent):
        row0_keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']
        for col, key in enumerate(row0_keys):
            btn = tk.Button(parent, text=key, font=("Arial", 12, "bold"), bg=CARD_BG, fg=TEXT_COLOR, activebackground=BTN_HOVER, relief="flat", bd=1, command=lambda k=key: self.press_key(k))
            btn.grid(row=0, column=col, padx=2, pady=2, sticky="nsew")
            
        row1_keys = ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P']
        for col, key in enumerate(row1_keys):
            btn = tk.Button(parent, text=key, font=("Arial", 12, "bold"), bg=CARD_BG, fg=TEXT_COLOR, activebackground=BTN_HOVER, relief="flat", bd=1, command=lambda k=key: self.press_key(k))
            btn.grid(row=1, column=col, padx=2, pady=2, sticky="nsew")

        row2_keys = ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', ':']
        for col, key in enumerate(row2_keys):
            btn = tk.Button(parent, text=key, font=("Arial", 12, "bold"), bg=CARD_BG, fg=TEXT_COLOR, activebackground=BTN_HOVER, relief="flat", bd=1, command=lambda k=key: self.press_key(k))
            btn.grid(row=2, column=col, padx=2, pady=2, sticky="nsew")

        row3_keys = ['Z', 'X', 'C', 'V', 'B', 'N', 'M']
        for col, key in enumerate(row3_keys):
            btn = tk.Button(parent, text=key, font=("Arial", 12, "bold"), bg=CARD_BG, fg=TEXT_COLOR, activebackground=BTN_HOVER, relief="flat", bd=1, command=lambda k=key: self.press_key(k))
            btn.grid(row=3, column=col, padx=2, pady=2, sticky="nsew")
            
        btn_space = tk.Button(parent, text="SPC", font=("Arial", 12, "bold"), bg=CARD_BG, fg=TEXT_COLOR, activebackground=BTN_HOVER, relief="flat", bd=1, command=lambda: self.press_key(" "))
        btn_space.grid(row=3, column=7, columnspan=3, padx=2, pady=2, sticky="nsew")

        btn_back = tk.Button(parent, text="⌫ DEL", font=("Arial", 11, "bold"), bg="#f97316", fg="white", activebackground="#ea580c", relief="flat", bd=1, command=self.press_back)
        btn_back.grid(row=4, column=0, columnspan=3, padx=2, pady=2, sticky="nsew")

        btn_clear = tk.Button(parent, text="CLR", font=("Arial", 11, "bold"), bg="#dc2626", fg="white", activebackground="#b91c1c", relief="flat", bd=1, command=self.press_clear)
        btn_clear.grid(row=4, column=3, columnspan=3, padx=2, pady=2, sticky="nsew")

        btn_done = tk.Button(parent, text="OK ✓", font=("Arial", 11, "bold"), bg="#10b981", fg="white", activebackground="#059669", relief="flat", bd=1, command=self.press_ok)
        btn_done.grid(row=4, column=6, columnspan=4, padx=2, pady=2, sticky="nsew")

        for c in range(10):
            parent.columnconfigure(c, weight=1)
        for r in range(5):
            parent.rowconfigure(r, weight=1)

    def press_key(self, char):
        self.entered_value += char
        self.display_var.set(self.entered_value)
        if self.show_masked:
            self.display_var_obs.set("●" * len(self.entered_value))
            
    def press_back(self):
        self.entered_value = self.entered_value[:-1]
        self.display_var.set(self.entered_value)
        if self.show_masked:
            self.display_var_obs.set("●" * len(self.entered_value))
            
    def press_clear(self):
        self.entered_value = ""
        self.display_var.set("")
        if self.show_masked:
            self.display_var_obs.set("")
            
    def press_ok(self):
        self.callback(self.entered_value)
        self.destroy()


# --- HELPER FUNCTION FOR CREATING EDIT CELLS (Reference: Adv_control.py) ---
def create_edit_cell(parent, label_text, val_text, on_edit_click):
    """Creates a clean card cell displaying a configuration key, its value, and an EDIT button."""
    cell = tk.Frame(parent, bg=CARD_BG)
    
    lbl = tk.Label(cell, text=label_text, fg=MUTED_TEXT, bg=CARD_BG, font=("Helvetica", 12, "bold"), width=14, anchor="w")
    lbl.pack(side="left", padx=(0, 4))
    
    btn = tk.Button(
        cell,
        text="EDIT",
        font=("Helvetica", 11, "bold"),
        bg=BTN_SECONDARY,
        fg=TEXT_COLOR,
        activebackground=BTN_HOVER,
        relief="flat",
        bd=0,
        padx=12,
        pady=4,
        command=on_edit_click
    )
    btn.pack(side="right", padx=(6, 0))

    val_len = len(str(val_text)) + 2
    val_lbl = tk.Label(cell, text=str(val_text), fg=TEXT_COLOR, bg=CARD_BG, font=("Helvetica", 13, "bold"), width=val_len, anchor="center")
    val_lbl.pack(side="right", padx=2)
    
    return cell, val_lbl


# --- MAIN GUI APP ---
class MainControllerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("InHydro Central Light Mind")
        self.root.configure(bg=BG_COLOR)
        self.root.update()
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", lambda e: self.exit_app())
        
        self.root.columnconfigure(0, weight=1)
        
        self.clock_labels = []

        self.setup_ui()
        self.update_clock_and_schedule()

    def setup_ui(self):
        # Header Panel (More compact vertical padding)
        header_frame = tk.Frame(self.root, bg=BG_COLOR)
        header_frame.pack(fill="x", padx=30, pady=(10, 5))

        # Text labels sub-frame (Left Side)
        text_frame = tk.Frame(header_frame, bg=BG_COLOR)
        text_frame.pack(side="left", fill="y")

        lbl_title = tk.Label(
            text_frame,
            text="INHYDRO LIGHT MONITOR",
            fg="#0f172a",
            bg=BG_COLOR,
            font=("Helvetica", 22, "bold")
        )
        lbl_title.pack(anchor="w", pady=(0, 1))

        lbl_subtitle = tk.Label(
            text_frame,
            text="Central Light Mind & Automated Timer Controller",
            fg="#64748b",
            bg=BG_COLOR,
            font=("Helvetica", 10, "italic")
        )
        lbl_subtitle.pack(anchor="w", pady=(0, 2))

        # Logo placement (Right Side)
        draw_logo(header_frame)

        # Lights List Container (Now a beautiful 4x2 grid container)
        self.list_frame = tk.Frame(self.root, bg=BG_COLOR)
        self.list_frame.pack(fill="both", expand=True, padx=30, pady=5)
        
        self.row_widgets = {}
        self.build_light_rows()

        # Action Buttons Panel at the bottom (Dual column: statuses on left, buttons on right)
        btn_frame = tk.Frame(self.root, bg=BG_COLOR)
        btn_frame.pack(fill="x", side="bottom", padx=30, pady=(10, 15))

        # Left Side: Clock Container (Time, Date, Day stacked)
        clock_container = tk.Frame(btn_frame, bg=BG_COLOR)
        clock_container.pack(side="left", anchor="s")

        self.lbl_clock = tk.Label(
            clock_container,
            text="",
            fg="#0f172a",
            bg=BG_COLOR,
            font=("Helvetica", 10, "bold"),
            justify="left",
            anchor="w"
        )
        self.lbl_clock.pack(anchor="w")
        self.clock_labels.append(self.lbl_clock)

        # Status Row (Connections) - placed next to the clock
        status_col = tk.Frame(btn_frame, bg=BG_COLOR)
        status_col.pack(side="left", anchor="s", padx=20, pady=2)

        local_status_str = "Local: Connected" if local_connected else "Local: Offline"
        local_status_color = ACCENT_GREEN if local_connected else RED_ACCENT
        self.lbl_local_status = tk.Label(
            status_col,
            text=local_status_str,
            fg=local_status_color,
            bg=BG_COLOR,
            font=("Helvetica", 10, "bold")
        )
        self.lbl_local_status.pack(side="left", padx=(0, 15))



        # Right Side: Action Buttons (reduced length/width)
        buttons_col = tk.Frame(btn_frame, bg=BG_COLOR)
        buttons_col.pack(side="right", anchor="e")

        self.btn_setpoints = tk.Button(
            buttons_col,
            text="🔒 Setpoints",
            fg="white",
            bg=BTN_PRIMARY,
            activebackground=BTN_HOVER_PRIMARY,
            activeforeground="white",
            font=("Helvetica", 11, "bold"),
            relief="flat",
            bd=0,
            width=12,
            pady=8,
            command=self.open_password_dialog
        )
        self.btn_setpoints.pack(side="left", padx=5)

        self.btn_restart = tk.Button(
            buttons_col,
            text="🔄 Restart",
            fg="#1e293b",
            bg=BTN_SECONDARY,
            activebackground=BTN_HOVER,
            activeforeground="#1e293b",
            font=("Helvetica", 11, "bold"),
            relief="flat",
            bd=0,
            width=12,
            pady=8,
            command=self.restart_app
        )
        self.btn_restart.pack(side="left", padx=5)

        self.btn_exit = tk.Button(
            buttons_col,
            text="❌ Exit",
            fg="white",
            bg=RED_ACCENT,
            activebackground="#D32F2F",
            activeforeground="white",
            font=("Helvetica", 11, "bold"),
            relief="flat",
            bd=0,
            width=8,
            pady=8,
            command=self.exit_app
        )
        self.btn_exit.pack(side="left", padx=5)

        # Hover configurations
        self.bind_btn_hover(self.btn_setpoints, BTN_PRIMARY, BTN_HOVER_PRIMARY)
        self.bind_btn_hover(self.btn_restart, BTN_SECONDARY, BTN_HOVER)
        self.bind_btn_hover(self.btn_exit, RED_ACCENT, "#D32F2F")

    def bind_btn_hover(self, btn, normal_color, hover_color):
        btn.bind("<Enter>", lambda e: btn.config(bg=hover_color))
        btn.bind("<Leave>", lambda e: btn.config(bg=normal_color))

    def build_light_rows(self):
        # Configure columns for 2-column grid
        self.list_frame.columnconfigure(0, weight=1)
        self.list_frame.columnconfigure(1, weight=1)
        
        for idx in range(1, 9):
            row_idx = (idx - 1) // 2
            col_idx = (idx - 1) % 2
            
            # Create a card frame for each light channel
            card = tk.Frame(
                self.list_frame, 
                bg=CARD_BG, 
                bd=1, 
                highlightbackground=BORDER_COLOR, 
                highlightthickness=1
            )
            card.grid(row=row_idx, column=col_idx, padx=15, pady=8, sticky="nsew")
            
            # Left: Channel Icon and Name
            info_frame = tk.Frame(card, bg=CARD_BG)
            info_frame.pack(side="left", padx=15, pady=8)
            
            lbl_dot = tk.Label(info_frame, text="●", fg="#dc2626", bg=CARD_BG, font=("Helvetica", 16))
            lbl_dot.pack(side="left", padx=(0, 8))
            
            lbl_name = tk.Label(
                info_frame, 
                text=f"Light Channel {idx}", 
                fg=TEXT_COLOR, 
                bg=CARD_BG, 
                font=("Helvetica", 12, "bold")
            )
            lbl_name.pack(side="left")
            
            # Right: Intensity
            lbl_intensity = tk.Label(
                card, 
                text="0%", 
                fg=ACCENT_BLUE, 
                bg=CARD_BG, 
                font=("Helvetica", 16, "bold"), 
                width=6, 
                anchor="e"
            )
            lbl_intensity.pack(side="right", padx=15)

            # Center/Right: Active Frame Name
            lbl_frame = tk.Label(
                card, 
                text="None", 
                fg=MUTED_TEXT, 
                bg=CARD_BG, 
                font=("Helvetica", 11, "italic")
            )
            lbl_frame.pack(side="right", padx=30)

            self.row_widgets[idx] = {
                "frame": card,
                "name": lbl_name,
                "frame_label": lbl_frame,
                "intensity_label": lbl_intensity,
                "dot": lbl_dot
            }
            
        # Configure row weights to spread cards evenly
        for r in range(4):
            self.list_frame.rowconfigure(r, weight=1)

    def update_clock_and_schedule(self):
        time_str = time.strftime("%H:%M:%S")
        date_str = time.strftime("%d-%m-%Y")
        day_str = time.strftime("%A")
        clock_text = f"Time: {time_str}\nDate: {date_str}\nDay: {day_str}"

        active_labels = []
        for lbl in self.clock_labels:
            try:
                if lbl.winfo_exists():
                    lbl.config(text=clock_text)
                    active_labels.append(lbl)
            except Exception:
                pass
        self.clock_labels = active_labels

        evaluate_scheduler()

        for idx in range(1, 9):
            if idx in self.row_widgets:
                widgets = self.row_widgets[idx]
                state = current_states[idx]
                
                frame_name = state["frame_name"]
                widgets["frame_label"].config(
                    text=frame_name,
                    fg=ACCENT_BLUE if frame_name != "None" else MUTED_TEXT
                )
                
                intensity_val = state["intensity"]
                widgets["intensity_label"].config(
                    text=f"{intensity_val}%" if intensity_val >= 0 else "0%"
                )
                
                # Update dot color based on active state (Green = glowing & ESP online, Red = off or ESP offline)
                is_esp_online = esp_connected_states.get(idx, False)
                if intensity_val > 0 and is_esp_online:
                    widgets["dot"].config(fg=ACCENT_GREEN)
                else:
                    widgets["dot"].config(fg="#dc2626")

                light_cfg = next((l for l in active_config["lights"] if l["id"] == idx), None)
                if light_cfg:
                    widgets["name"].config(text=light_cfg["name"])

        self.root.after(1000, self.update_clock_and_schedule)

    # --- PASSWORD SECURITY GATE ---
    def open_password_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Security Authentication")
        win.configure(bg="#f8fafc")
        win.focus_force()
        win.update()
        win.attributes("-fullscreen", True)
        win.grab_set()
        
        password_entered = ""
        correct_password = str(config.get("password", "1234"))

        # Center container frame to hold all dialog widgets in fullscreen mode
        main_container = tk.Frame(win, bg="#f8fafc")
        main_container.place(relx=0.5, rely=0.5, anchor="center")

        # Header Frame for Title and Logo
        header_frame = tk.Frame(main_container, bg="#f8fafc")
        header_frame.pack(fill="x", padx=20, pady=(20, 5))
        
        title_sub_frame = tk.Frame(header_frame, bg="#f8fafc")
        title_sub_frame.pack(side="left")
        
        tk.Label(title_sub_frame, text="SECURITY LOCK", font=("Arial", 16, "bold"), fg="#1e293b", bg="#f8fafc").pack(anchor="w")
        tk.Label(title_sub_frame, text="Enter authorization PIN to unlock settings:", font=("Arial", 9), fg="#64748b", bg="#f8fafc").pack(anchor="w", pady=2)
        
        draw_logo(header_frame)

        # Display entry for password (shows bullets/asterisks)
        display_lbl = tk.Label(main_container, text="", font=("Arial", 20, "bold"), fg="#0f172a", bg="white", width=12, relief="sunken", bd=2, anchor="center")
        display_lbl.pack(pady=10)

        error_lbl = tk.Label(main_container, text="", font=("Arial", 10, "bold"), fg="#dc2626", bg="#f8fafc")
        error_lbl.pack(pady=2)

        def kp_press(char):
            nonlocal password_entered
            if len(password_entered) < 12:
                password_entered += str(char)
                display_lbl.config(text="●" * len(password_entered))
                error_lbl.config(text="")

        def kp_back():
            nonlocal password_entered
            password_entered = password_entered[:-1]
            display_lbl.config(text="●" * len(password_entered))
            error_lbl.config(text="")

        def kp_clear():
            nonlocal password_entered
            password_entered = ""
            display_lbl.config(text="")
            error_lbl.config(text="")

        def kp_confirm():
            nonlocal password_entered
            if password_entered == correct_password:
                win.destroy()
                self.open_setpoints_window()
            else:
                error_lbl.config(text="❌ Incorrect PIN/Password!")
                kp_clear()

        # Keypad Grid (3x4 Layout with integrated DEL/CLR)
        kp_frame = tk.Frame(main_container, bg="#f8fafc")
        kp_frame.pack(pady=10)

        buttons = [
            ('1', 0, 0), ('2', 0, 1), ('3', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('7', 2, 0), ('8', 2, 1), ('9', 2, 2),
            ('CLR', 3, 0), ('0', 3, 1), ('DEL', 3, 2)
        ]

        for text, r, c in buttons:
            if text == 'DEL':
                cmd = kp_back
                bg, fg = "#f97316", "white"
            elif text == 'CLR':
                cmd = kp_clear
                bg, fg = "#dc2626", "white"
            else:
                cmd = lambda x=text: kp_press(x)
                bg, fg = "#ffffff", "#1e293b"
                
            btn = tk.Button(kp_frame, text=text, font=("Arial", 12, "bold"), width=6, height=2,
                            bg=bg, fg=fg, bd=1, relief="raised", command=cmd)
            btn.grid(row=r, column=c, padx=4, pady=4)

        # Confirm & Cancel
        action_frame = tk.Frame(main_container, bg="#f8fafc")
        action_frame.pack(fill="x", side="bottom", pady=15, padx=20)

        clock_container = tk.Frame(action_frame, bg="#f8fafc")
        clock_container.pack(side="left", anchor="s")

        kp_clock_lbl = tk.Label(
            clock_container,
            text="",
            fg="#0f172a",
            bg="#f8fafc",
            font=("Arial", 8, "bold"),
            justify="left",
            anchor="w"
        )
        kp_clock_lbl.pack(anchor="w")
        self.clock_labels.append(kp_clock_lbl)

        tk.Button(action_frame, text="EXIT", font=("Arial", 10, "bold"), bg="#cbd5e1", fg="#1e293b", width=10, height=2, bd=1, relief="raised",
                  command=win.destroy).pack(side="left", padx=15, anchor="s")

        tk.Button(action_frame, text="AUTHENTICATE", font=("Arial", 10, "bold"), bg="#0284c7", fg="white", width=14, height=2, bd=1, relief="raised",
                  command=kp_confirm).pack(side="right", anchor="s")

    # --- SETPOINTS CONFIGURATOR WINDOW (Reference: Adv_control.py) ---
    def open_setpoints_window(self):
        try:
            self._open_setpoints_window()
        except Exception as e:
            import traceback
            err_msg = traceback.format_exc()
            messagebox.showerror("Error", f"Failed to load Setpoints Window:\n{err_msg}", parent=self.root)

    def _open_setpoints_window(self):
        set_win = tk.Toplevel(self.root)
        set_win.title("Setpoint Configurations")
        set_win.configure(bg=BG_COLOR)
        set_win.focus_force()
        set_win.update()
        set_win.attributes("-fullscreen", True)
        set_win.grab_set()

        global active_config
        local_config_copy = json.loads(json.dumps(config))
        active_config = local_config_copy
        self.timeframe_sliders = {}

        style = ttk.Style()
        style.theme_use('default')
        
        # --- STATIC HEADER ---
        header = tk.Frame(set_win, bg=BG_COLOR)
        header.pack(fill="x", padx=30, pady=(5, 2))

        lbl_title = tk.Label(
            header,
            text="SYSTEM — SETPOINTS CONFIGURATION",
            font=("Helvetica", 18, "bold"),
            fg=ACCENT_BLUE,
            bg=BG_COLOR
        )
        lbl_title.pack(side="left", pady=2)

        # Statically place logo in the top right corner of the window
        draw_logo(header)

        # --- MAIN CONTENT FRAME ---
        content_frame = tk.Frame(set_win, bg=BG_COLOR)
        content_frame.pack(fill="both", expand=True)

        # Top Control Row (Drop-down, Name Editor, PIN Editor)
        top_bar = tk.Frame(content_frame, bg=BG_COLOR)
        top_bar.pack(fill="x", padx=30, pady=5)

        # Channel Selector
        ch_selector_frame = tk.Frame(top_bar, bg=BG_COLOR)
        ch_selector_frame.pack(side="left", padx=(0, 15))
        
        tk.Label(ch_selector_frame, text="Select Channel:", fg=MUTED_TEXT, bg=BG_COLOR, font=("Helvetica", 11, "bold")).pack(side="left", padx=(0, 6))

        dropdown_options = [f"Ch {i} - {local_config_copy['lights'][i-1]['name']}" for i in range(1, 9)]
        
        # Elegant Combobox Customization
        style.configure("TCombobox", 
                        fieldbackground=CARD_BG, 
                        background=BTN_SECONDARY, 
                        foreground=TEXT_COLOR, 
                        selectbackground=ACCENT_BLUE,
                        selectforeground="white",
                        font=("Helvetica", 13, "bold"),
                        padding=8)
        
        set_win.option_add("*TCombobox*Listbox.font", ("Helvetica", 13, "bold"))
        set_win.option_add("*TCombobox*Listbox.background", CARD_BG)
        set_win.option_add("*TCombobox*Listbox.foreground", TEXT_COLOR)
        set_win.option_add("*TCombobox*Listbox.selectBackground", ACCENT_BLUE)
        set_win.option_add("*TCombobox*Listbox.selectForeground", "white")
        set_win.option_add("*TCombobox*Listbox.relief", "flat")

        self.combo_light = ttk.Combobox(
            ch_selector_frame,
            values=dropdown_options,
            state="readonly",
            width=20,
            font=("Helvetica", 13, "bold")
        )
        self.combo_light.set(dropdown_options[0])
        self.combo_light.pack(side="left")

        # Alphanumeric EDIT cell for Channel Display Name
        name_cell_frame = tk.Frame(top_bar, bg=CARD_BG, bd=1, relief="solid", padx=12, pady=8)
        name_cell_frame.pack(side="left", padx=15)
        
        lbl_name_tag = tk.Label(name_cell_frame, text="Name:", fg=MUTED_TEXT, bg=CARD_BG, font=("Helvetica", 11, "bold"))
        lbl_name_tag.pack(side="left", padx=(0, 6))
        
        lbl_channel_name = tk.Label(name_cell_frame, text=local_config_copy['lights'][0]['name'], fg=TEXT_COLOR, bg=CARD_BG, font=("Helvetica", 13, "bold"))
        lbl_channel_name.pack(side="left", padx=(0, 8))

        # PIN code editing cell
        pin_cell_frame = tk.Frame(top_bar, bg=CARD_BG, bd=1, relief="solid", padx=12, pady=8)
        pin_cell_frame.pack(side="left", padx=15)
        
        lbl_pin_tag = tk.Label(pin_cell_frame, text="PIN:", fg=MUTED_TEXT, bg=CARD_BG, font=("Helvetica", 11, "bold"))
        lbl_pin_tag.pack(side="left", padx=(0, 6))
        lbl_pin_val = tk.Label(pin_cell_frame, text="●" * len(local_config_copy.get("password", "1234")), fg=TEXT_COLOR, bg=CARD_BG, font=("Helvetica", 13, "bold"))
        lbl_pin_val.pack(side="left", padx=(0, 10))

        # --- KEYPAD FRAME (INITIALLY HIDDEN) ---
        kp_frame = tk.Frame(set_win, bg=BG_COLOR)

        kp_title = tk.Label(kp_frame, font=("Helvetica", 16, "bold"), fg=ACCENT_BLUE, bg=BG_COLOR)
        kp_title.pack(pady=(8, 2))
        
        kp_display_frame = tk.Frame(kp_frame, bg=CARD_BG, bd=1, relief="solid", padx=20, pady=6)
        kp_display_frame.pack(pady=4)
        
        kp_display = tk.Label(kp_display_frame, font=("Helvetica", 20, "bold"), fg=TEXT_COLOR, bg=CARD_BG, width=25, anchor="center")
        kp_display.pack()
        
        kp_buttons = tk.Frame(kp_frame, bg=BG_COLOR)
        kp_buttons.pack(pady=4)
        
        kp_actions = tk.Frame(kp_frame, bg=BG_COLOR)
        kp_actions.pack(pady=4)

        sp_entered_value = ""

        # Handle context keypad editing
        def edit_field(light_id, frame_idx, field, val_lbl):
            light = local_config_copy["lights"][light_id - 1]
            
            is_password = False
            if frame_idx is None:
                if field == "password":
                    initial = local_config_copy.get("password", "1234")
                    title = "Edit Security PIN"
                    is_num = True
                    is_password = True
                else:
                    initial = light["name"]
                    title = f"Edit Channel {light_id} Name"
                    is_num = False
            else:
                frame = light["time_frames"][frame_idx]
                initial = frame[field]
                title = f"Edit TF {frame_idx+1} {field.capitalize()}"
                is_num = (field in ["start", "end", "intensity"])
                
            def on_keypad_submit(new_val):
                nonlocal local_config_copy
                new_val = new_val.strip()
                if frame_idx is None:
                    if field == "password":
                        if not new_val.isdigit():
                            messagebox.showerror("Error", "PIN must be numeric digits only.", parent=set_win)
                            return
                        if len(new_val) < 4 or len(new_val) > 8:
                            messagebox.showerror("Error", "PIN must be between 4 and 8 digits.", parent=set_win)
                            return
                        local_config_copy["password"] = new_val
                        lbl_pin_val.config(text="●" * len(new_val))
                    else:
                        if not new_val:
                            messagebox.showerror("Error", "Name cannot be empty.", parent=set_win)
                            return
                        light["name"] = new_val
                        lbl_channel_name.config(text=new_val)
                        
                        dropdown_options[light_id - 1] = f"Ch {light_id} - {new_val}"
                        self.combo_light.config(values=dropdown_options)
                        self.combo_light.set(dropdown_options[light_id - 1])
                else:
                    frame = light["time_frames"][frame_idx]
                    if field == "name":
                        if not new_val:
                            messagebox.showerror("Error", "Name cannot be empty.", parent=set_win)
                            return
                        frame["name"] = new_val
                        val_lbl.config(text=new_val, width=len(new_val) + 2)
                    elif field == "intensity":
                        try:
                            val = int(new_val.replace("%", ""))
                            if not (0 <= val <= 100):
                                 raise ValueError()
                        except ValueError:
                            messagebox.showerror("Error", "Intensity must be a number from 0 to 100.", parent=set_win)
                            return
                        frame["intensity"] = val
                        val_lbl.config(text=f"{val}%", width=len(f"{val}%") + 2)
                        if (light_id, frame_idx) in self.timeframe_sliders:
                            try:
                                 self.timeframe_sliders[(light_id, frame_idx)].set(val)
                            except Exception:
                                 pass
                    else:
                        # Time validation
                        try:
                            parts = new_val.split(':')
                            if len(parts) != 2:
                                 raise ValueError()
                            h, m = int(parts[0]), int(parts[1])
                            if not (0 <= h < 24 and 0 <= m < 60):
                                 raise ValueError()
                        except ValueError:
                            messagebox.showerror("Error", "Time format must be HH:MM (e.g. 06:30).", parent=set_win)
                            return
                        frame[field] = f"{h:02d}:{m:02d}"
                        val_lbl.config(text=f"{h:02d}:{m:02d}", width=len(f"{h:02d}:{m:02d}") + 2)

            # Open in-window keypad
            open_in_window_keypad(title, initial, is_num, is_password, on_keypad_submit)

        def open_in_window_keypad(title_text, initial_value, is_numeric, is_password, on_submit):
            nonlocal sp_entered_value
            sp_entered_value = str(initial_value)
            
            # Clear old keypad buttons and actions
            for w in kp_buttons.winfo_children():
                w.destroy()
            for w in kp_actions.winfo_children():
                w.destroy()
                
            kp_title.config(text=title_text)
            if is_password:
                kp_display.config(text="●" * len(sp_entered_value))
            else:
                kp_display.config(text=sp_entered_value)
                
            def kp_press(v):
                nonlocal sp_entered_value
                sp_entered_value += str(v)
                if is_password:
                    kp_display.config(text="●" * len(sp_entered_value))
                else:
                    kp_display.config(text=sp_entered_value)
                    
            def kp_clear():
                nonlocal sp_entered_value
                sp_entered_value = ""
                kp_display.config(text="")
                
            def kp_back():
                nonlocal sp_entered_value
                sp_entered_value = sp_entered_value[:-1]
                if is_password:
                    kp_display.config(text="●" * len(sp_entered_value))
                else:
                    kp_display.config(text=sp_entered_value)
                    
            def kp_confirm_action():
                on_submit(sp_entered_value)
                kp_frame.pack_forget()
                content_frame.pack(fill="both", expand=True)
                
            def kp_cancel_action():
                kp_frame.pack_forget()
                content_frame.pack(fill="both", expand=True)
                
            # Build Keyboard/Keypad buttons (Wide and tall keys for touchscreen ease of use)
            if not is_numeric:
                # Alphanumeric layout
                for ri, row_k in enumerate([list("1234567890"), list("QWERTYUIOP"),
                                             list("ASDFGHJKL:"), list("ZXCVBNM._ ")]):
                    for ci, ch in enumerate(row_k):
                        tk.Button(
                            kp_buttons,
                            text=ch if ch != ' ' else 'SPC',
                            font=("Arial", 11, "bold"),
                            width=6,
                            height=2,
                            bg=BTN_SECONDARY,
                            fg=TEXT_COLOR,
                            activebackground=BTN_HOVER,
                            command=lambda x=ch: kp_press(x)
                        ).grid(row=ri, column=ci, padx=2, pady=2)
                w_btn = 12
            else:
                # Numeric layout
                for text, ri, ci in [('1',0,0), ('2',0,1), ('3',0,2),
                                     ('4',1,0), ('5',1,1), ('6',1,2),
                                     ('7',2,0), ('8',2,1), ('9',2,2),
                                     ('.',3,0), ('0',3,1), (':',3,2)]:
                    tk.Button(
                        kp_buttons,
                        text=text,
                        font=("Arial", 12, "bold"),
                        width=10,
                        height=2,
                        bg=BTN_SECONDARY,
                        fg=TEXT_COLOR,
                        activebackground=BTN_HOVER,
                        command=lambda x=text: kp_press(x)
                    ).grid(row=ri, column=ci, padx=2, pady=2)
                w_btn = 10
                
            # Actions row (wide and easily clickable)
            for txt, bg, fg, cmd in [("DEL", "orange", "black", kp_back),
                                     ("CLR", "#d9534f", "white", kp_clear),
                                     ("OK", "green", "white", kp_confirm_action),
                                     ("CAN", "red", "white", kp_cancel_action)]:
                 tk.Button(
                     kp_actions,
                     text=txt,
                     font=("Arial", 11, "bold"),
                     bg=bg,
                     fg=fg,
                     width=w_btn,
                     height=2,
                     command=cmd
                 ).pack(side="left", padx=6)
                
            # Swap UI
            content_frame.pack_forget()
            kp_frame.pack(expand=True, fill="both")

        def edit_pin_code():
            current_id = self.combo_light.current() + 1
            edit_field(current_id, None, "password", lbl_pin_val)

        def edit_channel_name():
            current_id = self.combo_light.current() + 1
            edit_field(current_id, None, "name", lbl_channel_name)

        btn_edit_pin = tk.Button(
            pin_cell_frame,
            text="EDIT",
            font=("Helvetica", 11, "bold"),
            bg=BTN_SECONDARY,
            fg=TEXT_COLOR,
            activebackground=BTN_HOVER,
            relief="flat",
            bd=0,
            padx=12,
            pady=4,
            command=edit_pin_code
        )
        btn_edit_pin.pack(side="left", padx=6)

        btn_edit_channel = tk.Button(
            name_cell_frame,
            text="EDIT",
            font=("Helvetica", 11, "bold"),
            bg=BTN_SECONDARY,
            fg=TEXT_COLOR,
            activebackground=BTN_HOVER,
            relief="flat",
            bd=0,
            padx=12,
            pady=4,
            command=edit_channel_name
        )
        btn_edit_channel.pack(side="left", padx=6)

        # Timeframes Editor Container (Horizontal Layout)
        tf_container = tk.Frame(content_frame, bg=BG_COLOR)
        tf_container.pack(fill="x", expand=False, padx=30, pady=(15, 10))

        # Helper to generate cells for each TF frame
        def build_timeframe_card(parent, light_id, f_idx, row, col):
            light = local_config_copy["lights"][light_id - 1]
            frame = light["time_frames"][f_idx]
            
            f_frame = tk.LabelFrame(
                parent,
                text=f" Time Frame {f_idx + 1} ",
                fg=ACCENT_BLUE,
                bg=CARD_BG,
                font=("Helvetica", 12, "bold"),
                bd=1,
                relief="solid",
                padx=15,
                pady=8
            )
            # Grid layout for 2x2 presentation
            f_frame.grid(row=row, column=col, padx=15, pady=10, sticky="nsew")
            
            # Row 0: Name Cell
            cell_name, lbl_name = create_edit_cell(
                f_frame, 
                "Name:", 
                frame["name"], 
                lambda: edit_field(light_id, f_idx, "name", lbl_name)
            )
            cell_name.pack(fill="x", pady=1)
            
            # Row 1: Start Time Cell
            cell_start, lbl_start = create_edit_cell(
                f_frame, 
                "Start:", 
                frame["start"], 
                lambda: edit_field(light_id, f_idx, "start", lbl_start)
            )
            cell_start.pack(fill="x", pady=1)
            
            # Row 2: End Time Cell
            cell_end, lbl_end = create_edit_cell(
                f_frame, 
                "End:", 
                frame["end"], 
                lambda: edit_field(light_id, f_idx, "end", lbl_end)
            )
            cell_end.pack(fill="x", pady=1)
            
            # Row 3: Intensity % Cell
            cell_intensity, lbl_intensity = create_edit_cell(
                f_frame, 
                "Intensity:", 
                f"{frame['intensity']}%", 
                lambda: edit_field(light_id, f_idx, "intensity", lbl_intensity)
            )
            cell_intensity.pack(fill="x", pady=1)

            # Horizontal Scale Slider under Intensity
            slider = tk.Scale(
                f_frame,
                from_=0,
                to=100,
                orient="horizontal",
                bg="#cbd5e1",
                fg=TEXT_COLOR,
                troughcolor="#94a3b8",
                activebackground="#94a3b8",
                highlightthickness=0,
                bd=0,
                width=10,
                showvalue=False
            )
            slider.set(frame["intensity"])
            slider.pack(fill="x", pady=(2, 4))
            
            def make_slider_callback(fr, lbl, l_id):
                def callback(val):
                    val_int = int(float(val))
                    fr["intensity"] = val_int
                    lbl.config(text=f"{val_int}%", width=len(f"{val_int}%") + 2)
                    
                    # Live intensity adjustment along with slider movement
                    tm = time.localtime(time.time())
                    current_mins = tm.tm_hour * 60 + tm.tm_min
                    if is_time_in_frame(current_mins, fr["start"], fr["end"]):
                        current_states[l_id]["intensity"] = val_int
                    
                    local_topic = f"lights/intensity/{l_id}"
                    cloud_topic = f"mydevice_931d/lights/intensity/{l_id}"
                    if local_connected:
                        try:
                            local_client.publish(local_topic, str(val_int), qos=1, retain=True)
                        except Exception as e:
                            print(f"Local live publish error: {e}")
                    if cloud_connected:
                        try:
                            cloud_client.publish(cloud_topic, str(val_int), qos=1, retain=True)
                        except Exception as e:
                            print(f"Cloud live publish error: {e}")
                return callback

            slider.config(command=make_slider_callback(frame, lbl_intensity, light_id))
            self.timeframe_sliders[(light_id, f_idx)] = slider

        # Rebuild grid dynamically
        def rebuild_timeframe_grid():
            for widget in tf_container.winfo_children():
                widget.destroy()
                
            # Nested frame centered horizontally to hold the 2x2 grid
            cards_inner = tk.Frame(tf_container, bg=BG_COLOR)
            cards_inner.pack(anchor="center")
            
            current_id = self.combo_light.current() + 1
            for f_idx in range(4):
                r = f_idx // 2
                c = f_idx % 2
                build_timeframe_card(cards_inner, current_id, f_idx, r, c)

        # Handle Combobox Select
        def on_dropdown_select(event):
            current_id = self.combo_light.current() + 1
            lbl_channel_name.config(text=local_config_copy['lights'][current_id-1]['name'])
            rebuild_timeframe_grid()
            
        self.combo_light.bind("<<ComboboxSelected>>", on_dropdown_select)

        # Initialize Grid
        rebuild_timeframe_grid()

        # Save and Close Dialog
        def close_setpoints_window():
            global active_config
            active_config = config
            evaluate_scheduler()
            set_win.destroy()

        set_win.protocol("WM_DELETE_WINDOW", close_setpoints_window)

        def save_and_close():
            # Validate overlaps for all channels
            for light in local_config_copy["lights"]:
                has_conflict, error_msg = check_timeframes_conflict(light["time_frames"])
                if has_conflict:
                    messagebox.showerror(
                        "Time Conflict Error", 
                        f"Light '{light['name']}' has a scheduling conflict:\n{error_msg}", 
                        parent=set_win
                    )
                    return

            global config, active_config
            config = local_config_copy
            active_config = config
            if save_config(config):
                evaluate_scheduler()
                set_win.destroy()
            else:
                messagebox.showerror("Save Error", "Could not save configuration file.", parent=set_win)

        # Footer Buttons
        set_footer = tk.Frame(set_win, bg=BG_COLOR)
        set_footer.pack(fill="x", side="bottom", padx=30, pady=(5, 10))
        set_footer.columnconfigure(0, weight=1)
        set_footer.columnconfigure(1, weight=1)
        set_footer.columnconfigure(2, weight=1)
        set_footer.columnconfigure(3, weight=1)

        # Clock label in left downward corner
        clock_container = tk.Frame(set_footer, bg=BG_COLOR)
        clock_container.grid(row=0, column=0, sticky="sw", padx=(0, 10))
        
        set_clock_lbl = tk.Label(
            clock_container,
            text="",
            fg="#0f172a",
            bg=BG_COLOR,
            font=("Helvetica", 9, "bold"),
            justify="left",
            anchor="w"
        )
        set_clock_lbl.pack(anchor="w")
        self.clock_labels.append(set_clock_lbl)

        btn_exit_app = tk.Button(
            set_footer,
            text="EXIT",
            bg="#dc2626",
            fg="white",
            activebackground="#b91c1c",
            activeforeground="white",
            font=("Helvetica", 12, "bold"),
            relief="flat",
            pady=6,
            command=self.exit_app
        )
        btn_exit_app.grid(row=0, column=1, padx=10, sticky="ew")

        btn_back_home = tk.Button(
            set_footer,
            text="BACK TO HOME",
            bg=BTN_SECONDARY,
            fg="#1e293b",
            activebackground=BTN_HOVER,
            activeforeground="#1e293b",
            font=("Helvetica", 12, "bold"),
            relief="flat",
            pady=6,
            command=close_setpoints_window
        )
        btn_back_home.grid(row=0, column=2, padx=10, sticky="ew")

        btn_save = tk.Button(
            set_footer,
            text="SAVE & EXIT",
            bg=BTN_PRIMARY,
            fg="white",
            activebackground=BTN_HOVER_PRIMARY,
            activeforeground="white",
            font=("Helvetica", 12, "bold"),
            relief="flat",
            pady=6,
            command=save_and_close
        )
        btn_save.grid(row=0, column=3, padx=(10, 0), sticky="ew")

    # --- BUTTON ACTIONS ---
    def restart_app(self):
        print("Restarting application...")
        try:
            local_client.loop_stop()
            local_client.disconnect()
        except Exception:
            pass
        try:
            cloud_client.loop_stop()
            cloud_client.disconnect()
        except Exception:
            pass
        
        python = sys.executable
        os.execl(python, python, *sys.argv)

    def exit_app(self):
        #print("Exiting application safely...")
        
        for idx in range(1, 9):
            local_topic = f"lights/intensity/{idx}"
            cloud_topic = f"mydevice_931d/lights/intensity/{idx}"
            if local_connected:
                try:
                    local_client.publish(local_topic, "0", qos=1, retain=True)
                except Exception:
                    pass
            if cloud_connected:
                try:
                    cloud_client.publish(cloud_topic, "0", qos=1, retain=True)
                except Exception:
                    pass

        try:
            local_client.loop_stop()
            local_client.disconnect()
        except Exception:
            pass
        try:
            cloud_client.loop_stop()
            cloud_client.disconnect()
        except Exception:
            pass

        self.root.destroy()

# --- ENTRY POINT ---
if __name__ == "__main__":
    root = tk.Tk()
    app = MainControllerApp(root)
    
    def on_window_close():
        app.exit_app()

    root.protocol("WM_DELETE_WINDOW", on_window_close)
    root.mainloop()
