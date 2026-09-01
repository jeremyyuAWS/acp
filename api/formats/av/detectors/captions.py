"""1.2.1 / 1.2.2 for a standalone audio or video file — is a text alternative present at all?

WHAT THE TECHNIQUE ESTABLISHES. Whether the file is served by captions or a transcript, from two
places a machine can check without judgement: a caption stream inside the container, and a caption
sidecar next to it. Both are facts. Neither requires reading a word of the captions.

WHAT IT DELIBERATELY DOES NOT ESTABLISH, which is why the registration is PARTIAL and a clean scan
is REVIEW rather than a pass:

  * whether existing captions are ACCURATE or SYNCHRONISED — that needs the audio and the text
    compared, and a wrong-language auto-caption track would clear this check;
  * 1.2.2's media-alternative-for-text exception (a video that is itself an alternative for text
    already on the page needs no captions) — nothing in a standalone file expresses that;
  * whether an audio-only file is speech at all. A soundtrack of music needs no transcript, and
    this cannot tell music from talking.

THE SIDECAR BLIND SPOT, stated here because it decides how a finding should be read. A connector
scan downloads one file to a temporary directory and assesses it ALONE — its siblings are not
there. So `talk.vtt` sitting beside `talk.mp4` in the customer's Drive is invisible on that path,
and only a local/in-place scan sees it. That is a false-positive source in the one direction:
a served file may still be flagged. It is bounded, it is why a human adjudicates the finding, and
it is the main thing a later slice should close by passing the listing's sibling names through.

FAIL CLOSED. `media.probe` returns None when no engine could look. This detector never turns that
into silence. An empty finding list on a pass/fail path means "assessed, nothing wrong" — the
exact conflation #1082 removed from verification — so a file that could not be read produces a
REVIEW finding that says so, and a reviewer can tell "captions are missing" from "nobody looked".
"""
from __future__ import annotations

from pathlib import Path

import media

# Sidecars that count as a TRANSCRIPT for 1.2.1 but not as CAPTIONS for 1.2.2. A .txt beside an
# .mp3 is a transcript in the sense 1.2.1 asks for; the same file beside a video is not captions,
# because captions are synchronised with the picture and a text file is not.
_TRANSCRIPT_EXTS = (".txt", ".md", ".vtt", ".srt")


def _sidecars(path: Path) -> list[str]:
    """Caption files beside this one. Empty when the directory cannot be listed, which is the
    common case on a connector scan and is handled by the caller, not silently here."""
    try:
        siblings = [p.name for p in path.parent.iterdir() if p.is_file()]
    except Exception:
        return []
    return media.sidecar_captions(path.name, siblings=siblings)


def _transcript_sidecars(path: Path) -> list[str]:
    """The 1.2.1 variant: a plain-text transcript counts, where for captions it would not."""
    stem = path.stem.lower()
    try:
        names = [p.name for p in path.parent.iterdir() if p.is_file()]
    except Exception:
        return []
    out = []
    for name in names:
        p = Path(name)
        if p.suffix.lower() not in _TRANSCRIPT_EXTS:
            continue
        cand = p.stem.lower()
        # `startswith(stem)` alone matches `talkback.txt` for `talk.mp3`. The separator is what
        # makes `talk.en.vtt` a variant of `talk` and `talkback` a different file entirely.
        if cand == stem or cand.startswith(stem + "."):
            out.append(name)
    return sorted(out)


def _finding(rule_id: str, wcag: str, severity: str, detail: str) -> dict:
    return {"ruleId": rule_id, "wcag": wcag, "severity": severity, "detail": detail}


def detect(path: str | Path) -> list[dict]:
    """Findings for one standalone media file. Never raises — a structural check must not fail a
    scan (the rule every `office_structure.checks_for` detector follows)."""
    p = Path(str(path))
    kind = media.media_kind(p.name)
    if kind is None:
        return []

    try:
        info = media.probe(p)
    except Exception:
        info = None

    if info is None:
        # Not a defect and not a clean result — a statement that nothing looked. REVIEW severity,
        # so `_rule_outcome` resolves it to REVIEW and never to PASS.
        sc = "1.2.2 Captions (Prerecorded)" if kind == "video" else "1.2.1 Audio-only & Video-only"
        return [_finding(
            "MEDIA_NOT_ASSESSED", sc, "REVIEW",
            f"{p.name} was NOT ASSESSED for a text alternative: no media engine could read the "
            f"container. {media.engine_status().get('reason') or 'The engine is unavailable.'} "
            f"This is not evidence that captions are present or absent — a person must check.")]

    if info.has_captions:
        return []

    if info.has_video and info.has_audio:
        if _sidecars(p):
            return []
        return [_finding(
            "MEDIA_VIDEO_NO_CAPTIONS", "1.2.2 Captions (Prerecorded)", "SERIOUS",
            f"{p.name} has a soundtrack but carries no caption track, and no caption file was "
            f"found beside it. Prerecorded video with audio needs synchronised captions. If this "
            f"video is an alternative for text that already appears elsewhere, 1.2.2 does not "
            f"apply — that exception is not something the file itself can express.")]

    if info.has_audio and not info.has_video:
        if _transcript_sidecars(p):
            return []
        return [_finding(
            "MEDIA_AUDIO_NO_TRANSCRIPT", "1.2.1 Audio-only & Video-only", "SERIOUS",
            f"{p.name} is audio-only and no transcript was found beside it. Prerecorded "
            f"audio-only content needs an equivalent text alternative. Music or ambience with no "
            f"speech does not — this check cannot tell those apart, so a person confirms.")]

    # Video with no audio track. Nothing to caption and no soundtrack to transcribe; what it may
    # need is an audio description or a text alternative, which is 1.2.3 and is not claimed by any
    # detector in this codebase. Returning nothing here is the honest answer, and it is NOT the
    # same as the missing-engine branch above: this container was read.
    return []
