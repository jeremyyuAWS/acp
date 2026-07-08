namespace DigitalA11y.Core.Enums;

public enum UserRole
{
    GlobalAdmin, //platform-wide,
    TenantAdmin,      // tenant-wide, all departments
    DeptAdmin,  // manages own department connectors and policy
    Analyst,    // triggers scans, views reports
    Viewer      // read-only access to reports
}
