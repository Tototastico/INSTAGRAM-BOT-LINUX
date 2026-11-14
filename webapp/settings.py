"""Runtime paths and limits for the Linux service."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def data_dir():
    return Path(os.environ.get('BOT_DATA_DIR', ROOT / 'data')).expanduser().resolve()


def accounts_dir():
    return Path(os.environ.get('BOT_ACCOUNTS_DIR', os.environ.get('INSTAGRAM_ACCOUNTS_DIR', data_dir() / 'accounts'))).expanduser().resolve()


def db_path():
    return Path(os.environ.get('BOT_DB_PATH', data_dir() / 'bot.sqlite3')).expanduser().resolve()


def ensure_private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'posix':
        path.chmod(0o700)
    return path


def max_browsers():
    value = int(os.environ.get('MAX_CONCURRENT_BROWSERS', '1'))
    if value < 1:
        raise ValueError('MAX_CONCURRENT_BROWSERS debe ser positivo')
    return value


def headless():
    return os.environ.get('HEADLESS', 'true').lower() in ('1', 'true', 'yes', 'on')


def debug_dir():
    return Path(os.environ.get('BOT_DEBUG_DIR', data_dir() / 'debug')).expanduser().resolve()


def diagnostic_retention_days():
    return max(1, int(os.environ.get('BOT_DEBUG_RETENTION_DAYS', '7')))


def validate_visual_environment(platform_name=None, environ=None):
    """Fail before Chrome starts if a visible Linux session cannot use Xvfb."""
    platform_name = platform_name or os.name
    environ = environ if environ is not None else os.environ
    if platform_name != 'posix':
        return
    if not environ.get('DISPLAY'):
        raise RuntimeError('HEADLESS=false requiere DISPLAY (por ejemplo :99)')
    authority = environ.get('XAUTHORITY')
    if not authority or not Path(authority).is_file() or not os.access(authority, os.R_OK):
        raise RuntimeError('HEADLESS=false requiere un XAUTHORITY legible por el usuario del servicio')
