"""Read-only remediation automation policy preview API."""
from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt, StrictStr, StrictBool

from remediation_automation_policy import build_policy_preview

router = APIRouter()


class PolicyPreviewRequest(BaseModel):
    findings: list[dict]
    level: int | None = Field(default=None, ge=1, le=5)


@router.post("/remediation/automation-policy/preview")
def remediation_policy_preview(body: PolicyPreviewRequest):
    return build_policy_preview(body.findings, level=body.level)


class ImpactPreviewRequest(BaseModel):
    scope: list[StrictStr] | None = None
    rule_based: StrictInt | None = Field(default=None, ge=0, le=2)
    ai: StrictInt | None = Field(default=None, ge=0, le=3)
    ai_budget_usd: StrictStr | None = Field(default=None, pattern=r'^\d{1,7}(?:\.\d{1,2})?$', max_length=10)
    ai_review: dict | None = None
    auto_approve_ai: StrictBool | None = None
    generation_chain: dict | None = None


class ImpactSaveRequest(ImpactPreviewRequest):
    rule_based: StrictInt = Field(ge=0, le=2)
    ai: StrictInt = Field(ge=0, le=3)
    expected_revision: StrictInt = Field(ge=0)


def _impact_owner(request):
    return getattr(request.state, 'user_email', None) or 'demo'


from fastapi import HTTPException, Request, Response


@router.post('/scans/{sid}/remediation/impact-preview')
def remediation_impact_preview(sid: str, body: ImpactPreviewRequest, request: Request, response: Response):
    import core
    from remediation_impact import build_run_impact, provider_summary
    selected = body.model_dump(exclude_none=True, exclude={'scope'})
    if selected and not {'rule_based', 'ai'}.issubset(selected):
        raise HTTPException(422, 'Both rule_based and ai are required.')
    if selected:
        from remediation_impact_settings import normalize_policy
        try:
            selected = normalize_policy(selected)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    response.headers['Cache-Control'] = 'no-store'
    try:
        result = build_run_impact(core.store, sid, _impact_owner(request), selected or None, scope=body.scope)
        result['providers'] = provider_summary(result['capabilities']['ai_enabled'])
        from ai_review_policy import capabilities
        result['capabilities']['ai_review'] = capabilities(core.store, _impact_owner(request))
        from ai_standing_approval import capabilities as standing_capabilities
        result['capabilities']['ai_standing_approval'] = standing_capabilities(core.store, _impact_owner(request))
        if result['policy'].get('auto_approve_ai') and not result['capabilities']['ai_standing_approval']['supported']:
            result['capabilities'].update(execute=False, reason=result['capabilities']['ai_standing_approval']['reason'])
        from remediation_cohort_estimates import read_plan_estimate
        result['estimated_impact'] = read_plan_estimate(core.store, _impact_owner(request), result)
        return result
    except LookupError as exc:
        raise HTTPException(404, 'scan not found') from exc


@router.get('/scans/{sid}/remediation/impact-policy')
def remediation_impact_policy(sid: str, request: Request, response: Response):
    import core
    from remediation_impact_settings import read_impact_policy
    owner = _impact_owner(request)
    if core.store.get_scan(sid, owner=owner) is None:
        raise HTTPException(404, 'scan not found')
    response.headers['Cache-Control'] = 'no-store'
    return read_impact_policy(core.store, owner)


@router.get('/scans/{sid}/remediation/budget/{run_id}')
def remediation_run_budget(sid: str, run_id: str, request: Request, response: Response):
    import core
    from ai_run_policy import read_run_budget
    owner = _impact_owner(request)
    if core.store.get_scan(sid, owner=owner) is None:
        raise HTTPException(404, 'scan not found')
    result = read_run_budget(core.store, owner, sid, run_id)
    if result is None:
        raise HTTPException(404, 'Managed AI budget not found for this run.')
    response.headers['Cache-Control'] = 'no-store'
    # All amounts are integer micro-USD. No provider credentials are returned.
    return result


@router.post('/scans/{sid}/remediation/impact-policy')
def save_remediation_impact_policy(sid: str, body: ImpactSaveRequest, request: Request):
    import core
    from remediation_impact_settings import save_impact_policy, ImpactPolicyConflict
    owner = _impact_owner(request)
    if core.store.get_scan(sid, owner=owner) is None:
        raise HTTPException(404, 'scan not found')
    try:
        return save_impact_policy(core.store, owner, owner,
                                  body.model_dump(exclude_none=True, exclude={'scope', 'expected_revision'}), body.expected_revision)
    except ImpactPolicyConflict as exc:
        raise HTTPException(409, {'message': 'Policy changed. Reload and try again.', 'current': exc.current}) from exc
    except ValueError as exc:
        raise HTTPException(409 if 'revision' in str(exc).lower() else 422, str(exc)) from exc


class ImpactAssignmentPolicy(BaseModel):
    rule_based: StrictInt = Field(ge=0, le=2)
    ai: StrictInt = Field(ge=0, le=3)


class ImpactAssignmentRequest(BaseModel):
    files: list[StrictStr] = Field(min_length=1, max_length=10000)
    assignee: StrictStr = Field(min_length=3, max_length=320)
    policy: ImpactAssignmentPolicy | None = None


@router.post('/scans/{sid}/remediation/impact-assign')
def assign_remediation_impact_work(sid: str, body: ImpactAssignmentRequest, request: Request):
    import core
    from remediation_impact import assign_impact_work
    try:
        return assign_impact_work(core.store, sid, _impact_owner(request), body.files,
                                  body.assignee, body.policy.model_dump() if body.policy else None)
    except LookupError as exc:
        raise HTTPException(404, 'scan not found') from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/scans/{sid}/remediation/impact-estimate')
def remediation_plan_estimate(sid: str, body: ImpactPreviewRequest, request: Request, response: Response):
    """Identical owner/scope checks to routing preview; no paid inference or writes."""
    import core
    from remediation_cohort_estimates import read_plan_estimate
    preview = remediation_impact_preview(sid, body, request, response)
    return read_plan_estimate(core.store, _impact_owner(request), preview)
