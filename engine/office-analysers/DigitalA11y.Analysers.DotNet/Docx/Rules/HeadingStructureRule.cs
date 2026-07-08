using DigitalA11y.Analysers.DotNet.Docx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace DigitalA11y.Analysers.DotNet.Docx.Rules;

public class HeadingStructureRule : IDocxRule
{
    public string RuleId => DocxRuleIds.HeadingStructure;

    private static readonly Dictionary<string, int> HeadingLevels = new(StringComparer.OrdinalIgnoreCase)
    {
        ["Heading1"] = 1,
        ["Heading 1"] = 1,
        ["Heading2"] = 2,
        ["Heading 2"] = 2,
        ["Heading3"] = 3,
        ["Heading 3"] = 3,
        ["Heading4"] = 4,
        ["Heading 4"] = 4,
        ["Heading5"] = 5,
        ["Heading 5"] = 5,
        ["Heading6"] = 6,
        ["Heading 6"] = 6,
    };

    public IEnumerable<A11yIssue> Analyse(WordprocessingDocument document)
    {
        var body = document.MainDocumentPart?.Document?.Body;
        if (body is null) yield break;

        var paragraphs = body.Descendants<Paragraph>().ToList();

        var headings = new List<(int paragraphIndex, int level, string text)>();
        for (int i = 0; i < paragraphs.Count; i++)
        {
            var styleId = paragraphs[i].ParagraphProperties?.ParagraphStyleId?.Val?.Value ?? string.Empty;
            if (HeadingLevels.TryGetValue(styleId, out int level))
            {
                var text = string.Concat(paragraphs[i].Descendants<Text>().Select(t => t.Text));
                headings.Add((i, level, text));
            }
        }

        if (headings.Count == 0)
            yield break;

        if (headings.All(h => h.level != 1))
        {
            yield return MakeIssue(
                "No H1 heading found",
                "The document does not contain a Heading 1. Every document should have exactly one top-level heading.",
                new IssueLocation { Description = "docx:heading-structure" });
        }

        var h1s = headings.Where(h => h.level == 1).ToList();
        if (h1s.Count > 1)
        {
            foreach (var (paragraphIndex, _, text) in h1s.Skip(1))
            {
                yield return MakeIssue(
                    "Multiple H1 headings found",
                    $"A document should have only one Heading 1. Additional H1 found: \"{Truncate(text)}\".",
                    LocationHelper.FromParagraph(paragraphIndex),
                    snippet: text);
            }
        }

        int previousLevel = 0;
        foreach (var (paragraphIndex, level, text) in headings)
        {
            if (previousLevel > 0 && level > previousLevel + 1)
            {
                yield return MakeIssue(
                    $"Heading level skipped (H{previousLevel} → H{level})",
                    $"Heading levels should not be skipped. Found H{level} after H{previousLevel}: \"{Truncate(text)}\".",
                    LocationHelper.FromParagraph(paragraphIndex),
                    snippet: text);
            }
            previousLevel = level;
        }
    }

    private A11yIssue MakeIssue(string title, string description, IssueLocation location, string? snippet = null)
        => new()
        {
            IssueId = Guid.NewGuid(),
            RuleId = RuleId,
            Title = title,
            Description = description,
            Severity = IssueSeverity.MODERATE,
            Category = IssueCategory.HEADING_STRUCTURE,
            WcagCriterion = WcagCriterion.SC_1_3_1,
            RemediationType = RemediationType.HUMAN_REQUIRED,
            RemediationGuidance = "Ensure headings follow a logical hierarchy without skipping levels, with a single H1 at the top.",
            Location = location,
            Evidence = new IssueEvidence { Snippet = snippet }
        };

    private static string Truncate(string text, int max = 60)
        => text.Length <= max ? text : text[..max] + "…";
}
