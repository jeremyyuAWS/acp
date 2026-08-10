"""Contract: the v2 frontend's capability fallbacks must equal the backend, same as v1's.

frontend-v2/src/capability.js carries the SAME two projections v1 does — CAPABILITY_FALLBACK
(remediation ⚡/🤖/👤) and ASSESSMENT_FALLBACK (assessment 🟢/🟡/🔴) — bundled as the pre-fetch
default the redesign renders from. test_capability_frontend_sync.py pins the v1 copy to the
backend; nothing pinned the v2 copy, and it drifted exactly as an unguarded copy does.

MEASURED. On the code this test was written against, the v2 docx remediation block ended at
"3.3.2" and was missing four criteria the backend declares — 1.4.1, 1.4.11, 2.1.2 and 4.1.2, the
docx lanes added across #202/#203/#206/#208. v1's capability.js was updated in each of those
changes; v2 was not, because no test made it fail. So this is both the fix (sync v2) and the
guard that keeps it fixed: the drift is silent precisely because v2 has no backend sync guard, and
this is that guard.

The JS constants are authored as strict-JSON object literals so json.loads can parse them, exactly
as the v1 guard relies on.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import remediation_capability as cap  # noqa: E402

_JS = (ACP / "frontend-v2" / "src" / "capability.js").read_text()


def _extract(name: str) -> dict:
    m = re.search(rf"export const {name}\s*=\s*(\{{.*?\n\}})", _JS, re.S)
    assert m, f"{name} object literal not found in frontend-v2/src/capability.js"
    return json.loads(m.group(1))


def test_v2_remediation_fallback_matches_backend():
    assert _extract("CAPABILITY_FALLBACK") == cap.remediation_table(), (
        "frontend-v2/src/capability.js CAPABILITY_FALLBACK has drifted from "
        "api/remediation_capability.py remediation_table() — update the JS copy to match."
    )


def test_v2_assessment_fallback_matches_backend():
    assert _extract("ASSESSMENT_FALLBACK") == cap.assessment_table(), (
        "frontend-v2/src/capability.js ASSESSMENT_FALLBACK has drifted from "
        "api/remediation_capability.py assessment_table() — update the JS copy to match."
    )
