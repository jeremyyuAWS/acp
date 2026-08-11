"""A docx whose body (word/document.xml) is missing or malformed must be surfaced explicitly.

Found by edge-case testing 2026-08-11: such a file opens as a zip and yields its core-properties,
so the office CLI reports it as a nearly-clean `uncertain` (a lone "no document title" finding, no
error) — reading to a reviewer as "almost fine" when the document's entire body was unreadable.
These pin the affirmative check that catches it and the explicit engine error it attaches.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402


def _good_docx() -> bytes:
    d = Document(); d.add_paragraph("A normal, readable document.")
    b = io.BytesIO(); d.save(b); return b.getvalue()


def _rezip(mutate) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(_good_docx()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            data = src.read(n)
            data = mutate(n, data)
            if data is not None:
                z.writestr(n, data)
    return out.getvalue()


def _write(tmp_path, name, data) -> Path:
    p = tmp_path / name; p.write_bytes(data); return p


def test_readable_on_a_good_docx(tmp_path):
    assert scanner._docx_body_readable(_write(tmp_path, "good.docx", _good_docx())) is True


def test_unreadable_when_document_xml_is_malformed(tmp_path):
    bad = _rezip(lambda n, d: b"<?xml version='1.0'?><w:document><w:body><w:p>unclosed"
                 if n == "word/document.xml" else d)
    assert scanner._docx_body_readable(_write(tmp_path, "malformed.docx", bad)) is False


def test_unreadable_when_document_xml_is_missing(tmp_path):
    missing = _rezip(lambda n, d: None if n == "word/document.xml" else d)
    assert scanner._docx_body_readable(_write(tmp_path, "missing.docx", missing)) is False


def test_non_zip_is_deferred_to_engine_error_path(tmp_path):
    # A zero-byte / renamed-text / encrypted file is not a valid zip; that case is already
    # engine-error upstream, so this check reports it readable (True) to avoid a duplicate message.
    assert scanner._docx_body_readable(_write(tmp_path, "empty.docx", b"")) is True
    assert scanner._docx_body_readable(_write(tmp_path, "junk.docx", b"not a zip at all")) is True


def test_flag_appends_explicit_error_only_to_the_broken_file(tmp_path):
    _write(tmp_path, "good.docx", _good_docx())
    _write(tmp_path, "broken.docx", _rezip(lambda n, d: None if n == "word/document.xml" else d))
    res = {"good.docx": {"succeeded": True, "issues": [], "errors": []},
           "broken.docx": {"succeeded": True, "issues": [], "errors": []}}
    scanner._flag_unreadable_docx(tmp_path, res)
    assert res["good.docx"]["errors"] == []                       # untouched
    msgs = [e["message"] for e in res["broken.docx"]["errors"]]
    assert any("could not be read" in m for m in msgs)            # explicit reason, not silence
    assert scanner.UNREADABLE_BODY_MSG in msgs
