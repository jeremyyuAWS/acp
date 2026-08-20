#!/usr/bin/env python3
"""Read a scan's per-stage timing rollup (ADR 0037 Step 0) and print where the scan spent its time.

Measure-FIRST (ADR 0037): before tuning any worker counts, look at where the time actually goes —
download (I/O) vs analyse (CPU + GPU) — and which stage is the bottleneck. This calls the deployed
app's `GET /scans/{id}/timings` with YOUR signed-in session token and prints a readable breakdown, so
the next Track B step (splitting the bottleneck stage into its own bounded pool) is chosen from data.

Usage:
    export ACP_TOKEN="<your bearer token>"          # your signed-in session's token
    python scripts/read_timings.py <SCAN_ID>        # a specific scan
    python scripts/read_timings.py                  # the most recent scan (via GET /scans)

Options:
    --base URL        app base URL (default: $ACP_BASE_URL, else $ACP_FQDN, else prod)
    --token TOKEN     bearer token (default: $ACP_TOKEN)
    --provider P      auth provider header: google (default) | microsoft
    --json            print the raw JSON instead of the table

Stdlib only — no dependencies. NO SECRET IS PRINTED; the token is only sent as the Authorization header.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

_PROD = "https://acp-app.greenwater-4bf2c997.eastus2.azurecontainerapps.io"


def base_url(arg: str | None) -> str:
    """Resolve the app base URL: --base, else $ACP_BASE_URL, else $ACP_FQDN, else prod. A bare host
    (no scheme) is assumed https; a trailing slash is trimmed so path-joining is clean."""
    b = (arg or os.environ.get("ACP_BASE_URL") or os.environ.get("ACP_FQDN") or _PROD).strip().rstrip("/")
    if not b.startswith(("http://", "https://")):
        b = "https://" + b
    return b


def auth_headers(token: str, provider: str | None) -> dict:
    """Authorization + the provider hint the gate uses to verify against the right issuer (Graph for
    Microsoft; Google otherwise, matching app.py). The token is never logged, only sent."""
    h = {"Authorization": f"Bearer {token}"}
    if (provider or "").lower() == "microsoft":
        h["X-Auth-Provider"] = "microsoft"
    return h


def _get(url: str, token: str, provider: str | None, timeout: int = 30):
    req = urllib.request.Request(url, headers=auth_headers(token, provider))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def latest_scan_id(base: str, token: str, provider: str | None):
    """The most recent scan's id — GET /scans returns newest-first — or None if the account has none."""
    scans = _get(f"{base}/scans", token, provider)
    rows = scans if isinstance(scans, list) else (scans.get("scans") or [])
    for s in rows:
        sid = s.get("id") or (s.get("run") or {}).get("id")
        if sid:
            return sid
    return None


def format_timings(rollup, scan_id: str = "") -> str:
    """Pretty per-stage breakdown from a /scans/{id}/timings payload. PURE — the load-bearing bit, so
    it's unit-tested. Shows total seconds, calls, average, and share of total, with the bottleneck
    starred, and stays honest when nothing was measured (a scan from before this shipped, or one still
    early) rather than inventing a bottleneck."""
    rollup = rollup or {}
    totals = rollup.get("totals_s") or {}
    counts = rollup.get("counts") or {}
    avg = rollup.get("avg_s") or {}
    files = rollup.get("files_timed", 0)
    bn = rollup.get("bottleneck")
    grand = sum(v for v in totals.values() if isinstance(v, (int, float)))

    lines = [f"Stage timings — scan {scan_id}" if scan_id else "Stage timings"]
    note = "" if files else "  (no timing recorded — a scan from before this shipped, or still early)"
    lines.append(f"  files timed: {files}{note}")
    if not totals:
        lines.append("  (nothing measured yet)")
        return "\n".join(lines)

    lines.append(f"  {'stage':<12} {'total s':>10} {'calls':>7} {'avg s':>9} {'share':>7}")
    for stage in sorted(totals, key=lambda k: totals.get(k, 0) or 0, reverse=True):
        t = totals.get(stage, 0) or 0
        c = counts.get(stage, 0) or 0
        a = avg.get(stage, (t / c if c else 0))
        share = (t / grand * 100) if grand else 0
        star = "  <- bottleneck" if stage == bn else ""
        lines.append(f"  {stage:<12} {t:>10.2f} {c:>7} {a:>9.3f} {share:>6.0f}%{star}")
    if bn:
        lines.append(f"\n  Bottleneck: {bn}. Per ADR 0037, that is the stage to split into its own "
                     f"bounded pool first.")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Read a scan's per-stage timing rollup (ADR 0037 Step 0).")
    p.add_argument("scan_id", nargs="?", help="scan id (default: the most recent scan)")
    p.add_argument("--base", help="app base URL (default: $ACP_BASE_URL / $ACP_FQDN / prod)")
    p.add_argument("--token", help="bearer token (default: $ACP_TOKEN)")
    p.add_argument("--provider", default="google", help="auth provider: google (default) | microsoft")
    p.add_argument("--json", action="store_true", help="print raw JSON instead of the table")
    a = p.parse_args(argv)

    token = a.token or os.environ.get("ACP_TOKEN")
    if not token:
        print("error: no token. Set ACP_TOKEN to your signed-in session's bearer token, or pass "
              "--token.", file=sys.stderr)
        return 2
    base = base_url(a.base)

    try:
        sid = a.scan_id or latest_scan_id(base, token, a.provider)
        if not sid:
            print("error: no scan id given and no scans found for this account.", file=sys.stderr)
            return 1
        rollup = _get(f"{base}/scans/{sid}/timings", token, a.provider)
    except urllib.error.HTTPError as e:
        msg = {401: "401 - sign in again (token expired, or wrong provider; try --provider microsoft)",
               403: "403 - this scan is not yours",
               404: "404 - scan not found (or not yours)"}.get(e.code, f"HTTP {e.code}")
        print(f"error: {msg}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — a CLI reports the failure, it does not traceback
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(json.dumps(rollup, indent=2) if a.json else format_timings(rollup, sid))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
