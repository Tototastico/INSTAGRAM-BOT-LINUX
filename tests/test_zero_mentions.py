import pytest
from fastapi.testclient import TestClient

from webapp.api import make_app
from webapp.runner import compose_comment


def test_zero_mentions_use_only_draw_text():
    assert compose_comment([], 0, '  BMW  ') == 'BMW'
    assert compose_comment(['@ignored'], 0, 'BMW') == 'BMW'
    with pytest.raises(ValueError, match='texto adicional'):
        compose_comment([], 0, '   ')
    with pytest.raises(ValueError, match='etiqueta'):
        compose_comment([], 1, 'BMW')


def test_zero_mention_draw_requires_text_and_assignment_needs_no_tags(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_ACCOUNTS_DIR', str(tmp_path / 'profiles'))
    app = make_app(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with TestClient(app) as client:
        draw_payload = {'name': 'Palabra BMW', 'url': 'https://www.instagram.com/p/ABC/',
                        'tag_count': 0, 'extra_text': 'BMW'}
        assert client.post('/api/draws', json={**draw_payload, 'extra_text': '   '}).status_code == 422
        assert client.post('/api/draws', json={**draw_payload, 'extra_text': '😀'}).status_code == 422
        draw = client.post('/api/draws', json=draw_payload).json()
        assert client.put(f"/api/draws/{draw['id']}", json={
            'name': draw['name'], 'url': draw['url'], 'tag_count': 0}).json()['extra_text'] == 'BMW'
        account = client.post('/api/accounts', json={'name': 'Cuenta', 'profile_arg': 'cuenta-test'}).json()
        assignment_payload = {'account_id': account['id'], 'draw_id': draw['id'],
                              'duration_minutes': 1, 'comments_per_minute': 1, 'tags': []}
        assignment = client.post('/api/assignments', json=assignment_payload)
        assert assignment.status_code == 201
        assert client.get('/api/assignments').json()[0]['tags'] == []
        assert client.put(f"/api/assignments/{assignment.json()['id']}", json=assignment_payload).status_code == 200
        with app.state.db.connect() as con:
            task_id = con.execute('''INSERT INTO tasks(assignment_id,account_id,draw_id,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?)''', (assignment.json()['id'], account['id'], draw['id'], 'failed', 'x', 'x')).lastrowid
        task = app.state.coordinator._load_task(task_id)
        assert compose_comment([], task['tag_count'], task['extra_text']) == 'BMW'


def test_positive_mentions_still_require_tags(tmp_path, monkeypatch):
    monkeypatch.setenv('BOT_ACCOUNTS_DIR', str(tmp_path / 'profiles'))
    app = make_app(tmp_path / 'bot.sqlite3', tmp_path / 'missing.json')
    with TestClient(app) as client:
        draw = client.post('/api/draws', json={
            'name': 'Con etiqueta', 'url': 'https://www.instagram.com/p/ABC/',
            'tag_count': 1}).json()
        account = client.post('/api/accounts', json={'name': 'Cuenta', 'profile_arg': 'cuenta-test'}).json()
        response = client.post('/api/assignments', json={
            'account_id': account['id'], 'draw_id': draw['id'],
            'duration_minutes': 1, 'comments_per_minute': 1, 'tags': []})
        assert response.status_code == 409
