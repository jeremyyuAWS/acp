using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Contracts.Responses;

public class AvailableRulesResponse
{
    public AnalyserType AnalyserType { get; set; }
    public IReadOnlyList<string> RuleIds { get; set; } = [];
}
