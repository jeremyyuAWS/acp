# Reading the certification report — a guide for auditors

This explains the **per-scan certification report** ACP generates for a customer's documents
(`api/report.py`, one PDF per scan). It is a different artifact from
[`conformance-report.md`](conformance-report.md), which is ACP's own VPAT for the platform UI.

The guiding principle is **negative assurance**: the report states plainly what it checked, what it
changed, what it re-verified — and, just as prominently, what it did **not** evaluate. Every number
is a real, recomputable count or a ratio shown with its basis; where a figure cannot be derived
honestly it is omitted rather than estimated (ADR 0016). This guide names each section and what you
can and cannot conclude from it.

## The one thing not to misread

**A score of 100 does not mean "WCAG 2.1 AA conformant."** It means *no blocking findings remained
among the criteria ACP actually evaluated for that document's format*. ACP has an automated
validator for a **subset** of the 87 AA success criteria; many criteria require human or
assistive-technology judgement and are routed to review, never asserted here. The report says this
in several places by design — the sections below are built around making that boundary impossible
to miss.

## What each section lets you conclude

| Section | What it proves | What it does **not** prove |
|---|---|---|
| **What ACP checked, fixed and verified** (decision block) | The certifiable/open counts and a recomputable SHA-256 content digest — the report is tamper-evident. | It is a digest, **not** a digital signature: no identity is bound to it. |
| **Certification summary band** | Headline counts: documents with no blocking findings, average score, documents with open findings, documents that could not be analysed. | The percentage is over *evaluated* criteria, not all of WCAG. |
| **Scope & methodology** | The standard targeted, the documents in scope, and the method (deterministic engine + AI-assisted review of semantic criteria). | — |
| **Compliance velocity** | Movement since this estate's previous scan (improved / regressed / new / removed). | Renders only when a previous scan exists. |
| **File inventory** | Per document: status, score, findings, **fixed / open / human approvals**. | — |
| **What this report covers · and what it does not** (scope of assertion) | The heart of the negative assurance: how many criteria have a validator vs. the full 87; per document, evaluated / not-evaluated / by-mode; the criteria never run for a format; the file types never opened; and the whole-estate discovery funnel. | A criterion listed "not evaluated" is **not** asserted to pass *or* to be inapplicable — no check ran. |
| **Pass rate by WCAG principle** (POUR) | Of the criteria evaluated, the share that passed, grouped Perceivable / Operable / Understandable / Robust — table and bars, same numbers. | A pass rate **among evaluated checks only** — not a conformance percentage. Not-evaluated and review-only criteria are excluded. |
| **Remediation evidence appendix** | Per fix: before → after, the concrete value written, and the immutable sign-off ("what changed, and on whose authority" — reviewer and timestamp from the append-only decision log). Only re-scan-cleared fixes appear. | Proposals awaiting approval are shown separately and are **never** counted as remediated. |
| **How this result was produced** (provenance) | Method with this scan's real counts; the pipeline in order; a **reproduce** line (re-run against the stamped rubric hash → same findings); and, when a prior scan exists, a **supersedes** line. | — |
| **Human review & assurance** | Findings human-reviewed / approved / rejected (from the immutable log); the deterministic ÷ evaluated assurance ratio; and effort as fixes-cleared ÷ findings **with that basis named**. | No "% effort saved" and no "cleared ÷ attempted" — the attempted denominator is not tracked, so that ratio is omitted, not invented. |
| **How to verify this independently** | Per document format present, the mainstream tool and the checks that let you confirm the result yourself (Word / PowerPoint / Excel Accessibility Checker; Acrobat or NVDA/VoiceOver for PDF). | Generic per format — never a claim about a specific document. |
| **AI governance & provenance** | For this scan: how many AI-assisted operations ran, where they were processed (network boundary), and their cost. | — |
| **What this report is, and is not** (conformance statement) | The closing attestation: machine-generated audit evidence, not a conformance determination or a signed VPAT; a qualified reviewer should confirm AI-assisted judgements before any external attestation. | — |

## How to trust it without trusting us

Three independent checks, all supported by the report itself:

1. **Recompute the digest.** The content digest is a SHA-256 over the canonical scan result (scan
   id, rubric hash, target, per-file scores). Anyone holding the same scan can recompute it.
2. **Reproduce the findings.** Re-run the scan against the stamped rubric hash; the same inputs
   yield the same findings.
3. **Verify a document by hand.** Follow the "How to verify this independently" steps for its format
   and confirm the result in a mainstream tool or a screen reader.

If a figure you need is absent, that is deliberate: it could not be derived from real data, and the
report omits it rather than show a number an auditor would be right to distrust.
