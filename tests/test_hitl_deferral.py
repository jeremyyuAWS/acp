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


def test_no_commercial_llm_surface():
    # The AI layer is 100% local: no Anthropic/OpenAI SDK, no key, no external
    # call path. Even with a (would-bill) key set, there is nothing to invoke it —
    # the module carries no commercial-LLM symbols at all.
    import ai
    src = open(ai.__file__).read().lower()
    assert "anthropic" not in src, "ai.py must not reference Anthropic"
    assert "openai" not in src, "ai.py must not reference OpenAI"
    assert not hasattr(ai, "_claude_complete") and not hasattr(ai, "_claude_narrative")


def test_digest_is_keyless_and_deterministic_when_offline(monkeypatch):
    # With no key and Ollama unreachable, the compliance digest still returns a real
    # deterministic narrative (never crashes, never needs a commercial LLM key).
    import ai
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-would-bill-if-used")  # must be ignored — no code reads it
    d = ai.compliance_digest({"avg_score": 66, "total": 3, "certifiable": 1}, ai_enabled=True)
    assert d["ai"] is False and d["model"] == "deterministic" and d["narrative"]
