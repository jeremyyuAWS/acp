"""Fail-closed execution interpretation of a sealed remediation impact plan."""
from __future__ import annotations


def execution_controls(payload: dict, ai_enabled: bool) -> dict | None:
    """Legacy jobs retain their existing behavior; new plans must be complete and supported.

    Allowed criteria come from the authoritative forecast, never directly from the browser.
    The caller must still intersect them with recorded assessment failures and scan scope.
    """
    if "remediation_impact_policy" not in payload:
        return None
    policy = payload["remediation_impact_policy"]
    if not isinstance(policy, dict):
        raise ValueError("Invalid remediation impact policy")
    rule_based, ai = policy.get("rule_based"), policy.get("ai")
    if type(rule_based) is not int or rule_based not in range(3):
        raise ValueError("Invalid rule-based remediation setting")
    if type(ai) is not int or ai not in range(4):
        raise ValueError("Invalid AI remediation setting")
    if ai > 1:
        raise ValueError("Automatic AI application is not supported; select Draft for review")
    rules = payload.get("remediation_impact_allowed_rules")
    if not isinstance(rules, list) or any(not isinstance(rule, str) for rule in rules):
        raise ValueError("Missing authoritative remediation rule scope")
    return {"allowed_rules": frozenset(rules) if rule_based else frozenset(),
            "draft_ai": bool(ai_enabled) and ai == 1}
