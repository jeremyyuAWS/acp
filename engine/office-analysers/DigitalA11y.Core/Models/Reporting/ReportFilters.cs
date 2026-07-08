using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Reporting;

/// <summary>
/// Scoping filters applied before any aggregation in ReportingService.
/// All properties are optional; null/empty means "no filter on this dimension".
/// Filtered-out issues must not appear in any totals or report sections.
/// </summary>
public class ReportFilters
{
    /// <summary>Restrict to issues on these files only.</summary>
    public List<Guid>? FileRecordIds { get; set; }

    /// <summary>Restrict to issues on files belonging to these departments only.</summary>
    public List<Guid>? DepartmentIds { get; set; }

    /// <summary>Restrict to issues with these severities only.</summary>
    public List<IssueSeverity>? Severities { get; set; }

    /// <summary>Restrict to issues against these WCAG criteria only.</summary>
    public List<WcagCriterion>? WcagCriteria { get; set; }

    /// <summary>Restrict to issues in these categories only.</summary>
    public List<IssueCategory>? Categories { get; set; }

    /// <summary>Restrict by resolution status. Null means include all.</summary>
    public bool? IsResolved { get; set; }
}
