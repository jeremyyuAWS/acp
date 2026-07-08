namespace DigitalA11y.Core.Helpers;

public static class PathExtensions
{
    public static string CombineWithIdentifier(this string basePath, string? identifier)
    {
        if (string.IsNullOrWhiteSpace(identifier))
            return basePath;

        var cleanIdentifier = identifier.Trim().TrimStart('/', '\\');

        return string.IsNullOrWhiteSpace(cleanIdentifier)
            ? basePath
            : Path.GetFullPath(Path.Combine(basePath, cleanIdentifier));
    }

    /// <summary>
    /// Normalizes a FileIdentifierRoot to a canonical form: forward-slashes, lowercase,
    /// no leading or trailing slashes.
    /// </summary>
    public static string NormalizePath(this string path) =>
        path.Trim().Replace('\\', '/').Trim('/').ToLowerInvariant();

    /// <summary>
    /// Returns true if <paramref name="ancestor"/> is a strict path prefix of
    /// <paramref name="candidate"/> (i.e. candidate is the same path or lives beneath it).
    /// "sites" matches "sites/hr" but NOT "sites-extra".
    /// Both values must already be normalized.
    /// </summary>
    public static bool IsAncestorOrEqualOf(this string ancestor, string candidate) =>
        candidate == ancestor || candidate.StartsWith(ancestor + "/", StringComparison.Ordinal);
}