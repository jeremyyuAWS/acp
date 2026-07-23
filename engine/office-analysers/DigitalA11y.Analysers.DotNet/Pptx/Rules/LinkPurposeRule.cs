using System.Text.RegularExpressions;
using DigitalA11y.Analysers.DotNet.Pptx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using A = DocumentFormat.OpenXml.Drawing;

namespace DigitalA11y.Analysers.DotNet.Pptx.Rules;

public class LinkPurposeRule : IPptxRule
{
    public string RuleId => PptxRuleIds.LinkPurpose;

    private static readonly HashSet<string> GenericLinkTexts =
        new(StringComparer.OrdinalIgnoreCase)
        { "click here", "here", "read more", "link", "more" };

    // Mirrors DOCX's LinkPurposeRule and office_structure.py's _is_vague_link_text — a bare
    // URL used as its own label is the same failure as "click here", spelled differently.
    private static readonly Regex RawUrlPattern =
        new(@"^(https?://|www\.)", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    public IEnumerable<A11yIssue> AnalyseSlide(
        SlidePart slidePart,
        int slideIndex,
        PresentationDocument document)
    {
        var spTree = slidePart.Slide.CommonSlideData?.ShapeTree;
        if (spTree is null) yield break;

        foreach (var run in slidePart.Slide.Descendants<A.Run>())
        {
            A.RunProperties? rpr = run.RunProperties;
            if (rpr is null) continue;

            var hlClick = rpr.Elements<A.HyperlinkOnClick>().FirstOrDefault();
            var hlHover = rpr.Elements<A.HyperlinkOnMouseOver>().FirstOrDefault();

            if (hlClick is null && hlHover is null) continue;

            var relId = hlClick?.Id?.Value ?? hlHover?.Id?.Value;
            string url = string.Empty;
            if (relId is not null)
            {
                try
                {
                    var rel = slidePart.HyperlinkRelationships
                        .FirstOrDefault(r => r.Id == relId);
                    url = rel?.Uri?.ToString() ?? string.Empty;
                }
                catch
                {
                    url = string.Empty;
                }
            }

            var para = run.Ancestors<A.Paragraph>().FirstOrDefault();
            string linkText = para is not null
                ? string.Concat(para.Descendants<A.Text>().Select(t => t.Text ?? string.Empty)).Trim()
                : string.Concat(run.Descendants<A.Text>().Select(t => t.Text ?? string.Empty)).Trim();

            bool isEmpty = string.IsNullOrWhiteSpace(linkText);
            bool isGeneric = !isEmpty && GenericLinkTexts.Contains(linkText);
            bool isRawUrl = !isEmpty && !isGeneric && RawUrlPattern.IsMatch(linkText);

            if (isEmpty || isGeneric || isRawUrl)
            {
                yield return new A11yIssue
                {
                    IssueId = Guid.NewGuid(),
                    RuleId = RuleId,
                    Title = "Link text does not describe its purpose",
                    Description = isRawUrl
                        ? $"A hyperlink on slide {slideIndex + 1} uses the raw URL \"{linkText}\" as its text, not a description of the destination."
                        : $"A hyperlink on slide {slideIndex + 1} has non-descriptive link text \"{(isEmpty ? "(empty)" : linkText)}\". Users cannot determine the link destination without context.",
                    Severity = IssueSeverity.MODERATE,
                    Category = IssueCategory.LINKS,
                    WcagCriterion = WcagCriterion.SC_2_4_4,
                    RemediationType = RemediationType.HUMAN_REQUIRED,
                    RemediationGuidance = "Replace generic link text with a phrase that describes the destination or purpose, e.g. 'Read the full accessibility report'.",
                    Location = LocationHelper.FromSlide(slideIndex),
                    Evidence = new IssueEvidence
                    {
                        Snippet = linkText,
                        ComputedValue = string.IsNullOrWhiteSpace(linkText) ? "(empty)" : linkText,
                        ExpectedValue = "Descriptive text identifying the link purpose",
                        AdditionalContext = new Dictionary<string, string>
                        {
                            ["url"] = url
                        }
                    }
                };

                // One issue per slide — all runs share the same Location key.
                yield break;
            }
        }
    }
}
