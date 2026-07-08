using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace DigitalA11y.Analysers.DotNet.Docx.Rules;

public class BookmarksRule : IDocxRule
{
    public string RuleId => DocxRuleIds.Bookmarks;

    private const int PageThreshold = 10;

    public IEnumerable<A11yIssue> Analyse(WordprocessingDocument document)
    {
        var body = document.MainDocumentPart?.Document?.Body;
        if (body is null) yield break;

        int pageCount = Math.Max(1, body.Descendants<SectionProperties>().Count());
        int bookmarkCount = body.Descendants<BookmarkStart>()
                               .Count(b => !IsWordInternalBookmark(b.Name?.Value));

        if (pageCount > PageThreshold && bookmarkCount == 0)
        {
            yield return new A11yIssue
            {
                IssueId = Guid.NewGuid(),
                RuleId = RuleId,
                Title = "Long document has no navigation bookmarks",
                Description = $"The document is approximately {pageCount} pages long but contains no bookmarks. Bookmarks provide navigation landmarks that help keyboard and assistive technology users move through long documents efficiently.",
                Severity = IssueSeverity.MINOR,
                Category = IssueCategory.KEYBOARD_NAVIGATION,
                WcagCriterion = WcagCriterion.SC_2_4_2,
                RemediationType = RemediationType.HUMAN_REQUIRED,
                RemediationGuidance = "Add bookmarks at key sections via Insert → Bookmark. Consider also adding a table of contents using the built-in heading styles.",
                Location = new IssueLocation { Description = "docx:document-structure" },
                Evidence = new IssueEvidence
                {
                    ComputedValue = $"~{pageCount} pages, {bookmarkCount} bookmarks",
                    ExpectedValue = $"At least 1 bookmark for documents longer than {PageThreshold} pages"
                }
            };
        }
    }

    private static bool IsWordInternalBookmark(string? name)
        => name is null || name.StartsWith('_');
}
