using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Contracts.Responses;

public record FileRecordSummaryResponse(
    Guid Id,
    string FileName,
    string FilePath,
    FileType FileType,
    long FileSizeBytes,
    ArchiveStatus ArchiveStatus,
    DateTimeOffset FirstSeenAt,
    DateTimeOffset LastSeenAt,
    DateTimeOffset? SourceLastModified,
    decimal? ComplianceScore,
    bool? IsCompliant,
    int? TotalIssues,
    int? CriticalIssues,
    JobStatus? LatestJobStatus,
    DateTimeOffset? LatestJobCompletedAt);

public record FileRecordDetailResponse(
    Guid Id,
    Guid DepartmentId,
    Guid ConnectorConfigId,
    string FileName,
    string FilePath,
    FileType FileType,
    long FileSizeBytes,
    string? MimeType,
    string? Sha256Hash,
    ArchiveStatus ArchiveStatus,
    string? ArchiveReason,
    DateTimeOffset FirstSeenAt,
    DateTimeOffset LastSeenAt,
    DateTimeOffset? SourceLastModified,
    LatestComplianceResponse? LatestCompliance,
    List<AnalysisJobBriefResponse> AnalysisJobs,
    List<RemediationJobBriefResponse> RemediationJobs);

public record LatestComplianceResponse(
    Guid Id,
    decimal ComplianceScore,
    bool IsCompliant,
    int TotalIssues,
    int CriticalIssues,
    int SeriousIssues,
    int ModerateIssues,
    int MinorIssues,
    int AutoFixableIssues,
    int HumanRequiredIssues,
    DateTimeOffset ComputedAt);

public record RemediationJobBriefResponse(
    Guid JobId,
    Guid BatchRunId,
    Guid AnalysisJobRecordId,
    string Queue,
    JobStatus Status,
    int IssuesTargeted,
    int IssuesAutoFixed,
    int IssuesPlaceholder,
    int IssuesHumanRequired,
    DateTimeOffset CreatedAt,
    DateTimeOffset? StartedAt,
    DateTimeOffset? CompletedAt,
    string? ErrorMessage);

public record AnalysisJobBriefResponse(
    Guid JobId,
    Guid BatchRunId,
    string Queue,
    JobStatus Status,
    DateTimeOffset CreatedAt,
    DateTimeOffset? StartedAt,
    DateTimeOffset? CompletedAt,
    string? ErrorMessage);

public record FileVersionResponse(
    Guid Id,
    int VersionNumber,
    string Label,
    Guid? RemediationJobRecordId,
    DateTimeOffset CreatedAt);

public record IssueRecordResponse(
    Guid Id,
    Guid FirstDetectedByJobId,
    string RuleId,
    string Title,
    IssueSeverity Severity,
    IssueCategory Category,
    WcagCriterion WcagCriterion,
    RemediationType RemediationType,
    string LocationJson,
    string EvidenceJson,
    bool IsResolved,
    DateTimeOffset? ResolvedAt,
    Guid? ResolvedByRemediationJobId);
