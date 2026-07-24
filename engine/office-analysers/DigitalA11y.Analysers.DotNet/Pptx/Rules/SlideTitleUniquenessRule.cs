using DigitalA11y.Analysers.DotNet.Pptx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Presentation;
using A = DocumentFormat.OpenXml.Drawing;

namespace DigitalA11y.Analysers.DotNet.Pptx.Rules;

// Distinct from SlideTitleRule (SC_2_4_2, is a title present at all): this checks that
// present titles are actually UNIQUE across the deck, the other half of V3's "Unique Slide
// Titles" checklist item. IPptxRule only calls in per-slide, so each call recomputes every
// slide's title from the shared PresentationDocument and flags this slide only if an
// EARLIER slide already used the same non-empty title — each duplicate group is reported
// once, on its second (and any later) occurrence, not on every member.
public class SlideTitleUniquenessRule : IPptxRule
{
    public string RuleId => PptxRuleIds.SlideTitleUniqueness;

    public IEnumerable<A11yIssue> AnalyseSlide(
        SlidePart slidePart,
        int slideIndex,
        PresentationDocument document)
    {
        var slideParts = document.PresentationPart?.SlideParts.ToList();
        if (slideParts is null || slideIndex >= slideParts.Count) yield break;

        var thisTitle = TitleText(slidePart);
        if (string.IsNullOrWhiteSpace(thisTitle)) yield break;

        for (int earlier = 0; earlier < slideIndex; earlier++)
        {
            var earlierTitle = TitleText(slideParts[earlier]);
            if (string.Equals(earlierTitle, thisTitle, StringComparison.OrdinalIgnoreCase))
            {
                yield return new A11yIssue
                {
                    IssueId = Guid.NewGuid(),
                    RuleId = RuleId,
                    Title = "Slide title duplicates an earlier slide",
                    Description = $"Slide {slideIndex + 1}'s title \"{thisTitle}\" is the same as slide {earlier + 1}'s. Duplicate titles make it impossible to tell slides apart when navigating by title alone.",
                    Severity = IssueSeverity.MODERATE,
                    Category = IssueCategory.DOCUMENT_TITLE,
                    WcagCriterion = WcagCriterion.SC_2_4_2,
                    RemediationType = RemediationType.HUMAN_REQUIRED,
                    RemediationGuidance = "Give this slide a title that distinguishes it from the other slide(s) sharing this title.",
                    Location = LocationHelper.FromSlide(slideIndex),
                    Evidence = new IssueEvidence
                    {
                        ComputedValue = thisTitle,
                        ExpectedValue = $"A title not already used by slide {earlier + 1}"
                    }
                };
                yield break;
            }
        }
    }

    private static string TitleText(SlidePart slidePart)
    {
        var spTree = slidePart.Slide.CommonSlideData?.ShapeTree;
        if (spTree is null) return string.Empty;

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
        if (titleShape is null) return string.Empty;

        return string.Concat(
            titleShape.Descendants<A.Text>().Select(t => t.Text ?? string.Empty)).Trim();
    }
}
