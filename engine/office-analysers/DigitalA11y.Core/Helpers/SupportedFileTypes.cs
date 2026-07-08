using DigitalA11y.Core.Enums;
using System.Collections.Immutable;

namespace DigitalA11y.Core.Helpers;

public static class SupportedFileTypes
{
    public static readonly ImmutableHashSet<FileType> All = ImmutableHashSet.Create(
        FileType.DOCX,
        FileType.PPTX,
        FileType.XLSX,
        FileType.PDF,
        FileType.HTML
    );

    public static readonly ImmutableHashSet<string> AllExtensions = ImmutableHashSet.Create(
        ".docx",
        ".pptx",
        ".xlsx",
        ".pdf",
        ".html",
        ".htm"
    );
}