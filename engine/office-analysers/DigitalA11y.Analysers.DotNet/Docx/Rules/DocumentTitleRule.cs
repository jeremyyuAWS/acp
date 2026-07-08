using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;

namespace DigitalA11y.Analysers.DotNet.Docx.Rules;

public class DocumentTitleRule : IDocxRule
{
    public string RuleId => DocxRuleIds.DocumentTitle;

    public IEnumerable<A11yIssue> Analyse(WordprocessingDocument document)
    {
        var title = document.PackageProperties.Title;

        if (string.IsNullOrWhiteSpace(title))
        {
            yield return new A11yIssue
            {
                IssueId = Guid.NewGuid(),
                RuleId = RuleId,
                Title = "Document title not set",
                Description = "The document does not have a title in its core properties. A descriptive title helps users identify the document and is required by WCAG 2.4.2.",
                Severity = IssueSeverity.SERIOUS,
                Category = IssueCategory.DOCUMENT_TITLE,
                WcagCriterion = WcagCriterion.SC_2_4_2,
                RemediationType = RemediationType.HUMAN_REQUIRED,
                RemediationGuidance = "Set a descriptive title via File → Info → Properties → Title.",
                Location = new IssueLocation { Description = "docx:document-properties:title" },
                Evidence = new IssueEvidence
                {
                    Snippet = null,
                    ComputedValue = "(not set)",
                    ExpectedValue = "A descriptive document title"
                }
            };
        }
    }
}
