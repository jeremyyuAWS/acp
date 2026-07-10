"""Contract: every "auto" entry in remediation_capability.CAPABILITY must correspond
to a DETERMINISTIC remediator action that genuinely runs for that format — derived
independently from the remediator source. This is the guard that stops the capability
table from over-claiming "auto" (the dangerous direction in a compliance tool): a fix
we assert is automatic but no remediator performs.

Mirrors tests/test_rule_formats.py's drift-guard posture (derive ground truth from
source, then diff against the declared table). One-directional by design: it catches
"auto" with no remediator; it does NOT require every remediator action to be marked
"auto" (docx 3.1.1 and pptx 1.4.3 are deliberately "human" — see the module docstring).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import remediation_capability as cap  # noqa: E402
import remediate  # noqa: E402  (html fixer registry)

_OFFICE_SRC = (ACP / "api" / "remediate_office.py").read_text()
_PDF_SRC = (ACP / "api" / "remediate_pdf.py").read_text()

_SC_RE = re.compile(r"\b\d+\.\d+\.\d+\b")


def _strip_comments(src: str) -> str:
    """Drop everything from the first '#' on each line, so a WCAG SC mentioned only in a
    comment ("# WCAG 1.3.1") is never mistaken for a remediator action. SCs live in code
    before any '#' (a `_rec(diffs, "1.3.1", …)` call, or a "· 2.4.6" f-string tag), so this
    keeps the real signal and discards prose. (Truncating at '#' can also clip an f-string
    containing a hex colour, but the SC in such calls precedes the '#', so it survives.)"""
    return "\n".join(line.split("#", 1)[0] for line in src.splitlines())


def _func_body(src: str, name: str) -> str:
    """Source of a top-level `def name(...)` up to the next top-level `def`/EOF."""
    m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
    assert m, f"function {name} not found in source"
    nxt = re.search(r"^def ", src[m.end():], re.M)
    return src[m.start(): m.end() + nxt.start()] if nxt else src[m.start():]


def _scs_in(text: str) -> set[str]:
    return set(_SC_RE.findall(_strip_comments(text)))


def _derive_auto() -> dict[str, set[str]]:
    """The set of SCs each format has a genuine deterministic remediator for, derived
    from source. A superset of what should be marked "auto" (it also includes SCs the
    table intentionally leaves "human"/"assisted"); the contract only asserts every
    "auto" is contained here."""
    # HTML: the fixer registry is authoritative (import it, read the "auto" modes).
    html = {sc for sc, (mode, _fn) in remediate.FIXERS.items() if mode == "auto"}

    # Office: language + title are core-property fixes applied for every Office format
    # (remediate_office._ensure in the remediate_office orchestrator); the rest are
    # format-gated structural remediators.
    office_core = _scs_in(_func_body(_OFFICE_SRC, "remediate_office"))  # -> {3.1.1, 2.4.2}
    docx = office_core | _scs_in(_func_body(_OFFICE_SRC, "_remediate_docx_structure"))
    pptx = office_core | _scs_in(_func_body(_OFFICE_SRC, "_remediate_pptx_slides"))
    xlsx = (office_core
            | _scs_in(_func_body(_OFFICE_SRC, "_remediate_xlsx_contrast"))
            | _scs_in(_func_body(_OFFICE_SRC, "_remediate_xlsx_structure")))

    # PDF: language + display/doc title are the deterministic fixes.
    pdf = _scs_in(_func_body(_PDF_SRC, "remediate_pdf"))

    return {"html": html, "docx": docx, "pptx": pptx, "xlsx": xlsx, "pdf": pdf}


def test_every_auto_entry_has_a_deterministic_remediator():
    derived = _derive_auto()
    overclaims = []
    for fmt, scs in cap.CAPABILITY.items():
        have = derived.get(fmt, set())
        for sc, mode in scs.items():
            if mode == "auto" and sc not in have:
                overclaims.append(f"{fmt} {sc}: marked 'auto' but no deterministic remediator")
    assert not overclaims, "capability over-claims 'auto':\n" + "\n".join(overclaims)


def test_office_core_covers_language_and_title():
    """Sanity-anchor the derivation: the Office core-property fixes really are 3.1.1 + 2.4.2,
    so a regression that stopped detecting them would surface here, not as a silent pass."""
    core = _scs_in(_func_body(_OFFICE_SRC, "remediate_office"))
    assert {"3.1.1", "2.4.2"} <= core


def test_known_conservative_calls_stay_human():
    """The two deliberate under-claims must not drift back to 'auto'."""
    assert cap.mode_for("docx", "3.1.1") == "human"   # engine-blocked on docx
    assert cap.mode_for("pptx", "1.4.3") == "human"   # detect-only on pptx
    assert cap.mode_for("pdf", "1.4.3") == "human"    # no pdf contrast remediator


def test_the_original_bug_docx_is_auto_fixable():
    """The bug this whole change fixes: a docx has real auto-fixable criteria, so Assess
    must never read '0 auto-fixable' for one. Format-awareness means docx's auto set differs
    from a format-blind view."""
    assert cap.auto_scs("docx") == {"2.4.2", "1.3.1", "2.4.6", "1.4.3"}
    assert "1.4.3" in cap.auto_scs("docx")   # contrast — was omitted by the old hand map


def test_mode_for_defaults_to_human():
    assert cap.mode_for("docx", "9.9.9") == "human"
    assert cap.mode_for("unknown-format", "1.1.1") == "human"
    assert cap.mode_for(None, None) == "human"


def test_alt_text_is_assisted_not_auto_everywhere():
    """1.1.1 never silently auto-applies — it is AI-proposes-human-approves on every format
    that handles images."""
    for fmt in ("html", "docx", "pptx", "xlsx", "pdf"):
        assert cap.mode_for(fmt, "1.1.1") == "assisted", fmt
