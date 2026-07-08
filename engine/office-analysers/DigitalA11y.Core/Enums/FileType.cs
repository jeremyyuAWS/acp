namespace DigitalA11y.Core.Enums;

public enum FileType
{
    UNKNOWN,
    PDF,
    DOCX,
    PPTX,
    HTML,
    XLSX
}


// Todo: Consider supporting older binary formats (e.g. DOC, PPT, XLS).
// - Pros: May be necessary for some organisations with legacy content.
// - Cons: More complex parsing, more edge cases, higher maintenance burden.
// - Alternative: For unsupported formats, require users to convert to a supported format before analysis.
// - Or potentially use a third-party library that can handle such conversion