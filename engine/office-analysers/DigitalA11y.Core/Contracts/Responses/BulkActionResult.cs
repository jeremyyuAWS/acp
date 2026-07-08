namespace DigitalA11y.Core.Contracts.Responses;

public class BulkActionResult
{
    public int Succeeded { get; set; }
    public int Failed { get; set; }
    public List<BulkActionItemError> Errors { get; set; } = [];
}

public class BulkActionItemError
{
    public Guid JobId { get; set; }
    public string Reason { get; set; } = string.Empty;
}
