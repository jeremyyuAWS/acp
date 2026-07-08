using DigitalA11y.Analysers.DotNet.Docx.Rules;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using Microsoft.Extensions.Options;
using System.Diagnostics;

namespace DigitalA11y.Analysers.DotNet.Docx;

public class DocxAnalyser
{
    private readonly IEnumerable<IDocxRule> _rules;
    private readonly DocxAnalyserOptions _options;

    public DocxAnalyser(IEnumerable<IDocxRule> rules, IOptions<DocxAnalyserOptions> options)
    {
        _rules = rules;
        _options = options.Value;
    }

    public async Task<AnalyserResult> AnalyseAsync(
        string filePath,
        string jobId,
        string fileId,
        string fileName,
        IEnumerable<string>? disabledRuleIds = null)
    {
        var startedAt = DateTimeOffset.UtcNow;
        var stopwatch = Stopwatch.StartNew();

        var result = new AnalyserResult
        {
            AnalyserName = _options.AnalyserName,
            AnalyserVersion = _options.AnalyserVersion,
            StartedAt = startedAt
        };

        var fileInfo = new FileInfo(filePath);
        if (!fileInfo.Exists)
        {
            result.Errors.Add(AnalyserError.FileNotFoundError(filePath));
            result.Succeeded = false;
            result.CompletedAt = DateTimeOffset.UtcNow;
            return result;
        }

        if (fileInfo.Length > _options.MaxFileSizeBytes)
        {
            result.Errors.Add(AnalyserError.FileTooLargeError(filePath, fileInfo.Length, _options.MaxFileSizeBytes));
            result.Succeeded = false;
            result.CompletedAt = DateTimeOffset.UtcNow;
            return result;
        }

        var effectivelyDisabled = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (_options.SkipColourContrast) effectivelyDisabled.Add(DocxRuleIds.ColourContrast);
        if (disabledRuleIds is not null) effectivelyDisabled.UnionWith(disabledRuleIds);

        try
        {
            using var document = WordprocessingDocument.Open(filePath, isEditable: false);

            foreach (var rule in _rules)
            {
                if (effectivelyDisabled.Contains(rule.RuleId))
                    continue;

                try
                {
                    var issues = rule.Analyse(document).ToList();
                    result.Issues.AddRange(issues);
                }
                catch (Exception ex)
                {
                    result.Errors.Add(AnalyserError.RuleExecutionError(rule.RuleId, ex));
                }
            }

            result.Succeeded = true;
        }
        catch (Exception ex)
        {
            result.Errors.Add(AnalyserError.FileOpenFailed("Docx", ex));
            result.Succeeded = false;
        }
        finally
        {
            stopwatch.Stop();
            result.CompletedAt = DateTimeOffset.UtcNow;
        }

        return await Task.FromResult(result);
    }
}
