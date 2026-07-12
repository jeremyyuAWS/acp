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
    # The fan-out enqueue now lives in _enqueue_analysis (shared by the immediate scan and the
    # deferred Assess path, ADR 0020); both the per-file and batch branches must still stamp the
    # shadow_candidate + exclude_remediated flags so the shadow-skip works whenever analysis runs.
    src = HANDLERS.read_text()
    assert src.count('"shadow_candidate": name_counts[_logical_name(') == 2, \
        "scan_file AND scan_batch must both carry shadow_candidate"
    assert src.count('"exclude_remediated": exclude_remediated') == 2


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

def test_shadow_filter_logs_once_per_scan(tmp_path, capsys, monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp_path / "spam.db")
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


# ── the incremental-reuse path, which the first fix missed entirely ──

def test_shadow_check_also_runs_when_prior_analysis_is_reused():
    """With incremental=true, find_prior_analysis() short-circuits the download+analyse block.

    The pre-analysis skip lives inside that block, so on a re-scan the phantom sailed through
    with its reused issues, wrote scan_rule_traces, and reappeared in the human review queue.
    Observed live 2026-07-10T01:53:06Z: get_scan hid it 2s after discovery and no "skipping"
    line was ever printed. The convergent check must sit AFTER both branches.
    """
    src = HANDLERS.read_text()
    # the dedup branch
    dedup = src.index('if dedup:')
    # the convergent check
    check = src.index('and fdict.get("acp_stamped") and fdict.get("status") != "skipped"')
    # the single persist call
    save = src.index('core.store.save_file_result(scan_id, fdict, now)')
    assert dedup < check < save, "the check must run after the dedup branch and before persist"


def test_reused_shadow_record_is_stripped_of_its_issues():
    src = HANDLERS.read_text()
    start = src.index('and fdict.get("acp_stamped") and fdict.get("status") != "skipped"')
    # NB: 'if fdict is None:' also appears earlier, inside the fresh-analysis branch. Anchor on
    # the error-record line that follows the convergent check.
    end = src.index('# fetch/analyse failed', start)
    block = src[start:end]
    assert '"issues": []' in block, "reused issues must be dropped -> no traces -> no HITL item"
    assert '"status": "skipped"' in block
    assert 'pinfo = None' in block, "reused PII must not be carried onto a skipped file"


def test_the_convergent_check_does_not_re_wrap_the_pre_analysis_skip():
    # The fresh-analysis path already produced status='skipped'; re-wrapping would be harmless
    # but the guard makes the intent explicit and keeps the log line printing once.
    src = HANDLERS.read_text()
    assert 'fdict.get("status") != "skipped"' in src
