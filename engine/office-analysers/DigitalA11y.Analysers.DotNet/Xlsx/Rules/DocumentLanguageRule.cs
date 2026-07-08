using DigitalA11y.Analysers.DotNet.Xlsx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

public class DocumentLanguageRule : IXlsxRule
{
    public string RuleId => XlsxRuleIds.DocumentLanguage;

    public IEnumerable<A11yIssue> Analyse(SpreadsheetDocument document)
    {
        var language = document.PackageProperties.Language;

        if (string.IsNullOrWhiteSpace(language))
        {
            yield return new A11yIssue
            {
                IssueId = Guid.NewGuid(),
                RuleId = RuleId,
                Title = "Spreadsheet language is not set",
                Description = "The document Language property is absent or empty. Assistive technologies need a declared language to use correct pronunciation rules.",
                Severity = IssueSeverity.SERIOUS,
                Category = IssueCategory.LANGUAGE,
                WcagCriterion = WcagCriterion.SC_3_1_1,
                RemediationType = RemediationType.AUTO_FIX,
                RemediationGuidance = "Set the document language via File > Options > Language.",
                Location = LocationHelper.FromDocument(),
                Evidence = new IssueEvidence
                {
                    ComputedValue = "(empty)",
                    ExpectedValue = "A BCP 47 language tag such as 'en-GB'"
                }
            };
        }
    }
}
