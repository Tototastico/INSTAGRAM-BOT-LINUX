"""Small, read-only, secret-free snapshot taken after Chrome startup fails."""
import os
from pathlib import Path


def _number(path):
    try:
        value = path.read_text().strip()
        return int(value) if value != 'max' else None
    except (OSError, ValueError):
        return None


def _free_mb(path):
    try:
        stats = os.statvfs(path)
        return stats.f_bavail * stats.f_frsize // 1024 // 1024
    except (OSError, AttributeError):
        return None


def startup_snapshot(profile, proc_root=Path('/proc'), cgroup_root=Path('/sys/fs/cgroup'),
                     tmp_dir=Path('/tmp'), shm_dir=Path('/dev/shm'), platform_name=None):
    """Report available resources, never profile paths, command lines or page data."""
    if (platform_name or os.name) != 'posix':
        return {}
    result = {'mem_available_mb': None, 'swap_free_mb': None,
              'tmp_free_mb': _free_mb(tmp_dir), 'shm_free_mb': _free_mb(shm_dir),
              'cgroup_memory_mb': None, 'cgroup_limit_mb': None,
              'cgroup_oom_kills': None, 'cgroup_pids': None, 'cgroup_pids_limit': None,
              'profile_chrome_running': None}
    try:
        for line in (proc_root / 'meminfo').read_text().splitlines():
            name, _, rest = line.partition(':')
            if name in ('MemAvailable', 'SwapFree'):
                value = int(rest.split()[0]) // 1024
                result['mem_available_mb' if name == 'MemAvailable' else 'swap_free_mb'] = value
    except (OSError, ValueError, IndexError):
        pass
    try:
        group = next(line.split('::', 1)[1] for line in
                     (proc_root / 'self' / 'cgroup').read_text().splitlines() if line.startswith('0::'))
        root = cgroup_root.resolve()
        group_dir = (root / group.lstrip('/')).resolve()
        if group_dir.is_relative_to(root):
            memory = _number(group_dir / 'memory.current')
            limit = _number(group_dir / 'memory.max')
            result['cgroup_memory_mb'] = None if memory is None else memory // 1024 // 1024
            result['cgroup_limit_mb'] = None if limit is None else limit // 1024 // 1024
            result['cgroup_pids'] = _number(group_dir / 'pids.current')
            result['cgroup_pids_limit'] = _number(group_dir / 'pids.max')
            events = (group_dir / 'memory.events').read_text().splitlines()
            result['cgroup_oom_kills'] = next(
                (int(line.split()[1]) for line in events if line.startswith('oom_kill ')), None)
    except (OSError, StopIteration, ValueError, IndexError):
        pass
    try:
        from .visual_sessions import profile_process_running
        result['profile_chrome_running'] = profile_process_running(Path(profile))
    except OSError:
        pass
    return result
