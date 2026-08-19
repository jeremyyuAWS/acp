#!/usr/bin/env python3
"""Emit per-rule assessment/remediation detail to both SPAs, from docs/rules/*.md.

The question this answers is "for 1.3.1 on DOCX, what does ACP actually check — are we looking
at H1 and H2?". Until now the product could say a criterion was assessed and could not say what
that meant, so the honest answer lived in a markdown file nobody in the UI could reach.

WHY GENERATED FROM THE DOCS RATHER THAN TYPED INTO THE SPA. The prose already exists, one file
per rule, and it is the text an engineer maintains when the detector changes. Copying it into JS
would create the second copy this repo keeps writing generators to avoid (see
gen_scope_presets.py's docstring on `documents20.js`), and the copy in the UI is the one a
customer reads — so it is the copy that must not go stale.

WHAT IS DELIBERATELY NOT INVENTED. Six of the 36 docs have no "Fix mode rationale" section, and
those rules emit `remediation: null` rather than a plausible sentence. A per-rule detail panel
that quietly fabricates the remediation story for a sixth of the catalog is worse than one that
says nothing: the reader cannot tell which sentences are real. `--check` prints the coverage so
the gap stays visible instead of becoming the new normal.

A doc that EXISTS but does not parse is a hard error, not a skip. Skipping would make a broken
heading indistinguishable from a rule nobody has documented, and the first is a typo somebody
can fix in a minute while the second is a decision.

Usage:
    python scripts/gen_rule_details.py            # write every target in OUTS
    python scripts/gen_rule_details.py --stdout    # print it instead
    python scripts/gen_rule_details.py --check     # exit 1 (with a diff) if any target is stale
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "rules"

# One SPA since the v2 redesign replaced `frontend/` in place. Still listed explicitly rather
# than globbed `frontend*` — same reasoning as gen_scope_presets.py's OUTS: a glob would
# silently adopt any future directory that matched and start writing generated code into it.
OUTS = (
    ROOT / "frontend" / "src" / "ruleDetails.js",
)

sys.path.insert(0, str(ROOT / "api"))

_WCAG = re.compile(r"^\*\*WCAG:\*\*\s*(\d+\.\d+\.\d+)\s+(.*?)\s*\(Level\s+(A+)\)\s*$", re.M)
_SEV = re.compile(r"^\*\*Severity:\*\*\s*(\S+)", re.M)
_FIX = re.compile(r"^\*\*Fix mode:\*\*\s*(\S+)", re.M)
_SRC = re.compile(r"^\*\*Source:\*\*\s*`([^`]+)`", re.M)
_TITLE = re.compile(r"^#\s+(\S+)\s+—\s+(.*?)\s*$", re.M)


def _section(md: str, heading: str) -> str | None:
    """The prose under `## heading`, up to the next `##`. None when the section is absent."""
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", md, re.M | re.S)
    if not m:
        return None
    # Collapse to a single paragraph: the UI renders this inline, and the markdown's own line
    # wrapping is an artifact of the file, not of the sentence.
    text = " ".join(line.strip() for line in m.group(1).strip().splitlines() if line.strip())
    return text or None


def _parse(path: Path) -> dict:
    md = path.read_text()
    rule_id = path.stem

    title = _TITLE.search(md)
    wcag = _WCAG.search(md)
    sev = _SEV.search(md)
    fix = _FIX.search(md)
    checks = _section(md, "What it checks")

    missing = [n for n, v in (("# title", title), ("**WCAG:**", wcag), ("**Severity:**", sev),
                              ("**Fix mode:**", fix), ("## What it checks", checks)) if not v]
    if missing:
        raise SystemExit(
            f"{path.relative_to(ROOT)}: cannot parse {', '.join(missing)}.\n"
            "  A rule doc that exists but does not parse is a hard error — skipping it would make\n"
            "  a broken heading look exactly like a rule nobody has documented yet.")

    src = _SRC.search(md)
    return {
        "id": rule_id,
        "title": title.group(2),
        "sc": wcag.group(1),
        "scName": wcag.group(2),
        "level": wcag.group(3),
        "severity": sev.group(1),
        "fixMode": fix.group(1),
        "source": src.group(1) if src else None,
        "checks": checks,
        # None, never a guess — see the module docstring.
        "remediation": _section(md, "Fix mode rationale"),
    }


def _rules() -> list[dict]:
    return sorted((_parse(p) for p in sorted(DOCS.glob("*.md")) if p.stem != "README"),
                  key=lambda r: (r["sc"], r["id"]))


HEADER = """\
// GENERATED FILE — do not edit by hand.
//
// Source: docs/rules/*.md  ·  Regenerate: python scripts/gen_rule_details.py
// Guarded by: tests/test_rule_details_sync.py (CI fails on drift)
//
// Per-rule assessment and remediation detail — what ACP actually checks for a criterion, in the
// words an engineer maintains beside the detector. `remediation` is null for rules whose doc has
// no "Fix mode rationale" section; the UI must say nothing there rather than invent it.
"""


def render() -> str:
    import assessment_policy as ap  # noqa: PLC0415

    rules = _rules()
    by_sc: dict[str, list[str]] = {}
    for r in rules:
        by_sc.setdefault(r["sc"], []).append(r["id"])

    lines = [HEADER, "export const RULE_DETAILS = {"]
    for r in rules:
        lines.append(f"  {json.dumps(r['id'])}: {{")
        for k in ("title", "sc", "scName", "level", "severity", "fixMode", "source",
                  "checks", "remediation"):
            lines.append(f"    {k}: {json.dumps(r[k])},")
        lines.append("  },")
    lines.append("}")
    lines.append("")
    lines.append("// criterion → the rule ids that implement it, so a per-SC panel can list them.")
    lines.append("export const RULES_BY_SC = {")
    for sc, ids in sorted(by_sc.items(), key=lambda kv: [int(n) for n in kv[0].split(".")]):
        lines.append(f"  {json.dumps(sc)}: {json.dumps(ids)},")
    lines.append("}")
    lines.append("")
    lines.append("// The criteria Mova iO tracks (column G) — 17 of the 20-check document core.")
    lines.append("// Defined in api/assessment_policy.py:MOVA_TRACKED; see there for how it")
    lines.append("// relates to the other four totals this product quotes.")
    lines.append("export const TRACKED_17 = new Set(" +
                 json.dumps(sorted(ap.MOVA_TRACKED, key=lambda x: [int(n) for n in x.split(".")])) +
                 ")")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap_ = argparse.ArgumentParser(description=__doc__)
    ap_.add_argument("--check", action="store_true", help="exit 1 if a generated file is stale")
    ap_.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = ap_.parse_args()

    want = render()
    if args.stdout:
        sys.stdout.write(want)
        return 0

    rules = _rules()
    documented = sum(1 for r in rules if r["remediation"])
    note = (f"{len(rules)} rules · {documented} with a remediation rationale, "
            f"{len(rules) - documented} without")

    if args.check:
        stale = [(o, o.read_text() if o.exists() else "") for o in OUTS
                 if (o.read_text() if o.exists() else "") != want]
        if not stale:
            print(f"rule details current — {note}")
            return 0
        for out, have in stale:
            rel = out.relative_to(ROOT)
            print(f"{rel} is stale — regenerate with: python scripts/gen_rule_details.py",
                  file=sys.stderr)
            sys.stderr.writelines(difflib.unified_diff(
                have.splitlines(keepends=True), want.splitlines(keepends=True),
                fromfile=f"{rel} (on disk)", tofile=f"{rel} (from docs/rules)"))
        return 1

    for out in OUTS:
        out.write_text(want)
        print(f"wrote {out.relative_to(ROOT)}")
    print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
