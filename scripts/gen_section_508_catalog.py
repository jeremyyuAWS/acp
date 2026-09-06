#!/usr/bin/env python3
"""Generate (or --check) config/section-508.json from the Revised Section 508 Standards.

PRD delivery phase 6 is "Section 508, EU and International editions". #1532 built the half that
refuses a false claim: `acr_catalog.EDITION_REQUIREMENT_SETS` says the 508 edition obliges a report
to carry the Revised Section 508 chapters, `requirement_sets_available()` says which requirement
sets this build can actually populate, and the publication gate refuses an edition it cannot
supply. This script supplies one of the missing sets.

WHY DERIVED, NOT TRANSCRIBED. The same reason scripts/gen_wcag_catalog.py gives for the WCAG
catalog: a missing requirement or a wrong chapter is invisible at every stage — the matrix renders,
the report publishes, and the error surfaces in a customer's procurement review, in a document PRD
§17 says cannot be recalled. So the catalog comes from the normative text and is regenerated.

SOURCE. 36 CFR Part 1194, Appendix C — the Revised 508 Standards' own chapters, fetched from the
eCFR API rather than from the Access Board's rendering of them:

  https://www.ecfr.gov/api/versioner/v1/full/{date}/title-36.xml?chapter=XI&subchapter=D&part=1194

Two things about that endpoint, both measured on 2026-09-06 rather than read off documentation:
it answers 406 unless the request permits compression, and Appendix C carries the reportable
chapters while Appendix A carries the E-chapters (application and scoping, including E205.4's
incorporation of WCAG by reference). This parses Appendix C.

LICENSING, since Phase 5 stalled on exactly that question for the ITI template: this source needs
no ADR. 36 CFR is a work of the United States Government, uncopyrightable under 17 U.S.C. §105 and
published by the Government Publishing Office for reuse. Vendoring the fetched XML is a
reproducibility measure, not a redistribution question. EN 301 549 — the EU edition's requirement
set — is NOT in the same position, and that difference is flagged where it belongs, in the phase
plan, rather than discovered when someone tries to land it.

  python scripts/gen_section_508_catalog.py            # regenerate from the vendored or fetched source
  python scripts/gen_section_508_catalog.py --check    # CI: fail if the committed catalog drifted
  python scripts/gen_section_508_catalog.py --xml <f>  # parse a local copy instead of fetching

NETWORK. --check does NOT fetch, for the reason gen_wcag_catalog.py gives: CI must not depend on
ecfr.gov being up, and a regulation republished upstream must not turn a green build red without a
human looking at it. It re-parses the vendored copy when present and otherwise verifies the
committed catalog's internal consistency.

WHAT THIS DELIBERATELY DOES NOT DECIDE. Which of these requirements a given report has to answer.
Chapter 4 is hardware and ACP is software, so most of its 69 rows will end Not Applicable — but
applicability is a human decision with required remarks (PRD §10), never a default the catalog
picks, exactly as `acr_catalog.build_matrix` refuses to guess for WCAG. The catalog therefore
carries the WHOLE of chapters 3-6 and marks each row's `kind`, so a later slice can scope the
matrix from data rather than re-deriving it from the regulation.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config" / "section-508.json"
VENDORED_XML = ROOT / "config" / "section-508-source.xml"

# Pinned so a regeneration answers about the same edition of the regulation every time. The
# Revised 508 Standards have not been amended since the 2017 final rule's 2018 corrections; a date
# that moves the text is a change a person should see, which is what the counts below enforce.
ECFR_DATE = "2025-01-01"
SOURCE_URL = (f"https://www.ecfr.gov/api/versioner/v1/full/{ECFR_DATE}/title-36.xml"
              "?chapter=XI&subchapter=D&part=1194")
CITATION = "36 CFR Part 1194, Appendix C (Revised Section 508 Standards)"

# The chapters a VPAT's Revised Section 508 Report actually reports on. Chapter 7 (Referenced
# Standards) is in the appendix and is not a set of requirements a product conforms to — it names
# the documents the other chapters cite — so it is parsed and then dropped, deliberately and here
# rather than silently in a regex.
REPORTABLE_CHAPTERS = ("3", "4", "5", "6")
CHAPTER_NAMES = {
    "3": "Functional Performance Criteria",
    "4": "Hardware",
    "5": "Software",
    "6": "Support Documentation and Services",
}

# ASSERTIONS ABOUT THE PARSE, not the source of the catalog — the catalog comes from the
# regulation. These exist because a parser that silently matched nothing would otherwise emit a
# plausible-looking short catalog and pass, which is the failure gen_wcag_catalog.py's ADDED_IN_22
# block guards against for the same reason.
EXPECTED_PER_CHAPTER = {"3": 10, "4": 69, "5": 33, "6": 8}

# Requirements every reader of this file can check by eye against the regulation, chosen because
# each is load-bearing for a DIFFERENT part of the parse: the first functional performance
# criterion, a three-level number, the software chapter's WCAG incorporation, and the last row.
SPOT_CHECKS = {
    "302.1": "Without Vision",
    "402.2.1": "Information Displayed On-Screen",
    "501.1": "Scope",
    "602.4": "Alternate Formats for Non-Electronic Support Documentation",
}

_TAG = re.compile(r"<(HD1|P)[^>]*>(.*?)</\1>", re.S)
_CHAPTER = re.compile(r"^Chapter (\d): (.+)$")
# A requirement paragraph opens with a dotted number of at least two parts whose first part is the
# three-digit section, then its title, then a period. EXCEPTION paragraphs and the numbered items
# inside them ("2. Speech output shall not be required…") cannot match: they have no NNN. prefix.
_REQUIREMENT = re.compile(r"^(\d{3}(?:\.\d+)+)\s+(.+?)\.\s")


def fetch() -> str:
    """The regulation as XML. Only ever called by a regeneration, never by --check."""
    req = urllib.request.Request(SOURCE_URL, headers={
        "Accept-Encoding": "gzip",           # eCFR answers 406 without this
        "User-Agent": "acp-gen-section-508-catalog",
    })
    with urllib.request.urlopen(req) as r:                      # noqa: S310 — fixed literal URL
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return raw.decode("utf-8")


def appendix_c(xml: str) -> str:
    """Just Appendix C. Slicing before parsing keeps Appendix A's E-chapters, which use the same
    numbering shape (E205 vs 205), from being read as chapter rows."""
    start = xml.find(">Appendix C to Part 1194")
    if start < 0:
        raise SystemExit("Appendix C not found in the source — the endpoint's shape changed")
    end = xml.find("Appendix D to Part 1194", start)
    return xml[start:end] if end > 0 else xml[start:]


def parse(xml: str) -> list[dict]:
    """Every numbered requirement in Appendix C's reportable chapters, in regulation order."""
    chapter: str | None = None
    seen: set[str] = set()
    rows: list[dict] = []
    for tag, body in ((m.group(1), m.group(2)) for m in _TAG.finditer(appendix_c(xml))):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", body)).strip()
        heading = _CHAPTER.match(text)
        if tag == "HD1" and heading:
            chapter = heading.group(1)
            continue
        if tag != "P" or chapter not in REPORTABLE_CHAPTERS:
            continue
        found = _REQUIREMENT.match(text)
        if not found or found.group(1) in seen:
            continue
        num, name = found.group(1), found.group(2)
        seen.add(num)
        rows.append({
            "num": num,
            "name": name,
            "chapter": chapter,
            "chapter_name": CHAPTER_NAMES[chapter],
            "section": num.split(".")[0],
            # A scope provision states what the chapter applies to; the rest state what ICT must
            # do. Recorded rather than filtered, so the decision of which rows a report answers is
            # made once, visibly, by the slice that builds the matrix.
            "kind": "scope" if name.lower() in ("scope", "general") else "requirement",
        })
    return rows


def catalog_hash(catalog: dict) -> str:
    """SHA-256 over the requirement set, key-sorted and number-sorted.

    Byte-identical in construction to acr_catalog.catalog_hash so the script and the runtime can
    never disagree about which catalog a report was built from — tests/test_acr_section_508_catalog.py
    asserts the two agree, the same guard gen_wcag_catalog.py carries.
    """
    payload = json.dumps(sorted(catalog["requirements"], key=lambda r: _sortkey(r["num"])),
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sortkey(num: str) -> tuple[int, ...]:
    return tuple(int(p) for p in num.split("."))


def build(rows: list[dict]) -> dict:
    counts = collections.Counter(r["chapter"] for r in rows)
    return {
        "_meta": {
            "standard": "Revised Section 508 Standards",
            "citation": CITATION,
            "source_url": SOURCE_URL,
            "ecfr_date": ECFR_DATE,
            "generated_by": "scripts/gen_section_508_catalog.py",
            "chapters": {c: {"name": CHAPTER_NAMES[c], "count": counts[c]}
                         for c in REPORTABLE_CHAPTERS},
            "total": len(rows),
            "derivation": (
                "Every numbered requirement in Appendix C chapters 3-6, in regulation order. "
                "Chapter 7 (Referenced Standards) is excluded: it names documents the other "
                "chapters cite rather than requirements a product conforms to. Scope and General "
                "provisions are kept and marked kind=scope rather than dropped, because which "
                "rows a report must answer is a scoping decision this catalog does not make."),
        },
        "requirements": rows,
    }


def load_source(explicit: Path | None) -> str | None:
    for candidate in (explicit, VENDORED_XML):
        if candidate and candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return None


def check(committed: dict, source: str | None) -> list[str]:
    """Every way the committed catalog can be wrong, reported together rather than one at a time."""
    problems: list[str] = []
    rows = committed.get("requirements", [])
    counts = collections.Counter(r["chapter"] for r in rows)
    for chapter, expected in EXPECTED_PER_CHAPTER.items():
        if counts[chapter] != expected:
            problems.append(f"chapter {chapter}: {counts[chapter]} requirements, expected {expected}")
    if len(rows) != sum(EXPECTED_PER_CHAPTER.values()):
        problems.append(f"total {len(rows)}, expected {sum(EXPECTED_PER_CHAPTER.values())}")
    by_num = {r["num"]: r["name"] for r in rows}
    for num, name in SPOT_CHECKS.items():
        if by_num.get(num) != name:
            problems.append(f"{num}: {by_num.get(num)!r}, expected {name!r}")
    if len(by_num) != len(rows):
        problems.append("duplicate requirement numbers in the catalog")
    if [r["num"] for r in rows] != sorted(by_num, key=_sortkey):
        problems.append("requirements are not in regulation order")
    if source is not None:
        fresh = build(parse(source))
        if fresh["requirements"] != rows:
            problems.append("the committed catalog does not match a re-parse of the vendored "
                            "source — regenerate with scripts/gen_section_508_catalog.py")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify the committed catalog; never fetches")
    ap.add_argument("--xml", type=Path, help="parse this local copy instead of fetching")
    args = ap.parse_args(argv)

    if args.check:
        if not CATALOG.exists():
            print(f"{CATALOG} is missing", file=sys.stderr)
            return 1
        committed = json.loads(CATALOG.read_text(encoding="utf-8"))
        problems = check(committed, load_source(args.xml))
        for p in problems:
            print(f"section-508 catalog: {p}", file=sys.stderr)
        if problems:
            return 1
        print(f"section-508 catalog OK — {committed['_meta']['total']} requirements, "
              f"hash {catalog_hash(committed)[:12]}")
        return 0

    xml = load_source(args.xml) or fetch()
    if not VENDORED_XML.exists():
        VENDORED_XML.write_text(xml, encoding="utf-8")
    catalog = build(parse(xml))
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    meta = catalog["_meta"]
    per_chapter = ", ".join(f"ch{c}={meta['chapters'][c]['count']}" for c in REPORTABLE_CHAPTERS)
    print(f"wrote {CATALOG.relative_to(ROOT)} — {meta['total']} requirements ({per_chapter}), "
          f"hash {catalog_hash(catalog)[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
