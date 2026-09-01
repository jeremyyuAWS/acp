"""WebVTT / SRT / transcript output, and the cue segmentation that feeds them.

ENTIRELY PURE — no media file, no binary, no model. That is the point of the split in
`api/captions.py`: transcription accuracy belongs to whatever ASR produced the segments and this
repo cannot assert it, but cue timing, line breaking, escaping and file syntax are ours and are
exactly testable. Everything here is deterministic and runs in milliseconds with no engine.

WHAT THESE PROTECT. A caption file is consumed by players this project will never see, and a
syntax error does not degrade gracefully — a malformed timestamp makes a track silently fail to
load, which presents to a user as "this video has no captions" and to an auditor as a fixed
criterion. So the cases below are weighted towards the boundaries where that happens: the
hour rollover, millisecond rounding, the VTT/SRT separator difference, and markup characters in
speech.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

from captions import (  # noqa: E402
    MAX_CHARS_PER_LINE,
    MAX_CHARS_PER_SECOND,
    MAX_CUE_SECONDS,
    Cue,
    cue_warnings,
    parse_cues,
    segment_cues,
    srt_timestamp,
    to_srt,
    to_transcript,
    to_webvtt,
    vtt_timestamp,
)


# ── timestamps ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("seconds,vtt,srt", [
    (0,           "00:00:00.000", "00:00:00,000"),
    (1.5,         "00:00:01.500", "00:00:01,500"),
    (61.25,       "00:01:01.250", "00:01:01,250"),
    (3600,        "01:00:00.000", "01:00:00,000"),   # the hour rollover
    (3661.007,    "01:01:01.007", "01:01:01,007"),   # ms zero-padding
    (7322.999,    "02:02:02.999", "02:02:02,999"),
])
def test_timestamps_render_in_both_dialects(seconds, vtt, srt):
    """The one difference between VTT and SRT timestamps is the millisecond separator, and it is
    the detail most often got wrong — a VTT with a comma does not parse, and the failure is a
    track that never loads rather than an error anyone sees."""
    assert vtt_timestamp(seconds) == vtt
    assert srt_timestamp(seconds) == srt


def test_a_negative_timestamp_clamps_rather_than_rendering_garbage():
    """Arithmetic on cue offsets can go below zero. `-00:00:01.000` is not a timestamp any
    parser accepts, so it clamps — a caption one second early beats a file that will not load."""
    assert vtt_timestamp(-5) == "00:00:00.000"


def test_milliseconds_round_rather_than_truncate():
    """0.9999s is 1.000, not 0.999. Truncation accumulates: a file of truncated cues drifts
    steadily earlier against the audio."""
    assert vtt_timestamp(0.9999) == "00:00:01.000"


# ── escaping ─────────────────────────────────────────────────────────────────────
def test_webvtt_escapes_the_characters_that_carry_markup_meaning():
    """`&`, `<` and `>` are markup inside a VTT cue payload. Left raw, "R&D <5%" either renders
    wrong or swallows the rest of the cue — real speech contains all three."""
    out = to_webvtt([Cue(0, 2, "R&D spend <5% & falling")])
    assert "R&amp;D spend &lt;5% &amp; falling" in out
    assert "<5%" not in out


def test_srt_does_not_escape_because_it_is_not_markup():
    """SRT payloads are plain text; escaping them would put literal `&amp;` on screen. The two
    formats genuinely differ here and sharing one writer would corrupt one of them."""
    assert "R&D <5%" in to_srt([Cue(0, 2, "R&D <5%")])


def test_the_escape_round_trips():
    """The editor reads a file back to load a reviewer's edits, so escape and unescape must be
    inverses. If they are not, every save/load cycle mangles ampersands a little more."""
    original = "R&D <5% & rising"
    assert parse_cues(to_webvtt([Cue(0, 2, original)]))[0].text == original


# ── file shape ───────────────────────────────────────────────────────────────────
def test_webvtt_has_the_required_header_and_cue_structure():
    out = to_webvtt([Cue(0, 1.5, "One"), Cue(2, 3.5, "Two")], language="en")
    lines = out.splitlines()
    assert lines[0] == "WEBVTT", "a WebVTT file that does not start with WEBVTT will not load"
    assert "Language: en" in lines[:3]
    assert "00:00:00.000 --> 00:00:01.500" in out
    assert out.endswith("\n"), "a trailing newline keeps the last cue parseable"


def test_a_note_block_records_provenance_in_the_file_itself():
    """A caption file travels separately from this system. Whoever opens it next has no other way
    to learn it was machine-drafted and human-approved, so it is written into the file."""
    out = to_webvtt([Cue(0, 1, "Hi")], note="Drafted by ACP, approved by a reviewer.")
    assert "NOTE" in out
    assert "approved by a reviewer" in out
    assert out.index("NOTE") < out.index("00:00:00.000"), "NOTE must precede the cues"


def test_srt_indexes_from_one():
    """SRT indices are 1-based and some players reject a 0. Off-by-one here is invisible in a
    diff and fatal in VLC."""
    out = to_srt([Cue(0, 1, "One"), Cue(1.1, 2, "Two")])
    assert out.startswith("1\n")
    assert "\n2\n" in out


def test_empty_input_produces_no_malformed_file():
    """Zero cues is a legitimate result — silent media. It must not produce a file with a
    dangling index or a stray separator."""
    assert to_srt([]) == ""
    assert to_webvtt([]).strip() == "WEBVTT"
    assert to_transcript([]) == ""


# ── segmentation ─────────────────────────────────────────────────────────────────
def test_a_long_asr_segment_is_split_to_a_readable_rate():
    """THE REASON SEGMENTATION EXISTS. An ASR returns segments shaped by pauses, not by what a
    person can read. One 12-second, 300-character segment is a valid ASR result and an unusable
    caption; it must come back as several cues, each within the reading rate."""
    long_text = ("we begin with the quarterly figures and then move on to the regional breakdown "
                 "before considering the outlook for the coming year in some detail")
    cues = segment_cues([{"start": 0.0, "end": 12.0, "text": long_text}])

    assert len(cues) > 1, "a 12-second segment must be split"
    for c in cues:
        assert c.duration <= MAX_CUE_SECONDS + 1e-6, f"{c} stays on screen too long"
        assert c.chars_per_second <= MAX_CHARS_PER_SECOND * 1.35, f"{c} reads too fast"


def test_split_cues_never_outlive_the_segment_they_came_from():
    """Timings are only ever subdivided. A cue that outlived its speech would caption words
    nobody is saying and desynchronise everything after it."""
    cues = segment_cues([{"start": 5.0, "end": 11.0, "text": "word " * 40}])
    assert cues, "the fixture must actually produce cues"
    assert cues[0].start >= 5.0
    assert cues[-1].end <= 11.0 + 1e-6


def test_cues_never_overlap_and_are_ordered():
    """Two cues sharing a timestamp make a player choose an order neither file specifies."""
    cues = segment_cues([{"start": 0.0, "end": 4.0, "text": "first segment here"},
                         {"start": 3.9, "end": 8.0, "text": "second segment overlapping"}])
    for a, b in zip(cues, cues[1:]):
        assert b.start >= a.end, f"{b} starts before {a} ends"


def test_lines_are_wrapped_and_never_broken_mid_word():
    """A hyphenated split invents a word the speaker did not say."""
    cues = segment_cues([{"start": 0, "end": 6, "text": "supercalifragilistic expialidocious "
                                                        "and several other long words follow"}])
    for c in cues:
        for line in c.text.split("\n"):
            assert "-\n" not in c.text
            assert len(line.split()) >= 1
    joined = " ".join(c.text.replace("\n", " ") for c in cues)
    assert "supercalifragilistic" in joined, "no word may be chopped"


def test_a_single_over_long_word_is_left_intact_rather_than_broken():
    """An over-long line is legible; a chopped word is not. This is the deliberate exception to
    the line-length rule."""
    word = "A" * (MAX_CHARS_PER_LINE + 20)
    cues = segment_cues([{"start": 0, "end": 3, "text": word}])
    assert word in cues[0].text


def test_blank_and_inverted_segments_are_dropped_not_rendered():
    """ASR output carries empty segments and, rarely, an end before its start. Neither should
    reach a file: an empty cue renders as a blank flash on screen."""
    cues = segment_cues([{"start": 0, "end": 2, "text": "   "},
                         {"start": 5, "end": 4, "text": "inverted"},
                         {"start": 6, "end": 8, "text": "good"}])
    assert [c.text for c in cues] == ["good"]


def test_asr_whitespace_is_normalised():
    """Whisper-family output routinely has a leading space and internal newlines. Rendered
    literally, the leading space indents every caption."""
    cues = segment_cues([{"start": 0, "end": 2, "text": "  hello\n  there  "}])
    assert cues[0].text == "hello there"


def test_segments_may_be_objects_not_only_dicts():
    """The ASR adapter yields objects with .start/.end/.text; tests and the editor pass dicts.
    Supporting both keeps a conversion step out of the pipeline."""
    class Seg:
        start, end, text = 0.0, 2.0, "from an object"
    assert segment_cues([Seg()])[0].text == "from an object"


# ── parsing ──────────────────────────────────────────────────────────────────────
def test_round_trip_through_webvtt_and_srt():
    """The editor saves what a reviewer approved and loads it again. Timings must survive."""
    cues = [Cue(0, 1.5, "First line"), Cue(2.25, 4.0, "Second\nwith two lines")]
    for text in (to_webvtt(cues), to_srt(cues)):
        back = parse_cues(text)
        assert [(c.start, c.end) for c in back] == [(0, 1.5), (2.25, 4.0)]
        assert back[1].text == "Second\nwith two lines"


def test_the_parser_tolerates_a_hand_edited_file():
    """A reviewer may open the .vtt in a text editor. Missing indices, CRLF line endings and a
    comma separator in a VTT are all things a human produces and a strict parser rejects."""
    hand = ("WEBVTT\r\n\r\n00:00:00,000 --> 00:00:02,000\r\nHand edited\r\n\r\n"
            "00:00:03.000 --> 00:00:04.000\r\nSecond\r\n")
    cues = parse_cues(hand)
    assert [c.text for c in cues] == ["Hand edited", "Second"]


def test_a_cue_with_no_text_is_not_returned():
    """A timestamp line with an empty payload is not a caption."""
    assert parse_cues("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n\n") == []


# ── advisory warnings ────────────────────────────────────────────────────────────
def test_warnings_name_the_real_problems_and_their_cue():
    """The editor anchors each warning to a cue, so they are returned as data with an index —
    not as prose a UI would have to parse back apart."""
    cues = [Cue(0, 0.3, "Too brief for anyone to read"),
            Cue(1, 12, "On screen far too long"),
            Cue(13, 13.5, "X" * 90)]
    codes = {(w["index"], w["code"]) for w in cue_warnings(cues)}
    assert (0, "too_brief") in codes
    assert (1, "too_long") in codes
    assert (2, "too_fast") in codes
    assert (2, "line_too_long") in codes


def test_a_well_formed_cue_raises_no_warning():
    """The control. Without it, a `cue_warnings` that flagged everything would satisfy the
    assertions above."""
    assert cue_warnings([Cue(0, 3.0, "A comfortable line of caption text.")]) == []


def test_warnings_are_advisory_only_and_never_block_writing():
    """A reviewer who has watched the media knows things these rules do not — captioning a fast
    speaker faithfully may break the reading rate legitimately. The writers must not consult the
    warnings at all."""
    bad = [Cue(0, 0.1, "X" * 200)]
    assert cue_warnings(bad), "the fixture must actually be warned about"
    assert "X" * 200 in to_webvtt(bad), "the file is still written"
    assert "X" * 200 in to_srt(bad)


# ── transcript ───────────────────────────────────────────────────────────────────
def test_transcript_reads_as_prose_not_as_caption_fragments():
    """1.2.1 asks for a transcript, which a reader consumes without a player. Caption line
    breaks are a display artefact and must not survive into it."""
    out = to_transcript([Cue(0, 2, "First part\nsecond part")], timestamps=False)
    assert out.strip() == "First part second part"


def test_transcript_timestamps_are_optional_and_on_by_default():
    with_stamps = to_transcript([Cue(65, 67, "Later")])
    assert "[00:01:05.000]" in with_stamps
    assert "[" not in to_transcript([Cue(65, 67, "Later")], timestamps=False)
