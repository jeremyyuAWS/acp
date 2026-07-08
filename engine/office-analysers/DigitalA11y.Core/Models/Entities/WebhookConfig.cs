using DigitalA11y.Core.Enums;

namespace DigitalA11y.Core.Models.Entities;

public class WebhookConfig : BaseTenantEntity
{
    /// <summary>Null = applies to all departments (platform-wide).</summary>
    public Guid? DepartmentId { get; set; }
    public Department? Department { get; set; }

    public string TargetUrl { get; set; } = string.Empty;

    /// <summary>AES-encrypted HMAC secret used to sign outbound payloads.</summary>
    public string EncryptedSecret { get; set; } = string.Empty;

    public WebhookEvent Events { get; set; } = WebhookEvent.None;
    public bool IsActive { get; set; } = true;

    public DateTimeOffset? LastTriggeredAt { get; set; }
    public int? LastStatusCode { get; set; }
}
