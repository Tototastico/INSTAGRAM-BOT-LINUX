import types

from webapp.post_url import normalize_post_url


def test_only_instagram_reel_path_is_normalized():
    source = 'https://www.instagram.com/reel/Df-UfNth8d6/?jplx=cXkzaGhlOWNtdmJk'
    assert normalize_post_url(source) == 'https://www.instagram.com/p/Df-UfNth8d6/?jplx=cXkzaGhlOWNtdmJk'
    assert normalize_post_url('https://instagram.com/p/ABC/') == 'https://instagram.com/p/ABC/'
    assert normalize_post_url('https://www.instagram.com/reels/ABC/') == 'https://www.instagram.com/reels/ABC/'
    assert normalize_post_url('https://example.com/reel/ABC/') == 'https://example.com/reel/ABC/'


def test_existing_reel_draw_uses_post_route_without_real_chrome(monkeypatch):
    import selenium_runner

    calls = []

    class Editor:
        def click(self):
            pass

    editor = Editor()

    class Driver:
        def get(self, url):
            calls.append(url)

        def execute_script(self, script, *args):
            return 'complete' if 'readyState' in script else True

    driver = Driver()
    monkeypatch.setattr(selenium_runner, 'crear_driver', lambda profile: driver)
    monkeypatch.setattr(selenium_runner, 'ready_comment_field', lambda used: editor)
    monkeypatch.setattr(selenium_runner, 'confirm_comment_field', lambda element: True)
    monkeypatch.setattr(selenium_runner, 'WebDriverWait', lambda used, seconds: types.SimpleNamespace(
        until=lambda condition: condition(used)))
    success, _, _ = selenium_runner.acceder_caja(
        'https://www.instagram.com/reel/ABC/?jplx=public', 'cuenta1')
    assert success
    assert calls == ['https://www.instagram.com/p/ABC/?jplx=public']
