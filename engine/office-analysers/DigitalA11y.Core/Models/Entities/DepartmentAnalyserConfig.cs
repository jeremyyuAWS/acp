using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

/// <summary>
/// Stores per-department rule enable/disable overrides for a specific analyser type.
/// One row per (DepartmentId, AnalyserType) pair.
/// </summary>
public class DepartmentAnalyserConfig : BaseAuditableEntity
{
    public Guid DepartmentId { get; set; }

    /// <summary>Which analyser this config applies to.</summary>
    public AnalyserType AnalyserType { get; set; }

    /// <summary>
    /// JSON array of rule IDs that are disabled for this department.
    /// Empty array means all rules run (default behaviour).
    /// Example: ["PPTX-CONTRAST-001","PPTX-ANIM-001"]
    /// </summary>
    public string DisabledRuleIdsJson { get; set; } = "[]";

    // Navigation
    public Department Department { get; set; } = null!;
}
