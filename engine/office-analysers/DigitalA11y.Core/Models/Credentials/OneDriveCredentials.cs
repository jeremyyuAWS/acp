namespace DigitalA11y.Core.Models.Credentials;

public record OneDriveWorkCredentials(
    string TenantId,
    string ClientId,
    string ClientSecret,
    string DriveId);
