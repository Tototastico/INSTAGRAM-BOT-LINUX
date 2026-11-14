from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp.api import make_app
from webapp.db import profile_path
from webapp.settings import accounts_dir, db_path, max_browsers
from webapp import chrome_binary


def test_runtime_paths_and_profile_validation(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_DATA_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('BOT_ACCOUNTS_DIR', str(tmp_path / 'profiles'))
    monkeypatch.delenv('BOT_DB_PATH', raising=False)
    assert db_path() == tmp_path / 'state' / 'bot.sqlite3'
    assert profile_path('accounts/cuenta1') == str(accounts_dir() / 'cuenta1')
    assert profile_path('cuenta1') == profile_path('accounts/cuenta1')
    for invalid in ('../other', '/tmp/profile', r'C:\Users\profile', 'accounts/a/b'):
        with pytest.raises(ValueError):
            profile_path(invalid)


def test_health_and_spa_start_without_browser(tmp_path):
    app = make_app(db_path=tmp_path / 'bot.sqlite3')
    with TestClient(app) as client:
        assert client.get('/api/health').json() == {'status': 'ok'}
        assert client.get('/api/overview').status_code == 200
        assert client.get('/').status_code in (200, 404)  # dist is optional in source checkouts
        assert client.get('/api/missing').status_code == 404


def test_chrome_version_from_executable(tmp_path, monkeypatch):
    fake = tmp_path / 'chrome'
    fake.write_text('')
    monkeypatch.setenv('CHROME_BINARY', str(fake))
    class Result:
        stdout = 'Google Chrome 131.0.6778.0'
        stderr = ''
    monkeypatch.setattr(chrome_binary.subprocess, 'run', lambda *args, **kwargs: Result())
    assert chrome_binary.chrome_binary_and_major() == (str(fake.resolve()), 131)
    monkeypatch.setenv('MAX_CONCURRENT_BROWSERS', '0')
    with pytest.raises(ValueError):
        max_browsers()
