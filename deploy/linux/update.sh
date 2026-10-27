#!/usr/bin/env bash
# ==============================================================================
# update.sh - Actualización controlada sin pérdida de tareas ni datos
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPT_DIR="/opt/instagram-bot"
VENV="$OPT_DIR/venv"
DB_PATH="/var/lib/instagram-bot/data/bot.sqlite3"
BACKUP_DIR="/var/lib/instagram-bot/backups"
USER="instagram-bot"

echo "=== [1/4] Resguardando base de datos activa antes de la actualización ==="
if [ -f "$DB_PATH" ]; then
    echo "[*] Generando backup consistente..."
    sudo -u "$USER" "$VENV/bin/python" "$OPT_DIR/current/database/scripts/backup_sqlite.py" --db "$DB_PATH" --out "$BACKUP_DIR"
fi

echo "=== [2/4] Deteniendo servicio ordenadamente (drenando tareas activas) ==="
systemctl stop instagram-bot.service

echo "=== [3/4] Ejecutando deploy del nuevo código ==="
"$SCRIPT_DIR/deploy.sh"

echo "=== [4/4] Comprobando salud del sistema ==="
"$SCRIPT_DIR/healthcheck.sh"

echo "[OK] Actualización completada correctamente."
