namespace DigitalA11y.Analysers.DotNet.Docx;

public class DocxAnalyserOptions
{
    public string AnalyserName { get; set; } = "DigitalA11y.Analysers.DotNet.Docx";
    public bool SkipColourContrast { get; set; } = false;
    public int MaxFileSizeBytes { get; set; } = 52_428_800; // 50 MB
    public string AnalyserVersion { get; set; } = "1.0.0";
    public string SchemaVersion { get; set; } = "1.0.0";
}
