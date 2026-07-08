namespace DigitalA11y.Core.Contracts.Responses;

public record LoginResponse(
    string AccessToken,
    string RefreshToken,
    DateTimeOffset ExpiresAt,
    string DisplayName,
    string Role,
    string? DepartmentCode);

public record RefreshTokenResponse(
    string AccessToken,
    string RefreshToken,
    DateTimeOffset ExpiresAt);

public record UserProfileResponse(
    Guid Id,
    string ExternalUserId,
    string Email,
    string DisplayName,
    string Role,
    Guid? DepartmentId,
    string? DepartmentName,
    string? TenantName,
    bool IsActive,
    DateTimeOffset? LastLoginAt,
    DateTimeOffset CreatedAt);
// PasswordHash never included — lives in Identity, not in UserProfile
