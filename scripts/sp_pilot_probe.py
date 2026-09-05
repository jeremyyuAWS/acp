#!/usr/bin/env python3
"""Read-only SharePoint pilot breadth probe.

Runs ACP's production enumerator over an explicit site list and emits one JSON evidence document.
The Microsoft token is read from ``ACP_SP_TOKEN`` only; it is never accepted on the command line,
where it would be exposed through shell history and process listings.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import scanner  # noqa: E402


def _site_ids(values: list[str], site_file: str | None) -> list[str]:
    sites = [value.strip() for value in values if value.strip()]
    if site_file:
        sites.extend(line.strip() for line in Path(site_file).read_text().splitlines()
                     if line.strip() and not line.lstrip().startswith("#"))
    return list(dict.fromkeys(sites))


def run_probe(token: str, sites: list[str], max_files: int) -> dict:
    scope: dict = {}
    started = time.monotonic()
    files = scanner._sp_list(token, max_files=max_files, sites=sites, scope_out=scope)
    elapsed = time.monotonic() - started
    rows = scope.get("sites") or []
    exceptions = [row for row in rows if row.get("status") not in ("complete",)]
    inventory = scope.get("inventory") or {}
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "requested_sites": len(sites),
        "reported_sites": len(rows),
        "documents_listed": len(files),
        "elapsed_seconds": round(elapsed, 3),
        "truncated": bool(inventory.get("truncated")),
        "throttled_retries": sum(int(row.get("throttled") or 0) for row in rows),
        "exception_count": len(exceptions),
        "exceptions": exceptions,
        "sites": rows,
        "inventory": inventory,
        "complete": len(rows) == len(sites) and not exceptions and not inventory.get("truncated"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe ACP SharePoint discovery across pilot sites")
    parser.add_argument("--site", action="append", default=[], help="Graph site id; repeatable")
    parser.add_argument("--site-file", help="Text file containing one Graph site id per line")
    parser.add_argument("--max-files", type=int, default=1_000_000,
                        help="Shared listing cap across all sites (default: 1,000,000)")
    parser.add_argument("--output", help="Write the JSON evidence to this path instead of stdout")
    args = parser.parse_args(argv)

    sites = _site_ids(args.site, args.site_file)
    if not sites:
        parser.error("provide at least one --site or --site-file")
    limit = scanner._sp_max_sites()
    if len(sites) > limit:
        parser.error(f"requested {len(sites)} sites; this deployment allows {limit}")
    if args.max_files < 1:
        parser.error("--max-files must be at least 1")
    token = os.environ.get("ACP_SP_TOKEN", "").strip()
    if not token:
        parser.error("ACP_SP_TOKEN is required (the token is intentionally not a CLI argument)")

    evidence = run_probe(token, sites, args.max_files)
    payload = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(payload)
    else:
        sys.stdout.write(payload)
    return 0 if evidence["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
