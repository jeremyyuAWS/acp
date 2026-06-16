# acp — Accessibility Compliance Platform

A standalone, MDK-based platform that connects to enterprise content stores
(Google Drive, SharePoint/OneDrive), inventories them, and **scores documents
against a structured WCAG rubric** — read-only, secure, deployable into the
customer's own cloud.

> **Status:** architecture/diligence phase. MVP is **read-only assessment**
> (connect → scan → inventory → score). Remediation, AI, and write-back are
> deferred. Engine reuse is **gated on a license agreement** with devSEAL
> (see ADR 0001, decision D1).

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
