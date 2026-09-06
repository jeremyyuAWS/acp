"""One effective flag for the additive realtime shadow path.

Production is deliberately ineligible during the shadow phase even if somebody accidentally sets
one of the opt-in variables. Local development remains available when ACP_DEPLOY_ENV is unset.
"""
from __future__ import annotations

import os


_TRUE = frozenset({"1", "true", "yes", "on"})


def _on(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUE


def shadow_allowed() -> bool:
    return os.getenv("ACP_DEPLOY_ENV", "").strip().lower() != "production"


def gateway_enabled() -> bool:
    return shadow_allowed() and _on("ACP_REALTIME_V1_ENABLED")


def publisher_enabled() -> bool:
    return shadow_allowed() and _on("ACP_REALTIME_SHADOW_ENABLED")
