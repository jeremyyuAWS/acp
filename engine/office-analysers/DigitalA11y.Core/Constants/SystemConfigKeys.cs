namespace DigitalA11y.Core.Constants;

public static class SystemConfigKeys
{
    // Classification
    public const string ClassificationMagicBytesEnabled = "Classification:MagicBytesEnabled";
    public const string ClassificationMagicBytesReadLength = "Classification:MagicBytesReadLength";

    // Hangfire Worker Counts
    public const string HangfireDotNetWorkerCount = "Hangfire:DotNetWorkerCount";
    public const string HangfirePythonWorkerCount = "Hangfire:PythonWorkerCount";
    public const string HangfireRemediationWorkerCount = "Hangfire:RemediationWorkerCount";

    // Archive
    public const string ArchiveMaxFileSizeBytes = "Archive:MaxFileSizeBytes";
    public const string ArchiveArchiveThresholdDays = "Archive:ArchiveThresholdDays";

    // Email notifications
    public const string EmailNotificationsEnabled = "Email:NotificationsEnabled";

    // Webhooks
    public const string WebhooksEnabled = "Webhooks:Enabled";

    // LLM budget / cost cap
    public const string LlmMonthlyCapEnabled             = "Llm:MonthlyCapEnabled";
    public const string LlmMonthlyCapTokenLimit          = "Llm:MonthlyCapTokenLimit";
    public const string LlmCostPerMillionInputTokens     = "Llm:CostPerMillionInputTokens";
    public const string LlmCostPerMillionOutputTokens    = "Llm:CostPerMillionOutputTokens";

    // Remediation controls
    public const string RemediationAllowLlm                    = "Remediation:AllowLlm";
    public const string RemediationAllowPlaceholders           = "Remediation:AllowPlaceholders";
    public const string RemediationMaxCriticalIssues           = "Remediation:MaxCriticalIssues";
    public const string RemediationMaxHighIssues               = "Remediation:MaxHighIssues";
    public const string RemediationMaxMediumIssues             = "Remediation:MaxMediumIssues";
    public const string RemediationMaxLowIssues                = "Remediation:MaxLowIssues";
    public const string RemediationMaxTotalIssues              = "Remediation:MaxTotalIssues";
    public const string RemediationPendingApprovalTimeoutHours = "Remediation:PendingApprovalTimeoutHours";
}
