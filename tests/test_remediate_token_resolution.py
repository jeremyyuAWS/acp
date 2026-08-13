"""The Drive token a remediate job uses must survive a restart/redeploy.

Background (roadmap #1, verified stale 2026-08-12): "Couldn't remediate this file" was blamed on a
missing write scope + a Blob fallback that didn't catch it. Both are fixed — DRIVE_SCOPES grants
drive.file, the Blob copy is written first and unconditionally (ADR 0010), and the Drive-mirror 403
is caught. The ONE real residual path is a token that expired/was-wiped before a queued job ran. The
mitigation is that the token rides the DURABLE job payload, not only the per-replica in-memory store
(handlers.py:448-454). These tests pin that: the payload token is used when the in-memory store is
empty, and only a total absence of any token fails the job — with the honest 're-trigger' message,
never a silent bad write."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _payload(**over):
    p = {"scan_id": "s1", "file": "a.docx", "drive_file_id": "1a"}
    p.update(over)
    return p


def test_payload_token_survives_a_wiped_in_memory_store(monkeypatch):
    import core
    import handlers
    # Simulate the failure the mitigation exists for: the per-replica in-memory scan tokens are gone
    # (restart/redeploy), so only the durable payload token is left.
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {})
    monkeypatch.setattr(core.store, "is_shadowed_output", lambda sid, f: False)
    monkeypatch.setattr(handlers, "_phase", lambda *a, **k: None)

    class _PastTokenGuard(Exception):
        pass

    def _drive_client(tok):
        assert tok == "durable-tok", "the job must use the token from the durable payload"
        raise _PastTokenGuard()   # stop right after the token guard — we only assert we got here

    monkeypatch.setattr(handlers, "_drive_client", _drive_client)

    with pytest.raises(_PastTokenGuard):
        handlers._remediate_file(_payload(drive_token="durable-tok"), {})


def test_no_token_anywhere_fails_cleanly_asking_for_a_re_trigger(monkeypatch):
    import core
    import handlers
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {})
    monkeypatch.setattr(core.store, "is_shadowed_output", lambda sid, f: False)
    # No payload token AND no in-memory token → a clean FatalJobError, not a partial/bad write.
    with pytest.raises(handlers.FatalJobError, match="no Drive token"):
        handlers._remediate_file(_payload(), {})
