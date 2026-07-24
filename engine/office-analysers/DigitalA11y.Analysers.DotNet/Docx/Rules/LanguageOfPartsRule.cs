using DigitalA11y.Analysers.DotNet.Docx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace DigitalA11y.Analysers.DotNet.Docx.Rules;

// WCAG 3.1.2 (Language of Parts) — a passage in a language different from the document's
// must carry its own language marker. ADR 0012 originally deferred giving this its own
// WcagCriterion member and reported it under SC_3_1_1 instead — SC_3_1_2 is now a real
// enum value (WcagCriterion.cs) and this rule reports under it directly, distinct from
// DocumentLanguageRule's SC_3_1_1. The original rule flagged EVERY 20+ word run that
// lacked an explicit w:lang — but a run with no lang simply inherits the document/style
// default language and is therefore already programmatically determinable, so that fired
// on ordinary single-language documents (a false-positive flood). A run is only a genuine
// 3.1.2 concern when it is positively in a DIFFERENT script from the document body and
// carries no language of its own. That is the signal we can determine deterministically.
public class LanguageOfPartsRule : IDocxRule
{
    public string RuleId => DocxRuleIds.LanguageOfParts;

    private const int MinWordCount = 20;

    private enum Script { Latin, Cyrillic, Greek, Hebrew, Arabic, Cjk, Other }

    public IEnumerable<A11yIssue> Analyse(WordprocessingDocument document)
    {
        var body = document.MainDocumentPart?.Document?.Body;
        if (body is null) yield break;

        var paragraphs = body.Descendants<Paragraph>().ToList();

        // The document's dominant script, computed from all of its text. Runs that match it
        // inherit the document language and need no explicit marker.
        var docScript = DominantScript(string.Concat(
            body.Descendants<Text>().Select(t => t.Text)));
        if (docScript == Script.Other) yield break;

        for (int paraIdx = 0; paraIdx < paragraphs.Count; paraIdx++)
        {
            foreach (var run in paragraphs[paraIdx].Descendants<Run>())
            {
                // A run that declares its own language is already conformant.
                if (run.RunProperties?.Languages is not null)
                    continue;

                string runText = string.Concat(run.Descendants<Text>().Select(t => t.Text));
                if (CountWords(runText) < MinWordCount)
                    continue;

                var runScript = DominantScript(runText);
                if (runScript == Script.Other || runScript == docScript)
                    continue;

                yield return new A11yIssue
                {
                    IssueId = Guid.NewGuid(),
                    RuleId = RuleId,
                    Title = "Passage in a different script has no language set",
                    Description = $"A run of text is written predominantly in {runScript} script, different from the document's {docScript} script, but carries no explicit language. Text in a different language must be tagged so screen readers switch to the correct voice.",
                    Severity = IssueSeverity.MODERATE,
                    Category = IssueCategory.LANGUAGE,
                    WcagCriterion = WcagCriterion.SC_3_1_2,
                    RemediationType = RemediationType.HUMAN_REQUIRED,
                    RemediationGuidance = "Select this passage and set its language via Review → Language → Set Proofing Language so it is tagged distinctly from the document language.",
                    Location = LocationHelper.FromParagraph(paraIdx),
                    Evidence = new IssueEvidence
                    {
                        Snippet = Truncate(runText, 80),
                        ComputedValue = $"{runScript} script, no lang attribute",
                        ExpectedValue = $"Explicit language tag (document script is {docScript})"
                    }
                };

                // One issue per paragraph — all runs share the same Location key.
                break;
            }
        }
    }

    // Dominant Unicode script of a string, ignoring digits/punctuation/whitespace. Enough
    // to distinguish a genuine language switch (Latin vs CJK/Cyrillic/Arabic/…) from an
    // ordinary same-language run.
    private static Script DominantScript(string text)
    {
        var counts = new Dictionary<Script, int>();
        foreach (var c in text)
        {
            if (char.IsWhiteSpace(c) || char.IsDigit(c) || char.IsPunctuation(c)
                || char.IsSymbol(c) || char.IsControl(c))
                continue;
            var s = ClassifyChar(c);
            if (s == Script.Other) continue;
            counts[s] = counts.GetValueOrDefault(s) + 1;
        }

        if (counts.Count == 0) return Script.Other;

        Script best = Script.Other;
        int bestCount = 0;
        foreach (var kv in counts)
        {
            if (kv.Value > bestCount) { bestCount = kv.Value; best = kv.Key; }
        }
        return best;
    }

    private static Script ClassifyChar(char c)
    {
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
            || (c >= 'À' && c <= 'ɏ')) return Script.Latin;   // + Latin-1/Extended
        if (c >= 'Ͱ' && c <= 'Ͽ') return Script.Greek;
        if (c >= 'Ѐ' && c <= 'ӿ') return Script.Cyrillic;
        if (c >= '֐' && c <= '׿') return Script.Hebrew;
        if (c >= '؀' && c <= 'ۿ') return Script.Arabic;
        if ((c >= '一' && c <= '鿿')       // CJK unified ideographs
            || (c >= '぀' && c <= 'ヿ')    // hiragana + katakana
            || (c >= '가' && c <= '힣'))   // hangul syllables
            return Script.Cjk;
        return Script.Other;
    }

    private static int CountWords(string text)
        => text.Split((char[])null!, StringSplitOptions.RemoveEmptyEntries).Length;

    private static string Truncate(string text, int max)
        => text.Length <= max ? text : text[..max] + "…";
}
