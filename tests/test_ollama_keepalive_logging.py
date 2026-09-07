"""The expected Ollama prewarm timeout is useful signal, not an incident traceback."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import app


def test_keepalive_timeout_emits_one_concise_structured_warning(monkeypatch, caplog):
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("Ollama is waking")

    monkeypatch.setattr(httpx, "post", timeout)

    with caplog.at_level(logging.WARNING, logger="app"):
        app._ollama_keepalive_ping()

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == (
        "event=ollama.keepalive_timeout timeout_seconds=60 action=ignored"
    )
    assert record.exc_info is None
    assert "Traceback" not in logging.Formatter().format(record)


def test_unexpected_keepalive_failure_keeps_traceback_diagnostics(monkeypatch, caplog):
    import swallowed

    swallowed.reset()

    def fail(*args, **kwargs):
        raise RuntimeError("bad keepalive payload")

    monkeypatch.setattr(httpx, "post", fail)

    with caplog.at_level(logging.WARNING, logger="swallowed"):
        app._ollama_keepalive_ping()

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert "Ollama keep-alive ping failed" in record.getMessage()
    assert record.exc_info is not None
    assert "bad keepalive payload" in logging.Formatter().format(record)
    swallowed.reset()
