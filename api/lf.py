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
               user: str | None = None):
    """Create a Langfuse trace for one scan run, with a human-readable name.

    user — the signed-in person's email (GIS). Sets the Langfuse trace user_id so
    traces group by who ran the scan; falls back to 'demo' for the keyless demo."""
    lf = _lf()
    if lf is None:
        return _Noop()
    src = _SOURCE_LABEL.get(source, source)
    mode = "AI-assisted" if ai_enabled else "Deterministic (no AI)"
    who = user or "demo"
    # Lead the name with who ran it so the trace LIST segregates by user at a glance,
    # in addition to user_id (which powers Langfuse's Users view) and a user: tag.
    name = f"{who} · Step 1–2 · Discover + Deep scan · {n_files} document{'s' if n_files != 1 else ''} · {src}"
    return lf.trace(
        id=scan_id,
        name=name,
        user_id=who,
        metadata={
            "what": f"Discovered + deep-scanned (PII) {n_files} documents",
            "workflow_step": "1-2 · Discover + Deep scan",
            "source": src,
            "documents": n_files,
            "mode": mode,
            "ai_enabled": ai_enabled,
            "run_by": who,
        },
        tags=["accessibility-scan", "step:1-2", f"source:{source}", f"user:{who}",
              "ai-assisted" if ai_enabled else "deterministic"],
    )


def file_span(trace, filename: str, engine: str):
    """A child span for one document. The name is just the filename (readable)."""
    if isinstance(trace, _Noop):
        return _Noop()
    return trace.span(
        name=filename,
        input={"document": filename, "checked_with": engine},
    )


# Map our severities to a Langfuse observation level so failures stand out (color).
def _level_for(outcome: str, severity: str) -> str:
    if outcome != "FAIL":
        return "DEFAULT"
    return "ERROR" if (severity or "").upper() == "CRITICAL" else "WARNING"


def rule_spans(file_span_, sc_counts: dict[str, int], rule_catalog: list[dict],
               severity_map: dict[str, str] | None = None, filename: str | None = None):
    """One child span per WCAG rule for a document, in plain language.

    Pass → "✓ Non-text Content (1.1.1)".  Fail → "✗ Non-text Content (1.1.1) —
    3 issues", flagged WARNING (or ERROR for critical) so it's visibly highlighted.
    The document name rides on every span (name + input) so an individual rule span
    is associable with its file even outside the trace tree.
    """
    if isinstance(file_span_, _Noop):
        return
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
        else:
            label = f"✓ {plain} ({rid})"
            status = "No issues"
        s = file_span_.span(
            name=label,
            level=_level_for(outcome, severity),
            status_message=status,
            input={"document": filename, "rule": f"{rid} {plain}"} if filename else None,
            metadata={
                "document": filename,
                "wcag": f"{rid} {plain}",
                "wcag_level": rule.get("level"),
                "severity": severity,
                "how_its_fixed": rule.get("fix_mode"),
            },
        )
        s.end(output={"document": filename, "result": status, "outcome": outcome, "issues": count})


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
        name=f"🔒 Sensitive data — {summary}",
        level=level,
        status_message=f"This document exposes {pinfo.get('total', 0)} sensitive item(s)",
        input={"document": filename} if filename else None,
        metadata={"document": filename, "sensitive_data_types": pinfo.get("types", {})},
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
    cert = summary.get("certifiable", 0)
    uncertain = summary.get("uncertain", 0)
    err = summary.get("error", 0)
    avg = summary.get("avg_score")
    need_work = max(files - cert - uncertain - err, 0)
    src = _SOURCE_LABEL.get(source, source)
    sentence = (f"Scanned {files} documents from {src}. "
                f"{cert} ready to certify, {need_work} need fixing"
                + (f", {err} could not be opened" if err else "")
                + (f". Average score {avg}/100." if avg is not None else "."))
    if pii_docs:
        sentence += (f" ⚠ {pii_docs} document{'s' if pii_docs != 1 else ''} "
                     f"contain sensitive data ({pii_total} item{'s' if pii_total != 1 else ''}).")
    trace.update(output={
        "summary": sentence,
        "documents_scanned": files,
        "ready_to_certify": cert,
        "need_fixing": need_work,
        "uncertain": uncertain,
        "could_not_open": err,
        "average_score": avg,
        "documents_with_sensitive_data": pii_docs,
        "sensitive_items_found": pii_total,
        "mode": "AI-assisted" if ai_enabled else "Deterministic (no AI)",
    })
    lf = _lf()
    if lf and avg is not None:
        try:
            lf.score(trace_id=scan_id, name="compliance_score", value=float(avg),
                     comment=sentence)
        except Exception:
            pass


# ── Fan-out helpers: spans/finish referencing a trace by id (ADR 0007) ─────────
def file_span_for(scan_id: str, filename: str, engine: str):
    """A file span on an EXISTING trace, addressed by id — for the fan-out path
    where each file is processed in its own job (no shared in-process handle)."""
    lf = _lf()
    if lf is None:
        return _Noop()
    return lf.trace(id=scan_id).span(name=filename,
                                     input={"document": filename, "checked_with": engine})


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
        name=f"{user or 'demo'} · Step 4 · Assess · WCAG 2.1 {level} · {n_files} document{'s' if n_files != 1 else ''}",
        user_id=user or "demo",
        tags=["accessibility-assessment", "step:4", f"level:{level}", f"user:{user or 'demo'}"],
        metadata={"scan_id": scan_id, "workflow_step": "4 · Assess", "level": level, "documents": n_files},
    )


def finish_assess_trace(trace, summary: dict) -> None:
    if isinstance(trace, _Noop):
        return
    trace.update(output=summary)


def flush():
    """Flush pending events — call at the end of each scan."""
    lf = _lf()
    if lf:
        lf.flush()
