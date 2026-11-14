import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager, suppress
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from .coordinator import ACTIVE, Coordinator
from .db import Database, now, profile_path, row, rows
from .visual_auth import COOKIE, VisualAuth
from .visual_sessions import VisualSessionError, VisualSessions
from .settings import ensure_private_dir


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


class VisualLoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=500)


class DrawIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=500)
    notes: str = Field(default='', max_length=2000)
    end_date: date | None = None
    end_time: str | None = Field(default=None, pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    tag_count: int = Field(default=1, ge=0, le=100)

    @model_validator(mode='after')
    def time_needs_date(self):
        if self.end_time and not self.end_date:
            raise ValueError('La hora requiere una fecha de finalizacion')
        return self

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
    duration_minutes: int = Field(ge=0, le=10080)
    comments_per_minute: float = Field(gt=0, le=60)
    extra_text: str = Field(default='', max_length=1000)
    tags: list[str] = Field(min_length=1)

    @field_validator('tags')
    @classmethod
    def valid_tags(cls, value):
        if any(not tag.startswith('@') or any(char.isspace() for char in tag) or len(tag) > 32 for tag in value):
            raise ValueError('Cada etiqueta debe empezar con @ y no contener espacios')
        return list(dict.fromkeys(value))


class TagsIn(BaseModel):
    tags: list[str] = Field(min_length=1)

    @field_validator('tags')
    @classmethod
    def valid_tags(cls, value):
        return AssignmentIn.valid_tags(value)


class SettingsIn(BaseModel):
    reminder_hours_before: int | None = Field(default=None, ge=1, le=168)
    reminder_days_before: int | None = Field(default=None, ge=0, le=1)
    browser_limit: str | None = None

    @field_validator('browser_limit')
    @classmethod
    def valid_browser_limit(cls, value):
        if value is not None and value not in ('1', '2', '3', '4', 'auto'):
            raise ValueError('Selecciona 1, 2, 3, 4 o automatico')
        return value

    @model_validator(mode='after')
    def has_reminder(self):
        if self.reminder_hours_before is None and self.reminder_days_before is None and self.browser_limit is None:
            raise ValueError('Indica una configuracion')
        return self


class HistoryCorrectionIn(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=200)
    draw_id: int

    @field_validator('task_ids')
    @classmethod
    def valid_task_ids(cls, value):
        if any(task_id < 1 for task_id in value) or len(set(value)) != len(value):
            raise ValueError('Indica IDs de tareas positivos y sin duplicados')
        return value


def make_app(db_path=None, legacy_config=None, runner_factory=None, visual_factory=None):
    db = Database(db_path, legacy_config, initialize=False)
    coordinator = Coordinator(db, runner_factory) if runner_factory else Coordinator(db)
    visual = visual_factory(db, coordinator) if visual_factory else VisualSessions(db, coordinator)
    visual_auth = VisualAuth()

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        db.recover_interrupted()
        coordinator.diagnostics.prune()
        visual.recover_orphans()

        async def prune_diagnostics():
            while True:
                await asyncio.sleep(3600)
                await asyncio.to_thread(coordinator.diagnostics.prune)

        async def prune_visual():
            while True:
                await asyncio.sleep(15)
                await asyncio.to_thread(visual.prune)
                await asyncio.to_thread(coordinator.dispatch)

        cleanup = [asyncio.create_task(prune_diagnostics()), asyncio.create_task(prune_visual())]
        try:
            yield
        finally:
            for task in cleanup:
                task.cancel()
            for task in cleanup:
                with suppress(asyncio.CancelledError):
                    await task
            try:
                visual.close_all()
            finally:
                coordinator.shutdown()

    app = FastAPI(title='INSTAGRAM-BOT Local', lifespan=lifespan)
    app.state.db = db
    app.state.coordinator = coordinator
    app.state.visual = visual
    app.state.visual_auth = visual_auth

    def visual_required(request: Request, mutate=False):
        if not visual_auth.enabled():
            raise HTTPException(503, 'Configura BOT_PUBLIC_ORIGIN y BOT_VISUAL_ADMIN_PASSWORD_HASH')
        session_id = request.cookies.get(COOKIE)
        csrf = request.headers.get('x-visual-csrf') if mutate else None
        if (mutate and (not csrf or not visual_auth.origin_ok(request.headers.get('origin')))) or not visual_auth.check(session_id, csrf, renew=True):
            raise HTTPException(401 if not session_id else 403, 'Acceso visual no autorizado')

    @app.get('/api/visual/auth')
    def visual_auth_status(request: Request):
        session_id = request.cookies.get(COOKIE)
        return JSONResponse({'enabled': visual_auth.enabled(), 'authenticated': visual_auth.check(session_id),
                             'csrf': visual_auth.csrf(session_id) if visual_auth.check(session_id) else None},
                            headers={'Cache-Control': 'no-store'})

    @app.post('/api/visual/auth/login')
    def visual_login(data: VisualLoginIn, request: Request):
        if not visual_auth.enabled():
            raise HTTPException(503, 'Acceso visual no configurado')
        if not visual_auth.origin_ok(request.headers.get('origin')):
            raise HTTPException(403, 'Origen no autorizado')
        result = visual_auth.login(data.password, request.client.host if request.client else '')
        if not result:
            raise HTTPException(401, 'Clave incorrecta o acceso temporalmente limitado')
        session_id, csrf = result
        response = JSONResponse({'authenticated': True, 'csrf': csrf}, headers={'Cache-Control': 'no-store'})
        response.set_cookie(COOKIE, session_id, max_age=1800, httponly=True, secure=True, samesite='strict', path='/api')
        return response

    @app.post('/api/visual/auth/logout')
    def visual_logout(request: Request):
        visual_required(request, mutate=True)
        visual_auth.logout(request.cookies.get(COOKIE))
        response = JSONResponse({'authenticated': False}, headers={'Cache-Control': 'no-store'})
        response.delete_cookie(COOKIE, path='/api')
        return response

    @app.get('/api/accounts/{item_id}/session')
    def account_session(item_id: int, request: Request):
        visual_required(request)
        with db.connect() as con:
            account = row(con, '''SELECT id,name,profile_arg,profile_path,session_status,session_checked_at,
                session_user,session_reason FROM accounts WHERE id=?''', (item_id,))
        if not account:
            raise HTTPException(404, 'Cuenta inexistente')
        visual_state = visual.info(item_id)
        busy = coordinator.active_profiles.get(account.pop('profile_path'))
        if visual_state.get('checking'):
            account['session_status'] = 'verification_in_progress'
        elif busy not in (None, f'visual:{item_id}'):
            account['session_status'] = 'in_use_by_task'
        return {**account, 'visual': visual_state}

    @app.post('/api/accounts/{item_id}/session/open')
    def open_visual(item_id: int, request: Request):
        visual_required(request, mutate=True)
        try:
            return visual.open(item_id)
        except VisualSessionError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post('/api/accounts/{item_id}/session/close')
    def close_visual(item_id: int, request: Request):
        visual_required(request, mutate=True)
        try:
            visual.close(item_id)
            return {'open': False}
        except VisualSessionError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post('/api/accounts/{item_id}/session/verify')
    def verify_visual(item_id: int, request: Request):
        visual_required(request, mutate=True)
        try:
            status = visual.verify(item_id)
            with db.connect() as con:
                account = row(con, 'SELECT session_status,session_checked_at,session_user,session_reason FROM accounts WHERE id=?', (item_id,))
            return {'status': status, **account} if account else {'status': status}
        except VisualSessionError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.websocket('/api/accounts/{item_id}/session/ws')
    async def visual_socket(websocket: WebSocket, item_id: int):
        protocols = websocket.headers.get('sec-websocket-protocol', '').split(',')
        csrf = next((p.strip()[5:] for p in protocols if p.strip().startswith('csrf.')), None)
        if (not visual_auth.enabled() or not visual_auth.origin_ok(websocket.headers.get('origin')) or
                not visual_auth.check(websocket.cookies.get(COOKIE), csrf, renew=False) or csrf is None):
            await websocket.close(code=4403)
            return
        session = visual.viewer(item_id, True)
        if not session:
            await websocket.close(code=4409)
            return
        writer = None
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', session.port)
            await websocket.accept(subprotocol='binary' if 'binary' in [p.strip() for p in protocols] else None)

            async def from_vnc():
                while data := await reader.read(65536):
                    await websocket.send_bytes(data)

            async def to_vnc():
                while True:
                    message = await websocket.receive()
                    if message['type'] == 'websocket.disconnect':
                        return
                    data = message.get('bytes') or (message.get('text') or '').encode()
                    writer.write(data)
                    await writer.drain()
                    visual.touch(item_id)

            tasks = [asyncio.create_task(from_vnc()), asyncio.create_task(to_vnc())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
            for task in done:
                task.result()
        except (OSError, WebSocketDisconnect):
            pass
        finally:
            if writer:
                writer.close()
                with suppress(OSError):
                    await writer.wait_closed()
            visual.viewer(item_id, False)
            with suppress(RuntimeError):
                await websocket.close()

    @app.get('/api/tasks/{task_id}/diagnostics')
    def task_diagnostics(task_id: int, request: Request):
        visual_required(request)
        coordinator.diagnostics.prune()
        with db.connect() as con:
            task = row(con, 'SELECT id,status,account_id FROM tasks WHERE id=?', (task_id,))
            if not task:
                raise HTTPException(404, 'Tarea inexistente')
            state = row(con, 'SELECT stage,stage_at,last_progress_at FROM task_runtime_state WHERE task_id=?', (task_id,))
            last_event = row(con, """SELECT kind,message,created_at FROM events
                WHERE task_id=? AND kind!='attempt' ORDER BY id DESC LIMIT 1""", (task_id,))
        return JSONResponse({'task_id': task_id, 'account_id': task['account_id'],
            'stage': state['stage'] if state else task['status'],
            'stage_at': state['stage_at'] if state else None,
            'last_progress_at': state['last_progress_at'] if state else None,
            'last_event': last_event, 'items': coordinator.diagnostics.for_task(task_id)},
            headers={'Cache-Control': 'no-store'})

    @app.get('/api/tasks/{task_id}/diagnostics/{diagnostic_id}/screenshot')
    def diagnostic_screenshot(task_id: int, diagnostic_id: str, request: Request):
        visual_required(request)
        path = coordinator.diagnostics.screenshot(task_id, diagnostic_id)
        if path is None:
            raise HTTPException(404, 'Captura inexistente')
        return FileResponse(path, media_type='image/png', headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/api/health')
    def health():
        with db.connect() as con:
            con.execute('SELECT 1').fetchone()
        return {'status': 'ok'}

    def require(con, table, item_id):
        found = row(con, f'SELECT * FROM {table} WHERE id=?', (item_id,))
        if not found:
            raise HTTPException(404, 'No encontrado')
        return found

    def check_inactive(con, account_id=None, draw_id=None, assignment_id=None):
        if account_id is not None and visual.info(account_id)['open']:
            raise HTTPException(409, 'Cierra el navegador visual antes de editar la cuenta')
        resumable = (*ACTIVE, 'paused', 'interrupted')
        sql = f"SELECT 1 FROM tasks t WHERE t.status IN ({','.join('?' for _ in resumable)})"
        params = list(resumable)
        if account_id is not None:
            sql += ' AND t.account_id=?'
            params.append(account_id)
        if draw_id is not None:
            sql += ' AND t.draw_id=?'
            params.append(draw_id)
        if assignment_id is not None:
            sql += ' AND t.assignment_id=?'
            params.append(assignment_id)
        if con.execute(sql, params).fetchone():
            raise HTTPException(409, 'Hay una tarea activa o reanudable; cancelala antes de editar')

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

    @app.get('/api/dashboard')
    def dashboard():
        with db.connect() as con:
            draws = rows(con, '''SELECT d.id,d.name,d.url,d.end_date,d.end_time,d.archived,
                COALESCE(s.assignment_count,0) assignment_count,
                COALESCE(t.attempts,0) attempts,COALESCE(t.clicked,0) clicked,
                COALESCE(t.confirmed,0) confirmed
                FROM draws d
                LEFT JOIN (SELECT draw_id,COUNT(*) assignment_count FROM assignments GROUP BY draw_id) s ON s.draw_id=d.id
                LEFT JOIN (SELECT draw_id,SUM(attempts) attempts,SUM(clicked) clicked,
                    SUM(confirmed) confirmed FROM tasks GROUP BY draw_id) t ON t.draw_id=d.id
                ORDER BY clicked DESC,d.id DESC''')
            trend = rows(con, '''SELECT date(created_at,'localtime') day,COUNT(*) clicked
                FROM events WHERE kind='clicked' AND date(created_at,'localtime') >= date('now','localtime','-6 days')
                GROUP BY date(created_at,'localtime') ORDER BY day''')
            return {'draws': draws, 'trend': trend}

    @app.get('/api/settings')
    def settings():
        with db.connect() as con:
            values = {key: int(row(con, 'SELECT value FROM settings WHERE key=?', (key,))['value'])
                      for key in ('reminder_hours_before', 'reminder_days_before')}
            limit = row(con, "SELECT value FROM settings WHERE key='browser_limit'")
            values['browser_limit'] = limit['value'] if limit else str(coordinator.browser_limit(con))
            return values

    @app.put('/api/settings')
    def update_settings(data: SettingsIn):
        with db.connect() as con:
            current = {key: int(row(con, 'SELECT value FROM settings WHERE key=?', (key,))['value'])
                       for key in ('reminder_hours_before', 'reminder_days_before')}
            hours = data.reminder_hours_before if data.reminder_hours_before is not None else (
                6 if data.reminder_days_before == 0 else 24 if data.reminder_days_before == 1 else current['reminder_hours_before'])
            days = data.reminder_days_before if data.reminder_days_before is not None else int(hours >= 24)
            pairs = [('reminder_hours_before', str(hours)), ('reminder_days_before', str(days))]
            if data.browser_limit is not None:
                pairs.append(('browser_limit', data.browser_limit))
            con.executemany('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', pairs)
        coordinator.dispatch()
        return settings()

    @app.get('/api/scheduler')
    def scheduler():
        return coordinator.scheduler_status()

    @app.get('/api/tags')
    def tags():
        with db.connect() as con:
            return [item['tag'] for item in rows(con, 'SELECT tag FROM tag_library ORDER BY tag COLLATE NOCASE')]

    @app.post('/api/tags', status_code=201)
    def add_tags(data: TagsIn):
        with db.connect() as con:
            for tag in data.tags:
                con.execute('INSERT OR IGNORE INTO tag_library(tag) VALUES(?)', (tag,))
        return {'tags': data.tags}

    @app.delete('/api/tags/{tag}')
    def delete_tag(tag: str):
        with db.connect() as con:
            if any(tag in json.loads(item['tags_json']) for item in con.execute('SELECT tags_json FROM assignments')):
                raise HTTPException(409, 'La etiqueta esta en uso por una asignacion')
            con.execute('DELETE FROM tag_library WHERE tag=?', (tag,))
        return {'tag': tag}

    @app.get('/api/accounts')
    def accounts():
        with db.connect() as con:
            items = rows(con, 'SELECT * FROM accounts ORDER BY archived,id')
        for item in items:
            if visual.info(item['id']).get('checking'):
                item['session_status'] = 'verification_in_progress'
            elif coordinator.active_profiles.get(item['profile_path']) not in (None, f"visual:{item['id']}"):
                item['session_status'] = 'in_use_by_task'
        return items

    @app.post('/api/accounts', status_code=201)
    def add_account(data: AccountIn):
        with db.connect() as con:
            try:
                item_id = con.execute('INSERT INTO accounts(name,profile_arg,profile_path) VALUES(?,?,?)',
                                      (data.name.strip(), data.profile_arg, profile_path(data.profile_arg))).lastrowid
                ensure_private_dir(Path(profile_path(data.profile_arg)))
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

    @app.post('/api/accounts/{item_id}/clear-attention')
    def clear_account_attention(item_id: int):
        with db.connect() as con:
            require(con, 'accounts', item_id)
            con.execute('UPDATE accounts SET attention_required=0,attention_reason=NULL WHERE id=?', (item_id,))
            return require(con, 'accounts', item_id)

    @app.get('/api/draws')
    def draws():
        with db.connect() as con:
            return rows(con, 'SELECT * FROM draws ORDER BY archived,id')

    @app.post('/api/draws', status_code=201)
    def add_draw(data: DrawIn):
        with db.connect() as con:
            item_id = con.execute('INSERT INTO draws(name,url,notes,end_date,end_time,tag_count) VALUES(?,?,?,?,?,?)',
                                  (data.name.strip(), data.url, data.notes,
                                   data.end_date.isoformat() if data.end_date else None, data.end_time, data.tag_count)).lastrowid
            return require(con, 'draws', item_id)

    @app.put('/api/draws/{item_id}')
    def edit_draw(item_id: int, data: DrawIn):
        with db.connect() as con:
            existing = require(con, 'draws', item_id)
            if data.url != existing['url'] or data.tag_count != existing['tag_count']:
                check_inactive(con, draw_id=item_id)
            con.execute('UPDATE draws SET name=?,url=?,notes=?,end_date=?,end_time=?,tag_count=? WHERE id=?',
                        (data.name.strip(), data.url, data.notes,
                         data.end_date.isoformat() if data.end_date else None, data.end_time, data.tag_count, item_id))
            con.execute('UPDATE assignments SET tag_count=? WHERE draw_id=?', (data.tag_count, item_id))
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
            data = rows(con, '''SELECT s.*,a.name account_name,d.name draw_name,d.url draw_url,
                d.tag_count draw_tag_count,d.end_date draw_end_date
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
            available = {item['tag'] for item in rows(con, 'SELECT tag FROM tag_library')}
            if any(tag not in available for tag in data.tags):
                raise HTTPException(409, 'Selecciona etiquetas de la biblioteca')
            try:
                item_id = con.execute('''INSERT INTO assignments
                    (account_id,draw_id,duration_minutes,comments_per_minute,tag_count,extra_text,tags_json)
                    VALUES(?,?,?,?,?,?,?)''',
                    (data.account_id, data.draw_id, data.duration_minutes, data.comments_per_minute,
                     draw['tag_count'], data.extra_text, json.dumps(data.tags))).lastrowid
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
            available = {item['tag'] for item in rows(con, 'SELECT tag FROM tag_library')}
            if any(tag not in available for tag in data.tags):
                raise HTTPException(409, 'Selecciona etiquetas de la biblioteca')
            try:
                con.execute('''UPDATE assignments SET account_id=?,draw_id=?,duration_minutes=?,
                    comments_per_minute=?,tag_count=?,extra_text=?,tags_json=? WHERE id=?''',
                    (data.account_id, data.draw_id, data.duration_minutes, data.comments_per_minute,
                     draw['tag_count'], data.extra_text, json.dumps(data.tags), item_id))
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
                FROM tasks t JOIN accounts a ON a.id=t.account_id
                JOIN draws d ON d.id=t.draw_id
                ORDER BY CASE WHEN t.status='running' THEN 0
                    WHEN t.status IN ('queued','pausing','cancelling') THEN 1 ELSE 2 END,
                    t.id DESC LIMIT 200''')

    @app.post('/api/tasks/correct-history')
    def correct_history(data: HistoryCorrectionIn):
        with db.connect() as con:
            draw = require(con, 'draws', data.draw_id)
            placeholders = ','.join('?' for _ in data.task_ids)
            selected = rows(con, f'SELECT id,status,draw_id FROM tasks WHERE id IN ({placeholders})', data.task_ids)
            if len(selected) != len(data.task_ids):
                raise HTTPException(404, 'Alguna tarea no existe')
            if any(task['status'] not in ('completed', 'cancelled', 'failed') for task in selected):
                raise HTTPException(409, 'Solo se puede corregir el historial de tareas terminadas')
            changed = 0
            for task in selected:
                if task['draw_id'] == data.draw_id:
                    continue
                previous = require(con, 'draws', task['draw_id'])
                con.execute('UPDATE tasks SET draw_id=? WHERE id=?', (data.draw_id, task['id']))
                con.execute('INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)',
                            (task['id'], 'history_corrected',
                             f"Sorteo historico corregido: {previous['name']} -> {draw['name']}",
                             now()))
                changed += 1
            return {'changed': changed}

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
    if (dist / 'index.html').is_file() and (dist / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

        @app.get('/')
        def index():
            return FileResponse(dist / 'index.html')

        @app.get('/{path:path}', include_in_schema=False)
        def spa(path: str):
            if path.startswith(('api/', 'assets/')) or '.' in Path(path).name:
                raise HTTPException(404, 'No encontrado')
            return FileResponse(dist / 'index.html')

    return app


app = make_app()
