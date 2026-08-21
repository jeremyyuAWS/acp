"""R18 · Comments on a finding.

A finding's discussion thread is append-only and anchored to ONE finding within ONE scan
(scan × file × criterion × instance, via a client-computed `finding_key`). These tests pin the
store contract — append, oldest-first read, per-finding scoping, counts, reset-completeness — and
that the route + api.js wiring exists.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def test_add_then_list_oldest_first(isolated_store):
    s = isolated_store
    a = s.add_finding_comment("s1", "deck.pptx||1.1.1||slide3", "jeremy@acp.io",
                              "This one is decorative — should be marked so.",
                              file="deck.pptx", rule_id="1.1.1")
    b = s.add_finding_comment("s1", "deck.pptx||1.1.1||slide3", "deva@acp.io",
                              "Disagree — it carries the quarter's numbers.",
                              file="deck.pptx", rule_id="1.1.1")
    thread = s.list_finding_comments("s1", "deck.pptx||1.1.1||slide3")
    assert [c["id"] for c in thread] == [a["id"], b["id"]]          # oldest first
    assert [c["author"] for c in thread] == ["jeremy@acp.io", "deva@acp.io"]
    assert thread[0]["ts"] <= thread[1]["ts"]
    assert thread[1]["body"].startswith("Disagree")


def test_scoped_to_one_finding(isolated_store):
    s = isolated_store
    s.add_finding_comment("s1", "deck.pptx||1.1.1||slide3", "j@acp.io", "on slide 3")
    s.add_finding_comment("s1", "deck.pptx||1.1.1||slide9", "j@acp.io", "on slide 9")
    s.add_finding_comment("s2", "deck.pptx||1.1.1||slide3", "j@acp.io", "other scan")
    one = s.list_finding_comments("s1", "deck.pptx||1.1.1||slide3")
    assert len(one) == 1 and one[0]["body"] == "on slide 3"         # not slide9, not scan s2


def test_returned_row_shape(isolated_store):
    s = isolated_store
    row = s.add_finding_comment("s1", "f||sc||loc", "j@acp.io", "hi", file="f", rule_id="sc")
    assert set(row) == {"id", "ts", "scan_id", "finding_key", "file", "rule_id", "author", "body"}
    assert row["scan_id"] == "s1" and row["finding_key"] == "f||sc||loc"
    assert row["file"] == "f" and row["rule_id"] == "sc" and row["author"] == "j@acp.io"


def test_empty_thread_is_empty_not_error(isolated_store):
    assert isolated_store.list_finding_comments("no-scan", "no-finding") == []


def test_counts_by_finding(isolated_store):
    s = isolated_store
    s.add_finding_comment("s1", "a", "j@acp.io", "1")
    s.add_finding_comment("s1", "a", "j@acp.io", "2")
    s.add_finding_comment("s1", "b", "j@acp.io", "3")
    counts = s.count_finding_comments("s1")
    assert counts == {"a": 2, "b": 1}
    assert s.count_finding_comments("s-none") == {}


def test_comments_cleared_by_reset(isolated_store):
    s = isolated_store
    s.add_finding_comment("s1", "a", "j@acp.io", "customer note")
    assert "finding_comments" in s.reset_analytics()               # declared as a data table
    assert s.list_finding_comments("s1", "a") == []                # actually gone


def test_route_and_api_wiring():
    root = Path(__file__).resolve().parent.parent
    scans = (root / "api" / "routes" / "scans.py").read_text()
    assert '"/scans/{sid}/comments"' in scans
    assert "add_finding_comment" in scans and "list_finding_comments" in scans
    # author comes from the signed-in user, never from the request body
    assert "core.store.add_finding_comment(\n        sid, finding_key, owner" in scans
    api = (root / "frontend" / "src" / "api.js").read_text()
    assert "getFindingComments" in api and "addFindingComment" in api and "findingKeyOf" in api
    rem = (root / "frontend" / "src" / "Remediate.jsx").read_text()
    assert "FindingComments" in rem
