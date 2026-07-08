namespace DigitalA11y.Core.Models.Jobs;

public record JobNotificationInfo(
    Guid BatchRunId,
    Guid DepartmentId,
    string DepartmentName,
    string? UserEmail,
    string UserDisplayName,
    int FilesProcessed,
    int IssuesFixed);
