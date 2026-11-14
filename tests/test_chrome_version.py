import pytest
from webapp.db import profile_path

import selenium_runner
from webapp import chrome_binary


def test_driver_uses_detected_browser_and_major(monkeypatch):
    received = {}
    sentinel = object()

    monkeypatch.setattr(selenium_runner, 'chrome_binary_and_major',
                        lambda: (r'C:\Program Files\Google\Chrome\Application\chrome.exe', 155))

    def fake_chrome(**kwargs):
        received.update(kwargs)
        return sentinel

    monkeypatch.setattr(selenium_runner.uc, 'Chrome', fake_chrome)
    assert selenium_runner.crear_driver('accounts/cuenta1') is sentinel
    assert received['version_main'] == 155
    assert received['browser_executable_path'].endswith('chrome.exe')
    assert f'--user-data-dir={profile_path("cuenta1")}' in received['options'].arguments
    assert '--no-sandbox' not in received['options'].arguments
    assert '--headless=new' in received['options'].arguments


def test_invalid_browser_override_fails_clearly(monkeypatch):
    monkeypatch.setenv('INSTAGRAM_BOT_CHROME_BINARY', r'C:\no-existe\chrome.exe')
    with pytest.raises(RuntimeError, match='CHROME_BINARY'):
        chrome_binary.chrome_binary_and_major()
