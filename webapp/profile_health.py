"""Read-only size checks for Chrome preferences; never inspect profile contents."""
from pathlib import Path

PREFERENCES_WARN_MB = 8
PREFERENCES_MAX_MB = 64


class ProfilePreferencesTooLarge(RuntimeError):
    """Chrome must not load a profile whose preferences could exhaust RAM."""


def preferences_size(profile):
    try:
        return (Path(profile) / 'Default' / 'Preferences').stat().st_size
    except FileNotFoundError:
        return 0


def check_preferences_size(profile):
    size = preferences_size(profile)
    if size > PREFERENCES_MAX_MB * 1024 * 1024:
        error = ProfilePreferencesTooLarge(
            f'Preferences del perfil ocupa {size // (1024 * 1024)} MB; '
            f'limite preventivo {PREFERENCES_MAX_MB} MB. No se abrio Chrome ni se modifico el perfil.')
        error.bot_safe_message = str(error)
        raise error
    return size


def preference_warning(profile):
    """Return a safe summary for the panel, without paths or JSON data."""
    try:
        size = preferences_size(profile)
    except OSError:
        return {'state': 'unavailable', 'size_mb': None}
    if size < PREFERENCES_WARN_MB * 1024 * 1024:
        return None
    return {'state': 'blocked' if size > PREFERENCES_MAX_MB * 1024 * 1024 else 'growing',
            'size_mb': round(size / 1024 / 1024, 1)}
