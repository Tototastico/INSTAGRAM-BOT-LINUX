import json
import threading
import time
import types
import sys

from fastapi.testclient import TestClient

from webapp.api import make_app
from webapp.coordinator import Coordinator
from webapp.db import Database, LEGACY_PROFILE_ROOT, LEGACY_TAGS, row
from webapp.runner import SeleniumRunner, compose_comment


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('La condicion no se cumplio a tiempo')


def test_legacy_import_once_preserves_profile_and_config(tmp_path):
    config = tmp_path / 'config.json'
    content = json.dumps({
        'url_post': 'https://www.instagram.com/p/ABC/', 'perfil_chrome': ['accounts/cuenta1'],
        'comentario': 'Extra', 'etiquetas': 1, 'exe_time': 45, 'comentarios_min': 4,
    })
    config.write_text(content, encoding='utf-8')
    db = Database(tmp_path / 'bot.sqlite3', config)
    Database(tmp_path / 'bot.sqlite3', config)
    with db.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] == 1
        assert con.execute('SELECT COUNT(*) FROM draws').fetchone()[0] == 1
        account = row(con, 'SELECT * FROM accounts')
        assignment = row(con, 'SELECT * FROM assignments')
    assert account['profile_arg'] == 'accounts/cuenta1'
    assert account['profile_path'] == str((LEGACY_PROFILE_ROOT / 'accounts/cuenta1').resolve()).lower()
    assert assignment['comments_per_minute'] == 4
    assert assignment['extra_text'] == 'Extra'
    assert config.read_text(encoding='utf-8') == content


def test_crud_and_archive(tmp_path):
    app = make_app(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with TestClient(app) as client:
        account = client.post('/api/accounts', json={'name': 'Uno', 'profile_arg': 'cuenta1'})
        assert account.status_code == 201
        account_id = account.json()['id']
        draw = client.post('/api/draws', json={'name': 'Sorteo A', 'url': 'https://www.instagram.com/p/ABC/'})
        assert draw.status_code == 201
        draw_id = draw.json()['id']
        payload = {'account_id': account_id, 'draw_id': draw_id, 'duration_minutes': 5,
                   'comments_per_minute': 2, 'tag_count': 1, 'tags': ['@amigo']}
        assignment = client.post('/api/assignments', json=payload)
        assert assignment.status_code == 201
        assert client.post('/api/assignments', json=payload).status_code == 409
        assignment_id = assignment.json()['id']
        assert client.put(f'/api/assignments/{assignment_id}', json={**payload, 'duration_minutes': 7}).status_code == 200
        assert client.get('/api/assignments').json()[0]['duration_minutes'] == 7
        assert client.post(f'/api/assignments/{assignment_id}/archive').status_code == 200
        assert client.post(f'/api/assignments/{assignment_id}/start').status_code == 409
        assert client.post(f'/api/accounts/{account_id}/archive').status_code == 200
        assert client.post(f'/api/draws/{draw_id}/archive').status_code == 200


def test_runner_adapter_keeps_legacy_call_order(monkeypatch):
    calls = []
    driver = types.SimpleNamespace(quit=lambda: calls.append(('quit',)))
    textarea = object()
    fake_module = types.SimpleNamespace(
        acceder_caja=lambda url, profile: (calls.append(('open', url, profile)) or (True, driver, textarea)),
        comentar_en_post=lambda comment, used_driver, used_textarea: calls.append(
            ('post', comment, used_driver is driver, used_textarea is textarea)),
    )
    monkeypatch.setitem(sys.modules, 'selenium_runner', fake_module)
    runner = SeleniumRunner()
    runner.open('https://www.instagram.com/p/ABC/', 'accounts/cuenta1')
    runner.post('Hola @amigo')
    runner.close()
    assert calls == [
        ('open', 'https://www.instagram.com/p/ABC/', 'accounts/cuenta1'),
        ('post', 'Hola @amigo', True, True), ('quit',),
    ]
    text = compose_comment(LEGACY_TAGS, 1, '')
    assert any(tag in text for tag in LEGACY_TAGS)


def test_recovery_requires_manual_resume(tmp_path):
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        a = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('A','a','a')").lastrowid
        d = con.execute("INSERT INTO draws(name,url) VALUES('D','https://www.instagram.com/p/ABC/')").lastrowid
        s = con.execute('''INSERT INTO assignments(account_id,draw_id,duration_minutes,comments_per_minute,tag_count,tags_json)
            VALUES(?,?,?,?,?,?)''', (a, d, 1, 1, 1, '["@amigo"]')).lastrowid
        task_id = con.execute("INSERT INTO tasks(assignment_id,status,created_at,updated_at) VALUES(?,'running','x','x')", (s,)).lastrowid
    Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        assert row(con, 'SELECT status FROM tasks WHERE id=?', (task_id,))['status'] == 'interrupted'
        assert row(con, 'SELECT kind FROM events WHERE task_id=?', (task_id,))['kind'] == 'interrupted'


def test_same_profile_queues_and_pause_cancel(tmp_path):
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        a = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('A','a','a')").lastrowid
        d1 = con.execute("INSERT INTO draws(name,url) VALUES('D1','https://www.instagram.com/p/ABC/')").lastrowid
        d2 = con.execute("INSERT INTO draws(name,url) VALUES('D2','https://www.instagram.com/p/DEF/')").lastrowid
        ids = []
        for d in (d1, d2):
            ids.append(con.execute('''INSERT INTO assignments(account_id,draw_id,duration_minutes,comments_per_minute,tag_count,tags_json)
                VALUES(?,?,?,?,?,?)''', (a, d, 1, 1, 1, '["@amigo"]')).lastrowid)

    entered = threading.Event()
    release = threading.Event()
    active = 0
    max_active = 0
    guard = threading.Lock()

    class FakeRunner:
        def open(self, url, profile):
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)

        def post(self, comment):
            entered.set()
            release.wait(2)

        def close(self):
            nonlocal active
            with guard:
                active -= 1

    coordinator = Coordinator(db, FakeRunner)
    first = coordinator.create(ids[0])
    assert entered.wait(2)
    second = coordinator.create(ids[1])
    with db.connect() as con:
        assert row(con, 'SELECT status FROM tasks WHERE id=?', (second,))['status'] == 'queued'
    coordinator.control(first, 'pause')
    release.set()
    wait_for(lambda: first not in coordinator.threads)
    with db.connect() as con:
        assert row(con, 'SELECT status FROM tasks WHERE id=?', (first,))['status'] == 'paused'
    coordinator.control(second, 'cancel')
    coordinator.control(first, 'resume')
    wait_for(lambda: first in coordinator.threads)
    coordinator.control(first, 'cancel')
    wait_for(lambda: first not in coordinator.threads)
    assert max_active == 1
    with db.connect() as con:
        assert row(con, 'SELECT status FROM tasks WHERE id=?', (first,))['status'] == 'cancelled'
        assert row(con, 'SELECT status FROM tasks WHERE id=?', (second,))['status'] == 'cancelled'


def test_different_profiles_run_together_and_close_on_failure(tmp_path):
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        ids = []
        for index in (1, 2):
            a = con.execute('INSERT INTO accounts(name,profile_arg,profile_path) VALUES(?,?,?)',
                            (f'A{index}', f'a{index}', f'a{index}')).lastrowid
            d = con.execute('INSERT INTO draws(name,url) VALUES(?,?)',
                            (f'D{index}', f'https://www.instagram.com/p/{index}/')).lastrowid
            ids.append(con.execute('''INSERT INTO assignments(account_id,draw_id,duration_minutes,comments_per_minute,tag_count,tags_json)
                VALUES(?,?,?,?,?,?)''', (a, d, 1, 1, 1, '["@amigo"]')).lastrowid)

    both_open = threading.Event()
    release = threading.Event()
    opened = []
    closed = []
    guard = threading.Lock()

    class FakeRunner:
        def open(self, url, profile):
            self.profile = profile
            with guard:
                opened.append(profile)
                if len(opened) == 2:
                    both_open.set()
            release.wait(2)

        def post(self, comment):
            raise RuntimeError('Sesion vencida')

        def close(self):
            with guard:
                closed.append(self.profile)

    coordinator = Coordinator(db, FakeRunner)
    task_ids = [coordinator.create(item_id) for item_id in ids]
    assert both_open.wait(2)
    release.set()
    wait_for(lambda: not coordinator.threads)
    assert sorted(closed) == sorted(opened)
    with db.connect() as con:
        for task_id in task_ids:
            task = row(con, 'SELECT * FROM tasks WHERE id=?', (task_id,))
            assert task['status'] == 'failed'
            assert task['attempts'] == 1
            assert task['clicked'] == 0
            assert task['confirmed'] == 0


def test_duration_and_frequency_repeat_without_extra_post(tmp_path):
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        a = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('A','a','a')").lastrowid
        d = con.execute("INSERT INTO draws(name,url) VALUES('D','https://www.instagram.com/p/ABC/')").lastrowid
        assignment = con.execute('''INSERT INTO assignments(account_id,draw_id,duration_minutes,comments_per_minute,tag_count,tags_json)
            VALUES(?,?,?,?,?,?)''', (a, d, 1, 2, 1, '["@amigo"]')).lastrowid

    fake_time = [0.0]
    posted = []
    closed = []

    class FakeRunner:
        def open(self, url, profile):
            assert (url, profile) == ('https://www.instagram.com/p/ABC/', 'a')

        def post(self, comment):
            posted.append(comment)

        def close(self):
            closed.append(True)

    coordinator = Coordinator(db, FakeRunner, clock=lambda: fake_time[0],
                              sleep=lambda seconds: fake_time.__setitem__(0, fake_time[0] + seconds))
    task_id = coordinator.create(assignment)
    wait_for(lambda: task_id not in coordinator.threads)
    assert len(posted) == 2
    assert all('@amigo' in comment for comment in posted)
    assert closed == [True]
    with db.connect() as con:
        task = row(con, 'SELECT * FROM tasks WHERE id=?', (task_id,))
        assert (task['status'], task['attempts'], task['clicked'], task['confirmed']) == ('completed', 2, 2, 0)
