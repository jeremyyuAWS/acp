"""ADR 0021 §E — the "house style applied" chip: making review memory's influence visible.

Review memory changes the PROMPT behind a draft a human is about to certify, and the ADR is
explicit that this must never be a hidden hand: "A draft shaped by memory says so, on the card,
expandable to the exact guidance and (for derived rules) the evidence that justified it."

The backend has emitted a COUNT since stage 1 (`house_style_applied`) and nothing ever consumed
it. A count cannot be expanded into anything, so `/ai/suggest` now also carries the rules
themselves. These tests hold the two properties that make the chip trustworthy rather than
decorative:

  1. THE CHIP'S RULES ARE THE PROMPT'S RULES. Both come from one `store.memory_applied_rules`
     call. A chip built from a second, parallel lookup could drift from what the model was
     actually asked and quietly name a rule the prompt never carried — worse than showing
     nothing, because a reviewer has no way to notice. The selection logic (most-specific-first,
     active-only, dedup) is therefore tested through BOTH entry points on the same data.
  2. NO CHIP MEANS NO INFLUENCE. `ACP_REVIEW_MEMORY` defaults off, and off the prompt is
     byte-for-byte the pre-memory one. The response must then carry no house-style fields at
     all, so their absence is a fact about the draft and not about whether anyone looked.

Evidence handling follows ADR 0016: the count the row carries is passed through verbatim, and
nothing here computes a percentage or a confidence from it.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import memory as _mem  # noqa: E402

TRACE = {"rule_name": "Non-text Content", "level": "A", "detail": ""}


def _seed_rules(s, org="acme"):
    """One rule at each scope, plus a proposal and another tenant's rule — so a test that
    passes is a test that got the filtering right, not one with a single row to find."""
    s.add_org_memory(org, "style", "Docx alt: 100 characters or fewer.",
                     rule_id="1.1.1", format="docx")
    s.add_org_memory(org, "style", "Alt text: never begin with 'image of'.", rule_id="1.1.1")
    s.add_org_memory(org, "style", "Org-wide: British spelling.")
    s.add_org_memory(org, "derived", "Never applied — still a proposal.", rule_id="1.1.1",
                     status="proposed")
    s.add_org_memory("globex", "style", "Another tenant's rule.", rule_id="1.1.1")


# ── 1. one selection, two readers ────────────────────────────────────────────────

def test_the_chips_rules_are_exactly_the_prompts_rules(isolated_store):
    """The load-bearing property. If these ever disagree, the card is making a claim about a
    draft that the draft cannot support."""
    s = isolated_store
    _seed_rules(s)
    for rule_id, fmt in (("1.1.1", "docx"), ("1.1.1", "pptx"), ("2.4.4", "docx"),
                         (None, None), ("9.9.9", "xlsx")):
        rows = s.memory_applied_rules("acme", rule_id, fmt)
        assert [r["guidance"] for r in rows] == s.memory_guidance("acme", rule_id, fmt), (
            f"the chip and the prompt disagree for ({rule_id}, {fmt}) — the chip would name "
            f"a rule the model was never given, or miss one it was")


def test_selection_is_most_specific_first_active_only_and_org_isolated(isolated_store):
    s = isolated_store
    _seed_rules(s)
    rows = s.memory_applied_rules("acme", "1.1.1", "docx")
    assert [r["guidance"][:9] for r in rows] == ["Docx alt:", "Alt text:", "Org-wide:"]
    assert all("still a proposal" not in r["guidance"] for r in rows)   # ADR 0021 §D gate
    assert all("Another tenant" not in r["guidance"] for r in rows)     # org isolation
    # A different criterion sees only what actually applies to it.
    assert [r["guidance"] for r in s.memory_applied_rules("acme", "2.4.4", "docx")] == [
        "Org-wide: British spelling."]
    assert s.memory_applied_rules("globex", "1.1.1", "docx") == [
        {"id": s.list_org_memory("globex")[0]["id"], "kind": "style",
         "guidance": "Another tenant's rule.", "rule_id": "1.1.1", "format": None,
         "evidence": None}]


def test_rows_carry_what_the_chip_expands_to(isolated_store):
    """An ACCEPTED derived rule keeps kind='derived' (acceptance flips status, not kind) and the
    real count that justified it — which is the only reason the chip can show WHY a rule exists
    rather than just asserting it."""
    s = isolated_store
    ev = {"rule": "1.1.1", "edited": 8, "of": 10, "median_delta_chars": -34, "window_days": 30}
    mid = s.add_org_memory("acme", "derived", "Keep drafts concise.", rule_id="1.1.1",
                           status="proposed", evidence=json.dumps(ev), author="derivation")
    assert s.memory_applied_rules("acme", "1.1.1", None) == []      # proposed shapes nothing
    assert s.set_org_memory_status("acme", mid, "active") is True   # an admin accepts it
    rows = s.memory_applied_rules("acme", "1.1.1", None)
    assert len(rows) == 1
    assert rows[0]["kind"] == "derived" and json.loads(rows[0]["evidence"])["edited"] == 8


# ── 2. dark unless the flag is on ────────────────────────────────────────────────

def test_applied_rules_is_dark_exactly_when_guidance_is(isolated_store, monkeypatch):
    s = isolated_store
    _seed_rules(s)
    monkeypatch.delenv("ACP_REVIEW_MEMORY", raising=False)
    assert _mem.applied_rules(s, "acme", "1.1.1", "docx") == []
    assert _mem.guidance_for(s, "acme", "1.1.1", "docx") == ""      # the same condition
    assert _mem.applied_rule_count(s, "acme", "1.1.1", "docx") == 0

    monkeypatch.setenv("ACP_REVIEW_MEMORY", "1")
    on = _mem.applied_rules(s, "acme", "1.1.1", "docx")
    assert len(on) == 3 and _mem.applied_rule_count(s, "acme", "1.1.1", "docx") == 3
    assert _mem.guidance_for(s, "acme", "1.1.1", "docx") != ""
    # No org, no store, and a store that raises all degrade rather than break a draft.
    assert _mem.applied_rules(s, None, "1.1.1", "docx") == []
    assert _mem.applied_rules(None, "acme", "1.1.1", "docx") == []
    boom = types.SimpleNamespace(
        memory_applied_rules=lambda *a: (_ for _ in ()).throw(RuntimeError("db down")))
    assert _mem.applied_rules(boom, "acme", "1.1.1", "docx") == []


# ── 3. through the real route ────────────────────────────────────────────────────

def _route_call(monkeypatch, isolated_store, org="acme"):
    """Drive the real /ai/suggest handler with the REAL store selection — only the trace lookup
    and the model call are stubbed, so what comes back is what a card would receive."""
    import core
    import ai as _ai
    import routes.ai as rai
    monkeypatch.setattr(core, "store", types.SimpleNamespace(
        get_ai_enabled=lambda: True,
        get_trace_row=lambda s, f, r: TRACE,
        memory_applied_rules=isolated_store.memory_applied_rules,
        memory_guidance=isolated_store.memory_guidance))
    monkeypatch.setattr(_ai, "model_is_available", lambda: True)
    seen = {}

    def fake_suggest(**kw):
        seen.update(kw)
        return {"suggestion": "A clinician reviews a chart.", "is_template": False}

    monkeypatch.setattr(_ai, "suggest_fix", fake_suggest)
    req = types.SimpleNamespace(state=types.SimpleNamespace(user_email=org))
    out = rai.ai_suggest(request=req, scan_id="s1", file="report.docx", rule_id="1.1.1",
                         locator=None)
    return out, seen


def test_route_reports_the_rules_it_actually_injected(monkeypatch, isolated_store):
    monkeypatch.setenv("ACP_REVIEW_MEMORY", "1")
    _seed_rules(isolated_store)
    out, seen = _route_call(monkeypatch, isolated_store)

    assert out["house_style_applied"] == 3
    assert len(out["house_style"]) == 3
    # Every rule the card will name is a rule the model was actually given, in the same order.
    for r in out["house_style"]:
        assert r["guidance"] in seen["guidance"], (
            "the response named a rule the injected prompt does not contain")
    assert [r["guidance"] for r in out["house_style"]] == \
        isolated_store.memory_guidance("acme", "1.1.1", "docx")
    # The count is derived from the list, so the two can never disagree.
    assert out["house_style_applied"] == len(out["house_style"])
    # Scope rides along so the chip can say "WCAG 1.1.1 · DOCX" vs "all criteria".
    assert {r["rule_id"] for r in out["house_style"]} == {"1.1.1", None}


def test_route_says_nothing_about_house_style_when_the_flag_is_off(monkeypatch, isolated_store):
    """The absence of the chip is the statement that the prompt was unchanged. If the fields
    appeared (even as 0 / []) a reviewer could not tell "memory is off" from "memory found
    nothing to apply", and the card would be asserting a check it did not make."""
    monkeypatch.delenv("ACP_REVIEW_MEMORY", raising=False)
    _seed_rules(isolated_store)
    out, seen = _route_call(monkeypatch, isolated_store)
    assert "house_style" not in out and "house_style_applied" not in out
    assert seen["guidance"] == ""            # and the prompt really was the pre-memory one


def test_route_says_nothing_when_the_org_has_no_rules(monkeypatch, isolated_store):
    monkeypatch.setenv("ACP_REVIEW_MEMORY", "1")
    _seed_rules(isolated_store)                       # rules exist, but for OTHER orgs
    out, seen = _route_call(monkeypatch, isolated_store, org="nobody@example.com")
    assert "house_style" not in out and seen["guidance"] == ""


def test_route_passes_evidence_through_without_interpreting_it(monkeypatch, isolated_store):
    """ADR 0016 — the number on the card is the number in the row. The route hands the stored
    JSON along untouched; it does not compute a percentage, a confidence, or a rounding."""
    monkeypatch.setenv("ACP_REVIEW_MEMORY", "1")
    ev = {"rule": "1.1.1", "edited": 8, "of": 10, "median_delta_chars": -34, "window_days": 30}
    mid = isolated_store.add_org_memory("acme", "derived", "Keep drafts concise.",
                                        rule_id="1.1.1", status="proposed",
                                        evidence=json.dumps(ev), author="derivation")
    isolated_store.set_org_memory_status("acme", mid, "active")
    out, _ = _route_call(monkeypatch, isolated_store)
    row = out["house_style"][0]
    assert row["kind"] == "derived" and json.loads(row["evidence"]) == ev


# ── 4. the card consumes it ──────────────────────────────────────────────────────

def test_the_card_actually_renders_the_chip():
    """The stage-1 failure this PR fixes was a backend field with no consumer — the count was
    emitted, tested by a source-text assertion, and never read by the SPA. Assert the consumer
    exists, so it cannot silently go away again. The chip's BEHAVIOUR is covered DOM-level in
    frontend/src/houseStyleChip.test.jsx (vite serves the shared checkout, so a browser check
    would exercise code without this change — see CLAUDE.md)."""
    src = Path(__file__).resolve().parent.parent / "frontend" / "src"
    card = (src / "EvidenceCard.jsx").read_text()
    assert "houseStyleFromDraft" in card and "<HouseStyleChip" in card
    assert "house_style" in (src / "houseStyle.js").read_text()
