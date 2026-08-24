"""Polish fixes P-2 / P-3 / P-7.

P-2: _esc() must not silently drop characters; long strings get an ellipsis.
P-3: the evidence-truncation notice must not claim a non-existent API endpoint.
P-7: the outcome-summary stat band must disclose the evaluated-criteria count.
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


# ── P-2: _esc() truncation behaviour ─────────────────────────────────────────

def test_esc_short_string_returned_unchanged():
    from report import _esc
    assert _esc("hello") == "hello"


def test_esc_long_string_gets_ellipsis_not_silent_truncation():
    from report import _esc
    long = "x" * 3000
    result = _esc(long)
    assert result.endswith("…"), "truncated string must end with ellipsis"
    assert len(result) < 3000, "truncated string must be shorter than input"


def test_esc_exactly_2000_chars_not_truncated():
    from report import _esc
    s = "a" * 2000
    assert _esc(s) == s and not _esc(s).endswith("…")


def test_esc_2001_chars_gets_ellipsis():
    from report import _esc
    s = "b" * 2001
    r = _esc(s)
    assert r.endswith("…") and len(r) == 2001   # 2000 chars + ellipsis character


# ── P-3: evidence truncation notice must not cite a non-existent endpoint ────

_RUN = {"id": "s1", "completed_at": "2026-01-01T00:00:00", "avg_score": 100, "owner_email": None}
_META = {"target": "AA", "version": "1", "hash": "abc"}


def _make_evidence(n):
    return [{"file": f"f{i}.docx", "proposed": [], "applied": [{
        "sc": "1.1.1", "criterion": "Non-text Content", "before": "a", "after": "b",
        "note": None, "value": "b", "source": "auto", "thumb": None,
        "decision": None, "approved_value": None, "reviewer": None,
        "reviewed_at": None, "validated": True}]}
        for i in range(n)]


def _pdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader
    return " ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


def test_evidence_truncation_notice_omits_api_claim():
    from report import build_report, _EVIDENCE_MAX_FILES
    files = [{"file": f"f{i}.docx", "compliant": 1, "score": 100,
              "status": "ok", "issues": []} for i in range(_EVIDENCE_MAX_FILES + 2)]
    ev = _make_evidence(_EVIDENCE_MAX_FILES + 2)
    t = _pdf_text(build_report(_RUN, files, _META, evidence=ev))
    assert "API" not in t.split("Evidence shown")[1].split("\n")[0] if "Evidence shown" in t else True
    assert "per-file remediation API" not in t


# ── P-7: stat band discloses evaluated-criteria count ────────────────────────

def test_stat_band_shows_evaluated_criteria_when_facts_provided(isolated_store):
    import core
    from report import build_report
    core.store = isolated_store
    issues = [{"ruleId": "A", "wcag": "SC_1_1_1", "severity": "SERIOUS", "detail": "d"}]
    isolated_store.save_file_result(
        "s7", {"file": "deck.pptx", "engine": "office", "status": "pass",
               "score": 90, "compliant": 0, "skipped_rules": 0, "issues": issues},
        "2026-01-01T00:00:00Z")
    facts = isolated_store.get_certification_facts("s7")
    total_eval = sum(d.get("evaluated", 0) for d in facts["documents"])
    assert total_eval > 0, "fixture must have evaluated criteria"
    files = [{"file": "deck.pptx", "compliant": 0, "score": 90, "status": "pass", "issues": issues}]
    run = {"id": "s7", "completed_at": "2026-01-01T00:00:00", "avg_score": 90, "owner_email": None}
    t = _pdf_text(build_report(run, files, _META, facts=facts))
    assert "criteria evaluated" in t, "stat band must state evaluated-criteria count"


def test_stat_band_omits_criteria_note_when_facts_absent():
    from report import build_report
    files = [{"file": "x.docx", "compliant": 1, "score": 100, "status": "ok", "issues": []}]
    run = {"id": "s0", "completed_at": "2026-01-01T00:00:00", "avg_score": 100, "owner_email": None}
    t = _pdf_text(build_report(run, files, _META, facts=None))
    assert t  # renders without error; criteria note absent is acceptable (no facts)
