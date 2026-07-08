using DigitalA11y.Analysers.DotNet.Pptx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Presentation;
using A = DocumentFormat.OpenXml.Drawing;

namespace DigitalA11y.Analysers.DotNet.Pptx.Rules;

public class SlideTitleRule : IPptxRule
{
    public string RuleId => PptxRuleIds.SlideTitle;

    public IEnumerable<A11yIssue> AnalyseSlide(
        SlidePart slidePart,
        int slideIndex,
        PresentationDocument document)
    {
        var spTree = slidePart.Slide.CommonSlideData?.ShapeTree;
        if (spTree is null)
        {
            yield return MakeIssue(slideIndex, "Slide has no shape tree — title placeholder is absent.");
            yield break;
        }

        Shape? titleShape = spTree.Descendants<Shape>()
            .FirstOrDefault(s =>
            {
                var ph = s.NonVisualShapeProperties
                          ?.ApplicationNonVisualDrawingProperties
                          ?.PlaceholderShape;
                if (ph is null) return false;
                var type = ph.Type?.Value;
                return type == PlaceholderValues.Title
                    || type == PlaceholderValues.CenteredTitle;
            });

        if (titleShape is null)
        {
            yield return MakeIssue(slideIndex, "No title placeholder found on this slide.");
            yield break;
        }

        var text = string.Concat(
            titleShape.Descendants<A.Text>().Select(t => t.Text ?? string.Empty)).Trim();

        if (string.IsNullOrWhiteSpace(text))
        {
            yield return MakeIssue(slideIndex, "The title placeholder is present but contains no text.");
        }
    }

    private A11yIssue MakeIssue(int slideIndex, string detail) => new()
    {
        IssueId = Guid.NewGuid(),
        RuleId = RuleId,
        Title = "Slide is missing a title",
        Description = $"Slide {slideIndex + 1} does not have a meaningful title. {detail}",
        Severity = IssueSeverity.SERIOUS,
        Category = IssueCategory.DOCUMENT_TITLE,
        WcagCriterion = WcagCriterion.SC_2_4_2,
        RemediationType = RemediationType.HUMAN_REQUIRED,
        RemediationGuidance = "Add a descriptive title to the slide title placeholder so users can identify and navigate to individual slides.",
        Location = LocationHelper.FromSlide(slideIndex),
        Evidence = new IssueEvidence
        {
            ComputedValue = "(no title)",
            ExpectedValue = "A concise, meaningful slide title"
        }
    };
}
