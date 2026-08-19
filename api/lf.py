"""Langfuse observability wrapper for the ACP scan engine.

Emits one trace per scan, one span per document, one child span per WCAG rule.
Designed so a NON-technical viewer can open a trace and understand it: human
trace names, plain document/rule labels, ✓/✗ outcomes, failures flagged as
warnings/errors, a one-line summary, and a 0–100 compliance score on each trace.

All methods are no-ops when LANGFUSE_SECRET_KEY is absent — safe to import
everywhere without requiring the package.

Env vars:
  LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY  (all required to activate)
"""
from __future__ import annotations
import os

_HOST = os.environ.get("LANGFUSE_HOST", "")
_PK   = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
_SK   = os.environ.get("LANGFUSE_SECRET_KEY", "")
_ENABLED = bool(_HOST and _PK and _SK)

_client = None

# Friendly source labels for trace names/summaries.
_SOURCE_LABEL = {"drive": "Google Drive", "sharepoint": "SharePoint / OneDrive", "local": "local corpus"}


# ── document labels: the filename is PHI in a hospital estate ─────────────────
# `Smith_John_MRN0114233_intake.docx` names a patient, and the filename was the one field that
# rode on EVERY trace — name, id, tag and metadata — on every scan, whether or not a model ran.
# docs/audit-langfuse-phi.md called it the largest exposure by volume and the least obvious.
#
# So by default a document appears as a stable opaque label plus its extension:
#
#     Smith_John_MRN0114233_intake.docx  ->  doc-3f9a2c.docx
#
# WHAT THAT KEEPS. The label is deterministic per (deployment, filename), so every span for one
# document still collapses onto one trace, a document is still followable across scans, and the
# extension still says what kind of file it is — which is most of what a filename was doing in a
# trace. What it stops is a trace reader learning a patient's name, and trace access is a wider
# circle than document access.
#
# WHY IT IS KEYED, not a bare hash. An unkeyed digest is a dictionary: anyone who suspects a
# patient is in the estate can hash the likely filename and confirm it. HMAC with a per-deployment
# secret removes that. `ACP_TRACE_SALT` if set, else LANGFUSE_SECRET_KEY — which is already
# required for tracing to run at all, so a traced deployment always has one. Rotating it renames
# labels, which is acceptable: the traces it would break correlation with live in the project that
# key addressed.
#
# WHY THE DEFAULT IS REDACTED. This module's stated design goal is a trace a non-technical viewer
# can read, and plain filenames serve that. But the cost of the wrong default is asymmetric — a
# demo with opaque labels is inconvenient, a hospital deployment with patient names in an
# observability store is an incident. So it is fail-safe by default and the DEMO opts out, the
# same shape as the E2E bypass in core.py. Set ACP_TRACE_FILENAMES=plain for that.
_TRACE_FILENAMES = os.environ.get("ACP_TRACE_FILENAMES", "").strip().lower()
_PLAIN_FILENAMES = _TRACE_FILENAMES == "plain"


def _doc_label(file: str | None) -> str | None:
    """The document's trace-facing name: opaque + extension, or the filename when opted out.

    None in, None out — several callers pass an optional filename and gate on it, and turning
    that into the string "None" would put a fake document in the trace.
    """
    if not file:
        return file
    if _PLAIN_FILENAMES:
        return file
    import hashlib
    import hmac
    salt = (os.environ.get("ACP_TRACE_SALT") or _SK or "").encode()
    digest = hmac.new(salt, str(file).encode("utf-8"), hashlib.sha256).hexdigest()[:6]
    ext = ""
    if "." in str(file):
        candidate = str(file).rsplit(".", 1)[-1]
        # An extension is a type, not an identifier — but only when it looks like one. A file
        # named "Smith, John. Intake" would otherwise contribute " Intake" as its "extension".
        if candidate.isalnum() and len(candidate) <= 5:
            ext = "." + candidate.lower()
    return f"doc-{digest}{ext}"


def _trace_id(scan_id: str | None, file: str | None) -> str | None:
    """The per-file trace id, `{scan_id}::{label}`.

    EVERY site that builds this id must go through here. The id is what joins a file's spans,
    its AI calls, its HITL decisions and its score into one trace, so the label inside it has to
    match everywhere — and it used to interpolate the raw filename at five separate call sites,
    which is both the leak and the reason a single helper is worth more than five careful edits.
    """
    if not scan_id or not file:
        return None
    return f"{scan_id}::{_doc_label(file)}"


def _file_tags(file: str, user: str | None) -> list[str]:
    """Base tag set for a file's trace — shared so a later tag-only update (e.g.
    appending rule-fail tags after Assess) doesn't clobber the tags file_trace set."""
    return ["accessibility-file", f"user:{user or 'demo'}", f"file:{_doc_label(file)}"]


def _det_id(*parts) -> str:
    """Deterministic observation/score id from stable parts. Langfuse upserts
    observations and scores by id, so re-emitting the same logical span (an Assess
    re-run, a worker retry, a trace-chip rebuild) updates the existing one in place
    instead of appending an identical sibling — without this, every re-run added
    another 'Assess · WCAG 2.1 AA' span and another score row to the file's trace."""
    import hashlib
    return hashlib.sha1("::".join(str(p) for p in parts).encode()).hexdigest()


def _lf():
    global _client
    if not _ENABLED:
        return None
    if _client is None:
        from langfuse import Langfuse  # lazy — import only when creds present
        _client = Langfuse(public_key=_PK, secret_key=_SK, host=_HOST)
    return _client


def client():
    """Public accessor for the raw Langfuse client (or None when disabled)."""
    return _lf()


class _Noop:
    """Stand-in for Langfuse trace/span when observability is off."""
    def span(self, **_): return self
    def update(self, **_): return self
    def end(self, **_): return self
    def flush(self): pass


def scan_trace(scan_id: str, source: str, n_files: int, ai_enabled: bool = True,
               user: str | None = None, deep_scan: bool = False):
    """Create a Langfuse trace for one scan run, with a human-readable name.

    user — the signed-in person's email (GIS). Sets the Langfuse trace user_id so
    traces group by who ran the scan; falls back to 'demo' for the keyless demo.
    deep_scan — whether PII detection ran. When off, the trace is a plain "Discover"
    (Step 1) and carries no per-file spans; when on it's "Discover + Deep scan" (1–2)."""
    lf = _lf()
    if lf is None:
        return _Noop()
    src = _SOURCE_LABEL.get(source, source)
    mode = "AI-assisted" if ai_enabled else "Deterministic (no AI)"
    who = user or "demo"
    label = "Scan (Deep)" if deep_scan else "Scan"
    # Lead the name with who ran it so the trace LIST segregates by user at a glance,
    # in addition to user_id (which powers Langfuse's Users view) and a user: tag.
    name = f"{who} · {label} · {n_files} document{'s' if n_files != 1 else ''} · {src}"
    return lf.trace(
        id=scan_id,
        name=name,
        user_id=who,
        metadata={
            "what": (f"Discovered + deep-scanned (PII) {n_files} documents" if deep_scan
                     else f"Discovered {n_files} documents (deep scan off)"),
            "deep_scan": deep_scan,
            "source": src,
            "documents": n_files,
            "mode": mode,
            "ai_enabled": ai_enabled,
            "run_by": who,
        },
        tags=["accessibility-scan", ("deep-scan" if deep_scan else "discover-only"),
              f"source:{source}", f"user:{who}",
              "ai-assisted" if ai_enabled else "deterministic"],
    )


def file_span(trace, filename: str, engine: str):
    """A child span for one document. The name is just the filename (readable)."""
    if isinstance(trace, _Noop):
        return _Noop()
    return trace.span(
        name=_doc_label(filename),
        input={"document": _doc_label(filename), "checked_with": engine},
    )


# Map our severities to a Langfuse observation level so failures stand out (color).
def _level_for(outcome: str, severity: str) -> str:
    if outcome != "FAIL":
        return "DEFAULT"
    return "ERROR" if (severity or "").upper() == "CRITICAL" else "WARNING"


def rule_spans(file_span_, sc_counts: dict[str, int], rule_catalog: list[dict],
               severity_map: dict[str, str] | None = None, filename: str | None = None,
               scan_id: str | None = None, user: str | None = None):
    """One child span per WCAG rule for a document, in plain language.

    Pass → "✓ Non-text Content (1.1.1)".  Fail → "✗ Non-text Content (1.1.1) —
    3 issues", flagged WARNING (or ERROR for critical) so it's visibly highlighted.
    The document name rides on every span (name + input) so an individual rule span
    is associable with its file even outside the trace tree.

    When scan_id is also given, the failing rule ids are appended as tags
    (rule-fail:{id}) on the file's own trace — lets a Langfuse viewer filter across
    every file that failed a given rule, not just search within one file's trace.
    """
    if isinstance(file_span_, _Noop):
        return
    failing_ids: list[str] = []
    for rule in rule_catalog:
        rid = rule["id"]
        count = sc_counts.get(rid, 0)
        outcome = "FAIL" if count > 0 else "PASS"
        severity = (severity_map or {}).get(rid, rule.get("severity", ""))
        # Prefer the non-technical phrase; fall back to the WCAG name, then the id.
        plain = rule.get("plain") or rule.get("name", rid)
        if outcome == "FAIL":
            label = f"✗ {plain} ({rid}) — {count} issue{'s' if count != 1 else ''}"
            status = f"{count} document issue{'s' if count != 1 else ''} ({(severity or 'finding').lower()})"
            failing_ids.append(rid)
        else:
            label = f"✓ {plain} ({rid})"
            status = "No issues"
        s = file_span_.span(
            id=_det_id(getattr(file_span_, "id", ""), "rule", rid),
            name=label,
            level=_level_for(outcome, severity),
            status_message=status,
            input={"document": _doc_label(filename), "rule": f"{rid} {plain}"} if filename else None,
            metadata={
                "document": _doc_label(filename),
                "wcag": f"{rid} {plain}",
                "wcag_level": rule.get("level"),
                "severity": severity,
                "how_its_fixed": rule.get("fix_mode"),
            },
        )
        s.end(output={"document": _doc_label(filename), "result": status, "outcome": outcome, "issues": count})
    if scan_id and filename and failing_ids:
        lf = _lf()
        if lf:
            try:
                lf.trace(id=_trace_id(scan_id, filename)).update(
                    tags=_file_tags(filename, user) + [f"rule-fail:{rid}" for rid in failing_ids])
            except Exception:
                pass


def pii_span(file_span_, pinfo: dict, filename: str | None = None):
    """Emit a span flagging sensitive data found in a document (ADR 0006).

    Counts + MASKED samples only — never raw PII. Flagged WARNING (ERROR when any
    critical type like SSN/credit-card is present) so it stands out in the UI.
    """
    if isinstance(file_span_, _Noop):
        return
    findings = pinfo.get("findings", [])
    if not findings:
        return
    parts = []
    for f in findings:
        n = f["count"]
        noun = f["label"].lower()
        if n == 1:  # singularize: "addresses"->"address", "numbers"->"number"
            noun = noun[:-2] if noun.endswith("addresses") else (noun[:-1] if noun.endswith("s") else noun)
        parts.append(f"{n} {noun}")
    summary = ", ".join(parts)
    level = "ERROR" if pinfo.get("severity") == "critical" else "WARNING"
    s = file_span_.span(
        id=_det_id(getattr(file_span_, "id", ""), "pii"),
        name=f"🔒 Sensitive data — {summary}",
        level=level,
        status_message=f"This document exposes {pinfo.get('total', 0)} sensitive item(s)",
        input={"document": _doc_label(filename)} if filename else None,
        metadata={"document": _doc_label(filename), "sensitive_data_types": pinfo.get("types", {})},
    )
    s.end(output={"found": summary,
                  "examples_masked": {f["type"]: f["samples"] for f in findings}})


def error_span(file_span_, rule_id: str, error_msg: str):
    """A rule that could not be evaluated (engine error) — flagged ERROR."""
    if isinstance(file_span_, _Noop):
        return
    s = file_span_.span(name=f"⚠ Could not check rule {rule_id}", level="ERROR",
                        status_message="The engine could not evaluate this rule")
    s.end(output={"outcome": "ERROR", "error": error_msg})


def finish_scan_trace(trace, scan_id: str, summary: dict, *, source: str, ai_enabled: bool,
                      pii_docs: int = 0, pii_total: int = 0) -> None:
    """Close out a scan trace with a plain-language summary + a 0–100 score, so a
    non-technical viewer sees the outcome at a glance."""
    if isinstance(trace, _Noop):
        return
    files = summary.get("files", 0)
    err = summary.get("error", 0)
    src = _SOURCE_LABEL.get(source, source)
    # The scan trace reports DISCOVERY + deep-scan only. The compliance score and the
    # ready-to-certify / need-fixing conformance counts belong to the Assess trace
    # (written on demand), so they are deliberately not attached here.
    sentence = (f"Scanned {files} documents from {src}"
                + (f", {err} could not be opened" if err else "") + ".")
    if pii_docs:
        sentence += (f" ⚠ {pii_docs} document{'s' if pii_docs != 1 else ''} "
                     f"contain sensitive data ({pii_total} item{'s' if pii_total != 1 else ''}).")
    trace.update(output={
        "summary": sentence,
        "documents_scanned": files,
        "could_not_open": err,
        "documents_with_sensitive_data": pii_docs,
        "sensitive_items_found": pii_total,
        "mode": "AI-assisted" if ai_enabled else "Deterministic (no AI)",
    })


# ── Fan-out helpers: spans/finish referencing a trace by id (ADR 0007) ─────────
def file_span_for(scan_id: str, filename: str, engine: str):
    """A file span on an EXISTING trace, addressed by id — for the fan-out path
    where each file is processed in its own job (no shared in-process handle)."""
    lf = _lf()
    if lf is None:
        return _Noop()
    return lf.trace(id=scan_id).span(name=_doc_label(filename),
                                     input={"document": _doc_label(filename), "checked_with": engine})


def finish_scan_trace_by_id(scan_id: str, summary: dict, *, source: str, ai_enabled: bool,
                            pii_docs: int = 0, pii_total: int = 0) -> None:
    """finish_scan_trace addressed by trace id (fan-out finalize job)."""
    lf = _lf()
    if lf is None:
        return
    finish_scan_trace(lf.trace(id=scan_id), scan_id, summary, source=source,
                      ai_enabled=ai_enabled, pii_docs=pii_docs, pii_total=pii_total)


# ── Assessment trace — written when the user runs Assess (NOT during the scan) ──
def open_assess_trace(scan_id: str, level: str, n_files: int, user: str | None = None):
    """A SEPARATE Langfuse trace for the WCAG rule assessment. The scan trace covers
    discovery + deep-scan (PII); the per-rule ✓/✗ assessment lives here, emitted only
    when the user explicitly runs Assess."""
    lf = _lf()
    if lf is None:
        return _Noop()
    return lf.trace(
        id=f"{scan_id}-assess",
        name=f"{user or 'demo'} · Assess · WCAG 2.1 {level} · {n_files} document{'s' if n_files != 1 else ''}",
        user_id=user or "demo",
        tags=["accessibility-assessment", f"level:{level}", f"user:{user or 'demo'}"],
        metadata={"scan_id": scan_id, "level": level, "documents": n_files},
    )


def finish_assess_trace(trace, summary: dict, *, scan_id: str | None = None,
                        score: float | None = None) -> None:
    """Close the Assess trace with the conformance summary + the compliance score
    (the score lives here, not on the Scan trace)."""
    if isinstance(trace, _Noop):
        return
    trace.update(output=summary)
    lf = _lf()
    if lf and scan_id and score is not None:
        try:
            lf.score(trace_id=f"{scan_id}-assess", name="compliance_score",
                     value=float(score),
                     comment=f"WCAG 2.1 {summary.get('level', 'AA')} · "
                             f"{score}% of documents conformant")
        except Exception:
            pass


def flush():
    """Flush pending events — call at the end of each scan. Guarded: flush() runs before
    the fan-out progress counter advances (handlers.py), so a raising Langfuse flush must
    never fail or stall a scan/remediation job."""
    try:
        lf = _lf()
        if lf:
            lf.flush()
    except Exception:
        pass


_PROJECT_ID_CACHE: str | None = None


def _project_id() -> str:
    """Project id used in Langfuse deep-link URLs. Langfuse routes /project/<id>/... by
    the project's opaque id, NOT its human name, so a hardcoded slug ('acp-compliance')
    can 404 even when trace_exists() (which authenticates by API key) says the trace is
    there. Resolve the real id once from the project the key belongs to and cache it;
    an explicit LANGFUSE_DEFAULT_PROJECT_ID env wins, and the legacy literal is the
    last-resort fallback so a lookup failure never regresses below today's behaviour."""
    global _PROJECT_ID_CACHE
    if _PROJECT_ID_CACHE:
        return _PROJECT_ID_CACHE
    env = os.environ.get("LANGFUSE_DEFAULT_PROJECT_ID")
    if env:
        _PROJECT_ID_CACHE = env
        return env
    if _ENABLED:
        try:
            import base64
            import httpx
            auth = base64.b64encode(f"{_PK}:{_SK}".encode()).decode()
            r = httpx.get(f"{_HOST.rstrip('/')}/api/public/projects",
                          headers={"Authorization": f"Basic {auth}"}, timeout=5)
            r.raise_for_status()
            data = r.json().get("data") or []
            pid = (data[0] or {}).get("id") if data else None
            if pid:
                _PROJECT_ID_CACHE = pid
                return pid
        except Exception:
            pass
    return "acp-compliance"


def generation(trace, name: str, *, model: str | None = None, prompt_chars: int = 0,
               completion_chars: int = 0, prompt_tokens: int | None = None,
               completion_tokens: int | None = None, cost: float = 0.0,
               provider: str | None = None, zone: str | None = None,
               latency_ms: int | None = None, ok: bool = True, surface: str | None = None):
    """A Langfuse GENERATION (not a span) for one model call, hung on `trace`.

    A generation is what carries the LLM-native fields Langfuse understands — model, token
    usage and cost — so they land in the token/cost rollups a span cannot feed. Mirrors the
    span helpers: no-op when tracing is disabled or `trace` is a _Noop, and every Langfuse
    call is wrapped so a SDK surprise never breaks the AI call it is observing.

    PHI (docs/audit-langfuse-phi.md): everything here is non-content metadata — model id,
    provider, zone, latency, ok, token COUNTS, cost, and the CHAR COUNTS of prompt/completion.
    The prompt and completion TEXT are never passed in and never sent, exactly as the span
    form did; `name`/`surface` are the call kind ('vision', 'explain'), not a filename."""
    if trace is None or isinstance(trace, _Noop):
        return _Noop()
    # Langfuse v2 usage model — token counts + a real measured cost (0 for local Ollama; a
    # cloud adapter's per-call cost otherwise, never a fabricated one). Keys omitted when the
    # provider did not report them, so an absent count reads as "unknown", not "zero".
    usage: dict = {"unit": "TOKENS"}
    if prompt_tokens is not None:
        usage["input"] = prompt_tokens
    if completion_tokens is not None:
        usage["output"] = completion_tokens
    if prompt_tokens is not None and completion_tokens is not None:
        usage["total"] = prompt_tokens + completion_tokens
    if cost:
        usage["total_cost"] = cost
    try:
        g = trace.generation(
            name=name,
            model=model,
            input={"prompt_chars": prompt_chars, "model": model},
            output={"completion_chars": completion_chars, "latency_ms": latency_ms, "ok": ok},
            usage=usage,
            metadata={"provider": provider, "zone": zone, "cost_usd": cost,
                      "surface": surface or name, "prompt_tokens": prompt_tokens,
                      "completion_tokens": completion_tokens, "ok": ok},
        )
        g.end()
        return g
    except Exception:
        return _Noop()


def trace_ai_call(surface: str, model: str, latency_ms: int, *, ok: bool,
                  prompt_chars: int = 0, completion: str | None = None,
                  scan_id: str | None = None, file: str | None = None,
                  provider: str = "ollama", zone: str | None = None, cost: float = 0.0,
                  prompt_tokens: int | None = None,
                  completion_tokens: int | None = None) -> None:
    """Trace one model call as a Langfuse GENERATION. Captures model, latency, prompt size,
    completion SIZE, token usage, provider/zone and cost — the LLM-observability the audit
    found missing (it was recorded as a plain span, so token usage and cost never reached
    Langfuse). No-op when tracing is disabled.

    NESTING (G2). When scan_id + file are known this generation is hung on the file's OWN
    trace (`_trace_id(scan_id, file)`) — the same trace that carries that document's
    Discover/Assess/Remediate/HITL — so a file's model calls are visible in its story rather
    than in a detached top-level trace. When they are not (a request-path call with no file,
    e.g. the changelog digest), it falls back to a per-call `ai:{surface}` trace. Either way
    the call is grouped into the scan's Langfuse SESSION via session_id=scan_id, so the
    session view still gathers every one of a scan's AI calls.

    PROVIDER / ZONE / COST (G3). `ai._trace_ai` already knows which provider served the call,
    in which zone, at what cost (ADR 0019) and writes them to the ai_calls table; they now
    ride the generation too, so the trace and the provenance ledger agree.

    THE COMPLETION IS SENT AS A LENGTH, NOT AS TEXT (docs/audit-langfuse-phi.md). The
    completion is model output derived from the document — alt text, rewrites, extracted
    values — so for a PHI customer it is document content by another name and must not be
    retained in a trace. This mirrors what the module already does one axis over: the prompt
    is `prompt_chars`, a count, never the prompt, and `trace_hitl_decision` sends the
    reviewer note the same way."""
    lf = _lf()
    if lf is None:
        return
    try:
        tid = _trace_id(scan_id, file)
        if tid:
            t = lf.trace(id=tid, session_id=scan_id,
                         metadata={"file": _doc_label(file), "surface": surface})
        else:
            t = lf.trace(name=f"ai:{surface}", session_id=scan_id,
                         metadata={"file": _doc_label(file), "model": model, "surface": surface})
        generation(t, surface, model=model, prompt_chars=prompt_chars,
                   completion_chars=len(completion or ""),
                   prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                   cost=cost, provider=provider, zone=zone, latency_ms=latency_ms, ok=ok,
                   surface=surface)
    except Exception:
        pass


def trace_hitl_decision(scan_id, file, rule_id, status, *, note=None, approved_value=None) -> None:
    """Trace a human-in-the-loop review decision (approve/reject/skip) as a span on the
    file's scan trace — the audit found HITL decisions had zero Langfuse coverage. Reuses
    the file's trace id so the human decision sits alongside that document's AI/scan spans.
    No-op when tracing is disabled.

    THE REVIEWER'S NOTE IS SENT AS A LENGTH, NOT AS TEXT (docs/audit-langfuse-phi.md). It was
    the only field here with no bound and no schema: free text typed by a human who is looking
    at a patient document, which makes it the field most likely to contain a patient.

    Truncating it — the obvious reading of "bound the note", and what the neighbouring
    `approved_value` does — would have been theatre. PHI in a note is at the FRONT of it:
    "Patient John Smith MRN 0114233 disputes…" is forty-odd characters, so any cap that leaves
    the note readable leaves the identifier intact. A cap bounds volume, and volume was never
    the risk.

    Nothing is lost by sending the length instead. The note is already persisted in
    `hitl_queue.reviewer_note` (store.py), the span still carries scan_id/file/rule_id/status,
    and per routes/hitl.py the weak-rule rollup reads the structured `resolution` field rather
    than this free text. So the trace keeps every question it could previously answer, minus
    one it should never have been asked.

    This mirrors what the module already does for prompts one function up — `prompt_chars`, a
    count, never the prompt — which is the precedent rather than an invention: the two fields
    are the same class of thing, and only one of them had been treated that way.
    """
    lf = _lf()
    if lf is None:
        return
    try:
        tid = _trace_id(scan_id, file)
        t = lf.trace(id=tid, name="hitl:decision", session_id=scan_id,
                     metadata={"file": _doc_label(file), "rule_id": rule_id})
        s = t.span(name=f"hitl.{status}",
                   input={"rule_id": rule_id},
                   output={"status": status, "note_chars": len(note or ""),
                           "approved_value": (approved_value or "")[:500]})
        s.end()
    except Exception:
        pass


def trace_deep_link(trace_id: str) -> str | None:
    """Public Langfuse URL for a trace — the same shape /config exposes to the SPA.
    Returns None when tracing isn't configured (no LANGFUSE_HOST)."""
    if not _HOST:
        return None
    return f"{_HOST.rstrip('/')}/project/{_project_id()}/traces/{trace_id}"


def session_deep_link(scan_id: str) -> str | None:
    """Public Langfuse URL for a scan's SESSION — groups every one of that scan's
    per-file traces (see file_trace below). Unlike trace_deep_link, no 'exists' check is
    needed: an empty/not-yet-ingested session renders as 'no traces yet' in Langfuse, not
    a 404, so this is safe to link to immediately."""
    if not _HOST:
        return None
    return f"{_HOST.rstrip('/')}/project/{_project_id()}/sessions/{scan_id}"


# ── Per-file trace (file-centric tracing) ──────────────────────────────────────
# One trace PER FILE per scan, id=_trace_id(scan_id, file), grouped into a Langfuse SESSION
# keyed by scan_id (session_deep_link above) so "view this whole scan" = browse its
# session instead of one giant trace. Discover / Assess / Remediate are SPANS within that
# one file trace, written as each phase happens — potentially far apart in time (Discover
# at scan time; Assess only if/when the user clicks Assess; Remediate only for files
# actually fixed). Langfuse upserts a trace by id, so re-opening it for a later phase
# updates the SAME trace rather than creating a new one.
#
# Defensively wrapped (unlike the legacy scan/assess/remediate-trace functions above,
# kept only for historical scans created before this model) — a Langfuse SDK surprise
# here must never break the actual scan/assess/remediate pipeline, only lose tracing for
# that call.
def file_trace(scan_id: str, file: str, user: str | None = None):
    """Open or update the per-file trace. Call this at the start of EACH phase
    (Discover/Assess/Remediate) for that file — safe to call repeatedly."""
    lf = _lf()
    if lf is None:
        return _Noop()
    try:
        who = user or "demo"
        return lf.trace(
            id=_trace_id(scan_id, file),
            session_id=scan_id,
            name=f"{who} · {_doc_label(file)}",
            user_id=who,
            tags=_file_tags(file, who),
            metadata={"scan_id": scan_id, "file": _doc_label(file)},
        )
    except Exception:
        return _Noop()


def discover_span(trace, engine: str):
    """The Discover phase span on a file's trace. Deterministic id (_det_id) —
    a worker retry re-emits the same span instead of adding a sibling."""
    if isinstance(trace, _Noop):
        return _Noop()
    try:
        return trace.span(id=_det_id(trace.id, "discover"),
                          name="Discover", input={"checked_with": engine})
    except Exception:
        return _Noop()


def assess_span(trace, level: str):
    """The Assess phase span on a file's trace — rule_spans (above) attach as its
    children, exactly as they did on the old per-document span. Deterministic id
    per (trace, level): re-running Assess (another click, a worker retry, the
    trace-chip rebuild) upserts THIS span rather than appending an identical
    sibling; assessing at a different WCAG level still gets its own span."""
    if isinstance(trace, _Noop):
        return _Noop()
    try:
        return trace.span(id=_det_id(trace.id, "assess", level),
                          name=f"Assess · WCAG 2.1 {level}")
    except Exception:
        return _Noop()


def remediate_span(trace, drive_write_url: str | None, *, fixes_applied: int | None = None,
                   fixes_skipped: int | None = None, per_rule: dict | None = None):
    """The Remediate phase span on a file's trace.

    Now carries the outcome of the fix pass, not just where the corrected copy was written:
    how many fixes were APPLIED and how many were SKIPPED (deferred to review / out of scope),
    optionally broken out per WCAG criterion. Before this the span said a file was remediated
    but never what changed, so a reader could not tell a heavy fix from a no-op.

    PHI (docs/audit-langfuse-phi.md): COUNTS ONLY. The applied/skipped messages `_remediate_file`
    produces are prose ("3 images: added alt text") and are deliberately NOT sent — only their
    tallies — so no filename, no reviewer text and no document content rides on this span. Keys
    are omitted when the caller doesn't know them (the manual-upload / mark-remediated routes),
    so their absence reads as "not reported", not "zero fixes"."""
    if isinstance(trace, _Noop):
        return
    try:
        out: dict = {"drive_write_url": drive_write_url,
                     "written_to_drive": drive_write_url is not None}
        if fixes_applied is not None:
            out["fixes_applied"] = fixes_applied
        if fixes_skipped is not None:
            out["fixes_skipped"] = fixes_skipped
        if per_rule:
            out["fixes_by_rule"] = per_rule
        s = trace.span(name="Remediate", output=out)
        s.end()
    except Exception:
        pass



# ── Discover-phase tracing (ADR 0020) ─────────────────────────────────────────
#
# THE GAP THIS CLOSES. `discover_span` above hangs a "Discover" span on a file's trace, and it
# reads like the Discover phase is traced. It is not. Its only caller is
# `handlers._analyse_and_persist_one`, which runs on the ANALYSE path — and under ADR 0020 that
# path runs at ASSESS time, not at discovery. `_scan_discover`, the handler that lists the source,
# persists `scan_inventory`, evaluates the lifecycle rules and stops, emitted nothing at all.
#
# So a Discover-only run produced NO trace: not an empty one, not a thin one — nothing to open.
# What was labelled "Discover" was the discover portion of opening a file, which happens later and
# only for the assessable subset. The estate rows Discover inventories and never opens were
# invisible in Langfuse by construction.
#
# Two observations close it, and they answer different questions:
#
#   `discover_run_trace`  — what this RUN did: how many files it listed and inventoried, the
#                           boundary it listed within, whether it hit its cap. One trace per run,
#                           cheap, always emitted. This is the one that makes a discovery visible
#                           at all, and the counts carry their boundary with them for the same
#                           reason scanScope.js insists on it in the UI.
#
#   `discover_file_spans` — per-file Discover spans, so a document's trace shows Discover →
#                           Assess → Remediate rather than starting mid-story. Emitted from the
#                           inventory, so a file that is inventoried and never assessed still has
#                           a trace.
#
# WHY THE PER-FILE HALF IS CAPPED. A hospital estate is tens of thousands of files and Discover
# lists all of them by design; emitting a trace + span each would make tracing the most expensive
# part of a phase that opens no files. The cap is stated, not silent: the run trace carries
# `file_spans_emitted` alongside `files_inventoried`, so a reader can see the difference rather
# than conclude the estate is smaller than it is. ACP_TRACE_DISCOVER_FILES raises or disables it.
def _discover_file_cap() -> int:
    raw = os.environ.get("ACP_TRACE_DISCOVER_FILES", "").strip()
    if not raw:
        return 500
    try:
        return max(0, int(raw))
    except ValueError:
        return 500


def discover_run_trace(scan_id: str, source: str, *, listed: int, inventoried: int,
                       scope: dict | None = None, user: str | None = None,
                       file_spans_emitted: int | None = None, deferred: bool = True):
    """One trace for the discovery run itself. Safe to call repeatedly — the id is deterministic,
    so a worker retry updates the same trace instead of adding a sibling."""
    lf = _lf()
    if lf is None:
        return _Noop()
    sc = scope or {}
    who = user or "demo"
    label = _SOURCE_LABEL.get(source, source)
    # The boundary, carried WITH the count. "12,486 files" and "12,486 files in /Finance" are
    # different facts, and a trace that records only the first cannot tell them apart later.
    boundary = {"kind": sc.get("kind"), "folder": sc.get("folder"), "site": sc.get("site"),
                "truncated": bool(sc.get("truncated"))}
    try:
        trace = lf.trace(
            id=_det_id(scan_id, "discover-run"),
            session_id=scan_id,
            name=f"{who} · Discover · {label}",
            user_id=who,
            tags=["accessibility-discover", f"user:{who}", f"source:{source}"],
            metadata={"scan_id": scan_id, "source": source, "phase": "discover",
                      "deferred_assess": deferred},
            input=boundary,
            output={"files_listed": listed, "files_inventoried": inventoried,
                    "file_spans_emitted": file_spans_emitted,
                    "truncated": boundary["truncated"]},
        )
        return trace
    except Exception:
        return _Noop()


def discover_file_spans(scan_id: str, items, user: str | None = None) -> int:
    """A Discover span on each inventoried file's own trace. Returns how many were emitted, which
    the caller records on the run trace — a cap nobody can see is indistinguishable from a small
    estate.

    `items` are inventory dicts (file / doc_class / size_kb). No file is opened here, so the span
    records what LISTING knew: the classification taken from metadata, and the size.
    """
    lf = _lf()
    if lf is None:
        return 0
    cap = _discover_file_cap()
    if cap == 0:
        return 0
    n = 0
    for it in items:
        if n >= cap:
            break
        name = it.get("file")
        if not name:
            continue
        try:
            trace = file_trace(scan_id, name, user=user)
            if isinstance(trace, _Noop):
                continue
            span = trace.span(
                id=_det_id(_trace_id(scan_id, name), "discover-listed"),
                name="Discover",
                input={"listed_from": "source metadata", "opened": False},
                output={"doc_class": it.get("doc_class"), "size_kb": it.get("size_kb")},
            )
            span.end()
            n += 1
        except Exception:
            # One file's tracing must never stop the inventory being written.
            continue
    return n

def file_score(scan_id: str, file: str, score: float | None) -> None:
    """Attach this file's own compliance score to its trace — replaces the old scan-wide
    aggregate score (finish_assess_trace's lf.score call), which has no natural home once
    there's no single Assess trace; a per-file score is arguably more useful anyway."""
    if score is None:
        return
    lf = _lf()
    if lf is None:
        return
    try:
        # Deterministic score id — a re-assess updates the one score instead of
        # growing the trace's score list ("85.00, 85.00, 85.00, …").
        lf.score(id=_det_id(scan_id, file, "compliance_score"),
                 trace_id=_trace_id(scan_id, file), name="compliance_score", value=float(score))
    except Exception:
        pass


def session_exists(scan_id: str) -> bool:
    """Best-effort: does a Langfuse session with this scan_id exist?
    Older scans (before file-centric tracing) have no session — this lets the UI grey them out."""
    if not _ENABLED:
        return False
    try:
        import httpx
        r = httpx.get(f"{_HOST.rstrip('/')}/api/public/sessions/{scan_id}",
                      auth=(_PK, _SK), timeout=4.0)
        return r.status_code == 200
    except Exception:
        return False


def trace_exists(trace_id: str) -> bool:
    """Best-effort: is this trace queryable in Langfuse yet? Ingestion is async after
    flush(), so the detail view can 404 for a beat. Polls the public API; any error
    (not-configured, network, not-yet-ingested) → False."""
    if not _ENABLED:
        return False
    try:
        import httpx
        r = httpx.get(f"{_HOST.rstrip('/')}/api/public/traces/{trace_id}",
                      auth=(_PK, _SK), timeout=4.0)
        return r.status_code == 200
    except Exception:
        return False
