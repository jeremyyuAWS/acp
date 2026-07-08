using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Helpers;

public static class FileTypeDetector
{
    private static ReadOnlySpan<byte> PdfHeader => [0x25, 0x50, 0x44, 0x46]; // %PDF
    private static ReadOnlySpan<byte> ZipHeader => [0x50, 0x4B, 0x03, 0x04]; // PK\x03\x04

    /// <summary>
    /// Detects file type from raw bytes (magic-byte sniffing).
    /// Falls back to extension hint for ZIP-based formats (DOCX/PPTX share the same magic bytes).
    /// </summary>
    public static FileType DetectByMagicBytes(ReadOnlySpan<byte> bytes, string fileName)
    {
        if (bytes.Length < 4)
            return FileType.UNKNOWN;

        if (bytes[..4].SequenceEqual(PdfHeader))
            return FileType.PDF;

        if (bytes[..4].SequenceEqual(ZipHeader))
        {
            var ext = Path.GetExtension(fileName).ToLowerInvariant();
            return ext switch
            {
                ".docx" => FileType.DOCX,
                ".pptx" => FileType.PPTX,
                ".xlsx" => FileType.XLSX,
                _ => FileType.DOCX
            };
        }

        var text = System.Text.Encoding.UTF8.GetString(
            bytes[..Math.Min(bytes.Length, 512)]).ToLowerInvariant();

        if (text.Contains("<!doctype") || text.Contains("<html"))
            return FileType.HTML;

        return FileType.UNKNOWN;
    }

    public static FileType ResolveFileTypeByExtension(string ext) =>
       ext.ToLowerInvariant() switch
       {
           ".docx" => FileType.DOCX,
           ".pptx" => FileType.PPTX,
           ".xlsx" => FileType.XLSX,
           ".pdf" => FileType.PDF,
           ".html" or ".htm" => FileType.HTML,
           _ => FileType.UNKNOWN,
       };

    public static FileType ResolveFileTypeByFileName(string fileName)
    {
        var ext = Path.GetExtension(fileName);
        return ResolveFileTypeByExtension(ext);
    }

    public static FileType ResolveFileTypeByContentType(string contentType) =>
        contentType.ToLowerInvariant() switch
        {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document" => FileType.DOCX,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation" => FileType.PPTX,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" => FileType.XLSX,
            "application/pdf" => FileType.PDF,
            "text/html" => FileType.HTML,
            _ => FileType.UNKNOWN,
        };
}
