"""Map an axe-core run over ACP's own screens into ACR evidence records (PRD §7.6, §13).

WHY THIS EXISTS. Phase 1 attaches evidence one row at a time through a form, which is right for a
manual keyboard test and hopeless for automation: a single axe run over one ACP screen yields
results against dozens of criteria at once. This is the ingestion half — the thing that makes
"attach the automated evidence" a real workflow rather than a data-entry exercise.

THE FOUR AXE RESULT BUCKETS ARE NOT THREE PASSES AND A FAIL
------------------------------------------------------------
axe-core reports every rule into one of four buckets, and the difference between them is exactly
where an automated accessibility tool invents conformance if nobody is careful:

    violations    the rule ran and found a defect            -> RESULT_FAIL
    passes        the rule ran and its checks held           -> RESULT_PASS
    incomplete    the rule ran and COULD NOT DECIDE          -> RESULT_BLOCKED
    inapplicable  no element on the page matched the rule    -> NOT EVIDENCE AT ALL

The last two are the ones that matter.

`incomplete` is axe saying a human must look — colour contrast over a background image is the
canonical case. Mapping it to `pass` would turn "I could not tell" into "it conforms". It maps to
`blocked`, which acr_rules already refuses to treat as a positive result (see has_human_pass).

`inapplicable` is dropped entirely rather than recorded as a pass. A page with no `<video>` tells
you nothing whatsoever about whether the product captions its videos; recording that as evidence
for 1.2.2 would manufacture conformance out of absence. This is the single most tempting mistake
in this module — "the rule didn't fail, so it's fine" — and it is wrong in the direction that
produces a false ACR.

COVERAGE IS PER-RULE AND NEVER FULL
------------------------------------
Every emitted row declares `Coverage.PARTIAL`. That is not laziness, it is what axe is: its own
documentation is explicit that automated testing catches a minority of accessibility issues, and
each rule tests a specific technique rather than the whole success criterion. `2.4.7 Focus Visible`
is not established by `focus-order-semantics` passing.

The consequence, by design, is that ingesting a completely clean axe run moves NO criterion to
"Supports" — acr_rules gates that on Coverage.FULL (ADR 0031). It records what the tool actually
established and leaves the criterion needing a human, which is PRD §4.3.

TAG DECODING follows the convention already used in frontend/src/htmlAudit.js and
A11ySelfCheck.jsx: axe tags a rule with `wcag<major><minor><criterion>` — `wcag143` is 1.4.3,
`wcag2411` is 2.4.11. Kept identical so the backend and the two frontend readers cannot disagree
about which criterion a rule belongs to.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from acr_model import (RESULT_BLOCKED, RESULT_FAIL, RESULT_PASS, SRC_AUTOMATED, Evidence)

# `wcag` + at least three digits: major, minor, then the rest (2.4.11 -> wcag2411).
_TAG = re.compile(r"^wcag(\d)(\d)(\d+)$")

# The four buckets axe reports, and what each becomes. `inapplicable` is deliberately absent —
# see the module docstring; it is dropped rather than mapped, and INGESTED_BUCKETS is what the
# route iterates so adding a bucket here is a deliberate act.
BUCKET_RESULT: dict[str, str] = {
    "violations": RESULT_FAIL,
    "passes": RESULT_PASS,
    "incomplete": RESULT_BLOCKED,
}
INGESTED_BUCKETS: tuple[str, ...] = tuple(BUCKET_RESULT)
DROPPED_BUCKETS: tuple[str, ...] = ("inapplicable",)

# Every axe rule reaches a strict subset of its criterion. See the module docstring for why this
# is never FULL and what follows from that.
AXE_COVERAGE = "partial"

TOOL_NAME = "axe-core"


class AxeIngestError(ValueError):
    """The payload is not an axe-core result object."""


def criteria_for_tags(tags) -> list[str]:
    """Every WCAG criterion an axe rule's tags name, in tag order.

    A rule can carry several (`color-contrast` is tagged wcag143 only; others span two), so this
    returns a list rather than the first match. frontend/src/htmlAudit.js takes the first because
    it renders one label; here every criterion the rule speaks to should receive the evidence.
    """
    out: list[str] = []
    for tag in tags or []:
        m = _TAG.match(str(tag))
        if m:
            sc = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            if sc not in out:
                out.append(sc)
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def summarize(payload: dict) -> dict:
    """What an axe run contains, before anything is written. Powers the ingest preview.

    Reports the dropped bucket explicitly rather than silently omitting it: a user looking at
    "312 results, 47 ingested" deserves to see where the rest went, and "inapplicable rules are
    not evidence" is a claim worth showing rather than burying.
    """
    _require_axe(payload)
    counts = {b: len(payload.get(b) or []) for b in INGESTED_BUCKETS + DROPPED_BUCKETS}
    criteria: set[str] = set()
    for bucket in INGESTED_BUCKETS:
        for rule in payload.get(bucket) or []:
            criteria.update(criteria_for_tags(rule.get("tags")))
    return {
        "tool": TOOL_NAME,
        "tool_version": payload.get("testEngine", {}).get("version"),
        "tested_url": payload.get("url"),
        "tested_at": payload.get("timestamp"),
        "counts": counts,
        "criteria_touched": sorted(criteria, key=_sortkey),
        "dropped": {
            b: (payload.get(b) and len(payload[b])) or 0 for b in DROPPED_BUCKETS
        },
        "dropped_reason": (
            "axe reports a rule as 'inapplicable' when no element on the page matched it. That is "
            "not evidence about the criterion — a page with no video says nothing about whether "
            "the product captions its videos — so these are not ingested."),
    }


def _sortkey(num: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in num.split("."))


def _require_axe(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise AxeIngestError("axe result must be a JSON object")
    if not any(k in payload for k in INGESTED_BUCKETS + DROPPED_BUCKETS):
        raise AxeIngestError(
            "payload has none of axe's result buckets (violations, passes, incomplete, "
            "inapplicable) — this does not look like an axe-core run")


def to_evidence(payload: dict, *, report_id: str, product_version: str | None = None,
                build_id: str | None = None, environment: str | None = None,
                workflow: str | None = None, tester: str | None = None,
                known_criteria: set[str] | None = None) -> tuple[list[Evidence], dict]:
    """Turn one axe run into evidence records. Returns (records, report).

    `known_criteria` is the report's applicable-criteria set. A rule tagged with a criterion the
    catalog does not carry (a WCAG 2.1-only tag, an AAA criterion, an axe-specific tag that
    happens to match the shape) is SKIPPED and counted, not silently attached to nothing — the
    caller can then say "3 results named criteria outside this report's scope" rather than
    quietly losing them.

    One record per (rule, criterion) pair. A rule tagged for two criteria produces two records,
    because each criterion's evidence list must stand on its own when a reviewer reads it.
    """
    _require_axe(payload)
    engine = payload.get("testEngine") or {}
    tool_version = engine.get("version")
    url = payload.get("url")
    tested_at = payload.get("timestamp") or _now()

    records: list[Evidence] = []
    skipped_out_of_scope: dict[str, int] = {}
    unmapped_rules: list[str] = []

    for bucket in INGESTED_BUCKETS:
        for rule in payload.get(bucket) or []:
            rule_id = rule.get("id")
            criteria = criteria_for_tags(rule.get("tags"))
            if not criteria:
                # A rule with no wcag tag at all — axe's "best-practice" rules are the usual case.
                # They are real findings but they are not WCAG criteria, so they have nowhere to
                # attach in a conformance report. Counted so the caller can say so.
                if rule_id:
                    unmapped_rules.append(rule_id)
                continue
            nodes = rule.get("nodes") or []
            for sc in criteria:
                if known_criteria is not None and sc not in known_criteria:
                    skipped_out_of_scope[sc] = skipped_out_of_scope.get(sc, 0) + 1
                    continue
                records.append(Evidence(
                    criterion_num=sc,
                    source_kind=SRC_AUTOMATED,
                    result=BUCKET_RESULT[bucket],
                    report_id=report_id,
                    tool_name=TOOL_NAME,
                    tool_version=tool_version,
                    rule_id=rule_id,
                    tested_url=url,
                    coverage=AXE_COVERAGE,
                    tested_at=tested_at,
                    product_version=product_version,
                    build_id=build_id,
                    environment=environment,
                    workflow=workflow,
                    tester=tester,
                    method=f"axe-core rule '{rule_id}' ({bucket})",
                    notes=_note(bucket, rule, len(nodes)),
                ))

    return records, {
        "ingested": len(records),
        "by_result": {r: sum(1 for e in records if e.result == r)
                      for r in sorted(set(BUCKET_RESULT.values()))},
        "criteria": sorted({e.criterion_num for e in records}, key=_sortkey),
        "skipped_out_of_scope": skipped_out_of_scope,
        "unmapped_rules": sorted(set(unmapped_rules)),
        "dropped_inapplicable": len(payload.get("inapplicable") or []),
    }


def _note(bucket: str, rule: dict, node_count: int) -> str:
    """The human-readable line a reviewer sees next to the row.

    An `incomplete` row says WHY it needs a person, because that is the whole reason it is not a
    pass and the reviewer is the one who has to finish the job.
    """
    help_text = (rule.get("help") or rule.get("description") or "").strip()
    base = f"{help_text} — {node_count} element(s)" if help_text else f"{node_count} element(s)"
    if bucket == "incomplete":
        return (f"{base}. axe could not decide this automatically and flagged it for review; "
                f"recorded as BLOCKED, not as a pass.")
    if bucket == "passes":
        return (f"{base}. This axe rule's checks held. It covers part of the criterion, not all "
                f"of it — a human evaluation is still required before Supports.")
    return base
