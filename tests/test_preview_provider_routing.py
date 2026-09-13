from types import SimpleNamespace
import pytest


@pytest.mark.parametrize('source', ['sharepoint', 'local', None])
def test_non_drive_preview_never_interprets_provider_file_id_as_google_drive(monkeypatch, source, tmp_path):
    import blob
    import scanner
    from routes import scans
    monkeypatch.setenv('ACP_LOCAL_CORPUS', str(tmp_path))
    monkeypatch.setattr(scanner, 'read_cached_source', lambda *args: None)
    monkeypatch.setattr(scans.core.store, 'get_scan', lambda *args, **kwargs: {'run': {'source': source}})
    monkeypatch.setattr(scans.core.store, 'get_file_drive_id', lambda *args: 'shared-provider-item-id')
    calls = []
    def google(request):
        calls.append('google')
        raise RuntimeError('Google sign-in is unrelated to this provider')
    monkeypatch.setattr(scans.core, 'drive_service', google)
    monkeypatch.setattr(blob, 'download_remediated', lambda *args: b'saved corrected copy')
    assert scans._source_bytes_for_render(SimpleNamespace(), 's', 'a.pdf', 'owner') == b'saved corrected copy'
    assert calls == []


def test_google_drive_preview_still_downloads_original_when_assessed_cache_is_missing(monkeypatch):
    import scanner
    from routes import scans
    monkeypatch.setattr(scanner, 'read_cached_source', lambda *args: None)
    monkeypatch.setattr(scans.core.store, 'get_scan', lambda *args, **kwargs: {'run': {'source': 'drive'}})
    monkeypatch.setattr(scans.core.store, 'get_file_drive_id', lambda *args: 'google-item')
    seen = []
    def get_media(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(execute=lambda: b'original Google bytes')
    monkeypatch.setattr(scans.core, 'drive_service', lambda request: SimpleNamespace(files=lambda: SimpleNamespace(get_media=get_media)))
    assert scans._source_bytes_for_render(SimpleNamespace(), 's', 'a.pdf', 'owner') == b'original Google bytes'
    assert seen == [{'fileId': 'google-item'}]
