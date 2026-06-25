# ACP — Accessibility Compliance Platform

**ACP finds the accessibility problems in your organization's documents, fixes the
ones it safely can, and gives you the proof you fixed them.**

It connects to where your documents already live (Google Drive, SharePoint /
OneDrive), checks every Word doc, PowerPoint, PDF, Excel file, and web page, and
tells you — in plain terms — which ones a person with a disability would struggle
to use, and why.

**▶ [See it live](https://acp-app.greenwater-4bf2c997.eastus2.azurecontainerapps.io/hub)**
 · New here? Just read on. · Engineer? Skip to **[For developers](#for-developers)**.

<!-- Screenshots welcome here: drop product images into docs/images/ and embed them,
     e.g. ![Compliance dashboard](docs/images/dashboard.png) — see README suggestions. -->

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

## How ACP manages its accessibility rules

The easiest way to picture ACP is as an **automated accessibility inspector with a
detailed checklist.** Each item on the checklist is one specific accessibility
requirement. ACP runs the *entire* checklist against *every* document, every time,
and writes down the result of each item — so you always end up with a completed,
signed-off inspection sheet you can hand to an auditor.

Here's how that checklist is put together and kept trustworthy.

### Each rule is one accessibility requirement — in plain language

A "rule" isn't technical jargon — it's a single, specific thing that has to be true
for a document to be accessible. For example:

> **Every image needs a written description.**
> A person using a screen reader can't see the picture — the software reads the
> written description aloud instead. No description means they get nothing.

That's one rule. ACP has dozens of them, and each one maps to a specific line in
**WCAG 2.1**, the international accessibility standard. So a finding is never just
ACP's opinion — it's a citable requirement from a recognized standard.

### What every rule tells you

Each rule is small, self-contained, and described in the same plain-language way, so
anyone can understand exactly what it does. Think of each rule as a little index card:

```
┌─────────────────────────────────────────────────────────────┐
│  RULE:  "Non-text Content"                                    │
│  Standard:    WCAG 1.1.1  (Level A)                           │
│  Checks:      Does every image have a text description?       │
│  Why:         Screen readers read the description aloud to    │
│               people who can't see the image.                 │
│  Severity:    Critical                                        │
│  How it's fixed:  Description drafted automatically →         │
│                   a person reviews and approves it            │
└─────────────────────────────────────────────────────────────┘
```

Every rule carries those same facts: **which standard** it comes from, **what** it
looks for, **why** it matters, **how serious** a failure is (Critical, Serious, or
Moderate), and **how it gets fixed.**

### Three ways a problem gets fixed — and you choose how much AI is involved

Not every issue should be fixed the same way. ACP sorts each rule into one of three
"fix modes," so the easy things happen automatically and the judgment calls always
reach a person:

| Fix mode | What happens | Example |
|----------|--------------|---------|
| **Automatic** | Clear-cut and safe — ACP just fixes it, no review needed. | Tagging a document with its language so screen readers pronounce it correctly. |
| **Suggested → you approve** | ACP (optionally with AI) drafts a fix; a person reviews and approves it before anything changes. | Writing a good, meaningful description for a photo. |
| **Human-only** | Needs human judgment — ACP flags it and routes it to a review queue. It never guesses. | Deciding whether a complex chart conveys meaning that text alone can't. |

You set the policy. ACP can run with AI assistance on the "Suggested" items, or you
can switch AI **off entirely** — in which case nothing is auto-drafted, every
judgment call goes to a human, and no document data ever leaves your environment.

### How the rules stay organized, current, and trustworthy

- **One rule, one requirement.** Because each rule is self-contained, a rule can be
  added, adjusted, or turned off **without disturbing any of the others.** There's no
  tangled "change one thing, break five others" risk — which means the checklist can
  grow and improve safely over time.
- **You can see — and tune — the whole checklist.** The complete list of rules is
  visible in the app, along with what each one found across your documents. You can
  switch individual rules on or off to match your organization's policy or the
  conformance level you're targeting.
- **Every document type has its own checklist, one shared standard.** Word docs,
  PDFs, PowerPoint, Excel, and web pages are each checked by rules built for that
  format — but all of them are measured against the same WCAG 2.1 standard, so a
  score on a PDF means the same thing as a score on a Word doc.
- **Nothing is hidden.** For every document, ACP records every rule it ran and the
  outcome — passed, failed, errored, or not-applicable to that file type. That's how
  you can answer, for any file, "how do we know this requirement was actually
  checked?" — the question an auditor will eventually ask.

> In short: the rules are a transparent, editable checklist mapped to a recognized
> standard — not a mysterious score from a black box. You can read every rule, see
> what it found, decide how it's fixed, and prove it ran.

## Frequently asked questions

**Does ACP change my original files?**
No — not unless you tell it to. Scanning is entirely read-only. When you remediate,
ACP writes a *fixed copy* to a separate folder and leaves the original untouched;
nothing is moved, renamed, or deleted without an approval step you configure.

**What about data privacy — does my content go to an AI service?**
You control that. ACP can run in **deterministic-only mode**, where no document
content ever leaves your environment and no AI is involved at all. Even with AI
assistance turned on, it's used only to *draft* a fix that a person approves.

**Which file types can it check?**
Word (`.docx`), PowerPoint (`.pptx`), Excel (`.xlsx`), PDF, and web pages (HTML) —
all measured against the same WCAG 2.1 standard.

**How do I know a given rule was actually checked on a document?**
Every check on every document is recorded — pass, fail, error, or not-applicable —
so you can produce that evidence for any file, for any rule, at any time. That's the
core of how ACP supports an audit.

**How accurate is it — what about false positives?**
The checks are deterministic (rule-based), so results are consistent and
explainable. Anything that genuinely needs human judgment is *routed to a person*
rather than guessed at, which keeps confident automated fixes separate from
judgment calls.

**Can we run it inside our own cloud?**
Yes — ACP is designed to run entirely within your environment, with no dependency on
outside services. There's a one-command local/VPC stack with its own setup guide
([`deploy/compose/`](deploy/compose)) and an Azure deployment path.

## Who it's for

Compliance officers, accessibility leads, legal and records teams, and the IT
groups who support them — anyone responsible for making (and *proving*) that an
organization's documents are accessible.

> **Status:** built and demo-ready — connect a library, scan, score against WCAG
> 2.1, auto-fix what's safe, route the rest to human review, and export the report.

## Capability roadmap — the nine product goals

ACP is designed against nine capability goals (the product wishlist below). We track
them **honestly**: some run today, some are partly there, and some are designed and
written down but not yet built. Nothing here is marketing —

- ✅ **Built** — works in the platform today.
- 🟡 **Partial** — the foundation is real; some pieces remain.
- 📋 **Designed** — specified in a written design doc (linked), on the roadmap, not yet built.

The full engineering breakdown lives in the
[PRD conformance roadmap](docs/prd-conformance-roadmap.md).

| # | Goal | Status |
|---|------|--------|
| 1 | Configurable file disposition | 📋 Designed |
| 2 | Partial remediation workflow | 📋 Designed |
| 3 | Intelligent file triage & prioritization | 📋 Designed |
| 4 | Phased remediation strategy | 📋 Designed |
| 5 | Modular deterministic validation engine | ✅ / 🟡 |
| 6 | Deterministic-only operating mode | ✅ Built |
| 7 | Validation coverage & traceability | ✅ Built |
| 8 | Transparent validation specification | 🟡 Partial |
| 9 | White-box controls & explainability | 🟡 Partial |

### 1 · Configurable file disposition — 📋 Designed
**Goal:** let an administrator choose what happens to each document after analysis
or remediation — *leave in place, archive, rename by a naming convention, move, or
delete (with approval)* — so ACP fits an organization's existing records-management
process.
**Today:** ACP writes a remediated *copy* into a Drive `Remediated/` folder; your
originals are never moved, renamed, or deleted.
**Planned:** admin-defined disposition policies (e.g. "archive PDFs older than two
years"), real move/archive/delete actions, and an immutable record of what was done
to each file. Specified in [ADR 0003](docs/adr/0003-document-lifecycle-model.md).

### 2 · Partial remediation workflow — 📋 Designed
**Goal:** track files that are only partly fixed — which violations remain, which
need human review, and the ability to resume — with clear states (*Not Started → In
Progress → Partially Remediated → Awaiting Human Review → Complete*).
**Today:** each finding that needs judgment lands in a real **human review queue**
(the "Awaiting Human Review" state), and a file is marked remediated once written back.
**Planned:** a per-violation status machine so "3 of 5 issues fixed" and "resume from
where we stopped" are first-class. Specified in [ADR 0003](docs/adr/0003-document-lifecycle-model.md).

### 3 · Intelligent file triage & prioritization — 📋 Designed
**Goal:** decide *where to spend effort first* — surface high-value documents, flag
obsolete/duplicate/low-value files, and rank by accessibility risk, usage, business
criticality, owner, department, age, and regulatory importance.
**Today:** the interface demonstrates triage and prioritization on sample data.
**Planned:** a server-side scorer that ranks real documents from stored metadata, plus
duplicate/obsolete detection. Specified in [ADR 0003](docs/adr/0003-document-lifecycle-model.md).

### 4 · Phased remediation strategy — 📋 Designed
**Goal:** roll out remediation across thousands or millions of files in controlled
stages — batches, priority queues, department-by-department, with progress dashboards
and the ability to pause and resume a campaign.
**Today:** the interface shows staged, batched progress on sample data.
**Planned:** persisted campaigns and batches with real pause/resume, scoped to a
department or business unit. Specified in [ADR 0003](docs/adr/0003-document-lifecycle-model.md).

### 5 · Modular deterministic validation engine — ✅ / 🟡
**Goal:** one self-contained module per WCAG rule, independent and well-documented,
so any rule can be updated without disturbing the others — deterministic checks over
opaque AI logic.
**Today:** ✅ fully realized for the **web/HTML** engine — one file per rule, zero
coupling, documented; see [How ACP manages its accessibility rules](#how-acp-manages-its-accessibility-rules)
and the [Validation engine](#validation-engine--where-every-wcag-rule-lives) reference.
🟡 the Office and PDF rules are catalogued and parameterized here, but their detection
code lives in a separate (vendored) engine — so those rules aren't yet editable in this
repo to the same degree.
**Planned:** bring Office/PDF rules under the same one-module-per-rule contract.

### 6 · Deterministic-only operating mode — ✅ Built
**Goal:** an admin switch that disables **all** AI — only deterministic checks run, no
AI-generated fixes, and anything needing interpretation goes straight to human review —
for organizations with strict compliance, privacy, or audit requirements.
**Today:** ✅ a persisted, platform-wide setting. When off: AI explanations are blocked,
no AI fixes run, and findings that would need interpretation are **automatically routed
to the human review queue**. With AI off, no document content leaves your environment.

### 7 · Validation coverage & traceability — ✅ Built
**Goal:** complete transparency into every check on every document — record every WCAG
rule run, with pass/fail/not-applicable status and trace-level logging — so an auditor
can ask *"How do we know rule 1.1.3 was actually evaluated for this document?"* and get
an answer.
**Today:** ✅ every rule execution is recorded per document as **PASS / FAIL / ERROR /
NOT_APPLICABLE**, with a trace span (Langfuse) per rule per file. A per-scan completeness
report (`GET /scans/{id}/manifest`) answers that auditor question for *every* rule —
including the ones that didn't apply. See [ADR 0002](docs/adr/0002-assessment-transparency-spec.md).

### 8 · Transparent validation specification — 🟡 Partial
**Goal:** a formal written spec of the validation framework — pipeline, rule execution
order, deterministic algorithms, human-review boundaries, remediation decision logic,
and extensibility.
**Today:** [ADR 0002](docs/adr/0002-assessment-transparency-spec.md) specifies the
transparency contract (what every rule records, how completeness is proven), and every
rule has a plain-language write-up.
**Planned:** formalize the remediation decision tree, the rule execution order, and the
extensibility contract for the Office/PDF engines.

### 9 · White-box controls & explainability — 🟡 Partial
**Goal:** a fully inspectable platform — show what ACP is doing at each stage, explain
why decisions were made, surface confidence where AI is used, and keep audit logs and
execution history, rather than a black-box score.
**Today:** ✅ an **immutable audit log** records every consequential decision (scan mode,
auto-routing, each human review with reviewer + note, settings changes), and the per-rule
trace + completeness data is queryable for any scan.
🟡 the in-app surfacing of that data (completeness warnings, remediation rationale, AI
confidence) is still being built out — today the evidence is fully recorded and available
via the API, but not yet shown in every screen.

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

The **bundled sample corpus** (`test-corpus/files`, 55 synthetic WCAG fixtures of
varying quality across every supported file type) lets you run a full scan with no
Drive connection — use the "run a scan on the bundled sample corpus" link on the
Sources screen.

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
- [Engine provenance (internal)](docs/provenance.md)

## License & usage

**Proprietary — © mova.io. All rights reserved.** This software is not open-source
and is not licensed for redistribution or external use. Contact mova.io for terms.
