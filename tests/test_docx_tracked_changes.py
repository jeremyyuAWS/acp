"""Tracked deletions do not leak into extracted text; tracked insertions do stay.

THE GAP THIS PINS, measured before it was closed. `pii._ooxml_text` extracts a docx's text by
stripping every XML tag from the word/ parts — `re.sub(r"<[^>]+>", " ", xml)`. That is
dependency-free and fine for a normal document, but it does not know what tracked changes are. A
deletion under change-tracking is stored as `<w:del><w:r><w:delText>…</w:delText></w:r></w:del>`:
the text a reader of the accepted document never sees, still sitting in the part. Tag-stripping
turns `<w:delText>` into plain words, so the extractor returned content that is not in the
document — and every consumer of extracted text inherited it:

  * PII detection flags an SSN or phone number that was DELETED — a false positive on data the
    document does not contain, which for a PHI review is the alarming direction.
  * 3.1.2 language-of-parts can fire on a foreign passage that was struck out.
  * reading-level and other text metrics score prose no one reads.

The other half is the mirror image and is NOT a bug here: an insertion is
`<w:ins><w:r><w:t>…</w:t></w:r></w:ins>` — ordinary `<w:t>`, which tag-stripping keeps — so
inserted text (present in the accepted document) is correctly extracted. The regex detectors in
office_structure are also already safe: they read `<w:t>` via `_WT`, which never matches
`<w:delText>`. The leak is isolated to the tag-stripping extractor, and so is the fix.

The stance ACP takes, stated because it is a choice: extract the document as it reads with
tracked changes ACCEPTED — insertions in, deletions out. That is the content a person opening the
file in its intended final state encounters.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import pii  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

DOC = f'''<w:document xmlns:w="{W}"><w:body>
  <w:p><w:r><w:t>Call 555-0100 for the plan year.</w:t></w:r></w:p>
  <w:p><w:ins w:id="1" w:author="ed"><w:r><w:t>Added coverage note stays visible.</w:t></w:r></w:ins></w:p>
  <w:p><w:del w:id="2" w:author="ed"><w:r><w:delText>Removed old line, call 555-9999 instead.</w:delText></w:r></w:del></w:p>
</w:body></w:document>'''


def _docx(tmp_path: Path) -> Path:
    p = tmp_path / "tracked.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", DOC)
    return p


def test_kept_and_inserted_text_is_extracted(tmp_path):
    """Non-vacuity + the insertion half: what a reader of the accepted document sees is present."""
    text = pii.extract_text(_docx(tmp_path))
    assert "555-0100" in text, "the ordinary body text must be extracted"
    assert "Added coverage note" in text, "a tracked INSERTION is part of the accepted document"


def test_deleted_text_does_not_leak(tmp_path):
    """The finding. Struck-out content is not in the document and must not reach any consumer of
    extracted text — here proven both on the raw string and through the PII detector it feeds."""
    text = pii.extract_text(_docx(tmp_path))
    assert "555-9999" not in text, (
        "a tracked DELETION leaked into extracted text — a reader of the accepted document never "
        "sees it, so PII/language/reading-level checks are scoring content that is not there")
    assert "Removed old line" not in text

    # and the consequence that made it worth fixing: no phantom PII from deleted digits
    phones = [f for f in pii.detect_text(text) if f["type"] == "phone"]
    joined = " ".join(s for f in phones for s in f.get("samples", []))
    assert "9999" not in joined, "the deleted phone number was reported as PII present in the file"
