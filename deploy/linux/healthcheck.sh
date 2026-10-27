#!/usr/bin/env bash
# ==============================================================================
# healthcheck.sh - Verificación integral del estado del sistema en Ubuntu VPS
# ==============================================================================
set -euo pipefail

EXIT_CODE=0

echo "=== REPORTE DE SALUD DEL SISTEMA (HEALTHCHECK) ==="

# 1. Comprobar servicios systemd
echo -n "[*] Comprobando instagram-bot-display.service: "
if systemctl is-active --quiet instagram-bot-display.service; then
    echo "ACTIVO (OK)"
else
    echo "INACTIVO / FALLIDO"
    EXIT_CODE=1
fi

echo -n "[*] Comprobando instagram-bot.service: "
if systemctl is-active --quiet instagram-bot.service; then
    echo "ACTIVO (OK)"
else
    echo "INACTIVO / FALLIDO"
    EXIT_CODE=1
fi

# 2. Comprobar Xvfb display :99
echo -n "[*] Comprobando display virtual :99: "
if DISPLAY=:99 xdpyinfo >/dev/null 2>&1; then
    echo "DISPONIBLE (OK)"
else
    echo "NO RESPONDE O FALLA Xvfb"
    EXIT_CODE=1
fi

# 3. Comprobar API local en 127.0.0.1:8000
echo -n "[*] Comprobando API local (127.0.0.1:8000/api/overview): "
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/overview || true)
if [ "$HTTP_STATUS" = "200" ]; then
    echo "HTTP 200 (OK)"
else
    echo "ERROR HTTP $HTTP_STATUS"
    EXIT_CODE=1
fi

# 4. Comprobar binario de Google Chrome
echo -n "[*] Comprobando Google Chrome: "
if command -v google-chrome-stable >/dev/null 2>&1; then
    echo "$(google-chrome-stable --version) (OK)"
else
    echo "NO ENCONTRADO"
    EXIT_CODE=1
fi

# 5. Comprobar integridad de SQLite
DB_PATH="/var/lib/instagram-bot/data/bot.sqlite3"
echo -n "[*] Comprobando base de datos SQLite ($DB_PATH): "
if [ -f "$DB_PATH" ]; then
    INTEGRITY=$(sqlite3 "$DB_PATH" "PRAGMA integrity_check;" 2>/dev/null || echo "FAILED")
    if [ "$INTEGRITY" = "ok" ]; then
        echo "INTEGRITY OK"
    else
        echo "CORRUPCIÓN O ERROR ($INTEGRITY)"
        EXIT_CODE=1
    fi
else
    echo "NO EXISTE"
fi

echo "--------------------------------------------------"
if [ "$EXIT_CODE" -eq 0 ]; then
    echo "[OK] Todos los componentes están funcionando correctamente."
else
    echo "[ERROR] Se detectaron fallos en uno o más componentes."
fi

exit "$EXIT_CODE"
