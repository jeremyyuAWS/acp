# ACP — Architecture deck

Slide source. Every `##` is one slide; `---` separates them. Renders as-is in Marp, reveal.js,
Deckset or Slides.com, and reads fine as a plain document if nobody projects it.

Companion to `acp-overview-deck.md`, which covers *what ACP does* for a non-technical audience.
This one covers *how it is built* — service names, libraries, and the decisions behind them —
for an engineering or architecture-review audience.

**Everything here was read from the running system on 2026-07-29**, not from memory: container
names and sizes from `az containerapp list -g mdk-accessibility`, libraries from
`api/requirements.txt` and the `.csproj` files, ADR numbers from `docs/adr/`. Re-check before
presenting if it has been a while — the deploy is manual and the topology moves.

---

## How the deck is arranged, and why

Fourteen slides in four movements. The order is deliberate: it answers the questions an
architecture reviewer asks *in the order they ask them*.

| # | Movement | Slides | The question it answers |
|---|---|---|---|
| 1 | **Shape** | 2–4 | What is deployed, and what talks to what? |
| 2 | **Engines** | 5–8 | What actually reads a document — and why three of them? |
| 3 | **Flow** | 9–11 | What happens to one file, end to end? |
| 4 | **Honesty & ops** | 12–14 | How do we know it's right, and what is weak? |

Two things about the arrangement worth keeping if you re-cut it:

**Lead with the picture, not the stack.** Slide 2 is the topology. A reviewer cannot hold a
library list in their head until they know how many processes there are and which one is
public-facing.

**Put the weaknesses on the deck, not in the Q&A.** Slide 14 is deliberate. Every architecture
review finds the soft spots anyway; a deck that names them first is trusted on everything else.
The manual deploy is the honest headline there.

If you need a **5-minute cut**: slides 2, 5, 9, 12. That is topology → engines → flow → the
honesty bar, which is the whole argument in four slides.

---

## ACP in one picture

Six Azure Container Apps in one managed environment (`mdk-accessibility-env`), one registry,
one database, one object store.

```
                 ┌──────────────┐
   browser ──────►   acp-app     │  external ingress, 1 CPU / 2 GiB, 1–3 replicas
                 │  FastAPI      │  uvicorn app:app
                 └──────┬───────┘
                        │  Postgres job queue (ADR 0004)
                 ┌──────▼───────┐
                 │  acp-worker   │  internal, same image, 1–3 replicas
                 │  worker_main  │  python -m worker_main
                 └──┬────┬───┬──┘
       ┌────────────┘    │   └────────────┐
 ┌─────▼─────┐    ┌──────▼─────┐   ┌──────▼──────┐
 │ acp-ollama│    │  acp-redis │   │acpremediated│
 │ 4 CPU/8GiB│    │ redis:7    │   │store (Blob) │
 │ internal  │    │ internal   │   │ managed ID  │
 └───────────┘    └────────────┘   └─────────────┘

 observability:  acp-langfuse (per-rule traces) · acp-grafana · Log Analytics
```

**`acp-app` and `acp-worker` run the identical image** (`acp-app:<sha>-<ts>`) and differ only by
entrypoint. One build, two roles — so a capability fix cannot be live in the API and stale in
the worker, which is where scanning actually happens.

---

## The Azure inventory

| Resource | Type | Notes |
|---|---|---|
| `acp-app` | Container App | External ingress, port 8077. 1 CPU / 2 GiB, scale 1–3 |
| `acp-worker` | Container App | Internal. Same image, `python -m worker_main`. Scale 1–3 |
| `acp-ollama` | Container App | Internal, **4 CPU / 8 GiB**, scale-to-zero off. Local inference |
| `acp-redis` | Container App | `redis:7-alpine`. Cross-replica scan-token durability |
| `acp-langfuse` | Container App | `langfuse/langfuse:2`. Per-rule LLM traces |
| `acp-grafana` | Container App | Dashboards |
| `mdk-accessibility-env` | Managed Environment | The shared network boundary |
| `mdkaccessibilityacr` | Container Registry | All first-party images |
| `mdk-accessibility-pg` | PostgreSQL Flexible Server | Job queue + scan state |
| `acpremediatedstore` | Storage Account | Remediated output, **managed identity, no keys** (ADR 0010) |
| `workspace-mdkaccessibility…` | Log Analytics | Container logs |
| `acp-5xx-errors`, `acp-replica-restarts`, `acp-dead-letter-jobs` | Alerts | Platform + queue health |

No key-based auth to storage: `acp-app`'s system-assigned identity holds **Storage Blob Data
Contributor**. Secrets that must exist (Google ADC, DB URL, Langfuse keys) are Container App
secrets referenced as `secretref:`, never baked into the image.

---

## Why three document engines

This is the part of the architecture that surprises people, so it is worth being direct: ACP
does not have *an* engine. It has three, split by what each format's ecosystem does well.

| Engine | Language | Handles | Why not the others |
|---|---|---|---|
| **Office analysers** | C# / .NET 10 | DOCX, XLSX, PPTX | Open XML SDK is the only first-party OOXML reader; the Python options misread real files (ADR 0012) |
| **worker-python** | Python | PDF structure, tags, reading order | Pre-existing engine, vendored into the image at build |
| **api/formats/** | Python | Cross-format + HTML, capability registry | Where new per-format detectors land |

The cost is real — a build needs `dotnet build -c Release` *before* `az acr build`, because the
Dockerfile `COPY`s the compiled analyser. Forget it and the image build fails at step 18.

---

## Engine 1 — the .NET Office analysers

`engine/office-analysers/DigitalA11y.Analysers.DotNet`, invoked as a CLI
(`spike/dotnet/AcpScan.Cli`) and shelled out to per file.

- **Target:** `net10.0`
- **`DocumentFormat.OpenXml`** — first-party OOXML. Reads `w:docPr/@descr`, `xdr:cNvPr`,
  `a:rPr/@lang`, style tables, theme colours
- **`Microsoft.Extensions.DependencyInjection`** — rules are DI-registered, so adding a rule is
  a registration rather than an edit to a dispatch table
- **`Microsoft.Extensions.Options`** — per-rule configuration

Rules are one class per criterion — `AltTextRule`, `LinkPurposeRule`, `LanguageOfPartsRule`,
`ColourContrastRule`, `SheetNameUniquenessRule` — each mapped to a WCAG SC in
`config/rule-catalog.json`.

---

## Engine 2 — the PDF stack

PDF has no single library that does everything, so ACP uses four, each for what it is good at.

| Library | Used for |
|---|---|
| **`pikepdf`** (10.8) | Object model: `/StructTreeRoot`, `/AcroForm`, `/Alt`, `/TU`, content-stream rewriting |
| **`pdfplumber`** (0.11) | Geometry: `page.chars`, `page.rects`, per-glyph colour and bbox |
| **`pdfminer.six`** | Text extraction under pdfplumber |
| **`pypdf`** (6.14) | Metadata reads where pikepdf is awkward |
| **`pypdfium2`** | Page-1 thumbnail render — **pure wheel**, chosen to avoid poppler (GPL) and PyMuPDF (AGPL) |

Plus **`pytesseract`** for images-of-text OCR (1.4.5), wrapping the `tesseract-ocr` binary
installed in the image.

The vendored `worker-python` engine (`analysers/`, `models/`, `remediation/` — 41 modules) is
copied into the build context at deploy time and loaded at runtime from `ACP_PDF_ENGINE`. It is
**not** in this repo, which is a real supply-chain seam worth naming on slide 14.

---

## Engine 3 — the capability registry

The newest layer, and the one that makes per-format capability explicit rather than implied.

- **`api/capabilities.py`** — a `Capability` enum (TEXT, OCR, STRUCTURE, TAG_TREE, LINKS,
  TABLES, FORMS, ANNOTATIONS, COLOR, FONTS, READING_ORDER, DOM, ARIA, CSS) and a per-format
  baseline, adjusted per file: a PDF with no AcroForm loses FORMS; a scanned one swaps TEXT→OCR
- **`api/assessment.py`** — `Coverage` (UNSUPPORTED < DECLARED < HEURISTIC < PARTIAL < FULL) and
  `Confidence`. Only `FULL` may certify a pass
- **`api/rule_registry.py`** — `register(rule, fmt, detector, requires, coverage, confidence,
  reason)`. Adding a criterion to a format is one call plus a detector module
- **`api/formats/{docx,xlsx,pptx,pdf,html,office}/`** — the detectors themselves

`lxml` underpins the OOXML reading on the Python side.

---

## The control plane

`api/` — 42 modules, 10 route groups.

| Library | Role |
|---|---|
| **FastAPI** 0.137 / **Starlette** / **uvicorn** | HTTP. `uvicorn app:app --port $PORT` |
| **Pydantic** 2.13 | Request/response models |
| **psycopg2-binary** | Postgres — job queue and scan state |
| **APScheduler** | Scheduled Drive sweeps |
| **httpx** | Outbound (Ollama, Langfuse, webhooks) |
| **redis** | Cross-replica scan-token durability |
| **google-api-python-client** / **google-auth** | Drive discovery, keyless ADC |
| **azure-storage-blob** / **azure-identity** | Remediated output, managed identity |
| **reportlab** | Branded PDF conformance report |
| **langfuse** | Per-rule spans; no-ops when env vars absent |

Routes: `scans`, `hitl`, `drive`, `capability`, `rubric`, `disposition`, `campaigns`, `ai`,
`system`.

---

## AI: local by default

**No commercial LLM SDK is in the dependency list.** No Anthropic, no OpenAI, no key.

`acp-ollama` runs in-cluster at 4 CPU / 8 GiB, internal ingress only:

- **`llama3.1:8b`** — prose: alt-text drafts, link-text rewrites, compliance-digest narrative
- **`moondream`** — vision: page-render descriptions, PDF reading-order proposals

Governed by ADR 0019 (provider gateway) and ADR 0022 (GPU vision, RunPod serverless for burst).
Every call is traced to Langfuse per rule.

**The standing rule that shapes the whole product:** anything with a model in the decision path
caps at *drafted-then-approved*. ACP will not certify a pass on a generated judgement. That is
why the capability grid has a remediation axis at all.

---

## One file, end to end

```
Drive discovery ──► fingerprint ──► enqueue (Postgres) ──► worker claims
                                                              │
                    ┌─────────────────────────────────────────┤
                    ▼                    ▼                    ▼
              .NET analyser        worker-python        api/formats
              (docx/xlsx/pptx)        (pdf)            (html, cross-format)
                    └─────────────────────┬───────────────────┘
                                          ▼
                                    findings + outcome
                                  PASS │ FAIL │ REVIEW
                                          │
                    ┌─────────────────────┴─────────────────┐
                    ▼                                       ▼
             deterministic fix                      HITL review card
          (written, then re-scanned)          (drafted value, human approves)
                    └───────────────┬───────────────────────┘
                                    ▼
                       remediated file ──► Blob (managed identity)
                       + before/after evidence ──► conformance report
```

Discovery and assessment are **separate phases** (ADR 0020) — discovery is cheap and rescannable,
assessment is expensive and idempotent.

---

## The honesty bar

The design constraint that costs the most and matters the most: **ACP will not report a pass it
cannot evidence.**

- **Three outcomes, not two.** `PASS`, `FAIL`, `REVIEW`. `REVIEW` is not a weak fail — it is
  "a person must decide", and it is structurally enforced. `store.REVIEW_ASSESS_FORMATS` blocks
  a PASS on any (rule, format) whose detector cannot certify one
- **Coverage gates certification.** Only `Coverage.FULL` may certify. A `PARTIAL` detector can
  fail a file but never pass it
- **Fixes are verified, not assumed.** Every deterministic fix re-scans the output and credits
  the criterion only if the finding is gone (ADR 0009)
- **Caps are declared.** A detector that truncates says so (`_cap_note`) rather than reporting a
  clean bill on a partial read (ADR 0026)

On 2026-07-29 this bar caught a real regression: the PDF contrast fixer assumed a white page and
was rewriting compliant dark-theme documents from 21:1 to 3.66:1 — creating the failure it
claimed to fix. A fixture found it; reading the diff would not have.

---

## The WCAG capability matrix

A public, per-cell statement of what ACP can do — 20 criteria × 4 formats × 2 axes.

- **Assessment:** A4 Fully Assessed · A3 Potential Issue · A2 Human Assessment Required · N/A
- **Remediation:** R4 Automatically Fixed · R3 AI Generated Fix · R2 Guided · R1 None · N/A

Each cell carries a **rule-inherent ceiling** — the best any tool could do, distinct from what
ACP has built. Cells move on observed detector runs, never on a reading of a diff.

Kept in step by `repository_dispatch` from acp → wcag-matrix on every push to `main`:
`acp-progress-log` (a curated changelog entry) and `acp-capability-change` (re-derive the
ceiling and open a PR for any cell claiming more than the code supports).

---

## Build and deploy

```
dotnet build spike/dotnet/AcpScan.Cli -c Release     # analyser → bin/Release/net10.0
cp -R $ACP_PDF_ENGINE_SRC deploy/public/vendor/       # vendor the PDF engine
az acr build -r mdkaccessibilityacr -t acp-app:<sha>-<ts> -f deploy/public/Dockerfile .
az containerapp update -n acp-app    --image <image>   # image only — env/secrets survive
az containerapp update -n acp-worker --image <image>   # both, or the fixes ship nowhere
```

Version is CalVer (`2026.7.29.2`) baked in as a build arg and surfaced at `/healthz`.
`/readyz` reports worker-tier heartbeat age and PDF-engine availability separately, so an
outage is visible *before* a scan fails on it.

---

## Where it is weak

Named deliberately — every one of these is real as of 2026-07-29.

- **The deploy is manual.** Every image in the registry was built from a laptop
  (`runType: QuickRun`, `sourceTrigger: null`). There is no pipeline. Until today, production
  ran a commit that did not exist in git history
- **`worker-python` is vendored, not versioned.** It lives outside this repo and is copied in at
  build time. If that source is missing, the build fails at `COPY`
- **The PDF engine is loaded at runtime** from `ACP_PDF_ENGINE`. Absent, PDF analysis degrades
  to a reported error per file — correct, but a deploy-time check would be better
- **`acp-ollama` is a single replica with no scale-to-zero.** 4 CPU / 8 GiB always on, and a
  cold model load costs tens of seconds
- **Concurrency discipline is documented, not enforced.** `CLAUDE.md` carries six hard-won
  rules; nothing mechanically prevents breaking them

The first is the one to fix. Everything else is a known cost with a known shape.
