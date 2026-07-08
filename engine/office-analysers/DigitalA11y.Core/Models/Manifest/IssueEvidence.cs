namespace DigitalA11y.Core.Models.Manifest;

public class IssueEvidence
{
    /// <summary>Snippet of raw content (text, markup, attribute value) that triggered the issue.</summary>
    public string? Snippet { get; set; }

    /// <summary>Computed value relevant to the issue (e.g. contrast ratio "2.5:1").</summary>
    public string? ComputedValue { get; set; }

    /// <summary>Expected value or threshold that would satisfy the criterion.</summary>
    public string? ExpectedValue { get; set; }

    /// <summary>Additional context or analyser-specific metadata.</summary>
    public Dictionary<string, string>? AdditionalContext { get; set; }
}
