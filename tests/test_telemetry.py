"""Application Insights: opt-in, and scrubbed.

The two claims this file exists to hold, because both fail silently in the direction that hurts:

  1. NOTHING HAPPENS WITHOUT A CONNECTION STRING. Telemetry that turns itself on is telemetry
     nobody decided to send, and the failure is invisible — data simply starts leaving.

  2. NO FILENAME AND NO EMAIL LEAVES. Application Insights is a different trust boundary from the
     drawer, which shows a filename only to an authenticated member of that workspace. A span
     attribute that carries one is a customer's document title in an operations tool, and nothing
     in the trace itself would look wrong.

The allowlist direction is deliberate and is tested as such: a denylist protects the keys somebody
thought of, and the next attribute added anywhere in the codebase ships by default.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import pytest

import telemetry


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("ACP_TELEMETRY_SALT", raising=False)
    monkeypatch.delenv("APPLICATIONINSIGHTS_SAMPLING_RATIO", raising=False)
    telemetry._state.update(enabled=False, reason="not configured", sampling_ratio=None,
                            correlation="off", configured_at=None)
    yield


# ── Off unless asked for ────────────────────────────────────────────────────────────────────

def test_nothing_is_configured_without_a_connection_string():
    state = telemetry.configure()
    assert state["enabled"] is False
    assert state["reason"] == "not configured"
    assert state["sampling_ratio"] is None


def test_a_missing_sdk_is_reported_rather_than_crashing_startup(monkeypatch):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc")
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _no_azure(name, *args, **kwargs):
        if name.startswith("azure.monitor.opentelemetry"):
            raise ImportError("not installed here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _no_azure)
    state = telemetry.configure()
    assert state["enabled"] is False
    assert "not installed" in state["reason"]


def test_an_exporter_that_fails_to_start_leaves_the_api_running(monkeypatch):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc")
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _boom(name, *args, **kwargs):
        if name.startswith("azure.monitor.opentelemetry"):
            raise RuntimeError("bad connection string")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _boom)
    state = telemetry.configure()
    assert state["enabled"] is False
    assert "exporter failed to start" in state["reason"]


def test_the_sampling_ratio_defaults_to_everything_and_is_clamped(monkeypatch):
    """A quieter default would be cheaper and would silently lose the one trace an operator went
    looking for."""
    assert telemetry._sampling_ratio() == 1.0
    monkeypatch.setenv("APPLICATIONINSIGHTS_SAMPLING_RATIO", "0.25")
    assert telemetry._sampling_ratio() == 0.25
    monkeypatch.setenv("APPLICATIONINSIGHTS_SAMPLING_RATIO", "7")
    assert telemetry._sampling_ratio() == 1.0
    monkeypatch.setenv("APPLICATIONINSIGHTS_SAMPLING_RATIO", "nonsense")
    assert telemetry._sampling_ratio() == 1.0


# ── Identities never leave ──────────────────────────────────────────────────────────────────

def test_a_tenant_is_an_opaque_id_and_never_the_address(monkeypatch):
    monkeypatch.setenv("ACP_TELEMETRY_SALT", "pepper")
    ident = telemetry.tenant_id("Operator@Example.ORG")
    assert ident and "@" not in ident and "example" not in ident.lower()
    assert len(ident) == 16
    # Stable, and case/whitespace insensitive, so the same customer joins across services.
    assert ident == telemetry.tenant_id("  operator@example.org  ")


def test_a_document_is_an_opaque_id_scoped_to_its_scan(monkeypatch):
    monkeypatch.setenv("ACP_TELEMETRY_SALT", "pepper")
    first = telemetry.document_id("scan-1", "/Finance/Q3 Board Pack.docx")
    second = telemetry.document_id("scan-2", "/Finance/Q3 Board Pack.docx")
    assert "Board" not in first and ".docx" not in first
    # The same file in two customers' estates must not share an id.
    assert first != second
    assert first == telemetry.document_id("scan-1", "/Finance/Q3 Board Pack.docx")


def test_without_a_salt_the_ids_are_omitted_rather_than_invented(monkeypatch):
    """A per-process random salt would give every replica a different id for the same tenant —
    correlation that looks real and joins nothing. Omitted is the honest degradation."""
    assert telemetry.tenant_id("operator@example.org") is None
    assert telemetry.document_id("scan-1", "/a.docx") is None


def test_the_correlation_bag_carries_ids_and_drops_everything_else(monkeypatch):
    monkeypatch.setenv("ACP_TELEMETRY_SALT", "pepper")
    bag = telemetry.correlation(scan_id="scan-1", batch_id="b1", job_id="j1",
                                owner_email="operator@example.org",
                                path="/Finance/Q3 Board Pack.docx",
                                stage="assess", rule_id="1.4.3")
    assert bag["acp.scan_id"] == "scan-1"
    assert bag["acp.stage"] == "assess"
    assert bag["acp.rule_id"] == "1.4.3"
    assert bag["acp.tenant_id"] and bag["acp.document_id"]
    assert "operator@example.org" not in str(bag)
    assert "Board Pack" not in str(bag)


def test_a_caller_cannot_smuggle_a_filename_in_under_a_new_key(monkeypatch):
    """The allowlist is applied to `extra` too, so naming something new is not a way past it."""
    monkeypatch.setenv("ACP_TELEMETRY_SALT", "pepper")
    bag = telemetry.correlation(scan_id="scan-1", filename="Q3 Board Pack.docx",
                                owner="operator@example.org")
    assert bag == {"acp.scan_id": "scan-1"}


# ── The scrubber ────────────────────────────────────────────────────────────────────────────

def test_an_unknown_acp_attribute_is_dropped_not_passed():
    """We control that namespace, so an unknown key is an accident — and the next attribute added
    anywhere in the codebase must not ship by default."""
    out = telemetry.scrub({"acp.scan_id": "s1", "acp.current_file": "Private Report.docx"})
    assert out == {"acp.scan_id": "s1"}


def test_a_query_string_is_stripped_and_a_statement_redacted():
    out = telemetry.scrub({
        "http.url": "https://graph.microsoft.com/v1.0/drives/x/items?name=Q3%20Board%20Pack.docx",
        "db.statement": "SELECT * FROM documents WHERE path='/Finance/Q3.docx'",
    })
    assert out["http.url"] == "https://graph.microsoft.com/v1.0/drives/x/items"
    assert out["db.statement"] == "[redacted]"
    assert "Board" not in str(out) and "Finance" not in str(out)


def test_standard_attributes_pass_so_the_traces_remain_readable():
    """Dropping all of OpenTelemetry's own semantics would leave traces nobody can read, which is
    its own kind of useless."""
    out = telemetry.scrub({"http.method": "GET", "http.status_code": 200, "net.peer.name": "db"})
    assert out == {"http.method": "GET", "http.status_code": 200, "net.peer.name": "db"}


def test_scrub_is_total_and_never_raises():
    assert telemetry.scrub(None) == {}
    assert telemetry.scrub({}) == {}
    # A non-string url is left alone rather than crashing the span.
    assert telemetry.scrub({"http.url": 42}) == {"http.url": 42}


def test_the_allowlist_names_no_field_that_could_hold_free_text():
    """A standing guard on the list itself: every allowed key is an id, an enum or a counter.
    `file`, `path`, `name`, `email` and `owner` are the shapes that carry a customer's words."""
    forbidden = ("file", "path", "name", "email", "owner", "title", "url", "text", "message")
    for key in telemetry.ALLOWED_ACP_ATTRIBUTES:
        assert not any(marker in key for marker in forbidden), key


# ── What the drawer is told ─────────────────────────────────────────────────────────────────

def test_status_says_why_tracing_is_off_not_just_that_it_is():
    """A trace drill-down link to traces that do not exist is worse than no link."""
    state = telemetry.status()
    assert state["enabled"] is False
    assert state["reason"] == "not configured"


def test_correlation_is_reported_as_ids_only_when_no_salt_is_set(monkeypatch):
    """The difference is invisible in the traces themselves: spans still export and still join by
    scan_id, they just carry no tenant or document id at all."""
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc")
    monkeypatch.setattr(telemetry, "_install_scrubber", lambda: True)
    sent = {}

    class _Fake:
        @staticmethod
        def configure_azure_monitor(**kwargs):
            sent.update(kwargs)

    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", _Fake)
    state = telemetry.configure(now_iso="2026-09-05T00:00:00Z")
    assert state["enabled"] is True
    assert state["correlation"] == "ids_only"
    assert sent["sampling_ratio"] == 1.0
    assert sent["connection_string"] == "InstrumentationKey=abc"

    telemetry._state.update(enabled=False)
    monkeypatch.setenv("ACP_TELEMETRY_SALT", "pepper")
    assert telemetry.configure()["correlation"] == "full"


def test_no_scrubber_means_no_export(monkeypatch):
    """The processor is what stands between auto-instrumentation and a customer's filename in a
    URL query. If it cannot attach — a provider shape changed, the SDK swapped — the quiet outcome
    would be a live exporter with nothing filtering it, so the exporter is stopped instead."""
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc")
    stopped = []

    class _Fake:
        @staticmethod
        def configure_azure_monitor(**kwargs):
            return None

    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", _Fake)
    monkeypatch.setattr(telemetry, "_install_scrubber", lambda: False)
    monkeypatch.setattr(telemetry, "_shutdown_provider", lambda: stopped.append(True))

    state = telemetry.configure()
    assert state["enabled"] is False
    assert "exporter stopped" in state["reason"]
    assert stopped == [True]


def test_the_scrubber_reports_whether_it_actually_attached(monkeypatch):
    """Feature-detected on the provider, so a provider that cannot take a processor is a False
    rather than a silent no-op."""
    class _NoProcessor:
        pass

    class _Provider:
        def __init__(self):
            self.added = []

        def add_span_processor(self, processor):
            self.added.append(processor)

    import opentelemetry.trace as ot
    monkeypatch.setattr(ot, "get_tracer_provider", lambda: _NoProcessor())
    assert telemetry._install_scrubber() is False
    provider = _Provider()
    monkeypatch.setattr(ot, "get_tracer_provider", lambda: provider)
    assert telemetry._install_scrubber() is True
    assert len(provider.added) == 1


# ── The dependency pair ─────────────────────────────────────────────────────────────────────

def test_the_google_and_azure_pins_are_kept_as_a_pair():
    """google-api-core and the Azure Monitor distro constrain each other, and the constraint is
    invisible from either line alone.

    google-api-core 2.36.0 is the first release to make `opentelemetry-api>=1.44.0` a hard,
    non-extra dependency; azure-monitor-opentelemetry pins `opentelemetry-sdk~=1.43.0`. The two
    cannot both be satisfied, so google-api-core is held at 2.34.0 — which requires no
    opentelemetry-api at all.

    This fails if either pin is bumped without the other, because the next person to update
    dependencies will see two unrelated-looking lines and a passing `pip install`, and the
    reintroduced conflict shows up as one more warning in a log nobody reads.
    """
    requirements = (ACP / "api" / "requirements.txt").read_text()
    assert "google-api-core==2.34.0" in requirements
    assert "azure-monitor-opentelemetry==1.8.9" in requirements
    # And the reason travels with them, in both places.
    assert "opentelemetry-api>=1.44.0" in requirements
    assert "opentelemetry-sdk~=1.43.0" in requirements


def test_the_scrubber_attaches_to_a_real_sdk_provider(monkeypatch):
    """The `no scrubber, no export` guard is feature-detected, so this pins that the detection
    actually succeeds against the real SDK — not only against a fake with the right method name.
    If it ever returned False in production, tracing would switch itself off and nobody would get
    traces, which is safe but silent.

    A LOCAL provider, injected, rather than the global one: OpenTelemetry allows the global
    provider to be set once per process and warns rather than replacing it, so a test that sets it
    would pass or fail on whether it happened to run first.
    """
    pytest.importorskip("opentelemetry.sdk.trace",
                        reason="azure-monitor-opentelemetry pulls the SDK; pinned in api/requirements.txt")
    import opentelemetry.trace as ot
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    monkeypatch.setattr(ot, "get_tracer_provider", lambda: provider)
    assert telemetry._install_scrubber() is True


def test_a_live_span_loses_the_filename_and_the_query():
    """End to end through a real span rather than a dict: the attributes an actual tracer records
    are what the exporter would send."""
    pytest.importorskip("opentelemetry.sdk.trace",
                        reason="azure-monitor-opentelemetry pulls the SDK; pinned in api/requirements.txt")
    from opentelemetry.sdk.trace import TracerProvider

    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("probe") as span:
        span.set_attribute("acp.scan_id", "scan-1")
        span.set_attribute("acp.current_file", "Q3 Board Pack.docx")
        span.set_attribute("http.url", "https://graph.microsoft.com/items?name=Q3%20Board%20Pack.docx")
        cleaned = telemetry.scrub(dict(span.attributes))
    assert cleaned == {"acp.scan_id": "scan-1", "http.url": "https://graph.microsoft.com/items"}
    assert "Board Pack" not in str(cleaned)


def test_a_scrub_failure_is_reported_rather_than_shipped_in_silence(monkeypatch):
    """The one handler in this file whose silence has a security cost.

    `scrub` is total (see above), so the only way to reach its handler is an attribute shape
    nobody anticipated. When that happens the span still goes to the exporter carrying its
    ORIGINAL attributes — a filename among them — and `set_attribute` cannot take one back off.
    The failure is therefore invisible in the trace itself: the span looks normal and simply
    was not cleaned. `swallowed` is the only thing that says so.
    """
    pytest.importorskip("opentelemetry.sdk.trace",
                        reason="azure-monitor-opentelemetry pulls the SDK; pinned in api/requirements.txt")
    import logging

    import opentelemetry.trace as ot
    from opentelemetry.sdk.trace import TracerProvider
    import swallowed as _swallowed

    provider = TracerProvider()
    monkeypatch.setattr(ot, "get_tracer_provider", lambda: provider)
    assert telemetry._install_scrubber() is True

    def _explode(_attributes):
        raise RuntimeError("an attribute shape nobody anticipated")

    monkeypatch.setattr(telemetry, "scrub", _explode)
    _swallowed.reset()

    records = []
    handler = logging.Handler()
    handler.emit = records.append
    _swallowed.logger.addHandler(handler)
    try:
        with provider.get_tracer("test").start_as_current_span("probe") as span:
            span.set_attribute("acp.current_file", "Q3 Board Pack.docx")
    finally:
        _swallowed.logger.removeHandler(handler)
        _swallowed.reset()

    assert records, "a scrub failure produced no report at all — the unscrubbed span is untraceable"
    assert any("_Scrubber.on_start" in r.getMessage() for r in records)
    # And it names the consequence, not just the site: whoever reads this line needs to know the
    # span went out uncleaned rather than being dropped.
    assert any("unscrubbed" in r.getMessage() for r in records)
