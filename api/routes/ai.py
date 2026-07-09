"""AI explanation endpoints (local Ollama)."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query

import core

router = APIRouter()


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
def ai_suggest(scan_id: str = Query(...), file: str = Query(...), rule_id: str = Query(...)):
    """Draft a concrete, human-approvable fix value (alt text / link text / title) for a
    semantic finding. Same AI gates as /ai/explain; 503 when Ollama is unavailable. The
    reviewer accepts or edits the draft in the HITL queue — it is never auto-applied."""
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
    result = _ai.suggest_fix(
        rule_id=rule_id,
        rule_name=trace["rule_name"],
        level=trace["level"],
        filename=file,
        detail=trace.get("detail", "") or "",
    )
    if result is None:
        raise HTTPException(503, "AI suggestion unavailable — is Ollama running?")
    return result


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
