import json
import sqlite3
import threading
import time
import types
import sys

import pytest
from fastapi.testclient import TestClient
from selenium.common.exceptions import StaleElementReferenceException

from webapp.api import make_app
from webapp.coordinator import Coordinator
from webapp.db import Database, LEGACY_PROFILE_ROOT, LEGACY_TAGS, row
from webapp.runner import PendingCommentError, SeleniumRunner, compose_comment, parse_comment_count


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
    assert account['profile_path'] == str((LEGACY_PROFILE_ROOT / 'cuenta1').resolve())
    assert assignment['comments_per_minute'] == 4
    assert assignment['extra_text'] == 'Extra'
    with db.connect() as con:
        assert row(con, 'SELECT tag_count FROM draws')['tag_count'] == 1
        assert len(con.execute('SELECT tag FROM tag_library').fetchall()) == len(LEGACY_TAGS)
    assert config.read_text(encoding='utf-8') == content


def test_existing_accounts_table_gains_attention_columns(tmp_path):
    path = tmp_path / 'bot.sqlite3'
    with sqlite3.connect(path) as con:
        con.execute('''CREATE TABLE accounts (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, profile_arg TEXT NOT NULL,
            profile_path TEXT NOT NULL UNIQUE, archived INTEGER NOT NULL DEFAULT 0
        )''')
        con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('A','a','a')")
    db = Database(path, tmp_path / 'missing.json')
    with db.connect() as con:
        account = row(con, 'SELECT * FROM accounts WHERE id=1')
    assert account['name'] == 'A'
    assert account['attention_required'] == 0
    assert account['attention_reason'] is None


def test_existing_draws_gain_end_date_and_inherit_mentions(tmp_path):
    path = tmp_path / 'bot.sqlite3'
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE draws (id INTEGER PRIMARY KEY,name TEXT NOT NULL,url TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',archived INTEGER NOT NULL DEFAULT 0)")
        con.execute("CREATE TABLE assignments (id INTEGER PRIMARY KEY,account_id INTEGER,draw_id INTEGER,duration_minutes INTEGER,comments_per_minute REAL,tag_count INTEGER,extra_text TEXT,tags_json TEXT,archived INTEGER DEFAULT 0)")
        con.execute("INSERT INTO draws(id,name,url) VALUES(1,'Viejo','https://www.instagram.com/p/ABC/')")
        con.execute("INSERT INTO assignments(account_id,draw_id,duration_minutes,comments_per_minute,tag_count,extra_text,tags_json) VALUES(1,1,5,1,3,'','[\"@uno\"]')")
    db = Database(path, tmp_path / 'missing.json')
    with db.connect() as con:
        draw = row(con, 'SELECT * FROM draws WHERE id=1')
    assert draw['tag_count'] == 3
    assert draw['end_date'] is None
    assert draw['end_time'] is None
    assert draw['comment_count'] is None
    assert draw['comment_count_checked_at'] is None


def test_reminder_settings_migrate_from_days(tmp_path):
    path = tmp_path / 'bot.sqlite3'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        con.execute("INSERT INTO settings VALUES('reminder_days_before','0')")
    db = Database(path, tmp_path / 'missing.json')
    with db.connect() as con:
        assert row(con, "SELECT value FROM settings WHERE key='reminder_hours_before'")['value'] == '6'
    db.initialize()
    with db.connect() as con:
        assert row(con, "SELECT value FROM settings WHERE key='reminder_hours_before'")['value'] == '6'


def test_existing_tasks_get_assignment_snapshot_once(tmp_path):
    path = tmp_path / 'bot.sqlite3'
    with sqlite3.connect(path) as con:
        con.execute('''CREATE TABLE accounts (id INTEGER PRIMARY KEY,name TEXT,profile_arg TEXT,
            profile_path TEXT UNIQUE,archived INTEGER DEFAULT 0)''')
        con.execute('''CREATE TABLE draws (id INTEGER PRIMARY KEY,name TEXT,url TEXT,
            notes TEXT DEFAULT '',archived INTEGER DEFAULT 0)''')
        con.execute('''CREATE TABLE assignments (id INTEGER PRIMARY KEY,account_id INTEGER,draw_id INTEGER,
            duration_minutes INTEGER,comments_per_minute REAL,tag_count INTEGER,extra_text TEXT,
            tags_json TEXT,archived INTEGER DEFAULT 0)''')
        con.execute('''CREATE TABLE tasks (id INTEGER PRIMARY KEY,assignment_id INTEGER,status TEXT,
            elapsed_seconds REAL DEFAULT 0,attempts INTEGER DEFAULT 0,clicked INTEGER DEFAULT 0,
            confirmed INTEGER DEFAULT 0,failures INTEGER DEFAULT 0,last_error TEXT,
            created_at TEXT,updated_at TEXT)''')
        con.execute("INSERT INTO accounts(id,name,profile_arg,profile_path) VALUES(1,'A','a','a')")
        con.execute("INSERT INTO draws(id,name,url) VALUES(1,'D1','https://www.instagram.com/p/ONE/')")
        con.execute("INSERT INTO draws(id,name,url) VALUES(2,'D2','https://www.instagram.com/p/TWO/')")
        con.execute('''INSERT INTO assignments(id,account_id,draw_id,duration_minutes,
            comments_per_minute,tag_count,extra_text,tags_json) VALUES(1,1,1,5,1,1,'','["@amigo"]')''')
        con.execute("INSERT INTO tasks(id,assignment_id,status,clicked,created_at,updated_at) VALUES(1,1,'completed',505,'x','x')")
    db = Database(path, tmp_path / 'missing.json')
    with db.connect() as con:
        assert row(con, 'SELECT account_id,draw_id FROM tasks WHERE id=1') == {'account_id': 1, 'draw_id': 1}
        con.execute('UPDATE assignments SET draw_id=2 WHERE id=1')
    db.initialize()
    with db.connect() as con:
        assert row(con, 'SELECT account_id,draw_id FROM tasks WHERE id=1') == {'account_id': 1, 'draw_id': 1}


def test_task_history_stays_with_original_draw_after_assignment_edit(tmp_path):
    app = make_app(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with TestClient(app) as client:
        first_account = client.post('/api/accounts', json={'name': 'Uno', 'profile_arg': 'cuenta1'}).json()
        second_account = client.post('/api/accounts', json={'name': 'Dos', 'profile_arg': 'cuenta2'}).json()
        first_draw = client.post('/api/draws', json={'name': 'Sorteo 1', 'url': 'https://www.instagram.com/p/ONE/'}).json()
        second_draw = client.post('/api/draws', json={'name': 'Sorteo 2', 'url': 'https://www.instagram.com/p/TWO/'}).json()
        client.post('/api/tags', json={'tags': ['@amigo']})
        payload = {'account_id': first_account['id'], 'draw_id': first_draw['id'],
                   'duration_minutes': 5, 'comments_per_minute': 1, 'tags': ['@amigo']}
        assignment_id = client.post('/api/assignments', json=payload).json()['id']
        with app.state.db.connect() as con:
            old_task = con.execute('''INSERT INTO tasks(assignment_id,status,attempts,clicked,
                created_at,updated_at) VALUES(?,'completed',505,505,'x','x')''', (assignment_id,)).lastrowid
        changed = {**payload, 'account_id': second_account['id'], 'draw_id': second_draw['id']}
        assert client.put(f'/api/assignments/{assignment_id}', json=changed).status_code == 200
        with app.state.db.connect() as con:
            new_task = con.execute('''INSERT INTO tasks(assignment_id,status,attempts,clicked,
                created_at,updated_at) VALUES(?,'completed',3,3,'x','x')''', (assignment_id,)).lastrowid
        tasks = {task['id']: task for task in client.get('/api/tasks').json()}
        assert (tasks[old_task]['draw_name'], tasks[old_task]['account_name']) == ('Sorteo 1', 'Uno')
        assert (tasks[new_task]['draw_name'], tasks[new_task]['account_name']) == ('Sorteo 2', 'Dos')
        stats = {draw['id']: draw for draw in client.get('/api/dashboard').json()['draws']}
        assert stats[first_draw['id']]['clicked'] == 505
        assert stats[second_draw['id']]['clicked'] == 3
        loaded = app.state.coordinator._load_task(old_task)
        assert (loaded['url'], loaded['profile_arg']) == (first_draw['url'], first_account['profile_arg'])
        assert client.post('/api/tasks/correct-history', json={
            'task_ids': [old_task], 'draw_id': second_draw['id'],
        }).json()['changed'] == 1
        assert client.get('/api/tasks').json()[-1]['draw_name'] == 'Sorteo 2'
        assert client.post('/api/tasks/correct-history', json={
            'task_ids': [old_task], 'draw_id': first_draw['id'],
        }).json()['changed'] == 1
        assert any(event['kind'] == 'history_corrected' for event in client.get('/api/events').json())
        assert {draw['id']: draw['clicked'] for draw in client.get('/api/dashboard').json()['draws']} == {
            first_draw['id']: 505, second_draw['id']: 3,
        }


def test_running_tasks_come_before_newer_finished_tasks(tmp_path):
    app = make_app(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with TestClient(app) as client:
        account = client.post('/api/accounts', json={'name': 'Uno', 'profile_arg': 'cuenta1'}).json()
        draw = client.post('/api/draws', json={'name': 'Sorteo', 'url': 'https://www.instagram.com/p/ONE/'}).json()
        client.post('/api/tags', json={'tags': ['@amigo']})
        payload = {'account_id': account['id'], 'draw_id': draw['id'],
                   'duration_minutes': 5, 'comments_per_minute': 1, 'tags': ['@amigo']}
        assignment_id = client.post('/api/assignments', json=payload).json()['id']
        with app.state.db.connect() as con:
            running = con.execute("INSERT INTO tasks(assignment_id,status,created_at,updated_at) VALUES(?,'running','x','x')", (assignment_id,)).lastrowid
            con.execute("INSERT INTO tasks(assignment_id,status,created_at,updated_at) VALUES(?,'completed','x','x')", (assignment_id,))
        assert client.get('/api/tasks').json()[0]['id'] == running
        assert client.put(f'/api/assignments/{assignment_id}', json=payload).status_code == 409
        assert client.post('/api/tasks/correct-history', json={
            'task_ids': [running], 'draw_id': draw['id'],
        }).status_code == 409


def test_task_events_remain_available_after_other_activity(tmp_path):
    app = make_app(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with TestClient(app) as client:
        with app.state.db.connect() as con:
            account = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('A','a','a')").lastrowid
            draw = con.execute("INSERT INTO draws(name,url) VALUES('D','https://www.instagram.com/p/ABC/')").lastrowid
            assignment = con.execute('''INSERT INTO assignments
                (account_id,draw_id,duration_minutes,comments_per_minute,tag_count,tags_json)
                VALUES(?,?,?,?,?,?)''', (account, draw, 1, 1, 1, '["@amigo"]')).lastrowid
            old_task = con.execute("INSERT INTO tasks(assignment_id,status,last_error,created_at,updated_at) VALUES(?,'failed','StaleElementReferenceException: textarea','x','x')", (assignment,)).lastrowid
            recent_task = con.execute("INSERT INTO tasks(assignment_id,status,created_at,updated_at) VALUES(?,'completed','x','x')", (assignment,)).lastrowid
            con.execute("INSERT INTO events(task_id,kind,message,created_at) VALUES(?,'failed','detalle original','x')", (old_task,))
            con.executemany("INSERT INTO events(task_id,kind,message,created_at) VALUES(?,'clicked','clic','x')",
                            [(recent_task,)] * 110)
        assert all(event['task_id'] != old_task for event in client.get('/api/events').json())
        details = client.get(f'/api/events?task_id={old_task}&limit=200').json()
        assert len(details) == 1 and details[0]['message'] == 'detalle original'
        task = next(item for item in client.get('/api/tasks').json() if item['id'] == old_task)
        assert task['last_error'].startswith('StaleElementReferenceException')


def test_crud_and_archive(tmp_path):
    app = make_app(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with TestClient(app) as client:
        account = client.post('/api/accounts', json={'name': 'Uno', 'profile_arg': 'cuenta1'})
        assert account.status_code == 201
        account_id = account.json()['id']
        draw = client.post('/api/draws', json={'name': 'Sorteo A', 'url': 'https://www.instagram.com/p/ABC/'})
        assert draw.status_code == 201
        draw_id = draw.json()['id']
        assert client.post('/api/tags', json={'tags': ['@amigo']}).status_code == 201
        payload = {'account_id': account_id, 'draw_id': draw_id, 'duration_minutes': 5,
                   'comments_per_minute': 2, 'tags': ['@amigo']}
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


def test_draw_settings_library_and_dashboard(tmp_path):
    app = make_app(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with TestClient(app) as client:
        account = client.post('/api/accounts', json={'name': 'Uno', 'profile_arg': 'cuenta1'}).json()
        draw = client.post('/api/draws', json={
            'name': 'Nuevo', 'url': 'https://www.instagram.com/p/ABC/',
            'end_date': '2030-12-31', 'end_time': '18:30', 'tag_count': 3,
        })
        assert draw.status_code == 201
        draw_id = draw.json()['id']
        assert draw.json()['end_date'] == '2030-12-31'
        assert draw.json()['end_time'] == '18:30'
        assert client.post('/api/draws', json={
            'name': 'Invalido', 'url': 'https://www.instagram.com/p/ABC/', 'end_time': '18:30',
        }).status_code == 422
        assert client.post('/api/draws', json={
            'name': 'Invalido', 'url': 'https://www.instagram.com/p/ABC/',
            'end_date': '2030-12-31', 'end_time': '25:30',
        }).status_code == 422
        assert client.post('/api/tags', json={'tags': ['@uno', '@dos', '@uno']}).status_code == 201
        assert client.get('/api/tags').json() == ['@dos', '@uno']
        payload = {'account_id': account['id'], 'draw_id': draw_id,
                   'duration_minutes': 0, 'comments_per_minute': 1, 'tags': ['@uno', '@dos']}
        assignment = client.post('/api/assignments', json=payload)
        assert assignment.status_code == 201
        assert client.get('/api/assignments').json()[0]['draw_tag_count'] == 3
        assert client.delete('/api/tags/@uno').status_code == 409
        assert client.put('/api/settings', json={'reminder_days_before': 0}).status_code == 200
        assert client.get('/api/settings').json()['reminder_days_before'] == 0
        assert client.put('/api/settings', json={'reminder_days_before': 2}).status_code == 422
        assert client.put('/api/settings', json={'reminder_hours_before': 12}).status_code == 200
        assert client.get('/api/settings').json()['reminder_hours_before'] == 12
        assert client.put('/api/settings', json={'reminder_hours_before': 0}).status_code == 422
        with app.state.db.connect() as con:
            con.execute("INSERT INTO tasks(assignment_id,status,attempts,clicked,created_at,updated_at) VALUES(?,'completed',4,3,'x','x')", (assignment.json()['id'],))
        stats = client.get('/api/dashboard').json()
        assert stats['draws'][0]['clicked'] == 3
        assert stats['draws'][0]['attempts'] == 4
        assert stats['draws'][0]['end_date'] == '2030-12-31'
        assert stats['draws'][0]['end_time'] == '18:30'
        assert client.put(f'/api/draws/{draw_id}', json={
            'name': 'Nuevo', 'url': 'https://www.instagram.com/p/ABC/',
            'end_date': None, 'tag_count': 2,
        }).status_code == 200
        assert client.get('/api/assignments').json()[0]['draw_tag_count'] == 2


def test_draw_deadline_can_change_while_task_runs_but_runner_fields_cannot(tmp_path):
    app = make_app(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with TestClient(app) as client:
        account = client.post('/api/accounts', json={'name': 'Uno', 'profile_arg': 'cuenta1'}).json()
        draw = client.post('/api/draws', json={
            'name': 'Sorteo', 'url': 'https://www.instagram.com/p/ABC/', 'tag_count': 2,
        }).json()
        client.post('/api/tags', json={'tags': ['@amigo']})
        assignment = client.post('/api/assignments', json={
            'account_id': account['id'], 'draw_id': draw['id'], 'duration_minutes': 5,
            'comments_per_minute': 1, 'tags': ['@amigo'],
        }).json()
        with app.state.db.connect() as con:
            con.execute("INSERT INTO tasks(assignment_id,status,created_at,updated_at) VALUES(?,'running','x','x')", (assignment['id'],))
        payload = {'name': 'Sorteo', 'url': draw['url'], 'tag_count': 2,
                   'end_date': '2030-12-31', 'end_time': '19:00'}
        assert client.put(f"/api/draws/{draw['id']}", json=payload).json()['end_time'] == '19:00'
        assert client.put(f"/api/draws/{draw['id']}", json={**payload, 'tag_count': 3}).status_code == 409
        assert client.put(f"/api/draws/{draw['id']}", json={**payload, 'url': 'https://www.instagram.com/p/DEF/'}).status_code == 409


@pytest.mark.parametrize(('text', 'expected'), [
    ('6681', 6681), ('6.681', 6681), ('6,681', 6681), ('6 681', 6681),
    ('0', 0), ('6,6 mil', None), ('1921 comentarios', None), ('', None),
])
def test_parse_visible_comment_count(text, expected):
    assert parse_comment_count(text) == expected


def test_runner_reads_counter_next_to_comment_icon_without_touching_composer():
    calls = []
    counter = types.SimpleNamespace(text='6681')
    icon = types.SimpleNamespace(find_elements=lambda by, xpath: (
        calls.append(('counter', by, xpath)) or [counter]
    ))
    runner = SeleniumRunner()
    runner.driver = types.SimpleNamespace(find_elements=lambda by, selector: (
        calls.append(('icons', by, selector)) or [icon]
    ))
    assert runner.read_comment_count() == 6681
    assert calls[0][0] == 'icons' and 'aria-label="Comentar"' in calls[0][2]
    assert calls[1][0] == 'counter' and 'following-sibling::span' in calls[1][2]
    assert runner.textarea is None


def test_runner_adapter_keeps_legacy_call_order(monkeypatch):
    calls = []
    driver = types.SimpleNamespace(
        current_url='https://www.instagram.com/p/ABC/',
        page_source='<script>var captchaConfig = {};</script>',
        quit=lambda: calls.append(('quit',)),
    )
    textarea = types.SimpleNamespace(get_property=lambda name: '')
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


def test_pending_text_prevents_typing_or_publishing(monkeypatch):
    calls = []
    textarea = types.SimpleNamespace(get_property=lambda name: 'comentario anterior')
    driver = types.SimpleNamespace(current_url='https://www.instagram.com/p/ABC/', quit=lambda: None)
    monkeypatch.setitem(sys.modules, 'selenium_runner', types.SimpleNamespace(
        acceder_caja=lambda url, profile: (True, driver, textarea),
        comentar_en_post=lambda *args: calls.append(args),
    ))
    runner = SeleniumRunner()
    runner.open('https://www.instagram.com/p/ABC/', 'cuenta1')
    with pytest.raises(PendingCommentError, match='conserva texto'):
        runner.post('nuevo comentario')
    assert calls == []
    runner.close()


def test_stale_textarea_is_relocated_only_before_typing(monkeypatch):
    calls = []

    class OldTextarea:
        def get_property(self, name):
            raise StaleElementReferenceException('elemento reemplazado')

    class NewTextarea:
        tag_name = 'textarea'

        def get_property(self, name):
            return ''

        def get_attribute(self, name):
            return 'Add a comment' if name == 'aria-label' else None

        def is_displayed(self):
            return True

        def is_enabled(self):
            return True

    current = NewTextarea()
    driver = types.SimpleNamespace(
        current_url='https://www.instagram.com/p/ABC/',
        find_elements=lambda by, selector: (calls.append(('find', by, selector)) or [current]),
        quit=lambda: None,
    )
    monkeypatch.setitem(sys.modules, 'selenium_runner', types.SimpleNamespace(
        COMMENT_TEXTAREA_SELECTOR='textarea',
        acceder_caja=lambda url, profile, on_log=None: (True, driver, OldTextarea()),
        comentar_en_post=lambda comment, used_driver, textarea: calls.append(('post', comment, textarea is current)),
    ))
    runner = SeleniumRunner()
    events = []
    runner.set_event_sink(lambda kind, message: events.append((kind, message)))
    runner.open('https://www.instagram.com/p/ABC/', 'cuenta1')
    runner.post('hola @amigo')
    assert calls[-1] == ('post', 'hola @amigo', True)
    assert len([call for call in calls if call[0] == 'find' and call[2] ==
                'textarea, input, [contenteditable="true"], [role="textbox"]']) == 1
    assert events[0][0] == 'selenium_retry'
    runner.close()


def test_relocated_pending_text_still_prevents_post(monkeypatch):
    class OldTextarea:
        def get_property(self, name):
            raise StaleElementReferenceException('elemento reemplazado')

    current = types.SimpleNamespace(
        tag_name='textarea', get_property=lambda name: 'comentario anterior',
        get_attribute=lambda name: 'Add a comment' if name == 'aria-label' else None,
        is_displayed=lambda: True, is_enabled=lambda: True)
    driver = types.SimpleNamespace(
        current_url='https://www.instagram.com/p/ABC/',
        find_elements=lambda by, selector: [current],
        quit=lambda: None,
    )
    posts = []
    monkeypatch.setitem(sys.modules, 'selenium_runner', types.SimpleNamespace(
        COMMENT_TEXTAREA_SELECTOR='textarea',
        acceder_caja=lambda url, profile: (True, driver, OldTextarea()),
        comentar_en_post=lambda *args: posts.append(args),
    ))
    runner = SeleniumRunner()
    runner.open('https://www.instagram.com/p/ABC/', 'cuenta1')
    with pytest.raises(PendingCommentError):
        runner.post('nuevo')
    assert posts == []
    runner.close()


def test_stale_during_typing_is_not_retried(monkeypatch):
    posts = []
    textarea = types.SimpleNamespace(get_property=lambda name: '')
    driver = types.SimpleNamespace(current_url='https://www.instagram.com/p/ABC/', quit=lambda: None)

    def fail_post(*args):
        posts.append(args)
        raise StaleElementReferenceException('durante la escritura')

    monkeypatch.setitem(sys.modules, 'selenium_runner', types.SimpleNamespace(
        acceder_caja=lambda url, profile: (True, driver, textarea),
        comentar_en_post=fail_post,
    ))
    runner = SeleniumRunner()
    runner.open('https://www.instagram.com/p/ABC/', 'cuenta1')
    with pytest.raises(StaleElementReferenceException):
        runner.post('nuevo')
    assert len(posts) == 1
    runner.close()


def test_open_logs_retry_and_keeps_specific_failure(monkeypatch):
    driver = types.SimpleNamespace(current_url='https://www.instagram.com/p/ABC/', quit=lambda: None)

    def fail_open(url, profile, on_log=None):
        on_log('selenium_retry', 'Textarea obsoleto, reintentando')
        on_log('selenium_error', 'StaleElementReferenceException tras 3 intentos')
        return False, driver, None

    monkeypatch.setitem(sys.modules, 'selenium_runner', types.SimpleNamespace(acceder_caja=fail_open))
    runner = SeleniumRunner()
    events = []
    runner.set_event_sink(lambda kind, message: events.append((kind, message)))
    with pytest.raises(RuntimeError, match='StaleElementReferenceException tras 3 intentos'):
        runner.open('https://www.instagram.com/p/ABC/', 'cuenta1')
    assert [event[0] for event in events] == ['selenium_retry', 'selenium_error']
    runner.close()


def test_comment_editor_retry_avoids_page_body_clicks(monkeypatch):
    import selenium_runner as legacy

    calls = []

    class Old:
        def click(self):
            raise StaleElementReferenceException('reemplazado')

    class Fresh:
        def click(self):
            calls.append(('editor_click',))

    old, fresh = Old(), Fresh()
    found = iter((old, fresh))

    class Driver:
        def get(self, url):
            calls.append(('get', url))

        def execute_script(self, script, *args):
            return 'complete' if 'readyState' in script else True

    driver = Driver()
    monkeypatch.setattr(legacy, 'crear_driver', lambda profile: driver)
    monkeypatch.setattr(legacy, 'ready_comment_field', lambda used_driver: next(found))
    monkeypatch.setattr(legacy, 'confirm_comment_field', lambda element: element is fresh)
    monkeypatch.setattr(legacy, 'WebDriverWait', lambda used_driver, timeout: types.SimpleNamespace(
        until=lambda condition: condition(used_driver)))
    monkeypatch.setattr(legacy.time, 'sleep', lambda seconds: None)
    events = []
    success, used_driver, textarea = legacy.acceder_caja(
        'https://www.instagram.com/p/ABC/', 'cuenta1',
        on_log=lambda kind, message: events.append((kind, message)),
    )
    assert success and used_driver is driver and textarea is fresh
    assert calls[0] == ('get', 'https://www.instagram.com/p/ABC/')
    assert calls[-1:] == [('editor_click',)]
    assert events[0][0] == 'selenium_retry'


def test_runner_stops_on_actual_challenge_url(monkeypatch):
    driver = types.SimpleNamespace(current_url='https://www.instagram.com/challenge/', quit=lambda: None)
    monkeypatch.setitem(sys.modules, 'selenium_runner', types.SimpleNamespace(
        acceder_caja=lambda url, profile: (True, driver, object()),
    ))
    runner = SeleniumRunner()
    try:
        with pytest.raises(RuntimeError, match='verificacion manual'):
            runner.open('https://www.instagram.com/p/ABC/', 'cuenta1')
    finally:
        runner.close()


def test_recovery_requires_manual_resume(tmp_path):
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        a = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('A','a','a')").lastrowid
        d = con.execute("INSERT INTO draws(name,url) VALUES('D','https://www.instagram.com/p/ABC/')").lastrowid
        s = con.execute('''INSERT INTO assignments(account_id,draw_id,duration_minutes,comments_per_minute,tag_count,tags_json)
            VALUES(?,?,?,?,?,?)''', (a, d, 1, 1, 1, '["@amigo"]')).lastrowid
        task_id = con.execute("INSERT INTO tasks(assignment_id,status,created_at,updated_at) VALUES(?,'running','x','x')", (s,)).lastrowid
    restarted = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        assert row(con, 'SELECT status FROM tasks WHERE id=?', (task_id,))['status'] == 'running'
    restarted.recover_interrupted()
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


def test_different_profiles_run_together_and_close_on_failure(tmp_path, monkeypatch):
    # A larger configured limit still permits the original parallel behavior.
    monkeypatch.setenv('MAX_CONCURRENT_BROWSERS', '2')
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
            assert task['last_error'].startswith('Comentario - RuntimeError: Sesion vencida')


def test_coordinator_persists_selenium_retry_and_error_type(tmp_path):
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        account = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('A','a','a')").lastrowid
        draw = con.execute("INSERT INTO draws(name,url) VALUES('D','https://www.instagram.com/p/ABC/')").lastrowid
        assignment = con.execute('''INSERT INTO assignments
            (account_id,draw_id,duration_minutes,comments_per_minute,tag_count,tags_json)
            VALUES(?,?,?,?,?,?)''', (account, draw, 1, 1, 1, '["@amigo"]')).lastrowid

    class FakeRunner:
        def set_event_sink(self, sink):
            self.sink = sink

        def open(self, url, profile):
            self.sink('selenium_retry', 'Textarea obsoleto; encontrado de nuevo')

        def post(self, comment):
            raise StaleElementReferenceException('durante escritura')

        def close(self):
            pass

    coordinator = Coordinator(db, FakeRunner)
    task_id = coordinator.create(assignment)
    wait_for(lambda: task_id not in coordinator.threads)
    with db.connect() as con:
        task = row(con, 'SELECT * FROM tasks WHERE id=?', (task_id,))
        kinds = [event['kind'] for event in con.execute('SELECT kind FROM events WHERE task_id=? ORDER BY id', (task_id,))]
    assert task['status'] == 'failed'
    assert task['last_error'].startswith('Comentario - StaleElementReferenceException:')
    assert task['attempts'] == 1 and task['clicked'] == 0
    assert kinds == ['queued', 'running', 'selenium_retry', 'attempt', 'failed']


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


def test_comment_count_refreshes_on_each_start_and_failures_do_not_stop_posts(tmp_path):
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        account = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('A','a','a')").lastrowid
        draw = con.execute("INSERT INTO draws(name,url) VALUES('D','https://www.instagram.com/p/ABC/')").lastrowid
        assignment = con.execute('''INSERT INTO assignments
            (account_id,draw_id,duration_minutes,comments_per_minute,tag_count,tags_json)
            VALUES(?,?,?,?,?,?)''', (account, draw, 1, 1, 1, '["@amigo"]')).lastrowid
    samples = [6681, 6800, None, RuntimeError('DOM cambio')]
    calls = []
    fake_time = [0.0]

    class FakeRunner:
        def open(self, url, profile):
            calls.append('open')

        def read_comment_count(self):
            calls.append('read')
            result = samples.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        def post(self, comment):
            calls.append('post')

        def close(self):
            calls.append('close')

    coordinator = Coordinator(db, FakeRunner, clock=lambda: fake_time[0],
                              sleep=lambda seconds: fake_time.__setitem__(0, fake_time[0] + seconds))
    for expected, event_kind in (
        (6681, 'comment_count_observed'), (6800, 'comment_count_observed'),
        (6800, 'comment_count_unavailable'), (6800, 'comment_count_unavailable'),
    ):
        task_id = coordinator.create(assignment)
        wait_for(lambda: task_id not in coordinator.threads)
        with db.connect() as con:
            measured = row(con, 'SELECT comment_count,comment_count_checked_at FROM draws WHERE id=?', (draw,))
            task = row(con, 'SELECT status,clicked FROM tasks WHERE id=?', (task_id,))
            kinds = [item['kind'] for item in con.execute('SELECT kind FROM events WHERE task_id=? ORDER BY id', (task_id,))]
        assert measured['comment_count'] == expected
        assert measured['comment_count_checked_at'] is not None
        assert task == {'status': 'completed', 'clicked': 1}
        assert event_kind in kinds
    assert calls == ['open', 'read', 'post', 'close'] * 4


def test_unlimited_duration_stops_on_attention_not_elapsed_time(tmp_path):
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        account = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('A','a','a')").lastrowid
        draw = con.execute("INSERT INTO draws(name,url,tag_count) VALUES('D','https://www.instagram.com/p/ABC/',2)").lastrowid
        assignment = con.execute('''INSERT INTO assignments(account_id,draw_id,duration_minutes,comments_per_minute,tag_count,tags_json)
            VALUES(?,?,?,?,?,?)''', (account, draw, 0, 1, 1, '["@uno","@dos"]')).lastrowid
    fake_time = [0.0]
    posted = []

    class FakeRunner:
        def open(self, url, profile):
            pass

        def post(self, comment):
            posted.append(comment)
            if len(posted) == 2:
                raise PendingCommentError('Posible bloqueo')

        def close(self):
            pass

    coordinator = Coordinator(db, FakeRunner, clock=lambda: fake_time[0],
                              sleep=lambda seconds: fake_time.__setitem__(0, fake_time[0] + seconds))
    task_id = coordinator.create(assignment)
    wait_for(lambda: task_id not in coordinator.threads)
    with db.connect() as con:
        task = row(con, 'SELECT * FROM tasks WHERE id=?', (task_id,))
    assert task['status'] == 'paused'
    assert (task['attempts'], task['clicked']) == (2, 1)
    assert task['elapsed_seconds'] >= 60
    assert all('@uno' in comment and '@dos' in comment for comment in posted)


def test_pending_comment_pauses_account_and_queued_tasks(tmp_path):
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        a = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('A','a','a')").lastrowid
        assignment_ids = []
        for index in (1, 2):
            d = con.execute('INSERT INTO draws(name,url) VALUES(?,?)',
                            (f'D{index}', f'https://www.instagram.com/p/{index}/')).lastrowid
            assignment_ids.append(con.execute('''INSERT INTO assignments
                (account_id,draw_id,duration_minutes,comments_per_minute,tag_count,tags_json)
                VALUES(?,?,?,?,?,?)''', (a, d, 1, 2, 1, '["@amigo"]')).lastrowid)

    first_post = threading.Event()
    release = threading.Event()
    fake_time = [0.0]
    posted = []
    closed = []

    class FakeRunner:
        def open(self, url, profile):
            pass

        def post(self, comment):
            if not posted:
                posted.append(comment)
                first_post.set()
                release.wait(2)
            else:
                raise PendingCommentError('La caja de comentarios conserva texto; posible bloqueo')

        def close(self):
            closed.append(True)

    coordinator = Coordinator(db, FakeRunner, clock=lambda: fake_time[0],
                              sleep=lambda seconds: fake_time.__setitem__(0, fake_time[0] + seconds))
    first = coordinator.create(assignment_ids[0])
    assert first_post.wait(2)
    second = coordinator.create(assignment_ids[1])
    release.set()
    wait_for(lambda: not coordinator.threads)

    with db.connect() as con:
        account = row(con, 'SELECT * FROM accounts WHERE id=?', (a,))
        current = row(con, 'SELECT * FROM tasks WHERE id=?', (first,))
        queued = row(con, 'SELECT * FROM tasks WHERE id=?', (second,))
        event = row(con, "SELECT kind FROM events WHERE task_id=? AND kind='blocked_suspected'", (first,))
    assert account['attention_required'] == 1
    assert current['status'] == queued['status'] == 'paused'
    assert (current['attempts'], current['clicked'], current['failures']) == (2, 1, 0)
    assert queued['attempts'] == 0
    assert event['kind'] == 'blocked_suspected'
    assert len(posted) == 1 and closed == [True]
    with pytest.raises(ValueError, match='requiere revision'):
        coordinator.control(first, 'resume')
    with pytest.raises(ValueError, match='requiere revision'):
        coordinator.create(assignment_ids[1])

    app = make_app(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with TestClient(app) as client:
        cleared = client.post(f'/api/accounts/{a}/clear-attention')
        assert cleared.status_code == 200
        assert cleared.json()['attention_required'] == 0
