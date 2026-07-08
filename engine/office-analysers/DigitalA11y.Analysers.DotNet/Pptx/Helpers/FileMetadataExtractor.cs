using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;

namespace DigitalA11y.Analysers.DotNet.Pptx.Helpers;

public static class FileMetadataExtractor
{
    public static FileMetadata Extract(PresentationDocument document, string filePath)
    {
        var fileInfo = new FileInfo(filePath);

        return new FileMetadata
        {
            FileName = Path.GetFileName(filePath),
            FilePath = filePath,
            FileType = FileType.PPTX,
            FileSizeBytes = fileInfo.Exists ? fileInfo.Length : 0,
            MimeType = "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            LastModified = fileInfo.Exists ? new DateTimeOffset(fileInfo.LastWriteTimeUtc) : DateTimeOffset.UtcNow
        };
    }
}
