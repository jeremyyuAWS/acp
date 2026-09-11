# Full PDF context for AI remediation

The remediation plan offers **Document context** (existing extracted text/images) and **Full PDF — advanced preview**. Full PDF requires document-wide Cloud AI and a positive run spending limit. The accepted plan freezes this selection; existing accepted runs with no new field keep extracted context. Word files in a mixed run retain their existing image/text path.

The full PDF is the exact current saved candidate, including deterministic fixes already made. ACP sends it inline to the configured supported provider with selected assessment findings and stable target identities. OpenAI uses Responses file input; Anthropic uses a PDF document block. No separate uploaded-file resource is created. No extra page images are uploaded alongside the PDF.

## Repair scope

Only existing tagged-image descriptions (WCAG 1.1.1) and form-field accessible names (4.1.2) are writable in this PDF preview. Other selected findings are advisory context, not new write permissions. Multiple figures require explicit, non-overlapping layout bounds with supported page geometry; ambiguous targets stay deferred. Untagged content, heading/tag-tree repairs, complex tables, general reading-order changes and scanned-document reconstruction remain outside this preview.

AI output is a structured proposal, never a replacement binary. Existing approval choices determine application. Exact approved-value readback and content/form-state preservation run before saved-copy delivery. Applied semantic changes remain unverified until the required review is recorded.

## Limits and accounting

- Input must match the current artifact SHA-256, be readable and unencrypted, and fit 20 MiB / 100 pages.
- Current manifest limits remain 60,000 text characters, 20 supported findings and eight visual evidence targets. Model limits can be stricter.
- The configured primary and at most one fallback remain authoritative; this feature does not invent model names, prices, or a new provider selection.
- The existing durable spending reservation covers the configured input/output ceiling. Native request admission also checks extracted text, prompt, page allowance and output before transport.
- Measured usage is retained. Missing/unknown accounting or uncertain transport does not become a free retry. Paid quality evaluation was not performed during implementation.

## Validation and next evaluation

Offline tests exercise both provider request formats, source identity, local/disabled consent, reservation/settlement/replay, fallback limits, missing usage, mixed Word/PDF routing, real immutable policy snapshots and exact saved/delivered PDF bytes. A corrupt-writer fixture confirms loss of existing form data prevents upload.

For quality evaluation, begin with six representative PDFs and compare current context/current model, current context/stronger configured model, and native PDF/that same stronger model. Count correct actionable proposals, unsupported requests, semantic errors, saved-file integrity, latency and cost per useful applied fix. Estimate tokens and agree a spend cap before executing live comparisons. The 18-request design is a proposed benchmark, not a measured quality claim.

Provider contracts: [OpenAI file input](https://developers.openai.com/api/docs/guides/file-inputs) and [Anthropic PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support).
