"""Create a consistent SQLite backup outside the release directory."""
import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from webapp.settings import db_path, ensure_private_dir

parser = argparse.ArgumentParser()
parser.add_argument('destination', type=Path, help='Directory for the backup')
args = parser.parse_args()
destination = ensure_private_dir(args.destination.expanduser().resolve())
target = destination / f'bot-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.sqlite3'
with sqlite3.connect(db_path()) as source, sqlite3.connect(target) as backup:
    source.backup(backup)
target.chmod(0o600)
print(target)
