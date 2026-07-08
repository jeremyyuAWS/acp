using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

public class AnalysisJobRecord : BaseRecordEntity
{
    public Guid BatchRunId { get; set; }
    public Guid FileRecordId { get; set; }
    public string Queue { get; set; } = string.Empty;
    public AnalysisJobType JobType { get; set; } = AnalysisJobType.SCAN;
    public JobStatus Status { get; set; } = JobStatus.QUEUED;
    public string? WorkerId { get; set; }
    public string? ClaimToken { get; set; }
    public int ItemsProcessed { get; set; }
    public int? TotalItems { get; set; }
    public string? StatusMessage { get; set; }

    /// <summary>Raw JSON of the submitted IssueManifest, stored for audit and reprocessing.</summary>
    public string? ManifestJson { get; set; }

    public string? ErrorCode { get; set; }
    public string? ErrorMessage { get; set; }
    public bool IsRetryable { get; set; }

    // Navigation
    public BatchRun BatchRun { get; set; } = null!;
    public FileRecord FileRecord { get; set; } = null!;
    public ICollection<IssueRecord> Issues { get; set; } = [];
}
