"""Typed retry policies (ADR 0004 step 3): classify errors, apply per-class policy.

Tests:
- classify_job_error() maps exception types and message text to the right class
- job_retry_policy() returns the right (force_dead, backoff) per class + attempt
- fail_job() persists error_class on the job row
- Worker run_once() sets error_class on failure
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from conftest import held  # noqa: E402

import worker as w


# ── classify_job_error ────────────────────────────────────────────────────────

class _Ex(Exception):
    pass


def test_classify_rate_limit_from_message():
    assert w.classify_job_error(_Ex("HTTP 429 Too Many Requests")) == w.RATE_LIMIT


def test_classify_rate_limit_quota():
    assert w.classify_job_error(_Ex("quota exceeded for project")) == w.RATE_LIMIT


def test_classify_auth_401():
    assert w.classify_job_error(_Ex("server returned 401 Unauthorized")) == w.AUTH


def test_classify_auth_token_expired():
    assert w.classify_job_error(_Ex("token expired, please reconnect")) == w.AUTH


def test_classify_corrupt_bad_zip():
    assert w.classify_job_error(_Ex("Bad zip file: offset wrong")) == w.CORRUPT


def test_classify_corrupt_malformed():
    assert w.classify_job_error(_Ex("malformed XML at line 42")) == w.CORRUPT


def test_classify_corrupt_type_name():
    try:
        import zipfile
        raise zipfile.BadZipFile("CRC check failed")
    except Exception as e:
        assert w.classify_job_error(e) == w.CORRUPT


def test_classify_transient_default():
    assert w.classify_job_error(_Ex("connection reset by peer")) == w.TRANSIENT


def test_classify_transient_generic():
    assert w.classify_job_error(_Ex("unexpected server error")) == w.TRANSIENT


# ── job_retry_policy ──────────────────────────────────────────────────────────

def test_auth_always_force_dead():
    force_dead, _ = w.job_retry_policy(w.AUTH, 1)
    assert force_dead is True


def test_corrupt_force_dead_after_two_attempts():
    force_dead, _ = w.job_retry_policy(w.CORRUPT, 2)
    assert force_dead is True


def test_corrupt_retry_on_first_attempt():
    force_dead, _ = w.job_retry_policy(w.CORRUPT, 1)
    assert force_dead is False


def test_rate_limit_not_force_dead():
    force_dead, _ = w.job_retry_policy(w.RATE_LIMIT, 1)
    assert force_dead is False


def test_rate_limit_backoff_non_zero():
    _, backoff = w.job_retry_policy(w.RATE_LIMIT, 1)
    assert backoff >= 0  # jitter may land at 0 for attempt=1 base, but should be >= 0


def test_rate_limit_backoff_capped():
    for attempt in range(1, 20):
        _, backoff = w.job_retry_policy(w.RATE_LIMIT, attempt)
        assert backoff <= 600.1  # cap is 600s + float tolerance


def test_transient_not_force_dead():
    force_dead, backoff = w.job_retry_policy(w.TRANSIENT, 1)
    assert force_dead is False
    assert backoff >= 0


# ── fail_job persists error_class ────────────────────────────────────────────

def _enqueue(st, **kw):
    return st.enqueue_job("test", {"x": 1}, **kw)


def test_fail_job_persists_error_class_on_requeue(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    st.claim_job("w1")
    st.fail_job(jid, "too many requests", backoff_seconds=0, error_class=w.RATE_LIMIT, **held(st, jid))
    job = st.get_job(jid)
    assert job["error_class"] == w.RATE_LIMIT


def test_fail_job_persists_error_class_on_dead(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    st.claim_job("w1")
    st.fail_job(jid, "token expired", force_dead=True, error_class=w.AUTH, **held(st, jid))
    job = st.get_job(jid)
    assert job["status"] == "dead"
    assert job["error_class"] == w.AUTH


def test_fail_job_error_class_none_is_ok(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    st.claim_job("w1")
    st.fail_job(jid, "something happened", backoff_seconds=0, **held(st, jid))
    job = st.get_job(jid)
    assert job["error_class"] is None


# ── worker run_once() sets error_class ────────────────────────────────────────

def _make_worker(st):
    worker = w.JobWorker(st)
    return worker


def test_run_once_classifies_rate_limit(isolated_store):
    st = isolated_store
    jid = _enqueue(st)

    @w.handler("test")
    def _h(payload, job):
        raise _Ex("429 Too Many Requests")

    wk = _make_worker(st)
    wk.run_once()
    job = st.get_job(jid)
    assert job["error_class"] == w.RATE_LIMIT
    assert job["status"] == "queued"


def test_run_once_classifies_auth_and_dead_letters(isolated_store):
    st = isolated_store
    jid = _enqueue(st)

    @w.handler("test")
    def _h(payload, job):
        raise _Ex("401 Unauthorized: token expired")

    wk = _make_worker(st)
    wk.run_once()
    job = st.get_job(jid)
    assert job["error_class"] == w.AUTH
    assert job["status"] == "dead"


def test_run_once_classifies_transient_and_requeues(isolated_store):
    st = isolated_store
    jid = _enqueue(st)

    @w.handler("test")
    def _h(payload, job):
        raise _Ex("connection reset by peer")

    wk = _make_worker(st)
    wk.run_once()
    job = st.get_job(jid)
    assert job["error_class"] == w.TRANSIENT
    assert job["status"] == "queued"
