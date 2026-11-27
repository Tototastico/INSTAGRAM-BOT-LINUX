"""Read-only Chrome profile health and bounded diagnostics."""
import json
import logging
import stat
import subprocess
import sys
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


MIB = 1024 * 1024
KNOWN_FIELDS = (
    ('extensions', 'settings', 'fignfifoniblkonapihmkfakmlgkbkcf', 'manifest', 'tts_engine', 'voices'),
    ('extensions', 'settings', 'ghbmnnjooekpmoecnnnilnnbdlolhkhi', 'manifest', 'description'),
)
LOGGER = logging.getLogger(__name__)


def _fingerprint(info):
    # Windows can report slightly different creation times for fstat and lstat.
    base = info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    return base + (info.st_ctime_ns,) if sys.platform == 'linux' else base


def inspect_preferences(path):
    """Run JSON analysis in a bounded process, returning only known paths and sizes."""
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(path)],
            capture_output=True, text=True, timeout=10, check=True)
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {'diagnostic': 'unavailable'}


def _inspect(path):
    import os
    if os.name == 'posix':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (384 * MIB, 384 * MIB))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        limit = 80 * MIB
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            return {'diagnostic': 'outside_budget'}
        try:
            document = json.loads(stream.read(limit + 1))
        except (ValueError, RecursionError):
            return {'diagnostic': 'invalid_json'}
        if (_fingerprint(before) != _fingerprint(os.fstat(stream.fileno()))
                or _fingerprint(before) != _fingerprint(path.lstat())):
            return {'diagnostic': 'changed'}
    large_fields = []
    for field in KNOWN_FIELDS:
        value = document
        for key in field:
            value = value.get(key) if isinstance(value, dict) else None
        if not isinstance(value, (list, str)):
            continue
        size = sum(len(chunk) for chunk in json.JSONEncoder(
            ensure_ascii=True, separators=(',', ':')).iterencode(value))
        if size >= MIB:
            large_fields.append({'path': '.'.join(field), 'serialized_ascii_bytes': size})
    return {'diagnostic': 'complete', 'known_large_fields': large_fields}


class PreferencesMonitor:
    def __init__(self):
        self._samples = {}

    def scan(self, profiles):
        samples = {}
        for profile in profiles:
            path = Path(profile) / 'Default' / 'Preferences'
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise OSError('Preferences is not a regular file')
            except FileNotFoundError:
                samples[profile] = (None, {'state': 'missing', 'size_bytes': None})
                continue
            except OSError:
                samples[profile] = (None, {'state': 'unavailable', 'size_bytes': None})
                continue
            signature = _fingerprint(info)
            previous = self._samples.get(profile)
            if previous and previous[0] == signature and previous[1].get('diagnostic') not in {
                'changed', 'invalid_json', 'unavailable'
            }:
                samples[profile] = previous
                continue
            size = info.st_size
            state = 'normal'
            for threshold, label in ((MIB, 'inspect'), (8 * MIB, 'growing'),
                                     (32 * MIB, 'priority'), (64 * MIB + 1, 'blocked')):
                if size >= threshold:
                    state = label
            summary = {'state': state, 'size_bytes': size}
            if size >= MIB:
                summary.update(inspect_preferences(path))
            if state in {'growing', 'priority', 'blocked'} and (
                not previous or previous[1] != summary
            ):
                LOGGER.warning('Chrome Preferences: profile=%r summary=%s', path.parent.parent.name, summary)
            samples[profile] = (signature, summary)
        self._samples = samples

    def status(self, profile):
        sample = self._samples.get(profile)
        return sample[1] if sample else None


if __name__ == '__main__':
    print(json.dumps(_inspect(Path(sys.argv[1]))))
