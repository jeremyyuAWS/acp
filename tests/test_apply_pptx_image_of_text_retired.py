"""api/apply_pptx_image_of_text is PARTLY retired: its WRITER has no caller, its resolver does.

#1715 replaced the pptx 1.4.5 lane's writer. The lane used to set the OCR transcript as the
picture's `<p:cNvPr descr="...">`; it now calls apply_pptx_image_replacement, which swaps the
picture for a real text box and deletes the image — the only thing that actually clears 1.4.5,
since ocr._ooxml_images reads ppt/media/* straight out of the zip.

WHAT CHANGED, and why this file was narrowed rather than deleted. ADR 0055 (#1733) designed
describe-instead-of-replace: a reviewer who KEEPS an image of text and describes it. Its
description travels the proven 1.1.1 alt lane, and the one thing standing between the two is a
locator shape — so the module's RESOLVER (`resolve_media_locators` / `is_media_index_locator`:
media index -> canonical media path -> the rId a slide references it by) is now live, and its
WRITER is still dead. That is exactly the split the previous version of this file predicted
under "what would revive it", and it is why #1724 kept the file rather than deleting it.

So this now asserts something narrower and more useful than "nothing imports this module":
`_patch_pics` and `apply_pptx_image_of_text` — the descr-writing half — have no caller. They
stay dead because apply_alt_text already writes alt text, resolves both locator shapes, and has
a round-trip fixture behind it. Two writers for one job is how they drift.

WHY THAT STILL NEEDS ASSERTING. A complete, tested function inside a module something DOES
import reads as live code even more readily than one in an orphaned file — a grep for the module
name now finds a real caller, so the reader has no reason to look further (CLAUDE.md, "Keep
retired features in the tree"). The rule is both halves: keep it so the decision is reversible,
and assert the orphan so it cannot be mistaken for live code.

When the writer is called again, this file fails — which is the reminder to delete this file and
give that lane a round-trip fixture, not a regression.
"""
from __future__ import annotations

import ast
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
API = ACP / "api"
MODULE = "apply_pptx_image_of_text"
SELF = API / f"{MODULE}.py"

# The descr-writing half: no caller, and this file is what holds it that way.
RETIRED_NAMES = {"apply_pptx_image_of_text", "_patch_pics"}
# The locator resolver ADR 0055 revived. Live, and asserted to BE live below — a narrowing
# that stops being true the moment nothing uses it.
LIVE_NAMES = {"resolve_media_locators", "expand_media_locator_values", "is_media_index_locator"}


def _production_files() -> list[Path]:
    """Every .py under api/ except the module itself — the code that ships."""
    return [p for p in sorted(API.rglob("*.py")) if p != SELF]


def test_the_retired_writer_is_still_here():
    """Retired, not deleted. The owner's standing instruction is that an unused feature stays in
    the tree so bringing it back is one commit — and this half is one commit from returning."""
    assert SELF.is_file()
    src = ast.parse(SELF.read_text())
    fns = {n.name for n in src.body if isinstance(n, ast.FunctionDef)}
    missing = RETIRED_NAMES - fns
    assert not missing, f"{MODULE}.py no longer defines {sorted(missing)}"


def test_no_production_module_imports_or_calls_the_writer():
    """The assertion that keeps the retired WRITER from reading as live code.

    Names, not the module: the module IS imported now, for its resolver, so a
    module-level ban would fail on the very revival ADR 0055 designed. What must stay
    dead is the descr-writing half — the entry point and the function under it.

    Structural, not a substring search, for the reason this file has always given: the
    module docstring and the handler comment both NAME the writer while explaining that
    it is retired, so a whole-file text ban would match its own explanation. That is the
    failure mode discoverUploadRemoved.test.jsx documents hitting four times in this repo.
    """
    offenders: list[str] = []
    for path in _production_files():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue                      # not this test's business; other guards cover parsing
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == MODULE:
                for alias in node.names:
                    if alias.name in RETIRED_NAMES:
                        offenders.append(
                            f"{path.relative_to(ACP)}:{node.lineno}: imports {alias.name}")
            elif isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in RETIRED_NAMES:
                    offenders.append(f"{path.relative_to(ACP)}:{node.lineno}: calls {name}()")
    assert not offenders, (
        f"the retired descr writer in {MODULE} is documented as having no caller, but "
        f"production code uses it:\n  " + "\n  ".join(offenders)
        + f"\n\nIf reviving it is deliberate, delete tests/{Path(__file__).name} and give the "
          "lane a round-trip fixture (tests/test_capability_assisted_contract.py requires one)."
    )


def test_the_resolver_is_the_half_that_is_live():
    """The other half of the split, asserted so the file stays honest in BOTH directions.

    Without this, deleting the ADR 0055 wiring would leave the whole module orphaned again and
    nothing here would notice — the test above would go on passing, because a module nobody
    imports certainly does not import its writer. The narrowing is only safe while something
    really does use the resolver.
    """
    users: list[str] = []
    for path in _production_files():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == MODULE:
                users.extend(a.name for a in node.names if a.name in LIVE_NAMES)
    assert users, (
        f"nothing in api/ imports {MODULE}'s resolver ({', '.join(sorted(LIVE_NAMES))}) any "
        "more. The module is fully orphaned again, so this file should go back to asserting "
        "that — see #1724 for the version that did.")


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
