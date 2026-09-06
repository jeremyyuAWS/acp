from realtime_feature import gateway_enabled, publisher_enabled, shadow_allowed
from routes import system


def test_realtime_shadow_is_default_off(monkeypatch):
    for name in ("ACP_DEPLOY_ENV", "ACP_REALTIME_V1_ENABLED", "ACP_REALTIME_SHADOW_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    assert shadow_allowed()
    assert not gateway_enabled()
    assert not publisher_enabled()


def test_staging_can_enable_each_side_explicitly(monkeypatch):
    monkeypatch.setenv("ACP_DEPLOY_ENV", "staging")
    monkeypatch.setenv("ACP_REALTIME_V1_ENABLED", "true")
    monkeypatch.setenv("ACP_REALTIME_SHADOW_ENABLED", "1")
    assert gateway_enabled()
    assert publisher_enabled()


def test_production_refuses_shadow_even_if_both_flags_are_set(monkeypatch):
    monkeypatch.setenv("ACP_DEPLOY_ENV", "production")
    monkeypatch.setenv("ACP_REALTIME_V1_ENABLED", "true")
    monkeypatch.setenv("ACP_REALTIME_SHADOW_ENABLED", "true")
    assert not shadow_allowed()
    assert not gateway_enabled()
    assert not publisher_enabled()


def test_public_config_reports_only_the_effective_runtime_flag(monkeypatch):
    monkeypatch.setenv("ACP_DEPLOY_ENV", "staging")
    monkeypatch.setenv("ACP_REALTIME_V1_ENABLED", "true")
    assert system.config()["realtime_shadow_enabled"] is True
    monkeypatch.setenv("ACP_DEPLOY_ENV", "production")
    assert system.config()["realtime_shadow_enabled"] is False
