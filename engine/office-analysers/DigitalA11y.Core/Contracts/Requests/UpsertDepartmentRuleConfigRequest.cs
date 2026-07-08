namespace DigitalA11y.Core.Contracts.Requests;

/// <summary>
/// Sets the disabled rule IDs for a department + analyser type combination.
/// Send an empty list to re-enable all rules.
/// </summary>
public class UpsertDepartmentRuleConfigRequest
{
    /// <summary>
    /// The rule IDs to disable for this department.
    /// Valid PPTX IDs: PPTX-TITLE-001, PPTX-ALT-001, PPTX-ORDER-001,
    /// PPTX-CONTRAST-001, PPTX-TABLE-001, PPTX-LANG-001, PPTX-LINK-001, PPTX-ANIM-001
    /// </summary>
    public List<string> DisabledRuleIds { get; set; } = [];
}
