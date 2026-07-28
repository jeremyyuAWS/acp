"""The result vocabulary: what we concluded, how sure we are, and how much we actually looked.

`store._rule_outcome` answers PASS / FAIL / REVIEW / NOT_EVALUATED. That vocabulary conflates
two genuinely independent questions, and the 4.1.2-on-PDF bug is what the conflation costs:

  * `pdf_form_field_checks` runs on every PDF and can fail a file on three distinct grounds.
  * 4.1.2 is html-only in `store.RULE_FORMATS`, so a clean PDF resolves to NOT_EVALUATED.
  * `tests/test_rule_formats.py` asserts exactly that, reasoning "no validator ran".

That reason was true when it was written and is false now — a validator does run. But there
was no way to say so: the only token weaker than PASS was "we didn't look". So a real
detector's clean result got reported as no coverage at all.

COVERAGE is the missing axis. It answers "how much of this criterion did our technique
actually reach for this format?", which is a property of our IMPLEMENTATION. STATUS answers
"what did we find in this document?", which is a property of the FILE. A rule can be
HEURISTIC coverage and a confident FAIL at the same time; it can be FULL coverage and a
confident PASS. Neither collapses into the other.

The practical payoff is that a (rule, format) pair improves along the coverage axis without
the engine changing shape. 4.1.2 PDF today is honestly PARTIAL — AcroForm widgets only. When
a tag-tree walker lands it becomes FULL. Nothing about `evaluate()` changes; one registration
changes, and the matrix's ceiling follows automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Coverage(str, Enum):
    """How much of the criterion our technique reaches for this format. Ordered weakest to
    strongest — `RANK` below relies on the declaration order."""

    UNSUPPORTED = "unsupported"   # the format can't express what the rule is about; nothing to run
    DECLARED = "declared"         # we know it applies and have no technique yet — an honest IOU
    HEURISTIC = "heuristic"       # a proxy signal that correlates; can be wrong in both directions
    PARTIAL = "partial"           # a sound technique over a strict subset of the criterion
    FULL = "full"                 # the whole criterion, as far as the format can express it


class Confidence(str, Enum):
    """How much weight a single result carries. Distinct from coverage: a PARTIAL technique can
    be highly confident about the part it covers, which is exactly the 4.1.2 PDF case."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


RANK: dict[Coverage, int] = {c: i for i, c in enumerate(Coverage)}

# Coverage -> can a clean scan be reported as a certified PASS?
#
# Only FULL earns a pass. Everything weaker means we did not examine the whole criterion, so
# "no findings" is not evidence of conformance — it is evidence of nothing having tripped the
# part we looked at. This is ADR 0016's rule ("never fabricate a pass") expressed on the new
# axis, and it is why a PARTIAL detector's clean scan surfaces as REVIEW rather than PASS.
CAN_CERTIFY_PASS: frozenset[Coverage] = frozenset({Coverage.FULL})

# Coverage -> is a human review the honest resting state for a clean scan?
NEEDS_REVIEW_ON_CLEAN: frozenset[Coverage] = frozenset(
    {Coverage.PARTIAL, Coverage.HEURISTIC})


@dataclass(frozen=True)
class AssessmentResult:
    """One (rule, format, document) verdict.

    `status` is intentionally the same token set `store._rule_outcome` already returns, so this
    can be threaded through the existing pipeline incrementally rather than as a big-bang
    swap — a caller that only reads `.status` behaves exactly as it does today.
    """

    status: str                              # PASS | FAIL | REVIEW | NOT_EVALUATED
    coverage: Coverage
    confidence: Confidence
    evidence: list[dict] = field(default_factory=list)
    remediation: list[dict] = field(default_factory=list)
    reason: str = ""                         # why coverage is what it is — user-facing

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "coverage": self.coverage.value,
            "confidence": self.confidence.value,
            "evidence": self.evidence,
            "remediation": self.remediation,
            "reason": self.reason,
        }


def unsupported(reason: str) -> AssessmentResult:
    """The format cannot express what the rule asks about.

    Deliberately NOT a pass and NOT a failure. `tests/test_rule_formats.py` states the
    principle this encodes: "We may say 'we did not check this'. We may not say 'this does not
    apply'." The reason string carries the fact we DO hold — which capability was missing.
    """
    return AssessmentResult(status="NOT_EVALUATED", coverage=Coverage.UNSUPPORTED,
                            confidence=Confidence.HIGH, reason=reason)
