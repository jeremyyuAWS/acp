using DigitalA11y.Analysers.DotNet.Pptx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using A = DocumentFormat.OpenXml.Drawing;

namespace DigitalA11y.Analysers.DotNet.Pptx.Rules;

public class DocumentLanguageRule : IPptxRule
{
    public string RuleId => PptxRuleIds.DocumentLanguage;

    public IEnumerable<A11yIssue> AnalyseSlide(
        SlidePart slidePart,
        int slideIndex,
        PresentationDocument document)
    {
        if (slideIndex != 0) yield break;

        // WCAG 3.1.1 wants the programmatically-determinable content language, not just the
        // dc:language core-property metadata. PowerPoint stores the real language as the
        // lang attribute on every text run (a:rPr/@lang) and end-paragraph mark
        // (a:endParaRPr/@lang). A presentation is conformant if EITHER the metadata OR a
        // content language is declared; only flag when neither exists. (Reading only
        // PackageProperties.Language false-positived essentially every real deck, whose runs
        // always carry a lang even when the document metadata is blank.)
        var metadataLanguage = document.PackageProperties.Language;
        if (!string.IsNullOrWhiteSpace(metadataLanguage) || HasContentLanguage(document))
            yield break;

        yield return new A11yIssue
        {
            IssueId = Guid.NewGuid(),
            RuleId = RuleId,
            Title = "Presentation language not declared",
            Description = "The presentation does not declare a language in its metadata or on any of its text (no run-level language attribute). Screen readers cannot determine the correct language for text-to-speech rendering.",
            Severity = IssueSeverity.SERIOUS,
            Category = IssueCategory.LANGUAGE,
            WcagCriterion = WcagCriterion.SC_3_1_1,
            RemediationType = RemediationType.AUTO_PLACEHOLDER,
            RemediationGuidance = "Set the editing language in PowerPoint (Review > Language > Set Proofing Language) to declare the primary language of the presentation.",
            Location = LocationHelper.FromSlide(0),
            Evidence = new IssueEvidence
            {
                ComputedValue = "(no language declared)",
                ExpectedValue = "A valid BCP-47 language tag such as 'en-GB'"
            }
        };
    }

    // True when any run or end-paragraph mark on a slide, layout, or master declares a
    // language via its lang or altLang attribute — the signals assistive tech actually
    // reads. altLang is DrawingML's east-Asian-language counterpart to lang (e.g. CJK text
    // in a deck whose primary language is Latin-script); PowerPoint treats a run tagged only
    // via altLang as language-declared, so this must too.
    private static bool HasContentLanguage(PresentationDocument document)
    {
        var pres = document.PresentationPart;
        if (pres is null) return false;

        var parts = pres.SlideParts.Cast<OpenXmlPart>()
            .Concat(pres.SlideMasterParts)
            .Concat(pres.SlideMasterParts.SelectMany(m => m.SlideLayoutParts));

        foreach (var part in parts)
        {
            var root = part.RootElement;
            if (root is null) continue;
            foreach (var rpr in root.Descendants<A.RunProperties>())
                if (!string.IsNullOrWhiteSpace(rpr.Language) || !string.IsNullOrWhiteSpace(rpr.AlternativeLanguage))
                    return true;
            foreach (var epr in root.Descendants<A.EndParagraphRunProperties>())
                if (!string.IsNullOrWhiteSpace(epr.Language) || !string.IsNullOrWhiteSpace(epr.AlternativeLanguage))
                    return true;
        }

        return false;
    }
}
