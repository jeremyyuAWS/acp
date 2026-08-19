"""SMB estate samples carry size + recency so the drill-down lenses work (ADR 0032).

The estate drill-down sorts and filters its sample rows by size (biggest-first) and modified date
(recency) — read by estate_inventory._sample_meta off each file. SMB gets both free from the
directory listing, so a SMB sample must carry them the way Drive/SharePoint do. owner and shared are
NOT cheap on SMB (they need per-file Windows ACL reads), so they are honestly absent rather than a
wrong value.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import smb_source  # noqa: E402


def _entry(name, size, modified, path=r"\\fs\dept"):
    return {"name": name, "is_dir": False, "size": size, "modified": modified, "path": path}


def _samples(scope):
    return {s["name"]: s for status in scope["inventory"]["samples"].values() for s in status}


def test_smb_samples_carry_size_and_recency(monkeypatch):
    monkeypatch.setattr(smb_source, "_walk", lambda root, cfg: [
        _entry("Policy.docx", 2048, "2026-08-01T00:00:00"),
        _entry("scan.png", 500000, "2026-07-01T00:00:00"),
    ])
    scope: dict = {}
    smb_source.list_smb(r"\\fs\dept", max_files=10, scope_out=scope)
    s = _samples(scope)
    assert s["Policy.docx"]["size"] == 2048 and s["Policy.docx"]["modified"] == "2026-08-01T00:00:00"
    assert s["scan.png"]["size"] == 500000 and s["scan.png"]["modified"] == "2026-07-01T00:00:00"


def test_owner_and_shared_are_honestly_absent_for_smb(monkeypatch):
    # SMB has no cheap owner/ACL, so these are None/False — never a fabricated value.
    monkeypatch.setattr(smb_source, "_walk",
                        lambda root, cfg: [_entry("a.docx", 10, "2026-08-01T00:00:00")])
    scope: dict = {}
    smb_source.list_smb(r"\\fs\dept", max_files=10, scope_out=scope)
    row = _samples(scope)["a.docx"]
    assert row["owner"] is None and row["shared"] is False


def test_missing_size_or_modified_is_none_not_an_error(monkeypatch):
    # A listing that omits size/mtime (a stub, a permission quirk) must not break the sample.
    monkeypatch.setattr(smb_source, "_walk",
                        lambda root, cfg: [{"name": "x.docx", "is_dir": False, "path": r"\\fs\dept"}])
    scope: dict = {}
    smb_source.list_smb(r"\\fs\dept", max_files=10, scope_out=scope)
    row = _samples(scope)["x.docx"]
    assert row["size"] is None and row["modified"] is None
