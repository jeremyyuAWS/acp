namespace DigitalA11y.Core.Enums;

public enum AnalysisJobType
{
    /// <summary>Standard analysis — detects issues, creates a compliance record, and enqueues remediation.</summary>
    SCAN,

    /// <summary>Post-remediation verification — re-scans the file to confirm fixes and update compliance. Does not enqueue remediation.</summary>
    CHECK
}
