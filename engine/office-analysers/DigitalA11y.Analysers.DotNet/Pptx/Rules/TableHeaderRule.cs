using DigitalA11y.Analysers.DotNet.Pptx.Helpers;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Enums;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Presentation;
using A = DocumentFormat.OpenXml.Drawing;

namespace DigitalA11y.Analysers.DotNet.Pptx.Rules;

public class TableHeaderRule : IPptxRule
{
    public string RuleId => PptxRuleIds.TableHeaders;

    public IEnumerable<A11yIssue> AnalyseSlide(
        SlidePart slidePart,
        int slideIndex,
        PresentationDocument document)
    {
        var spTree = slidePart.Slide.CommonSlideData?.ShapeTree;
        if (spTree is null) yield break;

        int tableIndex = 0;
        foreach (var gf in spTree.Descendants<GraphicFrame>())
        {
            var table = gf.Graphic?.GraphicData?.Descendants<A.Table>().FirstOrDefault();
            if (table is null) continue;

            var rows = table.Descendants<A.TableRow>().ToList();
            if (rows.Count <= 1)
            {
                tableIndex++;
                continue;
            }

            var tableProps = table.TableProperties;
            bool firstRowSet = tableProps?.FirstRow?.Value == true;

            if (!firstRowSet)
            {
                yield return new A11yIssue
                {
                    IssueId = Guid.NewGuid(),
                    RuleId = RuleId,
                    Title = "Table is missing a designated header row",
                    Description = $"A table on slide {slideIndex + 1} (table {tableIndex + 1}) has more than one row but the first row is not marked as a header row.",
                    Severity = IssueSeverity.SERIOUS,
                    Category = IssueCategory.TABLES,
                    WcagCriterion = WcagCriterion.SC_1_3_1,
                    RemediationType = RemediationType.AUTO_PLACEHOLDER,
                    RemediationGuidance = "Select the table, go to Table Design, and enable the 'Header Row' option to designate the first row as column headers.",
                    Location = LocationHelper.FromSlideTable(slideIndex, tableIndex),
                    Evidence = new IssueEvidence
                    {
                        ComputedValue = "FirstRow property not set",
                        ExpectedValue = "FirstRow = true"
                    }
                };
            }

            tableIndex++;
        }
    }
}
