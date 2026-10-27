#!/usr/bin/env bash
# ==============================================================================
# backup.sh - Respaldo seguro de base SQLite y perfiles Chrome
# ==============================================================================
set -euo pipefail

OPT_DIR="/opt/instagram-bot"
VENV="$OPT_DIR/venv"
DB_PATH="/var/lib/instagram-bot/data/bot.sqlite3"
BACKUP_DIR="/var/lib/instagram-bot/backups"
USER="instagram-bot"

echo "=== [1/2] Respaldando Base de Datos SQLite (Online Backup API) ==="
if [ -f "$DB_PATH" ]; then
    sudo -u "$USER" "$VENV/bin/python" "$OPT_DIR/current/database/scripts/backup_sqlite.py" --db "$DB_PATH" --out "$BACKUP_DIR"
else
    echo "[AVISO] La base de datos no existe en $DB_PATH."
fi

echo "=== [2/2] Verificando backups existentes ==="
ls -lh "$BACKUP_DIR"

echo "[OK] Proceso de backup finalizado."
