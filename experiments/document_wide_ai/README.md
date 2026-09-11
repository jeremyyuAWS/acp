# Document-wide AI fixes — prototype

Status: **prototype, ready for integration review.** Not shipped, not production
verified, not wired into any production entry point, model, or UI. See ADR 0056 for the
distinction between the shipped provider waterfall and a deliberately unwired
verification prototype — this experiment is closer to the latter in spirit, but lives
entirely outside `api/` and is scoped even more narrowly (two operations, mock
provider only).

## What this is

An offline exploration of one hypothesis: sending a document's full context **once** and
requesting edits for **every remaining finding** in one structured response, instead of
one provider call per finding, may reduce repeated input and improve consistency. This
prototype does not measure real cost or quality — it builds the pipeline shape and the
safety rails needed to measure them later, against a real provider, on real documents.

The existing simpler waterfall (ADR 0056) is untouched. Nothing here changes its
behavior, delays it, or activates this mode anywhere.

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

Two operations, each backed by a real, isolated, already-shipped production adapter —
see `docs/ADAPTER_INVENTORY.md` for the full survey and why these two:

| Operation | Format | SC | Adapter |
|---|---|---|---|
| `set_pdf_field_accessible_name` | PDF | 4.1.2 | `api.remediate_pdf.apply_pdf_field_name` |
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
tests/         53 offline tests, zero provider/network calls
docs/          this adapter inventory, integration notes, and sample reports
```

## Running the tests

Needs `pikepdf`, `pypdf`, `python-docx` — already declared in `api/requirements.txt` /
`tests/requirements.txt`; install them into any venv if your environment doesn't have
them yet (nothing here changes those requirement files).

```
python -m pytest experiments/document_wide_ai -c experiments/document_wide_ai/pytest.ini
```

53 tests, all offline. No test calls a provider, a database, or the network.

## What this prototype does NOT do

- No production credentials, customer documents, or paid provider calls, anywhere.
- No UI control, no production mode selection, no default change.
- No new fix engines — only two already-shipped adapters, reused, not modified.
- No automatic chunking, retry, or repair request (PRD: "no automatic repair request...
  in the prototype").
- No live prompt caching or real pricing — only a cache-ready stable prefix is built
  (`request/builder.py`); see `docs/INTEGRATION_NOTES.md` for what real caching needs.
- No claim of full document conformance from any outcome report.

See `docs/INTEGRATION_NOTES.md` for exact test results, the required integration seams,
and what a follow-up task owns.
