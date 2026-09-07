"""Pure application boundary for capacity policies.

This module deliberately knows nothing about FastAPI, persistence, or the Azure SDK.  It gives
those layers one deterministic, secret-free policy shape and an injectable gateway contract.
The production SDK adapter belongs in a later change, after its merge-patch behaviour has been
verified against the pinned SDK and a real Container App.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Protocol

from capacity_policy import AppPolicy


class CapacityGateway(Protocol):
    """The small Azure boundary needed by an eventual route or reconciler."""

    def read_scale(self, app: str) -> dict | None:
        """Return an observed scale block, or None when it cannot be read."""

    def apply_scale(self, policy: AppPolicy) -> None:
        """Replace one app's complete scale policy, or raise on failure."""


_SENSITIVE = ("secret", "password", "token", "credential", "connection")


def _safe_value(key: str, value: Any) -> Any:
    """Canonicalise JSON values without ever retaining credential-shaped metadata."""
    folded = key.lower().replace("_", "").replace("-", "")
    if any(word in folded for word in _SENSITIVE):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): _safe_value(str(k), v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_safe_value(key, item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _rule(name: Any, kind: Any, metadata: Any) -> dict:
    return {
        "name": str(name or ""),
        "type": str(kind or "").lower(),
        "metadata": _safe_value("metadata", metadata if isinstance(metadata, dict) else {}),
    }


def desired_policy(policy: AppPolicy) -> dict:
    """Return the complete, comparable scale intent; auth references are intentionally omitted."""
    rules = [_rule(r.name, r.type, r.metadata) for r in policy.rules]
    rules.sort(key=lambda r: (r["name"], r["type"], _canonical_json(r["metadata"])))
    return {
        "app": policy.app,
        "min_replicas": int(policy.min_replicas),
        "max_replicas": int(policy.max_replicas),
        "rules": rules,
    }


def observed_policy(app: str, scale: dict) -> dict:
    """Normalise GET /capacity's scale block or its enclosing app block."""
    if isinstance(scale.get("scale"), dict):
        scale = scale["scale"]
    rules = []
    for raw in scale.get("rules") or []:
        if isinstance(raw, dict):
            rules.append(_rule(raw.get("name"), raw.get("type"), raw.get("metadata")))
    rules.sort(key=lambda r: (r["name"], r["type"], _canonical_json(r["metadata"])))
    return {
        "app": app,
        "min_replicas": _integer(scale.get("min_replicas")),
        "max_replicas": _integer(scale.get("max_replicas")),
        "rules": rules,
    }


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def policy_hash(policy: AppPolicy | dict) -> str:
    """A stable SHA-256 fingerprint of secret-free policy data."""
    normal = desired_policy(policy) if isinstance(policy, AppPolicy) else _safe_value("policy", policy)
    return hashlib.sha256(_canonical_json(normal).encode("utf-8")).hexdigest()


def compare(policy: AppPolicy, observed: dict | None) -> dict:
    """Compare full desired and observed scale configuration without guessing unreadable state."""
    desired = desired_policy(policy)
    if observed is None:
        return {"state": "unreadable", "desired_hash": policy_hash(desired),
                "observed_hash": None, "differences": []}
    actual = observed_policy(policy.app, observed)
    differences = []
    for field in ("min_replicas", "max_replicas", "rules"):
        if desired[field] != actual[field]:
            differences.append({"field": field, "desired": desired[field], "observed": actual[field]})
    return {"state": "matched" if not differences else "drifted",
            "desired_hash": policy_hash(desired), "observed_hash": policy_hash(actual),
            "differences": differences}


def _error_code(error: Exception) -> str:
    """Classify without returning exception text, which may contain request data or credentials."""
    status = getattr(error, "status_code", None)
    return f"http_{status}" if isinstance(status, int) else type(error).__name__


def apply_policies(policies: Iterable[AppPolicy], gateway: CapacityGateway) -> dict:
    """Preflight, apply sequentially, and verify each app, returning all per-app outcomes.

    A failed preflight performs no writes.  An apply failure stops later writes because a caller
    needs an honest partial result before deciding whether to reconcile.  No retry policy or
    persistence is hidden in this pure layer.
    """
    policies = list(policies)
    preflight: dict[str, dict | None] = {}
    preflight_errors: dict[str, str] = {}
    outcomes = []
    for policy in policies:
        try:
            preflight[policy.app] = gateway.read_scale(policy.app)
        except Exception as error:  # noqa: BLE001 - the boundary returns a classified outcome
            preflight_errors[policy.app] = _error_code(error)
    if preflight_errors or any(value is None for value in preflight.values()):
        for policy in policies:
            if policy.app in preflight_errors:
                outcomes.append({"app": policy.app, "status": "preflight_failed",
                                 "error_code": preflight_errors[policy.app]})
            else:
                status = "preflight_failed" if preflight.get(policy.app) is None else "not_applied"
                outcomes.append({"app": policy.app, "status": status})
        return {"state": "preflight_failed", "apps": outcomes}

    stopped = False
    for policy in policies:
        if stopped:
            outcomes.append({"app": policy.app, "status": "not_applied"})
            continue
        try:
            gateway.apply_scale(policy)
            verification = compare(policy, gateway.read_scale(policy.app))
            status = "applied" if verification["state"] == "matched" else verification["state"]
            outcomes.append({"app": policy.app, "status": status, **verification})
            stopped = status != "applied"
        except Exception as error:  # noqa: BLE001
            outcomes.append({"app": policy.app, "status": "apply_failed",
                             "error_code": _error_code(error)})
            stopped = True
    state = "applied" if all(row["status"] == "applied" for row in outcomes) else "partial"
    return {"state": state, "apps": outcomes}
