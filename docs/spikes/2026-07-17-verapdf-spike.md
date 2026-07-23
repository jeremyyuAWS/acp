# Spike: veraPDF as a local PDF/UA corroboration engine (ADR 0028, item A2)

**Status:** Spike complete, positive result — **re-run 2026-07-21, one conclusion corrected** (see the dated section at the end). The 4.1.2 AcroForm gap this doc originally said veraPDF "directly closes" has since been independently closed by ACP's own native code (`api/office_structure.py`'s `pdf_form_field_checks()`, shipped 2026-07-15 — two days before this spike, but not covered by the comparison below, which only tested the vendored 8-rule engine). Feeds the corroboration-engine framework in `docs/adr-0028-corroboration-engines` (branch, not yet merged) — this doc is written standalone so it can be folded in as an appendix without colliding with that branch's active work.

**Question:** Can veraPDF (open-source PDF/UA validator) accelerate ACP's PDF coverage without compromising the local-only, deterministic architecture ACP already commits to?

## License posture — resolved, no ambiguity

veraPDF is dual-licensed **GPLv3+ / MPLv2+** — an "either/or" choice, not a stack. ACP can adopt it under **MPLv2 alone**, a weak-copyleft license whose obligations extend only to *modifications of veraPDF's own source files* — not to the larger application calling it, regardless of whether it's invoked in-process, as a subprocess, or as a container. This makes the "subprocess vs linked code" distinction the plan item worried about moot: under MPLv2, unmodified, there's no copyleft exposure either way.

## What was run

- Pulled `verapdf/rest` (Docker Hub), 180MB image, self-contained (no external calls at runtime — confirmed via container logs, no outbound requests during validation).
- Ran under amd64 emulation on this arm64 dev machine; a production deploy should pull/build an arm64-native image or accept emulation overhead — not evaluated here.
- Validated `demo-fixtures/pdf-accessibility-demo.pdf` (ACP's own deliberately-untagged PDF fixture, documented in `demo-fixtures/README.md` to fire 1.3.1, 1.3.3, 1.4.3, 1.4.5, 1.4.6, 1.4.9, 2.4.1, 2.4.2, 3.1.1, 3.1.2) against both the `ua1` (PDF/UA-1) and `ua2` (PDF/UA-2) profiles.
- Ran ACP's own live PDF rule set (`worker-python/analysers/pdf_analyser.py`'s 8 rules) against the identical file for a direct side-by-side — not the README's static claim, the actual current output.

## Result: strong corroboration, some net-new, some confirmed-out-of-scope

**ACP's live findings on this fixture** (structural/tagging rules only — contrast/OCR/bypass-block checks live separately in `api/office_structure.py` and weren't run in this comparison since veraPDF doesn't touch that surface either):

| Rule | WCAG SC | Severity |
|---|---|---|
| `pdf.tagged` | 1.3.1 | CRITICAL |
| `pdf.display-doc-title` | 2.4.2 | MODERATE |
| `pdf.document-language` | 3.1.1 | SERIOUS |

**veraPDF's findings** (7 failed rule categories, UA1 and UA2 agree on substance, just re-numbered per the newer ISO 14289-2 clauses):

| Clause | Maps to | vs. ACP |
|---|---|---|
| 6.2 (MarkInfo/Marked missing) | 1.3.1 | **Exact match** — same underlying property ACP's `pdf.tagged` reads |
| 7.1/8.2.1 (no StructTreeRoot) | 1.3.1 | **Exact match** — same check, other half of `pdf.tagged` |
| 7.1/8.2.2 (53 content items not marked Artifact/tagged) | 1.3.1 | **Corroborates + more granular** — ACP flags the file once; veraPDF flags every offending content item |
| 7.2/8.4.4 (51 content items with no determinable language) | 3.1.1 | **Corroborates + more granular** — same conclusion as `pdf.document-language`, per-content-item instead of catalog-only |
| 7.1/8.11.2 (DisplayDocTitle missing) | 2.4.2 | **Exact match** — same check as `pdf.display-doc-title` |
| 7.1/8.11.1 (missing XMP metadata stream) | *none of ACP's 20 in-scope SCs* | **Net new**, but outside WCAG scope — a PDF/UA metadata requirement, not a WCAG success criterion |
| 7.21.4.1/8.4.5.5.1 (2 fonts not embedded) | *none of ACP's 20 in-scope SCs* | **Net new**, but outside WCAG scope — rendering-fidelity requirement, not WCAG |

**What veraPDF did NOT flag** (confirming these stay ACP's own value-add): 1.3.3 (sensory characteristics), 1.4.3/1.4.6 (contrast), 1.4.5/1.4.9 (images of text / OCR), 2.4.1 (bypass blocks), 3.1.2 (language of parts) — all genuinely outside PDF/UA structural validation's remit, exactly as the build-vs-buy evaluation predicted.

## Update: the open question is resolved — with a nuance worth reporting precisely

Built a minimal form-bearing fixture (`test-corpus/spike-fixtures/pdf-form-fields-spike.pdf`, via `reportlab`'s `AcroForm.textfield()`) with two fields: `full_name` (has `/TU "Full name"`) and `dob_field` (deliberately no `/TU`). Ran it through both profiles.

**UA1 catches it directly, on the correct field:**
```
7.18.1  "A form field shall have a TU key present or all its Widget annotations shall have alternative descriptions"
        context: root/document[0]/pages[0](10 0 obj PDPage)/annots[1](9 0 obj PDWidgetAnnot)   ← the second widget = dob_field, the unlabeled one
7.2/25  "Natural language in the TU key for form fields shall be determined"
        context: root/document[0]/AcroForm[0](15 0 obj PDAcroForm)/formFields[0](6 0 obj PDTextField)
```
This is exactly the AcroForm `/T`/`/TU` check the earlier build-vs-buy evaluation flagged as ACP's cheapest unbuilt gap for 4.1.2 — confirmed directly, not inferred.

**UA2 does NOT show the equivalent rule on this same fixture** — its 8 failures are the same tagging/language/metadata/font findings as the untagged fixture, with no `/TU`-specific failure despite the identical unlabeled field being present. Two failures in UA2's list mention annotations (8.9.3.3, about a `Tabs` dictionary entry — tab order, not field naming), but nothing matching UA1's 7.18.1. This could mean UA2's PDF/UA-2 model gates the TU-presence check behind other structural prerequisites (e.g. the widget being properly nested in a tagged Form structure element first) that this minimal, untagged fixture doesn't meet — the same kind of cascading-order effect ACP's own `pdf.tagged`-first design already uses. **Not resolved here** — reporting the observed asymmetry rather than guessing at UA2's internal rule-gating logic.

**Cross-checked against ACP's own live scanner on the identical fixture — confirms zero coverage today**, exactly as expected: ACP's 8 PDF rules return the same 3 findings as any other untagged file (`pdf.tagged`, `pdf.display-doc-title`, `pdf.document-language`) and say nothing whatsoever about the form fields, since none of ACP's PDF rules inspect `AcroForm`/`Widget` annotations at all.

**Practical implication:** if ACP wants veraPDF to close the 4.1.2 gap, **use the UA1 profile** for that specific check, not UA2 — until the UA2 gating behavior is understood on a properly-tagged form-bearing fixture (a good candidate for the Matterhorn Protocol corpus work in item 0.2).

## Recommendation

Corroborates the "yes, PDF/UA structural validation" call from the earlier build-vs-buy evaluation. Concretely:
- **Local, self-hosted, deterministic** — satisfies ACP's own Certified-tier bar; no architecture compromise.
- On the one fixture tested, veraPDF's tagging/language/title findings **agree with ACP's own conclusions** while adding useful per-content-item granularity ACP's current rules don't surface.
- Two genuinely new finding categories (XMP metadata, font embedding) exist outside WCAG's 20-criterion scope — worth a decision on whether ACP's rubric should ever absorb PDF/UA requirements beyond strict WCAG mapping, or whether these get reported as "bonus" PDF/UA findings without an SC key. Not resolved here; a scope question, not a technical one.
- **UA1 directly closes the unbuilt 4.1.2 AcroForm gap** (confirmed against a purpose-built form fixture, correct field identified) — this alone likely justifies the integration on its own, independent of the tagging/language/title corroboration. UA2's equivalent behavior is unresolved and shouldn't be assumed to match UA1's.
- Corpus run (item 0.2, *properly tagged* form-bearing files in particular, to resolve the UA1-vs-UA2 gating question) is the right next step before deciding replace-vs-cross-validate for the 8 existing PDF rules.

## Reproduction

```bash
docker pull verapdf/rest
docker run -d --name verapdf-spike -p 8080:8080 verapdf/rest
curl -s -X POST -F "file=@demo-fixtures/pdf-accessibility-demo.pdf" \
  "http://localhost:8080/api/validate/ua1?format=json" | python3 -m json.tool

# ACP's own live findings, same file, direct rule invocation (bypasses the Drive-corpus scan.py path):
.venv-drive/bin/python - <<'PY'
import sys
sys.path.insert(0, "/Users/css173265/projects/_review-digital-accessibility/worker-python")
import pikepdf, pdfplumber
from analysers.rules.pdf.tagged_pdf import TaggedPdfRule
from analysers.rules.pdf.display_title import DisplayTitleRule
from analysers.rules.pdf.document_language import DocumentLanguageRule
# ...(see full rule list in analysers/pdf_analyser.py)
pdf = pikepdf.open("demo-fixtures/pdf-accessibility-demo.pdf")
plumber_pdf = pdfplumber.open("demo-fixtures/pdf-accessibility-demo.pdf")
for rule in [TaggedPdfRule(), DisplayTitleRule(), DocumentLanguageRule()]:
    for issue in rule.check(pdf, plumber_pdf):
        print(rule.rule_id, issue.wcag_criterion, issue.severity)
PY
```

## Re-run 2026-07-21 — the 4.1.2 comparison was wrong, here's why and what's actually true now

Triggered by a GTM question about whether veraPDF should go on the roadmap. Before answering, re-ran this spike against ACP's **current combined pipeline** — `api/scanner.py:analyse_and_assess()`, which runs the vendored 8-rule engine (`_analyse_pdf`) AND ACP's own first-party checks (`ocr.py`, `textchecks.py`, `office_structure.py.checks_for()`) together, merged into one issue list, for every real PDF scan. The original run above only exercised the vendored engine in isolation (`worker-python/analysers/pdf_analyser.py`'s rules, invoked directly) — a narrower slice than what a real scan actually does, and specifically narrower than `office_structure.py`, which added `pdf_form_field_checks()` on 2026-07-15, two days before this spike was written. The original comparison never saw it.

**Docker, veraPDF's image, and both fixtures still work exactly as documented** — no drift there. Re-ran both:

**Form-fields fixture (`test-corpus/spike-fixtures/pdf-form-fields-spike.pdf`):**
- veraPDF UA1: **reproduces exactly** — clause 7.18.1 fails on `annots[1]` (the `dob_field` widget), byte-identical to the original run.
- veraPDF UA2: **reproduces exactly** — still no TU-equivalent failure on this fixture. The UA1-vs-UA2 asymmetry from the first run is confirmed unchanged, still unresolved, same recommendation (UA1, not UA2, if this signal is ever wanted).
- **ACP's current combined pipeline** (`scanner.analyse_and_assess()`, not just the vendored engine): returns `PDF_FORM_NO_ACCESSIBLE_NAME`, WCAG `4.1.2 Name, Role, Value`, CRITICAL, detail `"form field 'dob_field' has no accessible name (/TU)"` — **the exact same field, the exact same signal**, independently, from `office_structure.py`'s own `pdf_form_field_checks()`. This is the opposite of what the original run above found ("ACP's 8 PDF rules... say nothing whatsoever about the form fields") — that finding was accurate about the 8-rule engine alone, but incomplete about ACP's actual current pipeline, which the original spike didn't test.

**General-corroboration fixture (`demo-fixtures/pdf-accessibility-demo.pdf`):**
- veraPDF UA1: **reproduces exactly** — same 7 failed-rule categories, same clause numbers, same failed-check counts (53 untagged content items, 51 no-language content items, etc.) as the original run.
- **ACP's current combined pipeline**: returns **10 findings**, not the 3 (`pdf.tagged`, `pdf.display-doc-title`, `pdf.document-language`) the original comparison table shows. The other 7 — `OCR_IMAGE_OF_TEXT`/`OCR_IMAGE_OF_TEXT_STRICT` (1.4.5/1.4.9), `SENSORY_INSTRUCTION` (1.3.3), `LANG_PARTS_UNMARKED` (3.1.2), `PDF_LOW_CONTRAST_AA`/`PDF_LOW_CONTRAST_AAA` (1.4.3/1.4.6), `PDF_NO_BOOKMARKS` (2.4.1) — are exactly the categories the original "What veraPDF did NOT flag" section named as ACP's own value-add. That was a *prediction* on 07-17 (those checks existed in `office_structure.py` but weren't run in that comparison); this re-run *confirms* it directly — veraPDF's output still doesn't touch any of the 7, and ACP's current pipeline now demonstrably fires all of them on this fixture.

### Corrected conclusion

The **4.1.2 AcroForm gap this doc originally called "the practical implication" and led the Recommendation with is closed** — independently of veraPDF, by ACP's own code, three days before this spike's original write-up even shipped. veraPDF's UA1 signal for this specific SC is now **corroboration from a second, independent engine** (both tools agree, field-for-field), not new coverage. The real remaining gap on 4.1.2 — `/FT` and `/V`, per V3's fuller spec (`docs/deva-assessment-grid-comparison.md`) — is checked by **neither** ACP's native rule **nor** veraPDF's demonstrated UA1 rule; adopting veraPDF for 4.1.2 specifically would not close it.

**What still holds, unchanged:** the tagging/language/title corroboration-with-more-granularity case (1.3.1/2.4.2/3.1.1), the two out-of-WCAG-scope net-new categories (XMP metadata, font embedding), the license posture (MPLv2, no copyleft exposure), the local/self-hosted/deterministic architecture fit, and the UA1-vs-UA2 asymmetry (still open). The Phase-0 recommendation in `docs/adr/0028-amendment-local-corroboration-engines.md` stands on those grounds — it should be edited to drop the 4.1.2 AcroForm bullet as the lead justification and lean on the corroboration + PDF/UA-breadth case instead, which this re-run just independently re-confirmed with live current-code evidence, not a three-day-old snapshot.
