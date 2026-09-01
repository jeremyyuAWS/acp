"""Standalone audio/video — capability declarations and (rule × format) registrations.

THE DIRECTORY NAME IS THE FORMAT KEY, and `av` is not an abbreviation chosen for brevity. It is
the string `estate_inventory._format_of` has always returned for these files, and
`api/scan_formats`'s header states that its keys are that same vocabulary "so a value here can be
compared against a classified row without translation". Honouring it turned what looked like a
cross-module change into one table entry: `_status_of` already asks
`scan_formats.is_supported_format(fmt)` before falling back to METADATA_ONLY, so media becomes
assessable with no edit to `estate_inventory` at all.

This package was first written as `formats/media/`, which read better and was wrong.
`scripts/gen_rules_index.py` walks `api/formats/<fmt>/detectors/` and takes the format from the
path — "the directory IS the declaration", as it puts it. Under the nicer name every rule in here
was indexed against a format called "media" that exists in no capability table, no registry key
and no estate bucket. Nothing failed; the rules/ index simply documented them under a format
nobody could look up.

WHY BOTH PAIRS REQUIRE AUDIO_TRACK. 1.2.1 asks for a transcript of prerecorded audio; 1.2.2 asks
for captions synchronised with prerecorded video that HAS audio. Neither has anything to say about
a silent screen recording — that file's obligation is 1.2.3, which nothing here can establish. The
capability requirement is what makes those files report "this document does not expose an audio
track" rather than being handed a finding whose remedy does not exist.

NOT IN RULE_FORMATS, and that is the migration pattern rather than an omission. A pair registered
below FULL coverage may not also sit in the legacy pass/fail table — `tests/test_rule_registry.py`
asserts exactly that, because two tables describing one cell differently is the drift this whole
layer replaced. 1.2.1/1.2.2 keep `frozenset({"html"})` there for the in-page `<video>` case, which
is a different technique on a different substrate and is untouched by this package.
"""
from __future__ import annotations

from assessment import Confidence, Coverage
from capabilities import Capability
from rule_registry import register

from formats.av.detectors import captions

# The reason string both registrations share: the technique's ceiling, stated as what it does not
# reach rather than as a hedge. It is what a reviewer sees explaining why a clean scan is REVIEW.
_PARTIAL_REASON = (
    "presence only: this reads whether a caption track is in the container and whether a caption "
    "or transcript file sits beside it. It never reads the text, so it cannot judge accuracy, "
    "synchronisation or language, and an auto-generated track in the wrong language would clear "
    "it. On a connector scan the file is assessed alone in a temporary directory, so a sidecar "
    "that exists in the estate is not visible — a served file can still be flagged, which is why "
    "the finding routes to a person"
)

# ── 1.2.2 Captions (Prerecorded) ──────────────────────────────────────────────────────────────
# PARTIAL, not FULL, and not HEURISTIC. Not FULL because of everything in _PARTIAL_REASON, and
# because 1.2.2's media-alternative-for-text exception cannot be seen from inside the file. Not
# HEURISTIC because nothing here is a proxy signal that merely correlates: a caption stream is
# either in the container or it is not, and that is read from the container's own stream table.
# HIGH confidence about exactly that fact, which is the distinction between the two axes.
register(
    rule="1.2.2",
    fmt="av",
    detector=captions.detect,
    requires={Capability.MEDIA_STREAMS, Capability.AUDIO_TRACK},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=_PARTIAL_REASON,
)

# ── 1.2.1 Audio-only and Video-only (Prerecorded) ─────────────────────────────────────────────
# The audio-only half of the criterion only. 1.2.1 also covers VIDEO-only content — a silent
# animation needs a text or audio alternative — and this detector deliberately says nothing about
# that case, for the same reason 1.2.3 is unregistered: distinguishing a silent video that carries
# information from one that does not requires looking at the picture.
register(
    rule="1.2.1",
    fmt="av",
    detector=captions.detect,
    requires={Capability.MEDIA_STREAMS, Capability.AUDIO_TRACK},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=_PARTIAL_REASON + "; the video-only half of 1.2.1 (a silent moving image that carries "
                             "information) is not covered — establishing that needs the picture",
)
