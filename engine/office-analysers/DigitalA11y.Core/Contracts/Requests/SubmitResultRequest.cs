using DigitalA11y.Core.Models.Manifest;

namespace DigitalA11y.Core.Contracts.Requests;

/// <summary>
/// Sent by a worker on successful job completion, carrying the full issue manifest.
/// </summary>
public class SubmitResultRequest
{
    public Guid JobId { get; set; }
    public string ClaimToken { get; set; } = string.Empty;
    public IssueManifest Manifest { get; set; } = new();
}
