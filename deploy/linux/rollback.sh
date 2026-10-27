#!/usr/bin/env bash
# ==============================================================================
# rollback.sh - Revertir al release anterior de forma instantánea y segura
# ==============================================================================
set -euo pipefail

OPT_DIR="/opt/instagram-bot"
RELEASES_DIR="$OPT_DIR/releases"
CURRENT_LINK="$OPT_DIR/current"

echo "=== Verificando releases disponibles ==="
RELEASES=($(ls -1d "$RELEASES_DIR"/* 2>/dev/null | sort -r))
COUNT=${#RELEASES[@]}

if [ "$COUNT" -lt 2 ]; then
    echo "[ERROR] No hay release previo para realizar rollback (Total releases: $COUNT)." >&2
    exit 1
fi

CURRENT_TARGET=$(readlink -f "$CURRENT_LINK" || true)
PREVIOUS_RELEASE=""

for r in "${RELEASES[@]}"; do
    if [ "$r" != "$CURRENT_TARGET" ]; then
        PREVIOUS_RELEASE="$r"
        break
    fi
done

if [ -z "$PREVIOUS_RELEASE" ] || [ ! -d "$PREVIOUS_RELEASE" ]; then
    echo "[ERROR] No se pudo determinar el release anterior." >&2
    exit 1
fi

echo "[*] Release actual:   $CURRENT_TARGET"
echo "[*] Rollback hacia:   $PREVIOUS_RELEASE"

echo "[*] Deteniendo servicio..."
systemctl stop instagram-bot.service

echo "[*] Cambiando symlink a release anterior..."
ln -sfn "$PREVIOUS_RELEASE" "$CURRENT_LINK"

echo "[*] Reiniciando servicios..."
systemctl restart instagram-bot-display.service
systemctl restart instagram-bot.service

sleep 2
"$(dirname "${BASH_SOURCE[0]}")/healthcheck.sh"

echo "[OK] Rollback completado exitosamente a: $(basename "$PREVIOUS_RELEASE")"
