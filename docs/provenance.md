# Provenance (internal)

This note documents the origin of the validation engines and is kept in `docs/`
rather than the top-level README (it's an internal/engineering concern, not a
product-facing detail).

## Validation engines

- **HTML engine** — built in this repository (`frontend/src/rules/`), one module
  per WCAG Success Criterion. Fully owned and editable here.
- **Office (.docx/.pptx/.xlsx) and PDF engines** — detection logic is provided by
  the **DigitalA11y** engine (devSEAL "Digital A11y"). ACP consumes it as a pinned,
  compiled build artifact and catalogues each rule in
  [`config/rule-catalog.json`](../config/rule-catalog.json) (with the upstream
  `source` path per rule). The engine source is **not vendored** into this repo.

A read-only review checkout of the upstream engine may exist on a developer machine
for reference; it is intentionally kept **outside** this repository.

## Roadmap note

Bringing the Office/PDF rules under the same in-repo, one-module-per-rule contract
as the HTML engine is tracked as part of capability goal #5 — see the
[PRD conformance roadmap](prd-conformance-roadmap.md).
