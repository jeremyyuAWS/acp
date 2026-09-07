#!/usr/bin/env python3
"""Run the canonical gate against this staging container's Redis and emit one result marker."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from performance.canonical_realtime_gate import GateConfig, run


def main() -> int:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        print("staging_realtime_gate: REDIS_URL is not configured", file=sys.stderr)
        return 2
    result = run(GateConfig(redis_url=redis_url))
    print("ACP_REALTIME_GATE=" + json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if result["decision"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
