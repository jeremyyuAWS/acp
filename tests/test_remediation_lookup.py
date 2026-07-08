"""Cross-scan remediated-copy lookup (ADR 0010 + 0011).

Regression for the silent "Download fixed copy" 404: a remediation is keyed by
scan_id (both the file_records row and the Blob object), but an ADR 0011
incremental re-scan mints a NEW scan_id and, for an unchanged file, reuses the
prior analysis WITHOUT re-remediating. Viewing the file on the new scan must
still resolve the fixed copy recorded under the scan that ran the remediation.

Runs against a fresh SQLite database (same harness as test_jobs.py).
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def store():
    import store as store_mod
    tmp = Path(tempfile.mkdtemp()) / "remlookup-test.db"
    store_mod._SQLITE_PATH = tmp
    store_mod._SCHEMA[:] = [s for s in store_mod._SCHEMA
                            if not s.strip().upper().startswith("ALTER TABLE")]
    return store_mod.Store()


OWNER = "user@example.com"


def _file(name, **over):
    f = {"file": name, "engine": "pptx", "status": "issues", "score": 71,
         "compliant": 0, "skipped_rules": 0, "drive_file_id": "drv-abc",
         "acp_stamped": None, "checksum": "sum-1", "size_kb": 10,
         "pages": None, "sheets": None, "issues": []}
    f.update(over)
    return f


def _scan(store, sid, completed_at, *, files):
    store.init_scan_run(sid, "drive", len(files), "2026-07-07T00:00:00Z",
                        "WCAG 2.1 AA", "rub-1", owner=OWNER)
    for f in files:
        store.save_file_result(sid, f, completed_at)
    store.finalize_scan_run(sid, completed_at)


def test_cross_scan_lookup_resolves_prior_remediation(store):
    name = "Deck.pptx"
    # Old scan actually remediated the file (Blob URL recorded under its scan_id).
    _scan(store, "old", "2026-07-07T12:00:00Z", files=[_file(name)])
    store.record_remediation("old", name,
                             drive_write_url="https://drive/old",
                             blob_url="https://blob/old/Deck.pptx")

    # Incremental re-scan: new scan_id, same document, NO remediation recorded.
    _scan(store, "new", "2026-07-08T12:00:00Z", files=[_file(name)])

    # The scan the user is viewing has no remediation of its own …
    urls = store.get_remediation_urls("new", name)
    assert not (urls and (urls.get("blob_url") or urls.get("drive_write_url")))

    # … but the cross-scan resolver finds the copy under the scan that ran it,
    # returning WHERE the Blob object lives (scan_id + file) so the caller can
    # download from there instead of the viewed (empty) scan.
    alt = store.find_remediation_for_file(OWNER, "new", name)
    assert alt is not None
    assert alt["scan_id"] == "old"
    assert alt["file"] == name
    assert alt["blob_url"] == "https://blob/old/Deck.pptx"


def test_lookup_matches_across_rename_by_drive_id(store):
    # Same Drive file, renamed between scans — matched on the stable drive_file_id.
    _scan(store, "old", "2026-07-07T12:00:00Z", files=[_file("Deck-v6.pptx")])
    store.record_remediation("old", "Deck-v6.pptx", blob_url="https://blob/old/Deck-v6.pptx")
    _scan(store, "new", "2026-07-08T12:00:00Z", files=[_file("Deck-v7.pptx")])

    alt = store.find_remediation_for_file(OWNER, "new", "Deck-v7.pptx")
    assert alt is not None and alt["scan_id"] == "old"
    assert alt["file"] == "Deck-v6.pptx"   # download must use the source scan's name


def test_lookup_is_owner_scoped(store):
    # A remediation belonging to a different owner must never be returned.
    store.init_scan_run("other", "drive", 1, "2026-07-07T00:00:00Z",
                        "WCAG 2.1 AA", "rub-1", owner="someone-else@example.com")
    store.save_file_result("other", _file("Deck.pptx"), "2026-07-07T12:00:00Z")
    store.finalize_scan_run("other", "2026-07-07T12:00:00Z")
    store.record_remediation("other", "Deck.pptx", blob_url="https://blob/other/Deck.pptx")

    _scan(store, "mine", "2026-07-08T12:00:00Z", files=[_file("Deck.pptx")])
    assert store.find_remediation_for_file(OWNER, "mine", "Deck.pptx") is None


def test_lookup_none_when_never_remediated(store):
    _scan(store, "s1", "2026-07-08T12:00:00Z", files=[_file("Deck.pptx")])
    assert store.find_remediation_for_file(OWNER, "s1", "Deck.pptx") is None
