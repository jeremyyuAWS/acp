namespace DigitalA11y.Core.Constants;

public static class AuthorizationPolicies
{
    public const string GlobalAdminOnly = "GlobalAdminOnly";
    public const string TenantAdminOrAbove = "TenantAdminOrAbove";
    public const string DeptAdminOrAbove = "DeptAdminOrAbove";
    public const string AnalystOrAbove = "AnalystOrAbove";
    public const string AnyAuthenticatedUser = "AnyAuthenticatedUser";
}