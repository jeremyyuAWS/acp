using DigitalA11y.Analysers.DotNet.Docx.Helpers;
using DigitalA11y.Analysers.DotNet.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using DW = DocumentFormat.OpenXml.Drawing.Wordprocessing;

namespace DigitalA11y.Analysers.DotNet.Docx.Rules;

public class AltTextRule : IDocxRule
{
    public string RuleId => DocxRuleIds.AltText;

    private static readonly HashSet<string> PlaceholderPatterns = new(StringComparer.OrdinalIgnoreCase)
    {
        "image", "picture", "photo", "img", "figure"
    };

    public IEnumerable<A11yIssue> Analyse(WordprocessingDocument document)
    {
        var body = document.MainDocumentPart?.Document?.Body;
        if (body is null) yield break;

        var paragraphs = body.Descendants<Paragraph>().ToList();

        for (int paraIdx = 0; paraIdx < paragraphs.Count; paraIdx++)
        {
            var para = paragraphs[paraIdx];

            // Inline drawings
            foreach (var inline in para.Descendants<DW.Inline>())
            {
                var props = inline.DocProperties;
                var issue = CheckDocProperties(props, paraIdx, props?.Id is null ? "unknown" : props.Id.ToString()!);
                if (issue is not null) yield return issue;
            }

            // Anchored drawings
            foreach (var anchor in para.Descendants<DW.Anchor>())
            {
                var props = anchor.Descendants<DW.DocProperties>().FirstOrDefault();
                var issue = CheckDocProperties(props, paraIdx, props?.Id is null ? "unknown" : props.Id.ToString()!);
                if (issue is not null) yield return issue;
            }
        }
    }

    private A11yIssue? CheckDocProperties(DW.DocProperties? props, int paragraphIndex, string drawingId)
    {
        if (props is null)
        {
            return MakeIssue(paragraphIndex, drawingId, "(no DocProperties)", "Alt text is missing — DocProperties element not present.");
        }

        var description = props.Description?.Value;

        if (string.IsNullOrWhiteSpace(description))
        {
            if (AltTextHeuristics.IsMarkedDecorative(props)) return null;
            return MakeIssue(paragraphIndex, drawingId, "(empty)", "The image has no alt text description.");
        }

        var trimmed = description.Trim();
        if (PlaceholderPatterns.Contains(trimmed))
        {
            return MakeIssue(paragraphIndex, drawingId, trimmed, $"The alt text \"{trimmed}\" is a non-descriptive placeholder.");
        }

        if (AltTextHeuristics.LooksLikeFilenameOrPath(trimmed))
        {
            return MakeIssue(paragraphIndex, drawingId, trimmed, $"The alt text \"{trimmed}\" is a file name or path, not a description of the image.");
        }

        return null;
    }

    private A11yIssue MakeIssue(int paragraphIndex, string drawingId, string computed, string detail)
        => new()
        {
            IssueId = Guid.NewGuid(),
            RuleId = RuleId,
            Title = "Image missing meaningful alt text",
            Description = $"An image does not have descriptive alternative text. {detail}",
            Severity = IssueSeverity.CRITICAL,
            Category = IssueCategory.ALT_TEXT,
            WcagCriterion = WcagCriterion.SC_1_1_1,
            RemediationType = RemediationType.HUMAN_REQUIRED,
            RemediationGuidance = "Right-click the image, choose 'Edit Alt Text', and provide a concise description of the image content and function.",
            Location = LocationHelper.FromDrawing(paragraphIndex, drawingId),
            Evidence = new IssueEvidence
            {
                ComputedValue = computed,
                ExpectedValue = "A concise, meaningful description of the image"
            }
        };
}
