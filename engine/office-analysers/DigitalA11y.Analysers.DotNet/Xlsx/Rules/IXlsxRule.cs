using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;

namespace DigitalA11y.Analysers.DotNet.Xlsx.Rules;

public interface IXlsxRule
{
    string RuleId { get; }
    IEnumerable<A11yIssue> Analyse(SpreadsheetDocument document);
}
