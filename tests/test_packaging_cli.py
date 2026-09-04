"""acpctl's own contract: exit codes, refusals, and the promise that this release writes nothing.

The read-only promise is the reason `acpctl plan` is safe to run against a production document
before anything exists, so it is asserted rather than documented.
"""
from __future__ import annotations

import pytest

from packaging_helpers import EXAMPLE_IDS, EXAMPLES, PACKAGING


def run(argv, capsys):
    from acpctl.cli import main
    code = main(argv)
    return code, capsys.readouterr()


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_validate_accepts_every_shipped_example(path, capsys):
    code, out = run(["validate", str(path)], capsys)
    assert code == 0, out.err


@pytest.mark.parametrize("command", ["validate", "plan", "inventory", "values"])
def test_every_read_only_command_refuses_an_invalid_document(command, tmp_path, capsys):
    import yaml

    from packaging_helpers import load_example
    doc = load_example("standard-production")
    doc["network"]["privateWorkers"] = False       # a rule, not a typo
    bad = tmp_path / "bad.acp-deployment.yaml"
    bad.write_text(yaml.safe_dump(doc))
    code, out = run([command, str(bad)], capsys)
    assert code == 1
    assert "network.private-workers" in out.err


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_plan_covers_every_section_the_prd_requires(path, capsys):
    """PRD S10 fixes the contents of a plan. A silently missing section reads as nothing to
    report, so the sections this release cannot fill are present and say why."""
    code, out = run(["plan", str(path)], capsys)
    assert code == 0
    for heading in ("1. Resources", "2. Images", "3. CPU, memory and storage",
                    "4. Replica ranges", "5. Network", "6. Secret references",
                    "7. Estimated monthly cost", "8. Destructive changes", "9. Migrations",
                    "10. Rollback implications"):
        assert heading in out.out, f"{heading} missing from the plan for {path.name}"


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_plan_states_it_creates_nothing(path, capsys):
    _, out = run(["plan", str(path)], capsys)
    assert "PLAN ONLY" in out.out


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_plan_does_not_present_an_unresolved_tag_as_a_pin(path, capsys):
    """PRD S5.1: cloud templates reference digests. Printing a tag where a digest belongs is how
    a plan reviewer comes to believe a deployment is pinned when it is not."""
    _, out = run(["plan", str(path)], capsys)
    assert "digest  <unresolved>" in out.out


def test_the_cost_section_says_not_available_rather_than_estimating():
    """A fabricated range would be quoted in a budget."""
    from acpctl.plan import render
    from packaging_helpers import load_example
    assert "NOT AVAILABLE" in render(load_example("standard-production"))


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_no_command_writes_anything(path, capsys, monkeypatch):
    """The read-only promise, enforced rather than described."""
    import builtins
    real_open = builtins.open

    def guarded(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"acpctl opened {file} for writing in a read-only release")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded)
    for command in ("validate", "plan", "inventory", "values"):
        assert run([command, str(path)], capsys)[0] == 0
    # `init` takes no spec and CAN write — but only with -o. Included here rather than exempted,
    # because "the command that may write a file writes nothing when you do not ask it to" is a
    # stronger statement than leaving it outside the sweep. tests/test_packaging_init.py owns the
    # -o path and the refusal to overwrite.
    assert run(["init", "--profile", "standard", "--platform", "azure"], capsys)[0] == 0


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_no_command_prints_a_secret_value(path, capsys):
    """PRD S20.6: secrets never appear in configuration output or support bundles."""
    for command in ("validate", "plan", "inventory", "values"):
        _, out = run([command, str(path)], capsys)
        text = out.out + out.err
        for marker in ("hunter2", "-----BEGIN", "sk-lf-", "AKIA"):
            assert marker not in text, f"{command} printed {marker}"
    # init GENERATES a document, so it is the command most able to invent a credential — a
    # placeholder password in generated output is one that gets committed with it.
    _, out = run(["init", "--profile", "standard", "--platform", "azure"], capsys)
    generated = out.out + out.err
    for marker in ("hunter2", "-----BEGIN", "sk-lf-", "AKIA"):
        assert marker not in generated, f"init printed {marker}"


def _unimplemented_commands():
    """DERIVED, NOT LISTED. This was a hardcoded set and it went stale the moment `doctor` was
    implemented — the test then demanded that a working command exit 2, which is a failure that
    says "you built the thing" rather than "you broke something". Reading the CLI's own table
    means implementing a command updates this test by construction."""
    from acpctl.cli import NOT_YET_IMPLEMENTED
    return sorted(NOT_YET_IMPLEMENTED)


@pytest.mark.parametrize("command", _unimplemented_commands())
def test_unimplemented_commands_refuse_rather_than_silently_succeeding(command, capsys):
    """PRD S10 names twelve commands. The ones this release does not implement exit 2 and say so;
    accepting-and-ignoring is how an operator comes to believe a backup ran."""
    code, out = run([command], capsys)
    assert code == 2
    assert "not implemented" in out.err


def test_the_implemented_commands_are_not_also_listed_as_unimplemented():
    """The other direction. A command can be built and left in NOT_YET_IMPLEMENTED, in which case
    argparse registers the stub over the real one and the feature is unreachable from the CLI
    while every unit test of its module passes."""
    from acpctl.cli import NOT_YET_IMPLEMENTED, build_parser
    parser = build_parser()
    sub = next(a for a in parser._actions if hasattr(a, "choices") and a.choices)
    for name in ("validate", "plan", "inventory", "values", "doctor"):
        assert name in sub.choices, f"{name} is not registered as a command"
        assert name not in NOT_YET_IMPLEMENTED, (
            f"{name} is implemented but still listed as not-yet-implemented, so the CLI serves "
            "the stub")


def test_the_cli_lists_every_prd_command():
    """No command from PRD S10 may be simply absent from --help."""
    from acpctl.cli import NOT_YET_IMPLEMENTED, build_parser
    parser = build_parser()
    actions = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
    commands = set(actions[0].choices)
    expected = {"init", "validate", "plan", "install", "status", "doctor", "upgrade", "rollback",
                "backup", "restore", "uninstall", "support-bundle"}
    assert expected <= commands, f"missing from acpctl: {sorted(expected - commands)}"
    assert set(NOT_YET_IMPLEMENTED) < expected


def test_json_output_is_machine_readable(capsys):
    import json
    code, out = run(["inventory", str(EXAMPLES[0]), "--json"], capsys)
    assert code == 0
    assert json.loads(out.out)["services"]


def test_a_json_document_needs_no_yaml_dependency(tmp_path):
    """The installer bundle must not require PyYAML to read a spec it wrote as JSON."""
    import json

    from acpctl.spec import load_document, validate
    from packaging_helpers import load_example
    doc = load_example("standard-production")
    target = tmp_path / "spec.json"
    target.write_text(json.dumps(doc))
    assert validate(load_document(target)).ok


def test_the_examples_directory_is_not_empty():
    assert list((PACKAGING / "examples").glob("*.acp-deployment.yaml"))
