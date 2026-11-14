"""Conservative Linux admission check using only Chrome processes owned by the bot."""
import errno
import os
from math import ceil
from pathlib import Path

SYSTEM_RESERVE_MB = 1024
FIRST_BROWSER_MB = 768
GROWTH_MARGIN = 1.20
MAX_SAMPLE_ATTEMPTS = 3


def _process_disappeared(error, proc_root, pid):
    """ESRCH means a dying PID; a missing rollup on a live PID is different."""
    if isinstance(error, OSError) and error.errno == errno.ESRCH:
        return True
    try:
        (proc_root / str(pid) / 'status').read_text()
    except OSError as status_error:
        return status_error.errno in (errno.ENOENT, errno.ESRCH)
    return False


def _sample_managed_chrome_usage(proc_root, profiles, uid):
    """One independent /proc sample; transient=True requests a fresh tree scan."""
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
            rss = next((int(line.split()[1]) for line in status.splitlines() if line.startswith('VmRSS:')), None)
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
    if not included:
        return {'chrome_mb': 0, 'chrome_rss_mb': 0, 'managed_browsers': 0,
                'memory_source': 'none'}, False
    rss_complete = all(processes[pid][1] is not None for pid in included)
    rss_kb = sum(processes[pid][1] for pid in included) if rss_complete else None
    pss_kb = 0
    pss_complete = bool(included)
    transient = False
    for pid in included:
        try:
            lines = (proc_root / str(pid) / 'smaps_rollup').read_text().splitlines()
            pss_kb += next(int(line.split()[1]) for line in lines if line.startswith('Pss:'))
        except OSError as error:
            transient = _process_disappeared(error, proc_root, pid)
            pss_complete = False
            break
        except (StopIteration, ValueError, IndexError):
            pss_complete = False
            break
    chosen_kb = pss_kb if pss_complete else rss_kb
    usage = {'chrome_mb': None if chosen_kb is None else chosen_kb // 1024,
            'chrome_rss_mb': None if rss_kb is None else rss_kb // 1024,
            'managed_browsers': len(matched_profiles),
            'memory_source': 'pss' if pss_complete else 'rss_fallback' if rss_complete else 'unavailable'}
    return usage, transient


def managed_chrome_usage(proc_root, profiles, uid=None):
    """Retry complete samples for vanished PIDs, never combining partial PSS."""
    profiles = {str(Path(profile).resolve()) for profile in (profiles or ())}
    if not profiles:
        return {'chrome_mb': 0, 'chrome_rss_mb': 0, 'managed_browsers': 0,
                'memory_source': 'none', 'sampling_attempts': 0}
    for attempt in range(1, MAX_SAMPLE_ATTEMPTS + 1):
        usage, transient = _sample_managed_chrome_usage(proc_root, profiles, uid)
        if not transient:
            return {**usage, 'sampling_attempts': attempt}
    return {**usage, 'memory_source': 'rss_transient' if usage['chrome_mb'] is not None else 'unavailable',
            'sampling_attempts': MAX_SAMPLE_ATTEMPTS}


def managed_chrome_memory(proc_root, profiles, uid=None):
    """Compatibility helper returning the selected memory measure and browser count."""
    usage = managed_chrome_usage(proc_root, profiles, uid)
    return usage['chrome_mb'], usage['managed_browsers']


def snapshot(managed_profiles=()):
    if os.name != 'posix':
        return {'available_mb': None, 'chrome_mb': None, 'managed_browsers': 0,
                'chrome_rss_mb': None, 'memory_source': 'none', 'sampling_attempts': 0,
                'cpu_load': None, 'cpu_count': os.cpu_count() or 1, 'enforce': False}
    try:
        lines = Path('/proc/meminfo').read_text().splitlines()
        available = next(int(line.split()[1]) // 1024 for line in lines if line.startswith('MemAvailable:'))
    except (OSError, StopIteration, ValueError):
        available = None
    try:
        usage = managed_chrome_usage(Path('/proc'), managed_profiles, os.getuid())
    except OSError:
        usage = {'chrome_mb': None, 'chrome_rss_mb': None,
                 'managed_browsers': 0, 'memory_source': 'unavailable', 'sampling_attempts': 0}
    try:
        load = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        load = None
    return {'available_mb': available, **usage, 'cpu_load': load,
            'cpu_count': os.cpu_count() or 1, 'enforce': True}


def estimated_browser_mb(metrics):
    metrics = metrics or {}
    observed = metrics.get('managed_browsers') or 0
    chrome_mb = metrics.get('chrome_mb')
    if not observed or chrome_mb is None:
        return FIRST_BROWSER_MB
    return max(FIRST_BROWSER_MB, ceil(chrome_mb / observed * GROWTH_MARGIN))


def can_start(metrics, active):
    return admission_decision(metrics, active)['allowed']


def admission_decision(metrics, active):
    metrics = metrics or {}
    available = metrics.get('available_mb')
    load = metrics.get('cpu_load')
    observed = metrics.get('managed_browsers') or 0
    in_flight = max(0, active - observed)
    estimated = estimated_browser_mb(metrics)
    required = SYSTEM_RESERVE_MB + estimated * (1 + in_flight)
    cpu_count = metrics.get('cpu_count') or 1
    threshold = 2 * cpu_count
    decision = {'allowed': True, 'reason': 'Recursos suficientes',
                'available_mb': available, 'chrome_mb': metrics.get('chrome_mb'),
                'chrome_rss_mb': metrics.get('chrome_rss_mb'),
                'memory_source': metrics.get('memory_source', 'unknown'),
                'sampling_attempts': metrics.get('sampling_attempts'),
                'estimated_next_mb': estimated, 'system_reserve_mb': SYSTEM_RESERVE_MB,
                'starting_browsers': in_flight, 'required_mb': required,
                'projected_available_mb': None if available is None else available - estimated * (1 + in_flight),
                'cpu_load': load, 'cpu_threshold': threshold}
    if available is None or load is None:
        decision['allowed'] = not metrics.get('enforce', True)
        decision['reason'] = 'Métricas de RAM o CPU no disponibles' if not decision['allowed'] else 'Control de recursos no aplicable'
    elif metrics.get('chrome_mb') is None and active:
        decision['allowed'] = False
        decision['reason'] = 'Memoria de Chrome no disponible'
    elif available < required:
        decision['allowed'] = False
        decision['reason'] = f'Memoria insuficiente: {available} MB disponibles; se requieren {required} MB ({estimated} MB por navegador nuevo, {in_flight} iniciando, {SYSTEM_RESERVE_MB} MB de reserva)'
    elif load >= threshold:
        decision['allowed'] = False
        decision['reason'] = f'CPU ocupada: carga {load} >= límite {threshold}'
    return decision
