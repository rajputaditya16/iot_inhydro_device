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
