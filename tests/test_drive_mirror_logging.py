"""Every path through the Drive mirror says what it did. Silence means nothing ran.

The stamp check originally logged only when the stamp FAILED to round-trip. So when a scan
produced no mirror line, two very different states looked identical:

    * the stamp persisted fine, or
    * the mirror never executed at all.

On the day it mattered it was the second — no remediate request ever reached the server — and
several minutes went into interrogating a working system. A log that speaks only on failure
tells you nothing about a system that is quiet.

Three exits now each emit one greppable `[remediate] drive mirror: <file> ...` line:
    created/updated + stamp=persisted|MISSING · FAILED — <reason> · skipped — disabled
The `decisions` audit table still records only the anomalies, not every successful write.
"""
import re
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API))

SRC = (API / "handlers.py").read_text()
CODE = "\n".join(l for l in SRC.split("\n") if not l.strip().startswith("#"))

# The mirror block: from the enabled-check to the record_remediation that follows it.
MIRROR = CODE[CODE.index('if source == "drive" and core.store.get_drive_mirror_enabled():'):
              CODE.index("core.store.record_remediation(")]


def _prints(block: str) -> list[str]:
    return re.findall(r'print\(f?"([^"]*)"', block)


def test_the_success_path_logs_the_stamp_result():
    # Not just the failure. `stamp=` must be printed whether or not it persisted.
    assert "stamp={'persisted' if _stamped else 'MISSING'} " in MIRROR


def test_the_success_line_is_unconditional():
    # The print must NOT sit inside `if not _stamped:` — that was the original bug.
    stamped_at = MIRROR.index("_stamped = provenance.is_acp_generated(result)")
    guard_at = MIRROR.index("if not _stamped:")
    print_at = MIRROR.index('print(f"[remediate] drive mirror: {filename} {_mode}')
    assert stamped_at < print_at < guard_at, \
        "the mirror line must be emitted before (and outside) the not-stamped guard"


def test_the_line_carries_what_drive_actually_returned():
    """"stamp=MISSING" alone cannot be debugged; the echoed properties can.

    Scoped to the print statement, not the whole block: the same fragment also appears in the
    `_detail` string fed to log_decision, so a whole-block assertion stayed green when the
    properties were deleted from the log line."""
    stmt = MIRROR[MIRROR.index('print(f"[remediate] drive mirror: {filename} {_mode}'):]
    stmt = stmt[:stmt.index("flush=True)")]
    assert "properties={result.get('properties')!r}" in stmt
    assert "id={result.get('id')}" in stmt
    assert "stamp=" in stmt


def test_create_and_update_are_distinguishable():
    assert '_mode = "created"' in MIRROR and '_mode = "updated"' in MIRROR
    assert "{_mode}" in MIRROR


def test_both_failure_paths_reach_stdout_not_only_the_database():
    # A mirror failure recorded solely via log_decision is invisible in the logs, which is
    # where an operator looks first.
    http_branch = MIRROR[MIRROR.index("except HttpError"):MIRROR.index("except Exception")]
    any_branch = MIRROR[MIRROR.index("except Exception"):]
    for name, branch in (("HttpError", http_branch), ("Exception", any_branch)):
        assert "print(" in branch, f"the {name} branch logs only to the decisions table"
        assert "FAILED" in branch


def test_the_disabled_path_says_so():
    tail = CODE[CODE.index("except Exception as e:"):CODE.index("core.store.record_remediation(")]
    assert "skipped — disabled" in tail
    assert "drive_mirror_enabled=false" in tail


def test_every_exit_uses_the_same_greppable_prefix():
    # Four exits, not three: the write, the HttpError branch, the catch-all branch, and the
    # mirror-disabled branch. `grep 'drive mirror'` must find whichever one ran.
    lines = [p for p in _prints(MIRROR) if "drive mirror" in p]
    assert len(lines) == 4, f"expected write/http-fail/any-fail/skipped, got {len(lines)}: {lines}"
    for l in lines:
        assert l.startswith("[remediate] drive mirror: {filename}"), l
    assert sum("FAILED" in l for l in lines) == 2
    assert sum("skipped" in l for l in lines) == 1


def test_a_missing_stamp_still_never_fails_the_mirror():
    # Diagnostic only. Blob already holds the durable copy and the in-document content stamp
    # still catches ACP's own output; raising here would turn a blind spot into an outage.
    guard = MIRROR[MIRROR.index("if not _stamped:"):MIRROR.index("except HttpError")]
    assert "raise" not in guard


def test_the_audit_table_records_only_the_anomaly():
    # One decisions row per unstamped copy — not one per successful write.
    assert MIRROR.count('log_decision("system", "remediate.stamp_not_persisted"') == 1
    guard = MIRROR[MIRROR.index("if not _stamped:"):MIRROR.index("except HttpError")]
    assert "remediate.stamp_not_persisted" in guard
