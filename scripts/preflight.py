#!/usr/bin/env python3
"""Preflight: is this deployment actually wired for a real-source, GPU-backed, traced run?

WHY THIS EXISTS. Every dependency here fails SILENTLY and in the reassuring direction. Set
RUNPOD_ENDPOINT_ID and RUNPOD_API_KEY but forget ACP_VISION_PROVIDER and vision still works — on
the local CPU floor, slowly, with no error anywhere. Forget ACP_AZURE_CLIENT_ID and the SPA simply
hides the Connect Microsoft button, which reads as "SharePoint isn't part of this build". Leave
Langfuse unset and every lf.* call is a no-op by design, so a run completes and traces nothing.
None of those raise. All of them look like "it works" right up until somebody asks for evidence.

So this asks each question directly and reports one of THREE states, never two:

    PASS   verified — something was executed or resolved, and the answer was right
    WARN   configured but NOT verified, or deliberately off — stated, never silently skipped
    FAIL   configured and wrong, or required and missing

The distinction that matters is PASS vs WARN. A check that could not run reports WARN and says
why; it never borrows PASS from a check that did run. "We did not look" and "we looked and it was
fine" are different facts — the same rule the discovery diff this repo just shipped is built on.

OFFLINE BY DEFAULT. Config and wiring checks need no network and are safe in CI. The checks that
need to reach RunPod or Langfuse only run with --live, and say so when they don't.

    python scripts/preflight.py              # config + wiring, no network
    python scripts/preflight.py --live       # also reach RunPod and Langfuse
    python scripts/preflight.py --json       # machine-readable

Exit code is 1 if anything FAILed, else 0. WARNs do not fail the run — they are information, and a
deployment that has deliberately not configured a GPU is not broken.

NO SECRET IS EVER PRINTED. Secrets are reported as present/absent only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_ICON = {PASS: "✓", WARN: "!", FAIL: "✗"}

results: list[dict] = []


def record(group: str, name: str, state: str, detail: str) -> None:
    results.append({"group": group, "check": name, "state": state, "detail": detail})


def _set(var: str) -> bool:
    return bool((os.environ.get(var) or "").strip())


# ── GPU vision (RunPod Serverless, ADR 0022) ─────────────────────────────────

def check_gpu(live: bool) -> None:
    g = "GPU vision"
    eid, key = _set("RUNPOD_ENDPOINT_ID"), _set("RUNPOD_API_KEY")
    record(g, "RUNPOD_ENDPOINT_ID", PASS if eid else WARN,
           "set" if eid else "not set — serverless_vision_provider() returns None")
    record(g, "RUNPOD_API_KEY", PASS if key else WARN,
           "present" if key else "not set — the endpoint id alone is not enough")

    # THE TRAP. This is the whole reason the check exists as code rather than a doc line: with the
    # two vars above set and ACP_VISION_PROVIDER unset, `choice` defaults to "ollama" and the
    # RunPod provider is never selected. Nothing errors. Vision keeps working on the CPU floor and
    # the only symptom is that it is slow — which reads as "the GPU is not very fast".
    choice = (os.environ.get("ACP_VISION_PROVIDER") or "").strip().lower()
    if choice == "runpod_serverless":
        record(g, "ACP_VISION_PROVIDER", PASS, "runpod_serverless")
    elif choice:
        record(g, "ACP_VISION_PROVIDER", WARN,
               f"{choice!r} — not runpod_serverless, so the GPU endpoint will not be selected")
    else:
        record(g, "ACP_VISION_PROVIDER", WARN if not (eid and key) else FAIL,
               "unset — defaults to 'ollama'. With RunPod configured this silently uses the "
               "local CPU floor instead of the GPU")

    # Resolve the provider the way the app does, so this reports what will ACTUALLY run rather
    # than what the env implies. An admin setting overrides the env default, and that override is
    # invisible from the environment alone.
    try:
        import providers
        p = providers.active_vision_provider()
        name = getattr(p, "name", type(p).__name__)
        if name == "runpod_serverless":
            record(g, "resolved provider", PASS, f"{name} (zone={getattr(p, 'zone', '?')})")
        else:
            record(g, "resolved provider", WARN if not (eid and key) else FAIL,
                   f"{name} — the GPU provider is NOT what a scan will use")
    except Exception as e:                       # a store-less/partial env must not crash preflight
        record(g, "resolved provider", WARN, f"could not resolve ({type(e).__name__}: {e})")

    if not live:
        record(g, "endpoint reachable", WARN, "not checked — pass --live to reach RunPod")
        return
    if not (eid and key):
        record(g, "endpoint reachable", WARN, "skipped — endpoint id and key are not both set")
        return
    _probe_runpod(g)


def _probe_runpod(g: str) -> None:
    """Ask RunPod for the endpoint's health. A 401 and a 404 are different diagnoses and are
    reported as such — "it did not work" would send somebody to check the wrong thing."""
    import urllib.error
    import urllib.request
    eid = os.environ["RUNPOD_ENDPOINT_ID"].strip()
    url = f"https://api.runpod.ai/v2/{eid}/health"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {os.environ['RUNPOD_API_KEY'].strip()}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read().decode() or "{}")
        workers = body.get("workers") or {}
        jobs = body.get("jobs") or {}
        # Scale-to-zero is the DESIGN (workersMin 0), so "0 ready" is healthy, not a fault. Saying
        # otherwise would train people to ignore this line.
        record(g, "endpoint reachable", PASS,
               f"health ok — workers ready={workers.get('ready', 0)} idle={workers.get('idle', 0)}"
               f" (0 is normal: scale-to-zero), jobs in queue={jobs.get('inQueue', 0)}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            record(g, "endpoint reachable", FAIL, "401 — RUNPOD_API_KEY rejected")
        elif e.code == 404:
            record(g, "endpoint reachable", FAIL, f"404 — no endpoint {eid!r} on this account")
        else:
            record(g, "endpoint reachable", FAIL, f"HTTP {e.code}")
    except Exception as e:
        record(g, "endpoint reachable", FAIL, f"{type(e).__name__}: {e}")


# ── SharePoint / OneDrive (Microsoft Graph) ──────────────────────────────────

def check_sharepoint() -> None:
    g = "SharePoint"
    cid, tid = _set("ACP_AZURE_CLIENT_ID"), _set("ACP_AZURE_TENANT_ID")
    record(g, "ACP_AZURE_CLIENT_ID", PASS if cid else WARN,
           "set" if cid else "not set — /config returns null and the SPA HIDES the "
                            "Connect Microsoft button entirely, which reads as 'SharePoint "
                            "is not part of this build' rather than as missing config")
    record(g, "ACP_AZURE_TENANT_ID", PASS if tid else WARN,
           "set" if tid else "not set — sign-in falls back to the multi-tenant 'common' authority")

    # Read the scopes from the frontend rather than restating them here. A preflight that carries
    # its own copy of the list is a second source of truth, and the failure it produces is the
    # worst kind: it passes while the app asks for something else.
    src = ROOT / "frontend" / "src" / "sharepointScopes.js"
    try:
        line = next(l for l in src.read_text().splitlines() if "export const SP_SCOPES" in l)
        scopes = [s.strip().strip("'\"") for s in line.split("[", 1)[1].split("]", 1)[0].split(",")]
        scopes = [s for s in scopes if s]
    except Exception as e:
        record(g, "delegated scopes", WARN, f"could not read {src.name} ({type(e).__name__})")
        return
    record(g, "delegated scopes", PASS, " · ".join(scopes) + " — grant admin consent for these")
    writes = [s for s in scopes if ".readwrite" in s.lower()]
    record(g, "read-only posture", PASS if not writes else WARN,
           "no write scopes requested" if not writes else f"write scopes present: {writes}")

    # Token acquisition is delegated (MSAL popup, a human signs in), so a headless preflight
    # CANNOT verify it. Saying so is the point — reporting PASS on the config alone would be the
    # same "we did not look, so it must be fine" this script exists to prevent.
    record(g, "token acquisition", WARN,
           "not verifiable headlessly — SP_SCOPES are DELEGATED, so a person signs in via the "
           "browser. Verify by clicking Connect Microsoft in the app")


# ── Langfuse tracing ─────────────────────────────────────────────────────────

def check_smb() -> None:
    g = "Network drive (SMB)"
    import smb_source
    r = smb_source.describe_smb_readiness()
    shares, cred = r["shares"], r["credential_source"]
    if not shares and not cred:
        # SMB is an OPTIONAL source (like SharePoint): unconfigured is not a failure, but say so —
        # otherwise "no network-drive scans" reads as a missing feature rather than a deliberate choice.
        record(g, "configured", WARN,
               "no ACP_SMB_SHARES — the network-drive source is not part of this deployment")
        return
    record(g, "shares", PASS if shares else FAIL,
           f"{len(shares)} in scope: {', '.join(shares)}" if shares else
           "ACP_SMB_SHARES not set but a credential is — a network-drive scan has nothing to walk")
    record(g, "credential", PASS if cred else FAIL,
           "via Key Vault (Managed Identity)" if cred == "key_vault" else
           "via username+password" if cred == "userpass" else
           "none — set ACP_SMB_CREDENTIAL_KV (Key Vault, preferred) or ACP_SMB_USERNAME + ACP_SMB_PASSWORD")
    if cred == "userpass":
        record(g, "credential posture", WARN,
               "dev/test password in env — prefer Key Vault + Managed Identity for a PHI deployment")
    # The live reach cannot be verified headlessly: it needs the smbprotocol transport and the
    # customer's private network route (ADR 0036). Same honesty as SharePoint's token acquisition —
    # config being right is necessary, not sufficient, and PASS is never borrowed for what did not run.
    record(g, "share reachability", WARN,
           "not verified here — needs the live transport + the customer's private route; run a real scan")


def check_tracing(live: bool) -> None:
    g = "Tracing"
    try:
        import lf
    except Exception as e:
        record(g, "lf importable", FAIL, f"{type(e).__name__}: {e}")
        return
    record(g, "lf importable", PASS, "module loads without the langfuse package")

    if not lf._ENABLED:
        missing = [v for v in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
                   if not _set(v)]
        record(g, "credentials", WARN,
               f"tracing OFF — missing {', '.join(missing)}. Every lf.* call is a no-op, so runs "
               f"complete and trace nothing")
        return
    record(g, "credentials", PASS, f"host={os.environ.get('LANGFUSE_HOST')}")

    # The three phase lanes, checked by SYMBOL — this is the wiring that was broken for Discover
    # (the span existed; nothing on the discover path called it), so presence of the function is
    # not the question. Whether a CALLER exists is.
    for phase, module, symbol in (("Discover", "api/handlers.py", "discover_run_trace"),
                                  ("Assess", "api/handlers.py", "assess_span"),
                                  ("Remediate", "api/core.py", "remediate_span")):
        text = (ROOT / module).read_text()
        n = text.count(f"_lf.{symbol}")
        record(g, f"{phase} lane wired", PASS if n else FAIL,
               f"{module} calls _lf.{symbol}" if n else
               f"NO caller in {module} — this phase emits no trace")

    cap = lf._discover_file_cap()
    record(g, "per-file discover spans", PASS if cap else WARN,
           f"cap {cap} per run (ACP_TRACE_DISCOVER_FILES)" if cap
           else "disabled — run traces only, no per-file Discover spans")
    record(g, "filename redaction", PASS if not lf._PLAIN_FILENAMES else WARN,
           "opaque doc labels (PHI-safe default)" if not lf._PLAIN_FILENAMES
           else "ACP_TRACE_FILENAMES=plain — REAL FILENAMES in traces; wrong for a PHI estate")

    if not live:
        record(g, "trace delivery", WARN, "not checked — pass --live to emit a probe trace")
        return
    try:
        t = lf.discover_run_trace("preflight", "local", listed=0, inventoried=0,
                                  scope={"kind": "preflight"}, user="preflight",
                                  file_spans_emitted=0)
        lf.flush()
        record(g, "trace delivery", WARN if isinstance(t, lf._Noop) else PASS,
               "client returned a no-op" if isinstance(t, lf._Noop)
               else "probe trace emitted to session 'preflight'")
    except Exception as e:
        record(g, "trace delivery", FAIL, f"{type(e).__name__}: {e}")


# ── report ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="also make network calls (RunPod, Langfuse)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    args = ap.parse_args()

    check_gpu(args.live)
    check_sharepoint()
    check_smb()
    check_tracing(args.live)

    failed = sum(1 for r in results if r["state"] == FAIL)
    warned = sum(1 for r in results if r["state"] == WARN)

    if args.as_json:
        print(json.dumps({"results": results,
                          "summary": {"pass": len(results) - failed - warned,
                                      "warn": warned, "fail": failed},
                          "live": args.live}, indent=2))
        return 1 if failed else 0

    group = None
    for r in results:
        if r["group"] != group:
            group = r["group"]
            print(f"\n{group}")
        print(f"  {_ICON[r['state']]} {r['check']:<26} {r['detail']}")
    print(f"\n{len(results) - failed - warned} pass · {warned} warn · {failed} fail")
    if not args.live:
        print("(offline run — network checks reported as warn; use --live to verify them)")
    if failed:
        print("\nFAIL means configured-and-wrong or required-and-missing. WARN means not "
              "configured, or not verifiable here — never assume a WARN is fine.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
