# Inspecting remediated files

Each released document has a corrected copy, a change report and a remaining-actions checklist. The change report includes the published-file link, recorded artifact identity, before/after values and verification evidence. Change counts are separate from finding counts. Applied AI edits awaiting semantic review remain explicitly unverified.

Accessibility properties can change without changing a document's appearance. Image descriptions, accessible form-field names, document language and table-header properties should be inspected through their recorded values and supported document tools, rather than screenshots alone. Reports disclose that stored evidence values can be shortened; the corrected document contains the full saved value.

For PDFs, recorded canonical page locators connect change records to original/released page evidence. Images are shown only when the saved candidate matches the recorded release digest. Component crops are limited to form fields whose page, rectangle and preserved state match between versions. Figures retain full-page evidence when their geometry cannot be established safely. Missing, rotated or incompatible geometry is not guessed.

Word table-header repair recognizes explicitly disabled header flags. PowerPoint title repair changes only an exact empty title placeholder and preserves its layout and styling; ambiguous or newly populated titles remain unresolved. Adjacent formatted PowerPoint hyperlink runs receive one approved label. Unsupported complex Word hyperlinks are declined instead of removing bookmarks, fields, drawings or existing revisions.

Both normal release and delivery-only retry verify destination bytes before treating an upload as successful. A delivery retry does not run remediation or verification again and does not replace the customer's original file.

This evidence work does not add general Word Track Changes, PowerPoint revision tracking, or PDF heading/tag-tree, complex-table and reading-order repair. Those require additional format-specific writers and preservation tests. A successful upload or changed screenshot does not establish accessibility compliance.

AI-assisted expansion: document-wide review includes extracted document context and exact supported image evidence for Word, Excel and PowerPoint. It does not upload the original Office archive. Approved OCR transcripts replace simple Word inline body pictures and simple Excel drawing pictures with editable text; grouped, shared, cropped or rotated images remain unresolved. PDF language-of-parts proposals target existing text-bearing tagged leaves with their own `/ActualText`; approved writes change only `/Lang` and preserve page content. Untagged PDFs and ambiguous structures remain unsupported. These changes still require review of meaning and the saved-file verification path.

## Offline remediation guide

The audit export and released-file checklist include a document-by-document guide for follow-up outside ACP. Recorded AI suggestions remain recommendations until the saved-file evidence establishes an applied change. Technical checks and confirmation of meaning are separate. Review inside ACP remains available; the guide does not add a new approval requirement or change the run’s saved authorization.

Remaining findings retain individual recorded locations and priority, even when several findings share one success criterion. Unlinked recommendations are printed separately and are not counted as additional assessment findings. Missing or ambiguous locations are disclosed rather than guessed. Format-specific editor guidance covers Word, Excel, PowerPoint and PDF; it is general guidance rather than a claim that ACP can automatically write every repair.

Use the released-file receipt to identify the saved copy. Where no artifact version or hash was recorded, the guide says so. After editing a file externally, save a new version and reassess it; old verification evidence does not establish the result of those edits. Invisible accessibility-property changes are explained through recorded original and saved values. Existing exact-artifact PDF visual evidence remains available in the change report.
