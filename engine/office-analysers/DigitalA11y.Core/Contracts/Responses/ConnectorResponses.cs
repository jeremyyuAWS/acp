using System.Text.Json;
using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Contracts.Responses;

public record ConnectorDetailResponse(
    Guid Id,
    ConnectorType ConnectorType,
    string Name,
    bool IsActive,
    ConnectorValidationStatus ValidationStatus,
    DateTimeOffset? LastValidatedAt,
    string? LastValidationError,
    JsonElement Credentials);

public record ConnectorResponse(
    Guid Id,
    ConnectorType ConnectorType,
    string Name,
    bool IsActive,
    ConnectorValidationStatus ValidationStatus,
    DateTimeOffset? LastValidatedAt,
    string? LastValidationError);

public record DepartmentPolicyResponse(
    string DepartmentCode,
    int ArchiveThresholdDays,
    long MaxFileSizeBytes,
    List<string> SupportedExtensions,
    bool AutoRemediationEnabled,
    bool RequireHumanReviewOverride,
    bool ScheduledScanEnabled,
    string? CronExpression,
    DateTimeOffset UpdatedAt,
    string UpdatedBy);

public record DepartmentResponse(
    string Name,
    string Code,
    bool IsActive,
    int ConnectorCount,
    int UserCount,
    DateTimeOffset CreatedAt);

public record ConnectorValidationResult(
    bool IsValid,
    ConnectorValidationStatus Status,
    string? ErrorMessage);

public record OneDriveDriveItem(string Id, string Name, string DriveType);

public record ListDrivesResponse(string TokenHandle, List<OneDriveDriveItem> Drives);

public record DepartmentConnectorConfigResponse(
    Guid Id,
    Guid DepartmentId,
    Guid ConnectorId,
    string ConnectorName,
    ConnectorType ConnectorType,
    string FileIdentifierRoot,
    bool IsActive,
    List<string> ExcludedPaths,
    DateTimeOffset CreatedAt,
    Guid? OutputConnectorConfigId = null,
    string? OutputConnectorName = null,
    string? OutputPathOverride = null);
