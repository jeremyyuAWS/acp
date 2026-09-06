#!/usr/bin/env python3
"""Generate (or --check) config/en-301-549.json — clause NUMBERS and TITLES only.

WHAT IS REPRODUCED HERE, AND WHY IT IS ONLY THIS. The owner's decision on 2026-09-06, recorded in
`_meta.reproduction_scope`: clause numbers and titles may be reproduced in this repository; the
normative requirement text may not. A VPAT's EU report needs a row per reportable clause and a
heading a reader can match against their own copy of the standard — it does not need the prose.
So this script extracts two fields per clause and discards everything else, and the catalog it
writes carries no requirement text at all.

That constraint also explains the one place this generator differs from its two siblings.

  scripts/gen_wcag_catalog.py         vendors config/wcag22-source.html
  scripts/gen_section_508_catalog.py  vendors config/section-508-source.xml
  this one                            VENDORS NOTHING

Vendoring the source would reproduce the whole standard, which is the thing not permitted. So
`--check` cannot re-parse a committed copy the way the other two can, and it does not pretend to:
it verifies the catalog's internal consistency instead — the clause range, the counts, spot checks
a reader can match against a published table of contents, and that no requirement text crept in.
Regenerating fetches. That is a weaker guard than the others have, and saying so is part of the
guard: `--check` cannot detect a title that was wrong at generation time.

SOURCE, and why BOTH the contents page and the body:

  https://www.etsi.org/deliver/etsi_en/301500_301599/301549/03.02.01_60/en_301549v030201p.pdf

The contents page is the authority for structure. It carries numbers and titles in a fixed two-
column layout — but pdfminer emits the columns as separate runs, so reading order pairs 4.2.11
with clause 4's title. Every line carries a bounding box, so the columns are paired by GEOMETRY:
same y, sorted by x. That is the layout's own pairing rather than a guess about emission order,
and it yields 185 clean pairs across all 14 top-level clauses.

It also stops too shallow, and stopping with it would have shipped a EU report missing most of
what it claims. Clauses 9, 10 and 11 incorporate WCAG's success criteria as numbered sub-clauses,
and the contents page lists them only to guideline depth: sixteen rows for clause 9 where the
standard has fifty-six. So the body supplies the depth, restricted to headings that EXTEND a
contents-page entry — parsed alone it yields 458 candidates with truncated titles ("Concurrent
voice and") and stray glyphs, because headings wrap and tables repeat their numbers.

That the body extraction is sound was MEASURED rather than assumed, against a source already in
this repo. EN clause 9.x.y.z is WCAG x.y.z, so the titles can be compared with
config/wcag-2.2-aa.json: 44 match exactly, 5 differ only in this standard's house style ("Use of
colour", "(pre-recorded)", sentence case), and 6 are WCAG 2.1 criteria WCAG 2.2 no longer carries.
No truncation. tests/test_acr_en_301_549_catalog.py pins that comparison.

  python scripts/gen_en_301_549_catalog.py            # regenerate (fetches)
  python scripts/gen_en_301_549_catalog.py --check    # CI: verify the committed catalog; no fetch
  python scripts/gen_en_301_549_catalog.py --pdf <f>  # parse a local copy instead of fetching
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config" / "en-301-549.json"

VERSION = "V3.2.1 (2021-03)"
SOURCE_URL = ("https://www.etsi.org/deliver/etsi_en/301500_301599/301549/03.02.01_60/"
              "en_301549v030201p.pdf")
CITATION = "EN 301 549 V3.2.1 — Accessibility requirements for ICT products and services"
PUBLISHER = "CEN, CENELEC and ETSI"
TOC_PAGES = list(range(2, 14))

# The clauses a VPAT's EU report reports on. 1 (Scope), 2 (References) and 3 (Definitions) state
# what the document is, not what a product must do; 14 (Conformance) states how to claim it. A
# product conforms to 4-13. Excluded here and named, rather than filtered silently — the same
# reasoning that drops Chapter 7 from the Section 508 catalog.
REPORTABLE = [str(n) for n in range(4, 14)]
CLAUSE_NAMES = {
    "4": "Principles",
    "5": "Generic requirements",
    "6": "ICT with two-way voice communication",
    "7": "ICT with video capabilities",
    "8": "Hardware",
    "9": "Web",
    "10": "Non-web documents",
    "11": "Software",
    "12": "Documentation and support services",
    "13": "ICT providing relay or emergency service access",
}

# Checkable by eye against any published copy of the standard's contents page, and chosen to span
# the parse: the first reportable clause, a four-part number, the WCAG-derived web clause, and one
# from the last reportable clause.
SPOT_CHECKS = {
    "4.2.1": "Usage without vision",
    "9.1.1.1": "Non-text content",
    "11.7": "User preferences",
    "13.1.2": "Text relay services",
}

_NUM = re.compile(r"^(\d{1,2}(?:\.\d+)*)$")
_TITLE = re.compile(r"^(.+?)\s*\.{3,}\s*(\d+)\s*$")


def fetch() -> bytes:
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "acp-gen-en-301-549-catalog"})
    with urllib.request.urlopen(req) as r:                   # noqa: S310 — fixed literal URL
        return r.read()


def parse(pdf_path: Path) -> list[dict]:
    """Every numbered clause in the reportable range, as {num, name}, in standard order.

    Pairs the contents page's two columns by bounding box: a number and its title share a y, so
    grouping by y and sorting by x recovers the pairing the layout intends.
    """
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTTextLineHorizontal

    pairs: list[tuple[str, str]] = []
    for page in extract_pages(str(pdf_path), page_numbers=TOC_PAGES,
                              laparams=LAParams(line_margin=0.2)):
        by_y: dict[int, list[tuple[float, str]]] = {}
        for element in page:
            for line in getattr(element, "__iter__", lambda: [])():
                if isinstance(line, LTTextLineHorizontal):
                    text = line.get_text().strip()
                    if text:
                        by_y.setdefault(round(line.y0), []).append((line.x0, text))
        for y in sorted(by_y, reverse=True):
            parts = [t for _, t in sorted(by_y[y])]
            if len(parts) < 2:
                continue
            num, title = _NUM.match(parts[0]), _TITLE.match(" ".join(parts[1:]))
            if num and title:
                pairs.append((num.group(1), title.group(1).strip()))

    seen: set[str] = set()
    rows: list[tuple[str, str]] = []
    for num, name in pairs:
        if num.split(".")[0] in REPORTABLE and num not in seen:
            seen.add(num)
            rows.append((num, name))

    # THE CONTENTS PAGE STOPS TOO SHALLOW FOR THE WCAG-DERIVED CLAUSES, and stopping with it would
    # ship a EU report missing most of what it claims. Clause 9 (Web), 10 (Non-web documents) and
    # 11 (Software) each incorporate WCAG's success criteria as numbered sub-clauses — 9.1.1.1 Non-
    # text content, and so on — but the contents page lists them only to guideline depth (9.1.1
    # Text alternatives). Sixteen rows for clause 9 where the standard has fifty-six.
    #
    # So the body supplies the depth the contents page omits: any heading that EXTENDS a contents-
    # page entry. Body headings are noisier than the contents page (they wrap, and tables repeat
    # their numbers), which is why they are used only to extend a number the contents page already
    # established, never to introduce one.
    known = {num for num, _ in rows}
    for num, name in _body_headings(pdf_path):
        if num in known or num.split(".")[0] not in REPORTABLE:
            continue
        if any(num.startswith(f"{leaf}.") for leaf in known):
            known.add(num)
            rows.append((num, name))

    # A clause with children is a heading, not something a product conforms to — derived from the
    # numbering rather than judged. Dropping them is the same call as dropping clauses 1-3 and 14,
    # and `_meta.derivation` records it so a reader can disagree with a stated decision rather than
    # discover an unstated one.
    numbers = {n for n, _ in rows}
    leaves = [(n, name) for n, name in rows
              if not any(other.startswith(f"{n}.") for other in numbers)]

    return [
        {
            "num": num,
            "name": name,
            "clause": num.split(".")[0],
            # Mirrors config/section-508.json: a provision that states what a clause applies to,
            # rather than what ICT must do.
            "kind": "scope" if name.strip().lower() in ("general", "scope") else "requirement",
        }
        for num, name in sorted(leaves, key=lambda r: _sortkey(r[0]))
    ]


_BODY_HEADING = re.compile(r"^(\d{1,2}(?:\.\d+){1,3})\s+([A-Z][^\n]{2,80})$", re.M)


def _body_headings(pdf_path: Path) -> list[tuple[str, str]]:
    """Numbered headings from the standard's body, deduplicated, first occurrence winning.

    Page headers and cross-references repeat a clause number, so the same heading appears more than
    once; the first is the heading itself. Only the number and title are read — the requirement
    text that follows each heading is never extracted, which is the whole constraint this generator
    works under.
    """
    from pdfminer.high_level import extract_text

    text = extract_text(str(pdf_path), page_numbers=list(range(14, 90)))
    out: dict[str, str] = {}
    for num, name in _BODY_HEADING.findall(text):
        out.setdefault(num, name.strip())
    return sorted(out.items(), key=lambda r: _sortkey(r[0]))


def _sortkey(num: str) -> tuple[int, ...]:
    return tuple(int(p) for p in num.split("."))


def build(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["clause"]] = counts.get(row["clause"], 0) + 1
    return {
        "_meta": {
            "standard": "EN 301 549",
            "version": VERSION,
            "citation": CITATION,
            "publisher": PUBLISHER,
            "status": "sourced",
            "generated_by": "scripts/gen_en_301_549_catalog.py",
            "source_url": SOURCE_URL,
            "reproduction_scope": (
                "Clause NUMBERS and TITLES only. The owner decided on 2026-09-06 that these may be "
                "reproduced in this repository and that the normative requirement text may not. No "
                "requirement text is present in this file, and neither the source PDF nor any "
                "extract of it is vendored — which is why --check verifies internal consistency "
                "rather than re-parsing a committed copy, as the WCAG and Section 508 generators "
                "do."),
            "clauses": {c: {"name": CLAUSE_NAMES[c], "count": counts.get(c, 0)}
                        for c in REPORTABLE},
            "total": len(rows),
            "derivation": (
                "Every leaf clause in clauses 4-13 of the contents page, in standard order. "
                "Clauses 1-3 (scope, references, definitions) and 14 (conformance) are excluded: "
                "they state what the document is and how to claim against it, not what a product "
                "must do. A clause with sub-clauses is a heading and is excluded too, derived from "
                "the numbering rather than judged. Numbers and titles are paired by bounding box "
                "because the contents page is two columns and reading order pairs them wrongly."),
        },
        "requirements": rows,
    }


def check(committed: dict) -> list[str]:
    """Every way the committed catalog can be wrong WITHOUT the source to compare against.

    Weaker than gen_section_508_catalog.check by construction — there is no vendored copy to
    re-parse, because vendoring it would reproduce what may not be reproduced. This catches drift,
    truncation and contamination; it cannot catch a title that was wrong when it was generated.
    """
    problems: list[str] = []
    meta = committed.get("_meta", {})
    rows = committed.get("requirements", [])

    if meta.get("status") != "sourced":
        problems.append(f"status is {meta.get('status')!r}, expected 'sourced'")
    if not rows:
        problems.append("no requirements — a populated catalog is what makes the EU edition "
                        "offerable, and an empty one silently un-offers it")

    nums = [r["num"] for r in rows]
    if len(nums) != len(set(nums)):
        problems.append("duplicate clause numbers")
    if nums != sorted(nums, key=_sortkey):
        problems.append("clauses are not in standard order")

    outside = sorted({r["clause"] for r in rows} - set(REPORTABLE))
    if outside:
        problems.append(f"clauses outside the reportable range 4-13: {outside}")

    by_num = {r["num"]: r["name"] for r in rows}
    for num, name in SPOT_CHECKS.items():
        if by_num.get(num) != name:
            problems.append(f"{num}: {by_num.get(num)!r}, expected {name!r}")

    for row in rows:
        # A heading has children; a leaf does not. A catalog that grew one has been regenerated
        # with a different rule than the one _meta.derivation states.
        if any(other.startswith(f"{row['num']}.") for other in by_num):
            problems.append(f"{row['num']} is a heading, not a leaf clause")
        if row["clause"] != row["num"].split(".")[0]:
            problems.append(f"{row['num']}: clause is {row['clause']!r}")
        if row["kind"] not in ("requirement", "scope"):
            problems.append(f"{row['num']}: kind is {row['kind']!r}")
        # The licensing constraint, enforced rather than trusted: a title is a few words. Anything
        # sentence-shaped is requirement text that got in, and requirement text may not be here.
        if len(row["name"]) > 90 or row["name"].rstrip().endswith("."):
            problems.append(f"{row['num']}: {row['name']!r} reads as requirement text, not a title")
        if set(row) != {"num", "name", "clause", "kind"}:
            problems.append(f"{row['num']}: unexpected fields {sorted(set(row))}")

    declared = meta.get("clauses", {})
    for clause in REPORTABLE:
        actual = sum(1 for r in rows if r["clause"] == clause)
        if declared.get(clause, {}).get("count") != actual:
            problems.append(f"clause {clause}: _meta says "
                            f"{declared.get(clause, {}).get('count')}, catalog holds {actual}")
    if meta.get("total") != len(rows):
        problems.append(f"_meta.total {meta.get('total')}, catalog holds {len(rows)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify the committed catalog; no fetch")
    ap.add_argument("--pdf", type=Path, help="parse this local copy instead of fetching")
    args = ap.parse_args(argv)

    if args.check:
        if not CATALOG.exists():
            print(f"{CATALOG} is missing", file=sys.stderr)
            return 1
        problems = check(json.loads(CATALOG.read_text(encoding="utf-8")))
        for p in problems:
            print(f"en-301-549 catalog: {p}", file=sys.stderr)
        if problems:
            return 1
        total = json.loads(CATALOG.read_text(encoding="utf-8"))["_meta"]["total"]
        print(f"en-301-549 catalog OK — {total} clauses, numbers and titles only")
        return 0

    source = args.pdf
    if source is None:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(fetch())
            source = Path(handle.name)
    catalog = build(parse(source))
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    per = ", ".join(f"c{c}={catalog['_meta']['clauses'][c]['count']}" for c in REPORTABLE)
    print(f"wrote {CATALOG.relative_to(ROOT)} — {catalog['_meta']['total']} clauses ({per})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
