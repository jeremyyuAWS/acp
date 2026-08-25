"""Verify that run_scan instruments metadata exceptions in its progress payloads.

The scanner wraps _download() in a try/except that classifies failures into three counters
(exc_inaccessible_file, exc_metadata_failure, exc_deleted_during_scan) and emits them on
every reading-phase progress event. This contract is text-verified so that a refactor of the
exception-handling block fails loudly instead of silently dropping the counts.
"""
import re
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API))

SRC = (API / "scanner.py").read_text()
# Strip comment-only lines to avoid false positives from commented-out code.
CODE = "\n".join(l for l in SRC.split("\n") if not l.strip().startswith("#"))

# Locate the reading-phase section: from the discovering progress call to the office analysis.
# There are two occurrences of office = _analyse_office(tmp); we want the one in run_scan,
# which follows the reading loop. Use exc_inaccessible_file = 0 (unique to the reading block)
# as the start anchor, and the second occurrence of office = _analyse_office as the end.
_DISC_START = CODE.index('"phase": "discovering"')
_EXC_START = CODE.index("exc_inaccessible_file = 0")
_OFFICE_FIRST = CODE.index("office = _analyse_office(tmp)")
_OFFICE_SECOND = CODE.index("office = _analyse_office(tmp)", _OFFICE_FIRST + 1)
READING_BLOCK = CODE[_EXC_START:_OFFICE_SECOND]


def test_reading_phase_emits_schema_version_2():
    reading_progress = re.findall(r'progress\(\{[^}]*"phase": "reading"[^}]*\}\)', CODE, re.DOTALL)
    assert reading_progress, "reading phase must still emit progress"
    for call in reading_progress:
        assert '"schema_version": 2' in call, (
            f"reading phase progress must carry schema_version=2 so the frontend can detect "
            f"old backends and degrade gracefully: {call[:200]}")


def test_reading_block_catches_permission_errors_as_inaccessible():
    assert "exc_inaccessible_file" in READING_BLOCK, (
        "reading block must count PermissionError as exc_inaccessible_file")
    assert "PermissionError" in READING_BLOCK, (
        "reading block must catch PermissionError (raised by _sp_download / _download on 401/403)")


def test_reading_block_counts_deleted_during_scan():
    assert "exc_deleted_during_scan" in READING_BLOCK, (
        "reading block must count 404 responses as exc_deleted_during_scan")


def test_reading_block_counts_metadata_failures():
    assert "exc_metadata_failure" in READING_BLOCK, (
        "reading block must count other download errors as exc_metadata_failure")


def test_skipped_files_are_excluded_from_downstream_items():
    # After the reading loop, skipped files must be filtered out so _analyse_one does not
    # try to open a temp file that was never written.
    assert "skipped" in READING_BLOCK, (
        "reading block must track skipped file names and filter items after the loop")
    assert "items = [it for it in items if it" in READING_BLOCK or \
           "items = [i for i in items if i" in READING_BLOCK, (
        "skipped files must be removed from items before downstream analysis")


def test_exc_missing_optional_derived_from_listing():
    # exc_missing_optional is a count of items without owner or source_modified.
    # It is computed from the items list (not from download errors) so it is available
    # before the reading loop starts.
    pre_loop = CODE[_DISC_START:_EXC_START]
    assert "exc_missing_optional" in pre_loop, (
        "exc_missing_optional must be computed from the items list before the reading loop")


def test_exc_missing_required_derived_from_listing():
    pre_loop = CODE[_DISC_START:_EXC_START]
    assert "exc_missing_required" in pre_loop, (
        "exc_missing_required must be computed from the items list before the reading loop")
