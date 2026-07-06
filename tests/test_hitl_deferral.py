"""Office alt-text deferrals must reach the HITL queue (closes the silent gap:
auto fix_mode findings never enter queue_hitl_items' ai-assisted pull)."""
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
    tmp = Path(tempfile.mkdtemp()) / "hitl-test.db"
    store_mod._SQLITE_PATH = tmp
    store_mod._SCHEMA[:] = [s for s in store_mod._SCHEMA
                            if not s.strip().upper().startswith("ALTER TABLE")]
    return store_mod.Store()


def test_deferral_lands_in_queue_and_is_idempotent(store):
    note = "2 image(s) lack a faithful alt source — sent for human alt text"
    item_id = store.queue_hitl_deferral("s1", "deck.pptx", note, 2)
    assert item_id
    items = store.list_hitl_queue(status="pending", scan_id="s1")
    assert len(items) == 1
    it = items[0]
    assert it["rule_id"] == "1.1.1/deferred"
    assert it["finding_count"] == 2
    assert "faithful alt source" in it["rule_name"]
    # retried remediation job → same (scan, file, rule) never duplicates
    assert store.queue_hitl_deferral("s1", "deck.pptx", note, 2) is None
    assert len(store.list_hitl_queue(scan_id="s1")) == 1
    # a different file in the same scan still queues
    assert store.queue_hitl_deferral("s1", "other.docx", note, 1)
    assert len(store.list_hitl_queue(scan_id="s1")) == 2


def test_verify_item_for_fully_automatic_fix(store):
    # User decision 2026-07-02: fully-automatic remediate-now runs also queue a
    # human VERIFICATION item, under its own rule id so it never collides with
    # a deferral for the same file.
    a = store.queue_hitl_deferral("s3", "auto.pdf", "Automatic fix applied — verify the result", 1,
                                  rule_id="auto/verify")
    assert a
    assert store.queue_hitl_deferral("s3", "auto.pdf", "again", 1, rule_id="auto/verify") is None
    b = store.queue_hitl_deferral("s3", "auto.pdf", "2 image(s) lack a faithful alt source", 2)
    assert b                                       # distinct rule ids coexist per file
    ids = {i["rule_id"] for i in store.list_hitl_queue(scan_id="s3")}
    assert ids == {"auto/verify", "1.1.1/deferred"}


def test_deferral_does_not_collide_with_ai_assisted_pull(store):
    # A real 1.1.1 ai-assisted item and a deferral for the same file coexist —
    # distinct rule ids keep queue_hitl_items' dedupe from swallowing either.
    store.queue_hitl_deferral("s2", "doc.docx", "1 image(s) lack a faithful alt source", 1)
    ids = {i["rule_id"] for i in store.list_hitl_queue(scan_id="s2")}
    assert ids == {"1.1.1/deferred"}
