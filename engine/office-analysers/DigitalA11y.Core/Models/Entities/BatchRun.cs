using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

public class BatchRun : BaseRecordEntity
{
    public Guid ConnectorConfigId { get; set; }
    public Guid DepartmentId { get; set; }
    public BatchRunStatus Status { get; set; } = BatchRunStatus.QUEUED;
    public string? TriggeredBy { get; set; }
    public int TotalFiles { get; set; }
    public int TotalJobsEnqueued { get; set; }
    public int FilesAnalysed { get; set; }
    public int FilesRemediated { get; set; }
    public int FilesFailed { get; set; }
    public string? FailureReason { get; set; }

    // Navigation
    public DepartmentConnectorConfig ConnectorConfig { get; set; } = null!;
    public Department Department { get; set; } = null!;
    public ICollection<AnalysisJobRecord> AnalysisJobs { get; set; } = [];
    public ICollection<RemediationJobRecord> RemediationJobs { get; set; } = [];
}
