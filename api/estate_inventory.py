"""Estate inventory — classify EVERY discovered file, not only the ones ACP can assess.

Discovery lists the whole drive (`scanner._search_drive` asks Drive for `trashed=false`, no MIME
filter) and then keeps only the scannable formats for the scan. That is correct for *scanning* —
but it means the file count the UI shows is the assessable subset, and a customer cannot see their
real content estate or understand what ACP does not yet cover. "Unsupported" then reads as "passed"
by omission, which is the one reading that must never happen.

This module is the other half: given the raw Drive listing, it classifies every file into a
capability status and produces an estate summary. Assessment and remediation still run only on the
scannable formats — this changes what we REPORT, never what we scan.

Three denominators, never one percentage (ADR pending):
  * DISCOVERED         — every file, any format (this module inventories all of it)
  * ASSESSMENT ELIGIBLE — files with at least one applicable accessibility test
  * REMEDIATION ELIGIBLE — files ACP can deterministically or guided-remediate

Deliberately standalone (no `scanner` import) so it stays the single authority on the taxonomy and
can be unit-tested without a Drive. `scanner` imports THIS, never the reverse.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

# ── Capability status taxonomy ────────────────────────────────────────────────────────────────
# A per-file answer to "what can ACP do with this?", visible for every discovered file. Only
# ASSESSABLE files enter the assessment/remediation lanes; the rest are inventoried with metadata.
ASSESSABLE = "assessable"          # a supported format with at least one applicable WCAG test
METADATA_ONLY = "metadata_only"    # inventoried (image / audio / video) but no accessibility test
UNSUPPORTED = "unsupported"        # a format ACP does not parse for accessibility at all
EXCLUDED = "excluded"              # ACP's own output, or policy-excluded — not the user's content

STATUSES = (ASSESSABLE, METADATA_ONLY, UNSUPPORTED, EXCLUDED)

# ── Format buckets ──────────────────────────────────────────────────────────────────────────
# Google Workspace native types export to an Office format, so they assess as that format.
_GOOGLE_NATIVE = {
    "application/vnd.google-apps.document": "docx",
    "application/vnd.google-apps.spreadsheet": "xlsx",
    "application/vnd.google-apps.presentation": "pptx",
}
_OFFICE_PDF_HTML_MIME = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/html": "html",
}
_SUPPORTED_EXT = {
    ".docx": "docx", ".pdf": "pdf", ".pptx": "pptx", ".xlsx": "xlsx",
    ".html": "html", ".htm": "html",
}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".svg", ".heic", ".ico"}
_AV_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

FOLDER_MIME = "application/vnd.google-apps.folder"

# The formats that carry at least one applicable accessibility test. The single source of truth for
# WHICH criteria per format lives in remediation_capability; this is only the assessable-format set,
# which changes far less often. Kept here (not imported) so the taxonomy has no heavy dependency.
SUPPORTED_FORMATS = ("docx", "pdf", "pptx", "xlsx", "html")


def _format_of(name: str, mime: str) -> str:
    """The estate format bucket for a Drive file: a supported doc format, or 'image'/'av'/'other'.

    MIME wins over extension (a Google-native Doc has no useful name suffix, and a mislabeled
    upload is rare), then the extension fills in for uploads Drive typed only as octet-stream.
    """
    if mime in _GOOGLE_NATIVE:
        return _GOOGLE_NATIVE[mime]
    if mime in _OFFICE_PDF_HTML_MIME:
        return _OFFICE_PDF_HTML_MIME[mime]
    ext = Path(name or "").suffix.lower()
    if ext in _SUPPORTED_EXT:
        return _SUPPORTED_EXT[ext]
    if mime.startswith("image/") or ext in _IMAGE_EXT:
        return "image"
    if mime.startswith(("video/", "audio/")) or ext in _AV_EXT:
        return "av"
    return "other"


def _status_of(fmt: str) -> str:
    """The capability status for an estate format bucket."""
    if fmt in SUPPORTED_FORMATS:
        return ASSESSABLE
    if fmt in ("image", "av"):
        return METADATA_ONLY
    return UNSUPPORTED


def classify(f: dict) -> dict:
    """Classify one raw Drive file dict into its estate row.

    Input is a Drive file object (id, name, mimeType, modifiedTime, …). Returns a compact row:
    {id, name, ext, format, status}. An ACP-generated file, if flagged by the caller via the
    `_excluded` key, is reported EXCLUDED (its content is ACP's own, not the estate).
    """
    name = f.get("name", "") or ""
    mime = f.get("mimeType", "") or ""
    fmt = _format_of(name, mime)
    status = EXCLUDED if f.get("_excluded") else _status_of(fmt)
    return {
        "id": f.get("id"),
        "name": name,
        "ext": Path(name).suffix.lower(),
        "format": fmt,
        "status": status,
    }


# ── Age bands ─────────────────────────────────────────────────────────────────────────────────
# How long since each file was touched, aggregated over the WHOLE listing.
#
# `modified` already existed — but only on `_sample_meta`, which is capped at `sample_per_status`
# rows per status. A distribution built from that cap would be a histogram of at most 200 files per
# bucket presented as the estate, and it would look right: plausible shape, confident bars, wrong
# denominator. That is the failure this module's own header exists to prevent ("unsupported reads
# as passed by omission"), in a new place. So the bands are counted here, over every row.
#
# Ages are the retention question, not the accessibility one: a file nobody has opened in five
# years is a DELETE decision, which is what `DispositionRules` and `retentionOf` already act on.
AGE_BANDS = (
    ("lt_1y", "Under 1 year", 365),
    ("y1_3", "1–3 years", 3 * 365),
    ("y3_5", "3–5 years", 5 * 365),
    ("gt_5y", "Over 5 years", None),      # the open-ended tail
)
AGE_UNKNOWN = "unknown"                   # no usable timestamp — stated, never folded into a band


def _parse_iso(value):
    """A Drive/Graph RFC-3339 timestamp, or None. Never raises, never guesses.

    Graph returns `2026-08-19T10:00:00Z`; Drive returns the same shape. `fromisoformat` handles the
    offset forms and, from 3.11, the trailing Z — the replace keeps it working if that changes.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def age_band(modified, now=None) -> str:
    """Which band a file's last-modified timestamp falls in, or AGE_UNKNOWN.

    `now` is injectable, and every caller in this module passes one. A distribution that reads the
    wall clock is a distribution whose tests pass until they do not — the exact shape that broke a
    frontend date assertion in this repo the day after it was written.

    A timestamp in the FUTURE (clock skew on the source, or a mis-set modified date) bands as
    "under 1 year" rather than as unknown: it is a real file with a real, if implausible, date, and
    the youngest band is the honest home for it.
    """
    dt = _parse_iso(modified)
    if dt is None:
        return AGE_UNKNOWN
    now = now or datetime.now(timezone.utc)
    days = (now - dt).days
    for key, _label, upper in AGE_BANDS:
        if upper is None or days < upper:
            return key
    return AGE_BANDS[-1][0]


def _sample_meta(f: dict) -> dict:
    """Triage metadata for a drill-down sample row, pulled from the raw Drive file. Only the capped
    sample carries this (never all 30k) — size to sort biggest-first, owner to group, shared to flag
    the externally-visible files that matter most for a PHI estate. Missing/unparseable → None/False,
    never a wrong value."""
    owners = f.get("owners") or []
    owner = (owners[0].get("displayName") or owners[0].get("emailAddress")) if owners else None
    size = f.get("size")
    try:
        size = int(size) if size is not None else None
    except (TypeError, ValueError):
        size = None
    return {"size": size, "owner": owner, "shared": bool(f.get("shared")),
            "modified": f.get("modifiedTime")}


def summarize(files: list[dict], *, truncated: bool = False, sample_per_status: int = 200,
              now: datetime | None = None) -> dict:
    """The whole-estate summary the dashboard funnel and composition read.

    `files` is the raw Drive listing (every type, folders already removed by the caller — a folder
    is not content). Returns discovered totals plus by-format and by-status breakdowns, and the
    assessment-eligible count — the honest split between "found" and "can act on".

    `samples` carries, per capability status, up to `sample_per_status` of the actual files in that
    bucket ({id, name, format} + triage metadata {size, owner, shared, modified}) so the dashboard can
    drill from an aggregate ("unsupported: 4,231") into the files behind it, sorted biggest-first or by
    owner. It is a CAP, not the whole list: `by_status[status]` is the true total,
    so a consumer renders "showing N of <total>" and never mistakes the sample for the estate. The
    cap bounds the report size at 30k-file scale (4 statuses x cap rows), and the per-file paginated
    export is a separate follow-up.

    `truncated` is True when the listing hit its cap before reaching the end of the estate: the
    counts are then a FLOOR, not the whole estate, and a consumer must say so rather than present
    the number as complete. Silent truncation is the one failure this inventory exists to prevent.
    """
    by_format: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_age: dict[str, int] = {}
    # One `now` for the whole listing. Reading the clock per file would let a long scan straddle a
    # band boundary and produce counts that do not reconcile with each other.
    now = now or datetime.now(timezone.utc)
    samples: dict[str, list[dict]] = {}
    pairs = [(classify(f), f) for f in files if f.get("mimeType") != FOLDER_MIME]
    rows = [r for r, _ in pairs]
    for r, f in pairs:
        by_format[r["format"]] = by_format.get(r["format"], 0) + 1
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        # Over every row, not over the capped sample — see the AGE_BANDS comment.
        band = age_band(f.get("modifiedTime"), now)
        by_age[band] = by_age.get(band, 0) + 1
        bucket = samples.setdefault(r["status"], [])
        if len(bucket) < sample_per_status:
            bucket.append({"id": r["id"], "name": r["name"], "format": r["format"], **_sample_meta(f)})
    return {
        "discovered": len(rows),
        "assessment_eligible": by_status.get(ASSESSABLE, 0),
        "by_format": by_format,
        "by_status": by_status,
        # Bands sum to `discovered` by construction — every row lands in exactly one, including
        # AGE_UNKNOWN. A consumer can therefore reconcile them, which is the point of counting
        # unknown rather than dropping it.
        "by_age": by_age,
        "samples": samples,
        "sample_cap": sample_per_status,
        "truncated": bool(truncated),
    }


def funnel_facts(summary: dict | None) -> dict | None:
    """The estate-coverage funnel for the conformance report's scope section, derived from a stored
    `summarize()` output.

    The report's scope section narrows the assertion by CRITERION ("no check for 2.4.3 on a PDF")
    and by unread file-type ("47 documents of other types were not opened"). Neither of those
    states the whole-estate shape: of everything discovered, how much is even an assessable format.
    A conformance report that omits it lets an auditor read the scanned subset as the estate.

    Returns the three honest denominators as separate counts — never one percentage (the taxonomy's
    founding rule): `discovered` (every file), `assessable` (formats with at least one applicable
    test), and the `not_assessable` remainder broken out by why (image/audio/video that has no
    accessibility test, unsupported types, ACP-excluded). `truncated` carries through so the report
    can mark the counts a floor rather than the whole estate.

    Returns None when there is no inventory to report (a local scan, or one predating the field), so
    the report simply omits the funnel rather than printing zeros.
    """
    if not isinstance(summary, dict) or not summary.get("discovered"):
        return None
    by_status = summary.get("by_status") or {}
    discovered = int(summary.get("discovered") or 0)
    assessable = int(summary.get("assessment_eligible", by_status.get(ASSESSABLE, 0)) or 0)
    return {
        "discovered": discovered,
        "assessable": assessable,
        "metadata_only": int(by_status.get(METADATA_ONLY, 0)),
        "unsupported": int(by_status.get(UNSUPPORTED, 0)),
        "excluded": int(by_status.get(EXCLUDED, 0)),
        # Counted, not subtracted from a possibly-stale assessable: the remainder is whatever of the
        # discovered estate is not an assessable format, and can never read negative.
        "not_assessable": max(0, discovered - assessable),
        "truncated": bool(summary.get("truncated")),
    }
