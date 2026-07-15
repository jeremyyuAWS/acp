"""Enterprise review memory — ADR 0021 Rollout stage 1.

Org-scoped house style shapes AI draft PROMPTS (never weights). The safe-dark property is
the point: flag OFF or an empty store => guidance is "" and the prompt is byte-identical to
pre-memory. Retrieval is most-specific-first; memory is org-isolated; only ACTIVE rules
influence a draft (a 'proposed'/'derived' rule never does until accepted).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import ai as _ai  # noqa: E402
import memory as _mem  # noqa: E402


def test_store_roundtrip_and_status(isolated_store):
    s = isolated_store
    mid = s.add_org_memory("acme", "style", "Keep alt text under 120 characters.",
                           rule_id="1.1.1", format=None)
    rows = s.list_org_memory("acme")
    assert len(rows) == 1 and rows[0]["guidance"].startswith("Keep alt text")
    assert rows[0]["status"] == "active"                       # authored → active immediately
    assert s.set_org_memory_status("acme", mid, "archived") is True
    assert s.list_org_memory("acme", status="active") == []
    assert s.set_org_memory_status("acme", "no-such-id", "active") is False


def test_retrieval_is_most_specific_first_and_active_only(isolated_store):
    s = isolated_store
    s.add_org_memory("acme", "style", "Org-wide: British spelling.")                     # org-wide
    s.add_org_memory("acme", "style", "Alt text: no 'image of'.", rule_id="1.1.1")       # rule
    s.add_org_memory("acme", "style", "Docx alt: ≤100 chars.", rule_id="1.1.1", format="docx")
    s.add_org_memory("acme", "derived", "PROPOSED, must not apply.", rule_id="1.1.1",
                     status="proposed")
    g = s.memory_guidance("acme", "1.1.1", "docx")
    assert g[0].startswith("Docx alt")                          # rule+format is most specific
    assert "British spelling" in g[-1]                          # org-wide last
    assert all("PROPOSED" not in x for x in g)                  # proposed never influences a draft
    # a different rule sees only the org-wide rule
    assert s.memory_guidance("acme", "2.4.4", "docx") == ["Org-wide: British spelling."]


def test_org_isolation(isolated_store):
    s = isolated_store
    s.add_org_memory("acme", "style", "Acme only.")
    assert s.memory_guidance("acme", None, None) == ["Acme only."]
    assert s.memory_guidance("globex", None, None) == []        # never another tenant's memory


def test_guidance_for_is_dark_unless_flagged_on(isolated_store, monkeypatch):
    s = isolated_store
    s.add_org_memory("acme", "style", "Keep alt text under 120 characters.", rule_id="1.1.1")
    monkeypatch.delenv("ACP_REVIEW_MEMORY", raising=False)
    assert _mem.guidance_for(s, "acme", "1.1.1", "docx") == ""   # flag off → dark
    monkeypatch.setenv("ACP_REVIEW_MEMORY", "1")
    g = _mem.guidance_for(s, "acme", "1.1.1", "docx")
    assert "House style" in g and "under 120 characters" in g    # flag on → injected
    assert _mem.guidance_for(s, "globex", "1.1.1", "docx") == ""  # empty org → dark


def test_prompt_is_byte_identical_without_guidance():
    # The safe-dark guarantee at the prompt layer: no guidance ⇒ pre-memory prompt exactly.
    base = _ai._suggest_prompt("2.4.4", "Link Purpose", "f.docx", "click here")
    assert _ai._suggest_prompt("2.4.4", "Link Purpose", "f.docx", "click here", "") == base
    withg = _ai._suggest_prompt("2.4.4", "Link Purpose", "f.docx", "click here",
                                "House style: verb-first link text.")
    assert withg != base and "verb-first" in withg


def test_route_and_wiring_present():
    root = Path(__file__).resolve().parent.parent
    ai_routes = (root / "api" / "routes" / "ai.py").read_text()
    assert '"/org-memory"' in ai_routes and "guidance_for" in ai_routes
    assert "house_style_applied" in ai_routes                   # §E visibility on the card
    assert "_require_admin" in ai_routes                        # authoring is admin-gated


def test_org_memory_route_authors_and_lists(monkeypatch, isolated_store):
    # End-to-end through the real app: author a rule, then read it back org-scoped.
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient

    from app import app
    c = TestClient(app)
    r = c.post("/org-memory", params={"kind": "style", "rule_id": "1.1.1",
                                      "guidance": "Keep alt text under 120 characters."})
    assert r.status_code == 200 and r.json()["status"] == "active"
    g = c.get("/org-memory")
    assert g.status_code == 200
    rules = g.json()["rules"]
    assert len(rules) == 1 and rules[0]["rule_id"] == "1.1.1"
    # a bad kind is rejected (only style/glossary are admin-authorable)
    assert c.post("/org-memory", params={"kind": "derived", "guidance": "x"}).status_code == 422


def test_stage2_guidance_reaches_prose_proposers(monkeypatch):
    # A proposer must pass its guidance through to the model call (stage 2 spread). Mock
    # suggest_fix and assert the guidance arrives — for section headings here (2.4.10).
    import ai
    import proposals
    seen = {}
    monkeypatch.setattr(ai, "is_available", lambda: True)

    def fake_suggest(*a, **kw):
        seen["guidance"] = kw.get("guidance", "MISSING")
        return {"suggestion": "A Heading", "model": "m"}
    monkeypatch.setattr(ai, "suggest_fix", fake_suggest)

    import io
    import zipfile
    P = "<w:p><w:r><w:t>{}</w:t></w:r></w:p>"
    long = "Prose words enough to clear the section floor for this heading proposer test now."
    body = "<w:p></w:p>".join("".join(P.format(long) for _ in range(6)) for _ in range(3))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    (d / "x.docx").write_bytes(buf.getvalue())
    proposals.propose_section_headings(d / "x.docx", ".docx",
                                       guidance="House style: title case, under 8 words.")
    assert "title case" in seen.get("guidance", "")


def test_stage2_handler_computes_per_rule_guidance():
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    assert 'guidance=_g("2.4.4")' in src and 'guidance=_g("2.4.10")' in src
    assert 'guidance=_g("2.4.6")' in src and 'guidance=_g("1.3.3")' in src
    assert "owner_email" in src and "guidance_for" in src


# ── Stage 3: derivation job (hitl_events → PROPOSED rules, human-gated) ───────────
def _seed_scan(s, sid, org):
    s.init_scan_run(sid, "local", 1, "2026-07-12T00:00:00Z", "WCAG 2.1 AA", "h", owner=org)


def test_derivation_proposes_shorten_rule_with_real_evidence(isolated_store):
    import memory as mem
    s = isolated_store
    _seed_scan(s, "d1", "acme")
    # 6 alt-text edits that each shorten the draft substantially → a real shorten signal.
    for i in range(6):
        s.record_hitl_event("d1", f"f{i}.png", "1.1.1", f"i{i}", "edit", edited=True,
                            ai_value="A very long verbose alt text that the reviewer trimmed down a lot here",
                            final_value="Short alt")
    out = mem.derive_org_memory(s, "acme", min_evidence=5)
    assert len(out) == 1
    ev = out[0]["evidence"]
    assert ev["rule"] == "1.1.1" and ev["edited"] == 6 and ev["median_delta_chars"] < -20
    # It is PROPOSED, never active — the human gate (ADR 0021 §D).
    rows = s.list_org_memory("acme", status="proposed")
    assert len(rows) == 1 and rows[0]["kind"] == "derived"
    assert s.list_org_memory("acme", status="active") == []      # never auto-applied
    assert s.memory_guidance("acme", "1.1.1", None) == []         # a proposal never shapes a draft


def test_derivation_respects_min_evidence_floor(isolated_store):
    import memory as mem
    s = isolated_store
    _seed_scan(s, "d2", "acme")
    for i in range(3):                                            # only 3 < floor of 5
        s.record_hitl_event("d2", f"f{i}.png", "1.1.1", f"i{i}", "edit", edited=True,
                            ai_value="A long verbose alt text trimmed right down by the reviewer",
                            final_value="Short")
    assert mem.derive_org_memory(s, "acme", min_evidence=5) == []


def test_derivation_proposes_specificity_from_too_vague_rejects(isolated_store):
    import memory as mem
    s = isolated_store
    _seed_scan(s, "d3", "acme")
    for i in range(5):
        s.record_hitl_event("d3", f"f{i}.png", "2.4.4", f"i{i}", "reject",
                            reject_reason="too_vague")
    out = mem.derive_org_memory(s, "acme", min_evidence=5)
    assert any(p["evidence"].get("rejected_too_vague") == 5 for p in out)


def test_derivation_dedups_and_is_org_isolated(isolated_store):
    import memory as mem
    s = isolated_store
    _seed_scan(s, "d4", "acme")
    for i in range(6):
        s.record_hitl_event("d4", f"f{i}.png", "1.1.1", f"i{i}", "edit", edited=True,
                            ai_value="A long verbose alt text the reviewer trimmed down hard",
                            final_value="Short")
    first = mem.derive_org_memory(s, "acme", min_evidence=5)
    assert len(first) == 1
    assert mem.derive_org_memory(s, "acme", min_evidence=5) == []   # re-run doesn't duplicate
    assert mem.derive_org_memory(s, "globex", min_evidence=5) == [] # another org sees nothing


def test_stage3_route_and_scheduler_wired():
    root = Path(__file__).resolve().parent.parent
    assert '"/org-memory/derive"' in (root / "api" / "routes" / "ai.py").read_text()
    core = (root / "api" / "core.py").read_text()
    assert "_derive_review_memory_tick" in core and "ACP_REVIEW_MEMORY" in core
