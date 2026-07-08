namespace DigitalA11y.Core.Models.Credentials;

public record SftpCredentials(
    string Host,
    int Port,
    string Username,
    string Password,
    bool AcceptAllCertificates);
