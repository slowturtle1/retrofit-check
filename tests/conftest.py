"""Shared test setup.

@pytest.mark.pending("A5"): behaviour the lead has not landed yet. The test runs and is reported as
xfail (not strict), so pytest stays green and `make approach` lists it as a gap with the item it waits for.

Every test runs with the network blocked (only this machine answers) and with the growing local copy of
the snapshot (offline.LIVE) in a temporary folder, so runs/ is never touched.
"""

import socket

import pytest

from retrofit import offline

LOCAL = ("127.0.0.1", "localhost", "::1", None)
_connect, _getaddrinfo = socket.socket.connect, socket.getaddrinfo


def _connect_local(sock, address):
    if isinstance(address, tuple) and address[0] not in LOCAL:
        raise OSError(f"network blocked in tests: {address[0]}")
    return _connect(sock, address)


def _resolve_local(host, *a, **k):
    if host not in LOCAL:
        raise socket.gaierror(f"network blocked in tests: {host}")
    return _getaddrinfo(host, *a, **k)


def pytest_configure(config):
    config.addinivalue_line("markers", "pending(item): waits for a lead item (A1 to A8); runs as a non strict xfail")


def pytest_collection_modifyitems(config, items):
    for item in items:
        m = item.get_closest_marker("pending")
        if m:
            item.add_marker(pytest.mark.xfail(reason=f"pending {m.args[0] if m.args else '?'}", strict=False))


@pytest.fixture(scope="session", autouse=True)
def isolated(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(offline, "LIVE", tmp_path_factory.mktemp("live") / "live-cache.sqlite")
        mp.setattr(socket.socket, "connect", _connect_local)
        mp.setattr(socket, "getaddrinfo", _resolve_local)
        yield
