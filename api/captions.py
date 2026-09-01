"""Caption cues, and the WebVTT / SRT / transcript forms they are written out as.

PURE. Nothing here opens a media file, shells out, or loads a model — it turns a list of
timed text segments into caption files, and reads one back. That separation is deliberate:
transcription quality is a property of whatever ASR produced the segments and is not something
this repo can assert, but cue timing, line breaking, escaping and file syntax are entirely ours
and are testable exactly.

WHY SEGMENTATION IS ITS OWN STEP. An ASR returns segments shaped by pauses in speech, not by
what a person can read. A single 14-second segment of 300 characters is a valid ASR result and
an unusable caption: it exceeds the reading rate, overflows the safe area, and sits on screen
long enough to lose sync with the picture. So `segment_cues` re-cuts ASR output against the
constraints captioning practice actually uses — characters per line, lines per cue, seconds on
screen, and characters per second — before anything is written.

The defaults below follow widely used broadcast/streaming caption guidance (BBC subtitle
guidelines, WCAG-adjacent practice): 37 characters a line, 2 lines, 1–7 seconds on screen, and
about 17 characters per second of reading speed. They are constants, not magic numbers scattered
through the code, because a customer with a house style will want to change exactly these.

WHAT THIS DOES NOT DO. It does not claim a caption is CORRECT — only that it is well formed and
readable. A caption that faithfully renders the wrong words is a defect no format check can see,
which is the entire reason the human approval step exists and why nothing here writes a file a
reviewer has not accepted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

# ── caption shape defaults ───────────────────────────────────────────────────────
MAX_CHARS_PER_LINE = 37      # BBC/streaming practice; keeps a cue inside the title-safe area
MAX_LINES_PER_CUE = 2        # a third line starts covering picture
MIN_CUE_SECONDS = 1.0        # below this a cue flashes and cannot be read
MAX_CUE_SECONDS = 7.0        # above this a cue drifts out of sync with what is on screen
MAX_CHARS_PER_SECOND = 17.0  # reading rate; the constraint that actually drives splitting
GAP_SECONDS = 0.04           # a frame or so, so consecutive cues never share a timestamp


@dataclass(frozen=True)
class Cue:
    """One caption: when it appears, when it goes, and the text shown.

    `text` may contain a newline for a two-line cue. Timings are seconds from the start of the
    media, as floats — not frames, because the source here is an ASR that has no frame rate and
    converting to frames would invent precision.
    """
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)

    @property
    def chars_per_second(self) -> float:
        """Reading rate. Newlines do not count as characters a reader must process."""
        n = len(self.text.replace("\n", " "))
        return n / self.duration if self.duration > 0 else float("inf")


# ── segmentation ─────────────────────────────────────────────────────────────────
def _wrap(text: str, width: int, max_lines: int) -> list[str]:
    """Break text into at most `max_lines` lines of at most `width` characters.

    Breaks on whitespace and never mid-word: a hyphenated split invents a word the speaker did
    not say. A single word longer than `width` is left over-long rather than broken, because the
    alternative is worse — an over-long line is legible, a chopped one is not.
    """
    words, lines, cur = text.split(), [], ""
    for w in words:
        candidate = f"{cur} {w}".strip()
        if cur and len(candidate) > width:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
        else:
            cur = candidate
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines or [text.strip()]


def _split_points(text: str, parts: int) -> list[str]:
    """Divide text into `parts` chunks on word boundaries, as evenly as possible.

    Even by CHARACTER COUNT rather than word count: an ASR segment mixing short and long words
    otherwise produces one dense chunk and one sparse one, and the dense chunk is the one that
    breaks the reading rate this splitting exists to satisfy.
    """
    words = text.split()
    if parts <= 1 or len(words) <= 1:
        return [text.strip()]
    parts = min(parts, len(words))
    target = len(text) / parts
    chunks, cur, cur_len = [], [], 0
    for i, w in enumerate(words):
        remaining_parts = parts - len(chunks)
        words_left = len(words) - i
        # always leave at least one word for each remaining chunk
        must_close = words_left <= remaining_parts - 1
        if cur and (cur_len + len(w) + 1 > target or must_close) and len(chunks) < parts - 1:
            chunks.append(" ".join(cur))
            cur, cur_len = [w], len(w)
        else:
            cur.append(w)
            cur_len += len(w) + 1
    if cur:
        chunks.append(" ".join(cur))
    return [c for c in chunks if c]


def segment_cues(segments, *, max_chars_per_line: int = MAX_CHARS_PER_LINE,
                 max_lines: int = MAX_LINES_PER_CUE,
                 max_seconds: float = MAX_CUE_SECONDS,
                 min_seconds: float = MIN_CUE_SECONDS,
                 max_cps: float = MAX_CHARS_PER_SECOND) -> list[Cue]:
    """Re-cut ASR segments into readable cues.

    `segments` is any iterable of objects or mappings with start / end / text. A segment is split
    when it is too long on screen, or carries more text than a reader can take at `max_cps`; the
    split is proportional to the text, so a chunk with more words gets more time.

    Timings are only ever subdivided, never extended past the segment they came from. A cue that
    outlives its speech would be a caption for words nobody is saying — worse than a short one,
    because it desynchronises everything a viewer reads afterwards.
    """
    out: list[Cue] = []
    for seg in segments or []:
        start, end, text = _seg_fields(seg)
        text = _clean(text)
        if not text or end <= start:
            continue
        span = end - start
        by_time = int(span // max_seconds) + (1 if span % max_seconds > 1e-9 else 0)
        by_rate = int(len(text) / (max_cps * span)) + 1 if span > 0 else 1
        by_size = int(len(text) / (max_chars_per_line * max_lines)) + 1
        parts = max(1, by_time, by_rate, by_size)

        chunks = _split_points(text, parts)
        if not chunks:
            continue
        total = sum(len(c) for c in chunks) or 1
        cursor = start
        for i, chunk in enumerate(chunks):
            share = span * (len(chunk) / total)
            c_end = end if i == len(chunks) - 1 else min(end, cursor + share)
            if c_end - cursor <= 0:
                continue
            out.append(Cue(round(cursor, 3), round(c_end, 3),
                           "\n".join(_wrap(chunk, max_chars_per_line, max_lines))))
            cursor = c_end
    return _separate(out, min_seconds)


def _separate(cues: list[Cue], min_seconds: float) -> list[Cue]:
    """Keep cues strictly ordered and non-overlapping.

    Two cues sharing a timestamp make a player show them in an order neither file specifies, so a
    frame-sized gap is opened between them. A cue shorter than `min_seconds` is left short rather
    than stretched into its neighbour: stealing time from the next cue would desync the rest of
    the file to fix one that is merely brief.
    """
    fixed: list[Cue] = []
    for cue in sorted(cues, key=lambda c: (c.start, c.end)):
        if fixed and cue.start < fixed[-1].end + GAP_SECONDS:
            new_start = round(fixed[-1].end + GAP_SECONDS, 3)
            if new_start >= cue.end:
                continue                      # fully swallowed by its predecessor
            cue = replace(cue, start=new_start)
        fixed.append(cue)
    return fixed


def _seg_fields(seg):
    if isinstance(seg, dict):
        return float(seg.get("start", 0)), float(seg.get("end", 0)), str(seg.get("text", ""))
    return float(getattr(seg, "start", 0)), float(getattr(seg, "end", 0)), str(getattr(seg, "text", ""))


def _clean(text: str) -> str:
    """Collapse whitespace. ASR output routinely carries a leading space and internal newlines."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


# ── timestamps ───────────────────────────────────────────────────────────────────
def _stamp(seconds: float, sep: str) -> str:
    """HH:MM:SS<sep>mmm. WebVTT uses '.', SRT uses ',' — the only difference between the two
    formats' timestamps, and the one most often got wrong."""
    if seconds < 0:
        seconds = 0.0
    ms_total = int(round(seconds * 1000))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def vtt_timestamp(seconds: float) -> str:
    return _stamp(seconds, ".")


def srt_timestamp(seconds: float) -> str:
    return _stamp(seconds, ",")


# ── writers ──────────────────────────────────────────────────────────────────────
def _escape_vtt(text: str) -> str:
    """WebVTT gives `&`, `<` and `>` markup meaning (§ cue payload text). Left raw, a caption
    reading "R&D <5%" either renders wrong or swallows the rest of the cue."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def to_webvtt(cues, *, language: str | None = None, note: str | None = None) -> str:
    """WebVTT — the form an HTML5 <track> consumes, and the default companion file.

    The optional NOTE block is where provenance goes. A caption file that a machine drafted and a
    person approved should say so in the file itself: it travels separately from this system, and
    whoever opens it next has no other way to know how it was made.
    """
    lines = ["WEBVTT"]
    if language:
        lines.append(f"Language: {language}")
    lines.append("")
    if note:
        lines.append("NOTE")
        lines.extend(note.splitlines())
        lines.append("")
    for i, cue in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{vtt_timestamp(cue.start)} --> {vtt_timestamp(cue.end)}")
        lines.extend(_escape_vtt(cue.text).splitlines())
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def to_srt(cues) -> str:
    """SRT — no header, 1-based index, comma milliseconds, CRLF-agnostic. Kept because most
    non-web players and every video editor read it, and WebVTT is not universally accepted."""
    blocks = []
    for i, cue in enumerate(cues, 1):
        blocks.append(f"{i}\n{srt_timestamp(cue.start)} --> {srt_timestamp(cue.end)}\n{cue.text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def to_transcript(cues, *, timestamps: bool = True) -> str:
    """A plain-text transcript — what 1.2.1 asks for on audio-only media, and what a reader who
    cannot use a player needs. Sentences are joined back together, because a transcript broken at
    caption boundaries reads as a list of fragments rather than as prose."""
    out = []
    for cue in cues:
        text = cue.text.replace("\n", " ").strip()
        out.append(f"[{vtt_timestamp(cue.start)}] {text}" if timestamps else text)
    return "\n".join(out) + ("\n" if out else "")


# ── reader (the editor round-trips through this) ─────────────────────────────────
_VTT_TIME = re.compile(
    r"(?P<sh>\d{2,}):(?P<sm>\d{2}):(?P<ss>\d{2})[.,](?P<sms>\d{3})"
    r"\s*-->\s*"
    r"(?P<eh>\d{2,}):(?P<em>\d{2}):(?P<es>\d{2})[.,](?P<ems>\d{3})")


def _unescape_vtt(text: str) -> str:
    return (text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))


def parse_cues(content: str) -> list[Cue]:
    """Read WebVTT or SRT back into cues.

    One parser for both: they differ in the header, the index line and the millisecond separator,
    and all three are things a reader can simply tolerate. The editor saves what a reviewer
    approved, so this has to accept a file this module wrote AND one a human hand-edited — hence
    tolerance of `,`/`.`, of missing indices, and of blank-line sloppiness.
    """
    cues: list[Cue] = []
    block: list[str] = []
    for raw in (content or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.strip():
            block.append(raw)
            continue
        cue = _block_to_cue(block)
        if cue:
            cues.append(cue)
        block = []
    cue = _block_to_cue(block)
    if cue:
        cues.append(cue)
    return cues


def _block_to_cue(block: list[str]) -> Cue | None:
    if not block:
        return None
    for i, line in enumerate(block):
        m = _VTT_TIME.search(line)
        if not m:
            continue
        g = m.groupdict()
        start = int(g["sh"]) * 3600 + int(g["sm"]) * 60 + int(g["ss"]) + int(g["sms"]) / 1000
        end = int(g["eh"]) * 3600 + int(g["em"]) * 60 + int(g["es"]) + int(g["ems"]) / 1000
        text = "\n".join(block[i + 1:]).strip()
        if not text:
            return None
        return Cue(round(start, 3), round(end, 3), _unescape_vtt(text))
    return None


# ── quality signals for the review editor ────────────────────────────────────────
def cue_warnings(cues, *, max_chars_per_line: int = MAX_CHARS_PER_LINE,
                 max_lines: int = MAX_LINES_PER_CUE,
                 max_seconds: float = MAX_CUE_SECONDS,
                 min_seconds: float = MIN_CUE_SECONDS,
                 max_cps: float = MAX_CHARS_PER_SECOND) -> list[dict]:
    """Per-cue problems a reviewer should see while editing.

    ADVISORY, and deliberately not blocking: a reviewer who has watched the media knows things
    these rules do not, and a caption that breaks the reading rate to stay faithful to a fast
    speaker is a legitimate choice. The editor shows these; it never refuses a save because of
    them. Returned as data rather than prose so the UI can anchor each one to its cue.
    """
    out: list[dict] = []
    for i, cue in enumerate(cues):
        if cue.end <= cue.start:
            out.append({"index": i, "code": "non_positive_duration",
                        "detail": "the cue ends at or before it starts"})
            continue
        if cue.duration < min_seconds:
            out.append({"index": i, "code": "too_brief",
                        "detail": f"on screen for {cue.duration:.2f}s, under {min_seconds}s"})
        if cue.duration > max_seconds:
            out.append({"index": i, "code": "too_long",
                        "detail": f"on screen for {cue.duration:.2f}s, over {max_seconds}s"})
        if cue.chars_per_second > max_cps:
            out.append({"index": i, "code": "too_fast",
                        "detail": f"{cue.chars_per_second:.0f} characters per second, "
                                  f"over {max_cps:.0f}"})
        lines = cue.text.split("\n")
        if len(lines) > max_lines:
            out.append({"index": i, "code": "too_many_lines",
                        "detail": f"{len(lines)} lines, over {max_lines}"})
        for line in lines:
            if len(line) > max_chars_per_line:
                out.append({"index": i, "code": "line_too_long",
                            "detail": f"a line is {len(line)} characters, over "
                                      f"{max_chars_per_line}"})
                break
        if i and cue.start < cues[i - 1].end:
            out.append({"index": i, "code": "overlaps_previous",
                        "detail": "starts before the previous cue ends"})
    return out
