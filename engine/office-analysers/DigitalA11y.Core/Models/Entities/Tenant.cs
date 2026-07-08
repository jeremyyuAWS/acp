using DigitalA11y.Core.Helpers;

namespace DigitalA11y.Core.Models.Entities;

public class Tenant : BaseEntity
{
    /// <summary>URL-safe slug used as the subdomain prefix (e.g. "aangkora" → aangkora.lumynis.ai).</summary>
    public string Slug { get; set; } = string.Empty;

    public string DisplayName { get; set; } = string.Empty;

    /// <summary>PostgreSQL schema name derived from the slug: "tenant_{slug}".</summary>
    public string SchemaName => $"tenant_{Slug}";

    /// <summary>Public subdomain URL for this tenant.</summary>
    public string SubdomainUrl => TenantUrl.FromSlug(Slug);

    public string? AzureRegion { get; set; }

    public bool IsActive { get; set; } = true;

    public DateTimeOffset? DeactivatedAt { get; set; }
}
