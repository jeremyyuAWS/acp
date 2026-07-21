using DigitalA11y.Analysers.DotNet.Docx;
using DigitalA11y.Analysers.DotNet.Docx.Rules;
using DigitalA11y.Analysers.DotNet.Pptx;
using DigitalA11y.Analysers.DotNet.Pptx.Rules;
using DigitalA11y.Analysers.DotNet.Xlsx;
using DigitalA11y.Analysers.DotNet.Xlsx.Rules;
using Microsoft.Extensions.DependencyInjection;

namespace DigitalA11y.Analysers.DotNet;

public static class ServiceCollectionExtensions
{
    public static IServiceCollection AddDotNetAnalysers(
        this IServiceCollection services,
        Action<DocxAnalyserOptions>? configureDocx = null,
        Action<PptxAnalyserOptions>? configurePptx = null,
        Action<XlsxAnalyserOptions>? configureXlsx = null)
    {
        services.AddDocxAnalyser(configureDocx);
        services.AddPptxAnalyser(configurePptx);
        services.AddXlsxAnalyser(configureXlsx);
        return services;
    }

    public static IServiceCollection AddDocxAnalyser(
        this IServiceCollection services,
        Action<DocxAnalyserOptions>? configure = null)
    {
        var optionsBuilder = services.AddOptions<DocxAnalyserOptions>();
        if (configure is not null)
            optionsBuilder.Configure(configure);

        services.AddScoped<DocxAnalyser>();

        services.AddScoped<IDocxRule, Docx.Rules.DocumentLanguageRule>();
        services.AddScoped<IDocxRule, Docx.Rules.DocumentTitleRule>();
        services.AddScoped<IDocxRule, Docx.Rules.HeadingStructureRule>();
        services.AddScoped<IDocxRule, Docx.Rules.AltTextRule>();
        services.AddScoped<IDocxRule, Docx.Rules.TableHeaderRule>();
        services.AddScoped<IDocxRule, Docx.Rules.ColourContrastRule>();
        services.AddScoped<IDocxRule, Docx.Rules.LinkPurposeRule>();
        services.AddScoped<IDocxRule, Docx.Rules.LanguageOfPartsRule>();
        services.AddScoped<IDocxRule, Docx.Rules.BookmarksRule>();

        return services;
    }

    public static IServiceCollection AddPptxAnalyser(
        this IServiceCollection services,
        Action<PptxAnalyserOptions>? configure = null)
    {
        var optionsBuilder = services.AddOptions<PptxAnalyserOptions>();
        if (configure is not null)
            optionsBuilder.Configure(configure);

        services.AddScoped<PptxAnalyser>();

        services.AddScoped<IPptxRule, Pptx.Rules.SlideTitleRule>();
        services.AddScoped<IPptxRule, Pptx.Rules.AltTextRule>();
        services.AddScoped<IPptxRule, Pptx.Rules.ReadingOrderRule>();
        services.AddScoped<IPptxRule, Pptx.Rules.ColourContrastRule>();
        services.AddScoped<IPptxRule, Pptx.Rules.TableHeaderRule>();
        services.AddScoped<IPptxRule, Pptx.Rules.DocumentLanguageRule>();
        services.AddScoped<IPptxRule, Pptx.Rules.LinkPurposeRule>();
        services.AddScoped<IPptxRule, Pptx.Rules.AnimationOrderRule>();

        return services;
    }

    public static IServiceCollection AddXlsxAnalyser(
        this IServiceCollection services,
        Action<XlsxAnalyserOptions>? configure = null)
    {
        var optionsBuilder = services.AddOptions<XlsxAnalyserOptions>();
        if (configure is not null)
            optionsBuilder.Configure(configure);

        services.AddScoped<XlsxAnalyser>();

        services.AddScoped<IXlsxRule, Xlsx.Rules.DocumentTitleRule>();
        services.AddScoped<IXlsxRule, Xlsx.Rules.DocumentLanguageRule>();
        services.AddScoped<IXlsxRule, Xlsx.Rules.AltTextRule>();
        services.AddScoped<IXlsxRule, Xlsx.Rules.SheetNameRule>();
        services.AddScoped<IXlsxRule, Xlsx.Rules.TableHeaderRule>();
        services.AddScoped<IXlsxRule, Xlsx.Rules.HiddenContentRule>();
        services.AddScoped<IXlsxRule, Xlsx.Rules.MergedCellsRule>();
        services.AddScoped<IXlsxRule, Xlsx.Rules.BlankWorksheetRule>();
        services.AddScoped<IXlsxRule, Xlsx.Rules.LinkPurposeRule>();

        return services;
    }
}
