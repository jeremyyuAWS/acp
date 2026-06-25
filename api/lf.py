"""Langfuse observability wrapper for the ACP scan engine.

Emits one trace per scan, one span per file, one child span per WCAG rule check.
All methods are no-ops when LANGFUSE_SECRET_KEY is absent — safe to import
everywhere without requiring the package in environments without credentials.

Env vars:
  LANGFUSE_HOST        https://langfuse.example.com  (required to activate)
  LANGFUSE_PUBLIC_KEY  pk-lf-...                     (required to activate)
  LANGFUSE_SECRET_KEY  sk-lf-...                     (required to activate)
"""
from __future__ import annotations
import os

_HOST = os.environ.get("LANGFUSE_HOST", "")
_PK   = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
_SK   = os.environ.get("LANGFUSE_SECRET_KEY", "")
_ENABLED = bool(_HOST and _PK and _SK)

_client = None


def _lf():
    global _client
    if not _ENABLED:
        return None
    if _client is None:
        from langfuse import Langfuse  # lazy — import only when creds present
        _client = Langfuse(public_key=_PK, secret_key=_SK, host=_HOST)
    return _client


class _Noop:
    """Stand-in for Langfuse trace/span when observability is off."""
    def span(self, **_): return self
    def update(self, **_): return self
    def end(self, **_): return self
    def flush(self): pass


def scan_trace(scan_id: str, source: str, n_files: int):
    """Create a Langfuse trace for one scan run. Returns a trace handle."""
    lf = _lf()
    if lf is None:
        return _Noop()
    return lf.trace(
        id=scan_id,
        name="acp-scan",
        metadata={"source": source, "n_files": n_files},
    )


def file_span(trace, filename: str, engine: str):
    """Create a child span for a single file being analysed."""
    if isinstance(trace, _Noop):
        return _Noop()
    return trace.span(name=f"file:{filename}", input={"engine": engine})


def rule_spans(file_span_, sc_counts: dict[str, int], rule_catalog: list[dict]):
    """Emit one child span per WCAG rule for a file. sc_counts: {sc_id: finding_count}."""
    if isinstance(file_span_, _Noop):
        return
    for rule in rule_catalog:
        rid = rule["id"]
        count = sc_counts.get(rid, 0)
        outcome = "FAIL" if count > 0 else "PASS"
        s = file_span_.span(
            name=f"rule:{rid}",
            metadata={"name": rule["name"], "level": rule["level"], "fix_mode": rule["fix_mode"]},
        )
        s.end(output={"outcome": outcome, "finding_count": count})


def flush():
    """Flush pending events — call at the end of each scan."""
    lf = _lf()
    if lf:
        lf.flush()
