using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

public class LlmUsageRecord : BaseTenantEntity
{
    public Guid? DepartmentId { get; set; }
    public Guid? JobId { get; set; }
    public LlmJobType JobType { get; set; }
    public LlmProvider Provider { get; set; }
    public string Model { get; set; } = string.Empty;
    public int InputTokens { get; set; }
    public int OutputTokens { get; set; }
    public int CachedTokens { get; set; }
    public decimal EstimatedCostUsd { get; set; }

    // Navigation
    public Department? Department { get; set; }
}
