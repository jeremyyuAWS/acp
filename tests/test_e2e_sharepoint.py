"""The estate check asserts what a real SharePoint source can actually be held to.

scripts/e2e_test.py's EXPECTED table is ground truth for the hand-authored local corpus —
named files with known issue floors and score ceilings. A 50-per-type SharePoint estate has no
such ground truth, and pointing the existing flow at one would print 18 "expected file not
scanned" warnings and assert nothing about what IS there.

So --source sharepoint runs estate_assertions() instead. Every property below was chosen
because ITS FAILURE MODE IS A NUMBER THAT LOOKS FINE:

  · a missing file type is invisible in a total ("300 files" reads as success either way)
  · a truncated listing reports a clean, smaller number
  · listed > assessed is CORRECT under ADR 0020's deferred analysis, and reads as loss unless
    both are printed
  · configuration says what should have run; the ai_calls ledger says what did

These import the script directly (it has a __main__ guard) and stub the one network call
estate_assertions makes, so nothing reaches the live service.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "e2e_test.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="needs scripts/e2e_test.py")


def _load():
    spec = importlib.util.spec_from_file_location("acp_e2e", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def e2e(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "_get", lambda path: [], raising=True)
    return mod


def _scan(files, *, discovered=None, truncated=False):
    return {"files": [{"file": f, "issues": [], "score": 90} for f in files],
            "scope": {"kind": "sharepoint", "kept": len(files),
                      "inventory": {"discovered": discovered if discovered is not None else len(files),
                                    "truncated": truncated}}}


def test_a_missing_document_type_fails_rather_than_hiding_in_the_total(e2e):
    """200 files across three types looks like a healthy scan. It is a missing bucket."""
    fails, warns = [], []
    scan = _scan([f"d{i}.docx" for i in range(50)] + [f"p{i}.pdf" for i in range(50)]
                 + [f"s{i}.pptx" for i in range(50)])          # no .xlsx at all
    e2e.estate_assertions(scan, "scan1", 50, fails, warns)
    assert any("xlsx" in f for f in fails), \
        "a document type absent from the whole estate was not reported"


def test_a_short_bucket_warns_without_failing(e2e):
    # Fewer than expected is worth surfacing but is not proof of a fault — the corpus may simply
    # hold fewer of that type. A failure here would train people to ignore the check.
    fails, warns = [], []
    scan = _scan([f"d{i}.docx" for i in range(50)] + [f"x{i}.xlsx" for i in range(3)]
                 + [f"p{i}.pdf" for i in range(50)] + [f"s{i}.pptx" for i in range(50)])
    e2e.estate_assertions(scan, "scan1", 50, fails, warns)
    assert fails == [], "a short bucket was escalated to a failure"
    assert any("xlsx" in w for w in warns)


def test_truncation_is_a_failure_because_the_count_still_looks_clean(e2e):
    """The one failure that cannot be spotted from the result alone."""
    fails, warns = [], []
    scan = _scan([f"d{i}.docx" for i in range(50)] + [f"x{i}.xlsx" for i in range(50)]
                 + [f"p{i}.pdf" for i in range(50)] + [f"s{i}.pptx" for i in range(50)],
                 discovered=5000, truncated=True)
    e2e.estate_assertions(scan, "scan1", 50, fails, warns)
    assert any("TRUNCATED" in f for f in fails)
    assert any("coverage" in f for f in fails), \
        "the message does not say the counts must not be read as coverage"


def test_a_deferred_estate_is_not_treated_as_loss(e2e):
    """ADR 0020: Discover lists and stops; Assess opens files. listed > assessed is CORRECT."""
    fails, warns = [], []
    scan = _scan([f"d{i}.docx" for i in range(10)] + [f"x{i}.xlsx" for i in range(10)]
                 + [f"p{i}.pdf" for i in range(10)] + [f"s{i}.pptx" for i in range(10)],
                 discovered=300)
    e2e.estate_assertions(scan, "scan1", 0, fails, warns)
    assert fails == [], "the deferred-analysis gap was reported as a failure"


def test_assessed_exceeding_discovered_is_a_failure(e2e):
    """The denominators cannot disagree in that direction — one of them is wrong."""
    fails, warns = [], []
    scan = _scan([f"d{i}.docx" for i in range(10)], discovered=3)
    e2e.estate_assertions(scan, "scan1", 0, fails, warns)
    assert any("exceeds discovered" in f for f in fails)


def test_a_silent_fallback_to_the_local_floor_is_surfaced(e2e, monkeypatch):
    """Configuration says what SHOULD run. The ledger says what did. The gap is the finding."""
    mod = e2e
    monkeypatch.setattr(mod, "_get", lambda path: [
        {"provider": "runpod_serverless", "processing_zone": "cloud"},
        {"provider": "runpod_serverless", "processing_zone": "cloud"},
        {"provider": "ollama", "processing_zone": "local"},     # fell back
    ], raising=True)
    fails, warns = [], []
    mod.estate_assertions(_scan(["a.docx"]), "scan1", 0, fails, warns)
    assert any("Mixed providers" in w for w in warns), \
        "a scan partly served by the CPU floor reported as if the GPU did all of it"


def test_no_ai_calls_is_informational_not_a_failure(e2e):
    """Only 1.1.1 remediation uses vision. An estate with no undescribed images is fine."""
    fails, warns = [], []
    e2e.estate_assertions(_scan(["a.docx", "b.xlsx"]), "scan1", 0, fails, warns)
    assert fails == [], "an estate with no vision work was reported as broken"


def test_sharepoint_sends_the_graph_token_on_its_own_header(e2e, monkeypatch):
    # api/routes/scans.py:47 reads `x-sp-token`; the Drive headers would 401 the scan.
    monkeypatch.setattr(e2e, "SOURCE", "sharepoint", raising=False)
    monkeypatch.setattr(e2e, "SP_TOKEN", "tok-123", raising=False)
    monkeypatch.setattr(e2e, "GIS_TOKEN", "drive-tok", raising=False)
    h = e2e._drive_headers()
    assert h == {"x-sp-token": "tok-123"}, \
        f"SharePoint must send only its own token header, got {h}"


def test_drive_is_unaffected_by_the_sharepoint_branch(e2e, monkeypatch):
    monkeypatch.setattr(e2e, "SOURCE", "drive", raising=False)
    monkeypatch.setattr(e2e, "SP_TOKEN", "tok-123", raising=False)
    monkeypatch.setattr(e2e, "GIS_TOKEN", "drive-tok", raising=False)
    assert e2e._drive_headers() == {"x-drive-token": "drive-tok"}
