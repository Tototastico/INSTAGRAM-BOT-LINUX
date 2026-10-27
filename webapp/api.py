import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .coordinator import ACTIVE, Coordinator
from .db import Database, LEGACY_TAGS, profile_path, row, rows


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    profile_arg: str = Field(min_length=1, max_length=240)

    @field_validator('profile_arg')
    @classmethod
    def valid_profile(cls, value):
        profile_path(value)
        return value

    @field_validator('name')
    @classmethod
    def nonempty_name(cls, value):
        if not value.strip():
            raise ValueError('El nombre no puede estar vacio')
        return value


class DrawIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=500)
    notes: str = Field(default='', max_length=2000)

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        parsed = urlparse(value)
        if parsed.scheme != 'https' or parsed.hostname not in ('instagram.com', 'www.instagram.com') or not parsed.path.startswith(('/p/', '/reel/')):
            raise ValueError('Usa una URL HTTPS de publicacion o reel de Instagram')
        return value

    @field_validator('name')
    @classmethod
    def nonempty_name(cls, value):
        if not value.strip():
            raise ValueError('El nombre no puede estar vacio')
        return value


class AssignmentIn(BaseModel):
    account_id: int
    draw_id: int
    duration_minutes: int = Field(ge=1, le=10080)
    comments_per_minute: float = Field(gt=0, le=60)
    tag_count: int = Field(ge=0, le=100)
    extra_text: str = Field(default='', max_length=1000)
    tags: list[str] = Field(default_factory=lambda: LEGACY_TAGS.copy(), min_length=1)

    @field_validator('tags')
    @classmethod
    def valid_tags(cls, value):
        if any(not tag.startswith('@') or ' ' in tag or len(tag) > 32 for tag in value):
            raise ValueError('Cada etiqueta debe empezar con @ y no contener espacios')
        return value


def make_app(db_path=None, legacy_config=None, runner_factory=None):
    db = Database(db_path, legacy_config)
    coordinator = Coordinator(db, runner_factory) if runner_factory else Coordinator(db)

    @asynccontextmanager
    async def lifespan(app):
        yield

    app = FastAPI(title='INSTAGRAM-BOT Local', lifespan=lifespan)
    app.state.db = db
    app.state.coordinator = coordinator

    def require(con, table, item_id):
        found = row(con, f'SELECT * FROM {table} WHERE id=?', (item_id,))
        if not found:
            raise HTTPException(404, 'No encontrado')
        return found

    def check_inactive(con, account_id=None, draw_id=None, assignment_id=None):
        sql = f"SELECT 1 FROM tasks t JOIN assignments s ON s.id=t.assignment_id WHERE t.status IN ({','.join('?' for _ in ACTIVE)})"
        params = list(ACTIVE)
        if account_id is not None:
            sql += ' AND s.account_id=?'
            params.append(account_id)
        if draw_id is not None:
            sql += ' AND s.draw_id=?'
            params.append(draw_id)
        if assignment_id is not None:
            sql += ' AND s.id=?'
            params.append(assignment_id)
        if con.execute(sql, params).fetchone():
            raise HTTPException(409, 'Hay una tarea activa; pausala o cancelala primero')

    @app.get('/api/overview')
    def overview():
        with db.connect() as con:
            return {
                'accounts': con.execute('SELECT COUNT(*) FROM accounts WHERE archived=0').fetchone()[0],
                'draws': con.execute('SELECT COUNT(*) FROM draws WHERE archived=0').fetchone()[0],
                'assignments': con.execute('SELECT COUNT(*) FROM assignments WHERE archived=0').fetchone()[0],
                'active_tasks': con.execute(f"SELECT COUNT(*) FROM tasks WHERE status IN ({','.join('?' for _ in ACTIVE)})", ACTIVE).fetchone()[0],
                'attempts': con.execute('SELECT COALESCE(SUM(attempts),0) FROM tasks').fetchone()[0],
                'clicked': con.execute('SELECT COALESCE(SUM(clicked),0) FROM tasks').fetchone()[0],
                'confirmed': con.execute('SELECT COALESCE(SUM(confirmed),0) FROM tasks').fetchone()[0],
                'failures': con.execute('SELECT COALESCE(SUM(failures),0) FROM tasks').fetchone()[0],
            }

    @app.get('/api/accounts')
    def accounts():
        with db.connect() as con:
            return rows(con, 'SELECT * FROM accounts ORDER BY archived,id')

    @app.post('/api/accounts', status_code=201)
    def add_account(data: AccountIn):
        with db.connect() as con:
            try:
                item_id = con.execute('INSERT INTO accounts(name,profile_arg,profile_path) VALUES(?,?,?)',
                                      (data.name.strip(), data.profile_arg, profile_path(data.profile_arg))).lastrowid
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'Ese perfil ya esta registrado')
            return require(con, 'accounts', item_id)

    @app.put('/api/accounts/{item_id}')
    def edit_account(item_id: int, data: AccountIn):
        with db.connect() as con:
            require(con, 'accounts', item_id)
            check_inactive(con, account_id=item_id)
            try:
                con.execute('UPDATE accounts SET name=?,profile_arg=?,profile_path=? WHERE id=?',
                            (data.name.strip(), data.profile_arg, profile_path(data.profile_arg), item_id))
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'Ese perfil ya esta registrado')
            return require(con, 'accounts', item_id)

    @app.post('/api/accounts/{item_id}/archive')
    def archive_account(item_id: int):
        with db.connect() as con:
            require(con, 'accounts', item_id)
            check_inactive(con, account_id=item_id)
            con.execute('UPDATE accounts SET archived=1 WHERE id=?', (item_id,))
            return require(con, 'accounts', item_id)

    @app.get('/api/draws')
    def draws():
        with db.connect() as con:
            return rows(con, 'SELECT * FROM draws ORDER BY archived,id')

    @app.post('/api/draws', status_code=201)
    def add_draw(data: DrawIn):
        with db.connect() as con:
            item_id = con.execute('INSERT INTO draws(name,url,notes) VALUES(?,?,?)',
                                  (data.name.strip(), data.url, data.notes)).lastrowid
            return require(con, 'draws', item_id)

    @app.put('/api/draws/{item_id}')
    def edit_draw(item_id: int, data: DrawIn):
        with db.connect() as con:
            require(con, 'draws', item_id)
            check_inactive(con, draw_id=item_id)
            con.execute('UPDATE draws SET name=?,url=?,notes=? WHERE id=?',
                        (data.name.strip(), data.url, data.notes, item_id))
            return require(con, 'draws', item_id)

    @app.post('/api/draws/{item_id}/archive')
    def archive_draw(item_id: int):
        with db.connect() as con:
            require(con, 'draws', item_id)
            check_inactive(con, draw_id=item_id)
            con.execute('UPDATE draws SET archived=1 WHERE id=?', (item_id,))
            return require(con, 'draws', item_id)

    @app.get('/api/assignments')
    def assignments():
        with db.connect() as con:
            data = rows(con, '''SELECT s.*,a.name account_name,d.name draw_name,d.url draw_url
                FROM assignments s JOIN accounts a ON a.id=s.account_id
                JOIN draws d ON d.id=s.draw_id ORDER BY s.archived,s.id''')
            for item in data:
                item['tags'] = json.loads(item.pop('tags_json'))
            return data

    @app.post('/api/assignments', status_code=201)
    def add_assignment(data: AssignmentIn):
        with db.connect() as con:
            account = require(con, 'accounts', data.account_id)
            draw = require(con, 'draws', data.draw_id)
            if account['archived'] or draw['archived']:
                raise HTTPException(409, 'Cuenta o sorteo archivado')
            try:
                item_id = con.execute('''INSERT INTO assignments
                    (account_id,draw_id,duration_minutes,comments_per_minute,tag_count,extra_text,tags_json)
                    VALUES(?,?,?,?,?,?,?)''',
                    (data.account_id, data.draw_id, data.duration_minutes, data.comments_per_minute,
                     data.tag_count, data.extra_text, json.dumps(data.tags))).lastrowid
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'Esa cuenta ya esta vinculada al sorteo')
            return {'id': item_id}

    @app.put('/api/assignments/{item_id}')
    def edit_assignment(item_id: int, data: AssignmentIn):
        with db.connect() as con:
            require(con, 'assignments', item_id)
            check_inactive(con, assignment_id=item_id)
            account = require(con, 'accounts', data.account_id)
            draw = require(con, 'draws', data.draw_id)
            if account['archived'] or draw['archived']:
                raise HTTPException(409, 'Cuenta o sorteo archivado')
            try:
                con.execute('''UPDATE assignments SET account_id=?,draw_id=?,duration_minutes=?,
                    comments_per_minute=?,tag_count=?,extra_text=?,tags_json=? WHERE id=?''',
                    (data.account_id, data.draw_id, data.duration_minutes, data.comments_per_minute,
                     data.tag_count, data.extra_text, json.dumps(data.tags), item_id))
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'Esa cuenta ya esta vinculada al sorteo')
            return {'id': item_id}

    @app.post('/api/assignments/{item_id}/archive')
    def archive_assignment(item_id: int):
        with db.connect() as con:
            require(con, 'assignments', item_id)
            check_inactive(con, assignment_id=item_id)
            con.execute('UPDATE assignments SET archived=1 WHERE id=?', (item_id,))
            return {'id': item_id, 'archived': 1}

    @app.get('/api/tasks')
    def tasks():
        with db.connect() as con:
            return rows(con, '''SELECT t.*,a.name account_name,d.name draw_name,d.url draw_url
                FROM tasks t JOIN assignments s ON s.id=t.assignment_id
                JOIN accounts a ON a.id=s.account_id JOIN draws d ON d.id=s.draw_id
                ORDER BY t.id DESC LIMIT 200''')

    @app.post('/api/assignments/{item_id}/start', status_code=201)
    def start(item_id: int):
        try:
            return {'id': coordinator.create(item_id)}
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post('/api/tasks/{task_id}/{action}')
    def control(task_id: int, action: str):
        if action not in ('pause', 'resume', 'cancel'):
            raise HTTPException(404, 'Accion desconocida')
        try:
            coordinator.control(task_id, action)
        except KeyError:
            raise HTTPException(404, 'Tarea inexistente')
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {'id': task_id}

    @app.get('/api/events')
    def events(task_id: int | None = None, limit: int = 100):
        limit = min(max(limit, 1), 500)
        with db.connect() as con:
            if task_id is not None:
                return rows(con, 'SELECT * FROM events WHERE task_id=? ORDER BY id DESC LIMIT ?', (task_id, limit))
            return rows(con, 'SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,))

    dist = Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
    if dist.exists():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

        @app.get('/')
        def index():
            return FileResponse(dist / 'index.html')

    return app


app = make_app()
