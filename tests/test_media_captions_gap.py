"""The media-accessibility gap: what was missing, and what slice 1 deliberately does NOT close.

WHY THIS FILE COMES FIRST. It was written before the capability it describes, so the gap is
evidence rather than a story told afterwards. Measured against `origin/main` at 362e8d57:

    api/media.py                              absent
    api/captions.py                           absent
    any WebVTT/SRT writer under api/          none  (git grep, no hits)
    scan_formats.KNOWN_FORMATS                {pdf, docx, xlsx, pptx, html}
    any media extension in KNOWN_FORMATS      NONE
    assessment_policy scope for 1.2.1/1.2.2   frozenset({"html"})
    fix_mode for 1.2.1 / 1.2.2 / 1.2.3        "human-only"

So a standalone `talk.mp4` was not merely uncaptioned — it was not a file this system had any
concept of. 1.2.1 and 1.2.2 existed in the criteria table but only ever applied to `<video>` and
`<audio>` elements INSIDE an HTML page, and both were declared human-only, meaning ACP claimed no
ability to draft anything for them.

WHAT SLICE 1 CLOSES, AND WHAT IT DOES NOT. It closes the capability gap: there is now a path from
a media file to reviewable caption files (`api/media.py` → `api/captions.py`). It closes nothing
else, ON PURPOSE, and the assertions below pin that:

  * Discovery does not list media. `api/scan_formats.py` is untouched.
  * No detector is registered for 1.2.x on any format.
  * 1.2.1/1.2.2/1.2.3 remain scoped to html and remain `human-only`.
  * No scan behaviour changes.

That restraint is not tidiness. Adding media to Discovery means editing `api/scan_formats.py`,
which is (a) being edited by an open PR and (b) carries a scope decision dated 2026-09-01 fixing
Discovery to PDF/DOCX/XLSX/PPTX and deliberately dropping HTML. Widening it is a product decision
this slice has no business taking quietly.

READ THE FAILURES HERE AS INSTRUCTIONS. Every assertion below is of the form "this is still the
case". When one goes red it means a later slice changed the product's claims, which is exactly
when the coverage tables, the scope decision and this file need updating together.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))


# ── the capability gap this slice closes ─────────────────────────────────────────
def test_there_is_now_a_path_from_media_to_caption_files():
    """THE GAP, closed. Neither module existed on main and nothing under api/ could emit a cue.

    Asserted as importability plus the three verbs the pipeline needs, rather than by running
    them — the behaviour has its own files. What this pins is that the path EXISTS, which is the
    thing that was missing.
    """
    import captions
    import media

    for verb in ("probe", "extract_audio", "transcribe"):
        assert callable(getattr(media, verb, None)), f"media.{verb} is the pipeline's {verb} step"
    for writer in ("segment_cues", "to_webvtt", "to_srt", "to_transcript", "parse_cues"):
        assert callable(getattr(captions, writer, None)), f"captions.{writer} must exist"


def test_media_extensions_are_recognised_as_media():
    """The other half of the absence: no media extension was known to the system at all."""
    import media
    assert media.media_kind("talk.mp4") == "video"
    assert media.media_kind("interview.mp3") == "audio"
    assert media.media_kind("report.docx") is None
    assert not media.is_media("report.pdf")


# ── what slice 1 deliberately leaves open ────────────────────────────────────────
def test_discovery_still_does_not_list_media():
    """`api/scan_formats.py` is untouched, so no scan starts seeing .mp4 files.

    This is the assertion most likely to be "helpfully" deleted by whoever does the discovery
    slice. It should be — but as a deliberate edit alongside the scope decision, not as a
    side effect of something else.
    """
    import scan_formats as sf
    known = {f.lower() for f in sf.KNOWN_FORMATS}
    assert known == {"pdf", "docx", "xlsx", "pptx", "html"}, (
        f"KNOWN_FORMATS changed to {sorted(known)}. If media was added to Discovery, that is a "
        f"scope decision (see the 2026-09-01 note in api/scan_formats.py) — record it there and "
        f"update this test and tests for the coverage denominator together")
    assert "mp4" not in known and "mp3" not in known


def test_the_media_criteria_are_still_html_only_and_still_human_only():
    """1.2.1/1.2.2/1.2.3 are unchanged: scoped to html, declared human-only.

    Slice 1 gives ACP the ABILITY to draft captions. It does not change what ACP CLAIMS about any
    (criterion, format) pair, and until a detector is registered and a corpus pair earns it, the
    claim must not move. This is the same discipline that kept (1.3.2, pdf) at UNVERIFIED after
    its detector was repaired: a working capability is not coverage.

    NO `hasattr` GUARDS HERE, and that is deliberate. The first draft of this test read
    `ap.FORMAT_SCOPE if hasattr(...)` and `ap.CRITERIA if hasattr(...)`. Neither name exists —
    they are `RULE_FORMATS` and `RULE_CATALOG` — so both blocks were skipped and the test passed
    while asserting nothing at all. A conditional around an assertion turns a guard into a
    decoration; the names are now read directly, so a rename fails loudly instead of silently.
    """
    import assessment_policy as ap

    for sc in ("1.2.1", "1.2.2"):
        assert ap.RULE_FORMATS[sc] == frozenset({"html"}), (
            f"{sc} scope changed to {ap.RULE_FORMATS[sc]} — a media detector may have been "
            f"registered; if so this slice's boundary moved and the capability report needs "
            f"re-deriving")

    by_id = {c["id"]: c for c in ap.RULE_CATALOG}
    for sc in ("1.2.1", "1.2.2", "1.2.3"):
        assert by_id[sc]["fix_mode"] == "human-only", (
            f"{sc} is no longer human-only. Drafting captions is AI-assisted, but a draft is not "
            f"a fix: the reviewer's approval is what resolves these, so the mode should only "
            f"change when an approved-value write lane exists end to end")


def test_slice_one_registers_no_detector():
    """No rule registration, so the capability report cannot start counting 1.2.x as reachable.

    A registration is a declaration that a detector exists. `tests/test_orphaned_detectors.py`
    records what happens when one is declared and never invoked — three cells read as capability
    for months. Not registering until the detector is wired is the cheaper half of that lesson.

    THE REGISTRY MUST BE POPULATED FIRST. `rule_registry._REGISTRY` is empty on import; entries
    appear only when the format packages run their `register()` calls. The first draft of this
    test read the registry without importing them, so it compared against an EMPTY dict and would
    have passed no matter what anyone registered.
    """
    import rule_registry
    import formats.docx, formats.html, formats.pdf, formats.pptx, formats.xlsx  # noqa: F401

    assert len(rule_registry._REGISTRY) >= 32, (
        "the registry looks unpopulated; this test cannot say anything about what is registered")
    media_regs = [f"{sc} {fmt}" for (sc, fmt) in rule_registry._REGISTRY
                  if str(sc).startswith("1.2.")]
    assert media_regs == [], (
        f"a 1.2.x registration appeared: {media_regs}. Wire the detector into "
        f"office_structure.checks_for in the same change, or it becomes a fourth orphan")
