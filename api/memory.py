"""Enterprise review memory (ADR 0021) — the read side.

`guidance_for` is the single seam a prose proposer opts into: given the org + rule + format,
it returns a compact "House style for this organization: …" block to prepend to the model
prompt, or "" when memory is off / empty. It NEVER changes model weights, only what we ask —
and the caller surfaces the applied guidance on the card (ADR 0021 §E), so the influence is
always visible.

Flag-gated by ACP_REVIEW_MEMORY (default OFF). Off, or with no active rules for the org, the
returned block is "" and the prompt is byte-for-byte what it was before this ADR — the
safe-dark property Rollout stage 1 depends on.
"""
from __future__ import annotations

import os


def enabled() -> bool:
    return os.environ.get("ACP_REVIEW_MEMORY", "").strip().lower() in ("1", "true", "yes", "on")


def guidance_for(store, org: str | None, rule_id: str | None, fmt: str | None) -> str:
    """The org's active house-style guidance for a (rule, format) draft, as a prompt block.
    Returns "" when the flag is off, there is no org, or the org has no applicable rules —
    so a proposer can always call this unconditionally and get today's behaviour when memory
    is not in use. Best-effort: any lookup failure degrades to "" (memory must never break a
    draft)."""
    if not enabled() or not org or store is None:
        return ""
    try:
        rules = store.memory_guidance(org, rule_id, fmt)
    except Exception:
        return ""
    if not rules:
        return ""
    lines = "\n".join(f"- {g}" for g in rules)
    return ("House style for this organization (follow these unless the content requires "
            f"otherwise):\n{lines}\n")


def applied_rule_count(store, org: str | None, rule_id: str | None, fmt: str | None) -> int:
    """How many active rules shaped a draft — for the card's 'house style applied' chip.
    0 when memory is off/empty. Best-effort."""
    if not enabled() or not org or store is None:
        return 0
    try:
        return len(store.memory_guidance(org, rule_id, fmt))
    except Exception:
        return 0


# ── Derivation (ADR 0021 stage 3 / §D) — behaviour → PROPOSED rules, human-gated ─
# A derived preference is NEVER auto-applied: this job only inserts status='proposed' rows an
# admin must accept. It requires a real min-evidence floor and windows on recent behaviour
# (recency), and every proposal carries the actual count that justifies it (ADR 0016 — a real
# number or it does not exist). The gate + floor + window are the anti-drift / anti-bias
# controls: one reviewer's idiosyncrasy can't become "the org standard" silently.
DERIVE_WINDOW_DAYS = 30
DERIVE_MIN_EVIDENCE = 5          # fewer decisions than this never becomes a proposal
_SHORTEN_MEDIAN_CHARS = 20       # median edit must shorten by at least this to read as "prefers short"


def _median(xs: list[int]) -> int:
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) // 2


def derive_org_memory(store, org: str, *, window_days: int = DERIVE_WINDOW_DAYS,
                      min_evidence: int = DERIVE_MIN_EVIDENCE, now=None) -> list[dict]:
    """Read an org's recent HITL decisions and PROPOSE (never activate) house-style rules the
    behaviour supports. Returns the candidate dicts it inserted (status='proposed'), each with
    real evidence. Idempotent-ish: skips a candidate when a non-archived derived rule for the
    same (rule, signal) already exists, so re-running doesn't spam duplicates. Best-effort."""
    from collections import defaultdict
    from datetime import datetime, timedelta, timezone
    if store is None or not org:
        return []
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=window_days)).isoformat()
    try:
        events = store.list_hitl_events_for_org(org, since_iso=since)
    except Exception:
        return []

    # Group signal per rule.
    shorten_deltas: dict[str, list[int]] = defaultdict(list)   # edits that changed length
    total_by_rule: dict[str, int] = defaultdict(int)
    vague_by_rule: dict[str, int] = defaultdict(int)
    for e in events:
        rid = e.get("rule_id") or ""
        if not rid:
            continue
        total_by_rule[rid] += 1
        if e.get("edited") and e.get("ai_value") and e.get("final_value"):
            shorten_deltas[rid].append(len(str(e["final_value"])) - len(str(e["ai_value"])))
        if e.get("reject_reason") == "too_vague":   # reject_reason is only set on rejections
            vague_by_rule[rid] += 1

    # Existing non-archived derived rules → dedup by (rule_id, signal tag embedded in guidance).
    try:
        existing = store.list_org_memory(org)
    except Exception:
        existing = []
    have = {(r.get("rule_id"), (r.get("guidance") or "")[:24])
            for r in existing if r.get("kind") == "derived" and r.get("status") != "archived"}

    import json
    proposed: list[dict] = []

    def _propose(rule_id, guidance, evidence):
        tag = (rule_id, guidance[:24])
        if tag in have:
            return
        have.add(tag)
        try:
            mid = store.add_org_memory(org, "derived", guidance, rule_id=rule_id,
                                       status="proposed", evidence=json.dumps(evidence),
                                       author="derivation")
            proposed.append({"id": mid, "rule_id": rule_id, "guidance": guidance,
                             "evidence": evidence})
        except Exception:
            pass

    for rid, deltas in shorten_deltas.items():
        if len(deltas) >= min_evidence:
            med = _median(deltas)
            if med <= -_SHORTEN_MEDIAN_CHARS:
                _propose(rid,
                         "Keep drafts concise — reviewers here shorten them.",
                         {"rule": rid, "edited": len(deltas), "of": total_by_rule[rid],
                          "median_delta_chars": med, "window_days": window_days})

    for rid, n in vague_by_rule.items():
        if n >= min_evidence:
            _propose(rid,
                     "Be specific and descriptive — name what the content actually shows.",
                     {"rule": rid, "rejected_too_vague": n, "of": total_by_rule[rid],
                      "window_days": window_days})

    return proposed
