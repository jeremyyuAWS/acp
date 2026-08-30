"""Unit tests for scripts/validate_staging_azure.py.

Everything here mocks both sides of the comparison — the Azure SDK clients and the ACP HTTP
calls — so this suite exercises real network to neither Azure nor a running ACP instance. See
that script's own module docstring for what it does and why.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import validate_staging_azure as vsa  # noqa: E402


# --------------------------------------------------------------------------------- redaction

def test_redact_removes_known_subscription_tenant_client_ids():
    sub = "11111111-2222-3333-4444-555555555555"
    tenant = "66666666-7777-8888-9999-aaaaaaaaaaaa"
    client = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
    text = f"subscription={sub} tenant={tenant} client={client}"
    out = vsa.redact(text, {
        "<subscription>": sub, "<tenant>": tenant, "<client-id>": client,
    })
    assert sub not in out and tenant not in out and client not in out
    assert "<subscription>" in out and "<tenant>" in out and "<client-id>" in out


def test_redact_removes_hostnames():
    text = "ACP url: https://acp-app-staging.whitewater-1234abcd.eastus.azurecontainerapps.io/healthz"
    out = vsa.redact(text)
    assert "azurecontainerapps.io" not in out
    assert "<hostname>" in out


def test_redact_catches_uuid_not_passed_explicitly():
    """A backstop: any UUID-shaped string is redacted even if the caller didn't know to pass it
    (e.g. a revision resource id embedding the subscription id again)."""
    stray = "99999999-8888-7777-6666-555555555555"
    out = vsa.redact(f"resourceId contains {stray} unexpectedly")
    assert stray not in out
    assert "<uuid>" in out


def test_redact_preserves_unrelated_text():
    text = ("| min_replicas | 1 | 1 | agree |  |\n"
            "field=cpu_percent verdict=disagree note=azure-data-latency\n"
            "version azure-mgmt-appcontainers==5.0.0")
    out = vsa.redact(text, {"<subscription>": "11111111-2222-3333-4444-555555555555"})
    assert out == text  # nothing in this text should be touched


def test_redact_report_contains_no_real_identifiers_end_to_end():
    sub = "11111111-2222-3333-4444-555555555555"
    fqdn = "acp-app-staging.eastus.azurecontainerapps.io"
    rows = vsa.compare_fields(vsa._empty_azure_facts(), vsa._empty_acp_facts())
    meta = {"app_name": "acp-worker-staging", "resource_group": "mdk-accessibility",
            "generated_at": "2026-08-30T00:00:00+00:00"}
    report = vsa.render_report(rows, meta)
    report_with_secret = report + f"\nsome debug line: sub={sub} fqdn={fqdn}"
    out = vsa.redact(report_with_secret, {"<subscription>": sub, "<fqdn>": fqdn})
    assert sub not in out
    assert fqdn not in out


# --------------------------------------------------------------------------------- staging guard

@pytest.mark.parametrize("app_name", ["acp-worker", "acp-worker-prod", "acp-app", ""])
def test_assert_staging_target_rejects_non_staging_names(app_name):
    with pytest.raises(SystemExit):
        vsa.assert_staging_target("mdk-accessibility", app_name)


@pytest.mark.parametrize("app_name", ["acp-worker-staging", "ACP-WORKER-STAGING"])
def test_assert_staging_target_accepts_staging_names(app_name):
    vsa.assert_staging_target("mdk-accessibility", app_name)  # must not raise


def test_is_staging_target_is_case_insensitive_and_requires_suffix():
    assert vsa.is_staging_target("mdk-accessibility", "acp-worker-staging")
    assert vsa.is_staging_target("mdk-accessibility", "ACP-Worker-Staging")
    assert not vsa.is_staging_target("mdk-accessibility", "acp-worker-staging-canary")
    assert not vsa.is_staging_target("mdk-accessibility", "acp-worker")
    assert not vsa.is_staging_target("mdk-accessibility", "")


# --------------------------------------------------------------------------------- field comparison

def test_compare_fields_agree():
    azure = {"min_replicas": 1, "max_replicas": 5}
    acp = {"min_replicas": 1, "max_replicas": 5}
    rows = {r["field"]: r for r in vsa.compare_fields(azure, acp)}
    assert rows["min_replicas"]["verdict"] == "agree"
    assert rows["max_replicas"]["verdict"] == "agree"


def test_compare_fields_disagree():
    azure = {"min_replicas": 2}
    acp = {"min_replicas": 1}
    rows = {r["field"]: r for r in vsa.compare_fields(azure, acp)}
    assert rows["min_replicas"]["verdict"] == "disagree"
    assert "config" in rows["min_replicas"]["note"]


def test_compare_fields_acp_missing():
    azure = {"active_revision": "acp-worker-staging--rev2"}
    acp = {"active_revision": None}
    rows = {r["field"]: r for r in vsa.compare_fields(azure, acp)}
    assert rows["active_revision"]["verdict"] == "acp-missing"
    assert "code" in rows["active_revision"]["note"]


def test_compare_fields_azure_missing():
    azure = {"draining_replicas": None}
    acp = {"draining_replicas": 0}
    rows = {r["field"]: r for r in vsa.compare_fields(azure, acp)}
    assert rows["draining_replicas"]["verdict"] == "azure-missing"


def test_compare_fields_both_missing_is_agree():
    azure = {"cpu_percent": None}
    acp = {"cpu_percent": None}
    rows = {r["field"]: r for r in vsa.compare_fields(azure, acp)}
    assert rows["cpu_percent"]["verdict"] == "agree"


def test_compare_fields_metrics_missing_reports_rbac_reason():
    azure = {"cpu_percent": 42.0}
    acp = {"cpu_percent": None, "metrics_unavailable_reason": "permission"}
    rows = {r["field"]: r for r in vsa.compare_fields(azure, acp)}
    assert rows["cpu_percent"]["verdict"] == "acp-missing"
    assert "rbac" in rows["cpu_percent"]["note"]


def test_compare_fields_metrics_missing_reports_no_data_reason():
    azure = {"memory_percent": 10.0}
    acp = {"memory_percent": None, "metrics_unavailable_reason": "no_data"}
    rows = {r["field"]: r for r in vsa.compare_fields(azure, acp)}
    assert rows["memory_percent"]["verdict"] == "acp-missing"
    assert "missing-telemetry" in rows["memory_percent"]["note"]


def test_compare_fields_cpu_within_tolerance_is_agree_despite_small_drift():
    azure = {"cpu_percent": 40.0}
    acp = {"cpu_percent": 42.0}
    rows = {r["field"]: r for r in vsa.compare_fields(azure, acp)}
    assert rows["cpu_percent"]["verdict"] == "agree"


def test_compare_fields_cpu_outside_tolerance_is_disagree_with_latency_reason():
    azure = {"cpu_percent": 10.0}
    acp = {"cpu_percent": 90.0}
    rows = {r["field"]: r for r in vsa.compare_fields(azure, acp)}
    assert rows["cpu_percent"]["verdict"] == "disagree"
    assert "azure-data-latency" in rows["cpu_percent"]["note"]


# --------------------------------------------------------------------------------- Azure-side collection (mocked SDK)

class _FakeScale:
    def __init__(self, min_replicas, max_replicas):
        self.min_replicas = min_replicas
        self.max_replicas = max_replicas


class _FakeTemplate:
    def __init__(self, scale):
        self.scale = scale


class _FakeIngressTraffic:
    def __init__(self, revision_name, weight):
        self.revision_name = revision_name
        self.weight = weight


class _FakeIngress:
    def __init__(self, traffic):
        self.traffic = traffic


class _FakeConfiguration:
    def __init__(self, ingress):
        self.ingress = ingress


class _FakeAppProperties:
    def __init__(self, scale, latest_ready_revision_name, traffic):
        self.template = _FakeTemplate(scale)
        self.latest_ready_revision_name = latest_ready_revision_name
        self.configuration = _FakeConfiguration(_FakeIngress(traffic))


class _FakeApp:
    def __init__(self, scale, latest_ready_revision_name, traffic, resource_id="fake-id"):
        self.properties = _FakeAppProperties(scale, latest_ready_revision_name, traffic)
        self.id = resource_id


class _FakeRevision:
    def __init__(self, name, active, health_state, provisioning_state, replicas):
        self.name = name
        self.active = active
        self.health_state = health_state
        self.provisioning_state = provisioning_state
        self.replicas = replicas


class _FakeContainerApps:
    def __init__(self, app):
        self._app = app

    def get(self, rg, name):
        return self._app


class _FakeRevisionReplicas:
    def __init__(self, replicas):
        self._replicas = replicas

    def list_replicas(self, rg, app, revision):
        return SimpleNamespace(value=self._replicas)


class _FakeRevisions:
    def __init__(self, revisions):
        self._revisions = revisions

    def list_revisions(self, rg, app):
        return SimpleNamespace(value=self._revisions)


class _FakeContainerClient:
    def __init__(self, app, replicas, revisions):
        self.container_apps = _FakeContainerApps(app)
        self.container_apps_revision_replicas = _FakeRevisionReplicas(replicas)
        self.container_apps_revisions = _FakeRevisions(revisions)


class _FakeMonitorClient:
    def __init__(self, values):
        self.metrics = SimpleNamespace(list=lambda *a, **k: SimpleNamespace(value=values))


def test_collect_azure_facts_happy_path():
    active_rev = _FakeRevision("acp-worker-staging--rev2", True, "Healthy", "Provisioned", 2)
    old_rev = _FakeRevision("acp-worker-staging--rev1", False, "Healthy", "Provisioned", 1)
    app = _FakeApp(_FakeScale(1, 5), "acp-worker-staging--rev2",
                   [_FakeIngressTraffic("acp-worker-staging--rev2", 100)])
    client = _FakeContainerClient(app, replicas=[object(), object()],
                                  revisions=[active_rev, old_rev])
    monitor = _FakeMonitorClient([])

    facts = vsa.collect_azure_facts(client, monitor, "mdk-accessibility", "acp-worker-staging")

    assert facts["min_replicas"] == 1
    assert facts["max_replicas"] == 5
    assert facts["current_replicas"] == 2
    assert facts["active_revision"] == "acp-worker-staging--rev2"
    assert facts["revision_health"] == "Healthy"
    assert facts["revision_provisioning_state"] == "Provisioned"
    assert facts["revision_traffic_percent"] == 100
    assert facts["draining_replicas"] == 1


def test_collect_azure_facts_survives_revision_list_failure():
    """A failure fetching revisions must not lose the min/max data already gathered."""
    app = _FakeApp(_FakeScale(1, 5), "rev1", [])

    class _BrokenRevisions:
        def list_revisions(self, rg, app):
            raise RuntimeError("boom")

    client = _FakeContainerClient(app, replicas=[], revisions=[])
    client.container_apps_revisions = _BrokenRevisions()
    monitor = _FakeMonitorClient([])

    facts = vsa.collect_azure_facts(client, monitor, "mdk-accessibility", "acp-worker-staging")
    assert facts["min_replicas"] == 1
    assert facts["max_replicas"] == 5
    assert facts["active_revision"] is None


# --------------------------------------------------------------------------------- ACP-side collection (mocked HTTP)

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_collect_acp_facts_merges_all_three_endpoints(monkeypatch):
    responses = {
        "/control/workers/replicas": {"configured": True, "min_replicas": 1, "max_replicas": 5},
        "/control/workers/capacity": {
            "configured": True, "current_replicas": 2, "cpu_percent": 12.3,
            "memory_percent": 45.6, "revision_health": "Healthy",
            "revision_provisioning_state": "Provisioned", "draining_replicas": 0,
            "revision_traffic_percent": 100, "metrics_unavailable_reason": None,
        },
        "/control/workers/revisions": {
            "configured": True,
            "revisions": [
                {"name": "acp-worker-staging--rev2", "active": True},
                {"name": "acp-worker-staging--rev1", "active": False},
            ],
        },
    }

    def _fake_urlopen(req, timeout=None):
        for path, payload in responses.items():
            if req.full_url.endswith(path):
                return _FakeResponse(payload)
        raise AssertionError(f"unexpected URL {req.full_url}")

    monkeypatch.setattr(vsa.urllib.request, "urlopen", _fake_urlopen)

    facts = vsa.collect_acp_facts("https://acp-app-staging.example.com", "e2e-key-value")

    assert facts["min_replicas"] == 1
    assert facts["max_replicas"] == 5
    assert facts["current_replicas"] == 2
    assert facts["cpu_percent"] == 12.3
    assert facts["memory_percent"] == 45.6
    assert facts["active_revision"] == "acp-worker-staging--rev2"


# --------------------------------------------------------------------------------- CLI reuse modes
# validate-staging-scale-test.yml (workflow 2) shells out to these two modes rather than
# reimplementing the safety check or the redaction sweep in bash.

def test_cli_check_staging_only_exits_zero_for_staging_app(capsys):
    rc = _run_cli(["--check-staging-only", "--az-resource-group", "mdk-accessibility",
                   "--az-app", "acp-worker-staging"])
    assert rc in (0, None)
    assert "OK" in capsys.readouterr().out


def test_cli_check_staging_only_exits_nonzero_for_prod_app():
    with pytest.raises(SystemExit):
        _run_cli(["--check-staging-only", "--az-resource-group", "mdk-accessibility",
                  "--az-app", "acp-worker"])


def test_cli_redact_file_writes_redacted_output(tmp_path):
    sub = "11111111-2222-3333-4444-555555555555"
    src = tmp_path / "report.txt"
    src.write_text(f"original min_replicas=1 subscription={sub}")
    out = tmp_path / "report.redacted.txt"

    _run_cli(["--redact-file", str(src), "--out", str(out), "--secret", f"<subscription>={sub}"])

    redacted = out.read_text()
    assert sub not in redacted
    assert "<subscription>" in redacted
    assert "original min_replicas=1" in redacted
    assert src.read_text() == f"original min_replicas=1 subscription={sub}"  # source untouched


def test_cli_redact_file_in_place_when_no_out_given(tmp_path):
    sub = "11111111-2222-3333-4444-555555555555"
    src = tmp_path / "report.txt"
    src.write_text(f"subscription={sub}")

    _run_cli(["--redact-file", str(src), "--secret", f"<subscription>={sub}"])

    assert sub not in src.read_text()


def _run_cli(argv):
    old_argv = sys.argv
    sys.argv = ["validate_staging_azure.py"] + argv
    try:
        return vsa.main()
    finally:
        sys.argv = old_argv


def test_get_json_sends_e2e_key_header(monkeypatch):
    captured = {}

    def _fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.header_items())
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(vsa.urllib.request, "urlopen", _fake_urlopen)
    vsa._get_json("https://example.com/x", "my-secret-key", 10.0)
    # urllib title-cases header names it stores
    assert captured["headers"].get("X-e2e-key") == "my-secret-key"
