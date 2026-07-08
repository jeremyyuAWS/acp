using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

public class RemediationJobRecord : BaseRecordEntity
{
    public Guid BatchRunId { get; set; }
    public Guid FileRecordId { get; set; }
    public Guid AnalysisJobRecordId { get; set; }
    public string Queue { get; set; } = string.Empty;
    public JobStatus Status { get; set; } = JobStatus.QUEUED;
    public string? WorkerId { get; set; }
    public string? ClaimToken { get; set; }
    public int IssuesTargeted { get; set; }
    public int IssuesAutoFixed { get; set; }
    public int IssuesPlaceholder { get; set; }
    public int IssuesHumanRequired { get; set; }
    public string? OutputFilePath { get; set; }
    public string? ErrorCode { get; set; }
    public string? ErrorMessage { get; set; }
    public DateTimeOffset? PendingApprovalAt { get; set; }
    public string? ReviewedBy { get; set; }

    // Navigation
    public BatchRun BatchRun { get; set; } = null!;
    public FileRecord FileRecord { get; set; } = null!;
    public AnalysisJobRecord AnalysisJobRecord { get; set; } = null!;
    public FileVersion? FileVersion { get; set; }
}
