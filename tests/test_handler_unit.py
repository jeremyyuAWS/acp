"""Unit tests for three previously-uncovered handler paths.

_rescore_file       — re-analysis + aggregate refresh after self-remediation
_assess_trace       — delegation to ensure_assess_trace with correct defaults
_verify_residual_scs — shim delegation contract (never duplicates the logic)

Each test stubs only what it needs and asserts a single behavioural invariant,
so a regression appears as a specific assertion failure, not a mystery error.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


# ── rescore_file ──────────────────────────────────────────────────────────────

def test_rescore_file_calls_analysis_then_refreshes_aggregate(isolated_store, monkeypatch):
    """_rescore_file must call _analyse_and_persist_one BEFORE refresh_scan_aggregate.
    A refresh before analysis would re-publish the OLD numbers to the UI."""
    import core
    import handlers
    import lf

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(lf, "flush", lambda: None)
    monkeypatch.setattr(isolated_store, "get_file_record", lambda sid, f: {})

    call_log = []
    monkeypatch.setattr(handlers, "_analyse_and_persist_one",
                        lambda *a, **k: call_log.append("analyse"))
    monkeypatch.setattr(isolated_store, "refresh_scan_aggregate",
                        lambda sid: call_log.append(f"refresh:{sid}"))

    handlers._rescore_file(
        {"scan_id": "s1", "file": "report.docx", "source": "local"},
        {},
    )

    assert "analyse" in call_log, "_analyse_and_persist_one was not called"
    assert "refresh:s1" in call_log, "refresh_scan_aggregate was not called"
    assert call_log.index("analyse") < call_log.index("refresh:s1"), \
        "aggregate must be refreshed AFTER analysis, not before"


def test_rescore_file_local_path_uses_corpus_dir(isolated_store, monkeypatch):
    """For source='local', the item built for _analyse_and_persist_one must include
    ACP_CORPUS_DIR / filename so the local file is re-downloaded from the right place."""
    import core
    import handlers
    import lf

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(lf, "flush", lambda: None)
    monkeypatch.setenv("ACP_CORPUS_DIR", "/data/corpus")
    monkeypatch.setattr(isolated_store, "get_file_record", lambda sid, f: {})
    monkeypatch.setattr(isolated_store, "refresh_scan_aggregate", lambda sid: None)

    captured = {}

    def fake_analyse(scan_id, item, *a, **k):
        captured.update(item)

    monkeypatch.setattr(handlers, "_analyse_and_persist_one", fake_analyse)

    handlers._rescore_file(
        {"scan_id": "s1", "file": "report.docx", "source": "local"},
        {},
    )

    assert captured.get("path") == "/data/corpus/report.docx"


def test_rescore_file_propagates_drive_file_id_from_stored_record(isolated_store, monkeypatch):
    """drive_file_id from the stored file record must flow into the item so the
    re-download targets the right Drive object rather than a name-based lookup."""
    import core
    import handlers
    import lf

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(lf, "flush", lambda: None)
    monkeypatch.setattr(isolated_store, "get_file_record",
                        lambda sid, f: {"drive_file_id": "drive-abc123"})
    monkeypatch.setattr(isolated_store, "refresh_scan_aggregate", lambda sid: None)

    captured = {}

    def fake_analyse(scan_id, item, *a, **k):
        captured.update(item)

    monkeypatch.setattr(handlers, "_analyse_and_persist_one", fake_analyse)

    # For non-local source, _drive_service is attempted but will fail (no real token);
    # the try/except in _rescore_file catches it, svc stays None, and the test continues.
    handlers._rescore_file(
        {"scan_id": "s1", "file": "report.docx", "source": "drive",
         "drive_token": "tok"},
        {},
    )

    assert captured.get("drive_file_id") == "drive-abc123"


# ── assess_trace ──────────────────────────────────────────────────────────────

def test_assess_trace_defaults_level_to_AA(isolated_store, monkeypatch):
    """When 'level' is absent from the payload, _assess_trace must forward 'AA'
    to ensure_assess_trace — the standard WCAG conformance level."""
    import core
    import handlers

    monkeypatch.setattr(core, "store", isolated_store)

    captured = {}

    def fake_ensure(scan_id, level="AA"):
        captured["scan_id"] = scan_id
        captured["level"] = level

    monkeypatch.setattr(handlers, "ensure_assess_trace", fake_ensure)

    handlers._assess_trace({"scan_id": "s1"}, {})

    assert captured == {"scan_id": "s1", "level": "AA"}


def test_assess_trace_passes_explicit_level(isolated_store, monkeypatch):
    """An explicit 'level' in the payload overrides the AA default."""
    import core
    import handlers

    monkeypatch.setattr(core, "store", isolated_store)

    captured = {}

    def fake_ensure(scan_id, level="AA"):
        captured["level"] = level

    monkeypatch.setattr(handlers, "ensure_assess_trace", fake_ensure)

    handlers._assess_trace({"scan_id": "s1", "level": "AAA"}, {})

    assert captured["level"] == "AAA"


# ── _verify_residual_scs ──────────────────────────────────────────────────────

def test_verify_residual_scs_delegates_to_proposals(monkeypatch):
    """_verify_residual_scs is a thin shim. The invariant is that it always delegates
    to proposals.verify_residual_scs — never duplicates the logic — so the proposal
    lane and the remediation loop share the exact same residual re-scan path."""
    import proposals
    import handlers

    captured = {}

    def fake_verify(fixed_bytes, filename):
        captured["bytes"] = fixed_bytes
        captured["file"] = filename
        return {"1.1.1", "1.4.3"}

    monkeypatch.setattr(proposals, "verify_residual_scs", fake_verify)

    result = handlers._verify_residual_scs(b"\x00fake bytes", "report.docx")

    assert captured == {"bytes": b"\x00fake bytes", "file": "report.docx"}, \
        "arguments must be forwarded unchanged to proposals.verify_residual_scs"
    assert result == {"1.1.1", "1.4.3"}, \
        "return value must be forwarded unchanged from proposals.verify_residual_scs"


def test_verify_residual_scs_empty_set_means_fix_cleared(monkeypatch):
    """An empty set from proposals.verify_residual_scs means all SCs cleared.
    The callers use 'if residual' / '_sc not in residual' — the empty set must
    propagate unchanged so both patterns evaluate correctly."""
    import proposals
    import handlers

    monkeypatch.setattr(proposals, "verify_residual_scs", lambda b, f: set())

    result = handlers._verify_residual_scs(b"fixed bytes", "clean.docx")

    assert result == set()
    assert not result, "empty set must be falsy so callers do not refuse credit"
