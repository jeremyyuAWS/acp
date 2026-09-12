# Remediation reliability validation — September 11, 2026

## Publishing and proposal integrity

- Timeout and dead-letter assessment records retain the source modified timestamp and checksum supplied by their job inputs.
- Automatic planning freezes only eligible files. Failed, incomplete or untracked files remain excluded with explicit reasons; publication identity and freshness checks are preserved.
- Canonical, active legacy remediation jobs retain immutable proposal versions independently of managed AI spending permissions. Forged identities, cancelled executions and replacement proposals without authenticated producer context do not reuse valid version links.
- Optional assessment vision has a per-file deadline (default 240 seconds, at most 40% of the outer file timeout), and provider timeouts are reduced to its remaining time. This does not limit the separate document-wide remediation workflow.
- Remote vision API admission is bounded independently of local GPU inference; GPU saturation no longer consumes cloud fallback slots. Existing permission and budget gates remain authoritative.

The historic 147-file scan is absent from production file and inventory storage. It cannot be repaired or verified from those missing records. No historical source timestamp was guessed and no production patient documents were modified for these tests.

## Live native PDF comparison

Synthetic PDFs only; full original PDF bytes were sent to each provider. These calls exercise provider transport and the real PDF field-name writer, not an authenticated production publishing run.

Providers: OpenAI `gpt-4.1-2025-04-14`, Anthropic `claude-sonnet-5`.

| Case | OpenAI | Anthropic |
|---|---|---|
| Two-page form | Both names matched visible labels | Both names matched visible labels |
| Duplicate telephone labels in different sections | Both names included correct section | Both names included correct section |
| Unlabeled field, initial instruction | Declined to guess | Incorrectly copied existing field value |
| Unlabeled field, explicit value-versus-label instruction | Declined to guess | Declined to guess |

The refined instruction is now part of the application's document-wide request. In the ambiguous fixture, Anthropic named the separately labeled field; OpenAI conservatively declined both. Abstention is safer than fabricating a repair.

For all six refined outputs, field values remained unchanged and every rendered page was pixel-identical to its original at 72 DPI. Reopening the files confirmed the actual saved accessible names, including the two-page locator mapping. A rendered section fixture was visually inspected.

This is evidence for field naming, section context and abstention only. It does not prove automatic remediation of all 17 criteria, semantic correctness of every recommendation, or full WCAG conformance.

## Application journeys

153 focused tests passed across document-wide response parsing, native transport/fallback, approved-value writers, durable artifact/readiness progression, PowerPoint fallback journeys and offline audit guidance for DOCX/XLSX/PPTX/PDF. Provider HTTP and storage use controlled doubles in these application journeys. The live PDF comparison above tests real provider responses separately.

Frontend DOM tests confirm that automatic intent excludes blocked files while their reasons remain visible. Production end-to-end publication with a real connected destination remains a separate check; local journey tests must not be reported as proof of that external write.
