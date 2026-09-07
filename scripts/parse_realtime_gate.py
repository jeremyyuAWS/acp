#!/usr/bin/env python3
"""Strictly validate the single canonical gate marker from an ACA PTY transcript."""
from __future__ import annotations

import json
import re
import sys


MARKER = "ACP_REALTIME_GATE="
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def parse(transcript: str) -> dict | None:
    clean = ANSI.sub("", transcript).replace("\r", "")
    markers = [line[len(MARKER):] for line in clean.splitlines() if line.startswith(MARKER)]
    if len(markers) != 1:
        return None
    try:
        result = json.loads(markers[0])
    except (TypeError, ValueError):
        return None
    checks = result.get("checks")
    if result.get("decision") != "GO" or not isinstance(checks, dict) or not checks:
        return None
    if not all(value is True for value in checks.values()):
        return None
    if result.get("mode") != "redis" or result.get("config", {}).get("redis_url") != "configured":
        return None
    return result


def main() -> int:
    result = parse(sys.stdin.read())
    if result is None:
        print("canonical realtime gate marker missing, duplicated, malformed, or NO-GO",
              file=sys.stderr)
        return 1
    print("GO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
