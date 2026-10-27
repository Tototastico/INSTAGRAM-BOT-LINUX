#!/usr/bin/env bash
# ==============================================================================
# install.sh - Preparación y aprovisionamiento base de Ubuntu VPS para INSTAGRAM-BOT
# Debe ejecutarse como root (sudo ./install.sh)
# ==============================================================================
set -euo pipefail

echo "=== [1/6] Comprobando precondiciones del sistema ==="
ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ]; then
    echo "[ERROR] Esta aplicación requiere arquitectura x86_64. Detectado: $ARCH" >&2
    exit 1
fi

if [ ! -f /etc/os-release ]; then
    echo "[ERROR] No se detectó distribución compatible con Debian/Ubuntu." >&2
    exit 1
fi

. /etc/os-release
if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
    echo "[ADVERTENCIA] Sistema operativo detectado: $ID. Se recomienda Ubuntu 22.04 / 24.04 LTS."
fi

echo "=== [2/6] Instalando paquetes y dependencias del sistema ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    curl \
    wget \
    gnupg \
    ca-certificates \
    git \
    build-essential \
    python3 \
    python3-venv \
    python3-pip \
    xvfb \
    xauth \
    x11-utils \
    libnss3 \
    libgconf-2-4 \
    libasound2 \
    libatk1.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxss1 \
    libxtst6 \
    fonts-liberation \
    xdg-utils \
    sqlite3

# Instalar Node.js LTS (para build del frontend) si no existe
if ! command -v node >/dev/null 2>&1; then
    echo "[*] Instalando Node.js LTS..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi

echo "=== [3/6] Instalando Google Chrome estable oficial ==="
if ! command -v google-chrome-stable >/dev/null 2>&1; then
    wget -q -O /tmp/google-chrome-stable_current_amd64.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    apt-get install -y /tmp/google-chrome-stable_current_amd64.deb || apt-get install -f -y
    rm -f /tmp/google-chrome-stable_current_amd64.deb
fi
echo "[OK] Google Chrome instalado: $(google-chrome-stable --version)"

echo "=== [4/6] Creando usuario y directorios del servicio ==="
USER="instagram-bot"
GROUP="instagram-bot"

if ! id "$USER" >/dev/null 2>&1; then
    useradd -r -s /bin/bash -m -d /var/lib/instagram-bot -U "$USER"
    echo "[OK] Usuario del sistema $USER creado."
fi

# Directorios de la aplicación y datos
mkdir -p /opt/instagram-bot/releases
mkdir -p /opt/instagram-bot/shared
mkdir -p /var/lib/instagram-bot/accounts
mkdir -p /var/lib/instagram-bot/data
mkdir -p /var/lib/instagram-bot/backups
mkdir -p /etc/instagram-bot

chown -R "$USER":"$GROUP" /opt/instagram-bot
chown -R "$USER":"$GROUP" /var/lib/instagram-bot
chmod 750 /var/lib/instagram-bot
chmod 700 /var/lib/instagram-bot/accounts
chmod 700 /var/lib/instagram-bot/data
chmod 700 /var/lib/instagram-bot/backups

echo "=== [5/6] Preparando entorno virtual común ==="
VENV_DIR="/opt/instagram-bot/venv"
if [ ! -d "$VENV_DIR" ]; then
    sudo -u "$USER" python3 -m venv "$VENV_DIR"
    sudo -u "$USER" "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel
fi

echo "=== [6/6] Configurando archivo de entorno y Systemd ==="
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f /etc/instagram-bot/instagram-bot.env ]; then
    cp "$SCRIPT_DIR/env.example" /etc/instagram-bot/instagram-bot.env
    chown root:"$GROUP" /etc/instagram-bot/instagram-bot.env
    chmod 640 /etc/instagram-bot/instagram-bot.env
    echo "[OK] Archivo /etc/instagram-bot/instagram-bot.env creado."
fi

cp "$SCRIPT_DIR/systemd/instagram-bot-display.service" /etc/systemd/system/
cp "$SCRIPT_DIR/systemd/instagram-bot.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable instagram-bot-display.service
systemctl enable instagram-bot.service

echo "=========================================================="
echo " [OK] Instalación base completada con éxito."
echo " Para desplegar el código ejecuta: sudo ./deploy.sh"
echo "=========================================================="
