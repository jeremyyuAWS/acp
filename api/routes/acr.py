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
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import acr_authz
import acr_catalog
import acr_export_preview
import acr_freshness
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


# ── validation, audit and preview ──────────────────────────────────────────────

@router.get("/acr/{report_id}/validation")
def validation(report_id: str, request: Request):
    """PRD §15's validation screen. Calls the SAME acr_validation.validate the publish gate does —
    a separately-computed readiness summary is how a screen ends up green while the gate is red."""
    owner = _tenant()
    report = _report_or_404(report_id, owner)
    criteria = core.store.list_acr_criteria(report_id, owner_email=owner)
    ev_by = _evidence_objects(report_id, owner)
    blockers = acr_validation.validate(report, criteria, ev_by)
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
