using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;

namespace DigitalA11y.Core.Contracts.Responses;

public class ClaimRemediationJobResponse
{
    public bool Claimed { get; set; }

    public Guid JobId { get; set; }
    public Guid FileId { get; set; }
    public string FileIdentifier { get; set; } = string.Empty;
    public FileType FileType { get; set; }

    /// <summary>Opaque token required for subsequent result and fail calls.</summary>
    public string? ClaimToken { get; set; }

    /// <summary>The manifest from the analysis step — worker must never query the database directly.</summary>
    public IssueManifest? Manifest { get; set; }

    /// <summary>Reason the claim was denied, if applicable.</summary>
    public string? Reason { get; set; }

    public bool AllowLlm { get; set; } = true;
    public bool AllowPlaceholders { get; set; } = true;
}
