using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Manifest;

public class A11yIssue
{
    public Guid IssueId { get; set; } = Guid.NewGuid();

    public string RuleId { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;

    public IssueSeverity Severity { get; set; }
    public IssueCategory Category { get; set; }
    public WcagCriterion WcagCriterion { get; set; }

    public IssueLocation Location { get; set; } = new();
    public IssueEvidence Evidence { get; set; } = new();

    /// <summary>Whether an automated fix or placeholder can be applied.</summary>
    public RemediationType RemediationType { get; set; }

    /// <summary>Human-readable remediation guidance.</summary>
    public string? RemediationGuidance { get; set; }
}
