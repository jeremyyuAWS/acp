"""Network-drive (SMB) source adapter — discovery scaffolding (ADR 0032).

The live SMB transport is deployment-gated (a VNet worker + Key Vault credential); the discovery
LOGIC is not, and this pins it against a mock share via the single seam `smb_source._walk`. What is
under test: the file-dict shape discovery consumes, the whole-estate three-denominator inventory
(parity with Drive/SharePoint), non-scannable routing, the ACP-Remediated mirror skip, honest
truncation, and that dispatch works through `scanner._list("smb", ...)`. Also that the un-mocked
transport fails LOUDLY rather than silently returning an empty estate.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import smb_source  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _entry(name, *, is_dir=False, size=1024, modified=None, path=r"\\fs\dept"):
    return {"name": name, "is_dir": is_dir, "size": size, "modified": modified, "path": path}


def test_list_builds_the_analysis_set_and_the_three_denominator_estate(monkeypatch):
    monkeypatch.setattr(smb_source, "_walk", lambda root, cfg: [
        _entry("Policy.docx", size=2048, modified="2026-08-01T00:00:00"),
        _entry("scan.png", size=500000),
        _entry("Sub", is_dir=True),                                     # folder → excluded (not content)
        _entry("notes.txt", size=100),
        _entry("old.docx", path=r"\\fs\dept\ACP-Remediated"),           # ACP's own mirror → excluded
    ])
    scope: dict = {}
    inv: list = []
    result = smb_source.list_smb(r"\\fs\dept", max_files=10, scope_out=scope, inventory_out=inv)

    assert [f["name"] for f in result] == ["Policy.docx"]              # only scannable, mirror+folder out
    doc = result[0]
    assert doc["path"] == r"\\fs\dept\Policy.docx" and doc["smb"] is True   # UNC id
    assert doc["size_kb"] == 2 and doc["source_mime"] == DOCX

    est = scope["inventory"]
    assert est["discovered"] == 3                                      # docx + png + txt (folder & mirror out)
    assert est["by_status"] == {"assessable": 1, "metadata_only": 1, "unsupported": 1}
    assert est["truncated"] is False
    assert [f["name"] for f in inv] == ["scan.png", "notes.txt"]       # non-scannable inventoried, not opened


def test_truncation_is_an_honest_floor(monkeypatch):
    monkeypatch.setattr(smb_source, "_walk",
                        lambda root, cfg: [_entry(f"f{n}.docx") for n in range(5)])
    scope: dict = {}
    result = smb_source.list_smb(r"\\fs\dept", max_files=2, scope_out=scope)
    assert len(result) == 2
    assert scope["inventory"]["truncated"] is True                     # more scannable past the cap
    assert scope["inventory"]["discovered"] == 2                       # a floor: only what was listed


def test_dispatch_through_scanner_list(monkeypatch):
    import scanner
    monkeypatch.setattr(smb_source, "_walk", lambda root, cfg: [
        _entry("a.docx", size=2048), _entry("b.png", size=9)])
    scope: dict = {}
    result = scanner._list("smb", folder=r"\\fs\dept", max_files=10, scope_out=scope)
    assert scope["kind"] == "smb" and scope["root"] == r"\\fs\dept" and scope["kept"] == 1
    assert scope["truncated"] is False and scope["inventory"]["discovered"] == 2
    assert [f["name"] for f in result] == ["a.docx"]


def test_config_reads_the_environment(monkeypatch):
    monkeypatch.setenv("ACP_SMB_SHARES", r"\\fs\dept , \\nas\phi")
    monkeypatch.setenv("ACP_SMB_DOMAIN", "HOSP")
    monkeypatch.setenv("ACP_SMB_CREDENTIAL_KV", "smb-svc-acp")
    cfg = smb_source.smb_config()
    assert cfg["shares"] == [r"\\fs\dept", r"\\nas\phi"]               # comma-split, trimmed
    assert cfg["domain"] == "HOSP" and cfg["credential_kv"] == "smb-svc-acp"


def test_live_transport_fails_loudly_not_silently():
    # Without the deployment-gated transport (smbclient absent from the default image), discovery must
    # RAISE, never return an empty estate a customer would read as "nothing to remediate". The live
    # `_walk` imports smbclient first via `_smbclient_or_raise`; absent, that is a loud RuntimeError.
    with pytest.raises((RuntimeError, NotImplementedError)):
        smb_source.list_smb(r"\\fs\dept", scope_out={})


# ── the live walk's ACP-owned logic (recursion + shaping), proven against a fake scandir ────────────
# `_walk` itself is two gated smbclient calls wrapped around `_walk_tree`; the walk LOGIC (recursion,
# parent-path shaping, mtime→ISO, size handling) lives in `_walk_tree` and is provable with no server.

class _FakeStat:
    def __init__(self, size, mtime):
        self.st_size, self.st_mtime = size, mtime


class _FakeEntry:
    """A stand-in for smbclient's SMBDirEntry: `.name`, `.is_dir()`, `.stat()`."""
    def __init__(self, name, *, is_dir=False, size=0, mtime=None):
        self.name, self._is_dir, self._stat = name, is_dir, _FakeStat(size, mtime)

    def is_dir(self):
        return self._is_dir

    def stat(self):
        return self._stat


def _fake_scandir(tree):
    r"""Build a scandir(path) over an in-memory {parent_unc: [entries]} tree — the smbclient.scandir
    contract (yields entries; recursion is the walker's job, keyed on the child UNC)."""
    def scandir(path):
        return list(tree.get(path, []))
    return scandir


def test_walk_tree_recurses_and_shapes_entries_with_parent_paths():
    # Two levels: \\fs\dept has a file and a subfolder; the subfolder has a file. The walker must
    # descend and stamp each entry with its PARENT dir UNC, so _file_dict rebuilds the right file id.
    tree = {
        r"\\fs\dept": [
            _FakeEntry("Policy.docx", size=2048, mtime=1_700_000_000),
            _FakeEntry("Sub", is_dir=True),
        ],
        r"\\fs\dept\Sub": [
            _FakeEntry("Deep.pdf", size=4096, mtime=1_700_000_500),
        ],
    }
    entries = list(smb_source._walk_tree(_fake_scandir(tree), r"\\fs\dept"))
    by_name = {e["name"]: e for e in entries}

    assert by_name["Policy.docx"]["path"] == r"\\fs\dept"           # parent dir UNC (top level)
    assert by_name["Policy.docx"]["size"] == 2048
    assert by_name["Deep.pdf"]["path"] == r"\\fs\dept\Sub"          # parent = the subfolder, recursed
    assert by_name["Sub"]["is_dir"] is True and by_name["Sub"]["size"] is None  # dirs carry no size


def test_walk_tree_output_flows_through_list_smb_end_to_end(monkeypatch):
    # The whole point: the real _walk_tree, wired where the mock _walk normally sits, produces the same
    # analysis set + three-denominator estate the discovery layer already asserts — recursion included.
    tree = {
        r"\\fs\dept": [_FakeEntry("a.docx", size=1024, mtime=1_700_000_000),
                       _FakeEntry("img.png", size=9000),
                       _FakeEntry("Sub", is_dir=True)],
        r"\\fs\dept\Sub": [_FakeEntry("b.xlsx", size=2048)],
    }
    monkeypatch.setattr(smb_source, "_walk",
                        lambda root, cfg: smb_source._walk_tree(_fake_scandir(tree), root))
    scope: dict = {}
    inv: list = []
    result = smb_source.list_smb(r"\\fs\dept", max_files=10, scope_out=scope, inventory_out=inv)

    assert sorted(f["name"] for f in result) == ["a.docx", "b.xlsx"]   # both, subfolder recursed
    assert result[0]["path"].startswith(r"\\fs\dept")
    est = scope["inventory"]
    assert est["discovered"] == 3                                     # a.docx + img.png + b.xlsx
    assert est["by_status"] == {"assessable": 2, "metadata_only": 1}
    assert [f["name"] for f in inv] == ["img.png"]                    # non-scannable inventoried


def test_iso_mtime_converts_epoch_and_passes_through_none():
    assert smb_source._iso_mtime(None) is None
    iso = smb_source._iso_mtime(1_700_000_000)
    assert iso is not None and iso.startswith("2023-11-14T") and iso.endswith("+00:00")
    assert smb_source._iso_mtime("not-a-number") is None             # never fabricates a timestamp


def test_server_of_extracts_host_from_unc():
    assert smb_source._server_of(r"\\fileserver\dept\sub") == "fileserver"
    assert smb_source._server_of(r"\\nas\phi") == "nas"
