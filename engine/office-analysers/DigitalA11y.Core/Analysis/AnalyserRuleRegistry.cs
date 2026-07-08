using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Analysis;

/// <summary>
/// Central registry of all known rule IDs per analyser type.
/// </summary>
public static class AnalyserRuleRegistry
{
    private static readonly IReadOnlyDictionary<AnalyserType, IReadOnlyList<string>> Rules =
        new Dictionary<AnalyserType, IReadOnlyList<string>>
        {
            [AnalyserType.Pptx] = PptxRuleIds.All,
            [AnalyserType.Docx] = DocxRuleIds.All,
            [AnalyserType.Html] = HtmlRuleIds.All,
            [AnalyserType.Pdf]  = PdfRuleIds.All,
            [AnalyserType.Xlsx] = XlsxRuleIds.All,
        };

    /// <summary>
    /// Returns all rule IDs for the given analyser type,
    /// or an empty list if the type is not registered.
    /// </summary>
    public static IReadOnlyList<string> GetRules(AnalyserType analyserType)
        => Rules.TryGetValue(analyserType, out var ids) ? ids : [];
}
