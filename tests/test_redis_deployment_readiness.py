"""Redis is a shared worker dependency, not an optional production detail."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))


class _Redis:
    def __init__(self, result=True, error=None):
        self.result = result
        self.error = error

    def ping(self):
        if self.error:
            raise self.error
        return self.result


def test_managed_redis_is_identified_without_exposing_its_endpoint(monkeypatch):
    import core
    secret_url = "rediss://:secret@pilot.redis.azure.net:10000/0"
    monkeypatch.setattr(core, "REDIS_URL", secret_url)
    monkeypatch.setattr(core, "_get_redis", lambda: _Redis())

    status = core.redis_dependency_status()

    assert status == {"configured": True, "reachable": True, "tls": True,
                      "topology": "managed", "reason": None}
    assert "pilot" not in repr(status) and "secret" not in repr(status)


def test_self_hosted_redis_is_visible_as_a_remaining_failure_domain(monkeypatch):
    import core
    monkeypatch.setattr(core, "REDIS_URL", "redis://acp-redis:6379/0")
    monkeypatch.setattr(core, "_get_redis", lambda: _Redis())
    assert core.redis_dependency_status()["topology"] == "self_hosted"


def test_redis_failure_is_sanitised(monkeypatch):
    import core
    monkeypatch.setattr(core, "REDIS_URL", "rediss://:secret@private.redis.azure.net:10000/0")
    monkeypatch.setattr(core, "_get_redis",
                        lambda: _Redis(error=ConnectionError("private.redis.azure.net refused")))
    status = core.redis_dependency_status()
    assert status["reachable"] is False
    assert status["reason"] == "ConnectionError: Redis unavailable"


def test_redeploy_requires_reachable_redis_and_reports_topology():
    script = (ROOT / "deploy/public/redeploy.sh").read_text()
    gate = script[script.index("READY_BEFORE="):script.index("# ── 8-BG")]
    assert "REDIS_REPORTED" in gate and "REDIS_CONFIGURED" in gate and "REDIS_REACHABLE" in gate
    assert "Azure Managed Redis" in gate
    assert 'die "Redis is unavailable before deployment' in gate
    assert "predates Redis readiness reporting" in gate
