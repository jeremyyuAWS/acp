namespace DigitalA11y.Core.Analysis;

public static class XlsxRuleIds
{
    public const string AltText = "XLSX-ALT-001";
    public const string SheetName = "XLSX-SHEET-001";
    public const string DocumentLanguage = "XLSX-LANG-001";
    public const string TableHeaders = "XLSX-TABLE-001";
    public const string HiddenContent = "XLSX-HIDDEN-001";
    public const string MergedCells = "XLSX-MERGE-001";
    public const string DocumentTitle = "XLSX-TITLE-001";
    public const string BlankWorksheet = "XLSX-BLANK-001";
    public const string LinkPurpose = "XLSX-LINK-001";

    public static IReadOnlyList<string> All =>
    [
        AltText,
        SheetName,
        DocumentLanguage,
        TableHeaders,
        HiddenContent,
        MergedCells,
        DocumentTitle,
        BlankWorksheet,
        LinkPurpose,
    ];
}
