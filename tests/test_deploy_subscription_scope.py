"""deploy.sh must scope every `az` call to one subscription, without mutating the global default.

Regression under test: the script pinned its target with `az account set --subscription`, which
writes the choice into ~/.azure/azureProfile.json. That file is a GLOBAL default shared by every
shell, CI step and concurrent agent on the machine, and `az` has no per-invocation profile.

Observed failure (2026-07-09): a deploy built and pushed its image, then died at "3/5 registry
creds" with

    ERROR: The resource with name 'mdkaccessibilityacr' and type
    'Microsoft.ContainerRegistry/registries' could not be found in subscription
    'AZLABSV2.0-Sandbox(POC)'

because another process ran `az account set` between step 2 and step 3. The converse also bit:
a plain `bash deploy.sh` silently repointed the operator's own shell at the demo subscription
and left it there.

The fix resolves the subscription ID once in preflight and splices `--subscription <id>` into
every `az` invocation, so the run is immune to — and innocent of — concurrent default changes.
"""
from __future__ import annotations
import re
from pathlib import Path

import pytest

DEPLOY_SH = Path(__file__).resolve().parent.parent / "deploy" / "public" / "deploy.sh"


@pytest.fixture(scope="module")
def lines() -> list[str]:
    return DEPLOY_SH.read_text().splitlines()


def _code(lines: list[str]) -> list[tuple[int, str]]:
    """(1-indexed lineno, text) for lines that are not blank and not pure comments."""
    out = []
    for i, ln in enumerate(lines, 1):
        if ln.strip() and not ln.lstrip().startswith("#"):
            out.append((i, ln))
    return out


# An `az ...` invocation, matched only in COMMAND position: at the start of a line, or right
# after a construct that begins a command (`$(`, `&&`, `||`, `;`, `|`, `if`, `then`, `do`,
# `_retry`). Matching a bare `az\s` anywhere would also hit the word "az" inside quoted prose —
# e.g. the error string `... (az login?)` — which is not a call.
_AZ_CALL = re.compile(r"(?:^|\$\(|&&|\|\||;|\||\bif\b|\bthen\b|\bdo\b|_retry\s)\s*az\s")

# The two preflight resolvers are the ONLY calls allowed to run unscoped: they are what
# *determines* the scope. Both are `az account show`, and neither writes anything.
_RESOLVER = re.compile(r"az account show\b")


def test_no_global_subscription_mutation(lines):
    """`az account set` writes a machine-global default. It must not appear in executable code."""
    offenders = [(n, ln.strip()) for n, ln in _code(lines) if "az account set" in ln]
    assert offenders == [], (
        "deploy.sh mutates the shared az default; use --subscription per call instead:\n"
        + "\n".join(f"  L{n}: {t}" for n, t in offenders)
    )


def test_every_az_call_is_subscription_scoped(lines):
    """Every `az` call carries "${AZ[@]}" — except the preflight resolvers that compute it."""
    unscoped = [
        (n, ln.strip())
        for n, ln in _code(lines)
        if _AZ_CALL.search(ln) and "${AZ[@]}" not in ln and not _RESOLVER.search(ln)
    ]
    assert unscoped == [], (
        'these `az` calls would follow the machine-global default subscription:\n'
        + "\n".join(f"  L{n}: {t}" for n, t in unscoped)
    )


def test_the_scope_array_is_defined_before_first_use(lines):
    code = _code(lines)
    defined = next((n for n, ln in code if re.match(r"\s*AZ=\(", ln)), None)
    assert defined, 'preflight must define the scope array: AZ=(--subscription "$SUB")'
    # >=, not >: the defining line carries a trailing comment that names "${AZ[@]}".
    first_use = next((n for n, ln in code if "${AZ[@]}" in ln), None)
    assert first_use and first_use >= defined, "AZ[@] is used before it is defined"


def test_scope_pins_the_immutable_id_not_the_name(lines):
    """A subscription can be renamed mid-run; its ID cannot. Resolve name -> id once, pin the id."""
    src = "\n".join(ln for _, ln in _code(lines))
    assert re.search(r'SUB="\$\(az account show .*--query id -o tsv', src), \
        "preflight must resolve the subscription to its ID"
    assert 'AZ=(--subscription "$SUB")' in src, "the scope array must pin the resolved ID"


def test_preflight_fails_closed_when_no_subscription_resolves(lines):
    """A deploy that cannot name its target must abort, not silently use whatever az defaults to."""
    src = "\n".join(ln for _, ln in _code(lines))
    guards = re.findall(r'\[ -n "\$SUB" \] \|\| \{[^}]*exit 1', src)
    assert len(guards) == 2, (
        "both the explicit (ACP_SUBSCRIPTION) and implicit (az default) paths must abort "
        f"when the subscription does not resolve; found {len(guards)} guard(s)"
    )


def test_write_path_calls_are_scoped(lines):
    """The calls that actually mutate Azure are the ones a mis-scope would damage."""
    src = "\n".join(ln for _, ln in _code(lines))
    for verb in ("containerapp update", "containerapp create", "containerapp secret set",
                 "containerapp registry set", "acr build"):
        for m in re.finditer(rf"az {re.escape(verb)}(.*)", src):
            assert "${AZ[@]}" in m.group(0), f"unscoped write call: az {verb}"
