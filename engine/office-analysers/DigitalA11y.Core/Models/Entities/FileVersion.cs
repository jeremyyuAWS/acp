namespace DigitalA11y.Core.Models.Entities;

public class FileVersion : BaseTenantEntity
{
    public Guid FileRecordId { get; set; }

    /// <summary>Null for version 0 (original captured before first remediation).</summary>
    public Guid? RemediationJobRecordId { get; set; }

    /// <summary>0 = original/unremediated. Increments by 1 for each successful remediation.</summary>
    public int VersionNumber { get; set; }

    /// <summary>
    /// Connector-specific path where this version is stored in the __versions__ subfolder.
    /// NetworkDrive: full filesystem path. SharePoint/OneDrive: Graph drive item ID.
    /// </summary>
    public string VersionedFilePath { get; set; } = string.Empty;

    /// <summary>Human-readable label, e.g. "Original", "Remediated v1".</summary>
    public string Label { get; set; } = string.Empty;

    // Navigation
    public FileRecord FileRecord { get; set; } = null!;
    public RemediationJobRecord? RemediationJobRecord { get; set; }
}
