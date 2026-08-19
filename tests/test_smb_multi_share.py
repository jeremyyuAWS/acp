"""SMB discovery walks EVERY in-scope share, not just the first (ADR 0032).

A hospital estate spans several shares (UTSW: up to ~10). Walking only the first would report an
estate smaller than it is. `list_smb_estate` walks all configured roots into one combined analysis
set + one estate summary, with a GLOBAL cap and honest cross-share truncation, and `scanner._list`
uses it for the whole configured estate. `list_smb` (single root) is unchanged for direct callers.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner       # noqa: E402
import smb_source    # noqa: E402

S1 = r"\\a\s1"
S2 = r"\\a\s2"


def _entry(name, path):
    return {"name": name, "is_dir": False, "size": 10, "modified": "2026-08-01T00:00:00", "path": path}


def _fake_walk(monkeypatch, mapping):
    monkeypatch.setattr(smb_source, "_walk", lambda root, cfg: mapping.get(root, []))


def test_single_root_list_smb_is_unchanged(monkeypatch):
    _fake_walk(monkeypatch, {S1: [_entry("one.docx", S1), _entry("img.png", S1)]})
    scope: dict = {}
    result = smb_source.list_smb(S1, max_files=10, scope_out=scope)
    assert [f["name"] for f in result] == ["one.docx"]
    assert scope["inventory"]["discovered"] == 2


def test_estate_combines_every_share(monkeypatch):
    _fake_walk(monkeypatch, {S1: [_entry("one.docx", S1), _entry("img.png", S1)],
                             S2: [_entry("two.docx", S2)]})
    scope: dict = {}
    result = smb_source.list_smb_estate([S1, S2], max_files=10, scope_out=scope)
    assert sorted(f["name"] for f in result) == ["one.docx", "two.docx"]     # both shares scanned
    assert scope["inventory"]["discovered"] == 3                             # 2 docx + 1 png
    assert scope["inventory"]["truncated"] is False


def test_global_cap_truncates_honestly_across_shares(monkeypatch):
    # The cap bounds the whole scan, not each share. Filling it in share 1 leaves share 2 unreached →
    # the estate is a floor.
    _fake_walk(monkeypatch, {S1: [_entry("a.docx", S1), _entry("b.docx", S1)], S2: [_entry("c.docx", S2)]})
    scope: dict = {}
    result = smb_source.list_smb_estate([S1, S2], max_files=1, scope_out=scope)
    assert len(result) == 1 and scope["inventory"]["truncated"] is True


def test_empty_roots_is_an_empty_estate(monkeypatch):
    _fake_walk(monkeypatch, {})
    scope: dict = {}
    assert smb_source.list_smb_estate([], max_files=10, scope_out=scope) == []
    assert scope["inventory"]["discovered"] == 0


def test_scanner_dispatch_walks_all_configured_shares(monkeypatch):
    _fake_walk(monkeypatch, {S1: [_entry("one.docx", S1)], S2: [_entry("two.docx", S2)]})
    monkeypatch.setattr(smb_source, "smb_config",
                        lambda: {"shares": [S1, S2], "domain": None, "username": None,
                                 "password": None, "credential_kv": None})
    scope: dict = {}
    result = scanner._list("smb", folder=None, max_files=10, scope_out=scope)
    assert sorted(f["name"] for f in result) == ["one.docx", "two.docx"]     # not just the first share
    assert scope["kind"] == "smb" and scope["root"] == f"{S1}, {S2}"
