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
