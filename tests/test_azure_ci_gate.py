"""A release cannot borrow a green build from another commit, branch, repo or pipeline."""
import copy
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_azure_ci.py"
SPEC = importlib.util.spec_from_file_location("check_azure_ci", PATH)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

GREEN = {"status": "completed", "result": "succeeded", "sourceVersion": "a" * 40,
         "sourceBranch": "refs/heads/main", "repository": {"id": "repo"},
         "definition": {"id": 10}}


def check(build):
    gate.validate_build(build, commit="a" * 40, repository="repo", definition=10)


def test_accepts_the_completed_exact_build():
    check(GREEN)


@pytest.mark.parametrize("field,value", [
    ("status", "inProgress"), ("result", "failed"), ("result", "canceled"),
    ("result", "partiallySucceeded"), ("sourceVersion", "b" * 40),
    ("sourceBranch", "refs/heads/feature"), ("repository", {"id": "another-repo"}),
    ("definition", {"id": 11}), ("repository", {}), ("definition", {}),
])
def test_refuses_untrusted_or_incomplete_evidence(field, value):
    build = copy.deepcopy(GREEN)
    build[field] = value
    with pytest.raises(ValueError, match="refused deployment"):
        check(build)


def test_azure_gate_precedes_the_operator_skip_switch():
    source = (PATH.parents[1] / "deploy/public/redeploy.sh").read_text()
    assert source.index('python3 "$SRC_ROOT/scripts/check_azure_ci.py" "$PIN"') < source.index(
        'if [ "${ACP_SKIP_CI_GATE:-0}" = 1 ]')
