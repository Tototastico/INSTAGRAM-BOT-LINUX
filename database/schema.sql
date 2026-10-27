-- =====================================================================
-- Esquema real de SQLite para INSTAGRAM-BOT
-- Compatible con Windows y Linux
-- =====================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- 1. Tabla de metadatos del sistema
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 2. Cuentas de Instagram y rutas de perfiles de Chrome
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    profile_arg TEXT NOT NULL,
    profile_path TEXT NOT NULL UNIQUE,
    archived INTEGER NOT NULL DEFAULT 0,
    attention_required INTEGER NOT NULL DEFAULT 0,
    attention_reason TEXT
);

-- 3. Publicaciones / Sorteos de Instagram
CREATE TABLE IF NOT EXISTS draws (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0
);

-- 4. Asignaciones de cuenta a sorteo con reglas de comentarios
CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    draw_id INTEGER NOT NULL REFERENCES draws(id),
    duration_minutes INTEGER NOT NULL,
    comments_per_minute REAL NOT NULL,
    tag_count INTEGER NOT NULL,
    extra_text TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    UNIQUE(account_id, draw_id)
);

-- 5. Tareas de ejecución del coordinador
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id),
    status TEXT NOT NULL,
    elapsed_seconds REAL NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    clicked INTEGER NOT NULL DEFAULT 0,
    confirmed INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 6. Registro de eventos cronológicos de cada tarea
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Índices de consulta frecuente
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, id DESC);
