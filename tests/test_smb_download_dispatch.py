r"""SMB file fetch routes through the SMB transport, not the local-filesystem read (ADR 0032/0036).

An SMB item carries a UNC `path` (\\server\share\...), which is NOT a local path — scanner._download's
plain-`path` branch would misread it (or read a wrong local file). This pins that an item flagged
`smb` is fetched via smb_source.fetch_smb instead, that the branch is taken BEFORE the local-path
branch, and that with no live transport the fetch fails LOUDLY rather than writing an empty file.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner       # noqa: E402
import smb_source    # noqa: E402

UNC = r"\\fs\dept\a.docx"


def test_an_smb_item_is_fetched_via_the_smb_transport(tmp_path, monkeypatch):
    seen = {}

    def fake_fetch(path, cfg=None):
        seen["path"] = path
        return b"DOCX:" + path.encode()

    monkeypatch.setattr(smb_source, "fetch_smb", fake_fetch)
    scanner._download({"name": "a.docx", "path": UNC, "smb": True}, tmp_path)
    assert seen["path"] == UNC                                   # the UNC was handed to the transport
    assert (tmp_path / "a.docx").read_bytes() == b"DOCX:" + UNC.encode()


def test_the_smb_branch_beats_the_local_path_branch(tmp_path, monkeypatch):
    # The item has BOTH smb=True and a `path`. If the local branch won, it would try to read the UNC
    # as a local file and fail; instead the mocked transport supplies the bytes.
    monkeypatch.setattr(smb_source, "fetch_smb", lambda path, cfg=None: b"from-smb")
    scanner._download({"name": "b.docx", "path": UNC, "smb": True}, tmp_path)
    assert (tmp_path / "b.docx").read_bytes() == b"from-smb"


def test_no_live_transport_fails_loudly_not_an_empty_file(tmp_path):
    # Without the deployment-gated transport, a fetch must raise — never silently write 0 bytes that a
    # scan would treat as an unreadable/empty document.
    with pytest.raises((RuntimeError, NotImplementedError)):
        scanner._download({"name": "c.docx", "path": UNC, "smb": True}, tmp_path)
    assert not (tmp_path / "c.docx").exists()
