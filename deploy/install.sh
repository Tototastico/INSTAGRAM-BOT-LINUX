#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-server.txt
(cd frontend && npm ci && npm run build)
echo 'Chrome:'
"${CHROME_BINARY:-$(command -v google-chrome-stable || command -v chromium)}" --version
if command -v chromedriver >/dev/null 2>&1; then chromedriver --version; else echo 'ChromeDriver se resolvera al abrir Chrome con undetected-chromedriver'; fi
echo 'Instalacion lista. Configure .env fuera del repositorio e inicie el servicio.'
