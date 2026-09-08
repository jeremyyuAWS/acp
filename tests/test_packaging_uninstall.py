"""`acpctl uninstall` — the preview that changes nothing, and the data policy with no default.

THE TEST THAT MATTERS MOST HERE IS `test_a_preview_issues_no_mutating_command`. A preview is only
worth having if it is one, and "it printed what it would do" is indistinguishable from "it did it
and then printed" unless something reads the command log. Every other refusal in this file is
asserted the same way: exit code AND an empty mutation list, because a command that refuses after
it has already removed half the release has not refused.

THE SECOND THEME IS THE RETAINED LIST. ACP's Postgres, Redis and object storage are supplied by
the infrastructure adapter, not by the chart, so `helm uninstall` cannot touch them and neither
can this. An operator who reads "uninstalled" and assumes their data went with it goes looking for
a database that is still running and still being billed; one who assumes it was kept when it was
not has lost it. Both are avoidable by printing the list, so the tests require the list.

The fake cluster comes from tests/test_packaging_install.py rather than being copied. One
recording runner, shared, so an uninstall is tested against an installation the install tests
actually produced — two fakes would drift, and the first thing they would disagree about is what
an installed namespace looks like.
"""
from __future__ import annotations

import json

import pytest

from packaging_helpers import PACKAGING, load_example
from test_packaging_install import (
    CHART,
    EXAMPLE,
    FakeRunner,
    manifest_file,
    mutations,
    run_install,
)

MANIFEST_TEXT = """\
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: acp-production-api
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: acp-production-worker-assess
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: acp-production-default-deny
"""


def installed(**kwargs) -> FakeRunner:
    """A namespace holding a release this tool installed, ready to be removed."""
    kwargs.setdefault("release", {"status": "deployed", "revision": 3})
    kwargs.setdefault("manifest_text", MANIFEST_TEXT)
    kwargs.setdefault("state", _state())
    return FakeRunner(**kwargs)


def run_uninstall(runner, **kwargs):
    from acpctl.helm import Helm
    from acpctl.uninstall import uninstall

    kwargs.setdefault("namespace", "acp-production")
    lines: list[str] = []
    outcome = uninstall(str(EXAMPLE), helm=Helm(runner=runner), echo=lines.append, **kwargs)
    outcome.messages = lines
    return outcome


def text(outcome) -> str:
    return "\n".join(outcome.messages) + "\n" + outcome.reason


# ── the preview ──────────────────────────────────────────────────────────────

def test_a_preview_issues_no_mutating_command():
    """THE LOAD-BEARING TEST IN THIS FILE. Asserted on the recorded argv, not on the exit code:
    "it printed what it would do" and "it did it and then printed" produce the same 0."""
    runner = installed(pvcs=["data-acp-0"])
    outcome = run_uninstall(runner)
    assert outcome.code == 0
    assert outcome.changed is False
    assert mutations(runner) == []
    assert runner.release is not None, "the release was removed by a preview"
    assert runner.state is not None, "the installation record was removed by a preview"


def test_the_preview_lists_what_would_be_removed():
    runner = installed()
    body = text(run_uninstall(runner))
    assert "WOULD REMOVE" in body
    assert "helm release acp-production (revision 3, status deployed)" in body
    for obj in ("Deployment/acp-production-api", "NetworkPolicy/acp-production-default-deny"):
        assert obj in body
    assert "configmap/acp-installation" in body


def test_the_preview_lists_what_is_retained_and_says_it_is_never_touched():
    """The half that tools normally omit, and the one an operator most needs before they act."""
    body = text(run_uninstall(installed()))
    assert "RETAINED" in body
    for service in ("Postgres", "Redis", "Object storage"):
        assert service in body
    assert "Not touched, whatever --data-policy says" in body
    assert "supplied by the infrastructure adapter" in body


def test_the_preview_says_a_volume_needs_a_decision():
    body = text(run_uninstall(installed(pvcs=["data-acp-0", "data-acp-1"])))
    assert "data-acp-0" in body
    assert "--data-policy to decide" in body


def test_the_preview_says_so_when_there_are_no_volumes_at_all():
    """Rather than leaving --data-policy looking consequential when it has nothing to act on."""
    body = text(run_uninstall(installed(pvcs=[])))
    assert "owns NO in-cluster PersistentVolumeClaims" in body


def test_the_preview_names_the_command_that_would_act():
    body = text(run_uninstall(installed()))
    assert "PREVIEW ONLY" in body
    assert "--yes" in body and "--data-policy" in body


# ── the data policy ──────────────────────────────────────────────────────────

def test_acting_without_a_data_policy_is_a_usage_error():
    """No default, on purpose: `retain` and `delete` are opposite answers to a question only the
    operator can answer, and a default would be acpctl answering it for them."""
    runner = installed()
    outcome = run_uninstall(runner, assume_yes=True)
    assert outcome.code == 2
    assert "no default" in outcome.reason
    assert mutations(runner) == []


def test_deleting_data_without_typing_the_release_name_is_a_usage_error():
    runner = installed(pvcs=["data-acp-0"])
    outcome = run_uninstall(runner, assume_yes=True, data_policy="delete")
    assert outcome.code == 2
    assert "--confirm-name acp-production" in outcome.reason
    assert mutations(runner) == []


def test_a_mismatched_confirmation_name_is_refused():
    """More likely to mean the wrong namespace than a typo, which is exactly why it is checked."""
    runner = installed(pvcs=["data-acp-0"])
    outcome = run_uninstall(runner, assume_yes=True, data_policy="delete",
                            confirm_name="acp-staging")
    assert outcome.code == 1
    assert mutations(runner) == []


def test_an_unknown_data_policy_is_a_usage_error():
    runner = installed()
    outcome = run_uninstall(runner, assume_yes=True, data_policy="destroy-everything")
    assert outcome.code == 2
    assert mutations(runner) == []


def test_retain_removes_the_release_and_leaves_the_volumes():
    runner = installed(pvcs=["data-acp-0"])
    outcome = run_uninstall(runner, assume_yes=True, data_policy="retain")
    assert outcome.code == 0, outcome.reason
    assert runner.release is None, "the release was not removed"
    assert runner.pvcs == ["data-acp-0"], "a retain policy deleted a volume"
    assert not [argv for argv in runner.log if argv[1:3] == ["delete", "pvc"]]
    assert "no volume was deleted" in text(outcome)


def test_delete_removes_the_volumes_this_release_owns_and_only_by_selector():
    runner = installed(pvcs=["data-acp-0", "data-acp-1"])
    outcome = run_uninstall(runner, assume_yes=True, data_policy="delete",
                            confirm_name="acp-production")
    assert outcome.code == 0, outcome.reason
    assert runner.pvcs == []
    deletes = [argv for argv in runner.log if argv[1:3] == ["delete", "pvc"]]
    assert len(deletes) == 1
    assert "app.kubernetes.io/instance=acp-production" in deletes[0]
    assert "data-acp-0" in text(outcome)


def test_delete_with_no_volumes_says_nothing_was_deleted():
    """It must not print a reassuring "data deleted" that describes no event — a message that
    would send somebody away believing customer documents were destroyed when they are sitting in
    a storage account, untouched and still being billed."""
    runner = installed(pvcs=[])
    outcome = run_uninstall(runner, assume_yes=True, data_policy="delete",
                            confirm_name="acp-production")
    assert outcome.code == 0, outcome.reason
    assert "removed NO data" in text(outcome)
    assert not [argv for argv in runner.log if argv[1:3] == ["delete", "pvc"]]


def test_no_data_policy_reaches_outside_the_release():
    """Whatever the policy, the only mutations are helm's own uninstall and the two narrow
    kubectl writes. Nothing here can reach the adapter-supplied database, and that is a property
    of the command log rather than of the prose above it."""
    runner = installed(pvcs=["data-acp-0"])
    run_uninstall(runner, assume_yes=True, data_policy="delete", confirm_name="acp-production")
    for argv in mutations(runner):
        kind = argv[1:3]
        assert kind in (["uninstall", "acp-production"], ["apply", "-n"],
                        ["delete", "configmap"], ["delete", "pvc"]), argv


# ── the record ───────────────────────────────────────────────────────────────

def test_the_uninstall_is_recorded_before_the_record_is_removed():
    """Order matters: the ConfigMap must never be in a position of describing an installation
    that has already been removed without saying so."""
    runner = installed()
    outcome = run_uninstall(runner, assume_yes=True, data_policy="retain")
    assert outcome.code == 0, outcome.reason

    applied = [i for i, argv in enumerate(runner.log) if argv[1] == "apply"]
    deleted = [i for i, argv in enumerate(runner.log) if argv[1:3] == ["delete", "configmap"]]
    assert applied and deleted
    assert applied[-1] < deleted[-1], "the record was deleted before the entry was written"

    written = json.loads(json.loads(runner.stdins[applied[-1]])["data"]["installation.json"])
    assert written["history"][-1]["action"] == "uninstall"
    assert written["history"][-1]["result"] == "ok"
    assert written["history"][-1]["helmRevision"] == 3
    assert runner.state is None, "the record was left behind"


def test_the_command_says_where_the_record_went():
    """The in-cluster copy is deleted with the release, so the printed one is all that survives —
    and an operator who does not know that keeps nothing."""
    outcome = run_uninstall(installed(), assume_yes=True, data_policy="retain")
    body = text(outcome)
    assert "configmap/acp-installation" in body
    assert "SURVIVING COPY" in body
    assert outcome.state["history"][-1]["action"] == "uninstall"


def test_an_installation_with_no_record_still_produces_one():
    """Installed by helm directly, or by an acpctl too old to write a record. Printing "no record
    found" instead would leave the removal itself undocumented."""
    runner = installed(state=None)
    outcome = run_uninstall(runner, assume_yes=True, data_policy="retain")
    assert outcome.code == 0, outcome.reason
    assert outcome.state["history"][-1]["action"] == "uninstall"
    assert "never observed" in outcome.state["note"]


# ── nothing to remove is not a success ───────────────────────────────────────

def test_removing_nothing_is_reported_as_a_failure():
    """"We removed nothing" is a different answer from "we removed it", and a 0 here would let a
    decommissioning script report a namespace clean that it never touched."""
    runner = FakeRunner(release=None, state=None)
    outcome = run_uninstall(runner, assume_yes=True, data_policy="retain")
    assert outcome.code == 1
    assert "nothing to uninstall" in outcome.reason
    assert mutations(runner) == []


def test_an_unestablished_release_is_not_acted_on():
    runner = installed(fail={"status": "Error: query failed"})
    outcome = run_uninstall(runner, assume_yes=True, data_policy="retain")
    assert outcome.code == 1
    assert "could not establish" in outcome.reason
    assert mutations(runner) == []


def test_a_failing_helm_uninstall_does_not_report_success():
    runner = installed(fail={"uninstall": "Error: timed out waiting for the condition"})
    outcome = run_uninstall(runner, assume_yes=True, data_policy="retain")
    assert outcome.code == 1
    assert "did not complete" in outcome.reason
    assert runner.state is not None, "the record was removed after a failed uninstall"


def test_an_invalid_document_can_still_be_uninstalled(tmp_path):
    """The opposite rule from `install`. A document that has stopped validating still describes an
    installation running right now, and refusing here would strand the one most likely to need
    removing."""
    import yaml

    from acpctl.helm import Helm
    from acpctl.uninstall import uninstall

    doc = load_example("standard-production")
    doc["network"]["privateWorkers"] = False          # a rule, not a typo
    bad = tmp_path / "bad.acp-deployment.yaml"
    bad.write_text(yaml.safe_dump(doc), encoding="utf-8")

    runner = installed()
    lines: list[str] = []
    outcome = uninstall(str(bad), namespace="acp-production", helm=Helm(runner=runner),
                        assume_yes=True, data_policy="retain", echo=lines.append)
    assert outcome.code == 0, outcome.reason
    assert "no longer satisfies the contract" in "\n".join(lines)


# ── install, then uninstall, on one fake cluster ─────────────────────────────

def test_a_release_this_tool_installed_can_be_removed_and_the_history_reads_back(tmp_path):
    """END TO END ON ONE NAMESPACE, which is the only way to check the two commands agree about
    the record's shape. Each half passing against its own fixture would not."""
    runner = FakeRunner()
    assert run_install(tmp_path, runner).code == 0

    outcome = run_uninstall(runner, assume_yes=True, data_policy="retain")
    assert outcome.code == 0, outcome.reason
    assert [e["action"] for e in outcome.state["history"]] == ["install", "uninstall"]
    assert runner.release is None
    assert runner.state is None


# ── the command ──────────────────────────────────────────────────────────────

def cli(monkeypatch, runner, argv):
    from acpctl import uninstall as uninstall_mod
    from acpctl.cli import main
    from acpctl.helm import Helm

    monkeypatch.setattr(uninstall_mod, "Helm", lambda **kwargs: Helm(runner=runner))
    return main(argv)


def test_the_command_previews_and_exits_zero(monkeypatch, capsys):
    runner = installed()
    code = cli(monkeypatch, runner, ["uninstall", str(EXAMPLE), "-n", "acp-production"])
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "PREVIEW ONLY" in out.out
    assert mutations(runner) == []


def test_the_command_exits_two_without_a_data_policy(monkeypatch, capsys):
    runner = installed()
    code = cli(monkeypatch, runner, ["uninstall", str(EXAMPLE), "-n", "acp-production", "--yes"])
    assert code == 2
    assert "--data-policy" in capsys.readouterr().err
    assert mutations(runner) == []


def test_the_command_removes_the_release_with_yes_and_a_policy(monkeypatch, capsys):
    runner = installed()
    code = cli(monkeypatch, runner, ["uninstall", str(EXAMPLE), "-n", "acp-production", "--yes",
                                     "--data-policy", "retain", "--json"])
    out = capsys.readouterr()
    assert code == 0, out.err
    assert json.loads(out.out)["history"][-1]["action"] == "uninstall"
    assert runner.release is None


def test_the_command_requires_a_namespace(capsys):
    from acpctl.cli import main
    with pytest.raises(SystemExit) as exc:
        main(["uninstall", str(EXAMPLE)])
    assert exc.value.code == 2
    capsys.readouterr()


def test_the_command_rejects_a_data_policy_it_does_not_implement(capsys):
    from acpctl.cli import main
    with pytest.raises(SystemExit) as exc:
        main(["uninstall", str(EXAMPLE), "-n", "acp", "--yes", "--data-policy", "archive"])
    assert exc.value.code == 2
    capsys.readouterr()


def test_uninstall_is_no_longer_advertised_as_unimplemented():
    from acpctl.cli import NOT_YET_IMPLEMENTED, build_parser
    assert "uninstall" not in NOT_YET_IMPLEMENTED
    sub = next(a for a in build_parser()._actions if hasattr(a, "choices") and a.choices)
    assert "uninstall" in sub.choices


# ── the documentation this command's promises live in ────────────────────────

def test_the_lifecycle_doc_states_the_data_retention_policy():
    """The preview's guarantees are only useful if an operator can read them before running it.
    Asserted because a doc that stops matching the tool is worse than none."""
    doc = (PACKAGING / "docs" / "lifecycle.md").read_text(encoding="utf-8")
    for phrase in ("--data-policy", "retain", "delete", "--confirm-name",
                   "PersistentVolumeClaim"):
        assert phrase in doc, phrase
    assert "supported" in doc.lower()


def _state():
    """An installation record as `acpctl install` writes one."""
    return {
        "apiVersion": "packaging.acp.mova.io/v1alpha1",
        "kind": "ACPInstallation",
        "installation": {"name": "acp-production", "namespace": "acp-production",
                         "releaseName": "acp-production", "profile": "standard",
                         "platform": "azure", "environment": "production", "version": "2026.9"},
        "document": {"path": str(EXAMPLE), "sha256": "sha256:" + "0" * 64},
        "release": {"revision": 3, "version": "2026.9", "pinned": True,
                    "components": {"api": {"repository": "acp-web-api",
                                           "digest": "sha256:" + "a" * 64}},
                    "manifestSha256": "sha256:" + "0" * 64},
        "chart": {"name": "acp", "version": "0.1.0", "appVersion": "2026.9",
                  "valuesSha256": "sha256:" + "0" * 64},
        "recordedAt": "2026-09-01T00:00:00Z",
        "acpctlVersion": "0.1.0-alpha",
        "flags": {"skipPreflight": False, "adopted": False, "allowUnpinned": False},
        "history": [{"action": "install", "at": "2026-09-01T00:00:00Z", "helmRevision": 3,
                     "result": "ok"}],
    }
