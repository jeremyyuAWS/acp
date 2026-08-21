"""SharePoint's Content Type, read best-effort and never at the cost of the scan itself.

UNVERIFIED AGAINST A LIVE TENANT — flagged in the code and here. `fields.ContentType` is the
standard SharePoint column every list item carries, which makes it the most likely-correct shape
to guess at, but it has not been confirmed against a real Graph response. What IS verified here is
that the feature is safe on every failure mode a real tenant could hand back: wrong shape, missing
field, permission refusal, network error, or simply "SharePoint doesn't support this" — all resolve
to `content_type: None`, which is the honest default the whole frontend pipeline is built to render
correctly (contentTypeBreakdown.js, discoveryInventory.js).

THE ONE THING THIS FEATURE MUST NEVER DO is break the walk-not-search enumeration fix that shipped
earlier tonight — a malformed classification call must never propagate and fail a listing that
would otherwise have succeeded.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _file(fid, name, path="/drive/root:"):
    return {"id": fid, "name": name, "file": {"mimeType": DOCX}, "parentReference": {"path": path}}


def _routed(pages, seen=None):
    def sp_get(token, url):
        if seen is not None:
            seen.append(url)
        for key, payload in pages.items():
            if key in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"unrouted URL: {url}")
    return sp_get


class TestSpContentType:
    def test_reads_the_field_when_present(self, monkeypatch):
        seen = []
        monkeypatch.setattr(scanner, "_sp_get", _routed({
            "items/i1/listItem": {"fields": {"ContentType": "Policy"}},
        }, seen))
        assert scanner._sp_content_type("tok", "https://graph.microsoft.com/v1.0/me/drive", "i1") == "Policy"
        assert any("$expand=fields" in u for u in seen)

    def test_returns_none_when_the_field_is_absent(self, monkeypatch):
        monkeypatch.setattr(scanner, "_sp_get", _routed({"items/i1/listItem": {"fields": {}}}))
        assert scanner._sp_content_type("tok", "base", "i1") is None

    def test_returns_none_when_there_is_no_listItem_at_all(self, monkeypatch):
        # A personal OneDrive item with no backing SharePoint list, or a Graph shape that dropped
        # the relationship entirely — the field this reads simply is not there.
        monkeypatch.setattr(scanner, "_sp_get", _routed({"items/i1/listItem": {}}))
        assert scanner._sp_content_type("tok", "base", "i1") is None

    def test_never_raises_on_a_permission_refusal(self, monkeypatch):
        monkeypatch.setattr(scanner, "_sp_get", _routed({"items/i1/listItem": PermissionError("403")}))
        assert scanner._sp_content_type("tok", "base", "i1") is None

    def test_never_raises_on_a_network_or_http_error(self, monkeypatch):
        monkeypatch.setattr(scanner, "_sp_get", _routed({"items/i1/listItem": RuntimeError("HTTP 500")}))
        assert scanner._sp_content_type("tok", "base", "i1") is None

    def test_never_raises_on_a_malformed_response_shape(self, monkeypatch):
        # `fields` present but not a dict — a Graph response nothing here anticipated.
        monkeypatch.setattr(scanner, "_sp_get", _routed({"items/i1/listItem": {"fields": "not-a-dict"}}))
        assert scanner._sp_content_type("tok", "base", "i1") is None


class TestSpEnrichContentTypes:
    def test_enriches_every_scannable_row_when_the_tenant_supports_it(self, monkeypatch):
        calls = []
        def fake(token, base, item_id):
            calls.append(item_id)
            return f"Type-{item_id}"
        monkeypatch.setattr(scanner, "_sp_content_type", fake)
        files = [{"id": "1", "name": "a.docx"}, {"id": "2", "name": "b.docx", "driveId": "d1"}]
        scanner._sp_enrich_content_types("tok", files)
        assert files[0]["content_type"] == "Type-1"
        assert files[1]["content_type"] == "Type-2"
        assert calls == ["1", "2"]

    def test_disables_itself_after_three_consecutive_failures(self, monkeypatch):
        # A tenant that does not support this at all — every attempt fails the same way. Burning
        # one call per remaining file for a guaranteed failure is pure waste; the circuit breaker
        # is what keeps a large estate from paying for that.
        calls = []
        def always_none(token, base, item_id):
            calls.append(item_id)
            return None
        monkeypatch.setattr(scanner, "_sp_content_type", always_none)
        files = [{"id": str(i), "name": f"{i}.docx"} for i in range(10)]
        scanner._sp_enrich_content_types("tok", files)
        assert len(calls) == 3, "did not stop after the third consecutive failure"
        assert all("content_type" not in f for f in files)

    def test_a_recovery_resets_the_failure_count(self, monkeypatch):
        # One bad item (a corrupt listItem, say) must not spend down toward the circuit breaker
        # for every file that follows it.
        seq = iter([None, None, "Contract", None, None, None])
        monkeypatch.setattr(scanner, "_sp_content_type", lambda t, b, i: next(seq))
        files = [{"id": str(i), "name": f"{i}.docx"} for i in range(6)]
        scanner._sp_enrich_content_types("tok", files)
        # The 3rd item recovered, so the breaker should not have tripped until 3 MORE consecutive
        # failures after it — items 4, 5, 6 (indices 3,4,5) are exactly that.
        assert files[2]["content_type"] == "Contract"
        assert "content_type" not in files[5]

    def test_can_be_switched_off_without_a_code_change(self, monkeypatch):
        called = []
        monkeypatch.setattr(scanner, "_sp_content_type", lambda t, b, i: called.append(i) or "X")
        monkeypatch.setenv("ACP_SP_CONTENT_TYPE", "0")
        files = [{"id": "1", "name": "a.docx"}]
        scanner._sp_enrich_content_types("tok", files)
        assert called == []
        assert "content_type" not in files[0]

    def test_skips_a_row_with_no_item_id_rather_than_crashing(self, monkeypatch):
        called = []
        monkeypatch.setattr(scanner, "_sp_content_type", lambda t, b, i: called.append(i) or "X")
        files = [{"name": "no-id.docx"}]
        scanner._sp_enrich_content_types("tok", files)
        assert called == []


class TestSpListWiresItThrough:
    def test_a_whole_onedrive_listing_carries_content_type_on_the_final_set(self, monkeypatch):
        monkeypatch.setattr(scanner, "_sp_get", _routed({
            "me/drive/root/children": {"value": [_file("1", "policy.docx")]},
        }))
        monkeypatch.setattr(scanner, "_sp_content_type", lambda t, b, i: "Policy")
        files = scanner._sp_list("tok", max_files=50)
        assert files[0]["content_type"] == "Policy"

    def test_enrichment_runs_after_truncation_not_before(self, monkeypatch):
        # Enrichment must operate on the FINAL (capped) set, or a capped listing pays a Graph call
        # per item for classification on files it is about to drop from the analysis set.
        seen_ids = []
        monkeypatch.setattr(scanner, "_sp_get", _routed({
            "me/drive/root/children": {"value": [
                _file("1", "a.docx"), _file("2", "b.docx"), _file("3", "c.docx")]},
        }))
        def fake(token, base, item_id):
            seen_ids.append(item_id)
            return "X"
        monkeypatch.setattr(scanner, "_sp_content_type", fake)
        files = scanner._sp_list("tok", max_files=2)
        assert len(files) == 2
        assert sorted(seen_ids) == ["1", "2"], "enrichment ran on files the cap had already dropped"
