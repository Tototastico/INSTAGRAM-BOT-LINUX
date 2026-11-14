import errno
import shutil
from pathlib import Path

from webapp.resources import admission_decision, can_start, estimated_browser_mb, managed_chrome_memory, managed_chrome_usage


def _process(root, pid, ppid, rss_kb, args, pss_kb=None, state='S'):
    folder = root / str(pid)
    folder.mkdir()
    rss_line = '' if rss_kb is None else f'VmRSS:\t{rss_kb} kB\n'
    (folder / 'status').write_text(f'Name:\tchrome\nState:\t{state}\nPPid:\t{ppid}\n{rss_line}')
    (folder / 'cmdline').write_bytes(b'\0'.join(arg.encode() for arg in args) + b'\0')
    if pss_kb is not None:
        (folder / 'smaps_rollup').write_text(f'Pss: {pss_kb} kB\n')


def test_only_bot_profile_and_its_children_are_measured(tmp_path):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'accounts' / 'one'
    other = tmp_path / 'unrelated'
    _process(proc, 10, 1, 600_000, ['chrome', f'--user-data-dir={ours}'])
    _process(proc, 11, 10, 400_000, ['chrome', '--type=renderer'])
    _process(proc, 20, 1, 2_000_000, ['chrome', f'--user-data-dir={other}'])
    _process(proc, 21, 20, 200_000, ['chrome', '--type=renderer'])
    assert managed_chrome_memory(proc, [ours]) == (1_000_000 // 1024, 1)
    assert managed_chrome_memory(proc, []) == (0, 0)


def test_first_browser_ignores_unrelated_chrome_and_reserves_memory():
    metrics = {'available_mb': 2500, 'chrome_mb': 0, 'managed_browsers': 0,
               'cpu_load': 0.70, 'cpu_count': 2, 'enforce': True}
    assert estimated_browser_mb(metrics) == 768
    assert can_start(metrics, 0)
    assert not can_start(metrics, 1)  # Do not start a second until the first is measured.
    assert not can_start(metrics, 2)
    metrics.update(chrome_mb=900, managed_browsers=1)
    assert estimated_browser_mb(metrics) == 1080
    assert can_start(metrics, 1)
    metrics['available_mb'] = 1800
    assert not can_start(metrics, 1)


def test_missing_metrics_fail_closed_on_linux_without_exceptions():
    metrics = {'available_mb': None, 'chrome_mb': None, 'managed_browsers': 0,
               'cpu_load': 0.7, 'cpu_count': 2, 'enforce': True}
    assert estimated_browser_mb(metrics) == 768
    assert not can_start(metrics, 0)
    assert not can_start(None, 0)
    metrics['available_mb'] = 2500
    metrics['cpu_load'] = None
    assert not can_start(metrics, 0)
    metrics['cpu_load'] = 4.5
    assert not can_start(metrics, 0)


def test_pss_avoids_shared_rss_overcount_and_excludes_other_profiles(tmp_path):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'accounts' / 'one'
    other = tmp_path / 'other'
    _process(proc, 10, 1, 900_000, ['chrome', f'--user-data-dir={ours}'], 550_000)
    _process(proc, 11, 10, 828_512, ['chrome', '--type=renderer'], 498_000)
    _process(proc, 20, 1, 2_000_000, ['chrome', f'--user-data-dir={other}'], 1_000_000)
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'pss'
    assert usage['chrome_rss_mb'] == 1688
    assert usage['chrome_mb'] == 1023
    assert usage['managed_browsers'] == 1
    assert usage['sampling_attempts'] == 1


def test_disappearing_child_rebuilds_tree_and_retries_complete_pss(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'one'
    _process(proc, 10, 1, 900_000, ['chrome', f'--user-data-dir={ours}'], 550_000)
    _process(proc, 11, 10, 600_000, ['chrome', '--type=renderer'], 300_000)
    original = Path.read_text
    vanished = False

    def racing_read(path, *args, **kwargs):
        nonlocal vanished
        if path == proc / '11' / 'smaps_rollup' and not vanished:
            vanished = True
            shutil.rmtree(proc / '11')
            raise FileNotFoundError(errno.ENOENT, 'process ended', str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', racing_read)
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'pss'
    assert usage['sampling_attempts'] == 2
    assert usage['chrome_mb'] == 550_000 // 1024
    assert usage['chrome_rss_mb'] == 900_000 // 1024
    decision = admission_decision({'available_mb': 2569, **usage,
                                   'cpu_load': 0.78, 'cpu_count': 2, 'enforce': True}, 1)
    assert decision['allowed']
    assert decision['memory_source'] == 'pss'
    assert decision['sampling_attempts'] == 2


def test_missing_vmrss_pid_exits_among_thirteen_valid_chrome_processes(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'one'
    _process(proc, 65000, 1, 300_000, ['chrome', f'--user-data-dir={ours}'], 200_000)
    for pid in range(65001, 65013):
        _process(proc, pid, 65000, 100_000, ['chrome', '--type=renderer'], 70_000)
    _process(proc, 66110, 65000, None, ['chrome', '--type=renderer'])
    original = Path.read_text

    def racing_read(path, *args, **kwargs):
        if path == proc / '66110' / 'smaps_rollup':
            shutil.rmtree(proc / '66110')
            raise ProcessLookupError(errno.ESRCH, 'No such process', str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', racing_read)
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'pss'
    assert usage['chrome_mb'] == 1_040_000 // 1024
    assert usage['chrome_rss_mb'] == 1_500_000 // 1024
    assert usage['sampling_attempts'] == 2
    assert usage['pid_detected'] == 13
    assert usage['pid_disappeared'] == 1
    assert usage['pid_retried'] == 1
    assert usage['pid_unmeasurable'] == 0
    assert admission_decision({'available_mb': 2569, **usage,
                               'cpu_load': 0.78, 'cpu_count': 2, 'enforce': True}, 1)['allowed']


def test_zombie_and_terminated_without_vmrss_are_excluded_without_fallback(tmp_path):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'one'
    _process(proc, 10, 1, 800_000, ['chrome', f'--user-data-dir={ours}'], 500_000)
    _process(proc, 11, 10, None, ['chrome', '--type=renderer'], state='Z')
    _process(proc, 12, 10, None, ['chrome', '--type=renderer'], state='X')
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'pss'
    assert usage['sampling_attempts'] == 1
    assert usage['chrome_mb'] == 500_000 // 1024
    assert usage['pid_detected'] == 3
    assert usage['pid_zombie'] == 1
    assert usage['pid_terminated'] == 1
    assert usage['pid_unmeasurable'] == 0


def test_live_process_without_vmrss_can_still_be_measured_by_pss(tmp_path):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'one'
    _process(proc, 10, 1, 800_000, ['chrome', f'--user-data-dir={ours}'], 500_000)
    _process(proc, 11, 10, None, ['chrome', '--type=renderer'], 200_000)
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'pss'
    assert usage['chrome_mb'] == 700_000 // 1024
    assert usage['chrome_rss_mb'] is None
    assert usage['pid_unmeasurable'] == 0


def test_live_process_with_inaccessible_pss_keeps_conservative_rss(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'one'
    _process(proc, 10, 1, 800_000, ['chrome', f'--user-data-dir={ours}'], 400_000)
    _process(proc, 11, 10, 600_000, ['chrome', '--type=renderer'], 300_000)
    original = Path.read_text

    def denied_read(path, *args, **kwargs):
        if path == proc / '11' / 'smaps_rollup':
            raise PermissionError(errno.EACCES, 'PSS denied', str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', denied_read)
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'rss_fallback'
    assert usage['sampling_attempts'] == 1
    assert usage['chrome_mb'] == 1_400_000 // 1024


def test_multiple_process_turnovers_never_mix_pss_samples(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'one'
    _process(proc, 10, 1, 800_000, ['chrome', f'--user-data-dir={ours}'], 400_000)
    _process(proc, 11, 10, 600_000, ['chrome', '--type=renderer'], 300_000)
    original = Path.read_text

    def racing_read(path, *args, **kwargs):
        if path == proc / '11' / 'smaps_rollup':
            shutil.rmtree(proc / '11')
            _process(proc, 12, 10, 500_000, ['chrome', '--type=renderer'], 250_000)
            raise ProcessLookupError(errno.ESRCH, 'process ended', str(path))
        if path == proc / '12' / 'smaps_rollup':
            shutil.rmtree(proc / '12')
            _process(proc, 13, 10, 400_000, ['chrome', '--type=renderer'], 200_000)
            raise FileNotFoundError(errno.ENOENT, 'process ended', str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', racing_read)
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'pss'
    assert usage['sampling_attempts'] == 3
    assert usage['chrome_mb'] == 600_000 // 1024


def test_repeated_churn_uses_labeled_rss_fallback(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'one'
    _process(proc, 10, 1, 800_000, ['chrome', f'--user-data-dir={ours}'], 400_000)
    _process(proc, 11, 10, 600_000, ['chrome', '--type=renderer'], 300_000)
    original = Path.read_text

    def racing_read(path, *args, **kwargs):
        if path.parent.parent == proc and path.name == 'smaps_rollup' and path.parent.name in {'11', '12', '13'}:
            next_pid = int(path.parent.name) + 1
            shutil.rmtree(path.parent)
            _process(proc, next_pid, 10, 600_000, ['chrome', '--type=renderer'], 300_000)
            raise ProcessLookupError(errno.ESRCH, 'process ended', str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', racing_read)
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'rss_transient'
    assert usage['sampling_attempts'] == 3
    assert usage['chrome_mb'] == 1_400_000 // 1024
    assert usage['pid_disappeared'] == 3
    assert usage['pid_retried'] == 2
    assert usage['transient_reserved_mb'] == 586


def test_repeated_churn_without_vmrss_gets_conservative_transient_reserve(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'one'
    _process(proc, 10, 1, 800_000, ['chrome', f'--user-data-dir={ours}'], 400_000)
    _process(proc, 11, 10, None, ['chrome', '--type=renderer'])
    original = Path.read_text

    def racing_read(path, *args, **kwargs):
        if path.parent.parent == proc and path.name == 'smaps_rollup' and path.parent.name in {'11', '12', '13'}:
            next_pid = int(path.parent.name) + 1
            shutil.rmtree(path.parent)
            _process(proc, next_pid, 10, None, ['chrome', '--type=renderer'])
            raise ProcessLookupError(errno.ESRCH, 'process ended', str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', racing_read)
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'rss_transient'
    assert usage['chrome_rss_mb'] == 800_000 // 1024
    assert usage['chrome_mb'] == 800_000 // 1024 + 768
    assert usage['transient_reserved_mb'] == 768
    assert usage['pid_unmeasurable'] == 0
    assert not admission_decision({'available_mb': 2000, **usage,
                                   'cpu_load': 0.5, 'cpu_count': 2, 'enforce': True}, 1)['allowed']


def test_esrch_with_still_live_process_and_unknown_rss_fails_closed(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'one'
    _process(proc, 10, 1, 800_000, ['chrome', f'--user-data-dir={ours}'], 400_000)
    _process(proc, 11, 10, None, ['chrome', '--type=renderer'])
    original = Path.read_text

    def missing_rollup(path, *args, **kwargs):
        if path == proc / '11' / 'smaps_rollup':
            raise ProcessLookupError(errno.ESRCH, 'rollup missing', str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', missing_rollup)
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'unavailable'
    assert usage['sampling_attempts'] == 1
    assert usage['pid_unmeasurable'] == 1
    assert usage['pid_disappeared'] == 0


def test_live_process_with_unknown_pss_and_rss_fails_closed(tmp_path):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'one'
    _process(proc, 10, 1, 800_000, ['chrome', f'--user-data-dir={ours}'], 400_000)
    _process(proc, 11, 10, 0, ['chrome', '--type=renderer'])
    (proc / '11' / 'status').write_text('Name:\tchrome\nPPid:\t10\n')
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'unavailable'
    assert usage['chrome_mb'] is None
    assert usage['pid_unmeasurable'] == 1
    metrics = {'available_mb': 4000, **usage, 'cpu_load': 0.5, 'cpu_count': 2, 'enforce': True}
    assert not can_start(metrics, 1)


def test_partial_pss_uses_whole_tree_rss_instead_of_mixing(tmp_path):
    proc = tmp_path / 'proc'
    proc.mkdir()
    ours = tmp_path / 'one'
    _process(proc, 10, 1, 800_000, ['chrome', f'--user-data-dir={ours}'], 400_000)
    _process(proc, 11, 10, 600_000, ['chrome', '--type=renderer'])
    usage = managed_chrome_usage(proc, [ours])
    assert usage['memory_source'] == 'rss_fallback'
    assert usage['chrome_mb'] == 1_400_000 // 1024


def test_two_cpu_four_gb_vps_admits_second_only_when_safe():
    metrics = {'available_mb': 2569, 'chrome_mb': 1000, 'chrome_rss_mb': 1688,
               'managed_browsers': 1, 'memory_source': 'pss',
               'cpu_load': 0.78, 'cpu_count': 2, 'enforce': True}
    decision = admission_decision(metrics, 1)
    assert decision['allowed']
    assert decision['estimated_next_mb'] == 1200
    assert decision['required_mb'] == 2224
    assert decision['projected_available_mb'] == 1369
    assert decision['cpu_threshold'] == 4
    assert not admission_decision(metrics, 2)['allowed']  # Another Chrome is still starting.
    metrics['chrome_mb'] = 1400
    blocked = admission_decision(metrics, 1)
    assert not blocked['allowed']
    assert 'Memoria insuficiente' in blocked['reason']
