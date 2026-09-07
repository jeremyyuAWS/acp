"""ADR 0055's premises, measured. "Keep this image of text, but describe it" has no home today.

WCAG 1.4.5 asks for real text INSTEAD of a picture of text, and #1715 shipped the fix that
actually delivers that: apply_pptx_image_replacement swaps the picture for a text box and
deletes the raster. But a reviewer sometimes decides the picture must STAY — the writer refuses
it (a group, a layout-referenced part, no `<a:xfrm>`), the styling carries meaning a text box
cannot, or it is a 1.4.9 chart where replacing the picture with its axis labels would destroy
information. Their honest outcome is to keep the image and describe it.

The review model has no cell for that decision, and the two ways a reviewer can express it today
are both wrong — differently, and neither loudly. This file pins both, so ADR 0055 argues from
measurements rather than from a reading of the code, and so the shape of the fix is falsifiable:

  * `test_a_described_row_certifies_while_the_description_reaches_nothing` — the reviewer
    records a resolution, and the description they wrote is dropped on the floor while the file
    is marked 100/100 conformant. This is the exact defect mark_file_compliant_if_reviewed's
    docstring records ("marked a PPTX 100/100 and conformant with WCAG 1.1.1 while its ten
    images were still undescribed") arriving through a new door.

  * `test_without_a_resolution_the_description_is_fed_to_the_writer_that_deletes_the_image` —
    the reviewer records no resolution, and their description is handed to the REPLACEMENT
    writer. The picture they chose to keep is deleted, and prose ABOUT the image is written
    where the image's OWN words belong. A description is not a transcript.

WHAT WOULD MAKE THESE FAIL, which is the point of writing them down: implementing ADR 0055.
The first fails when a described row is no longer allowed to certify with content outstanding;
the second when a described row's value stops reaching the replacement lane. Both failures are
the reminder to rewrite this file around the new behaviour, not a regression.

The third test is the other direction — the ONE capability ADR 0055 needs that does not exist
today is a locator translation, and it establishes that the destination shape is real and
already resolvable, so the design is not resting on an assumption about apply_alt.
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

    'described' is used as the resolution string, but nothing here depends on that spelling:
    _row_is_resolved tests only that the column is non-empty, so EVERY resolution a reviewer
    could pick behaves this way.
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
        "if this now returns False, a described row no longer certifies with content "
        "outstanding — ADR 0055 is implemented and this file should be rewritten around it")


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
        "if this is now empty, the described value no longer reaches the replacement lane — "
        "ADR 0055 is implemented and this file should be rewritten around it")

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
