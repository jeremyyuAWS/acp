"""The scan's progress signal must move, and must never go backwards.

Live symptom (screenshot): the Live Scan Theater showed the "Score" stage lit next to
"0 documents", for the whole scan. Two causes:

  * `analysing` — the long phase — used `ThreadPoolExecutor.map`, which yields nothing until
    the entire batch finishes. It emitted files_done=0 once and never updated.
  * `scoring` then reported its own 0-based index, so the counter fell back to 0.

The theater's stages come from `phase`, which is real. The counter comes from files_done.
"""
import re
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API))

SRC = (API / "scanner.py").read_text()
CODE = "\n".join(l for l in SRC.split("\n") if not l.strip().startswith("#"))


def test_analysing_reports_each_document_as_it_lands():
    # `map` cannot report progress; as_completed can.
    block = CODE[CODE.index('"phase": "analysing"'):CODE.index('"phase": "scoring"')]
    assert "as_completed" in block, "the analysing phase must report per-document progress"
    assert "_ex.map(" not in block, "map() yields nothing until the whole batch finishes"
    assert '"files_done": _done_n' in block


def test_scoring_never_drops_the_counter_back_to_zero():
    # files_done is monotonic across the scan: everything is analysed before scoring begins.
    scoring = re.findall(r'progress\(\{"phase": "scoring"[^}]*\}\)', CODE)
    assert scoring, "scoring must still report progress"
    for call in scoring:
        assert '"files_done": n' in call, f"scoring must report all n analysed: {call}"
        assert "done_i" not in call, f"scoring must not report its own 0-based index: {call}"


def test_every_phase_the_ui_knows_about_is_actually_emitted():
    # frontend/src/phaseNarration.js has a line per phase; a phase it does not know narrates
    # nothing. Keep the two in step.
    emitted = set(re.findall(r'"phase": "(\w+)"', CODE))
    known = {"queued", "connecting", "discovering", "reading", "analysing", "scoring", "done"}
    assert emitted <= known, f"scanner emits a phase the UI cannot narrate: {emitted - known}"


def test_the_scan_really_does_score():
    # The Score stage is not decoration: rb.assess/rb.aggregate run inside run_scan. If this
    # ever stops being true, the UI must stop claiming it.
    assert "rb.assess(" in CODE and "rb.aggregate(" in CODE
