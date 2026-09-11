# Adapter inventory

Snapshot against `origin/main` at `37f75f69` (2026-09-11). This prototype reuses exactly
two production fix-application primitives, both confirmed by direct execution (see
`tests/test_applier_and_recheck.py`) to be pure, offline, and free of DB/network/worker
coupling. Everything else considered is listed below as **rejected** with the reason.

## Supported (format, operation) pairs

| Operation | Format | SC | Production adapter reused | Locator |
|---|---|---|---|---|
| `set_pdf_field_accessible_name` | PDF | 4.1.2 | `api.remediate_pdf.apply_pdf_field_name` (bytes → bytes) | `pdf:field:{page}:{seq}` |
| `set_office_image_alt_text` | DOCX | 1.1.1 | `api.apply_alt.apply_alt_text` (bytes → bytes) | `{part}#{docPr name \| r:embed id}` |

Both are declared in `application/allowlist.py::SUPPORTED_OPERATIONS` and imported,
never copied, via `application/production_adapters.py`. Read-only helper functions were
also reused for locator-minting and enumeration, so a locator produced by this
prototype's packagers always resolves at application time:

- `api.remediate_pdf._collect_form_fields`, `api.remediate_pdf._form_field_locators`
- `api.formats.office.images.undescribed_images`, `api.formats.office.images.is_junk_descr`

## Why these two, and not others

The full inventory (`api/remediate_pdf.py`, `api/remediate_office.py`, `api/apply_alt.py`,
`api/apply_field_name.py`, `api/apply_link_text.py`) was reviewed for functions that are
genuinely isolable: pure bytes-in/bytes-out, no DB, no network, no worker/job coupling,
documented as never-raising. That review found:

**Safe and reused here:**
- `remediate_pdf.apply_pdf_field_name` — AcroForm `/TU`, bytes → bytes.
- `apply_alt.apply_alt_text` — Office image `descr=`, bytes → bytes.

**Safe but not exercised in this prototype (timebox; good next additions):**
- `remediate_pdf.apply_pdf_figure_alt` / `apply_pdf_approved` — PDF `/Figure` `/Alt`.
  Requires a tagged PDF with a `/StructTreeRoot` and `/Figure` struct elements, which is
  materially more work to build as a synthetic fixture than an AcroForm field; the two
  chosen operations already satisfy "at least one real operation for PDF and one for
  DOCX" without that fixture cost.
- `apply_field_name.apply_docx_field_name` — DOCX form-field accessible names.
- `apply_link_text.apply_link_text` — hyperlink text.
- `remediate_office.image_bytes_for_locator` — read-only, useful for a future
  visual-evidence packager.

**Considered and REJECTED as unsafe to isolate** (see the anti-patterns section of the
adapter survey that produced this table):
- `remediate_pdf._fix_pdf_figure_alt`, `remediate_office._vision_alt` — reach the local
  vision model and a global `core.store.get_auto_apply_validated()` singleton mid-fix.
- `remediate_pdf.remediate_pdf`, `remediate_office.remediate_office` — top-level
  orchestrators; read/write a `Path` with input-derived sibling filenames, mutate
  `sys.path` (`remediate_pdf`, to reach a vendored fixer package), and couple to
  `activity.record`/job tracing. Not a pure function of their arguments.
- `api.document_context.py` — deliberately NOT used to build this prototype's manifest.
  It validates a *model-produced* context package's shape (summary/sections/entities
  bounds) and has no page-count or file-size limit at all; this prototype needs to
  validate the *document's own* extracted content and enforce real extraction limits
  (`packaging/limits.py`), which is a different job. Per ADR 0056, its own docstring
  states it "never calls a provider and never treats the package as approval or
  conformance evidence" — consistent with, but not a substitute for, this prototype's
  contract.

No production module was modified to make any of this work. `production_adapters.py`
only prepends the repo's `api/` directory to `sys.path` so those modules' own bare-name
sibling imports (e.g. `remediate_pdf.py`'s `from swallowed import swallowed`) resolve.
