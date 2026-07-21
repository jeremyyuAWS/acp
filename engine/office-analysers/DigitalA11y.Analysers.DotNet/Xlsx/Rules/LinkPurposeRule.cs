using System.Text.RegularExpressions;
using DigitalA11y.Analysers.DotNet.Xlsx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

public class LinkPurposeRule : IXlsxRule
{
    public string RuleId => XlsxRuleIds.LinkPurpose;

    // Same deny-list as Docx/Pptx LinkPurposeRule, kept in sync deliberately — a generic
    // link text failure is the same failure regardless of which format carries it.
    private static readonly HashSet<string> GenericLinkTexts = new(StringComparer.OrdinalIgnoreCase)
    {
        "click here", "here", "read more", "link", "more", "click", "this link", "url"
    };

    // Matches a top-level =HYPERLINK(...) call so formula-driven links can be found without
    // a full formula parser — good enough to flag the cell; the friendly-name argument (if
    // any) is read from the cell's own cached/calculated display value, not re-parsed here.
    private static readonly Regex HyperlinkFormula = new(@"HYPERLINK\s*\(", RegexOptions.IgnoreCase);

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

            // Cell references already covered via the worksheet's own <hyperlinks> element —
            // formula-driven HYPERLINK() cells never appear there, so scanning cell.CellFormula
            // separately below is how those get found at all, not a redundant second pass.
            var relationshipLinkedRefs = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            // ── Standard cell-level hyperlinks (Insert > Link), external or internal ──
            var hyperlinksElement = worksheetPart.Worksheet?.GetFirstChild<Hyperlinks>();
            if (hyperlinksElement is not null)
            {
                foreach (var link in hyperlinksElement.Elements<Hyperlink>())
                {
                    var cellRef = link.Reference?.Value;
                    if (cellRef is null) continue;
                    relationshipLinkedRefs.Add(cellRef);

                    var cell = FindCell(worksheetData, cellRef);
                    var displayText = cell is not null ? CellValueHelper.GetCellValue(cell, sharedStrings) : null;
                    var url = ResolveUrl(link, worksheetPart);

                    var issue = EvaluateLinkText(displayText, sheetName, cellRef, url);
                    if (issue is not null) yield return issue;
                }
            }

            // ── Formula-driven links: =HYPERLINK(url, [friendly_name]) — invisible to the
            // worksheet's <hyperlinks> element entirely, a distinct and easy-to-miss case ──
            foreach (var cell in worksheetData.Descendants<Cell>())
            {
                var formula = cell.CellFormula?.Text;
                if (formula is null || !HyperlinkFormula.IsMatch(formula)) continue;

                var cellRef = cell.CellReference?.Value;
                if (cellRef is null || relationshipLinkedRefs.Contains(cellRef)) continue;

                var displayText = CellValueHelper.GetCellValue(cell, sharedStrings);
                var url = ExtractFormulaUrl(formula);

                var issue = EvaluateLinkText(displayText, sheetName, cellRef, url);
                if (issue is not null) yield return issue;
            }
        }
    }

    private A11yIssue? EvaluateLinkText(string? displayText, string sheetName, string cellRef, string url)
    {
        var trimmed = displayText?.Trim() ?? string.Empty;
        bool isEmpty = string.IsNullOrWhiteSpace(trimmed);
        bool isGeneric = !isEmpty && GenericLinkTexts.Contains(trimmed);
        bool isRawUrl = !isEmpty && !isGeneric && LooksLikeRawUrl(trimmed);

        if (!isEmpty && !isGeneric && !isRawUrl) return null;

        var computed = isEmpty ? "(empty)" : trimmed;
        var detail = isEmpty
            ? "The linked cell has no display text. Screen reader users will not know its destination."
            : isRawUrl
                ? $"The link text \"{trimmed}\" is the raw URL, not a description of the destination."
                : $"The link text \"{trimmed}\" is generic and does not describe the link destination.";

        return new A11yIssue
        {
            IssueId = Guid.NewGuid(),
            RuleId = RuleId,
            Title = "Link text does not describe the link purpose",
            Description = detail,
            Severity = IssueSeverity.MODERATE,
            Category = IssueCategory.LINKS,
            WcagCriterion = WcagCriterion.SC_2_4_4,
            RemediationType = RemediationType.HUMAN_REQUIRED,
            RemediationGuidance = "Replace the cell's display text with a description that identifies the destination or purpose of the link.",
            Location = LocationHelper.FromCell(sheetName, cellRef),
            Evidence = new IssueEvidence
            {
                Snippet = computed,
                ComputedValue = computed,
                ExpectedValue = "Descriptive link text that identifies the destination",
                AdditionalContext = new Dictionary<string, string> { ["url"] = url }
            }
        };
    }

    private static bool LooksLikeRawUrl(string text) =>
        text.StartsWith("http://", StringComparison.OrdinalIgnoreCase) ||
        text.StartsWith("https://", StringComparison.OrdinalIgnoreCase) ||
        text.StartsWith("www.", StringComparison.OrdinalIgnoreCase);

    private static Cell? FindCell(SheetData worksheetData, string cellReference) =>
        worksheetData.Descendants<Cell>()
            .FirstOrDefault(c => string.Equals(c.CellReference?.Value, cellReference, StringComparison.OrdinalIgnoreCase));

    private static string ResolveUrl(Hyperlink link, WorksheetPart worksheetPart)
    {
        if (!string.IsNullOrEmpty(link.Location?.Value)) return link.Location.Value;

        var relationshipId = link.Id?.Value;
        if (relationshipId is null) return string.Empty;

        try
        {
            var rel = worksheetPart.HyperlinkRelationships.FirstOrDefault(r => r.Id == relationshipId);
            return rel?.Uri?.ToString() ?? string.Empty;
        }
        catch
        {
            return string.Empty;
        }
    }

    // Best-effort extraction of HYPERLINK()'s first argument for evidence purposes only —
    // not used for the pass/fail decision, so a formula this doesn't parse cleanly (nested
    // quotes, cell-reference args) just yields an empty url string rather than a wrong one.
    private static string ExtractFormulaUrl(string formula)
    {
        var match = Regex.Match(formula, @"HYPERLINK\s*\(\s*""([^""]*)""", RegexOptions.IgnoreCase);
        return match.Success ? match.Groups[1].Value : string.Empty;
    }
}
