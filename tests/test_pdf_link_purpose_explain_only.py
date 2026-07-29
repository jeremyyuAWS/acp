"""WCAG 2.4.4 Link Purpose on PDF is EXPLAIN-ONLY: assessed, never proposed.

The regression these pin closed: remediate_pdf used to emit a link-purpose review card whose
locator was the raw URI, and no PDF writer could route it. apply_pdf_approved handles
`pdf:fig:` (→ /Alt) and `pdf:field:` (→ /TU); a URI locator fell through to `unknown`, and
handlers._apply_approved_values returns before any of that for a non-Office extension. So a
reviewer approved a link-text card and the document was unchanged, with no error surfaced —
the finding merely LOOKED handled. It was also unresolvable: an approved row holding a
locator + value is counted by store.count_unapplied_approved_values forever, so the file could
never certify and never reached Publish.

Writing the label is the alternative, and it is the one the proposer's own docstring ruled out:
the visible label is drawn by text-showing operators, so replacing it re-flows the page's glyph
widths — re-authoring, not remediation (ADR 0016).

The contract, in one line: **an approved PDF 2.4.4 value either changes the bytes or is never
offered.** test_a_link_value_is_appliable_or_never_offered asserts exactly that, so a future
change may re-add the card only by also building the writer.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import remediate_pdf as rp  # noqa: E402
from conftest import requires_pdf_engine  # noqa: E402

reportlab = pytest.importorskip("reportlab")
pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("pdfplumber")

URL = "https://example.org/reports/regional-summary-2026.pdf"


def _raw_url_pdf(tmp: Path) -> Path:
    """The flagged shape: a /Link annotation whose visible text IS its target URL — exactly
    office_structure.pdf_link_purpose_check's predicate."""
    from reportlab.pdfgen import canvas
    p = tmp / "raw-url-link.pdf"
    c = canvas.Canvas(str(p))
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, URL)
    c.linkURL(URL, (72, 695, 460, 715), relative=0)
    c.drawString(72, 650, "Body prose so the page carries readable text for extraction.")
    c.save()
    return p


def _remediate(src: Path) -> list[dict]:
    """Run the real PDF remediator over `src` and return the proposals it emitted."""
    props: list[dict] = []
    rp.remediate_pdf(src, ai_enabled=False, proposals=props, diffs=[], applied_fixes=[])
    return props


# ── the finding is real, and it is still assessed ──────────────────────────────

def test_the_detector_still_flags_the_raw_url_link(tmp_path):
    """Explain-only is a statement about the FIX, not the assessment. Dropping the proposal
    must not quietly drop the finding — that would be a worse dishonesty than the one it fixes."""
    from office_structure import pdf_link_purpose_check
    assert pdf_link_purpose_check(_raw_url_pdf(tmp_path)), "2.4.4 stopped being detected on PDF"


# ── the contract ───────────────────────────────────────────────────────────────

@requires_pdf_engine
def test_a_link_value_is_appliable_or_never_offered(tmp_path):
    """THE regression. Either the card is not offered, or approving it changes the document.

    Written as one assertion over both branches on purpose: it holds today because no card is
    offered, and it keeps holding if someone builds the write-back — but it fails loudly for
    the state that shipped, a card whose approval is a silent no-op."""
    src = _raw_url_pdf(tmp_path)
    data = src.read_bytes()
    cards = [p for p in _remediate(src) if p.get("kind") == "link-purpose"]
    if not cards:
        return                                   # never offered — the contract holds
    fixed, applied, unresolved = rp.apply_pdf_approved(
        data, {p["locator"]: p["proposed_value"] for p in cards})
    assert not unresolved, (
        f"2.4.4 card(s) offered for PDF whose locators no writer routes: {unresolved}. "
        "Either build the write-back or stop enqueueing the card — an approval that cannot "
        "be honoured leaves the finding looking handled.")
    assert fixed != data, "the approved link text was routed but changed nothing in the file"


@requires_pdf_engine
def test_remediation_emits_no_link_purpose_proposal(tmp_path):
    props = _remediate(_raw_url_pdf(tmp_path))
    assert [p for p in props if p.get("kind") == "link-purpose"] == []


def test_the_writer_cannot_route_a_uri_locator(tmp_path):
    """The other half of the contract, asserted directly on the writer so it runs everywhere:
    a raw-URI locator is unroutable. This is WHY the card cannot be offered — if someone
    teaches apply_pdf_approved to handle link text, this test is the one that goes green
    first, and re-adding the card becomes legitimate."""
    data = _raw_url_pdf(tmp_path).read_bytes()
    fixed, applied, unresolved = rp.apply_pdf_approved(
        data, {URL: "Download Regional Summary 2026 (PDF)"})
    assert applied == [] and unresolved == [URL]
    assert fixed == data


def test_the_remediator_has_no_link_purpose_proposer_at_all():
    """The engine-gated tests above skip on a clean checkout (the partner PDF engine is a
    separate repo), so the same claim is also asserted structurally — here it always runs."""
    src = (ACP / "api" / "remediate_pdf.py").read_text()
    assert 'kind="link-purpose"' not in src
    assert "_propose_pdf_link_purpose" not in src


def test_the_handler_never_enqueues_a_244_card_for_pdf():
    """The other half of the wiring: even a stray link-purpose proposal must not reach a rule.
    Source-level, like the sibling wiring test — the enqueue is inside the remediate_file job."""
    src = (ACP / "api" / "handlers.py").read_text()
    pdf_branch = src[src.index('if ext == "pdf":'):src.index("else:  # docx / pptx / xlsx")]
    assert '"link-purpose"' not in pdf_branch
    assert '"2.4.4"' not in pdf_branch


def test_the_capability_lane_records_explain_only():
    """The matrix ceiling is derived from this lane (scripts/gen_matrix_coverage.py maps
    'human' → guided-manual). Claiming 'assisted' here is what let the grid advertise an
    AI-proposal fix path that could not complete."""
    import remediation_capability as cap
    assert cap.mode_for("pdf", "2.4.4") == cap.HUMAN


# ── why the card had to go: the certification gate ─────────────────────────────

SID = "s-pdf-244"
FILE = "report.pdf"


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "pdf244.db")
    return store_mod.Store()


def _remediated_pdf_record(store):
    store.init_scan_run(SID, "drive", 1, "2026-07-10T00:00:00Z", "rubric", "hash")
    store.save_file_result(SID, {
        "file": FILE, "engine": "pdf", "status": "fail", "score": 60, "compliant": 0,
        "skipped_rules": 0, "drive_file_id": "drv1",
        "issues": [{"ruleId": "PDF_LINK_RAW_URL", "wcag": "2.4.4", "severity": "MODERATE"}],
    }, "2026-07-10T00:00:00Z")
    store.record_remediation(SID, FILE, drive_write_url="http://d/1", blob_url="http://b/1")


def test_the_judgement_row_a_pdf_now_gets_can_actually_be_resolved(store):
    """What a reviewer sees instead: the residual 2.4.4 FAIL routed by
    queue_hitl_review_for_file — a card with no prefilled value. Approving it is the human
    sign-off mark_file_compliant_if_reviewed documents ("a link text deemed adequate as it
    stands"), so the document can reach Publish."""
    _remediated_pdf_record(store)
    created = store.queue_hitl_review_for_file(SID, FILE, [
        {"rule_id": "2.4.4", "rule_name": "Link Purpose (In Context)", "finding_count": 1}])
    assert len(created) == 1
    store.update_hitl_item(created[0]["id"], "approved", "re-authored the link text in Acrobat")

    assert store.count_unapplied_approved_values(SID, FILE) == 0    # nothing was promised
    assert store.mark_file_compliant_if_reviewed(SID, FILE) is True


def test_the_old_proposal_card_would_have_blocked_certification_forever(store):
    """Why 'stop offering it' beats 'offer it and hope': the gate counts ANY approved row
    holding a locator + value, whatever the format. With no PDF writer to mark the row applied,
    that count never reached zero — the file was approved and permanently unpublishable."""
    _remediated_pdf_record(store)
    item_id = store.enqueue_proposals(SID, FILE, "2.4.4", [
        {"locator": URL, "before": URL, "proposed_value": "Download Regional Summary 2026 (PDF)",
         "rationale": "r", "source": "derived from the link target (deterministic)"},
    ], rule_name="Link Purpose (In Context)")
    store.update_hitl_item(item_id, "approved")
    store.approve_proposal_values(item_id, [])                     # accept the draft unedited

    assert store.count_unapplied_approved_values(SID, FILE) == 1
    assert store.mark_file_compliant_if_reviewed(SID, FILE) is False
