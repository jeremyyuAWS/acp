namespace DigitalA11y.Core.Analysis;

public static class PdfRuleIds
{
    public const string Tagged = "pdf.tagged";
    public const string DocumentTitle = "pdf.document-title";
    public const string DisplayDocTitle = "pdf.display-doc-title";
    public const string DocumentLanguage = "pdf.document-language";
    public const string MissingAltText = "pdf.missing-alt-text";
    public const string ReadingOrder = "pdf.reading-order";
    public const string MissingBookmarks = "pdf.missing-bookmarks";

    public static IReadOnlyList<string> All =>
    [
        Tagged,
        DocumentTitle,
        DisplayDocTitle,
        DocumentLanguage,
        MissingAltText,
        ReadingOrder,
        MissingBookmarks,
    ];
}
