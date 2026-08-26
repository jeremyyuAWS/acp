"""The Drive token a scan_discover job uses must survive a worker restart/redeploy.

Mirror of test_remediate_token_resolution — the same split-topology bug (PR #716) applied to
the discovery path. Before the fix, drive_token was only in the API replica's in-memory store
(core.SCAN_TOKENS). A worker running in a separate container had no access to it, so
get_scan_tokens() returned {} and every Drive scan ran unauthenticated against ADC — which
resolved to the service-account's empty Drive and returned 0 documents.

Fix (api/routes/scans.py, enqueue_job call): drive_token is now included in the durable job
payload so the worker can authenticate regardless of memory state."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


class _StopAfterTokenCheck(Exception):
    """Raised to halt _scan_discover immediately after the Drive service is built."""


def _payload(**over):
    base = {"source": "drive", "scan_id": "s-disc-1", "ai": False}
    base.update(over)
    return base


class _StubRubric:
    name = "test"
    hash = "00"

    @classmethod
    def load_active(cls, *_):
        return cls()


def _minimal_stubs(monkeypatch):
    """Patch away every side-effect in _scan_discover that runs before or after the
    token is resolved, so the test is only about token resolution."""
    import core
    import rubric as rubric_mod
    import scanner

    # No in-memory token — simulates a worker container that never saw the scan start.
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {})

    # Rubric.load_active is called before _drive_service; stub it to avoid touching disk.
    monkeypatch.setattr(rubric_mod, "Rubric", _StubRubric)

    # _scope_for_listing reads the DB — not under test here.
    monkeypatch.setattr(scanner, "_scope_for_listing", lambda user=None: None)

    import handlers
    return handlers


def test_payload_token_is_used_when_in_memory_store_is_empty(monkeypatch):
    """When the in-memory token store is clear (different replica), _scan_discover must
    use the drive_token from the durable job payload to build the Drive service."""
    import scanner
    handlers = _minimal_stubs(monkeypatch)

    seen = {}

    def _fake_drive_service(tok):
        seen["tok"] = tok
        raise _StopAfterTokenCheck()

    monkeypatch.setattr(scanner, "_drive_service", _fake_drive_service)

    with pytest.raises(_StopAfterTokenCheck):
        handlers._scan_discover(_payload(drive_token="payload-tok"), {})

    assert seen.get("tok") == "payload-tok", (
        "_scan_discover must pass the payload drive_token to _drive_service; "
        "passing None falls back to ADC (service-account Drive) and returns 0 files"
    )


def test_in_memory_token_is_used_as_fallback_when_payload_has_none(monkeypatch):
    """When the payload has no drive_token (e.g. an older queued job pre-#716), the
    in-memory store is consulted as a fallback so same-replica scans keep working."""
    import core
    import scanner
    handlers = _minimal_stubs(monkeypatch)

    # Override: in-memory DOES have a token (same-replica path).
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {"drive": "memory-tok"})

    seen = {}

    def _fake_drive_service(tok):
        seen["tok"] = tok
        raise _StopAfterTokenCheck()

    monkeypatch.setattr(scanner, "_drive_service", _fake_drive_service)

    with pytest.raises(_StopAfterTokenCheck):
        handlers._scan_discover(_payload(), {})  # no drive_token in payload

    assert seen.get("tok") == "memory-tok"


def test_no_token_falls_back_to_adc(monkeypatch):
    """When neither payload nor in-memory store has a token, _scan_discover passes None to
    _drive_service, which falls back to ADC. This is the root cause of the 0-result bug:
    ADC resolves to a service-account with no user files. The test documents the fallback
    so the gap is visible rather than silently returning empty results."""
    import scanner
    handlers = _minimal_stubs(monkeypatch)

    seen = {}

    def _fake_drive_service(tok):
        seen["tok"] = tok
        raise _StopAfterTokenCheck()

    monkeypatch.setattr(scanner, "_drive_service", _fake_drive_service)

    with pytest.raises(_StopAfterTokenCheck):
        handlers._scan_discover(_payload(), {})  # no token anywhere

    assert seen.get("tok") is None, (
        "with no token _scan_discover passes None → ADC fallback → service-account Drive → "
        "0 files. Callers must ensure drive_token is in the payload (see PR #716)."
    )
