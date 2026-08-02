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
  DEEP    /monitor/estate, a read-only aggregate route that exists for this script. Skipped
          LOUDLY when ACP_MONITOR_KEY is absent, never silently: a monitor that quietly stops
          checking is worse than no monitor, because it still reports green.

THE DEEP TIER USED TO BE UNRUNNABLE, and it is worth saying why so nobody reinstates it. It
read /scans and /hitl/queue through the X-E2E-Key gate bypass, and that bypass is disabled in
production BY DESIGN — core.E2E_KEY is None whenever IS_PROD, so the header was refused on the
one deployment worth monitoring. Setting ACP_E2E_KEY would not have helped. The only way to
make it work was ACP_ENABLE_TEST_BYPASS=1, i.e. reopening a whole-gate backdoor on a public
deployment so that a health check could log in — trading the thing being protected for the
ability to check on it.

It was broken a second way too: /scans is scoped to the request's owner, and the keyed path
never sets one, so it read the 'demo' user's scans (empty) and would have reported "no
completed scans at all" against a perfectly healthy 258-document estate.

So the deep tier now asks a purpose-built endpoint that returns COUNTS across all owners, and
carries a credential (ACP_MONITOR_KEY) that unlocks nothing else.

Usage:
    ACP_FQDN=acp-app...azurecontainerapps.io python3 scripts/monitor.py
    ACP_MONITOR_KEY=... python3 scripts/monitor.py --repo .   # add the deep + drift checks

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
    req = urllib.request.Request(url, headers={"X-Monitor-Key": key} if key else {})
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


def check_estate(base: str, key: str, rep: Report) -> None:
    """The deep tier: one call to /monitor/estate, two questions.

    1. THE NEWEST SCAN MUST NOT BE A FRACTION OF THE ESTATE IT REPLACED. This is the sweep bug's
       exact fingerprint, and it needs no stored history: the collapsed scan and the real estate
       sit side by side in the same list of recent counts.
    2. THE REVIEW BACKLOG. Not an assertion — a number worth watching.
    """
    code, body, _ = get(f"{base}/monitor/estate", key=key)
    if code == 503:
        # The deployment has no ACP_MONITOR_KEY set. Distinct from a rejected key, and a FAIL
        # rather than a skip: the operator asked for the deep checks by setting the key locally,
        # so a deployment that cannot answer is a misconfiguration, not an absence.
        rep.fail("estate readable", "HTTP 503 — ACP_MONITOR_KEY is not set ON THE DEPLOYMENT")
        return
    if code == 401:
        rep.fail("estate readable", "HTTP 401 — the key here and the key on the deployment differ")
        return
    if code != 200:
        rep.fail("estate readable", f"HTTP {code} — {body[:120]}")
        return
    try:
        est = json.loads(body)
    except json.JSONDecodeError:
        rep.fail("estate is JSON", body[:120])
        return

    files = [(n or 0) for n in ((est.get("scans") or {}).get("recent_files") or [])]
    total = (est.get("scans") or {}).get("total", len(files))
    if not files:
        rep.fail("scan list non-empty", "no completed scans at all")
    else:
        recent = files[:COLLAPSE_WINDOW]
        newest, biggest = recent[0], max(recent)
        rep.ok("estate readable", f"{total} scans, newest has {newest} documents")
        if biggest and newest < biggest * COLLAPSE_RATIO:
            rep.fail(
                "newest scan is full-size",
                f"newest has {newest} documents but a recent scan had {biggest} — "
                f"a collapsed 'latest' scan is what every dashboard, report and selector will show",
            )
        else:
            rep.ok("newest scan is full-size", f"{newest} vs {biggest} biggest of last {len(recent)}")

    pending = (est.get("inbox") or {}).get("pending")
    if pending is None:
        rep.fail("inbox readable", "response carried no inbox.pending count")
    else:
        rep.ok("inbox readable", f"{pending} pending review items")


def _git(repo: str, *args: str) -> str:
    """Run git and return stdout, or raise. Kept tiny so the checks below read as questions."""
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True, check=True, timeout=60).stdout


def check_deploy_drift(base_health: dict, repo: str, rep: Report) -> None:
    """How far production is behind main.

    Production ran four hours behind main on 2026-07-29 with six merged fixes unshipped, and
    nothing said so. Merged is not deployed; this is the only check that knows the difference.

    IT ASKS BY COMMIT, NOT BY CLOCK. The timestamp version of this check undercounts, and the
    gap is not a rounding error — it silently omits whole commits. On 2026-07-30 d08cd95 merged
    at 13:41:35Z and the running image was built two minutes later at 13:43:34Z, but from an
    earlier pin (598abe9). `--since=built_at` therefore reported 4 commits behind when the true
    answer was 5, and it would have reported 0 for a deploy that pinned a stale sha and ran a
    minute afterwards. Comparing shas cannot make that mistake.

    The timestamp path remains as a FALLBACK for images built before BUILD_SHA existed, and it
    says so in its own message — an operator reading "4 behind (by timestamp)" needs to know the
    number is a floor, not a count.
    """
    sha = (base_health.get("commit") or "").strip()
    built = base_health.get("built_at")

    # Age is reported either way; it is the number that tells you whether to care.
    age = ""
    if built:
        try:
            when = datetime.strptime(built, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age = f", build is {(datetime.now(timezone.utc) - when).total_seconds() / 3600:.1f}h old"
        except ValueError:
            pass

    try:
        subprocess.run(["git", "-C", repo, "fetch", "-q", "origin"], check=True, timeout=60)
    except Exception as e:  # noqa: BLE001
        rep.skip("deploy drift", f"git unavailable: {e}")
        return

    if sha:
        # Does the deployed sha exist here at all? An image built from a commit that is not in
        # origin/main is its own incident, not a drift measurement: 2553e6d reached production
        # from a sha absent from git history (see docs/pipeline.md, guard 1). Reporting that as
        # "0 commits behind" would be the most dangerous possible green.
        try:
            _git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
        except Exception:  # noqa: BLE001
            rep.fail("production is current",
                     f"the running image was built from {sha[:12]} — a commit that does not exist "
                     f"in this repository{age}")
            return
        try:
            behind = [l for l in _git(repo, "log", "--oneline", f"{sha}..origin/main").splitlines()
                      if l.strip()]
            ahead = [l for l in _git(repo, "log", "--oneline", f"origin/main..{sha}").splitlines()
                     if l.strip()]
        except Exception as e:  # noqa: BLE001
            rep.skip("deploy drift", f"git unavailable: {e}")
            return
        if behind:
            rep.fail("production is current",
                     f"{len(behind)} commit(s) on main since {sha[:7]}{age} — "
                     f"newest: {behind[0][:70]}")
        elif ahead:
            # Deployed something that never landed on main — a hand-built image, or a branch.
            rep.fail("production is current",
                     f"{sha[:7]} is {len(ahead)} commit(s) AHEAD of main — production is running "
                     f"code that was never merged{age}")
        else:
            rep.ok("production is current", f"running {sha[:7]}, level with main{age}")
        return

    # ── fallback: no sha in this image ──────────────────────────────────────────────────────
    # Everything below reports a FLOOR. It may only ever say "at least N behind" or "unverifiable",
    # never "current" — because the timestamp cannot prove currency, only disprove it.
    #
    # And it must not go red merely for being an old image. Every currently-running image predates
    # BUILD_SHA, and a check that fails on all of them would put this workflow back where it was
    # found: red on all 43 of its scheduled runs, which is indistinguishable from red for a real
    # outage and gets read the same way — not at all.
    if not built:
        rep.skip("deploy drift",
                 "healthz reported neither commit nor built_at — this image cannot be located in "
                 "history (the 'build is stamped' check above is the one that fails on this)")
        return
    try:
        when = datetime.strptime(built, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        rep.skip("deploy drift", f"unparseable built_at {built!r}")
        return
    try:
        out = _git(repo, "log", "--oneline", f"--since={when.isoformat()}", "origin/main")
    except Exception as e:  # noqa: BLE001
        rep.skip("deploy drift", f"git unavailable: {e}")
        return
    behind = [l for l in out.splitlines() if l.strip()]
    note = "by timestamp — this image predates BUILD_SHA, so the count is a FLOOR, not a total"
    if behind:
        rep.fail("production is current",
                 f"at least {len(behind)} commit(s) on main since the running build{age} "
                 f"({note}) — newest: {behind[0][:70]}")
    else:
        rep.skip("deploy drift",
                 f"nothing merged since the build clock{age}, but this image carries no commit "
                 f"sha, so currency is UNVERIFIED ({note}). The next deploy stamps it.")


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
    key = os.environ.get("ACP_MONITOR_KEY") or None

    print(f"monitoring {base}\n")
    rep = Report()
    health = check_health(base, rep)
    check_ready(base, rep)

    if key:
        check_estate(base, key, rep)
    else:
        # Loud, and counted. The deep checks are the ones that would have caught the sweep.
        rep.skip("newest scan is full-size", "ACP_MONITOR_KEY not set — the deep checks did NOT run")
        rep.skip("inbox readable", "ACP_MONITOR_KEY not set")

    if args.repo:
        check_deploy_drift(health, args.repo, rep)
    else:
        rep.skip("deploy drift", "--repo not given")

    return rep.render()


if __name__ == "__main__":
    raise SystemExit(main())
