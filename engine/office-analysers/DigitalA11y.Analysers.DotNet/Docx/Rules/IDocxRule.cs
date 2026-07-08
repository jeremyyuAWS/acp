using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;

namespace DigitalA11y.Analysers.DotNet.Docx.Rules;

public interface IDocxRule
{
    string RuleId { get; }
    IEnumerable<A11yIssue> Analyse(WordprocessingDocument document);
}
