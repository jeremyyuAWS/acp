using DigitalA11y.Analysers.DotNet.Docx.Helpers;
using DigitalA11y.Analysers.DotNet.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace DigitalA11y.Analysers.DotNet.Docx.Rules;

public class ColourContrastRule : IDocxRule
{
    public string RuleId => DocxRuleIds.ColourContrast;

    private const string DefaultBackground = "FFFFFF";
    private const string DefaultForeground = "000000";

    public IEnumerable<A11yIssue> Analyse(WordprocessingDocument document)
    {
        var body = document.MainDocumentPart?.Document?.Body;
        if (body is null) yield break;

        var stylesPart = document.MainDocumentPart?.StyleDefinitionsPart;
        var themePart = document.MainDocumentPart?.ThemePart;

        var paragraphs = body.Descendants<Paragraph>().ToList();

        for (int paraIdx = 0; paraIdx < paragraphs.Count; paraIdx++)
        {
            var para = paragraphs[paraIdx];
            var paraBackground = ResolveParaBackground(para, stylesPart);

            // Track the worst-failing run per paragraph to avoid duplicate (RuleId, Location) keys.
            Run? worstRun = null;
            double worstRatio = double.MaxValue;
            double worstThreshold = 4.5;
            string worstForeground = DefaultForeground;
            string worstBackground = DefaultBackground;
            bool worstIsLarge = false;

            foreach (var run in para.Descendants<Run>())
            {
                var rpr = run.RunProperties;
                var colorVal = rpr?.Color?.Val?.Value;

                if (string.IsNullOrWhiteSpace(colorVal) || colorVal.Equals("auto", StringComparison.OrdinalIgnoreCase))
                    continue;

                string foreground = NormaliseHex(colorVal);
                string background = paraBackground ?? DefaultBackground;

                bool isBold = IsBold(run, stylesPart);
                string? szVal = rpr?.FontSize?.Val?.Value
                              ?? GetStyleFontSize(rpr?.RunStyle?.Val?.Value, stylesPart);
                bool isLarge = ColourContrastHelper.IsLargeText(szVal, isBold);

                double ratio = ColourContrastHelper.GetContrastRatio(foreground, background);
                double threshold = isLarge ? 3.0 : 4.5;

                if (ratio < threshold && ratio < worstRatio)
                {
                    worstRun = run;
                    worstRatio = ratio;
                    worstThreshold = threshold;
                    worstForeground = foreground;
                    worstBackground = background;
                    worstIsLarge = isLarge;
                }
            }

            if (worstRun is not null)
            {
                string runText = string.Concat(worstRun.Descendants<Text>().Select(t => t.Text));

                yield return new A11yIssue
                {
                    IssueId = Guid.NewGuid(),
                    RuleId = RuleId,
                    Title = "Insufficient colour contrast",
                    Description = $"The text has a contrast ratio of {worstRatio:F2}:1, which is below the required {worstThreshold:F1}:1 for {(worstIsLarge ? "large" : "normal")} text.",
                    Severity = IssueSeverity.SERIOUS,
                    Category = IssueCategory.COLOUR_CONTRAST,
                    WcagCriterion = WcagCriterion.SC_1_4_3,
                    RemediationType = RemediationType.HUMAN_REQUIRED,
                    RemediationGuidance = $"Increase the contrast between the foreground colour #{worstForeground} and background colour #{worstBackground} to at least {worstThreshold:F1}:1.",
                    Location = LocationHelper.FromParagraph(paraIdx),
                    Evidence = new IssueEvidence
                    {
                        Snippet = Truncate(runText, 80),
                        ComputedValue = $"{worstRatio:F2}:1",
                        ExpectedValue = $"≥ {worstThreshold:F1}:1",
                        AdditionalContext = new Dictionary<string, string>
                        {
                            ["foreground_hex"] = worstForeground,
                            ["background_hex"] = worstBackground,
                            ["is_large_text"] = worstIsLarge.ToString()
                        }
                    }
                };
            }
        }
    }

    private static string? ResolveParaBackground(Paragraph para, StyleDefinitionsPart? stylesPart)
    {
        var paraShading = para.ParagraphProperties?.Shading?.Fill?.Value;
        if (!string.IsNullOrWhiteSpace(paraShading) && !paraShading.Equals("auto", StringComparison.OrdinalIgnoreCase))
            return NormaliseHex(paraShading);

        var styleId = para.ParagraphProperties?.ParagraphStyleId?.Val?.Value;
        if (styleId is not null && stylesPart is not null)
        {
            var style = FindStyle(styleId, stylesPart);
            var styleShading = style?.StyleParagraphProperties?.Shading?.Fill?.Value;
            if (!string.IsNullOrWhiteSpace(styleShading) && !styleShading.Equals("auto", StringComparison.OrdinalIgnoreCase))
                return NormaliseHex(styleShading);
        }

        return DefaultBackground;
    }

    private static bool IsBold(Run run, StyleDefinitionsPart? stylesPart)
    {
        var rpr = run.RunProperties;
        if (rpr?.Bold is not null) return rpr.Bold.Val?.Value != false;

        var runStyleId = rpr?.RunStyle?.Val?.Value;
        if (runStyleId is not null && stylesPart is not null)
        {
            var style = FindStyle(runStyleId, stylesPart);
            if (style?.StyleRunProperties?.Bold is not null)
                return style.StyleRunProperties.Bold.Val?.Value != false;
        }

        return false;
    }

    private static string? GetStyleFontSize(string? styleId, StyleDefinitionsPart? stylesPart)
    {
        if (styleId is null || stylesPart is null) return null;
        var style = FindStyle(styleId, stylesPart);
        return style?.StyleRunProperties?.FontSize?.Val?.Value;
    }

    private static Style? FindStyle(string styleId, StyleDefinitionsPart stylesPart)
        => stylesPart.Styles?.Descendants<Style>()
                     .FirstOrDefault(s => string.Equals(s.StyleId?.Value, styleId, StringComparison.OrdinalIgnoreCase));

    private static string NormaliseHex(string? hex)
    {
        if (string.IsNullOrWhiteSpace(hex)) return DefaultBackground;
        hex = hex.TrimStart('#');
        return hex.Length == 6 ? hex.ToUpperInvariant() : DefaultBackground;
    }

    private static string Truncate(string text, int max)
        => text.Length <= max ? text : text[..max] + "…";
}
