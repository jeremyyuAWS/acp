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

CORRECTION, MADE IN SLICE 2. This docstring used to say that a standalone `talk.mp4` "was not a
file this system had any concept of". That reads well and is wrong, in the direction that sends
the next person to the wrong module. `estate_inventory` has always known what a video is: `_AV_EXT`
lists eleven media extensions, `_format_of` returns the bucket `"av"` for them, and `_status_of`
returns METADATA_ONLY — "inventoried (image / audio / video) but no accessibility test". The
estate could see media all along. What it could not do was ASSESS it, and the reason was the
narrow one in the table above: no entry in `KNOWN_FORMATS`, so `is_supported_format("av")` was
False, so the bucket resolved to METADATA_ONLY rather than ASSESSABLE. The claim to make is
"media was never assessable", not "media was never seen".

1.2.1 and 1.2.2 existed in the criteria table but only ever applied to `<video>` and `<audio>`
elements INSIDE an HTML page, and both were declared human-only, meaning ACP claimed no ability to
draft anything for them.

WHAT SLICE 1 CLOSED, AND WHAT SLICE 2 THEN MOVED. Slice 1 closed the capability gap: a path from
a media file to reviewable caption files (`api/media.py` → `api/captions.py`), registering nothing
and changing no claim. Slice 2 registered 1.2.1/1.2.2 against a real detector, wired it into
`office_structure.checks_for`, and put `"av"` in `KNOWN_FORMATS` — which is what `scan_formats`
requires before a format may be switched on at all.

The two assertions that used to read "slice 1 leaves this alone" now read as the invariants that
survived, and they are the ones worth keeping:

  * media is switchable on but is NOT in Discovery's DEFAULT scope (the 2026-09-01 decision);
  * a registered 1.2.x pair must be REACHABLE, never a declaration with nothing calling it;
  * 1.2.1/1.2.2/1.2.3 stay `human-only`, because a draft is not a fix.

READ THE FAILURES HERE AS INSTRUCTIONS. Every assertion is of the form "this is still the case".
When one goes red it means a later slice changed the product's claims, which is exactly when the
coverage tables, the scope decision and this file need updating together — as slice 2 did.
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
def test_discovery_does_not_list_media_by_default():
    """Media is switchable on and is NOT on. The 2026-09-01 scope decision still governs.

    This assertion was rewritten in slice 2 rather than deleted, and the rewrite is the point.
    Its first form pinned `KNOWN_FORMATS` to the five document formats, which was right while no
    media detector existed — `scan_formats` says a format absent from that set "cannot be switched
    on by env: naming one that no engine can assess would list files Assess is guaranteed to fail
    on". Slice 2 built the detector, so the entry became legitimate and this test had to move.

    What must NOT move is the default. `DEFAULT_FORMATS` is what every existing deployment scans,
    and adding video to it would change the meaning of every estate's totals overnight — the
    eligible denominator, the coverage funnel, the assessed-of-discovered ratio — for content
    nobody asked us to walk. That is a product decision, and it is recorded in
    `api/scan_formats.py`, not taken as a side effect here.
    """
    import scan_formats as sf
    known = {f.lower() for f in sf.KNOWN_FORMATS}
    assert known == {"pdf", "docx", "xlsx", "pptx", "html", "av"}, (
        f"KNOWN_FORMATS changed to {sorted(known)}. A format may only appear here once a detector "
        f"can assess it — otherwise an operator can switch on a scope that lists files Assess is "
        f"guaranteed to fail on")
    assert "av" not in sf.DEFAULT_FORMATS, (
        "media entered Discovery's DEFAULT scope. Record that decision in api/scan_formats.py "
        "first — and update the coverage denominator with it")
    assert sf.formats() == frozenset({"pdf", "docx", "xlsx", "pptx"}), (
        f"the effective default scope is {sorted(sf.formats())}, not the 2026-09-01 four")


def test_the_media_criteria_are_still_html_only_and_still_human_only():
    """1.2.1/1.2.2/1.2.3 are unchanged: scoped to html in RULE_FORMATS, declared human-only.

    STILL TRUE AFTER SLICE 2, and for a reason worth stating rather than a coincidence. A pair
    registered below FULL coverage may NOT also sit in the legacy pass/fail table — that is what
    `tests/test_rule_registry.py::test_registry_does_not_contradict_the_legacy_scope_tables`
    enforces, because two tables describing one cell differently is the drift the registry
    replaced. So `av` deliberately does not join `RULE_FORMATS["1.2.2"]`; the `html` entry there
    is the separate in-page `<video>` technique and is untouched.

    `fix_mode` stays `human-only` for all three. Slice 1 can draft captions and slice 2 can find
    that they are missing, but neither makes 1.2.x fixable: the reviewer's approval is what
    resolves these, and the mode should only change when an approved-value write lane exists end
    to end — the same bar the other 17 lanes had to clear.

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


def test_every_registered_media_pair_is_actually_reachable():
    """A 1.2.x registration must be REACHED by the live path, not merely declared.

    THIS TEST'S PREVIOUS FORM DID ITS JOB, which is why it is worth recording what happened. It
    asserted `media_regs == []` and said, in its failure message, "wire the detector into
    office_structure.checks_for in the same change, or it becomes a fourth orphan". Slice 2 made
    it go red, read that message, and wired the dispatch. The assertion has been inverted rather
    than deleted: the hazard it guards did not go away when the registration arrived — it moved
    from "don't declare yet" to "don't declare more than you dispatch".

    `tests/test_orphaned_detectors.py` records the cost of getting this wrong: three cells read as
    capability for months because a detector was declared and never invoked. A registration is a
    claim in the capability report; being reachable is what makes the claim true.

    THE REGISTRY MUST BE POPULATED FIRST. `rule_registry._REGISTRY` is empty on import; entries
    appear only when the format packages run their `register()` calls. An early draft of this test
    read the registry without importing them, so it compared against an EMPTY dict and would have
    passed no matter what anyone registered.
    """
    import office_structure
    import rule_registry
    import formats.av, formats.docx, formats.html, formats.pdf, formats.pptx, formats.xlsx  # noqa: F401,E501

    assert len(rule_registry._REGISTRY) >= 32, (
        "the registry looks unpopulated; this test cannot say anything about what is registered")
    media_regs = sorted(f"{sc} {fmt}" for (sc, fmt) in rule_registry._REGISTRY
                        if str(sc).startswith("1.2."))
    assert media_regs == ["1.2.1 av", "1.2.2 av"], (
        f"the registered 1.2.x pairs are {media_regs}. Every one needs a dispatch in "
        f"office_structure.checks_for, and 1.2.3 needs a technique that can see the picture "
        f"before it may be registered at all")

    # Reachability, asserted by DISPATCH rather than by the registration table restating itself.
    for ext in (".mp4", ".mp3"):
        assert ext in office_structure._AV_EXTS, (
            f"{ext} is a media extension the registry claims to cover and checks_for does not "
            f"dispatch — the exact shape of an orphaned detector")
