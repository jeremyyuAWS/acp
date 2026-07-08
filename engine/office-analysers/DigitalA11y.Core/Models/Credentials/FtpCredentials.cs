namespace DigitalA11y.Core.Models.Credentials;

public record FtpCredentials(
    string Host,
    int Port,
    string Username,
    string Password,
    bool PassiveMode,
    bool RequireTls);
