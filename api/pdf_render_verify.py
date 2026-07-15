"""ADR 0025 Tier B — render-verified PDF contrast, pixel sampling.

The PDF analogue of `render_verify.measure_hybrid_contrast` (ADR 0024 Tier B.1). The scan-time
detector `office_structure.pdf_text_over_image_checks` flags text sitting over a raster image —
where the declared text colour can't prove contrast because the real background is the picture's
pixels. This module answers the follow-up "so what's the actual contrast?" by RENDERING the page
(pdfium, `render.render_page_png` — always available, no LibreOffice needed) and measuring the
text-vs-image contrast from the pixels under each text run.

Honesty (ADR 0016): a ratio actually read from the pixels, or an honest abstain — never a certified
pass. text-over-image stays a 🟡 review even when measured (a single line's legibility doesn't
certify the document). Never raises; every failure degrades to `{"measured": False, ...}`.
"""
from __future__ import annotations

from pathlib import Path

# One card open shouldn't rasterize a whole book; bound the runs measured per request (the same
# cap posture as the Office Tier B endpoint). More runs than this reports the cap honestly via
# checked < total rather than silently covering only some.
_MAX_PDF_RUNS = 12


def measure_pdf_over_image_contrast(data: bytes, *, render_page=None, locators=None) -> dict:
    """Render each page that carries text-over-image and MEASURE the contrast of every such text run
    against the image behind it. Returns an always-shaped result the card renders directly:

        {"measured": True, "runs": [...], "worst_ratio": 2.4, "any_fail_aa": True,
         "checked": 3, "total": 3}
        {"measured": False, "reason": "no_text_over_image" | "ambiguous_background" |
                                      "render_failed" | "error"}

    `render_page` is injectable (defaults to `render.render_page_png`) so the composition unit-tests
    without a real render. `locators` is injectable to skip re-derivation in tests. Never raises."""
    try:
        import office_structure as _off

        runs = locators if locators is not None else _off.pdf_over_image_locators(data)
        if not runs:
            return {"measured": False, "reason": "no_text_over_image"}
        if render_page is None:
            import render as _render
            render_page = _render.render_page_png

        import render_verify as _rv
        page_png: dict[int, bytes | None] = {}
        out: list[dict] = []
        for r in runs[:_MAX_PDF_RUNS]:
            bbox = r.get("bbox") or {}
            page = int(bbox.get("page") or r.get("page") or 1)
            if page not in page_png:
                page_png[page] = render_page(data, ".pdf", page)
            png = page_png[page]
            if not png:
                out.append({"measured": False, "reason": "render_failed", "page": page})
                continue
            m = _rv.region_contrast(png, bbox)
            if m:
                out.append({"measured": True, "page": page, "bbox": bbox, "chars": r.get("chars"), **m})
            else:
                out.append({"measured": False, "reason": "ambiguous_background", "page": page})

        ok = [m for m in out if m.get("measured") and isinstance(m.get("ratio"), (int, float))]
        if not ok:
            # Nothing measurable. Report why honestly: a pure render failure (pdfium couldn't
            # rasterize) reads differently from busy backgrounds no field can be measured against.
            reasons = {m.get("reason") for m in out}
            reason = "render_failed" if reasons == {"render_failed"} else "ambiguous_background"
            return {"measured": False, "reason": reason,
                    "checked": len(out), "total": len(runs)}
        worst = min(ok, key=lambda m: m["ratio"])
        return {"measured": True, "runs": out,
                "worst_ratio": worst["ratio"], "worst_page": worst["page"],
                "any_fail_aa": any(not m["passes_aa"] for m in ok),
                "checked": len(out), "total": len(runs)}
    except Exception:
        return {"measured": False, "reason": "error"}


def _read_bytes(path_or_bytes) -> bytes:
    """Convenience for callers that hold a path (tests, ad-hoc use). The endpoint passes bytes."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        return bytes(path_or_bytes)
    return Path(path_or_bytes).read_bytes()
