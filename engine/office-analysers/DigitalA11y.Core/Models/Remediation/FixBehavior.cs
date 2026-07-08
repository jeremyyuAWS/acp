namespace DigitalA11y.Core.Models.Remediation;

public record FixBehavior(bool AllowLlm, bool AllowPlaceholders)
{
    public static readonly FixBehavior Default = new(AllowLlm: true, AllowPlaceholders: true);
}
