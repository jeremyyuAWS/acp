using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Contracts.Responses;

public class PendingApprovalJobSummary
{
    public Guid JobId { get; set; }
    public Guid BatchRunId { get; set; }
    public Guid FileId { get; set; }
    public string FileName { get; set; } = string.Empty;
    public FileType FileType { get; set; }
    public DateTimeOffset PendingApprovalAt { get; set; }
    public int CriticalIssues { get; set; }
    public int SeriousIssues { get; set; }
    public int ModerateIssues { get; set; }
    public int MinorIssues { get; set; }
    public int TotalIssues { get; set; }
}
