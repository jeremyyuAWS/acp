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


def _file_tags(file: str, user: str | None) -> list[str]:
    """Base tag set for a file's trace — shared so a later tag-only update (e.g.
    appending rule-fail tags after Assess) doesn't clobber the tags file_trace set."""
    return ["accessibility-file", f"user:{user or 'demo'}", f"file:{file}"]


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
        name=filename,
        input={"document": filename, "checked_with": engine},
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
    if scan_id and filename and failing_ids:
        lf = _lf()
        if lf:
            try:
                lf.trace(id=f"{scan_id}::{filename}").update(
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
    """Flush pending events — call at the end of each scan."""
    lf = _lf()
    if lf:
        lf.flush()


def trace_deep_link(trace_id: str) -> str | None:
    """Public Langfuse URL for a trace — the same shape /config exposes to the SPA.
    Returns None when tracing isn't configured (no LANGFUSE_HOST)."""
    if not _HOST:
        return None
    project = os.environ.get("LANGFUSE_DEFAULT_PROJECT_ID", "acp-compliance")
    return f"{_HOST.rstrip('/')}/project/{project}/traces/{trace_id}"


def session_deep_link(scan_id: str) -> str | None:
    """Public Langfuse URL for a scan's SESSION — groups every one of that scan's
    per-file traces (see file_trace below). Unlike trace_deep_link, no 'exists' check is
    needed: an empty/not-yet-ingested session renders as 'no traces yet' in Langfuse, not
    a 404, so this is safe to link to immediately."""
    if not _HOST:
        return None
    project = os.environ.get("LANGFUSE_DEFAULT_PROJECT_ID", "acp-compliance")
    return f"{_HOST.rstrip('/')}/project/{project}/sessions/{scan_id}"


# ── Per-file trace (file-centric tracing) ──────────────────────────────────────
# One trace PER FILE per scan, id=f"{scan_id}::{file}", grouped into a Langfuse SESSION
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
            id=f"{scan_id}::{file}",
            session_id=scan_id,
            name=f"{who} · {file}",
            user_id=who,
            tags=_file_tags(file, who),
            metadata={"scan_id": scan_id, "file": file},
        )
    except Exception:
        return _Noop()


def discover_span(trace, engine: str):
    """The Discover phase span on a file's trace."""
    if isinstance(trace, _Noop):
        return _Noop()
    try:
        return trace.span(name="Discover", input={"checked_with": engine})
    except Exception:
        return _Noop()


def assess_span(trace, level: str):
    """The Assess phase span on a file's trace — rule_spans (above) attach as its
    children, exactly as they did on the old per-document span."""
    if isinstance(trace, _Noop):
        return _Noop()
    try:
        return trace.span(name=f"Assess · WCAG 2.1 {level}")
    except Exception:
        return _Noop()


def remediate_span(trace, drive_write_url: str | None):
    """The Remediate phase span on a file's trace."""
    if isinstance(trace, _Noop):
        return
    try:
        s = trace.span(name="Remediate",
                       output={"drive_write_url": drive_write_url,
                               "written_to_drive": drive_write_url is not None})
        s.end()
    except Exception:
        pass


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
        lf.score(trace_id=f"{scan_id}::{file}", name="compliance_score", value=float(score))
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
