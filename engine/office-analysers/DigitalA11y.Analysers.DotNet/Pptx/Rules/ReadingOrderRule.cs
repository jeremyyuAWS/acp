using DigitalA11y.Analysers.DotNet.Pptx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Presentation;

namespace DigitalA11y.Analysers.DotNet.Pptx.Rules;

public class ReadingOrderRule : IPptxRule
{
    public string RuleId => PptxRuleIds.ReadingOrder;

    public IEnumerable<A11yIssue> AnalyseSlide(
        SlidePart slidePart,
        int slideIndex,
        PresentationDocument document)
    {
        var spTree = slidePart.Slide.CommonSlideData?.ShapeTree;
        if (spTree is null) yield break;

        var shapesWithPosition = spTree
            .OfType<Shape>()
            .Select((shape, tabOrder) =>
            {
                var xfrm = shape.ShapeProperties?.Transform2D;
                var off = xfrm?.Offset;
                return new
                {
                    TabOrder = tabOrder,
                    Name = shape.NonVisualShapeProperties?.NonVisualDrawingProperties?.Name?.Value ?? tabOrder.ToString(),
                    Top = off?.Y?.Value ?? long.MaxValue,
                    Left = off?.X?.Value ?? long.MaxValue,
                    HasPos = off is not null
                };
            })
            .Where(s => s.HasPos)
            .ToList();

        if (shapesWithPosition.Count < 2) yield break;

        var visualOrder = shapesWithPosition
            .OrderBy(s => s.Top)
            .ThenBy(s => s.Left)
            .Select((s, i) => new { s.Name, s.TabOrder, VisualRank = i })
            .ToList();

        bool hasOrderMismatch = visualOrder.Any(v =>
            Math.Abs(v.VisualRank - v.TabOrder) > 1);

        if (hasOrderMismatch)
        {
            yield return new A11yIssue
            {
                IssueId = Guid.NewGuid(),
                RuleId = RuleId,
                Title = "Reading order may not match visual order",
                Description = $"On slide {slideIndex + 1}, the tab/reading order of shapes does not match their visual top-to-bottom, left-to-right order. Screen readers will announce content in tab order, which may confuse users.",
                Severity = IssueSeverity.SERIOUS,
                Category = IssueCategory.READING_ORDER,
                WcagCriterion = WcagCriterion.SC_1_3_2,
                RemediationType = RemediationType.HUMAN_REQUIRED,
                RemediationGuidance = "Open the Selection Pane in PowerPoint (Home > Arrange > Selection Pane) and reorder shapes so the tab order matches the intended reading sequence.",
                Location = LocationHelper.FromSlide(slideIndex),
                Evidence = new IssueEvidence
                {
                    ComputedValue = "Tab order differs from visual order by more than 1 position",
                    ExpectedValue = "Tab order matches visual top-to-bottom, left-to-right sequence"
                }
            };
        }
    }
}
