import json
import threading
import time
from selenium.common.exceptions import WebDriverException

from .db import now, row, rows
from .diagnostics import DiagnosticStore
from .runner import PendingCommentError, SeleniumRunner, SessionUnavailableError, compose_comment
from .resources import admission_decision, can_start, snapshot
from .profile_health import preference_warning
from .settings import max_browsers


ACTIVE = ('queued', 'running', 'pausing', 'cancelling')


class Coordinator:
    def __init__(self, db, runner_factory=SeleniumRunner, clock=time.monotonic, sleep=time.sleep):
        self.db = db
        self.runner_factory = runner_factory
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.RLock()
        self.active_profiles = {}
        self.threads = {}
        self.stopping = False
        self.diagnostics = DiagnosticStore(db)

    def _event(self, con, task_id, kind, message):
        con.execute('INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)',
                    (task_id, kind, message, now()))

    def _runner_event(self, task_id, kind, message):
        with self.db.connect() as con:
            self._event(con, task_id, kind, message)

    def _stage(self, task_id, stage, progress=False):
        stamp = now()
        with self.db.connect() as con:
            con.execute('''INSERT INTO task_runtime_state(task_id,stage,stage_at,last_progress_at)
                VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET
                stage=excluded.stage,stage_at=excluded.stage_at,
                last_progress_at=COALESCE(excluded.last_progress_at,task_runtime_state.last_progress_at)''',
                (task_id, stage, stamp, stamp if progress else None))

    def _diagnostic(self, task_id, account_id, stage, exc, driver, selector):
        diagnostic_id = self.diagnostics.record(task_id, account_id, stage, exc, driver, selector)
        self._runner_event(task_id, 'diagnostic', f'Diagnostico {diagnostic_id}: {type(exc).__name__} durante {stage}')
        return diagnostic_id

    def _status(self, con, task_id, status, message=None):
        con.execute('UPDATE tasks SET status=?,updated_at=? WHERE id=?', (status, now(), task_id))
        self._event(con, task_id, status, message or status)

    def create(self, assignment_id):
        with self.lock, self.db.connect() as con:
            if self.stopping:
                raise ValueError('El servicio se esta deteniendo')
            assignment = row(con, '''SELECT s.id,s.account_id,s.draw_id,a.attention_required,a.session_status FROM assignments s
                JOIN accounts a ON a.id=s.account_id JOIN draws d ON d.id=s.draw_id
                WHERE s.id=? AND s.archived=0 AND a.archived=0 AND d.archived=0''', (assignment_id,))
            if not assignment:
                raise ValueError('Asignacion inexistente o archivada')
            if assignment['attention_required']:
                raise ValueError('La cuenta requiere revision antes de iniciar otra tarea')
            if assignment['session_status'] == 'wrong_account':
                raise ValueError('La verificacion detecto una cuenta de Instagram diferente')
            existing = row(con, f"SELECT id FROM tasks WHERE assignment_id=? AND status IN ({','.join('?' for _ in ACTIVE)})",
                           (assignment_id, *ACTIVE))
            if existing:
                raise ValueError('La asignacion ya tiene una tarea activa')
            task_id = con.execute('''INSERT INTO tasks
                (assignment_id,account_id,draw_id,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?)''',
                (assignment_id, assignment['account_id'], assignment['draw_id'], 'queued', now(), now())).lastrowid
            self._event(con, task_id, 'queued', 'Tarea en cola')
        self.dispatch()
        return task_id

    def control(self, task_id, action):
        with self.lock, self.db.connect() as con:
            task = row(con, 'SELECT status FROM tasks WHERE id=?', (task_id,))
            if not task:
                raise KeyError(task_id)
            state = task['status']
            if action == 'pause' and state == 'running':
                self._status(con, task_id, 'pausing', 'Pausa solicitada')
            elif action == 'pause' and state == 'queued':
                self._status(con, task_id, 'paused', 'Tarea pausada en cola')
            elif action == 'resume' and state in ('paused', 'interrupted'):
                if self.stopping:
                    raise ValueError('El servicio se esta deteniendo')
                account = row(con, '''SELECT a.attention_required,a.session_status FROM tasks t
                    JOIN accounts a ON a.id=t.account_id WHERE t.id=?''', (task_id,))
                if account['attention_required']:
                    raise ValueError('La cuenta requiere revision antes de reanudar')
                if account['session_status'] == 'wrong_account':
                    raise ValueError('Verifica el usuario de Instagram antes de reanudar')
                self._status(con, task_id, 'queued', 'Reanudacion manual solicitada')
            elif action == 'cancel' and state == 'running':
                self._status(con, task_id, 'cancelling', 'Cancelacion solicitada')
            elif action == 'cancel' and state in ('queued', 'paused', 'interrupted'):
                self._status(con, task_id, 'cancelled', 'Tarea cancelada')
            else:
                raise ValueError(f'No se puede {action} una tarea {state}')
        self.dispatch()

    def dispatch(self):
        with self.lock, self.db.connect() as con:
            if self.stopping:
                return
            limit = self.browser_limit(con)
            metrics = snapshot(self.active_profiles)
            candidates = rows(con, '''SELECT t.id, a.profile_path FROM tasks t
                JOIN accounts a ON a.id=t.account_id
                WHERE t.status='queued' AND a.attention_required=0 ORDER BY t.id''')
            for task in candidates:
                if len(self.active_profiles) >= limit or not can_start(metrics, len(self.active_profiles)):
                    break
                path = task['profile_path']
                if path in self.active_profiles:
                    continue
                self.active_profiles[path] = task['id']
                self._status(con, task['id'], 'running', 'Ejecucion iniciada')
                thread = threading.Thread(target=self._run, args=(task['id'], path), daemon=True)
                self.threads[task['id']] = thread
                thread.start()

    def browser_limit(self, con=None):
        if con is None:
            with self.db.connect() as own:
                return self.browser_limit(own)
        value = row(con, "SELECT value FROM settings WHERE key='browser_limit'")
        configured = value['value'] if value else str(max_browsers())
        return 4 if configured == 'auto' else int(configured)

    def scheduler_status(self):
        with self.lock, self.db.connect() as con:
            metrics = snapshot(self.active_profiles)
            limit = self.browser_limit(con)
            active = set(self.active_profiles)
            admission = admission_decision(metrics, len(active))
            profile_warnings = []
            for account in rows(con, 'SELECT id,name,profile_path FROM accounts WHERE archived=0'):
                warning = preference_warning(account['profile_path'])
                if warning:
                    profile_warnings.append({'account_id': account['id'], 'account_name': account['name'],
                                             **warning})
            queued = rows(con, "SELECT t.id,a.profile_path FROM tasks t JOIN accounts a ON a.id=t.account_id WHERE t.status='queued' ORDER BY t.id")
            reasons = {}
            for task in queued:
                if task['profile_path'] in active:
                    reasons[task['id']] = 'Cuenta ocupada'
                elif len(active) >= limit:
                    reasons[task['id']] = 'Límite de navegadores'
                elif not admission['allowed']:
                    reasons[task['id']] = admission['reason']
                else:
                    reasons[task['id']] = 'Próxima en cola'
            return {'active_browsers': len(active), 'running_tasks': sum(isinstance(v, int) for v in self.active_profiles.values()),
                    'queued_tasks': len(queued), 'limit': limit, 'memory_available_mb': metrics['available_mb'],
                      'chrome_memory_mb': metrics.get('chrome_mb'), 'cpu_load': metrics.get('cpu_load'),
                      'admission': admission, 'reasons': reasons,
                      'profile_warnings': profile_warnings}

    def _load_task(self, task_id):
        with self.db.connect() as con:
            return row(con, '''SELECT t.*, s.duration_minutes, s.comments_per_minute,
                d.tag_count, d.extra_text, s.tags_json, a.profile_arg, a.name account_name,
                a.session_status, d.url
                FROM tasks t JOIN assignments s ON s.id=t.assignment_id
                JOIN accounts a ON a.id=t.account_id JOIN draws d ON d.id=t.draw_id
                WHERE t.id=?''', (task_id,))

    def _run(self, task_id, path):
        runner = None
        task = None
        diagnostic_recorded = False
        segment_start = self.clock()
        def record_from_runner(stage, exc, driver, selector):
            nonlocal diagnostic_recorded
            diagnostic_id = self._diagnostic(task_id, task['account_id'], stage, exc, driver, selector)
            diagnostic_recorded = True
            return diagnostic_id

        def record_unhandled(exc, stage):
            if diagnostic_recorded:
                return
            if task is not None:
                try:
                    self._diagnostic(task_id, task['account_id'], stage, exc,
                                     getattr(runner, 'driver', None), '')
                except Exception:
                    pass  # An evidence storage failure cannot change the task outcome.
        try:
            task = self._load_task(task_id)
            base_elapsed = task['elapsed_seconds']
            last_saved = segment_start
            runner = self.runner_factory()
            if hasattr(runner, 'set_expected_account'):
                runner.set_expected_account(task['account_name'] if task['session_status'] == 'connected' else '')
            if hasattr(runner, 'set_event_sink'):
                runner.set_event_sink(lambda kind, message: self._runner_event(task_id, kind, message))
            if hasattr(runner, 'set_stage_sink'):
                runner.set_stage_sink(lambda stage: self._stage(
                    task_id, stage, stage in ('page_ready', 'comment_box_ready')))
            if hasattr(runner, 'set_diagnostic_sink'):
                runner.set_diagnostic_sink(record_from_runner)
            runner.open(task['url'], task['profile_arg'])
            self._stage(task_id, 'comment_count')
            if hasattr(runner, 'read_comment_count'):
                try:
                    count = runner.read_comment_count()
                    with self.db.connect() as con:
                        if count is None:
                            self._event(con, task_id, 'comment_count_unavailable',
                                        'No se encontro el contador de comentarios en la publicacion')
                        else:
                            con.execute('UPDATE draws SET comment_count=?,comment_count_checked_at=? WHERE id=?',
                                        (count, now(), task['draw_id']))
                            self._event(con, task_id, 'comment_count_observed',
                                        f'Comentarios visibles de Instagram al iniciar: {count}')
                except Exception as exc:
                    with self.db.connect() as con:
                        self._event(con, task_id, 'comment_count_unavailable',
                                    f'No se pudo leer el contador: {type(exc).__name__}')
            duration = task['duration_minutes'] * 60
            interval = 60 / task['comments_per_minute']
            next_attempt = self.clock()
            while True:
                current = self._load_task(task_id)
                elapsed = base_elapsed + self.clock() - segment_start
                if self.clock() - last_saved >= 1:
                    with self.db.connect() as con:
                        con.execute('UPDATE tasks SET elapsed_seconds=?,updated_at=? WHERE id=?',
                                    (elapsed, now(), task_id))
                    last_saved = self.clock()
                if current['status'] in ('pausing', 'cancelling'):
                    terminal = 'interrupted' if self.stopping else ('paused' if current['status'] == 'pausing' else 'cancelled')
                    self._finish(task_id, terminal, elapsed)
                    break
                if duration and elapsed >= duration:
                    self._finish(task_id, 'completed', duration)
                    break
                if self.clock() < next_attempt:
                    self.sleep(min(0.2, next_attempt - self.clock()))
                    continue
                comment = compose_comment(json.loads(task['tags_json']), task['tag_count'], task['extra_text'])
                with self.db.connect() as con:
                    con.execute('UPDATE tasks SET attempts=attempts+1,updated_at=? WHERE id=?', (now(), task_id))
                    self._event(con, task_id, 'attempt', comment)
                diagnostic_recorded = False
                try:
                    runner.post(comment)
                except PendingCommentError as exc:
                    record_unhandled(exc, 'comment_box_pending_check')
                    self._pause_for_attention(task_id, exc, base_elapsed + self.clock() - segment_start)
                    break
                except SessionUnavailableError as exc:
                    record_unhandled(exc, 'session_check')
                    self._pause_session(task_id, exc, base_elapsed + self.clock() - segment_start)
                    break
                except Exception as exc:
                    record_unhandled(exc, 'comment')
                    self._fail(task_id, exc, base_elapsed + self.clock() - segment_start, 'Comentario')
                    break
                with self.db.connect() as con:
                    con.execute('UPDATE tasks SET clicked=clicked+1,updated_at=? WHERE id=?', (now(), task_id))
                    self._event(con, task_id, 'clicked', 'Clic en Publicar; confirmacion no verificada')
                self._stage(task_id, 'publish_click', progress=True)
                next_attempt = self.clock() + interval
        except SessionUnavailableError as exc:
            record_unhandled(exc, 'session_check')
            self._pause_session(task_id, exc, base_elapsed + self.clock() - segment_start if 'base_elapsed' in locals() else 0)
        except Exception as exc:
            record_unhandled(exc, 'execution')
            self._fail(task_id, exc, base_elapsed + self.clock() - segment_start if 'base_elapsed' in locals() else 0,
                       'Inicio o ejecucion')
        finally:
            if runner is not None:
                try:
                    runner.close()
                except Exception as exc:
                    with self.db.connect() as con:
                        self._event(con, task_id, 'close_error', type(exc).__name__)
            with self.lock:
                self.active_profiles.pop(path, None)
                self.threads.pop(task_id, None)
            self.dispatch()

    def shutdown(self, timeout=75):
        with self.lock:
            self.stopping = True
            with self.db.connect() as con:
                con.execute("UPDATE tasks SET status='interrupted',updated_at=? WHERE status='queued'", (now(),))
                con.execute("UPDATE tasks SET status='cancelling',updated_at=? WHERE status IN ('running','pausing')", (now(),))
            threads = list(self.threads.values())
        deadline = time.monotonic() + timeout
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))

    def _finish(self, task_id, status, elapsed):
        self._stage(task_id, status)
        with self.db.connect() as con:
            con.execute('UPDATE tasks SET elapsed_seconds=? WHERE id=?', (max(0, elapsed), task_id))
            self._status(con, task_id, status)

    def _fail(self, task_id, exc, elapsed, stage='Ejecucion'):
        detail = '' if isinstance(exc, WebDriverException) else str(exc).strip()[:240]
        message = f'{stage} - {type(exc).__name__}: {detail}'
        self._stage(task_id, 'failed')
        with self.db.connect() as con:
            con.execute('UPDATE tasks SET elapsed_seconds=?,failures=failures+1,last_error=? WHERE id=?',
                        (max(0, elapsed), message, task_id))
            self._status(con, task_id, 'failed', message)

    def _pause_for_attention(self, task_id, exc, elapsed):
        message = str(exc)
        self._stage(task_id, 'paused')
        with self.lock, self.db.connect() as con:
            task = row(con, 'SELECT account_id FROM tasks WHERE id=?', (task_id,))
            account_id = task['account_id']
            con.execute('UPDATE accounts SET attention_required=1,attention_reason=? WHERE id=?',
                        (message, account_id))
            con.execute('UPDATE tasks SET elapsed_seconds=?,last_error=? WHERE id=?',
                        (max(0, elapsed), message, task_id))
            self._event(con, task_id, 'blocked_suspected', message)
            self._status(con, task_id, 'paused', 'Pausada: requiere revision de la cuenta')
            queued = rows(con, '''SELECT id FROM tasks
                WHERE account_id=? AND status='queued' ''', (account_id,))
            for pending in queued:
                self._status(con, pending['id'], 'paused', 'Pausada: la cuenta requiere revision')

    def _pause_session(self, task_id, exc, elapsed):
        self._stage(task_id, 'paused')
        with self.lock, self.db.connect() as con:
            task = row(con, 'SELECT account_id FROM tasks WHERE id=?', (task_id,))
            con.execute('''UPDATE accounts SET session_status=?,session_checked_at=?,
                session_user=?,session_reason=? WHERE id=?''',
                (exc.state, now(), exc.detected, exc.reason, task['account_id']))
            con.execute('UPDATE tasks SET last_error=?,elapsed_seconds=? WHERE id=?',
                        (str(exc), max(0, elapsed), task_id))
            self._status(con, task_id, 'paused', 'Pausada: revisar sesion de Instagram')
            for pending in rows(con, "SELECT id FROM tasks WHERE account_id=? AND status='queued'", (task['account_id'],)):
                self._status(con, pending['id'], 'paused', 'Pausada: revisar sesion de Instagram')
