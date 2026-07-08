using DigitalA11y.Core.Models.Manifest;

namespace DigitalA11y.Core.Contracts.Responses;

public class NextRemediationJobResponse
{
    public Guid JobId { get; set; }
    public Guid BatchRunId { get; set; }
    public Guid FileId { get; set; }
    public Guid AnalysisJobId { get; set; }
    public string FileIdentifier { get; set; } = string.Empty;
    public string FileType { get; set; } = string.Empty;
    public string Queue { get; set; } = string.Empty;
    public DateTimeOffset CreatedAt { get; set; }

    /// <summary>The manifest from the analysis step — worker must never query the database directly.</summary>
    public IssueManifest Manifest { get; set; } = null!;

    /// <summary>
    /// The tenant slug this job belongs to.
    /// Workers must pass this back as X-Tenant-Slug on all subsequent calls for this job.
    /// </summary>
    public string? TenantSlug { get; set; }
}
