"""ADR 0026 Epic 1 — the no-silent-gaps contract: every catalogued criterion × format × signal
combination resolves to an EXPLICIT outcome. A criterion may be PASS, FAIL, REVIEW, or
NOT_EVALUATED — it may never fall through to None, raise, or invent a new token. This is the
test that keeps 'evaluated + not_evaluated + review == catalog_size' true forever."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import store as store_mod  # noqa: E402

FORMATS = ("docx", "xlsx", "pptx", "pdf", "html", None)   # None = unknown format
SIGNALS = ((0, 0), (1, 0), (0, 1), (2, 3))                # (fail_count, review_count)
ALLOWED = {"PASS", "FAIL", store_mod.REVIEW, store_mod.NOT_EVALUATED,
           getattr(store_mod, "_LEGACY_NOT_EVALUATED", store_mod.NOT_EVALUATED)}


def test_every_criterion_format_signal_resolves_explicitly():
    unresolved = []
    for rule in store_mod.RULE_CATALOG:
        for fmt in FORMATS:
            for fails, reviews in SIGNALS:
                try:
                    out = store_mod._rule_outcome(rule["id"], fmt, fails, reviews)
                except Exception as e:   # a raise IS a silent gap — the scan would misreport
                    unresolved.append((rule["id"], fmt, fails, reviews, f"raised {e!r}"))
                    continue
                if out not in ALLOWED:
                    unresolved.append((rule["id"], fmt, fails, reviews, f"got {out!r}"))
    assert not unresolved, f"criteria without an explicit outcome: {unresolved[:10]}"


def test_a_blocking_finding_is_never_swallowed():
    """Whatever the lane, fail_count > 0 must surface as FAIL — a fail can never be silently
    reclassified into a softer outcome by lane bookkeeping."""
    for rule in store_mod.RULE_CATALOG:
        for fmt in ("docx", "xlsx", "pptx", "pdf", "html"):
            assert store_mod._rule_outcome(rule["id"], fmt, 1, 0) == "FAIL", (rule["id"], fmt)
