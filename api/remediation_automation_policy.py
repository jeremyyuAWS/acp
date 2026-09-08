"""Authoritative contract for the remediation automation-policy preview.

The UI may explain this result, but it must never re-classify a finding.  In particular,
``primary_reason`` is a single value (or ``None`` when the evidence is insufficient); consumers
must not turn an unknown into a more reassuring reason.
"""
from __future__ import annotations

from collections import defaultdict
from enum import Enum
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable


class RoutingReason(str, Enum):
    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    SUBJECTIVE_DECISION = "subjective_decision"
    MISSING_EVIDENCE = "missing_evidence"
    UNSUPPORTED_REMEDIATION = "unsupported_remediation"
    SAFETY_RULE = "safety_rule"
    FAILED_VERIFICATION = "failed_verification"


REASON_ORDER = tuple(reason.value for reason in RoutingReason)
LANES = frozenset({"automatic", "review", "protected"})


def _text(value: Any) -> str | None:
    value = str(value or "").strip()
    return value or None


def _criterion(row: dict) -> str | None:
    value = _text(row.get("criterion") or row.get("rule_id") or row.get("ruleId"))
    if not value:
        return None
    return value.removeprefix("WCAG_").removeprefix("SC_").replace("_", ".")


def _format(row: dict) -> str | None:
    explicit = _text(row.get("format"))
    if explicit:
        return explicit.lower()
    filename = _text(row.get("file"))
    if not filename or "." not in filename:
        return None
    return filename.rsplit(".", 1)[1].lower()


def primary_reason(row: dict) -> str | None:
    """Return exactly one recorded/derivable reason, never a guessed fallback.

    An explicit backend reason wins.  Legacy evidence is evaluated in safety precedence: a failed
    verification and a hard safety rule are stronger explanations than proposal characteristics.
    """
    explicit = _text(row.get("primary_reason") or row.get("primaryReason"))
    if explicit in REASON_ORDER:
        return explicit
    if row.get("verification_failed") is True or row.get("verificationFailed") is True:
        return RoutingReason.FAILED_VERIFICATION.value
    if row.get("safety_rule") is True or row.get("safetyRule") is True or row.get("rejectedFix") is True:
        return RoutingReason.SAFETY_RULE.value
    supported = row.get("remediation_supported", row.get("remediationSupported"))
    if supported is False or row.get("hasProposal") is False:
        return RoutingReason.UNSUPPORTED_REMEDIATION.value
    evidence = row.get("evidence_complete", row.get("evidenceComplete"))
    if evidence is False:
        return RoutingReason.MISSING_EVIDENCE.value
    if row.get("subjective") is True or row.get("subjective_decision") is True:
        return RoutingReason.SUBJECTIVE_DECISION.value
    confidence = row.get("confidence")
    threshold = row.get("confidence_threshold", row.get("confidenceThreshold"))
    if isinstance(confidence, (int, float)) and isinstance(threshold, (int, float)) and confidence < threshold:
        return RoutingReason.CONFIDENCE_BELOW_THRESHOLD.value
    return None


def _lane(row: dict, reason: str | None) -> str:
    # The evaluator's lane is an independent policy outcome; the reason explains why that lane
    # was chosen.  Do not silently move a recorded review item into protected (or vice versa).
    lane = _text(row.get("lane"))
    if lane in LANES:
        return lane
    if reason in {RoutingReason.SAFETY_RULE.value, RoutingReason.FAILED_VERIFICATION.value}:
        return "protected"
    if reason is not None:
        return "review"
    # Unknown is conservatively open/protected, but remains unknown in the reason contract.
    return "protected"


def _count(rows: Iterable[dict]) -> dict[str, int]:
    rows = list(rows)
    return {"findings": len(rows), "files": len({_text(r.get("file")) for r in rows if _text(r.get("file"))})}


def build_policy_preview(findings: Iterable[dict] | None, *, level: int | None = None) -> dict:
    """Build the versioned, internally checkable policy-preview response."""
    rows = [dict(row) for row in (findings or []) if isinstance(row, dict)]
    routed: list[dict] = []
    by_lane: dict[str, list[dict]] = defaultdict(list)
    by_reason: dict[str, list[dict]] = defaultdict(list)
    unknown: list[dict] = []
    for row in rows:
        reason = primary_reason(row)
        lane = _lane(row, reason)
        normalized = {**row, "primary_reason": reason, "lane": lane,
                      "criterion": _criterion(row), "format": _format(row)}
        routed.append(normalized)
        by_lane[lane].append(normalized)
        if reason is None:
            if lane != "automatic":
                unknown.append(normalized)
        else:
            by_reason[reason].append(normalized)

    reasons = []
    for reason in REASON_ORDER:
        bucket = by_reason[reason]
        if not bucket:
            continue
        criteria: dict[str, list[dict]] = defaultdict(list)
        formats: dict[str, list[dict]] = defaultdict(list)
        for row in bucket:
            criteria[row["criterion"] or "Unknown"].append(row)
            formats[row["format"] or "unknown"].append(row)
        reasons.append({
            "reason": reason, **_count(bucket),
            "criteria": [{"criterion": key, **_count(value)} for key, value in sorted(criteria.items())],
            "formats": [{"format": key, **_count(value)} for key, value in sorted(formats.items())],
        })

    lanes = {lane: _count(by_lane[lane]) for lane in ("automatic", "review", "protected")}
    opened = _count(routed)
    lane_sum = sum(lanes[lane]["findings"] for lane in lanes)
    return {
        "contract_version": "remediation-automation-policy-preview.v1",
        "level": level,
        "open": opened,
        "lanes": lanes,
        "reasons": reasons,
        "findings": routed,
        "integrity": {
            "open_equals_lane_sum": opened["findings"] == lane_sum,
            "reason_is_mutually_exclusive": True,
            "unknown_primary_reason": _count(unknown),
            "complete": opened["findings"] == lane_sum and not unknown,
        },
    }


DEFAULT_LEVEL = 3
MIN_LEVEL, MAX_LEVEL = 1, 5


class PolicyConflict(Exception):
    def __init__(self, current: dict):
        self.current = current


class IdempotencyConflict(Exception):
    pass


class ActiveRunUnsupported(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(action: str, level: int, expected_revision: int) -> str:
    raw = json.dumps({"action": action, "level": level,
                      "expected_revision": expected_revision}, sort_keys=True,
                     separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def snapshot_for_future_run(store, owner: str) -> dict:
    """Content-addressed immutable value to place in a newly accepted run's job contract."""
    saved = read(store, owner)["policy"]
    canonical = json.dumps({"owner": owner, "level": int(saved["level"]),
                            "policy_revision": int(saved["revision"])},
                           sort_keys=True, separators=(",", ":"))
    return {"snapshot_id": "rap-" + hashlib.sha256(canonical.encode()).hexdigest()[:24],
            "level": int(saved["level"]), "policy_revision": int(saved["revision"])}


def bind_run_snapshot(store, owner: str, actor: str, scan_id: str, batch_id: str,
                      snapshot: dict) -> None:
    """Seal policy provenance once; a replay of the same accepted batch is a no-op."""
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO remediation_run_policy_snapshot(scan_id,batch_id,"
                          "snapshot_id,owner_email,level,policy_revision,created_at,created_by) "
                          "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,batch_id) DO NOTHING",
                          (scan_id, batch_id, snapshot["snapshot_id"], owner, snapshot["level"],
                           snapshot["policy_revision"], _now(), actor))


def read(store, owner: str, *, scan_id: str | None = None) -> dict:
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT level,revision,updated_at,updated_by "
                          "FROM remediation_automation_policy WHERE owner_email=%s", (owner,))
        row = store._db.fetchone(cur)
        snapshot = None
        if scan_id:
            store._db.execute(cur, "SELECT snapshot_id,level,policy_revision,batch_id,created_at "
                              "FROM remediation_run_policy_snapshot WHERE scan_id=%s "
                              "AND owner_email=%s ORDER BY created_at DESC LIMIT 1",
                              (scan_id, owner))
            snapshot = store._db.fetchone(cur)
    policy = row or {"level": DEFAULT_LEVEL, "revision": 0,
                     "updated_at": None, "updated_by": None}
    return {"policy": policy, "run_policy_snapshot": snapshot,
            "capabilities": {"apply_waiting": False,
                             "reason": "This run cannot be safely re-routed after it starts."}}


def _execute_once(store, owner: str, actor: str, *, action: str, level: int,
                  expected_revision: int, idempotency_key: str) -> dict:
    if action == "apply_waiting":
        raise ActiveRunUnsupported()
    if action != "save_future":
        raise ValueError("unknown policy action")
    level = int(level)
    expected_revision = int(expected_revision)
    if not MIN_LEVEL <= level <= MAX_LEVEL:
        raise ValueError("level must be between 1 and 5")
    request_digest = _digest(action, level, expected_revision)
    now = _now()
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT request_digest,result_json FROM remediation_policy_action "
                          "WHERE owner_email=%s AND idempotency_key=%s", (owner, idempotency_key))
        prior = store._db.fetchone(cur)
        if prior:
            if prior["request_digest"] != request_digest:
                raise IdempotencyConflict()
            return {**json.loads(prior["result_json"]), "duplicate": True}
        store._db.execute(cur, "SELECT level,revision,updated_at,updated_by FROM "
                          "remediation_automation_policy WHERE owner_email=%s", (owner,))
        current = store._db.fetchone(cur)
        current_view = current or {"level": DEFAULT_LEVEL, "revision": 0,
                                   "updated_at": None, "updated_by": None}
        if int(current_view["revision"]) != expected_revision:
            # A concurrent identical request can commit between the receipt lookup above and
            # this policy read (SQLite defers its transaction until the first write; PostgreSQL
            # can reach the same window at READ COMMITTED). Reconcile the receipt once more
            # before calling the retry stale. Otherwise an exact retry nondeterministically
            # becomes PolicyConflict even though its first copy completed successfully.
            store._db.execute(cur, "SELECT request_digest,result_json FROM remediation_policy_action "
                              "WHERE owner_email=%s AND idempotency_key=%s",
                              (owner, idempotency_key))
            concurrent = store._db.fetchone(cur)
            if concurrent:
                if concurrent["request_digest"] != request_digest:
                    raise IdempotencyConflict()
                return {**json.loads(concurrent["result_json"]), "duplicate": True}
            raise PolicyConflict(current_view)
        next_revision = expected_revision + 1
        if current:
            store._db.execute(cur, "UPDATE remediation_automation_policy SET level=%s,revision=%s,"
                              "updated_at=%s,updated_by=%s WHERE owner_email=%s AND revision=%s",
                              (level, next_revision, now, actor, owner, expected_revision))
            if cur.rowcount != 1:
                store._db.execute(cur, "SELECT level,revision,updated_at,updated_by FROM "
                                  "remediation_automation_policy WHERE owner_email=%s", (owner,))
                raise PolicyConflict(store._db.fetchone(cur) or current_view)
        else:
            store._db.execute(cur, "INSERT INTO remediation_automation_policy"
                              "(owner_email,level,revision,updated_at,updated_by) VALUES(%s,%s,%s,%s,%s)",
                              (owner, level, next_revision, now, actor))
        result = {"action": action, "policy": {"level": level, "revision": next_revision,
                  "updated_at": now, "updated_by": actor}, "duplicate": False}
        store._db.execute(cur, "INSERT INTO remediation_policy_action(owner_email,idempotency_key,"
                          "request_digest,action,result_json,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                          (owner, idempotency_key, request_digest, action,
                           json.dumps(result, sort_keys=True), now))
        store._db.execute(cur, "INSERT INTO decision_log(id,ts,actor,action,scan_id,file,rule_id,detail) "
                          "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                          (uuid.uuid4().hex[:12], now, actor, "remediation.policy.saved", None,
                           None, None, json.dumps({"level": level, "revision": next_revision,
                                                  "idempotency_key": idempotency_key}, sort_keys=True)))
        return result


def execute(store, owner: str, actor: str, *, action: str, level: int,
            expected_revision: int, idempotency_key: str) -> dict:
    try:
        return _execute_once(store, owner, actor, action=action, level=level,
                             expected_revision=expected_revision, idempotency_key=idempotency_key)
    except Exception as exc:
        if "unique" not in str(exc).lower() and "duplicate" not in str(exc).lower():
            raise
        return _execute_once(store, owner, actor, action=action, level=level,
                             expected_revision=expected_revision, idempotency_key=idempotency_key)
