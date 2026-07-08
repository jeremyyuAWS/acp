using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

public class ReportingJobRecord : BaseRecordEntity
{
    // ── Scope ────────────────────────────────────────────────────────────────
    public Guid BatchRunId { get; set; }
    public BatchRun BatchRun { get; set; } = null!;

    // ManifestDiff: the two snapshot endpoints (null for AuditSummary / BatchRollup)
    public Guid? BaseSnapshotId { get; set; }
    public ManifestSnapshot? BaseSnapshot { get; set; }

    public Guid? HeadSnapshotId { get; set; }
    public ManifestSnapshot? HeadSnapshot { get; set; }

    // ── Report configuration ─────────────────────────────────────────────────
    public ReportType ReportType { get; set; }
    public ReportAudience Audience { get; set; }
    public ReportOutputFormat OutputFormat { get; set; }

    // Serialised ReportFilters — null means no filters applied
    public string? FiltersJson { get; set; }

    // ── Status ───────────────────────────────────────────────────────────────
    public ReportJobStatus Status { get; set; } = ReportJobStatus.Queued;
    public string? ErrorMessage { get; set; }

    // ── Output (write-once; never overwritten once Status == Ready) ──────────
    public string? OutputContent { get; set; }

    // ── Audit ────────────────────────────────────────────────────────────────
    public string? RequestedBy { get; set; }   // ExternalUserId; null for system-generated
}
