"""The media engine boundary: real ffmpeg, and the contract that absence is never a clean result.

WHAT IS REAL HERE. The extraction tests build an actual .mp4 with ffmpeg — a real H.264 video
track and a real AAC soundtrack — and decode it to a real WAV, then read the WAV header back to
check the sample rate, channel count and depth. Nothing is mocked, because the thing worth
asserting is that a decode a caller depends on actually happens and produces the shape the
transcriber requires.

WHAT IS DELIBERATELY NOT ASSERTED. Whether the ASR returns the right WORDS. That is a property of
the model, not of this repo, and a test that pinned it would fail on a model upgrade that
improved accuracy. What IS asserted about transcription is its contract: the shape of the result,
and — the part that matters — that a missing engine is distinguishable from silent audio.

THE CONTRACT, restated because it is the whole reason this file exists:

    transcribe(...) -> None   nothing ran; nothing is known
    transcribe(...) -> []     audio was processed and held no speech

`api/proposals.py` was changed in #1082 precisely because a scan that could not run once looked
identical to one that found nothing, and every caller read the second meaning. A caption pipeline
has the same failure available to it: a media file whose transcriber was missing must never
report as "no speech, nothing to caption", because that is indistinguishable from a correctly
captioned-as-empty file and would certify a video nobody transcribed.

CI DOES NOT NEED THESE ENGINES. Both probes come from `tests/engines.py`, and the ASR tests skip
with a reason naming the install. The first model load downloads weights, so requiring it in CI
would put a network fetch on the critical path of every shard — the engine is optional by design,
and its absence makes the capability abstain rather than pass.
"""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "api", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import media  # noqa: E402
from engines import ASR_OK, MEDIA_OK, NO_ASR, NO_MEDIA  # noqa: E402

needs_media = pytest.mark.skipif(not MEDIA_OK, reason=NO_MEDIA)
needs_asr = pytest.mark.skipif(not ASR_OK, reason=NO_ASR)


# ── fixtures: real media, built by ffmpeg ────────────────────────────────────────
def _make_media(path: Path, *, seconds: int = 2, video: bool = True, audio: bool = True) -> Path:
    """A real container. `lavfi` synthesises both tracks, so no asset is checked in and the
    fixture cannot drift from what it claims to be."""
    ff = media.ffmpeg_path()
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"]
    if video:
        cmd += ["-f", "lavfi", "-i", f"testsrc=size=160x120:rate=10:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    if video:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac"]
    cmd += ["-shortest", str(path)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, f"fixture build failed: {res.stderr[-400:]}"
    return path


# ── recognition (no engine needed) ───────────────────────────────────────────────
def test_media_is_recognised_by_extension_and_split_by_kind():
    """Video and audio are separated because WCAG asks for different artefacts: captions for
    video with a soundtrack (1.2.2), a transcript for audio-only (1.2.1). A detector that lumped
    them together would request the wrong one."""
    assert media.media_kind("talk.mp4") == "video"
    assert media.media_kind("TALK.MOV") == "video", "extension matching must be case-insensitive"
    assert media.media_kind("interview.mp3") == "audio"
    assert media.media_kind("notes.docx") is None
    assert media.is_media("clip.webm") and not media.is_media("clip.webp")


def test_engine_status_names_the_fix_not_just_the_state():
    """A readiness signal that says only "unavailable" sends the next person to read source."""
    status = media.engine_status()
    assert set(status) >= {"available", "ffmpeg", "asr", "reason"}
    if not status["available"]:
        assert status["reason"], "an unavailable engine must say what to install"
        assert "install" in status["reason"] or "pip" in status["reason"]
    else:
        assert status["reason"] is None


# ── probing and extraction (real ffmpeg) ─────────────────────────────────────────
@needs_media
def test_probe_reads_the_streams_a_container_actually_holds(tmp_path):
    """Container-level truth, not extension guessing: an .mp4 may legitimately hold no audio,
    and that changes which criterion applies."""
    both = _make_media(tmp_path / "both.mp4")
    info = media.probe(both)
    assert info is not None, "a real file with a real engine must probe"
    assert info.has_video and info.has_audio
    assert info.kind == "video"
    assert info.duration and 1.5 <= info.duration <= 3.0, f"duration read as {info.duration}"


@needs_media
def test_a_silent_video_is_distinguished_from_one_with_a_soundtrack(tmp_path):
    """The 1.2.2-vs-1.2.3 fork. A video with no audio track cannot be captioned — there is
    nothing to caption — and needs a description instead. Getting this wrong asks a reviewer for
    an artefact that cannot exist."""
    silent = _make_media(tmp_path / "silent.mp4", audio=False)
    info = media.probe(silent)
    assert info is not None and info.has_video and not info.has_audio
    assert info.kind == "video_silent"


@needs_media
def test_extract_audio_produces_exactly_what_the_transcriber_wants(tmp_path):
    """16 kHz, mono, 16-bit PCM — read back from the WAV header, not assumed from the flags.

    Those parameters are not arbitrary: Whisper-family models resample to 16 kHz mono internally,
    so producing it here means one decode instead of two.
    """
    src = _make_media(tmp_path / "clip.mp4")
    out = media.extract_audio(src, tmp_path / "clip.wav")
    assert out is not None and out.exists() and out.stat().st_size > 0

    with wave.open(str(out), "rb") as w:
        assert w.getframerate() == 16000, "the transcriber expects 16 kHz"
        assert w.getnchannels() == 1, "mono"
        assert w.getsampwidth() == 2, "16-bit PCM"
        assert w.getnframes() > 0, "an empty WAV is not an extraction"


@needs_media
def test_extraction_of_a_non_media_file_fails_rather_than_writing_a_stub(tmp_path):
    """A .docx renamed to .mp4 is a real thing in a document estate. ffmpeg rejects it, and the
    caller must get None — not a zero-length WAV that a transcriber would happily read as
    silence and report as "no speech"."""
    fake = tmp_path / "not-really.mp4"
    fake.write_bytes(b"PK\x03\x04 this is a zip, not a video")
    assert media.extract_audio(fake, tmp_path / "out.wav") is None
    assert media.probe(fake) is None


def test_a_missing_file_never_reports_as_empty_media(tmp_path):
    """Runs with or without an engine: absence of the input is not a property of the input."""
    assert media.probe(tmp_path / "nope.mp4") is None
    assert media.extract_audio(tmp_path / "nope.mp4", tmp_path / "o.wav") is None


# ── the contract that absence is not a clean result ──────────────────────────────
def test_transcribe_returns_None_when_no_engine_ran(tmp_path, monkeypatch):
    """THE CONTRACT. Forced by disabling the probe, so it holds on a machine that HAS the engine —
    otherwise this test would only ever run where it cannot fail interestingly.

    None, never `Transcript(segments=[])`. The empty list means "processed, no speech"; a caller
    that received it for a file nothing opened would report a video as needing no captions.
    """
    monkeypatch.setattr(media, "asr_available", lambda: False)
    wav = tmp_path / "silence.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    assert media.transcribe(wav) is None, (
        "a missing transcriber returned something other than None — an empty result here is "
        "indistinguishable from silent audio and would certify an untranscribed file")


def test_transcribe_returns_None_for_a_missing_input_not_an_empty_result(tmp_path):
    assert media.transcribe(tmp_path / "absent.wav") is None


@needs_asr
@needs_media
def test_real_transcription_of_speechless_audio_is_EMPTY_not_None(tmp_path):
    """The other side of the contract, and the one that needs a real engine to mean anything.

    A pure 440 Hz tone contains no speech. The transcriber runs, succeeds, and finds nothing — so
    the result is a Transcript whose segments are empty, NOT None. If both cases returned None
    the distinction would be untestable and the contract merely aspirational.
    """
    src = _make_media(tmp_path / "tone.mp4")
    wav = media.extract_audio(src, tmp_path / "tone.wav")
    assert wav is not None

    result = media.transcribe(wav)
    assert result is not None, "the engine is present, so this must not be None"
    assert result.segments == [], f"a pure tone should hold no speech, got {result.segments}"
    assert result.model, "the result must record which model produced it"


@needs_asr
@needs_media
def test_the_whole_pipeline_runs_on_a_real_file_and_produces_a_valid_caption_file(tmp_path):
    """End to end on real bytes: container -> audio -> transcript -> cues -> WebVTT.

    Deliberately does NOT assert the words. A tone yields no speech, so the honest end-to-end
    assertion is that every stage completes and the writer emits a structurally valid file for
    whatever the ASR returned — including nothing.
    """
    import captions

    src = _make_media(tmp_path / "end2end.mp4", seconds=3)
    info = media.probe(src)
    assert info and info.has_audio

    wav = media.extract_audio(src, tmp_path / "end2end.wav")
    assert wav is not None

    result = media.transcribe(wav)
    assert result is not None

    cues = captions.segment_cues(result.segments)
    vtt = captions.to_webvtt(cues, language=result.language,
                             note=f"Drafted by ACP using {result.model}; awaiting human approval.")
    assert vtt.startswith("WEBVTT"), "the pipeline must emit a loadable file even with no cues"
    assert "awaiting human approval" in vtt, "provenance travels with the file"
    assert captions.parse_cues(vtt) == cues, "what was written must read back identically"


# ── sidecars ─────────────────────────────────────────────────────────────────────
def test_existing_caption_files_beside_the_media_are_found():
    """A media file sitting next to its own captions is already served. Without this, the first
    finding on a correctly captioned library would be a false positive on every file in it."""
    siblings = ["talk.mp4", "talk.vtt", "talk.en.vtt", "talk.en-GB.srt",
                "talkback.vtt", "other.srt", "talk.txt"]
    found = media.sidecar_captions("talk.mp4", siblings=siblings)
    assert found == ["talk.en-GB.srt", "talk.en.vtt", "talk.vtt"]
    assert "talkback.vtt" not in found, "a different file that merely shares a prefix"
    assert "other.srt" not in found
    assert "talk.txt" not in found, "a transcript is not a caption track"


def test_no_sidecars_is_an_empty_list_not_an_error():
    assert media.sidecar_captions("talk.mp4", siblings=["talk.mp4", "readme.md"]) == []
