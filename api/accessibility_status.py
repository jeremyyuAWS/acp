"""ADR 0026 — Accessibility Status: the authoritative status model (file scope, PR 1).

A pure derivation over the per-file certification facts (`store.get_certification_facts`) — NO new
measurement, so the numbers reconcile with the coverage matrix by construction (one source of truth).
`derive_file_status` partitions the in-scope criteria into six mutually-exclusive display buckets that
sum to `in_scope` (the identity a test enforces), separates Assessment Coverage ("did ACP look?") from
Accessibility Status ("is it ready?"), and drives the hero card's state machine + one CTA.

Honesty (ADR 0016/0023): counts only, never a percentage of an invented denominator; "approved ≠
applied" gates certification; an automated pass is "Automatically Verified", never "Certified".
"""
from __future__ import annotations

# Per-item review estimate until reviewer medians exist (Phase 3 swaps in the hitl_events median).
# Labeled "~" in the UI and never presented as precision.
DEFAULT_REVIEW_SECS = 45

# State machine (ADR 0026). Order = precedence when deriving from stored facts.
STATE_ASSESSING = "assessing"                 # background measurements still running
STATE_NEEDS_REMEDIATION = "needs_remediation"
STATE_APPLY_APPROVED = "apply_approved_fixes"  # approved-but-unapplied gate (promise ≠ fix)
STATE_READY_AFTER_REVIEW = "ready_after_review"
STATE_REVALIDATING = "re_validating"           # post-fix re-scan in flight
STATE_READY = "ready_for_certification"
STATE_CERTIFIED = "certified"

# The one state-matched CTA (label map lives with the contract, not scattered in the UI).
CTA = {
    STATE_ASSESSING: None,
    STATE_NEEDS_REMEDIATION: "Start Remediation",
    STATE_APPLY_APPROVED: "Apply Approved Fixes",
    STATE_READY_AFTER_REVIEW: "Review Findings",
    STATE_REVALIDATING: None,
    STATE_READY: "Generate Report",
    STATE_CERTIFIED: "Publish Certification",
}


def derive_file_status(doc: dict, approved_review_scs, unapplied_approved: int, *,
                       per_item_secs: int = DEFAULT_REVIEW_SECS,
                       assessing: bool = False, revalidating: bool = False,
                       certified: bool = False) -> dict:
    """Derive the Accessibility Status model from ONE per-file certification-facts document.

    `doc` is an entry of `get_certification_facts()['documents']` (evaluated/failing/review/
    not_evaluated/remediated + review_criteria). `approved_review_scs` = the SCs a human has approved
    for this file. `unapplied_approved` = count_unapplied_approved_values(scan, file).

    The six buckets partition `in_scope` exactly (identity enforced by test):
        automatically_verified + human_verified + needs_review + needs_remediation
          + not_automatically_assessable == in_scope
    """
    evaluated = int(doc.get("evaluated", 0))
    failing = int(doc.get("failing", 0))
    review = int(doc.get("review", 0))
    not_evaluated = int(doc.get("not_evaluated", 0))
    remediated = int(doc.get("remediated", 0))
    review_scs = doc.get("review_criteria") or []

    # Clamp so the human-overlay can never make the buckets exceed the base partition:
    #   remediated fails ⊆ fails, approved reviews ⊆ reviews.
    remediated_eff = max(0, min(remediated, failing))
    # Keep the SC identities, not just the count: the drawer seeds its ✓ chips and the Coverage
    # Manifest marks human-approved rows from this list — same derivation as human_verified, so the
    # chips can never disagree with the hero's numbers.
    approved_sc_list = sorted(set(approved_review_scs) & set(review_scs))
    approved_reviews = len(approved_sc_list)

    automatically_verified = max(0, evaluated - failing)     # deterministic PASS
    needs_remediation = max(0, failing - remediated_eff)     # unresolved FAIL
    needs_review = max(0, review - approved_reviews)         # still awaiting a human
    human_verified = remediated_eff + approved_reviews       # a human / verified fix resolved it
    not_automatically_assessable = not_evaluated             # no auto pass/fail (v1 folds N/A in here)

    in_scope = evaluated + not_evaluated + review
    resolved = automatically_verified + human_verified + 0   # not_applicable folded for v1
    coverage_evaluable = evaluated + review                  # criteria ACP had a method for

    if assessing:
        state = STATE_ASSESSING
    elif certified:
        state = STATE_CERTIFIED
    elif revalidating:
        state = STATE_REVALIDATING
    elif needs_remediation > 0:
        state = STATE_NEEDS_REMEDIATION
    elif unapplied_approved > 0:
        state = STATE_APPLY_APPROVED
    elif needs_review > 0:
        state = STATE_READY_AFTER_REVIEW
    else:
        state = STATE_READY

    return {
        "available": True,
        "in_scope": in_scope,
        # Two distinct questions (ADR 0026): coverage = "did ACP look?", status = "is it ready?"
        "coverage": {"evaluable": coverage_evaluable, "total": in_scope},
        "resolved": resolved,
        "automatically_verified": automatically_verified,
        "human_verified": human_verified,
        "human_verified_criteria": approved_sc_list,
        "needs_review": needs_review,
        "needs_remediation": needs_remediation,
        "not_automatically_assessable": not_automatically_assessable,
        "not_applicable": 0,   # v1: folded into not_automatically_assessable (ADR limitation, noted)
        "unapplied_approved": int(unapplied_approved),
        "est_review_secs": needs_review * int(per_item_secs),
        "state": state,
        "cta": CTA.get(state),
    }


def file_status(store, scan_id: str, file: str, *, per_item_secs: int = DEFAULT_REVIEW_SECS) -> dict:
    """Compose the file-scope status from the store — the seam the endpoint calls. Reuses
    get_certification_facts (the SAME _rule_outcome the coverage matrix uses), the immutable decision
    log, and the applied-values gate. Returns {"available": False, ...} when the file isn't in scope."""
    facts = store.get_certification_facts(scan_id)
    doc = next((d for d in facts.get("documents", []) if d.get("file") == file), None)
    if doc is None:
        return {"available": False, "reason": "file_not_in_scan"}

    approved = {
        d["rule_id"] for d in store.list_decisions(scan_id, limit=2000)
        if d.get("action") == "hitl.approved" and d.get("file") == file and d.get("rule_id")
    }
    try:
        unapplied = store.count_unapplied_approved_values(scan_id, file)
    except Exception:
        unapplied = 0
    return derive_file_status(doc, approved, unapplied, per_item_secs=per_item_secs)


# The aggregation-summable fields (ADR 0026 PR 3): a scan/folder/estate status is the SUM of its
# files' models with the state machine re-derived over the totals — no new measurement, so the
# roll-up reconciles with the per-file cards by construction.
_SUM_FIELDS = (
    "in_scope", "resolved", "automatically_verified", "human_verified", "needs_review",
    "needs_remediation", "not_automatically_assessable", "not_applicable", "unapplied_approved",
)


def scan_status(store, scan_id: str, *, per_item_secs: int = DEFAULT_REVIEW_SECS,
                path_prefix: str | None = None) -> dict:
    """The Accessibility Status for a whole SCAN (ADR 0026 PR 3, first aggregation scope): derive
    the file model for every document via the SAME per-file logic, sum the buckets, and re-run the
    state machine over the totals. Powers the scan-level card and the Confidence Dashboard —
    process confidence (coverage & resolution counts), never a model % (ADR 0016).

    path_prefix narrows the roll-up to a FOLDER (files whose path starts with the prefix) — the
    same summation over a subset, so folder cards reconcile with both the scan card above them and
    the file cards below them by construction. Estate/org scopes (across scans) are a named
    follow-on: they need a cross-scan document model, not another sum here.

    NB: one count_unapplied_approved_values call per document — fine at demo/estate-slice sizes;
    batch it before pointing this at 100K-file estates (noted, not silently ignored)."""
    facts = store.get_certification_facts(scan_id)
    docs = facts.get("documents", [])
    if path_prefix:
        docs = [d for d in docs if str(d.get("file") or "").startswith(path_prefix)]
    if not docs:
        return {"available": False, "reason": "no_documents"}

    approved_by_file: dict[str, set] = {}
    for d in store.list_decisions(scan_id, limit=5000):
        if d.get("action") == "hitl.approved" and d.get("file") and d.get("rule_id"):
            approved_by_file.setdefault(d["file"], set()).add(d["rule_id"])

    totals = {k: 0 for k in _SUM_FIELDS}
    coverage_evaluable = coverage_total = 0
    for doc in docs:
        try:
            unapplied = store.count_unapplied_approved_values(scan_id, doc.get("file"))
        except Exception:
            unapplied = 0
        m = derive_file_status(doc, approved_by_file.get(doc.get("file"), ()), unapplied,
                               per_item_secs=per_item_secs)
        for k in _SUM_FIELDS:
            totals[k] += int(m.get(k, 0))
        coverage_evaluable += m["coverage"]["evaluable"]
        coverage_total += m["coverage"]["total"]

    if totals["needs_remediation"] > 0:
        state = STATE_NEEDS_REMEDIATION
    elif totals["unapplied_approved"] > 0:
        state = STATE_APPLY_APPROVED
    elif totals["needs_review"] > 0:
        state = STATE_READY_AFTER_REVIEW
    else:
        state = STATE_READY

    return {
        "available": True,
        "scope": "folder" if path_prefix else "scan",
        **({"path_prefix": path_prefix} if path_prefix else {}),
        "documents": len(docs),
        "coverage": {"evaluable": coverage_evaluable, "total": coverage_total},
        **totals,
        "est_review_secs": totals["needs_review"] * int(per_item_secs),
        "state": state,
        "cta": CTA.get(state),
    }


def confirm_review_criterion(store, scan_id: str, file: str, sc: str, actor: str,
                             note: str | None = None) -> dict:
    """Confirm-the-pass (ADR 0026 / Epic 3): a human records that a 🟡 review criterion is verified.
    Writes the SAME immutable `hitl.approved` decision the HITL queue writes — so the status model's
    `human_verified` bucket, the certification facts' approvals, and the Assessment Timeline's
    Human-review stage all pick it up with zero model changes.

    Honesty guard (ADR 0016): only a criterion whose recorded outcome is REVIEW can be confirmed —
    a FAIL needs remediation and a PASS needs nothing; neither may be waved through. Never raises."""
    import re
    if not re.match(r"^\d+\.\d+\.\d+$", sc or ""):
        return {"ok": False, "reason": "invalid_criterion"}
    try:
        row = store.get_trace_row(scan_id, file, sc)
    except Exception:
        row = None
    if not row:
        return {"ok": False, "reason": "criterion_not_in_scan"}
    if row.get("outcome") != "REVIEW":
        return {"ok": False, "reason": "not_a_review_criterion",
                "outcome": row.get("outcome")}
    store.log_decision(actor, "hitl.approved", scan_id=scan_id, file=file, rule_id=sc,
                       detail=(note or "").strip() or "Criterion confirmed by human review (confirm-the-pass)")
    return {"ok": True, "sc": sc, "actor": actor}
