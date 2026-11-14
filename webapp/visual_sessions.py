"""Isolated X11/Chrome sessions. No VNC listener is reachable off loopback."""
import json
import os
import secrets
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # Linux-only feature; keep the Windows test/import path usable.
    fcntl = None

from .db import now, row, profile_path
from .settings import accounts_dir, data_dir, ensure_private_dir
from .session_probe import probe


class VisualSessionError(RuntimeError):
    pass


@dataclass
class Session:
    account_id: int
    profile: Path
    display: str
    port: int
    authority: Path
    processes: list
    lock_file: object
    last_activity: float
    viewer_busy: bool = False


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _process_start(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().split(') ')[1].split()[19]
    except (OSError, IndexError):
        return None


def profile_process_running(profile):
    """Catch manually opened Chrome instances that did not take our flock."""
    if os.name != 'posix':
        return False
    expected = f'--user-data-dir={profile}'.encode()
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid == os.getuid() and expected in (entry / 'cmdline').read_bytes().split(b'\0'):
                return True
        except (OSError, PermissionError):
            continue
    return False


class VisualSessions:
    def __init__(self, db, coordinator, clock=time.monotonic, popen=subprocess.Popen):
        self.db, self.coordinator, self.clock, self.popen = db, coordinator, clock, popen
        self.platform = os.name
        self.sessions = {}
        self.checking = set()
        self.lock = threading.RLock()
        self.runtime = data_dir() / 'visual-runtime'

    def _event(self, account_id, action):
        with self.db.connect() as con:
            con.execute('INSERT INTO admin_events(account_id,action,created_at) VALUES(?,?,?)',
                        (account_id, action, now()))

    def _record(self, session):
        ensure_private_dir(self.runtime)
        path = self.runtime / f'{session.account_id}.json'
        payload = [{'pid': p.pid, 'start': _process_start(p.pid)} for p in session.processes]
        path.write_text(json.dumps(payload), encoding='utf-8')
        path.chmod(0o600)

    def recover_orphans(self):
        if self.platform != 'posix' or not self.runtime.exists():
            return
        for path in self.runtime.glob('*.json'):
            try:
                records = json.loads(path.read_text(encoding='utf-8'))
                for item in reversed(records):
                    pid = item['pid']
                    if item['start'] and _process_start(pid) == item['start']:
                        if Path(f'/proc/{pid}').stat().st_uid == os.getuid():
                            os.killpg(pid, signal.SIGTERM)
            except (OSError, ValueError, KeyError, TypeError, ProcessLookupError):
                pass
            path.unlink(missing_ok=True)
        for path in self.runtime.glob('auth-*'):
            path.unlink(missing_ok=True)

    def _reserve(self, account_id):
        with self.coordinator.lock:
            with self.db.connect() as con:
                account = row(con, 'SELECT * FROM accounts WHERE id=? AND archived=0', (account_id,))
                if not account:
                    raise VisualSessionError('Cuenta inexistente o archivada')
                profile = Path(profile_path(account['profile_arg']))
                if str(profile) != account['profile_path']:
                    raise VisualSessionError('La ruta del perfil no coincide con la cuenta registrada')
                if profile.parent != accounts_dir().resolve():
                    raise VisualSessionError('El perfil debe estar dentro de BOT_ACCOUNTS_DIR')
                busy = con.execute("SELECT 1 FROM tasks WHERE account_id=? AND status IN ('running','pausing','cancelling')", (account_id,)).fetchone()
                if busy or str(profile) in self.coordinator.active_profiles:
                    raise VisualSessionError('La cuenta esta en uso por una tarea o sesion visual')
                from .resources import can_start, snapshot
                if len(self.coordinator.active_profiles) >= self.coordinator.browser_limit(con) or not can_start(
                        snapshot(self.coordinator.active_profiles), len(self.coordinator.active_profiles)):
                    raise VisualSessionError('No hay capacidad para otro navegador; espera o aumenta el limite')
                if profile_process_running(profile):
                    raise VisualSessionError('Hay un Chrome manual abierto con este perfil')
                self.coordinator.active_profiles[str(profile)] = f'visual:{account_id}'
            try:
                ensure_private_dir(accounts_dir())
                lock_path = accounts_dir() / f'{profile.name}.lock'
                lock_file = open(lock_path, 'a+b')
                lock_path.chmod(0o600)
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    lock_file.close()
                    raise VisualSessionError('El perfil Chrome ya esta abierto en otro proceso')
                return profile, lock_file
            except Exception:
                self.coordinator.active_profiles.pop(str(profile), None)
                raise

    def _release(self, profile, lock_file):
        if lock_file:
            lock_file.close()
        with self.coordinator.lock:
            self.coordinator.active_profiles.pop(str(profile), None)
        self.coordinator.dispatch()

    def _display(self):
        for number in range(120, 180):
            if not Path(f'/tmp/.X11-unix/X{number}').exists() and all(
                item.display != f':{number}' for item in self.sessions.values()
            ):
                return f':{number}'
        raise VisualSessionError('No quedan pantallas visuales disponibles')

    def _spawn(self, command, env=None):
        return self.popen(command, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          start_new_session=True)

    def open(self, account_id):
        if self.platform != 'posix':
            raise VisualSessionError('La sesion visual requiere Linux')
        with self.lock:
            if account_id in self.sessions:
                raise VisualSessionError('Esta cuenta ya tiene una sesion visual')
            if len(self.sessions) >= int(os.environ.get('BOT_VISUAL_MAX_SESSIONS', '1')):
                raise VisualSessionError('Se alcanzo el limite de sesiones visuales')
            profile, lock_file = self._reserve(account_id)
            processes = []
            authority = None
            try:
                display = self._display()
                ensure_private_dir(profile)
                ensure_private_dir(self.runtime)
                authority = self.runtime / f'auth-{account_id}-{secrets.token_hex(8)}'
                authority.touch(mode=0o600)
                authority.chmod(0o600)
                subprocess.run(['xauth', '-f', str(authority), 'add', display, '.', secrets.token_hex(16)],
                               check=True, capture_output=True, timeout=10)
                env = {**os.environ, 'DISPLAY': display, 'XAUTHORITY': str(authority)}
                processes.append(self._spawn(['Xvfb', display, '-screen', '0', '1366x900x24',
                                              '-nolisten', 'tcp', '-auth', str(authority)], env))
                deadline = self.clock() + 5
                while not Path(f'/tmp/.X11-unix/X{display[1:]}').exists():
                    if processes[0].poll() is not None or self.clock() >= deadline:
                        raise VisualSessionError('Xvfb no pudo iniciar; revisa X11 y XAUTHORITY')
                    time.sleep(0.05)
                port = _free_port()
                processes.append(self._spawn(['x11vnc', '-display', display, '-auth', str(authority),
                                              '-localhost', '-nopw', '-rfbport', str(port), '-forever',
                                              '-noxdamage'], env))
                ready = False
                deadline = self.clock() + 5
                while self.clock() < deadline:
                    if processes[1].poll() is not None:
                        break
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                            ready = True
                            break
                    except OSError:
                        time.sleep(0.05)
                if not ready:
                    raise VisualSessionError('El servidor VNC privado no pudo iniciar')
                chrome = os.environ.get('CHROME_BINARY', '/usr/bin/google-chrome-stable')
                processes.append(self._spawn([chrome, f'--user-data-dir={profile}',
                                              '--new-window', 'https://www.instagram.com/'], env))
                time.sleep(0.3)
                if processes[2].poll() is not None:
                    raise VisualSessionError('Chrome se cerro al iniciar; revisa el perfil o X11')
                session = Session(account_id, profile, display, port, authority, processes,
                                  lock_file, self.clock())
                self.sessions[account_id] = session
                self._record(session)
                self._event(account_id, 'visual_opened')
                return self.info(account_id)
            except Exception as exc:
                self.sessions.pop(account_id, None)
                self._stop_processes(processes)
                if authority:
                    authority.unlink(missing_ok=True)
                (self.runtime / f'{account_id}.json').unlink(missing_ok=True)
                self._release(profile, lock_file)
                if isinstance(exc, VisualSessionError):
                    raise
                raise VisualSessionError(f'No se pudo abrir Chrome visual: {type(exc).__name__}') from exc

    @staticmethod
    def _stop_processes(processes):
        for process in reversed(processes):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
        for process in reversed(processes):
            try:
                process.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass

    def close(self, account_id, action='visual_closed'):
        with self.lock:
            session = self.sessions.pop(account_id, None)
            if not session:
                raise VisualSessionError('No hay una sesion visual abierta')
            try:
                self._stop_processes(session.processes)
                session.authority.unlink(missing_ok=True)
                (self.runtime / f'{account_id}.json').unlink(missing_ok=True)
                self._event(account_id, action)
            finally:
                self._release(session.profile, session.lock_file)

    def close_all(self):
        for account_id in list(self.sessions):
            self.close(account_id, 'visual_service_stopped')

    def prune(self):
        with self.lock:
            for account_id, session in list(self.sessions.items()):
                if self.clock() - session.last_activity > 1200 or any(
                    p.poll() is not None for p in session.processes
                ):
                    self.close(account_id, 'visual_expired')

    def info(self, account_id):
        with self.lock:
            session = self.sessions.get(account_id)
            if not session:
                return {'open': False, 'checking': account_id in self.checking}
            return {'open': True, 'viewer_busy': session.viewer_busy,
                    'checking': False,
                    'expires_in': max(0, int(1200 - (self.clock() - session.last_activity)))}

    def viewer(self, account_id, acquire):
        with self.lock:
            session = self.sessions.get(account_id)
            if not session or (acquire and session.viewer_busy):
                return None
            session.viewer_busy = acquire
            session.last_activity = self.clock()
            return session

    def touch(self, account_id):
        with self.lock:
            if account_id in self.sessions:
                self.sessions[account_id].last_activity = self.clock()

    def verify(self, account_id, driver_factory=None):
        """Read the login state once; never submit forms or copy browser storage."""
        from selenium import webdriver
        profile, lock_file = self._reserve(account_id)
        with self.lock:
            self.checking.add(account_id)
        driver = None
        state = 'verification_error'
        detected = ''
        reason = 'No se pudo iniciar la verificacion'
        try:
            with self.db.connect() as con:
                expected = row(con, 'SELECT name FROM accounts WHERE id=?', (account_id,))['name']
            if not profile.is_dir():
                state = 'not_signed_in'
                reason = 'El perfil Chrome aun no existe'
            else:
                options = webdriver.ChromeOptions()
                options.binary_location = os.environ.get('CHROME_BINARY', '/usr/bin/google-chrome-stable')
                options.add_argument(f'--user-data-dir={profile}')
                options.add_argument('--headless=new')
                options.add_argument('--window-size=1200,850')
                driver = (driver_factory or webdriver.Chrome)(options=options)
                driver.set_page_load_timeout(30)
                driver.get('https://www.instagram.com/')
                deadline = self.clock() + 8
                while True:
                    state, detected, reason = probe(driver, expected)
                    if state != 'unknown' or self.clock() >= deadline:
                        break
                    time.sleep(0.5)
            return state
        except Exception as exc:
            reason = f'Verificacion fallida: {type(exc).__name__}'
            return state
        finally:
            with self.lock:
                self.checking.discard(account_id)
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            try:
                with self.db.connect() as con:
                    con.execute('''UPDATE accounts SET session_status=?,session_checked_at=?,
                        session_user=?,session_reason=? WHERE id=?''',
                                (state, now(), detected, reason, account_id))
                self._event(account_id, 'session_verified')
            finally:
                self._release(profile, lock_file)
