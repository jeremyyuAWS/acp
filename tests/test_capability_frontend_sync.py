"""Contract: the frontend's bundled CAPABILITY_FALLBACK (frontend/src/capability.js —
used in SIM and as the pre-fetch default) must equal the backend's authoritative
remediation_capability.CAPABILITY, byte-for-byte in meaning. Without this the JS copy is
free to drift, re-introducing the exact "three disagreeing tables" problem this whole
change removes — just across the language boundary instead of within one.

The JS constant is authored as a strict-JSON object literal precisely so this test can
parse it with json.loads and diff it structurally.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import remediation_capability as cap  # noqa: E402

_JS = (ACP / "frontend" / "src" / "capability.js").read_text()


def _extract_fallback() -> dict:
    m = re.search(r"export const CAPABILITY_FALLBACK\s*=\s*(\{.*?\n\})", _JS, re.S)
    assert m, "CAPABILITY_FALLBACK object literal not found in capability.js"
    return json.loads(m.group(1))


def test_frontend_fallback_matches_backend_capability():
    assert _extract_fallback() == cap.CAPABILITY, (
        "frontend/src/capability.js CAPABILITY_FALLBACK has drifted from "
        "api/remediation_capability.py CAPABILITY — update the JS copy to match."
    )
