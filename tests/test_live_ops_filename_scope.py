"""Document names are scoped to the viewer's own runs.

Live Operations spans workspace users. A non-admin's runs were already filtered to their own, so
this is really about ADMINS: they see the whole fleet by design, which makes their view the one
path by which another tenant's filename reaches a screen. Before #1574 that was one name per
stage; it is now up to _IN_FLIGHT_LIMIT of them.

What is redacted is the NAME only. Stage, job type, phase, WCAG criterion, runtime, attempts and
every count stay, so an operator can still see that someone else's remediate stage is retrying.
"""
from __future__ import annotations

import pytest

from api.routes import system


ADMIN = "admin@example.org"
VIEWER = "viewer@example.org"
OTHER = "other@example.org"


def _run(owner, **fields):
    return {
        "scan_id": f"scan-{owner}", "owner": owner, "stage": "assess", "status": "active",
        "running": 3, "queued": 7, "current_file": "Board Minutes.docx",
        "current_rule_id": "WCAG 1.4.3", "current_job_type": "assess_file",
        "in_flight": [
            {"job_id": "j1", "file": "Board Minutes.docx", "rule_id": "WCAG 1.4.3",
             "job_type": "assess_file", "phase": "remediating", "attempts": 0},
            {"job_id": "j2", "file": "Payroll 2026.xlsx", "rule_id": "WCAG 1.1.1",
             "job_type": "assess_file", "phase": "verifying", "attempts": 1},
        ],
        **fields,
    }


def _scoped(monkeypatch, runs, viewer, *, admin):
    monkeypatch.setattr(system.core, "is_admin", lambda email: admin)
    return system._scope_activity_snapshot(
        {"runs": runs, "workflows": [], "summary": {}}, viewer)


def _by_owner(scoped, owner):
    return next(row for row in scoped["runs"] if row["owner"] == owner)


# -- the admin case, which is the whole point --------------------------------------------------

def test_an_admin_keeps_their_own_filenames(monkeypatch):
    scoped = _scoped(monkeypatch, [_run(ADMIN)], ADMIN, admin=True)
    mine = _by_owner(scoped, ADMIN)
    assert mine["current_file"] == "Board Minutes.docx"
    assert [job["file"] for job in mine["in_flight"]] == ["Board Minutes.docx", "Payroll 2026.xlsx"]
    assert "file_redacted" not in mine


def test_an_admin_does_not_see_another_tenants_filenames(monkeypatch):
    scoped = _scoped(monkeypatch, [_run(ADMIN), _run(OTHER)], ADMIN, admin=True)
    theirs = _by_owner(scoped, OTHER)

    assert theirs["current_file"] is None
    assert [job["file"] for job in theirs["in_flight"]] == [None, None]
    # The row is still THERE. Redaction is not filtering: an admin must still see that this stage
    # is running, or the operations view stops being one.
    assert theirs["stage"] == "assess"
    assert theirs["running"] == 3
    assert theirs["queued"] == 7


def test_everything_except_the_name_survives_redaction(monkeypatch):
    # Diagnosis has to keep working on a tenant that is not yours: what stage, what kind of job,
    # what it is doing right now, which criterion, and whether it is retrying.
    scoped = _scoped(monkeypatch, [_run(OTHER)], ADMIN, admin=True)
    job = _by_owner(scoped, OTHER)["in_flight"][1]
    assert job["job_type"] == "assess_file"
    assert job["phase"] == "verifying"
    assert job["rule_id"] == "WCAG 1.1.1"
    assert job["attempts"] == 1
    assert job["job_id"] == "j2"


def test_redaction_is_flagged_not_left_as_a_bare_none(monkeypatch):
    """"Withheld from you" and "the handler did not report one" are different facts.

    A UI handed only an empty value will state whichever it assumes, and a screen that says "file
    not reported" about a file that WAS reported is lying about the system rather than protecting
    the tenant.
    """
    scoped = _scoped(monkeypatch, [_run(OTHER)], ADMIN, admin=True)
    theirs = _by_owner(scoped, OTHER)
    assert theirs["file_redacted"] is True
    assert all(job["file_redacted"] is True for job in theirs["in_flight"])


def test_a_run_that_reported_no_filename_is_not_flagged_as_redacted(monkeypatch):
    # The flag must mean "withheld", so it cannot be set on a row that never had a name.
    quiet = _run(ADMIN, current_file=None, in_flight=[])
    scoped = _scoped(monkeypatch, [quiet], ADMIN, admin=True)
    assert "file_redacted" not in _by_owner(scoped, ADMIN)


# -- the non-admin case, where it is a no-op but must still hold -------------------------------

def test_a_non_admin_still_sees_only_their_own_runs_with_names_intact(monkeypatch):
    scoped = _scoped(monkeypatch, [_run(VIEWER), _run(OTHER)], VIEWER, admin=False)
    assert [row["owner"] for row in scoped["runs"]] == [VIEWER]
    assert scoped["runs"][0]["current_file"] == "Board Minutes.docx"


def test_no_foreign_filename_survives_either_path(monkeypatch):
    """The guarantee is one rule, not the interaction of two.

    Redaction runs on the non-admin path as well, where the filter has already removed the
    foreign rows and it therefore changes nothing. That is deliberate: a future change to the
    filter cannot quietly widen what names reach a viewer.
    """
    for admin in (True, False):
        scoped = _scoped(monkeypatch, [_run(VIEWER), _run(OTHER)], VIEWER, admin=admin)
        for row in scoped["runs"]:
            if row["owner"] != VIEWER:
                assert row["current_file"] is None
                assert all(job["file"] is None for job in row["in_flight"])


# -- it must not corrupt the snapshot it was handed --------------------------------------------

def test_the_source_snapshot_is_never_mutated(monkeypatch):
    """The SSE generator and the GET share one builder, and each viewer scopes the result.

    Redacting in place would mean the FIRST viewer's redaction reached every later reader of that
    object -- including the run's own owner, who would then be shown "withheld" about their own
    document.
    """
    monkeypatch.setattr(system.core, "is_admin", lambda email: True)
    source = {"runs": [_run(OTHER)], "workflows": [], "summary": {}}

    system._scope_activity_snapshot(source, ADMIN)

    assert source["runs"][0]["current_file"] == "Board Minutes.docx"
    assert [job["file"] for job in source["runs"][0]["in_flight"]] == [
        "Board Minutes.docx", "Payroll 2026.xlsx"]
    assert "file_redacted" not in source["runs"][0]

    # And the owner, scoped afterwards from the same object, still gets their own name.
    theirs = system._scope_activity_snapshot(source, OTHER)
    assert theirs["runs"][0]["current_file"] == "Board Minutes.docx"


@pytest.mark.parametrize("owner", ["OTHER@EXAMPLE.ORG", "  other@example.org  "])
def test_ownership_is_compared_case_and_whitespace_insensitively(monkeypatch, owner):
    # An owner recorded with different casing is the SAME tenant. Comparing raw would redact a
    # viewer's own documents from them, which reads as a bug rather than as a policy.
    scoped = _scoped(monkeypatch, [_run(owner)], "other@example.org", admin=True)
    assert scoped["runs"][0]["current_file"] == "Board Minutes.docx"


def test_a_malformed_in_flight_entry_does_not_break_scoping(monkeypatch):
    # in_flight comes from a JSON payload column; a row a partially-rolled-forward replica wrote
    # in an unexpected shape must cost that entry, never the whole live map.
    odd = _run(OTHER, in_flight=["not-a-dict", {"job_id": "j9", "file": "Secret.docx"}])
    scoped = _scoped(monkeypatch, [odd], ADMIN, admin=True)
    entries = _by_owner(scoped, OTHER)["in_flight"]
    assert entries[0] == "not-a-dict"
    assert entries[1]["file"] is None
