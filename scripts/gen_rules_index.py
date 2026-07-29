#!/usr/bin/env python3
"""Generate the rules/ developer index from the authoritative rule sources.

This makes rules/ a *derived* single source of truth: it stitches together the
four places rules actually live —

  1. config/rule-catalog.json   — Office (.docx/.pptx/.xlsx) + PDF engine rules
                                   (the .NET DigitalA11y analysers + Python PDF engine)
  2. frontend/src/rules/*.js     — the HTML deterministic engine (one module per SC)
  3. api/office_structure.py     — FIRST-PARTY Python checks layered on top of the
     api/textchecks.py             engine findings for Office/PDF (ADR 0023 review
     api/ocr.py                    findings + deterministic structural checks). These
                                   are NOT in rule-catalog.json: that file is the
                                   ADR 0002 engine-rule contract (A/AA only, one
                                   docs/rules/<ID>.md per rule), and these checks
                                   include AAA criteria and carry no per-rule doc.
                                   They are read straight from the code instead, so
                                   this index cannot drift from what actually runs.
  4. test-corpus/manifest.json   — synthetic fixtures that exercise the rules

…into one folder per WCAG Success Criterion, each with a README a human owner can
read top-to-bottom to know exactly what they're responsible for and which files to
change.

Run after any rule change:
    python scripts/gen_rules_index.py

The per-SC READMEs are GENERATED — edit the sources above, not the output. The
top-level rules/README.md is hand-written prose EXCEPT its ownership table, which is
regenerated between the markers in it: the criteria list and Engines column are derived
here, while each row's Owner cell is parsed out and written back, so a claim survives
regeneration and only the part a human actually maintains is left to a human.
"""
from __future__ import annotations
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config" / "rule-catalog.json"
FE_RULES = ROOT / "frontend" / "src" / "rules"
MANIFEST = ROOT / "test-corpus" / "manifest.json"
API = ROOT / "api"
OUT = ROOT / "rules"

# WCAG 2.1 Understanding-doc URL slugs. Auto-derived from the SC name where the
# slug == kebab-case(name); listed explicitly only where W3C's slug differs.
# Note _slug() strips parenthesised qualifiers, so every SC whose W3C slug KEEPS
# them ("Contrast (Enhanced)" -> contrast-enhanced) must be listed here.
_SLUG_OVERRIDE = {
    "1.4.3": "contrast-minimum",
    "1.4.6": "contrast-enhanced",
    "1.4.9": "images-of-text-no-exception",
    "1.4.11": "non-text-contrast",
    "2.4.2": "page-titled",
    "2.4.4": "link-purpose-in-context",
    "2.4.6": "headings-and-labels",
    "2.4.9": "link-purpose-link-only",
    "4.1.2": "name-role-value",
    "3.1.4": "abbreviations",
    "1.3.2": "meaningful-sequence",
}

# WCAG conformance level per SC. rule-catalog.json carries wcag_level for engine
# rules, but the first-party checks are read from code, which does not state a
# level — and several are AAA (which the ADR 0002 catalog contract forbids).
_SC_LEVEL = {
    "1.1.1": "A",   "1.2.1": "A",   "1.2.2": "A",   "1.2.3": "A",
    "1.3.1": "A",   "1.3.2": "A",   "1.3.3": "A",   "1.3.4": "AA",  "1.3.5": "AA",
    "1.4.1": "A",   "1.4.2": "A",   "1.4.3": "AA",  "1.4.4": "AA",  "1.4.5": "AA",
    "1.4.6": "AAA", "1.4.8": "AAA", "1.4.9": "AAA",
    "1.4.10": "AA", "1.4.11": "AA", "1.4.12": "AA",
    "2.1.1": "A",   "2.1.2": "A",
    "2.4.1": "A",   "2.4.2": "A",   "2.4.3": "A",   "2.4.4": "A",
    "2.4.6": "AA",  "2.4.7": "AA",  "2.4.9": "AAA", "2.4.10": "AAA",
    "2.5.3": "A",   "2.5.8": "AA",
    "3.1.1": "A",   "3.1.2": "AA",  "3.1.4": "AAA", "3.1.5": "AAA",
    "3.3.2": "A",   "4.1.2": "A",
}

_ALL_FORMATS = ("docx", "pptx", "xlsx", "pdf")
# Modules whose findings are appended to every scan regardless of format, and the
# formats they actually reach. Mirrors api/scanner.py's _analyse_one() wiring and
# the same convention tests/test_rule_formats.py derives from.
_BROAD_SOURCES = {
    "textchecks.py": _ALL_FORMATS,   # 1.3.3 sensory, 3.1.2 language-of-parts, 3.1.5
    "ocr.py": _ALL_FORMATS,          # 1.4.5 / 1.4.9 images-of-text (OCR)
}

# api/scanner.py is the HTML engine, and was missing from this generator entirely — so every
# HTML_* rule it emits was absent from rules/, and a criterion backed by a shipped backend
# detector read as frontend-module-only. That is the same false-coverage failure the module
# docstring says this index exists to prevent, one source short.
#
# Declared per FUNCTION rather than per module (unlike _BROAD_SOURCES above): scanner.py also
# orchestrates the office and PDF paths, so a module-level entry would stamp "html" on any rule
# a future edit adds to those. _analyse_one() dispatches this one on HTML_EXTS (.html/.htm,
# which are the single capability format "html"). Anything emitting rules outside the declared
# functions raises rather than being quietly dropped — silent omission is what this fixes.
_SCANNER_SOURCES = {
    "_analyse_html": ("html",),
}
_WCAG_STR = re.compile(r"^(\d+\.\d+\.\d+)\s+(.+)$")


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


def _const_strs(nodes) -> list[str]:
    return [n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _severities() -> frozenset[str]:
    """The rubric's severity vocabulary. A severity sits beside the rule id in every finding
    shape and is SHOUTY_CASE too, so without this it reads as a second rule id and the index
    grows phantom rules called `SERIOUS`/`MODERATE`. Read from the rubric rather than listed
    here, so a new severity cannot start appearing as a rule the day it is introduced."""
    try:
        weights = json.loads((ROOT / "config" / "rubric.default.json").read_text())
        return frozenset(k for k in weights["severity_weights"] if not k.startswith("_"))
    except Exception:
        return frozenset({"CRITICAL", "SERIOUS", "MODERATE", "MINOR", "REVIEW"})


_SEVERITIES = _severities()


def _rules_in(node: ast.AST) -> set[tuple[str, str, str]]:
    """Every (rule_id, sc, sc_name) literal emitted anywhere under `node`.

    Findings are built in four shapes — `_finding(id, wcag, severity)`,
    `_review_finding(id, wcag, detail)` / `_duplicate_href_findings(links, id, wcag)`,
    bare `{"ruleId": ..., "wcag": ...}` dicts, and a TABLE of rows a loop turns into findings
    (`for worst, rule_id, wcag, severity in ((…, "PDF_LOW_CONTRAST_AA", "1.4.3 …", "SERIOUS"),
    …)`). Rather than special-case each callee by name, pair the literals structurally: within
    one Call's positional args, one Dict's keys, or ONE ROW of such a table there is at most one
    "X.Y.Z Name" string, and the rule id is the SHOUTY_CASE constant beside it.

    Table rows pair at the row, never at the sequence that holds them: direct elements only, so
    a two-row table cannot cross-multiply each rule id with the other row's criterion.
    """
    found: set[tuple[str, str, str]] = set()

    def _pair(rule_ids: list[str], wcags: list[str]) -> None:
        scs = [m.groups() for w in wcags if (m := _WCAG_STR.match(w))]
        ids = [r for r in rule_ids
               if re.fullmatch(r"[A-Z][A-Z0-9_]{3,}", r) and r not in _SEVERITIES]
        for sc, name in scs:
            for rid in ids:
                found.add((rid, sc, name.strip()))

    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            args = _const_strs(sub.args)
            _pair(args, args)
        elif isinstance(sub, (ast.Tuple, ast.List, ast.Set)):
            elems = _const_strs(sub.elts)
            _pair(elems, elems)
        elif isinstance(sub, ast.Dict):
            pairs = {k.value: v.value for k, v in zip(sub.keys, sub.values)
                     if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)}
            if "ruleId" in pairs and "wcag" in pairs:
                _pair([pairs["ruleId"]], [pairs["wcag"]])
    return found


def _dispatch_formats(tree: ast.Module) -> dict[str, list[str]]:
    """{check_function_name: [formats]} read from office_structure.checks_for().

    checks_for() IS the wiring — a function that exists but is never dispatched is
    not coverage, so the dispatcher is the only honest source for which formats a
    check actually reaches.
    """
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "checks_for"), None)
    if fn is None:
        raise SystemExit("gen_rules_index: office_structure.checks_for() not found — "
                         "the first-party dispatch moved; update this generator.")
    out: dict[str, list[str]] = {}
    for branch in [n for n in ast.walk(fn) if isinstance(n, ast.If)]:
        exts = [s.lstrip(".") for s in _const_strs(ast.walk(branch.test))
                if s.startswith(".")]
        if not exts:
            continue
        for call in [n for n in ast.walk(branch) if isinstance(n, ast.Call)]:
            if isinstance(call.func, ast.Name):
                out.setdefault(call.func.id, []).extend(exts)
    return {k: sorted(set(v)) for k, v in out.items()}


def load_first_party() -> dict[str, list[dict]]:
    """{sc: [{id, formats, source, name}, ...]} for the first-party Python checks.

    Read from the code itself — these deliberately do NOT live in
    rule-catalog.json (see the module docstring), so code is the only source of
    truth available, and reading it directly is what keeps this index honest.
    """
    by_sc: dict[str, list[dict]] = {}

    def _add(rid, sc, name, formats, source):
        entry = {"id": rid, "formats": sorted(formats), "source": source, "name": name}
        if not any(e["id"] == rid and e["source"] == source for e in by_sc.setdefault(sc, [])):
            by_sc[sc].append(entry)

    struct = API / "office_structure.py"
    tree = ast.parse(struct.read_text())
    formats_of = _dispatch_formats(tree)
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        if fn.name not in formats_of:
            continue
        for rid, sc, name in _rules_in(fn):
            _add(rid, sc, name, formats_of[fn.name],
                 f"api/office_structure.py:{fn.name}")

    for mod, formats in _BROAD_SOURCES.items():
        path = API / mod
        if not path.exists():
            continue
        for rid, sc, name in _rules_in(ast.parse(path.read_text())):
            _add(rid, sc, name, formats, f"api/{mod}")

    # The HTML engine (see _SCANNER_SOURCES). Attributed to the function that emits each rule,
    # then checked for completeness: a rule literal anywhere else in scanner.py means the
    # declaration is stale, and failing loudly is the whole point — these rules were invisible
    # for as long as the file was simply not read.
    scanner_tree = ast.parse((API / "scanner.py").read_text())
    declared: set[tuple[str, str, str]] = set()
    for fn in [n for n in ast.walk(scanner_tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name in _SCANNER_SOURCES]:
        for rid, sc, name in _rules_in(fn):
            declared.add((rid, sc, name))
            _add(rid, sc, name, _SCANNER_SOURCES[fn.name], f"api/scanner.py:{fn.name}")
    stray = sorted(_rules_in(scanner_tree) - declared)
    if stray:
        raise SystemExit(
            "gen_rules_index: api/scanner.py emits rules outside the functions declared in "
            f"_SCANNER_SOURCES ({', '.join(sorted(_SCANNER_SOURCES))}) — "
            f"{', '.join(f'{r[0]} ({r[1]})' for r in stray)}. Add the emitting function and the "
            "formats it actually reaches, so the rule appears in rules/ instead of vanishing.")

    # Detectors migrated to the capability registry (api/rule_registry.py) live under
    # api/formats/<fmt>/detectors/. Without this walk they would vanish from the index the
    # moment they moved out of office_structure.py — the file looks smaller, the rules folder
    # quietly loses a criterion, and nothing fails. The format comes from the path, which is
    # the whole point of a format-first tree: the directory IS the declaration.
    for det in sorted((API / "formats").glob("*/detectors/*.py")):
        if det.name == "__init__.py":
            continue
        fmt = det.parent.parent.name
        rel = det.relative_to(API.parent)
        for rid, sc, name in _rules_in(ast.parse(det.read_text())):
            _add(rid, sc, name, [fmt], str(rel))

    return {sc: sorted(rules, key=lambda r: r["id"]) for sc, rules in by_sc.items()}


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
              fe: dict | None, fixtures: list[dict],
              fp_rules: list[dict] | None = None, owner: str = "") -> str:
    lines = [
        f"# WCAG {sc} — {name}",
        "",
        "> **GENERATED FILE.** Edit the sources (rule-catalog.json, "
        "frontend/src/rules/, api/office_structure.py, api/textchecks.py, "
        "api/ocr.py, test-corpus/manifest.json), then run "
        "`python scripts/gen_rules_index.py`. Do not hand-edit.",
        "",
        f"- **Success Criterion:** {sc} {name} (Level {level or '—'})",
        f"- **Understanding doc:** {_understanding_url(sc, name)}",
        # Mirrors the owner from rules/README.md's table, which is the one place a claim is
        # made. Hardcoding "_unassigned_" here meant the per-SC page flatly contradicted the
        # table the moment anyone claimed a criterion — and this page is the one a person
        # actually lands on from a finding.
        (f"- **Owner:** {owner} — see [rules/README.md](../README.md)" if owner else
         "- **Owner:** _unassigned_ — claim this SC in [rules/README.md](../README.md)"),
        "",
        "## Where this is checked",
        "",
    ]
    if not cat_rules and not fe and not fp_rules:
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
    # First-party Python checks (layered on top of the engine findings)
    if fp_rules:
        lines += ["### First-party checks (Python, in-repo)", "",
                  "| Rule ID | Formats | Source |",
                  "|---------|---------|--------|"]
        for r in fp_rules:
            lines.append(f"| `{r['id']}` | {', '.join(r['formats'])} | `{r['source']}` |")
        lines.append("")
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
    if fp_rules:
        lines.append(
            "- **First-party Python:** edit the `source` function above. These run "
            "in-process on top of the engine result (`api/scanner.py`), and "
            "`office_structure.checks_for()` decides which formats each one reaches — "
            "add a check there or it will never be dispatched.")
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


# ── Ownership table (rules/README.md) ────────────────────────────────────────
# The per-SC READMEs are fully generated; the top-level README is a HUMAN document — prose,
# workflow, and an Owner column somebody has to fill in. So only the table between the markers
# is rewritten, and each row's Owner cell survives the rewrite.
#
# That split follows the file's own instruction, "keep the ownership column current". Keeping
# the OWNER current is a job for a person. Keeping the criteria list and the Engines column
# current is not, and leaving it to one had exactly the effect this index exists to prevent:
# the table was written once and never revisited, so it listed 18 of 38 criteria and told a
# reader that 2.4.6 was html-only (docx, pptx, xlsx and pdf all check it) and that 1.3.2 had
# no html rule (HTML_VISUAL_REORDER). Derived columns belong to the generator.
_OWNERSHIP_BEGIN = "<!-- BEGIN GENERATED: ownership table (scripts/gen_rules_index.py) -->"
_OWNERSHIP_END = "<!-- END GENERATED: ownership table -->"
_DEFAULT_OWNER = "_unassigned_"
# Matches a row by its link target, which is the stable key — the display name and the
# Engines cell are both regenerated, so neither can be relied on to find the owner again.
_OWNER_ROW = re.compile(
    r"^\|\s*\[[^\]]*\]\(\./wcag-([\d-]+)/\)\s*\|[^|]*\|[^|]*\|\s*(.*?)\s*\|\s*$", re.M)


def _existing_owners(text: str) -> dict[str, str]:
    """{sc: owner} recovered from the table currently in the file, so a claim is never lost
    to a regeneration. Keyed off the folder slug (wcag-1-4-10 → 1.4.10)."""
    return {m.group(1).replace("-", "."): m.group(2) for m in _OWNER_ROW.finditer(text)}


def render_ownership_table(index_rows, owners: dict[str, str]) -> str:
    lines = ["| Success Criterion | Level | Engines | Owner |",
             "|-------------------|-------|---------|-------|"]
    for sc, name, level, engines, slug in index_rows:
        owner = owners.get(sc) or _DEFAULT_OWNER
        lines.append(f"| [{sc} {name}](./{slug}/) | {level} | {', '.join(engines)} | {owner} |")
    return "\n".join(lines)


def update_readme(index_rows) -> tuple[int, int]:
    """Rewrite the ownership table in place, preserving owners. Returns (criteria, claimed)."""
    path = OUT / "README.md"
    text = path.read_text()
    if _OWNERSHIP_BEGIN not in text or _OWNERSHIP_END not in text:
        raise SystemExit(
            f"gen_rules_index: rules/README.md is missing the ownership-table markers.\n"
            f"  expected: {_OWNERSHIP_BEGIN}\n"
            f"        and: {_OWNERSHIP_END}\n"
            "Restore them around the table. Without them the criteria list and Engines column "
            "silently go stale, which is the drift they exist to prevent.")
    owners = _existing_owners(text)
    head, _, rest = text.partition(_OWNERSHIP_BEGIN)
    _, _, tail = rest.partition(_OWNERSHIP_END)
    path.write_text(f"{head}{_OWNERSHIP_BEGIN}\n"
                    f"{render_ownership_table(index_rows, owners)}\n"
                    f"{_OWNERSHIP_END}{tail}")
    claimed = sum(1 for sc, _, _, _, _ in index_rows
                  if (owners.get(sc) or _DEFAULT_OWNER) != _DEFAULT_OWNER)
    return len(index_rows), claimed


def main():
    cat = load_catalog()
    fe = load_frontend()
    fp = load_first_party()
    manifest = load_manifest()

    # Canonical SC universe = union of catalog + frontend + first-party checks.
    names: dict[str, str] = {}
    levels: dict[str, str] = {}
    for sc, rules in cat.items():
        names[sc] = rules[0].get("wcag_display", sc)
        levels[sc] = rules[0].get("wcag_level", "")
    for sc, meta in fe.items():
        names.setdefault(sc, meta["name"])
        levels.setdefault(sc, meta["level"])
    for sc, rules in fp.items():
        # The emitted wcag string carries the display name ("1.4.11 Non-text
        # Contrast"), so first-party SCs are self-naming; only the level needs
        # the table.
        names.setdefault(sc, rules[0]["name"])
        levels.setdefault(sc, _SC_LEVEL.get(sc, ""))
    missing = sorted(sc for sc, lv in levels.items() if not lv)
    if missing:
        raise SystemExit(f"gen_rules_index: no WCAG level for {missing} — "
                         f"add them to _SC_LEVEL.")

    OUT.mkdir(exist_ok=True)
    # Read the claims BEFORE rendering — the per-SC pages carry the owner too, and
    # update_readme() below writes the same values back, so both surfaces agree.
    owners = _existing_owners((OUT / "README.md").read_text()) if (OUT / "README.md").exists() else {}
    index_rows = []
    for sc in sorted(names, key=_sc_sort_key):
        slug = f"wcag-{sc.replace('.', '-')}"
        d = OUT / slug
        d.mkdir(exist_ok=True)
        fixtures = fixtures_for(sc, names[sc], manifest)
        owner = owners.get(sc, "")
        (d / "README.md").write_text(
            render_sc(sc, names[sc], levels[sc], cat.get(sc, []),
                      fe.get(sc), fixtures, fp.get(sc),
                      owner="" if owner == _DEFAULT_OWNER else owner))
        engines = {r["_engine"] for r in cat.get(sc, [])}
        engines.update(f for r in fp.get(sc, []) for f in r["formats"])
        if sc in fe:
            engines.add("html")
        index_rows.append((sc, names[sc], levels[sc], sorted(engines), slug))

    print(f"Generated {len(index_rows)} per-SC READMEs under rules/")
    # Emit a machine-readable index too (for CI / tooling).
    (OUT / "index.json").write_text(json.dumps(
        [{"sc": sc, "name": n, "level": lv, "engines": e, "dir": s}
         for sc, n, lv, e, s in index_rows], indent=2) + "\n")
    print("Wrote rules/index.json")
    criteria, claimed = update_readme(index_rows)
    print(f"Updated rules/README.md ownership table — {criteria} criteria, {claimed} claimed")


if __name__ == "__main__":
    main()
