"""HTML format package — capability declarations and (rule × format) registrations."""
from __future__ import annotations

from assessment import Confidence, Coverage
from capabilities import Capability
from rule_registry import register

from formats.html.detectors import language_of_page

# ── 3.1.1 Language of Page ────────────────────────────────────────────────────────────
# The first FULL registration, and deliberately so: it is the counterexample showing the
# coverage scale has a top, not just degrees of incompleteness. A valid `lang` on the root IS
# programmatic determinability — nothing the criterion asks about is left unexamined — so a
# clean scan certifies a PASS, where PDF 4.1.2 (PARTIAL) and PDF 2.4.3 (HEURISTIC) cannot.
#
# Requires METADATA rather than DOM: the check reads one document-level attribute and needs
# nothing about the element tree, so it stays assessable on any HTML we can parse at all.
register(
    rule="3.1.1",
    fmt="html",
    detector=language_of_page.detect,
    requires={Capability.METADATA},
    coverage=Coverage.FULL,
    confidence=Confidence.HIGH,
    reason=("a valid lang attribute on the root element is exactly what 3.1.1 asks for, so this "
            "covers the criterion completely; whether the declared language is the CORRECT one "
            "is a content question 3.1.1 does not ask"),
)
