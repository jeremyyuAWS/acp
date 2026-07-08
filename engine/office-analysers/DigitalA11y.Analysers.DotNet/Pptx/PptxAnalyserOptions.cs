namespace DigitalA11y.Analysers.DotNet.Pptx;

public class PptxAnalyserOptions
{
    public string AnalyserName { get; set; } = "DigitalA11y.Analysers.DotNet.Pptx";
    public bool SkipColourContrast { get; set; } = false;
    public bool SkipAnimationCheck { get; set; } = false;
    public int MaxFileSizeBytes { get; set; } = 104_857_600; // 100 MB
    public int SlideTimeoutSeconds { get; set; } = 10;
    public string AnalyserVersion { get; set; } = "1.0.0";
    public string SchemaVersion { get; set; } = "1.0.0";
}
