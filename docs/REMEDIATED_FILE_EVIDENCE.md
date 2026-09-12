# Inspecting remediated files

Each released document has a corrected copy, a change report and a remaining-actions checklist. The change report includes the published-file link, recorded artifact identity, before/after values and verification evidence. Change counts are separate from finding counts. Applied AI edits awaiting semantic review remain explicitly unverified.

Accessibility properties can change without changing a document's appearance. Image descriptions, accessible form-field names, document language and table-header properties should be inspected through their recorded values and supported document tools, rather than screenshots alone. Reports disclose that stored evidence values can be shortened; the corrected document contains the full saved value.

For PDFs, recorded canonical page locators connect change records to original/released page evidence. Images are shown only when the saved candidate matches the recorded release digest. Component crops are limited to form fields whose page, rectangle and preserved state match between versions. Figures retain full-page evidence when their geometry cannot be established safely. Missing, rotated or incompatible geometry is not guessed.

Word table-header repair recognizes explicitly disabled header flags. PowerPoint title repair changes only an exact empty title placeholder and preserves its layout and styling; ambiguous or newly populated titles remain unresolved. Adjacent formatted PowerPoint hyperlink runs receive one approved label. Unsupported complex Word hyperlinks are declined instead of removing bookmarks, fields, drawings or existing revisions.

Both normal release and delivery-only retry verify destination bytes before treating an upload as successful. A delivery retry does not run remediation or verification again and does not replace the customer's original file.

This evidence work does not add general Word Track Changes, PowerPoint revision tracking, or PDF heading/tag-tree, complex-table and reading-order repair. Those require additional format-specific writers and preservation tests. A successful upload or changed screenshot does not establish accessibility compliance.

AI-assisted expansion: document-wide review includes extracted document context and exact supported image evidence for Word, Excel and PowerPoint. It does not upload the original Office archive. Approved OCR transcripts replace simple Word inline body pictures and simple Excel drawing pictures with editable text; grouped, shared, cropped or rotated images remain unresolved. PDF language-of-parts proposals target existing text-bearing tagged leaves with their own `/ActualText`; approved writes change only `/Lang` and preserve page content. Untagged PDFs and ambiguous structures remain unsupported. These changes still require review of meaning and the saved-file verification path.
