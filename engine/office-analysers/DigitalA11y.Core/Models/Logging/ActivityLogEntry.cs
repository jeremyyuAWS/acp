using DigitalA11y.Core.Models.Entities;

namespace DigitalA11y.Core.Models.Logging;

/// <summary>
/// Records significant system events — job state transitions, batch lifecycle, connector activity.
/// </summary>
public class ActivityLogEntry : BaseLoggingEntity
{
    /// <summary>Category of event, e.g. "JobStateChange", "BatchStarted", "ConnectorSync".</summary>
    public string EventType { get; set; } = string.Empty;

    public string Message { get; set; } = string.Empty;

    /// <summary>Primary entity affected, e.g. "Job", "BatchRun", "FileRecord".</summary>
    public string? EntityType { get; set; }

    public Guid? EntityId { get; set; }
    public Guid? BatchRunId { get; set; }
    public Guid? DepartmentId { get; set; }

    /// <summary>Worker or service that generated this entry.</summary>
    public string? Source { get; set; }

    /// <summary>Structured metadata as a JSON blob (e.g. before/after status values).</summary>
    public string? MetadataJson { get; set; }
}
