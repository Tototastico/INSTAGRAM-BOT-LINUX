"""Keep scheduling tests independent of the developer or VPS resource load."""
import pytest


@pytest.fixture(autouse=True)
def deterministic_scheduler_resources(monkeypatch):
    def ample_resources(_profiles=()):
        return {'available_mb': 8192, 'chrome_mb': 0, 'managed_browsers': 0,
                'cpu_load': 0.1, 'cpu_count': 2, 'enforce': True}

    monkeypatch.setattr('webapp.resources.snapshot', ample_resources)
    monkeypatch.setattr('webapp.coordinator.snapshot', ample_resources)
