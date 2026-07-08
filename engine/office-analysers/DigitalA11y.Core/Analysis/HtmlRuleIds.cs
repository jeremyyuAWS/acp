namespace DigitalA11y.Core.Analysis;

public static class HtmlRuleIds
{
    public const string AltText = "html.alt-text";
    public const string DocumentTitle = "html.document-title";
    public const string HeadingStructure = "html.heading-structure";
    public const string LinkPurpose = "html.link-purpose";
    public const string Language = "html.language";
    public const string HtmlLangValid = "html.html-lang-valid";
    public const string Label = "html.label";
    public const string ColourContrast = "html.colour-contrast";
    public const string TableHeaders = "html.table-headers";
    public const string AriaRoles = "html.aria-roles";
    public const string SkipNav = "html.skip-nav";
    public const string Accessibility = "html.accessibility";

    public static IReadOnlyList<string> All =>
    [
        AltText,
        DocumentTitle,
        HeadingStructure,
        LinkPurpose,
        Language,
        HtmlLangValid,
        Label,
        ColourContrast,
        TableHeaders,
        AriaRoles,
        SkipNav,
        Accessibility,
    ];
}
