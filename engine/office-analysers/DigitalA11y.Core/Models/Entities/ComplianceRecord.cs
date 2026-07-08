namespace DigitalA11y.Core.Models.Entities;

/// <summary>
/// Point-in-time compliance snapshot for a file, computed after each analysis run.
/// </summary>
public class ComplianceRecord : BaseTenantEntity
{
    public Guid FileRecordId { get; set; }
    public Guid AnalysisJobRecordId { get; set; }
    public Guid BatchRunId { get; set; }
    public int TotalIssues { get; set; }
    public int CriticalIssues { get; set; }
    public int SeriousIssues { get; set; }
    public int ModerateIssues { get; set; }
    public int MinorIssues { get; set; }
    public int AutoFixableIssues { get; set; }
    public int HumanRequiredIssues { get; set; }

    /// <summary>Percentage of WCAG AA criteria passed (0–100).</summary>
    public decimal ComplianceScore { get; set; }

    public bool IsCompliant { get; set; }
    public DateTimeOffset ComputedAt { get; set; } = DateTimeOffset.UtcNow;

    // Navigation
    public FileRecord FileRecord { get; set; } = null!;
    public AnalysisJobRecord AnalysisJobRecord { get; set; } = null!;
    public BatchRun BatchRun { get; set; } = null!;
}
