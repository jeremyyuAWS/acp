"""Slice 2: a standalone media file becomes ASSESSABLE — the step from inventoried to judged.

THE GAP, measured on `origin/main` at b261fdfa, and it is NOT the one slice 1's fixture claims.

Slice 1's docstring said a standalone `talk.mp4` "was not a file this system had any concept
of". That reads well and is wrong in a way worth correcting, because it points the next person
at the wrong file. Media has been discovered and inventoried all along:

    estate_inventory._AV_EXT      {".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", …}
    estate_inventory._format_of   returns the bucket "av" for any of them
    estate_inventory._status_of   returns METADATA_ONLY — "inventoried … but no accessibility test"

So the estate has always known what a video IS. What it could not do is assess one. `_status_of`
resolves METADATA_ONLY precisely because `scan_formats.is_supported_format("av")` is False, and
that is the real, narrow gap:

    scan_formats.KNOWN_FORMATS            {"pdf","docx","xlsx","pptx","html"} — no "av"
    office_structure.checks_for(p, ".mp4") []  — the dispatch falls through to the empty return
    rule_registry, 1.2.x on any format     unregistered

A video with a soundtrack and no captions therefore produced NO finding, on any path, ever. Not
a FAIL, not a REVIEW — nothing, because nothing looked. `test_the_gap_this_slice_closes` below is
that fact, and it is the assertion that was red before the detector existed.

WHY av GOES IN KNOWN_FORMATS BUT NOT DEFAULT_FORMATS. `scan_formats` is explicit that a format
absent from KNOWN_FORMATS "cannot be switched on by env: naming one that no engine can assess
would list files Assess is guaranteed to fail on". Slice 1 could not have added media there — it
registered no detector, by design. Now one exists, so the entry is earned rather than asserted.
DEFAULT_FORMATS is untouched: the 2026-09-01 scope decision fixing Discovery to PDF/DOCX/XLSX/PPTX
still holds, and media is opt-in exactly as HTML already is —

    ACP_SCAN_FORMATS=pdf,docx,xlsx,pptx,av

WHAT THIS SLICE STILL DOES NOT CLAIM, pinned at the bottom of this file: 1.2.3 (audio description)
is not registered, no caption file is written by a scan, and no remediation lane exists. Drafting
captions — the thing slice 1 built — is not wired into a proposal yet.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "api", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import media  # noqa: E402
import office_structure  # noqa: E402
import scan_formats  # noqa: E402
from engines import MEDIA_OK, NO_MEDIA  # noqa: E402

needs_media = pytest.mark.skipif(not MEDIA_OK, reason=NO_MEDIA)

SRT = "1\n00:00:00,000 --> 00:00:02,000\nHello there.\n\n"


def _build(path: Path, *, video=True, audio=True, captions=False, seconds=3) -> Path:
    """A real container built by ffmpeg. `captions=True` muxes a real mov_text track in, which is
    the only way to test the has-captions branch honestly — an .mp4 CAN carry its captions
    internally, and a detector that only looked for a sidecar would fail every one of them."""
    ff = media.ffmpeg_path()
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"]
    if video:
        cmd += ["-f", "lavfi", "-i", f"testsrc=size=160x120:rate=10:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    if video:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        # aac only inside an mp4. Forcing it into the .mp3 the audio-only fixture asks for makes
        # ffmpeg write no packets and exit non-zero — the container picks its own codec, and
        # naming one here made the first run of this file fail for a reason that had nothing to
        # do with the code under test.
        if audio:
            cmd += ["-c:a", "aac"]
        cmd += ["-shortest"]
    cmd += [str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"fixture build failed: {r.stderr[-400:]}"
    if not captions:
        return path

    srt = path.with_suffix(".srt")
    srt.write_text(SRT)
    muxed = path.with_name(f"cap-{path.name}")
    r = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(path), "-i", str(srt), "-c", "copy", "-c:s", "mov_text",
                        str(muxed)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"caption mux failed: {r.stderr[-400:]}"
    srt.unlink()
    muxed.replace(path)
    return path


def _scs(findings) -> set[str]:
    """The success criteria a finding list names, e.g. {"1.2.2"}. Findings carry `wcag` as
    "1.2.2 Captions (Prerecorded)", so the code is the first token."""
    return {str(f.get("wcag", "")).split()[0] for f in findings if f.get("wcag")}


# ── the gap ──────────────────────────────────────────────────────────────────────────────────
@needs_media
def test_the_gap_this_slice_closes(tmp_path):
    """A video with a soundtrack and no captions must produce a 1.2.2 finding.

    RED BEFORE THIS SLICE: checks_for's dispatch ended in `return []` for every extension it did
    not name, so this returned nothing at all — not a pass, not a review, nothing. That silence
    is worse than a wrong answer: a file with no findings reads as a file with no problems.
    """
    clip = _build(tmp_path / "townhall.mp4")
    findings = office_structure.checks_for(clip, ".mp4")
    assert "1.2.2" in _scs(findings), (
        f"no 1.2.2 finding for a captionless video with audio; got {findings}")
    assert any(str(f.get("severity", "")).upper() != "REVIEW" for f in findings), (
        "a missing caption track on a video that has speech-carrying audio is a determinable "
        "failure, not an advisory")


@needs_media
def test_an_audio_only_file_is_judged_under_1_2_1_not_1_2_2(tmp_path):
    """The fork that decides which artefact a reviewer is asked for. 1.2.2 asks for CAPTIONS,
    which are synchronised with a picture; a podcast has no picture. Asking for captions on an
    .mp3 sends the reviewer to produce the wrong thing."""
    pod = _build(tmp_path / "interview.mp3", video=False)
    findings = office_structure.checks_for(pod, ".mp3")
    assert "1.2.1" in _scs(findings)
    assert "1.2.2" not in _scs(findings), "captions are not the artefact an audio-only file needs"


@needs_media
def test_a_silent_video_is_not_asked_for_captions(tmp_path):
    """The false positive that would land on every screen recording without narration. There is
    nothing to caption in a file with no audio track — it needs an audio description or a text
    alternative (1.2.3), which this slice deliberately does not claim. Silence here is correct,
    and it is not the same silence as the gap above: this file was READ and found to have no
    soundtrack."""
    silent = _build(tmp_path / "screen-capture.mp4", audio=False)
    findings = office_structure.checks_for(silent, ".mp4")
    assert "1.2.2" not in _scs(findings), f"asked a silent video for captions: {findings}"
    assert "1.2.1" not in _scs(findings)


@needs_media
def test_an_embedded_caption_track_clears_the_finding(tmp_path):
    """A correctly captioned video must not be flagged. The captions here are a REAL mov_text
    stream muxed into the container, not a sidecar — .mp4 carries them internally and a detector
    that only checked for a neighbouring .vtt would report a false positive on every one."""
    captioned = _build(tmp_path / "briefing.mp4", captions=True)
    info = media.probe(captioned)
    assert info is not None and info.has_captions, (
        "the fixture did not actually get a caption track — the test below would then pass for "
        "the wrong reason")
    assert "1.2.2" not in _scs(office_structure.checks_for(captioned, ".mp4"))


@needs_media
def test_a_sidecar_caption_file_beside_the_media_also_clears_it(tmp_path):
    """The other way an estate serves captions. A `talk.vtt` next to `talk.mp4` is how most
    libraries do it, and flagging those would make the first scan of a compliant library read as
    entirely non-conformant."""
    clip = _build(tmp_path / "talk.mp4")
    (tmp_path / "talk.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello there.\n")
    assert "1.2.2" not in _scs(office_structure.checks_for(clip, ".mp4"))


# ── fail closed: the contract slice 1 was built on, applied to the live path ─────────────────
def test_a_missing_engine_never_reads_as_a_captioned_file(tmp_path, monkeypatch):
    """THE ONE THAT MATTERS. #1082 made verification fail closed because a scan that could not
    run looked identical to one that found nothing. The same failure is available here and is
    worse, because it is silent in the safe-looking direction: with no ffmpeg, `probe()` returns
    None, and a detector that read None as "no audio track" or as "clean" would return [] — and
    [] on a pass/fail path means the file is fine.

    Forced by disabling the probe, so it holds on a machine that HAS ffmpeg. The assertion is not
    that a finding of some kind appears — it is that the finding SAYS the file was not assessed,
    so a reviewer is told the difference between "captions are missing" and "nobody looked".
    """
    monkeypatch.setattr(media, "probe", lambda *_a, **_k: None)
    clip = tmp_path / "unreadable.mp4"
    clip.write_bytes(b"\x00" * 64)

    findings = office_structure.checks_for(clip, ".mp4")
    assert findings, (
        "a media file that could not be probed produced NO finding — indistinguishable from a "
        "correctly captioned file, which is the fail-open this repo has already paid for once")
    assert all(str(f.get("severity", "")).upper() == "REVIEW" for f in findings), (
        "not being able to look is not evidence of a defect; it routes to a human, it does not "
        "assert one")
    assert any("not assessed" in str(f.get("detail", "")).lower() for f in findings), (
        f"the finding must say the file was not assessed, not merely exist: {findings}")


def test_the_detector_never_raises_on_rubbish(tmp_path):
    """A structural check must not fail a scan — the rule every checks_for detector follows. A
    .docx renamed to .mp4 is ordinary in a real estate."""
    fake = tmp_path / "not-really.mp4"
    fake.write_bytes(b"PK\x03\x04 this is a zip")
    findings = office_structure.checks_for(fake, ".mp4")
    assert isinstance(findings, list)
    assert all(str(f.get("severity", "")).upper() == "REVIEW" for f in findings), (
        "an unreadable file is unassessed, not failed")


# ── the registry and capability declarations ────────────────────────────────────────────────
def test_the_pairs_are_registered_with_a_detector_and_partial_coverage():
    """A registration is what makes the capability report able to count these pairs at all.

    PARTIAL, not FULL, and the reason is specific rather than modest: the technique establishes
    whether a caption track or sidecar EXISTS. It does not read the captions, so it cannot judge
    accuracy or synchronisation, and it cannot see 1.2.2's media-alternative-for-text exception.
    A clean scan is therefore REVIEW, never a certified pass.
    """
    import rule_registry
    rule_registry.load()

    for sc in ("1.2.1", "1.2.2"):
        reg = rule_registry.get(sc, "av")
        assert reg is not None, f"{sc} × av is not registered"
        assert callable(reg.detector), f"{sc} × av claims coverage with no detector"
        assert reg.coverage.value == "partial", (
            f"{sc} × av is {reg.coverage.value}; FULL would let a clean scan certify a pass on a "
            f"technique that never reads the caption text")
        assert reg.reason, "a partial technique must say what it does not reach"


def test_a_clean_media_file_is_review_and_never_a_certified_pass():
    """Asserted through `store._rule_outcome` — the function the product actually calls — rather
    than through the registry's own helper, for the reason test_rule_registry gives: a rule that
    certifies correctly in the registry and wrongly in the pipeline is still wrong."""
    import store
    assert store._rule_outcome("1.2.2", "av", fail_count=0, review_count=0) == "REVIEW"
    assert store._rule_outcome("1.2.2", "av", fail_count=1, review_count=0) == "FAIL"


def test_the_capability_layer_fails_closed_for_an_unreadable_file(tmp_path, monkeypatch):
    """The architectural half of the same contract. `capabilities_for` narrows per document, so a
    file nothing could probe must advertise NOTHING — which makes `rule_registry.evaluate` report
    the missing capability by name instead of running a technique over an unknown."""
    import capabilities
    monkeypatch.setattr(media, "probe", lambda *_a, **_k: None)
    clip = tmp_path / "x.mp4"
    clip.write_bytes(b"\x00" * 32)
    assert capabilities.capabilities_for("av", clip) == frozenset(), (
        "an unprobeable media file still advertised capabilities — a rule requiring them would "
        "then run against a file nothing could read")


@needs_media
def test_a_silent_video_does_not_advertise_an_audio_track(tmp_path):
    """Per-document narrowing, which is what makes 1.2.2 report unsupported-for-THIS-document on
    a silent video rather than inventing a finding."""
    import capabilities
    silent = _build(tmp_path / "silent.mp4", audio=False)
    caps = capabilities.capabilities_for("av", silent)
    assert capabilities.Capability.AUDIO_TRACK not in caps
    assert capabilities.Capability.MEDIA_STREAMS in caps, (
        "the container was read successfully — that capability is present even with no audio")


# ── discovery scope: earned, and still opt-in ───────────────────────────────────────────────
def test_av_is_known_but_not_a_default_discovery_format():
    """Both halves matter. KNOWN means an operator MAY switch it on; not-DEFAULT means the
    2026-09-01 scope decision is untouched and no existing deployment starts listing video."""
    assert "av" in scan_formats.KNOWN_FORMATS, (
        "av is not switchable on; the detector this slice adds would be unreachable")
    assert "av" not in scan_formats.DEFAULT_FORMATS, (
        "media entered Discovery's DEFAULT scope. That contradicts the 2026-09-01 decision "
        "recorded in api/scan_formats.py — change the decision there first, deliberately")
    assert scan_formats.formats() == frozenset({"pdf", "docx", "xlsx", "pptx"})


def test_switching_av_on_makes_media_assessable_rather_than_metadata_only(monkeypatch):
    """The estate-inventory consequence, which needed no change to estate_inventory at all.

    `_status_of` already asks `scan_formats.is_supported_format(fmt)` FIRST and falls back to
    METADATA_ONLY for the "av" bucket. Choosing "av" as the scan_formats key rather than inventing
    "media" is what makes that work: scan_formats' own header says its keys are "the same strings
    estate_inventory._format_of returns", and honouring that turned a cross-module edit into a
    table entry.
    """
    import estate_inventory as ei
    row = {"name": "townhall.mp4", "mimeType": "video/mp4"}
    assert ei.classify(row)["format"] == "av"
    assert ei.classify(row)["status"] == ei.METADATA_ONLY

    monkeypatch.setenv("ACP_SCAN_FORMATS", "pdf,docx,xlsx,pptx,av")
    assert ei.classify(row)["status"] == ei.ASSESSABLE
    assert ".mp4" in scan_formats.extensions()


def test_the_dispatch_and_the_scan_scope_list_the_same_extensions():
    """`office_structure._AV_EXTS` is a literal, and this is what makes that safe.

    It has to be a literal: `scripts/gen_rules_index.py` reads `checks_for`'s AST to learn which
    formats each check reaches, and it cannot evaluate `frozenset(scan_formats._EXT_OF["av"])`. A
    derived set would leave the branch with no string constants in it, the branch would be skipped,
    and the media rules would quietly stop being documented in rules/ — the exact silence
    tests/test_rules_index.py was written after.

    So the list exists twice, and drift is caught here rather than in production. BOTH DIRECTIONS
    are asserted because they fail differently and both fail quietly: an extension in scan_formats
    and not in the dispatch is a file Discovery lists and `checks_for` answers with `[]`, which
    reads as a clean file; one in the dispatch and not in scan_formats is a detector nothing can
    route to.
    """
    assert set(office_structure._AV_EXTS) == set(scan_formats._EXT_OF["av"]), (
        f"only in the dispatch: {sorted(set(office_structure._AV_EXTS) - set(scan_formats._EXT_OF['av']))}; "
        f"only in scan scope: {sorted(set(scan_formats._EXT_OF['av']) - set(office_structure._AV_EXTS))}")


def test_the_scan_scope_and_the_estate_bucket_list_the_same_extensions():
    """The third copy, and the one whose drift is invisible from either side.

    `estate_inventory._AV_EXT` decides which files get the "av" BUCKET; `scan_formats._EXT_OF`
    decides which extensions that bucket's scope covers. An extension known to the inventory and
    not to scan_formats classifies as "av" and then never matches the listing filter; one known to
    scan_formats and not to the inventory is listed and then classified "other" — unsupported. Both
    end with a media file silently not assessed, from opposite directions.
    """
    import estate_inventory as ei
    assert set(ei._AV_EXT) == set(scan_formats._EXT_OF["av"]), (
        f"only in the estate bucket: {sorted(set(ei._AV_EXT) - set(scan_formats._EXT_OF['av']))}; "
        f"only in scan scope: {sorted(set(scan_formats._EXT_OF['av']) - set(ei._AV_EXT))}")


def test_an_unknown_format_name_still_cannot_be_switched_on(monkeypatch):
    """The guard that makes KNOWN_FORMATS worth having stays intact — adding one entry must not
    turn the validation into a pass-through."""
    monkeypatch.setenv("ACP_SCAN_FORMATS", "mp4,video,av")
    assert scan_formats.formats() == frozenset({"av"}), (
        "'mp4' and 'video' are not format keys and must be dropped, not accepted")


# ── what slice 2 still does NOT claim ────────────────────────────────────────────────────────
def test_1_2_3_is_still_unclaimed():
    """Audio description is a different artefact and a different technique — it cannot be
    established by looking at stream layout. Registering it here to "complete the set" is exactly
    the unearned claim the capability report exists to prevent."""
    import rule_registry
    rule_registry.load()
    assert rule_registry.get("1.2.3", "av") is None, (
        "1.2.3 was registered. Nothing in this slice can tell whether a video needs an audio "
        "description, let alone whether one is present")


def test_no_caption_file_is_written_by_an_assessment():
    """Slice 1 can DRAFT captions; nothing in the assessment path calls it. A scan that silently
    produced files would be writing to a customer's estate as a side effect of reading it.

    READ FROM THE AST, not with a substring scan. The first version of this test grepped the
    source for "transcribe" and failed on the phrase "no soundtrack to transcribe" inside a
    comment — a test that reports prose as a code defect is one people learn to edit around. The
    parse asks the question actually meant: does this module CALL any of them?
    """
    import ast

    import formats.av.detectors.captions as det
    tree = ast.parse(Path(det.__file__).read_text())
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    called |= {n.func.id for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    writes = called & {"to_webvtt", "to_srt", "to_transcript", "transcribe", "extract_audio"}
    assert not writes, (
        f"the detector calls {sorted(writes)} — drafting belongs to the remediation lane, which "
        f"this slice does not build; an assessment must only read")
