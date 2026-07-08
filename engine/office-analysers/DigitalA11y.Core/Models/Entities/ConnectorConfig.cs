using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

/// <summary>
/// Tenant-scoped connector definition (e.g. SharePoint site, file share, OneDrive).
/// Managed by tenant admins. Departments link to these via DepartmentConnectorConfig.
/// </summary>
public class ConnectorConfig : BaseAuditableEntity
{
    public ConnectorType ConnectorType { get; set; }

    public string Name { get; set; } = "";                    // e.g. "Corporate SharePoint", "Lagos File Server"

    /// <summary>
    /// AES-256-CBC encrypted JSON of the typed credentials.
    /// Never returned in regular API responses.
    /// </summary>
    public string EncryptedCredentials { get; set; } = "";

    public bool IsActive { get; set; } = true;

    public ConnectorValidationStatus ValidationStatus { get; set; } = ConnectorValidationStatus.Unknown;
    public DateTimeOffset? LastValidatedAt { get; set; }
    public string? LastValidationError { get; set; }

    // Navigation (optional, for eager loading)
    public ICollection<DepartmentConnectorConfig> DepartmentConnectorConfigs { get; set; } = new List<DepartmentConnectorConfig>();
}
