import json
import threading
import time

from .db import now, row, rows
from .runner import PendingCommentError, SeleniumRunner, compose_comment


ACTIVE = ('queued', 'running', 'pausing', 'cancelling')


class Coordinator:
    def __init__(self, db, runner_factory=SeleniumRunner, clock=time.monotonic, sleep=time.sleep):
        self.db = db
        self.runner_factory = runner_factory
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.RLock()
        self.active_profiles = {}  # profile_path -> task_id
        self.threads = {}          # task_id -> thread
        self.runners = {}          # task_id -> runner
        self.shutting_down = False

    def _event(self, con, task_id, kind, message):
        con.execute('INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)',
                    (task_id, kind, message, now()))

    def _status(self, con, task_id, status, message=None):
        con.execute('UPDATE tasks SET status=?,updated_at=? WHERE id=?', (status, now(), task_id))
        self._event(con, task_id, status, message or status)

    def create(self, assignment_id):
        with self.lock:
            if self.shutting_down:
                raise ValueError('El servidor esta apagandose; no se aceptan nuevas tareas')
            with self.db.connect() as con:
                assignment = row(con, '''SELECT s.id, a.attention_required FROM assignments s
                    JOIN accounts a ON a.id=s.account_id JOIN draws d ON d.id=s.draw_id
                    WHERE s.id=? AND s.archived=0 AND a.archived=0 AND d.archived=0''', (assignment_id,))
                if not assignment:
                    raise ValueError('Asignacion inexistente o archivada')
                if assignment['attention_required']:
                    raise ValueError('La cuenta requiere revision antes de iniciar otra tarea')
                existing = row(con, f"SELECT id FROM tasks WHERE assignment_id=? AND status IN ({','.join('?' for _ in ACTIVE)})",
                               (assignment_id, *ACTIVE))
                if existing:
                    raise ValueError('La asignacion ya tiene una tarea activa')
                task_id = con.execute('INSERT INTO tasks(assignment_id,status,created_at,updated_at) VALUES(?,?,?,?)',
                                      (assignment_id, 'queued', now(), now())).lastrowid
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
                if self.shutting_down:
                    raise ValueError('El servidor esta apagandose; no se puede reanudar')
                account = row(con, '''SELECT a.attention_required FROM tasks t
                    JOIN assignments s ON s.id=t.assignment_id
                    JOIN accounts a ON a.id=s.account_id WHERE t.id=?''', (task_id,))
                if account['attention_required']:
                    raise ValueError('La cuenta requiere revision antes de reanudar')
                self._status(con, task_id, 'queued', 'Reanudacion manual solicitada')
            elif action == 'cancel' and state == 'running':
                self._status(con, task_id, 'cancelling', 'Cancelacion solicitada')
            elif action == 'cancel' and state in ('queued', 'paused', 'interrupted'):
                self._status(con, task_id, 'cancelled', 'Tarea cancelada')
            else:
                raise ValueError(f'No se puede {action} una tarea {state}')
        self.dispatch()

    def dispatch(self):
        with self.lock:
            if self.shutting_down:
                return
            with self.db.connect() as con:
                candidates = rows(con, '''SELECT t.id, a.profile_path FROM tasks t
                    JOIN assignments s ON s.id=t.assignment_id JOIN accounts a ON a.id=s.account_id
                    WHERE t.status='queued' AND a.attention_required=0 ORDER BY t.id''')
                for task in candidates:
                    path = task['profile_path']
                    if path in self.active_profiles:
                        continue
                    self.active_profiles[path] = task['id']
                    self._status(con, task['id'], 'running', 'Ejecucion iniciada')
                    thread = threading.Thread(target=self._run, args=(task['id'], path), daemon=True)
                    self.threads[task['id']] = thread
                    thread.start()

    def _load_task(self, task_id):
        with self.db.connect() as con:
            return row(con, '''SELECT t.*, s.duration_minutes, s.comments_per_minute,
                s.tag_count, s.extra_text, s.tags_json, a.profile_arg, d.url
                FROM tasks t JOIN assignments s ON s.id=t.assignment_id
                JOIN accounts a ON a.id=s.account_id JOIN draws d ON d.id=s.draw_id
                WHERE t.id=?''', (task_id,))

    def _run(self, task_id, path):
        runner = None
        segment_start = self.clock()
        try:
            task = self._load_task(task_id)
            base_elapsed = task['elapsed_seconds']
            last_saved = segment_start
            runner = self.runner_factory()
            with self.lock:
                self.runners[task_id] = runner

            runner.open(task['url'], task['profile_arg'])
            duration = task['duration_minutes'] * 60
            interval = 60 / task['comments_per_minute']
            next_attempt = self.clock()
            while True:
                with self.lock:
                    if self.shutting_down:
                        self._finish(task_id, 'interrupted', base_elapsed + self.clock() - segment_start)
                        break

                current = self._load_task(task_id)
                elapsed = base_elapsed + self.clock() - segment_start
                if self.clock() - last_saved >= 1:
                    with self.db.connect() as con:
                        con.execute('UPDATE tasks SET elapsed_seconds=?,updated_at=? WHERE id=?',
                                    (elapsed, now(), task_id))
                    last_saved = self.clock()
                if current['status'] in ('pausing', 'cancelling'):
                    terminal = 'paused' if current['status'] == 'pausing' else 'cancelled'
                    self._finish(task_id, terminal, elapsed)
                    break
                if elapsed >= duration:
                    self._finish(task_id, 'completed', duration)
                    break
                if self.clock() < next_attempt:
                    self.sleep(min(0.2, next_attempt - self.clock()))
                    continue
                comment = compose_comment(json.loads(task['tags_json']), task['tag_count'], task['extra_text'])
                with self.db.connect() as con:
                    con.execute('UPDATE tasks SET attempts=attempts+1,updated_at=? WHERE id=?', (now(), task_id))
                    self._event(con, task_id, 'attempt', comment)
                try:
                    runner.post(comment)
                except PendingCommentError as exc:
                    self._pause_for_attention(task_id, exc, base_elapsed + self.clock() - segment_start)
                    break
                except Exception as exc:
                    self._fail(task_id, exc, base_elapsed + self.clock() - segment_start)
                    break
                with self.db.connect() as con:
                    con.execute('UPDATE tasks SET clicked=clicked+1,updated_at=? WHERE id=?', (now(), task_id))
                    self._event(con, task_id, 'clicked', 'Clic en Publicar; confirmacion no verificada')
                next_attempt = self.clock() + interval
        except Exception as exc:
            self._fail(task_id, exc, base_elapsed + self.clock() - segment_start if 'base_elapsed' in locals() else 0)
        finally:
            with self.lock:
                self.runners.pop(task_id, None)
            if runner is not None:
                try:
                    runner.close()
                except Exception as exc:
                    with self.db.connect() as con:
                        self._event(con, task_id, 'close_error', str(exc))
            with self.lock:
                self.active_profiles.pop(path, None)
                self.threads.pop(task_id, None)
            self.dispatch()

    def shutdown(self, timeout_seconds=15.0):
        """
        Detiene la aceptación de tareas, marca tareas activas para pausarse/interrumpirse,
        espera a los hilos activos y cierra de forma forzada los runners que persistan.
        """
        with self.lock:
            self.shutting_down = True
            active_task_ids = list(self.threads.keys())
            with self.db.connect() as con:
                # Pasar las queued a interrupted inmediatamente
                con.execute("UPDATE tasks SET status='interrupted', updated_at=? WHERE status='queued'", (now(),))

        deadline = self.clock() + timeout_seconds
        while self.clock() < deadline:
            with self.lock:
                if not self.threads:
                    break
            self.sleep(0.2)

        # Cierre forzado de runners si algún hilo no terminó
        with self.lock:
            for task_id, runner in list(self.runners.items()):
                try:
                    runner.close()
                except Exception:
                    pass
            self.runners.clear()
            self.active_profiles.clear()
            self.threads.clear()

        # Asegurar estado en BD
        self.db.recover_interrupted()

    def _finish(self, task_id, status, elapsed):
        with self.db.connect() as con:
            con.execute('UPDATE tasks SET elapsed_seconds=? WHERE id=?', (max(0, elapsed), task_id))
            self._status(con, task_id, status)

    def _fail(self, task_id, exc, elapsed):
        message = str(exc) or type(exc).__name__
        with self.db.connect() as con:
            con.execute('UPDATE tasks SET elapsed_seconds=?,failures=failures+1,last_error=? WHERE id=?',
                        (max(0, elapsed), message, task_id))
            self._status(con, task_id, 'failed', message)

    def _pause_for_attention(self, task_id, exc, elapsed):
        message = str(exc)
        with self.lock, self.db.connect() as con:
            task = row(con, 'SELECT assignment_id FROM tasks WHERE id=?', (task_id,))
            assignment = row(con, 'SELECT account_id FROM assignments WHERE id=?', (task['assignment_id'],))
            account_id = assignment['account_id']
            con.execute('UPDATE accounts SET attention_required=1,attention_reason=? WHERE id=?',
                        (message, account_id))
            con.execute('UPDATE tasks SET elapsed_seconds=?,last_error=? WHERE id=?',
                        (max(0, elapsed), message, task_id))
            self._event(con, task_id, 'blocked_suspected', message)
            self._status(con, task_id, 'paused', 'Pausada: requiere revision de la cuenta')
            queued = rows(con, '''SELECT t.id FROM tasks t JOIN assignments s ON s.id=t.assignment_id
                WHERE s.account_id=? AND t.status='queued' ''', (account_id,))
            for pending in queued:
                self._status(con, pending['id'], 'paused', 'Pausada: la cuenta requiere revision')
