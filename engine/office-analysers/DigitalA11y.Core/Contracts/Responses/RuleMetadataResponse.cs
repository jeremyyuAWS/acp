namespace DigitalA11y.Core.Contracts.Responses;

public record RuleMetadataResponse(
    string RuleId,
    string Title,
    string Description,
    string RemediationGuidance);
