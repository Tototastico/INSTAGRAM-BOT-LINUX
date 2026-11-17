from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest
from selenium.common.exceptions import SessionNotCreatedException

import selenium_runner
from webapp.startup_health import startup_snapshot
from webapp.profile_health import preference_warning, check_preferences_size, ProfilePreferencesTooLarge


def test_startup_snapshot_reports_safe_resource_fields(tmp_path):
    proc = tmp_path / 'proc'
    group = tmp_path / 'cgroup' / 'system.slice' / 'bot.service'
    (proc / 'self').mkdir(parents=True)
    group.mkdir(parents=True)
    (proc / 'meminfo').write_text('MemAvailable: 2621440 kB\nSwapFree: 1572864 kB\n')
    (proc / 'self' / 'cgroup').write_text('0::/system.slice/bot.service\n')
    (group / 'memory.current').write_text(str(1200 * 1024 * 1024))
    (group / 'memory.max').write_text(str(3072 * 1024 * 1024))
    (group / 'memory.events').write_text('oom 3\noom_kill 1\n')
    (group / 'pids.current').write_text('144')
    (group / 'pids.max').write_text('512')
    metrics = startup_snapshot('private-account', proc, tmp_path / 'cgroup',
                               tmp_path, tmp_path, platform_name='posix')
    assert metrics['mem_available_mb'] == 2560
    assert metrics['swap_free_mb'] == 1536
    assert metrics['cgroup_memory_mb'] == 1200
    assert metrics['cgroup_limit_mb'] == 3072
    assert metrics['cgroup_oom_kills'] == 1
    assert metrics['cgroup_pids'] == 144
    assert 'private-account' not in str(metrics)


def test_chrome_startup_is_serialized_across_accounts(tmp_path, monkeypatch):
    profiles = tmp_path / 'profiles'
    profiles.mkdir()
    monkeypatch.setenv('BOT_ACCOUNTS_DIR', str(profiles))
    monkeypatch.setenv('HEADLESS', 'true')
    monkeypatch.setattr(selenium_runner, 'chrome_binary_and_major', lambda: ('/fake/chrome', 157))
    guard = threading.Lock()
    active = 0
    maximum = 0

    def fake_chrome(**kwargs):
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.05)
        with guard:
            active -= 1
        return object()

    monkeypatch.setattr(selenium_runner.uc, 'Chrome', fake_chrome)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(selenium_runner.crear_driver, ('cuenta1', 'cuenta2')))
    assert len(results) == 2
    assert maximum == 1


def test_failed_start_attaches_resource_evidence_without_retry(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_ACCOUNTS_DIR', str(tmp_path / 'profiles'))
    monkeypatch.setenv('HEADLESS', 'true')
    monkeypatch.setattr(selenium_runner, 'chrome_binary_and_major', lambda: ('/fake/chrome', 157))
    monkeypatch.setattr(selenium_runner, 'startup_snapshot', lambda profile: {
        'mem_available_mb': 900, 'profile_chrome_running': False})
    attempts = []

    def fail(**kwargs):
        attempts.append(kwargs)
        raise SessionNotCreatedException('chrome not reachable')

    monkeypatch.setattr(selenium_runner.uc, 'Chrome', fail)
    try:
        selenium_runner.crear_driver('cuenta1')
        assert False, 'Expected SessionNotCreatedException'
    except SessionNotCreatedException as exc:
        assert exc.bot_control_state == {'mem_available_mb': 900, 'profile_chrome_running': False}
    assert len(attempts) == 1


def test_oversized_preferences_stop_before_chrome_without_reading_profile(tmp_path, monkeypatch):
    profiles = tmp_path / 'profiles'
    preferences = profiles / 'cuenta1' / 'Default' / 'Preferences'
    preferences.parent.mkdir(parents=True)
    with preferences.open('wb') as stream:
        stream.seek((selenium_runner.PREFERENCES_MAX_MB + 1) * 1024 * 1024 - 1)
        stream.write(b'x')
    monkeypatch.setenv('BOT_ACCOUNTS_DIR', str(profiles))
    monkeypatch.setenv('HEADLESS', 'true')
    monkeypatch.setattr(selenium_runner, 'chrome_binary_and_major', lambda: ('/fake/chrome', 157))
    monkeypatch.setattr(selenium_runner.uc, 'Chrome',
                        lambda **kwargs: pytest.fail('Chrome must not start with oversized Preferences'))
    with pytest.raises(selenium_runner.ProfilePreferencesTooLarge, match='limite preventivo') as caught:
        selenium_runner.crear_driver('cuenta1')
    assert preferences.stat().st_size == 65 * 1024 * 1024
    assert str(profiles) not in str(caught.value)


def test_preferences_warning_uses_only_file_size_and_never_changes_profile(tmp_path):
    profile = tmp_path / 'private-account'
    preferences = profile / 'Default' / 'Preferences'
    preferences.parent.mkdir(parents=True)
    preferences.write_text('{"token":"private"}')
    original = preferences.read_bytes()
    assert preference_warning(profile) is None
    assert check_preferences_size(profile) == len(original)
    with preferences.open('wb') as stream:
        stream.truncate(9 * 1024 * 1024)
    assert preference_warning(profile) == {'state': 'growing', 'size_mb': 9.0}
    with preferences.open('wb') as stream:
        stream.truncate(65 * 1024 * 1024)
    assert preference_warning(profile) == {'state': 'blocked', 'size_mb': 65.0}
    with pytest.raises(ProfilePreferencesTooLarge) as caught:
        check_preferences_size(profile)
    assert 'private-account' not in str(caught.value)
    assert 'token' not in str(caught.value)
    assert preferences.stat().st_size == 65 * 1024 * 1024
