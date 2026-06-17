# acp — Accessibility Compliance Platform

A standalone, MDK-based platform that connects to enterprise content stores
(Google Drive, SharePoint/OneDrive), inventories them, and **scores documents
against a structured WCAG rubric** — read-only, secure, deployable into the
customer's own cloud.

> **Status:** MVP vertical slice **built and demo-ready** — sign in → connect
> Google Drive → scan → live progress → score against a versioned WCAG rubric →
> inventory → knowledge graph → PDF report. Read-only only; remediation, AI, and
> write-back are deferred. Engine reuse is **gated on a license agreement** with
> devSEAL (see ADR 0001, decision D1).

## Run the MVP locally

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

- **Substrate:** MDK (runtime, Temporal, `StorageProvider`, observability,
  deploy, OAuth, secrets) — consumed as a dependency, *not* extended.
- **Orchestration:** Temporal — `Discover → Classify → Analyze (fan-out) → Score`.
- **Engines:** Office (.NET) + HTML/PDF (Python) as polyglot Temporal **activity
  workers**, behind the versioned `A11yIssue` contract.
- **Security:** read-only scopes · ephemeral document copies (never persisted) ·
  zero third-party LLM egress · per-customer single-tenant deploy · Postgres RLS.

## Docs

- [ADR 0001 — read-only assessment spine on MDK](docs/adr/0001-read-only-assessment-spine-on-mdk.md)
- [MVP build plan (lean first cut)](docs/mvp-build-plan.md)

## Provenance note

The `~/projects/_review-digital-accessibility` checkout (devSEAL "Digital A11y")
is a **read-only diligence clone**, kept outside this repo. No customer code is
vendored here until IP rights are secured in writing.
