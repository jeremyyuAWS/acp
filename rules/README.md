# Rule ownership index

This directory is the **developer map of every accessibility rule** the platform
checks — one folder per WCAG 2.1 Success Criterion (SC). If you own a criterion,
your folder tells you exactly what is checked, by which engine, where the source
lives, how to change it, and which test fixtures cover it.

## How rules are actually implemented

Rules live in **three** places depending on the document type. This index stitches
them together so you don't have to know that to find your way around:

| Engine | Language | Source of truth | What it covers |
|--------|----------|-----------------|----------------|
| **HTML** | JS (in-app, deterministic) | [`frontend/src/rules/`](../frontend/src/rules/) — one `wcag-X-X-X.js` per SC | `.html` files; live `check()` + `fix()` |
| **Office** | C# (partner DigitalA11y engine) | [`config/rule-catalog.json`](../config/rule-catalog.json) → `docx`/`pptx`/`xlsx` | `.docx` `.pptx` `.xlsx` |
| **PDF** | Python (worker-python engine) | [`config/rule-catalog.json`](../config/rule-catalog.json) → `pdf` | `.pdf` |

The per-SC READMEs here are **generated** from those sources by
[`scripts/gen_rules_index.py`](../scripts/gen_rules_index.py). After any rule
change, run:

```bash
python scripts/gen_rules_index.py
```

A machine-readable version is at [`rules/index.json`](./index.json) (used by CI and
tooling). **This file** (`rules/README.md`) is the one humans hand-maintain — keep
the ownership column current.

## The single rule-ID convention

Everything is keyed by **WCAG SC number** (`1.4.3`), end to end. Engine-specific IDs
(`DOCX-CONTRAST-001`, `pdf.missing-alt-text`) are an implementation detail that maps
*to* the SC via the `wcag_sc` field in the catalog and `_extract_sc()` in
[`api/store.py`](../api/store.py). When you see a finding, trace it: engine rule ID →
`wcag_sc` → this folder.

## Ownership

Claim a criterion by putting your name in the Owner column. Owning an SC means you're
the reviewer for any change to its detection or remediation, across all engines.

| Success Criterion | Level | Engines | Owner |
|-------------------|-------|---------|-------|
| [1.1.1 Non-text Content](./wcag-1-1-1/) | A | docx, pdf, pptx, xlsx, html | _unassigned_ |
| [1.3.1 Info and Relationships](./wcag-1-3-1/) | A | docx, pdf, pptx, xlsx, html | _unassigned_ |
| [1.3.2 Meaningful Sequence](./wcag-1-3-2/) | A | pdf, pptx, xlsx | _unassigned_ |
| [1.4.1 Use of Color](./wcag-1-4-1/) | A | html | _unassigned_ |
| [1.4.3 Contrast (Minimum)](./wcag-1-4-3/) | AA | docx, pptx, html | _unassigned_ |
| [1.4.4 Resize Text](./wcag-1-4-4/) | AA | html | _unassigned_ |
| [1.4.10 Reflow](./wcag-1-4-10/) | AA | html | _unassigned_ |
| [1.4.11 Non-text Contrast](./wcag-1-4-11/) | AA | html | _unassigned_ |
| [1.4.12 Text Spacing](./wcag-1-4-12/) | AA | html | _unassigned_ |
| [2.1.1 Keyboard](./wcag-2-1-1/) | A | pptx, html | _unassigned_ |
| [2.4.2 Page Titled](./wcag-2-4-2/) | A | docx, pdf, pptx, xlsx, html | _unassigned_ |
| [2.4.3 Focus Order](./wcag-2-4-3/) | A | html | _unassigned_ |
| [2.4.4 Link Purpose (In Context)](./wcag-2-4-4/) | A | docx, pptx, html | _unassigned_ |
| [2.4.6 Headings and Labels](./wcag-2-4-6/) | AA | html | _unassigned_ |
| [2.4.7 Focus Visible](./wcag-2-4-7/) | AA | html | _unassigned_ |
| [3.1.1 Language of Page](./wcag-3-1-1/) | A | docx, pdf, pptx, xlsx, html | _unassigned_ |
| [3.1.4 Abbreviations](./wcag-3-1-4/) | AAA | html | _unassigned_ |
| [4.1.2 Name, Role, Value](./wcag-4-1-2/) | A | html | _unassigned_ |

## Adding a new rule

1. **HTML:** create `frontend/src/rules/wcag-X-X-X.js` (copy an existing module),
   export `meta` + `check` + `fix`, import it in `frontend/src/rules/index.js`.
2. **Office/PDF:** add the rule entry to `config/rule-catalog.json` under the engine,
   with `wcag_sc`, `severity`, `fix_mode`, and the engine `source` path.
3. Add a fixture to `test-corpus/` that triggers it, and note it in
   `test-corpus/manifest.json`.
4. Run `python scripts/gen_rules_index.py` and commit the regenerated folder.

## Fix modes

- `auto` — deterministic engine fix, applied without human review.
- `ai-assisted` — engine drafts a fix, a human approves it (routed to the HITL queue
  when AI is **on**; routed straight to HITL as `human-only` when AI is **off** —
  see the AI toggle in the app header).
- `human-only` — must be verified by a person; never auto-applied.
