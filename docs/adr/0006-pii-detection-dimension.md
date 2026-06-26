# ADR 0006 — Sensitive-data (PII) Detection Dimension

**Status:** ACCEPTED
**Date:** 2026-06-26
**Authors:** ACP team

---

## Context

ACP scans documents for **WCAG accessibility** problems. "PII" appears in the
product today only as a **simulated tag** in the demo UI (`frontend/src/sim.js`,
`Discover.jsx`, `ChatWidget.jsx`) used for risk-framing — the real scan engines
(HTML/Office/PDF) never look at document *content* for sensitive data.

Customers governing a document estate care about a second axis of risk:
**personally-identifiable / sensitive information** (SSNs, payment-card numbers,
emails, phone numbers) sitting in shared files. That is orthogonal to whether a
document is *accessible* — a perfectly accessible PDF can still leak 200 SSNs.

We want to **detect** sensitive data during the same scan, so a single pass over
the estate reports both "is it accessible?" and "does it expose sensitive data?"

## Decision

Add a **PII detection dimension** that runs alongside (not inside) the
accessibility engines, behind a small module seam — mirroring how the WCAG
engines are deterministic and in-repo.

### Where it runs

The scanner already downloads each file to a temp dir and hands it to the
right accessibility engine. PII detection hooks the **same loop**: after the
accessibility engine returns, we extract the document's text and run the
detectors. The temp dir is still wiped at scan end — **documents are never
retained** (unchanged).

### Contract

```python
# api/pii.py — deterministic, no new shipped dependency
def extract_text(path: Path) -> str          # html→lxml, ooxml→zip+strip, pdf→pdfplumber, text→read
def detect_text(text: str) -> list[Finding]  # validated detectors over extracted text
def detect_file(path: Path) -> dict           # {types, total, severity, findings[]}
```

Detectors are **deterministic + validated**, consistent with ACP's "deterministic
control path" philosophy — no AI, no probabilistic NER in the shipped path:

| Type | Detector | Validation | Severity |
|------|----------|-----------|----------|
| `ssn` | `\d{3}-\d{2}-\d{4}` | reject invalid area/group/serial (000/666/9xx, 00, 0000) | critical |
| `credit_card` | 13–19 digit runs | **Luhn** checksum | critical |
| `email` | RFC-ish local@domain.tld | — | moderate |
| `phone` | NANP `(NNN) NNN-NNNN` etc. | — | moderate |
| `ip` | dotted-quad | each octet 0–255 | low |

(Named-entity detection — person names, addresses — is **out of scope** for the
shipped path. Microsoft Presidio is noted as an opt-in future extra in an
`pyproject` group, not a default dependency, per the minimal-deps posture.)

### Privacy: masked-only storage

We must not turn the compliance database into a **second copy of everyone's
SSNs**. So:

- `detect_*` returns **masked** samples only — `•••-••-1234`, `•••• •••• •••• 1111`,
  `j•••@example.com`. Raw matches never leave the function.
- The new `pii_findings` table stores `(scan_id, file, pii_type, label, count,
  severity, samples)` where `samples` is a JSON array of **masked** strings.
- Langfuse spans/labels carry **counts and masked samples**, never raw values.

### Storage

```sql
CREATE TABLE pii_findings (
  scan_id TEXT, file TEXT, pii_type TEXT, label TEXT,
  count INT, severity TEXT, samples TEXT,   -- samples = JSON array of MASKED strings
  PRIMARY KEY (scan_id, file, pii_type)
)
```

Persisted in `save_scan()` from `report.files[].pii`, the same transaction as the
accessibility results — one scan, two dimensions, one write.

### Observability

- **Langfuse:** one child span per document with sensitive data —
  `🔒 Sensitive data — 3 SSNs, 2 cards` at `WARNING` (`ERROR` if any critical),
  plus a `contains-sensitive-data` signal in the trace summary.
- **Grafana:** "Documents containing sensitive data" stat + "Sensitive data by
  type" breakdown, from `pii_findings`.

## Consequences

- **+** A single scan now reports two independent risk axes; no extra pass over
  the estate, no new infra, no new shipped dependency (lxml/pdfplumber/zipfile
  already present).
- **+** Synthetic-PII test documents in the corpus now exercise a *real* detector
  end-to-end (the original ask).
- **−** Regex/Luhn detection has the usual false-positive/negative profile of
  deterministic DLP; we accept this for v1 and flag NER (Presidio) as a future
  opt-in. False positives are visible (masked sample shown) so a reviewer can
  dismiss them.
- **−** One more table + one more thing to keep out of the clear: enforced by the
  masked-only contract in `api/pii.py` and covered by tests.

## Alternatives considered

- **Microsoft Presidio** as the shipped engine — richer (NER for names/addresses)
  but pulls spaCy + a model (~hundreds of MB), against the minimal-deps posture
  and the 1 GiB demo-container constraint. Deferred to an opt-in extra.
- **Detect inside each accessibility engine** — couples two unrelated concerns and
  would need the change made in three engines (incl. the vendored .NET/PDF ones).
  Rejected in favor of a single format-agnostic text pass in `api/pii.py`.
