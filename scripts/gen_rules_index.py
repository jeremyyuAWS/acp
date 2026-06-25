#!/usr/bin/env python3
"""Generate the rules/ developer index from the authoritative rule sources.

This makes rules/ a *derived* single source of truth: it stitches together the
three places rules actually live —

  1. config/rule-catalog.json   — Office (.docx/.pptx/.xlsx) + PDF engine rules
                                   (the .NET DigitalA11y analysers + Python PDF engine)
  2. frontend/src/rules/*.js     — the HTML deterministic engine (one module per SC)
  3. test-corpus/manifest.json   — synthetic fixtures that exercise the rules

…into one folder per WCAG Success Criterion, each with a README a human owner can
read top-to-bottom to know exactly what they're responsible for and which files to
change.

Run after any rule change:
    python scripts/gen_rules_index.py

The per-SC READMEs are GENERATED — edit the sources above, not the output. The
top-level rules/README.md is hand-maintained (ownership table + workflow).
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config" / "rule-catalog.json"
FE_RULES = ROOT / "frontend" / "src" / "rules"
MANIFEST = ROOT / "test-corpus" / "manifest.json"
OUT = ROOT / "rules"

# WCAG 2.1 Understanding-doc URL slugs. Auto-derived from the SC name where the
# slug == kebab-case(name); listed explicitly only where W3C's slug differs.
_SLUG_OVERRIDE = {
    "1.4.3": "contrast-minimum",
    "1.4.11": "non-text-contrast",
    "2.4.2": "page-titled",
    "2.4.4": "link-purpose-in-context",
    "2.4.6": "headings-and-labels",
    "4.1.2": "name-role-value",
    "3.1.4": "abbreviations",
    "1.3.2": "meaningful-sequence",
}


def _slug(sc: str, name: str) -> str:
    if sc in _SLUG_OVERRIDE:
        return _SLUG_OVERRIDE[sc]
    s = name.lower()
    s = re.sub(r"\(.*?\)", "", s)          # drop "(Minimum)" etc.
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _understanding_url(sc: str, name: str) -> str:
    return f"https://www.w3.org/WAI/WCAG21/Understanding/{_slug(sc, name)}.html"


def _sc_sort_key(sc: str):
    return [int(p) for p in sc.split(".")]


def load_catalog() -> dict[str, list[dict]]:
    """Return {sc: [rule, ...]} from the Office/PDF catalog, rule['_engine'] tagged."""
    data = json.loads(CATALOG.read_text())
    by_sc: dict[str, list[dict]] = {}
    for engine, rules in data.items():
        if not isinstance(rules, list):
            continue
        for r in rules:
            r = {**r, "_engine": engine}
            by_sc.setdefault(r["wcag_sc"], []).append(r)
    return by_sc


def load_frontend() -> dict[str, dict]:
    """Return {sc: {file, name, level, fixMode}} parsed from frontend/src/rules/*.js meta."""
    out: dict[str, dict] = {}
    for f in sorted(FE_RULES.glob("wcag-*.js")):
        text = f.read_text()
        m = re.search(r"export const meta\s*=\s*\{(.*?)\}", text, re.S)
        if not m:
            continue
        body = m.group(1)
        def field(key):
            mm = re.search(rf"{key}\s*:\s*'([^']*)'", body)
            return mm.group(1) if mm else ""
        sc = field("id")
        if sc:
            out[sc] = {"file": f"frontend/src/rules/{f.name}",
                       "name": field("name"), "level": field("level"),
                       "fixMode": field("fixMode")}
    return out


def load_manifest() -> list[dict]:
    try:
        return json.loads(MANIFEST.read_text())
    except Exception:
        return []


def fixtures_for(sc: str, name: str, manifest: list[dict]) -> list[dict]:
    """Best-effort: corpus fixtures whose description mentions this SC's concern."""
    keywords = {
        "1.1.1": ["alt", "image", "non-text"],
        "1.3.1": ["table", "header", "heading", "structure", "relationship"],
        "1.3.2": ["order", "sequence", "reading"],
        "1.4.1": ["color", "colour"],
        "1.4.3": ["contrast"],
        "2.4.2": ["title", "titled"],
        "2.4.3": ["focus order", "reading order", "tab order"],
        "2.4.4": ["link", "vague", "ambiguous", "click here"],
        "2.4.6": ["heading", "label"],
        "3.1.1": ["lang", "language"],
    }.get(sc, [name.lower().split()[0]])
    hits = []
    for entry in manifest:
        desc = (entry.get("desc", "") + " " + entry.get("file", "")).lower()
        if any(k in desc for k in keywords):
            hits.append(entry)
    return hits


def render_sc(sc: str, name: str, level: str, cat_rules: list[dict],
              fe: dict | None, fixtures: list[dict]) -> str:
    lines = [
        f"# WCAG {sc} — {name}",
        "",
        "> **GENERATED FILE.** Edit the sources (rule-catalog.json, "
        "frontend/src/rules/, test-corpus/manifest.json), then run "
        "`python scripts/gen_rules_index.py`. Do not hand-edit.",
        "",
        f"- **Success Criterion:** {sc} {name} (Level {level or '—'})",
        f"- **Understanding doc:** {_understanding_url(sc, name)}",
        f"- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)",
        "",
        "## Where this is checked",
        "",
    ]
    if not cat_rules and not fe:
        lines.append("_No engine currently implements this SC._")
    # Office / PDF engines
    if cat_rules:
        lines += ["### Office & PDF engines", "",
                  "| Engine | Rule ID | Severity | Fix mode | Source |",
                  "|--------|---------|----------|----------|--------|"]
        for r in sorted(cat_rules, key=lambda x: x["_engine"]):
            lines.append(
                f"| `{r['_engine']}` | `{r['id']}` | {r.get('severity','—')} "
                f"| {r.get('fix_mode','—')} | `{r.get('source','—')}` |")
        lines.append("")
    # HTML engine
    if fe:
        lines += ["### HTML engine (deterministic, in-app)", "",
                  f"- Module: [`{fe['file']}`](../../{fe['file']})",
                  f"- Fix mode: `{fe['fixMode']}`",
                  "- Exports `check(doc)` and `fix(doc)` — see "
                  "[frontend/src/rules/index.js](../../frontend/src/rules/index.js).",
                  ""]
    # How to change
    lines += ["## How to change this rule", ""]
    if cat_rules:
        offices = sorted({r["_engine"] for r in cat_rules})
        lines.append(
            f"- **Office/PDF ({', '.join(offices)}):** the detection logic lives in "
            "the partner DigitalA11y engine (see `source` paths above). You own the "
            "*mapping and parameters* here, not the .NET source. To change a threshold "
            "or disable a rule, edit `config/rule-catalog.json` and/or the active rubric "
            "(`config/rubric.active.json` → `disabled_rules`).")
    if fe:
        lines.append(
            f"- **HTML:** edit [`{fe['file']}`](../../{fe['file']}). Change `check()` "
            "to alter detection, `fix()` to alter the deterministic remediation. The "
            "orchestrator picks it up automatically — no other file changes needed.")
    lines.append("")
    # Fixtures
    lines += ["## Test fixtures", ""]
    if fixtures:
        lines += ["| File | What it exercises |", "|------|-------------------|"]
        for fx in fixtures:
            lines.append(f"| `test-corpus/files/{fx['file']}` | {fx.get('desc','')} |")
    else:
        lines.append("_No dedicated fixture yet — add one to `test-corpus/` and "
                     "regenerate._")
    lines.append("")
    return "\n".join(lines)


def main():
    cat = load_catalog()
    fe = load_frontend()
    manifest = load_manifest()

    # Canonical SC universe = union of catalog + frontend.
    names: dict[str, str] = {}
    levels: dict[str, str] = {}
    for sc, rules in cat.items():
        names[sc] = rules[0].get("wcag_display", sc)
        levels[sc] = rules[0].get("wcag_level", "")
    for sc, meta in fe.items():
        names.setdefault(sc, meta["name"])
        levels.setdefault(sc, meta["level"])

    OUT.mkdir(exist_ok=True)
    index_rows = []
    for sc in sorted(names, key=_sc_sort_key):
        slug = f"wcag-{sc.replace('.', '-')}"
        d = OUT / slug
        d.mkdir(exist_ok=True)
        fixtures = fixtures_for(sc, names[sc], manifest)
        (d / "README.md").write_text(
            render_sc(sc, names[sc], levels[sc], cat.get(sc, []),
                      fe.get(sc), fixtures))
        engines = sorted({r["_engine"] for r in cat.get(sc, [])})
        if sc in fe:
            engines.append("html")
        index_rows.append((sc, names[sc], levels[sc], engines, slug))

    print(f"Generated {len(index_rows)} per-SC READMEs under rules/")
    # Emit a machine-readable index too (for CI / tooling).
    (OUT / "index.json").write_text(json.dumps(
        [{"sc": sc, "name": n, "level": lv, "engines": e, "dir": s}
         for sc, n, lv, e, s in index_rows], indent=2) + "\n")
    print("Wrote rules/index.json")


if __name__ == "__main__":
    main()
