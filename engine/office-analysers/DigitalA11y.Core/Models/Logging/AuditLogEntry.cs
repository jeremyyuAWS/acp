using DigitalA11y.Core.Models.Entities;

namespace DigitalA11y.Core.Models.Logging;

/// <summary>
/// Immutable record of user or system actions that affect data or configuration.
/// Used for compliance and accountability reporting.
/// </summary>
public class AuditLogEntry : BaseLoggingEntity
{
    /// <summary>The action performed, e.g. "AcceptRisk", "OverrideRemediation", "ConfigUpdated".</summary>
    public string Action { get; set; } = string.Empty;

    public string PerformedBy { get; set; } = string.Empty;
    public string? EntityType { get; set; }
    public Guid? EntityId { get; set; }
    public Guid? DepartmentId { get; set; }

    /// <summary>JSON snapshot of the entity state before the action.</summary>
    public string? BeforeJson { get; set; }

    /// <summary>JSON snapshot of the entity state after the action.</summary>
    public string? AfterJson { get; set; }

    public string? Reason { get; set; }
    public string? IpAddress { get; set; }
}
