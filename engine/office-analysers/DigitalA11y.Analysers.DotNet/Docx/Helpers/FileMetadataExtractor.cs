using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace DigitalA11y.Analysers.DotNet.Docx.Helpers;

public static class FileMetadataExtractor
{
    public static FileMetadata Extract(WordprocessingDocument document, string filePath)
    {
        var body = document.MainDocumentPart?.Document?.Body;

        var fileInfo = new FileInfo(filePath);

        int pageCount = CountPages(document);
        int imageCount = CountDrawings(document);
        int tableCount = body?.Descendants<Table>().Count() ?? 0;
        int headingCount = CountHeadings(document);
        int wordCount = CountWords(document);

        string? languageDeclared = document.PackageProperties.Language;
        string? titleDeclared = document.PackageProperties.Title;

        return new FileMetadata
        {
            FileName = Path.GetFileName(filePath),
            FilePath = filePath,
            FileType = FileType.DOCX,
            FileSizeBytes = fileInfo.Exists ? fileInfo.Length : 0,
            MimeType = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            LastModified = fileInfo.Exists ? new DateTimeOffset(fileInfo.LastWriteTimeUtc) : DateTimeOffset.UtcNow
        };
    }

    private static int CountPages(WordprocessingDocument document)
    {
        var body = document.MainDocumentPart?.Document?.Body;
        if (body is null) return 1;

        int sectionCount = body.Descendants<SectionProperties>().Count();
        return Math.Max(1, sectionCount);
    }

    private static int CountDrawings(WordprocessingDocument document)
    {
        var body = document.MainDocumentPart?.Document?.Body;
        return body?.Descendants<DocumentFormat.OpenXml.Drawing.Wordprocessing.Inline>().Count()
             + body?.Descendants<DocumentFormat.OpenXml.Drawing.Wordprocessing.Anchor>().Count()
             ?? 0;
    }

    private static int CountHeadings(WordprocessingDocument document)
    {
        var body = document.MainDocumentPart?.Document?.Body;
        if (body is null) return 0;

        var headingStyles = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "Heading1","Heading2","Heading3","Heading4","Heading5","Heading6",
            "Heading 1","Heading 2","Heading 3","Heading 4","Heading 5","Heading 6"
        };

        return body.Descendants<Paragraph>()
                   .Count(p => headingStyles.Contains(
                       p.ParagraphProperties?.ParagraphStyleId?.Val?.Value ?? string.Empty));
    }

    private static int CountWords(WordprocessingDocument document)
    {
        var body = document.MainDocumentPart?.Document?.Body;
        if (body is null) return 0;

        return body.Descendants<Text>()
                   .SelectMany(t => t.Text.Split((char[])null!, StringSplitOptions.RemoveEmptyEntries))
                   .Count();
    }
}
