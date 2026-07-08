namespace DigitalA11y.Core.Enums;

[Flags]
public enum WebhookEvent
{
    None            = 0,
    JobCompleted    = 1 << 0,
    JobFailed       = 1 << 1,
    BatchCompleted  = 1 << 2,
    BatchFailed     = 1 << 3,
}
