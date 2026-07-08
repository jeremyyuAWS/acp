namespace DigitalA11y.Core.Models.Entities;

public class Department : BaseAuditableEntity
{
    public string Name { get; set; } = string.Empty;
    public string Code { get; set; } = "";
    public bool IsActive { get; set; } = true;

    // Navigation
    public DepartmentPolicy? Policy { get; set; }

    public ICollection<DepartmentConnectorConfig> DepartmentConnectorConfigs { get; set; } = new List<DepartmentConnectorConfig>();

    public ICollection<UserProfile> UserProfiles { get; set; } = new List<UserProfile>();

    // Kept for pipeline compatibility
    public ICollection<FileRecord> Files { get; set; } = [];
    public ICollection<DepartmentAnalyserConfig> AnalyserConfigs { get; set; } = [];
}