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


def scan_trace(scan_id: str, source: str, n_files: int, ai_enabled: bool = True):
    """Create a Langfuse trace for one scan run, with a human-readable name."""
    lf = _lf()
    if lf is None:
        return _Noop()
    src = _SOURCE_LABEL.get(source, source)
    mode = "AI-assisted" if ai_enabled else "Deterministic (no AI)"
    name = f"Accessibility scan · {n_files} document{'s' if n_files != 1 else ''} · {src}"
    return lf.trace(
        id=scan_id,
        name=name,
        metadata={
            "what": f"Checked {n_files} documents against WCAG 2.1 accessibility rules",
            "source": src,
            "documents": n_files,
            "mode": mode,
            "ai_enabled": ai_enabled,
        },
        tags=["accessibility-scan", f"source:{source}", "ai-assisted" if ai_enabled else "deterministic"],
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
               severity_map: dict[str, str] | None = None):
    """One child span per WCAG rule for a document, in plain language.

    Pass → "✓ Non-text Content".  Fail → "✗ Non-text Content — 3 issues",
    flagged WARNING (or ERROR for critical) so it's visibly highlighted.
    """
    if isinstance(file_span_, _Noop):
        return
    for rule in rule_catalog:
        rid = rule["id"]
        count = sc_counts.get(rid, 0)
        outcome = "FAIL" if count > 0 else "PASS"
        severity = (severity_map or {}).get(rid, rule.get("severity", ""))
        plain = rule.get("name", rid)
        if outcome == "FAIL":
            label = f"✗ {plain} — {count} issue{'s' if count != 1 else ''}"
            status = f"{count} document issue{'s' if count != 1 else ''} ({(severity or 'finding').lower()})"
        else:
            label = f"✓ {plain}"
            status = "No issues"
        s = file_span_.span(
            name=label,
            level=_level_for(outcome, severity),
            status_message=status,
            metadata={
                "wcag": f"{rid} {plain}",
                "wcag_level": rule.get("level"),
                "severity": severity,
                "how_its_fixed": rule.get("fix_mode"),
            },
        )
        s.end(output={"result": status, "outcome": outcome, "issues": count})


def pii_span(file_span_, pinfo: dict):
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
        parts.append(f"{n} {noun if n != 1 else noun.rstrip('s')}")
    summary = ", ".join(parts)
    level = "ERROR" if pinfo.get("severity") == "critical" else "WARNING"
    s = file_span_.span(
        name=f"🔒 Sensitive data — {summary}",
        level=level,
        status_message=f"This document exposes {pinfo.get('total', 0)} sensitive item(s)",
        metadata={"sensitive_data_types": pinfo.get("types", {})},
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


def flush():
    """Flush pending events — call at the end of each scan."""
    lf = _lf()
    if lf:
        lf.flush()
