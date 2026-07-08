using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

/// <summary>
/// The DigitalA11y-domain identity. Links to the auth provider user via ExternalUserId.
/// In v1 (EF Core Identity): IdentityUser.Id
/// In future (Keycloak): Keycloak sub claim
/// In future (Azure AD): Entra ID object ID
/// This entity must NEVER contain a PasswordHash — passwords live in the Identity tables.
/// </summary>
public class UserProfile : BaseAuditableEntity
{
    /// <summary>
    /// Stable reference to the identity provider user. Never changes when auth provider switches.
    /// </summary>
    public string ExternalUserId { get; set; } = "";

    /// <summary>Cached from identity provider for display — not authoritative.</summary>
    public string Email { get; set; } = "";

    /// <summary>Cached from identity provider for display — not authoritative.</summary>
    public string DisplayName { get; set; } = "";

    /// <summary>DigitalA11y-specific role — independent of Identity roles.</summary>
    public UserRole Role { get; set; }

    /// <summary>Null = platform admin with no department restriction.</summary>
    public Guid? DepartmentId { get; set; }
    public Department? Department { get; set; }

    public bool IsActive { get; set; } = true;
    public DateTimeOffset? LastLoginAt { get; set; }
}
