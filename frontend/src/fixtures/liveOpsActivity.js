export const LIVE_OPS_ACTIVITY_FIXTURE = {
  snapshot: {
    workflows: [{
      workflow_id: 'workflow-42',
      scan_id: 'scan-42',
      events: [{
        event_id: 'stage-1',
        occurred_at: '2026-09-07T17:01:30.000Z',
        kind: 'job.stage_completed',
        stage: 'assess',
        correlation_id: 'batch-42',
        detail: { documents: 4 },
      }],
    }],
  },
  capacity: {
    worker_app_name: 'acp-assess',
    deployments: {
      queried: true,
      window_hours: 24,
      events: [
        { id: 'op-3', at: '2026-09-07T17:03:00.000Z', kind: 'operation',
          label: 'Container app updated', status: 'Succeeded', failed: false },
        { id: 'op-2', at: '2026-09-07T17:02:30.000Z', kind: 'operation',
          label: 'Container app updated', status: 'Succeeded', failed: false },
        { id: 'op-1', at: '2026-09-07T17:02:00.000Z', kind: 'operation',
          label: 'Container app updated', status: 'Succeeded', failed: false },
        { id: 'revision-1', at: '2026-09-07T17:00:00.000Z', kind: 'revision',
          label: 'Revision acp-assess--v42 created', status: 'Provisioned', failed: false },
      ],
    },
  },
  liveEvents: [{
    id: 'live-capacity-1',
    at: '2026-09-07T17:01:00.000Z',
    kind: 'capacity',
    text: 'assess worker slots changed from 2 to 4',
    outcome: 'Scaled up',
    correlation: 'assess',
  }, {
    id: 'live-warning-1',
    at: '2026-09-07T16:59:00.000Z',
    kind: 'warning',
    text: 'assess worker service stopped reporting a heartbeat',
    outcome: 'Offline',
    correlation: 'assess',
  }],
}
