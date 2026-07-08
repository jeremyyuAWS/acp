namespace DigitalA11y.Core.Models.Entities;

/// <summary>
/// Tenant-scoped key-value configuration stored in the database.
/// Provides defaults for engine settings that can be overridden per-department via DepartmentPolicy.
/// </summary>
public class SystemConfig : BaseAuditableEntity
{
    /// <summary>Unique dotted key, e.g. SystemConfigKeys.ClassificationMagicBytesEnabled</summary>
    public string Key { get; set; } = "";

    public string Value { get; set; } = "";
    public string Description { get; set; } = "";

    /// <summary>false = read-only from the admin UI; still readable by code.</summary>
    public bool IsEditable { get; set; } = true;
}
