// Track-A Office scan CLI: dotnet run -- <inputDir> <outJsonPath>
// Dispatches each .docx/.pptx/.xlsx to devSEAL's unchanged analyser, writes JSON.
//
// WHY THIS FILE HAS ERROR HANDLING AT ALL (2026-07-30)
//
// It used to have none, and that is the whole of the `office CLI exited -6` bug that was
// flagged twice without a diagnosis. On Unix the .NET runtime responds to an *unhandled
// managed exception* by printing the trace and calling abort(), so the process dies of
// SIGABRT and `subprocess` reports returncode -6. -6 is therefore not evidence of a native
// fault or a runtime-shutdown bug — an ordinary `ArgumentException` from one rule's code
// path produces exactly the same -6. (Verified: pointing this CLI at a missing directory
// raises DirectoryNotFoundException and yields returncode -6, on macOS, every time.)
//
// Unguarded, that had two costs beyond the crash itself:
//
//   1. `File.WriteAllText` sits AFTER the loop, so a throw on any file discarded the
//      results of every file already analysed in that batch — not just the failing one.
//   2. The only record of the cause was stderr, which api/scanner.py clipped to its last
//      400 characters — all stack frames, no exception type or message. Eight crashes over
//      12h across both analysers logged nothing more useful than `office CLI exited -6: ne)`.
//
// Both analysers already wrap their file-open and their whole rule sweep in try/catch, so
// an exception that still escapes `AnalyseAsync` comes from the unguarded preamble around
// them, and there is no reason for one file's misfortune to be fatal to the run. The
// per-file catch below turns it into what it should always have been: that file fails, with
// its exception type and message recorded as data, and the batch completes.
using DigitalA11y.Analysers.DotNet;
using DigitalA11y.Analysers.DotNet.Docx;
using DigitalA11y.Analysers.DotNet.Pptx;
using DigitalA11y.Analysers.DotNet.Xlsx;
using DigitalA11y.Core.Models.Manifest;
using Microsoft.Extensions.DependencyInjection;
using System.Text.Json;
using System.Text.Json.Serialization;

if (args.Length < 2)
{
    Console.Error.WriteLine("usage: AcpScan.Cli <inputDir> <outJsonPath>");
    return 2;
}

var inDir = args[0];
var outPath = args[1];

var results = new List<object>();
var failures = new List<string>();

try
{
    await Run();
}
catch (Exception ex)
{
    // The outer half of the same fix. Everything the loop cannot contain — the input directory
    // missing, DI construction failing, serialization throwing — used to reach the runtime
    // unhandled and become SIGABRT, which is the least diagnosable way for a CLI to fail: the
    // caller sees a signal rather than a status, and the cause is a 30-frame trace whose only
    // identifying line is the one a tail clip drops.
    //
    // A plain non-zero exit says the same thing without the ambiguity, and the message goes out
    // SHORT and FIRST, so it survives any clipping anywhere downstream. Nothing this CLI can
    // catch should ever again reach api/scanner.py as a signal death.
    Console.Error.WriteLine($"FATAL: {ex.GetType().FullName}: {ex.Message}");
    Console.Error.WriteLine(ex.ToString());
    TryWrite();
    return 2;
}

TryWrite();
if (failures.Count > 0)
    Console.WriteLine($"{failures.Count} file(s) failed to analyse: {string.Join(", ", failures)}");

// Exit 0 even when individual files failed. The failure is now IN the output, per file and
// with its cause, which is strictly better than a process-level exit code: a non-zero exit
// makes api/scanner.py mark every file in the batch `uncertain`, including the ones that
// analysed perfectly well.
return 0;

void TryWrite()
{
    // Write whatever was analysed, even on the fatal path — partial results beat none, and the
    // caller can already tell them apart because the exit status is non-zero.
    try
    {
        File.WriteAllText(outPath, JsonSerializer.Serialize(results, new JsonSerializerOptions
        {
            WriteIndented = true,
            Converters = { new JsonStringEnumConverter() },
        }));
        Console.WriteLine($"wrote {results.Count} office results -> {outPath}");
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"FATAL: could not write {outPath}: {ex.GetType().FullName}: {ex.Message}");
    }
}

async Task Run()
{
    var sp = new ServiceCollection().AddDotNetAnalysers().BuildServiceProvider();
    var docx = sp.GetRequiredService<DocxAnalyser>();
    var pptx = sp.GetRequiredService<PptxAnalyser>();
    var xlsx = sp.GetRequiredService<XlsxAnalyser>();

    foreach (var path in Directory.GetFiles(inDir))
    {
        var name = Path.GetFileName(path);
        var id = Guid.NewGuid().ToString();
        var ext = Path.GetExtension(path).ToLowerInvariant();
        if (ext is not (".docx" or ".pptx" or ".xlsx")) continue;

        try
        {
            AnalyserResult? r = ext switch
            {
                ".docx" => await docx.AnalyseAsync(path, id, name, name),
                ".pptx" => await pptx.AnalyseAsync(path, id, name, name),
                ".xlsx" => await xlsx.AnalyseAsync(path, id, name, name),
                _ => null,
            };
            if (r is null) continue;
            results.Add(Project(name, r.Succeeded, r.Errors.Cast<object>(), r.Issues.Select(ProjectIssue)));
        }
        catch (Exception ex)
        {
            // `succeeded = false`, deliberately. An analyser that threw did not complete its rule
            // sweep, so its findings are not a result — this file is unanalysable and the rubric
            // should score it that way. That is a different claim from the process-level abort
            // handling in api/scanner.py, which keeps findings and downgrades to `uncertain`:
            // there the CLI *did* finish its sweep and died afterwards, so what it reported stands.
            // Here it did not, and this is the narrower, per-file, more accurate signal.
            //
            // The message carries the exception TYPE as well as its text. Type is what identifies
            // the defect and it is what the old tail-clipped log line always cut off; putting it in
            // the payload means the next occurrence diagnoses itself, in `_o.json`, with no
            // dependence on whether anyone catches the container's stderr in time.
            failures.Add(name);
            Console.Error.WriteLine($"[cli] {name}: {ext[1..]} analyser threw {ex.GetType().FullName}: {ex.Message}");
            results.Add(Project(
                name,
                succeeded: false,
                errors: new object[]
                {
                    new
                    {
                        Code = "ANALYSER_UNHANDLED",
                        Message = $"{ext[1..]} analyser threw {ex.GetType().FullName}: {ex.Message}",
                        Detail = ex.ToString(),
                    },
                },
                issues: Enumerable.Empty<object>()));
        }
    }
}

static object ProjectIssue(A11yIssue i) => new
{
    ruleId = i.RuleId,
    wcag = i.WcagCriterion.ToString(),
    severity = i.Severity.ToString(),
    title = i.Title,
    // Where the finding is. The analysers already populate this (Pptx/LocationHelper
    // sets SlideNumber; Xlsx sets ElementIndex; Docx rules set a Description) — it was
    // simply dropped at this projection. Surfaced so the review UI can show the exact
    // slide/page instead of making a reviewer hunt. Projected explicitly (camelCase) to
    // match the rest of this payload; every field stays nullable — never invent a page.
    location = new
    {
        pageNumber = i.Location.PageNumber,
        slideNumber = i.Location.SlideNumber,
        elementIndex = i.Location.ElementIndex,
        xPath = i.Location.XPath,
        description = i.Location.Description,
    },
};

static object Project(string file, bool succeeded, IEnumerable<object> errors, IEnumerable<object> issues) => new
{
    file,
    succeeded,
    errors,
    issues,
};
