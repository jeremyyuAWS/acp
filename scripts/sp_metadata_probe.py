#!/usr/bin/env python3
"""Prove — against a real tenant — which SharePoint-native metadata fields ACP can actually read.

THIS SCRIPT IS THE PHASE 2 EXIT GATE, not a diagnostic. The gate says "every supported field is
proven against the tenant, with 'unavailable' distinguished from 'not configured'", and that is a
claim nobody can make from a unit test: every Graph shape in api/sp_metadata.py is drawn from
documentation, several are marked UNVERIFIED, and this repo has been bitten before by a plausible
shape that was reasoned about instead of run (CLAUDE.md, the .pdf ground-truth corpus). A fixture
can only prove that ACP handles a response correctly; it cannot prove the tenant sends one.

WHAT IT PRINTS is the evidence table the gate asks for — per field, across a real sample:

    field               present  not_configured  unavailable  not_applicable
    content_type            94              6            0              0
    retention_label          0              0          100              0   ← ACP's problem
    sensitivity_label        0              0          100              0   ← not requested
    managed_columns         94              6            0              0

Read the columns, not the totals. A field that is `not_configured` everywhere is an ANSWER: the
tenant does not use it, stop building for it. A field that is `unavailable` everywhere is a TASK,
and the reason column says whose: a missing scope, a Graph version, a select this tenant refuses.
The two produce the same empty cell in every report ACP renders, which is exactly why they are
worth one run of this script to tell apart.

USAGE

    export SP_TOKEN='<a delegated Graph access token>'
    python3 scripts/sp_metadata_probe.py --site 'contoso.sharepoint.com,<guid>,<guid>'
    python3 scripts/sp_metadata_probe.py --onedrive            # the signed-in user's drive
    python3 scripts/sp_metadata_probe.py --site '<id>' --json  # machine-readable, for a report

Get the token the way the app does — sign in to ACP with Microsoft and copy the value the SPA
sends as `X-SP-Token` — or from any tool that mints a delegated token with User.Read +
Files.Read.All + Sites.Read.All. It is read-only: this script issues GETs and writes nothing.

The sample is bounded (--limit, default 100 documents) because the gate is about which fields
ARRIVE, not about the size of the estate: a hundred documents across a library settles every
question here, and walking a 6,000-file library to answer it would spend a customer's Graph
budget on a question already answered.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner            # noqa: E402
import sp_metadata        # noqa: E402

STATES = (sp_metadata.PRESENT, sp_metadata.NOT_CONFIGURED,
          sp_metadata.UNAVAILABLE, sp_metadata.NOT_APPLICABLE)


def _sample(token: str, site: str | None, limit: int) -> tuple[list[dict], list[str]]:
    """Walk a bounded sample and return (normalized metadata records, notes).

    Deliberately the REAL walk (scanner._sp_list), not a bespoke request: a probe that asked
    Graph its own way would prove something about the probe. The whole value here is that the
    path under test is the path a scan takes — the same tiered $select, the same expansion, the
    same fallback — so what it reports is what a scan would record.
    """
    notes: list[str] = []
    inventory: list[dict] = []
    scope: dict = {}
    files = scanner._sp_list(token, limit, site=site, inventory_out=inventory, scope_out=scope)
    metas = [f["sp_metadata"] for f in files if isinstance(f.get("sp_metadata"), dict)]
    # The non-scannable half carries the same metadata and is just as good evidence — a probe
    # that looked only at documents would miss a library that is mostly images, which is a large
    # share of a real estate.
    for row in inventory:
        raw = row.get("sp_metadata")
        if raw:
            try:
                blob = json.loads(raw) if isinstance(raw, str) else raw
                metas.append({"fields": {k: {"value": None, "state": v, "reason":
                                             (blob.get("reasons") or {}).get(k)}
                                         for k, v in (blob.get("availability") or {}).items()}})
            except Exception:  # noqa: BLE001
                notes.append("one inventory row carried an unreadable sp_metadata blob")
    if not files and not inventory:
        notes.append("the sample is EMPTY — this proves nothing about any field. Check the site "
                     "id, the token's scopes, and that the library actually holds documents.")
    if scope.get("inventory", {}).get("truncated"):
        notes.append(f"the walk stopped at the {limit}-document sample cap, which is expected")
    return metas, notes


def _reasons(metas: list[dict]) -> dict[str, str]:
    """One representative reason per field that was ever `unavailable` — the column that turns a
    zero into an action."""
    out: dict[str, str] = {}
    for m in metas:
        for name, f in (m.get("fields") or {}).items():
            if f.get("state") == sp_metadata.UNAVAILABLE and f.get("reason") and name not in out:
                out[name] = f["reason"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", help="Graph site id (contoso.sharepoint.com,<guid>,<guid>)")
    ap.add_argument("--onedrive", action="store_true",
                    help="probe the signed-in user's OneDrive instead of a site")
    ap.add_argument("--limit", type=int, default=100, help="documents to sample (default 100)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if not args.site and not args.onedrive:
        ap.error("give --site <id> or --onedrive")
    token = os.environ.get("SP_TOKEN", "").strip()
    if not token:
        print("SP_TOKEN is not set. Sign in to ACP with Microsoft and copy the X-SP-Token value, "
              "or mint a delegated token with User.Read + Files.Read.All + Sites.Read.All.",
              file=sys.stderr)
        return 2

    try:
        metas, notes = _sample(token, args.site if not args.onedrive else None, args.limit)
    except PermissionError as e:
        # The one failure worth its own exit path: it is a scope problem, it is the commonest
        # thing this script will hit in a new tenant, and the message already names the consent.
        print(f"Graph refused the walk: {e}", file=sys.stderr)
        return 3

    table = sp_metadata.summarize_availability(metas)
    reasons = _reasons(metas)

    if args.json:
        print(json.dumps({"sampled": len(metas), "fields": table, "reasons": reasons,
                          "notes": notes}, indent=2))
        return 0

    where = "OneDrive" if args.onedrive else f"site {args.site}"
    print(f"\nSharePoint-native metadata probe — {where}, {len(metas)} items sampled\n")
    width = max([len(f) for f in table] + [16])
    print(f"{'field'.ljust(width)}  {'present':>8}{'not_cfg':>9}{'unavail':>9}{'n/a':>6}")
    print("-" * (width + 34))
    for name in sorted(table):
        c = table[name]
        print(f"{name.ljust(width)}  " + "".join([
            f"{c[sp_metadata.PRESENT]:>8}", f"{c[sp_metadata.NOT_CONFIGURED]:>9}",
            f"{c[sp_metadata.UNAVAILABLE]:>9}", f"{c[sp_metadata.NOT_APPLICABLE]:>6}"]))
    if reasons:
        print("\nWhy a field was UNAVAILABLE (ACP's problem to fix, not the tenant's):")
        for name, why in sorted(reasons.items()):
            print(f"  {name}: {why}")
    if notes:
        print("\nNotes:")
        for n in notes:
            print(f"  - {n}")
    # Said out loud, because a table of zeros in the `unavailable` column is the result this
    # script exists to produce and it is easy to read as "nothing happened".
    unread = sorted(n for n, c in table.items() if c[sp_metadata.UNAVAILABLE] and
                    not c[sp_metadata.PRESENT])
    print("\nVerdict: " + ("every field this build reads arrived from the tenant."
                           if not unread else
                           "these fields never arrived and are ACP's to fix before the gate "
                           "passes: " + ", ".join(unread)))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
