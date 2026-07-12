"""AI explanation endpoints (local Ollama)."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query, Request

import core

router = APIRouter()


def _image_for_locator(request: Request, scan_id: str, file: str, locator: str) -> bytes | None:
    """The embedded image a 1.1.1 review item is asking about, fetched at REVIEW time.

    Without this the vision model can never be reached from the inbox: suggest_fix only
    consults it when handed image bytes, so 1.1.1 always fell through to the text model's
    fill-in template — a guess from the filename, never a look at the picture.

    Reuses the preview's source-bytes ladder (local corpus → Drive original → remediated blob),
    so it needs no new credentials. Best-effort by construction: every failure returns None and
    the caller degrades to the template it would have produced anyway."""
    if not locator:
        return None
    try:
        from remediate_office import image_bytes_for_locator
        from routes.scans import _owner, _source_bytes_for_render
        data = _source_bytes_for_render(request, scan_id, file, _owner(request))
        return image_bytes_for_locator(data, locator) if data else None
    except Exception:
        return None


@router.get("/ai/explain")
def ai_explain(scan_id: str = Query(...), file: str = Query(...), rule_id: str = Query(...)):
    """Generate a plain-English explanation + fix example for one WCAG finding.

    Calls the local Ollama instance (OLLAMA_BASE_URL, default http://localhost:11434).
    Returns 503 when Ollama is unavailable — callers should handle gracefully.
    """
    # Deterministic-only mode is a hard gate: no AI calls when an admin has
    # disabled AI platform-wide. Findings are reachable via the HITL queue instead.
    if not core.store.get_ai_enabled():
        raise HTTPException(403, "AI is disabled (deterministic-only mode) — findings route to human review")
    import os

    import ai as _ai
    # Fast-fail when no backend can answer: without an Anthropic key the only path
    # is Ollama, and probing it costs 3s — far better than letting the request (and
    # the UI's "thinking…" spinner) hang on a wedged/scaled-to-zero instance.
    ollama_only = os.environ.get("ACP_AI_BACKEND", "auto").lower() == "ollama" or not os.environ.get("ANTHROPIC_API_KEY")
    if ollama_only and not _ai.is_available():
        raise HTTPException(503, "AI explanation unavailable — is Ollama running?")
    trace = core.store.get_trace_row(scan_id, file, rule_id)
    if trace is None:
        raise HTTPException(404, "trace not found")
    engine_rule_ids = core.store.get_issue_rule_ids(scan_id, file, rule_id)
    result = _ai.explain_finding(
        rule_id=rule_id,
        rule_name=trace["rule_name"],
        level=trace["level"],
        filename=file,
        finding_count=trace["finding_count"],
        severity=trace.get("severity", ""),
        engine_rule_ids=engine_rule_ids,
    )
    if result is None:
        raise HTTPException(503, "AI explanation unavailable — is Ollama running?")
    return result


@router.get("/ai/suggest")
def ai_suggest(request: Request, scan_id: str = Query(...), file: str = Query(...),
               rule_id: str = Query(...), locator: str | None = Query(None),
               style: str | None = Query(None), validate: int = Query(0)):
    """Draft a concrete, human-approvable fix value (alt text / link text / title) for a
    semantic finding. Same AI gates as /ai/explain; 503 when Ollama is unavailable. The
    reviewer accepts or edits the draft in the HITL queue — it is never auto-applied.

    `locator` ('part#rId', from hitl_queue.evidence) names WHICH embedded image to describe.
    With it, 1.1.1 reaches the vision model and returns genuine image-derived alt text; without
    it the text model can only emit a fill-in template, because it cannot see."""
    if not core.store.get_ai_enabled():
        raise HTTPException(403, "AI is disabled (deterministic-only mode) — findings route to human review")
    import os

    import ai as _ai
    ollama_only = os.environ.get("ACP_AI_BACKEND", "auto").lower() == "ollama" or not os.environ.get("ANTHROPIC_API_KEY")
    if ollama_only and not _ai.is_available():
        raise HTTPException(503, "AI suggestion unavailable — is Ollama running?")
    trace = core.store.get_trace_row(scan_id, file, rule_id)
    if trace is None:
        raise HTTPException(404, "trace not found")
    # Reviewer refinement (#131): only a bounded length steer reaches the model — never free text —
    # so a caption can be re-drafted shorter/longer/afresh without opening a prompt-injection path.
    safe_style = style if style in ("shorter", "detailed", "regenerate") else ""
    img = _image_for_locator(request, scan_id, file, locator) if rule_id == "1.1.1" else None
    result = _ai.suggest_fix(
        rule_id=rule_id,
        rule_name=trace["rule_name"],
        level=trace["level"],
        filename=file,
        detail=trace.get("detail", "") or "",
        image_bytes=img,
        style="" if safe_style == "regenerate" else safe_style,
    )
    if result is None:
        raise HTTPException(503, "AI suggestion unavailable — is Ollama running?")
    # Opt-in second-opinion cross-check (#123): the model independently re-describes the image and we
    # compare — 'consistent' raises confidence toward auto-approve, 'divergent' hands the reviewer the
    # second description as evidence. Additive; only for a real vision draft, and best-effort.
    if validate and img and rule_id == "1.1.1" and result.get("suggestion") and not result.get("is_template"):
        try:
            v = _ai.validate_alt_text(img, result["suggestion"], filename=file, scan_id=scan_id, file=file)
            if v:
                result["validation"] = v
        except Exception:
            pass
    return result


@router.get("/ai/validate")
def ai_validate(request: Request, scan_id: str = Query(...), file: str = Query(...),
                rule_id: str = Query(...), alt: str = Query(...), locator: str | None = Query(None)):
    """Second-opinion cross-check of a proposed alt text (#123): the vision model INDEPENDENTLY
    re-describes the located image, and we compare — 'consistent' (the draft agrees with a fresh
    look) or 'divergent' (+ the second description as evidence). A verification pass, never a score.
    Only meaningful for 1.1.1 image findings; returns {} when there's no image or the model is down."""
    if not core.store.get_ai_enabled():
        raise HTTPException(403, "AI is disabled (deterministic-only mode)")
    import ai as _ai
    if not _ai.is_available():
        raise HTTPException(503, "AI validation unavailable — is Ollama running?")
    img = _image_for_locator(request, scan_id, file, locator) if rule_id == "1.1.1" else None
    if not img or not (alt or "").strip():
        return {}
    try:
        return _ai.validate_alt_text(img, alt, filename=file, scan_id=scan_id, file=file) or {}
    except Exception:
        return {}


@router.get("/ai/status")
def ai_status():
    """Check whether the local Ollama instance is reachable, and report whether
    AI is enabled platform-wide (admin deterministic-only toggle). Also reports
    whether a vision model is pulled — genuine image alt text (WCAG 1.1.1) needs it,
    and it degrades to human review when absent."""
    import ai as _ai
    vision = _ai.vision_is_available()
    return {"available": _ai.is_available(), "base_url": _ai.OLLAMA_BASE_URL,
            "model": _ai.OLLAMA_MODEL, "ai_enabled": core.store.get_ai_enabled(),
            "backend": os.environ.get("ACP_AI_BACKEND", "auto").lower(),
            "vision_available": vision, "vision_model": _ai.OLLAMA_VISION_MODEL}


@router.get("/ai/costs")
def ai_costs():
    """AI usage + cost governance rollup (ADR 0019 Phase 1): today / 30-day / all-time, each
    a real aggregate of recorded ai_calls (provider, zone, surface, latency, summed cost).
    For the keyless local-Ollama build every cost is a genuine $0 — no per-token billing, no
    bytes off-network — which is itself the governance headline; a cloud adapter records real
    cost and this reflects it. Requires sign-in (governance data isn't exposed anonymously);
    the admin Settings panel reads it with the signed-in user's session."""
    return {"today": core.store.ai_cost_rollup(since_days=1),
            "month": core.store.ai_cost_rollup(since_days=30),
            "all_time": core.store.ai_cost_rollup(since_days=None)}
