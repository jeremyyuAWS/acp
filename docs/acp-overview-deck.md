# ACP — Overview deck outline (for Deva)

A ~14-slide walkthrough of what the Accessibility Compliance Platform does and how
it's built on Azure. Each slide has talking points + speaker notes. Build it in
PowerPoint/Google Slides from this; the architecture slide has a text diagram to
redraw as boxes.

---

## Slide 1 — Title
**ACP — Accessibility Compliance Platform**
Scan, score, and remediate document accessibility (WCAG 2.1) across Google Drive —
with full operational + AI observability.
- Sub-line: *mova.io · ADA Title II / WCAG 2.1 AA*
- Live: `acp-drive.mova-io.app` (hub) → the app on Azure.

---

## Slide 2 — The problem
- Organizations hold **thousands of documents** (Word, PDF, PowerPoint, Excel, HTML)
  in Drive/SharePoint that must meet **ADA Title II / WCAG 2.1**.
- Manual accessibility auditing **doesn't scale** and isn't repeatable or auditable.
- Need: **continuous, automated, evidence-backed** compliance — find issues, fix what
  can be fixed, route the rest to humans, and prove it over time.

*Speaker note:* the deadline pressure (ADA Title II) is the "why now."

---

## Slide 3 — What ACP does (the 10-step lifecycle)
A single workflow, tab by tab:
1–3. **Discover** — Inventory → Classify (by department/exposure/risk) → Actions
4–5. **Assess** — scan every document, score 0–100 against the WCAG rubric
6–8. **Remediate** — auto-fix what's deterministic, AI-draft semantic fixes, route the rest to human review (HITL)
9. **Publish** — certify documents that pass
10. **Monitor** — watch for drift, re-scan, alert

*Speaker note:* "certifiable" = full, trustworthy run with score ≥ threshold.

---

## Slide 4 — User flow (what Deva will click)
1. **Sign in with Google** → 2. **Connect Drive** (read-only) → 3. **Scan** (Durable mode) →
4. **Review findings** (Assess) → 5. **Remediate** → 6. **Certify** (Publish) → 7. **Monitor**.
- Observability alongside: **Grafana** (dashboards) + **Langfuse** (per-scan detail).

*Speaker note:* emphasize it's their own Drive, read-only; fixed copies are written to a
`Remediated/` folder, originals untouched.

---

## Slide 5 — Architecture on Azure (diagram)
Everything runs as **Azure Container Apps** in resource group `mdk-accessibility`
(env `mdk-accessibility-env`), images from ACR `mdkaccessibilityacr`.

```
                         ┌──────────────────────────────────────┐
   Browser (SPA) ─────▶  │  acp-app  (Container App, 1–3 replicas)│
   Google sign-in        │  ┌────────────┐   ┌──────────────────┐│
                         │  │ FastAPI API│   │ Job workers      ││
                         │  │ + serves   │   │ (JobWorker pool, ││
                         │  │  React SPA │   │  live-scale 0–16) ││
                         │  └─────┬──────┘   └─────┬────────────┘│
                         └────────┼────────────────┼─────────────┘
              per-scan tokens     │  durable job queue + all data │  AI calls
                 (TTL 1h)         ▼                ▼               ▼
            ┌───────────┐   ┌──────────────┐  ┌──────────┐  ┌───────────┐
            │ acp-redis │   │  PostgreSQL  │  │ Engines: │  │acp-ollama │
            │ (tokens)  │   │ (system of   │  │ HTML/lxml│  │(llama3.2, │
            └───────────┘   │  record)     │  │ Office/  │  │ scale-to- │
                            └──┬────────┬──┘  │ .NET CLI │  │  zero)    │
                               │        │     │ PDF/py   │  └───────────┘
                     reads ◀───┘        └───▶ reads      └──────────────┘
                  ┌──────────────┐   ┌─────────────────┐
                  │ acp-grafana  │   │  acp-langfuse   │
                  │ (dashboards) │   │ (LLM/agent obs) │
                  └──────────────┘   └─────────────────┘
```

*Speaker note:* one app container does control + execution; Postgres is the backbone
that everything else reads from.

---

## Slide 6 — The scan pipeline: durable fan-out (ADR 0007)
A scan is decomposed into durable jobs, not one big job:
- **`scan_discover`** — lists the Drive folder (paginated, up to ~50k), creates the
  `scan_runs` row + opens the Langfuse trace, enqueues **one `scan_file` job per file**.
- **`scan_file`** (× N, in parallel) — download → analyse → score → detect PII →
  persist that file → emit its Langfuse spans → tick an atomic counter.
- **`scan_finalize`** — the job that completes the count aggregates the summary +
  closes the trace.

**Why:** memory/disk bounded (one file per job), parallel downloads, retry per file,
scales to **10K files/user**. Same machinery powers remediation.

---

## Slide 7 — Three engines, one WCAG key
| Type | Engine | Notes |
|------|--------|-------|
| **HTML** | in-repo `lxml` analyzer | deterministic |
| **Office** (docx/pptx/xlsx) | **.NET** DigitalA11y CLI | invoked per file |
| **PDF** | vendored Python worker (`pdfminer`/`pikepdf`) | |
- Every finding maps to a **WCAG 2.1 Success Criterion** (e.g. 1.1.1, 2.4.4) — the
  common key across engines, the rubric, Grafana, and Langfuse.
- **+ PII detection** (SSNs, cards, emails) as a parallel risk dimension.

---

## Slide 8 — Workers & the durable job queue
- The **job queue lives in Postgres** (`jobs` table) — durable, survives restarts.
- A **pool of JobWorker threads** runs inside `acp-app` (env `ACP_WORKERS`,
  **live-scalable 0–16** from the Monitor tab), across **1–3 replicas**.
- Each worker **atomically claims** the next job, runs it, **retries with backoff**
  on failure, and **dead-letters** after N attempts (visible + clearable in the UI).
- **Why it matters:** a 10K-file scan or a big remediation batch keeps going if a
  browser tab closes or a container restarts — nothing is lost.

*Speaker note:* this is the difference between "Durable scan" and "Quick scan" in the UI.

---

## Slide 9 — Postgres — the system of record
Stores everything that must be durable + auditable:
- `jobs` (the queue) · `scan_runs` (summaries) · `file_records` + `issue_records`
  (per-file findings) · `scan_rule_traces` (every rule × file: PASS/FAIL/SKIP) ·
  `pii_findings` (masked) · `hitl_queue` · `decision_log` (audit) · `inventory`.
- **Also backs Grafana and Langfuse** (their own schemas in the same Postgres).
- Per-scan Drive tokens are **NOT** here — they live in **Redis** (transient, TTL 1h).

---

## Slide 10 — Langfuse — per-scan, per-document observability
"**What did the agent check on each file?**"
- **One trace per scan**, attributed to the **signed-in user**.
- **One span per document** → **one child span per WCAG rule**: ✓ pass / ✗ fail
  with the SC in parentheses (e.g. *"✓ Images missing a text description (1.1.1)"*).
- **PII spans**, a plain-language summary, and a **0–100 compliance score** on the trace.
- Use it to **drill into a specific scan/document** and explain every check.

*Speaker note:* this is the "microscope." Filter by user to see one person's scans.

---

## Slide 11 — Grafana — operational & executive dashboards
"**How are we doing overall?**"
- **Compliance posture** — avg score, certifiable rate, open findings, awaiting review.
- **Trends over time** — score + scan outcomes.
- **Job queue** — depth, throughput, processing-now, stuck items.
- **WCAG-level breakdown** + the most common problems + worst documents.
- **Alerts** — e.g. compliance score below threshold → contact point.
- Reads straight from **Postgres**; **anonymous read-only** viewing is enabled.

*Speaker note:* this is the "telescope" / exec view. No login needed to view.

---

## Slide 12 — AI (Ollama) + Human-in-the-loop
- **Deterministic rules always run** (contrast, language, titles, tab order…).
- **AI drafts semantic fixes** (alt text, link labels, name/role/value) via **Ollama
  (llama3.2)** on `acp-ollama` — **scale-to-zero** to save cost (cold start on first use).
- **AI-off mode**: a hard switch — AI-dependent fixes route to the **HITL review queue**
  instead, fully deterministic.
- Humans **confirm or override** classifications and fixes; everything is logged.

---

## Slide 13 — Security & access
- **Google sign-in** (GIS) + an **email/domain allowlist** + an access-gate on every
  non-public route.
- **Test-user model** today: named Gmail users are added as Google *test users* +
  to the allowlist (restricted Drive scope; ~100-user cap until CASA verification).
- **Read-only Drive** scope for scanning; `drive.file` for writing fixed copies into
  a `Remediated/` folder (originals never modified).
- **Tokens in Redis only** (TTL 1h), **never persisted** to Postgres.

---

## Slide 14 — Status & roadmap
**Live & verified:** Drive scan (durable fan-out, 10K-file ready), assessment + scoring,
PII detection, Langfuse traces (file/WCAG/user), Grafana dashboards, durable queue.
**Pilot-stage / next:**
- Remediation **write-back** end-to-end verification.
- **Per-user data isolation** (`owner_email`) for multiple users.
- **OAuth CASA verification** for open public signup.
- Real **content-based** Classify (vs filename heuristic).

*Speaker note:* honest "what's solid vs what's in progress" — sets pilot expectations.

---

### Appendix (optional slides)
- **A1 — Live URLs:** app, hub, Grafana, Langfuse, API docs (`/docs`).
- **A2 — The Remediation program:** Batch 1 CRITICAL / Batch 2 SERIOUS (HITL) /
  Batch 3 MODERATE, by top finding severity.
- **A3 — Deploy:** Docker image → ACR → `az containerapp update`; CalVer from git.
