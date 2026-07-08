using DigitalA11y.Core.Contracts.Responses;

namespace DigitalA11y.Core.Analysis;

/// <summary>
/// Single source of truth for human-readable rule descriptions and remediation guidance.
/// Descriptions are intentionally generic (no runtime interpolation placeholders) so they
/// display sensibly in a UI without access to the concrete issue instance values.
/// </summary>
public static class RuleMetadataRegistry
{
    private static readonly IReadOnlyDictionary<string, RuleMetadataResponse> All =
        new Dictionary<string, RuleMetadataResponse>
        {
            // ── DOCX ─────────────────────────────────────────────────────────────

            [DocxRuleIds.AltText] = new(
                DocxRuleIds.AltText,
                "Image missing meaningful alt text",
                "An image does not have descriptive alternative text. Screen reader users and users who cannot load images will have no way to understand its content or purpose.",
                "Right-click the image, choose 'Edit Alt Text', and provide a concise description of the image content and function. Mark purely decorative images as decorative."),

            [DocxRuleIds.Bookmarks] = new(
                DocxRuleIds.Bookmarks,
                "Long document has no navigation bookmarks",
                "The document is long but contains no bookmarks. Bookmarks provide navigation landmarks that help keyboard and assistive technology users move through long documents efficiently.",
                "Add bookmarks at key sections via Insert → Bookmark. Consider also adding a table of contents using the built-in heading styles."),

            [DocxRuleIds.ColourContrast] = new(
                DocxRuleIds.ColourContrast,
                "Insufficient colour contrast",
                "Text in this document has a contrast ratio below the required threshold. Low contrast makes text difficult or impossible to read for users with low vision or colour deficiencies.",
                "Increase the contrast between the foreground and background colours to at least 4.5:1 for normal text and 3:1 for large text (18pt or 14pt bold). Use a contrast checker to verify."),

            [DocxRuleIds.DocumentLanguage] = new(
                DocxRuleIds.DocumentLanguage,
                "Document language not declared",
                "The document does not declare a language. Screen readers rely on the language declaration to select the correct speech synthesiser and pronunciation rules.",
                "Set the document language via File → Info → Language (or via Document Properties)."),

            [DocxRuleIds.DocumentTitle] = new(
                DocxRuleIds.DocumentTitle,
                "Document title not set",
                "The document does not have a title in its core properties. A descriptive title helps users identify the document and is required by WCAG 2.4.2.",
                "Set a descriptive title via File → Info → Properties → Title."),

            [DocxRuleIds.HeadingStructure] = new(
                DocxRuleIds.HeadingStructure,
                "Heading structure is incorrect",
                "The document has no H1 heading, has multiple H1 headings, or skips heading levels. Poor heading structure prevents screen reader users from navigating the document by section.",
                "Apply built-in Heading styles (Heading 1, 2, 3…) in the correct hierarchical order. Ensure exactly one H1 at the top and do not skip levels."),

            [DocxRuleIds.LanguageOfParts] = new(
                DocxRuleIds.LanguageOfParts,
                "Long text run has no explicit language set",
                "A significant run of text does not have an explicit language attribute. If this text is in a different language from the document language, screen readers will mispronounce it.",
                "Select the foreign-language text and set the correct language via Review → Language → Set Proofing Language."),

            [DocxRuleIds.LinkPurpose] = new(
                DocxRuleIds.LinkPurpose,
                "Link text does not describe the link purpose",
                "A hyperlink has empty or generic text (e.g. 'click here', 'read more'). Screen reader users navigating a list of links will not know its destination.",
                "Replace the link text with a description that identifies the destination or purpose of the link, e.g. 'Download the 2024 Accessibility Report (PDF)'."),

            [DocxRuleIds.TableHeaders] = new(
                DocxRuleIds.TableHeaders,
                "Table has no header row",
                "The table has multiple rows but its first row is not marked as a header row. Without headers, screen readers cannot associate data cells with their column labels.",
                "Select the first row of the table, open Table Properties → Row, and check 'Repeat as header row at the top of each page'. Apply the 'Table Header' paragraph style to cells in that row."),

            // ── PPTX ─────────────────────────────────────────────────────────────

            [PptxRuleIds.AltText] = new(
                PptxRuleIds.AltText,
                "Image or graphic missing meaningful alt text",
                "An image or graphic on a slide does not have descriptive alternative text. Screen reader users will have no way to understand its content or purpose.",
                "Right-click the image, choose 'Edit Alt Text', and provide a concise description of the image content and purpose. Mark purely decorative elements as decorative."),

            [PptxRuleIds.AnimationOrder] = new(
                PptxRuleIds.AnimationOrder,
                "Animations may auto-advance without user control",
                "One or more animations are configured to play automatically without a manual trigger. This can prevent users from controlling the pace of content presentation.",
                "In the Animations panel, change the animation start trigger from 'After Previous' or 'With Previous' to 'On Click' so users control when content appears."),

            [PptxRuleIds.ColourContrast] = new(
                PptxRuleIds.ColourContrast,
                "Insufficient colour contrast",
                "Text on a slide has a contrast ratio below the required threshold. Low contrast makes text difficult or impossible to read for users with low vision.",
                "Increase the contrast between text and background colours to at least 4.5:1 for normal text and 3:1 for large text. Avoid placing text over complex background images."),

            [PptxRuleIds.DocumentLanguage] = new(
                PptxRuleIds.DocumentLanguage,
                "Presentation language not declared",
                "The presentation does not declare a document language. Screen readers cannot determine the correct language for text-to-speech rendering.",
                "Set the editing language in PowerPoint (Review → Language → Set Proofing Language) to declare the primary language of the presentation."),

            [PptxRuleIds.LinkPurpose] = new(
                PptxRuleIds.LinkPurpose,
                "Link text does not describe its purpose",
                "A hyperlink on a slide has non-descriptive link text. Users cannot determine the link destination without additional context.",
                "Replace generic link text with a phrase that describes the destination or purpose, e.g. 'Read the full accessibility report'."),

            [PptxRuleIds.ReadingOrder] = new(
                PptxRuleIds.ReadingOrder,
                "Reading order may not match visual order",
                "The tab/reading order of shapes on a slide does not match their visual top-to-bottom, left-to-right order. Screen readers announce content in tab order, which may confuse users.",
                "Open the Selection Pane (Home → Arrange → Selection Pane) and reorder shapes so the tab order matches the intended reading sequence. Items are listed bottom-to-top in the pane."),

            [PptxRuleIds.SlideTitle] = new(
                PptxRuleIds.SlideTitle,
                "Slide is missing a title",
                "A slide does not have a meaningful title. Untitled slides are indistinguishable to screen reader users navigating slide-by-slide.",
                "Add a descriptive title to the slide title placeholder so users can identify and navigate to individual slides."),

            [PptxRuleIds.TableHeaders] = new(
                PptxRuleIds.TableHeaders,
                "Table is missing a designated header row",
                "A table has more than one row but the first row is not marked as a header row. Screen readers cannot associate data cells with their column headings.",
                "Select the table, go to Table Design, and enable the 'Header Row' option to designate the first row as column headers."),

            // ── XLSX ─────────────────────────────────────────────────────────────

            [XlsxRuleIds.AltText] = new(
                XlsxRuleIds.AltText,
                "Image or chart missing meaningful alt text",
                "An image or chart in the spreadsheet does not have descriptive alternative text. Screen reader users will have no way to understand its content.",
                "Right-click the image or chart, choose 'Edit Alt Text', and provide a concise description. Mark purely decorative images as decorative."),

            [XlsxRuleIds.DocumentLanguage] = new(
                XlsxRuleIds.DocumentLanguage,
                "Spreadsheet language is not set",
                "The document Language property is absent or empty. Assistive technologies need a declared language to use correct pronunciation rules.",
                "Set the document language via File → Options → Language."),

            [XlsxRuleIds.DocumentTitle] = new(
                XlsxRuleIds.DocumentTitle,
                "Spreadsheet has no document title",
                "The document Title property is absent or empty. A meaningful title helps users identify the document and is required for WCAG 2.4.2.",
                "Add a descriptive title via File → Properties → Summary."),

            [XlsxRuleIds.HiddenContent] = new(
                XlsxRuleIds.HiddenContent,
                "Hidden row or column contains content",
                "A hidden row or column contains data. Hidden content may be inaccessible to assistive technology users and can cause confusion when encountered unexpectedly.",
                "Unhide the row or column if the content is still needed, or remove it entirely if it is no longer relevant."),

            [XlsxRuleIds.MergedCells] = new(
                XlsxRuleIds.MergedCells,
                "Excessive merged cells disrupt reading order",
                "A sheet has a high number of merged cell ranges. Excessive merging makes it difficult for assistive technologies to interpret the logical reading order of the spreadsheet.",
                "Review merged cells and use formatting alternatives such as 'Centre Across Selection' where possible to reduce merging without losing visual alignment."),

            [XlsxRuleIds.SheetName] = new(
                XlsxRuleIds.SheetName,
                "Sheet has a generic default name",
                "A sheet uses a generic default name such as 'Sheet1'. Meaningful sheet names help users navigate and understand the spreadsheet structure.",
                "Double-click the sheet tab and rename it to a concise, descriptive name that reflects the sheet's content."),

            [XlsxRuleIds.TableHeaders] = new(
                XlsxRuleIds.TableHeaders,
                "Table has no header row",
                "A table has no header row. Header rows are required for assistive technologies to identify column context when navigating data cells.",
                "Convert the first row to a header row via Table Design → Header Row."),

            // ── PDF ──────────────────────────────────────────────────────────────

            [PdfRuleIds.Tagged] = new(
                PdfRuleIds.Tagged,
                "PDF is not tagged for accessibility",
                "This PDF does not have a tagged structure tree. Tagged PDFs are required for screen readers and other assistive technologies to interpret document content and reading order correctly.",
                "Open the PDF in Adobe Acrobat Pro and use the Accessibility Checker to add tags. Alternatively, re-export from the source document with accessibility options enabled."),

            [PdfRuleIds.DocumentTitle] = new(
                PdfRuleIds.DocumentTitle,
                "PDF is missing a document title",
                "The PDF document information does not contain a title. A descriptive title helps users identify the document and is announced by screen readers when the document is opened.",
                "Set the document title in File → Properties → Description in Adobe Acrobat, or re-export from the source document with the title property set."),

            [PdfRuleIds.DisplayDocTitle] = new(
                PdfRuleIds.DisplayDocTitle,
                "PDF viewer is not set to display the document title",
                "The PDF ViewerPreferences dictionary does not set DisplayDocTitle to true. Without this setting, PDF viewers display the filename rather than the document title in the title bar.",
                "In Adobe Acrobat: File → Properties → Initial View → Show → Document Title. This ensures the meaningful title is shown instead of the filename."),

            [PdfRuleIds.DocumentLanguage] = new(
                PdfRuleIds.DocumentLanguage,
                "PDF is missing a document language",
                "The PDF catalog does not specify a language. Screen readers use the document language to select the correct text-to-speech voice and pronunciation rules.",
                "Set the document language in Adobe Acrobat: File → Properties → Advanced → Language. Or re-export from the source document with the language set."),

            [PdfRuleIds.MissingAltText] = new(
                PdfRuleIds.MissingAltText,
                "Figure element is missing alternative text",
                "A tagged figure (image) in the PDF structure tree does not have an /Alt attribute. Screen readers cannot describe this image to users.",
                "Add alternative text to the figure using the Tags panel in Adobe Acrobat: right-click the Figure tag → Properties → Alternate Text."),

            [PdfRuleIds.ReadingOrder] = new(
                PdfRuleIds.ReadingOrder,
                "Possible reading order issue detected",
                "A page may have a reading order that does not match the visual layout. Screen readers follow the content stream order, which may cause text to be read in the wrong sequence.",
                "Use the Order panel in Adobe Acrobat to verify and correct the reading order. This may require re-tagging the document."),

            [PdfRuleIds.MissingBookmarks] = new(
                PdfRuleIds.MissingBookmarks,
                "Long PDF is missing a bookmark outline",
                "This PDF has many pages but no bookmark outline. Bookmarks allow keyboard and screen reader users to navigate directly to sections without scrolling through the entire document.",
                "Add bookmarks using the Bookmarks panel in Adobe Acrobat, or re-export from the source document with heading-based bookmarks enabled."),

            // ── HTML ─────────────────────────────────────────────────────────────

            [HtmlRuleIds.AltText] = new(
                HtmlRuleIds.AltText,
                "Image is missing alternative text",
                "One or more images do not have an alt attribute. Screen reader users will have no way to understand the image content or purpose.",
                "Add a meaningful alt attribute to all informative images. Use alt=\"\" (empty) for decorative images so assistive technologies skip them."),

            [HtmlRuleIds.DocumentTitle] = new(
                HtmlRuleIds.DocumentTitle,
                "Page is missing a document title",
                "The page has a missing or empty <title> element. Users cannot identify the page when switching tabs, using browser history, or when a screen reader announces the page.",
                "Add a descriptive <title> to the <head> of every page. Titles should be unique and describe the current page purpose."),

            [HtmlRuleIds.HeadingStructure] = new(
                HtmlRuleIds.HeadingStructure,
                "Heading structure is incorrect",
                "Heading levels are skipped or out of order, or a heading element is empty. This breaks the document outline and prevents efficient navigation by screen reader users.",
                "Use heading elements (h1–h6) in a logical hierarchical order. Do not skip levels or use headings purely for visual styling."),

            [HtmlRuleIds.LinkPurpose] = new(
                HtmlRuleIds.LinkPurpose,
                "Link text does not describe its purpose",
                "One or more links have text that does not describe their destination (e.g. 'click here', 'read more'). Screen reader users navigating by links will not know where they lead.",
                "Write link text that describes the destination or action. If the context is visual only, add an aria-label or visually-hidden span with descriptive text."),

            [HtmlRuleIds.Language] = new(
                HtmlRuleIds.Language,
                "Page is missing a language declaration",
                "The <html> element does not have a lang attribute. Screen readers cannot select the correct language voice or pronunciation rules.",
                "Add a lang attribute to the <html> element, e.g. <html lang=\"en\">."),

            [HtmlRuleIds.HtmlLangValid] = new(
                HtmlRuleIds.HtmlLangValid,
                "Page language code is invalid",
                "The lang attribute on the <html> element contains an invalid BCP 47 language tag. Screen readers may mispronounce content as a result.",
                "Use a valid BCP 47 language tag such as \"en\", \"en-GB\", or \"fr-FR\"."),

            [HtmlRuleIds.Label] = new(
                HtmlRuleIds.Label,
                "Form input is missing a label",
                "One or more form inputs do not have an associated label. Screen reader users filling out the form will not know what information is expected.",
                "Associate a <label> element with each input using the for/id pair, or use aria-label / aria-labelledby to provide an accessible name."),

            [HtmlRuleIds.ColourContrast] = new(
                HtmlRuleIds.ColourContrast,
                "Insufficient colour contrast",
                "Text on the page has a contrast ratio below the required threshold. Low contrast makes text difficult to read for users with low vision or colour deficiencies.",
                "Ensure a contrast ratio of at least 4.5:1 for normal text and 3:1 for large text (18px regular or 14px bold). Use a colour contrast checker to verify all text."),

            [HtmlRuleIds.TableHeaders] = new(
                HtmlRuleIds.TableHeaders,
                "Table is missing header cells",
                "A data table does not have <th> elements or scope attributes. Screen readers cannot associate data cells with their column or row labels.",
                "Use <th scope=\"col\"> for column headers and <th scope=\"row\"> for row headers. Add a <caption> to describe the table's purpose."),

            [HtmlRuleIds.AriaRoles] = new(
                HtmlRuleIds.AriaRoles,
                "Invalid or missing ARIA roles",
                "One or more elements have invalid, conflicting, or missing ARIA roles or attributes. This can misrepresent the purpose of interactive elements to assistive technologies.",
                "Use ARIA roles that match the element's true purpose and ensure required ARIA attributes are present. Prefer native HTML elements over ARIA where possible."),

            [HtmlRuleIds.SkipNav] = new(
                HtmlRuleIds.SkipNav,
                "Page is missing a skip navigation link",
                "There is no skip navigation link at the top of the page. Keyboard and screen reader users must tab through every navigation item before reaching the main content.",
                "Add a visually-hidden 'Skip to main content' link as the first focusable element on the page, linking to the <main> landmark element."),

            [HtmlRuleIds.Accessibility] = new(
                HtmlRuleIds.Accessibility,
                "General accessibility violation detected",
                "One or more general accessibility violations were detected that affect users of assistive technology.",
                "Review the specific evidence and location details to identify and fix the underlying accessibility issue."),
        };

    /// <summary>Returns the metadata for a single rule, or null if the rule ID is not registered.</summary>
    public static RuleMetadataResponse? Get(string ruleId)
        => All.TryGetValue(ruleId, out var meta) ? meta : null;

    /// <summary>Returns metadata for all known rules.</summary>
    public static IReadOnlyList<RuleMetadataResponse> GetAll()
        => [.. All.Values];
}
