"""Server-enforced stronger-model pilot for assisted remediation.

The allow-list is intentionally code-owned.  An admin may arm or stop the pilot, but cannot
turn an arbitrary criterion or file type into a cloud lane through a settings payload.
"""
from __future__ import annotations

import json

SETTING_KEY = "remediation_model_pilot"
MODEL = "claude-sonnet-5"
PROVIDER = "anthropic"
ZONE = "cloud"
ALLOWED_CATEGORIES = ("docx:2.4.4", "html:2.4.4")

DEFAULT_POLICY = {
    "enabled": False,
    "categories": list(ALLOWED_CATEGORIES),
    "max_calls": 100,
    "max_spend_usd": 5.0,
    "min_sample": 10,
    "max_failure_rate": 0.10,
    "min_acceptance_rate": 0.90,
    "max_edit_rate": 0.20,
    "min_validation_clear_rate": 0.95,
}


def normalize_policy(value: dict | None) -> dict:
    src = value or {}
    categories = [c for c in src.get("categories", ALLOWED_CATEGORIES)
                  if c in ALLOWED_CATEGORIES]
    return {
        "enabled": bool(src.get("enabled", False)),
        "categories": list(dict.fromkeys(categories)),
        "max_calls": max(1, min(1000, int(src.get("max_calls", 100)))),
        "max_spend_usd": max(0.01, min(1000.0, float(src.get("max_spend_usd", 5.0)))),
        "min_sample": max(1, min(1000, int(src.get("min_sample", 10)))),
        "max_failure_rate": max(0.0, min(1.0, float(src.get("max_failure_rate", .10)))),
        "min_acceptance_rate": max(0.0, min(1.0, float(src.get("min_acceptance_rate", .90)))),
        "max_edit_rate": max(0.0, min(1.0, float(src.get("max_edit_rate", .20)))),
        "min_validation_clear_rate": max(0.0, min(1.0, float(src.get("min_validation_clear_rate", .95)))),
    }


def load_policy(store) -> dict:
    try:
        return normalize_policy(json.loads(store.get_setting(SETTING_KEY, "") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return dict(DEFAULT_POLICY)


def pilot_status(store) -> dict:
    policy = load_policy(store)
    rollup = store.ai_cost_rollup(since_days=30, surface="remediation-pilot")
    model = next((m for m in rollup.get("by_model", [])
                  if m.get("provider") == PROVIDER and m.get("model") == MODEL
                  and m.get("zone") == ZONE), None) or {}
    calls, failed = int(model.get("calls") or 0), int(model.get("failed") or 0)
    reviewed, validation = model.get("reviewed") or {}, model.get("validation") or {}
    decisions = int(reviewed.get("decisions") or 0)
    accepted = int(reviewed.get("approved") or 0) + int(reviewed.get("edited") or 0)
    edited = int(reviewed.get("edited") or 0)
    validated = int(validation.get("validated") or 0)
    cleared = int(validation.get("cleared") or 0)
    reasons: list[str] = []
    if not policy["enabled"]:
        reasons.append("Pilot is off")
    if calls >= policy["max_calls"]:
        reasons.append("30-day call cap reached")
    if float(model.get("cost_usd") or 0) >= policy["max_spend_usd"]:
        reasons.append("30-day spend cap reached")
    if int(validation.get("regressed") or 0) or int(validation.get("newly_failing") or 0):
        reasons.append("Post-write validation found a regression")
    if calls >= policy["min_sample"] and failed / calls > policy["max_failure_rate"]:
        reasons.append("Model failure rate crossed the stop threshold")
    if decisions >= policy["min_sample"] and accepted / decisions < policy["min_acceptance_rate"]:
        reasons.append("Reviewer acceptance fell below the stop threshold")
    if accepted >= policy["min_sample"] and edited / accepted > policy["max_edit_rate"]:
        reasons.append("Reviewer edit rate crossed the stop threshold")
    if validated >= policy["min_sample"] and cleared / validated < policy["min_validation_clear_rate"]:
        reasons.append("Validation clear rate fell below the stop threshold")
    return {
        **policy, "provider": PROVIDER, "model": MODEL, "window_days": 30,
        "running": policy["enabled"] and not reasons, "stop_reasons": reasons,
        "metrics": {"calls": calls, "failed": failed, "cost_usd": float(model.get("cost_usd") or 0),
                    "decisions": decisions, "accepted": accepted, "edited": edited,
                    "validated": validated, "cleared": cleared,
                    "regressed": int(validation.get("regressed") or 0),
                    "newly_failing": int(validation.get("newly_failing") or 0)},
    }


def decision(store, file_format: str, criterion: str) -> dict:
    status = pilot_status(store)
    category = f"{(file_format or '').lower().lstrip('.')}:{criterion}"
    allowed = status["running"] and category in status["categories"] and category in ALLOWED_CATEGORIES
    return {"allowed": allowed, "category": category, "model": MODEL if allowed else None,
            "stop_reasons": status["stop_reasons"]}
