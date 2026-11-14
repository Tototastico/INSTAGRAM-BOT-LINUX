"""Conservative Linux admission check using only Chrome processes owned by the bot."""
import os
from pathlib import Path

SYSTEM_RESERVE_MB = 1024
FIRST_BROWSER_MB = 768


def managed_chrome_memory(proc_root, profiles, uid=None):
    """Return RSS of profile Chrome process trees, excluding unrelated browsers."""
    profiles = {str(Path(profile).resolve()) for profile in (profiles or ())}
    if not profiles:
        return 0, 0
    processes = {}
    roots = set()
    matched_profiles = set()
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if uid is not None and entry.stat().st_uid != uid:
                continue
            status = (entry / 'status').read_text()
            ppid = next(int(line.split()[1]) for line in status.splitlines() if line.startswith('PPid:'))
            rss = next((int(line.split()[1]) for line in status.splitlines() if line.startswith('VmRSS:')), 0)
            args = (entry / 'cmdline').read_bytes().split(b'\0')
        except (OSError, StopIteration, ValueError, IndexError):
            continue
        pid = int(entry.name)
        processes[pid] = (ppid, rss)
        for arg in args:
            if not arg.startswith(b'--user-data-dir='):
                continue
            try:
                profile = str(Path(os.fsdecode(arg.split(b'=', 1)[1])).resolve())
            except (OSError, ValueError):
                continue
            if profile in profiles:
                roots.add(pid)
                matched_profiles.add(profile)
    included = set(roots)
    # Chrome renderers and helpers generally inherit the profile via their parent.
    changed = True
    while changed:
        descendants = {pid for pid, (ppid, _) in processes.items() if ppid in included}
        changed = bool(descendants - included)
        included.update(descendants)
    return sum(processes[pid][1] for pid in included) // 1024, len(matched_profiles)


def snapshot(managed_profiles=()):
    if os.name != 'posix':
        return {'available_mb': None, 'chrome_mb': None, 'managed_browsers': 0,
                'cpu_load': None, 'cpu_count': os.cpu_count() or 1, 'enforce': False}
    try:
        lines = Path('/proc/meminfo').read_text().splitlines()
        available = next(int(line.split()[1]) // 1024 for line in lines if line.startswith('MemAvailable:'))
    except (OSError, StopIteration, ValueError):
        available = None
    try:
        chrome_mb, managed_browsers = managed_chrome_memory(Path('/proc'), managed_profiles, os.getuid())
    except OSError:
        chrome_mb, managed_browsers = None, 0
    try:
        load = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        load = None
    return {'available_mb': available, 'chrome_mb': chrome_mb,
            'managed_browsers': managed_browsers, 'cpu_load': load,
            'cpu_count': os.cpu_count() or 1, 'enforce': True}


def estimated_browser_mb(metrics):
    metrics = metrics or {}
    observed = metrics.get('managed_browsers') or 0
    chrome_mb = metrics.get('chrome_mb')
    if not observed or chrome_mb is None:
        return FIRST_BROWSER_MB
    return max(FIRST_BROWSER_MB, chrome_mb // observed)


def can_start(metrics, active):
    metrics = metrics or {}
    available = metrics.get('available_mb')
    load = metrics.get('cpu_load')
    if available is None or load is None:
        return not metrics.get('enforce', True)
    observed = metrics.get('managed_browsers')
    in_flight = max(0, active - observed) if observed is not None else 0
    estimated = estimated_browser_mb(metrics)
    if available < SYSTEM_RESERVE_MB + estimated * (1 + in_flight):
        return False
    cpu_count = metrics.get('cpu_count') or 1
    return load < 2 * cpu_count
