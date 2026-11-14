from webapp.resources import can_start, estimated_browser_mb, managed_chrome_memory


def _process(root, pid, ppid, rss_kb, args):
    folder = root / str(pid)
    folder.mkdir()
    (folder / 'status').write_text(f'Name:\tchrome\nPPid:\t{ppid}\nVmRSS:\t{rss_kb} kB\n')
    (folder / 'cmdline').write_bytes(b'\0'.join(arg.encode() for arg in args) + b'\0')


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
    assert estimated_browser_mb(metrics) == 900
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
