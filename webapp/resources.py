"""Conservative admission check for Chrome on the Linux host."""
import os
from pathlib import Path

MIB = 1024 * 1024


def snapshot():
    if os.name != 'posix':
        return {'available_mb': None, 'chrome_mb': None, 'cpu_load': None, 'cpu_count': os.cpu_count() or 1}
    try:
        lines = Path('/proc/meminfo').read_text().splitlines()
        available = next(int(line.split()[1]) // 1024 for line in lines if line.startswith('MemAvailable:'))
        chrome_kb = 0
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                command = (entry / 'comm').read_text().strip()
                if command not in ('chrome', 'chromium', 'chrome-headless'):
                    continue
                status = (entry / 'status').read_text()
                chrome_kb += next(int(line.split()[1]) for line in status.splitlines() if line.startswith('VmRSS:'))
            except (OSError, StopIteration, ValueError):
                continue
        return {'available_mb': available, 'chrome_mb': chrome_kb // 1024,
                'cpu_load': round(os.getloadavg()[0], 2), 'cpu_count': os.cpu_count() or 1}
    except (OSError, StopIteration, ValueError):
        return {'available_mb': None, 'chrome_mb': None, 'cpu_load': None, 'cpu_count': os.cpu_count() or 1}


def can_start(metrics, active):
    available = metrics['available_mb']
    if available is None:
        return True
    # Preserve 1 GiB for the OS and service. Use observed Chrome usage when present.
    estimated = max(512, metrics['chrome_mb'] // max(1, active))
    if available < 1024 + estimated:
        return False
    load = metrics['cpu_load']
    return load is None or load < 2 * metrics['cpu_count']
