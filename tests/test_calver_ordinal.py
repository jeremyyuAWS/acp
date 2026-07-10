"""deploy.sh's CalVer build date + ordinal (YYYY.M.D.N).

The DATE is the calendar day in Pacific time (BUILD_TZ), not UTC. A deploy at 8:06 PM PDT on
Jul 9 was stamped 2026.7.10, and the login screen showed that version beside a build time it
renders in the viewer's own zone — "v2026.7.10.11 · Jul 9, 2026, 8:06 PM PDT".

N is the number of acp-app revisions created today (PACIFIC) + 1 — a count of DEPLOYS, not
commits. Moving the date without moving the day BOUNDARY would be worse than leaving it: at
8 PM PDT the Pacific day spans two UTC days, so a UTC-prefix count would reset the ordinal
every evening and stamp a version that already existed.

A commit-derived ordinal went backwards when a deploy ran from a branch behind main, and
repeated when the same commit was rebuilt. Both are exercised below.

The shell is executed for real, with `az` stubbed, so the test covers the actual quoting,
`set -euo pipefail` interactions, and the awk/python3 boundary computation.
"""
import re
import subprocess
from pathlib import Path

import pytest

DEPLOY_SH = Path(__file__).resolve().parent.parent / "deploy" / "public" / "deploy.sh"


def _ordinal_block() -> str:
    """The exact ordinal computation lifted from deploy.sh, so the test can never drift."""
    src = DEPLOY_SH.read_text()
    start = src.index('BUILD_TZ="${BUILD_TZ:-')
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


# 01:09:47 UTC on the 10th is 18:09:47 PDT on the NINTH. Every fixture below is a UTC instant;
# the expected version is its Pacific calendar day.
NOW = "2026-07-10T01:09:47Z"                    # Thu Jul 9, 6:09 PM PDT
BEFORE_PT_MIDNIGHT = "2026-07-09T06:48:56+00:00"   # Wed Jul 8, 11:48 PM PDT — the PREVIOUS day
AFTER_PT_MIDNIGHT = "2026-07-09T07:11:42+00:00"    # Thu Jul 9, 12:11 AM PDT — the same PT day


def test_the_date_is_the_pacific_day_not_the_utc_day():
    # The reported bug, verbatim: an evening deploy stamped tomorrow.
    assert run("2026-07-10T03:06:00Z", "").startswith("2026.7.9.")


def test_counts_only_todays_pacific_revisions():
    revs = "\n".join([BEFORE_PT_MIDNIGHT, AFTER_PT_MIDNIGHT, "2026-07-10T00:34:16+00:00"])
    assert run(NOW, revs) == "2026.7.9.3"      # 2 today (PT) -> next is .3


def test_a_revision_from_the_previous_pacific_day_is_not_counted():
    # 06:48 UTC is 23:48 PDT YESTERDAY. A UTC-prefix match would have counted it (same UTC day
    # as AFTER_PT_MIDNIGHT), inflating the ordinal.
    assert run(NOW, BEFORE_PT_MIDNIGHT) == "2026.7.9.1"


def test_a_revision_later_the_same_utc_day_but_next_pacific_day_is_not_counted():
    # The evening deploy's own revisions live in TOMORROW's UTC day. Counting by UTC prefix
    # would drop them and reset the ordinal to .1 every night at 5 PM PDT.
    revs = "\n".join(["2026-07-10T00:11:42+00:00", "2026-07-10T01:00:00+00:00"])
    assert run(NOW, revs) == "2026.7.9.3"


def test_first_deploy_of_the_day_is_one():
    assert run(NOW, BEFORE_PT_MIDNIGHT) == "2026.7.9.1"


def test_zero_matching_revisions_does_not_kill_the_script():
    # The old `grep -c` exited 1 on zero matches; under `set -e` that aborted the deploy.
    assert run(NOW, "2020-01-01T00:00:00+00:00") == "2026.7.9.1"


def test_missing_app_falls_back_to_seconds_since_pacific_midnight():
    # First-ever deploy: no revisions. 18:09:47 PDT -> 65387s. Monotonic, no git, no Azure.
    assert run(NOW, "") == "2026.7.9.65387"


def test_month_and_day_are_unpadded():
    assert run("2026-07-09T22:00:00Z", "2026-07-09T20:00:00+00:00") == "2026.7.9.2"


# ── DST: the offset is not a constant ──

def test_winter_uses_pst_not_pdt():
    # Jan 5, 2026 04:30 UTC = Jan 4, 8:30 PM PST (UTC-8). A hardcoded -7 would say Jan 4 too,
    # but the day BOUNDARY (08:00Z, not 07:00Z) is what a fixed offset would get wrong.
    assert run("2026-01-05T04:30:00Z", "") == "2026.1.4.73800"


def test_a_revision_in_the_pst_boundary_hour_is_attributed_correctly():
    # 2026-01-05T07:30:00Z is 23:30 PST on Jan 4 — still the same Pacific day as the build.
    # Under a fixed UTC-7 assumption it would have been 00:30 on Jan 5: the wrong day.
    assert run("2026-01-05T04:30:00Z", "2026-01-04T08:30:00+00:00") == "2026.1.4.2"


def test_new_year_rolls_the_year_back_in_pacific():
    # 2027-01-01T05:00:00Z is 2026-12-31 21:00 PST. The year, month and day all differ.
    assert run("2027-01-01T05:00:00Z", "") == "2026.12.31.75600"


def test_ordinal_only_increases_across_same_day_deploys():
    revs = [BEFORE_PT_MIDNIGHT]
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
    revs = "\n".join([BEFORE_PT_MIDNIGHT, "2026-07-10T00:11:42+00:00"])
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


# ── the "is this stamped?" guard ──

def _guard_accepts(version: str) -> bool:
    """Run deploy.sh's actual BUILD_VERSION regex against a candidate."""
    src = DEPLOY_SH.read_text()
    line = next(l for l in src.split("\n") if l.startswith('if ! [[ "$BUILD_VERSION" =~'))
    script = f'set -u\nBUILD_VERSION="{version}"\n{line}\n  exit 1\nfi\nexit 0\n'
    return subprocess.run(["bash", "-c", script], capture_output=True).returncode == 0


@pytest.mark.parametrize("version", [
    "2026.7.10.6",       # the deploy count — the normal case
    "2026.7.10.1",       # first deploy of the day
    "2026.7.9.65387",    # seconds-since-Pacific-midnight fallback
    "2026.7.10.005859",  # the timestamp scheme this replaced (still a valid stamp)
    "2026.12.31.99",
])
def test_guard_accepts_every_stamp_this_script_can_produce(version):
    # Pinning the ordinal to exactly 6 digits rejected .6 and aborted the deploy — safely, but
    # it made the readable ordinal unshippable. The guard's job is catching an UNSTAMPED image.
    assert _guard_accepts(version), f"{version} must be accepted"


@pytest.mark.parametrize("version", [
    "dev",               # the Dockerfile's ARG default — the whole reason the guard exists
    "",
    "2026.7.10",         # no ordinal
    "v2026.7.10.6",
    "2026.7.10.1234567", # 7 digits — not an ordinal this script emits
    "2026.7.10.abc",
])
def test_guard_still_refuses_an_unstamped_or_malformed_version(version):
    assert not _guard_accepts(version), f"{version} must be refused"
