"""Read-only import shim onto the small set of `api/` fix-application primitives this
prototype reuses. This module makes ZERO changes to any production file — it only
prepends the repo's `api/` directory to `sys.path` (once, only if the path is not
already present) so that those modules resolve their own bare-name sibling imports
(e.g. `remediate_pdf.py` does `from swallowed import swallowed`) exactly the way they
do when `api/` is the process's working import root.

Only PURE, bytes-in/bytes-out functions with no DB, network, worker, or job coupling
are imported here. Each was confirmed by direct execution against a synthetic fixture
before being added to `application/allowlist.py` — see
`experiments/document_wide_ai/docs/ADAPTER_INVENTORY.md` for the evidence and for the
production functions that were considered and rejected as unsafe to isolate (they reach
`core.store`, a local vision model, or the filesystem via input-derived paths).

If either import below starts failing, that is a signal the production module changed
shape — this shim must not silently degrade, so failures propagate.
"""
from __future__ import annotations

import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[3] / "api"


def _ensure_api_on_path() -> None:
    p = str(_API_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


_ensure_api_on_path()

import apply_alt as _apply_alt  # noqa: E402
import remediate_pdf as _remediate_pdf  # noqa: E402
from formats.office.images import is_junk_descr as office_is_junk_descr  # noqa: E402
from formats.office.images import undescribed_images as office_undescribed_images  # noqa: E402

# PDF — AcroForm accessible name (/TU), WCAG 4.1.2. Locator: "pdf:field:{page}:{seq}".
apply_pdf_field_name = _remediate_pdf.apply_pdf_field_name
collect_pdf_form_fields = _remediate_pdf._collect_form_fields
pdf_form_field_locators = _remediate_pdf._form_field_locators

# DOCX/PPTX/XLSX — image alt text (descr=), WCAG 1.1.1. Locator: "{part}#{docPr name|r:embed}".
apply_office_alt_text = _apply_alt.apply_alt_text
parse_office_alt_locator = _apply_alt.parse_locator
