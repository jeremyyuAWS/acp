"""Contract: the frontend's bundled capability fallbacks (frontend/src/capability.js — used
in SIM and as the pre-fetch default) must equal the backend's authoritative projections,
byte-for-byte in meaning, on BOTH axes (ADR 0023):

  CAPABILITY_FALLBACK  == remediation_capability.remediation_table()  (⚡/🤖/👤 remediation)
  ASSESSMENT_FALLBACK  == remediation_capability.assessment_table()   (🟢/🟡/🔴 assessment)

Without this the JS copies are free to drift, re-introducing the exact "disagreeing tables"
problem this whole change removes — just across the language boundary. The JS constants are
authored as strict-JSON object literals precisely so this test can parse them with json.loads.
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


def _extract(name: str) -> dict:
    m = re.search(rf"export const {name}\s*=\s*(\{{.*?\n\}})", _JS, re.S)
    assert m, f"{name} object literal not found in capability.js"
    return json.loads(m.group(1))


def test_frontend_remediation_fallback_matches_backend():
    assert _extract("CAPABILITY_FALLBACK") == cap.remediation_table(), (
        "frontend/src/capability.js CAPABILITY_FALLBACK has drifted from "
        "api/remediation_capability.py remediation_table() — update the JS copy to match."
    )


def test_frontend_assessment_fallback_matches_backend():
    assert _extract("ASSESSMENT_FALLBACK") == cap.assessment_table(), (
        "frontend/src/capability.js ASSESSMENT_FALLBACK has drifted from "
        "api/remediation_capability.py assessment_table() — update the JS copy to match."
    )
