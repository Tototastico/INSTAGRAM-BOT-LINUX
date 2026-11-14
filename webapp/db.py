import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from .settings import accounts_dir, db_path, ensure_private_dir


ROOT = Path(__file__).resolve().parents[1]

ACCOUNTS_ROOT = accounts_dir()
LEGACY_PROFILE_ROOT = ACCOUNTS_ROOT
LEGACY_TAGS = [
    '@camifernandl', '@karinasilvetti1', '@camisuliii', '@soyteoo',
    '@tobi.sirne', '@nailsconkary', '@camiiiythiago',
]


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def profile_path(profile_arg):
    path = Path(profile_arg.replace("\\", "/"))

    if path.is_absolute() or PureWindowsPath(profile_arg).is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Ruta de perfil inválida")

    parts = list(path.parts)

    if parts[0].lower() == "accounts":
        parts = parts[1:]

    if len(parts) != 1 or parts[0] in ("", "."):
        raise ValueError("Usá un nombre de perfil, por ejemplo cuenta1")

    return str((accounts_dir() / parts[0]).resolve())


class Database:
    def __init__(self, path=None, legacy_config=None, initialize=True):
        self.path = Path(path) if path is not None else db_path()
        # Import of a legacy Windows config requires an explicit path.
        self.legacy_config = Path(legacy_config) if legacy_config is not None else None
        ensure_private_dir(self.path.parent)
        if initialize:
            self.initialize()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        if os.name == 'posix':
            self.path.chmod(0o600)
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
                    notes TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0,
                    end_date TEXT, end_time TEXT, tag_count INTEGER NOT NULL DEFAULT 1,
                    comment_count INTEGER, comment_count_checked_at TEXT
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
                    account_id INTEGER REFERENCES accounts(id),
                    draw_id INTEGER REFERENCES draws(id),
                    status TEXT NOT NULL, elapsed_seconds REAL NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, clicked INTEGER NOT NULL DEFAULT 0,
                    confirmed INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
                    kind TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tag_library (
                    tag TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_runtime_state (
                    task_id INTEGER PRIMARY KEY REFERENCES tasks(id),
                    stage TEXT NOT NULL, stage_at TEXT NOT NULL,
                    last_progress_at TEXT
                );
                CREATE TABLE IF NOT EXISTS task_diagnostics (
                    id TEXT PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
                    account_id INTEGER NOT NULL REFERENCES accounts(id),
                    created_at TEXT NOT NULL, stage TEXT NOT NULL,
                    error_type TEXT NOT NULL, category TEXT NOT NULL,
                    summary TEXT NOT NULL, page_url TEXT NOT NULL,
                    page_title TEXT NOT NULL, ready_state TEXT NOT NULL,
                    browser_responding INTEGER NOT NULL,
                    selector TEXT NOT NULL, matching_elements INTEGER,
                    visible_elements INTEGER, dialog_count INTEGER,
                    screenshot_file TEXT, operation TEXT NOT NULL DEFAULT '',
                    condition TEXT NOT NULL DEFAULT '', error_message TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_diagnostics_task ON task_diagnostics(task_id, created_at DESC);
            ''')
            diagnostic_columns = {item['name'] for item in con.execute('PRAGMA table_info(task_diagnostics)')}
            for name in ('operation', 'condition', 'error_message'):
                if name not in diagnostic_columns:
                    con.execute(f"ALTER TABLE task_diagnostics ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            columns = {item['name'] for item in con.execute('PRAGMA table_info(accounts)')}
            if 'attention_required' not in columns:
                con.execute('ALTER TABLE accounts ADD COLUMN attention_required INTEGER NOT NULL DEFAULT 0')
            if 'attention_reason' not in columns:
                con.execute('ALTER TABLE accounts ADD COLUMN attention_reason TEXT')
            draw_columns = {item['name'] for item in con.execute('PRAGMA table_info(draws)')}
            if 'end_date' not in draw_columns:
                con.execute('ALTER TABLE draws ADD COLUMN end_date TEXT')
            if 'end_time' not in draw_columns:
                con.execute('ALTER TABLE draws ADD COLUMN end_time TEXT')
            if 'comment_count' not in draw_columns:
                con.execute('ALTER TABLE draws ADD COLUMN comment_count INTEGER')
            if 'comment_count_checked_at' not in draw_columns:
                con.execute('ALTER TABLE draws ADD COLUMN comment_count_checked_at TEXT')
            if 'tag_count' not in draw_columns:
                con.execute('ALTER TABLE draws ADD COLUMN tag_count INTEGER NOT NULL DEFAULT 1')
                con.execute('''UPDATE draws SET tag_count=COALESCE(
                    (SELECT s.tag_count FROM assignments s WHERE s.draw_id=draws.id ORDER BY s.id LIMIT 1), 1)''')
            task_columns = {item['name'] for item in con.execute('PRAGMA table_info(tasks)')}
            if 'account_id' not in task_columns:
                con.execute('ALTER TABLE tasks ADD COLUMN account_id INTEGER REFERENCES accounts(id)')
            if 'draw_id' not in task_columns:
                con.execute('ALTER TABLE tasks ADD COLUMN draw_id INTEGER REFERENCES draws(id)')
            con.execute('''UPDATE tasks SET
                account_id=COALESCE(account_id,(SELECT account_id FROM assignments WHERE id=tasks.assignment_id)),
                draw_id=COALESCE(draw_id,(SELECT draw_id FROM assignments WHERE id=tasks.assignment_id))
                WHERE account_id IS NULL OR draw_id IS NULL''')
            con.execute('''CREATE TRIGGER IF NOT EXISTS snapshot_task_assignment
                AFTER INSERT ON tasks
                WHEN NEW.account_id IS NULL OR NEW.draw_id IS NULL
                BEGIN
                    UPDATE tasks SET
                        account_id=COALESCE(NEW.account_id,(SELECT account_id FROM assignments WHERE id=NEW.assignment_id)),
                        draw_id=COALESCE(NEW.draw_id,(SELECT draw_id FROM assignments WHERE id=NEW.assignment_id))
                    WHERE id=NEW.id;
                END''')
            con.execute('CREATE INDEX IF NOT EXISTS idx_tasks_draw_id ON tasks(draw_id)')
            self._import_legacy(con)
            con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('reminder_days_before','1')")
            con.execute("""INSERT OR IGNORE INTO settings(key,value)
                SELECT 'reminder_hours_before', CASE value WHEN '0' THEN '6' ELSE '24' END
                FROM settings WHERE key='reminder_days_before'""")
            for assignment in con.execute('SELECT tags_json FROM assignments'):
                try:
                    tags = json.loads(assignment['tags_json'])
                except (ValueError, TypeError):
                    continue
                for tag in tags:
                    if isinstance(tag, str) and tag.startswith('@'):
                        con.execute('INSERT OR IGNORE INTO tag_library(tag) VALUES(?)', (tag,))

    def recover_interrupted(self):
        with self.connect() as con:
            con.execute("UPDATE tasks SET status='interrupted', updated_at=? WHERE status IN ('running', 'queued', 'pausing', 'cancelling')", (now(),))
            for row in con.execute("SELECT id FROM tasks WHERE status='interrupted' AND id NOT IN (SELECT task_id FROM events WHERE kind='interrupted')"):
                con.execute('INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)',
                            (row['id'], 'interrupted', 'Ejecucion interrumpida; requiere reanudacion manual', now()))

    def _import_legacy(self, con):
        if con.execute("SELECT 1 FROM meta WHERE key='legacy_imported'").fetchone():
            return
        if self.legacy_config is not None and self.legacy_config.exists():
            cfg = json.loads(self.legacy_config.read_text(encoding='utf-8'))
            profiles = cfg.get('perfil_chrome', [])
            if isinstance(profiles, str):
                profiles = [profiles]
            url = cfg.get('url_post', '').strip()
            if url and profiles:
                draw_id = con.execute('INSERT INTO draws(name,url,notes,tag_count) VALUES(?,?,?,?)',
                                      ('Sorteo importado', url, 'Importado desde config.json',
                                       int(cfg.get('etiquetas', 1)))).lastrowid
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
