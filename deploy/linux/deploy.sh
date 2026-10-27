#!/usr/bin/env bash
# ==============================================================================
# deploy.sh - Despliegue atómico con versionado y build del frontend
# Debe ejecutarse como root o sudo
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

USER="instagram-bot"
GROUP="instagram-bot"
OPT_DIR="/opt/instagram-bot"
RELEASES_DIR="$OPT_DIR/releases"
VENV="$OPT_DIR/venv"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
RELEASE_DIR="$RELEASES_DIR/$TIMESTAMP"

echo "=== [1/6] Verificando entorno y permisos ==="
if [ ! -d "$VENV" ]; then
    echo "[ERROR] El entorno virtual $VENV no existe. Ejecuta primero install.sh." >&2
    exit 1
fi

echo "=== [2/6] Copiando código al nuevo release: $RELEASE_DIR ==="
mkdir -p "$RELEASE_DIR"
# Copiar el código excluyendo perfiles, venvs y bases de datos locales
tar --exclude='.git' \
    --exclude='accounts' \
    --exclude='data/*.sqlite3*' \
    --exclude='*.sqlite3*' \
    --exclude='node_modules' \
    --exclude='venv' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    -cf - -C "$REPO_ROOT" . | tar -xf - -C "$RELEASE_DIR"

chown -R "$USER":"$GROUP" "$RELEASE_DIR"

echo "=== [3/6] Instalando dependencias de servidor Python ==="
sudo -u "$USER" "$VENV/bin/pip" install --no-cache-dir -r "$RELEASE_DIR/requirements-server.txt"

echo "=== [4/6] Compilando frontend (Vite / React) ==="
if [ -d "$RELEASE_DIR/frontend" ]; then
    cd "$RELEASE_DIR/frontend"
    sudo -u "$USER" npm ci
    sudo -u "$USER" npm run build
    cd "$RELEASE_DIR"
fi

echo "=== [5/6] Verificando o inicializando base de datos persistente ==="
DB_PATH="/var/lib/instagram-bot/data/bot.sqlite3"
if [ ! -f "$DB_PATH" ]; then
    echo "[*] Base de datos no encontrada. Inicializando nueva en: $DB_PATH"
    sudo -u "$USER" "$VENV/bin/python" "$RELEASE_DIR/database/scripts/init_database.py" --db "$DB_PATH"
else
    echo "[*] Base de datos persistente detectada. Validando integridad..."
    sudo -u "$USER" "$VENV/bin/python" "$RELEASE_DIR/database/scripts/validate_database.py" --db "$DB_PATH"
fi

echo "=== [6/6] Activando nuevo release mediante symlink atómico ==="
ln -sfn "$RELEASE_DIR" "$OPT_DIR/current"

echo "[*] Reiniciando servicios systemd..."
systemctl restart instagram-bot-display.service
systemctl restart instagram-bot.service

sleep 2
"$SCRIPT_DIR/healthcheck.sh"

echo "=========================================================="
echo " [OK] Despliegue completado exitosamente: release $TIMESTAMP"
echo "=========================================================="
