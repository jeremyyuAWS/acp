using DigitalA11y.Analysers.DotNet.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Presentation;
using A = DocumentFormat.OpenXml.Drawing;
using PptxLocationHelper = DigitalA11y.Analysers.DotNet.Pptx.Helpers.LocationHelper;

namespace DigitalA11y.Analysers.DotNet.Pptx.Rules;

public class ColourContrastRule : IPptxRule
{
    public string RuleId => PptxRuleIds.ColourContrast;

    private const string DefaultBackground = "FFFFFF";
    private const string DefaultForeground = "000000";

    private const int LargeNormalThreshold = 1800;
    private const int LargeBoldThreshold = 1400;

    public IEnumerable<A11yIssue> AnalyseSlide(
        SlidePart slidePart,
        int slideIndex,
        PresentationDocument document)
    {
        var slide = slidePart.Slide;

        string slideBackground = ResolveSlideBackground(slidePart, document);

        // Track worst-failing run across all shapes on the slide to avoid duplicate (RuleId, Location) keys.
        A.Run? worstRun = null;
        double worstRatio = double.MaxValue;
        double worstThreshold = 4.5;
        string worstForeground = DefaultForeground;
        string worstBackground = DefaultBackground;
        bool worstIsLarge = false;

        foreach (var txBody in slide.Descendants<A.TextBody>())
        {
            var shape = txBody.Ancestors<Shape>().FirstOrDefault();
            string shapeBackground = ResolveShapeFill(shape) ?? slideBackground;

            foreach (var run in txBody.Descendants<A.Run>())
            {
                var rpr = run.RunProperties;
                if (rpr is null) continue;

                var solidFill = rpr.Descendants<A.SolidFill>().FirstOrDefault();
                if (solidFill is null) continue;

                string? rawHex = solidFill.RgbColorModelHex?.Val?.Value
                              ?? solidFill.SystemColor?.LastColor?.Value;
                if (string.IsNullOrWhiteSpace(rawHex)) continue;

                string foreground = NormaliseHex(rawHex);
                string background = shapeBackground;

                bool isBold = rpr.Bold?.Value == true;
                int? szInt = rpr.FontSize?.Value;
                bool isLarge = szInt.HasValue
                    ? (isBold ? szInt.Value >= LargeBoldThreshold : szInt.Value >= LargeNormalThreshold)
                    : false;

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
        }

        if (worstRun is not null)
        {
            string runText = string.Concat(worstRun.Descendants<A.Text>().Select(t => t.Text ?? string.Empty));

            yield return new A11yIssue
            {
                IssueId = Guid.NewGuid(),
                RuleId = RuleId,
                Title = "Insufficient colour contrast",
                Description = $"Text on slide {slideIndex + 1} has a contrast ratio of {worstRatio:F2}:1, below the required {worstThreshold:F1}:1 for {(worstIsLarge ? "large" : "normal")} text.",
                Severity = IssueSeverity.SERIOUS,
                Category = IssueCategory.COLOUR_CONTRAST,
                WcagCriterion = WcagCriterion.SC_1_4_3,
                RemediationType = RemediationType.HUMAN_REQUIRED,
                RemediationGuidance = $"Increase the contrast between text colour #{worstForeground} and background #{worstBackground} to at least {worstThreshold:F1}:1.",
                Location = PptxLocationHelper.FromSlide(slideIndex),
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

    private static string ResolveSlideBackground(SlidePart slidePart, PresentationDocument document)
    {
        var bg = slidePart.Slide.CommonSlideData?.Background;
        if (bg is not null)
        {
            var solidFill = bg.Descendants<A.SolidFill>().FirstOrDefault();
            if (solidFill is not null)
            {
                var hex = solidFill.RgbColorModelHex?.Val?.Value
                       ?? solidFill.SystemColor?.LastColor?.Value;
                if (!string.IsNullOrWhiteSpace(hex))
                    return NormaliseHex(hex);
            }
        }

        var layoutBg = slidePart.SlideLayoutPart?.SlideLayout?.CommonSlideData?.Background;
        if (layoutBg is not null)
        {
            var solidFill = layoutBg.Descendants<A.SolidFill>().FirstOrDefault();
            if (solidFill is not null)
            {
                var hex = solidFill.RgbColorModelHex?.Val?.Value
                       ?? solidFill.SystemColor?.LastColor?.Value;
                if (!string.IsNullOrWhiteSpace(hex))
                    return NormaliseHex(hex);
            }
        }

        var masterBg = slidePart.SlideLayoutPart?.SlideLayout
            .SlideLayoutPart?.SlideMasterPart?.SlideMaster?.CommonSlideData?.Background;
        if (masterBg is not null)
        {
            var solidFill = masterBg.Descendants<A.SolidFill>().FirstOrDefault();
            if (solidFill is not null)
            {
                var hex = solidFill.RgbColorModelHex?.Val?.Value
                       ?? solidFill.SystemColor?.LastColor?.Value;
                if (!string.IsNullOrWhiteSpace(hex))
                    return NormaliseHex(hex);
            }
        }

        return DefaultBackground;
    }

    private static string? ResolveShapeFill(Shape? shape)
    {
        if (shape is null) return null;

        var solidFill = shape.ShapeProperties?.Descendants<A.SolidFill>().FirstOrDefault();
        if (solidFill is null) return null;

        var hex = solidFill.RgbColorModelHex?.Val?.Value
               ?? solidFill.SystemColor?.LastColor?.Value;
        return string.IsNullOrWhiteSpace(hex) ? null : NormaliseHex(hex);
    }

    private static string NormaliseHex(string? hex)
    {
        if (string.IsNullOrWhiteSpace(hex)) return DefaultBackground;
        hex = hex.TrimStart('#');
        return hex.Length == 6 ? hex.ToUpperInvariant() : DefaultBackground;
    }

    private static string Truncate(string text, int max)
        => text.Length <= max ? text : text[..max] + "…";
}
