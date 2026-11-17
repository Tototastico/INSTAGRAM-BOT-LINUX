from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementNotInteractableException, SessionNotCreatedException

from webapp.api import make_app
from webapp.db import Database, now
from webapp.diagnostics import DiagnosticStore, safe_exception_message, safe_url
from webapp.settings import validate_visual_environment
from webapp.runner import PendingCommentError


class Element:
    def is_displayed(self):
        return True

    def is_enabled(self):
        return True


class Browser:
    title = 'Instagram'

    def __init__(self, url):
        self.current_url = url
        self.screenshots = 0

    def execute_script(self, script):
        return False if 'const body' in script else 'complete'

    def find_elements(self, by, selector):
        if 'password' in selector or 'dialog' in selector:
            return []
        return []

    def save_screenshot(self, path):
        self.screenshots += 1
        with open(path, 'wb') as image:
            image.write(b'\x89PNG\r\n\x1a\nprivate image')
        return True


def seeded_database(tmp_path):
    db = Database(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with db.connect() as con:
        account = con.execute("INSERT INTO accounts(name,profile_arg,profile_path) VALUES('A','a','a')").lastrowid
        draw = con.execute("INSERT INTO draws(name,url) VALUES('D','https://www.instagram.com/p/ABC/')").lastrowid
        assignment = con.execute('''INSERT INTO assignments(account_id,draw_id,duration_minutes,
            comments_per_minute,tag_count,tags_json) VALUES(?,?,?,?,?,?)''',
            (account, draw, 1, 1, 1, '["@test"]')).lastrowid
        task = con.execute('''INSERT INTO tasks(assignment_id,account_id,draw_id,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?)''', (assignment, account, draw, 'failed', now(), now())).lastrowid
        other = con.execute('''INSERT INTO tasks(assignment_id,account_id,draw_id,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?)''', (assignment, account, draw, 'failed', now(), now())).lastrowid
    return db, task, other, account


def test_failure_capture_is_private_sanitized_and_bound_to_task(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'private-debug'))
    db, task, other, account = seeded_database(tmp_path)
    store = DiagnosticStore(db)
    browser = Browser('https://www.instagram.com/p/ABC/?token=secret#private')
    diagnostic_id = store.record(task, account, 'comment_box_lookup', TimeoutException('token=secret'), browser)
    item = store.for_task(task)[0]
    assert item['id'] == diagnostic_id
    assert item['category'] == 'selector_missing'
    assert item['page_url'] == 'https://www.instagram.com/p/ABC/'
    assert 'secret' not in str(item)
    assert item['has_screenshot'] == 1
    assert browser.screenshots == 1
    assert store.screenshot(task, diagnostic_id).is_file()
    assert store.screenshot(other, diagnostic_id) is None


def test_webdriver_message_and_operation_are_saved_with_secrets_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'debug'))
    db, task, _, account = seeded_database(tmp_path)
    error = TimeoutException(
        'unknown error during click\nURL https://www.instagram.com/p/ABC/?token=secret\n'
        'Cookie: sessionid=private\nAuthorization: Bearer private')
    error.bot_operation = 'comment_field.click'
    error.bot_condition = 'editor reconocido visible y habilitado'
    DiagnosticStore(db).record(task, account, 'comment_box_lookup', error,
                               Browser('https://www.instagram.com/p/ABC/'))
    item = DiagnosticStore(db).for_task(task)[0]
    assert item['operation'] == 'comment_field.click'
    assert item['condition'] == 'editor reconocido visible y habilitado'
    assert 'unknown error during click' in item['error_message']
    assert 'https://www.instagram.com/p/ABC/' in item['error_message']
    assert 'secret' not in item['error_message']
    assert 'private' not in item['error_message']
    assert 'sessionid' not in item['error_message']
    assert 'Authorization' not in item['error_message']
    assert 'secret' not in safe_exception_message(error)


def test_login_skips_capture_and_retention_removes_old_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'debug'))
    monkeypatch.setenv('BOT_DEBUG_RETENTION_DAYS', '1')
    db, task, _, account = seeded_database(tmp_path)
    store = DiagnosticStore(db)
    login = Browser('https://www.instagram.com/accounts/login/?next=%2Fp%2FABC')
    login_id = store.record(task, account, 'comment_box_lookup', TimeoutException(), login)
    assert login.screenshots == 0
    assert store.for_task(task)[0]['category'] == 'session'
    assert store.screenshot(task, login_id) is None
    post = Browser('https://www.instagram.com/p/ABC/')
    old_id = store.record(task, account, 'comment_box_lookup', TimeoutException(), post)
    image = store.screenshot(task, old_id)
    with db.connect() as con:
        con.execute('UPDATE task_diagnostics SET created_at=? WHERE id=?',
                    ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(), old_id))
    store.prune()
    assert not image.exists()
    assert old_id not in [item['id'] for item in store.for_task(task)]


def test_pending_comment_pause_keeps_private_screenshot_only_on_post(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'private-debug'))
    db, task, other, account = seeded_database(tmp_path)
    store = DiagnosticStore(db)
    browser = Browser('https://www.instagram.com/p/ABC/?token=private')
    diagnostic_id = store.record(task, account, 'comment_box_pending_check',
                                 PendingCommentError('Comentario pendiente'), browser)
    item = store.for_task(task)[0]
    assert item['category'] == 'pending_comment'
    assert item['page_url'] == 'https://www.instagram.com/p/ABC/'
    assert item['has_screenshot'] == 1
    assert browser.screenshots == 1
    assert store.screenshot(other, diagnostic_id) is None
    login = Browser('https://www.instagram.com/accounts/login/?token=private')
    store.record(task, account, 'session_check', PendingCommentError('Sesion requerida'), login)
    assert login.screenshots == 0


def test_chrome_start_failure_reports_resource_snapshot_without_screenshot(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'debug'))
    db, task, _, account = seeded_database(tmp_path)
    error = SessionNotCreatedException('chrome not reachable at 127.0.0.1:60161')
    error.bot_operation = 'crear_driver'
    error.bot_control_state = {'mem_available_mb': 900, 'tmp_free_mb': 14000,
                               'cgroup_oom_kills': 2, 'profile_chrome_running': False,
                               'secret': 'must not be stored'}
    DiagnosticStore(db).record(task, account, 'chrome_start', error)
    item = DiagnosticStore(db).for_task(task)[0]
    assert item['category'] == 'browser_start_failed'
    assert item['has_screenshot'] == 0
    assert 'mem_available_mb' in item['control_state']
    assert 'secret' not in str(item)


def test_oversized_preferences_have_specific_private_diagnostic(tmp_path, monkeypatch):
    from selenium_runner import ProfilePreferencesTooLarge

    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'debug'))
    db, task, _, account = seeded_database(tmp_path)
    error = ProfilePreferencesTooLarge('Preferences del perfil ocupa 3072 MB; limite preventivo 64 MB.')
    error.bot_safe_message = str(error)
    DiagnosticStore(db).record(task, account, 'chrome_start', error)
    item = DiagnosticStore(db).for_task(task)[0]
    assert item['category'] == 'profile_preferences_oversized'
    assert item['has_screenshot'] == 0
    assert '3072 MB' in item['error_message']


def test_login_modal_on_post_url_skips_capture(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'debug'))
    db, task, _, account = seeded_database(tmp_path)

    class LoginModal(Browser):
        def find_elements(self, by, selector):
            if 'password' in selector:
                return [Element()]
            return []

    browser = LoginModal('https://www.instagram.com/p/ABC/')
    item_id = DiagnosticStore(db).record(task, account, 'comment_box_lookup', TimeoutException(), browser)
    item = DiagnosticStore(db).for_task(task)[0]
    assert item['id'] == item_id and item['category'] == 'session'
    assert item['has_screenshot'] == 0 and browser.screenshots == 0


def test_non_selenium_error_keeps_metadata_without_screenshot(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'debug'))
    db, task, _, account = seeded_database(tmp_path)
    browser = Browser('https://www.instagram.com/p/ABC/')
    item_id = DiagnosticStore(db).record(task, account, 'navigation', RuntimeError('password=secret'), browser)
    item = DiagnosticStore(db).for_task(task)[0]
    assert item['id'] == item_id and item['has_screenshot'] == 0
    assert browser.screenshots == 0
    assert 'secret' not in str(item)


def test_diagnostic_api_requires_admin_session_and_never_returns_image_for_other_task(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'debug'))
    from webapp.visual_auth import password_hash
    monkeypatch.setenv('BOT_PUBLIC_ORIGIN', 'https://bot.example.test')
    monkeypatch.setenv('BOT_VISUAL_ADMIN_PASSWORD_HASH', password_hash('test-password'))
    db, task, other, account = seeded_database(tmp_path)
    diagnostic_id = DiagnosticStore(db).record(task, account, 'comment_box_lookup', TimeoutException(),
                                            Browser('https://www.instagram.com/p/ABC/'))
    app = make_app(db_path=db.path, legacy_config=tmp_path / 'missing.json')
    with TestClient(app, base_url='https://bot.example.test') as client:
        endpoint = f'/api/tasks/{task}/diagnostics'
        assert client.get(endpoint).status_code == 401
        assert client.get(endpoint, headers={'X-Diagnostics-Token': 'test-only-token'}).status_code == 401
        assert client.post('/api/visual/auth/login', json={'password': 'test-password'},
                           headers={'Origin': 'https://bot.example.test'}).status_code == 200
        response = client.get(endpoint)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['items'][0]['id'] == diagnostic_id
        assert client.get(f'/api/tasks/{other}/diagnostics/{diagnostic_id}/screenshot').status_code == 404
        image = client.get(f'/api/tasks/{task}/diagnostics/{diagnostic_id}/screenshot')
        assert image.status_code == 200 and image.content.startswith(b'\x89PNG')


def test_visual_mode_needs_xvfb_authority_and_headless_does_not(tmp_path, monkeypatch):
    authority = tmp_path / '.Xauthority'
    authority.write_bytes(b'fake-test-authority')
    with pytest.raises(RuntimeError, match='DISPLAY'):
        validate_visual_environment('posix', {'XAUTHORITY': str(authority)})
    with pytest.raises(RuntimeError, match='XAUTHORITY'):
        validate_visual_environment('posix', {'DISPLAY': ':99'})
    validate_visual_environment('posix', {'DISPLAY': ':99', 'XAUTHORITY': str(authority)})
    monkeypatch.setenv('HEADLESS', 'true')
    from webapp.settings import headless
    assert headless() is True
    monkeypatch.setenv('HEADLESS', 'false')
    assert headless() is False
    assert safe_url('https://www.instagram.com/p/ABC/?secret=1') == 'https://www.instagram.com/p/ABC/'


def test_comment_box_timeout_reports_exact_stage_without_real_instagram(monkeypatch):
    import selenium_runner

    class Driver:
        def get(self, url): pass
        def maximize_window(self): pass
        def execute_script(self, script, *args): pass
        def find_element(self, by, value): return self
        def click(self): pass

    class Wait:
        def __init__(self, driver, seconds): pass
        def until(self, condition):
            if getattr(condition, '__name__', '') == 'ready_comment_field':
                raise TimeoutException('private-url?token=secret')
            return True

    monkeypatch.setattr(selenium_runner, 'crear_driver', lambda profile: Driver())
    monkeypatch.setattr(selenium_runner, 'WebDriverWait', Wait)
    monkeypatch.setattr(selenium_runner.time, 'sleep', lambda seconds: None)
    stages, failures, events = [], [], []
    success, driver, textarea = selenium_runner.acceder_caja(
        'https://www.instagram.com/p/ABC/', 'cuenta1',
        on_stage=stages.append,
        on_diagnostic=lambda stage, exc, driver, selector: failures.append((stage, type(exc).__name__, selector)),
        on_log=lambda kind, message: events.append(message),
    )
    assert not success and textarea is None
    assert stages[-1] == 'comment_box_lookup'
    assert failures[0][0:2] == ('comment_box_lookup', 'TimeoutException')
    assert 'textarea' in failures[0][2]
    assert 'secret' not in str(events)


def test_page_ready_failure_records_exact_operation_and_condition(monkeypatch):
    import selenium_runner

    class Driver:
        def get(self, url): pass
        def execute_script(self, script):
            raise WebDriverException('Chrome rejected readyState command')

    monkeypatch.setattr(selenium_runner, 'crear_driver', lambda profile: Driver())
    failures = []
    success, _, _ = selenium_runner.acceder_caja(
        'https://www.instagram.com/p/ABC/', 'cuenta1',
        on_diagnostic=lambda stage, exc, driver, selector: failures.append(
            (stage, exc.bot_operation, exc.bot_condition, selector, str(exc))))
    assert not success
    assert failures[0][0:3] == ('page_ready', 'document.readyState', 'document.readyState == complete')
    assert failures[0][3] == ''
    assert 'Chrome rejected readyState command' in failures[0][4]


def test_wrong_comment_field_is_never_typed_into(monkeypatch):
    import selenium_runner

    class WrongField:
        def __init__(self): self.typed = []
        def send_keys(self, value): self.typed.append(value)

    field = WrongField()
    monkeypatch.setattr(selenium_runner, 'confirm_comment_field', lambda element: False)
    failures = []
    with pytest.raises(ElementNotInteractableException):
        selenium_runner.comentar_en_post(
            'texto de prueba', object(), field,
            on_diagnostic=lambda stage, exc, driver, selector: failures.append(
                (stage, exc.bot_operation)))
    assert field.typed == []
    assert failures == [('comment_typing', 'comment_field.confirm')]


def test_disabled_publish_control_has_precise_private_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'debug'))
    db, task, _, account = seeded_database(tmp_path)
    error = TimeoutException('button stayed disabled')
    error.bot_operation = 'publish_button.lookup'
    error.bot_condition = 'un unico boton Post/Publicar visible y habilitado'
    error.bot_control_state = {'editor_matches': 1, 'button_matches': 1,
                               'visible': 1, 'enabled': 0, 'stale_references': 0,
                               'ambiguous': False, 'scope': 'form'}
    error.bot_control_structure = '<form><textarea aria-label="[comentario]" /><div role="button">post</div></form>'
    DiagnosticStore(db).record(task, account, 'publish_button_lookup', error,
                               Browser('https://www.instagram.com/p/ABC/'),
                               'button, [role="button"], input[type="submit"]')
    item = DiagnosticStore(db).for_task(task)[0]
    assert item['category'] == 'not_interactable'
    assert '"enabled": 0' in item['control_state']
    assert '[comentario]' in item['control_structure']


@pytest.mark.parametrize(('state', 'category'), [
    ({'editor_matches': 1, 'button_matches': 0, 'stale_references': 0}, 'selector_missing'),
    ({'editor_matches': 1, 'button_matches': 1, 'visible': 0}, 'not_visible'),
    ({'editor_matches': 1, 'button_matches': 0, 'stale_references': 2}, 'stale_reference'),
    ({'editor_matches': 1, 'button_matches': 2, 'ambiguous': True}, 'ambiguous_control'),
    ({'editor_matches': 0, 'button_matches': 0}, 'editor_changed'),
])
def test_publish_lookup_classifies_control_state(tmp_path, monkeypatch, state, category):
    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'debug'))
    db, task, _, account = seeded_database(tmp_path)
    error = TimeoutException('unresolved control')
    error.bot_operation = 'publish_button.lookup'
    error.bot_control_state = state
    DiagnosticStore(db).record(task, account, 'publish_button_lookup', error,
                               Browser('https://www.instagram.com/p/ABC/'),
                               'button, [role="button"], input[type="submit"]')
    assert DiagnosticStore(db).for_task(task)[0]['category'] == category


def test_visible_chrome_options_do_not_enable_headless(tmp_path, monkeypatch):
    import selenium_runner

    monkeypatch.setenv('BOT_ACCOUNTS_DIR', str(tmp_path / 'profiles'))
    monkeypatch.setenv('HEADLESS', 'false')
    monkeypatch.setattr(selenium_runner, 'chrome_binary_and_major', lambda: ('/fake/chrome', 157))
    checked = []
    monkeypatch.setattr(selenium_runner, 'validate_visual_environment', lambda: checked.append(True))
    received = {}
    monkeypatch.setattr(selenium_runner.uc, 'Chrome', lambda **kwargs: received.update(kwargs) or object())
    selenium_runner.crear_driver('cuenta1')
    assert checked == [True]
    assert '--headless=new' not in received['options'].arguments


def test_coordinator_links_selenium_failure_to_correct_task(tmp_path, monkeypatch):
    import time
    from webapp.coordinator import Coordinator

    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'debug'))
    db, task, other, account = seeded_database(tmp_path)
    browser = Browser('https://www.instagram.com/p/ABC/')

    class FailingRunner:
        def set_diagnostic_sink(self, sink): self.sink = sink
        def set_stage_sink(self, sink): self.stage = sink
        def open(self, url, profile):
            self.stage('comment_box_lookup')
            self.sink('comment_box_lookup', TimeoutException('secret=hidden'), browser, 'textarea')
            raise RuntimeError('No se encontro la caja')
        def close(self): pass

    with db.connect() as con:
        con.execute("UPDATE tasks SET status='queued' WHERE id=?", (task,))
    coordinator = Coordinator(db, FailingRunner)
    coordinator.dispatch()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not coordinator.diagnostics.for_task(task):
        time.sleep(0.01)
    assert len(coordinator.diagnostics.for_task(task)) == 1
    assert coordinator.diagnostics.for_task(other) == []
    coordinator.shutdown()


def test_paused_task_records_diagnostic_and_capture_before_browser_closes(tmp_path, monkeypatch):
    import time
    from webapp.coordinator import Coordinator

    monkeypatch.setenv('BOT_DEBUG_DIR', str(tmp_path / 'debug'))
    db, task, other, account = seeded_database(tmp_path)
    browser = Browser('https://www.instagram.com/p/ABC/?token=private')

    class PausingRunner:
        driver = browser

        def open(self, url, profile):
            pass

        def post(self, comment):
            raise PendingCommentError('Comentario pendiente')

        def close(self):
            pass

    with db.connect() as con:
        con.execute("UPDATE tasks SET status='queued' WHERE id=?", (task,))
    coordinator = Coordinator(db, PausingRunner)
    coordinator.dispatch()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and task in coordinator.threads:
        time.sleep(0.01)
    with db.connect() as con:
        status = con.execute('SELECT status FROM tasks WHERE id=?', (task,)).fetchone()[0]
        stage = con.execute('SELECT stage FROM task_runtime_state WHERE task_id=?', (task,)).fetchone()[0]
    evidence = coordinator.diagnostics.for_task(task)
    assert status == 'paused'
    assert stage == 'paused'
    assert len(evidence) == 1
    assert evidence[0]['category'] == 'pending_comment'
    assert evidence[0]['has_screenshot'] == 1
    assert coordinator.diagnostics.for_task(other) == []
    coordinator.shutdown()
