#!/usr/bin/env python3
"""Extract one strict aggregate result from an Azure container-exec transcript.

Azure CLI can return nonzero while tearing down its websocket after the remote command has
already completed.  The remote probe result—not terminal cleanup—is authoritative.  This parser
accepts exactly one well-formed marker and otherwise emits the fail-closed sentinel.  It never
echoes the transcript, which may contain Azure resource details in connection banners.
"""
from __future__ import annotations

import json
import re
import sys


PREFIX = "ACP_LEGACY_BOOTSTRAP="
EXPECTED = {"redis_write_read", "queued", "retrying", "running"}
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def parse(transcript: str) -> tuple[bool, int, int, int] | None:
    clean = ANSI.sub("", transcript)
    markers = [line[len(PREFIX):] for line in clean.splitlines() if line.startswith(PREFIX)]
    if len(markers) != 1:
        return None
    try:
        result = json.loads(markers[0])
    except (TypeError, ValueError):
        return None
    if not isinstance(result, dict) or set(result) != EXPECTED:
        return None
    values = result["queued"], result["retrying"], result["running"]
    if result["redis_write_read"] is not True:
        return None
    if not all(type(value) is int and value >= 0 for value in values):
        return None
    return True, *values


def main() -> None:
    parsed = parse(sys.stdin.read())
    print(*(("true", *parsed[1:]) if parsed is not None else ("false", "", "", "")))


if __name__ == "__main__":
    main()
