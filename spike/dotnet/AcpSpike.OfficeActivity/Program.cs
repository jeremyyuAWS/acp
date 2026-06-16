// acp derisk spike — wrap devSEAL's UNCHANGED DocxAnalyser as a Temporal .NET activity.
// Proves: Temporal .NET SDK worker + their OpenXML engine as an activity + the
// A11yIssue contract crossing the Temporal serialization boundary, end to end.
//
//   1. temporal server start-dev    (local Temporal on :7233)
//   2. dotnet run -- <path-to.docx>
//
// Their analysis functions are called AS-IS (no edits to their code).

using DigitalA11y.Analysers.DotNet;          // AddDocxAnalyser (their DI extension)
using DigitalA11y.Analysers.DotNet.Docx;     // DocxAnalyser
using DigitalA11y.Core.Models.Manifest;      // AnalyserResult, A11yIssue
using Microsoft.Extensions.DependencyInjection;
using System.Text.Json;
using System.Text.Json.Serialization;
using Temporalio.Activities;
using Temporalio.Client;
using Temporalio.Worker;
using Temporalio.Workflows;

const string TaskQueue = "office";

var filePath = args.Length > 0
    ? Path.GetFullPath(args[0])
    : throw new ArgumentException("usage: dotnet run -- <path-to.docx>");

// Build their analyser via their own DI registration — unchanged.
var services = new ServiceCollection();
services.AddDocxAnalyser();
var sp = services.BuildServiceProvider();

var client = await TemporalClient.ConnectAsync(new("localhost:7233"));
Console.WriteLine($"connected to Temporal; analysing {Path.GetFileName(filePath)} via task queue '{TaskQueue}'");

using var worker = new TemporalWorker(
    client,
    new TemporalWorkerOptions(TaskQueue)
        .AddAllActivities(new OfficeActivities(sp))
        .AddWorkflow<ScanFileWorkflow>());

using var cts = new CancellationTokenSource();
var workerTask = worker.ExecuteAsync(cts.Token);

var input = new AnalyseInput(filePath, Guid.NewGuid().ToString(), "spike-file", Path.GetFileName(filePath), null);
var result = await client.ExecuteWorkflowAsync(
    (ScanFileWorkflow wf) => wf.RunAsync(input),
    new(id: $"scan-{Guid.NewGuid():N}", taskQueue: TaskQueue));

cts.Cancel();
try { await workerTask; } catch (OperationCanceledException) { }

var json = JsonSerializer.Serialize(result, new JsonSerializerOptions
{
    WriteIndented = true,
    Converters = { new JsonStringEnumConverter() },
});
Console.WriteLine(json);
Console.WriteLine($"\n✔ succeeded={result.Succeeded}  issues={result.Issues.Count}  errors={result.Errors.Count}");
foreach (var i in result.Issues)
    Console.WriteLine($"  - [{i.Severity}] {i.RuleId} ({i.WcagCriterion}) — {i.Title}");

// ---- the wrapper: their unchanged AnalyseAsync, behind a Temporal activity ----
public class OfficeActivities(IServiceProvider sp)
{
    [Activity]
    public async Task<AnalyserResult> AnalyseDocx(AnalyseInput input)
    {
        using var scope = sp.CreateScope();
        var analyser = scope.ServiceProvider.GetRequiredService<DocxAnalyser>();
        return await analyser.AnalyseAsync(
            input.FilePath, input.JobId, input.FileId, input.FileName, input.DisabledRuleIds);
    }
}

[Workflow]
public class ScanFileWorkflow
{
    [WorkflowRun]
    public async Task<AnalyserResult> RunAsync(AnalyseInput input) =>
        await Workflow.ExecuteActivityAsync(
            (OfficeActivities a) => a.AnalyseDocx(input),
            new ActivityOptions { StartToCloseTimeout = TimeSpan.FromMinutes(2) });
}

public record AnalyseInput(string FilePath, string JobId, string FileId, string FileName, string[]? DisabledRuleIds);
