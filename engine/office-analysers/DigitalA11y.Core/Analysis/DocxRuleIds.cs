namespace DigitalA11y.Core.Analysis;

public static class DocxRuleIds
{
    public const string DocumentLanguage = "DOCX-LANG-001";
    public const string DocumentTitle = "DOCX-TITLE-001";
    public const string HeadingStructure = "DOCX-HEAD-001";
    public const string AltText = "DOCX-ALT-001";
    public const string TableHeaders = "DOCX-TABLE-001";
    public const string ColourContrast = "DOCX-CONTRAST-001";
    public const string LinkPurpose = "DOCX-LINK-001";
    public const string LanguageOfParts = "DOCX-LANGPART-001";
    public const string Bookmarks = "DOCX-BOOKMARK-001";

    public static IReadOnlyList<string> All =>
    [
        DocumentLanguage,
        DocumentTitle,
        HeadingStructure,
        AltText,
        TableHeaders,
        ColourContrast,
        LinkPurpose,
        LanguageOfParts,
        Bookmarks,
    ];
}
