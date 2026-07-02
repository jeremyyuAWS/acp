"""AI explanation endpoints (local Ollama)."""
from __future__ import annotations

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
    if not os.environ.get("ANTHROPIC_API_KEY") and not _ai.is_available():
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


@router.get("/ai/status")
def ai_status():
    """Check whether the local Ollama instance is reachable, and report whether
    AI is enabled platform-wide (admin deterministic-only toggle)."""
    import ai as _ai
    return {"available": _ai.is_available(), "base_url": _ai.OLLAMA_BASE_URL,
            "model": _ai.OLLAMA_MODEL, "ai_enabled": core.store.get_ai_enabled()}
