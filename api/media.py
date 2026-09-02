"""Standalone media: recognising it, probing it, pulling audio out, transcribing it locally.

THE ENGINE BOUNDARY. Everything here that needs a binary or a model goes through one probe, and
every entry point answers honestly when the engine is absent rather than guessing. That is the
same contract the Office .NET analyser, the PDF analyser, tesseract and the vision model already
have in this codebase, and it exists because of what the alternative costs: `api/proposals.py`
now fails CLOSED precisely because a scan that could not run once looked identical to a scan that
found nothing.

So, stated once and enforced below: A MISSING ENGINE PRODUCES `None`, NEVER AN EMPTY RESULT.
`transcribe()` returning `[]` means the audio was processed and held no speech. Returning `None`
means nothing was processed and nothing is known. A caller that conflates the two would publish
"no captions needed" for a file no transcriber ever opened.

WHY LOCAL. Media routinely carries the most sensitive material an organisation holds — recorded
meetings, HR interviews, customer calls. Shipping that audio to a third-party ASR to obtain an
accessibility artefact would trade one compliance problem for a worse one. `faster-whisper` runs
on CPU through CTranslate2, needs no GPU and no API key, and the model is fetched once and cached.

WHY THE FFMPEG LOOKUP LOOKS LIKE THAT. A system ffmpeg is preferred when present. Failing that,
`imageio-ffmpeg` ships a static binary as an ordinary Python wheel, which is the only way to get
ffmpeg into an environment where apt is unavailable — the case in this project's own build
sandbox. Both are checked; neither is required.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# ── what counts as media ─────────────────────────────────────────────────────────
# Split by kind because WCAG treats them differently: video with audio needs captions (1.2.2),
# audio-only needs a transcript (1.2.1), and video-only (no soundtrack) needs a description or
# transcript (1.2.3). A detector that lumps them together asks for the wrong artefact.
VIDEO_EXTS = (".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".wmv", ".mpg", ".mpeg")
AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma")
MEDIA_EXTS = VIDEO_EXTS + AUDIO_EXTS

# Sidecar caption files. A media file sitting beside its own captions is already served, and
# flagging it would be a false positive on the commonest correct arrangement there is.
CAPTION_EXTS = (".vtt", ".srt", ".ttml", ".dfxp", ".sbv", ".sub", ".ass", ".ssa")

# Extension -> the MIME type a BROWSER needs to play it.
#
# WHY THIS EXISTS SEPARATELY FROM scan_formats._MIME_OF. That map answers "which uploaded MIME
# types are in Discovery's scope" and is a per-FORMAT set — "av" maps to twelve strings, several
# of them alternates for one extension (audio/wav and audio/x-wav are both .wav). A player needs
# the opposite shape: one extension, one type to put in a Content-Type header, chosen rather than
# enumerated. Deriving one from the other would mean picking arbitrarily from a set.
#
# THIS IS NOT COSMETIC. A <video> element handed `application/octet-stream` refuses to play the
# file — browsers will not sniff a container out of a generic type — so a caption reviewer could
# not watch the video they were correcting a transcript for, which is the one thing the
# correction requires. The keys are bound to scan_formats._EXT_OF["av"] by
# tests/test_media_content_type.py, so a format the remediation lane admits cannot come back as a
# type the reviewer's browser will not open.
MEDIA_MIME_TYPES: dict[str, str] = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".webm": "video/webm", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
    ".wmv": "video/x-ms-wmv", ".mpg": "video/mpeg", ".mpeg": "video/mpeg",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav",
    ".aac": "audio/aac", ".ogg": "audio/ogg", ".oga": "audio/ogg",
    ".opus": "audio/opus", ".flac": "audio/flac", ".wma": "audio/x-ms-wma",
}


def media_mime(name: str) -> str | None:
    """The playable MIME type for a filename, or None when it is not media we can name one for.

    None rather than a default: a caller that cannot identify the type must fall back to its own
    honest answer (`application/octet-stream`), not be handed a guess. Telling a browser that an
    unknown file is video/mp4 is how a player is asked to render something that is not video.
    """
    ext = Path(str(name or "")).suffix.lower()
    return MEDIA_MIME_TYPES.get(ext)
TRANSCRIPT_EXTS = (".txt", ".md", ".docx", ".pdf", ".rtf")

ASR_MODEL = os.environ.get("ACP_ASR_MODEL", "tiny")
ASR_COMPUTE = os.environ.get("ACP_ASR_COMPUTE", "int8")
_FFMPEG_TIMEOUT = int(os.environ.get("ACP_FFMPEG_TIMEOUT", "300"))


def is_media(name: str | os.PathLike) -> bool:
    return Path(str(name)).suffix.lower() in MEDIA_EXTS


def media_kind(name: str | os.PathLike) -> str | None:
    """"video" | "audio" | None — from the EXTENSION alone.

    Container-level, not content-level: an .mp4 holding only a soundtrack is still declared video
    here. `probe()` is what knows whether streams are actually present, and the detector uses that
    rather than this, because the difference decides which criterion applies.
    """
    ext = Path(str(name)).suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


# ── engine probes ────────────────────────────────────────────────────────────────
def ffmpeg_path() -> str | None:
    """A usable ffmpeg, or None. System first, then the pip-installed static binary."""
    found = shutil.which(os.environ.get("ACP_FFMPEG") or "ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe if exe and Path(exe).exists() else None
    except Exception:
        return None


def ffprobe_path() -> str | None:
    """ffprobe if the system has it. The static wheel ships ffmpeg only, so this is often None —
    `probe()` falls back to parsing ffmpeg's own stderr, which always exists where ffmpeg does."""
    return shutil.which(os.environ.get("ACP_FFPROBE") or "ffprobe")


def media_available() -> bool:
    """Can audio be extracted at all?"""
    return ffmpeg_path() is not None


def asr_available() -> bool:
    """Is a local transcriber importable?

    Import only — it deliberately does NOT load the model, because the first load downloads
    weights and a readiness probe must not block on a network fetch. A present library with an
    unreachable model surfaces at `transcribe()` as None with a reason, not as a hung /readyz.
    """
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def engine_status() -> dict:
    """One dict for /readyz and the capability report. Names the fix, not just the state —
    a readiness signal that says only "unavailable" sends someone reading source to find out
    what to install."""
    ff, asr = ffmpeg_path(), asr_available()
    reason = None
    if not ff and not asr:
        reason = ("no media engine: install ffmpeg (or `pip install imageio-ffmpeg`) and "
                  "`pip install faster-whisper`")
    elif not ff:
        reason = "ffmpeg is missing: install it, or `pip install imageio-ffmpeg`"
    elif not asr:
        reason = "no local transcriber: `pip install faster-whisper`"
    return {
        "available": bool(ff and asr),
        "ffmpeg": ff,
        "asr": asr,
        "model": ASR_MODEL if asr else None,
        "reason": reason,
    }


# ── probing ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class MediaInfo:
    """What a container actually holds. `duration` is seconds; None when it could not be read.

    `has_captions` is a fact about the CONTAINER, not about the estate: an .mp4 can carry its
    captions internally as a mov_text stream, an .mkv as embedded WebVTT. A caption check that
    looked only for a neighbouring .vtt would report a false positive on every correctly
    captioned file of that shape — which is most broadcast and LMS output. The sidecar is the
    other half and lives in `sidecar_captions`; a file is served if EITHER is true.

    Defaulted to False rather than made required so no existing caller has to change. That is
    safe here and would not be for `has_audio`: a wrong default of False on captions produces a
    finding a human then dismisses, while a wrong default on audio would silence one. Neither is
    ever reached by the missing-engine path, which returns None for the whole object.
    """
    duration: float | None
    has_audio: bool
    has_video: bool
    has_captions: bool = False

    @property
    def kind(self) -> str:
        if self.has_video and self.has_audio:
            return "video"
        if self.has_video:
            return "video_silent"
        return "audio"


def probe(path: str | os.PathLike) -> MediaInfo | None:
    """Read stream layout and duration, or None when no engine could look.

    None is not "an empty file" — see this module's header. A detector that read None as "no
    audio track" would ask for an audio description on every file the moment ffmpeg went missing.
    """
    p = Path(str(path))
    if not p.exists():
        return None
    probe_exe = ffprobe_path()
    if probe_exe:
        info = _probe_with_ffprobe(probe_exe, p)
        if info is not None:
            return info
    ff = ffmpeg_path()
    if not ff:
        return None
    return _probe_with_ffmpeg(ff, p)


def _probe_with_ffprobe(exe: str, path: Path) -> MediaInfo | None:
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT)
        if out.returncode != 0:
            return None
        data = json.loads(out.stdout or "{}")
        kinds = {s.get("codec_type") for s in data.get("streams", [])}
        raw = (data.get("format") or {}).get("duration")
        return MediaInfo(duration=_as_float(raw),
                         has_audio="audio" in kinds, has_video="video" in kinds,
                         has_captions="subtitle" in kinds)
    except Exception:
        return None


def _probe_with_ffmpeg(exe: str, path: Path) -> MediaInfo | None:
    """Parse `ffmpeg -i` stderr. Used when only the static wheel is installed (no ffprobe).

    ffmpeg exits non-zero when given no output file — that is expected here and is not a failure;
    the stream banner it prints on the way out is exactly what is being read.
    """
    try:
        out = subprocess.run([exe, "-hide_banner", "-i", str(path)],
                             capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT)
    except Exception:
        return None
    err = out.stderr or ""
    if "Invalid data found" in err or "No such file" in err:
        return None
    has_audio = " Audio: " in err
    has_video = " Video: " in err
    # " Subtitle: " is how ffmpeg's own stream banner names a caption track, verified against a
    # real mov_text mux rather than assumed from the ffprobe codec_type spelling ("subtitle",
    # lower case, no spaces). The two formats differ, and reading one off the other is the shape
    # of mistake this repo keeps a section about.
    has_captions = " Subtitle: " in err
    if not (has_audio or has_video):
        return None
    duration = None
    for line in err.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            stamp = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
            duration = _hhmmss_to_seconds(stamp)
            break
    return MediaInfo(duration=duration, has_audio=has_audio, has_video=has_video,
                     has_captions=has_captions)


def _as_float(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _hhmmss_to_seconds(stamp: str):
    try:
        h, m, s = stamp.split(":")
        return round(int(h) * 3600 + int(m) * 60 + float(s), 3)
    except Exception:
        return None


# ── audio extraction ─────────────────────────────────────────────────────────────
def extract_audio(path: str | os.PathLike, dest: str | os.PathLike) -> Path | None:
    """Decode the audio track to 16 kHz mono 16-bit PCM WAV, or None if it could not be done.

    Those parameters are not arbitrary: Whisper-family models resample to 16 kHz mono internally,
    so doing it here means one decode instead of two and a file the ASR reads without conversion.
    PCM rather than a compressed form because this is a temporary intermediate — spending CPU to
    compress something about to be read once and deleted is pure loss.

    `-vn` matters more than it looks: without it, a video's picture is decoded too, which on a
    long file is most of the runtime for a result that is then discarded.
    """
    ff = ffmpeg_path()
    src = Path(str(path))
    if not ff or not src.exists():
        return None
    out_path = Path(str(dest))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(
            [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_path)],
            capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT)
    except Exception:
        return None
    if res.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        return None
    return out_path


# ── transcription ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Transcript:
    """Segments as the ASR produced them, plus what it believed about the audio.

    `segments` are raw — not yet cues. `captions.segment_cues` re-cuts them for readability, and
    keeping the two apart means a reviewer's re-segmentation never has to re-run the model.
    """
    segments: list
    language: str | None
    duration: float | None
    model: str


def transcribe(audio_path: str | os.PathLike, *, language: str | None = None) -> Transcript | None:
    """Transcribe a WAV locally. None when no engine ran — never an empty Transcript.

    A `Transcript` with `segments == []` is a real result: audio was decoded and no speech was
    found (silence, music, tone). That distinction is the whole contract of this module, and the
    caller acts on it — empty means "nothing to caption", None means "we do not know".
    """
    if not asr_available():
        return None
    src = Path(str(audio_path))
    if not src.exists():
        return None
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(ASR_MODEL, device="cpu", compute_type=ASR_COMPUTE)
        segments, info = model.transcribe(str(src), language=language, vad_filter=True)
        out = [{"start": float(s.start), "end": float(s.end), "text": str(s.text)}
               for s in segments]
    except Exception:
        return None
    return Transcript(segments=out,
                      language=getattr(info, "language", None) or language,
                      duration=_as_float(getattr(info, "duration", None)),
                      model=ASR_MODEL)


# ── sidecars ─────────────────────────────────────────────────────────────────────
def sidecar_captions(path: str | os.PathLike, siblings=None) -> list[str]:
    """Caption files already sitting beside this media.

    Matches `talk.mp4` against `talk.vtt`, `talk.en.vtt`, `talk.en-GB.srt` — the stem-plus-tag
    convention every player and CMS uses for a language track. Without this, the detector's first
    finding on a correctly captioned library would be a false positive on every file in it.

    `siblings` is injectable so the detector can pass a listing it already has (an object store,
    a scan manifest) instead of forcing a directory walk that may not be possible.
    """
    p = Path(str(path))
    stem = p.stem.lower()
    names = ([Path(str(s)).name for s in siblings] if siblings is not None
             else [c.name for c in p.parent.iterdir()] if p.parent.is_dir() else [])
    found = []
    for name in names:
        cand = Path(name)
        if cand.suffix.lower() not in CAPTION_EXTS:
            continue
        cand_stem = cand.stem.lower()
        if cand_stem == stem or cand_stem.startswith(stem + "."):
            found.append(name)
    return sorted(found)
