# ADR 0005 — Server-side Remediation Engine

**Status:** ACCEPTED
**Date:** 2026-06-25
**Authors:** ACP team

---

## Context

Remediation today runs **in the browser**: `frontend/src/rules/*.js` `fix(doc)`
functions mutate the DOM client-side (`remediateHtml`), and write-back goes through
`POST /drive/upload`. The Office/PDF *remediators* (DigitalA11y) are not wired into
the backend at all.

That blocks the things ADR 0004 set up:

- A durable **`remediate_file` job** (async, retryable, observable) has nothing to
  call — there is no server-side "apply the fixes to file X".
- **Phased remediation at scale** (PRD #4) can't run fixes on the server.
- Remediation isn't traceable in Langfuse the way scanning is.

So we need a server-side remediation engine.

## Decision

Add a backend remediation module (`api/remediate.py`) that mirrors the frontend
rule contract — **one deterministic fixer per WCAG SC** — operating on the parsed
document. Start with the **HTML engine** (fully in-repo, `lxml`-based, already a
dependency); Office/PDF remediation wraps the vendored DigitalA11y remediator and
is deferred.

### Contract

```python
# api/remediate.py
FIXERS: dict[str, Fixer]          # wcag_sc -> fixer

def remediate_html(html: str, *, ai_enabled: bool) -> tuple[str, list[str], list[str]]:
    """Returns (fixed_html, applied_changes, deferred_rule_ids).
    Applies every 'auto' fixer deterministically. 'ai-assisted'/'human-only'
    findings are NOT auto-fixed — their rule_ids are returned as 'deferred' so the
    caller routes them to the HITL queue (consistent with the AI toggle / ADR 0002)."""
```

Each fixer is a small function `fix(tree) -> list[str]` returning human-readable
change descriptions (same shape as the frontend `fix()` returns).

### Apply policy (matches the existing AI semantics)

| fix_mode | server-side behavior |
|----------|----------------------|
| `auto` | applied deterministically, always |
| `ai-assisted` | **not** auto-applied → deferred to HITL (AI may *draft* later; a human approves) |
| `human-only` | never auto-applied → deferred to HITL |

This is the same rule the frontend orchestrator and deterministic-only mode already
use, so server and client behave identically.

### Integration (ADR 0004)

A `remediate_file` job: fetch the file → `remediate_html(...)` → write the fixed
copy back to Drive (`Remediated/`) → `record_remediation` + a Langfuse span →
queue the deferred rules to HITL. One job per in-scope file; the queue gives
durability, retries, and Grafana/Langfuse visibility.

### Parity

The backend fixers port the **same WCAG logic** as `frontend/src/rules/`. Until a
shared source exists, the two must be kept in sync; each backend fixer cites the
frontend module it mirrors, and both are covered by tests against the same corpus.
Unifying them (one rule definition, two runtimes) is a future improvement noted in
[the rules index](../../rules/README.md).

## Consequences

**Gains**
- HTML remediation becomes server-side → durable, async (`remediate_file` jobs),
  batchable, and Langfuse-traceable, exactly like scanning.
- Deterministic-only mode now covers *remediation* too: with AI off, only `auto`
  fixes apply and everything else routes to a human — server-enforced.

**Costs / limits**
- **Office/PDF remediation is not in-repo** — it needs the DigitalA11y remediator
  (a vendored .NET engine). Wiring it is a separate, larger step (mirrors the
  scan-engine boundary in [ADR 0001](0001-read-only-assessment-spine-on-mdk.md)).
  Until then, Office/PDF findings route to HITL rather than auto-fix.
- **Two implementations of HTML rules** (JS + Python) is duplication; mitigated by
  shared tests + the parity rule above, but a real risk to watch.

## Implementation order

1. **HTML remediation module** + the deterministic `auto` fixers (`3.1.1` lang,
   `2.4.2` title, `1.3.1` form labels first) + tests. ← this ADR's first slice
2. `remediate_file` job handler + enqueue endpoint (write-back + span + HITL
   routing of deferred rules).
3. Port the remaining HTML `auto` fixers from `frontend/src/rules/`.
4. Office/PDF remediation via the DigitalA11y remediator (separate effort).
