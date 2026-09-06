"""A Redis blip cannot turn one accepted scan into thousands of auth dead-letters."""

import pytest
from fastapi import HTTPException

import core
from routes import scans


class _Redis:
    def __init__(self, *, fail_sets=0, fail_gets=0, value=None):
        self.fail_sets = fail_sets
        self.fail_gets = fail_gets
        self.value = value
        self.set_calls = 0
        self.get_calls = 0

    def set(self, *_args, **_kwargs):
        self.set_calls += 1
        if self.set_calls <= self.fail_sets:
            raise ConnectionError("redis unavailable")
        return True

    def get(self, *_args, **_kwargs):
        self.get_calls += 1
        if self.get_calls <= self.fail_gets:
            raise ConnectionError("redis unavailable")
        return self.value

    def close(self):
        return None


def test_required_shared_registration_reconnects_once(monkeypatch):
    first = _Redis(fail_sets=1)
    second = _Redis()
    clients = iter((first, second))
    monkeypatch.setattr(core, "REDIS_URL", "redis://shared")
    monkeypatch.setattr(core, "get_scan_tokens", lambda _scan_id: {})
    monkeypatch.setattr(core, "_get_redis", lambda: next(clients))
    monkeypatch.setattr(core, "_reset_token_redis", lambda: None)
    monkeypatch.setattr(core._time, "sleep", lambda _seconds: None)

    core.register_scan_tokens("scan-1", drive="token", require_shared=True)

    assert first.set_calls == 1
    assert second.set_calls == 1


def test_required_shared_registration_fails_closed(monkeypatch):
    failed = _Redis(fail_sets=99)
    monkeypatch.setattr(core, "REDIS_URL", "redis://shared")
    monkeypatch.setattr(core, "get_scan_tokens", lambda _scan_id: {})
    monkeypatch.setattr(core, "_get_redis", lambda: failed)
    monkeypatch.setattr(core, "_reset_token_redis", lambda: None)
    monkeypatch.setattr(core._time, "sleep", lambda _seconds: None)

    with pytest.raises(core.SharedTokenStoreUnavailable):
        core.register_scan_tokens("scan-2", drive="token", require_shared=True)

    assert failed.set_calls == 2


def test_shared_token_read_reconnects_once(monkeypatch):
    first = _Redis(fail_gets=1)
    second = _Redis(value='{"drive":"fresh"}')
    clients = iter((first, second))
    monkeypatch.setattr(core, "REDIS_URL", "redis://shared")
    monkeypatch.setattr(core, "_get_redis", lambda: next(clients))
    monkeypatch.setattr(core, "_reset_token_redis", lambda: None)
    monkeypatch.setattr(core._time, "sleep", lambda _seconds: None)

    assert core.get_scan_tokens("scan-3") == {"drive": "fresh"}


def test_route_returns_retryable_503_when_shared_registration_fails(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise core.SharedTokenStoreUnavailable("down")

    monkeypatch.setattr(core, "register_scan_tokens", unavailable)

    with pytest.raises(HTTPException) as raised:
        scans._register_scan_tokens("scan-4", drive="token")

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "credential_store_unavailable"
    assert "No processing was started" in raised.value.detail["message"]
