"""An expired Drive token must fail once, in plain words — not five times, quoting google-auth.

Live symptom: "2 jobs failed permanently. Reason: The credentials do not contain the necessary
fields need to refresh the access token. You must specify refresh_token, token_uri, client_id,
and client_secret."

Two defects produced it.

1. We asked google-auth to refresh a credential that cannot be refreshed. The GIS implicit flow
   (SignIn.jsx initTokenClient) returns an access token with NO refresh_token. google-auth only
   refreshes when `credentials.expired` is True, and `expired` is False whenever `expiry` is
   None. Every Drive client set `expiry = now + 1h` under a comment claiming it PREVENTED the
   refresh. Once that hour lapsed — a job queued behind a backlog, a long remediation — the
   credential reported expired and google-auth called refresh(), which raised.

2. Nothing classified that as terminal, so the queue retried a deterministic failure five times
   with backoff before dead-lettering it with the library's own words.
"""
import datetime as dt
import sys
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API))

import worker  # noqa: E402


# ── 1. no call site fabricates an expiry ──

SOURCES = ["core.py", "scanner.py", "handlers.py", "routes/drive.py"]


def _code(name: str) -> str:
    """Executable lines only — a comment explaining the deleted bug is not the bug."""
    src = (API / name).read_text()
    return "\n".join(l for l in src.split("\n") if not l.strip().startswith("#"))


@pytest.mark.parametrize("name", SOURCES)
def test_no_drive_client_sets_a_fabricated_expiry(name):
    assert ".expiry" not in _code(name), (
        f"{name} sets creds.expiry; that is what makes google-auth attempt the impossible "
        f"refresh. Leave it None.")


def test_every_drive_client_still_builds_a_credential():
    # Guard against "fixing" the above by deleting the credential.
    assert sum("Credentials(token=" in _code(n) for n in SOURCES) == 4


# ── the google-auth semantics the fix depends on ──

def test_a_credential_without_expiry_is_never_refreshed():
    from google.oauth2.credentials import Credentials
    c = Credentials(token="ya29.x", scopes=["s"])
    assert c.expiry is None
    assert c.expired is False and c.valid is True
    c.before_request(object(), "GET", "https://drive/x", {})   # must not raise


def test_a_credential_with_a_lapsed_expiry_raises_the_reported_error():
    # This is precisely what the deleted line produced, one hour after the client was built.
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    c = Credentials(token="ya29.x", scopes=["s"])
    c.expiry = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=1)
    assert c.expired is True
    with pytest.raises(RefreshError, match="do not contain the necessary fields"):
        c.before_request(object(), "GET", "https://drive/x", {})


# ── 2. the classifier ──

def _http_error(status: int):
    from googleapiclient.errors import HttpError

    class _Resp:
        def __init__(self, s):
            self.status = s
            self.reason = "x"
    return HttpError(_Resp(status), b"{}")


def test_a_refresh_error_is_terminal():
    from google.auth.exceptions import RefreshError
    assert worker.drive_session_expired(RefreshError("no fields")) == worker.DRIVE_SESSION_EXPIRED


def test_a_drive_401_is_terminal():
    assert worker.drive_session_expired(_http_error(401)) == worker.DRIVE_SESSION_EXPIRED


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_rate_limits_and_server_errors_stay_retryable(status):
    # Misclassifying a transient failure as terminal LOSES WORK. The default must be to retry.
    assert worker.drive_session_expired(_http_error(status)) is None


@pytest.mark.parametrize("exc", [ValueError("bad xml"), TimeoutError(), OSError("disk full"),
                                 RuntimeError("boom")])
def test_an_unrecognised_error_keeps_its_retries(exc):
    assert worker.drive_session_expired(exc) is None


def test_the_message_is_actionable_and_quotes_no_library_internals():
    m = worker.DRIVE_SESSION_EXPIRED
    assert "Reconnect Drive" in m and "re-run" in m
    for leak in ["refresh_token", "token_uri", "client_secret", "google", "RefreshError", "401"]:
        assert leak not in m, f"{leak!r} leaks implementation into a user-facing message"


# ── 3. the worker dead-letters it once, and still retries everything else ──

class _FakeStore:
    def __init__(self, job):
        self._job = job
        self.calls = []

    def claim_job(self, worker_id):
        j, self._job = self._job, None
        return j

    def fail_job(self, job_id, error, backoff_seconds=0.0, force_dead=False):
        self.calls.append({"error": error, "force_dead": force_dead,
                           "backoff": backoff_seconds})
        return "dead" if force_dead else "queued"

    def complete_job(self, job_id):
        self.calls.append({"done": True})

    def touch_job(self, job_id):
        pass


def _run(monkeypatch, exc):
    job = {"id": "j1", "type": "scan_file", "payload": {}, "attempts": 1}
    st = _FakeStore(job)
    monkeypatch.setitem(worker.HANDLERS, "scan_file", lambda p, j: (_ for _ in ()).throw(exc))
    w = worker.JobWorker(st, worker_id="w1")
    assert w.run_once() is True
    return st.calls[-1]


def test_an_expired_token_dead_letters_immediately(monkeypatch):
    from google.auth.exceptions import RefreshError
    call = _run(monkeypatch, RefreshError("no fields"))
    assert call["force_dead"] is True                    # no retry — it can never succeed
    assert call["error"] == worker.DRIVE_SESSION_EXPIRED


def test_a_drive_401_dead_letters_immediately(monkeypatch):
    call = _run(monkeypatch, _http_error(401))
    assert call["force_dead"] is True
    assert call["error"] == worker.DRIVE_SESSION_EXPIRED


def test_a_rate_limit_is_still_requeued_with_backoff(monkeypatch):
    call = _run(monkeypatch, _http_error(403))
    assert call["force_dead"] is False
    assert call["backoff"] > 0


def test_an_ordinary_error_is_still_requeued_with_backoff(monkeypatch):
    call = _run(monkeypatch, ValueError("bad xml"))
    assert call["force_dead"] is False
    assert call["backoff"] > 0
    assert "bad xml" in call["error"]


def test_a_fatal_job_error_still_dead_letters(monkeypatch):
    call = _run(monkeypatch, worker.FatalJobError("unsupported"))
    assert call["force_dead"] is True
    assert "unsupported" in call["error"]
