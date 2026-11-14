"""Find Chrome or Chromium and read its major version."""
import os
import re
import shutil
import subprocess
from pathlib import Path


def chrome_binary_and_major():
    override = os.environ.get('CHROME_BINARY') or os.environ.get('INSTAGRAM_BOT_CHROME_BINARY')
    candidate = override or next((shutil.which(name) for name in
        ('google-chrome-stable', 'google-chrome', 'chromium', 'chromium-browser')
        if shutil.which(name)), None)
    if not candidate or not Path(candidate).is_file():
        raise RuntimeError('No se encontro Chrome/Chromium. Define CHROME_BINARY con su ruta completa.')
    executable = str(Path(candidate).resolve())
    result = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=10, check=True)
    match = re.search(r'\b(?:Chrome|Chromium)\s+(\d+)\.', result.stdout + result.stderr, re.I)
    if not match:
        raise RuntimeError(f'No se pudo leer la version de Chrome/Chromium: {executable}')
    return executable, int(match.group(1))
