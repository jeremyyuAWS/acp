namespace DigitalA11y.Core.Models.Manifest;

public class IssueLocation
{
    /// <summary>Page number (1-based) for paginated formats such as PDF and PPTX.</summary>
    public int? PageNumber { get; set; }

    /// <summary>Slide number (1-based) for PPTX.</summary>
    public int? SlideNumber { get; set; }

    /// <summary>Paragraph or element index within the page/slide.</summary>
    public int? ElementIndex { get; set; }

    /// <summary>XPath or CSS selector identifying the element in HTML/XML-based formats.</summary>
    public string? XPath { get; set; }

    /// <summary>Free-text description of the location when a structured reference is unavailable.</summary>
    public string? Description { get; set; }
}
