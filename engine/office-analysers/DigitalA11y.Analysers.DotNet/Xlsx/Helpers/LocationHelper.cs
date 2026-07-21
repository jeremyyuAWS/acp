using DigitalA11y.Core.Models.Manifest;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Helpers;

public static class LocationHelper
{
    public static IssueLocation FromSheet(string sheetName) => new()
    {
        Description = $"xlsx:sheet:{sheetName}"
    };

    public static IssueLocation FromDrawing(string sheetName, string drawingId) => new()
    {
        Description = $"xlsx:sheet:{sheetName}:drawing:{drawingId}"
    };

    public static IssueLocation FromTable(string sheetName, string tableName) => new()
    {
        Description = $"xlsx:sheet:{sheetName}:table:{tableName}"
    };

    public static IssueLocation FromRow(string sheetName, uint rowIndex) => new()
    {
        ElementIndex = (int)rowIndex,
        Description = $"xlsx:sheet:{sheetName}:row:{rowIndex}"
    };

    public static IssueLocation FromColumn(string sheetName, uint colIndex) => new()
    {
        ElementIndex = (int)colIndex,
        Description = $"xlsx:sheet:{sheetName}:col:{colIndex}"
    };

    public static IssueLocation FromCell(string sheetName, string cellReference) => new()
    {
        Description = $"xlsx:sheet:{sheetName}:cell:{cellReference}"
    };

    public static IssueLocation FromDocument() => new()
    {
        Description = "xlsx:document"
    };
}
