using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

public class IssueRecord : BaseTenantEntity
{
    public Guid FirstDetectedByJobId { get; set; }
    public Guid FileRecordId { get; set; }
    public string RuleId { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public IssueSeverity Severity { get; set; }
    public IssueCategory Category { get; set; }
    public WcagCriterion WcagCriterion { get; set; }
    public RemediationType RemediationType { get; set; }

    /// <summary>JSON snapshot of IssueLocation.</summary>
    public string LocationJson { get; set; } = "{}";

    /// <summary>JSON snapshot of IssueEvidence.</summary>
    public string EvidenceJson { get; set; } = "{}";

    public bool IsResolved { get; set; }
    public DateTimeOffset? ResolvedAt { get; set; }
    public Guid? ResolvedByRemediationJobId { get; set; }

    public Guid? LastDetectedByJobId { get; set; }
    public DateTimeOffset? LastDetectedAt { get; set; }

    // Navigation
    public AnalysisJobRecord FirstDetectedByJob { get; set; } = null!;
    public AnalysisJobRecord? LastDetectedByJob { get; set; }
    public FileRecord FileRecord { get; set; } = null!;
}
