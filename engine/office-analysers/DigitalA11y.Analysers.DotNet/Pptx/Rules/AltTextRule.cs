using DigitalA11y.Analysers.DotNet.Helpers;
using DigitalA11y.Analysers.DotNet.Pptx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Presentation;

namespace DigitalA11y.Analysers.DotNet.Pptx.Rules;

public class AltTextRule : IPptxRule
{
    public string RuleId => PptxRuleIds.AltText;

    private static readonly HashSet<string> PlaceholderPatterns =
        new(StringComparer.OrdinalIgnoreCase)
        { "image", "picture", "photo", "slide" };

    public IEnumerable<A11yIssue> AnalyseSlide(
        SlidePart slidePart,
        int slideIndex,
        PresentationDocument document)
    {
        var spTree = slidePart.Slide.CommonSlideData?.ShapeTree;
        if (spTree is null) yield break;

        foreach (var pic in spTree.Descendants<Picture>())
        {
            var nvPr = pic.NonVisualPictureProperties?.NonVisualDrawingProperties;
            if (nvPr is null) continue;
            if (nvPr.Hidden?.Value == true) continue;

            var issue = EvaluateDrawingProps(
                nvPr.Name?.Value ?? "unknown",
                nvPr.Description?.Value,
                slideIndex,
                nvPr);
            if (issue is not null) yield return issue;
        }

        foreach (var gf in spTree.Descendants<GraphicFrame>())
        {
            var nvPr = gf.NonVisualGraphicFrameProperties?.NonVisualDrawingProperties;
            if (nvPr is null) continue;
            if (nvPr.Hidden?.Value == true) continue;

            var issue = EvaluateDrawingProps(
                nvPr.Name?.Value ?? "unknown",
                nvPr.Description?.Value,
                slideIndex,
                nvPr);
            if (issue is not null) yield return issue;
        }
    }

    private A11yIssue? EvaluateDrawingProps(
        string elementName,
        string? description,
        int slideIndex,
        DocumentFormat.OpenXml.OpenXmlElement nvPr)
    {
        if (string.IsNullOrWhiteSpace(description))
        {
            if (AltTextHeuristics.IsMarkedDecorative(nvPr)) return null;
            return MakeIssue(slideIndex, elementName, "(empty)", "The element has no alt text description.");
        }

        var trimmed = description.Trim();
        if (PlaceholderPatterns.Contains(trimmed))
        {
            return MakeIssue(slideIndex, elementName, trimmed,
                $"The alt text \"{trimmed}\" is a non-descriptive placeholder.");
        }

        if (AltTextHeuristics.LooksLikeFilenameOrPath(trimmed))
        {
            return MakeIssue(slideIndex, elementName, trimmed,
                $"The alt text \"{trimmed}\" is a file name or path, not a description of the image.");
        }

        return null;
    }

    private A11yIssue MakeIssue(
        int slideIndex, string elementId, string computed, string detail) => new()
        {
            IssueId = Guid.NewGuid(),
            RuleId = RuleId,
            Title = "Image or graphic missing meaningful alt text",
            Description = $"An image or graphic on slide {slideIndex + 1} does not have descriptive alternative text. {detail}",
            Severity = IssueSeverity.CRITICAL,
            Category = IssueCategory.ALT_TEXT,
            WcagCriterion = WcagCriterion.SC_1_1_1,
            RemediationType = RemediationType.HUMAN_REQUIRED,
            RemediationGuidance = "Right-click the image, choose 'Edit Alt Text', and provide a concise description of the image content and purpose.",
            Location = LocationHelper.FromSlideElement(slideIndex, elementId),
            Evidence = new IssueEvidence
            {
                ComputedValue = computed,
                ExpectedValue = "A concise, meaningful description of the image"
            }
        };
}
