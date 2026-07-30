#!/usr/bin/env python3
"""Emit the operator scope presets to the frontend, so the SPA has no second copy of them.

`SCOPE_PRESETS` (api/store.py, re-exported from api/assessment_policy.py) is the authoritative
answer to "which (criterion, format) pairs did the operator put in scope for this engagement".
The backend already gates on it — `in_scope()` is consulted inside `_rule_outcome`, so an
out-of-scope pair reads NOT_EVALUATED in every stored trace.

The SPA needs the same list to scope what it DISPLAYS, and the obvious shortcut — retype the 14
criteria into a JS constant — is the thing this script exists to prevent. Two hand-maintained
copies of one customer-agreed checklist drift, and the surface they drift on is a panel a
customer's accessibility specialist reads. `documents20.js` is the cautionary precedent: it
calls itself the "single source of truth" for the 20-check core and is nonetheless a hand-typed
list with no mechanical tie to anything.

Why build-time generation rather than an endpoint. The SPA ships in two modes and the panel has
to be right in both: `VITE_SIM=false` (deploy/public/Dockerfile — real backend) and
`VITE_SIM=true` (the offline synthetic-data demo, which is also the `npm run dev` default). An
endpoint answers only in the first, so a SIM build would still need a fallback constant — the
second copy again, on the surface where nobody would notice it going stale. A generated module
is one copy, derived, and `--check` fails CI the moment the Python moves.

Usage:
    python scripts/gen_scope_presets.py            # write frontend/src/scopePresets.js
    python scripts/gen_scope_presets.py --stdout    # print it instead
    python scripts/gen_scope_presets.py --check     # exit 1 (with a diff) if the file is stale

Pinned by tests/test_scope_presets_frontend_sync.py.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "src" / "scopePresets.js"

# Read through api/store.py rather than api/assessment_policy.py. PR #94 moves the definitions
# into assessment_policy and re-exports them from store, so store's namespace is the name that
# is correct both before and after that lands.
sys.path.insert(0, str(ROOT / "api"))

HEADER = """\
// GENERATED FILE — do not edit by hand.
//
// Source: SCOPE_PRESETS in api/store.py (defined in api/assessment_policy.py once #94 lands).
// Regenerate:  python scripts/gen_scope_presets.py
// Guarded by:  tests/test_scope_presets_frontend_sync.py  (CI fails on drift)
//
// An operator scope is the narrower of two different questions. RULE_FORMATS says which
// (criterion, format) pairs ACP *can* evaluate — a fact about the code. A scope preset says
// which of those the customer *asked* to have evaluated for this engagement — a choice. The
// backend gates on it inside `_rule_outcome`, so an out-of-scope pair reads NOT_EVALUATED in
// every stored trace; this file is the same list, for the surfaces that display it.
"""


def _presets() -> dict[str, dict[str, list[str]]]:
    import store  # noqa: PLC0415 — after the sys.path insert above

    return {
        name: {sc: sorted(fmts) for sc, fmts in sorted(scope.items())}
        for name, scope in sorted(store.SCOPE_PRESETS.items())
    }


def render() -> str:
    presets = _presets()
    lines = [HEADER, "export const SCOPE_PRESETS = {"]
    for name, scope in presets.items():
        lines.append(f"  {json.dumps(name)}: {{")
        for sc, fmts in scope.items():
            fmt_list = ", ".join(json.dumps(f) for f in fmts)
            lines.append(f"    {json.dumps(sc)}: [{fmt_list}],")
        lines.append(f"  }},   // {len(scope)} criteria")
    lines.append("}")
    lines.append("")
    lines.append(
        "// The criteria a preset covers, as a Set — the estate-level question ('is this\n"
        "// criterion in scope at all'), as distinct from the per-format one below."
    )
    lines.append(
        "export const scopeCriteria = (name) => new Set(Object.keys(SCOPE_PRESETS[name] || {}))"
    )
    lines.append("")
    lines.append(
        "// The per-(criterion, format) question, mirroring the backend's `in_scope()`: false only\n"
        "// when a scope IS set and it excludes this pair. An unknown format is never excluded —\n"
        "// the gate honours a deliberate choice, it does not invent one from an unparsed filename."
    )
    lines.append("export const inScope = (name, sc, fmt) => {")
    lines.append("  const scope = SCOPE_PRESETS[name]")
    lines.append("  if (!scope) return true")
    lines.append("  if (fmt == null) return true")
    lines.append("  const fmts = scope[sc]")
    lines.append("  return Boolean(fmts && fmts.includes(fmt))")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 if the generated file is stale")
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = ap.parse_args()

    want = render()
    if args.stdout:
        sys.stdout.write(want)
        return 0
    if args.check:
        have = OUT.read_text() if OUT.exists() else ""
        if have == want:
            return 0
        rel = OUT.relative_to(ROOT)
        print(f"{rel} is stale — regenerate with: python scripts/gen_scope_presets.py",
              file=sys.stderr)
        sys.stderr.writelines(difflib.unified_diff(
            have.splitlines(keepends=True), want.splitlines(keepends=True),
            fromfile=f"{rel} (on disk)", tofile=f"{rel} (from api/store.py)"))
        return 1
    OUT.write_text(want)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
