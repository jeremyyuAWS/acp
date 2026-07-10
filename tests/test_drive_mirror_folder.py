"""The Drive mirror folder is admin-configurable — every writer must honour the setting.

`settings.drive_mirror_folder` (default "Remediated") is read by scanner, handlers and
disposition. `routes/drive.py::drive_upload` hardcoded the literal 'Remediated' instead, so an
operator who renamed the mirror got their per-file uploads written into a folder nothing else
reads: the scan skips it as ACP output, the UI never lists it, and the certified copy silently
diverges from the estate.

These tests pin the behaviour of the shared find-or-create, and assert the route calls it.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import core  # noqa: E402
import handlers  # noqa: E402


class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _Files:
    def __init__(self, fake):
        self._fake = fake

    def list(self, q=None, fields=None, orderBy=None, pageSize=None):
        self._fake.calls.append(("list", q, orderBy))
        return _Exec({"files": self._fake.list_result})

    def create(self, body=None, fields=None):
        self._fake.calls.append(("create", (body or {}).get("name"), None))
        return _Exec({"id": "created-id"})


class _FakeSvc:
    def __init__(self, list_result=None):
        self.list_result = list_result or []
        self.calls = []

    def files(self):
        return _Files(self)


class _FakeStore:
    def __init__(self, folder):
        self._folder = folder

    def get_drive_mirror_folder(self):
        return self._folder


# ── the shared find-or-create honours the setting ──

def test_lookup_queries_the_configured_name_not_the_default(monkeypatch):
    monkeypatch.setattr(core, "store", _FakeStore("Accessible Docs"))
    svc = _FakeSvc(list_result=[{"id": "found-id"}])
    assert handlers.ensure_remediated_folder(svc) == "found-id"
    kind, q, _ = svc.calls[0]
    assert kind == "list"
    assert "name='Accessible Docs'" in q
    assert "Remediated" not in q


def test_create_uses_the_configured_name(monkeypatch):
    monkeypatch.setattr(core, "store", _FakeStore("Deva Certified"))
    svc = _FakeSvc(list_result=[])          # nothing found -> create
    assert handlers.ensure_remediated_folder(svc) == "created-id"
    assert ("create", "Deva Certified", None) in svc.calls


def test_default_is_still_remediated(monkeypatch):
    monkeypatch.setattr(core, "store", _FakeStore("Remediated"))
    svc = _FakeSvc(list_result=[])
    handlers.ensure_remediated_folder(svc)
    assert ("create", "Remediated", None) in svc.calls


def test_a_quote_in_the_folder_name_cannot_break_out_of_the_query(monkeypatch):
    # Drive's query language is single-quoted. An unescaped apostrophe would terminate the
    # literal early — "Deva's Docs" becomes name='Deva' + garbage, a 400 at best.
    monkeypatch.setattr(core, "store", _FakeStore("Deva's Docs"))
    svc = _FakeSvc(list_result=[])
    handlers.ensure_remediated_folder(svc)
    q = svc.calls[0][1]
    assert r"name='Deva\'s Docs'" in q


def test_duplicate_folders_resolve_to_the_oldest_deterministically(monkeypatch):
    # Legacy duplicates exist in real Drives (concurrent workers each created one). Picking an
    # arbitrary duplicate scatters output; ordering by createdTime always picks the same folder.
    monkeypatch.setattr(core, "store", _FakeStore("Remediated"))
    svc = _FakeSvc(list_result=[{"id": "oldest"}])
    assert handlers.ensure_remediated_folder(svc) == "oldest"
    assert svc.calls[0][2] == "createdTime"


# ── the upload route uses the seam rather than its own copy ──

DRIVE_ROUTE = (Path(__file__).resolve().parents[1] / "api" / "routes" / "drive.py").read_text()


def _code(src):
    """Strip comments/docstring prose: a comment naming the old bug is not the old bug."""
    return "\n".join(l for l in src.split("\n") if not l.strip().startswith("#"))


def test_drive_upload_delegates_to_ensure_remediated_folder():
    assert "handlers.ensure_remediated_folder(svc)" in _code(DRIVE_ROUTE)


def test_drive_upload_no_longer_hardcodes_the_folder_name():
    code = _code(DRIVE_ROUTE)
    # No string literal 'Remediated' anywhere in executable code.
    assert not re.search(r"""["']Remediated["']""", code)
    # And no second find-or-create: exactly one folder mimeType reference remains, the
    # /drive/folders browser (which lists a caller-supplied parent, not the mirror).
    assert code.count("vnd.google-apps.folder") == 1
