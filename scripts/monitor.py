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


# Paths that provably CANNOT reach the container image, checked against every `COPY` in
# deploy/public/Dockerfile. A commit touching only these changes nothing that production runs, so
# it is not deploy drift and must not turn the monitor red.
#
# This is a DENYLIST, and that direction is the whole design. An allowlist of image paths would
# read more naturally — but the day someone adds a `COPY` for a new directory and forgets to
# update the list, the monitor reports "production is current" about a change that genuinely is
# not deployed. That is a false GREEN, and a monitor that goes green through the thing it exists
# to catch is worse than no monitor (this file's own header). A denylist fails the other way: a
# new directory counts as image-affecting until someone deliberately exempts it, so the worst
# case is the noise we already have.
#
# Kept deliberately short for the same reason. `tests/` and `docs/` are here because they are
# provably absent from every COPY; `deploy/` is NOT here, because two files under it DO ship
# (deploy/public/Dockerfile is the recipe, worker-entry.sh is the worker's entrypoint) — see
# _touches_image, which exempts the deploy scripts by name rather than the directory.
_NON_IMAGE_PREFIXES = (
    "docs/",          # prose
    "tests/",         # python suite — the image copies api/ and scripts/, never tests/
    ".github/",       # CI config runs on runners, not in the container
    "adr/",           # decision records
    "deploy/compose/",  # the LOCAL docker-compose stack; no COPY references it, verified
)
# Files under an otherwise-shipping directory that are themselves never copied in. Deploy scripts
# run from a laptop or a runner; only the Dockerfile and the worker entrypoint are baked.
#
# `azure-pipelines.yml` is a ROOT-level CI config, so `.github/` above does not reach it and its
# `.yml` suffix is not exempt — yet no `COPY` references it, so a commit touching only it changes
# nothing production runs. Left unexempted it turned the monitor red naming a CI-only change as
# "what production runs" (e.g. #235's `d9b5f14`), the exact false-red the cosmetic filter exists
# to suppress. Named, not a broad root-`.yml` suffix rule: the only root yaml today is this CI
# file, and a future root yaml that DOES ship should count until someone deliberately exempts it.
_NON_IMAGE_FILES = (
    "deploy/public/redeploy.sh",
    "deploy/public/deploy.sh",
    "azure-pipelines.yml",
)
# Root-level files that ship nothing.
_NON_IMAGE_SUFFIXES = (".md",)


def _touches_image(paths: list[str]) -> bool:
    """Could this set of changed paths alter what production runs?

    True when ANY path is not provably exempt — including an empty list, which means git told us
    nothing and the honest answer is "assume it matters".
    """
    if not paths:
        return True
    for p in paths:
        if p in _NON_IMAGE_FILES:
            continue
        if p.startswith(_NON_IMAGE_PREFIXES):
            continue
        # A root-level .md only. `api/foo.md` would not exist, but scoping this to the root keeps
        # the rule from quietly exempting a markdown file that some shipped directory reads.
        if p.endswith(_NON_IMAGE_SUFFIXES) and "/" not in p:
            continue
        return True
    return False


def check_deploy_drift(base_health: dict, repo: str, rep: Report) -> None:
    """How far production is behind main, counting only commits that could change the image.

    Production ran four hours behind main on 2026-07-29 with six merged fixes unshipped, and
    nothing said so. Merged is not deployed; this is the only check that knows the difference.

    But "merged" was measured as ANY commit newer than the build, by timestamp, so a docs-only or
    tests-only PR turned the monitor red about a production that was perfectly current. In a repo
    landing ~20 PRs a day that is red almost always, and a check that is usually red is one people
    learn to skip — which is how the four-hour drift went unnoticed in the first place. Alarm
    fatigue is not a smaller failure than silence, it is the same failure with more output.

    So the count is now commits whose changed paths could actually reach the image
    (`_touches_image`). Commits that cannot are reported as a suffix, never as a reason to fail —
    they are still worth SEEING, because "nothing shipped" and "nothing merged" are different
    facts and the reader should not have to guess which one they are looking at.
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
        # --name-only with a record separator, so one call yields both each commit's subject and
        # the paths it touched. `-m` matters: without it a MERGE commit lists no files at all,
        # which _touches_image would have to treat as "assume it matters" on every merge — true
        # to the fail-safe rule, and useless here, since this repo squash-merges and a real merge
        # commit would defeat the whole check.
        out = subprocess.run(
            ["git", "-C", repo, "log", "-m", "--first-parent", "--name-only",
             "--format=%x00%h %s", f"--since={when.isoformat()}", "origin/main"],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except Exception as e:  # noqa: BLE001
        rep.skip("deploy drift", f"git unavailable: {e}")
        return

    shipping, cosmetic = [], []
    for block in out.stdout.split("\x00"):
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        subject, paths = lines[0], lines[1:]
        (shipping if _touches_image(paths) else cosmetic).append(subject)

    age_h = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    # Said in both branches: a reader comparing a red run to a green one needs the same facts in
    # both, not a number that only appears when something is wrong.
    also = (f"; {len(cosmetic)} docs/test-only commit(s) ignored" if cosmetic else "")
    if shipping:
        rep.fail(
            "production is current",
            f"{len(shipping)} commit(s) on main since the running build ({age_h:.1f}h old) "
            f"change what production runs — newest: {shipping[0][:70]}{also}",
        )
    else:
        rep.ok("production is current",
               f"build is {age_h:.1f}h old, nothing that ships has merged since{also}")


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
