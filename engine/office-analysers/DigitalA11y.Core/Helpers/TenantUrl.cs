namespace DigitalA11y.Core.Helpers;

public static class TenantUrl
{
    private const string BaseDomain = "lumynis.ai";

    public static string FromSlug(string slug) => $"https://{slug}.{BaseDomain}";

    public static string DefaultUrl => FromSlug("app");
}
