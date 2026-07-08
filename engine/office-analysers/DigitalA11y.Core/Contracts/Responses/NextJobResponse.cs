using DigitalA11y.Core.Models.Jobs;

namespace DigitalA11y.Core.Contracts.Responses;

/// <summary>
/// Returned when a worker polls for work but no job is available, or before claiming.
/// </summary>
public class NextJobResponse
{
    public bool HasJob { get; set; }
    public AnalysisJob? Job { get; set; }

    /// <summary>
    /// The tenant slug this job belongs to.
    /// Workers must pass this back as X-Tenant-Slug on all subsequent calls for this job.
    /// </summary>
    public string? TenantSlug { get; set; }
}
