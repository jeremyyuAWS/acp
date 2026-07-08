using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Remediation;

public sealed class LlmUsageEntry
{
    public int InputTokens   { get; set; }
    public int OutputTokens  { get; set; }
    public int CachedTokens  { get; set; }
    public LlmProvider Provider     { get; set; }
    public string      Model        { get; set; } = string.Empty;
    public LlmJobType  JobType      { get; set; }
    public Guid?       IssueId      { get; set; }
    public Guid?       DepartmentId { get; set; }
}
