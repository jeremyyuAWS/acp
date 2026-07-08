namespace DigitalA11y.Core.Models.Credentials;

public record OneDriveWorkDelegatedCredentials(
    string RefreshToken,
    string DriveId);
