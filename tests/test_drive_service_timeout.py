"""`scanner._drive_service` must hand Drive a BOUNDED socket.

`build("drive", "v3", credentials=creds, cache_discovery=False)` (the old shape) has no timeout —
httplib2's underlying socket blocks with the platform default, effectively forever, until data
arrives or the connection is torn down at a lower layer. `.execute(num_retries=5)` retries on an
HTTP error or a raised httplib2/socket exception, but a genuinely STALLED connection (a network
blip that neither returns data nor errors) raises neither, so num_retries never gets a chance to
act — the call just never returns.

Found live 2026-08-29: a discovery job sat on "Build document inventory" for 250+ seconds with the
queue worker reporting online and the job itself 'running' — the exact failure mode worker.py's
own max_unverified_lease_s() docstring warns about ("blocked on a socket with no timeout... the
queue showing 'N active · 0 waiting' and draining nothing").

These tests don't hit the network — they capture what `googleapiclient.discovery.build` is called
with and assert the http client it's handed carries a real, finite timeout.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import scanner  # noqa: E402


@pytest.fixture()
def capture_build(monkeypatch):
    """Stub googleapiclient.discovery.build to record its kwargs instead of hitting the network."""
    calls = []

    def _fake_build(*args, **kwargs):
        calls.append(kwargs)
        return "fake-drive-service"

    import googleapiclient.discovery
    monkeypatch.setattr(googleapiclient.discovery, "build", _fake_build)
    return calls


def test_a_per_user_token_gets_a_bounded_http_client(capture_build, monkeypatch):
    calls = capture_build
    result = scanner._drive_service(drive_token="fake-token")
    assert result == "fake-drive-service"
    assert len(calls) == 1
    kwargs = calls[0]
    # build() refuses `http=` and `credentials=` together, so getting a timeout through means
    # this now goes via `http=`, not the `credentials=` shortcut.
    assert "credentials" not in kwargs
    http = kwargs.get("http")
    assert http is not None, "no http= client was passed — Drive calls would use an unbounded socket"
    assert http.http.timeout == scanner._DRIVE_HTTP_TIMEOUT_S


def test_the_adc_fallback_also_gets_a_bounded_http_client(capture_build, monkeypatch):
    import google.auth
    monkeypatch.setattr(google.auth, "default", lambda **k: ("fake-creds", "fake-project"))

    scanner._drive_service(drive_token=None)

    kwargs = capture_build[0]
    assert "credentials" not in kwargs
    assert kwargs["http"].http.timeout == scanner._DRIVE_HTTP_TIMEOUT_S


def test_the_default_timeout_is_a_real_finite_number_not_a_no_op():
    """Guards against a regression back to `timeout=None` (httplib2's own default, i.e.
    unbounded) — `_DISCOVERY_WORKERS` two lines above this constant is read the same
    `int(os.environ.get(…))` way and has no dedicated env-override test either; what matters
    here is that the value in force is a real, finite bound, not which env var reads it."""
    assert isinstance(scanner._DRIVE_HTTP_TIMEOUT_S, int)
    assert 0 < scanner._DRIVE_HTTP_TIMEOUT_S < 600


# ── core.drive_service — same bug, same fix, the request-time (not background-job) call site ──

import core  # noqa: E402


def test_core_drive_service_with_a_gis_token_gets_a_bounded_http_client(capture_build, monkeypatch):
    class Req:
        headers = {"x-drive-token": "fake-token"}

    core.drive_service(Req())

    kwargs = capture_build[0]
    assert "credentials" not in kwargs
    assert kwargs["http"].http.timeout == core._DRIVE_HTTP_TIMEOUT_S


def test_core_drive_service_adc_fallback_gets_a_bounded_http_client(capture_build, monkeypatch):
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    import google.auth
    monkeypatch.setattr(google.auth, "default", lambda **k: ("fake-creds", "fake-project"))

    core.drive_service(None)

    kwargs = capture_build[0]
    assert "credentials" not in kwargs
    assert kwargs["http"].http.timeout == core._DRIVE_HTTP_TIMEOUT_S
