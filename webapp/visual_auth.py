"""Short lived, browser bound authorization for remote Chrome administration."""
import hashlib
import hmac
import os
import secrets
import threading
import time
from urllib.parse import urlsplit


COOKIE = 'bot_visual_session'


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 310_000)
    return f'pbkdf2_sha256:310000:{salt.hex()}:{digest.hex()}'


def verify_password(password, encoded):
    try:
        algorithm, rounds, salt, expected = encoded.split(':')
        if algorithm != 'pbkdf2_sha256' or int(rounds) < 310_000:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


class VisualAuth:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.sessions = {}
        self.lock = threading.RLock()
        self.failures = {}

    @staticmethod
    def origin():
        value = os.environ.get('BOT_PUBLIC_ORIGIN', '').rstrip('/')
        parsed = urlsplit(value)
        return value if parsed.scheme == 'https' and parsed.netloc and not parsed.path else ''

    def enabled(self):
        return bool(self.origin() and os.environ.get('BOT_VISUAL_ADMIN_PASSWORD_HASH'))

    def origin_ok(self, origin):
        return bool(self.origin() and hmac.compare_digest(origin or '', self.origin()))

    def login(self, password, client_key):
        encoded = os.environ.get('BOT_VISUAL_ADMIN_PASSWORD_HASH', '')
        with self.lock:
            until, count = self.failures.get(client_key, (0, 0))
            if until > self.clock():
                return None
            if not encoded or not verify_password(password, encoded):
                count += 1
                self.failures[client_key] = (self.clock() + (60 if count >= 5 else 0), count)
                return None
            self.failures.pop(client_key, None)
            session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.sessions[session_id] = (self.clock() + 1800, csrf)
            return session_id, csrf

    def check(self, session_id, csrf=None, renew=True):
        with self.lock:
            item = self.sessions.get(session_id or '')
            if not item or item[0] <= self.clock():
                self.sessions.pop(session_id or '', None)
                return False
            if csrf is not None and not hmac.compare_digest(csrf, item[1]):
                return False
            if renew:
                self.sessions[session_id] = (self.clock() + 1800, item[1])
            return True

    def csrf(self, session_id):
        with self.lock:
            return self.sessions[session_id][1] if self.check(session_id) else None

    def logout(self, session_id):
        with self.lock:
            self.sessions.pop(session_id or '', None)
