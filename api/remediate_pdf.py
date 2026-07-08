"""Server-side PDF remediation (ADR 0005 step 4).

Two-stage, both deterministic (no LLM):
  1. pikepdf — Root-level structural fixes from the vendored DigitalA11y engine:
     document language (`/Lang`) and display-document-title (ViewerPreferences).
  2. pypdf — document metadata (docinfo): a filename-derived /Title (WCAG 2.4.2) when
     one is missing, plus the provenance stamp. Metadata is written with pypdf rather
     than pikepdf because pikepdf's docinfo writes persist nondeterministically once
     libxml2 is loaded in the same long-lived worker process (office/HTML remediation
     use lxml); pypdf is pure-Python and reliable, and `clone_from` preserves the
     stage-1 catalog fixes (/Lang, ViewerPreferences).

The remaining LLM-driven PDF fixers (alt-text, bookmark structure) need content
judgement and route to human review — the same 'deferred' contract as the HTML
remediator (api/remediate.py).
"""
from __future__ import annotations
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace


def remediate_pdf(path: Path, *, lang: str = "en"):
    """Apply deterministic PDF accessibility fixes to a copy of the file.

    Returns (fixed_path, applied, skipped):
      fixed_path — Path to the remediated PDF, or None if nothing was applied.
      applied/skipped — human-readable change descriptions.
    """
    from scanner import WP  # vendored worker-python root (engine + fixers)
    sys.path.insert(0, str(WP))
    import pikepdf
    from remediation.fixers.pdf.language_fixer import PdfLanguageFixer
    from remediation.fixers.pdf.display_title_fixer import PdfDisplayTitleFixer
    from remediation.base_fixer import FixBehavior, FixStatus

    # Read the ORIGINAL metadata up front with pypdf — reliably, from the source. pikepdf's
    # docinfo reads AND writes are unstable once libxml2 is loaded in a long-lived worker,
    # so we never trust it for metadata (title, provenance).
    from pypdf import PdfReader
    orig_meta: dict[str, str] = {}
    try:
        om = PdfReader(str(path)).metadata
        if om:
            orig_meta = {k: str(v) for k, v in om.items() if v is not None}
    except Exception:
        orig_meta = {}
    existing_title = str(orig_meta.get("/Title") or "").strip()

    try:
        pdf = pikepdf.open(str(path))
    except Exception as e:
        return None, [], [f"could not open PDF: {type(e).__name__}"]

    behavior = FixBehavior(allow_llm=False, allow_placeholders=True)
    applied: list[str] = []
    skipped: list[str] = []
    mid_path = path.with_name(f".mid-{path.name}")

    # ── Stage 1: pikepdf — Root-level structural fixes ──
    try:
        for fixer, meta in ((PdfLanguageFixer(), {"language": lang}),
                            (PdfDisplayTitleFixer(), {})):
            # The deterministic fixers read only issue.issue_id, so a light stub
            # avoids constructing a full A11yIssue (and its enum imports).
            issue = SimpleNamespace(issue_id=uuid.uuid4())
            res = fixer.apply(pdf, issue, meta, behavior)
            (applied if res.status == FixStatus.FIXED else skipped).append(res.description)
        pdf.save(str(mid_path))
    finally:
        pdf.close()

    # Deterministic document title (WCAG 2.4.2) — filename-derived when none is set.
    new_title = None
    if not existing_title:
        new_title = path.stem.replace("-", " ").replace("_", " ").strip() or "Document"
        applied.append(f"Set document title to '{new_title}' · 2.4.2")

    if not applied:
        _unlink(mid_path)
        return None, [], skipped

    # ── Stage 2: pypdf — reliable docinfo metadata (title + provenance stamp) ──
    from datetime import datetime, timezone

    from pypdf import PdfWriter

    from remediate_office import TOOL, VERSION
    # Preserve the document's ORIGINAL metadata (clone_from copies pages/catalog but not
    # docinfo — and pikepdf's mid save can drop it), then layer the provenance stamp on top.
    now = datetime.now(timezone.utc)
    metadata = {
        **orig_meta,
        "/Producer": f"{TOOL} {VERSION}",
        "/RemediatedBy": TOOL,
        "/RemediationDate": now.strftime("%Y-%m-%d"),
        "/ModDate": "D:" + now.strftime("%Y%m%d%H%M%S") + "Z",
        "/WCAGTarget": "WCAG 2.1 AA",
        "/FixesApplied": "; ".join(applied)[:255],
    }
    # Carry the title through: the new filename-derived one when missing, else the existing
    # one (which clone_from would otherwise drop). A real title is never overwritten.
    title_to_set = new_title or existing_title
    if title_to_set:
        metadata["/Title"] = title_to_set

    out_path = path.with_name(f"remediated-{path.name}")
    try:
        writer = PdfWriter(clone_from=str(mid_path))   # preserves /Lang + ViewerPreferences
        writer.add_metadata(metadata)
        with open(out_path, "wb") as f:
            writer.write(f)
    except Exception as e:
        _unlink(mid_path)
        return None, [], skipped + [f"could not write PDF metadata: {type(e).__name__}"]
    _unlink(mid_path)
    return out_path, applied, skipped


def _unlink(p: Path) -> None:
    try:
        p.unlink()
    except Exception:
        pass
