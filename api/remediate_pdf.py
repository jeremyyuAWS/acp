"""Server-side PDF remediation (ADR 0005 step 4).

Two-stage:
  1. pikepdf — Root-level structural fixes from the vendored DigitalA11y engine:
     document language (`/Lang`) and display-document-title (ViewerPreferences); plus
     genuine image alt text (WCAG 1.1.1) — every tagged /Figure struct element that
     lacks /Alt gets a description of its page from the local vision (llava-class)
     model, written as /Alt (exactly what the pdf.missing-alt-text analyser reads).
  2. pypdf — document metadata (docinfo): a filename-derived /Title (WCAG 2.4.2) when
     one is missing, plus the provenance stamp. Metadata is written with pypdf rather
     than pikepdf because pikepdf's docinfo writes persist nondeterministically once
     libxml2 is loaded in the same long-lived worker process (office/HTML remediation
     use lxml); pypdf is pure-Python and reliable, and `clone_from` preserves the
     stage-1 catalog fixes (/Lang, ViewerPreferences, and the /Alt attributes).

Alt text only applies to TAGGED PDFs with figure struct elements. Untagged PDFs (no
StructTreeRoot) are a separate structural-tagging finding and still route to human
review, as does any figure the vision model can't caption (AI off / unavailable).
"""
from __future__ import annotations
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

# Bound worst-case latency: vision inference is slow on CPU, so cap figures captioned
# per document; the rest defer to review (the residual re-scan routes them to HITL).
_VISION_MAX_FIGURES = 25
# Render at 150 DPI — enough detail for vision without excessive cost (mirrors the
# vendored PdfAltTextFixer).
_RENDER_SCALE = 150 / 72


def _propose_reading_order(pdf, source_path: str, *, ai_enabled: bool, scan_id, file,
                           proposals) -> None:
    """WCAG 1.3.2 — for an UNTAGGED (scanned/flat) PDF, vision proposes the page reading
    order for a human to confirm. Never auto-applied (a machine can't be trusted to fix
    reading order on a scan) and bounded to the first page. No-op when tagged, AI off, or no
    vision model — those degrade to the existing review path."""
    if proposals is None or not ai_enabled:
        return
    try:
        if "/StructTreeRoot" in pdf.Root:
            return  # tagged → reading order comes from the structure tree, not a guess
    except Exception:
        return
    try:
        import ai as _ai
        if not _ai.vision_is_available():
            return
    except Exception:
        return
    png = _render_page_png(source_path, 1)
    if not png:
        return
    res = _ai.describe_reading_order(png, filename=file, scan_id=scan_id, file=file)
    if not res:
        return
    import proposals as _prop
    proposals.append(_prop.proposal(
        locator="page 1", before="(untagged PDF — reading order not defined for assistive tech)",
        proposed_value=res["order"],
        rationale="AI read the page layout and proposed a reading order — confirm it matches the intended flow",
        source=f"AI vision model ({res['model']})"))


def remediate_pdf(path: Path, *, lang: str = "en", ai_enabled: bool = True,
                  scan_id: str | None = None, diffs=None, proposals=None):
    """Apply deterministic PDF accessibility fixes to a copy of the file.

    ai_enabled — when True and a vision (llava-class) Ollama model is reachable, tagged
    figures missing /Alt get genuine vision-generated alt text; otherwise they defer to
    human review (AI-off degrades gracefully). scan_id threads the vision calls into that
    scan's Langfuse session.

    Returns (fixed_path, applied, skipped):
      fixed_path — Path to the remediated PDF, or None if nothing was applied.
      applied/skipped — human-readable change descriptions.
    """
    def _rec(rule_id, before, after, note=""):
        if diffs is not None:
            diffs.append({"rule_id": rule_id, "before": before, "after": after, "note": note})
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

    # ── Stage 1: pikepdf — Root-level structural fixes + figure alt text ──
    try:
        for fixer, meta, _diff in (
                (PdfLanguageFixer(), {"language": lang},
                 ("3.1.1", "(no /Lang entry — screen readers guessed the language)",
                  lang, "catalog /Lang set")),
                (PdfDisplayTitleFixer(), {},
                 ("2.4.2", "ViewerPreferences did not request the title bar show the doc title",
                  "DisplayDocTitle = true", "viewer shows the document title, not the file name"))):
            # The deterministic fixers read only issue.issue_id, so a light stub
            # avoids constructing a full A11yIssue (and its enum imports).
            issue = SimpleNamespace(issue_id=uuid.uuid4())
            res = fixer.apply(pdf, issue, meta, behavior)
            if res.status == FixStatus.FIXED:
                applied.append(res.description)
                _rec(*_diff)
            else:
                skipped.append(res.description)
        # Genuine alt text for tagged figures (WCAG 1.1.1) — vision when AI is on and a
        # vision model is reachable; unfixed figures defer to review via the re-scan.
        alt_applied, alt_deferred = _fix_pdf_figure_alt(
            pdf, str(path), ai_enabled=ai_enabled, scan_id=scan_id, file=path.name)
        applied.extend(alt_applied)
        if alt_deferred:
            skipped.append(f"{alt_deferred} figure(s) need human alt text "
                           "(no vision description) — routed to review · 1.1.1")
        # 1.3.2 reading order — a vision proposal for an untagged (scanned) PDF (never auto).
        try:
            _propose_reading_order(pdf, str(path), ai_enabled=ai_enabled,
                                   scan_id=scan_id, file=path.name, proposals=proposals)
        except Exception:
            pass
        pdf.save(str(mid_path))
    finally:
        pdf.close()

    # Deterministic document title (WCAG 2.4.2) — filename-derived when none is set.
    new_title = None
    if not existing_title:
        new_title = path.stem.replace("-", " ").replace("_", " ").strip() or "Document"
        applied.append(f"Set document title to '{new_title}' · 2.4.2")
        _rec("2.4.2", "(no document title in metadata)", new_title,
             "filename-derived /Title written to the docinfo dictionary")

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


def _fix_pdf_figure_alt(pdf, source_path: str, *, ai_enabled: bool,
                        scan_id: str | None, file: str) -> tuple[list[str], int]:
    """Set /Alt on tagged /Figure struct elements that lack it, from a vision description
    of the figure's page. Returns (applied messages, deferred_count). Mutates pdf in place;
    the caller saves. Never raises — a figure we can't caption is just deferred."""
    import pikepdf
    root = pdf.Root
    if "/StructTreeRoot" not in root:
        return [], 0            # untagged → separate tagging finding, not alt text
    try:
        figures = _collect_figures(root["/StructTreeRoot"])
    except Exception:
        return [], 0
    missing = [f for f in figures if _fig_alt(f) is None]
    if not missing:
        return [], 0

    vision = False
    if ai_enabled:
        try:
            import ai as _ai
            vision = _ai.vision_is_available()
        except Exception:
            vision = False
    if not vision:
        return [], len(missing)  # AI off / no vision model → all defer to review

    import ai as _ai
    applied: list[str] = []
    deferred = 0
    budget = _VISION_MAX_FIGURES
    page_cache: dict[int, bytes | None] = {}
    for idx, fig in enumerate(missing):
        if budget <= 0:
            deferred += 1
            continue
        page_num = _resolve_page_number(fig, pdf)
        if page_num is None:
            deferred += 1
            continue
        if page_num not in page_cache:
            page_cache[page_num] = _render_page_png(source_path, page_num)
        img = page_cache[page_num]
        if not img:
            deferred += 1
            continue
        # Structured (OCR-anchored) alt: a rendered figure page carries the figure's own
        # labels, so the description leads with the headline/chart type. The page render is
        # inherently text-anchored, so this stays an inline auto-fix (unlike the office
        # textless-photo case, which surfaces an ungrounded guess for approval).
        res = _ai.describe_image_structured(img, filename=file, scan_id=scan_id, file=file)
        if not res:
            deferred += 1
            continue
        try:
            fig["/Alt"] = pikepdf.String(res["alt"])
        except Exception:
            deferred += 1
            continue
        budget -= 1
        applied.append(f"Alt text \"{res['alt'][:60]}\" set on figure (page {page_num}) "
                       "from an AI vision description of the image · 1.1.1")
    return applied, deferred


def _collect_figures(node, figures: list | None = None) -> list:
    """Walk the structure tree collecting /Figure struct elements (mirrors the
    pdf.missing-alt-text analyser's traversal so we target the exact elements it checks)."""
    import pikepdf
    if figures is None:
        figures = []
    try:
        if isinstance(node, pikepdf.Dictionary):
            if str(node.get("/S", "")) == "/Figure":
                figures.append(node)
            for key in ("/K", "/C"):
                if key in node:
                    child = node[key]
                    if isinstance(child, pikepdf.Array):
                        for item in child:
                            _collect_figures(item, figures)
                    else:
                        _collect_figures(child, figures)
        elif isinstance(node, pikepdf.Array):
            for item in node:
                _collect_figures(item, figures)
    except Exception:
        pass
    return figures


def _fig_alt(figure) -> str | None:
    try:
        raw = figure.get("/Alt")
        if raw is None:
            return None
        val = str(raw).strip()
        return val or None
    except Exception:
        return None


def _resolve_page_number(figure, pdf) -> int | None:
    """1-based page number for a figure via its /Pg reference."""
    try:
        pg_ref = figure.get("/Pg")
        if pg_ref is None:
            return None
        for i, page in enumerate(pdf.pages):
            if page.obj.objgen == pg_ref.objgen:
                return i + 1
    except Exception:
        pass
    return None


def _render_page_png(source_path: str, page_number: int) -> bytes | None:
    """Render a PDF page to PNG bytes via pypdfium2 (pure wheel; no poppler/PyMuPDF).
    The whole page is rendered — for a figure-bearing page that's dominated by the figure,
    which is what the vision model describes. Returns None on any failure."""
    try:
        import io
        import pypdfium2
        doc = pypdfium2.PdfDocument(source_path)
        try:
            i = page_number - 1
            if i < 0 or i >= len(doc):
                return None
            bitmap = doc[i].render(scale=_RENDER_SCALE)
            buf = io.BytesIO()
            bitmap.to_pil().save(buf, format="PNG")
            return buf.getvalue()
        finally:
            doc.close()
    except Exception:
        return None


def _unlink(p: Path) -> None:
    try:
        p.unlink()
    except Exception:
        pass
