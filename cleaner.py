import re

with open("dynamic.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Remove emojis
content = content.replace("📱 ", "").replace("📱", "")
content = content.replace("ℹ️ ", "").replace("ℹ️", "")

# 2. Remove unused imports
content = re.sub(r'import os, sys, json, time, datetime, socket, glob, fcntl', 'import os, sys, json, time, datetime, glob, fcntl', content)
content = re.sub(r'from tkinter import font\n', '', content)
content = re.sub(r'import serial\n', '', content)

# 3. Remove legacy setpoints.json removal
old_file_pattern = r'# Remove legacy setpoints file to avoid sync conflicts\s+OLD_FILE = os\.path\.join\(BASE_DIR, "setpoints\.json"\)\s+if os\.path\.exists\(OLD_FILE\):\s+try:\s+os\.remove\(OLD_FILE\)\s+print\(" Removed legacy setpoints\.json\.\.\."\)\s+except Exception: pass\n+'
content = re.sub(old_file_pattern, '', content)

# 4. Remove alt_files fallback & uS/cm migration
alt_pattern = r'else:\s+alt_files = glob\.glob\(os\.path\.join\(BASE_DIR, "setpoints_\*\.json"\)\)\s+if alt_files:\s+try:\s+with open\(alt_files\[0\]\) as f:\s+setpoints\.update\(json\.load\(f\)\)\s+print\(f" Inherited setpoints from alternate file: \{alt_files\[0\]\}"\)\s+except Exception as e:\s+print\(f" Error reading alt setpoint file: \{e\}"\)\s+# Legacy auto-migration from uS/cm \(1200/1800\) to mS/cm \(1\.2/1\.8\)\s+if float\(setpoints\.get\("EC MIN", 1\.2\)\) > 100:\s+setpoints\["EC MIN"\] = round\(float\(setpoints\["EC MIN"\]\) / 1000\.0, 2\)\s+if float\(setpoints\.get\("EC MAX", 1\.8\)\) > 100:\s+setpoints\["EC MAX"\] = round\(float\(setpoints\["EC MAX"\]\) / 1000\.0, 2\)\n+'
content = re.sub(alt_pattern, '', content)

# 5. Remove dead aliases and unused trackers
content = content.replace('relay_temp = relay_fan1\n', '')
content = content.replace('relay_humi = relay_fogger\n', '')
content = content.replace('relay_temp', 'relay_fan1')
content = content.replace('relay_humi', 'relay_fogger')
content = content.replace('temp_active       = False\n', '')
content = content.replace('humi_active       = False\n', '')
content = content.replace('temp_active = False\n', '')
content = content.replace('humi_active = False\n', '')
content = content.replace('temp_active = humi_active = ', '')
content = content.replace('temp_active, humi_active, ', '')

# 6. Clean dead timer_state keys
content = content.replace('    1: {"state": "OFF", "last": 0.0},\n    2: {"state": "OFF", "last": 0.0},\n', '')

# 7. Remove full-line comments (# ...)
lines = content.split('\n')
cleaned_lines = []
for line in lines:
    stripped = line.strip()
    if stripped.startswith('#'):
        continue
    cleaned_lines.append(line)

# 8. Collapse multiple blank lines into at most one blank line
final_lines = []
prev_blank = False
for line in cleaned_lines:
    if not line.strip():
        if not prev_blank:
            final_lines.append('')
            prev_blank = True
    else:
        final_lines.append(line)
        prev_blank = False

new_content = '\n'.join(final_lines) + '\n'

with open("dynamic_cleaned.py", "w", encoding="utf-8") as f:
    f.write(new_content)

print(f"Cleaned lines: {len(final_lines)}")
