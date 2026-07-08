namespace DigitalA11y.Core.Contracts.Requests;

public record LoginRequest(string Username, string Password);

public record RefreshTokenRequest(string RefreshToken);

public record ChangePasswordRequest(string CurrentPassword, string NewPassword);

public record ResetPasswordRequest(string NewPassword);

/// <summary>Self-service request to email a password-reset link.</summary>
public record ForgotPasswordRequest(string Email);

/// <summary>Self-service password reset using an emailed token (distinct from admin reset).</summary>
public record ResetPasswordWithTokenRequest(string Email, string Token, string NewPassword);

/// <summary>Self-service update of the current user's own profile.</summary>
public record UpdateMeRequest(string DisplayName);
