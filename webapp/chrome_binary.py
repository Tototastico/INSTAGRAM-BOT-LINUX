import ctypes
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import undetected_chromedriver as uc


class _FileVersionInfo(ctypes.Structure):
    _fields_ = [
        ('signature', ctypes.c_uint32), ('structure_version', ctypes.c_uint32),
        ('file_version_ms', ctypes.c_uint32), ('file_version_ls', ctypes.c_uint32),
        ('product_version_ms', ctypes.c_uint32), ('product_version_ls', ctypes.c_uint32),
        ('file_flags_mask', ctypes.c_uint32), ('file_flags', ctypes.c_uint32),
        ('file_os', ctypes.c_uint32), ('file_type', ctypes.c_uint32),
        ('file_subtype', ctypes.c_uint32), ('file_date_ms', ctypes.c_uint32),
        ('file_date_ls', ctypes.c_uint32),
    ]


def _chrome_version_windows(executable: str) -> int:
    version_api = ctypes.WinDLL('version', use_last_error=True)
    version_api.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
    version_api.GetFileVersionInfoSizeW.restype = ctypes.c_uint32
    version_api.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    version_api.GetFileVersionInfoW.restype = ctypes.c_int
    version_api.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)]
    version_api.VerQueryValueW.restype = ctypes.c_int

    size = version_api.GetFileVersionInfoSizeW(executable, None)
    if not size:
        raise RuntimeError(f'No se pudo leer la version de Chrome: {executable}')
    buffer = ctypes.create_string_buffer(size)
    if not version_api.GetFileVersionInfoW(executable, 0, size, buffer):
        raise RuntimeError(f'No se pudo leer la version de Chrome: {executable}')
    pointer = ctypes.c_void_p()
    length = ctypes.c_uint32()
    if not version_api.VerQueryValueW(buffer, '\\', ctypes.byref(pointer), ctypes.byref(length)) or length.value < ctypes.sizeof(_FileVersionInfo):
        raise RuntimeError(f'No se pudo interpretar la version de Chrome: {executable}')
    info = ctypes.cast(pointer, ctypes.POINTER(_FileVersionInfo)).contents
    if info.signature != 0xFEEF04BD:
        raise RuntimeError(f'Version de ejecutable invalida: {executable}')
    major = info.file_version_ms >> 16
    if major <= 0:
        raise RuntimeError(f'Version principal de Chrome invalida: {executable}')
    return major


def _chrome_version_linux(executable: str) -> int:
    try:
        proc = subprocess.run(
            [executable, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=10,
        )
        output = proc.stdout.strip() or proc.stderr.strip()
    except Exception as exc:
        raise RuntimeError(f'No se pudo ejecutar {executable} --version: {exc}')

    match = re.search(r'(\d+)\.\d+\.\d+\.\d+', output)
    if not match:
        raise RuntimeError(f'No se pudo extraer la versión de Chrome desde la salida: {output}')
    return int(match.group(1))


def find_linux_chrome() -> str | None:
    # Búsqueda en rutas conocidas de Ubuntu / Debian
    candidates = [
        os.environ.get('INSTAGRAM_BOT_CHROME_BINARY'),
        shutil.which('google-chrome-stable'),
        shutil.which('google-chrome'),
        shutil.which('chromium-browser'),
        shutil.which('chromium'),
        '/usr/bin/google-chrome-stable',
        '/usr/bin/google-chrome',
        '/usr/bin/chromium-browser',
        '/usr/bin/chromium',
    ]
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(Path(c).resolve())
    return None


def chrome_binary_and_major():
    override = os.environ.get('INSTAGRAM_BOT_CHROME_BINARY')
    candidate = None

    if override:
        if not Path(override).is_file():
            raise RuntimeError(f'El ejecutable configurado en INSTAGRAM_BOT_CHROME_BINARY no existe: {override}')
        candidate = override
    elif sys.platform == 'win32':
        candidate = uc.find_chrome_executable()
    else:
        candidate = find_linux_chrome() or uc.find_chrome_executable()

    if not candidate or not Path(candidate).is_file():
        raise RuntimeError('No se encontro chrome. Define INSTAGRAM_BOT_CHROME_BINARY con su ruta completa.')

    executable = str(Path(candidate).resolve())

    if sys.platform == 'win32':
        major = _chrome_version_windows(executable)
    else:
        major = _chrome_version_linux(executable)

    return executable, major
