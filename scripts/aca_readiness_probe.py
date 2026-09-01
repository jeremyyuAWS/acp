#!/usr/bin/env python3
"""Patch an Azure Container Apps template so its container has a READINESS probe — and only that.

Used by deploy/public/deploy.sh. Reads the app's current `properties.template` on stdin (as
`az containerapp show --query properties.template -o json` prints it) and writes the body for
`az containerapp update --yaml` on stdout. JSON is valid YAML, so no serialiser is needed.

WHY THIS IS A SEPARATE FILE RATHER THAN A HEREDOC IN deploy.sh. The Azure call itself cannot be
exercised anywhere but against a live subscription, but the decision it carries out — which
container, which probes survive, whether anything needs changing at all — is pure data, and a
mistake in it rewrites the template of the production app. Splitting it out is what makes that
half testable (tests/test_aca_readiness_probe.py) instead of trusted.

THREE RULES IT WILL NOT BREAK.

1. READINESS ONLY. It never writes a Liveness or Startup probe, and it refuses to remove one
   somebody else set. A liveness probe on this endpoint would be actively harmful: the endpoint
   answers 503 when the database is unreachable, and a liveness probe reads that as "restart the
   container" — turning a database blip into a crash loop that cannot possibly fix a database.
   Readiness withdraws the replica from ingress and puts it back on its own when the check
   recovers, which is the behaviour wanted here.

2. IT EDITS, IT DOES NOT REBUILD. `az containerapp update --yaml` REPLACES the template it is
   given, so the output has to carry the image, env, resources, command and volume mounts the
   app already had. Those are copied through from the input untouched; the only key this file
   writes is `probes` on one container.

3. IT FAILS CLOSED. Anything it does not understand — no containers, several containers and no
   name match, a template that is not an object — is a refusal on stderr with exit 1, never a
   guess. deploy.sh treats that as "leave the app alone", which is the safe outcome: an app with
   no readiness probe is what production has today.

Exit codes: 0 patch on stdout · 3 nothing to do · 1 refused (reason on stderr).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys

# ── The probe, and why each number is what it is ───────────────────────────────────────────
#
# ACA's own bounds: initialDelaySeconds 1-60, periodSeconds 1-240, timeoutSeconds 1-240,
# successThreshold 1-10, failureThreshold 1-10. Everything below sits inside them.
#
# THE ASYMMETRY IS THE POINT. Admission is fast and withdrawal is slow:
#
#   successThreshold 1  — one good answer admits a new replica. The window this exists to close
#                         is a new replica taking traffic before it can serve a database read,
#                         and holding a replica that HAS answered adds deploy latency for
#                         nothing.
#   failureThreshold 10 — a serving replica is withdrawn only after 10 consecutive failures,
#                         i.e. ~50s of a database that will not answer. This app runs at
#                         min-replicas 1, so withdrawing its only replica takes the whole app
#                         off ingress; that must be a considered response to a real outage, not
#                         a reaction to one slow query.
#
# timeoutSeconds 4 is under periodSeconds 5 so a hung check cannot overlap the next one, and it
# is well over the 0.4-0.8s a healthy /probe/readyz answers in (measured in production).
READINESS_PROBE = {
    "type": "Readiness",
    "httpGet": {"path": "/probe/readyz", "port": 8077, "scheme": "HTTP"},
    "initialDelaySeconds": 3,
    "periodSeconds": 5,
    "timeoutSeconds": 4,
    "successThreshold": 1,
    "failureThreshold": 10,
}


def _pick_container(containers: list, name: str | None) -> int:
    """Index of the container to patch, or raise ValueError saying why it cannot be chosen."""
    if not containers:
        raise ValueError("template has no containers")
    if name:
        matches = [i for i, c in enumerate(containers) if isinstance(c, dict) and c.get("name") == name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"{len(matches)} containers are named {name!r}")
    if len(containers) == 1:
        # The single-container case, which is what this app is. Falling back to it when the
        # name does not match matters: the ACA CLI derives the container name from the image
        # repository, not from the app name, and those can legitimately differ.
        return 0
    raise ValueError(
        f"{len(containers)} containers and none named {name!r} — refusing to guess which one "
        "serves ingress")


def patch(template: dict, container_name: str | None, probe: dict | None = None,
          remove: bool = False) -> dict | None:
    """The patched template, or None when there is nothing to change.

    Non-Readiness probes are carried through untouched, and at most one Readiness probe exists
    afterwards (ACA rejects duplicates of a type).

    `remove=True` strips the Readiness probe instead of writing one — the escape hatch for the
    one way this gate can bite. Probes live on the template and survive an image change, so
    deploying an image that predates /probe/readyz onto a gated app leaves the probe asking for
    a route that answers 404 and the new revision never becomes ready. ACA holds traffic on the
    last healthy revision rather than going dark, so it fails safe; but it fails, and an
    operator needs a way out that is not "edit the template by hand at 3am". See deploy.sh.
    """
    if not isinstance(template, dict):
        raise ValueError("template is not a JSON object")
    containers = template.get("containers")
    if not isinstance(containers, list):
        raise ValueError("template has no containers list")
    idx = _pick_container(containers, container_name)
    target = containers[idx]
    if not isinstance(target, dict):
        raise ValueError("container entry is not a JSON object")

    want = copy.deepcopy(probe if probe is not None else READINESS_PROBE)
    existing = target.get("probes") or []
    if not isinstance(existing, list):
        raise ValueError("container's probes is not a list")

    kept = [p for p in existing if not (isinstance(p, dict) and p.get("type") == "Readiness")]
    current = [p for p in existing if isinstance(p, dict) and p.get("type") == "Readiness"]

    if remove:
        if not current:
            return None                  # nothing to remove
        out = copy.deepcopy(template)
        out["containers"][idx]["probes"] = kept
        return out

    if len(current) == 1 and current[0] == want and len(kept) == len(existing) - 1:
        return None                      # already exactly this — deploy.sh prints and moves on

    out = copy.deepcopy(template)
    out["containers"][idx]["probes"] = kept + [want]
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--container", default=None,
                    help="name of the container to patch; falls back to the only container")
    ap.add_argument("--path", default=READINESS_PROBE["httpGet"]["path"])
    ap.add_argument("--port", type=int, default=READINESS_PROBE["httpGet"]["port"])
    ap.add_argument("--remove", action="store_true",
                    help="strip the Readiness probe instead of writing one (the escape hatch)")
    args = ap.parse_args(argv)

    raw = sys.stdin.read().strip()
    if not raw:
        print("refusing: no template on stdin (did `az containerapp show` fail?)", file=sys.stderr)
        return 1
    try:
        template = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"refusing: template on stdin is not JSON — {exc}", file=sys.stderr)
        return 1

    probe = copy.deepcopy(READINESS_PROBE)
    probe["httpGet"]["path"] = args.path
    probe["httpGet"]["port"] = args.port

    try:
        patched = patch(template, args.container, probe, remove=args.remove)
    except ValueError as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 1
    if patched is None:
        return 3
    json.dump({"properties": {"template": patched}}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
