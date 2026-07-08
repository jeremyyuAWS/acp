namespace DigitalA11y.Core.Contracts.Requests;

/// <summary>
/// Sent by a worker to report incremental job progress to the server.
/// </summary>
public class ProgressUpdateRequest
{
    public Guid JobId { get; set; }
    public string ClaimToken { get; set; } = string.Empty;

    public int ItemsProcessed { get; set; }
    public int? TotalItems { get; set; }
    public string? StatusMessage { get; set; }
}
