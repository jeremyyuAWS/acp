"""Google Drive rate-limit transparency in the folder-BFS listing path (scanner._search_folder).

Before this, a folder subtree that Drive rate-limited (execute()'s own internal num_retries
already exhausted) was caught, silently skipped, and counted only in the generic
`skipped_errors` bucket — indistinguishable from a permission error, a deleted folder, or any
other failure. A user watching Discover had no way to tell "Drive is throttling this scan" from
any other cause of a stalled-looking run.

This does NOT touch retry behavior or timing — `.execute(num_retries=5)` is untouched. It only
classifies an exception that was already being caught, from information already in it (HTTP
status + Drive's own reason string), so the classification carries none of the risk a change to
the actual backoff logic would.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FOLDER = "application/vnd.google-apps.folder"


class _FakeResp:
    def __init__(self, status):
        self.status = status
        self.reason = "error"


def _rate_limit_error(status=403, reason="userRateLimitExceeded"):
    # HttpError._get_reason() reads data["error"]["message"] unconditionally before it ever looks
    # at data["error"]["errors"] — omitting the top-level "message" key raises a KeyError there,
    # caught and swallowed, which skips populating error_details entirely and silently degrades
    # str(e) to a generic "<HttpError 403 ...>" with none of the reason text. Real Drive error
    # payloads always carry this key; this fixture must too, or it tests a shape Drive never sends.
    content = (
        b'{"error": {"errors": [{"domain": "usageLimits", "reason": "%s", '
        b'"message": "Rate Limit Exceeded"}], "code": %d, "message": "Rate Limit Exceeded"}}'
        % (reason.encode(), status)
    )
    return HttpError(_FakeResp(status), content)


def _permission_denied_error():
    content = (
        b'{"error": {"errors": [{"domain": "global", "reason": "insufficientFilePermissions", '
        b'"message": "The user does not have sufficient permissions for this file."}], '
        b'"code": 403, "message": "The user does not have sufficient permissions for this file."}}'
    )
    return HttpError(_FakeResp(403), content)


class _RaisingReq:
    """A files().list() request whose .execute() raises a fixed exception every call —
    simulating .execute(num_retries=5) having already exhausted its internal retries."""

    def __init__(self, exc):
        self._exc = exc

    def execute(self, num_retries=0):
        raise self._exc


class _OkReq:
    def __init__(self, payload):
        self._p = payload

    def execute(self, num_retries=0):
        return self._p


class _Files:
    def __init__(self, drive):
        self.d = drive

    def list(self, **kw):
        q = kw.get("q", "")
        fid = q.split("'")[1] if q.startswith("'") else None
        if fid in self.d.failing:
            return _RaisingReq(self.d.failing[fid])
        files = self.d.children.get(fid, []) if fid else []
        return _OkReq({"files": files})


class FakeDrive:
    def __init__(self, children, failing=None):
        self.children = children          # {folder_id: [file/folder dicts]}
        self.failing = failing or {}       # {folder_id: exception to raise}

    def files(self):
        return _Files(self)


def _doc(fid, name="doc.docx"):
    return {"id": fid, "name": name, "mimeType": DOCX}


def _folder(fid, name="subfolder"):
    return {"id": fid, "name": name, "mimeType": FOLDER}


def test_is_drive_rate_limit_error_matches_403_rate_limit_reasons():
    assert scanner._is_drive_rate_limit_error(_rate_limit_error(403, "userRateLimitExceeded"))
    assert scanner._is_drive_rate_limit_error(_rate_limit_error(403, "rateLimitExceeded"))
    assert scanner._is_drive_rate_limit_error(_rate_limit_error(403, "quotaExceeded"))


def test_is_drive_rate_limit_error_matches_429():
    assert scanner._is_drive_rate_limit_error(_rate_limit_error(429, "anything"))


def test_is_drive_rate_limit_error_rejects_unrelated_403():
    """A bare permission-denied 403 is a real, different failure — must not be misreported
    as rate-limiting, which would tell the user to wait when the actual problem is access."""
    assert not scanner._is_drive_rate_limit_error(_permission_denied_error())


def test_is_drive_rate_limit_error_rejects_non_http_errors():
    assert not scanner._is_drive_rate_limit_error(ValueError("boom"))
    assert not scanner._is_drive_rate_limit_error(ConnectionError("network blip"))


def test_rate_limited_subtree_is_classified_separately_from_generic_errors():
    drive = FakeDrive(
        children={"root": [_folder("A"), _folder("B"), _folder("C")], "C": [_doc("f3")]},
        failing={"A": _rate_limit_error(), "B": _permission_denied_error()},
    )
    scope: dict = {}
    result = scanner._search_folder(drive, "root", max_files=100, scope_out=scope)
    assert [r["id"] for r in result] == ["f3"]
    # Both A and B failed and were skipped — same as before this change.
    assert scope["skipped_errors"] == 2
    # Only A's failure was Drive rate-limiting; B's was a permission error.
    assert scope["skipped_rate_limited"] == 1


def test_no_rate_limiting_reports_zero_not_absent():
    drive = FakeDrive({"root": [_doc("f1")]})
    scope: dict = {}
    scanner._search_folder(drive, "root", max_files=100, scope_out=scope)
    assert scope["skipped_rate_limited"] == 0


def test_a_rate_limited_folder_still_lets_the_rest_of_the_tree_complete():
    """The whole point: one throttled subtree must not sink the run — sibling subtrees keep
    being walked normally, exactly as a generic per-folder error already did before this."""
    drive = FakeDrive(
        children={"root": [_folder(f"F{i}") for i in range(5)]},
        failing={"F2": _rate_limit_error()},
    )
    for i in range(5):
        if i != 2:
            drive.children[f"F{i}"] = [_doc(f"file{i}")]
    scope: dict = {}
    result = scanner._search_folder(drive, "root", max_files=100, scope_out=scope)
    assert {r["id"] for r in result} == {"file0", "file1", "file3", "file4"}
    assert scope["skipped_rate_limited"] == 1
