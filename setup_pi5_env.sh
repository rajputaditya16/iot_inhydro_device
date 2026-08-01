#!/bin/bash
# Raspberry Pi 5 Environment Setup & Launcher for Almora2 Controller

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================"
echo "🚀 Setting up Raspberry Pi 5 Environment for Almora2"
echo "======================================================"

# 1. Setup Passwordless Sudo for Headless Bluetooth & WiFi (nmcli)
echo "🔑 [1/5] Configuring sudo permissions..."
echo "$USER ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/$USER >/dev/null

# 2. Update APT & Install System Dependencies for Pi 5, GPIO & Bluetooth
echo "📦 [2/5] Installing system packages, GPIO & Bluetooth tools..."
sudo apt update
sudo apt install -y \
    python3-lgpio \
    python3-rpi-lgpio \
    python3-gpiozero \
    liblgpio-dev \
    python3-dev \
    build-essential \
    swig \
    python3-venv \
    python3-pip \
    python3-pil \
    python3-pil.imagetk \
    bluez \
    bluez-tools \
    network-manager

# 3. Configure Bluetooth Service Compatibility (-C) & SDP Permission
echo "📡 [3/5] Configuring Bluetooth service and SDP socket..."
sudo mkdir -p /etc/systemd/system/bluetooth.service.d
BLUETOOTH_PATH=$(which bluetoothd || echo "/usr/libexec/bluetooth/bluetoothd")
echo -e "[Service]\nExecStart=\nExecStart=${BLUETOOTH_PATH} -C\nExecStartPost=-/bin/chmod 777 /var/run/sdp" | sudo tee /etc/systemd/system/bluetooth.service.d/override.conf >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable bluetooth
sudo systemctl restart bluetooth
sleep 1
sudo sdptool add SP >/dev/null 2>&1 || true
if [ -e /var/run/sdp ]; then
    sudo chmod 777 /var/run/sdp >/dev/null 2>&1 || true
fi

# 4. Setup Virtual Environment with System Site Packages enabled
VENV_DIR="${SCRIPT_DIR}/venv"
echo "🐍 [4/5] Configuring Python virtual environment at ${VENV_DIR}..."

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv --system-site-packages "$VENV_DIR"
else
    python3 -m venv --system-site-packages "$VENV_DIR"
fi

# 5. Install Python Dependencies in Virtual Environment
echo "📥 [5/5] Installing Python requirements into venv..."
"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel >/dev/null
"${VENV_DIR}/bin/pip" install \
    lgpio \
    gpiozero \
    minimalmodbus \
    paho-mqtt \
    pillow \
    pyserial

echo "======================================================"
echo "✅ Raspberry Pi 5 & Bluetooth Setup Complete!"
echo "======================================================"

# Launch almora2.py
if [ "$1" == "--no-run" ]; then
    echo "Setup finished. You can run the controller anytime using:"
    echo "  ${VENV_DIR}/bin/python almora2.py"
else
    echo "▶️ Launching almora2.py..."
    "${VENV_DIR}/bin/python" almora2.py
fi
