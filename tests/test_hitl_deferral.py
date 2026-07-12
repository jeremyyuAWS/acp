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
def store(monkeypatch):
    import store as store_mod
    tmp = Path(tempfile.mkdtemp()) / "hitl-test.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    return store_mod.Store()


def test_deferral_lands_in_queue_and_is_idempotent(store):
    note = "2 image(s) lack a faithful alt source — sent for human alt text"
    item_id = store.queue_hitl_deferral("s1", "deck.pptx", note, 2)
    assert item_id
    items = store.list_hitl_queue(status="pending", scan_id="s1")
    assert len(items) == 1
    it = items[0]
    assert it["rule_id"] == "1.1.1"          # a deferral is not a separate criterion
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
    # human VERIFICATION item. 'auto/verify' is a pseudo-rule ("an automatic fix was
    # applied, please eyeball it"), NOT a WCAG criterion — so unlike '1.1.1/deferred'
    # it keeps a row of its own and never merges into 1.1.1.
    a = store.queue_hitl_deferral("s3", "auto.pdf", "Automatic fix applied — verify the result", 1,
                                  rule_id="auto/verify")
    assert a
    assert store.queue_hitl_deferral("s3", "auto.pdf", "again", 1, rule_id="auto/verify") is None
    b = store.queue_hitl_deferral("s3", "auto.pdf", "2 image(s) lack a faithful alt source", 2)
    assert b                                       # distinct rule ids coexist per file
    ids = {i["rule_id"] for i in store.list_hitl_queue(scan_id="s3")}
    assert ids == {"auto/verify", "1.1.1"}


def test_a_deferral_occupies_the_criterion_row_not_a_second_one(store):
    # A deferral and an ai-assisted 1.1.1 item are the SAME criterion for the same file.
    # They used to sit in two rows, both rendering as "WCAG 1.1.1", and the one a reviewer
    # opened was not necessarily the one holding the AI proposals.
    store.queue_hitl_deferral("s2", "doc.docx", "1 image(s) lack a faithful alt source", 1)
    ids = {i["rule_id"] for i in store.list_hitl_queue(scan_id="s2")}
    assert ids == {"1.1.1"}


def test_ai_module_stays_vendor_agnostic():
    # ai.py orchestrates; it must never name or import a cloud vendor (rule 6 / ADR 0019 §1).
    # The provider adapters live behind the seam in providers.py — ai.py learns a provider's
    # name only from the adapter's result at runtime, never as a literal or an SDK import.
    import ai
    src = open(ai.__file__).read().lower()
    assert "anthropic" not in src, "ai.py must not reference Anthropic"
    assert "openai" not in src, "ai.py must not reference OpenAI"
    assert not hasattr(ai, "_claude_complete") and not hasattr(ai, "_claude_narrative")


def test_cloud_is_opt_in_and_keyless_by_default():
    # ADR 0019 Phase 1: a cloud adapter EXISTS in providers.py (opt-in escalation), but the default
    # build ships no key and no enabled cloud provider — so there is no external call path out of the
    # box, and providers.py holds no hardcoded credential (only an env-secret REFERENCE is ever read).
    import providers
    src = open(providers.__file__).read()
    assert "os.environ.get" in src, "the key must come from an env secret, never a literal"
    # no obvious hardcoded key literal (sk-…/api-key=…) baked into the seam
    assert "sk-" not in src.lower() and "api_key=" not in src.replace(" ", "").lower()
    # default state: nothing configured → no cloud provider selected
    import core
    import types
    _orig = core.store
    try:
        core.store = types.SimpleNamespace(get_ai_provider_config=lambda p: None)
        assert providers.cloud_vision_provider() is None
    finally:
        core.store = _orig


def test_digest_is_keyless_and_deterministic_when_offline(monkeypatch):
    # With no key and Ollama unreachable, the compliance digest still returns a real
    # deterministic narrative (never crashes, never needs a commercial LLM key).
    import ai
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-would-bill-if-used")  # must be ignored — no code reads it
    d = ai.compliance_digest({"avg_score": 66, "total": 3, "certifiable": 1}, ai_enabled=True)
    assert d["ai"] is False and d["model"] == "deterministic" and d["narrative"]
