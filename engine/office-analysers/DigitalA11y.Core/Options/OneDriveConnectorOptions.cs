namespace DigitalA11y.Core.Options;

public class OneDriveConnectorOptions
{
    public const string GraphScope = "https://graph.microsoft.com/.default";


    public string PersonalClientId { get; set; } = "";

    public const string PersonalTokenEndpoint = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token";
    public const string PersonalDeviceCodeEndpoint = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode";


    public string WorkDelegatedClientId { get; set; } = "";

    public const string WorkDelegatedTokenEndpoint = "https://login.microsoftonline.com/organizations/oauth2/v2.0/token";
    public const string WorkDelegatedDeviceCodeEndpoint = "https://login.microsoftonline.com/organizations/oauth2/v2.0/devicecode";
}
