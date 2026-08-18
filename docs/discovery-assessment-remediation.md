# Discovery, Assessment, Remediation — three denominators, never one percentage

> We find the entire content estate, then identify what ACP can act on today.

This is the product model behind ACP's estate view. Its central rule: **discovery, assessment, and
remediation are three different denominators.** Reporting them as one percentage is how analytics
mislead — "40% assessed" gets read as "60% failed" when the truth is that most of the other 60% is
a format ACP does not yet cover. So each rate is measured against the denominator that is actually
true for it, and every discovered file stays visible with a clear capability status.

The one reading that must never happen: **unsupported must never read as "passed."** Unsupported
means *not evaluated*, not accessible.

---

## The three denominators

| Denominator | Meaning | Source of truth |
|-------------|---------|-----------------|
| **Discovered** | Every file ACP can inventory, regardless of format | `scanner._search_drive` lists the whole drive (`trashed=false`, no MIME filter) |
| **Assessment eligible** | Files with at least one applicable accessibility test | `estate_inventory` status `assessable` (Office + PDF + HTML) |
| **Remediation eligible** | Files ACP can deterministically or guided-remediate | `remediation_capability.REMEDIATION` — a fixer exists for at least one criterion |

Discovery is the widest set; each subsequent denominator is a strict subset. The gap between them
is not failure — it is the honest edge of what ACP covers today, and the roadmap for what it covers
next.

---

## Capability status — a per-file answer

Every discovered file carries exactly one status (`api/estate_inventory.py`). Only `assessable`
files enter the assessment and remediation lanes; the rest are inventoried with metadata.

| Status | What it means | Examples |
|--------|---------------|----------|
| `assessable` | A supported format with at least one applicable WCAG test | `.docx` `.pdf` `.pptx` `.xlsx` `.html`, and Google-native Docs/Sheets/Slides (export to Office) |
| `metadata_only` | Inventoried, but no accessibility test exists | images, audio, video |
| `unsupported` | A format ACP does not parse for accessibility at all | `.txt` `.csv` `.zip`, legacy `.doc/.ppt/.xls` |
| `excluded` | ACP's own output, or policy-excluded — not the user's content | files carrying ACP's provenance stamp |

The classifier is MIME-first, extension-fallback: a Google-native Doc (no filename suffix) and an
upload Drive typed only as `application/octet-stream` both resolve correctly.

---

## The coverage funnel

One estate, nine stages. The funnel never merges "unsupported" with "passed" — an unsupported file
leaves at stage 3, it does not pass through it.

1. **All files discovered** — the whole estate, any format
2. **Readable & inventoried** — minus access-blocked / unreadable
3. **Assessment eligible** — the `assessable` subset
4. **Assessed** — eligible files that have been scanned
5. **Issues detected** — files with at least one finding
6. **Remediation eligible** — files with at least one auto/guided fix available
7. **Remediated** — deterministic + approved guided fixes applied
8. **Human review required** — guided-awaiting-approval + human-only findings
9. **Published / ready for release**

Stages 1–3 come from `report.scope.inventory` (discovery); 4–9 come from the scan/remediation
records.

---

## Coverage matrix — by format and capability

More honest than one overall number. "Assessable" and "Remediable" are read from
`remediation_capability` over the 20 core WCAG A/AA criteria (`assessment_table()` /
`remediation_table()`); volumes come from the estate inventory.

| Format | Assessable (of 20) | Remediable (of 20) | Notes |
|--------|:------------------:|:------------------:|-------|
| DOCX | 17 | 14 | deepest coverage |
| PPTX | 18 | 11 | |
| PDF | 16 | 12 | AcroForm-scoped for some criteria |
| XLSX | 15 | 10 | |
| HTML | 18 | 14 | |
| Images | 0 | 0 | metadata-only |
| Video / audio | 0 | 0 | metadata-only |
| Other | 0 | 0 | unsupported |

`Assessable` = deterministic (🟢) + review-lane (🟡) criteria. `Remediable` = deterministic-fix (⚡) +
guided-fix (🤖) criteria. The per-format numbers are the single source of truth for the
assessment/remediation denominators and are guarded (`tests/test_assess_coverage_contract_sync.py`,
`docs/assessment-capability-matrix.md`).

---

## How discovery works (and what scale it holds)

- **Whole-estate listing.** `_search_drive` asks Drive only for `trashed=false` — no `mimeType`
  clause — because Drive's search index lags badly for freshly-uploaded files (proven live: an
  unfiltered listing returned 60 documents while the same query with a MIME filter returned 2, in
  the same second). The scannable filter is applied in Python, so a just-uploaded file appears at
  once.
- **Scanning stays scannable-only.** The inventory counts every file; assessment and remediation
  still run only on the scannable subset. Discovery changes what we **count**, never what we
  **scan**.
- **The ceiling is configurable.** `ACP_FANOUT_MAX_FILES` (default 50,000) caps a scan; both the
  production fan-out (`handlers._scan_discover`) and the local `run_scan` path honour it.
- **Truncation is never silent.** When a listing hits its cap, `report.scope.inventory.truncated`
  is set, so an estate larger than the ceiling is reported as a **floor**, never as a complete
  count.
- **Dedup by identity.** A file with several parents, or on a Shared Drive many people can see, is
  surfaced multiple times in one listing; a Drive file id is the document's identity, so N sightings
  collapse to one document.

---

## Scan-setup UX — two separate controls

Discovery scope and assessment policy are distinct choices, presented separately:

- **Discovery scope** — entire connected drive / selected folders / *include all file formats*
  (default on).
- **Assessment policy** — which formats ACP should assess, which WCAG criteria, with an estimated
  eligible-file count shown before starting.

And stated explicitly at setup:

> All files will be inventoried. Assessment and remediation will be applied only where ACP has a
> validated method.

---

## Status and roadmap

**Shipped**
- Whole-estate inventory + capability status per file (`estate_inventory`, #290).
- `run_scan` honours `FANOUT_MAX_FILES`; inventory flags truncation (#292).
- 30k-file scale corpus that doubles as a scale test of the classifier (#293).
- Labeled `complex_corpus` embedded in the estate for accuracy-at-scale (#294).
- Truncation flag and shared-drive dedup proven end-to-end at scale (#295, #296).

**Next**
- Persist per-file inventory rows and expose an API; wire the dashboard funnel/composition/matrix to
  `report.scope.inventory`.
- Metadata enrichment (owner / size / sharing) via a small `DRIVE_FIELDS` expansion — for the
  department and prioritized-risk views.
- Folder-scan and SharePoint/OneDrive parity for the inventory.
- Prioritized-risk view: public + high-reach files first.

---

## The design principle, restated

Discovery coverage, assessment coverage, and remediation coverage are three different denominators.
If ACP reports them as one percentage, the analytics are misleading. Keep them separate, keep every
file visible with an honest status, and let "unsupported" mean *not evaluated* — never *passed*.
