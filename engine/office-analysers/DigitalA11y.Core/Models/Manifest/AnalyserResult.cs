namespace DigitalA11y.Core.Models.Manifest;

public class AnalyserResult
{
    public string AnalyserName { get; set; } = string.Empty;
    public string AnalyserVersion { get; set; } = string.Empty;
    public DateTimeOffset StartedAt { get; set; }
    public DateTimeOffset CompletedAt { get; set; }
    public bool Succeeded { get; set; }
    public List<A11yIssue> Issues { get; set; } = [];
    public List<AnalyserError> Errors { get; set; } = [];
}
