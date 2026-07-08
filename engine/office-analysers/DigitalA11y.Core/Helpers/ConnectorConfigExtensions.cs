using DigitalA11y.Core.Models.Entities;

namespace DigitalA11y.Core.Helpers;

public static class ConnectorConfigExtensions
{
    public static ConnectorConfig DecryptedCopy(ConnectorConfig config, string plainJson) =>
        new()
        {
            Id = config.Id,
            ConnectorType = config.ConnectorType,
            Name = config.Name,
            EncryptedCredentials = plainJson,
            IsActive = config.IsActive,
            ValidationStatus = config.ValidationStatus,
            LastValidatedAt = config.LastValidatedAt,
            LastValidationError = config.LastValidationError,
            CreatedAt = config.CreatedAt,
            UpdatedAt = config.UpdatedAt,
            CreatedBy = config.CreatedBy,
            UpdatedBy = config.UpdatedBy
        };
}
