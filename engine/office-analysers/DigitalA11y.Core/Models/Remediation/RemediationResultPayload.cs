using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Remediation;

/// <summary>
/// Serialisation-safe remediation result used in the API contract.
/// Mirrors the shape of both DocxRemediator and PptxRemediator RemediationResult records.
/// </summary>
public class RemediationResultPayload
{
    public Guid JobId { get; set; }
    public Guid FileId { get; set; }
    public int AutoFixedCount { get; set; }
    public int HumanRequiredCount { get; set; }
    public int SkippedCount { get; set; }
    public List<AppliedFixPayload> AppliedFixes { get; set; } = [];
    public List<SkippedFixPayload> SkippedFixes { get; set; } = [];
    public string RemediatorVersion { get; set; } = string.Empty;
    public List<LlmUsageEntry> LlmUsage { get; set; } = [];
}

public class AppliedFixPayload
{
    public Guid IssueId { get; set; }
    public IssueCategory Category { get; set; }
    public RemediationType RemediationType { get; set; }
    public string Description { get; set; } = string.Empty;
}

public class SkippedFixPayload
{
    public Guid IssueId { get; set; }
    public IssueCategory Category { get; set; }
    public string Reason { get; set; } = string.Empty;
}
