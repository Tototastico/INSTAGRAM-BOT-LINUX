import os
import socket
import subprocess
import threading
import time
import types
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from webapp.api import make_app
from webapp.visual_auth import VisualAuth, password_hash
from webapp.visual_sessions import Session, VisualSessionError, VisualSessions


@pytest.fixture
def visual_client(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('BOT_ACCOUNTS_DIR', str(tmp_path / 'accounts'))
    monkeypatch.setenv('BOT_PUBLIC_ORIGIN', 'https://bot.example.test')
    monkeypatch.setenv('BOT_VISUAL_ADMIN_PASSWORD_HASH', password_hash('strong-test-password'))
    app = make_app(tmp_path / 'data' / 'bot.sqlite3')
    with TestClient(app, base_url='https://bot.example.test') as client:
        yield client, app, tmp_path


def login(client):
    response = client.post('/api/visual/auth/login', json={'password': 'strong-test-password'},
                           headers={'Origin': 'https://bot.example.test'})
    assert response.status_code == 200
    return response.json()['csrf']


def test_visual_auth_cookie_csrf_origin_and_websocket(visual_client):
    client, app, _ = visual_client
    assert client.get('/api/accounts/1/session').status_code == 401
    assert client.post('/api/visual/auth/login', json={'password': 'strong-test-password'},
                       headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.post('/api/visual/auth/login', json={'password': 'bad'},
                       headers={'Origin': 'https://bot.example.test'}).status_code == 401
    csrf = login(client)
    assert client.post('/api/accounts/1/session/open', headers={'Origin': 'https://bot.example.test'}).status_code == 403
    assert client.post('/api/accounts/1/session/open', headers={'Origin': 'https://evil.test',
                       'X-Visual-CSRF': csrf}).status_code == 403
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect('/api/accounts/1/session/ws',
                                      headers={'Origin': 'https://evil.test',
                                               'Sec-WebSocket-Protocol': f'binary, csrf.{csrf}'}):
            pass
    assert exc.value.code == 4403
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect('/api/accounts/1/session/ws',
                                      headers={'Origin': 'https://bot.example.test'}):
            pass
    assert exc.value.code == 4403


def test_account_creation_reuses_existing_profile_and_reports_unknown(visual_client):
    client, _, root = visual_client
    profile = root / 'accounts' / 'cuenta2'
    profile.mkdir(parents=True)
    marker = profile / 'Preferences'
    marker.write_text('preserve')
    response = client.post('/api/accounts', json={'name': 'Cuenta 2', 'profile_arg': 'cuenta2'})
    assert response.status_code == 201
    assert marker.read_text() == 'preserve'
    assert response.json()['session_status'] == 'unknown'
    assert response.json()['session_checked_at'] is None
    assert client.post('/api/accounts', json={'name': 'duplicada', 'profile_arg': 'accounts/cuenta2'}).status_code == 409


def test_visual_open_close_routes_and_active_task_conflict(visual_client, monkeypatch):
    client, app, _ = visual_client
    account = client.post('/api/accounts', json={'name': 'Cuenta 2', 'profile_arg': 'cuenta2'}).json()
    csrf = login(client)
    headers = {'Origin': 'https://bot.example.test', 'X-Visual-CSRF': csrf}
    profile = account['profile_path']
    app.state.coordinator.active_profiles[profile] = 99
    assert client.get('/api/accounts').json()[0]['session_status'] == 'in_use_by_task'
    assert client.post(f"/api/accounts/{account['id']}/session/open", headers=headers).status_code == 409
    app.state.coordinator.active_profiles.pop(profile)
    monkeypatch.setattr(app.state.visual, 'open', lambda _id: {'open': True})
    monkeypatch.setattr(app.state.visual, 'close', lambda _id: None)
    assert client.post(f"/api/accounts/{account['id']}/session/open", headers=headers).json() == {'open': True}
    monkeypatch.setattr(app.state.visual, 'info', lambda _id: {'open': True})
    assert client.put(f"/api/accounts/{account['id']}", json={'name': 'Cambio', 'profile_arg': 'cuenta2'}).status_code == 409
    assert client.post(f"/api/accounts/{account['id']}/archive").status_code == 409
    assert client.post(f"/api/accounts/{account['id']}/session/close", headers=headers).json() == {'open': False}


def test_verification_reads_state_and_releases_profile(visual_client, monkeypatch):
    client, app, _ = visual_client
    account = client.post('/api/accounts', json={'name': 'Cuenta 2', 'profile_arg': 'cuenta2'}).json()
    import webapp.visual_sessions as visual_module
    if visual_module.fcntl is None:
        monkeypatch.setattr(visual_module, 'fcntl', types.SimpleNamespace(
            LOCK_EX=1, LOCK_NB=2, flock=lambda *_: None))

    class Driver:
        current_url = 'https://www.instagram.com/'
        def set_page_load_timeout(self, _): pass
        def get(self, _): pass
        def find_elements(self, _, selector):
            if selector == 'a[href]':
                return [types.SimpleNamespace(get_attribute=lambda name: '/Cuenta 2/' if name == 'href' else 'Perfil',
                    find_elements=lambda *_: [])]
            return []
        def quit(self): self.closed = True

    driver = Driver()
    assert app.state.visual.verify(account['id'], driver_factory=lambda **_: driver) == 'connected'
    assert driver.closed
    assert not app.state.coordinator.active_profiles
    assert client.get('/api/accounts').json()[0]['session_status'] == 'connected'


def test_oversized_preferences_block_visual_and_verification_before_chrome(visual_client, monkeypatch):
    client, app, _ = visual_client
    account = client.post('/api/accounts', json={'name': 'Cuenta 2', 'profile_arg': 'cuenta2'}).json()
    profile = Path(account['profile_path'])
    preferences = profile / 'Default' / 'Preferences'
    preferences.parent.mkdir(parents=True, exist_ok=True)
    with preferences.open('wb') as stream:
        stream.truncate(65 * 1024 * 1024)
    import webapp.visual_sessions as module
    if module.fcntl is None:
        monkeypatch.setattr(module, 'fcntl', types.SimpleNamespace(
            LOCK_EX=1, LOCK_NB=2, flock=lambda *_: None))
    app.state.visual.platform = 'posix'
    monkeypatch.setattr(app.state.visual, '_display', lambda: ':120')
    monkeypatch.setattr(app.state.visual, '_spawn', lambda *_args, **_kwargs: pytest.fail('Chrome must not launch'))
    with pytest.raises(VisualSessionError, match='limite preventivo'):
        app.state.visual.open(account['id'])
    assert not app.state.coordinator.active_profiles
    assert app.state.visual.verify(account['id'], driver_factory=lambda **_: pytest.fail('Chrome must not launch')) == 'verification_error'
    assert preferences.stat().st_size == 65 * 1024 * 1024


def test_password_hash_and_session_expiration(monkeypatch):
    monkeypatch.setenv('BOT_PUBLIC_ORIGIN', 'https://bot.example.test')
    monkeypatch.setenv('BOT_VISUAL_ADMIN_PASSWORD_HASH', password_hash('secret'))
    clock = [0]
    auth = VisualAuth(clock=lambda: clock[0])
    session, csrf = auth.login('secret', 'client')
    assert auth.check(session, csrf)
    assert not auth.check(session, 'wrong')
    clock[0] = 1801
    assert not auth.check(session, csrf)


def test_authorized_websocket_bridges_only_its_session(visual_client):
    client, app, root = visual_client
    account = client.post('/api/accounts', json={'name': 'Cuenta', 'profile_arg': 'cuenta2'}).json()
    csrf = login(client)
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    port = server.getsockname()[1]

    def vnc_stub():
        connection, _ = server.accept()
        with connection:
            connection.sendall(b'RFB 003.008\n')
            connection.sendall(connection.recv(64))
        server.close()

    thread = threading.Thread(target=vnc_stub)
    thread.start()
    app.state.visual.sessions[account['id']] = Session(
        account['id'], Path(account['profile_path']), ':120', port,
        root / 'missing-xauth', [], None, time.monotonic())
    with client.websocket_connect(f"wss://bot.example.test/api/accounts/{account['id']}/session/ws",
                                  subprotocols=['binary', f'csrf.{csrf}'],
                                  headers={'Origin': 'https://bot.example.test',
                                           'Cookie': f"bot_visual_session={client.cookies.get('bot_visual_session')}"}) as websocket:
        assert websocket.accepted_subprotocol == 'binary'
        assert websocket.receive_bytes() == b'RFB 003.008\n'
        websocket.send_bytes(b'hello')
        assert websocket.receive_bytes() == b'hello'
    thread.join(timeout=3)
    assert not thread.is_alive()


def test_visual_process_lifecycle_and_x11_failure_release_profile(visual_client, monkeypatch):
    client, app, _ = visual_client
    account = client.post('/api/accounts', json={'name': 'Cuenta', 'profile_arg': 'cuenta2'}).json()
    manager = app.state.visual
    manager.platform = 'posix'  # Exercise the Linux launch path with fake processes on Windows too.
    import webapp.visual_sessions as module
    if module.fcntl is None:
        monkeypatch.setattr(module, 'fcntl', types.SimpleNamespace(
            LOCK_EX=1, LOCK_NB=2, flock=lambda *_: None))
    monkeypatch.setattr(module.os, 'killpg', lambda *_: None, raising=False)
    monkeypatch.setattr(manager, '_display', lambda: ':120')
    original_exists = Path.exists
    monkeypatch.setattr(Path, 'exists', lambda path: True if str(path).endswith('X120') else original_exists(path))
    monkeypatch.setattr(module.socket, 'create_connection', lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)

    class Process:
        def __init__(self, pid): self.pid, self.status = pid, None
        def poll(self): return self.status
        def wait(self, timeout=None): return 0

    launches = []
    monkeypatch.setattr(manager, '_spawn', lambda command, env=None: (launches.append(command) or Process(100 + len(launches))))
    monkeypatch.setattr(module.subprocess, 'run', lambda *_args, **_kwargs: None)
    assert manager.open(account['id'])['open']
    assert len(launches) == 3
    assert launches[0][0] == 'Xvfb'
    assert launches[1][0] == 'x11vnc'
    assert '-localhost' in launches[1]
    assert '--no-sandbox' not in launches[2]
    assert any(str(account['profile_path']) in arg for arg in launches[2])
    with pytest.raises(VisualSessionError):
        manager.open(account['id'])
    manager.close(account['id'])
    assert not app.state.coordinator.active_profiles
    assert Path(account['profile_path']).is_dir()

    manager.open(account['id'])
    manager.sessions[account['id']].processes[1].status = 1
    manager.prune()
    assert not manager.sessions
    assert not app.state.coordinator.active_profiles

    monkeypatch.setattr(module.subprocess, 'run', lambda *_args, **_kwargs: (_ for _ in ()).throw(
        subprocess.CalledProcessError(1, 'xauth')))
    with pytest.raises(VisualSessionError, match='No se pudo abrir Chrome visual'):
        manager.open(account['id'])
    assert not app.state.coordinator.active_profiles
