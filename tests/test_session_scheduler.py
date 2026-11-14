from fastapi.testclient import TestClient
import threading
import time

from webapp.api import make_app
from webapp.coordinator import Coordinator
from webapp.db import Database, row
from webapp.resources import can_start
from webapp.session_probe import probe


class Element:
    def __init__(self, tag='a', **attributes):
        self.tag_name, self.attributes = tag, attributes

    def get_attribute(self, key):
        return self.attributes.get(key)

    def is_displayed(self):
        return True

    def find_elements(self, *_):
        return []


class Driver:
    def __init__(self, url='https://www.instagram.com/', profile=None, login=False):
        self.current_url, self.profile, self.login = url, profile, login

    def find_elements(self, _, selector):
        if selector == 'a[href]' and self.profile:
            return [Element(href=f'https://www.instagram.com/{self.profile}/', **{'aria-label': 'Profile'})]
        if 'input[type="password"]' in selector and self.login:
            return [Element('input', type='password')]
        return []


def test_session_probe_requires_positive_evidence_and_detects_wrong_account():
    assert probe(Driver(profile='soyteoo'), 'soyteoo')[0:2] == ('connected', 'soyteoo')
    assert probe(Driver(profile='soyteoo'), 'tobi_sirne')[0] == 'wrong_account'
    assert probe(Driver(), 'soyteoo')[0] == 'unknown'
    assert probe(Driver(login=True), 'soyteoo')[0] == 'not_signed_in'
    assert probe(Driver(url='https://www.instagram.com/accounts/login/'), 'soyteoo')[0] == 'session_expired'
    assert probe(Driver(url='https://www.instagram.com/challenge/'), 'soyteoo')[0] == 'verification_required'
    # Display names with spaces are not Instagram handles; do not pause a working account.
    assert probe(Driver(profile='cuenta2'), 'Cuenta 2')[0] == 'connected'


def test_resource_admission_uses_available_memory_and_cpu():
    metrics = {'available_mb': 1100, 'chrome_mb': 900, 'managed_browsers': 1,
               'cpu_load': 0.1, 'cpu_count': 2, 'enforce': True}
    assert not can_start(metrics, 1)
    metrics['available_mb'] = 3000
    assert can_start(metrics, 1)
    metrics['cpu_load'] = 5
    assert not can_start(metrics, 1)


def test_browser_limit_settings_keep_conservative_default(tmp_path, monkeypatch):
    monkeypatch.setenv('MAX_CONCURRENT_BROWSERS', '1')
    app = make_app(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with TestClient(app) as client:
        assert client.get('/api/settings').json()['browser_limit'] == '1'
        assert client.put('/api/settings', json={'browser_limit': '3'}).json()['browser_limit'] == '3'
        assert client.get('/api/scheduler').json()['limit'] == 3
        assert client.put('/api/settings', json={'browser_limit': 'auto'}).json()['browser_limit'] == 'auto'
        assert client.put('/api/settings', json={'browser_limit': '9'}).status_code == 422


def test_busy_account_does_not_block_next_account(tmp_path, monkeypatch):
    monkeypatch.setenv('MAX_CONCURRENT_BROWSERS', '2')
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        assignments = []
        for profile in ('a', 'a', 'b'):
            account = row(con, 'SELECT id FROM accounts WHERE profile_path=?', (profile,))
            account_id = account['id'] if account else con.execute(
                'INSERT INTO accounts(name,profile_arg,profile_path) VALUES(?,?,?)',
                (profile, profile, profile)).lastrowid
            draw_id = con.execute('INSERT INTO draws(name,url) VALUES(?,?)',
                                  (profile, 'https://www.instagram.com/p/ABC/')).lastrowid
            assignments.append(con.execute('''INSERT INTO assignments
                (account_id,draw_id,duration_minutes,comments_per_minute,tag_count,tags_json)
                VALUES(?,?,?,?,?,?)''', (account_id, draw_id, 1, 1, 1, '["@friend"]')).lastrowid)
    opened = []
    release = threading.Event()

    class Runner:
        def open(self, _, profile):
            opened.append(profile)
            release.wait(3)

        def post(self, _):
            raise RuntimeError('controlled stop')

        def close(self):
            pass

    coordinator = Coordinator(db, Runner)
    first, second, third = [coordinator.create(assignment) for assignment in assignments]
    deadline = time.monotonic() + 2
    while len(opened) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sorted(opened) == ['a', 'b']
    with db.connect() as con:
        assert row(con, 'SELECT status FROM tasks WHERE id=?', (second,))['status'] == 'queued'
    assert coordinator.scheduler_status()['reasons'][second] == 'Cuenta ocupada'
    release.set()
    deadline = time.monotonic() + 3
    while coordinator.threads and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not coordinator.active_profiles


def test_visual_reservation_keeps_same_profile_queued(tmp_path, monkeypatch):
    monkeypatch.setenv('MAX_CONCURRENT_BROWSERS', '2')
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        account = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('a','a','a')").lastrowid
        draw = con.execute("INSERT INTO draws(name,url) VALUES('d','https://www.instagram.com/p/ABC/')").lastrowid
        assignment = con.execute('''INSERT INTO assignments(account_id,draw_id,duration_minutes,
            comments_per_minute,tag_count,tags_json) VALUES(?,?,?,?,?,?)''',
            (account, draw, 1, 1, 1, '["@friend"]')).lastrowid
    coordinator = Coordinator(db, lambda: None)
    coordinator.active_profiles['a'] = f'visual:{account}'
    task = coordinator.create(assignment)
    with db.connect() as con:
        assert row(con, 'SELECT status FROM tasks WHERE id=?', (task,))['status'] == 'queued'
    assert coordinator.scheduler_status()['reasons'][task] == 'Cuenta ocupada'


def test_scheduler_waits_for_memory_then_retries(tmp_path, monkeypatch):
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        account = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('a','a','a')").lastrowid
        draw = con.execute("INSERT INTO draws(name,url) VALUES('d','https://www.instagram.com/p/ABC/')").lastrowid
        assignment = con.execute('''INSERT INTO assignments(account_id,draw_id,duration_minutes,
            comments_per_minute,tag_count,tags_json) VALUES(?,?,?,?,?,?)''',
            (account, draw, 1, 1, 1, '["@friend"]')).lastrowid
    metrics = {'available_mb': 1200, 'chrome_mb': 0, 'managed_browsers': 0,
               'cpu_load': 0.7, 'cpu_count': 2, 'enforce': True}
    monkeypatch.setattr('webapp.coordinator.snapshot', lambda _profiles: metrics.copy())

    class Runner:
        def open(self, *_):
            raise RuntimeError('controlled stop')

        def close(self):
            pass

    coordinator = Coordinator(db, Runner)
    task = coordinator.create(assignment)
    with db.connect() as con:
        assert row(con, 'SELECT status FROM tasks WHERE id=?', (task,))['status'] == 'queued'
    assert coordinator.scheduler_status()['reasons'][task] == 'Esperando recursos'
    metrics['available_mb'] = 2500
    coordinator.dispatch()
    deadline = time.monotonic() + 2
    while coordinator.threads and time.monotonic() < deadline:
        time.sleep(0.01)
    with db.connect() as con:
        assert row(con, 'SELECT status FROM tasks WHERE id=?', (task,))['status'] == 'failed'
