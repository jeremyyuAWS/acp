using DigitalA11y.Core.Models.Manifest;

namespace DigitalA11y.Analysers.DotNet.Pptx.Helpers;

public static class LocationHelper
{
    public static IssueLocation FromSlide(int slideIndex) => new()
    {
        SlideNumber = slideIndex + 1,
        Description = $"pptx:slide:{slideIndex}"
    };

    public static IssueLocation FromSlideElement(int slideIndex, string elementId) => new()
    {
        SlideNumber = slideIndex + 1,
        Description = $"pptx:slide:{slideIndex}:element:{elementId}"
    };

    public static IssueLocation FromSlideTable(int slideIndex, int tableIndex) => new()
    {
        SlideNumber = slideIndex + 1,
        ElementIndex = tableIndex,
        Description = $"pptx:slide:{slideIndex}:table:{tableIndex}"
    };
}
