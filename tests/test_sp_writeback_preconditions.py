"""What has to be true before ACP overwrites a document in SharePoint.

THE ORDER WAS THE BUG. `sharepoint_upload`'s in-place path archived the original and THEN replaced
it, with nothing in between asking whether the replace could succeed. A file somebody has checked
out fails the replace — after the copy has already landed in `SP_ARCHIVE_FOLDER/<today>/`. The
original is not lost (the archive is a copy, not a move), but the archive folder accumulates dated
copies of documents that were never replaced, indistinguishable from the ones that were, in the
folder a customer would go to to roll a remediation back.

The quieter case is the one that matters more. A DECLARED RECORD is a document the tenant has
locked under a retention policy; overwriting one is a compliance event, not a failed write.
`sp_metadata` has read `_IsRecord` and `_ComplianceTag` since Phase 2 and its own docstring calls
check-out "the precondition Phase 5 has to check". The fields were read for this purpose and
nothing consumed them.

REFUSING TOO MUCH IS ITS OWN FAILURE, so the boundaries are tested as carefully as the blocks:

  * a retention LABEL alone does not block — it commonly sets a period without locking edits, and
    refusing on it would turn away writes that would have succeeded;
  * an UNREADABLE precondition does not block either — a tenant that refuses the listItem
    expansion would otherwise have every write-back refused by a check that never ran. It
    proceeds, and the response says the preconditions were unverified rather than clear. "We did
    not look" must not read as "we looked and it was fine".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import sp_metadata as M  # noqa: E402
import sp_writeback as W  # noqa: E402


# ── what blocks ──────────────────────────────────────────────────────────────────────────────

def test_a_checked_out_document_is_refused_and_the_holder_is_named():
    r = W.preconditions({"CheckoutUser": "Dana Reed"})
    assert r["ok"] is False
    [b] = r["blockers"]
    assert b["code"] == W.CHECKED_OUT
    assert "Dana Reed" in b["message"]


def test_the_id_only_checkout_shadow_still_blocks():
    """Some tenants return `CheckoutUserLookupId` instead of the readable column. A name nobody
    can read is still evidence that somebody holds the lock, and treating the id-only shape as
    "not checked out" would let the write through to fail after the archive."""
    r = W.preconditions({"CheckoutUserLookupId": 42})
    assert r["ok"] is False and r["blockers"][0]["code"] == W.CHECKED_OUT


def test_a_declared_record_is_refused_as_a_governance_decision():
    r = W.preconditions({"_IsRecord": True, "_ComplianceTag": "Contracts-7y"})
    assert r["ok"] is False
    [b] = r["blockers"]
    assert b["code"] == W.DECLARED_RECORD
    assert "Contracts-7y" in b["message"]
    assert "governance decision" in b["message"]


def test_both_blockers_are_reported_together():
    """One refusal per round-trip. Reporting only the first would send somebody to get a file
    checked in and then refuse it again for being a record."""
    r = W.preconditions({"CheckoutUser": "Dana Reed", "_IsRecord": True})
    assert sorted(b["code"] for b in r["blockers"]) == [W.CHECKED_OUT, W.DECLARED_RECORD]


# ── what deliberately does NOT block ─────────────────────────────────────────────────────────

def test_a_clean_item_passes():
    r = W.preconditions({})
    assert r == {"ok": True, "checked": True, "blockers": [], "notes": []}


def test_a_retention_LABEL_alone_does_not_block():
    """It commonly sets a retention period without locking edits. Refusing on it would turn away
    writes that would have succeeded — refusing too much is its own failure."""
    r = W.preconditions({"_ComplianceTag": "Finance-3y"})
    assert r["ok"] is True
    assert any("Finance-3y" in n for n in r["notes"])
    assert any("does not block" in n for n in r["notes"])


def test_a_record_does_not_ALSO_emit_the_label_note():
    """It is already refused, with the tag named in the refusal. A note saying the same label
    "does not block a replace" beside a blocker that does is a contradiction in one response."""
    r = W.preconditions({"_IsRecord": True, "_ComplianceTag": "Contracts-7y"})
    assert r["notes"] == []


def test_is_record_FALSE_is_not_a_blocker():
    """The tenant said it is not a record. That is an answer, not a missing one."""
    assert W.preconditions({"_IsRecord": False})["ok"] is True


def test_an_UNREADABLE_precondition_proceeds_and_says_it_did_not_check():
    """A tenant that refuses the listItem expansion would otherwise have every write-back refused
    by a check that never ran. Proceeding is exactly today's behaviour and Graph still enforces
    the real rules; what changes is that the answer does not claim to be clean."""
    r = W.preconditions(None, checked=False)
    assert r["ok"] is True and r["checked"] is False
    assert r["blockers"] == []
    assert any("NOT known" in n for n in r["notes"])
    assert any("not a clean check" in n for n in r["notes"])


def test_a_clean_check_and_an_unchecked_one_are_distinguishable():
    """The whole availability contract in one assertion: both pass, and a caller can tell them
    apart. Collapsing them is how "we did not look" becomes "we looked and it was fine"."""
    assert W.preconditions({})["checked"] is True
    assert W.preconditions(None, checked=False)["checked"] is False


# ── one reader of the columns, not two ───────────────────────────────────────────────────────

def test_the_columns_are_read_through_sp_metadata_so_the_two_cannot_drift():
    """`normalize` records these per document and this module refuses a write on them. Two
    readers of `_IsRecord` that disagree is a scan reporting a file as a declared record while the
    write path overwrites it — the drift this repo keeps paying for, on the one field where the
    cost is a compliance event rather than a wrong number."""
    fields = {"CheckoutUser": "Dana Reed", "_IsRecord": True, "_ComplianceTag": "Contracts-7y"}
    assert M.checkout_user(fields) == "Dana Reed"
    assert M.is_record(fields) is True
    assert M.compliance_tag(fields) == "Contracts-7y"
    # And the per-document record agrees with the refusal.
    meta = M.normalize({"id": "i1", "name": "a.docx", "file": {}},
                       list_item=M.Container({"fields": fields}), drive_item=None, rich=None,
                       permissions=None, site_id="S", site_name="S", library_name="L")
    assert meta["fields"]["checked_out_by"]["value"] == "Dana Reed"
    assert meta["fields"]["is_record"]["value"] is True


def test_an_absent_is_record_column_is_None_not_False():
    """"This tenant says it is not a record" and "this tenant did not tell us" are different
    facts. The second must not read as the first on the path that decides an overwrite."""
    assert M.is_record({}) is None
    assert M.is_record({"_IsRecord": False}) is False


# ── the live read ────────────────────────────────────────────────────────────────────────────

def _fetch(payload=None, raises=None, seen=None):
    def get(token, url, **kw):
        if seen is not None:
            seen.append(url)
        if raises:
            raise raises
        return payload
    return get


def test_the_live_read_asks_only_for_the_three_columns_it_decides_on():
    """A bare `$expand=fields` would pull the tenant's entire column set per write-back for three
    values."""
    seen: list = []
    W.read_state("tok", "d1", "i1", get=_fetch({"fields": {}}, seen=seen))
    [url] = seen
    assert "/drives/d1/items/i1/listItem" in url
    for col in ("CheckoutUser", "CheckoutUserLookupId", "_IsRecord", "_ComplianceTag"):
        assert col in url
    assert "$expand=fields($select=" in url


def test_the_live_read_blocks_on_what_it_finds():
    r = W.read_state("tok", "d1", "i1", get=_fetch({"fields": {"CheckoutUser": "Dana Reed"}}))
    assert r["ok"] is False and r["blockers"][0]["code"] == W.CHECKED_OUT


def test_a_failed_read_never_raises_and_never_blocks():
    """A precondition check that can fail the write it is guarding would be worse than no check."""
    r = W.read_state("tok", "d1", "i1", get=_fetch(raises=RuntimeError("http 403")))
    assert r["ok"] is True and r["checked"] is False


def test_a_listItem_with_no_fields_bag_is_UNCHECKED_not_clean():
    """A shape this code does not understand is not a clean read of an unlocked item, and saying
    so costs nothing."""
    for payload in ({}, {"fields": None}, {"fields": "surprise"}, None):
        assert W.read_state("tok", "d1", "i1", get=_fetch(payload))["checked"] is False


def test_onedrive_reads_from_the_personal_drive_root():
    seen: list = []
    W.read_state("tok", None, "i1", get=_fetch({"fields": {}}, seen=seen))
    assert "/me/drive/items/i1/listItem" in seen[0]


# ── the route ────────────────────────────────────────────────────────────────────────────────

class _FakeUpload:
    content_type = "application/octet-stream"

    async def read(self):
        return b"remediated-bytes"


class _FakeRequest:
    def __init__(self, form):
        self._form = form
        self.headers = {"x-sp-token": "tok"}

    async def form(self):
        return self._form


def _upload(monkeypatch, *, fields, archive_calls):
    """Drive the real route. `asyncio.run` rather than a pytest-asyncio marker: this repo has no
    such plugin, and an unknown marker makes an async test body a silent no-op that passes."""
    import scanner
    from routes.sharepoint import sharepoint_upload
    monkeypatch.setattr(W, "read_state",
                        lambda t, d, i, **kw: W.preconditions(fields) if fields is not None
                        else W.preconditions(None, checked=False))
    monkeypatch.setattr(scanner, "_sp_archive_original",
                        lambda *a, **kw: archive_calls.append(a) or "folder")
    monkeypatch.setattr(scanner, "_sp_replace", lambda *a, **kw: {"webUrl": "https://sp/doc"})
    monkeypatch.setattr(scanner, "_sp_describe", lambda *a, **kw: None)
    import asyncio
    return asyncio.run(sharepoint_upload(_FakeRequest(
        {"scan_id": "", "file": "a.docx", "drive_id": "d1", "item_id": "i1",
         "blob": _FakeUpload()})))


def test_a_blocked_write_is_refused_BEFORE_the_archive(monkeypatch):
    """THE ORDER, asserted. A refusal that happened after the archive would still leave the
    orphan copy this check exists to prevent."""
    from fastapi import HTTPException
    archive_calls: list = []
    with pytest.raises(HTTPException) as e:
        _upload(monkeypatch, fields={"CheckoutUser": "Dana Reed"},
                      archive_calls=archive_calls)
    assert e.value.status_code == 409
    assert archive_calls == [], "the original was archived for a write that was then refused"
    assert e.value.detail["blockers"][0]["code"] == W.CHECKED_OUT
    assert e.value.detail["archived"] is False and e.value.detail["replaced"] is False


def test_a_clean_item_is_written_and_the_response_says_it_was_checked(monkeypatch):
    archive_calls: list = []
    out = _upload(monkeypatch, fields={}, archive_calls=archive_calls)
    assert out["replaced"] is True and len(archive_calls) == 1
    assert out["preconditionsChecked"] is True
    assert "preconditionNotes" not in out


def test_an_unverified_write_proceeds_and_the_response_admits_it(monkeypatch):
    """The response must not read as a clean check. A caller storing "preconditions: ok" against
    a write nobody verified is the audit record that matters here."""
    archive_calls: list = []
    out = _upload(monkeypatch, fields=None, archive_calls=archive_calls)
    assert out["replaced"] is True and len(archive_calls) == 1
    assert out["preconditionsChecked"] is False
    assert any("not a clean check" in n for n in out["preconditionNotes"])


def test_a_retention_label_is_carried_into_the_response_without_blocking(monkeypatch):
    out = _upload(monkeypatch, fields={"_ComplianceTag": "Finance-3y"}, archive_calls=[])
    assert out["replaced"] is True and out["preconditionsChecked"] is True
    assert any("Finance-3y" in n for n in out["preconditionNotes"])
