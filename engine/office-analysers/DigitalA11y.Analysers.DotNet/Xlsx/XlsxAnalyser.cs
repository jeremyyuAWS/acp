using DigitalA11y.Analysers.DotNet.Xlsx.Rules;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using Microsoft.Extensions.Options;
using System.Diagnostics;

namespace DigitalA11y.Analysers.DotNet.Xlsx;

public class XlsxAnalyser
{
    private readonly IEnumerable<IXlsxRule> _rules;
    private readonly XlsxAnalyserOptions _options;

    public XlsxAnalyser(IEnumerable<IXlsxRule> rules, IOptions<XlsxAnalyserOptions> options)
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
        if (disabledRuleIds is not null) effectivelyDisabled.UnionWith(disabledRuleIds);

        try
        {
            using var document = SpreadsheetDocument.Open(filePath, isEditable: false);

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
            result.Errors.Add(AnalyserError.FileOpenFailed("Xlsx", ex));
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
