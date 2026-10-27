import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .paths import get_accounts_dir, get_db_path, resolve_profile_path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS_ROOT = get_accounts_dir()
LEGACY_PROFILE_ROOT = ACCOUNTS_ROOT
LEGACY_TAGS = [
    '@camifernandl', '@karinasilvetti1', '@camisuliii', '@soyteoo',
    '@tobi.sirne', '@nailsconkary', '@camiiiythiago',
]


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def profile_path(profile_arg):
    return resolve_profile_path(profile_arg, get_accounts_dir())


class Database:
    def __init__(self, path=None, legacy_config=None, initialize=True):
        self.path = Path(path or get_db_path())
        self.legacy_config = Path(legacy_config or ROOT / 'config.json')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if initialize:
            self.initialize()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys = ON')
        con.execute('PRAGMA busy_timeout = 30000')
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def initialize(self):
        with self.connect() as con:
            con.executescript('''
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, profile_arg TEXT NOT NULL,
                    profile_path TEXT NOT NULL UNIQUE, archived INTEGER NOT NULL DEFAULT 0,
                    attention_required INTEGER NOT NULL DEFAULT 0,
                    attention_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS draws (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS assignments (
                    id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
                    draw_id INTEGER NOT NULL REFERENCES draws(id),
                    duration_minutes INTEGER NOT NULL, comments_per_minute REAL NOT NULL,
                    tag_count INTEGER NOT NULL, extra_text TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(account_id, draw_id)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY, assignment_id INTEGER NOT NULL REFERENCES assignments(id),
                    status TEXT NOT NULL, elapsed_seconds REAL NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, clicked INTEGER NOT NULL DEFAULT 0,
                    confirmed INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
                    kind TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, id DESC);
            ''')
            columns = {item['name'] for item in con.execute('PRAGMA table_info(accounts)')}
            if 'attention_required' not in columns:
                con.execute('ALTER TABLE accounts ADD COLUMN attention_required INTEGER NOT NULL DEFAULT 0')
            if 'attention_reason' not in columns:
                con.execute('ALTER TABLE accounts ADD COLUMN attention_reason TEXT')
            self._import_legacy(con)

    def recover_interrupted(self):
        with self.connect() as con:
            con.execute("UPDATE tasks SET status='interrupted', updated_at=? WHERE status IN ('running', 'queued', 'pausing', 'cancelling')", (now(),))
            for row in con.execute("SELECT id FROM tasks WHERE status='interrupted' AND id NOT IN (SELECT task_id FROM events WHERE kind='interrupted')"):
                con.execute('INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)',
                            (row['id'], 'interrupted', 'Ejecucion interrumpida; requiere reanudacion manual', now()))

    def _import_legacy(self, con):
        if con.execute("SELECT 1 FROM meta WHERE key='legacy_imported'").fetchone():
            return
        if self.legacy_config.exists():
            cfg = json.loads(self.legacy_config.read_text(encoding='utf-8'))
            profiles = cfg.get('perfil_chrome', [])
            if isinstance(profiles, str):
                profiles = [profiles]
            url = cfg.get('url_post', '').strip()
            if url and profiles:
                draw_id = con.execute('INSERT INTO draws(name,url,notes) VALUES(?,?,?)',
                                      ('Sorteo importado', url, 'Importado desde config.json')).lastrowid
                for arg in profiles:
                    resolved = profile_path(arg)
                    account_id = con.execute('INSERT OR IGNORE INTO accounts(name,profile_arg,profile_path) VALUES(?,?,?)',
                                             (Path(arg).name, arg, resolved)).lastrowid
                    if not account_id:
                        account_id = con.execute('SELECT id FROM accounts WHERE profile_path=?', (resolved,)).fetchone()['id']
                    con.execute('''INSERT OR IGNORE INTO assignments
                        (account_id,draw_id,duration_minutes,comments_per_minute,tag_count,extra_text,tags_json)
                        VALUES(?,?,?,?,?,?,?)''',
                        (account_id, draw_id, int(cfg.get('exe_time', 60)), float(cfg.get('comentarios_min', 1)),
                         int(cfg.get('etiquetas', 1)), cfg.get('comentario', ''), json.dumps(LEGACY_TAGS)))
        con.execute("INSERT INTO meta(key,value) VALUES('legacy_imported',?)", (now(),))


def rows(con, sql, params=()):
    return [dict(row) for row in con.execute(sql, params)]


def row(con, sql, params=()):
    found = con.execute(sql, params).fetchone()
    return dict(found) if found else None
