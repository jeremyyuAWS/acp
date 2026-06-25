# ACP — Accessibility Compliance Platform

**ACP finds the accessibility problems in your organization's documents, fixes the
ones it safely can, and gives you the proof you fixed them.**

It connects to where your documents already live (Google Drive, SharePoint /
OneDrive), checks every Word doc, PowerPoint, PDF, Excel file, and web page, and
tells you — in plain terms — which ones a person with a disability would struggle
to use, and why.

---

## Why this matters

Millions of everyday business documents can't be read by people who are blind,
low-vision, or who rely on assistive technology like screen readers. That's not
just a barrier for real people — in most regions it's now a **legal requirement**
(ADA, Section 508, the European Accessibility Act). Organizations are expected to
prove their documents meet **WCAG 2.1**, the international accessibility standard.

Doing that by hand across thousands or millions of files is impossible. ACP does
it automatically, at scale, and — crucially — **keeps a record an auditor will accept.**

## How it works

```
   1. CONNECT          2. SCAN            3. SCORE           4. FIX             5. PROVE
  ┌──────────┐       ┌──────────┐       ┌──────────┐       ┌──────────┐       ┌──────────┐
  │  Google  │       │  reads   │       │  rates   │       │  fixes   │       │  audit   │
  │  Drive / │  ──▶  │  every   │  ──▶  │  every   │  ──▶  │ what it  │  ──▶  │  report  │
  │SharePoint│       │ document │       │ document │       │ safely   │       │  + PDF   │
  └──────────┘       └──────────┘       └──────────┘       │   can    │       └──────────┘
   your files         originals          0–100 vs          └──────────┘        every check,
   stay in place      never changed      WCAG 2.1          rest → human         on the record
                                                            review queue
```

1. **Connect** — point ACP at your document library. It only ever *reads* your
   files; your originals are never moved or changed without your say-so.
2. **Scan** — it inspects every document against the WCAG accessibility rules.
3. **Score** — each document gets a 0–100 compliance score and a clear list of issues.
4. **Fix** — issues it can fix safely and automatically, it fixes. Anything that
   needs judgment is sent to a **human review queue** instead of guessed at.
5. **Prove** — you get a compliance report (and per-document PDF) showing exactly
   which checks ran and what was found — the evidence for an audit or regulator.

## Why you can trust it

- **Rule-based, not black-box AI.** The checks are deterministic — the same
  document always gets the same result. You can read exactly what each rule looks
  for. AI is only ever used to *draft* a fix that a human approves, and it can be
  **switched off entirely** for a fully deterministic, audit-strict mode.
- **A complete paper trail.** Every check on every document is recorded — pass,
  fail, error, or not-applicable — so you can answer "how do we know rule X was
  checked on this file?" for any document, at any time.
- **Your data stays yours.** ACP runs inside your own cloud. It reads documents
  into temporary memory, never stores copies, and (in deterministic mode) sends
  nothing to any outside AI service.
- **You stay in control.** Nothing is deleted, moved, or published without an
  approval step you configure.

## Who it's for

Compliance officers, accessibility leads, legal and records teams, and the IT
groups who support them — anyone responsible for making (and *proving*) that an
organization's documents are accessible.

> **Status:** built and demo-ready — connect a library, scan, score against WCAG
> 2.1, auto-fix what's safe, route the rest to human review, and export the report.

---

# For developers

Everything below is the technical reference — how to run it, how it's built, and
where every accessibility rule lives.

## Run it locally

```bash
# one-time setup
python -m venv .venv-drive && .venv-drive/bin/pip install -r api/requirements.txt
(cd frontend && npm install)
# Drive scans need keyless ADC (local-corpus scans do not):
gcloud auth application-default login

# start API (:8077) + UI (:5173) together
./scripts/run.sh        # open http://localhost:5173
```

The **bundled sample corpus** (`test-corpus/files`, 14 synthetic WCAG fixtures of
varying quality) lets you run a full scan with no Drive connection — use the
"run a scan on the bundled sample corpus" link on the Sources screen.

## Tests

```bash
.venv-drive/bin/python -m pytest tests/ -q
```

`tests/test_scan.py` runs the real engines against the sample corpus and locks
the oracle outcomes plus the core safety invariant: **an `error` or `uncertain`
file is never certified** (incomplete analysis is never a pass).

## Architecture at a glance

- **Substrate:** MDK (`StorageProvider`, observability, deploy, OAuth, secrets) —
  consumed as a dependency, *not* extended.
- **Orchestration:** the FastAPI control plane (`api/`, split into `core.py` +
  `routes/`) runs scans directly — `Discover → Analyze → Score`. Each scan is an
  **immutable event** persisted to Postgres.
- **Validation engines:** three **deterministic** engines, one per file family —
  HTML (JS, fully modular in-repo), Office (.NET), PDF (Python). See
  [Validation engine — where every WCAG rule lives](#validation-engine--where-every-wcag-rule-lives).
- **Security:** read-only scopes · ephemeral document copies (never persisted) ·
  admin-gated AI (off ⇒ zero LLM egress) · per-customer single-tenant deploy.

## Validation engine — where every WCAG rule lives

ACP's validation framework is **deterministic-first and modular by design**: every
WCAG Success Criterion (SC) is an independent rule with a small, documented
interface, so a developer (or Claude) can change one rule without touching any
other. AI never decides pass/fail — it only *drafts* fixes a human approves, and it
can be switched off platform-wide.

### The three engines (by file type)

| File types | Engine | Language | Where the rule code lives | Editable in this repo? |
|------------|--------|----------|---------------------------|------------------------|
| `.html` `.htm` | HTML | JavaScript | [`frontend/src/rules/wcag-X-X-X.js`](frontend/src/rules) — **one file per SC** | ✅ Yes — fully in-repo |
| `.docx` `.pptx` `.xlsx` | Office | C# (DigitalA11y) | catalogued in [`config/rule-catalog.json`](config/rule-catalog.json); compiled engine | ⚠️ Catalog + params here; rule source upstream |
| `.pdf` | PDF | Python (worker-python) | catalogued in [`config/rule-catalog.json`](config/rule-catalog.json) | ⚠️ Catalog + params here; rule source upstream |

### The registry (single source of truth)

Everything is keyed by **WCAG SC number** (`1.4.3`) end-to-end. Engine-specific IDs
(`DOCX-CONTRAST-001`, `pdf.missing-alt-text`) map *to* the SC via the `wcag_sc`
field. Three places, one convention:

- **[`config/rule-catalog.json`](config/rule-catalog.json)** — every Office/PDF rule:
  `id`, `wcag_sc`, `severity`, `fix_mode`, and the `source` path to its engine code.
- **[`rules/`](rules/)** — the developer map: one folder per SC, each with a README
  listing the engines that check it, the rule IDs, how to change it, and its test
  fixtures. Generated by [`scripts/gen_rules_index.py`](scripts/gen_rules_index.py);
  `rules/README.md` is the **ownership table**, `rules/index.json` the machine-readable index.
- **[`docs/rules/`](docs/rules/)** — per-rule deep-dive notes (what it checks, why, fix rationale).

→ Owning WCAG 1.4.3? Open [`rules/wcag-1-4-3/`](rules/wcag-1-4-3) and everything you
need is linked from there.

### File map — every file that touches a WCAG rule

Where rule-related files live across the repo:

```
acp/
├── config/
│   └── rule-catalog.json ........ REGISTRY · every Office/PDF rule, keyed by wcag_sc
│                                   (id · severity · fix_mode · source path to engine)
├── frontend/src/rules/ .......... HTML ENGINE (deterministic, fully in-repo)
│   ├── index.js ................. orchestrator — runChecks() / runFixes()
│   ├── utils.js ................. shared matchers (AMBIGUOUS_LINK, …)
│   ├── wcag-1-1-1.js ...........┐
│   ├── wcag-1-4-3.js ...........├─ ONE FILE PER SC — exports meta + check() + fix()
│   └── wcag-X-X-X.js ...........┘
├── rules/ ....................... DEVELOPER MAP (generated from the 3 sources)
│   ├── README.md ................ ownership table — who owns each SC
│   ├── index.json ............... machine-readable  SC → engines
│   └── wcag-1-4-3/README.md ..... per-SC guide: engines, rule IDs, how-to, fixtures
├── docs/rules/
│   └── DOCX-CONTRAST-001.md ..... per-rule deep dive (what · why · fix rationale)
├── test-corpus/
│   ├── files/ ................... fixtures that trigger rules
│   └── manifest.json ............ fixture → expected findings
├── scripts/
│   └── gen_rules_index.py ....... regenerates rules/ from catalog + frontend + corpus
└── api/
    ├── scanner.py ............... runs the engines, emits per-rule outcomes
    ├── lf.py ⟶ Langfuse ......... one trace span per (file, rule)
    └── store.py ⟶ Postgres ...... scan_file_manifests · scan_rule_traces
                                    (PASS / FAIL / ERROR / NOT_APPLICABLE per rule)
```

Following **one** Success Criterion — `1.4.3 Contrast (Minimum)` — through every file:

```
                    WCAG 1.4.3 — Contrast (Minimum)   [the cross-engine key]
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                           ▼
   HTML engine                Office engine                PDF engine
   (JS · in-repo)             (.NET · vendored)            (Python · vendored)
        │                          │                           │
 frontend/src/rules/        config/rule-catalog.json    config/rule-catalog.json
   wcag-1-4-3.js              docx: DOCX-CONTRAST-001     (no 1.4.3 PDF rule yet)
   ├ meta {id:'1.4.3'}        pptx: PPTX-CONTRAST-001          → NOT_APPLICABLE
   ├ check(doc) → findings    each entry's `source`:
   └ fix(doc)   → changes       …/Rules/.../ContrastRule.cs
        │                          │                           │
        └──────────────┬───────────┴───────────────────────────┘
                       ▼
        scanner.py runs it → recorded for EVERY scanned file:
        ├ Postgres :  scan_file_manifests · scan_rule_traces   (PASS/FAIL/ERROR/N-A)
        └ Langfuse :  one span per (file, rule)                → GET /scans/{id}/manifest
                       │
                       ▼  documentation for this SC
        rules/wcag-1-4-3/README.md ....... dev guide (generated)
        docs/rules/DOCX-CONTRAST-001.md .. deep dive
        test-corpus/files/*contrast*.pdf . fixtures (pdf-serious-contrast.pdf, …)
```

### Anatomy of an HTML rule module

Each `frontend/src/rules/wcag-X-X-X.js` exports exactly three things and imports
nothing from other rules (zero coupling):

```js
// frontend/src/rules/wcag-2-4-4.js  — 2.4.4 Link Purpose (In Context)
export const meta = {
  id: '2.4.4',            // WCAG SC number — the cross-engine key
  level: 'A',
  name: 'Link Purpose (In Context)',
  fixMode: 'ai-assisted', // 'auto' | 'ai-assisted' | 'human-only'
}

export function check(doc) {            // pure, deterministic: DOM → findings
  const findings = []
  doc.querySelectorAll('a').forEach((a) => {
    if (AMBIGUOUS_LINK.test(a.textContent.trim()) && !a.getAttribute('aria-label')) {
      findings.push({ element: …, detail: …, severity: 'SERIOUS' })
    }
  })
  return findings                       // [] === PASS
}

export function fix(doc) {              // deterministic remediation → change descriptions
  const changes = new Set()
  /* … mutate doc … */ changes.add('Clarified ambiguous links · 2.4.4')
  return changes
}
```

The orchestrator [`frontend/src/rules/index.js`](frontend/src/rules/index.js) runs
`check()` on every rule and aggregates outcomes (`runChecks`), and applies `fix()`
respecting the AI mode (`runFixes`). It is the **only** file that knows about all
rules — individual modules know nothing about each other.

### Adding or changing an HTML rule

1. `cp frontend/src/rules/wcag-2-4-4.js frontend/src/rules/wcag-X-X-X.js` and edit
   `meta` / `check` / `fix`.
2. Import it in [`frontend/src/rules/index.js`](frontend/src/rules/index.js) and
   append it to `allRules`. **No other file changes.**
3. Add a fixture under `test-corpus/` and note it in `test-corpus/manifest.json`.
4. Run `python scripts/gen_rules_index.py` (refreshes `rules/`) and
   `.venv-drive/bin/python -m pytest tests/ -q`.

For Office/PDF rules you edit the catalog entry (`config/rule-catalog.json`) and/or
the rubric (`config/rubric.active.json` → `disabled_rules`); the detection source
lives in the upstream DigitalA11y engine (its `source` path is in the catalog).

### Deterministic over AI

- `check()` and the Office/PDF engines are **pure deterministic functions** — the
  same document always yields the same findings. AI is never in the detection path.
- AI appears in exactly two opt-in places: `fixMode: 'ai-assisted'` rules (AI drafts
  a fix, a human approves it via the HITL queue) and the `/ai/explain` helper.
- An admin can set **deterministic-only mode** (`PUT /settings {ai_enabled:false}`):
  no AI fixes run, `/ai/explain` returns 403, and findings needing interpretation
  auto-route to human review. See [ADR 0002](docs/adr/0002-assessment-transparency-spec.md).

### Traceability (every rule, every file)

Every rule execution is recorded: `scan_file_manifests` stores **PASS / FAIL /
ERROR / NOT_APPLICABLE** per `(scan, file, rule)`, and a Langfuse span is emitted
per rule per file. So "was WCAG 1.1.1 evaluated for this document?" is answerable
from `GET /scans/{id}/manifest` — for every rule, including the ones that didn't
apply. See [ADR 0002](docs/adr/0002-assessment-transparency-spec.md).

## Docs

- [Validation engine](#validation-engine--where-every-wcag-rule-lives) · [rules/ ownership index](rules/README.md)
- [ADR 0001 — read-only assessment spine on MDK](docs/adr/0001-read-only-assessment-spine-on-mdk.md)
- [ADR 0002 — assessment transparency spec](docs/adr/0002-assessment-transparency-spec.md)
- [ADR 0003 — document lifecycle model](docs/adr/0003-document-lifecycle-model.md)
- [PRD conformance roadmap](docs/prd-conformance-roadmap.md)
- [MVP build plan (lean first cut)](docs/mvp-build-plan.md)

## Provenance note

The `~/projects/_review-digital-accessibility` checkout (devSEAL "Digital A11y")
is a **read-only diligence clone**, kept outside this repo. No customer code is
vendored here until IP rights are secured in writing.
