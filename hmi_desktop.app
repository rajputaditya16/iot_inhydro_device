nano ~/.config/autostart/hmi_app.desktop


[Desktop Entry]
Type=Application
Name=Industrial HMI
Exec=bash -c "sleep 5; while true; do /home/rock/Documents/New/venv/bin/python /home/rock/Documents/New/monit.pyc; echo 'App Closed, restarting in 2 seconds...'; sleep 3; done"
Terminal=false
NoDisplay=false
X-GNOME-Autostart-enabled=true


chmod +x ~/.config/autostart/hmi_app.desktop
gtk-launch hmi_app.desktop

pkill -f "hmi_app.desktop" && pkill -f "monit.pyc"

killall -9 bash


[Desktop Entry]
Type=Application
Name=Industrial HMI
Exec=bash -c "sleep 5; xset s off; xset -dpms; xset s noblank; while true; do cd /home/rock/Documents/New/ && /home/rock/Documents/New/venv/bin/python /home/rock/Documents/New/__pycache__/monit.pyc; echo 'Restarting...'; sleep 3; done"
Path=/home/rock/Documents/New/
Terminal=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
X-XFCE-Autostart-Override=true
