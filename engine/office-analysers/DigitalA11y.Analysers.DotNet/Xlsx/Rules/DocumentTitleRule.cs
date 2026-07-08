using DigitalA11y.Analysers.DotNet.Xlsx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

public class DocumentTitleRule : IXlsxRule
{
    public string RuleId => XlsxRuleIds.DocumentTitle;

    public IEnumerable<A11yIssue> Analyse(SpreadsheetDocument document)
    {
        var props = document.PackageProperties;
        var title = props.Title;

        if (string.IsNullOrWhiteSpace(title))
        {
            yield return new A11yIssue
            {
                IssueId = Guid.NewGuid(),
                RuleId = RuleId,
                Title = "Spreadsheet has no document title",
                Description = "The document Title property is absent or empty. A meaningful title helps users identify the document and is required for WCAG 2.4.2.",
                Severity = IssueSeverity.SERIOUS,
                Category = IssueCategory.DOCUMENT_TITLE,
                WcagCriterion = WcagCriterion.SC_2_4_2,
                RemediationType = RemediationType.AUTO_FIX,
                RemediationGuidance = "Add a descriptive title via File > Properties > Summary.",
                Location = LocationHelper.FromDocument(),
                Evidence = new IssueEvidence
                {
                    ComputedValue = "(empty)",
                    ExpectedValue = "A descriptive title for the spreadsheet"
                }
            };
        }
    }
}
