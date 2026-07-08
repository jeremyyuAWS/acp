using DigitalA11y.Analysers.DotNet.Xlsx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using System.Text.RegularExpressions;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

public partial class SheetNameRule : IXlsxRule
{
    public string RuleId => XlsxRuleIds.SheetName;

    [GeneratedRegex(@"^Sheet\d+$", RegexOptions.IgnoreCase)]
    private static partial Regex DefaultSheetNamePattern();

    public IEnumerable<A11yIssue> Analyse(SpreadsheetDocument document)
    {
        var sheets = document.WorkbookPart?.Workbook.Sheets;
        if (sheets is null) yield break;

        foreach (DocumentFormat.OpenXml.Spreadsheet.Sheet sheet in sheets)
        {
            var name = sheet.Name?.Value ?? string.Empty;
            if (DefaultSheetNamePattern().IsMatch(name))
            {
                yield return new A11yIssue
                {
                    IssueId = Guid.NewGuid(),
                    RuleId = RuleId,
                    Title = "Sheet has a generic default name",
                    Description = $"The sheet named \"{name}\" uses a generic default name. Meaningful sheet names help users navigate and understand the spreadsheet structure.",
                    Severity = IssueSeverity.MODERATE,
                    Category = IssueCategory.DOCUMENT_TITLE,
                    WcagCriterion = WcagCriterion.SC_2_4_2,
                    RemediationType = RemediationType.HUMAN_REQUIRED,
                    RemediationGuidance = "Double-click the sheet tab and rename it to a concise, descriptive name.",
                    Location = LocationHelper.FromSheet(name),
                    Evidence = new IssueEvidence
                    {
                        ComputedValue = name,
                        ExpectedValue = "A descriptive name (e.g. 'Q1 Sales Data')"
                    }
                };
            }
        }
    }
}
