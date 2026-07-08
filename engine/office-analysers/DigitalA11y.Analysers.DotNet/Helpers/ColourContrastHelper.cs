namespace DigitalA11y.Analysers.DotNet.Helpers;

public static class ColourContrastHelper
{
    /// <summary>
    /// Calculates the WCAG 2.2 contrast ratio between two hex colours.
    /// </summary>
    /// <param name="hexForeground">Foreground colour as RRGGBB (no #).</param>
    /// <param name="hexBackground">Background colour as RRGGBB (no #).</param>
    public static double GetContrastRatio(string hexForeground, string hexBackground)
    {
        double l1 = GetRelativeLuminance(hexForeground);
        double l2 = GetRelativeLuminance(hexBackground);

        double lighter = Math.Max(l1, l2);
        double darker = Math.Min(l1, l2);

        return (lighter + 0.05) / (darker + 0.05);
    }

    /// <summary>
    /// Calculates relative luminance per WCAG 2.2 formula.
    /// </summary>
    /// <param name="hex">Colour as RRGGBB (no #).</param>
    public static double GetRelativeLuminance(string hex)
    {
        if (hex.Length != 6)
            return 1.0; // treat malformed as white

        double r = Linearise(Convert.ToInt32(hex[..2], 16) / 255.0);
        double g = Linearise(Convert.ToInt32(hex[2..4], 16) / 255.0);
        double b = Linearise(Convert.ToInt32(hex[4..6], 16) / 255.0);

        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    }

    /// <summary>
    /// Returns true if the text qualifies as "large text" under WCAG 2.2
    /// (18pt+ normal, or 14pt+ bold).
    /// </summary>
    /// <param name="fontSize">Font size as a half-point string (Open XML stores sizes in half-points).</param>
    /// <param name="isBold">Whether the run is bold.</param>
    public static bool IsLargeText(string? fontSize, bool isBold)
    {
        if (fontSize is null)
            return false;

        if (!double.TryParse(fontSize, out double halfPoints))
            return false;

        double points = halfPoints / 2.0;

        return isBold ? points >= 14.0 : points >= 18.0;
    }

    private static double Linearise(double c)
        => c <= 0.04045 ? c / 12.92 : Math.Pow((c + 0.055) / 1.055, 2.4);
}
