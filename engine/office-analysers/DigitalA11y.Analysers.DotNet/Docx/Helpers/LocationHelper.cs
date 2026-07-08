using DigitalA11y.Core.Models.Manifest;

namespace DigitalA11y.Analysers.DotNet.Docx.Helpers;

public static class LocationHelper
{
    public static IssueLocation FromParagraph(int paragraphIndex) => new()
    {
        ElementIndex = paragraphIndex,
        Description = $"docx:paragraph:{paragraphIndex}"
    };

    public static IssueLocation FromTable(int tableIndex, int rowIndex) => new()
    {
        ElementIndex = tableIndex,
        Description = $"docx:table:{tableIndex}:row:{rowIndex}"
    };

    public static IssueLocation FromDrawing(int paragraphIndex, string drawingId) => new()
    {
        ElementIndex = paragraphIndex,
        Description = $"docx:drawing:{drawingId}:paragraph:{paragraphIndex}"
    };

    public static IssueLocation FromHyperlink(int paragraphIndex, string url) => new()
    {
        ElementIndex = paragraphIndex,
        Description = $"docx:hyperlink:paragraph:{paragraphIndex}:url:{url}"
    };
}
