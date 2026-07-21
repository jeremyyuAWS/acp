using DocumentFormat.OpenXml.Spreadsheet;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Helpers;

public static class CellValueHelper
{
    /// <summary>
    /// Resolves a cell's textual value, handling inline strings (t="inlineStr", emitted by
    /// writers such as openpyxl by default) and shared-string references. Reading only
    /// CellValue.Text leaves inline-string cells looking empty.
    /// </summary>
    public static string? GetCellValue(Cell cell, SharedStringTable? sharedStrings)
    {
        if (cell.DataType?.Value == CellValues.InlineString)
        {
            return cell.InlineString?.InnerText;
        }

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
}
