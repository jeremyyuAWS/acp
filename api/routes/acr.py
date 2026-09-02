"""Accessibility Conformance Report workspace — ADR 0047, PRD Phase 1.

The ACR is a VPAT-structured statement about ACP'S OWN WEB UI at WCAG 2.2 A+AA. It is NOT about
the customer documents ACP remediates, and no endpoint here joins to scan_runs or issue_records
for that reason: docs/conformance-report.md draws that line in prose, and an endpoint that let a
finding about a customer's Word file become evidence for a claim about ACP's UI would cross it in
exactly the way PRD §3 opens by warning about.

WHERE THE HONESTY RULES LIVE. Not here. Every one of them is in a module this file calls:

    acr_rules       what evidence permits (may_draft / may_select_final_status)
    acr_freshness   which evidence is stale
    acr_validation  what blocks publication — the SAME function the validation screen renders
    acr_authz       who may approve and publish
    acr_catalog     the four VPAT terms, and the internal states that are not them

This module's job is HTTP: resolve the caller, call the rule, and serialize. When a route looks
like it is making a judgement, it is calling something that does.

WHICH ACTIONS ARE ROLE-GATED. Reads are open to any admitted user; every WRITE requires a role.
That split is core.py's own reasoning applied here, not a new policy: OPEN_ACCESS deliberately
gives every admitted user the same screens and the same non-destructive features, and just as
deliberately does NOT open "the genuinely destructive, irreversible actions". Publishing a
conformance claim about the product, and approving the criteria behind it, are squarely in the
second category — an ACR goes to a customer's procurement file and cannot be recalled.

AUTHORIZATION IS NOT core.is_admin(). Under the default ACP_OPEN_ACCESS=1 that helper returns True
for any authenticated user, which would make "only an approver may publish" (PRD §21.11) true on
paper and absent in fact. Authority here comes from the acr_role table via acr_authz, with the
protected ACP_OWNER_EMAIL as the only carve-out. See api/acr_authz.py for the full argument, and
tests/test_acr_authorization.py, which runs with OPEN_ACCESS=1 explicitly set because that is the
configuration the gate exists to survive.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

import acr_authz
import acr_axe
import acr_catalog
import acr_export_pdf
import acr_export_preview
import acr_freshness
import acr_plans
import acr_publish
import acr_rules
import acr_validation
import core
from acr_model import AcrValidationError, Evidence

router = APIRouter()


def _actor(request: Request) -> str:
    """WHO is calling — for role checks and attribution. Never the storage key; see _tenant."""
    return getattr(request.state, "user_email", None) or "demo"


def _tenant() -> str:
    """WHERE ACR rows live: ONE namespace per deployment, not one per user.

    This is the one place ACR deliberately departs from the rest of the app, and the departure is
    forced by what an ACR is. Everywhere else `owner_email` is PER-USER data isolation — routes/
    scans.py's `_owner` says so directly ("the current user for per-user data isolation"), because
    a scan is about a customer's own files and nobody else has any business seeing it.

    An ACR is the opposite kind of object. There is exactly ONE product being evaluated (ACP), and
    the report about it is an organizational artifact that an analyst drafts, an engineer reads and
    a DIFFERENT person approves — PRD §6 lists five distinct human roles, and §18 goes further and
    recommends the approver not be the person who made most of the decisions. Per-user tenancy
    makes every one of those impossible: a second person's request 404s at the ownership check
    before any role is consulted, so the approver can never see the report they must approve.

    Found by test_acr_authorization: the role model was built first, keyed on the caller, and
    every cross-user test returned 404 instead of 403. The roles were not wrong; the namespace was.

    The namespace is the deployment's protected owner (ACP_OWNER_EMAIL) — the same identity that
    is the root of trust for access management elsewhere in core.py — falling back to "demo" for
    the keyless local path, which matches every other `_owner` helper's fallback.
    """
    return (getattr(core, "OWNER_EMAIL", "") or "").strip().lower() or "demo"


def _roles(email: str, report_id: str) -> list[str]:
    try:
        return core.store.get_acr_roles(owner_email=_tenant(), email=email, report_id=report_id)
    except Exception:
        return []


def _require(role: str, request: Request, report_id: str) -> str:
    """Enforce an ACR role on the CALLER. Returns their email.

    Reads are deliberately not gated by this — see the module docstring's note on which actions
    are role-gated and why that matches core.py's own OPEN_ACCESS reasoning.
    """
    who = _actor(request)
    try:
        acr_authz.require(role, _roles(who, report_id), email=who,
                          is_platform_owner=core.is_owner(who))
    except acr_authz.AcrForbidden as exc:
        raise HTTPException(403, str(exc)) from exc
    return who


def _report_or_404(report_id: str, owner: str) -> dict:
    """Resolve a report in the ACR namespace, or 404.

    `owner` is always _tenant() here, not the caller — see _tenant for why ACR reports are not
    per-user. The store method still scopes in the query rather than filtering afterwards, so a
    report id from a different deployment namespace is indistinguishable from a nonexistent one,
    matching the contract tests/test_foreign_scan_404.py fixes for scans.
    """
    row = core.store.get_acr_report(report_id, owner_email=owner)
    if row is None:
        raise HTTPException(404, "no such report")
    return row


def _evidence_objects(report_id: str, owner: str, criterion_num: str | None = None) -> dict[str, list]:
    """Stored evidence rows rehydrated into acr_model.Evidence, grouped by criterion.

    The rules operate on objects with an `.id`, `.result`, `.tested_at` and `.is_automated`, and
    rehydrating here means the rule modules never learn the database's column names — which is
    what lets them be tested against constructed records with no store at all.

    Rows are rebuilt with object.__new__ rather than Evidence(...) DELIBERATELY: the constructor
    validates, and a stored row that predates a validation rule (or was written before one
    existed) must still be READABLE. Refusing to load history because it fails today's constructor
    would hide exactly the audit trail PRD §17 requires be kept.
    """
    out: dict[str, list] = {}
    for row in core.store.list_acr_evidence(report_id, owner_email=owner,
                                            criterion_num=criterion_num):
        ev = object.__new__(Evidence)
        for k, v in row.items():
            setattr(ev, k, v)
        for field in ("attachments", "related_finding_ids"):
            raw = getattr(ev, field, None)
            if isinstance(raw, str):
                try:
                    setattr(ev, field, json.loads(raw))
                except (ValueError, TypeError):
                    setattr(ev, field, [])
        out.setdefault(ev.criterion_num, []).append(ev)
    return out


def _stale_for(report: dict, evidence_by_criterion: dict[str, list]) -> dict[str, str]:
    flat = [e for rows in evidence_by_criterion.values() for e in rows]
    return acr_freshness.evaluate(report, flat)


# ── models ─────────────────────────────────────────────────────────────────────

class CreateReport(BaseModel):
    report_title: str | None = None
    product_name: str | None = "ACP by Movate"
    product_version: str | None = None
    build_id: str | None = None
    metadata: dict | None = None


class PatchReport(BaseModel):
    fields: dict


class AddEvidence(BaseModel):
    criterion_num: str
    source_kind: str
    result: str
    tester: str | None = None
    tested_at: str | None = None
    product_version: str | None = None
    build_id: str | None = None
    environment: str | None = None
    workflow: str | None = None
    browser: str | None = None
    assistive_tech: str | None = None
    tool_name: str | None = None
    tool_version: str | None = None
    rule_id: str | None = None
    tested_url: str | None = None
    coverage: str | None = None
    method: str | None = None
    notes: str | None = None
    attachments: list[str] | None = None
    related_finding_ids: list[str] | None = None


class Decide(BaseModel):
    final_status: str
    remarks: str | None = None


class IngestAxe(BaseModel):
    """One axe-core result object, as `axe.run()` returns it."""
    result: dict
    environment: str | None = None
    workflow: str | None = None
    product_version: str | None = None
    build_id: str | None = None
    # Report what would be written without writing it. The interesting part of this operation is
    # what it drops, and acr_evidence is append-only — a preview is cheaper than a retraction.
    preview: bool = False


class SetApplicability(BaseModel):
    applicable: bool
    rationale: str | None = None


# ── reports ────────────────────────────────────────────────────────────────────

@router.post("/acr")
def create_report(body: CreateReport, request: Request):
    """Create a draft report and its FULL applicable criteria matrix (PRD §21.2).

    The matrix is built in the same transaction as the report, not lazily on first read: a report
    row without its criteria is one that looks complete and silently has nothing to evaluate.
    """
    owner = _tenant()
    who = _require(acr_authz.ROLE_EDITOR, request, "*")
    meta = dict(body.metadata or {})
    for k in ("report_title", "product_name", "product_version", "build_id"):
        if getattr(body, k) is not None:
            meta[k] = getattr(body, k)
    meta.setdefault("vpat_edition", "VPAT 2.5Rev WCAG")
    meta.setdefault("wcag_version", acr_catalog.meta()["version"])
    meta.setdefault("wcag_levels", "A, AA")

    report_id = f"acr_{uuid.uuid4().hex[:12]}"
    core.store.create_acr_report(
        report_id, owner_email=owner, catalog_hash=acr_catalog.catalog_hash(),
        criteria=acr_catalog.build_matrix(report_id), metadata=meta)
    core.store.append_acr_decision_log(
        report_id, owner_email=owner, actor=who, action="report.created",
        detail=f"catalog={acr_catalog.meta()['version']} "
               f"criteria={acr_catalog.meta()['criteria_count']}")
    return {"report_id": report_id,
            "criteria_count": acr_catalog.meta()["criteria_count"],
            "catalog_hash": acr_catalog.catalog_hash()}


@router.get("/acr")
def list_reports(request: Request):
    owner = _tenant()
    return {"reports": core.store.list_acr_reports(owner)}


@router.get("/acr/{report_id}")
def get_report(report_id: str, request: Request):
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    criteria = core.store.list_acr_criteria(report_id, owner_email=owner)
    ev = _evidence_objects(report_id, owner)
    stale = _stale_for(report, ev)
    decided = sum(1 for c in criteria if c.get("final_status"))
    return {
        "report": report,
        "roles": _roles(_actor(request), report_id),
        "progress": {
            "total": len(criteria),
            "decided": decided,
            "undecided": len(criteria) - decided,
            "approved": sum(1 for c in criteria if c.get("approval_state") == "approved"),
            "evidence_total": sum(len(v) for v in ev.values()),
            "evidence_stale": len(stale),
        },
    }


@router.patch("/acr/{report_id}")
def patch_report(report_id: str, body: PatchReport, request: Request):
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    if report.get("status") == "published":
        # PRD §17: a published snapshot is immutable; changes after publication create a new draft
        # revision rather than editing what was published.
        raise HTTPException(409, "this report is published — changes create a new draft revision")
    _require(acr_authz.ROLE_EDITOR, request, report_id)
    written = core.store.update_acr_report_metadata(report_id, owner_email=owner,
                                                    fields=body.fields)
    core.store.append_acr_decision_log(report_id, owner_email=owner, actor=owner,
                                       action="report.metadata_changed",
                                       detail=f"{written} field(s): "
                                              f"{','.join(sorted(body.fields))[:180]}")
    return {"updated": written}


# ── criteria ───────────────────────────────────────────────────────────────────

@router.get("/acr/{report_id}/criteria")
def list_criteria(report_id: str, request: Request):
    owner = _tenant()
    _report_or_404(report_id, owner)
    return {"criteria": core.store.list_acr_criteria(report_id, owner_email=owner)}


@router.get("/acr/{report_id}/criteria/{criterion_num}")
def get_criterion(report_id: str, criterion_num: str, request: Request):
    """Everything the criterion-detail screen needs, including WHY a status is refused.

    The refusal reasons come from acr_rules.summarize, the same function the decision endpoint
    gates on — so the screen can never offer a button the POST would reject, and can never explain
    a refusal differently from the reason the server would give.
    """
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    crit = core.store.get_acr_criterion(report_id, criterion_num, owner_email=owner)
    if crit is None:
        raise HTTPException(404, "no such criterion in this report")

    ev_by = _evidence_objects(report_id, owner)
    stale = _stale_for(report, ev_by)
    evidence = ev_by.get(criterion_num, [])
    return {
        "criterion": crit,
        "catalog": acr_catalog.criterion(criterion_num),
        "evidence": [dict(e.__dict__, stale_reason=stale.get(e.id)) for e in evidence],
        "assessment": acr_rules.summarize(criterion_num, evidence, set(stale)),
    }


@router.post("/acr/{report_id}/evidence/axe")
def ingest_axe(report_id: str, body: IngestAxe, request: Request):
    """Ingest one axe-core run over ACP's own screens as evidence (PRD §7.6, §13).

    `preview=true` reports what WOULD be written and writes nothing — worth having because the
    interesting part of this operation is what it DROPS, and a user should be able to see that
    before committing a few hundred rows to an append-only table.

    The honesty rules are all in api/acr_axe.py, not here: `incomplete` becomes BLOCKED rather
    than a pass, `inapplicable` is not evidence at all, and every row declares PARTIAL coverage —
    so a perfectly clean axe run moves nothing to Supports. See that module's docstring.
    """
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    if report.get("status") == "published":
        raise HTTPException(409, "this report is published — changes create a new draft revision")
    who = _require(acr_authz.ROLE_EVALUATOR, request, report_id)

    known = {c["criterion_num"] for c in core.store.list_acr_criteria(report_id, owner_email=owner)}
    try:
        summary = acr_axe.summarize(body.result)
        records, ingest_report = acr_axe.to_evidence(
            body.result, report_id=report_id,
            product_version=body.product_version or report.get("product_version"),
            build_id=body.build_id or report.get("build_id"),
            environment=body.environment, workflow=body.workflow, tester=who,
            known_criteria=known)
    except (acr_axe.AxeIngestError, AcrValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc

    if body.preview:
        return {"preview": True, "run": summary, "would_ingest": ingest_report}

    for ev in records:
        core.store.add_acr_evidence(ev.to_row(), owner_email=owner)
    core.store.append_acr_decision_log(
        report_id, owner_email=owner, actor=who, action="evidence.axe_ingested",
        detail=(f"{ingest_report['ingested']} record(s) over "
                f"{len(ingest_report['criteria'])} criteria from {summary.get('tested_url') or '?'}; "
                f"{ingest_report['dropped_inapplicable']} inapplicable dropped"))

    # Recompute ACP's draft suggestion for every criterion the run touched. Still only ever a
    # suggestion — save_acr_draft_status cannot reach final_status (PRD §20).
    ev_by = _evidence_objects(report_id, owner)
    stale = _stale_for(report, ev_by)
    drafts: dict[str, str | None] = {}
    for sc in ingest_report["criteria"]:
        draft, _why = acr_rules.may_draft(sc, ev_by.get(sc, []), set(stale))
        core.store.save_acr_draft_status(report_id, sc, owner_email=owner, draft_status=draft,
                                         workflow_state=acr_catalog.NEEDS_REVIEW)
        drafts[sc] = draft
    return {"preview": False, "run": summary, "ingested": ingest_report, "drafts": drafts}


@router.get("/acr/{report_id}/gaps")
def gaps(report_id: str, request: Request):
    """PRD §7.8 — "ACP identifies criteria that have no adequate evidence".

    Distinct from /validation, which answers "can this publish" and is keyed on decisions. This
    answers "where does a human still need to go and look", which is the question an analyst has
    while the report is still being built and every criterion is undecided.

    The three buckets are deliberately different kinds of gap, because the work each implies is
    different:
      no_evidence        nobody has looked at this criterion at all
      automated_only     a tool looked; PRD §4.3 says that is not enough on its own
      stale_only         someone looked, but not at this version of the product
    """
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    criteria = core.store.list_acr_criteria(report_id, owner_email=owner)
    ev_by = _evidence_objects(report_id, owner)
    stale = set(_stale_for(report, ev_by))

    buckets: dict[str, list[dict]] = {"no_evidence": [], "automated_only": [], "stale_only": []}
    covered = 0
    for crit in criteria:
        sc = crit["criterion_num"]
        rows = ev_by.get(sc, [])
        live = [e for e in rows if e.id not in stale]
        row = {"criterion_num": sc, "criterion_name": crit.get("criterion_name"),
               "level": crit.get("level"), "principle": crit.get("principle"),
               "final_status": crit.get("final_status"),
               "evidence_total": len(rows), "evidence_live": len(live)}
        if not rows:
            buckets["no_evidence"].append(row)
        elif not live:
            buckets["stale_only"].append(row)
        elif not acr_rules.has_human_evaluation(rows, stale):
            buckets["automated_only"].append(row)
        else:
            covered += 1

    return {
        "total": len(criteria),
        "with_human_evidence": covered,
        "counts": {k: len(v) for k, v in buckets.items()},
        "buckets": buckets,
        "note": ("A criterion with only automated evidence is a gap, not a result: an automated "
                 "pass covers part of a criterion and never establishes conformance (PRD §4.3)."),
    }


@router.post("/acr/{report_id}/criteria/{criterion_num}/applicability")
def set_applicability(report_id: str, criterion_num: str, body: SetApplicability, request: Request):
    """Mark a criterion applicable or not (PRD §9's applicability column).

    NOT the same act as deciding "Not Applicable", and the difference is worth keeping. The
    conformance decision is what a customer reads in the exported table and needs remarks
    explaining why the criterion does not apply (PRD §10). This flag is the workspace's own
    triage — "we do not expect to evaluate this" — and marking it does not write a status.

    Marking a criterion inapplicable therefore does NOT let a report publish with it undecided:
    acr_validation still requires a final status for every row. That is deliberate; an ACR reports
    on every applicable criterion in the standard, and "we decided not to look" is not one of the
    four VPAT terms.
    """
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    if report.get("status") == "published":
        raise HTTPException(409, "this report is published — changes create a new draft revision")
    who = _require(acr_authz.ROLE_EDITOR, request, report_id)

    if core.store.get_acr_criterion(report_id, criterion_num, owner_email=owner) is None:
        raise HTTPException(404, "no such criterion in this report")
    if not body.applicable and not (body.rationale or "").strip():
        raise HTTPException(422, "marking a criterion inapplicable requires a rationale")

    core.store.set_acr_criterion_applicability(report_id, criterion_num, owner_email=owner,
                                               applicable=body.applicable)
    core.store.append_acr_decision_log(
        report_id, owner_email=owner, actor=who, action="criterion.applicability_changed",
        criterion_num=criterion_num,
        detail=f"applicable={body.applicable}: {(body.rationale or '').strip()[:180]}")
    return {"criterion_num": criterion_num, "applicable": body.applicable}


@router.post("/acr/{report_id}/criteria/{criterion_num}/evidence")
def add_evidence(report_id: str, criterion_num: str, body: AddEvidence, request: Request):
    """Attach one evidence record. Append-only (PRD §12, §17) — there is no update or delete.

    After writing, ACP recomputes its own DRAFT suggestion and stores it. The draft is never a
    decision: save_acr_draft_status cannot write final_status, which is the structural guarantee
    behind PRD §20's "never select or approve the final conformance status".
    """
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    if report.get("status") == "published":
        raise HTTPException(409, "this report is published — changes create a new draft revision")
    who = _require(acr_authz.ROLE_EVALUATOR, request, report_id)

    if body.criterion_num != criterion_num:
        raise HTTPException(400, "criterion_num in the body does not match the path")
    if core.store.get_acr_criterion(report_id, criterion_num, owner_email=owner) is None:
        raise HTTPException(404, "no such criterion in this report")

    payload = body.model_dump(exclude_none=True)
    payload["report_id"] = report_id
    payload.setdefault("tester", who)
    # Default the evidence's product version to the report's. A row with no version cannot be
    # freshness-checked against the report at all (acr_freshness needs both sides to name one),
    # so an omitted version silently produces evidence that never goes stale.
    if not payload.get("product_version") and report.get("product_version"):
        payload["product_version"] = report["product_version"]
    if not payload.get("build_id") and report.get("build_id"):
        payload["build_id"] = report["build_id"]

    try:
        ev = Evidence(**payload)
    except (AcrValidationError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc

    core.store.add_acr_evidence(ev.to_row(), owner_email=owner)
    core.store.append_acr_decision_log(
        report_id, owner_email=owner, actor=who, action="evidence.added",
        criterion_num=criterion_num,
        detail=f"{ev.source_kind}/{ev.result} tool={ev.tool_name or '-'} "
               f"coverage={ev.coverage or '-'}")

    ev_by = _evidence_objects(report_id, owner)
    stale = _stale_for(report, ev_by)
    evidence = ev_by.get(criterion_num, [])
    draft, why = acr_rules.may_draft(criterion_num, evidence, set(stale))
    # NEEDS_REVIEW either way, and that is the point: a draft suggestion moves the criterion out
    # of "nobody has looked" and no further. Even a drafted "Supports" is a suggestion awaiting a
    # person, so there is no evidence-driven path to DECIDED — only save_acr_decision reaches it.
    core.store.save_acr_draft_status(report_id, criterion_num, owner_email=owner,
                                     draft_status=draft,
                                     workflow_state=acr_catalog.NEEDS_REVIEW)
    return {"evidence_id": ev.id, "draft_status": draft, "draft_reason": why,
            "assessment": acr_rules.summarize(criterion_num, evidence, set(stale))}


@router.post("/acr/{report_id}/criteria/{criterion_num}/decision")
def decide(report_id: str, criterion_num: str, body: Decide, request: Request):
    """A HUMAN selects the final conformance status (PRD §4.2, §21.6-21.8).

    Refuses with the rule's own sentence, not a generic 400: a gate whose refusal the user cannot
    read is a gate they work around.
    """
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    if report.get("status") == "published":
        raise HTTPException(409, "this report is published — changes create a new draft revision")
    who = _require(acr_authz.ROLE_EDITOR, request, report_id)

    if core.store.get_acr_criterion(report_id, criterion_num, owner_email=owner) is None:
        raise HTTPException(404, "no such criterion in this report")

    ev_by = _evidence_objects(report_id, owner)
    stale = _stale_for(report, ev_by)
    evidence = ev_by.get(criterion_num, [])

    verdict = acr_rules.may_select_final_status(
        body.final_status, criterion_num=criterion_num, evidence=evidence,
        remarks=body.remarks, stale_ids=set(stale))
    if not verdict.allowed:
        raise HTTPException(422, verdict.reason)

    try:
        core.store.save_acr_decision(report_id, criterion_num, owner_email=owner,
                                     final_status=body.final_status, remarks=body.remarks,
                                     decided_by=who)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    core.store.append_acr_decision_log(
        report_id, owner_email=owner, actor=who, action="criterion.decided",
        criterion_num=criterion_num,
        detail=f"{body.final_status} remarks={'yes' if (body.remarks or '').strip() else 'no'}")
    return {"criterion_num": criterion_num, "final_status": body.final_status}


@router.post("/acr/{report_id}/criteria/{criterion_num}/approve")
def approve(report_id: str, criterion_num: str, request: Request):
    """An approver signs off one criterion (PRD §4.2: every applicable criterion needs one)."""
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    if report.get("status") == "published":
        raise HTTPException(409, "this report is published — changes create a new draft revision")
    who = _require(acr_authz.ROLE_APPROVER, request, report_id)

    crit = core.store.get_acr_criterion(report_id, criterion_num, owner_email=owner)
    if crit is None:
        raise HTTPException(404, "no such criterion in this report")
    if not crit.get("final_status"):
        raise HTTPException(422, "this criterion has no final conformance status to approve")

    core.store.approve_acr_criterion(report_id, criterion_num, owner_email=owner, reviewer=who)
    core.store.append_acr_decision_log(report_id, owner_email=owner, actor=who,
                                       action="criterion.approved", criterion_num=criterion_num,
                                       detail=crit["final_status"])
    return {"criterion_num": criterion_num, "approval_state": "approved"}


# ── guided manual test plans (PRD §14) ─────────────────────────────────────────


def _run_instances(report_id: str, owner: str) -> list[dict]:
    """Every manual run on this report, shaped the way acr_plans expects.

    Assembles three sources the module deliberately cannot read for itself — it is pure functions
    over records (test_the_rule_modules_stay_free_of_io) — into one instance dict per run:

      the run row          which plan, which criterion, who tested
      its step outcomes    keyed by step index as a string
      its evidence row     the environment metadata, which lives THERE and only there

    That last join is the point. The plan declares the metadata it needs; the evidence row is
    where that metadata durably lives; so completeness is computed against the record a reader of
    the ACR would actually see, not against a second copy that could drift from it.
    """
    runs = core.store.list_acr_manual_runs(report_id, owner_email=owner)
    steps = core.store.list_acr_manual_steps(report_id, owner_email=owner)
    evidence = {e["id"]: e
                for e in core.store.list_acr_evidence(report_id, owner_email=owner)}

    by_run: dict[str, dict[str, str]] = {}
    for s in steps:
        by_run.setdefault(s["run_id"], {})[str(s["step_index"])] = s["outcome"]

    out = []
    for run in runs:
        ev = evidence.get(run.get("evidence_id") or "") or {}
        out.append({
            "id": run["id"],
            "criterion_num": run["criterion_num"],
            "plan_id": run["plan_id"],
            "tester": run.get("tester") or ev.get("tester"),
            "result": run.get("result"),
            "evidence_id": run.get("evidence_id"),
            "steps": by_run.get(run["id"], {}),
            "environment": {"browser": ev.get("browser"),
                            "assistive_tech": ev.get("assistive_tech"),
                            "environment": ev.get("environment")},
            "created_at": run.get("created_at"),
        })
    return out


def _manual_plan_status(report: dict, report_id: str, owner: str) -> dict[str, bool]:
    """The map acr_validation.validate has accepted since Phase 1 and nobody has supplied.

    Phase 1 built the socket and passed nothing, so `incomplete_manual_test_plan` produced no rows
    — the module refusing to pretend it knew. This is the plug. From here on, a report whose
    manual plans are unfinished cannot publish.
    """
    criteria = core.store.list_acr_criteria(report_id, owner_email=owner)
    ev_by = _evidence_objects(report_id, owner)
    stale = set(_stale_for(report, ev_by))
    # Which criteria a HUMAN has evaluated, by acr_rules' own definition — the plan catalog is
    # structure, not a gate, so directly-recorded manual evidence satisfies the obligation too.
    human = {num for num, rows in ev_by.items()
             if acr_rules.has_human_evaluation(rows, stale)}
    return acr_plans.manual_plan_status(criteria, _run_instances(report_id, owner), human)


@router.get("/acr/{report_id}/criteria/{criterion_num}/plans")
def criterion_plans(report_id: str, criterion_num: str, request: Request):
    """Which manual plans this criterion needs, and how far each has got."""
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    if acr_catalog.criterion(criterion_num) is None:
        raise HTTPException(404, f"{criterion_num} is not in the WCAG 2.2 A/AA catalog")

    instances = [i for i in _run_instances(report_id, owner)
                 if i["criterion_num"] == criterion_num]
    ev_by = _evidence_objects(report_id, owner, criterion_num)
    stale = set(_stale_for(report, ev_by))
    human = acr_rules.has_human_evaluation(ev_by.get(criterion_num, []), stale)
    prog = acr_plans.progress(criterion_num, instances, human)
    prog["plan_detail"] = acr_plans.plans_for_criterion(criterion_num)
    prog["runs"] = instances
    prog["step_outcomes"] = sorted(acr_plans.STEP_OUTCOMES)
    return prog


class StartRunBody(BaseModel):
    plan_id: str
    tester: str | None = None


@router.post("/acr/{report_id}/criteria/{criterion_num}/plans/start")
def start_plan_run(report_id: str, criterion_num: str, body: StartRunBody, request: Request):
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    if report.get("status") == "published":
        raise HTTPException(409, "this report is published — changes create a new draft revision")
    who = _require(acr_authz.ROLE_EDITOR, request, report_id)

    if acr_plans.plan(body.plan_id) is None:
        raise HTTPException(400, f"{body.plan_id} is not in the manual test plan catalog")
    if body.plan_id not in acr_plans.required_plan_ids(criterion_num):
        raise HTTPException(
            400, f"{body.plan_id} does not cover {criterion_num}; running it would record "
                 f"evidence against a criterion it never exercised")

    run_id = core.store.start_acr_manual_run(report_id, criterion_num, owner_email=owner,
                                             plan_id=body.plan_id, tester=body.tester or who)
    core.store.append_acr_decision_log(report_id, owner_email=owner, actor=who,
                                       action="manual_test.started", criterion_num=criterion_num,
                                       detail=body.plan_id)
    return {"run_id": run_id, "plan_id": body.plan_id, "criterion_num": criterion_num}


class StepBody(BaseModel):
    step_index: int
    outcome: str
    notes: str | None = None


@router.post("/acr/{report_id}/plans/runs/{run_id}/step")
def record_step(report_id: str, run_id: str, body: StepBody, request: Request):
    """Record what the tester observed at one step.

    A `fail` here is a first-class outcome, not an error: a plan is complete when every step has
    been ANSWERED, whatever the answers were. Completeness is about whether someone looked.
    """
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    if report.get("status") == "published":
        raise HTTPException(409, "this report is published — changes create a new draft revision")
    _require(acr_authz.ROLE_EDITOR, request, report_id)

    run = next((r for r in core.store.list_acr_manual_runs(report_id, owner_email=owner)
                if r["id"] == run_id), None)
    if run is None:
        raise HTTPException(404, "no such manual test run on this report")
    if run.get("evidence_id"):
        raise HTTPException(409, "this run is complete; start a new run to record a fresh result")

    if body.outcome not in acr_plans.STEP_OUTCOMES:
        raise HTTPException(400, f"outcome must be one of {sorted(acr_plans.STEP_OUTCOMES)}")
    total = acr_plans.step_count(run["plan_id"])
    if not 0 <= body.step_index < total:
        raise HTTPException(400, f"{run['plan_id']} has {total} steps; there is no step "
                                 f"{body.step_index}")

    core.store.record_acr_manual_step(run_id, report_id=report_id, owner_email=owner,
                                      step_index=body.step_index, outcome=body.outcome,
                                      notes=body.notes)
    instances = [i for i in _run_instances(report_id, owner) if i["id"] == run_id]
    complete, why = acr_plans.instance_complete(instances[0]) if instances else (False, "")
    return {"run_id": run_id, "step_index": body.step_index, "outcome": body.outcome,
            "complete": complete, "blocking_reason": why}


class CompleteRunBody(BaseModel):
    result: str
    tester: str
    browser: str | None = None
    assistive_tech: str | None = None
    environment: str | None = None
    notes: str | None = None


@router.post("/acr/{report_id}/plans/runs/{run_id}/complete")
def complete_plan_run(report_id: str, run_id: str, body: CompleteRunBody, request: Request):
    """Close a run: create the evidence row it produced, then link it.

    The evidence comes FIRST and the run points at it, so a run can never read as complete while
    the record a customer would see is missing. `result` is what the tester observed; it is not a
    conformance status and nothing here can write one — acr_rules remains the only place a status
    is derived, and `save_acr_draft_status` has no path to `final_status`.
    """
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    if report.get("status") == "published":
        raise HTTPException(409, "this report is published — changes create a new draft revision")
    who = _require(acr_authz.ROLE_EDITOR, request, report_id)

    run = next((r for r in core.store.list_acr_manual_runs(report_id, owner_email=owner)
                if r["id"] == run_id), None)
    if run is None:
        raise HTTPException(404, "no such manual test run on this report")
    if run.get("evidence_id"):
        raise HTTPException(409, "this run is already complete")

    plan = acr_plans.plan(run["plan_id"])
    if plan is None:
        raise HTTPException(400, f"{run['plan_id']} is no longer in the plan catalog")

    # Refuse to close a run whose steps are unanswered. The screen shows the same sentence, from
    # this same module, so it cannot offer a Complete button the server then rejects.
    provisional = dict(next(i for i in _run_instances(report_id, owner) if i["id"] == run_id))
    provisional["tester"] = body.tester
    provisional["environment"] = {"browser": body.browser,
                                  "assistive_tech": body.assistive_tech,
                                  "environment": body.environment}
    ok, why = acr_plans.instance_complete(provisional)
    if not ok:
        raise HTTPException(400, why)

    ev = Evidence(criterion_num=run["criterion_num"], source_kind="manual", result=body.result,
                  report_id=report_id, tester=body.tester,
                  product_version=report.get("product_version"), build_id=report.get("build_id"),
                  environment=body.environment, browser=body.browser,
                  assistive_tech=body.assistive_tech,
                  method=f"Guided manual test plan: {plan['title']} ({plan['plan_id']})",
                  notes=body.notes)
    core.store.add_acr_evidence(ev.to_row(), owner_email=owner)
    core.store.complete_acr_manual_run(run_id, report_id=report_id, owner_email=owner,
                                       result=body.result, evidence_id=ev.id, tester=body.tester,
                                       notes=body.notes)
    core.store.append_acr_decision_log(report_id, owner_email=owner, actor=who,
                                       action="manual_test.completed",
                                       criterion_num=run["criterion_num"],
                                       detail=f"{run['plan_id']}: {body.result}")
    return {"run_id": run_id, "evidence_id": ev.id, "result": body.result,
            "note": "A completed plan records what a tester observed. It does not select a "
                    "conformance status."}


# ── validation, audit and preview ──────────────────────────────────────────────

@router.get("/acr/{report_id}/validation")
def validation(report_id: str, request: Request):
    """PRD §15's validation screen. Calls the SAME acr_validation.validate the publish gate does —
    a separately-computed readiness summary is how a screen ends up green while the gate is red."""
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    criteria = core.store.list_acr_criteria(report_id, owner_email=owner)
    ev_by = _evidence_objects(report_id, owner)
    blockers = acr_validation.validate(report, criteria, ev_by,
                                       manual_plan_status=_manual_plan_status(report, report_id, owner))
    return {"summary": acr_validation.summary(blockers),
            "by_category": acr_validation.group(blockers),
            "category_labels": acr_validation.CATEGORY_LABELS}


@router.get("/acr/{report_id}/audit")
def audit(report_id: str, request: Request):
    owner = _tenant()
    _report_or_404(report_id, owner)
    return {"events": core.store.list_acr_decision_log(report_id, owner_email=owner)}


@router.get("/acr/{report_id}/preview")
def preview(report_id: str, request: Request, format: str = "json"):
    """The draft structural export (PRD §15 publication review).

    NOT a VPAT and not a .docx — the official ITI template is Phase 5, gated on a licensing
    decision. The output says so on its face; see api/acr_export_preview.py.

    `format=pdf` returns the SAME projection rendered as a tagged PDF/UA-1 document, which is what
    PRD §16's "the exported report is itself accessible" asks for. All three formats are built
    from one `project()` call below — a reviewer who approves the HTML and a customer who receives
    the PDF are looking at the same rows, and no code path exists in which they could differ.
    """
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    criteria = core.store.list_acr_criteria(report_id, owner_email=owner)
    ev_by = _evidence_objects(report_id, owner)
    stale = _stale_for(report, ev_by)
    try:
        projection = acr_export_preview.project(report, criteria, evidence_by_criterion=ev_by,
                                                stale_ids=set(stale))
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc

    if format == "html":
        return HTMLResponse(acr_export_preview.to_html(projection))
    if format == "pdf":
        # 503 and not a fallback. An untagged PDF is indistinguishable from this one to everyone
        # except the reader it exists for, so a deployment that cannot tag must say so rather than
        # hand over a conformance document that quietly lost its structure tree.
        try:
            pdf = acr_export_pdf.render_html(acr_export_preview.to_html(projection))
        except acr_export_pdf.RendererUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        return Response(
            pdf, media_type="application/pdf",
            headers={"Content-Disposition":
                     f'attachment; filename="{acr_export_pdf.filename_for(report)}"'})
    return projection


# ── roles ──────────────────────────────────────────────────────────────────────

class GrantRole(BaseModel):
    email: str
    role: str
    report_id: str | None = None


@router.get("/acr/{report_id}/roles")
def get_roles(report_id: str, request: Request):
    owner = _tenant()
    _report_or_404(report_id, owner)
    who = _actor(request)
    granted = _roles(who, report_id)
    return {"email": who, "roles": granted,
            "effective": sorted(acr_authz.effective_roles(
                granted, is_platform_owner=core.is_owner(who)))}


@router.put("/acr/{report_id}/roles")
def grant_role(report_id: str, body: GrantRole, request: Request):
    """Grant an ACR role. Requires the ACR admin role — which, on a fresh deploy where nobody has
    one yet, only the protected ACP_OWNER_EMAIL holds (acr_authz's anti-lockout carve-out)."""
    owner = _tenant()
    _report_or_404(report_id, owner)
    who = _require(acr_authz.ROLE_ADMIN, request, report_id)
    if body.role not in acr_authz.ROLES:
        raise HTTPException(422, f"{body.role!r} is not one of {sorted(acr_authz.ROLES)}")
    core.store.grant_acr_role(owner_email=owner, email=body.email, role=body.role,
                              report_id=body.report_id or report_id, granted_by=who)
    core.store.append_acr_decision_log(report_id, owner_email=owner, actor=who,
                                       action="role.granted",
                                       detail=f"{body.email} -> {body.role}")
    return {"email": body.email, "role": body.role}


# ── publication and revisions (PRD §16, §17, Phase 4) ──────────────────────────
#
# THE IRREVERSIBLE ACT. Everything the earlier phases built exists so that what gets frozen here
# is true. The gate is deliberately ASSEMBLED FROM PARTS THAT ALREADY EXISTED and are tested on
# their own — acr_validation.validate, acr_authz.may_publish, acr_freshness — rather than a new
# "can publish?" predicate written for this endpoint. A second implementation of the gate is how a
# screen ends up green while the real check is red, and this is the check that matters most.


def _decision_makers(criteria: list[dict]) -> dict[str, int]:
    """Who decided how many criteria — the input to PRD §18's separation-of-duties advisory."""
    counts: dict[str, int] = {}
    for crit in criteria:
        who = (crit.get("evaluator") or "").strip().lower()
        if who and crit.get("final_status"):
            counts[who] = counts.get(who, 0) + 1
    return counts


def _other_approvers(report_id: str, owner: str, me: str) -> int:
    """How many OTHER people could approve this report.

    PRD §18 conditions its recommendation on a second qualified reviewer being available, so this
    count decides whether the warning is meaningful at all. Counting generously would nag a
    one-person team on every publish until they learned to ignore the warning entirely.
    """
    try:
        holders = core.store.list_acr_role_holders(
            owner_email=owner, report_id=report_id,
            roles=(acr_authz.ROLE_APPROVER, acr_authz.ROLE_ADMIN))
    except Exception:
        return 0
    mine = me.strip().lower()
    return len({h.strip().lower() for h in holders if h.strip().lower() != mine})


def _lineage(report: dict, owner: str) -> list[dict]:
    """This report and every revision it supersedes, newest first.

    A revision is a NEW acr_report row, so "the history of this report" spans several ids and has
    to be walked. BOUNDED rather than `while True`: a supersedes_id cycle would otherwise hang the
    request, and a corrupt chain should degrade to a short history rather than an outage.
    """
    chain = [report]
    seen = {report["id"]}
    current = report
    for _ in range(50):
        prev_id = current.get("supersedes_id")
        if not prev_id or prev_id in seen:
            break
        prev = core.store.get_acr_report(prev_id, owner_email=owner)
        if prev is None:
            break
        chain.append(prev)
        seen.add(prev_id)
        current = prev
    return chain


@router.get("/acr/{report_id}/publication")
def publication_readiness(report_id: str, request: Request):
    """Everything the publish button needs to render itself honestly, from the REAL gate.

    The screen does not decide whether publishing is allowed; it renders what this says. Same rule
    the criterion detail follows for refusal sentences, and it is why the blocking count here comes
    from acr_validation.validate rather than from a tally the UI keeps.
    """
    owner = _tenant()
    who = _actor(request)
    report = _report_or_404(report_id, owner)
    criteria = core.store.list_acr_criteria(report_id, owner_email=owner)
    ev_by = _evidence_objects(report_id, owner)

    blockers = acr_validation.validate(
        report, criteria, ev_by,
        manual_plan_status=_manual_plan_status(report, report_id, owner))
    granted = _roles(who, report_id)
    allowed, why = acr_authz.may_publish(who, granted, report=report,
                                         is_platform_owner=core.is_owner(who))
    warning = acr_authz.separation_warning(
        who, _decision_makers(criteria), other_approvers=_other_approvers(report_id, owner, who))
    blocking = [b for b in blockers if b.blocking]

    return {
        "report_id": report_id,
        "status": report.get("status"),
        "revision": report.get("revision"),
        "may_publish": bool(allowed) and not blocking,
        "role_refusal": "" if allowed else why,
        "blocking_count": len(blocking),
        "summary": acr_validation.summary(blockers),
        "by_category": acr_validation.group(blockers),
        "category_labels": acr_validation.CATEGORY_LABELS,
        # Advisory, never a block. PRD §18 words it as a recommendation, and encoding it as a
        # refusal would stop a one-person team from ever publishing.
        "separation_warning": warning or "",
        "irreversible_note": ("Publishing freezes this report as an immutable revision. It cannot "
                              "be edited or withdrawn afterwards — a correction is published as a "
                              "new revision that supersedes it."),
    }


@router.post("/acr/{report_id}/publish")
def publish(report_id: str, request: Request):
    """Freeze the report as an immutable published revision (PRD §16, §21.11, §21.12).

    THE ORDER OF THESE CHECKS IS NOT ARBITRARY:

      1. the report exists, and is not already published,
      2. the CALLER may publish — acr_authz, never core.is_admin, which returns True for every
         authenticated user under the default OPEN_ACCESS=1,
      3. validation is completely clean — every blocker, recomputed here, never a count the
         caller passed in.

    (2) before (3) so an unauthorized caller learns nothing about the report's internal readiness,
    and (3) last because it is the expensive one.

    The snapshot is written by store.create_acr_snapshot, which inserts the row and flips the
    report's status in ONE transaction — a report marked published whose snapshot write failed
    would be a report claiming an artifact that does not exist.
    """
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    who = _actor(request)

    granted = _roles(who, report_id)
    allowed, why = acr_authz.may_publish(who, granted, report=report,
                                         is_platform_owner=core.is_owner(who))
    if not allowed:
        # 409 when it is already published (a state conflict); 403 when it is about the caller.
        raise HTTPException(409 if report.get("status") == "published" else 403, why)

    criteria = core.store.list_acr_criteria(report_id, owner_email=owner)
    ev_by = _evidence_objects(report_id, owner)
    blockers = acr_validation.validate(
        report, criteria, ev_by,
        manual_plan_status=_manual_plan_status(report, report_id, owner))
    blocking = [b for b in blockers if b.blocking]
    if blocking:
        raise HTTPException(400, {
            "message": f"{len(blocking)} blocker(s) prevent publication",
            "blockers": [b.to_row() for b in blocking],
        })

    content = acr_publish.snapshot_content(report, criteria, ev_by,
                                           catalog_hash=acr_catalog.catalog_hash())
    digest = acr_publish.content_digest(content)
    snapshot_id = f"acrsnap_{uuid.uuid4().hex[:12]}"
    published_at = core.store.create_acr_snapshot(
        snapshot_id, report_id=report_id, owner_email=owner,
        revision=int(report.get("revision") or 1), catalog_hash=acr_catalog.catalog_hash(),
        content_json=json.dumps(content, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False),
        content_digest=digest, published_by=who)

    warning = acr_authz.separation_warning(
        who, _decision_makers(criteria), other_approvers=_other_approvers(report_id, owner, who))
    core.store.append_acr_decision_log(
        report_id, owner_email=owner, actor=who, action="report.published",
        detail=(f"revision {report.get('revision')} · digest {digest[:12]}"
                + (f" · {warning}" if warning else "")))

    return {
        "snapshot_id": snapshot_id, "revision": report.get("revision"),
        "published_at": published_at, "published_by": who,
        "content_digest": digest,
        # Repeated on the response, not left to the module docstring. Someone reading an API
        # client's log should not be able to conclude this was signed.
        "digest_note": ("A recomputable SHA-256 over the snapshot content. This is a digest, not "
                        "a digital signature: it makes alteration detectable and provides no "
                        "non-repudiation."),
        "separation_warning": warning or "",
    }


@router.get("/acr/{report_id}/revisions")
def revisions(report_id: str, request: Request):
    """Every published revision across this report's supersedes chain, newest first."""
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    chain = _lineage(report, owner)
    snaps = core.store.list_acr_snapshots_for_lineage([r["id"] for r in chain], owner_email=owner)

    rows = []
    for snap in snaps:
        ok, why = acr_publish.verify(snap)
        rows.append({
            "snapshot_id": snap["id"], "report_id": snap["report_id"],
            "revision": snap["revision"], "published_at": snap["published_at"],
            "published_by": snap["published_by"], "content_digest": snap["content_digest"],
            "catalog_hash": snap["catalog_hash"],
            # Verified on every listing rather than on request. A tamper-evident record that
            # nobody ever checks is a record nobody has checked.
            "digest_verified": ok, "digest_problem": why,
        })
    return {"revisions": rows, "current_report_id": report_id,
            "lineage": [{"report_id": r["id"], "revision": r.get("revision"),
                         "status": r.get("status"),
                         "product_version": r.get("product_version")} for r in chain]}


@router.get("/acr/{report_id}/revisions/{revision}")
def revision_detail(report_id: str, revision: int, request: Request):
    """One immutable published revision, with its digest re-verified against its contents."""
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    chain = _lineage(report, owner)
    snaps = core.store.list_acr_snapshots_for_lineage([r["id"] for r in chain], owner_email=owner)
    snap = next((s for s in snaps if int(s["revision"]) == int(revision)), None)
    if snap is None:
        raise HTTPException(404, f"no published revision {revision} for this report")

    ok, why = acr_publish.verify(snap)
    return {
        "snapshot_id": snap["id"], "revision": snap["revision"],
        "published_at": snap["published_at"], "published_by": snap["published_by"],
        "content_digest": snap["content_digest"], "digest_verified": ok, "digest_problem": why,
        "content": json.loads(snap["content_json"]),
    }


@router.post("/acr/{report_id}/revise")
def revise(report_id: str, request: Request):
    """Open a NEW draft revision that supersedes a published report (PRD §17).

    A published snapshot is never edited, so a correction is a new report row with supersedes_id
    set and revision+1. What it INHERITS is the interesting part.

    THE RULE PRD §19 ENDS ON: never copy a previous version's "Supports" decisions without
    freshness validation. `acr_publish.carry_forward` re-derives staleness against the NEW report
    and sends any Supports claim with no live evidence left back to needs_review — and NO approval
    carries at all, because an approval granted for the previous product version is not a sign-off
    on this one. The criteria that were reset are RETURNED rather than applied silently: the person
    opening the revision needs to know what they are being asked to re-evaluate.
    """
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    who = _require(acr_authz.ROLE_EDITOR, request, report_id)

    if report.get("status") != "published":
        raise HTTPException(409, "only a published report is revised; this one is still a draft "
                                 "and can be edited directly")

    new_id = f"acr_{uuid.uuid4().hex[:12]}"
    new_revision = int(report.get("revision") or 1) + 1
    meta = {k: report.get(k) for k in core.store._ACR_REPORT_EDITABLE}
    new_report = dict(report)
    new_report.update({"id": new_id, "revision": new_revision, "status": "draft",
                       "published_at": None, "supersedes_id": report_id})

    criteria = core.store.list_acr_criteria(report_id, owner_email=owner)
    ev_by = _evidence_objects(report_id, owner)
    carried, reset = acr_publish.carry_forward(criteria, ev_by, new_report=new_report)

    core.store.create_acr_report(new_id, owner_email=owner,
                                 catalog_hash=acr_catalog.catalog_hash(),
                                 criteria=acr_catalog.build_matrix(new_id), metadata=meta,
                                 supersedes_id=report_id, revision=new_revision)
    written = core.store.carry_acr_decisions(new_id, carried, owner_email=owner)
    # Roles carry; approvals do not. A role authorizes someone to act on this report, and a
    # revision is the same report — without this, every revision would need an admin to re-grant
    # every role before anyone could touch it, and the person revising may not be one. An
    # APPROVAL is the opposite kind of fact and is deliberately left behind; see carry_forward.
    core.store.copy_acr_role_grants(owner_email=owner, from_report_id=report_id,
                                    to_report_id=new_id)

    core.store.append_acr_decision_log(
        new_id, owner_email=owner, actor=who, action="report.revised",
        detail=(f"revision {new_revision}, superseding {report_id}; {written} decision(s) "
                f"carried, {len(reset)} reset for re-evaluation"))

    return {
        "report_id": new_id, "revision": new_revision, "supersedes_id": report_id,
        "carried": written, "reset_criteria": reset,
        "note": ("Every carried criterion re-enters the approval queue: an approval granted "
                 "against the previous revision was granted for a different product version. "
                 f"{len(reset)} criterion/criteria lost a Supports claim because the evidence "
                 "behind it is stale for this version."),
    }
