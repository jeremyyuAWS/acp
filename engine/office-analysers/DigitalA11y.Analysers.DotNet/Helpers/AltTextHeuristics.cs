using System.Text.RegularExpressions;

namespace DigitalA11y.Analysers.DotNet.Helpers;

/// <summary>
/// Shared heuristics for spotting non-descriptive image alt text (WCAG 1.1.1).
/// A non-empty <c>descr</c> is not automatically meaningful: authoring tools and
/// slide templates routinely leave the source file name or path in it
/// (e.g. "icons/user.png"), which a screen reader announces verbatim
/// ("icons slash user dot png") and which conveys nothing about the image.
/// </summary>
public static class AltTextHeuristics
{
    // A bare image file name, e.g. "user.png", "diagram.jpeg", "logo.emf".
    // Anchored end-to-end so it only matches when the WHOLE (trimmed) value is a
    // file name — never prose that merely mentions a file. A part name the
    // authoring tool copies in (word "media/image1.png", pptx "image1.png") is
    // caught here (extension) or by the slash check below, so no separate
    // part-name comparison is needed.
    private static readonly Regex ImageFilename = new(
        @"^[^\s/\\]+\.(png|jpe?g|gif|bmp|svg|tiff?|emf|wmf)$",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    /// <summary>
    /// True when <paramref name="description"/> reads like a file path or image
    /// file name rather than a human description — e.g. "icons/user.png",
    /// "media\image1.png", "logo.svg".
    /// </summary>
    /// <remarks>
    /// A real description is a phrase (it has spaces); a path or file name is a
    /// single whitespace-free token. Requiring "no interior whitespace" keeps
    /// legitimate prose that happens to contain a slash — "input/output diagram",
    /// "24/7 support" — from being flagged.
    /// </remarks>
    public static bool LooksLikeFilenameOrPath(string? description)
    {
        if (string.IsNullOrWhiteSpace(description)) return false;
        var trimmed = description.Trim();
        if (trimmed.Any(char.IsWhiteSpace)) return false;
        if (trimmed.Contains('/') || trimmed.Contains('\\')) return true;
        return ImageFilename.IsMatch(trimmed);
    }
}
