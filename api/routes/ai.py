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


def _language_parts_draft(request: Request, scan_id: str, file: str) -> dict | None:
    """Deterministic 3.1.2 draft: re-extract the document's text via the same source-bytes
    ladder the preview uses, run the seeded langdetect suggester, and hand back the detected
    language(s) + passages. Best-effort — None degrades to the caller's existing flow."""
    try:
        import tempfile
        from pathlib import Path as _P

        import pii as _pii
        import proposals as _prop
        from routes.scans import _owner, _source_bytes_for_render
        data = _source_bytes_for_render(request, scan_id, file, _owner(request))
        if not data:
            return None
        with tempfile.TemporaryDirectory(prefix="acp-langdraft-") as d:
            p = _P(d) / _P(file).name
            p.write_bytes(data)
            text = _pii.extract_text(p)
        return _prop.language_parts_suggestion(text)
    except Exception:
        return None


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
    # 3.1.2 Language of Parts is machine-detectable, not authored: langdetect (seeded,
    # deterministic) identifies the foreign passage's language from the document text itself.
    # Answer from that BEFORE any model gate — the generic text model produced rule-mismatched
    # nonsense here ("add alt text", "rename the file"), and this path needs no model at all.
    if rule_id == "3.1.2":
        det = _language_parts_draft(request, scan_id, file)
        if det:
            return det
        # No confident detection (e.g. the foreign text lives only in an image with no OCR
        # here) — hand back an honest fill-in template rather than asking a text model, which
        # demonstrably produced rule-mismatched nonsense for this criterion.
        return {"suggestion": 'lang="fr"  (replace fr with the passage\'s language code)',
                "kind": "language tag", "is_template": True, "model": None,
                "reason": ("No confident automatic detection for this passage — identify its "
                           "language and give the ISO code (fr, es, de, …).")}
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
    # ADR 0021 — org house-style guidance (empty unless review memory is active for this org).
    # Best-effort: memory must never break a draft, so any lookup failure degrades to "".
    import memory as _mem
    guidance, org, fmt = "", None, (file.rsplit(".", 1)[-1].lower() if "." in file else None)
    try:
        org = getattr(request.state, "user_email", None) or "demo"
        guidance = _mem.guidance_for(core.store, org, rule_id, fmt)
    except Exception:
        guidance = ""
    result = _ai.suggest_fix(
        rule_id=rule_id,
        rule_name=trace["rule_name"],
        level=trace["level"],
        filename=file,
        detail=trace.get("detail", "") or "",
        image_bytes=img,
        style="" if safe_style == "regenerate" else safe_style,
        guidance=guidance,
    )
    if result is not None and guidance:
        # ADR 0021 §E — the memory that shaped this draft is visible on the card.
        result["house_style_applied"] = _mem.applied_rule_count(core.store, org, rule_id, fmt)
    if result is None:
        raise HTTPException(503, "AI suggestion unavailable — is Ollama running?")
    # Verification aid (<10s trust): alongside a vision draft, hand the reviewer the text OCR
    # actually read from the image — a deterministic cross-check of the description against
    # what the image says, not another score (ADR 0016). Best-effort; absent when no text.
    if img and rule_id == "1.1.1" and result.get("suggestion") and not result.get("is_template"):
        try:
            import ocr as _ocr
            if _ocr.is_available():
                txt = " ".join(_ocr.ocr_text(img).split())[:400]
                if txt:
                    result["ocr_text"] = txt
        except Exception:
            pass
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


# ── Enterprise review memory (ADR 0021) — admin authoring + read ────────────────
_MEMORY_KINDS = {"style", "glossary"}   # admin may AUTHOR these; 'derived' is job-only (stage 3)


@router.get("/org-memory")
def list_org_memory(request: Request):
    """The signed-in org's review-memory rules — all statuses, so an admin sees active house
    style AND (later) derived proposals awaiting a decision. Org-scoped: never another
    tenant's memory."""
    from routes.scans import _owner
    return {"rules": core.store.list_org_memory(_owner(request)),
            "enabled": os.environ.get("ACP_REVIEW_MEMORY", "").strip().lower()
            in ("1", "true", "yes", "on")}


@router.post("/org-memory")
def add_org_memory(request: Request, kind: str = Query(...), guidance: str = Query(...),
                   rule_id: str | None = Query(None), format: str | None = Query(None)):
    """Author a house-style / glossary rule (admin only). It applies immediately (status
    'active') because a human wrote it — that is the authored tier of ADR 0021 §A. `derived`
    rules are never created here; the derivation job (stage 3) proposes those."""
    from .system import _require_admin
    _require_admin(request)
    from routes.scans import _owner
    if kind not in _MEMORY_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(_MEMORY_KINDS)}")
    g = (guidance or "").strip()
    if not g:
        raise HTTPException(422, "guidance is required")
    mid = core.store.add_org_memory(_owner(request), kind, g[:600], rule_id=rule_id or None,
                                    format=(format or None), status="active",
                                    author=_owner(request))
    core.store.log_decision(_owner(request), "org_memory.authored",
                            detail=f"{kind} {rule_id or 'all'}/{format or 'all'}")
    return {"id": mid, "status": "active"}


@router.post("/org-memory/derive")
def derive_org_memory(request: Request):
    """Run the derivation job for the signed-in org NOW (ADR 0021 stage 3): read recent HITL
    decisions and PROPOSE house-style rules the behaviour supports — status='proposed', never
    auto-applied. Admin-gated; returns the candidates it added (each with its real evidence
    count). The nightly scheduler runs the same job across all orgs when review memory is on."""
    from .system import _require_admin
    _require_admin(request)
    import memory as _mem
    from routes.scans import _owner
    proposed = _mem.derive_org_memory(core.store, _owner(request))
    if proposed:
        core.store.log_decision(_owner(request), "org_memory.derived",
                                detail=f"{len(proposed)} proposal(s)")
    return {"proposed": proposed, "count": len(proposed)}


@router.put("/org-memory/{mid}/status")
def set_org_memory_status(mid: str, request: Request, status: str = Query(...)):
    """Accept a proposal ('active') or retire a rule ('archived'). Admin-gated, org-scoped.
    Archiving takes effect on the next draft; prompt-hash provenance (ADR 0102) means past
    drafts remain attributable to the rule that shaped them."""
    from .system import _require_admin
    _require_admin(request)
    from routes.scans import _owner
    if status not in ("active", "archived", "proposed"):
        raise HTTPException(422, "status must be active | archived | proposed")
    if not core.store.set_org_memory_status(_owner(request), mid, status):
        raise HTTPException(404, "rule not found for this org")
    core.store.log_decision(_owner(request), f"org_memory.{status}", detail=mid)
    return {"id": mid, "status": status}


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
