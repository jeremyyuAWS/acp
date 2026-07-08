using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace DigitalA11y.Analysers.DotNet.Docx.Rules;

public class DocumentLanguageRule : IDocxRule
{
    public string RuleId => DocxRuleIds.DocumentLanguage;

    public IEnumerable<A11yIssue> Analyse(WordprocessingDocument document)
    {
        // WCAG 3.1.1 asks for the *programmatically-determinable* language of the content,
        // not merely the dc:language core-property metadata. Word declares the real content
        // language via w:lang — on the style-level default (w:docDefaults/w:rPrDefault/w:rPr/
        // w:lang) and/or per run — which is what assistive tech actually reads. A document is
        // conformant if EITHER the metadata OR the content language is set; only flag when
        // neither is present. (Reading only PackageProperties.Language false-positived every
        // properly-authored doc that set an editing language but left the metadata blank.)
        var metadataLanguage = document.PackageProperties.Language;
        if (!string.IsNullOrWhiteSpace(metadataLanguage) || HasContentLanguage(document))
            yield break;

        yield return new A11yIssue
        {
            IssueId = Guid.NewGuid(),
            RuleId = RuleId,
            Title = "Document language not declared",
            Description = "The document does not declare a language in its metadata or its content (no editing language and no run-level language). Screen readers rely on the language declaration to select the correct speech synthesiser.",
            Severity = IssueSeverity.SERIOUS,
            Category = IssueCategory.LANGUAGE,
            WcagCriterion = WcagCriterion.SC_3_1_1,
            RemediationType = RemediationType.HUMAN_REQUIRED,
            RemediationGuidance = "Set the document language via File → Info → Language (or Review → Language → Set Proofing Language), which writes the editing language onto the document.",
            Location = new IssueLocation { Description = "docx:document-properties:language" },
            Evidence = new IssueEvidence
            {
                Snippet = null,
                ComputedValue = "(not set)",
                ExpectedValue = "A valid BCP 47 language tag, e.g. en-GB"
            }
        };
    }

    // True when the document declares a content language: the style-level default language
    // (applies to every run that does not override it) or any explicit run-level language.
    private static bool HasContentLanguage(WordprocessingDocument document)
    {
        var main = document.MainDocumentPart;
        if (main is null) return false;

        var defaultLang = main.StyleDefinitionsPart?.Styles
            ?.DocDefaults?.RunPropertiesDefault?.RunPropertiesBaseStyle
            ?.GetFirstChild<Languages>();
        if (LangSet(defaultLang)) return true;

        var root = main.Document;
        if (root is not null)
        {
            foreach (var lang in root.Descendants<Languages>())
                if (LangSet(lang)) return true;
        }

        return false;
    }

    private static bool LangSet(Languages? lang)
        => lang is not null && (!string.IsNullOrWhiteSpace(lang.Val)
                                || !string.IsNullOrWhiteSpace(lang.EastAsia)
                                || !string.IsNullOrWhiteSpace(lang.Bidi));
}
