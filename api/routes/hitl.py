"""Human-in-the-loop review queue endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import core

router = APIRouter()


class HitlUpdate(BaseModel):
    status: str                     # pending | approved | rejected | skipped
    reviewer_note: str | None = None
    approved_value: str | None = None   # AI-drafted or hand-edited final text (alt/link text)
    edited: bool = False                # reviewer changed the AI draft before approving (calibration signal)
    review_ms: int | None = None        # client-measured time from card-open to decision (reviewer-time metric)
    ai_value: str | None = None         # the AI-proposed value shown, so we store proposed-vs-final
    # One final text per proposal, positionally: the row holds N proposals (one per image) and
    # a single approved_value could never describe ten different pictures. An entry that is
    # null/"" accepts that proposal's own draft, so approving an unedited card means exactly
    # "the drafts I was shown are correct". Omit entirely for a judgement finding.
    approved_values: list[str | None] | None = None
    # Reviewer Feedback Intelligence: WHY a rejection happened. A fixed vocabulary so the
    # rollup can answer "which rules are weakest" — free text goes in reviewer_note.
    reject_reason: str | None = None    # incorrect_object | too_vague | hallucinated | missed_text | org_preference | other
    # WCAG exception the reviewer applied INSTEAD of authoring a fix — the honest resolution for a
    # finding a model can't decide. 'decorative' (1.1.1: the image conveys nothing, so no text
    # alternative is required) or 'essential_exception' (1.4.5/1.4.9: a logo/brand mark is exempt
    # from the images-of-text rule). Recorded in the immutable audit trail as WHY the finding was
    # resolved, so the certification report never implies a written fix that never happened.
    resolution: str | None = None       # decorative | essential_exception | out_of_scope


REJECT_REASONS = {"incorrect_object", "too_vague", "hallucinated", "missed_text", "org_preference", "other", "unspecified"}
# Human-judgment exceptions that resolve a finding without a written value. Each maps to the WCAG
# clause that makes the exception legitimate — kept beside the enum so the audit note is honest.
RESOLUTIONS = {
    "decorative": "reviewer marked image decorative — no text alternative required (WCAG 1.1.1)",
    "essential_exception": "reviewer marked essential logo/brand mark — exempt from images-of-text (WCAG 1.4.5/1.4.9)",
    # Unlike the two above (which RESOLVE a finding that IS in scope, so it stays a human_verified
    # pass), out_of_scope means the criterion does not APPLY to this document — the reviewer's
    # judgement that it is not applicable. It leaves the coverage denominator (accessibility_status
    # counts it as its own `not_applicable` bucket, outside in_scope), like an N/A cell on the matrix.
    "out_of_scope": "reviewer marked finding not applicable / out of scope for this document",
}


@router.post("/hitl/queue/{scan_id}/auto")
def hitl_auto_queue(scan_id: str):
    """Auto-populate the HITL review queue from ai-assisted FAILs in an existing scan.

    Idempotent — safe to call multiple times. Returns the newly created items.
    Fires a webhook (HITL_WEBHOOK_URL) if configured.
    """
    if core.store.get_scan(scan_id) is None:
        raise HTTPException(404, "scan not found")
    created = core.store.queue_hitl_items(scan_id)
    core.fire_webhook(created)
    return {"queued": len(created), "items": created}


@router.post("/hitl/queue/{scan_id}/verify")
def hitl_verify_queue(scan_id: str, file: str = Query(...)):
    """Queue a post-fix VERIFICATION item for one fully-automatic remediation
    (user decision 2026-07-02: automatic fixes also get human review). The
    ai-assisted pull above never sees auto-mode rules, so this is the only
    path that puts a fully-automatic fix in front of a person. Idempotent per
    (scan, file) — repeat clicks of remediate-now never duplicate the item."""
    if core.store.get_scan(scan_id) is None:
        raise HTTPException(404, "scan not found")
    item_id = core.store.queue_hitl_deferral(
        scan_id, file, "Automatic fix applied — verify the result", 1, rule_id="auto/verify")
    if item_id:
        core.fire_webhook([{"id": item_id, "scan_id": scan_id, "file": file,
                            "rule_id": "auto/verify", "status": "pending"}])
    return {"queued": 0 if item_id is None else 1, "id": item_id}


@router.get("/hitl/queue")
def hitl_list(request: Request, status: str | None = None, scan_id: str | None = None,
              include_superseded: bool = False):
    """List HITL review items, scoped to the signed-in user's own documents. Filter by
    status (pending/approved/rejected/skipped) or scan_id.

    Superseded items — queued while a finding failed, and since re-verified to PASS or
    NOT_EVALUATED — are omitted, so the inbox count is work outstanding rather than work ever
    queued. include_superseded=true returns them as well, each flagged `superseded`; that is
    the audit view of everything this scan ever asked a human to look at."""
    owner = getattr(request.state, "user_email", None)
    return core.store.list_hitl_queue(status=status, scan_id=scan_id, owner=owner,
                                      include_superseded=include_superseded)


@router.get("/hitl/analytics")
def hitl_metrics(request: Request, scan_id: str | None = None):
    """Human-review telemetry for the Intelligent Review Workspace dashboard — decisions by
    action, approval rate, edit rate (confidence-calibration signal), and average review time
    (the headline metric: reviewer time eliminated). Scoped to one scan when scan_id is given."""
    if scan_id is not None and core.store.get_scan(
            scan_id, owner=getattr(request.state, "user_email", None)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.hitl_analytics(scan_id)


@router.put("/hitl/queue/{item_id}")
def hitl_update(item_id: str, body: HitlUpdate, request: Request = None):
    """Update a HITL review item status (approve, reject, skip) with an optional reviewer note."""
    item = core.store.get_hitl_item(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    valid = {"pending", "approved", "rejected", "skipped"}
    if body.status not in valid:
        raise HTTPException(422, f"status must be one of {sorted(valid)}")
    if body.reject_reason is not None and body.reject_reason not in REJECT_REASONS:
        raise HTTPException(422, f"reject_reason must be one of {sorted(REJECT_REASONS)}")
    if body.resolution is not None and body.resolution not in RESOLUTIONS:
        raise HTTPException(422, f"resolution must be one of {sorted(RESOLUTIONS)}")
    # The resolution is persisted ON THE ROW, not only in the decision log below. The certify
    # gate and the appliers read rows: with the exception recorded nowhere they could reach,
    # store._row_approved_values fell back to the card's own UI label, so "Mark as decorative"
    # became content the file owed the document — countable forever, and (on docx/pptx/xlsx,
    # which really are appliable) writable as the image's alt text.
    updated = core.store.update_hitl_item(item_id, body.status, body.reviewer_note,
                                          body.approved_value, resolution=body.resolution)
    # Record the reviewer's final text per proposal, so the applier knows which image gets which
    # description. Only on approval: rejecting or skipping approves no content.
    if body.status == "approved" and body.approved_values is not None:
        try:
            core.store.approve_proposal_values(item_id, body.approved_values)
        except Exception:
            pass
    # Immutable audit trail: WHO decided what, when, on which finding — include the
    # approved value itself so the log is self-sufficient compliance evidence.
    #
    # The actor is the authenticated reviewer's email, not a generic "reviewer" label: a
    # certification report that says a human signed off must be able to say WHICH human, or
    # the chain of custody is unattributable. Falls back to the literal 'reviewer' when there
    # is no authenticated identity (the demo/SSO-less path, and direct in-process callers for
    # whom `request` is None) — we record what we actually know and never invent a name.
    actor = getattr(getattr(request, "state", None), "user_email", None) or "reviewer"
    _detail = body.reviewer_note or None
    # A WCAG-exception resolution IS the evidence for this finding — record it verbatim, so an
    # auditor reading the log sees the finding was resolved by human judgment (not a written fix).
    if body.resolution:
        _detail = f"{_detail + ' | ' if _detail else ''}resolution: {RESOLUTIONS[body.resolution]}"
    if body.approved_value:
        _detail = f"{_detail + ' | ' if _detail else ''}approved: {body.approved_value[:160]}"
    core.store.log_decision(
        actor, f"hitl.{body.status}",
        scan_id=item.get("scan_id"), file=item.get("file"), rule_id=item.get("rule_id"),
        detail=_detail)
    # Review telemetry (Intelligent Review Workspace): one event per decision so we can
    # report reviewer time saved + calibrate confidence from the edit/reject signal.
    # Best-effort — never blocks the review.
    try:
        _action = ("edit" if (body.status == "approved" and body.edited)
                   else {"approved": "approve", "rejected": "reject", "skipped": "skip"}.get(body.status, body.status))
        core.store.record_hitl_event(
            item.get("scan_id"), item.get("file"), item.get("rule_id"), item_id, _action,
            edited=body.edited, review_ms=body.review_ms, ai_value=body.ai_value,
            final_value=body.approved_value,
            reviewer=(getattr(request.state, "user_email", None) if request is not None else None),
            reject_reason=(body.reject_reason if body.status == "rejected" else None))
    except Exception:
        pass
    # Observability: the human decision joins the file's Langfuse trace (audit P1 — HITL
    # decisions were previously untraced). Best-effort; never blocks the review.
    try:
        import lf as _lf
        _lf.trace_hitl_decision(item.get("scan_id"), item.get("file"), item.get("rule_id"),
                                body.status, note=body.reviewer_note,
                                approved_value=body.approved_value)
    except Exception:
        pass
    # ADR 0003 Phase 2: HITL resolution is an explicit remediation_state transition.
    # approved (AI draft accepted) -> complete; rejected (a human said it's wrong, still
    # needs work) -> in_progress; skipped (deferred, still needs attention) -> unchanged
    # (stays awaiting_review) -- pending doesn't transition anything.
    _STATE_FOR = {"approved": "complete", "rejected": "in_progress", "skipped": "awaiting_review"}
    if body.status in _STATE_FOR and item.get("scan_id") and item.get("file") and item.get("rule_id"):
        try:
            from documents import resolve_doc_id
            scan_id, file = item["scan_id"], item["file"]
            source = (core.store.get_scan(scan_id) or {}).get("run", {}).get("source")
            ident = next((i for i in core.store.list_file_identities(scan_id) if i["file"] == file), {})
            doc_id = resolve_doc_id(source, ident.get("drive_file_id"), file, ident.get("checksum"))
            core.store.upsert_remediation_state(doc_id, item["rule_id"], _STATE_FOR[body.status], scan_id)
        except Exception:
            pass
    # Write the approved content into the document. Approving alt text used to store the text
    # and stop — the images stayed undescribed, so mark_file_compliant_if_reviewed below
    # refused to certify and the file could never reach Publish. The job applies the values to
    # the remediated copy, re-scans it, and only then marks the row applied; it re-runs the
    # certify seam itself once the document actually carries the content.
    # The gate asks for ANY approved content an applier can write, per kind — alt text (1.1.1),
    # link text (2.4.4/2.4.9), a PDF form-field name (4.1.2) — because each lives in its OWN
    # hitl row. Naming only some of them strands the rest: a file whose only pending value was a
    # field name, or link text, enqueued no job, so the document never carried the value and
    # mark_file_compliant_if_reviewed below correctly refused to certify it, forever. The
    # handler already writes all three; this is the gate that decides whether it ever runs.
    # A 'decorative' resolution is the fourth kind and the odd one out — it approves no TEXT,
    # only the OOXML marking — and it is folded into the same helper for exactly the reason
    # above: left out, the reviewer's decision would live only in our audit log.
    if (body.status == "approved" and item.get("scan_id") and item.get("file")
            and core.store.has_approved_values_to_write(item["scan_id"], item["file"])):
        try:
            core.store.enqueue_job("apply_approved_values",
                                   {"scan_id": item["scan_id"], "file": item["file"]},
                                   scan_id=item["scan_id"])
        except Exception:
            pass
    # Re-validate → certify: once a remediated file's every review item is approved AND every
    # approved value has been written in, it is fully conformant (auto fixes verified + human
    # findings signed off) and advances to Publish. A file still holding unwritten approved
    # content returns False here and certifies later, from the apply job.
    if body.status == "approved" and item.get("scan_id") and item.get("file"):
        try:
            if core.store.mark_file_compliant_if_reviewed(item["scan_id"], item["file"]):
                core.store.log_decision(
                    "system", "revalidate.certified", scan_id=item["scan_id"], file=item["file"],
                    detail="all findings resolved (auto-fixed + human-approved) — certified & advanced to Publish")
        except Exception:
            pass
    return updated
