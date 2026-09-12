# Visual remediation progress

Large KPI tiles replace the remediation and publication progress bars and compact
counter rows. File coverage, document status, findings, and publication use separate
scopes and denominators.

Each tile shows its current count, a saved starting count where durable admission
evidence exists, and the net change. Confirmed updates animate signed +N / −N deltas
once. Reduced motion disables counting animations. Missing historical evidence is
shown as “Before unavailable”; refreshing must never create a new baseline.

File coverage counts unique assessed files with findings. A file is processed when
its recorded remediation attempt finishes, even if findings remain or fixes fail.
Queued or active retries remain outstanding. Approval, verification, and publication
do not substitute for processing evidence. Processed plus outstanding must reconcile
with the files-with-findings scope.

Finding tiles group queued work, applying/checking, needs attention, verified fixes,
and excluded findings. Detailed outcomes remain available under Outcome details.
Publication tiles group queued, publishing, published, needs attention, and skipped
files, and identify the release scope. Publication does not certify accessibility.

Counts retain their last confirmed values through connection gaps. A failed check can
increase needs attention; the UI displays that movement honestly. Completed automated
work can coexist with unresolved findings.
