"""ADR 0055's premises, and what implementing it did and did NOT change.

WCAG 1.4.5 asks for real text INSTEAD of a picture of text, and #1715 shipped the fix that
delivers it: apply_pptx_image_replacement swaps the picture for a text box and deletes the
raster. But a reviewer sometimes decides the picture must STAY — the writer refuses it (a group,
a layout-referenced part, no `<a:xfrm>`), the styling carries meaning, or it is a 1.4.9 chart
where replacing the picture with its axis labels would destroy information.

This file was written BEFORE that decision had anywhere to go, to measure the two dead ends
rather than argue them. ADR 0055 has since been implemented, and the file is now the record of
which half of what it measured was a BUG to fix and which was a GUARD to keep — a distinction
that is easy to lose and expensive to get wrong.

  * FIXED. A described decision no longer certifies while the description reaches nothing.
    `described_not_replaced` resolves 1.4.5 by judgement and records the description as 1.1.1
    alt text the document owes, so the file cannot certify until it is written and a re-scan
    agrees. Proved end to end in tests/test_remediation_verified_pptx_described.py, which also
    holds the route's refusals — an incomplete described decision is rejected before any row is
    touched, so the old behaviour cannot return through one.

  * KEPT, deliberately. Every OTHER resolution still swallows a value, and _row_is_resolved is
    still absolute. That guard exists because approving "Mark as decorative" once wrote the
    card's own UI label into the document as alt text (#43). ADR 0055 rejected relaxing it —
    option A in the ADR — and routed around it instead, so the first test below still passes
    unchanged and SHOULD. If it ever fails, the general guard has been weakened and #43 is back.

  * KEPT. A transcript approved with NO resolution still goes to the replacement writer, which
    deletes the picture. That is correct: it is the 1.4.5 fix, and it is what the reviewer asked
    for when they did not say to keep the image.

The third test pins the locator shape the design routes through, which is now load-bearing
rather than prospective.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

SID, FILE = "s-adr55", "deck.pptx"

# What the OCR proposer drafts for the picture: the words baked into the image.
TRANSCRIPT = "Q3 revenue rose 12%"
# What a reviewer who KEEPS the picture writes instead: prose about it. The distinction is the
# whole reason the two decisions cannot share one lane — 1.4.5 wants the transcript IN the
# document as text, 1.1.1 wants the description ON the image as alt.
DESCRIPTION = "A slide titled Q3 revenue, in the brand's display face, reading: revenue rose 12%"


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "adr55.db")
    return store_mod.Store()


def _reviewed_image_of_text_row(st, *, value: str, resolution: str | None) -> str:
    """A remediated deck with one approved 1.4.5 image-of-text card.

    Mirrors tests/test_remediation_verified_pptx_image_of_text.py's seed: the same locator shape
    the real proposer mints ('image N', a media index into ppt/media/*), approved through the
    same two production calls a reviewer's decision goes through.
    """
    st.init_scan_run(SID, "drive", 1, "2026-09-07T00:00:00Z", "rubric", "hash")
    st.save_file_result(SID, {
        "file": FILE, "engine": "office", "status": "pass", "score": 60, "compliant": 0,
        "skipped_rules": 0, "drive_file_id": "d1",
        "issues": [{"ruleId": "OCR_IMAGE_OF_TEXT", "wcag": "1.4.5 Images of Text",
                    "severity": "SERIOUS", "detail": "embedded image 1 contains readable text"}],
    }, "2026-09-07T00:00:00Z")
    st.record_remediation(SID, FILE, drive_write_url="http://d/1", blob_url="http://b/1")
    item_id = st.enqueue_proposals(SID, FILE, "1.4.5", [
        {"locator": "image 1", "before": "text baked into an image",
         "proposed_value": TRANSCRIPT, "rationale": "r", "source": "OCR"}],
        rule_name="Images of Text")
    st.update_hitl_item(item_id, "approved", None, None, resolution=resolution)
    st.approve_proposal_values(item_id, [value])
    return item_id


def test_a_described_row_certifies_while_the_description_reaches_nothing(st):
    """Branch one: the reviewer records their judgement as a `resolution`.

    Every existing resolution promises the document NO prose, and _row_is_resolved enforces that
    promise for good reasons (#43: approving "Mark as decorative" wrote descr="Mark as
    decorative" onto the picture). So the description is stored on the row, dropped by every
    accessor, and the file certifies with the image untouched AND undescribed — worse than
    either half alone, because the certification asserts the opposite.

    STILL TRUE, AND DELIBERATELY. ADR 0055 did not relax this — it routed around it. The string
    used below is a bare 'described', NOT the real 'described_not_replaced' resolution, and the
    row is written directly rather than through the route, so this exercises the general guard
    and not the new lane. _row_is_resolved tests only that the column is non-empty, so every
    resolution WITHOUT a lane of its own still behaves exactly this way.
    """
    import store as store_mod
    item_id = _reviewed_image_of_text_row(st, value=DESCRIPTION, resolution="described")
    row = st.get_hitl_item(item_id)

    # The reviewer's description IS stored — this is data loss at the read, not at the write.
    assert row["proposals"][0]["approved_value"] == DESCRIPTION
    assert store_mod.Store._row_is_resolved(row) is True

    # ...and every accessor that could carry it to a writer returns nothing.
    assert st._row_approved_values(row) == {}
    assert st.approved_images_of_text_values(SID, FILE, ("1.4.5",)) == {}
    assert st.approved_alt_values(SID, FILE) == {}

    # ...so the file is certified 100/100 conformant with the picture untouched and undescribed.
    assert st.count_unapplied_approved_values(SID, FILE) == 0
    assert st.mark_file_compliant_if_reviewed(SID, FILE) is True, (
        "the general resolution guard has been weakened. This is NOT the ADR 0055 path — that "
        "one goes through the route, which records the description as 1.1.1 alt text owed. This "
        "is any OTHER resolution, and it must keep swallowing values: relaxing _row_is_resolved "
        "was option A in the ADR and was rejected, because it re-opens #43 on every decision")


def test_without_a_resolution_the_description_is_fed_to_the_writer_that_deletes_the_image(st):
    """Branch two: the reviewer types the description and records no resolution.

    Now the value flows — to `approved_images_of_text_values`, which handlers hands to
    apply_pptx_image_replacement. That writer's whole job is to DELETE the picture and put the
    value in a text box, so a reviewer who decided to keep the image gets it removed, and the
    text box carries prose ABOUT the picture where the picture's own words should be.

    Nothing in the row distinguishes the two intents: the locator, the rule_id and the shape of
    the value are identical to an approved transcript. That is why ADR 0055 makes the intent
    explicit rather than inferring it from the text.
    """
    item_id = _reviewed_image_of_text_row(st, value=DESCRIPTION, resolution=None)
    row = st.get_hitl_item(item_id)
    assert row["proposals"][0]["approved_value"] == DESCRIPTION

    to_write = st.approved_images_of_text_values(SID, FILE, ("1.4.5",))
    assert to_write == {"image 1": DESCRIPTION}, (
        "a value approved with NO resolution must still reach the replacement lane: that is the "
        "1.4.5 fix, and it is what the reviewer asked for by not saying to keep the image. "
        "ADR 0055 added a separate path for keeping it; it did not change this one")

    # And the lane it reaches is the one that deletes the media part. Asserted against the
    # handler's own wiring rather than restated, so a future re-point of the 1.4.5 lane to some
    # other writer fails here instead of quietly invalidating the claim.
    import ast
    tree = ast.parse((ACP / "api" / "handlers.py").read_text())
    lane_writers = {
        alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        and node.module == "apply_pptx_image_replacement"
        for alias in node.names
    }
    assert "apply_pptx_image_replacement" in lane_writers

    # The row owes the document content, so the file correctly does NOT certify yet. The damage
    # here is not a stuck file — it is that the write it is waiting for is the wrong one.
    assert st.count_unapplied_approved_values(SID, FILE) == 1
    assert st.mark_file_compliant_if_reviewed(SID, FILE) is False


def test_the_locator_shape_adr_0055_routes_to_already_resolves(st):
    """The one new capability ADR 0055 needs is a locator translation, and this pins its target.

    The 1.4.5 proposer mints 'image N' — a media index into ppt/media/*, which apply_alt cannot
    read at all (parse_locator requires a '#'). The proven 1.1.1 alt lane addresses an image
    either by the shape's NAME or by the relationship id of the image it embeds, and the second
    is derivable from 'image N' by the resolution the retired apply_pptx_image_of_text already
    performs: media index -> canonical media path -> the rId a slide uses to reference it.

    So the design routes through 'part#rIdN', and this establishes that shape resolves TODAY
    rather than assuming it. It matters because api/store.py's _row_proposal_locators asserted
    the opposite until this change corrected it — that apply_alt resolves by NAME only, so an
    rId locator "reaches no element". apply_alt.resolve_target has had an r:embed branch since
    #553 and tests/test_alt_locator_rid_writeback.py has proved it end to end since; a design
    that trusted the stale docstring would have rejected its own best route.
    """
    import apply_alt

    xml = (
        '<p:sld xmlns:p="p" xmlns:a="a" xmlns:r="r"><p:cSld><p:spTree>'
        '<p:pic><p:nvPicPr><p:cNvPr id="2" name="Picture 2"/></p:nvPicPr>'
        '<p:blipFill><a:blip r:embed="rId2"/></p:blipFill></p:pic>'
        '</p:spTree></p:cSld></p:sld>'
    )
    tag = r"(?:p:)?cNvPr"

    by_name = apply_alt.resolve_target(xml, tag, "Picture 2")
    by_rid = apply_alt.resolve_target(xml, tag, "rId2")
    assert by_name is not None and by_rid == by_name, (
        "an r:embed locator no longer reaches the same element as the shape name — ADR 0055's "
        "'image N' -> 'part#rIdN' route is gone and the design needs revisiting")
    assert apply_alt.resolve_target(xml, tag, "rId9") is None   # and it is not matching blindly

    # The half that does NOT exist: the proposer's own locator reaches nothing, which is the
    # gap the translation fills.
    assert apply_alt.parse_locator("image 1") is None
