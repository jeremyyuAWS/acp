using DigitalA11y.Analysers.DotNet.Xlsx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

public class TableHeaderRule : IXlsxRule
{
    public string RuleId => XlsxRuleIds.TableHeaders;

    public IEnumerable<A11yIssue> Analyse(SpreadsheetDocument document)
    {
        var workbookPart = document.WorkbookPart;
        if (workbookPart is null) yield break;

        var sheets = workbookPart.Workbook.Sheets;
        if (sheets is null) yield break;

        foreach (DocumentFormat.OpenXml.Spreadsheet.Sheet sheet in sheets)
        {
            var sheetName = sheet.Name?.Value ?? "Unknown";
            var sheetId = sheet.Id?.Value;
            if (sheetId is null) continue;

            if (workbookPart.GetPartById(sheetId) is not WorksheetPart worksheetPart)
                continue;

            foreach (var tablePart in worksheetPart.TableDefinitionParts)
            {
                var table = tablePart.Table;
                if (table is null) continue;

                var tableName = table.DisplayName?.Value ?? table.Name?.Value ?? "Unknown";

                var headerRowCount = table.HeaderRowCount?.Value ?? 1u;
                if (headerRowCount == 0)
                {
                    yield return new A11yIssue
                    {
                        IssueId = Guid.NewGuid(),
                        RuleId = RuleId,
                        Title = "Table has no header row",
                        Description = $"The table \"{tableName}\" on sheet \"{sheetName}\" has no header row. Header rows are required for assistive technologies to identify column context.",
                        Severity = IssueSeverity.SERIOUS,
                        Category = IssueCategory.TABLES,
                        WcagCriterion = WcagCriterion.SC_1_3_1,
                        RemediationType = RemediationType.HUMAN_REQUIRED,
                        RemediationGuidance = "Convert the first row to a header row via Table Design > Header Row.",
                        Location = LocationHelper.FromTable(sheetName, tableName),
                        Evidence = new IssueEvidence
                        {
                            ComputedValue = "HeaderRowCount = 0",
                            ExpectedValue = "HeaderRowCount >= 1"
                        }
                    };
                }
            }
        }
    }
}
