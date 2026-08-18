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


def summarize(files: list[dict], *, truncated: bool = False, sample_per_status: int = 200) -> dict:
    """The whole-estate summary the dashboard funnel and composition read.

    `files` is the raw Drive listing (every type, folders already removed by the caller — a folder
    is not content). Returns discovered totals plus by-format and by-status breakdowns, and the
    assessment-eligible count — the honest split between "found" and "can act on".

    `samples` carries, per capability status, up to `sample_per_status` of the actual files in that
    bucket ({id, name, format}) so the dashboard can drill from an aggregate ("unsupported: 4,231")
    into the files behind it. It is a CAP, not the whole list: `by_status[status]` is the true total,
    so a consumer renders "showing N of <total>" and never mistakes the sample for the estate. The
    cap bounds the report size at 30k-file scale (4 statuses x cap rows), and the per-file paginated
    export is a separate follow-up.

    `truncated` is True when the listing hit its cap before reaching the end of the estate: the
    counts are then a FLOOR, not the whole estate, and a consumer must say so rather than present
    the number as complete. Silent truncation is the one failure this inventory exists to prevent.
    """
    by_format: dict[str, int] = {}
    by_status: dict[str, int] = {}
    samples: dict[str, list[dict]] = {}
    rows = [classify(f) for f in files if f.get("mimeType") != FOLDER_MIME]
    for r in rows:
        by_format[r["format"]] = by_format.get(r["format"], 0) + 1
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        bucket = samples.setdefault(r["status"], [])
        if len(bucket) < sample_per_status:
            bucket.append({"id": r["id"], "name": r["name"], "format": r["format"]})
    return {
        "discovered": len(rows),
        "assessment_eligible": by_status.get(ASSESSABLE, 0),
        "by_format": by_format,
        "by_status": by_status,
        "samples": samples,
        "sample_cap": sample_per_status,
        "truncated": bool(truncated),
    }
