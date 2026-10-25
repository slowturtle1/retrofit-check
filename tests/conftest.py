"""Shared test setup.

@pytest.mark.pending("A5"): behaviour the lead has not landed yet. The test runs and is reported as
xfail (not strict), so pytest stays green and `make approach` lists it as a gap with the item it waits for.
"""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "pending(item): waits for a lead item (A1 to A8); runs as a non strict xfail")


def pytest_collection_modifyitems(config, items):
    for item in items:
        m = item.get_closest_marker("pending")
        if m:
            item.add_marker(pytest.mark.xfail(reason=f"pending {m.args[0] if m.args else '?'}", strict=False))
