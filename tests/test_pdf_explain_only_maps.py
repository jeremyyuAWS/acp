"""The three PDF map cards are EXPLAIN-ONLY: approved as evidence, never counted as unwritten content.

WCAG 1.3.2 reading order, 1.3.1 structure map and 2.4.6 headings map each hand a reviewer a
derived map to CONFIRM. Re-tagging a PDF re-authors it (ADR 0016), so the approved map is the
tagging instruction and the compliance evidence — it is never written into the file.

The regression these pin closed: the cards carried a locator + proposed_value like any other
proposal, and store.count_unapplied_approved_values counts ANY approved row holding a locator +
value, whatever the format. No PDF writer routes "page 1" / "document structure" / "document
headings" (apply_pdf_approved handles only `pdf:fig:` → /Alt and `pdf:field:` → /TU), so no
applier ever marked the row applied. The moment a reviewer confirmed a map,
mark_file_compliant_if_reviewed returned False forever: the file was correctly approved and
permanently unable to certify or reach Publish.

Why these are flagged rather than dropped, which is what WCAG 2.4.4 Link Purpose on PDF got
(tests/test_pdf_link_purpose_explain_only.py): 2.4.4's proposed_value was a link LABEL, useful
only once written into the document, so offering it promised a write that never came. A confirmed
structure map is useful as itself. The honest fix is therefore to keep offering it and stop
claiming it is content the document still owes — `explain_only=True` on the proposal, which
store._row_approved_values skips.

The flag is on the PROPOSAL, not on the reviewer's action, because _row_approved_values falls
back to `proposed_value` when a client sends no approved value: any client-side suppression
would be handed straight back by that fallback. test_the_flag_survives_a_client_that_sends_a_value
pins that.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import remediate_pdf as rp  # noqa: E402

SID = "s-pdf-maps"
FILE = "report.pdf"

# The three cards, as api/remediate_pdf.py builds them: (rule_id, rule_name, locator, kind).
MAP_CARDS = [
    ("1.3.2", "Meaningful Sequence", "page 1", "reading-order"),
    ("1.3.1", "Info and Relationships", "document structure", "structure-map"),
    ("2.4.6", "Headings and Labels", "document headings", "headings-map"),
]

MAP_VALUE = "Heading 1 · “Discharge Instructions” (p.1)\nHeading 2 · “Medications” (p.1)"


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "maps.db")
    return store_mod.Store()


def _remediated_pdf_record(store):
    store.init_scan_run(SID, "drive", 1, "2026-07-10T00:00:00Z", "rubric", "hash")
    store.save_file_result(SID, {
        "file": FILE, "engine": "pdf", "status": "fail", "score": 60, "compliant": 0,
        "skipped_rules": 0, "drive_file_id": "drv1",
        "issues": [{"ruleId": "PDF_NO_STRUCT", "wcag": "1.3.1", "severity": "SERIOUS"}],
    }, "2026-07-10T00:00:00Z")
    store.record_remediation(SID, FILE, drive_write_url="http://d/1", blob_url="http://b/1")


def _enqueue_map(store, rule_id, rule_name, locator, *, explain_only=True):
    return store.enqueue_proposals(SID, FILE, rule_id, [
        {"locator": locator, "before": "(untagged PDF)", "proposed_value": MAP_VALUE,
         "rationale": "confirm it matches the intended structure",
         "source": "font hierarchy in document order (deterministic)",
         **({"explain_only": True} if explain_only else {})},
    ], rule_name=rule_name)


# ── the gate ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rule_id,rule_name,locator,_kind", MAP_CARDS)
def test_confirming_a_map_does_not_block_certification(store, rule_id, rule_name, locator, _kind):
    """THE regression. Approving the card must leave nothing 'awaiting a write', so the file
    can still certify — the state that shipped had it blocked permanently."""
    _remediated_pdf_record(store)
    item_id = _enqueue_map(store, rule_id, rule_name, locator)
    store.update_hitl_item(item_id, "approved")
    store.approve_proposal_values(item_id, [])          # confirm the map unedited

    assert store.count_unapplied_approved_values(SID, FILE) == 0, (
        f"the confirmed {rule_id} map counts as content the document does not carry — but no "
        "writer will ever write it, so the file can never certify")
    assert store.mark_file_compliant_if_reviewed(SID, FILE) is True


@pytest.mark.parametrize("rule_id,rule_name,locator,_kind", MAP_CARDS)
def test_without_the_flag_the_same_card_blocks_forever(store, rule_id, rule_name, locator, _kind):
    """The bug, still reproducible on demand: drop `explain_only` and the block comes back.
    This is what keeps the test above honest — it would pass just as well if the gate had been
    disabled wholesale, and this shows it was not."""
    _remediated_pdf_record(store)
    item_id = _enqueue_map(store, rule_id, rule_name, locator, explain_only=False)
    store.update_hitl_item(item_id, "approved")
    store.approve_proposal_values(item_id, [])

    assert store.count_unapplied_approved_values(SID, FILE) == 1
    assert store.mark_file_compliant_if_reviewed(SID, FILE) is False


def test_the_flag_survives_a_client_that_sends_a_value(store):
    """Why the flag lives on the proposal. A client that posts a headline value writes the legacy
    `approved_value` column, which normally counts forever by design ('a human agreed to some text
    but we don't know where it goes'). For an explain-only row there is nowhere for it to go BY
    DESIGN, so it must not resurrect the dead end."""
    _remediated_pdf_record(store)
    item_id = _enqueue_map(store, "1.3.1", "Info and Relationships", "document structure")
    store.update_hitl_item(item_id, "approved", "looks right", MAP_VALUE)
    store.approve_proposal_values(item_id, [MAP_VALUE])   # and an edited per-proposal value

    assert store.count_unapplied_approved_values(SID, FILE) == 0
    assert store.mark_file_compliant_if_reviewed(SID, FILE) is True


def test_a_writable_row_still_blocks_even_beside_an_explain_only_one(store):
    """The flag must not become a way to certify on a promise. A real 1.1.1 alt-text row awaiting
    a write still blocks, with a confirmed map sitting next to it."""
    _remediated_pdf_record(store)
    _enqueue_map(store, "1.3.1", "Info and Relationships", "document structure")
    alt_id = store.enqueue_proposals(SID, FILE, "1.1.1", [
        {"locator": "pdf:fig:1:0", "before": "(no alt text)", "proposed_value": "A bar chart",
         "rationale": "r", "source": "AI vision model (llava)"},
    ], rule_name="Non-text Content")
    store.update_hitl_item(alt_id, "approved")
    store.approve_proposal_values(alt_id, [])

    assert store.count_unapplied_approved_values(SID, FILE) == 1   # the figure, not the map
    assert store.mark_file_compliant_if_reviewed(SID, FILE) is False


def test_the_batch_counter_agrees_with_the_per_file_one(store):
    """scan_status uses the batch form; a gate that disagreed with itself would let a file certify
    on one screen and not the other."""
    _remediated_pdf_record(store)
    item_id = _enqueue_map(store, "1.3.1", "Info and Relationships", "document structure")
    store.update_hitl_item(item_id, "approved")
    store.approve_proposal_values(item_id, [])

    assert store.count_unapplied_approved_values_by_file(SID).get(FILE, 0) == 0
    assert store.count_unapplied_approved_values(SID, FILE) == 0


def test_an_explain_only_value_is_never_offered_to_a_writer(store):
    """The value-getters feed the appliers. An explain-only value must not reach one even if a
    future change routes its criterion — the map is not bytes for the document."""
    _remediated_pdf_record(store)
    item_id = _enqueue_map(store, "1.3.1", "Info and Relationships", "document structure")
    store.update_hitl_item(item_id, "approved")
    store.approve_proposal_values(item_id, [])

    rows = store._approved_unapplied_rows(SID, FILE)
    assert rows, "the approved row vanished — the rest of this test would pass vacuously"
    assert all(store._row_approved_values(r) == {} for r in rows)


# ── the proposers actually set it ─────────────────────────────────────────────

def test_all_three_proposers_mark_their_card_explain_only():
    """Source-level so it runs on a clean checkout (the partner PDF engine is a separate repo,
    and 1.3.2 additionally needs a vision model). Each proposal(...) call that builds one of the
    three maps must carry the flag — a new one added without it re-opens the dead end."""
    src = (ACP / "api" / "remediate_pdf.py").read_text()
    for fn, locator in [("_propose_reading_order", "page 1"),
                        ("_propose_structure_map", "document structure"),
                        ("_propose_pdf_headings", "document headings")]:
        start = src.index(f"def {fn}(")
        end = src.index("\ndef ", start + 1)
        body = src[start:end]
        assert f'locator="{locator}"' in body, f"{fn} stopped emitting {locator!r}"
        assert "explain_only=True" in body, (
            f"{fn} builds a map card the certify gate would count as unwritten content")


def test_the_structure_map_proposer_really_emits_the_flag(tmp_path):
    """The source-level test above proves the argument is written; this proves it survives into
    the proposal dict store actually stores. Runs the real 1.3.1 proposer over a real untagged
    PDF — no partner engine or vision model needed, unlike its 1.3.2 / 2.4.6 siblings."""
    pytest.importorskip("reportlab")
    pikepdf = pytest.importorskip("pikepdf")
    pytest.importorskip("pdfplumber")
    from reportlab.pdfgen import canvas

    src = tmp_path / "untagged.pdf"
    c = canvas.Canvas(str(src))
    c.setFont("Helvetica-Bold", 24); c.drawString(72, 750, "Discharge Instructions")
    c.setFont("Helvetica-Bold", 16); c.drawString(72, 700, "Medications")
    c.setFont("Helvetica-Bold", 16); c.drawString(72, 620, "Follow-up appointments")
    c.setFont("Helvetica", 11)
    c.drawString(72, 560, "Body prose so the page is not empty and body size is modal.")
    c.drawString(72, 540, "More body prose in the same modal size to anchor the ratio.")
    c.save()

    props: list[dict] = []
    with pikepdf.open(str(src)) as pdf:
        rp._propose_structure_map(pdf, str(src), proposals=props)
    cards = [p for p in props if p.get("kind") == "structure-map"]
    if not cards:
        pytest.skip("no structure map derived from this PDF (heading extraction unavailable)")
    assert all(p.get("explain_only") is True for p in cards)

    # And end-to-end through the gate, with the proposer's own dict rather than a handwritten one.
    import store as store_mod
    monkey = Path(tempfile.mkdtemp()) / "e2e.db"
    store_mod._SQLITE_PATH = monkey
    st = store_mod.Store()
    st.init_scan_run(SID, "drive", 1, "2026-07-10T00:00:00Z", "rubric", "hash")
    st.save_file_result(SID, {
        "file": FILE, "engine": "pdf", "status": "fail", "score": 60, "compliant": 0,
        "skipped_rules": 0, "drive_file_id": "drv1",
        "issues": [{"ruleId": "PDF_NO_STRUCT", "wcag": "1.3.1", "severity": "SERIOUS"}],
    }, "2026-07-10T00:00:00Z")
    st.record_remediation(SID, FILE, drive_write_url="http://d/1", blob_url="http://b/1")
    item_id = st.enqueue_proposals(SID, FILE, "1.3.1", cards, rule_name="Info and Relationships")
    st.update_hitl_item(item_id, "approved")
    st.approve_proposal_values(item_id, [])
    assert st.count_unapplied_approved_values(SID, FILE) == 0
    assert st.mark_file_compliant_if_reviewed(SID, FILE) is True


def test_the_flag_is_a_first_class_proposal_field():
    """Set through proposals.proposal(), not hand-stuffed into the dict, so there is one place
    documenting what it means and one spelling for store to test."""
    import proposals as _prop
    p = _prop.proposal(locator="document structure", before="b", proposed_value=MAP_VALUE,
                       rationale="r", source="s", kind="structure-map", explain_only=True)
    assert p["explain_only"] is True
    plain = _prop.proposal(locator="pdf:fig:1:0", before="b", proposed_value="A bar chart",
                           rationale="r", source="s")
    assert "explain_only" not in plain, "the default must stay absent — writable is the norm"


# ── the cards are still offered (this is not a quiet deletion) ────────────────

@pytest.mark.parametrize("fn", ["_propose_structure_map", "_propose_pdf_headings",
                                "_propose_reading_order"])
def test_the_proposer_still_exists(fn):
    """Explain-only is a statement about the write-back, not about the card. Unlike 2.4.4, these
    three stay: dropping them would delete a genuinely useful artefact, which is the failure mode
    this fix exists to avoid."""
    assert hasattr(rp, fn), f"{fn} was removed — the map card is the deliverable, not a stopgap"
