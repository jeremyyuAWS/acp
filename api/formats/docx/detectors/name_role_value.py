"""4.1.2 Name, Role, Value — DOCX.

Scope, stated plainly because the registry's `coverage=PARTIAL` depends on it: this reads
interactive CONTENT CONTROLS (`w:sdt` whose properties carry a checkbox, date, dropDownList,
comboBox or picture gallery) and nothing else. For each one it establishes the criterion's Name
half from a single attribute —

    Name -> w:alias   (the control's Title, which Word exposes to assistive technology)

— and says nothing about the other population 4.1.2 covers in a Word document: ActiveX controls,
embedded OLE objects, and anything else a form can hold. Establishing a name and role for those
means reading a control's own implementation, which nothing in this codebase does and which a
static read cannot do in general.

That is why the registration requires only `Capability.FORMS`, and why a clean result is REVIEW
rather than PASS: we genuinely checked every content control, and genuinely did not check
anything else. It is the same shape as `formats/pdf/detectors/name_role_value.py`, whose
AcroForm-only walk is sound over a strict subset and silent outside it.

WHY w:alias AND NOT w:tag. A content control has both. `w:alias` is the Title — what Word shows
in its UI and what reaches the accessibility tree. `w:tag` is a developer-facing identifier for
data binding and is never announced. A check keyed on `w:tag` shipped in 062642f and was wrong
in both directions: it failed documents whose fields announce perfectly, and passed documents
whose fields are anonymous to AT. Corrected in #144; this module inherits the corrected rule.

WHY THE SAME ATTRIBUTE ALSO ANSWERS 3.3.2. A missing Title fails both criteria at once — a
sighted user gets no prompt, a screen-reader user gets no announced name — which is why
`office_structure.docx_checks` emits 3.3.2 from the same condition and delegates the 4.1.2 half
here rather than keeping a second copy of the predicate.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

# Imported from office_structure rather than re-declared, so this detector and the 3.3.2 check
# beside it can never disagree about what counts as an interactive content control. If these
# move, the import fails loudly instead of the two silently drifting apart.
from office_structure import _SDT, _SDT_ALIAS, _SDT_INPUT_TYPE, _SDT_PR, _docx_story_xmls, _finding


def detect(path: Path) -> list[dict]:
    """One 4.1.2 finding per interactive content control with no Title (w:alias).

    Reads content controls from word/document.xml AND the running header/footer and foot/endnote
    parts (via _docx_story_xmls) — an unnamed date or checkbox field in a running header is as
    anonymous to assistive technology as one in the body, and the 3.3.2 check in
    office_structure.docx_checks that delegates here reads the same parts, so the two never disagree
    about which controls exist.

    Self-gating in the same way every structural check here is: a missing part, a bad zip or a
    malformed document yields [] rather than raising. A detector must never fail a scan.
    """
    findings: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for doc in _docx_story_xmls(zf):
                for sdt_inner in _SDT.findall(doc):
                    pr_m = _SDT_PR.search(sdt_inner)
                    if not pr_m or not _SDT_INPUT_TYPE.search(pr_m.group(1)):
                        continue          # not an input gallery type — a TOC or rich-text block
                    alias_m = _SDT_ALIAS.search(pr_m.group(1))
                    if not alias_m or not alias_m.group(1).strip():
                        findings.append(
                            _finding("DOCX_FORM_FIELD_NO_NAME", "4.1.2 Name, Role, Value", "SERIOUS"))
    except (zipfile.BadZipFile, OSError):
        return []
    return findings
