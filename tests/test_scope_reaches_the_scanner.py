"""The file-type scope gates what is READ, not only what is scored.

THE BUG THIS CLOSES. `scan_scope` gated which CRITERIA were evaluated and never which FILES were
opened. An operator who scoped to `.docx` still caused every PDF in the estate to be downloaded,
rasterised, OCR'd, cached to blob and potentially traced — and then had its findings discarded by
`_scoped_for_scoring`. The UI hid the rows (`visibleForFileTypes`, #196), which is what made it
invisible: the screen agreed with the operator and the server did not.

For a hospital that is the whole issue. "We read every PDF anyway and discarded the findings" is
a data-minimisation answer no security review accepts, and it was the honest description.

THE LOAD-BEARING ASSERTION IS ON THE FETCH, NOT THE LIST. A test that checks the returned file
list would have passed against the OLD behaviour too, because the old list was filtered
downstream anyway. What changed is that `_download` is never called for an out-of-scope file, so
that is what is asserted.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import assessment_policy as pol  # noqa: E402
import scanner  # noqa: E402

DOCX_ONLY = {"1.1.1": frozenset({"docx"}), "1.3.1": frozenset({"docx"})}
DOCX_AND_PDF = {"1.1.1": frozenset({"docx", "pdf"})}


# TWO SCOPES, AND THEY ARE NOT THE SAME THING. The per-scan `scan_scope` these tests are about
# gates which criteria run and therefore which files are read, for one engagement. Outside it
# sits the DEPLOYMENT format scope (api/scan_formats, PDF/DOCX/XLSX/PPTX since 2026-08-31),
# which decides what discovery may enumerate at all. The outer one runs first, so a format it
# excludes never reaches the per-scan predicate — which is why `e.html` stays in the corpus
# below and is asserted ABSENT from every listing: keeping the file is what makes the layering
# visible instead of leaving it to be inferred from a corpus that quietly stopped having one.
_IN_SCOPE = ["a.docx", "b.pdf", "c.pptx", "d.xlsx"]


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """A local estate with one file of every format ACP can enumerate, plus one it cannot."""
    for name in _IN_SCOPE + ["e.html"]:
        (tmp_path / name).write_bytes(b"x")
    monkeypatch.setenv("ACP_LOCAL_CORPUS", str(tmp_path))
    return tmp_path


def _listed(scope, **kw):
    out: dict = {}
    items = scanner._list("local", scope_out=out, scope_files=scope, **kw)
    return sorted(i["name"] for i in items), out


# ── the predicate ─────────────────────────────────────────────────────────────

def test_unset_scope_means_no_restriction_not_no_formats():
    """`None`, never the empty set. Collapsing "unset" into "nothing selected" is how an empty
    scope comes to mean "scan nothing" — the inverse of the operator's intent (#187)."""
    assert pol.formats_in_scope({}) is None
    assert pol.formats_in_scope(None) is not ()          # resolves through active_scope, not []
    assert pol.file_in_scope("anything.pdf", {}) is True


def test_formats_in_scope_unions_across_criteria():
    assert pol.formats_in_scope({"1.1.1": frozenset({"docx"}),
                                 "1.4.3": frozenset({"pdf"})}) == frozenset({"docx", "pdf"})


def test_html_is_exempt_and_that_is_deliberate():
    """`scan_scope`'s format axis is the four DOCUMENT formats — gen_scope_presets._DOC_FORMATS
    excludes html on purpose — so html can never appear in a scope map. A naive intersection
    would therefore stop scanning HTML the moment anyone scoped to .docx, silently, and would
    look like a consistent rule rather than a bug."""
    assert pol.file_in_scope("page.html", DOCX_ONLY) is True
    assert pol.file_in_scope("page.htm", DOCX_ONLY) is True


def test_an_unclassifiable_file_is_kept():
    """Same principle as `in_scope`: honour a deliberate choice, never invent one from a filename
    that could not be parsed. Skipping on a guess silently shrinks the estate."""
    assert pol.file_in_scope("mystery.bin", DOCX_ONLY) is True
    assert pol.file_in_scope("", DOCX_ONLY) is True


# ── enumeration ───────────────────────────────────────────────────────────────

def test_a_docx_scope_drops_the_pdf_from_the_listing(corpus):
    names, _ = _listed(DOCX_ONLY)
    assert "b.pdf" not in names
    assert "a.docx" in names
    # The predicate above still exempts html (test_html_is_exempt_and_that_is_deliberate), but
    # the exemption is no longer REACHABLE through enumeration: the deployment format scope
    # drops html before the per-scan predicate is ever consulted. Asserted rather than deleted,
    # because "html is exempt" is still true of the layer it was written about.
    assert "e.html" not in names


def test_a_docx_scope_still_drops_pptx_and_xlsx(corpus):
    """The scope is a union over criteria, not "office vs pdf" — a .docx-only engagement should
    not read a deck either."""
    names, _ = _listed(DOCX_ONLY)
    assert "c.pptx" not in names and "d.xlsx" not in names


def test_no_scope_scans_every_format(corpus):
    """"Every format" means every format the DEPLOYMENT enumerates — the four. An unrestricted
    per-scan scope removes the inner filter, never the outer one."""
    names, _ = _listed(None)
    assert names == _IN_SCOPE


def test_a_wider_scope_keeps_the_pdf(corpus):
    names, _ = _listed(DOCX_AND_PDF)
    assert "b.pdf" in names and "a.docx" in names


def test_the_skips_are_reported_not_silent(corpus):
    """Narrowing the scope makes the estate smaller. An operator who cannot see why cannot tell a
    scoped scan from a source that lost files — and this is the line that answers "did you look
    at everything?" in an audit."""
    names, out = _listed(DOCX_ONLY)
    assert out["skipped_out_of_scope"] == 3          # pdf + pptx + xlsx
    assert out["kept"] == len(names), "kept must describe the population the caller receives"


def test_nothing_is_reported_skipped_when_nothing_is_scoped_out(corpus):
    _names, out = _listed(None)
    assert out.get("skipped_out_of_scope", 0) == 0


# ── the one that actually matters ─────────────────────────────────────────────

def test_a_docx_scoped_scan_never_downloads_the_pdf(corpus, monkeypatch):
    """THE load-bearing test. Asserted on the FETCH, because a list-only assertion passes against
    the old behaviour too — the old list was filtered downstream anyway. Reading is what was
    happening to a hospital's PDFs, so reading is what must stop.
    """
    fetched: list[str] = []
    monkeypatch.setattr(scanner, "_download",
                        lambda it, tmp, svc, **kw: fetched.append(it["name"]))
    monkeypatch.setattr(scanner, "cache_source_bytes", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "_scope_for_listing", lambda user=None: DOCX_ONLY)

    scanner.run_scan("local", folder=str(corpus), ai_enabled=False, scan_id="s-scope")

    assert "b.pdf" not in fetched, f"an out-of-scope PDF was downloaded: {fetched}"
    assert "c.pptx" not in fetched and "d.xlsx" not in fetched
    assert "a.docx" in fetched
    # Not read either, and for a different reason than the pdf: the pdf is excluded by THIS
    # scan's scope, html by the deployment's format scope. Same observable outcome, two
    # different gates — the data-minimisation guarantee this module exists for holds under both.
    assert "e.html" not in fetched


def test_an_unscoped_scan_downloads_everything(corpus, monkeypatch):
    """The no-restriction case, asserted on the same channel — so the test above is known to be
    measuring the scope rather than a corpus that never had a PDF in it."""
    fetched: list[str] = []
    monkeypatch.setattr(scanner, "_download",
                        lambda it, tmp, svc, **kw: fetched.append(it["name"]))
    monkeypatch.setattr(scanner, "cache_source_bytes", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "_scope_for_listing", lambda user=None: None)

    scanner.run_scan("local", folder=str(corpus), ai_enabled=False, scan_id="s-open")

    assert set(_IN_SCOPE) <= set(fetched)
    assert "e.html" not in fetched, "the deployment format scope still applies with no scan scope"


def test_run_scan_threads_the_signed_in_user_into_the_scope_gate(corpus, monkeypatch):
    """Per-user scope (ADR 0035 stage 2) only works if the scan's `user` reaches the scope
    resolution. run_scan already carries `user`; this pins that it is passed to `_scope_for_listing`,
    which resolves the owner default WIDENED by that user's override and freezes it. Without this
    thread the override would be stored and silently never applied."""
    seen: list = []
    monkeypatch.setattr(scanner, "_download", lambda it, tmp, svc, **kw: None)
    monkeypatch.setattr(scanner, "cache_source_bytes", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "_scope_for_listing", lambda user=None: seen.append(user) or None)

    scanner.run_scan("local", folder=str(corpus), ai_enabled=False, scan_id="s-user",
                     user="reviewer@hospital.org")

    assert seen == ["reviewer@hospital.org"]
