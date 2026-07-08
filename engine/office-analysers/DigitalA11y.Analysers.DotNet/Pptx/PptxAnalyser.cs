using DigitalA11y.Analysers.DotNet.Pptx.Rules;
using DigitalA11y.Core.Analysis;
using DigitalA11y.Core.Models.Manifest;
using DocumentFormat.OpenXml.Packaging;
using Microsoft.Extensions.Options;
using System.Diagnostics;

namespace DigitalA11y.Analysers.DotNet.Pptx;

public class PptxAnalyser
{
    private readonly IEnumerable<IPptxRule> _rules;
    private readonly PptxAnalyserOptions _options;

    public PptxAnalyser(IEnumerable<IPptxRule> rules, IOptions<PptxAnalyserOptions> options)
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
            result.Errors.Add(AnalyserError.FileTooLargeError(
                filePath, fileInfo.Length, _options.MaxFileSizeBytes));
            result.Succeeded = false;
            result.CompletedAt = DateTimeOffset.UtcNow;
            return result;
        }

        var effectivelyDisabled = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (_options.SkipColourContrast) effectivelyDisabled.Add(PptxRuleIds.ColourContrast);
        if (_options.SkipAnimationCheck) effectivelyDisabled.Add(PptxRuleIds.AnimationOrder);
        if (disabledRuleIds is not null) effectivelyDisabled.UnionWith(disabledRuleIds);

        try
        {
            using var document = PresentationDocument.Open(filePath, isEditable: false);

            var slideParts = document.PresentationPart?.SlideParts.ToList() ?? [];

            for (int slideIndex = 0; slideIndex < slideParts.Count; slideIndex++)
            {
                var slidePart = slideParts[slideIndex];

                using var cts = new CancellationTokenSource();
                cts.CancelAfter(TimeSpan.FromSeconds(_options.SlideTimeoutSeconds));

                try
                {
                    await Task.Run(() =>
                    {
                        foreach (var rule in _rules)
                        {
                            cts.Token.ThrowIfCancellationRequested();

                            if (effectivelyDisabled.Contains(rule.RuleId))
                                continue;

                            try
                            {
                                var issues = rule.AnalyseSlide(slidePart, slideIndex, document).ToList();
                                result.Issues.AddRange(issues);
                            }
                            catch (OperationCanceledException)
                            {
                                throw;
                            }
                            catch (Exception ex)
                            {
                                result.Errors.Add(AnalyserError.RuleExecutionError(rule.RuleId, ex));
                            }
                        }
                    }, cts.Token);
                }
                catch (OperationCanceledException)
                {
                    result.Errors.Add(new AnalyserError
                    {
                        Code = "SLIDE_TIMEOUT",
                        Message = $"Slide {slideIndex + 1} exceeded the {_options.SlideTimeoutSeconds}s timeout and was skipped.",
                        Detail = $"slide_index={slideIndex}"
                    });
                }
            }

            result.Succeeded = true;
        }
        catch (Exception ex)
        {
            result.Errors.Add(AnalyserError.FileOpenFailed("Pptx", ex));
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
