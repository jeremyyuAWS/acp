namespace DigitalA11y.Core.Enums;

public enum ReportType
{
    AuditSummary,    // per-batch run summary across all files
    BatchRollup,     // aggregated view across all files in a batch
    ManifestDiff,    // delta report between two snapshots
    LlmUsageSummary  // AI token usage and cost breakdown
}
