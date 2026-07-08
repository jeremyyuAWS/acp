using DigitalA11y.Analysers.DotNet.Xlsx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

public class MergedCellsRule : IXlsxRule
{
    public string RuleId => XlsxRuleIds.MergedCells;

    private const int MergedCellThreshold = 20;

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

            var mergeCells = worksheetPart.Worksheet?.GetFirstChild<MergeCells>();
            var count = mergeCells?.Count?.Value ?? 0;

            if (count > MergedCellThreshold)
            {
                yield return new A11yIssue
                {
                    IssueId = Guid.NewGuid(),
                    RuleId = RuleId,
                    Title = "Excessive merged cells disrupt reading order",
                    Description = $"Sheet \"{sheetName}\" has {count} merged cell ranges, which exceeds the threshold of {MergedCellThreshold}. Excessive merging makes it difficult for assistive technologies to interpret the logical reading order.",
                    Severity = IssueSeverity.MODERATE,
                    Category = IssueCategory.READING_ORDER,
                    WcagCriterion = WcagCriterion.SC_1_3_2,
                    RemediationType = RemediationType.HUMAN_REQUIRED,
                    RemediationGuidance = "Review merged cells and use formatting alternatives (e.g. centre-align across selection) where possible to reduce merging.",
                    Location = LocationHelper.FromSheet(sheetName),
                    Evidence = new IssueEvidence
                    {
                        ComputedValue = $"{count} merged cell ranges",
                        ExpectedValue = $"Fewer than {MergedCellThreshold} merged cell ranges per sheet"
                    }
                };
            }
        }
    }
}
