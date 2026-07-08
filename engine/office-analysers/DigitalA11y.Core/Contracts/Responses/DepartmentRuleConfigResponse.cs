using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Contracts.Responses;

public class DepartmentRuleConfigResponse
{
    public Guid DepartmentId { get; set; }
    public AnalyserType AnalyserType { get; set; }

    /// <summary>Rule IDs currently disabled for this department. Empty means all rules run.</summary>
    public List<string> DisabledRuleIds { get; set; } = [];
}
