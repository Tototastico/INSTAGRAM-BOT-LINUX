import json

from deploy import collect_memory


def test_process_sample_omits_command_line_and_profile_data(tmp_path):
    process = tmp_path / '123'
    process.mkdir()
    (process / 'status').write_text('Name:\tchrome\nVmRSS:\t2048 kB\n')
    (process / 'comm').write_text('chrome\n')
    (process / 'cmdline').write_bytes(b'--user-data-dir=/private/profile\0token=secret\0')
    result = collect_memory.process_memory(tmp_path)
    assert result == [{'pid': 123, 'name': 'chrome', 'rss_mb': 2.0}]
    assert 'private' not in json.dumps(result)
    assert 'secret' not in json.dumps(result)


def test_capture_writes_private_json_lines_and_summary(tmp_path, monkeypatch):
    samples = iter([
        {'mem_available_mb': 2500, 'bot_memory_mb': 500, 'swap_used_mb': 100,
         'bot_oom_kill_count': 0, 'top_processes': []},
        {'mem_available_mb': 900, 'bot_memory_mb': 2800, 'swap_used_mb': 700,
         'bot_oom_kill_count': 1, 'top_processes': []},
    ])
    monkeypatch.setattr(collect_memory, 'service_cgroup', lambda unit: tmp_path)
    monkeypatch.setattr(collect_memory, 'sample', lambda group: next(samples))
    times = iter([0, 0, 2])
    monkeypatch.setattr(collect_memory.time, 'monotonic', lambda: next(times))
    monkeypatch.setattr(collect_memory.time, 'sleep', lambda interval: None)
    result = collect_memory.collect(1, 0.5, tmp_path / 'logs', 'instagram-bot.service')
    records = [json.loads(line) for line in collect_memory.Path(result['file']).read_text().splitlines()]
    assert len(records) == 2
    assert result['min_available_mb'] == 900
    assert result['max_bot_memory_mb'] == 2800
    assert result['bot_oom_kills_during_capture'] == 1
    assert not any('cmdline' in record for record in records)
