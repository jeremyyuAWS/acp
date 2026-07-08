using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

public class ManifestSnapshot : BaseTenantEntity
{
    // --- Scope ---
    public Guid BatchRunId { get; set; }
    public BatchRun BatchRun { get; set; } = null!;

    // --- Identity ---
    public string? Label { get; set; }          // null = auto; non-null = user-pinned baseline
    public bool IsPinned { get; set; }          // true when user explicitly marked as named baseline
    public SnapshotStatus Status { get; set; }  // see enum below

    // --- Aggregate health (duplicated from ComplianceRecord for diff speed) ---
    public int TotalIssues { get; set; }
    public int CriticalCount { get; set; }
    public int SeriousCount { get; set; }
    public int ModerateCount { get; set; }
    public int MinorCount { get; set; }
    public int AccessibilityScore { get; set; }

    // --- Hybrid diff payload (computed at snapshot creation time) ---
    // Compared against the previous snapshot for this file set.
    // Null on the very first snapshot (no baseline to diff against).
    public Guid? PreviousSnapshotId { get; set; }
    public ManifestSnapshot? PreviousSnapshot { get; set; }
    public List<Guid>? ResolvedIssueIds { get; set; }    // issue_ids closed since previous snapshot
    public List<Guid>? IntroducedIssueIds { get; set; }  // issue_ids new in this snapshot
    public List<Guid>? PersistingIssueIds { get; set; }  // issue_ids unchanged since previous snapshot

    // --- Timestamps ---
    public DateTimeOffset? PinnedAt { get; set; }        // set when IsPinned flips to true
}