namespace DigitalA11y.Analysers.DotNet.Xlsx;

public class XlsxAnalyserOptions
{
    public string AnalyserName { get; set; } = "DigitalA11y.Analysers.DotNet.Xlsx";
    public int MaxFileSizeBytes { get; set; } = 52_428_800; // 50 MB
    public string AnalyserVersion { get; set; } = "1.0.0";
    public string SchemaVersion { get; set; } = "1.0.0";
}
