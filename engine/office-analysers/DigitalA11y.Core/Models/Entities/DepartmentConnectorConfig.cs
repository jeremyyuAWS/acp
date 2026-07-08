namespace DigitalA11y.Core.Models.Entities;

/// <summary>
/// Many-to-Many relationship + per-department configuration.
/// Allows multiple departments to reuse the same Connector with different file locations.
/// </summary>
public class DepartmentConnectorConfig: BaseAuditableEntity
{
    public Guid DepartmentId { get; set; }
    public Department Department { get; set; } = null!;

    public Guid ConnectorId { get; set; }
    public ConnectorConfig Connector { get; set; } = null!;

    /// <summary>
    /// Department-specific path inside the connector.
    /// Example: "sites/HR", "Departments/Finance", "\\server\shares\Lagos\"
    /// Combined with Connector.BaseUrl to get full location.
    /// </summary>
    public string FileIdentifierRoot { get; set; } = "";

    public bool IsActive { get; set; } = true;

    /// <summary>
    /// Relative path segments that the scanner will skip.
    /// Supports partial matching — any file whose path contains one of these segments is excluded.
    /// Defaults to ["__versions__"] on creation.
    /// </summary>
    public List<string> ExcludedPaths { get; set; } = ["__versions__"];

    /// <summary>
    /// When set, remediated files are written to this connector instead of the source connector.
    /// Null means output goes back to the same connector (default behaviour).
    /// </summary>
    public Guid? OutputConnectorConfigId { get; set; }
    public ConnectorConfig? OutputConnector { get; set; }

    /// <summary>
    /// Optional path override on the output connector.
    /// When null the original file's relative path is preserved on the output connector.
    /// </summary>
    public string? OutputPathOverride { get; set; }
}