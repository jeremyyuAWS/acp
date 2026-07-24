using DigitalA11y.Analysers.DotNet.Xlsx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

// Distinct from SheetNameRule (does a sheet name match Excel's generic default pattern):
// this checks that CUSTOM names are also unique across the workbook — the other half of
// V3's "Unique Names for Worksheets" checklist item. Two sheets legitimately renamed to the
// same non-default name still leave a screen-reader user unable to tell them apart by name.
public class SheetNameUniquenessRule : IXlsxRule
{
    public string RuleId => XlsxRuleIds.SheetNameUniqueness;

    public IEnumerable<A11yIssue> Analyse(SpreadsheetDocument document)
    {
        var sheets = document.WorkbookPart?.Workbook.Sheets;
        if (sheets is null) yield break;

        var seen = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (DocumentFormat.OpenXml.Spreadsheet.Sheet sheet in sheets)
        {
            var name = sheet.Name?.Value;
            if (string.IsNullOrWhiteSpace(name)) continue;

            if (seen.TryGetValue(name, out var firstSeenAs))
            {
                yield return new A11yIssue
                {
                    IssueId = Guid.NewGuid(),
                    RuleId = RuleId,
                    Title = "Sheet name duplicates another sheet",
                    Description = $"The sheet named \"{name}\" duplicates another sheet's name (first seen as \"{firstSeenAs}\"). Duplicate sheet names make it impossible to distinguish sheets by name alone.",
                    Severity = IssueSeverity.MODERATE,
                    Category = IssueCategory.HEADING_STRUCTURE,
                    WcagCriterion = WcagCriterion.SC_2_4_6,
                    RemediationType = RemediationType.HUMAN_REQUIRED,
                    RemediationGuidance = "Double-click the sheet tab and rename it so it no longer duplicates another sheet's name.",
                    Location = LocationHelper.FromSheet(name),
                    Evidence = new IssueEvidence
                    {
                        ComputedValue = name,
                        ExpectedValue = "A name not already used by another sheet in this workbook"
                    }
                };
            }
            else
            {
                seen[name] = name;
            }
        }
    }
}
