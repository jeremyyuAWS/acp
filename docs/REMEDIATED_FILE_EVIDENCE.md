# Inspecting remediated files

Each released document has a corrected copy, a change report and a remaining-actions checklist. The change report includes the published-file link, recorded artifact identity, before/after values and verification evidence. Change counts are separate from finding counts. Applied AI edits awaiting semantic review remain explicitly unverified.

Accessibility properties can change without changing a document's appearance. Image descriptions, accessible form-field names, document language and table-header properties should be inspected through their recorded values and supported document tools, rather than screenshots alone. Reports disclose that stored evidence values can be shortened; the corrected document contains the full saved value.

For PDFs, recorded canonical page locators connect change records to original/released page evidence. Images are shown only when the saved candidate matches the recorded release digest. Component crops are limited to form fields whose page, rectangle and preserved state match between versions. Figures retain full-page evidence when their geometry cannot be established safely. Missing, rotated or incompatible geometry is not guessed.

Word table-header repair recognizes explicitly disabled header flags. PowerPoint title repair changes only an exact empty title placeholder and preserves its layout and styling; ambiguous or newly populated titles remain unresolved. Adjacent formatted PowerPoint hyperlink runs receive one approved label. Unsupported complex Word hyperlinks are declined instead of removing bookmarks, fields, drawings or existing revisions.

Both normal release and delivery-only retry verify destination bytes before treating an upload as successful. A delivery retry does not run remediation or verification again and does not replace the customer's original file.

Before a new publication or corrected-copy package is prepared, ACP assesses the saved corrected candidate through the same canonical whole-file assessment path used by remediation. The candidate must match its authorized corrected SHA-256 and current record both before and after assessment. Approved but unwritten changes remain blockers. The original Assess baseline is not overwritten: release-specific evidence records the candidate hash, selected scope, remaining findings, skipped checks and any uncertainty.

Strict publishing rejects remaining findings or an assessment that could not establish a trustworthy result. Explicit publishing with remaining issues preserves that fresh evidence and does not claim full verification. A malformed corrected copy is not an acceptable remaining-issues delivery. Successful delivery still verifies the provider's bytes against the assessed artifact identity. Native Office/PDF checker success and full WCAG compliance are not established by selected automated checks alone.

Automatic Excel image-description writes preserve the actual drawing element name and namespace spelling, rather than writing the regex used to locate it. Authored XML-escaped title, caption and name values are decoded once before being written as descriptions. Real saved-workbook regression fixtures preserve the original source, cells, formulas and images and run the accessibility detectors on the corrected copy.

## Read-only saved-copy audit

`python scripts/audit_remediated_copy.py original.docx corrected.docx --expected expected.json --output audit.json`

This local audit accepts Word, Excel, PowerPoint and PDF files. It checks readability and exact corrected-byte identity, inventories Office drawing accessibility properties and checks explicitly supplied property expectations. `expected.json` may contain `corrected_sha256` and `images`; each image expectation must identify its exact `part`, expanded XML `tag` and string `id`, and provide the expected `description`, `title` or `decorative` property. The audit never guesses an ambiguous or missing object identity.

Exit zero means the supplied claims passed against readable files. Missing expectations, hash mismatches, invalid XML and ambiguous identities cannot pass. A matching hash alone establishes file identity, not every recorded repair. Full change coverage and Office/PDF Accessibility Checker success remain explicitly unestablished; those require the appropriate assessment and semantic review. The audit reads local bytes without credentials, provider writes, run-state changes or approval changes. It does not establish that a source file on SharePoint is unchanged: use the production canary bundle for provider identity, original-byte, placement and permission evidence.

This evidence work does not add general Word Track Changes, PowerPoint revision tracking, or PDF heading/tag-tree, complex-table and reading-order repair. Those require additional format-specific writers and preservation tests. A successful upload or changed screenshot does not establish accessibility compliance.

AI-assisted expansion: document-wide review includes extracted document context and exact supported image evidence for Word, Excel and PowerPoint. It does not upload the original Office archive. Approved OCR transcripts replace simple Word inline body pictures and simple Excel drawing pictures with editable text; grouped, shared, cropped or rotated images remain unresolved. PDF language-of-parts proposals target existing text-bearing tagged leaves with their own `/ActualText`; approved writes change only `/Lang` and preserve page content. Untagged PDFs and ambiguous structures remain unsupported. These changes still require review of meaning and the saved-file verification path.

## Offline remediation guide

The audit export and released-file checklist include a document-by-document guide for follow-up outside ACP. Recorded AI suggestions remain recommendations until the saved-file evidence establishes an applied change. Technical checks and confirmation of meaning are separate. Review inside ACP remains available; the guide does not add a new approval requirement or change the run’s saved authorization.

Remaining findings retain individual recorded locations and priority, even when several findings share one success criterion. Unlinked recommendations are printed separately and are not counted as additional assessment findings. Missing or ambiguous locations are disclosed rather than guessed. Format-specific editor guidance covers Word, Excel, PowerPoint and PDF; it is general guidance rather than a claim that ACP can automatically write every repair.

Use the released-file receipt to identify the saved copy. Where no artifact version or hash was recorded, the guide says so. After editing a file externally, save a new version and reassess it; old verification evidence does not establish the result of those edits. Invisible accessibility-property changes are explained through recorded original and saved values. Existing exact-artifact PDF visual evidence remains available in the change report.
