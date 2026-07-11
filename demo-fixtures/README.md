# Accessibility demo fixtures — Word, Excel, PDF, PowerPoint

Deliberately-broken business documents that seed **one instance of every in-scope WCAG
failure ACP can action** on that format. Scanning them, then running remediation, walks a
live audience through all three remediation lanes and drives the file from many findings to a
clean certificate — the proof behind "100% actioned on Word and Excel" (and broad coverage on
PDF and PowerPoint).

| File | In-scope criteria that fire on scan |
|------|-------------------------------------|
| `word-accessibility-demo.docx` | 1.1.1, 1.3.1, 1.3.3, 1.4.3, 1.4.5, 1.4.8, 2.4.2, 2.4.6, 2.4.9, 3.1.1, 3.1.2, 3.1.5, 3.3.2 |
| `excel-accessibility-demo.xlsx` | 1.1.1, 1.3.1, 1.3.2, 1.3.3, 1.4.3, 1.4.5, 1.4.6, 2.4.2, 3.1.1, 3.1.2, 3.1.5 |
| `pdf-accessibility-demo.pdf` | 1.3.1, 1.3.3, 1.4.3, 1.4.5, 1.4.6, 1.4.9, 2.4.1, 2.4.2, 3.1.1, 3.1.2 — *untagged*, so 1.1.1 (image alt) & 3.1.1 tagging route to human, honest for the format |
| `powerpoint-accessibility-demo.pptx` | 1.1.1, 1.3.3, 1.4.5, 1.4.9, 2.4.2, 2.4.4, 2.4.6, 2.4.9, 3.1.2, 3.1.5 |

## The three lanes the demo shows

- **Auto** — cleared deterministically on re-scan, no human touch: document title (2.4.2),
  language (3.1.1), heading outline/skip (2.4.6 + 1.3.1 pseudo-heading), table headers
  (1.3.1), low-contrast text (1.4.3 / 1.4.6), hidden content (1.3.2), form-field labels
  (3.3.2). *(8 fixes clear on the docx, 5 on the xlsx.)*
- **Proposed** — a prefilled one-click HITL card the reviewer approves: image alt text
  (1.1.1), **images-of-text OCR (1.4.5)**, language-of-parts (3.1.2), sensory rewrite (1.3.3).
- **Guided** — surfaced with guidance: reading level (3.1.5), ambiguous link purpose (2.4.9).

## Regenerate

```
python scripts/gen_demo_fixtures.py demo-fixtures
```

The generator is self-contained (python-docx / openpyxl / PIL). `tests/test_demo_fixtures.py`
scans the freshly-generated files with the real pipeline and fails if any expected finding
stops firing, so the fixtures can't silently drift out of sync with the detectors.

> Note: 2.4.10 (Section Headings) is out of scope for the docx fixture on purpose — it only
> fires on a document with *no* headings, which is mutually exclusive with the 2.4.6 heading
> skip a realistic multi-section document exhibits.
