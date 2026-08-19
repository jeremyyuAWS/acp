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
    # Without the deployment-gated transport, discovery must RAISE, never return an empty estate that
    # a customer would read as "nothing to remediate". _walk raises RuntimeError (no smbclient) or
    # NotImplementedError (installed but the live walk is Phase-1 gated) — either is loud.
    with pytest.raises((RuntimeError, NotImplementedError)):
        smb_source.list_smb(r"\\fs\dept", scope_out={})
