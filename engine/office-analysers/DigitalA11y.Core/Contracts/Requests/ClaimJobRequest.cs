using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Contracts.Requests;

/// <summary>
/// Sent by a worker to claim the next available job from the server.
/// </summary>
public class ClaimJobRequest
{
    /// <summary>Unique identifier for this worker instance.</summary>
    public string WorkerId { get; set; } = string.Empty;

    /// <summary>Queue the worker is polling — use <see cref="A11yQueue"/> constants.</summary>
    public string Queue { get; set; } = string.Empty;

    /// <summary>File types this worker is capable of analysing.</summary>
    public List<FileType> SupportedFileTypes { get; set; } = [];
}
