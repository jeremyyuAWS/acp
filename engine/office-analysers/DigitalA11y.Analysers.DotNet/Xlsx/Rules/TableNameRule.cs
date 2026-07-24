using DigitalA11y.Analysers.DotNet.Xlsx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using System.Text.RegularExpressions;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

public partial class TableNameRule : IXlsxRule
{
    public string RuleId => XlsxRuleIds.TableName;

    [GeneratedRegex(@"^Table\d+$", RegexOptions.IgnoreCase)]
    private static partial Regex DefaultTableNamePattern();

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

                var displayName = table.DisplayName?.Value ?? table.Name?.Value ?? string.Empty;
                if (DefaultTableNamePattern().IsMatch(displayName))
                {
                    yield return new A11yIssue
                    {
                        IssueId = Guid.NewGuid(),
                        RuleId = RuleId,
                        Title = "Table has a generic default name",
                        Description = $"The table \"{displayName}\" on sheet \"{sheetName}\" uses Excel's generic auto-generated name. A descriptive name helps assistive technology and formula users identify the table's purpose.",
                        Severity = IssueSeverity.MODERATE,
                        // Distinct from TableHeaderRule (SC_1_3_1, structural — does a header row
                        // exist) and from SheetNameRule (SC_2_4_6, sheet-tab labels). This is the
                        // table object's own DisplayName acting as its label — SC_2_4_2 Page Titled's
                        // table-scoped analogue, exactly as V3's checklist item "Name the Table" asks.
                        Category = IssueCategory.TABLES,
                        WcagCriterion = WcagCriterion.SC_2_4_2,
                        RemediationType = RemediationType.HUMAN_REQUIRED,
                        RemediationGuidance = "Select the table, open Table Design > Table Name, and set a descriptive name.",
                        Location = LocationHelper.FromTable(sheetName, displayName),
                        Evidence = new IssueEvidence
                        {
                            ComputedValue = displayName,
                            ExpectedValue = "A descriptive name (e.g. 'QuarterlySalesData')"
                        }
                    };
                }
            }
        }
    }
}
