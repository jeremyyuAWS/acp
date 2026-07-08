namespace DigitalA11y.Core.Contracts.Responses;

public record PagedResult<T>(
    List<T> Items,
    int Page,
    int PageSize,
    int TotalCount,
    int TotalPages);
