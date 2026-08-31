"""A missing analysis engine withholds credit — the deliberate cost of failing closed.

This is the half of the fail-closed change that is a REAL BEHAVIOUR CHANGE rather than a bug
fix, so it is asserted here rather than discovered later in production.

WHAT CHANGED. Office analysis shells out to the .NET CLI. When that CLI is absent, times out,
or dies, `scanner` records `succeeded: False` and the rubric grades the scan ERROR — for the
whole document, however healthy it is. Under the old fail-open verification the residual was
read off `issues` and the status thrown away, so an Office document scanned WITHOUT the
analyser looked exactly like one that had been scanned and found clean, and was credited.
Now it verifies nothing and credits nothing.

WHY THAT IS THE RIGHT READING, and not over-strictness: the first-party detectors do still run
and would still observe the criterion, so it is tempting to credit on those alone. But "the
checks that ran found nothing" is only evidence of compliance if you know WHICH checks ran.
A document whose engine died is a document nobody assessed; crediting it publishes a claim
about a file no analyser ever opened. The rubric already says exactly this — ERROR is
"unscored, not certifiable" — and the verification seam now honours it.

WHAT IT COSTS, so nobody has to rediscover it: on a developer host with no .NET SDK, every
Office remediation lane withholds credit. That is why the 17 lane proofs stand in for the
analyser (see tests/test_remediation_verified_*.py) instead of silently depending on whether
one is installed. It also means a production deployment that loses the Office CLI stops
certifying Office documents rather than certifying them wrongly — which is the intended
failure direction, and is what `scripts/check_engines.py --require office,pdf,ocr` exists to
catch in CI before it reaches one.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

FILE = "report.docx"


def _docx_with_undescribed_image() -> bytes:
    """A real .docx whose inline image carries no alt text — a genuine 1.1.1 failure."""
    from test_remediation_verified_docx_alt import _doc
    return _doc()


def _healthy_office_engine(monkeypatch):
    """Stand in for the .NET Office analyser as CI builds it: a run that SUCCEEDED and found
    nothing of its own. The first-party detectors still supply the real findings, so this
    changes only whether the scan grades `analysed` — which is precisely the variable under
    test."""
    import scanner

    def analyse(tmp):
        out = {}
        for p in Path(tmp).iterdir():
            out[p.name] = {"succeeded": True, "errors": [], "issues": []}
        return out

    monkeypatch.setattr(scanner, "_analyse_office", analyse)


def _dead_office_engine(monkeypatch, *, errors=("office CLI not found",)):
    """The engine-missing / engine-crashed shape scanner produces for real."""
    import scanner

    def analyse(tmp):
        return {p.name: {"succeeded": False, "errors": list(errors), "issues": []}
                for p in Path(tmp).iterdir()}

    monkeypatch.setattr(scanner, "_analyse_office", analyse)


# ── the two worlds, side by side ──────────────────────────────────────────────
def test_with_the_engine_present_an_office_scan_verifies(monkeypatch):
    """Baseline. With a healthy analyser the scan grades `analysed`, verification succeeds,
    and the criterion the first-party detectors found is reported as residual."""
    from proposals import verify_residual
    _healthy_office_engine(monkeypatch)

    v = verify_residual(_docx_with_undescribed_image(), FILE)
    assert v.ok, f"a healthy Office scan must verify, got {v!r}"
    assert "1.1.1" in v.residual, "the first-party detector still supplies the finding"
    assert not v.cleared({"1.1.1"}), "and it is still failing, so not cleared"


def test_with_the_engine_missing_nothing_is_credited(monkeypatch):
    """THE BEHAVIOUR CHANGE. Same document, same first-party findings, dead engine — and now
    the answer is 'could not verify' rather than a credit."""
    from proposals import verify_residual
    _dead_office_engine(monkeypatch)

    v = verify_residual(_docx_with_undescribed_image(), FILE)
    assert not v.ok, f"a scan whose engine died must not report ok, got {v!r}"
    assert "error" in v.reason, f"the reason must name the failure, got {v.reason!r}"
    assert not v.cleared({"1.1.1"})


def test_a_document_that_looks_clean_to_a_dead_engine_is_still_not_credited(monkeypatch):
    """The dangerous shape, stated on its own. Take a document with NO first-party findings
    either — so the residual really is empty — and confirm the empty residual still does not
    buy credit while the engine is dead. This is the case the old code got wrong in the most
    expensive direction: a fully unassessed document reading as fully compliant."""
    from proposals import verify_residual
    import io

    # a .docx with no image, no links, no sensory wording: nothing for anyone to find
    src = _docx_with_undescribed_image()
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(src)) as zin, zipfile.ZipFile(buf, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = re.sub(rb"<w:drawing>.*?</w:drawing>", b"", data, flags=re.S)
            zout.writestr(item, data)
    plain = buf.getvalue()

    _dead_office_engine(monkeypatch)
    v = verify_residual(plain, FILE)
    assert v.residual == frozenset(), "nothing was found — the residual really is empty"
    assert not v.ok, "but nothing ran either"
    assert not v.cleared({"1.1.1"}), (
        "AN UNASSESSED DOCUMENT MUST NOT CERTIFY. This is the exact case the fail-open "
        "verification credited: no findings, because no engine.")

    # ...and with the engine alive, the same bytes DO verify as clear.
    _healthy_office_engine(monkeypatch)
    v2 = verify_residual(plain, FILE)
    assert v2.ok and v2.cleared({"1.1.1"}), (
        f"the same document must verify clean once an engine actually runs, got {v2!r}")


def test_a_timeout_reads_as_unverifiable_not_as_clean(monkeypatch):
    """`ACP_OFFICE_CLI_TIMEOUT` fires as a failed run with an error, not as an exception, so
    it reaches verification as `succeeded: False` — the same shape as a missing engine."""
    from proposals import verify_residual
    _dead_office_engine(monkeypatch, errors=("office CLI exceeded ACP_OFFICE_CLI_TIMEOUT",))

    v = verify_residual(_docx_with_undescribed_image(), FILE)
    assert not v.ok and not v.cleared({"1.1.1"})


def test_the_observational_shim_still_reports_what_first_party_checks_found(monkeypatch):
    """The shim keeps working for the ~15 tests that ask an observational question. On a host
    with no analyser it still reports the first-party findings — which is why it must not be
    used to grant credit, and why it is kept for the tests that only want to look."""
    from proposals import verify_residual_scs
    _dead_office_engine(monkeypatch)

    assert "1.1.1" in (verify_residual_scs(_docx_with_undescribed_image(), FILE) or set()), (
        "the observational shim reports what the first-party detectors saw, engine or not")
