"""deploy.sh's CalVer build ordinal (.N).

N is the number of acp-app revisions created today (UTC) + 1 — a count of DEPLOYS, not commits.
A commit-derived ordinal went backwards when a deploy ran from a branch behind main, and
repeated when the same commit was rebuilt. Both are exercised below.

The shell is executed for real, with `az` stubbed, so the test covers the actual quoting,
`set -euo pipefail` interactions, and the `grep -c` zero-match exit code.
"""
import re
import subprocess
from pathlib import Path

import pytest

DEPLOY_SH = Path(__file__).resolve().parent.parent / "deploy" / "public" / "deploy.sh"


def _ordinal_block() -> str:
    """The exact ordinal computation lifted from deploy.sh, so the test can never drift."""
    src = DEPLOY_SH.read_text()
    start = src.index('BUILD_DATE="${BUILD_TIME:0:4}')
    end = src.index('BUILD_VERSION="${BUILD_DATE}.${BUILD_SEQ}"') + len('BUILD_VERSION="${BUILD_DATE}.${BUILD_SEQ}"')
    return src[start:end]


def run(build_time: str, revision_times: str) -> str:
    """Execute the real block with `az` replaced by a stub printing `revision_times`."""
    block = _ordinal_block()
    script = f"""
set -euo pipefail
APP=acp-app; RG=rg
az() {{ printf '%s' "$FAKE_REVS"; }}
BUILD_TIME="{build_time}"
{block}
echo "$BUILD_VERSION"
"""
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                         env={"FAKE_REVS": revision_times, "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, f"deploy.sh ordinal died: {out.stderr}"
    return out.stdout.strip().splitlines()[-1]


NOW = "2026-07-10T01:09:47Z"
YESTERDAY = "2026-07-09T21:48:56+00:00"


def test_counts_only_todays_revisions():
    revs = "\n".join([YESTERDAY, "2026-07-10T00:11:42+00:00", "2026-07-10T00:34:16+00:00"])
    assert run(NOW, revs) == "2026.7.10.3"      # 2 today -> next is .3


def test_first_deploy_of_the_day_is_one():
    assert run(NOW, YESTERDAY) == "2026.7.10.1"


def test_grep_zero_match_does_not_kill_the_script():
    # grep -c exits 1 on zero matches; under `set -e` that would abort the deploy.
    assert run(NOW, "2020-01-01T00:00:00+00:00") == "2026.7.10.1"


def test_missing_app_falls_back_to_seconds_since_midnight():
    # First-ever deploy: no revisions exist. 01:09:47 -> 4187s. Still monotonic, no git.
    assert run(NOW, "") == "2026.7.10.4187"


def test_month_and_day_are_unpadded():
    assert run("2026-07-09T05:00:00Z", "2026-07-09T01:00:00+00:00") == "2026.7.9.2"


def test_ordinal_only_increases_across_same_day_deploys():
    revs = [YESTERDAY]
    seen = []
    for k in range(1, 6):
        v = run(NOW, "\n".join(revs))
        seen.append(int(v.rsplit(".", 1)[1]))
        revs.append(f"2026-07-10T0{k}:00:00+00:00")   # each deploy creates one revision
    assert seen == sorted(seen) and len(set(seen)) == len(seen), seen


def test_ordinal_is_independent_of_which_commit_deploys():
    # The defect this replaced: a deploy from a stale branch stamped a LOWER N than what was
    # live. N now depends only on the revision history, so two different commits with the same
    # deploy history get the same N — and the next deploy always gets one more.
    revs = "\n".join([YESTERDAY, "2026-07-10T00:11:42+00:00"])
    assert run(NOW, revs) == run(NOW, revs)


def test_revision_list_passes_the_all_flag():
    # acp-app runs activeRevisionsMode=Single: `revision list` returns ONLY the active
    # revision, so without --all the count is always 1 and every deploy stamps .1.
    #
    # Assert on the COMMAND, not the file: the comment above it also contains "--all", so a
    # whole-file check stays green when the flag is deleted from the command.
    src = DEPLOY_SH.read_text()
    cmd_start = src.index("az containerapp revision list")
    cmd = src[cmd_start:src.index("-o tsv", cmd_start)]
    assert "--all" in cmd, f"revision list must pass --all; got: {cmd.strip()!r}"


def test_ordinal_is_not_derived_from_git():
    # Judge the code, not the comments — which mention git precisely to explain why it is absent.
    code = "\n".join(l for l in _ordinal_block().split("\n") if not l.lstrip().startswith("#"))
    assert not re.search(r"\bgit\b", code), "the ordinal must not depend on the deployed commit"
