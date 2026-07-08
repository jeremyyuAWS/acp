using System;
using System.Collections.Generic;
using System.Text;

namespace DigitalA11y.Core.Models.Credentials;

// Models/Credentials/NetworkDriveCredentials.cs
public record NetworkDriveCredentials(
    string RootPath,
    string? Username,    // null = current process identity
    string? Password,
    string? Domain);