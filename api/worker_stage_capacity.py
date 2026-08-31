"""Role-aware worker heartbeat reads for dedicated stage services.

Each worker writes ``worker_tier_heartbeat:<role>`` as well as the legacy global key. The
role key is authoritative once present; the global fallback keeps rolling deploys available
while an older worker image is still running.
"""
from __future__ import annotations

from datetime import datetime, timezone

from store import _parse_worker_tier_heartbeat


def worker_role_alive(store, role: str, window_s: int = 120) -> bool:
    raw = store.get_setting(f"worker_tier_heartbeat:{role}")
    if not raw:
        raw = store.get_setting("worker_tier_heartbeat")
    if not raw:
        return False
    iso, _pool, _version = _parse_worker_tier_heartbeat(raw)
    try:
        beat = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return False
    if beat.tzinfo is None:
        beat = beat.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - beat).total_seconds() <= window_s
