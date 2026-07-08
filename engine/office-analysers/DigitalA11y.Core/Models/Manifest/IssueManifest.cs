namespace DigitalA11y.Core.Models.Manifest;

/// <summary>
/// The central contract produced by every analyser and consumed by the server.
/// One manifest per file per analysis run.
/// </summary>
public class IssueManifest
{
    public Guid ManifestId { get; set; } = Guid.NewGuid();
    public Guid JobId { get; set; }
    public Guid BatchRunId { get; set; }

    public FileMetadata File { get; set; } = new();

    /// <summary>Results from each analyser that processed this file.</summary>
    public List<AnalyserResult> AnalyserResults { get; set; } = [];

    /// <summary>Flattened view of all issues across all analysers, populated by the server on ingest.</summary>
    public List<A11yIssue> AllIssues { get; set; } = [];

    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public string SchemaVersion { get; set; } = "1.0";
}
