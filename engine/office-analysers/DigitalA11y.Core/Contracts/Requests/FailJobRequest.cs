namespace DigitalA11y.Core.Contracts.Requests;

/// <summary>
/// Sent by a worker when a job fails and cannot produce a manifest.
/// </summary>
public class FailJobRequest
{
    public Guid JobId { get; set; }
    public string ClaimToken { get; set; } = string.Empty;

    public string ErrorCode { get; set; } = string.Empty;
    public string ErrorMessage { get; set; } = string.Empty;
    public string? StackTrace { get; set; }
    public bool IsRetryable { get; set; }
}
