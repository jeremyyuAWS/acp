"""get_scan()'s per-file issue_records read used to issue one SELECT per file, sequentially,
inside the request — a real estate is thousands of files, not the handful in a test fixture, so
this was thousands of separate network round trips on every Discover/Overview/Assess load.

Found live 2026-08-30: a ~6,916-file production scan's Discover tab sat on "Loading your
inventory…" indefinitely. frontend/src/api.js's getScan() is a plain fetch() with no client-side
timeout, so a slow backend response here doesn't error — it just hangs the tab forever. The exact
same bug class as add_inventory's per-row INSERT loop (#880, also a real ~6,922-file scan) — this
is its unfixed sibling on the read side.

Fix: one SELECT for every file's issues, grouped in Python, instead of N. These pin the batched
path (one query, not N) and that the grouping is still correct — same issues attached to the
same files, files with zero issues get [], multiple issues per file all survive.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _report(files):
    return {"started_at": "2026-08-30T00:00:00+00:00", "completed_at": "2026-08-30T00:01:00+00:00",
            "source": "drive", "rubric": {"name": "WCAG 2.1 AA", "hash": "abc123"},
            "summary": {"files": len(files), "certifiable": 0, "uncertain": 0, "error": 0,
                        "avg_score": 80},
            "files": files}


def _file(name, issues=None):
    return {"file": name, "engine": "office", "status": "FAIL" if issues else "PASS",
            "score": 60 if issues else 100, "compliant": 0 if issues else 1, "skipped_rules": 0,
            "issues": issues or []}


def _issue(rule_id, wcag="1.1.1", severity="SERIOUS"):
    return {"ruleId": rule_id, "wcag": wcag, "severity": severity, "detail": f"{rule_id} finding",
            "page": 1, "location": None}


class TestGetScanIssuesBatching:
    def test_issues_are_fetched_in_one_query_not_per_file(self, isolated_store, monkeypatch):
        """30 files, most with issues — get_scan() must issue exactly ONE query against
        issue_records, not 30. The whole point of the fix."""
        files = [_file(f"doc_{i:03d}.docx", [_issue(f"rule-{i}-a"), _issue(f"rule-{i}-b")])
                 for i in range(25)]
        files += [_file(f"clean_{i:03d}.docx") for i in range(5)]   # no issues at all
        sid = isolated_store.save_scan(_report(files))

        calls = {"issue_queries": 0}
        real_execute = isolated_store._db.execute

        def _counted_execute(cur, sql, params=()):
            if "FROM issue_records" in sql:
                calls["issue_queries"] += 1
            return real_execute(cur, sql, params)

        monkeypatch.setattr(isolated_store._db, "execute", _counted_execute)

        scan = isolated_store.get_scan(sid)

        assert calls["issue_queries"] == 1, \
            f"expected exactly one issue_records query for 30 files, got {calls['issue_queries']}"
        assert len(scan["files"]) == 30

    def test_each_file_gets_its_own_issues_not_a_neighbours(self, isolated_store):
        files = [_file("a.docx", [_issue("rule-a1")]),
                 _file("b.docx", [_issue("rule-b1"), _issue("rule-b2")]),
                 _file("c.docx")]   # clean
        sid = isolated_store.save_scan(_report(files))

        scan = isolated_store.get_scan(sid)
        by_name = {f["file"]: f for f in scan["files"]}

        assert [i["rule_id"] for i in by_name["a.docx"]["issues"]] == ["rule-a1"]
        assert sorted(i["rule_id"] for i in by_name["b.docx"]["issues"]) == ["rule-b1", "rule-b2"]
        assert by_name["c.docx"]["issues"] == []

    def test_issue_fields_survive_the_batched_read_unchanged(self, isolated_store):
        """Same field set as before the fix: rule_id, wcag, severity, detail, page, location."""
        files = [_file("a.docx", [_issue("rule-1", wcag="1.4.3", severity="CRITICAL")])]
        sid = isolated_store.save_scan(_report(files))

        scan = isolated_store.get_scan(sid)
        issue = scan["files"][0]["issues"][0]

        assert issue["rule_id"] == "rule-1"
        assert issue["wcag"] == "1.4.3"
        assert issue["severity"] == "CRITICAL"
        assert issue["detail"] == "rule-1 finding"
        assert issue["page"] == 1
        assert "location" in issue
