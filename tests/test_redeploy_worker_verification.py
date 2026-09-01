"""The worker services must be verified by asking THEM, per role — not by asking ACA what it was
told, and not through the shared heartbeat key.

WHAT WENT WRONG, measured on 2026-09-01. Production's app rolled 2026.9.1.12 -> .23 across roughly
eleven deploys. Every one ran `az containerapp update -n acp-worker --image <new>`, confirmed
`properties.template.containers[0].image` matched, and printed `acp-worker ✓`. The live worker tier
reported an image built on 31 August throughout.

TWO GAPS, and this file pins both, plus the trap that turned the first attempt at fixing them into
a check that could never fail.

1. The ✓ read the TEMPLATE — the image ACA was told to run, which equals the image being run only
   if the new revision actually replaces the running replicas. The app never had this problem
   because step 9 verifies it through /healthz. The worker services had no equivalent, so the
   tiers that could drift silently were the ones nothing interrogated.
2. Nothing in this repo asserted the worker services' REVISION MODE. The restore block named $APP
   only, and no script sets their mode either. With no ingress there is no traffic weight to
   strand an old revision at 0% — it just keeps running and keeps claiming jobs.

AND THE TRAP. The obvious check — compare /readyz's `workers.version` against the build — is
WRONG, because that field comes from a single key every worker overwrites; with two services it
reports whichever beat last, so the same deploy would pass or fail at random. The check must read
`workers.roles.<role>.version`. See tests/test_worker_roles_status.py.

Source-level, deliberately: `az` and `curl` cannot run here, and the property under test is which
SURFACE each check interrogates. tests/test_az_subscription_scope.py takes the same approach to
the same file.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REDEPLOY = ROOT / "deploy" / "public" / "redeploy.sh"
SRC = REDEPLOY.read_text()

# Comments stripped for structural assertions: the comments here quote the very strings under
# test (they record the incident), so asserting on prose instead of code is a live risk.
CODE = re.sub(r"^\s*#.*$", "", SRC, flags=re.M)


def _embedded_program() -> str:
    """The python3 -c program step 9b runs, lifted OUT of the script.

    Extracted rather than retyped so these tests exercise the shipped code. A retyped copy is how
    a broken embedded program passes its own test.
    """
    m = re.search(r"python3 -c '\n(.*?)\n' \"\$BUILD_VERSION\"", SRC, re.S)
    assert m, "could not find step 9b's embedded program"
    return m.group(1)


def _run_extractor(payload: str, want: str = "2026.9.2.1") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", _embedded_program(), want],
                          input=payload, capture_output=True, text=True)


# ── the trap: a check that cannot go red ──────────────────────────────────────────────────
def test_the_embedded_program_actually_compiles():
    """THE bite that mattered. The first version used an f-string containing an escaped quote —

        print(f"{role}={r.get(\\"version\\")}")

    which is a SyntaxError. Python wrote to stderr, the shell swallowed it, `_STALE` came back
    empty, and step 9b printed its ✓ on every input. A check that cannot fail is worse than no
    check, and nothing but running it would have shown that.
    """
    compile(_embedded_program(), "<embedded>", "exec")


def test_the_extractor_reports_a_role_on_the_wrong_build():
    r = _run_extractor('{"workers":{"roles":{"mixed":{"version":"2026.9.2.1"},'
                       '"discovery":{"version":"2026.8.31.20"}}}}')
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "discovery=2026.8.31.20"


def test_the_extractor_is_silent_when_every_role_matches():
    """The ✓ path has to be reachable, or the warning becomes noise everyone learns to skip."""
    r = _run_extractor('{"workers":{"roles":{"mixed":{"version":"2026.9.2.1"},'
                       '"discovery":{"version":"2026.9.2.1"}}}}')
    assert r.stdout.strip() == "" and r.returncode == 0


def test_the_extractor_reports_every_stale_role_not_just_the_first():
    r = _run_extractor('{"workers":{"roles":{"mixed":{"version":"2026.8.31.39"},'
                       '"discovery":{"version":"2026.8.31.20"}}}}')
    assert sorted(r.stdout.split()) == ["discovery=2026.8.31.20", "mixed=2026.8.31.39"]


def test_the_extractor_survives_an_api_without_the_roles_field():
    """A deploy can outrun the API version it is talking to. An older /readyz must read as
    'nothing to report', not as a crash or a false alarm."""
    r = _run_extractor('{"workers":{"version":"2026.8.31.39"}}')
    assert r.stdout.strip() == "" and r.returncode == 0


def test_the_extractor_survives_a_roles_error_payload():
    """/readyz reports {"error": ...} when the role read itself failed."""
    r = _run_extractor('{"workers":{"roles":{"error":"Boom: x"}}}')
    assert r.stdout.strip() == "" and r.returncode == 0


def test_a_null_version_is_not_treated_as_stale():
    """A heartbeat predating the version field reports null. That is 'unknown', not 'wrong', and
    warning on it would fire against every worker that has not redeployed onto the field yet."""
    r = _run_extractor('{"workers":{"roles":{"mixed":{"version":null}}}}')
    assert r.stdout.strip() == ""


def test_garbage_input_does_not_crash_the_deploy():
    """curl fails, or returns an error page. `set -euo pipefail` is on."""
    r = _run_extractor("not json at all")
    assert r.returncode == 0 and r.stdout.strip() == ""


# ── which surface each check reads ────────────────────────────────────────────────────────
def test_the_worker_check_reads_the_per_role_key_not_the_shared_one():
    """The whole correction. `workers.version` is last-writer-wins across services; comparing it
    against the build passes or fails at random once two services run."""
    assert '["workers"].get("roles")' in SRC, "step 9b must read workers.roles"
    tail = CODE[CODE.index("_ROLES_JSON"):]
    assert not re.search(r'"version":\\"\$BUILD_VERSION', tail), \
        "must not compare the shared workers.version against the build"


def test_the_template_check_still_exists_and_is_a_different_question():
    """Step 8 asks ACA what it was told; step 9b asks the service what it runs. Both belong."""
    assert "properties.template.containers[0].image" in CODE
    assert "_ROLES_JSON" in CODE


def test_a_stale_role_warning_names_the_role_and_the_expected_build():
    """A warning that does not say WHICH role and WHICH versions sends the reader to the console.
    The incident was diagnosable only because both strings were visible together."""
    warn = CODE[CODE.index("_ROLES_JSON"):]
    assert "$BUILD_VERSION" in warn and "_STALE" in warn


def test_the_warning_tells_the_reader_what_to_run_next():
    assert "activeRevisionsMode" in SRC and "revision list" in SRC


def test_the_worker_check_does_not_fail_the_deploy():
    """Deliberate, with the reason written down: the condition is PRE-EXISTING, so dying here
    would red every deploy including the one shipping the cleanup. Making it fatal is the rollout
    owner's call. If this is ever flipped, flip it as a decision rather than by accident."""
    tail = CODE[CODE.index("_ROLES_JSON"):]
    assert "die " not in tail


# ── revision mode, for every app ──────────────────────────────────────────────────────────
def test_single_revision_mode_is_restored_for_all_three_apps():
    """The asymmetry that let the worker services drift: this named $APP only."""
    loop = re.search(r'for a in "\$APP" "\$WORKER" "\$DISCOVERY_WORKER"; do\s*\n\s*MODE=(.*?)\ndone',
                     CODE, re.S)
    assert loop, "revision mode is not restored for all three apps in one loop"
    body = loop.group(1)
    assert "revision set-mode" in body and "--mode single" in body
    assert '-n "$a"' in body, "set-mode must target the loop variable, not a hardcoded app"


def test_the_mode_restore_defaults_to_single_when_the_query_fails():
    """`|| echo Single` stops a failed read reading as 'Multiple' and triggering a set-mode
    against an app whose state is unknown."""
    assert re.search(r'activeRevisionsMode -o tsv 2>/dev/null \|\| echo Single', CODE)


def test_the_blue_green_path_is_untouched_by_the_restore():
    """Blue-green deliberately LEAVES the app in Multiple mode, keeping blue at 0% for rollback,
    and exits before this block. Restoring Single there would deactivate the rollback target."""
    assert CODE.index("ROLLBACK") < CODE.index('for a in "$APP" "$WORKER" "$DISCOVERY_WORKER"; do\n  MODE=')


def test_the_script_still_parses():
    assert subprocess.run(["bash", "-n", str(REDEPLOY)]).returncode == 0
