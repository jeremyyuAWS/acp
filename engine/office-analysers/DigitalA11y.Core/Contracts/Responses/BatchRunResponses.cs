using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Contracts.Responses;

public record BatchRunStatusResponse(
    Guid Id,
    BatchRunStatus Status,
    int FilesDiscovered,
    int TotalJobsEnqueued,
    int CompletedJobs,
    int FailedJobs,
    int PendingJobs,
    DateTimeOffset CreatedAt,
    DateTimeOffset? StartedAt,
    DateTimeOffset? CompletedAt,
    string? FailureReason);

public record BatchRunSummaryResponse(
    Guid Id,
    BatchRunStatus Status,
    DateTimeOffset CreatedAt,
    DateTimeOffset? CompletedAt,
    int TotalJobsEnqueued);

public record AnalysisJobSummaryResponse(
    Guid JobId,
    Guid FileId,
    string FileName,
    FileType FileType,
    JobStatus AnalyseStatus,
    JobStatus? RemediationStatus,
    string QueueName,
    AnalysisJobType JobType,
    DateTimeOffset CreatedAt,
    DateTimeOffset? CompletedAt,
    int? AccessibilityScore,
    int? TotalIssues);
