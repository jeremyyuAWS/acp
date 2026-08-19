"""The deployment preflight (scripts/preflight.py).

WHAT IT IS FOR. Every dependency it checks fails SILENTLY and in the reassuring direction: RunPod
configured but not selected still does vision, on the CPU floor, with no error; Azure unset just
hides a button; Langfuse unset makes every lf.* call a no-op so runs trace nothing. None of them
raise. A preflight that reported those as fine would be worse than no preflight, so what is pinned
here is the CLASSIFICATION, not the plumbing:

  PASS   only when something was executed or resolved and the answer was right
  WARN   configured-but-unverified, deliberately off, or not checkable here
  FAIL   configured-and-wrong, which is the only state that should stop a deploy

The two cases that carry their weight are the silent-fallback trap (RunPod set, provider unset →
FAIL, not PASS) and the phase-lane check, which is what would have caught the Discover tracing gap:
`lf.discover_span` existed all along; nothing on the discover path called it.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

_ENV = ("RUNPOD_ENDPOINT_ID", "RUNPOD_API_KEY", "ACP_VISION_PROVIDER", "ACP_AZURE_CLIENT_ID",
        "ACP_AZURE_TENANT_ID", "LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
        "ACP_TRACE_DISCOVER_FILES", "ACP_TRACE_FILENAMES")


@pytest.fixture()
def pf(monkeypatch):
    """A freshly imported preflight with a clean env — it reads os.environ at call time, but lf
    reads it at IMPORT, so both have to start from a known state.

    AND IT HAS TO BE PUT BACK. `_with_langfuse` below reloads lf with credentials set, and a
    reloaded module's globals outlive monkeypatch's env teardown — so without this, lf stays
    _ENABLED=True pointing at a fake host for the REST OF THE SESSION, and the next test that
    touches a traced path tries to reach it. That surfaced as a stray "Unexpected error occurred"
    from the langfuse SDK at the end of an otherwise green run: not a failure, just a suite
    quietly making network calls it was never asked to make.
    """
    import lf
    for v in _ENV:
        monkeypatch.delenv(v, raising=False)
    spec = importlib.util.spec_from_file_location("preflight", ROOT / "scripts" / "preflight.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.results.clear()
    yield mod
    # Restore lf to the credential-free state the rest of the suite expects.
    importlib.reload(lf)



def _with_langfuse(monkeypatch, **extra):
    """Set the Langfuse env AND reload lf.

    lf reads its config at IMPORT time, and pytest keeps it in sys.modules across the session, so
    setting the vars alone leaves _ENABLED stale from whatever imported it first. A reload is what
    a fresh process gives you for free — which is how preflight actually runs, as a CLI.
    """
    import importlib
    monkeypatch.setenv("LANGFUSE_HOST", "http://lf")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)
    import lf
    importlib.reload(lf)


def state(pf, check):
    return next((r["state"] for r in pf.results if r["check"] == check), None)


def detail(pf, check):
    return next((r["detail"] for r in pf.results if r["check"] == check), "")


# ── the silent-fallback trap ─────────────────────────────────────────────────

def test_runpod_configured_but_not_selected_is_a_FAIL(pf, monkeypatch):
    """The whole reason this is code and not a doc line. Endpoint and key set, ACP_VISION_PROVIDER
    forgotten → `choice` defaults to 'ollama', the GPU is never selected, nothing errors, and the
    only symptom is that vision is slow — which reads as "the GPU is not very fast"."""
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "abc123")
    monkeypatch.setenv("RUNPOD_API_KEY", "secret")
    pf.check_gpu(live=False)
    assert state(pf, "ACP_VISION_PROVIDER") == pf.FAIL
    assert state(pf, "resolved provider") == pf.FAIL
    assert "CPU floor" in detail(pf, "ACP_VISION_PROVIDER")


def test_nothing_configured_is_a_WARN_not_a_FAIL(pf):
    """A deployment that has deliberately not attached a GPU is not broken. FAIL has to stay
    reserved for configured-and-wrong or it stops meaning anything."""
    pf.check_gpu(live=False)
    assert state(pf, "RUNPOD_ENDPOINT_ID") == pf.WARN
    assert state(pf, "ACP_VISION_PROVIDER") == pf.WARN


def test_a_fully_configured_gpu_resolves_to_the_gpu_provider(pf, monkeypatch):
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "abc123")
    monkeypatch.setenv("RUNPOD_API_KEY", "secret")
    monkeypatch.setenv("ACP_VISION_PROVIDER", "runpod_serverless")
    pf.check_gpu(live=False)
    assert state(pf, "ACP_VISION_PROVIDER") == pf.PASS
    assert state(pf, "resolved provider") == pf.PASS
    assert "runpod_serverless" in detail(pf, "resolved provider")


def test_a_wrong_provider_name_is_not_silently_accepted(pf, monkeypatch):
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "abc123")
    monkeypatch.setenv("RUNPOD_API_KEY", "secret")
    monkeypatch.setenv("ACP_VISION_PROVIDER", "runpod")        # plausible, and wrong
    pf.check_gpu(live=False)
    assert state(pf, "ACP_VISION_PROVIDER") == pf.WARN
    assert state(pf, "resolved provider") == pf.FAIL


def test_an_offline_run_never_claims_the_endpoint_was_reached(pf, monkeypatch):
    """"We did not look" must not borrow PASS from the checks that did run."""
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "abc123")
    monkeypatch.setenv("RUNPOD_API_KEY", "secret")
    monkeypatch.setenv("ACP_VISION_PROVIDER", "runpod_serverless")
    pf.check_gpu(live=False)
    assert state(pf, "endpoint reachable") == pf.WARN
    assert "--live" in detail(pf, "endpoint reachable")


# ── SharePoint ───────────────────────────────────────────────────────────────

def test_scopes_are_read_from_the_app_not_restated(pf):
    """A preflight carrying its own copy of the scope list is a second source of truth, and it
    fails in the worst direction: it passes while the app asks for something else."""
    pf.check_sharepoint()
    d = detail(pf, "delegated scopes")
    src = (ROOT / "frontend" / "src" / "sharepointScopes.js").read_text()
    for scope in ("User.Read", "Files.Read.All", "Sites.Read.All"):
        assert scope in d and scope in src


def test_the_read_only_posture_is_asserted_not_assumed(pf):
    pf.check_sharepoint()
    assert state(pf, "read-only posture") == pf.PASS


def test_delegated_token_acquisition_is_reported_as_unverifiable(pf):
    """It needs a human at a browser. Reporting PASS off the config alone would be exactly the
    "we did not look, so it must be fine" this script exists to prevent."""
    pf.check_sharepoint()
    assert state(pf, "token acquisition") == pf.WARN
    assert "delegated" in detail(pf, "token acquisition").lower()


# ── tracing ──────────────────────────────────────────────────────────────────

def test_tracing_off_is_stated_with_what_it_costs(pf):
    pf.check_tracing(live=False)
    assert state(pf, "credentials") == pf.WARN
    assert "no-op" in detail(pf, "credentials")


def test_all_three_phase_lanes_are_detected_wired(pf, monkeypatch):
    """The check that would have caught the Discover gap. `lf.discover_span` existed the whole
    time — the defect was that nothing on the discover path called it, so this asks whether a
    CALLER exists, not whether the function does."""
    _with_langfuse(monkeypatch)
    pf.check_tracing(live=False)
    for phase in ("Discover", "Assess", "Remediate"):
        assert state(pf, f"{phase} lane wired") == pf.PASS, phase


def test_plain_filenames_are_flagged_for_a_phi_estate(pf, monkeypatch):
    _with_langfuse(monkeypatch, ACP_TRACE_FILENAMES="plain")
    pf.check_tracing(live=False)
    assert state(pf, "filename redaction") == pf.WARN
    assert "PHI" in detail(pf, "filename redaction")


# ── exit code ────────────────────────────────────────────────────────────────

def test_only_FAIL_sets_a_nonzero_exit(pf, monkeypatch):
    """A deploy gate that trips on WARN gets disabled within a week. Warns inform; fails stop."""
    monkeypatch.setattr(sys, "argv", ["preflight"])
    assert pf.main() == 0                                  # nothing configured → all warns
    pf.results.clear()
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "abc123")
    monkeypatch.setenv("RUNPOD_API_KEY", "secret")         # the trap → fail
    assert pf.main() == 1


def test_no_secret_value_is_ever_printed(pf, monkeypatch, capsys):
    monkeypatch.setenv("RUNPOD_API_KEY", "super-secret-key-value")
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "abc123")
    monkeypatch.setenv("ACP_VISION_PROVIDER", "runpod_serverless")
    monkeypatch.setattr(sys, "argv", ["preflight"])
    pf.main()
    assert "super-secret-key-value" not in capsys.readouterr().out
