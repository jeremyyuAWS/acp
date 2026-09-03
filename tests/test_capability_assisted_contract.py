"""Contract test: every (pptx, pdf) ASSISTED lane has a provable write-back chain.

Scope: pptx and pdf only — the capability-audit scope. docx/xlsx/html ASSISTED chains
are tracked separately (task #175).

A lane is ASSISTED in name only if clicking "Apply" on its review card does nothing.
The chain breaks most visibly at has_approved_values_to_write: if no getter reads the
rule_id, the apply_approved_values job is never enqueued and bytes never change.

PPTX_PDF_APPLIER_REGISTRY lists every (pptx|pdf, SC) pair whose write-back is provably
wired end-to-end:
  1. Detector emits a reproducible finding.
  2. Proposer emits a card with a stable writable locator.
  3. Approval is stored.
  4. has_approved_values_to_write returns True (a getter reads this rule_id).
  5. apply_approved_values / apply_pdf_approved dispatches a real applier.
  6. The changed copy is uploaded and re-scanned.
  7. The targeted finding clears on re-scan.

Add a pair to this registry only when you can trace all seven steps. Until then,
the lane belongs in HUMAN.
"""
from api.remediation_capability import REMEDIATION, ASSISTED

# (format, SC) pairs whose write-back chain is fully wired end-to-end.
# Verified by tracing: has_approved_values_to_write → getter → applier → re-scan clears.
PPTX_PDF_APPLIER_REGISTRY = frozenset({
    # ── image alt text (1.1.1) ────────────────────────────────────────────────
    # approved_alt_values reads rule_id "1.1.1".
    # pptx: apply_alt_text via _apply_approved_values; pptx in _OFFICE_ALT_MIME.
    # pdf:  apply_pdf_figure_alt via apply_pdf_approved (pdf:fig: locator).
    ("pptx", "1.1.1"),
    ("pdf",  "1.1.1"),
    # ── sensory rewrites (1.3.3) ──────────────────────────────────────────────
    # approved_sensory_values reads rule_id "1.3.3".
    # pptx in _SENSORY_EXTS → apply_text_values writes sensory rewrites.
    # pdf is NOT in _SENSORY_EXTS → downgraded to HUMAN.
    ("pptx", "1.3.3"),
    # ── link text (2.4.4 / 2.4.9) ─────────────────────────────────────────────
    # approved_link_values reads rule_ids "2.4.4" and "2.4.9".
    # pptx in _OFFICE_LINK_EXTS → apply_link_text writes back.
    ("pptx", "2.4.4"),
    ("pptx", "2.4.9"),
    # ── language of parts (3.1.2) ─────────────────────────────────────────────
    # approved_language_values reads rule_id "3.1.2".
    # pptx in _LANGUAGE_EXTS → apply_text_values writes language marks.
    # pdf is NOT in _LANGUAGE_EXTS → downgraded to HUMAN.
    ("pptx", "3.1.2"),
})

SCOPED_FORMATS = frozenset({"pptx", "pdf"})


def test_every_pptx_pdf_assisted_lane_in_applier_registry():
    """Every ASSISTED lane for pptx/pdf must have a registered write-back path.

    Fails on any lane that claims ASSISTED without a provable applier. Adding a new
    ASSISTED lane for pptx or pdf requires first wiring the applier AND then adding
    the (fmt, sc) pair to PPTX_PDF_APPLIER_REGISTRY — not the other way round.
    """
    missing = []
    for fmt in SCOPED_FORMATS:
        for sc, lane in REMEDIATION.get(fmt, {}).items():
            if lane == ASSISTED and (fmt, sc) not in PPTX_PDF_APPLIER_REGISTRY:
                missing.append((fmt, sc))
    assert not missing, (
        "ASSISTED lanes with no registered write-back applier — downgrade to HUMAN "
        "or wire the applier and add to PPTX_PDF_APPLIER_REGISTRY:\n"
        + "\n".join(f"  ({fmt!r}, {sc!r})" for fmt, sc in sorted(missing))
    )


def test_applier_registry_entries_are_assisted():
    """No registry entry should point at a non-ASSISTED lane.

    A (fmt, sc) in PPTX_PDF_APPLIER_REGISTRY that was downgraded to HUMAN is a ghost.
    Remove it from the registry when the lane is downgraded.
    """
    ghosts = [
        (fmt, sc) for fmt, sc in PPTX_PDF_APPLIER_REGISTRY
        if REMEDIATION.get(fmt, {}).get(sc) != ASSISTED
    ]
    assert not ghosts, (
        "Registry entries whose REMEDIATION lane is no longer ASSISTED (remove them):\n"
        + "\n".join(f"  ({fmt!r}, {sc!r})" for fmt, sc in sorted(ghosts))
    )
