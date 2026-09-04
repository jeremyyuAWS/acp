"""`acpctl init` — and the one invariant that makes a generator worth having.

EVERY DOCUMENT IT EMITS MUST PASS `validate`, for every legal (profile, platform) pair. A
generator whose output its own validator rejects is worse than no generator: it teaches an
operator that the tool is unreliable at the moment they are learning to trust it.

That invariant is not a formality here. The contract has 37 semantic rules on top of its schema
and they interact — and the first draft of `init` failed 12 of the 16 combinations, twice, for two
different reasons the matrix test found immediately:

  * invented telemetry exporter names (`otlp`, `aws-otel`) instead of reading the schema's enum
  * replica ceilings on the single-machine evaluation profile that needed 372 Postgres
    connections against an embedded server declared at 100

Both were caught by running the real validator over the real output rather than by reading the
generator, which is why the matrix is the first test in this file.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from packaging_helpers import PACKAGING

ROOT = Path(__file__).resolve().parent.parent

# Every legal pair, derived from the generator's own table so a profile or platform added later
# is covered without anyone remembering this file.
def _combinations():
    from acpctl.init_doc import PROFILE_PLATFORMS
    return [(profile, platform)
            for profile, platforms in sorted(PROFILE_PLATFORMS.items())
            for platform in platforms]


COMBINATIONS = _combinations()
COMBINATION_IDS = [f"{p}-on-{q}" for p, q in COMBINATIONS]


def generate(profile: str, platform: str, **kw):
    from acpctl.init_doc import build
    defaults = dict(name="acp", environment="production", release="2026.9")
    if profile == "evaluation":
        defaults["environment"] = "development"
    defaults.update(kw)
    return build(profile=profile, platform=platform, **defaults)


def run_cli(*args, cwd=None):
    env = {**os.environ, "PYTHONPATH": str(PACKAGING / "cli")}
    return subprocess.run([sys.executable, "-m", "acpctl", "init", *args],
                          capture_output=True, text=True, env=env,
                          cwd=str(cwd or ROOT), timeout=120)


# ── the invariant ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("profile,platform", COMBINATIONS, ids=COMBINATION_IDS)
def test_every_generated_document_is_valid(profile, platform):
    """THE TEST THIS COMMAND EXISTS TO PASS."""
    from acpctl.spec import validate
    result = validate(generate(profile, platform))
    assert result.ok, "\n".join(f.render() for f in result.errors)


@pytest.mark.parametrize("profile,platform", COMBINATIONS, ids=COMBINATION_IDS)
def test_the_rendered_yaml_round_trips_to_the_document_it_came_from(profile, platform):
    """WHAT MAKES HAND-AUTHORED YAML SAFE.

    The rendered file is assembled as text so it can carry comments — the notes explaining why a
    worker scales on queue depth are worth more to a reader than the keys they sit above. The risk
    is malformed output; the mitigation is that each section's body is dumped by PyYAML and this
    test parses the whole thing back and requires it to equal the dict. A formatting error is a
    red test rather than an operator's confusing parse failure.
    """
    from acpctl.init_doc import render
    document = generate(profile, platform)
    assert yaml.safe_load(render(document)) == document


@pytest.mark.parametrize("profile,platform", COMBINATIONS, ids=COMBINATION_IDS)
def test_the_rendered_file_validates_after_a_round_trip(profile, platform):
    """Belt and braces, and not redundant: the two tests above could both pass while the RENDERED
    text validated differently from the dict — a quoted `'2026.9'` that parsed back as a float,
    say. This checks the artefact an operator actually feeds to the next command."""
    from acpctl.init_doc import render
    from acpctl.spec import validate
    parsed = yaml.safe_load(render(generate(profile, platform)))
    assert validate(parsed).ok


# ── what it must refuse ───────────────────────────────────────────────────────

def test_an_impossible_combination_is_refused_before_anything_is_generated():
    """`evaluation` is single-machine Compose by contract. Emitting a document for it on Azure and
    letting `validate` reject it would be a worse experience than refusing, and the refusal names
    the rule so the operator learns why rather than just that."""
    from acpctl.init_doc import InitError, build
    with pytest.raises(InitError) as exc:
        build(profile="evaluation", platform="azure", name="acp",
              environment="development", release="2026.9")
    assert "profile.platform" in str(exc.value)


@pytest.mark.parametrize("profile", ["standard", "regulated", "high-availability"])
def test_the_production_profiles_refuse_compose(profile):
    from acpctl.init_doc import InitError, build
    with pytest.raises(InitError):
        build(profile=profile, platform="compose", name="acp",
              environment="production", release="2026.9")


def test_an_unknown_profile_is_refused_with_the_list():
    from acpctl.init_doc import InitError, build
    with pytest.raises(InitError) as exc:
        build(profile="hardened", platform="azure", name="acp",
              environment="production", release="2026.9")
    assert "standard" in str(exc.value)


# ── secrets ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("profile,platform", COMBINATIONS, ids=COMBINATION_IDS)
def test_no_generated_document_contains_a_secret_value(profile, platform):
    """PRD S13. A generator that emitted a placeholder password would be a generator whose output
    gets committed with it."""
    from acpctl.init_doc import render
    text = render(generate(profile, platform))
    for marker in ("password", "hunter2", "-----BEGIN", "AKIA", "sk-", "token:"):
        assert marker not in text.lower().replace("client_secret", ""), \
            f"{profile}/{platform} emitted something resembling a credential: {marker}"


@pytest.mark.parametrize("profile,platform", COMBINATIONS, ids=COMBINATION_IDS)
def test_the_required_secret_refs_are_present_and_come_from_the_validator(profile, platform):
    """init asks `spec.required_secret_names` — the function `validate` itself uses — rather than
    restating the rule. So a connector added later gets its secret into generated documents
    without anyone remembering init exists."""
    from acpctl.spec import required_secret_names
    document = generate(profile, platform)
    assert set(required_secret_names(document)) <= set(document["secrets"]["refs"])


def test_a_new_required_secret_flows_into_generated_documents(monkeypatch):
    """The control for the test above, and the reason it is not circular.

    Both sides could read the same empty list and agree. This adds a requirement to the
    validator's own function and asserts init picks it up — which is only true because init calls
    that function rather than keeping its own list.
    """
    from acpctl import spec as spec_mod
    real = spec_mod.required_secret_names
    monkeypatch.setattr(spec_mod, "required_secret_names",
                        lambda doc: list(real(doc)) + ["a-newly-required-secret"])
    document = generate("standard", "azure")
    assert "a-newly-required-secret" in document["secrets"]["refs"]


# ── the profile rules, on the generated output ────────────────────────────────

def test_regulated_gets_the_four_things_that_profile_means():
    """local-only AI, local telemetry, customer-managed keys and long retention — all four, or the
    profile's name is decorative. Asserted on the OUTPUT rather than on the generator's branches,
    so a refactor that drops one is caught."""
    document = generate("regulated", "azure")
    assert document["ai"]["mode"] == "local-only"
    assert document["observability"]["exporter"] == "local"
    assert document["data"]["objectStorage"]["encryption"] == "customer-managed"
    assert document["data"]["postgres"]["backupRetentionDays"] >= 30


def test_high_availability_gets_two_replicas_in_every_critical_tier():
    document = generate("high-availability", "aws")
    assert document["api"]["replicas"]["min"] >= 2
    for tier in ("discover", "assess", "remediate"):
        assert document["workers"][tier]["replicas"]["min"] >= 2, tier


def test_the_evaluation_profile_does_not_declare_headroom_it_cannot_use():
    """Compose has no autoscaler, so a ceiling above the floor describes capacity nothing can
    reach — while still costing the deployment its full Postgres connection budget. The first
    draft's evaluation defaults needed 372 connections against a server declared at 100, and the
    contract's `data.connection-budget` rule is what caught it."""
    document = generate("evaluation", "compose")
    assert document["api"]["replicas"]["min"] == document["api"]["replicas"]["max"]
    assert "autoscale" not in document["api"]
    for tier in document["workers"].values():
        assert "autoscale" not in tier


def test_every_platform_gets_a_data_mode_it_can_actually_provide():
    """Read from presets.PLATFORM_DATA_MODES rather than decided again here — a second opinion
    about what a platform offers is one that drifts from the validator."""
    from acpctl import presets
    for profile, platform in COMBINATIONS:
        document = generate(profile, platform)
        mode = document["data"]["postgres"]["mode"]
        assert mode in presets.PLATFORM_DATA_MODES[platform], f"{platform}: {mode}"


def test_every_platform_gets_a_secret_provider_it_can_resolve():
    from acpctl import presets
    for profile, platform in COMBINATIONS:
        document = generate(profile, platform)
        provider = document["secrets"]["provider"]
        assert provider in presets.PLATFORM_SECRET_PROVIDERS[platform], f"{platform}: {provider}"


# ── the command, and the write boundary ───────────────────────────────────────

def test_init_writes_nothing_without_an_output_path(capsys, monkeypatch):
    """THE READ-ONLY BOUNDARY, and init is inside it by default.

    Every other acpctl command writes nothing at all. init is the first with any reason to produce
    a file, so it produces TEXT and writing is opt-in — which keeps `acpctl init > acp.yaml` the
    ordinary use and keeps the guarantee precise rather than weakened.
    """
    import builtins

    from acpctl.cli import main
    real_open = builtins.open

    def guarded(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"acpctl init opened {file} for writing with no -o")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded)
    assert main(["init", "--profile", "standard", "--platform", "azure"]) == 0
    assert "apiVersion:" in capsys.readouterr().out


def test_writing_to_a_path_produces_a_file_the_other_commands_accept(tmp_path):
    """End to end through the real CLI: init writes, validate reads. The two halves of the
    contract meeting is the whole point of the command."""
    target = tmp_path / "acp.yaml"
    written = run_cli("--profile", "standard", "--platform", "azure", "-o", str(target))
    assert written.returncode == 0, written.stderr
    assert target.is_file()

    env = {**os.environ, "PYTHONPATH": str(PACKAGING / "cli")}
    checked = subprocess.run([sys.executable, "-m", "acpctl", "validate", str(target)],
                             capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=120)
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_it_refuses_to_overwrite_an_existing_document(tmp_path):
    """That file is the record of a deployment, possibly one already installed and hand-edited.
    Replacing it silently would destroy the only description of a running system."""
    target = tmp_path / "acp.yaml"
    target.write_text("# somebody's real deployment\n", encoding="utf-8")
    proc = run_cli("--profile", "standard", "--platform", "azure", "-o", str(target))
    assert proc.returncode == 1
    assert "refusing to overwrite" in proc.stderr
    assert target.read_text(encoding="utf-8") == "# somebody's real deployment\n"


def test_there_is_no_force_flag():
    """Deliberate. Removing the file yourself is one command, and it is a decision worth making
    explicitly rather than one a flag makes routine."""
    proc = run_cli("--help")
    assert "--force" not in proc.stdout


def test_the_impossible_combination_exits_one_from_the_cli(tmp_path):
    proc = run_cli("--profile", "evaluation", "--platform", "azure")
    assert proc.returncode == 1
    assert "cannot run on" in proc.stderr
    assert not list(tmp_path.iterdir()), "a refused init left a file behind"


def test_the_generated_document_names_what_the_operator_must_replace(tmp_path):
    """It is valid as generated but three values are placeholders. A document that validates and
    is nonsense in production is the failure mode of every generator; saying so in the file is
    what stops it."""
    proc = run_cli("--profile", "standard", "--platform", "azure")
    assert "publicUrl" in proc.stdout
    assert "placeholders" in proc.stdout
    assert "secrets.refs" in proc.stdout


def test_init_is_no_longer_advertised_as_unimplemented():
    from acpctl.cli import NOT_YET_IMPLEMENTED
    assert "init" not in NOT_YET_IMPLEMENTED
