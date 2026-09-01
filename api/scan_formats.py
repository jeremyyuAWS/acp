"""The document formats Discovery is in scope for — one source of truth, read per call.

WHY THIS MODULE EXISTS. The scannable-format set was written down in three places that had to
agree and had no mechanism forcing them to: `scanner._SCANNABLE_MIME` (the Drive listing filter),
`scanner._SP_SCANNABLE_EXTS` (the SharePoint/Graph walk filter), and
`estate_inventory.SUPPORTED_FORMATS` (the per-file `assessable` capability status the coverage
funnel counts). Drift between the first two and the third is the expensive direction: a format
the connectors stop listing but the inventory still calls `assessable` inflates the
assessment-eligible denominator with files Assess will never receive — the "unsupported must
never read as passed" failure the product model (docs/discovery-assessment-remediation.md) exists
to prevent. All three now derive from `formats()` below.

THE SCOPE, AND HOW TO CHANGE IT. Discovery covers PDF, DOCX, XLSX and PPTX (2026-09-01 scope
decision). HTML was previously in scope and is still fully implemented downstream — the detectors,
fixers and report paths for it are untouched — so it remains available behind an explicit operator
override:

    ACP_SCAN_FORMATS=pdf,docx,xlsx,pptx,html

Read per call, never latched at import, deliberately: `api/worker_main.py`'s own header records a
production incident where a module-level `int(os.environ[...])` read at import time silently won
over an env var set afterwards, and the container ran with zero workers while reporting itself
healthy. A set that governs what a scan can see deserves the same treatment.

GOOGLE-NATIVE TYPES ARE NOT A FIFTH FORMAT. A Google Doc/Sheet/Slides file is exported to
docx/xlsx/pptx and assessed as that format (`scanner.EXPORT_MAP`), so it is in scope exactly when
its export target is — never listed separately. Reading "four file types" as "four MIME types"
would drop native Google documents, which on a Drive estate are routinely the majority of the
real content; that is a much larger scope cut than the decision intended.

NOT the remediation-capability set: which WCAG criteria are fixable per format still lives in
`remediation_capability`. This module answers only "may Discovery list it at all".
"""
from __future__ import annotations

import os

# Format key -> the file extension it is listed and assessed as.
#
# Keys are the vocabulary of ACP_SCAN_FORMATS and of estate_inventory's format buckets; they are
# the same strings `estate_inventory._format_of` returns, so a value here can be compared against
# a classified row without translation.
_EXT_OF: dict[str, tuple[str, ...]] = {
    "pdf":  (".pdf",),
    "docx": (".docx",),
    "xlsx": (".xlsx",),
    "pptx": (".pptx",),
    # Two extensions, one format — which is why this maps to a tuple rather than a single string.
    "html": (".html", ".htm"),
    # Standalone audio and video. ONE key for both because they are one estate bucket and one
    # detector: `estate_inventory._format_of` has always returned "av" for either, and 1.2.1 vs
    # 1.2.2 is decided per FILE (does this container hold a video stream?) rather than per format
    # — splitting the key would put that decision in a table that cannot see inside the file.
    #
    # The list matches estate_inventory._AV_EXT exactly. It has to: that function is what assigns
    # the bucket, so an extension known here and not there classifies as "other" and is never
    # assessed, while one known there and not here reads as assessable and then finds no detector.
    # tests/test_media_assessment.py pins the two together.
    "av": (".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".aac", ".flac",
           ".ogg"),
}

# Uploaded-file MIMEs per format. Google-native MIMEs are NOT here; they resolve through
# scanner.EXPORT_MAP to one of these formats instead (see the module docstring).
#
# TUPLES, matching _EXT_OF above. The four document formats each have exactly one MIME and read
# as a one-tuple, which is verbose for them and correct for "av": a video estate is mp4 and mov
# and webm under half a dozen MIME spellings, and a single-string map could not express that
# without a second, differently-shaped table beside this one.
_MIME_OF: dict[str, tuple[str, ...]] = {
    "pdf":  ("application/pdf",),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
    "html": ("text/html",),
    "av": ("video/mp4", "video/quicktime", "video/x-msvideo", "video/x-matroska", "video/webm",
           "audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/aac", "audio/flac",
           "audio/ogg"),
}

# Every format this codebase has detectors for — the set ACP_SCAN_FORMATS is validated against.
# A format absent from here cannot be switched on by env: naming one that no engine can assess
# would list files Assess is guaranteed to fail on, which is worse than ignoring the typo.
#
# "av" JOINED THIS SET WHEN, AND ONLY WHEN, A DETECTOR EXISTED. The media pipeline
# (api/media.py, api/captions.py) shipped first and registered nothing, deliberately: it could
# draft captions and could not assess anything, so listing media then would have broken the
# invariant this comment states. `formats/media` now registers 1.2.1 and 1.2.2 against a real
# technique, which is what earns the entry.
KNOWN_FORMATS: frozenset[str] = frozenset(_EXT_OF)

# The 2026-09-01 scope decision, UNCHANGED. Ordered widest-value-first only for readable log
# output; every consumer treats it as a set.
#
# "av" is deliberately absent. Being assessable is not the same as being in Discovery's default
# scope: switching video on for every existing deployment would change what every estate's totals
# mean overnight — the eligible denominator, the coverage funnel, the assessed-of-discovered
# ratio — for content nobody has asked us to walk. It is opt-in exactly as html is, and the
# operator says so:
#
#     ACP_SCAN_FORMATS=pdf,docx,xlsx,pptx,av
DEFAULT_FORMATS: tuple[str, ...] = ("pdf", "docx", "xlsx", "pptx")

_ENV_VAR = "ACP_SCAN_FORMATS"


def formats() -> frozenset[str]:
    """The format keys Discovery may list, from ACP_SCAN_FORMATS or the default four.

    Unknown names are DROPPED rather than raising, and a value that leaves nothing valid falls
    back to the default set. A malformed env var must not be able to make a deployment discover
    zero files: an empty scope produces empty scans that look exactly like an empty estate, which
    is the failure mode nobody investigates. Comma-separated, case- and space-insensitive, and a
    leading dot is tolerated so `.pdf,.docx` means what it obviously means.
    """
    raw = os.environ.get(_ENV_VAR, "")
    if not raw.strip():
        return frozenset(DEFAULT_FORMATS)
    picked = {tok.strip().lower().lstrip(".") for tok in raw.split(",")}
    valid = picked & KNOWN_FORMATS
    return frozenset(valid) if valid else frozenset(DEFAULT_FORMATS)


def extensions() -> frozenset[str]:
    """Lower-case file extensions in scope, dot-prefixed (`.pdf`). The SharePoint/Graph walk
    filters on these — Graph gives a filename, so extension is the only signal available there."""
    return frozenset(ext for f in formats() for ext in _EXT_OF[f])


def upload_mimes() -> frozenset[str]:
    """MIME types of UPLOADED files in scope — no Google-native types (see module docstring)."""
    return frozenset(m for f in formats() for m in _MIME_OF[f])


def google_native_in_scope(export_map: dict[str, tuple[str, str]]) -> frozenset[str]:
    """The Google-native MIMEs in scope, given scanner.EXPORT_MAP's {native_mime: (mime, ext)}.

    A native type is in scope exactly when the format it exports to is — a Google Doc rides on
    docx. `export_map` is passed in rather than imported so this module stays free of the scanner
    (which pulls in the whole engine); the scanner owns that table and is its only caller.
    """
    exts = extensions()
    return frozenset(native for native, (_mime, ext) in export_map.items() if ext.lower() in exts)


def is_supported_format(fmt: str | None) -> bool:
    """True when an estate_inventory format bucket ('docx', 'image', 'other', …) is in scope.

    The one predicate behind the `assessable` capability status, so a format dropped from the
    scan scope stops being counted as assessment-eligible in the same breath.
    """
    return bool(fmt) and fmt in formats()


def describe() -> str:
    """Stable, sorted, human-readable scope for a startup log line or a diagnostic."""
    return ",".join(sorted(formats()))
