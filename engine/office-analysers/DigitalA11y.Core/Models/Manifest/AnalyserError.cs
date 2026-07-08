namespace DigitalA11y.Core.Models.Manifest;

public class AnalyserError
{
    public string Code { get; set; } = string.Empty;
    public string Message { get; set; } = string.Empty;
    public string? Detail { get; set; }
    public DateTimeOffset OccurredAt { get; set; } = DateTimeOffset.UtcNow;

    //FileNotFoundError
    public static AnalyserError FileNotFoundError(string filePath) => new()
    {
        Code = "FILE_NOT_FOUND",
        Message = $"The file '{filePath}' was not found."
    };

    public static AnalyserError InvalidFileFormatError(string filePath, string expectedFormat) => new()
    {
        Code = "INVALID_FILE_FORMAT",
        Message = $"The file '{filePath}' is not in the expected format: {expectedFormat}"
    };

    public static AnalyserError FileTooLargeError(string filePath, long fileSize, long maxSize) => new()
    {
        Code = "FILE_TOO_LARGE",
        Message = $"File size {fileSize} bytes exceeds the maximum of {maxSize} bytes for file: {filePath}"
    };

    public static AnalyserError RuleExecutionError(string ruleName, Exception ex) => new()
    {
        Code = $"RULE_EXECUTION_ERROR_{ruleName}",
        Message = $"Rule {ruleName} threw an exception and was skipped.",
        Detail = ex.ToString()
    };

    public static AnalyserError FileOpenFailed(string fileType, Exception ex) => new()
    {
        Code = "OPEN_FAILED",
        Message = $"Failed to open the {fileType} file.",
        Detail = ex.ToString()
    };
}
