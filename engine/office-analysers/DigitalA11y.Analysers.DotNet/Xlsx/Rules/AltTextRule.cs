using DigitalA11y.Analysers.DotNet.Helpers;
using DigitalA11y.Analysers.DotNet.Xlsx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Drawing.Spreadsheet;
using DocumentFormat.OpenXml.Packaging;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

public class AltTextRule : IXlsxRule
{
    public string RuleId => XlsxRuleIds.AltText;

    private static readonly HashSet<string> PlaceholderPatterns = new(StringComparer.OrdinalIgnoreCase)
    {
        "image", "picture", "photo", "img", "figure", "chart", "graph"
    };

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

            foreach (var drawingsPart in worksheetPart.DrawingsPart is not null
                ? new[] { worksheetPart.DrawingsPart }
                : [])
            {
                var wsDr = drawingsPart.WorksheetDrawing;
                if (wsDr is null) continue;

                // Walk pictures/frames regardless of anchor kind. Scoping to TwoCellAnchor
                // silently skipped OneCellAnchor and AbsoluteAnchor images (a single-cell
                // anchored image, openpyxl's default and common in hand-authored sheets),
                // so those were never checked for alt text.
                foreach (var picture in wsDr.Descendants<Picture>())
                {
                    var nvPr = picture.NonVisualPictureProperties?.NonVisualDrawingProperties;
                    var issue = CheckNonVisualProps(nvPr, sheetName);
                    if (issue is not null) yield return issue;
                }

                foreach (var frame in wsDr.Descendants<GraphicFrame>())
                {
                    var nvPr = frame.NonVisualGraphicFrameProperties?.NonVisualDrawingProperties;
                    var issue = CheckNonVisualProps(nvPr, sheetName);
                    if (issue is not null) yield return issue;
                }
            }
        }
    }

    private A11yIssue? CheckNonVisualProps(
        DocumentFormat.OpenXml.Drawing.Spreadsheet.NonVisualDrawingProperties? nvPr,
        string sheetName)
    {
        if (nvPr is null)
        {
            return MakeIssue(sheetName, "(no NonVisualDrawingProperties)", "unknown", "Alt text is missing — NonVisualDrawingProperties element not present.");
        }

        var description = nvPr.Description?.Value;
        var drawingId = nvPr.Id?.Value.ToString() ?? "unknown";

        if (string.IsNullOrWhiteSpace(description))
        {
            return MakeIssue(sheetName, "(empty)", drawingId, "The image or chart has no alt text description.");
        }

        var trimmed = description.Trim();
        if (PlaceholderPatterns.Contains(trimmed))
        {
            return MakeIssue(sheetName, trimmed, drawingId, $"The alt text \"{trimmed}\" is a non-descriptive placeholder.");
        }

        if (AltTextHeuristics.LooksLikeFilenameOrPath(trimmed))
        {
            return MakeIssue(sheetName, trimmed, drawingId, $"The alt text \"{trimmed}\" is a file name or path, not a description of the image or chart.");
        }

        return null;
    }

    private A11yIssue MakeIssue(string sheetName, string computed, string drawingId, string detail)
        => new()
        {
            IssueId = Guid.NewGuid(),
            RuleId = RuleId,
            Title = "Image or chart missing meaningful alt text",
            Description = $"An image or chart does not have descriptive alternative text. {detail}",
            Severity = IssueSeverity.CRITICAL,
            Category = IssueCategory.ALT_TEXT,
            WcagCriterion = WcagCriterion.SC_1_1_1,
            RemediationType = RemediationType.AUTO_PLACEHOLDER,
            RemediationGuidance = "Right-click the image or chart, choose 'Edit Alt Text', and provide a concise description.",
            Location = LocationHelper.FromDrawing(sheetName, drawingId),
            Evidence = new IssueEvidence
            {
                ComputedValue = computed,
                ExpectedValue = "A concise, meaningful description of the image or chart content"
            }
        };
}
