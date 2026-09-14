import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { openAdminActivityStream } from './api.js'
import LiveOperationsNotifier from './LiveOperationsNotifier.jsx'
vi.mock('./api.js', () => ({ openAdminActivityStream: vi.fn() }))
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { LiveOperationsToast, newStageCompletions, newStageStarts, notificationRuns, playNotificationSound } from './LiveOperationsNotifier.jsx'

describe('Live Operations notifications', () => {
  it('announces only newly active Discover, Assess, and Remediate stages', () => {
    const previous = [{ scan_id: 'one', stage: 'discover', status: 'active', running: 1 }]
    const current = [
      ...previous,
      { scan_id: 'one', stage: 'assess', status: 'active', queued: 2 },
      { scan_id: 'two', stage: 'release', status: 'active', running: 1 },
      { scan_id: 'old', stage: 'remediate', status: 'recent', running: 0 },
    ]
    expect(newStageStarts(previous, current).map((run) => run.stage)).toEqual(['assess'])
  })

  it('announces a completion only when an active stage records successful completion', () => {
    const active = { scan_id: 'one', stage: 'assess', status: 'active', running: 1, queued: 2 }
    const completed = { ...active, status: 'recent', running: 0, queued: 0, completed: 24, total: 24, completion_recorded: true, terminal_outcome: 'completed' }
    expect(newStageCompletions([active], [completed])).toEqual([completed])
    expect(newStageCompletions([], [completed])).toEqual([])
    expect(newStageCompletions([completed], [completed])).toEqual([])
  })

  it('does not call a late trace-job tail assessment completion', () => {
    const before = {scan_id:'one',stage:'assess',status:'active',running:1,queued:0}
    const tail = {...before,status:'recent',running:0,completed:147,total:147}
    expect(newStageCompletions([before], [tail])).toEqual([])
  })

  it('opens Live Operations when the notification is clicked', () => {
    const onOpen = vi.fn()
    const run = { stage: 'remediate', owner: 'admin@example.com', total: 24 }
    const toast = LiveOperationsToast({ run, onOpen })
    const openButton = toast.props.children[1]
    openButton.props.onClick()
    expect(onOpen).toHaveBeenCalledOnce()
    const markup = renderToStaticMarkup(<LiveOperationsToast run={run} />)
    expect(markup).toContain('Remediation started')
    expect(markup).toContain('aria-atomic="true"')
    expect(markup).toContain('aria-label="Dismiss notification"')
    expect(markup).toContain('width:min(320px,calc(100vw - 28px))')
    expect(markup).toContain('padding:11px')
    expect(markup).toContain('border:1px solid var(--info-fg)')
    expect(markup).toContain('border-left:4px solid var(--info-fg)')
    expect(markup).toContain('background:var(--surface, #fff)')
    expect(markup).toContain('opacity:1')
    expect(markup).not.toContain('background:var(--panel)')
    expect(markup.match(/<button/g)).toHaveLength(2)
  })

  it('uses a distinct success treatment for stage completion', () => {
    const markup = renderToStaticMarkup(<LiveOperationsToast
      run={{ stage: 'discover', owner: 'admin@example.com', total: 9 }} kind="completed" />)
    expect(markup).toContain('Discovery complete')
    expect(markup).toContain('data-notification-kind="completed"')
    expect(markup).toContain('border:1px solid var(--success-fg)')
    expect(markup).toContain('border-left:4px solid var(--success-fg-strong)')
  })

  it('uses a distinct three-note completion chime', () => {
    vi.useFakeTimers()
    const frequencies = []
    const OriginalAudioContext = window.AudioContext
    window.AudioContext = class {
      currentTime = 0
      destination = {}
      createGain() { return { gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }, connect: vi.fn() } }
      createOscillator() {
        const frequency = { value: 0 }
        frequencies.push(frequency)
        return { frequency, connect: vi.fn(), start: vi.fn(), stop: vi.fn() }
      }
      close() {}
    }
    playNotificationSound('completed')
    expect(frequencies.map((frequency) => frequency.value)).toEqual([523, 659, 784])
    window.AudioContext = OriginalAudioContext
    vi.runAllTimers()
    vi.useRealTimers()
  })
})


describe('assessment notification result boundary', () => {
  const workflow = (assessmentState, traceStatus = 'active', remediationState = null) => ({
    runs: [{scan_id:'scan',stage:'assess',status:traceStatus,running:traceStatus==='active'?1:0,queued:0}],
    workflows: [{scan_id:'scan',owner_display_name:'Owner',stages:[{
      stage:'assess',stage_run_id:'assessment-execution',status:assessmentState==='succeeded'?'completed':'running',
      active:assessmentState==='processing'?18:0,waiting:assessmentState==='processing'?129:0,
      total:147,completed:assessmentState==='processing'?0:147,
      canonical:{state:assessmentState,execution_id:'assessment-execution'},
    }, ...(remediationState ? [{stage:'remediate',stage_run_id:'remediation-execution',status:'running',active:3,waiting:144,total:147,completed:0,canonical:{state:remediationState}}] : [])]}],
  })
  it('announces the recorded assessment completion while the trace job is still active', () => {
    const before = notificationRuns(workflow('processing_complete'))
    const finished = notificationRuns(workflow('succeeded'))
    expect(newStageCompletions(before, finished).map((run)=>run.stage)).toEqual(['assess'])
    const remediating = notificationRuns(workflow('succeeded','active','processing'))
    expect(newStageStarts(finished, remediating).map((run)=>run.stage)).toEqual(['remediate'])
    expect(newStageCompletions(finished, remediating)).toEqual([])
    const lateTraceDone = notificationRuns(workflow('succeeded','recent','processing'))
    expect(newStageCompletions(remediating, lateTraceDone)).toEqual([])
  })
  it('does not announce controller processing_complete before the stage succeeds', () => {
    expect(newStageCompletions(notificationRuns(workflow('processing')), notificationRuns(workflow('processing_complete')))).toEqual([])
  })
  it('does not announce a stale assessment completion after remediation was already observed', () => {
    expect(newStageCompletions(notificationRuns(workflow('processing_complete','active','processing')), notificationRuns(workflow('succeeded','recent','processing')))).toEqual([])
  })
  it('does not fabricate completion from queue disappearance without authoritative workflow completion', () => {
    const before=notificationRuns({runs:[{scan_id:'scan',stage:'assess',status:'active',running:1}]})
    const after=notificationRuns({runs:[{scan_id:'scan',stage:'assess',status:'recent',running:0}]})
    expect(newStageCompletions(before, after)).toEqual([])
  })
})


it('shows assessment completion before remediation and ignores later trace settlement in the mounted notifier', async () => {
  const host=document.createElement('div');document.body.appendChild(host)
  const root=createRoot(host);let push
  vi.mocked(openAdminActivityStream).mockImplementation(({onMessage})=>{push=onMessage;return {close:vi.fn()}})
  const snapshot = (state,remediation=false,trace='active') => ({
    runs:[{scan_id:'scan',stage:'assess',status:trace,running:trace==='active'?1:0}],
    workflows:[{scan_id:'scan',owner_display_name:'Owner',stages:[{
      stage:'assess',stage_run_id:'assess-1',status:state==='succeeded'?'completed':'running',
      active:state==='processing'?18:0,waiting:0,total:147,completed:state==='processing'?129:147,canonical:{state},
    },...(remediation?[{stage:'remediate',stage_run_id:'remediate-1',status:'running',active:2,waiting:145,total:147,canonical:{state:'processing'}}]:[])]}],
  })
  try {
    await act(async()=>root.render(<LiveOperationsNotifier />))
    await act(async()=>push(snapshot('processing')))
    expect(host.textContent).toBe('')
    await act(async()=>push(snapshot('succeeded')))
    expect(host.textContent).toContain('Assessment complete')
    await act(async()=>push(snapshot('succeeded',true)))
    expect(host.textContent).toContain('Remediation started')
    await act(async()=>push(snapshot('succeeded',true,'recent')))
    expect(host.textContent).toContain('Remediation started')
    expect(host.textContent).not.toContain('Assessment complete')
    await act(async()=>push({runs:[{scan_id:'scan',stage:'assess',status:'active',running:1}]}))
    await act(async()=>push(snapshot('succeeded')))
    expect(host.textContent).toContain('Remediation started')
    expect(host.textContent).not.toContain('Assessment complete')
  } finally {
    await act(async()=>root.unmount());host.remove()
  }
})


it('does not toast an already completed stage on initial connection', async () => {
  const host=document.createElement('div');document.body.appendChild(host);const root=createRoot(host);let push
  vi.mocked(openAdminActivityStream).mockImplementation(({onMessage})=>{push=onMessage;return{close:vi.fn()}})
  const completed={workflows:[{scan_id:'scan',stages:[{stage:'assess',stage_run_id:'assess-1',status:'completed',total:147,completed:147,canonical:{state:'succeeded'}}]}]}
  try {
    await act(async()=>root.render(<LiveOperationsNotifier />))
    await act(async()=>push(completed))
    expect(host.textContent).toBe('')
    await act(async()=>push({runs:[{scan_id:'scan',stage:'assess',status:'active',running:1}]}))
    await act(async()=>push(completed))
    expect(host.textContent).toBe('')
  }finally{await act(async()=>root.unmount());host.remove()}
})


it('does not pre-mark future waiting stages and announces their real start after assessment completion', async () => {
  const host=document.createElement('div');document.body.appendChild(host);const root=createRoot(host);let push
  vi.mocked(openAdminActivityStream).mockImplementation(({onMessage})=>{push=onMessage;return{close:vi.fn()}})
  const snapshot=(assessment, started=false)=>({workflows:[{scan_id:'future-scan',stages:[
    {stage:'assess',stage_run_id:'assess-future',status:assessment==='succeeded'?'completed':'running',active:0,waiting:0,canonical:{state:assessment}},
    {stage:'remediate',stage_run_id:'rem-future',status:'waiting',active:started?1:0,waiting:0,canonical:{state:started?'processing':'pending'}},
  ]}]})
  try {
    await act(async()=>root.render(<LiveOperationsNotifier />))
    await act(async()=>push(snapshot('processing_complete')))
    expect(host.textContent).toBe('')
    await act(async()=>push(snapshot('succeeded')))
    expect(host.textContent).toContain('Assessment complete')
    await act(async()=>push(snapshot('succeeded',true)))
    expect(host.textContent).toContain('Remediation started')
  } finally {await act(async()=>root.unmount());host.remove()}
})
