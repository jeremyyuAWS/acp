using System.Text.Json;
using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Contracts.Requests;

public record CreateConnectorRequest(
    ConnectorType ConnectorType,
    string Name,
    JsonElement Credentials);

public record UpdateConnectorRequest(
    string Name,
    JsonElement? Credentials);

// Step 1: request device code — no body needed (client id is server config)
public record InitiateOneDrivePersonalRequest;

// Step 2: user has signed in — exchange device code, list drives, cache refresh token
public record ListOneDrivePersonalDrivesRequest(string DeviceCode);

// Step 3: user picked a drive — retrieve cached refresh token and persist connector
public record CompleteOneDrivePersonalRequest(
    string Name,
    string TokenHandle,
    string DriveId);

// Same three-step shape for work/delegated
public record InitiateOneDriveWorkDelegatedRequest;

public record ListOneDriveWorkDelegatedDrivesRequest(string DeviceCode);

public record CompleteOneDriveWorkDelegatedRequest(
    string Name,
    string TokenHandle,
    string DriveId);

public record CreateDepartmentConnectorRequest(
    Guid ConnectorId,
    string FileIdentifierRoot,
    List<string>? ExcludedPaths = null,
    Guid? OutputConnectorConfigId = null,
    string? OutputPathOverride = null);

public record UpdateDepartmentConnectorRequest(
    string FileIdentifierRoot,
    bool IsActive,
    List<string>? ExcludedPaths = null,
    Guid? OutputConnectorConfigId = null,
    string? OutputPathOverride = null);

public record CreateBatchRunRequest(Guid DepartmentConnectorConfigId);

public record UpdateDepartmentPolicyRequest(
    int ArchiveThresholdDays,
    long MaxFileSizeBytes,
    List<string> SupportedExtensions,
    bool AutoRemediationEnabled,
    bool RequireHumanReviewOverride,
    bool ScheduledScanEnabled,
    string? CronExpression);

public record CreateDepartmentRequest(string Name, string Code);

public record UpdateDepartmentRequest(string Name, bool IsActive);

public record CreateUserRequest(
    string Username,
    string Email,
    string Password,
    string Role,
    string? DepartmentCode,
    Guid? TenantId);

public record UpdateUserRequest(
    string DisplayName,
    string Role,
    string? DepartmentCode);
