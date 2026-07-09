"""Discovery must never re-ingest ACP's own output.

The live symptom: a Drive holding ONE document reported "2 total scanned · 1 duplicate ·
1 remediated ✓". The second file was ACP's own remediated copy, re-discovered as a source
document. Folder-name exclusion missed it; a stamp on the artifact does not.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import provenance  # noqa: E402
import scanner  # noqa: E402

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
FOLDER = "application/vnd.google-apps.folder"


# ── fake Drive ──

class _Req:
    def __init__(self, payload):
        self._p = payload

    def execute(self, num_retries=0):
        return self._p


class _Files:
    def __init__(self, drive):
        self.d = drive

    def list(self, **kw):
        self.d.queries.append(kw)
        q = kw.get("q", "")
        if FOLDER in q and q.startswith("name="):
            return _Req({"files": self.d.folder_lookup})     # _find_remediated_folder_id
        if q.startswith("'"):
            fid = q.split("'")[1]
            return _Req({"files": self.d.children.get(fid, [])})
        return _Req({"files": self.d.all_files})             # whole-Drive search


class FakeDrive:
    def __init__(self, all_files=(), children=None, folder_lookup=()):
        self.all_files = list(all_files)
        self.children = children or {}
        self.folder_lookup = list(folder_lookup)
        self.queries = []

    def files(self):
        return _Files(self)


def _source(name="deck.pptx"):
    return {"id": "src1", "name": name, "mimeType": PPTX, "md5Checksum": "aaa"}


def _acp_copy(name="deck.pptx"):
    """ACP's own remediated copy — same name, different id, stamped."""
    return {"id": "acp1", "name": name, "mimeType": PPTX, "md5Checksum": "bbb",
            "properties": provenance.stamp(name)}


@pytest.fixture(autouse=True)
def _stub_core(monkeypatch):
    """_search_folder reads the admin-configured mirror-folder name off core.store."""
    core = types.ModuleType("core")
    core.store = types.SimpleNamespace(get_drive_mirror_folder=lambda: "Remediated")
    monkeypatch.setitem(sys.modules, "core", core)


# ── the stamp itself ──

def test_stamp_and_detect():
    f = {"properties": provenance.stamp("deck.pptx")}
    assert provenance.is_acp_generated(f)
    assert f["properties"][provenance.ACP_SOURCE_KEY] == "deck.pptx"


def test_unstamped_files_are_not_acp_generated():
    assert not provenance.is_acp_generated(_source())
    assert not provenance.is_acp_generated({})
    assert not provenance.is_acp_generated({"properties": {}})
    assert not provenance.is_acp_generated({"properties": {"acpGenerated": "false"}})
    assert not provenance.is_acp_generated(None)


def test_fields_mask_requests_properties():
    # Without `properties` in the fields mask Drive omits it and every file silently
    # looks unstamped — the exclusion would pass its unit tests and fail in production.
    assert "properties" in provenance.DRIVE_FIELDS


# ── whole-Drive search: the live failure ──

def test_whole_drive_skips_acp_output_even_when_no_remediated_folder_exists():
    svc = FakeDrive(all_files=[_source(), _acp_copy()], folder_lookup=[])  # lookup finds nothing
    out = scanner._search_drive(svc, max_files=50, exclude_remediated=True)
    assert [f["name"] for f in out] == ["deck.pptx"]
    # _dedupe_names never fires, so no phantom "deck (1).pptx" duplicate
    assert not any("(1)" in f["name"] for f in out)


def test_whole_drive_asks_drive_for_properties():
    svc = FakeDrive(all_files=[_source()], folder_lookup=[])
    scanner._search_drive(svc, max_files=50, exclude_remediated=True)
    listing = [q for q in svc.queries if "nextPageToken" in q.get("fields", "")]
    assert listing and all("properties" in q["fields"] for q in listing)


def test_whole_drive_keeps_everything_when_exclusion_is_off():
    # exclude_remediated=False must not silently drop files.
    svc = FakeDrive(all_files=[_source(), _acp_copy()], folder_lookup=[])
    out = scanner._search_drive(svc, max_files=50, exclude_remediated=False)
    assert len(out) == 2


# ── folder walk ──

def test_folder_walk_skips_acp_copy_sitting_beside_its_source():
    # The copy is in the SAME folder as the original, so folder-name exclusion cannot help.
    svc = FakeDrive(children={"root": [_source(), _acp_copy()]})
    out = scanner._search_folder(svc, "root", max_files=50, exclude_remediated=True)
    assert [f["name"] for f in out] == ["deck.pptx"]


def test_folder_walk_still_skips_the_mirror_folder():
    # Retained: pre-provenance copies carry no stamp and are only caught by folder name.
    legacy = {"id": "old1", "name": "legacy.pptx", "mimeType": PPTX, "md5Checksum": "ccc"}
    svc = FakeDrive(children={
        "root": [_source(), {"id": "remf", "name": "Remediated", "mimeType": FOLDER}],
        "remf": [legacy],
    })
    out = scanner._search_folder(svc, "root", max_files=50, exclude_remediated=True)
    assert [f["name"] for f in out] == ["deck.pptx"]


def test_folder_walk_keeps_acp_copy_when_exclusion_is_off():
    svc = FakeDrive(children={"root": [_source(), _acp_copy()]})
    out = scanner._search_folder(svc, "root", max_files=50, exclude_remediated=False)
    assert len(out) == 2


# ── discovery logging: the audit trail of what a scan ingested, and what it refused ──

def test_whole_drive_logs_what_it_listed_skipped_and_kept(capsys):
    svc = FakeDrive(all_files=[_source(), _acp_copy()], folder_lookup=[])
    scanner._search_drive(svc, max_files=50, exclude_remediated=True)
    line = [ln for ln in capsys.readouterr().out.splitlines() if "discovery (whole-Drive)" in ln]
    assert line, "discovery emitted no audit line"
    assert "2 listed" in line[0]
    assert "1 skipped as ACP-generated output" in line[0]
    assert "1 scannable" in line[0]


def test_whole_drive_logs_zero_skips_when_exclusion_is_off(capsys):
    svc = FakeDrive(all_files=[_source(), _acp_copy()], folder_lookup=[])
    scanner._search_drive(svc, max_files=50, exclude_remediated=False)
    line = [ln for ln in capsys.readouterr().out.splitlines() if "discovery (whole-Drive)" in ln][0]
    assert "0 skipped as ACP-generated output" in line and "2 scannable" in line


def test_folder_walk_logs_folders_walked_and_both_skip_reasons(capsys):
    legacy = {"id": "old1", "name": "legacy.pptx", "mimeType": PPTX, "md5Checksum": "ccc"}
    svc = FakeDrive(children={
        "root": [_source(), _acp_copy(), {"id": "remf", "name": "Remediated", "mimeType": FOLDER}],
        "remf": [legacy],
    })
    scanner._search_folder(svc, "root", max_files=50, exclude_remediated=True)
    line = [ln for ln in capsys.readouterr().out.splitlines() if "discovery (folder subtree)" in ln][0]
    assert "1 folder(s) walked" in line          # the mirror folder was never entered
    assert "2 listed" in line
    assert "1 skipped as ACP-generated output" in line
    assert "1 mirror folder(s) skipped" in line
    assert "1 scannable" in line
