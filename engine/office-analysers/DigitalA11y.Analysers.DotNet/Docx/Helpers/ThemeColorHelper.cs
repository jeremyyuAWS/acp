using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using A = DocumentFormat.OpenXml.Drawing;

namespace DigitalA11y.Analysers.DotNet.Docx.Helpers;

/// <summary>
/// Resolves WordprocessingML <c>w:themeColor</c> (+ <c>w:themeTint</c>/<c>w:themeShade</c>)
/// references against the document's <c>theme1.xml</c> colour scheme. A run coloured via
/// theme rather than a direct <c>w:color/@val</c> hex was previously invisible to contrast
/// checks — this is the only place that resolution happens.
/// </summary>
public static class ThemeColorHelper
{
    /// <summary>Builds the 12-slot theme colour scheme (hex, no '#') from a document's ThemePart.</summary>
    public static Dictionary<ThemeColorValues, string> BuildScheme(ThemePart? themePart)
    {
        var scheme = new Dictionary<ThemeColorValues, string>();
        var clrScheme = themePart?.Theme?.ThemeElements?.ColorScheme;
        if (clrScheme is null) return scheme;

        void Add(ThemeColorValues key, DocumentFormat.OpenXml.OpenXmlCompositeElement? colour)
        {
            var hex = ResolveDrawingColor(colour);
            if (hex is not null) scheme[key] = hex;
        }

        Add(ThemeColorValues.Dark1, clrScheme.Dark1Color);
        Add(ThemeColorValues.Light1, clrScheme.Light1Color);
        Add(ThemeColorValues.Dark2, clrScheme.Dark2Color);
        Add(ThemeColorValues.Light2, clrScheme.Light2Color);
        Add(ThemeColorValues.Accent1, clrScheme.Accent1Color);
        Add(ThemeColorValues.Accent2, clrScheme.Accent2Color);
        Add(ThemeColorValues.Accent3, clrScheme.Accent3Color);
        Add(ThemeColorValues.Accent4, clrScheme.Accent4Color);
        Add(ThemeColorValues.Accent5, clrScheme.Accent5Color);
        Add(ThemeColorValues.Accent6, clrScheme.Accent6Color);
        Add(ThemeColorValues.Hyperlink, clrScheme.Hyperlink);
        Add(ThemeColorValues.FollowedHyperlink, clrScheme.FollowedHyperlinkColor);

        // WordprocessingML's background1/text1/background2/text2 aliases map onto the
        // clrScheme's light1/dark1/light2/dark2 slots (ECMA-376 §17.3.2.6 clrMap default).
        if (scheme.TryGetValue(ThemeColorValues.Light1, out var lt1)) scheme[ThemeColorValues.Background1] = lt1;
        if (scheme.TryGetValue(ThemeColorValues.Dark1, out var dk1)) scheme[ThemeColorValues.Text1] = dk1;
        if (scheme.TryGetValue(ThemeColorValues.Light2, out var lt2)) scheme[ThemeColorValues.Background2] = lt2;
        if (scheme.TryGetValue(ThemeColorValues.Dark2, out var dk2)) scheme[ThemeColorValues.Text2] = dk2;

        return scheme;
    }

    private static string? ResolveDrawingColor(DocumentFormat.OpenXml.OpenXmlCompositeElement? colour)
    {
        var hex = colour?.GetFirstChild<A.RgbColorModelHex>()?.Val?.Value;
        if (!string.IsNullOrWhiteSpace(hex)) return hex.ToUpperInvariant();

        // a:sysClr (dk1/lt1 are frequently "windowText"/"window" system colours rather
        // than an explicit srgbClr) carries the resolved value in @lastClr.
        var sysHex = colour?.GetFirstChild<A.SystemColor>()?.LastColor?.Value;
        return string.IsNullOrWhiteSpace(sysHex) ? null : sysHex.ToUpperInvariant();
    }

    /// <summary>
    /// Resolves a run's theme colour reference to a final #RRGGBB hex, applying
    /// <paramref name="themeTint"/>/<paramref name="themeShade"/> (each a 2-digit hex byte,
    /// 00-FF) on top of the scheme's base colour. Returns null if the theme colour or scheme
    /// slot is unresolvable — callers should skip rather than guess, same posture as the
    /// no-colour-at-all case.
    /// </summary>
    public static string? Resolve(
        ThemeColorValues? themeColor,
        string? themeTint,
        string? themeShade,
        Dictionary<ThemeColorValues, string> scheme)
    {
        if (themeColor is null || themeColor == ThemeColorValues.None) return null;
        if (!scheme.TryGetValue(themeColor.Value, out var baseHex)) return null;

        if (string.IsNullOrWhiteSpace(themeTint) && string.IsNullOrWhiteSpace(themeShade))
            return baseHex;

        return ApplyTintShade(baseHex, themeTint, themeShade);
    }

    /// <summary>
    /// ECMA-376 theme tint/shade: convert to HSL, scale the Luminance channel toward white
    /// (tint) or black (shade) by the given fraction (byte/255.0), convert back to RGB.
    /// Hue and Saturation are preserved — only lightness moves.
    /// </summary>
    private static string ApplyTintShade(string baseHex, string? themeTint, string? themeShade)
    {
        var (h, s, l) = RgbToHsl(baseHex);

        if (!string.IsNullOrWhiteSpace(themeShade) && TryParseFraction(themeShade, out double shade))
        {
            l *= shade;
        }
        else if (!string.IsNullOrWhiteSpace(themeTint) && TryParseFraction(themeTint, out double tint))
        {
            l = l * tint + (1.0 - tint);
        }

        return HslToRgb(h, s, Math.Clamp(l, 0.0, 1.0));
    }

    /// <summary>w:themeTint/w:themeShade store a hex byte (00-FF) representing a 0.0-1.0 fraction.</summary>
    private static bool TryParseFraction(string hexByte, out double fraction)
    {
        if (byte.TryParse(hexByte, System.Globalization.NumberStyles.HexNumber, null, out byte b))
        {
            fraction = b / 255.0;
            return true;
        }
        fraction = 0;
        return false;
    }

    private static (double h, double s, double l) RgbToHsl(string hex)
    {
        double r = Convert.ToInt32(hex[..2], 16) / 255.0;
        double g = Convert.ToInt32(hex[2..4], 16) / 255.0;
        double b = Convert.ToInt32(hex[4..6], 16) / 255.0;

        double max = Math.Max(r, Math.Max(g, b));
        double min = Math.Min(r, Math.Min(g, b));
        double l = (max + min) / 2.0;

        if (max == min) return (0, 0, l);

        double d = max - min;
        double s = l > 0.5 ? d / (2.0 - max - min) : d / (max + min);

        double h;
        if (max == r) h = (g - b) / d + (g < b ? 6 : 0);
        else if (max == g) h = (b - r) / d + 2;
        else h = (r - g) / d + 4;
        h /= 6.0;

        return (h, s, l);
    }

    private static string HslToRgb(double h, double s, double l)
    {
        double r, g, b;
        if (s == 0)
        {
            r = g = b = l;
        }
        else
        {
            double q = l < 0.5 ? l * (1 + s) : l + s - l * s;
            double p = 2 * l - q;
            r = HueToRgb(p, q, h + 1.0 / 3.0);
            g = HueToRgb(p, q, h);
            b = HueToRgb(p, q, h - 1.0 / 3.0);
        }

        return $"{ToByte(r):X2}{ToByte(g):X2}{ToByte(b):X2}";
    }

    private static double HueToRgb(double p, double q, double t)
    {
        if (t < 0) t += 1;
        if (t > 1) t -= 1;
        if (t < 1.0 / 6.0) return p + (q - p) * 6 * t;
        if (t < 1.0 / 2.0) return q;
        if (t < 2.0 / 3.0) return p + (q - p) * (2.0 / 3.0 - t) * 6;
        return p;
    }

    private static int ToByte(double c) => (int)Math.Round(Math.Clamp(c, 0.0, 1.0) * 255.0);
}
