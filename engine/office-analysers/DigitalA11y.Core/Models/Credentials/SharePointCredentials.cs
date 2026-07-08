namespace DigitalA11y.Core.Models.Credentials;

// Models/Credentials/SharePointCredentials.cs
public record SharePointCredentials(
    string TenantId,
    string ClientId,
    string ClientSecret,
    string SiteId,
    string DriveId);
