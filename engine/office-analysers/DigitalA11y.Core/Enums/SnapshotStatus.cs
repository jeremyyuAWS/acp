namespace DigitalA11y.Core.Enums;

public enum SnapshotStatus
{
    Pending,     // batch run completed; snapshot creation job is queued
    Computing,   // diff arrays being computed against previous snapshot
    Ready,       // snapshot is available for diff reports
    Failed       // snapshot creation failed; check activity log for reason
}