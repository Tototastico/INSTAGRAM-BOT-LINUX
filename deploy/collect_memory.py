"""Sample host and instagram-bot memory without reading browser profiles.

Run as the service user in a separate terminal while reproducing a failure.
Only process names and memory sizes are recorded; no command lines, URLs or
environment variables are collected.
"""

import argparse
import json
import os
import shutil
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

MIB = 1024 * 1024


def read_number(path):
    try:
        value = Path(path).read_text().strip()
        return int(value) if value != 'max' else None
    except (OSError, ValueError):
        return None


def key_values(path):
    result = {}
    try:
        for line in Path(path).read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    result[parts[0].rstrip(':')] = int(parts[1])
                except ValueError:
                    pass
    except OSError:
        pass
    return result


def process_memory(proc_root=Path('/proc')):
    processes = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return processes
    for entry in entries:
        if not entry.name.isdigit():
            continue
        values = key_values(entry / 'status')
        rss = values.get('VmRSS')
        if rss is None:
            continue
        try:
            name = (entry / 'comm').read_text().strip()[:40]
        except OSError:
            continue
        processes.append({'pid': int(entry.name), 'name': name, 'rss_mb': round(rss / 1024, 1)})
    return processes


def service_cgroup(unit='instagram-bot.service'):
    try:
        result = subprocess.run(
            ['systemctl', 'show', unit, '--property=ControlGroup', '--value'],
            check=True, capture_output=True, text=True, timeout=5)
        group = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not group or not group.startswith('/') or '..' in Path(group).parts:
        return None
    path = Path('/sys/fs/cgroup') / group.lstrip('/')
    return path if path.is_dir() else None


def cgroup_pids(group):
    if group is None:
        return set()
    pids = set()
    try:
        files = group.rglob('cgroup.procs')
        for path in files:
            for line in path.read_text().splitlines():
                if line.isdigit():
                    pids.add(int(line))
    except OSError:
        pass
    return pids


def free_mb(path):
    try:
        return round(shutil.disk_usage(path).free / MIB)
    except OSError:
        return None


def cgroup_mb(group, filename):
    value = read_number(group / filename) if group else None
    return round(value / MIB) if value is not None else None


def sample(group):
    memory = key_values('/proc/meminfo')
    processes = process_memory()
    bot_pids = cgroup_pids(group)
    totals = defaultdict(float)
    for process in processes:
        if process['pid'] in bot_pids:
            totals[process['name']] += process['rss_mb']
    swap_total = memory.get('SwapTotal')
    swap_free = memory.get('SwapFree')
    events = key_values(group / 'memory.events') if group else {}
    breakdown = key_values(group / 'memory.stat') if group else {}
    return {
        'at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'mem_available_mb': round(memory['MemAvailable'] / 1024) if 'MemAvailable' in memory else None,
        'swap_used_mb': round((swap_total - swap_free) / 1024)
        if swap_total is not None and swap_free is not None else None,
        'load_1m': round(os.getloadavg()[0], 2),
        'bot_memory_mb': cgroup_mb(group, 'memory.current'),
        'bot_memory_peak_mb': cgroup_mb(group, 'memory.peak'),
        'bot_swap_mb': cgroup_mb(group, 'memory.swap.current'),
        'bot_anon_mb': round(breakdown['anon'] / MIB) if 'anon' in breakdown else None,
        'bot_file_cache_mb': round(breakdown['file'] / MIB) if 'file' in breakdown else None,
        'bot_pagetables_mb': round(breakdown['pagetables'] / MIB)
        if 'pagetables' in breakdown else None,
        'bot_oom_kill_count': events.get('oom_kill'),
        'bot_process_count': len(bot_pids),
        'bot_rss_by_name_mb': {name: round(value) for name, value in sorted(totals.items())},
        'top_processes': sorted(processes, key=lambda item: item['rss_mb'], reverse=True)[:10],
        'tmp_free_mb': free_mb('/tmp'),
        'shm_free_mb': free_mb('/dev/shm'),
    }


def collect(duration, interval, output_dir, unit):
    if duration <= 0 or interval <= 0:
        raise ValueError('duration e interval deben ser positivos')
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_dir.chmod(0o700)
    path = output_dir / f'memory-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{os.getpid()}.jsonl'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    group = service_cgroup(unit)
    count = 0
    min_available = None
    max_bot = None
    max_swap = None
    first_oom = last_oom = None
    deadline = time.monotonic() + duration
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as log:
            while True:
                item = sample(group)
                log.write(json.dumps(item, ensure_ascii=True) + '\n')
                log.flush()
                os.fsync(log.fileno())
                count += 1
                available = item['mem_available_mb']
                bot = item['bot_memory_mb']
                swap = item['swap_used_mb']
                oom = item['bot_oom_kill_count']
                if available is not None:
                    min_available = available if min_available is None else min(min_available, available)
                if bot is not None:
                    max_bot = bot if max_bot is None else max(max_bot, bot)
                if swap is not None:
                    max_swap = swap if max_swap is None else max(max_swap, swap)
                if oom is not None:
                    first_oom = oom if first_oom is None else first_oom
                    last_oom = oom
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(interval, remaining))
    except KeyboardInterrupt:
        pass
    result = {'file': str(path), 'samples': count, 'min_available_mb': min_available,
              'max_bot_memory_mb': max_bot, 'max_swap_used_mb': max_swap,
              'bot_oom_kills_during_capture': last_oom - first_oom
              if first_oom is not None and last_oom is not None else None,
              'bot_cgroup_found': group is not None}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration-seconds', type=int, default=600)
    parser.add_argument('--interval-seconds', type=float, default=2)
    parser.add_argument('--output-dir', type=Path,
                        default=Path.home() / 'instagram-bot-data' / 'memory-logs')
    parser.add_argument('--unit', default='instagram-bot.service')
    args = parser.parse_args()
    collect(args.duration_seconds, args.interval_seconds, args.output_dir, args.unit)


if __name__ == '__main__':
    main()
