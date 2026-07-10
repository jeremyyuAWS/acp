"""ACP's own output must be skipped BEFORE it is analysed, not hidden afterwards.

Live evidence (2026-07-10T01:29:28Z):
    [scan] discovery (whole-Drive): 3 listed · 0 skipped as ACP-generated output · 3 scannable
    [scan] get_scan(...): hiding 1 ACP-generated file(s) shadowing their source: ['... (1).pptx']
Three files were downloaded, parsed by the Office engine, PII-scanned and AI-scanned; the
phantom was then hidden at read time — after we paid for it, and after it had already reached
the human review queue.
"""
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
HANDLERS = Path(__file__).resolve().parent.parent / "api" / "handlers.py"
STORE = Path(__file__).resolve().parent.parent / "api" / "store.py"


# ── the skip happens before the expensive work ──

def test_stamp_check_precedes_analyse_and_assess():
    src = HANDLERS.read_text()
    dl = src.index("_download(it, tmp, svc, sp_token=toks.get(\"sp\"))")
    stamp = src.index("detect_acp_stamp(tmp / name", dl)
    analyse = src.index("analyse_and_assess(tmp, name, detect_pii=pii)", dl)
    assert dl < stamp < analyse, "the stamp check must sit between download and analysis"


def test_skipped_file_still_gets_a_row():
    # count_files_done() counts file_records rows against scan_runs.files. Skipping the row
    # entirely would leave done < total forever and the scan would never finalize.
    src = HANDLERS.read_text()
    block = src[src.index("if item.get(\"shadow_candidate\")"):src.index("if fdict is None:")]
    assert '"status": "skipped"' in block
    assert '"acp_stamped": stamp' in block, "the row must carry the stamp so get_scan hides it"
    assert '"issues": []' in block, "no issues -> no scan_rule_traces -> never reaches HITL"


def test_skip_requires_both_a_name_collision_and_the_stamp():
    # A certified document published back into the estate is stamped but stands alone under its
    # own name. Dropping it on the stamp alone would hide the estate's real document.
    block = HANDLERS.read_text()
    assert 'if item.get("shadow_candidate") and item.get("exclude_remediated"):' in block


def test_both_fanout_paths_carry_the_flag():
    src = HANDLERS.read_text()
    assert src.count('"shadow_candidate": _name_counts[_logical_name(') == 2, \
        "scan_file AND scan_batch must both carry shadow_candidate"
    assert src.count('"exclude_remediated": _exclude_rem') == 2


# ── the collision flag itself ──

def test_shadow_candidate_marks_only_colliding_names():
    from store import logical_name
    items = [{"name": "deck.pptx"}, {"name": "deck (1).pptx"}, {"name": "solo.pdf"}]
    counts = {}
    for it in items:
        counts[logical_name(it["name"])] = counts.get(logical_name(it["name"]), 0) + 1
    flags = {it["name"]: counts[logical_name(it["name"])] > 1 for it in items}
    assert flags == {"deck.pptx": True, "deck (1).pptx": True, "solo.pdf": False}


# ── the log spam ──

def test_shadow_filter_logs_once_per_scan(tmp_path, capsys):
    import store as store_mod
    store_mod._SQLITE_PATH = tmp_path / "spam.db"
    store_mod._SCHEMA[:] = [x for x in store_mod._SCHEMA
                            if not x.strip().upper().startswith("ALTER TABLE")]
    store_mod._shadow_logged.clear()
    st = store_mod.Store()
    st.init_scan_run("s1", "drive", total=2, started_at="t0", rubric_name="r", rubric_hash="h")

    def rec(name, stamped):
        return {"file": name, "engine": "e", "status": "analysed", "score": 1, "compliant": 0,
                "skipped_rules": 0, "acp_stamped": stamped, "issues": []}
    st.save_file_result("s1", rec("deck.pptx", None), "t1")
    st.save_file_result("s1", rec("deck (1).pptx", "2026-07-10"), "t1")

    for _ in range(10):                       # the dashboard polls
        assert [f["file"] for f in st.get_scan("s1")["files"]] == ["deck.pptx"]

    lines = [l for l in capsys.readouterr().out.splitlines() if "hiding" in l]
    assert len(lines) == 1, f"expected one line for ten polls, got {len(lines)}"
