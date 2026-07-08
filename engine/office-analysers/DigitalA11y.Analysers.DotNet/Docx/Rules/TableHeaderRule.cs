using DigitalA11y.Analysers.DotNet.Docx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace DigitalA11y.Analysers.DotNet.Docx.Rules;

public class TableHeaderRule : IDocxRule
{
    public string RuleId => DocxRuleIds.TableHeaders;

    public IEnumerable<A11yIssue> Analyse(WordprocessingDocument document)
    {
        var body = document.MainDocumentPart?.Document?.Body;
        if (body is null) yield break;

        var tables = body.Descendants<Table>().ToList();

        for (int tableIdx = 0; tableIdx < tables.Count; tableIdx++)
        {
            var rows = tables[tableIdx].Descendants<TableRow>().ToList();
            if (rows.Count <= 1) continue;

            if (!HasHeaderRow(rows[0]))
            {
                yield return new A11yIssue
                {
                    IssueId = Guid.NewGuid(),
                    RuleId = RuleId,
                    Title = "Table has no header row",
                    Description = "The table has multiple rows but its first row is not marked as a header row. Header rows allow screen readers to associate data cells with their column headings.",
                    Severity = IssueSeverity.SERIOUS,
                    Category = IssueCategory.TABLES,
                    WcagCriterion = WcagCriterion.SC_1_3_1,
                    RemediationType = RemediationType.HUMAN_REQUIRED,
                    RemediationGuidance = "Select the first row of the table, open Table Properties → Row, and check 'Repeat as header row at the top of each page'. Apply the 'Table Header' paragraph style to cells in that row.",
                    Location = LocationHelper.FromTable(tableIdx, 0),
                    Evidence = new IssueEvidence
                    {
                        ComputedValue = $"Table {tableIdx + 1}: {rows.Count} rows, no header row detected",
                        ExpectedValue = "First row marked as header (TableHeader style or TblHeader property)"
                    }
                };
            }
        }
    }

    private static bool HasHeaderRow(TableRow row)
    {
        if (row.TableRowProperties?.Descendants<TableHeader>().Any() == true)
            return true;

        var cells = row.Descendants<TableCell>().ToList();
        if (cells.Count == 0) return false;

        return cells.All(cell =>
        {
            var styleId = cell.Descendants<Paragraph>()
                             .Select(p => p.ParagraphProperties?.ParagraphStyleId?.Val?.Value)
                             .FirstOrDefault(s => s is not null);
            return string.Equals(styleId, "TableHeader", StringComparison.OrdinalIgnoreCase)
                || string.Equals(styleId, "Table Header", StringComparison.OrdinalIgnoreCase);
        });
    }
}
