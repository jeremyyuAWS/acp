using System.Text.RegularExpressions;
using DigitalA11y.Analysers.DotNet.Docx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace DigitalA11y.Analysers.DotNet.Docx.Rules;

public class LinkPurposeRule : IDocxRule
{
    public string RuleId => DocxRuleIds.LinkPurpose;

    private static readonly HashSet<string> GenericLinkTexts = new(StringComparer.OrdinalIgnoreCase)
    {
        "click here", "here", "read more", "link", "more", "click", "this link", "url"
    };

    // A bare URL used as its own label ("https://example.com/report") is not a meaningful
    // link name — the same failure mode as "click here", just spelled differently. Matches
    // office_structure.py's _is_vague_link_text on the Python side (same "^(https?://|www\.)"
    // anchor), so DOCX/PPTX/XLSX/PDF agree on what counts as a raw URL.
    private static readonly Regex RawUrlPattern =
        new(@"^(https?://|www\.)", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    public IEnumerable<A11yIssue> Analyse(WordprocessingDocument document)
    {
        var body = document.MainDocumentPart?.Document?.Body;
        if (body is null) yield break;

        var paragraphs = body.Descendants<Paragraph>().ToList();

        for (int paraIdx = 0; paraIdx < paragraphs.Count; paraIdx++)
        {
            foreach (var hyperlink in paragraphs[paraIdx].Descendants<Hyperlink>())
            {
                string linkText = string.Concat(hyperlink.Descendants<Text>().Select(t => t.Text)).Trim();
                string url = ResolveUrl(hyperlink, document);

                bool isEmpty = string.IsNullOrWhiteSpace(linkText);
                bool isGeneric = !isEmpty && GenericLinkTexts.Contains(linkText);
                bool isRawUrl = !isEmpty && !isGeneric && RawUrlPattern.IsMatch(linkText);

                if (isEmpty || isGeneric || isRawUrl)
                {
                    string computed = isEmpty ? "(empty)" : linkText;

                    yield return new A11yIssue
                    {
                        IssueId = Guid.NewGuid(),
                        RuleId = RuleId,
                        Title = "Link text does not describe the link purpose",
                        Description = isEmpty
                            ? "A hyperlink has no text. Screen reader users will not know its destination."
                            : isRawUrl
                                ? $"The link text \"{linkText}\" is the raw URL, not a description of the link destination."
                                : $"The link text \"{linkText}\" is generic and does not describe the link destination.",
                        Severity = IssueSeverity.MODERATE,
                        Category = IssueCategory.LINKS,
                        WcagCriterion = WcagCriterion.SC_2_4_4,
                        RemediationType = RemediationType.HUMAN_REQUIRED,
                        RemediationGuidance = "Replace the link text with a description that identifies the destination or purpose of the link.",
                        Location = LocationHelper.FromHyperlink(paraIdx, url),
                        Evidence = new IssueEvidence
                        {
                            Snippet = computed,
                            ComputedValue = computed,
                            ExpectedValue = "Descriptive link text that identifies the destination",
                            AdditionalContext = new Dictionary<string, string>
                            {
                                ["url"] = url
                            }
                        }
                    };
                }
            }
        }
    }

    private static string ResolveUrl(Hyperlink hyperlink, WordprocessingDocument document)
    {
        var relationshipId = hyperlink.Id?.Value;
        if (relationshipId is null) return string.Empty;

        try
        {
            var rel = document.MainDocumentPart?.HyperlinkRelationships
                              .FirstOrDefault(r => r.Id == relationshipId);
            return rel?.Uri?.ToString() ?? string.Empty;
        }
        catch
        {
            return string.Empty;
        }
    }
}
