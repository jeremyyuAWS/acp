import { expect, it, vi } from 'vitest'
import { authorizeAcceptedRelease, releasePlanKey } from './releasePlanIntent.js'
const intent = { key: releasePlanKey('scan', ['a']), files: ['a'], destination: { provider: 'drive', folder_id: 'root' }, source_revision: 'source' }
const accepted = { scan_id: 'scan', enqueued: 1, batch_id: 'accepted-run', snapshot_id: 'source' }
const client = () => ({ enable: vi.fn().mockResolvedValue({}), get: vi.fn() })
it('does nothing without an explicit Plan choice', async () => {
  const c = client(); expect(await authorizeAcceptedRelease('scan', ['a'], accepted, null, c)).toBe('')
  expect(c.enable).not.toHaveBeenCalled(); expect(c.get).not.toHaveBeenCalled()
})
it('authorizes the returned accepted run with frozen scope, source and destination', async () => {
  const c = client(); await authorizeAcceptedRelease('scan', ['a'], accepted, intent, c)
  expect(c.enable).toHaveBeenCalledWith('scan', expect.objectContaining({run_id:'accepted-run', files:['a'], destination:intent.destination, expected_source_revision:'source',request_id:expect.any(String)}))
  expect(c.get).not.toHaveBeenCalled()
})
it.each([{batch_id:null},{enqueued:0},{scan_id:'other'},{snapshot_id:'new-source'}])('never falls back to the current run for an invalid acceptance %j', async change => {
  const c = client(); const notice = await authorizeAcceptedRelease('scan', ['a'], {...accepted,...change}, intent, c)
  expect(notice).toContain('was not enabled'); expect(c.enable).not.toHaveBeenCalled(); expect(c.get).not.toHaveBeenCalled()
})
it('rejects changed scope before sending any release request', async () => {
  const c = client(); await authorizeAcceptedRelease('scan', ['b'], accepted, intent, c)
  expect(c.enable).not.toHaveBeenCalled()
})
it('reconciles a lost response by exact request without repeating either action', async () => {
  const c = client(); c.enable.mockRejectedValue(new Error('lost'))
  c.get.mockImplementation(async () => ({authorization:{request_id:c.enable.mock.calls[0][1].request_id,run_id:'accepted-run',source_revision:'source',status:'active'}}))
  expect(await authorizeAcceptedRelease('scan', ['a'], accepted, intent, c)).toContain('confirmed after refreshing')
  expect(c.enable).toHaveBeenCalledOnce(); expect(c.get).toHaveBeenCalledOnce()
})
it('keeps successful remediation distinct from an unconfirmed release', async () => {
  const c = client(); c.enable.mockRejectedValue(new Error('lost')); c.get.mockResolvedValue({authorization:{request_id:'other',run_id:'accepted-run',source_revision:'source',status:'active'}})
  expect(await authorizeAcceptedRelease('scan', ['a'], accepted, intent, c)).toContain('remediation does not need to be started again')
  expect(c.enable).toHaveBeenCalledOnce()
})

it('rejects an intent whose stored files disagree with its displayed scope key', async () => {
  const c = client(); await authorizeAcceptedRelease('scan', ['a'], accepted, {...intent,files:['b']}, c)
  expect(c.enable).not.toHaveBeenCalled(); expect(c.get).not.toHaveBeenCalled()
})

it('passes remaining issue and report flags only for a matching accepted run',async()=>{
 const c=client();const auto={...intent,allow_remaining_issues:true,include_reports:true}
 await authorizeAcceptedRelease('scan',['a'],accepted,auto,c)
 expect(c.enable).toHaveBeenCalledWith('scan',expect.objectContaining({allow_remaining_issues:true,include_reports:true}))
 c.enable.mockClear();await authorizeAcceptedRelease('scan',['a'],{...accepted,enqueued:0},auto,c);expect(c.enable).not.toHaveBeenCalled()
})
it('does not claim recovered consent if saved report or remaining-issue flags differ',async()=>{
 const c=client();c.enable.mockRejectedValue(new Error('lost'))
 c.get.mockImplementation(async()=>({authorization:{request_id:c.enable.mock.calls[0][1].request_id,run_id:'accepted-run',source_revision:'source',status:'active',allow_remaining_issues:false,include_reports:false}}))
 const notice=await authorizeAcceptedRelease('scan',['a'],accepted,{...intent,allow_remaining_issues:true,include_reports:true},c)
 expect(notice).toContain('could not be confirmed')
})
