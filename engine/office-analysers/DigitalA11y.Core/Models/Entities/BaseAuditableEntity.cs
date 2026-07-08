namespace DigitalA11y.Core.Models.Entities;

/// <summary>
/// Base record that provides standard auditing and soft delete capabilities.
/// All entities that need Created/Updated audit fields and soft delete should inherit from this.
/// </summary>
public abstract class BaseEntity
{
    public Guid Id { get; set; } = Guid.NewGuid();
    
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
}

public abstract class BaseTenantEntity : BaseEntity
{
    public Guid? TenantId { get; set; }
}

public abstract class BaseLoggingEntity : BaseTenantEntity
{
    public DateTimeOffset OccurredAt { get; set; } = DateTimeOffset.UtcNow;
}

public abstract class BaseRecordEntity : BaseTenantEntity
{
    public DateTimeOffset? ClaimedAt { get; set; }
    public DateTimeOffset? StartedAt { get; set; }
    public DateTimeOffset? CompletedAt { get; set; }
}

public abstract class BaseAuditableEntity : BaseTenantEntity
{
    // Audit Fields
    public DateTimeOffset UpdatedAt { get; set; } = DateTimeOffset.UtcNow;
    public string CreatedBy { get; set; } = "";   // ExternalUserId
    public string UpdatedBy { get; set; } = "";   // ExternalUserId

    // Soft Delete
    public bool IsDeleted { get; set; } = false;
    public DateTimeOffset? DeletedAt { get; set; }
    public string? DeletedBy { get; set; } = "";   // ExternalUserId

    public void SoftDelete(string deletedBy)
    {
        IsDeleted = true;
        DeletedAt = DateTimeOffset.UtcNow;
        DeletedBy = deletedBy;
        UpdatedAt = DateTimeOffset.UtcNow;
        UpdatedBy = deletedBy;
    }
}