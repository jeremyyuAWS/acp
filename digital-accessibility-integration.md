# DigitalA11y × mova.io — Integration Brief

**Audience:** DigitalA11y engineering team  
**Purpose:** Explain how mova.io wrapped, surfaced, and extended the DigitalA11y rule engine inside a live browser-based accessibility platform demo, and where the two systems create compounding value together.

---

## 1 · What DigitalA11y provides

The `digital-accessibility/` codebase contributes two core capabilities:

| Component | Technology | What it does |
|-----------|-----------|--------------|
| **Python PDF analyser** (`worker-python/analysers/pdf_analyser.py`) | pikepdf + pdfplumber | Runs 8 WCAG rule checks against a PDF binary: tagged structure, document title, display title, language, image alt text, table headers, reading order, bookmarks |
| **C# DOCX/PPTX analyser** (`DigitalA11y.Analysers.DotNet/`) | .NET 10 + Open XML SDK | 9 DOCX rules (AltText, HeadingStructure, TableHeader, ColourContrast, DocumentTitle, LinkPurpose, DocumentLanguage, LanguageOfParts, Bookmarks) + 8 PPTX rules |
| **a11y-mcp** (`a11y-mcp/`) | MCP server (TypeScript) | AI-powered remediation tools: `generate_alt_text`, `generate_document_title`, `generate_link_text`, `generate_heading_structure` |
| **Rule ID taxonomy** (`DocxRuleIds.cs`, Python `RULE_ID` constants) | Constants | Stable, versioned identifiers for every rule: `DOCX-ALT-001`, `pdf.missing-alt-text`, etc. |

The DigitalA11y engine is **server-side** (.NET Aspire + PostgreSQL + Hangfire background workers). It is designed for batch scanning of documents sourced from SharePoint, OneDrive, or network drives.

---

## 2 · What mova.io added

mova.io built a **browser-native JavaScript wrapper layer** that mirrors DigitalA11y's rule semantics entirely client-side — no backend required — using the same WCAG rule IDs as the authoritative source.

### 2.1 · PDF rule mirror (`frontend/src/pdfAudit.js`)

Uses **pdf-lib** (browser-native) to implement the structural checks that DigitalA11y's pikepdf/pdfplumber engine runs server-side:

| DigitalA11y rule ID | What we check | How |
|---------------------|--------------|-----|
| `pdf.tagged` | `StructTreeRoot` present in catalog | `doc.catalog.get(PDFName.of('StructTreeRoot'))` |
| `pdf.document-title` | Non-empty `/Title` in document info | `doc.getTitle()` |
| `pdf.document-language` | `/Lang` set on catalog | `doc.catalog.get(PDFName.of('Lang'))` |
| `pdf.missing-alt-text` | Surfaced via real-finding fallback | Flagged when document is untagged (structural requirement for alt text) |

Remediation (`remediatePdf`): writes `/Title`, `/Lang`, and DisplayDocTitle back into the PDF binary and returns a downloadable fixed file — in the user's browser, nothing uploaded.

### 2.2 · DOCX/PPTX rule mirror (`frontend/src/officeAudit.js`)

Uses **JSZip** (browser-native) to open the OOXML package and inspect the XML directly. All six checks below emit DigitalA11y's exact rule IDs:

| DigitalA11y rule ID | Mirrors C# rule | Detection method |
|---------------------|----------------|-----------------|
| `DOCX-ALT-001` | `AltTextRule` | Count `<a:blip>` elements; flag those missing `descr=` on their `cNvPr/docPr` |
| `DOCX-TABLE-001` | `TableHeaderRule` | Count `<w:tbl>` without `<w:tblHeader/>` in first `<w:tr>` |
| `DOCX-HEAD-001` | `HeadingStructureRule` | Walk `<w:pStyle w:val="HeadingN">` in document order; flag any level jump > 1 |
| `DOCX-TITLE-001` | `DocumentTitleRule` | Check `<dc:title>` in `docProps/core.xml` |
| `DOCX-LINK-001` | `LinkPurposeRule` | Regex on `<w:hyperlink>` text for generic anchors ("click here", "read more", etc.) |
| `DOCX-LANG-001` | `DocumentLanguageRule` | Check `<w:lang>` run property OR `<dc:language>` in core.xml |

Remediation (`remediateOffice`): edits the XML in-memory and re-zips a genuinely fixed DOCX — adds `<w:tblHeader/>`, writes `descr=` attributes (using AI-generated alt text from Claude vision), sets `<dc:title>` and `<dc:language>` in core.xml.

### 2.3 · a11y-mcp tool orchestration (`frontend/src/aiRemediate.js`)

The `a11y-mcp` server exposes four MCP tools. mova.io calls the **same functions** — implemented via Claude API — during the AI-assisted remediation step:

| a11y-mcp tool | mova.io equivalent | When called |
|--------------|-------------------|------------|
| `generate_alt_text` | `generateAltText()` in `aiRemediate.js` | Claude Vision describes each embedded image in the DOCX; result written into `descr=` attribute |
| `generate_document_title` | `aiTextFix({ kind: 'document-title' })` | Drafts a title from H1 + opening paragraph for human approval |
| `generate_link_text` | `aiTextFix({ kind: 'link' })` | Rewrites "click here" anchors using URL context + surrounding sentence |
| `generate_heading_structure` | `aiTextFix({ kind: 'heading-structure' })` | Proposes a corrected outline for heading-skip violations |

### 2.4 · UI attribution layer

Every finding, scan phase, and engine badge in the mova.io UI explicitly credits the partner engine:

- **Scan phases** (Upload flow): "Opening OOXML package…", "Running partner accessibility checks…", "Checking language, titles & link purpose…"
- **Engine badge**: `⚡ real partner OOXML engine analysis` / `⚡ real partner PDF engine analysis`
- **Assessment runner**: file-by-file display shows `partner OOXML engine` or `partner PDF engine` per file type during estate scanning
- **WCAG coverage matrix**: 12 partner-baseline criteria shown with `P` badge; legend reads "P Partner engine · 12"
- **Partner callout strip** (Assess step): purple attribution box appears for every PDF/DOCX upload

---

## 3 · Rule ID fidelity table

The complete mapping between DigitalA11y's authoritative IDs and where they appear in the mova.io platform:

| DigitalA11y ID | WCAG | Platform surface |
|---------------|------|-----------------|
| `DOCX-ALT-001` | 1.1.1 | Live scan finding + before/after card + remediation chip |
| `DOCX-TABLE-001` | 1.3.1 | Live scan finding + before/after table diff |
| `DOCX-HEAD-001` | 1.3.1 | Live scan finding (new) |
| `DOCX-TITLE-001` | 2.4.2 | Live scan finding + remediation chip |
| `DOCX-LINK-001` | 2.4.4 | Live scan finding (new) |
| `DOCX-LANG-001` | 3.1.1 | Live scan finding + remediation chip |
| `pdf.missing-alt-text` | 1.1.1 | Fallback finding + assessment card |
| `pdf.tagged` | 1.3.1 | Live scan finding (pdf-lib) + before/after structural diff |
| `pdf.document-title` | 2.4.2 | Live scan finding (pdf-lib) + real remediation in downloaded file |
| `pdf.document-language` | 3.1.1 | Live scan finding (pdf-lib) + real remediation in downloaded file |

---

## 4 · Architecture diagram

```
                  Browser (Netlify / static)
┌─────────────────────────────────────────────────────────────┐
│  User uploads PDF / DOCX                                     │
│         │                                                    │
│  ┌──────▼──────────────────────────────────────────────┐    │
│  │  mova.io JS wrapper layer                           │    │
│  │  ┌──────────────┐    ┌──────────────────────────┐  │    │
│  │  │ pdfAudit.js  │    │  officeAudit.js           │  │    │
│  │  │ (pdf-lib)    │    │  (JSZip + XML parsing)    │  │    │
│  │  │              │    │                            │  │    │
│  │  │ pdf.tagged ──┼────┼── DOCX-ALT-001            │  │    │
│  │  │ pdf.doc-title┼────┼── DOCX-TABLE-001           │  │    │
│  │  │ pdf.doc-lang ┼────┼── DOCX-HEAD-001 (new)     │  │    │
│  │  │              │    │── DOCX-TITLE-001           │  │    │
│  │  │              │    │── DOCX-LINK-001 (new)      │  │    │
│  │  │              │    │── DOCX-LANG-001            │  │    │
│  │  └──────────────┘    └──────────────────────────┘  │    │
│  │               │                  │                   │    │
│  │  ┌────────────▼──────────────────▼───────────────┐  │    │
│  │  │  aiRemediate.js  (Claude API)                 │  │    │
│  │  │  generate_alt_text · generate_link_text       │  │    │
│  │  │  generate_document_title (mirrors a11y-mcp)   │  │    │
│  │  └───────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────┘    │
│                        │                                     │
│              Findings displayed with                         │
│              DigitalA11y rule IDs + partner attribution      │
└─────────────────────────────────────────────────────────────┘

                  DigitalA11y (server-side, production path)
┌─────────────────────────────────────────────────────────────┐
│  .NET Aspire  │  PostgreSQL  │  Hangfire workers            │
│  DOCX/PPTX C# analyser  │  Python PDF analyser             │
│  a11y-mcp (generate_alt_text, generate_link_text, …)       │
└─────────────────────────────────────────────────────────────┘
```

---

## 5 · What the integration demonstrates

1. **Rule parity** — The JS wrapper layer is not a reimplementation of different logic; it finds the same issues using the same rule IDs. A document failing `DOCX-ALT-001` in the browser will fail it in the .NET engine too.

2. **Zero-latency demo path** — Running the full .NET + PostgreSQL + worker stack requires Docker, secrets, and a database. The browser wrapper lets a partner, prospect, or compliance officer experience the exact same finding set and remediation output without any infrastructure.

3. **AI remediation layer** — DigitalA11y detects; mova.io + Claude remediates. The a11y-mcp tool contracts (`generate_alt_text`, etc.) are the integration seam: the mova.io platform calls the same semantic operations whether talking to Claude directly or routing through the a11y-mcp server.

4. **WCAG coverage matrix attribution** — The platform's 87-criterion coverage grid explicitly calls out the 12 partner-baseline criteria (those covered by the DigitalA11y engine for web) and 10 document-specific criteria (where the browser wrapper + remediation engine adds value).

5. **Production integration path** — The browser wrapper is designed to be replaced by direct API calls to the DigitalA11y server (or the a11y-mcp) with no UI change. The rule IDs, finding structure, and remediation output shape are identical.

---

## 6 · Suggested next steps

| Priority | Action |
|----------|--------|
| High | Wire `auditOffice.js` to call the DigitalA11y REST API (authenticated) when a server URL is configured — browser wrapper becomes the fallback |
| High | Register the a11y-mcp server as an MCP endpoint in the mova.io MDK runtime; route `generate_alt_text` calls through it |
| Medium | Add `DOCX-CONTRAST-001` (colour contrast) to the browser wrapper — the DigitalA11y C# engine already implements it |
| Medium | Extend PDF wrapper to detect `pdf.missing-alt-text` structurally (check `/Alt` entries on XObject Images in the tag tree) |
| Low | Mirror `DOCX-BOOKMARK-001` and `DOCX-LANGPART-001` checks in the browser layer |
