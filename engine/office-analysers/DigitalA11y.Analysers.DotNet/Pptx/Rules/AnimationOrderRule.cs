using DigitalA11y.Analysers.DotNet.Pptx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Presentation;

namespace DigitalA11y.Analysers.DotNet.Pptx.Rules;

public class AnimationOrderRule : IPptxRule
{
    public string RuleId => PptxRuleIds.AnimationOrder;

    public IEnumerable<A11yIssue> AnalyseSlide(
        SlidePart slidePart,
        int slideIndex,
        PresentationDocument document)
    {
        var timing = slidePart.Slide.Timing;
        if (timing is null) yield break;

        var autoNodes = timing.Descendants<CommonTimeNode>()
            .Where(IsAutoAdvancing)
            .ToList();

        if (autoNodes.Count > 0)
        {
            yield return new A11yIssue
            {
                IssueId = Guid.NewGuid(),
                RuleId = RuleId,
                Title = "Animations may auto-advance without user control",
                Description = $"Slide {slideIndex + 1} contains {autoNodes.Count} animation(s) configured to play automatically without a manual trigger. This can prevent users from controlling the pace of content.",
                Severity = IssueSeverity.MODERATE,
                Category = IssueCategory.READING_ORDER,
                WcagCriterion = WcagCriterion.SC_2_1_1,
                RemediationType = RemediationType.HUMAN_REQUIRED,
                RemediationGuidance = "In the Animations panel, change the animation start trigger from 'After Previous' or 'With Previous' to 'On Click' so users control when content appears.",
                Location = LocationHelper.FromSlide(slideIndex),
                Evidence = new IssueEvidence
                {
                    ComputedValue = $"{autoNodes.Count} auto-advancing animation node(s) detected",
                    ExpectedValue = "All animations triggered by user interaction (On Click)"
                }
            };
        }
    }

    private static bool IsAutoAdvancing(CommonTimeNode node)
    {
        if (node.NodeType is null) return false;

        var type = node.NodeType.Value;

        if (type == TimeNodeValues.MainSequence || type == TimeNodeValues.InteractiveSequence)
            return false;

        var parent = node.Parent as CommonTimeNode;
        if (parent is null) return false;

        bool parentIsMainSeq = parent.NodeType?.Value == TimeNodeValues.MainSequence;
        if (!parentIsMainSeq) return false;

        var conditions = node.StartConditionList?.OfType<Condition>().ToList() ?? [];
        bool hasClickTrigger = conditions.Any(c =>
            c.Event?.Value == TriggerEventValues.OnClick);

        return !hasClickTrigger;
    }
}
