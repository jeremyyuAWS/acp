#!/usr/bin/env python3
"""Ask production whether it is actually alright, and say so out loud when it is not.

Every defect found on 2026-07-29 was SILENT. Not one of them surfaced anywhere a person looks:

  - a scheduled sweep replaced a 258-document estate with a 1-file scan of the bundled samples,
    every five minutes, for hours — and every "latest" view faithfully showed the wrong thing
  - the review inbox could only ever grow; nothing withdrew an item, so the count a reviewer
    plans their day around was inflated by an unknown amount
  - the product failed the WCAG criterion it certifies documents against, and only its own
    bundled axe-core knew
  - Drive ADC threw 403 every five minutes into a log nobody reads
  - production ran four hours behind main with six merged fixes unshipped

CI told us the code was right. Nothing told us PRODUCTION was right. That is the gap this closes.

Two tiers, because most of the surface needs a credential and liveness alone would have caught
none of the above:

  PUBLIC  /healthz, /readyz — always run, no secret needed.
  DEEP    /scans, /hitl/queue via the X-E2E-Key bypass the app already implements for smoke tests
          (api/app.py:_access_gate). Skipped LOUDLY when ACP_E2E_KEY is absent, never silently:
          a monitor that quietly stops checking is worse than no monitor, because it still
          reports green.

Usage:
    ACP_FQDN=acp-app...azurecontainerapps.io python3 scripts/monitor.py
    ACP_E2E_KEY=... python3 scripts/monitor.py --repo .    # add the deep + drift checks

Exit 0 = healthy, 1 = at least one check failed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# A newest scan this much smaller than the biggest of its recent siblings is the fingerprint of
# the fallback-sweep bug: a 1-file scan of the local corpus landing on top of a 258-file estate.
# Expressed as a RATIO rather than an absolute floor so it needs no per-estate configuration and
# cannot go stale when the estate grows.
COLLAPSE_RATIO = 0.5
COLLAPSE_WINDOW = 10          # how many recent scans count as "siblings"
HEARTBEAT_MAX_AGE_S = 300     # the worker tier proves itself alive by writing a timestamp
SLOW_MS = 3000


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []
        self.failed = 0
        self.skipped = 0

    def ok(self, name: str, detail: str = "") -> None:
        self.rows.append(("ok", name, detail))

    def fail(self, name: str, detail: str) -> None:
        self.rows.append(("FAIL", name, detail))
        self.failed += 1

    def skip(self, name: str, why: str) -> None:
        self.rows.append(("skip", name, why))
        self.skipped += 1

    def render(self) -> int:
        icon = {"ok": "  ok  ", "FAIL": " FAIL ", "skip": " skip "}
        for state, name, detail in self.rows:
            print(f"{icon[state]} {name:<28} {detail}")
        print()
        if self.failed:
            # GitHub Actions surfaces ::error:: in the run summary and the PR/commit checks UI.
            for state, name, detail in self.rows:
                if state == "FAIL":
                    print(f"::error title=production monitor::{name} — {detail}")
            print(f"{self.failed} check(s) FAILED, {self.skipped} skipped")
            return 1
        print(f"all checks passed ({self.skipped} skipped)")
        return 0


def get(url: str, key: str | None = None, timeout: int = 20) -> tuple[int, str, float]:
    req = urllib.request.Request(url, headers={"X-E2E-Key": key} if key else {})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), (time.monotonic() - t0) * 1000
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), (time.monotonic() - t0) * 1000
    except Exception as e:  # noqa: BLE001 — a monitor must report a failure, never raise one
        return 0, str(e), (time.monotonic() - t0) * 1000


def check_health(base: str, rep: Report) -> dict:
    code, body, ms = get(f"{base}/healthz")
    if code != 200:
        rep.fail("healthz reachable", f"HTTP {code} — {body[:120]}")
        return {}
    try:
        h = json.loads(body)
    except json.JSONDecodeError:
        rep.fail("healthz is JSON", body[:120])
        return {}
    rep.ok("healthz reachable", f"{ms:.0f}ms")
    if ms > SLOW_MS:
        rep.fail("healthz latency", f"{ms:.0f}ms exceeds {SLOW_MS}ms")

    if h.get("ok") is True:
        rep.ok("healthz ok", f"v{h.get('version')}")
    else:
        rep.fail("healthz ok", json.dumps(h)[:160])
    # An unstamped image runs perfectly well while every surface reports version "dev" — the
    # failure mode redeploy.sh refuses to ship and this catches if one ever slips past.
    if h.get("version_stamped") is True:
        rep.ok("build is stamped", str(h.get("built_at")))
    else:
        rep.fail("build is stamped", f"version={h.get('version')!r} — this image did not come from a real deploy")
    return h


def check_ready(base: str, rep: Report) -> None:
    code, body, _ = get(f"{base}/readyz")
    if code != 200:
        rep.fail("readyz reachable", f"HTTP {code} — {body[:120]}")
        return
    try:
        r = json.loads(body)
    except json.JSONDecodeError:
        rep.fail("readyz is JSON", body[:120])
        return

    if r.get("ready") is True:
        rep.ok("readyz ready")
    else:
        rep.fail("readyz ready", json.dumps(r)[:200])

    degraded = r.get("degraded") or []
    if degraded:
        rep.fail("nothing degraded", ", ".join(map(str, degraded)))
    else:
        rep.ok("nothing degraded")

    w = r.get("workers") or {}
    # The worker tier is where scanning happens. Its heartbeat is the only thing that proves the
    # queue is manned — the API's own pool is 0 by design in the split topology.
    if w.get("alive") is True and (w.get("age_s") is None or w["age_s"] <= HEARTBEAT_MAX_AGE_S):
        rep.ok("worker tier alive", f"heartbeat {w.get('age_s')}s ago")
    else:
        rep.fail("worker tier alive", f"alive={w.get('alive')} age_s={w.get('age_s')} — scans will queue forever")

    pdf = ((r.get("engines") or {}).get("pdf") or {})
    if pdf.get("available") is True:
        rep.ok("pdf engine loaded", str(pdf.get("path")))
    else:
        rep.fail("pdf engine loaded", f"{pdf.get('reason')} — every PDF would error, one at a time")


def check_scan_scale(base: str, key: str, rep: Report) -> None:
    """The newest scan must not be a fraction of the estate it replaced.

    This is the sweep bug's exact fingerprint, and it is checkable without any stored history:
    the collapsed scan and the real estate sit side by side in the same list.
    """
    code, body, _ = get(f"{base}/scans", key=key)
    if code != 200:
        rep.fail("scan list readable", f"HTTP {code} — X-E2E-Key rejected or route moved")
        return
    try:
        scans = json.loads(body)
    except json.JSONDecodeError:
        rep.fail("scan list is JSON", body[:120])
        return
    if not isinstance(scans, list) or not scans:
        rep.fail("scan list non-empty", "no completed scans at all")
        return

    recent = scans[:COLLAPSE_WINDOW]
    files = [(s.get("files") or 0) for s in recent]
    newest, biggest = files[0], max(files)
    rep.ok("scan list readable", f"{len(scans)} scans, newest has {newest} documents")

    if biggest and newest < biggest * COLLAPSE_RATIO:
        rep.fail(
            "newest scan is full-size",
            f"newest has {newest} documents but a recent scan had {biggest} — "
            f"a collapsed 'latest' scan is what every dashboard, report and selector will show",
        )
    else:
        rep.ok("newest scan is full-size", f"{newest} vs {biggest} biggest of last {len(recent)}")


def check_inbox(base: str, key: str, rep: Report) -> None:
    """Report the review backlog. Not an assertion — a number worth watching."""
    code, body, _ = get(f"{base}/hitl/queue?status=pending", key=key)
    if code != 200:
        rep.fail("inbox readable", f"HTTP {code}")
        return
    try:
        items = json.loads(body)
    except json.JSONDecodeError:
        rep.fail("inbox is JSON", body[:120])
        return
    rep.ok("inbox readable", f"{len(items)} pending review items")


def check_deploy_drift(base_health: dict, repo: str, rep: Report) -> None:
    """How far production is behind main.

    Production ran four hours behind main on 2026-07-29 with six merged fixes unshipped, and
    nothing said so. Merged is not deployed; this is the only check that knows the difference.
    """
    built = base_health.get("built_at")
    if not built:
        rep.skip("deploy drift", "healthz reported no built_at")
        return
    try:
        when = datetime.strptime(built, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        rep.skip("deploy drift", f"unparseable built_at {built!r}")
        return
    try:
        subprocess.run(["git", "-C", repo, "fetch", "-q", "origin"], check=True, timeout=60)
        out = subprocess.run(
            ["git", "-C", repo, "log", "--oneline", f"--since={when.isoformat()}", "origin/main"],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except Exception as e:  # noqa: BLE001
        rep.skip("deploy drift", f"git unavailable: {e}")
        return
    behind = [l for l in out.stdout.splitlines() if l.strip()]
    age_h = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    if behind:
        rep.fail(
            "production is current",
            f"{len(behind)} commit(s) on main since the running build ({age_h:.1f}h old) — "
            f"newest: {behind[0][:70]}",
        )
    else:
        rep.ok("production is current", f"build is {age_h:.1f}h old, nothing merged since")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fqdn", default=os.environ.get("ACP_FQDN", ""),
                    help="app hostname, no scheme")
    ap.add_argument("--repo", default=None,
                    help="path to an acp checkout, for the deploy-drift check")
    args = ap.parse_args()

    if not args.fqdn:
        sys.exit("monitor: set ACP_FQDN (or pass --fqdn) to the app hostname, without a scheme")
    base = f"https://{args.fqdn.rstrip('/')}"
    key = os.environ.get("ACP_E2E_KEY") or None

    print(f"monitoring {base}\n")
    rep = Report()
    health = check_health(base, rep)
    check_ready(base, rep)

    if key:
        check_scan_scale(base, key, rep)
        check_inbox(base, key, rep)
    else:
        # Loud, and counted. The deep checks are the ones that would have caught the sweep.
        rep.skip("newest scan is full-size", "ACP_E2E_KEY not set — the deep checks did NOT run")
        rep.skip("inbox readable", "ACP_E2E_KEY not set")

    if args.repo:
        check_deploy_drift(health, args.repo, rep)
    else:
        rep.skip("deploy drift", "--repo not given")

    return rep.render()


if __name__ == "__main__":
    raise SystemExit(main())
