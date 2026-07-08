using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

public class FileRecord : BaseTenantEntity
{
    public Guid DepartmentId { get; set; }
    public Guid ConnectorConfigId { get; set; }

    public string FileName { get; set; } = string.Empty;
    public string FilePath { get; set; } = string.Empty;
    public FileType FileType { get; set; }
    public long FileSizeBytes { get; set; }
    public string? MimeType { get; set; }
    public string? Sha256Hash { get; set; }
    public DateTimeOffset? SourceLastModified { get; set; }
    public DateTimeOffset FirstSeenAt { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset LastSeenAt { get; set; } = DateTimeOffset.UtcNow;

    // ── Archive engine fields ─────────────────────────────────────────────
    public ArchiveStatus ArchiveStatus { get; set; } = ArchiveStatus.PENDING;
    public string? ArchiveReason { get; set; }
    public FileType? DetectedFileType { get; set; }

    // Navigation
    public Department Department { get; set; } = null!;
    public DepartmentConnectorConfig ConnectorConfig { get; set; } = null!;
    public ICollection<AnalysisJobRecord> AnalysisJobs { get; set; } = [];
    public ICollection<RemediationJobRecord> RemediationJobs { get; set; } = [];
    public ICollection<IssueRecord> Issues { get; set; } = [];
    public ICollection<ComplianceRecord> ComplianceRecords { get; set; } = [];
    public ICollection<FileVersion> Versions { get; set; } = [];
}
