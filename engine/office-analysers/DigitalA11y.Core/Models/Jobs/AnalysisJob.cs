using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Jobs;

/// <summary>
/// Payload enqueued into Hangfire for a single-file analysis task.
/// </summary>
public class AnalysisJob
{
    public Guid JobId { get; set; } = Guid.NewGuid();
    public Guid BatchRunId { get; set; }
    public Guid FileId { get; set; }

    public string FilePath { get; set; } = string.Empty;
    public FileType FileType { get; set; }

    /// <summary>Target Hangfire queue — use <see cref="A11yQueue"/> constants.</summary>
    public string Queue { get; set; } = A11yQueue.AnalyseDotNet;

    public AnalysisJobType JobType { get; set; } = AnalysisJobType.SCAN;

    public DateTimeOffset EnqueuedAt { get; set; } = DateTimeOffset.UtcNow;

    /// <summary>The department that owns the file being analysed.</summary>
    public Guid DepartmentId { get; set; }

    /// <summary>
    /// Rule IDs disabled for this department, resolved at claim time.
    /// Empty list means all rules run (default).
    /// </summary>
    public IReadOnlyList<string> DisabledRuleIds { get; set; } = [];
}
