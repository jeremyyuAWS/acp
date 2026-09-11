"""Recheck the SAVED artifact (PRD §6): write the candidate to a dedicated local output
directory, reopen it from disk, and rerun the same extraction used to find the finding
in the first place — never trust the applier's own report of what it wrote.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from experiments.document_wide_ai.packaging.docx_packager import PackagedDocx, package_docx
from experiments.document_wide_ai.packaging.pdf_packager import PackagedPdf, package_pdf


@dataclass(frozen=True)
class RecheckResult:
    reopened_ok: bool
    still_failing_locators: frozenset[str]
    new_failure_locators: frozenset[str]
    text_preserved: bool
    unexpected_changes: tuple[str, ...]
    error: str | None = None


def _write_candidate(output_dir: Path, filename: str, data: bytes) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_bytes(data)
    return path


def recheck_pdf(
    output_dir: Path,
    candidate_bytes: bytes,
    baseline: PackagedPdf,
    authorized_locators: frozenset[str],
    *,
    max_text_chars: int,
) -> RecheckResult:
    try:
        path = _write_candidate(output_dir, f"candidate-{uuid.uuid4().hex}.pdf", candidate_bytes)
        reopened_bytes = path.read_bytes()
        reopened = package_pdf(reopened_bytes, max_text_chars=max_text_chars)
    except Exception as exc:
        return RecheckResult(False, frozenset(), frozenset(), False, (), error=str(exc))

    if any(issue.kind in {"extraction_failed", "extraction_truncated"}
           for issue in (*reopened.extraction_issues, *baseline.extraction_issues)):
        return RecheckResult(False, authorized_locators, frozenset(), False, (),
                             error="PDF extraction incomplete; verification unavailable")
    baseline_by_loc = {f.locator: f.current_tu for f in baseline.form_fields}
    reopened_by_loc = {f.locator: f.current_tu for f in reopened.form_fields}
    baseline_by_loc.update({f.locator: f.current_alt for f in getattr(baseline, "figures", ())})
    reopened_by_loc.update({f.locator: f.current_alt for f in getattr(reopened, "figures", ())})
    baseline_missing = {loc for loc, value in baseline_by_loc.items() if not value}
    reopened_missing = {loc for loc, value in reopened_by_loc.items() if not value}
    disappeared = set(baseline_by_loc) - set(reopened_by_loc)
    still_failing = (authorized_locators & reopened_missing) | (authorized_locators - set(reopened_by_loc))
    new_failures = (reopened_missing - baseline_missing) | disappeared
    unexpected = tuple(sorted(
        disappeared | (set(reopened_by_loc) - set(baseline_by_loc)) |
        {loc for loc, value in reopened_by_loc.items()
         if loc not in authorized_locators and loc in baseline_by_loc and value != baseline_by_loc[loc]}
    ))

    return RecheckResult(
        reopened_ok=True,
        still_failing_locators=frozenset(still_failing),
        new_failure_locators=frozenset(new_failures),
        text_preserved=reopened.text_context == baseline.text_context,
        unexpected_changes=unexpected,
    )


def recheck_docx(
    output_dir: Path,
    candidate_bytes: bytes,
    baseline: PackagedDocx,
    authorized_locators: frozenset[str],
    *,
    max_text_chars: int,
) -> RecheckResult:
    try:
        path = _write_candidate(output_dir, f"candidate-{uuid.uuid4().hex}.docx", candidate_bytes)
        reopened_bytes = path.read_bytes()
        reopened = package_docx(reopened_bytes, max_text_chars=max_text_chars)
    except Exception as exc:
        return RecheckResult(False, frozenset(), frozenset(), False, (), error=str(exc))

    baseline_missing = {img.locator for img in baseline.undescribed_images}
    reopened_missing = {img.locator for img in reopened.undescribed_images}

    still_failing = authorized_locators & reopened_missing
    new_failures = reopened_missing - baseline_missing
    # An "unexpected change" for docx alt text would be an authorized-target-adjacent image
    # losing its (already-good) alt text; images outside the authorized set that were never
    # undescribed and remain absent from both sets are, by construction, unaffected.
    unexpected = tuple(sorted(new_failures - authorized_locators))

    return RecheckResult(
        reopened_ok=True,
        still_failing_locators=frozenset(still_failing),
        new_failure_locators=frozenset(new_failures),
        text_preserved=reopened.text_context == baseline.text_context,
        unexpected_changes=unexpected,
    )
