"""Every TEXT-model gate must ask "is the model pulled", not "did Ollama answer the door".

The two questions came apart on 2026-07-29. An Ollama was reachable but had never pulled
OLLAMA_MODEL, so `ai.is_available()` was true (GET /api/tags answered), every POST /api/generate
returned 404 "model not found", and each model-backed proposer returned []. An empty proposal
list is exactly what a clean document produces, so the remediation pipeline reported "no
proposals for this finding" and the missing model never surfaced anywhere.

`ai.model_is_available()` was added for precisely this distinction and `vision_is_available()`
was already used correctly; `is_available()` was the one too-weak gate left in front of text.

Two layers here, because each catches what the other cannot:

  * A live stub Ollama — reachable, zero models, 404 on every generate — run against the real
    proposers. This reproduces the production condition exactly and is the only thing that can
    prove no wasted /api/generate call is issued. Bound to an ephemeral port, so a developer
    with a real Ollama on 11434 still gets a truthful run.
  * A source guard over the gate call sites, so a seventh proposer written next month cannot
    quietly reintroduce `is_available()` in front of a text draft.
"""
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

API = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API))
import ai  # noqa: E402
import proposals  # noqa: E402
import textchecks  # noqa: E402

SENSORY = "Click the round green button on the right to submit the form."
PROSE = ("The organization must fundamentally reconsider its longstanding operational assumptions "
         "because the accelerating pace of technological transformation renders previously "
         "dependable strategic frameworks increasingly inadequate for contemporary conditions.")


# ── a reachable Ollama that cannot generate ────────────────────────────────────
class _Modelless(BaseHTTPRequestHandler):
    """GET /api/tags -> 200 {"models": []};  POST /api/generate -> 404 model not found."""
    generates: list[str] = []

    def log_message(self, *a):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._json(200, {"models": []}) if self.path.startswith("/api/tags") else self.send_error(404)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        type(self).generates.append(self.path)
        self._json(404, {"error": "model not found"})


@pytest.fixture
def modelless_ollama(monkeypatch):
    """Point api/ai.py at a live, reachable, model-free Ollama. Yields the generate-call log."""
    _Modelless.generates = []
    srv = HTTPServer(("127.0.0.1", 0), _Modelless)          # port 0: never collides with a real Ollama
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)   # no store in this harness
    monkeypatch.setattr(ai, "OLLAMA_BASE_URL", f"http://127.0.0.1:{srv.server_port}")
    ai.reset_probe_cache()
    try:
        yield _Modelless.generates
    finally:
        srv.shutdown()
        srv.server_close()
        ai.reset_probe_cache()


def test_the_stub_reproduces_the_incident_exactly(modelless_ollama):
    """The premise of every assertion below: reachable and green, but incapable."""
    assert ai.is_available() is True           # the reading that misled everyone
    assert ai.model_is_available() is False    # ...and the one that was actually true


# ── the proposers, against that Ollama ─────────────────────────────────────────
def test_sensory_proposer_is_closed_and_wastes_no_generate_call(modelless_ollama):
    assert proposals.propose_sensory_rewrite(SENSORY, filename="f.docx", ai_enabled=True) == []
    assert modelless_ollama == [], (
        "gated on is_available(), so it POSTed to /api/generate and ate a 404 per finding")


def test_reading_level_proposer_is_closed_and_wastes_no_generate_call(modelless_ollama, monkeypatch):
    # The proposer self-gates on the real detector first; force it open so the AI gate is what
    # this test measures, not the readability score of the sample prose.
    monkeypatch.setattr(textchecks, "detect_reading_level", lambda t: [{"wcag": "3.1.5"}])
    assert proposals.propose_reading_level(PROSE, filename="f.docx", ai_enabled=True) == []
    assert modelless_ollama == []


def test_simplify_text_declines_before_the_wire(modelless_ollama):
    """ai.simplify_text is the reading-level proposer's inner call and had the same weak gate."""
    assert ai.simplify_text(PROSE) is None
    assert modelless_ollama == []


def test_the_missing_model_is_named_in_the_log(modelless_ollama, capsys):
    """Silent degradation was the whole defect — the operator gets one actionable line."""
    ai._MISSING_TEXT_MODEL_WARNED.clear()
    ai.model_is_available()
    out = capsys.readouterr().out
    assert ai.OLLAMA_MODEL in out and "not pulled" in out.lower()
    assert "ollama pull" in out.lower()          # the remedy, not just the symptom

    ai.model_is_available()                      # once per (endpoint, model), not once per file
    assert capsys.readouterr().out == ""


# ── the gate opens again when the model is actually pulled ─────────────────────
def _pulled(monkeypatch, model="llama3.2"):
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    monkeypatch.setattr(ai, "_tags_cached", lambda: [{"name": f"{model}:latest"}])
    monkeypatch.setattr(ai, "OLLAMA_MODEL", model)


def test_a_pulled_text_model_lets_the_proposers_through(monkeypatch):
    """The tightened gate must not be a blanket off-switch."""
    _pulled(monkeypatch)
    monkeypatch.setattr(ai, "suggest_fix",
                        lambda *a, **k: {"suggestion": "Click Approve.", "model": "llama3.2"})
    assert ai.model_is_available() is True
    assert proposals.propose_sensory_rewrite(SENSORY, filename="f.docx", ai_enabled=True)

    monkeypatch.setattr(textchecks, "detect_reading_level", lambda t: [{"wcag": "3.1.5"}])
    monkeypatch.setattr(ai, "simplify_text", lambda s, **k: "A shorter, clearer sentence.")
    assert proposals.propose_reading_level(PROSE, filename="f.docx", ai_enabled=True)


def test_an_unreachable_ollama_still_closes_the_gate(monkeypatch):
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    monkeypatch.setattr(ai, "_tags_cached", lambda: None)
    assert ai.model_is_available() is False
    assert proposals.propose_sensory_rewrite(SENSORY, filename="f.docx", ai_enabled=True) == []


# ── the user-facing route says which model is missing ──────────────────────────
def test_the_route_names_the_missing_model_instead_of_asking_about_ollama(monkeypatch):
    """"is Ollama running?" is the wrong question when Ollama is running.

    api.js turns the 503 detail into the error text on the review card (`body.detail` →
    `new Error(detail)`), so this string is what the reviewer actually reads.
    """
    from fastapi import HTTPException
    import core
    import routes.ai as rai

    monkeypatch.setattr(core, "store", type("S", (), {
        "get_ai_enabled": staticmethod(lambda: True)})())
    monkeypatch.setenv("ACP_AI_BACKEND", "ollama")
    monkeypatch.setattr(ai, "is_available", lambda: True)       # Ollama IS up...
    monkeypatch.setattr(ai, "model_is_available", lambda: False)  # ...and has no text model

    with pytest.raises(HTTPException) as e:
        rai.ai_explain(scan_id="s1", file="p.docx", rule_id="2.4.4")
    assert e.value.status_code == 503
    detail = e.value.detail
    assert "is Ollama running?" not in detail, "blames the wrong thing — Ollama IS running"
    assert ai.OLLAMA_MODEL in detail and "ollama pull" in detail


def _suggest_route(monkeypatch, rule_id, *, text_ok, vision_ok, reachable=True):
    """Call /ai/suggest's handler with the capability probes forced, returning its HTTPException
    detail — or None when the gate let the request through."""
    from fastapi import HTTPException
    import core
    import routes.ai as rai

    monkeypatch.setattr(core, "store", type("S", (), {
        "get_ai_enabled": staticmethod(lambda: True),
        "get_trace_row": staticmethod(lambda *a: None)})())     # 404s AFTER the gate
    monkeypatch.setenv("ACP_AI_BACKEND", "ollama")
    monkeypatch.setattr(ai, "is_available", lambda: reachable)
    monkeypatch.setattr(ai, "model_is_available", lambda: text_ok)
    monkeypatch.setattr(ai, "vision_is_available", lambda: vision_ok)
    try:
        rai.ai_suggest(request=object(), scan_id="s1", file="p.docx", rule_id=rule_id)
    except HTTPException as e:
        return None if e.status_code == 404 else e.detail   # 404 = gate passed, trace absent
    return None


def test_suggest_names_the_text_model_for_a_text_criterion(monkeypatch):
    detail = _suggest_route(monkeypatch, "2.4.4", text_ok=False, vision_ok=True)
    assert detail and "is Ollama running?" not in detail
    assert f"text model '{ai.OLLAMA_MODEL}'" in detail


def test_suggest_still_serves_alt_text_from_a_vision_only_ollama(monkeypatch):
    """1.1.1 is the one criterion the vision model answers alone. Tightening the TEXT gate must
    not take alt-text drafting away from a deployment that only ever pulled the vision model."""
    assert _suggest_route(monkeypatch, "1.1.1", text_ok=False, vision_ok=True) is None


def test_suggest_names_both_models_when_neither_can_serve_an_image(monkeypatch):
    detail = _suggest_route(monkeypatch, "1.1.1", text_ok=False, vision_ok=False)
    assert detail and ai.OLLAMA_MODEL in detail and ai.OLLAMA_VISION_MODEL in detail


def test_an_actually_down_ollama_still_gets_the_ollama_message(monkeypatch):
    """The original message is still right for the original cause; don't lose it."""
    from fastapi import HTTPException
    import core
    import routes.ai as rai

    monkeypatch.setattr(core, "store", type("S", (), {
        "get_ai_enabled": staticmethod(lambda: True)})())
    monkeypatch.setenv("ACP_AI_BACKEND", "ollama")
    monkeypatch.setattr(ai, "is_available", lambda: False)
    monkeypatch.setattr(ai, "model_is_available", lambda: False)

    with pytest.raises(HTTPException) as e:
        rai.ai_explain(scan_id="s1", file="p.docx", rule_id="2.4.4")
    assert "is Ollama running?" in e.value.detail


# ── drift guard: no text draft may gate on reachability again ──────────────────
# The six proposals.py sites were found by reading; this is what stops a seventh being written
# the old way. Scoped to lines that gate on the `ai` module (never ocr.is_available(), which is
# tesseract and has no model).
_AI_REACHABILITY_GATE = re.compile(r"\b_ai\.is_available\s*\(")


@pytest.mark.parametrize("rel", ["proposals.py", "remediate.py", "remediate_office.py",
                                 "handlers.py"])
def test_no_proposer_gates_a_draft_on_mere_reachability(rel):
    """In the proposal/remediation modules there is no correct use of _ai.is_available() at all:
    every model call there is a text draft (or a vision one, which has its own probe)."""
    src = (API / rel).read_text()
    offenders = [f"{rel}:{n}  {ln.strip()}"
                 for n, ln in enumerate(src.splitlines(), 1)
                 if _AI_REACHABILITY_GATE.search(ln)]
    assert not offenders, (
        "gate a TEXT draft on ai.model_is_available() (or vision_is_available() for vision) — "
        "ai.is_available() only proves /api/tags answered:\n  " + "\n  ".join(offenders))


def test_the_draft_routes_consult_capability_not_just_reachability():
    """routes/ai.py legitimately still calls is_available() — to CHOOSE THE MESSAGE once the
    capability gate has already failed, and to report `available` from /ai/status, which is
    what that field means. So pin the gates themselves rather than banning the name."""
    src = (API / "routes/ai.py").read_text()
    for fn in ("def ai_explain", "def ai_suggest"):
        body = src.split(fn, 1)[1].split("\n@router", 1)[0]
        assert "model_is_available()" in body, f"{fn} must gate on the TEXT model, not reachability"


def test_the_one_remaining_reachability_gate_is_the_known_vision_one():
    """/ai/validate still fast-fails on is_available() while validate_alt_text needs the VISION
    model. Deliberately out of this change's scope (it is a vision gate, not a text one) and
    harmless — validate_alt_text re-checks vision_is_available() itself and returns {}. Recorded
    here so the remaining site is a known quantity rather than something nobody wrote down."""
    src = (API / "routes/ai.py").read_text()
    body = src.split("def ai_validate", 1)[1].split("\n@router", 1)[0]
    assert "_ai.is_available()" in body        # if this fails, someone fixed it — delete this test
    assert "vision_is_available" in (API / "ai.py").read_text()


def test_ocr_availability_is_left_alone():
    """propose_images_of_text gates on tesseract, not a model — it must NOT be swept up."""
    src = (API / "proposals.py").read_text()
    assert "_ocr.is_available()" in src
