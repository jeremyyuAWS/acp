# Word tracked-change companion

Publication uses the **accepted corrected copy** that passed fresh assessment. A separately generated Word companion represents supported prose changes as native `w:del`/`w:ins` revisions authored by Mova.io ACP. Word's markup view can show the original and revised text; accepting ACP revisions yields the revised text, rejecting them yields the original text for those supported edits.

The companion is bound to SHA-256 hashes of the exact original, corrected and companion files. Its comparison report lists each represented paragraph and every changed part or paragraph that cannot safely be represented as a native revision. It does not modify the source or the assessed primary copy.

Supported comparisons:

- Simple Word paragraph runs, including styled text and multiple runs.
- Simple hyperlink label text with the original relationship/anchor unchanged.
- Main document, header and footer parts with unchanged surrounding structure.

Existing author revisions remain intact. ACP refuses to create nested revisions in a paragraph containing existing revisions. Fields, drawings, complex runs, added/removed paragraphs and changed paragraph properties are retained as accepted corrected content and reported as **untracked**, rather than producing a misleading or damaged revision history.

Accessibility metadata such as image descriptions and document language/title has no ordinary prose insertion/deletion representation. The release's recorded before/after changes and exact artifact evidence cover those edits. A partial comparison never claims that every change is represented through Word Track Changes. PowerPoint and PDF native revision histories are not provided by this Word companion.

The companion is for optional inspection. It does not replace the freshly assessed corrected copy, create a new manual approval barrier, or claim a native Office accessibility-checker pass. For a download containing no supported prose changes, no redundant companion is emitted; the comparison report still explains metadata or unsupported changes.
