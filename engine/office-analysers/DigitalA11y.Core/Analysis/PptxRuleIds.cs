namespace DigitalA11y.Core.Analysis;

public static class PptxRuleIds
{
    public const string SlideTitle = "PPTX-TITLE-001";
    public const string AltText = "PPTX-ALT-001";
    public const string ReadingOrder = "PPTX-ORDER-001";
    public const string ColourContrast = "PPTX-CONTRAST-001";
    public const string TableHeaders = "PPTX-TABLE-001";
    public const string DocumentLanguage = "PPTX-LANG-001";
    public const string LinkPurpose = "PPTX-LINK-001";
    public const string AnimationOrder = "PPTX-ANIM-001";

    public static IReadOnlyList<string> All =>
    [
        SlideTitle,
        AltText,
        ReadingOrder,
        ColourContrast,
        TableHeaders,
        DocumentLanguage,
        LinkPurpose,
        AnimationOrder,
    ];
}
