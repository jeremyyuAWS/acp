#!/usr/bin/env python3
"""Fan-out load harness for the multi-user concurrency scenario (ADR 0008, R11).

Simulates N users each enqueueing M scans concurrently via the durable queue
(POST /scans?source=local&queue=true), then checks that each user's job history
is isolated (no cross-contamination in GET /scans).

Usage — demo/local mode (no auth, all scans land as the "demo" user):
    python scripts/load_test_concurrency.py --url http://localhost:8000

Usage — auth mode (N distinct bearer tokens from env vars):
    BEARER_0=<tok0> BEARER_1=<tok1> BEARER_2=<tok2> \\
        python scripts/load_test_concurrency.py \\
            --url https://staging.example.com --users 3 --auth-env

The isolation check (no cross-contamination) only runs in --auth-env mode because
demo mode routes all requests to the same "demo" owner by design.

Exit codes:
    0   all invariants passed
    1   API errors, duplicate job IDs, or cross-user contamination detected
"""
import argparse
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request


def _request(url: str, method: str = "GET", headers: dict | None = None,
             timeout: int = 30) -> tuple[int, dict]:
    h = {"Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read())
        except Exception:
            pass
        return e.code, body
    except Exception as exc:
        return 0, {"error": str(exc)}


def _enqueue_scans_for_user(base_url: str, user_index: int, n_scans: int,
                             token: str | None) -> dict:
    """Enqueue n_scans for one simulated user; return timings and job IDs."""
    auth_header = {"Authorization": f"Bearer {token}"} if token else {}
    job_ids, scan_ids = [], []
    t0 = time.monotonic()

    for _ in range(n_scans):
        status, body = _request(
            f"{base_url}/scans?source=local&queue=true",
            method="POST",
            headers=auth_header,
        )
        if status not in (200, 201, 202):
            return {"user": user_index, "error": f"POST /scans → {status}: {body}",
                    "job_ids": [], "scan_ids": []}
        job_ids.append(body.get("job_id", ""))
        scan_ids.append(body.get("scan_id", ""))

    return {
        "user": user_index,
        "job_ids": job_ids,
        "scan_ids": scan_ids,
        "latency_ms": round((time.monotonic() - t0) * 1000),
        "error": None,
    }


def _check_isolation(base_url: str, results: list[dict], tokens: list[str]) -> bool:
    """Return True if no cross-user scan contamination is detected."""
    scan_sets: dict[int, set[str]] = {}
    ok = True

    for r in results:
        i = r["user"]
        status, body = _request(f"{base_url}/scans",
                                headers={"Authorization": f"Bearer {tokens[i]}"})
        if status != 200:
            print(f"  USER {i}: GET /scans → {status}", file=sys.stderr)
            ok = False
            continue
        scan_sets[i] = {s["id"] for s in body.get("scans", [])}

    for i, own_ids in scan_sets.items():
        for j, other_ids in scan_sets.items():
            if i >= j:
                continue
            cross = own_ids & other_ids
            if cross:
                print(f"  ISOLATION BREACH: user {i} and user {j} share scan IDs: {cross}",
                      file=sys.stderr)
                ok = False

    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--url", required=True,
                        help="Base URL of the ACP API, no trailing slash")
    parser.add_argument("--users", type=int, default=3,
                        help="Number of concurrent users (default: 3)")
    parser.add_argument("--scans-per-user", type=int, default=2,
                        help="Scans each user enqueues (default: 2)")
    parser.add_argument("--auth-env", action="store_true",
                        help="Read bearer tokens from BEARER_0, BEARER_1, … env vars")
    args = parser.parse_args()

    tokens: list[str | None]
    if args.auth_env:
        tokens = []
        for i in range(args.users):
            tok = os.environ.get(f"BEARER_{i}")
            if not tok:
                print(f"ERROR: BEARER_{i} is not set", file=sys.stderr)
                sys.exit(1)
            tokens.append(tok)
    else:
        tokens = [None] * args.users
        print("[demo mode] no auth tokens — all scans land as the 'demo' owner; "
              "cross-user isolation check is skipped")

    total = args.users * args.scans_per_user
    print(f"Enqueueing {args.users} users × {args.scans_per_user} scans = {total} jobs …")

    t0 = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.users) as pool:
        futs = {
            pool.submit(_enqueue_scans_for_user, args.url, i, args.scans_per_user, tokens[i]): i
            for i in range(args.users)
        }
        results = [f.result() for f in concurrent.futures.as_completed(futs)]
    wall_ms = round((time.monotonic() - t0) * 1000)

    # ── API error check ────────────────────────────────────────────────────────
    errors = [r for r in results if r.get("error")]
    if errors:
        for e in errors:
            print(f"  USER {e['user']}: {e['error']}", file=sys.stderr)
        print(f"FAIL: {len(errors)} user(s) hit API errors", file=sys.stderr)
        sys.exit(1)

    # ── Collision check ────────────────────────────────────────────────────────
    all_job_ids = [jid for r in results for jid in r["job_ids"] if jid]
    unique_count = len(set(all_job_ids))
    duplicates = len(all_job_ids) - unique_count
    lost = total - len(all_job_ids)

    print(f"\n  Wall time ({args.users} users in parallel): {wall_ms} ms")
    for r in sorted(results, key=lambda x: x["user"]):
        print(f"  USER {r['user']}: {len(r['job_ids'])} job(s) queued in {r['latency_ms']} ms")
    print(f"  Jobs expected: {total} | landed: {len(all_job_ids)} | "
          f"unique IDs: {unique_count} | duplicates: {duplicates} | lost: {lost}")

    if duplicates or lost:
        if duplicates:
            print(f"FAIL: {duplicates} duplicate job ID(s) — concurrent-enqueue collision",
                  file=sys.stderr)
        if lost:
            print(f"FAIL: {lost} job(s) lost under concurrent enqueue", file=sys.stderr)
        sys.exit(1)

    # ── Isolation check (auth mode only) ──────────────────────────────────────
    if args.auth_env:
        print("\nChecking per-user scan isolation (GET /scans) …")
        if not _check_isolation(args.url, results, tokens):
            print("FAIL: cross-user scan contamination detected", file=sys.stderr)
            sys.exit(1)
        print("  Isolation check passed — no cross-user contamination.")

    print(f"\nPASS: {total} jobs queued concurrently with no collisions"
          + (" and no isolation breaches." if args.auth_env else "."))


if __name__ == "__main__":
    main()
