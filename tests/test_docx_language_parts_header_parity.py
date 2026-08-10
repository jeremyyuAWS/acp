"""3.1.2 must judge a header's language the same way it judges the body's.

The 3.1.2 detector feeds `textchecks.detect_language_parts(text, marked)`. Since P5.2, `text`
comes from `pii.extract_text`, which flattens EVERY `word/` part — body, headers, footers,
foot/endnotes. But `office_structure.language_marked_spans` reads `word/document.xml` ALONE. That
asymmetry is a false-positive generator: a foreign passage that the document DID identify with a
`w:lang` mark, sitting in a running header, shows up in `text` as unexplained foreign words while
its mark is invisible to `marked` — so the detector flags a passage that is correctly marked, in
the one place the mark reader does not look.

This pins the symmetry from both sides, because the fix has a direction it must NOT overshoot:

  * A correctly-marked foreign passage in a header must NOT fire (the false positive to kill).
  * An UNMARKED foreign passage in a header must STILL fire (the real defect — the fix must widen
    where marks are read, not suppress the check in headers, which would trade a false positive
    for a silent miss on the worse side of the ledger).

The body controls prove the header behaviour is new coverage, not a change to what the body does.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import pii  # noqa: E402
import textchecks  # noqa: E402
from office_structure import language_marked_spans  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Two ~25-word passages, well over textchecks._MIN_SEG_WORDS (12), so langdetect is trusted.
EN = ("Please review the accessibility policy for the coming plan year before the enrollment "
      "deadline at the end of March to avoid any interruption in your medical coverage today.")
FR = ("Veuillez consulter attentivement la politique d'accessibilite de notre etablissement avant "
      "le trente et un mars prochain sans faute pour eviter toute interruption de votre couverture.")


def _run(text: str, lang: str | None = None) -> str:
    rpr = f'<w:rPr><w:lang w:val="{lang}"/></w:rPr>' if lang else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def _doc(*paragraphs: str) -> str:
    body = "".join(f"<w:p>{p}</w:p>" for p in paragraphs)
    return f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'


def _build(path: Path, *, fr_lang: str | None, in_header: bool) -> Path:
    """A docx whose English body always carries the FR passage either in a header or the body,
    marked with `fr_lang` (None = unmarked)."""
    with zipfile.ZipFile(path, "w") as z:
        if in_header:
            z.writestr("word/document.xml", _doc(_run(EN)))
            z.writestr("word/header1.xml", f'<w:hdr xmlns:w="{W}"><w:p>{_run(FR, fr_lang)}</w:p></w:hdr>')
        else:
            z.writestr("word/document.xml", _doc(_run(EN), _run(FR, fr_lang)))
    return path


def _fires_312(path: Path) -> bool:
    text = pii.extract_text(path)
    marked = language_marked_spans(path, ".docx")
    findings = textchecks.detect_language_parts(text, marked)
    return any("3.1.2" in str(f.get("wcag", "")) for f in findings)


def test_marked_french_in_body_does_not_fire(tmp_path):
    """Control: a correctly-marked French passage in the body is fine — as it always has been."""
    p = _build(tmp_path / "body_marked.docx", fr_lang="fr-FR", in_header=False)
    assert not _fires_312(p)


def test_unmarked_french_in_body_fires(tmp_path):
    """Control: an unmarked French passage in the body is a real 3.1.2 defect."""
    p = _build(tmp_path / "body_unmarked.docx", fr_lang=None, in_header=False)
    assert _fires_312(p)


def test_unmarked_french_in_header_still_fires(tmp_path):
    """The real defect the fix must preserve: an unmarked foreign header passage still fails."""
    p = _build(tmp_path / "header_unmarked.docx", fr_lang=None, in_header=True)
    assert _fires_312(p)


def test_marked_french_in_header_does_not_fire(tmp_path):
    """The false positive the fix kills: a header's language mark must be read, so a correctly
    marked foreign header passage does NOT fire."""
    p = _build(tmp_path / "header_marked.docx", fr_lang="fr-FR", in_header=True)
    assert not _fires_312(p)


def test_header_marks_do_not_mask_a_different_unmarked_body_passage(tmp_path):
    """The under-report direction the fix must not open: reading header marks pulls the header's
    marked text into `marked`, but that must not excuse an UNMARKED, textually different foreign
    passage in the body. A header correctly marked fr-FR, and a *different* unmarked French
    sentence in the body — the body passage still fails 3.1.2."""
    other_fr = ("Le service clientele demeure disponible chaque jour ouvrable pour repondre a "
                "toutes vos questions concernant votre dossier medical et vos prestations en cours.")
    with zipfile.ZipFile(tmp_path / "mask.docx", "w") as z:
        z.writestr("word/document.xml", _doc(_run(EN), _run(other_fr)))  # body: unmarked French
        z.writestr("word/header1.xml",
                   f'<w:hdr xmlns:w="{W}"><w:p>{_run(FR, "fr-FR")}</w:p></w:hdr>')  # header: marked
    assert _fires_312(tmp_path / "mask.docx")
