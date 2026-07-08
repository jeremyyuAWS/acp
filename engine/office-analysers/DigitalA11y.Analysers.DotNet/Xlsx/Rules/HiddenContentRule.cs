using DigitalA11y.Analysers.DotNet.Xlsx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

public class HiddenContentRule : IXlsxRule
{
    public string RuleId => XlsxRuleIds.HiddenContent;

    public IEnumerable<A11yIssue> Analyse(SpreadsheetDocument document)
    {
        var workbookPart = document.WorkbookPart;
        if (workbookPart is null) yield break;

        var sheets = workbookPart.Workbook.Sheets;
        if (sheets is null) yield break;

        var sharedStrings = workbookPart.SharedStringTablePart?.SharedStringTable;

        foreach (DocumentFormat.OpenXml.Spreadsheet.Sheet sheet in sheets)
        {
            var sheetName = sheet.Name?.Value ?? "Unknown";
            var sheetId = sheet.Id?.Value;
            if (sheetId is null) continue;

            if (workbookPart.GetPartById(sheetId) is not WorksheetPart worksheetPart)
                continue;

            var worksheetData = worksheetPart.Worksheet?.GetFirstChild<SheetData>();
            if (worksheetData is null) continue;

            foreach (var row in worksheetData.Descendants<Row>())
            {
                var hidden = row.Hidden?.Value == true;
                if (!hidden) continue;

                var hasContent = row.Descendants<Cell>()
                    .Any(c => !string.IsNullOrWhiteSpace(GetCellValue(c, sharedStrings)));

                if (hasContent)
                {
                    yield return new A11yIssue
                    {
                        IssueId = Guid.NewGuid(),
                        RuleId = RuleId,
                        Title = "Hidden row contains content",
                        Description = $"Row {row.RowIndex?.Value} on sheet \"{sheetName}\" is hidden but contains data. Hidden content may be inaccessible to assistive technology users.",
                        Severity = IssueSeverity.MODERATE,
                        Category = IssueCategory.READING_ORDER,
                        WcagCriterion = WcagCriterion.SC_1_3_2,
                        RemediationType = RemediationType.HUMAN_REQUIRED,
                        RemediationGuidance = "Unhide the row or remove the content if it is no longer needed.",
                        Location = LocationHelper.FromRow(sheetName, row.RowIndex?.Value ?? 0),
                        Evidence = new IssueEvidence
                        {
                            ComputedValue = "Row is hidden",
                            ExpectedValue = "Row should be visible or contain no content"
                        }
                    };
                }
            }

            var columns = worksheetPart.Worksheet?.GetFirstChild<Columns>();
            if (columns is null) continue;

            foreach (var col in columns.Descendants<Column>())
            {
                var hidden = col.Hidden?.Value == true;
                if (!hidden) continue;

                var minCol = col.Min?.Value ?? 0;
                var maxCol = col.Max?.Value ?? 0;

                var hasContent = worksheetData.Descendants<Cell>()
                    .Any(c =>
                    {
                        var colIndex = GetColumnIndex(c.CellReference?.Value);
                        return colIndex >= minCol && colIndex <= maxCol &&
                               !string.IsNullOrWhiteSpace(GetCellValue(c, sharedStrings));
                    });

                if (hasContent)
                {
                    yield return new A11yIssue
                    {
                        IssueId = Guid.NewGuid(),
                        RuleId = RuleId,
                        Title = "Hidden column contains content",
                        Description = $"Column {minCol} on sheet \"{sheetName}\" is hidden but contains data. Hidden content may be inaccessible to assistive technology users.",
                        Severity = IssueSeverity.MODERATE,
                        Category = IssueCategory.READING_ORDER,
                        WcagCriterion = WcagCriterion.SC_1_3_2,
                        RemediationType = RemediationType.HUMAN_REQUIRED,
                        RemediationGuidance = "Unhide the column or remove the content if it is no longer needed.",
                        Location = LocationHelper.FromColumn(sheetName, minCol),
                        Evidence = new IssueEvidence
                        {
                            ComputedValue = "Column is hidden",
                            ExpectedValue = "Column should be visible or contain no content"
                        }
                    };
                }
            }
        }
    }

    private static string? GetCellValue(Cell cell, SharedStringTable? sharedStrings)
    {
        var value = cell.CellValue?.Text;
        if (value is null) return null;

        if (cell.DataType?.Value == CellValues.SharedString && sharedStrings is not null)
        {
            if (int.TryParse(value, out var idx))
            {
                var item = sharedStrings.ElementAtOrDefault(idx) as SharedStringItem;
                return item?.InnerText;
            }
        }

        return value;
    }

    private static uint GetColumnIndex(string? cellReference)
    {
        if (string.IsNullOrEmpty(cellReference)) return 0;

        uint index = 0;
        foreach (var ch in cellReference)
        {
            if (!char.IsLetter(ch)) break;
            index = index * 26 + (uint)(char.ToUpperInvariant(ch) - 'A' + 1);
        }
        return index;
    }
}
