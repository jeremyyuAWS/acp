"""api/apply_pptx_image_of_text.py is RETIRED: nothing in production calls it.

#1715 replaced the pptx 1.4.5 lane's writer. The lane used to set the OCR transcript as the
picture's `<p:cNvPr descr="...">`; it now calls apply_pptx_image_replacement, which swaps the
picture for a real text box and deletes the image — the only thing that actually clears 1.4.5,
since ocr._ooxml_images reads ppt/media/* straight out of the zip. The descr writer was left in
the tree, correct and fully unit-tested, with no caller.

WHY THAT NEEDED WRITING DOWN. A complete, tested module with a passing test file reads as live
code to anyone who greps it — which is precisely how ten unmounted frontend components sat on
main being reported as shipped (CLAUDE.md, "Keep retired features in the tree"). The rule there
is both halves: keep the file so the decision is reversible, and assert the orphan so it cannot
be mistaken for live code. This is that assertion for the backend.

WHAT WOULD REVIVE IT, so the next reader does not have to re-derive it:

  Its unique capability is the 'image N' locator — a media-index into ppt/media/*, mirroring
  ocr._ooxml_images. apply_alt.parse_locator cannot read that shape at all (it requires a '#',
  as in 'ppt/slides/slide1.xml#Picture 2'), so this module is the only writer that can aim at an
  image the OCR proposer named.

  It does NOT have a job in 1.1.1 today, and that was checked rather than assumed:
    * 'image N' is emitted in exactly one place (proposals.propose_images_of_text) and enqueued
      under exactly one rule id (handlers, "1.4.5"), so no 1.1.1 row can carry that locator.
    * Every 1.1.1 row uses 'part#name', which apply_alt_text already writes and
      tests/test_remediation_verified_pptx_alt.py already proves end to end.
    * "The OCR transcript as alt text" is already shipped on a better path: ai._transcribed_alt
      feeds the vision alt draft when _looks_like_an_image_of_text says the picture is prose, so
      the transcript reaches the 1.1.1 card with a locator the proven lane can resolve.

  So the revival case is a NEW one: a reviewer who chooses to keep an image of text and describe
  it rather than replace it. That needs a disposition carrying a value, which store._row_is_resolved
  deliberately forbids today (an exception-resolved row promises the document no prose). Design
  that first; this module is then the writer it would use.

When it is called again, this file fails — which is the reminder to delete this file, not a
regression.
"""
from __future__ import annotations

import ast
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
API = ACP / "api"
MODULE = "apply_pptx_image_of_text"
SELF = API / f"{MODULE}.py"


def _production_files() -> list[Path]:
    """Every .py under api/ except the module itself — the code that ships."""
    return [p for p in sorted(API.rglob("*.py")) if p != SELF]


def test_the_module_is_still_here():
    """Retired, not deleted. The owner's standing instruction is that an unused feature stays in
    the tree so bringing it back is one commit."""
    assert SELF.is_file()
    src = ast.parse(SELF.read_text())
    fns = {n.name for n in src.body if isinstance(n, ast.FunctionDef)}
    assert MODULE in fns, f"{MODULE}.py no longer defines {MODULE}()"


def test_no_production_module_imports_or_calls_it():
    """The assertion that keeps a tested orphan from reading as live code.

    Structural, not a substring search: the handler comment explaining the retirement names the
    module, and a whole-file text ban would match its own explanation — the failure mode
    discoverUploadRemoved.test.jsx documents hitting four times in this repo.
    """
    offenders: list[str] = []
    for path in _production_files():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue                      # not this test's business; other guards cover parsing
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name == MODULE for a in node.names):
                    offenders.append(f"{path.relative_to(ACP)}: import {MODULE}")
            elif isinstance(node, ast.ImportFrom):
                if node.module == MODULE:
                    offenders.append(f"{path.relative_to(ACP)}: from {MODULE} import …")
            elif isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name == MODULE:
                    offenders.append(f"{path.relative_to(ACP)}:{node.lineno}: calls {MODULE}()")
    assert not offenders, (
        f"{MODULE} is documented as retired but production code uses it:\n  "
        + "\n  ".join(offenders)
        + f"\n\nIf reviving it is deliberate, delete tests/{Path(__file__).name} and give the "
          "lane a round-trip fixture (tests/test_capability_assisted_contract.py requires one)."
    )


def test_the_live_1_4_5_writer_is_the_replacement_one():
    """The other direction: the lane this module used to serve still has a writer, so this file
    records a RETIREMENT rather than a hole. Without it, dropping the replacement lane would
    leave both writers unused and nothing here would notice.

    Structural for the same reason as the test above — and this one was written as a substring
    check first, which passed against `import apply_pptx_image_replacement as _x` because the
    text it looked for is a prefix of the aliased line. The bite check caught it.
    """
    tree = ast.parse((API / "handlers.py").read_text())
    imported = {
        alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        and node.module == "apply_pptx_image_replacement"
        for alias in node.names
    }
    assert "apply_pptx_image_replacement" in imported, (
        "handlers no longer imports the replacement writer — the 1.4.5 lane lost its writer, so "
        "this file would be recording a hole rather than a retirement")
