"""Validated, immutable policy for assessment-time cloud second opinions."""
from __future__ import annotations

import json
from typing import Any

SETTING_KEY = "second_opinion_policy"
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
DEFAULT_POLICY = {
    "enabled": False,
    "criteria": ["1.3.5"],
    "confidence_threshold": "low",
}


def normalize_policy(value: Any) -> dict:
    """Return a bounded policy shape; malformed stored state fails closed."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = {}
    if not isinstance(value, dict):
        value = {}
    threshold = str(value.get("confidence_threshold") or "low").lower()
    if threshold not in CONFIDENCE_ORDER:
        threshold = "low"
    criteria = sorted({str(item).strip() for item in (value.get("criteria") or [])
                       if str(item).strip()})
    return {
        "enabled": value.get("enabled") is True,
        "criteria": criteria,
        "confidence_threshold": threshold,
    }


def load_policy(store) -> dict:
    return normalize_policy(store.get_setting(SETTING_KEY, ""))


def eligible(policy: dict, criterion: str, confidence: str) -> bool:
    policy = normalize_policy(policy)
    return bool(
        policy["enabled"]
        and criterion in policy["criteria"]
        and CONFIDENCE_ORDER.get(confidence, 99)
        <= CONFIDENCE_ORDER[policy["confidence_threshold"]]
    )
