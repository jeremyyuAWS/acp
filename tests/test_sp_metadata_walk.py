"""The walk that reads SharePoint-native metadata, and the promise it must never break.

A metadata feature that could not be tested against a live tenant must not be able to break
SCANNING. That was the pre-Phase-2 design's whole argument for paying one Graph call per document
to read a single field: a malformed `$expand` on the listing call fails the listing, and the
listing is the product.

Phase 2 keeps the promise and drops the per-document cost by TIERING the request instead of
avoiding it — rich select + expansion, then base select + expansion, then the exact request that
shipped before. What is lost when a tenant refuses an ask is the metadata, never the files. And
what the walk records is WHICH ask was refused, so a field nobody could read is reported as
unread rather than as unset (see tests/test_sp_metadata.py for why that is the whole point).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import scanner       # noqa: E402
import sp_metadata   # noqa: E402


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.content = b""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _graph(*, reject_expand=False, reject_rich=False, seen=None, item=None, with_list_item=True):
    """A Graph stand-in that refuses the asks a real tenant refuses.

    `reject_rich` is the tenant that does not offer `retentionLabel`; `reject_expand` the one
    that will not expand `listItem`. Both answer the base request perfectly, which is the case
    that matters: the listing must survive either.
    """
    doc = item or {"id": "i1", "name": "policy.docx", "file": {"mimeType": "application/msword"},
                   "createdBy": {"user": {"displayName": "Alice Brown"}},
                   "parentReference": {"driveId": "d1"}}

    def get(url, headers=None, timeout=None, follow_redirects=None):
        if seen is not None:
            seen.append(url)
        if "retentionLabel" in url and reject_rich:
            return _Resp({"error": {"message": "unknown property retentionLabel"}}, status=400)
        if "expand=listItem" in url and reject_expand:
            return _Resp({"error": {"message": "expand not supported here"}}, status=400)
        payload = dict(doc)
        if "expand=listItem" in url and with_list_item:
            payload["listItem"] = {"contentType": {"name": "Policy Document"},
                                   "fields": {"Records Category": "Superseded",
                                              "_UIVersionString": "4.0"}}
        if "retentionLabel" in url:
            payload["retentionLabel"] = {"name": "Retain 7 Years"}
        return _Resp({"value": [payload]})
    return get


def _walk(monkeypatch, **kw):
    import httpx
    seen: list[str] = []
    monkeypatch.setattr(httpx, "get", _graph(seen=seen, **kw))
    raw, _ = scanner._sp_walk_folder("tok", "d1", "root", 50, {".docx"})
    return raw, seen


# ── the happy path: everything in one page, no per-document calls ────────────────────────────

def test_the_columns_arrive_on_the_LISTING_page_not_one_call_per_document(monkeypatch):
    """The cost argument for Phase 2. The old content-type read was one Graph call per scannable
    document for a single field; this gets the whole column bag on the page the walk already
    fetches, so a 6,000-document library costs what it costs today."""
    raw, seen = _walk(monkeypatch)
    assert len(seen) == 1, f"the walk made {len(seen)} calls for one page: {seen}"
    assert "expand=listItem" in seen[0] and "retentionLabel" in seen[0]
    assert raw[0]["_acp_list_item"]["fields"]["Records Category"] == "Superseded"


def test_a_full_read_normalizes_to_the_tenants_own_vocabulary(monkeypatch):
    raw, _ = _walk(monkeypatch)
    meta = scanner._sp_item_metadata(raw[0], site_id="c,1,1", site_name="Regulatory",
                                     library_name="Policies")
    v = sp_metadata.values(meta)
    assert v["content_type"] == "Policy Document"
    assert v["retention_label"] == "Retain 7 Years"
    assert v["managed_columns"] == {"Records Category": "Superseded"}


# ── the tiers, and what each one costs ───────────────────────────────────────────────────────

def test_a_refused_wider_select_loses_the_label_and_keeps_the_columns(monkeypatch):
    """A tenant with no retention plan refuses `retentionLabel` and still has managed metadata.
    Falling straight to the base request would throw away a working expansion to punish an ask
    that failed beside it."""
    raw, seen = _walk(monkeypatch, reject_rich=True)
    assert len(raw) == 1, "the listing was lost to a metadata ask"
    meta = scanner._sp_item_metadata(raw[0], site_id="c,1,1", site_name="S", library_name="L")
    states = sp_metadata.availability(meta)
    assert states["retention_label"] == sp_metadata.UNAVAILABLE
    assert states["managed_columns"] == sp_metadata.PRESENT
    assert any("$select" in u and "expand=listItem" in u and "retentionLabel" not in u
               for u in seen), f"never tried tier 1: {seen}"


def test_a_refused_expansion_loses_the_columns_and_keeps_the_LISTING(monkeypatch):
    """The promise. A tenant that refuses both asks still gets scanned — with exactly the request
    that shipped before Phase 2 — and the fields it could not answer are reported unread."""
    raw, seen = _walk(monkeypatch, reject_rich=True, reject_expand=True)
    assert [r["name"] for r in raw] == ["policy.docx"], "a metadata ask cost the listing"
    assert seen[-1].endswith("&$top=200"), f"the floor request was not plain: {seen[-1]}"
    meta = scanner._sp_item_metadata(raw[0], site_id="c,1,1", site_name="S", library_name="L")
    states = sp_metadata.availability(meta)
    assert states["content_type"] == sp_metadata.UNAVAILABLE
    assert states["managed_columns"] == sp_metadata.UNAVAILABLE
    assert "refused the listItem expansion" in meta["fields"]["content_type"]["reason"]


def test_the_tier_is_held_for_the_whole_DRIVE_not_retried_per_folder(monkeypatch):
    """A drive that refuses the expansion refuses it everywhere. Re-attempting the wider ask on
    every folder of a deep library spends one failed round trip per folder to learn the same
    thing — on a customer's tenant, against their throttling budget."""
    import httpx
    seen: list[str] = []
    folders = {"root": [{"id": "f1", "name": "Sub", "folder": {}}],
               "f1": [{"id": "f2", "name": "Deeper", "folder": {}}], "f2": []}

    def get(url, headers=None, timeout=None, follow_redirects=None):
        seen.append(url)
        if "expand=listItem" in url:
            return _Resp({"error": {}}, status=400)
        key = next((k for k in ("f1", "f2") if f"items/{k}" in url), "root")
        return _Resp({"value": folders[key] + [
            {"id": f"i-{key}", "name": f"{key}.docx", "file": {}}]})

    monkeypatch.setattr(httpx, "get", get)
    raw, _ = scanner._sp_walk_folder("tok", "d1", "root", 50, {".docx"})
    assert len(raw) == 3
    # TWO failed attempts in total — one per TIER of the ladder, both spent on the first folder.
    # Retried per folder this would be six across three folders, and on a library with hundreds
    # of folders it would be hundreds of round trips to re-learn one refusal.
    assert sum(1 for u in seen if "expand=listItem" in u) == 2, seen
    assert all("expand=listItem" not in u for u in seen if "items/f2" in u), seen


def test_a_403_is_raised_not_demoted(monkeypatch):
    """A missing scope on the DRIVE is not a refused ask, and stepping down would turn it into a
    silently metadata-less success. Phase 1's per-site isolation reads this exception to mark the
    site blocked; swallowing it here would make a blocked site look complete and empty."""
    import httpx
    monkeypatch.setattr(httpx, "get",
                        lambda url, **kw: _Resp({"error": {"message": "Access denied"}}, status=403))
    with pytest.raises(PermissionError):
        scanner._sp_walk_folder("tok", "d1", "root", 50, {".docx"})


def test_a_real_failure_on_the_floor_request_still_raises(monkeypatch):
    """Tier 2 is the floor. Demoting past it would swallow a genuinely broken drive and report an
    empty library, which is the silent under-reporting this connector's whole design fights."""
    import httpx
    monkeypatch.setattr(httpx, "get",
                        lambda url, **kw: _Resp({"error": {}}, status=500))
    with pytest.raises(Exception):
        scanner._sp_walk_folder("tok", "d1", "root", 50, {".docx"})


def test_the_operator_can_turn_the_expansion_off_without_a_code_change(monkeypatch):
    monkeypatch.setenv("ACP_SP_LIST_FIELDS", "0")
    raw, seen = _walk(monkeypatch)
    assert all("expand=listItem" not in u for u in seen)
    meta = scanner._sp_item_metadata(raw[0], site_id=None, site_name=None, library_name=None)
    f = meta["fields"]["content_type"]
    assert f["state"] == sp_metadata.UNAVAILABLE and "ACP_SP_LIST_FIELDS=0" in f["reason"]


# ── a personal OneDrive has no backing list at all ───────────────────────────────────────────

def test_a_drive_with_no_backing_list_says_that_rather_than_claiming_the_tenant_sets_nothing(monkeypatch):
    """Graph grants the expansion and returns no listItem for the item: a personal OneDrive file.
    That is neither a refusal nor an unconfigured library, and reporting it as `not_configured`
    would put "this document has no content type" next to a drive where content types cannot
    exist."""
    raw, _ = _walk(monkeypatch, with_list_item=False)
    meta = scanner._sp_item_metadata(raw[0], site_id=None, site_name=None, library_name=None)
    f = meta["fields"]["content_type"]
    assert f["state"] == sp_metadata.UNAVAILABLE
    assert "no backing SharePoint list" in f["reason"]


# ── what reaches the inventory row ───────────────────────────────────────────────────────────

def test_the_inventory_row_carries_the_values_AND_the_availability(monkeypatch):
    """An empty `retention_label` cell is uninterpretable on its own. The availability map is
    persisted at the row so the distinction survives to an export and an auditor — which is the
    exit gate stated as a column."""
    import json
    raw, _ = _walk(monkeypatch)
    meta = scanner._sp_item_metadata(raw[0], site_id="c,1,1", site_name="Regulatory",
                                     library_name="Policies")
    row = scanner._inv_row(file="policy.docx", site_id="c,1,1", library_name="Policies",
                           site_name="Regulatory", sp_meta=meta)
    assert row["content_type"] == "Policy Document"
    assert row["retention_label"] == "Retain 7 Years"
    assert row["site_name"] == "Regulatory"
    blob = json.loads(row["sp_metadata"])
    assert blob["managed_columns"] == {"Records Category": "Superseded"}
    assert blob["availability"]["sensitivity_label"] == sp_metadata.UNAVAILABLE
    assert "beta" in blob["reasons"]["sensitivity_label"]


def test_an_unread_field_writes_NULL_not_a_placeholder(monkeypatch):
    """A column that stored "unavailable" as its VALUE would match a rule looking for that string
    and would print as a retention label in an export. The state belongs in the map; the column
    holds a value or nothing."""
    raw, _ = _walk(monkeypatch, reject_rich=True, reject_expand=True)
    meta = scanner._sp_item_metadata(raw[0], site_id="c,1,1", site_name="S", library_name="L")
    row = scanner._inv_row(file="policy.docx", sp_meta=meta)
    assert row["content_type"] is None and row["retention_label"] is None


# ── the cost argument, asserted ──────────────────────────────────────────────────────────────

def test_the_walk_supplying_a_content_type_cancels_the_per_document_call(monkeypatch):
    """Phase 2 must not be one extra Graph call per document ON TOP of what shipped before.

    The pre-Phase-2 enrichment made exactly that call for every scannable file, to read one
    field. Now the listing page carries it — and if the enrichment still ran unconditionally, the
    new read would be pure addition: the same per-document cost, plus a wider listing request.
    """
    import httpx
    seen: list[str] = []
    monkeypatch.setattr(httpx, "get", _graph(seen=seen))
    monkeypatch.delenv("ACP_SP_CONTENT_TYPE", raising=False)
    files = scanner._sp_list("tok", 50, site=None)
    assert files[0]["content_type"] == "Policy Document"
    assert not any("/listItem?" in u for u in seen), \
        f"paid a per-document call for a field the walk already had: {seen}"


def test_the_per_document_call_is_still_there_for_a_tenant_that_refuses_the_expansion(monkeypatch):
    """The fallback has to survive. A tenant whose expansion is refused loses the managed
    columns; it must not also lose the one field ACP could always read."""
    import httpx
    seen: list[str] = []
    monkeypatch.setattr(httpx, "get", _graph(seen=seen, reject_rich=True, reject_expand=True))
    monkeypatch.delenv("ACP_SP_CONTENT_TYPE", raising=False)
    scanner._sp_list("tok", 50, site=None)
    assert any("/listItem?" in u for u in seen), "the fallback path was removed with the cost"
