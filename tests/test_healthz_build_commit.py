"""`/healthz` names the commit it was built from — the build-provenance chain, end to end.

WHY THIS EXISTS. `version` answers "which build" and `built_at` answers "when". Neither answers
"is THIS commit live?", which is the only question a deploy verification actually has. On
2026-09-06 answering it took a CalVer stamp, two workflow-run timestamps and a cancelled deploy
run to disambiguate — and the result was still an inference from when a build happened rather
than from what it contained.

The field is only worth having if the whole chain carries it, so these tests walk all four links
rather than just the last one:

    deploy.sh / redeploy.sh  --build-arg BUILD_SHA
      -> Dockerfile          ARG BUILD_SHA -> ENV ACP_BUILD_SHA
        -> _build_info()     reads it
          -> /healthz        reports it

A test that only checked the Python would pass just as happily against a build arg nobody passes,
which is precisely how a provenance field comes to read `null` in production forever.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

DOCKERFILE = (ACP / "deploy" / "public" / "Dockerfile").read_text()
DEPLOY_SH = (ACP / "deploy" / "public" / "deploy.sh").read_text()
REDEPLOY_SH = (ACP / "deploy" / "public" / "redeploy.sh").read_text()


# ── the app reports it ───────────────────────────────────────────────────────

def test_the_commit_is_reported_when_the_image_carries_one(monkeypatch):
    import routes.system as system
    monkeypatch.setenv("ACP_BUILD_SHA", "d914f31425fac1df0216a27b7442d0cbc105c320")
    assert system._build_info()["commit"] == "d914f31425fac1df0216a27b7442d0cbc105c320"


def test_an_image_that_cannot_name_its_commit_reports_null_not_a_guess(monkeypatch):
    """An older image predating this field, or one from a bare `docker build`. Null is the honest
    answer; a placeholder would be a commit nobody can look up, presented as if they could."""
    import routes.system as system
    monkeypatch.delenv("ACP_BUILD_SHA", raising=False)
    assert system._build_info()["commit"] is None
    for blank in ("", "   "):
        monkeypatch.setenv("ACP_BUILD_SHA", blank)
        assert system._build_info()["commit"] is None


def test_the_commit_is_a_report_and_never_a_health_gate(monkeypatch):
    """`ok` exists to catch an image that never went through deploy.sh. An image that is stamped
    but predates this field is not unhealthy, and must not start failing a health check because a
    provenance field was added after it shipped."""
    import routes.system as system
    monkeypatch.setenv("ACP_BUILD_VERSION", "2026.9.6.11")
    monkeypatch.delenv("ACP_BUILD_SHA", raising=False)
    info = system._build_info()
    assert info["commit"] is None
    assert info["version_stamped"] is True

    # ...and the converse: a commit cannot rescue an unstamped image.
    monkeypatch.setenv("ACP_BUILD_VERSION", "dev")
    monkeypatch.setenv("ACP_BUILD_SHA", "d914f31425fac1df0216a27b7442d0cbc105c320")
    assert system._build_info()["version_stamped"] is False


def test_healthz_carries_the_commit_on_the_wire(monkeypatch):
    """Through the route, not just the helper — the helper's return value is not the contract."""
    import core
    import routes.system as system
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setenv("ACP_BUILD_VERSION", "2026.9.6.11")
    monkeypatch.setenv("ACP_BUILD_SHA", "d914f31425fac1df0216a27b7442d0cbc105c320")
    body = TestClient(app).get("/healthz").json()
    assert body["commit"] == "d914f31425fac1df0216a27b7442d0cbc105c320"
    assert body["ok"] is True
    # The fields that were already there must keep their meaning.
    for key in ("service", "rubric_hash", "version", "built_at", "version_stamped"):
        assert key in body, key


def test_the_published_schema_documents_the_field():
    """/healthz is in the publicly-readable Swagger document. A response field absent from it is
    one an integrator has no way to know exists."""
    from routes.openapi_health import HEALTH_OPENAPI_SPEC
    props = HEALTH_OPENAPI_SPEC["components"]["schemas"]["HealthzResponse"]["properties"]
    assert "commit" in props
    assert props["commit"]["nullable"] is True


# ── the build chain actually passes it ───────────────────────────────────────

def test_the_dockerfile_accepts_the_build_arg_and_exports_it():
    assert "ARG BUILD_SHA=" in DOCKERFILE
    assert "ACP_BUILD_SHA=$BUILD_SHA" in DOCKERFILE


def test_the_dockerfile_default_is_empty_rather_than_a_placeholder():
    """`ARG BUILD_SHA=` with nothing after it. A default like `dev` or `unknown` would reach
    _build_info as a truthy string and be reported as though it were a commit."""
    arg_line = next(line for line in DOCKERFILE.splitlines()
                    if line.startswith("ARG BUILD_SHA"))
    assert arg_line.strip() == "ARG BUILD_SHA="


# The two scripts quote their build args differently; each is asserted as it is actually
# written, because what matters is that the ARGUMENT is passed — not that the two words appear
# somewhere in the same file. Parametrised over NAMES, with the source looked up inside: passing
# the file contents as a parameter puts the whole script into pytest's generated test id, which
# turned one failure into 49KB of output.
_BUILD_ARG = {"deploy.sh": '--build-arg BUILD_SHA="$BUILD_SHA"',
              "redeploy.sh": '--build-arg "BUILD_SHA=$BUILD_SHA"'}


@pytest.mark.parametrize("script", sorted(_BUILD_ARG))
def test_both_deploy_paths_pass_the_commit_to_the_build(script):
    """redeploy.sh is what production runs; deploy.sh is the first-deploy path. A field wired
    into only one of them is null on exactly the deploys nobody remembers to check.

    THE PAIRING IS THE ASSERTION. This test first read `"BUILD_SHA=" in source and "--build-arg"
    in source`, which a mutation removing the build arg passed happily: `BUILD_SHA="$PIN"` still
    defined the variable and `--build-arg BUILD_VERSION` still matched the other half. Two
    substrings co-occurring in one file says nothing about whether they are connected — the exact
    shape of a check that cannot fail.
    """
    source = DEPLOY_SH if script == "deploy.sh" else REDEPLOY_SH
    assert _BUILD_ARG[script] in source, \
        f"{script} no longer passes the commit to az acr build"


def test_redeploy_stamps_the_resolved_pin_rather_than_re_deriving_it():
    """redeploy.sh clones and checks out `$PIN` — the sha it resolved precisely so a pin could not
    be taken verbatim and mean something else later. Stamping that value states the intent;
    re-deriving from a cwd would be a second source of truth for one fact."""
    assert 'BUILD_SHA="$PIN"' in REDEPLOY_SH


def test_deploy_sh_marks_a_dirty_tree_because_it_builds_from_the_working_directory():
    """The asymmetry that matters. redeploy.sh builds from a fresh clone at a resolved pin, so it
    is clean by construction. deploy.sh uploads the WORKING DIRECTORY as build context, where a
    bare sha would name a tree that is not what shipped — an identity wrong in the one direction
    that sends someone diffing the wrong code against an incident."""
    assert "git diff-index --quiet HEAD" in DEPLOY_SH
    assert '-dirty' in DEPLOY_SH
    # redeploy.sh needs no such marker, and asserting its absence keeps the asymmetry deliberate
    # rather than something a later edit copies across without the reason.
    assert "-dirty" not in REDEPLOY_SH
