#!/usr/bin/env python3
"""
SSE smoke test for the Discover live-update stream.

Tests that:
  1. POST /scans starts a scan and returns a scan_id.
  2. GET /scans/{sid}/events emits valid SSE frames.
  3. Each frame is valid JSON with required fields (available, active, phase).
  4. Counters are monotonically non-decreasing.
  5. The stream terminates (active→False) within the timeout.
  6. No frame ever claims available=False mid-run (would be a logic error).

Usage (token from browser DevTools → Network → any /api/ request → Authorization header):

    # Staging with real Google auth:
    uv run python3 scripts/smoke_sse_discover.py \\
        --url https://<STAGING_FQDN> \\
        --token "<bearer-token-from-browser>"

    # Local API in ACCESS_CODE/demo mode (no token needed):
    uv run python3 scripts/smoke_sse_discover.py \\
        --url http://localhost:8000

    # Drive source (needs the GIS token the browser passes as x-drive-token):
    uv run python3 scripts/smoke_sse_discover.py \\
        --url https://<STAGING_FQDN> \\
        --token "<bearer-token>" \\
        --source drive \\
        --drive-token "<gis-access-token>"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import urllib.error


# Fields that must be present in every snapshot frame.
REQUIRED_FIELDS = {"available", "active", "phase", "state"}

# Snapshot counter paths (nested) that must never decrease between frames.
# Each entry is (label, top-level key, nested key).
MONOTONIC_FIELDS = (
    ("discovered",  "totals",   "discovered"),
    ("eligible",    "totals",   "eligible"),
    ("completed",   "kpis",     "completed"),
    ("passed",      "outcomes", "passed"),
    ("review",      "outcomes", "review"),
    ("failed",      "outcomes", "failed"),
)


def _counter(frame: dict, top: str, key: str):
    return frame.get(top, {}).get(key)


def _headers(token: str | None, drive_token: str | None = None) -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if drive_token:
        h["x-drive-token"] = drive_token
    return h


def _post_scan(base_url: str, source: str, token: str | None,
               drive_token: str | None) -> str:
    url = f"{base_url.rstrip('/')}/scans?source={source}&ai=false&incremental=false"
    req = urllib.request.Request(url, data=b"", headers=_headers(token, drive_token),
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            detail = json.loads(body_bytes).get("detail", body_bytes.decode())
        except Exception:
            detail = body_bytes.decode()
        print(f"FAIL: POST /scans → HTTP {e.code}: {detail}", file=sys.stderr)
        sys.exit(1)

    scan_id = body.get("scan_id")

    # Default (non-queue) path returns job_id immediately; scan_id appears once discovered.
    if not scan_id:
        job_id = body.get("job_id")
        if not job_id:
            print(f"FAIL: no scan_id or job_id in response: {body}", file=sys.stderr)
            sys.exit(1)
        print(f"  scan enqueued  job_id={job_id}  polling for scan_id …")
        scan_id = _poll_job(base_url, job_id, token)

    print(f"  scan started  scan_id={scan_id}  source={source}")
    return scan_id


def _poll_job(base_url: str, job_id: str, token: str | None,
              timeout: float = 60.0) -> str:
    url = f"{base_url.rstrip('/')}/scans/jobs/{job_id}"
    req = urllib.request.Request(url, headers=_headers(token))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                job = json.loads(r.read())
        except Exception as e:
            print(f"  WARN: polling job failed: {e}", file=sys.stderr)
            time.sleep(2)
            continue
        if job.get("done"):
            scan_id = job.get("scan_id")
            if not scan_id:
                print(f"FAIL: job done but no scan_id: {job}", file=sys.stderr)
                sys.exit(1)
            return scan_id
        if job.get("error"):
            print(f"FAIL: scan job errored: {job.get('error')}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
    print(f"FAIL: timed out waiting for job {job_id} to produce a scan_id", file=sys.stderr)
    sys.exit(1)


def _stream_events(base_url: str, scan_id: str, token: str | None,
                   timeout: float) -> list[dict]:
    url = f"{base_url.rstrip('/')}/scans/{scan_id}/events"
    req = urllib.request.Request(url, headers={**_headers(token), "Accept": "text/event-stream"})

    frames: list[dict] = []
    deadline = time.monotonic() + timeout

    try:
        with urllib.request.urlopen(req, timeout=timeout + 5) as r:
            buf = b""
            while time.monotonic() < deadline:
                chunk = r.read(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n\n" in buf:
                    frame_bytes, buf = buf.split(b"\n\n", 1)
                    for line in frame_bytes.split(b"\n"):
                        line = line.strip()
                        if line.startswith(b"data:"):
                            payload = line[5:].strip()
                            try:
                                frames.append(json.loads(payload))
                            except json.JSONDecodeError as e:
                                print(f"  WARN: invalid JSON in frame: {e}", file=sys.stderr)
                        elif line.startswith(b":"):
                            pass  # keep-alive comment, ignore
                # Stop as soon as the stream signals completion.
                if frames and not frames[-1].get("active", True):
                    break
    except TimeoutError:
        pass  # treat as stream-closed-by-server after timeout

    return frames


def _check(frames: list[dict]) -> list[str]:
    errors: list[str] = []

    if not frames:
        return ["no SSE frames received — stream was empty or unreachable"]

    prev: dict = {}
    for i, f in enumerate(frames):
        missing = REQUIRED_FIELDS - f.keys()
        if missing:
            errors.append(f"frame {i}: missing required fields {missing}")

        if f.get("available") is False and f.get("active") is True:
            errors.append(f"frame {i}: available=False while active=True (logic error)")

        for label, top, key in MONOTONIC_FIELDS:
            v = _counter(f, top, key)
            p = _counter(prev, top, key)
            if v is not None and p is not None:
                if isinstance(v, (int, float)) and isinstance(p, (int, float)) and v < p:
                    errors.append(f"frame {i}: {label} went backwards ({p} → {v})")
        prev = f

    last = frames[-1]
    if last.get("active", True):
        errors.append(
            "stream closed before scan reached a terminal state (active is still True on last frame)"
            " — increase --timeout or the scan is still running"
        )

    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description="SSE smoke test for Discover live-update stream")
    ap.add_argument("--url", default="http://localhost:8000",
                    help="Base URL of the ACP API (default: http://localhost:8000)")
    ap.add_argument("--token", default=None,
                    help="Bearer token (Authorization header value, without 'Bearer ' prefix)")
    ap.add_argument("--source", default="local", choices=["local", "drive", "sharepoint"],
                    help="Scan source (default: local; use drive/sharepoint with --drive-token)")
    ap.add_argument("--drive-token", default=None, dest="drive_token",
                    help="GIS access token for x-drive-token header (required for --source=drive)")
    ap.add_argument("--timeout", type=float, default=120,
                    help="Seconds to wait for the SSE stream to complete (default: 120)")
    args = ap.parse_args()

    if args.source == "drive" and not args.drive_token:
        print("FAIL: --source=drive requires --drive-token", file=sys.stderr)
        sys.exit(1)

    print(f"\nSSE smoke test  url={args.url}  source={args.source}")
    print("-" * 60)

    # 1. Start the scan.
    scan_id = _post_scan(args.url, args.source, args.token, args.drive_token)

    # 2. Give the scan a moment to register before streaming.
    time.sleep(1)

    # 3. Stream SSE events until terminal or timeout.
    print(f"  connecting to  /scans/{scan_id}/events  (timeout={args.timeout}s)")
    t0 = time.monotonic()
    frames = _stream_events(args.url, scan_id, args.token, timeout=args.timeout)
    elapsed = time.monotonic() - t0

    print(f"  received {len(frames)} frame(s) in {elapsed:.1f}s")

    # 4. Print a brief phase progression log.
    phases_seen: list[str] = []
    for f in frames:
        p = f.get("phase") or f.get("state") or "?"
        if not phases_seen or phases_seen[-1] != p:
            phases_seen.append(p)
            completed = _counter(f, "kpis", "completed") or 0
            total = (_counter(f, "totals", "eligible")
                     or _counter(f, "totals", "discovered") or "?")
            print(f"    phase={p:<20} completed={completed}/{total}")

    # 5. Print final snapshot summary.
    if frames:
        last = frames[-1]
        print(f"\n  final snapshot:")
        for k in ("phase", "state", "active", "available"):
            if k in last:
                print(f"    {k}: {last[k]}")
        for label, top, key in MONOTONIC_FIELDS:
            v = _counter(last, top, key)
            if v is not None:
                print(f"    {label}: {v}")

    # 6. Validate.
    print()
    errors = _check(frames)
    if errors:
        print(f"FAIL: {len(errors)} assertion(s) failed:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    print("PASS: SSE stream delivered valid, monotonic frames and reached terminal state.")
    print(f"      {len(frames)} frame(s) | phases: {' → '.join(phases_seen)} | {elapsed:.1f}s")


if __name__ == "__main__":
    main()
