"""
Registry mapping (rule_id, file_type) → BaseFixer instance.
Import lazily to avoid loading pikepdf/bs4 at startup.
"""

from __future__ import annotations

from models.manifest import FileType


def build_registry(mcp_client=None) -> dict[tuple[str, FileType], object]:
    from remediation.fixers.pdf.title_fixer import PdfTitleFixer
    from remediation.fixers.pdf.language_fixer import PdfLanguageFixer
    from remediation.fixers.pdf.alt_text_fixer import PdfAltTextFixer
    from remediation.fixers.pdf.bookmarks_fixer import PdfBookmarksFixer
    from remediation.fixers.pdf.display_title_fixer import PdfDisplayTitleFixer
    from remediation.fixers.html.title_fixer import HtmlTitleFixer
    from remediation.fixers.html.lang_fixer import HtmlLangFixer
    from remediation.fixers.html.skip_nav_fixer import HtmlSkipNavFixer
    from remediation.fixers.html.label_fixer import HtmlLabelFixer
    from remediation.fixers.html.alt_text_fixer import HtmlAltTextFixer
    from remediation.fixers.html.link_purpose_fixer import HtmlLinkPurposeFixer
    from remediation.fixers.html.heading_structure_fixer import HtmlHeadingStructureFixer
    from remediation.fixers.html.table_header_fixer import HtmlTableHeaderFixer

    return {
        ("pdf.document-title",    FileType.PDF):  PdfTitleFixer(mcp_client),
        ("pdf.document-language", FileType.PDF):  PdfLanguageFixer(),
        ("pdf.missing-alt-text",  FileType.PDF):  PdfAltTextFixer(mcp_client),
        ("pdf.missing-bookmarks", FileType.PDF):  PdfBookmarksFixer(mcp_client),
        ("pdf.display-doc-title", FileType.PDF):  PdfDisplayTitleFixer(),
        ("html.document-title",   FileType.HTML): HtmlTitleFixer(mcp_client),
        ("html.language",         FileType.HTML): HtmlLangFixer(),
        ("html.html-lang-valid",  FileType.HTML): HtmlLangFixer(),
        ("html.skip-nav",         FileType.HTML): HtmlSkipNavFixer(),
        ("html.label",            FileType.HTML): HtmlLabelFixer(),
        ("html.alt-text",         FileType.HTML): HtmlAltTextFixer(mcp_client),
        ("html.link-purpose",     FileType.HTML): HtmlLinkPurposeFixer(mcp_client),
        ("html.heading-structure",FileType.HTML): HtmlHeadingStructureFixer(mcp_client),
        ("html.table-headers",    FileType.HTML): HtmlTableHeaderFixer(),
    }
