using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Manifest;

public class FileMetadata
{
    public Guid FileId { get; set; }
    public string FileName { get; set; } = string.Empty;
    public string FilePath { get; set; } = string.Empty;
    public FileType FileType { get; set; }
    public long FileSizeBytes { get; set; }
    public string? MimeType { get; set; }
    public string? Sha256Hash { get; set; }
    public DateTimeOffset LastModified { get; set; }
}
