"""A delivery retry must prove that the destination contains corrected bytes."""
from types import SimpleNamespace

import pytest

import remediation_delivery as delivery


class Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class DriveFiles:
    def __init__(self, content, existing=False, identifier=True):
        self.content = content
        self.existing = existing
        self.identifier = identifier
        self.reads = []

    def list(self, **kwargs):
        return Request({'files': [{'id': 'item'}] if self.existing else []})

    def create(self, **kwargs):
        return Request({'id': 'item', 'webViewLink': 'https://drive/item'} if self.identifier else {})

    update = create

    def get_media(self, *, fileId):
        self.reads.append(fileId)
        return Request(self.content)


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('content', [b'corrected', b'original'])
def test_drive_retry_reads_back_new_and_existing_files(existing, content):
    files = DriveFiles(content, existing)
    svc = SimpleNamespace(files=lambda: files)
    if content == b'corrected':
        assert delivery.deliver_to_drive(svc, folder_id='folder', filename='a.docx', data=b'corrected') == 'https://drive/item'
    else:
        with pytest.raises(IOError, match='verification'):
            delivery.deliver_to_drive(svc, folder_id='folder', filename='a.docx', data=b'corrected')
    assert files.reads == ['item']


def test_drive_retry_requires_destination_identity():
    files = DriveFiles(b'corrected', identifier=False)
    with pytest.raises(IOError, match='identifier'):
        delivery.deliver_to_drive(SimpleNamespace(files=lambda: files), folder_id='folder', filename='a.docx', data=b'corrected')


@pytest.mark.parametrize('content', [b'corrected', b'original'])
def test_graph_retry_reads_back_destination(monkeypatch, content):
    import scanner
    import httpx
    monkeypatch.setattr(scanner, '_sp_upload', lambda *a, **k: {'id': 'item', 'webUrl': 'https://sharepoint/item'})
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, content=content, request=httpx.Request('GET', url))

    monkeypatch.setattr(httpx, 'get', get)
    if content == b'corrected':
        assert delivery.deliver_to_graph('token', drive_id='drive', folder='folder', filename='a.pptx', data=b'corrected') == 'https://sharepoint/item'
    else:
        with pytest.raises(IOError, match='verification'):
            delivery.deliver_to_graph('token', drive_id='drive', folder='folder', filename='a.pptx', data=b'corrected')
    assert len(calls) == 1 and calls[0].endswith('/items/item/content')


def test_graph_retry_requires_destination_identity(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_sp_upload', lambda *a, **k: {'webUrl': 'https://sharepoint/item'})
    with pytest.raises(IOError, match='identifier'):
        delivery.deliver_to_graph('token', drive_id='drive', folder='folder', filename='a.pdf', data=b'corrected')
