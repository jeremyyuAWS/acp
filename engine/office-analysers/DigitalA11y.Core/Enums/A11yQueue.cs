namespace DigitalA11y.Core.Enums;

/// <summary>
/// Hangfire queue name constants for routing analysis and remediation jobs to the correct worker.
/// </summary>
public static class A11yQueue
{
    public const string AnalyseDotNet = "analyse-dotnet";
    public const string AnalysePython = "analyse-python";
    public const string RemediateDotNet = "remediate-dotnet";
    public const string RemediatePython = "remediate-python";
    public const string Report = "report";
    public const string Snapshot = "snapshot";

    public static string? GetAnalysisQueue(FileType fileType) => fileType switch
    {
        FileType.DOCX or FileType.PPTX or FileType.XLSX => AnalyseDotNet,
        FileType.PDF  or FileType.HTML                  => AnalysePython,
        _ => null
    };

    public static string GetRemediationQueue(FileType fileType) => fileType switch
    {
        FileType.DOCX or FileType.PPTX or FileType.XLSX => RemediateDotNet,
        FileType.PDF or FileType.HTML => RemediatePython,
        _ => RemediateDotNet
    };
}
