"""A folder-based archival rule has to mean the same thing on SharePoint as on Drive.

THE BUG. `disposition._values` derived `parent_folder` from the document's `path`, unconditionally
— and Graph gives a driveItem no path. SharePoint rows therefore arrived with `path` of None and
the real folder sitting in their own `parent_folder` column, and the derivation overwrote it with
None. A folder rule matched correctly on Drive and matched NOTHING on SharePoint, with no error
anywhere: it validated, it saved, and it quietly never fired.

WHY IT SURVIVED, and why it is worth a file of its own. `docs/sharepoint-gaps.md` recorded this as
"the disposition engine has no path/folder match field — small build, expose one". The symptom
(folder rules do not work on SharePoint) was read as its cause (the field does not exist), and the
field has been in `disposition.FIELDS` since the Lifecycle PRD's Phase B1. Anybody working that
row would have added a field that was already there, watched the rule still not fire, and had no
reason to look at `_values`. The wrong diagnosis was doing more harm than the bug.

Folder-based rules are one of the three shapes the UTSW pilot SOW names (folder, date, user), so
this is not a corner.

WHAT MUST HOLD:

  1. The same rule matches the same document from either source.
  2. Drive is BYTE-IDENTICAL to before — the derivation still wins wherever a path exists, so
     nothing about Drive's matching moved to fix SharePoint's.
  3. The Graph prefix is normalised away, so a rule is written against `/Finance/Archive` and not
     against `/drives/b!xxx/root:/Finance/Archive` — an id nobody can type and that differs per
     library for the same logical folder.
  4. A document genuinely in no folder still reports none.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import disposition  # noqa: E402

IN_ARCHIVE = [{"field": "parent_folder", "op": "contains", "value": "Archive"}]
IS_ARCHIVE = [{"field": "parent_folder", "op": "eq", "value": "/Finance/Archive"}]

#: A Drive row: the path is the authority and the folder is derived from it.
DRIVE = {"path": "/Finance/Archive/contract.docx", "parent_folder": "/Finance/Archive"}
#: A SharePoint row as the scanner records it — no path, and `parentReference.path` verbatim.
SHAREPOINT = {"path": None, "parent_folder": "/drives/b!abc123/root:/Finance/Archive"}


# ── 1. the same rule, the same answer, either source ─────────────────────────────────────────

def test_a_folder_rule_matches_a_sharepoint_document():
    assert disposition.matches(SHAREPOINT, IN_ARCHIVE), (
        "a folder-based archival rule matched nothing on SharePoint — one of the three rule "
        "shapes the pilot SOW names")


def test_the_same_rule_matches_the_same_document_from_either_source():
    assert (disposition.matches(DRIVE, IN_ARCHIVE)
            is disposition.matches(SHAREPOINT, IN_ARCHIVE) is True)
    assert (disposition.matches(DRIVE, IS_ARCHIVE)
            is disposition.matches(SHAREPOINT, IS_ARCHIVE) is True)


def test_a_folder_rule_that_should_NOT_match_still_does_not():
    """The fix must not turn the field into something that matches everything — a rule that always
    fires is a worse failure than one that never does, because it archives."""
    other = {"path": None, "parent_folder": "/drives/b!abc123/root:/Finance/Active"}
    assert disposition.matches(other, IN_ARCHIVE) is False
    assert disposition.matches(other, IS_ARCHIVE) is False


# ── 2. Drive is untouched ────────────────────────────────────────────────────────────────────

def test_drive_still_derives_its_folder_from_the_path():
    """The derivation wins wherever a path exists, so Drive's matching is byte-identical to
    before. Asserted against a row whose stored `parent_folder` DISAGREES with its path: if the
    fallback had been ordered the other way, this is the case that would have moved."""
    conflicting = {"path": "/Finance/Archive/contract.docx", "parent_folder": "/somewhere/else"}
    assert disposition._values(conflicting)["parent_folder"] == "/Finance/Archive"


def test_a_drive_row_with_no_stored_folder_is_unaffected():
    assert disposition._values({"path": "/a/b/c.docx"})["parent_folder"] == "/a/b"


# ── 3. the Graph prefix is normalised away ───────────────────────────────────────────────────

def test_the_rule_is_written_against_the_folder_not_the_drive_id():
    """`/drives/b!abc123/root:/Finance/Archive` is not a folder anybody can type, and the drive id
    differs per library for the same logical folder name — so a rule keyed on the raw value would
    have to be rewritten for every library it applies to."""
    assert disposition._values(SHAREPOINT)["parent_folder"] == "/Finance/Archive"


def test_the_personal_onedrive_spelling_normalises_too():
    """A OneDrive walk records `/drive/root:/…` (singular, no id) — the other shape Graph emits."""
    one = {"path": None, "parent_folder": "/drive/root:/Reports/2024"}
    assert disposition._values(one)["parent_folder"] == "/Reports/2024"


def test_an_already_normal_folder_is_returned_unchanged():
    """A value with no `root:` marker is already Drive-shaped. The normaliser must be a no-op on
    it rather than eating the first path segment."""
    assert disposition._recorded_folder("/Finance/Archive") == "/Finance/Archive"


# ── 4. no folder is still no folder ──────────────────────────────────────────────────────────

def test_a_library_root_document_reports_no_folder():
    """`/drives/d1/root:` with nothing after it is the library root. Reporting `""` would make an
    `eq ""` rule fire on every root-level document in the estate."""
    assert disposition._values({"path": None,
                                "parent_folder": "/drives/d1/root:"})["parent_folder"] is None


def test_a_row_with_neither_reports_none():
    assert disposition._values({"path": None, "parent_folder": None})["parent_folder"] is None
    assert disposition._values({})["parent_folder"] is None


# ── the field was always declared, which is what made the wrong diagnosis stick ──────────────

def test_parent_folder_has_been_a_declared_rule_field_all_along():
    """Pinned because the gap was recorded as "expose a path/folder rule field" and the field was
    already exposed. Somebody acting on that note would have added it a second time, seen the rule
    still not fire, and had no reason to look at the derivation that was blanking it."""
    assert {"path", "parent_folder"} <= disposition.FIELDS


def test_a_bare_filename_still_has_an_EMPTY_directory_not_a_missing_one():
    """`test_disposition_conditions.test_parent_folder_no_dir` documents this and the first
    version of the fix broke it. `posixpath.dirname("report.docx")` is `""`, and written as
    `derived or recorded` the `or` read that empty string as absent and fell through to the
    fallback — turning a documented `""` into `None` for every Drive file at a drive root. The
    fallback is keyed on whether there IS a path, not on whether the derivation produced
    anything."""
    assert disposition._values({"path": "report.docx"})["parent_folder"] == ""
    assert disposition.matches({"path": "report.docx"},
                               [{"field": "parent_folder", "op": "eq", "value": ""}])


def test_a_pathless_row_does_not_borrow_the_empty_string():
    """The other side of the same boundary: no path at all is not "a path with no directory", and
    a SharePoint row must reach its recorded folder rather than matching `eq ""`."""
    assert disposition._values({"path": None, "parent_folder": None})["parent_folder"] is None
    assert disposition._values(SHAREPOINT)["parent_folder"] == "/Finance/Archive"
