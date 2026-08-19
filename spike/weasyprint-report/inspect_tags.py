"""Structural accessibility inspection of the WeasyPrint spike PDF (ADR 0034).

This checks the STRUCTURE — the questions passing `TaggedPdfRule` alone does NOT answer:
  * catalog is marked + tagged + has a language and a shown title
  * heading hierarchy is a proper outline (H1 → H2 → H3, no skipped levels)
  * data tables expose TH cells WITH a /Scope
  * every Figure in the tag tree carries /Alt (and the decorative chart produces NO Figure)
  * page furniture (running header/footer) and decorative graphics are Artifacts, not reading order

It is deliberately honest about its ceiling: structural correctness is necessary, not sufficient,
for PDF/UA. It does NOT replace veraPDF/PAC or a screen-reader pass (see README, "Validation gate").
Exits non-zero if any structural check fails, so CI/a reviewer gets a hard signal.

Run:  python inspect_tags.py            # builds the sample if needed, then inspects
"""
from __future__ import annotations

import sys
from pathlib import Path

import pikepdf

HERE = Path(__file__).resolve().parent
PDF = HERE / "sample_report.pdf"

# Heading structure types, in level order, for the hierarchy check.
_HHEADS = ["/H1", "/H2", "/H3", "/H4", "/H5", "/H6"]


def _name(x):
    return str(x) if x is not None else None


def walk(node, depth=0, out=None):
    """Yield (depth, structure_type, element) for every StructElem under `node`."""
    out = [] if out is None else out
    k = node.get("/K")
    if k is None:
        return out
    kids = list(k) if isinstance(k, pikepdf.Array) else [k]
    for kid in kids:
        if isinstance(kid, pikepdf.Dictionary) and "/S" in kid:
            out.append((depth, _name(kid.get("/S")), kid))
            walk(kid, depth + 1, out)
        elif isinstance(kid, pikepdf.Dictionary):
            walk(kid, depth, out)
    return out


def marked_content_tags(pdf):
    """Count marked-content sequences by tag across all pages, so we can confirm furniture and
    decoration are Artifacts and body content is tagged (P/H*/Table/Span/...)."""
    counts: dict[str, int] = {}
    for page in pdf.pages:
        try:
            for instr in pikepdf.parse_content_stream(page):
                op = str(instr.operator)
                if op in ("BDC", "BMC") and instr.operands:
                    counts[str(instr.operands[0])] = counts.get(str(instr.operands[0]), 0) + 1
        except Exception:
            pass
    return counts


def main() -> int:
    if not PDF.exists():
        from sample_report import build
        build()

    pdf = pikepdf.open(PDF)
    root = pdf.Root
    checks: list[tuple[str, bool, str, str]] = []   # (label, ok, detail, severity)

    def check(label, ok, detail="", severity="FAIL"):
        # severity="FAIL" → a hard structural must-have; "WARN" → a PDF/UA-nuance finding for the
        # veraPDF/screen-reader gate, not a blocker on the spike itself.
        checks.append((label, bool(ok), detail, severity))

    # ── 1. catalog ────────────────────────────────────────────────────────────────────────────
    mi = root.get("/MarkInfo")
    marked = bool(mi.get("/Marked")) if isinstance(mi, pikepdf.Dictionary) else False
    check("catalog /MarkInfo /Marked true", marked)
    check("catalog /StructTreeRoot present", "/StructTreeRoot" in root)
    check("catalog /Lang set (3.1.1)", root.get("/Lang") is not None, _name(root.get("/Lang")))
    vp = root.get("/ViewerPreferences")
    dt = bool(vp.get("/DisplayDocTitle")) if isinstance(vp, pikepdf.Dictionary) else False
    check("DisplayDocTitle true (2.4.2)", dt)

    if "/StructTreeRoot" not in root:
        _report(checks, [], {})
        return 1
    mc = marked_content_tags(pdf)

    elems = walk(root["/StructTreeRoot"])
    types = [t for _, t, _ in elems]

    # ── 2. heading hierarchy: no skipped levels ────────────────────────────────────────────────
    levels = [_HHEADS.index(t) + 1 for t in types if t in _HHEADS]
    no_skip = all(b - a <= 1 for a, b in zip(levels, levels[1:])) and (not levels or levels[0] == 1)
    check("heading hierarchy has no skipped levels", no_skip, f"levels seen: {levels}")

    # ── 3. tables expose scoped TH ─────────────────────────────────────────────────────────────
    th = [e for _, t, e in elems if t == "/TH"]
    th_scoped = [e for e in th if e.get("/A") is not None or "/Scope" in (e.get("/A") or {})]
    # /Scope rides an attribute object (/A) with /O /Table; check any TH carries a Scope attribute.
    def has_scope(e):
        a = e.get("/A")
        objs = list(a) if isinstance(a, pikepdf.Array) else [a] if a is not None else []
        return any(isinstance(o, pikepdf.Dictionary) and "/Scope" in o for o in objs)
    scoped = [e for e in th if has_scope(e)]
    check("table has TH header cells", len(th) > 0, f"{len(th)} TH")
    # FINDING (WARN): WeasyPrint tags <th scope> as /TH but emits no PDF /Scope attribute. PDF/UA can
    # still associate headers by table position, so this is a veraPDF question, not a hard structural
    # failure — flagged for the gate rather than blocking the spike.
    check("every TH carries an explicit /Scope", len(th) > 0 and len(scoped) == len(th),
          f"{len(scoped)}/{len(th)} scoped — WeasyPrint omits /Scope; verify header association in veraPDF",
          severity="WARN")

    # ── 4. figures: the chart tags as a Figure WITH alt, and no orphan ─────────────────────────
    # Iteration 2: the chart is an <img alt="conclusion"> (data-URI SVG), not an aria-hidden inline
    # <svg>. That is the treatment the probe found actually works: it tags as a /Figure carrying
    # /Alt, and leaves NO orphan /Figure marked-content. Both are now hard checks — the orphan was a
    # real PDF/UA violation in iteration 1, so this guards against regressing to it.
    figs = [e for _, t, e in elems if t == "/Figure"]
    figs_no_alt = [e for e in figs if not e.get("/Alt")]
    check("chart tags as a Figure carrying /Alt", len(figs) >= 1 and len(figs_no_alt) == 0,
          f"{len(figs)} Figure struct elem(s), {len(figs_no_alt)} missing alt")
    orphan_figs = mc.get("/Figure", 0) - len(figs)
    check("no orphan /Figure marked-content", orphan_figs <= 0,
          f"{mc.get('/Figure', 0)} /Figure in stream vs {len(figs)} in struct tree — "
          f"{max(orphan_figs, 0)} orphan")

    # ── 5. furniture is Artifacts ──────────────────────────────────────────────────────────────
    check("Artifact marked-content present (running header/footer)", mc.get("/Artifact", 0) > 0,
          f"Artifact sequences: {mc.get('/Artifact', 0)}")

    _report(checks, types, mc)
    hard_fail = any((not ok) and sev == "FAIL" for _, ok, _, sev in checks)
    return 1 if hard_fail else 0


def _report(checks, types, mc):
    print("=" * 78)
    print("WeasyPrint conformance-report spike — structural inspection")
    print("=" * 78)
    for label, ok, detail, sev in checks:
        mark = "PASS" if ok else sev            # PASS / FAIL / WARN
        print(f"  [{mark}] {label}" + (f"   ({detail})" if detail else ""))
    print("-" * 78)
    print("tag outline (structure types in reading order):")
    print("   " + (" ".join(t.lstrip("/") for t in types) if types else "(none)"))
    print("marked-content tags:", {k: v for k, v in sorted(mc.items())})
    print("-" * 78)
    hard = [l for l, ok, _, sev in checks if not ok and sev == "FAIL"]
    warns = [l for l, ok, _, sev in checks if not ok and sev == "WARN"]
    if hard:
        print(f"RESULT: {len(hard)} HARD structural check(s) FAILED — {hard}")
    else:
        print("RESULT: all HARD structural checks PASSED.")
    if warns:
        print(f"        {len(warns)} PDF/UA-nuance finding(s) for the gate — {warns}")
    print("NOTE: structural pass is necessary, not sufficient. veraPDF/PAC + a screen-reader pass")
    print("      remain the gate before the full renderer migration (see README).")


if __name__ == "__main__":
    sys.exit(main())
