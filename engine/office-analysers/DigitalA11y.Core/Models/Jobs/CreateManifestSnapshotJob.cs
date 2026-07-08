namespace DigitalA11y.Core.Models.Jobs;

public record CreateManifestSnapshotJob(
    Guid BatchRunId,
    Guid ConnectorConfigId);