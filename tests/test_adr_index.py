"""The ADR index is derived and checked, not maintained by hand.

It was maintained by hand and it drifted: on 2026-09-06, 16 of the 55 ADRs on disk had no entry
in docs/adr/README.md at all — including 0051 and 0052, merged the day before, and 0029, which
three source comments were citing as a precedent while the index did not list it. Twelve of the
sixteen were not mentioned anywhere in the file, so grepping the index for them returned nothing
and read exactly like "no such ADR".

That is the failure worth guarding: a missing index entry does not look like an omission, it looks
like an answer. Someone asking "did we already decide this?" gets told no.

Two facts are asserted, in the two directions that matter:

  * every ADR file is reachable from the index — so a new ADR cannot land unlisted;
  * every ADR-to-ADR link resolves — so a renamed file cannot leave a dangling reference.

The second is not hypothetical either. `0045` pointed at `0029-vendored-pdf-engine.md` and two
ADRs pointed at `0006-pii-sensitive-data.md`; neither filename has ever existed. Markdown does not
complain about a link to nothing, so all three read as live cross-references.

This mirrors `frontend/src/unmountedComponents.test.jsx`, which the repo added for the same reason
after the hand-maintained list of unmounted components drifted from 12 to 17.
"""
from __future__ import annotations

import re
from pathlib import Path

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"
README = ADR_DIR / "README.md"

# A markdown link whose target is a sibling .md file: `](0029-vendor-the-pdf-analyser.md)`.
# Anchored to a leading digit so prose links out of the directory (../spikes/..., ../../docs)
# are not treated as ADR references.
_LINK = re.compile(r"\]\((\d{4}[A-Za-z0-9._-]*\.md)\)")


def _adr_files() -> set[str]:
    return {p.name for p in ADR_DIR.glob("*.md") if p.name != "README.md"}


def _listed() -> set[str]:
    return set(_LINK.findall(README.read_text(encoding="utf-8")))


def test_every_adr_is_listed_in_the_index():
    missing = sorted(_adr_files() - _listed())
    assert not missing, (
        "ADR files with no entry in docs/adr/README.md: "
        + ", ".join(missing)
        + ". Add one line per ADR in the index, matching the surrounding format. An unlisted ADR "
        "reads as a decision nobody made."
    )


def test_the_index_lists_nothing_that_is_not_there():
    phantom = sorted(_listed() - _adr_files())
    assert not phantom, (
        "docs/adr/README.md links to files that do not exist: " + ", ".join(phantom)
    )


def test_every_adr_to_adr_link_resolves():
    on_disk = _adr_files() | {"README.md"}
    broken: list[str] = []
    for path in sorted(ADR_DIR.glob("*.md")):
        for target in _LINK.findall(path.read_text(encoding="utf-8")):
            if target not in on_disk:
                broken.append(f"{path.name} -> {target}")
    assert not broken, (
        "ADR cross-references pointing at filenames that do not exist: "
        + "; ".join(broken)
        + ". A dangling markdown link renders as an ordinary link, so it is invisible until "
        "somebody clicks it."
    )
