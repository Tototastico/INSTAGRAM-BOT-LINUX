"""Open a disposable Selenium Chrome window on Xvfb without visiting Instagram."""
import os
import subprocess
import tempfile
import time
from pathlib import Path

from selenium_runner import crear_driver
from webapp.settings import debug_dir, ensure_private_dir, validate_visual_environment

if os.environ.get('HEADLESS', '').lower() not in ('false', '0', 'no', 'off'):
    raise SystemExit('Ejecuta esta prueba con HEADLESS=false')
validate_visual_environment()
if not __import__('shutil').which('xdotool'):
    raise SystemExit('Instala xdotool para comprobar la ventana visible en Xvfb')

root = ensure_private_dir(debug_dir())
with tempfile.TemporaryDirectory(prefix='visual-smoke-', dir=root) as temporary:
    os.environ['BOT_ACCOUNTS_DIR'] = str(Path(temporary) / 'profiles')
    driver = None
    try:
        driver = crear_driver('prueba-descartable')
        driver.get('data:text/html,<title>Prueba visual Selenium</title><h1>Chrome controlado por Selenium</h1>')
        time.sleep(2)
        result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--class',
                                 'google-chrome|Google-chrome|chromium|Chromium'],
                                capture_output=True, text=True, timeout=10)
        if result.returncode or not result.stdout.strip():
            raise RuntimeError('Chrome arranco, pero no hay una ventana visible en DISPLAY')
        print(f'Chrome visible en DISPLAY={os.environ["DISPLAY"]}; ventanas X11: {result.stdout.strip()}')
        print('Verifica la pantalla en tu VNC privado durante los proximos 30 segundos.')
        time.sleep(30)
    finally:
        if driver is not None:
            driver.quit()
