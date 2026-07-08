namespace DigitalA11y.Core.Contracts;

public interface ISystemConfigService
{
    Task<string?> GetAsync(string key, CancellationToken ct);
    Task<T> GetAsync<T>(string key, T defaultValue, CancellationToken ct);
    Task SetAsync(string key, string value, string updatedBy, CancellationToken ct);
}
