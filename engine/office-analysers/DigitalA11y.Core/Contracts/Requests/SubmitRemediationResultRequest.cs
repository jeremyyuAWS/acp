using DigitalA11y.Core.Models.Remediation;

namespace DigitalA11y.Core.Contracts.Requests;

public class SubmitRemediationResultRequest
{
    public Guid JobId { get; set; }
    public string ClaimToken { get; set; } = string.Empty;
    public RemediationResultPayload Result { get; set; } = null!;

    /// <summary>Connector path where the original (pre-remediation) copy was saved. Null if version 0 already exists.</summary>
    public string? OriginalVersionPath { get; set; }

    /// <summary>Connector path where the remediated output copy was saved in the versions subfolder.</summary>
    public string? RemediatedVersionPath { get; set; }
}
