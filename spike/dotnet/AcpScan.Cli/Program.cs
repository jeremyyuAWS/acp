// Track-A Office scan CLI: dotnet run -- <inputDir> <outJsonPath>
// Dispatches each .docx/.pptx/.xlsx to devSEAL's unchanged analyser, writes JSON.
using DigitalA11y.Analysers.DotNet;
using DigitalA11y.Analysers.DotNet.Docx;
using DigitalA11y.Analysers.DotNet.Pptx;
using DigitalA11y.Analysers.DotNet.Xlsx;
using DigitalA11y.Core.Models.Manifest;
using Microsoft.Extensions.DependencyInjection;
using System.Text.Json;
using System.Text.Json.Serialization;

var inDir = args[0];
var outPath = args[1];

var sp = new ServiceCollection().AddDotNetAnalysers().BuildServiceProvider();
var docx = sp.GetRequiredService<DocxAnalyser>();
var pptx = sp.GetRequiredService<PptxAnalyser>();
var xlsx = sp.GetRequiredService<XlsxAnalyser>();

var results = new List<object>();
foreach (var path in Directory.GetFiles(inDir))
{
    var name = Path.GetFileName(path);
    var id = Guid.NewGuid().ToString();
    AnalyserResult? r = Path.GetExtension(path).ToLowerInvariant() switch
    {
        ".docx" => await docx.AnalyseAsync(path, id, name, name),
        ".pptx" => await pptx.AnalyseAsync(path, id, name, name),
        ".xlsx" => await xlsx.AnalyseAsync(path, id, name, name),
        _ => null,
    };
    if (r is null) continue;
    results.Add(new
    {
        file = name,
        succeeded = r.Succeeded,
        errors = r.Errors,
        issues = r.Issues.Select(i => new
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
        }),
    });
}

var json = JsonSerializer.Serialize(results, new JsonSerializerOptions
{
    WriteIndented = true,
    Converters = { new JsonStringEnumConverter() },
});
File.WriteAllText(outPath, json);
Console.WriteLine($"wrote {results.Count} office results -> {outPath}");
