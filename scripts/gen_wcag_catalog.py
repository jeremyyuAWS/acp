#!/usr/bin/env python3
"""Generate (or --check) config/wcag-2.2-aa.json from the W3C WCAG 2.2 Recommendation.

The ACR criteria matrix must be the WHOLE applicable standard, and it must be right. A
hand-transcribed catalog is the wrong shape for that: a missing criterion or a wrong level is
invisible — the matrix renders, the report publishes, and the error surfaces in a customer's
procurement review. So the catalog is DERIVED from the normative source and regenerated, the same
posture scripts/gen_matrix_coverage.py and gen_todo_status.py already take for their artifacts.

WHY THIS IS A SEPARATE CATALOG from config/rule-catalog.json. That file maps ACP's DETECTORS to
WCAG 2.1 success criteria, per document format (docx/pptx/xlsx/pdf) — "what can ACP find in a
customer's file". This one is the list of criteria ACP'S OWN WEB UI is evaluated against, at
WCAG 2.2 A+AA. Different standard version, different subject, different scope. docs/
conformance-report.md already draws that line in prose ("the conformance of the platform's own
web UI, not the conformance of customer documents it remediates"); conflating the two in code is
the most direct route to an unsupported conformance claim, so they are deliberately two files.

SOURCE. https://www.w3.org/TR/WCAG22/ — the Recommendation itself, not the quickref (which is
JS-rendered) and not an Understanding page (non-normative). Parsing is deterministic: the spec
marks every criterion as `<h4><bdi class="secno">Success Criterion N.N.N </bdi>Title</h4>`
followed by `<p class="conformance-level">(Level X)</p>`. No model, no judgement.

  python scripts/gen_wcag_catalog.py            # regenerate from a cached or fetched copy
  python scripts/gen_wcag_catalog.py --check    # CI: fail if the committed catalog drifted
  python scripts/gen_wcag_catalog.py --html <f> # parse a local copy instead of fetching

NETWORK. --check does NOT fetch. It re-parses a vendored copy of the spec when one is present,
and otherwise verifies the committed catalog's internal consistency (counts, level split, the
2.2 delta below). CI must not depend on w3.org being up, and a spec errata republished upstream
must not turn a green build red without a human looking at it.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config" / "wcag-2.2-aa.json"
VENDORED_HTML = ROOT / "config" / "wcag22-source.html"
SOURCE_URL = "https://www.w3.org/TR/WCAG22/"

# The WCAG 2.2 delta against 2.1, at A+AA. These are ASSERTIONS ABOUT THE PARSE, not the source
# of the catalog — the catalog comes from the spec. They exist because a parser that silently
# matched nothing would otherwise emit a plausible-looking short catalog and pass. See
# tests/test_acr_catalog.py, which enforces the same facts against the committed file.
ADDED_IN_22 = {
    "2.4.11": "AA",   # Focus Not Obscured (Minimum)
    "2.5.7": "AA",    # Dragging Movements
    "2.5.8": "AA",    # Target Size (Minimum)
    "3.2.6": "A",     # Consistent Help
    "3.3.7": "A",     # Redundant Entry
    "3.3.8": "AA",    # Accessible Authentication (Minimum)
}
# 4.1.1 Parsing was made obsolete in WCAG 2.2. The spec still PRINTS it — as "Success Criterion
# 4.1.1 Parsing (Obsolete and removed)" — but strips its `<p class="conformance-level">`, because
# it no longer has one. That absence is the machine-readable fact, and it is a sharper 2.1-vs-2.2
# discriminator than presence would be: in WCAG 2.1 this same criterion carries "(Level A)".
#
# So the invariant is NOT "4.1.1 is absent" (it is present) but "4.1.1 is present, carries no
# conformance level, and is therefore not in the A/AA catalog". Found by running the parser: the
# first draft asserted absence and died on the real document.
OBSOLETE_IN_22 = "4.1.1"
_OBSOLETE_TITLE = "(Obsolete and removed)"

_HDR = re.compile(
    r'<h(?P<lvl>[234])[^>]*>(?:<bdi class="secno">(?P<secno>[^<]*)</bdi>)?(?P<title>.*?)</h(?P=lvl)>',
    re.S)
_LEVEL = re.compile(r'<p class="conformance-level">\(Level (A+)\)</p>')


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment)).strip()


def parse_spec(html: str) -> list[dict]:
    """Every success criterion in the document, in spec order, with its principle and guideline.

    Principle/guideline are carried down from the enclosing h2/h3 rather than re-derived from the
    criterion number, so a renumbering upstream cannot put a criterion under the wrong heading.
    """
    principle = guideline = None
    out: list[dict] = []
    marks = list(_HDR.finditer(html))
    for i, m in enumerate(marks):
        lvl = m.group("lvl")
        secno = (m.group("secno") or "").strip()
        title = _text(m.group("title"))
        # The spec's three heading shapes, verbatim (checked against the published document, not
        # guessed): principles number themselves "1. ", guidelines "Guideline 1.1 ", criteria
        # "Success Criterion 1.1.1 ". The `.`/prefix details are load-bearing — a tighter `\d+`
        # matches none of them and silently yields criteria with no principle at all.
        if lvl == "2" and re.fullmatch(r"\d+\.?", secno):
            principle = title
        elif lvl == "3" and (gm := re.fullmatch(r"Guideline\s+(\d+\.\d+)", secno)):
            guideline = f"{gm.group(1)} {title}"
        elif lvl == "4" and secno.startswith("Success Criterion"):
            num = secno[len("Success Criterion"):].strip()
            tail = html[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(html)]
            lm = _LEVEL.search(tail)
            if not lm:
                # An obsolete criterion legitimately has no level (see OBSOLETE_IN_22). Anything
                # ELSE missing one means the spec's markup moved and this parser is stale — which
                # must fail loudly rather than silently drop a criterion from the matrix.
                if _OBSOLETE_TITLE in title:
                    out.append({"num": num, "name": title, "level": None,
                                "principle": principle, "guideline": guideline})
                    continue
                raise SystemExit(f"criterion {num} has no conformance-level marker — parser is stale")
            out.append({"num": num, "name": title, "level": lm.group(1),
                        "principle": principle, "guideline": guideline})
    return out


def build_catalog(rows: list[dict]) -> dict:
    aa = [r for r in rows if r["level"] in ("A", "AA")]
    _assert_sane(rows, aa)
    return {
        "_meta": {
            "standard": "WCAG",
            "version": "2.2",
            "levels": ["A", "AA"],
            "source": SOURCE_URL,
            "generator": "scripts/gen_wcag_catalog.py",
            "note": ("Applicable-criteria catalog for the ACR workspace: the criteria ACP's own "
                     "web UI is evaluated against. NOT config/rule-catalog.json, which maps ACP's "
                     "document detectors to WCAG 2.1 criteria per file format."),
            "criteria_count": len(aa),
            "level_counts": dict(sorted(collections.Counter(r["level"] for r in aa).items())),
        },
        "criteria": [{"num": r["num"], "name": r["name"], "level": r["level"],
                      "principle": r["principle"], "guideline": r["guideline"]} for r in aa],
    }


def _assert_sane(rows: list[dict], aa: list[dict]) -> None:
    """Fail loudly on the parse errors that would otherwise emit a believable wrong catalog."""
    if not aa:
        raise SystemExit("parsed zero A/AA criteria — the spec's markup changed")
    by_num = {r["num"]: r for r in rows}
    # 4.1.1 must be present-but-levelless in a full parse (proving the source is 2.2), and must
    # never reach the A/AA catalog. When _assert_sane is called on an already-built catalog (the
    # --check path with no vendored spec) `rows is aa`, so the first arm cannot apply — there the
    # only thing to assert is its absence.
    obsolete = by_num.get(OBSOLETE_IN_22)
    if rows is not aa:
        if obsolete is None:
            raise SystemExit(f"{OBSOLETE_IN_22} is absent entirely — unexpected source document")
        if obsolete["level"] is not None:
            raise SystemExit(
                f"{OBSOLETE_IN_22} carries Level {obsolete['level']} — this is WCAG 2.1, not 2.2")
    if any(r["num"] == OBSOLETE_IN_22 for r in aa):
        raise SystemExit(f"{OBSOLETE_IN_22} is obsolete in WCAG 2.2 and must not be in the catalog")
    for num, level in ADDED_IN_22.items():
        got = by_num.get(num)
        if got is None:
            raise SystemExit(f"{num} (added in WCAG 2.2) is absent — wrong source document")
        if got["level"] != level:
            raise SystemExit(f"{num} parsed as Level {got['level']}, expected {level}")
    dupes = [n for n, c in collections.Counter(r["num"] for r in aa).items() if c > 1]
    if dupes:
        raise SystemExit(f"duplicate criteria: {dupes}")
    missing = [r["num"] for r in aa if not r["principle"] or not r["guideline"]]
    if missing:
        raise SystemExit(f"criteria with no principle/guideline: {missing}")


def canonical(obj: dict) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def catalog_hash(obj: dict) -> str:
    """SHA-256 over the CRITERIA only, key-sorted — stable across _meta edits and reordering.

    Mirrors the rubric_hash idea overview_snapshots already stamps: a report records the exact
    criteria set it was built from, so a snapshot stays interpretable after the catalog moves on.
    """
    payload = json.dumps(sorted(obj["criteria"], key=lambda r: r["num"]),
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_html(explicit: str | None) -> str | None:
    if explicit:
        return Path(explicit).read_text(encoding="utf-8")
    if VENDORED_HTML.exists():
        return VENDORED_HTML.read_text(encoding="utf-8")
    return None


def _fetch() -> str:
    import urllib.request
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as r:
        return r.read().decode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the committed catalog drifted")
    ap.add_argument("--html", help="parse this local copy of the spec instead of fetching")
    args = ap.parse_args()

    html = _load_html(args.html)

    if args.check:
        if not CATALOG.exists():
            print(f"FAIL {CATALOG.relative_to(ROOT)} is missing", file=sys.stderr)
            return 1
        committed = json.loads(CATALOG.read_text(encoding="utf-8"))
        if html is None:
            # No vendored spec: verify the committed catalog against its own invariants. This is
            # weaker than a re-parse and deliberately so — see this module's NETWORK note.
            rows = [dict(r) for r in committed["criteria"]]
            try:
                _assert_sane(rows, rows)
            except SystemExit as e:
                print(f"FAIL {e}", file=sys.stderr)
                return 1
            meta = committed["_meta"]
            if meta.get("criteria_count") != len(rows):
                print(f"FAIL _meta.criteria_count={meta.get('criteria_count')} but "
                      f"{len(rows)} criteria are listed", file=sys.stderr)
                return 1
            print(f"OK  {len(rows)} criteria, self-consistent (no vendored spec to re-parse)")
            return 0
        fresh = build_catalog(parse_spec(html))
        if canonical(fresh) != CATALOG.read_text(encoding="utf-8"):
            print(f"FAIL {CATALOG.relative_to(ROOT)} differs from the spec — regenerate it",
                  file=sys.stderr)
            return 1
        print(f"OK  {fresh['_meta']['criteria_count']} criteria match {SOURCE_URL}")
        return 0

    if html is None:
        html = _fetch()
    catalog = build_catalog(parse_spec(html))
    CATALOG.write_text(canonical(catalog), encoding="utf-8")
    print(f"wrote {CATALOG.relative_to(ROOT)} — {catalog['_meta']['criteria_count']} criteria "
          f"{catalog['_meta']['level_counts']} hash={catalog_hash(catalog)[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
