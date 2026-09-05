import json
import types

import pytest
from fastapi import HTTPException


class _Store:
    def __init__(self):
        self.value = ""
        self.audit = []

    def get_setting(self, _key, _default=""):
        return self.value

    def set_setting(self, _key, value):
        self.value = value

    def log_decision(self, *args, **kwargs):
        self.audit.append((args, kwargs))


def _request():
    return types.SimpleNamespace(state=types.SimpleNamespace(user_email="owner@example.com"))


def test_policy_route_round_trips_bounded_state(monkeypatch):
    from routes import system
    store = _Store()
    monkeypatch.setattr(system.core, "store", store)
    monkeypatch.setattr(system, "_require_admin", lambda _request: None)
    body = system.SecondOpinionPolicyUpdate(
        enabled=True, criteria=["1.3.5", "1.3.5"], confidence_threshold="medium")
    result = system.put_second_opinion_policy(body, _request())
    assert result["enabled"] is True
    assert result["criteria"] == ["1.3.5"]
    assert result["confidence_threshold"] == "medium"
    assert json.loads(store.value) == result
    assert system.get_second_opinion_policy(_request()) == result
    assert "future scans only" in store.audit[0][1]["detail"]


def test_enabled_policy_requires_criteria(monkeypatch):
    from routes import system
    store = _Store()
    monkeypatch.setattr(system.core, "store", store)
    monkeypatch.setattr(system, "_require_admin", lambda _request: None)
    with pytest.raises(HTTPException) as exc:
        system.put_second_opinion_policy(system.SecondOpinionPolicyUpdate(
            enabled=True, criteria=[], confidence_threshold="low"), _request())
    assert exc.value.status_code == 422
    assert store.value == ""


def test_invalid_threshold_is_rejected_before_write(monkeypatch):
    from routes import system
    store = _Store()
    monkeypatch.setattr(system.core, "store", store)
    monkeypatch.setattr(system, "_require_admin", lambda _request: None)
    with pytest.raises(HTTPException) as exc:
        system.put_second_opinion_policy(system.SecondOpinionPolicyUpdate(
            enabled=False, criteria=[], confidence_threshold="certain"), _request())
    assert exc.value.status_code == 422
    assert store.value == ""
