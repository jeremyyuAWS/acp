"""Microsoft Graph throttling — the retry SharePoint never had.

Every SharePoint call in this codebase goes through one door, `scanner._sp_get`: the walk, the
delta feed, the site list, the drives list, the freshness replay. Until this it made one
`httpx.get` and failed on whatever came back — while the Drive path has had
`execute(num_retries=5)` from the start. Graph throttles hard, with 429 and a `Retry-After`, and
on a 30-site estate that is not an edge case; it is the ordinary Friday afternoon.

THE LOAD-BEARING EXCLUSION IS THE 403. It is a scope problem, not a busy service: the answer will
not change, Phase 1's per-site isolation reads the PermissionError to mark that site blocked with
the consent that would fix it, and retrying would turn one fast correct diagnosis into four slow
ones — delaying the only thing the operator can act on, and making a permissions failure look
like a performance one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import scanner  # noqa: E402


class _Resp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code, self._payload = status, payload or {"ok": True}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def _sequence(monkeypatch, responses, sleeps=None):
    """Answer each call with the next response in `responses`, recording the sleeps."""
    import httpx
    calls = {"n": 0}

    def get(url, headers=None, timeout=None, follow_redirects=None):
        r = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(httpx, "get", get)
    if sleeps is not None:
        monkeypatch.setattr(scanner, "_sp_sleep", lambda s: sleeps.append(s), raising=True)
    return calls


# ── what is retried ──────────────────────────────────────────────────────────────────────────

def test_a_429_is_retried_and_then_succeeds(monkeypatch):
    calls = _sequence(monkeypatch, [_Resp(429), _Resp(429), _Resp(200, {"value": []})], sleeps=[])
    assert scanner._sp_get("tok", "https://graph/x") == {"value": []}
    assert calls["n"] == 3


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_transient_server_error_is_retried(monkeypatch, status):
    calls = _sequence(monkeypatch, [_Resp(status), _Resp(200, {"value": []})], sleeps=[])
    assert scanner._sp_get("tok", "https://graph/x") == {"value": []}
    assert calls["n"] == 2


def test_a_transport_failure_is_retried(monkeypatch):
    """A connection reset is the transient case too, and the one a long walk against a customer's
    tenant hits most."""
    calls = _sequence(monkeypatch, [ConnectionError("reset"), _Resp(200, {"value": []})], sleeps=[])
    assert scanner._sp_get("tok", "https://graph/x") == {"value": []}
    assert calls["n"] == 2


# ── what is NOT retried, and why it matters more ─────────────────────────────────────────────

def test_a_403_is_NEVER_retried(monkeypatch):
    """THE exclusion. A missing scope will still be missing on the fourth attempt, and the
    PermissionError is what Phase 1's per-site isolation reads to mark a site blocked with the
    consent that would fix it. Retrying delays the only actionable answer and dresses a
    permissions failure as a performance one."""
    calls = _sequence(monkeypatch, [_Resp(403)], sleeps=[])
    with pytest.raises(PermissionError) as e:
        scanner._sp_get("tok", "https://graph/sites")
    assert calls["n"] == 1, "a scope failure was retried"
    assert "Sites.Read.All" in str(e.value) and "admin consent" in str(e.value)


def test_a_401_is_never_retried_either(monkeypatch):
    calls = _sequence(monkeypatch, [_Resp(401)], sleeps=[])
    with pytest.raises(PermissionError):
        scanner._sp_get("tok", "https://graph/x")
    assert calls["n"] == 1


@pytest.mark.parametrize("status", [400, 404, 409])
def test_a_client_error_is_not_retried(monkeypatch, status):
    """A refused `$select` will be refused again, and a deleted item is deleted. Retrying either
    buys a longer wait for the same answer — and the walk's tier fallback depends on a 400 coming
    back promptly so it can step down."""
    calls = _sequence(monkeypatch, [_Resp(status)], sleeps=[])
    with pytest.raises(RuntimeError):
        scanner._sp_get("tok", "https://graph/x")
    assert calls["n"] == 1


def test_retries_are_bounded_and_the_failure_still_surfaces(monkeypatch):
    """An unbounded retry against a throttled tenant is a scan that never finishes and never
    says why."""
    monkeypatch.setenv("ACP_SP_MAX_RETRIES", "2")
    calls = _sequence(monkeypatch, [_Resp(429)], sleeps=[])
    with pytest.raises(RuntimeError):
        scanner._sp_get("tok", "https://graph/x")
    assert calls["n"] == 3, "attempts != 1 initial + 2 retries"


def test_retries_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("ACP_SP_MAX_RETRIES", "0")
    calls = _sequence(monkeypatch, [_Resp(429)], sleeps=[])
    with pytest.raises(RuntimeError):
        scanner._sp_get("tok", "https://graph/x")
    assert calls["n"] == 1


@pytest.mark.parametrize("bad", ["", "nonsense", "-3"])
def test_a_malformed_retry_setting_falls_back(monkeypatch, bad):
    monkeypatch.setenv("ACP_SP_MAX_RETRIES", bad)
    assert scanner._sp_max_retries() in (4, 0)


def test_the_retry_budget_is_capped_however_large_the_setting(monkeypatch):
    """`_sp_get` is the door every SharePoint call goes through, so a generous budget multiplies
    across an estate rather than adding to it."""
    monkeypatch.setenv("ACP_SP_MAX_RETRIES", "500")
    assert scanner._sp_max_retries() == 10


# ── how long to wait ─────────────────────────────────────────────────────────────────────────

def test_graphs_own_Retry_After_is_honoured(monkeypatch):
    """It is the service telling us exactly how long it wants. Guessing shorter earns another
    429; guessing longer wastes the scan's time."""
    sleeps: list = []
    _sequence(monkeypatch, [_Resp(429, headers={"Retry-After": "12"}),
                            _Resp(200, {"value": []})], sleeps=sleeps)
    scanner._sp_get("tok", "https://graph/x")
    assert sleeps == [12.0]


def test_a_hostile_Retry_After_cannot_park_the_scan(monkeypatch):
    """A header is caller-controlled input. One that says 'come back in six hours' must not be
    able to hold a scan open for six hours."""
    sleeps: list = []
    _sequence(monkeypatch, [_Resp(429, headers={"Retry-After": "99999"}),
                            _Resp(200, {"value": []})], sleeps=sleeps)
    scanner._sp_get("tok", "https://graph/x")
    assert sleeps == [120.0]


@pytest.mark.parametrize("header", ["Wed, 21 Oct 2026 07:28:00 GMT", "soon", ""])
def test_an_unparseable_Retry_After_falls_back_to_backoff(monkeypatch, header):
    """Graph may send the HTTP-date form. Falling through to the backoff is right; raising on it
    would turn a throttle into a failed scan."""
    delay = scanner._sp_retry_delay(_Resp(429, headers={"Retry-After": header}), 1)
    assert 0 <= delay <= 60


def test_the_backoff_grows_and_stays_capped():
    """Capped exponential, so a long throttle does not become an unbounded wait."""
    assert all(0 <= scanner._sp_retry_delay(_Resp(429), n) <= 60 for n in range(1, 12))


def test_the_backoff_is_jittered():
    """Not decoration. A 30-site walk that hits a tenant-wide throttle would otherwise retry
    every library in lockstep — re-creating the burst that caused the throttle, at exactly the
    moment the service asked for less."""
    seen = {round(scanner._sp_retry_delay(_Resp(429), 6), 6) for _ in range(40)}
    assert len(seen) > 1, "every retry would fire at the same instant"


def test_a_missing_response_object_still_yields_a_delay():
    """The transport-failure path has no response to read a header from."""
    assert 0 <= scanner._sp_retry_delay(None, 1) <= 60
