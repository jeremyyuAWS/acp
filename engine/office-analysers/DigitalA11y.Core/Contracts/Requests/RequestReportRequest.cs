using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Reporting;

namespace DigitalA11y.Core.Contracts.Requests;

public class RequestReportRequest
{
    public Guid BatchRunId { get; set; }
    public ReportType ReportType { get; set; } = ReportType.AuditSummary;
    public ReportAudience Audience { get; set; } = ReportAudience.All;
    public ReportOutputFormat OutputFormat { get; set; } = ReportOutputFormat.Json;
    public ReportFilters? Filters { get; set; }

    /// <summary>Required only for ManifestDiff reports.</summary>
    public Guid? BaseSnapshotId { get; set; }

    /// <summary>Required only for ManifestDiff reports.</summary>
    public Guid? HeadSnapshotId { get; set; }
}
