using DigitalA11y.Analysers.DotNet.Xlsx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

public class BlankWorksheetRule : IXlsxRule
{
    public string RuleId => XlsxRuleIds.BlankWorksheet;

    public IEnumerable<A11yIssue> Analyse(SpreadsheetDocument document)
    {
        var workbookPart = document.WorkbookPart;
        if (workbookPart is null) yield break;

        var sheets = workbookPart.Workbook.Sheets;
        if (sheets is null) yield break;

        var sharedStrings = workbookPart.SharedStringTablePart?.SharedStringTable;

        foreach (DocumentFormat.OpenXml.Spreadsheet.Sheet sheet in sheets)
        {
            // A hidden sheet is never presented to a user tabbing through the workbook —
            // blank or not, there is no navigation experience to flag it for.
            var state = sheet.State?.Value;
            if (state is not null && state != SheetStateValues.Visible) continue;

            var sheetName = sheet.Name?.Value ?? "Unknown";
            var sheetId = sheet.Id?.Value;
            if (sheetId is null) continue;

            if (workbookPart.GetPartById(sheetId) is not WorksheetPart worksheetPart)
                continue;

            if (HasCellContent(worksheetPart, sharedStrings)) continue;
            if (HasAnchoredDrawing(worksheetPart)) continue;

            yield return new A11yIssue
            {
                IssueId = Guid.NewGuid(),
                RuleId = RuleId,
                Title = "Sheet has no content",
                Description = $"The sheet named \"{sheetName}\" contains no cell data, charts, or images. Blank sheets add confusing, empty stops for screen reader users navigating between sheet tabs.",
                Severity = IssueSeverity.MODERATE,
                Category = IssueCategory.READING_ORDER,
                WcagCriterion = WcagCriterion.SC_1_3_2,
                RemediationType = RemediationType.HUMAN_REQUIRED,
                RemediationGuidance = "Delete the sheet if it is not needed, or add content to it.",
                Location = LocationHelper.FromSheet(sheetName),
                Evidence = new IssueEvidence
                {
                    ComputedValue = "Sheet has no cell data, charts, or images",
                    ExpectedValue = "Sheet should contain content or be removed"
                }
            };
        }
    }

    /// <summary>
    /// Checks actual cell values/formulas rather than the sheet's dimension ("used range")
    /// record — that record reflects the historical maximum extent a writer ever touched
    /// and stays inflated even after every cell in it has been cleared, so it cannot be
    /// trusted to indicate live content.
    /// </summary>
    private static bool HasCellContent(WorksheetPart worksheetPart, SharedStringTable? sharedStrings)
    {
        var worksheetData = worksheetPart.Worksheet?.GetFirstChild<SheetData>();
        if (worksheetData is null) return false;

        foreach (var cell in worksheetData.Descendants<Cell>())
        {
            if (cell.CellFormula is not null) return true;
            if (!string.IsNullOrWhiteSpace(CellValueHelper.GetCellValue(cell, sharedStrings))) return true;
        }

        return false;
    }

    private static bool HasAnchoredDrawing(WorksheetPart worksheetPart)
    {
        var drawingsPart = worksheetPart.DrawingsPart;
        if (drawingsPart?.WorksheetDrawing is null) return false;

        var wsDr = drawingsPart.WorksheetDrawing;
        return wsDr.Descendants<DocumentFormat.OpenXml.Drawing.Spreadsheet.Picture>().Any()
            || wsDr.Descendants<DocumentFormat.OpenXml.Drawing.Spreadsheet.GraphicFrame>().Any();
    }
}
