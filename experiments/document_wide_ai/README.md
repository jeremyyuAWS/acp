# Document-wide AI fixes — prototype

Status: **limited production integration with an offline evaluation harness.**
The app integrates this package through `api/document_wide_workflow.py` and
`api/document_wide_provider.py`. Users opt into document-wide AI in the remediation
plan; configured cloud providers receive bounded extracted context and, for eligible
PDF figures, page images. This does not upload the original file wholesale.

Requests include the selected assessment findings. Only allowlisted edits are
accepted. Production proposals flow through existing approval and saved-copy paths;
semantic edits remain unverified until the required review is recorded. The offline
harness additionally exercises candidate application and structural readback.

Real provider cost and quality have not been established by the offline tests.

## Pipeline

```
source bytes ──> package (extract text + the one structural fact per allowlisted op)
             ──> freeze manifest (document identity, selected SCs, findings, allowed ops)
             ──> build ONE request (stable JSON prefix + short instruction suffix)
             ──> mock provider.generate()  [no network — see request/mock_provider.py]
             ──> validate (structural + per-edit + conflict checks against the manifest)
             ──> apply valid edits to a FRESH copy, via a REUSED production adapter
             ──> save candidate to a dedicated output dir, reopen, recheck
             ──> per-finding outcome report
```

Entry point: `evaluation.harness.run_pipeline(source_bytes, manifest, provider, output_dir)`.

## Supported operations (the allowlist)

Three operations backed by existing production adapters:

| Operation | Format | SC | Adapter |
|---|---|---|---|
| `set_pdf_field_accessible_name` | PDF | 4.1.2 | `api.remediate_pdf.apply_pdf_field_name` |
| `set_pdf_figure_alt_text` | PDF | 1.1.1 | `api.remediate_pdf.apply_pdf_figure_alt` |
| `set_office_image_alt_text` | DOCX | 1.1.1 | `api.apply_alt.apply_alt_text` |

Anything else is `unsupported_operation` and is never applied, only reported.

## Directory layout

```
contracts/     versioned manifest + edit-response schemas (contracts/v1.py)
packaging/     extraction limits, PDF/DOCX context packagers, manifest builder
request/       request builder (cache-ready stable prefix) + offline mock provider
validation/    strict per-edit + conflict validation against the frozen manifest
application/   the allowlist, the production-adapter import shim, and the applier
recheck/       save/reopen/recheck the candidate, and the final outcome report
evaluation/    end-to-end harness + cost/caching instrumentation
fixtures/      synthetic PDF/DOCX builders (no binaries committed)
tests/         offline tests, zero provider/network calls
docs/          this adapter inventory, integration notes, and sample reports
```

## Running the tests

Needs `pikepdf`, `pypdf`, `python-docx` — already declared in `api/requirements.txt` /
`tests/requirements.txt`; install them into any venv if your environment doesn't have
them yet (nothing here changes those requirement files).

```
python -m pytest experiments/document_wide_ai -c experiments/document_wide_ai/pytest.ini
```

The experiment tests are offline. No test calls a provider, a database, or the network.

## Remaining limits

- No wholesale original-file upload or automatic chunking.
- No general PDF heading, table, reading-order or untagged-document repair.
- PDF figure suggestions require an existing tagged target and unambiguous page-image evidence.
- Extraction, image and spending limits apply; unsupported findings remain explicit.
- No claim of full document conformance from a saved edit or outcome report.
- Historical integration notes and adapter inventory describe the original prototype;
  the production entry points above are the current integration reference.
