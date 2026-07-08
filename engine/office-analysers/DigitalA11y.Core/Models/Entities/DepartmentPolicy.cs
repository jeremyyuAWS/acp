using DigitalA11y.Core.Helpers;

namespace DigitalA11y.Core.Models.Entities;

/// <summary>
/// Per-department archive, remediation, and scheduling rules.
/// If no policy exists for a department, global SystemConfig defaults apply.
/// </summary>
public class DepartmentPolicy : BaseAuditableEntity
{
    public Guid DepartmentId { get; set; }
    public Department Department { get; set; } = null!;

    // Archive rules
    public int ArchiveThresholdDays { get; set; } = 365;
    public long MaxFileSizeBytes { get; set; } = 104_857_600;  // 100MB
    public List<string> SupportedExtensions { get; set; } =
        SupportedFileTypes.AllExtensions.ToList();

    // Remediation rules
    public bool AutoRemediationEnabled { get; set; } = true;
    public bool RequireHumanReviewOverride { get; set; } = false;

    // Scheduling
    public bool ScheduledScanEnabled { get; set; } = false;
    public string? CronExpression { get; set; }   // null = manual only
}
