using DigitalA11y.Core.Models.Jobs;

namespace DigitalA11y.Core.Contracts.Responses;

/// <summary>
/// Returned to a worker after a claim attempt.
/// </summary>
public class ClaimJobResponse
{
    public bool Claimed { get; set; }

    /// <summary>Populated when <see cref="Claimed"/> is true.</summary>
    public AnalysisJob? Job { get; set; }

    /// <summary>Opaque token required for subsequent progress and result calls.</summary>
    public string? ClaimToken { get; set; }

    /// <summary>Reason the claim was denied, if applicable.</summary>
    public string? Reason { get; set; }
}
