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


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_no_command_prints_a_secret_value(path, capsys):
    """PRD S20.6: secrets never appear in configuration output or support bundles."""
    for command in ("validate", "plan", "inventory", "values"):
        _, out = run([command, str(path)], capsys)
        text = out.out + out.err
        for marker in ("hunter2", "-----BEGIN", "sk-lf-", "AKIA"):
            assert marker not in text, f"{command} printed {marker}"


@pytest.mark.parametrize("command", sorted({
    "init", "install", "status", "doctor", "upgrade", "rollback", "backup", "restore",
    "uninstall", "support-bundle"}))
def test_unimplemented_commands_refuse_rather_than_silently_succeeding(command, capsys):
    """PRD S10 names twelve commands. The ones this release does not implement exit 2 and say so;
    accepting-and-ignoring is how an operator comes to believe a backup ran."""
    code, out = run([command], capsys)
    assert code == 2
    assert "not implemented" in out.err


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
