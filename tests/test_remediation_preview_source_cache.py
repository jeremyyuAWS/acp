from types import SimpleNamespace


def test_preview_prefers_the_owner_scoped_assessed_source_cache(monkeypatch):
    import scanner
    from routes import scans

    monkeypatch.setattr(
        scans.core.store,
        "get_scan",
        lambda scan_id, owner=None: {"run": {"source": "local"}},
    )
    seen = {}

    def cached(scan_id, filename, owner):
        seen.update(scan_id=scan_id, filename=filename, owner=owner)
        return b"assessed workbook bytes"

    monkeypatch.setattr(scanner, "read_cached_source", cached)

    result = scans._source_bytes_for_render(
        SimpleNamespace(), "scan-1", "book.xlsx", "person@example.com"
    )

    assert result == b"assessed workbook bytes"
    assert seen == {
        "scan_id": "scan-1",
        "filename": "book.xlsx",
        "owner": "person@example.com",
    }
