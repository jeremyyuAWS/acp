// The previous row is retained for reversibility; the live UI has one Workspace role field.
import { act, createElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const api=vi.hoisted(()=>({getPeople:vi.fn(),getWorkspaceRoles:vi.fn(),assignWorkspaceRole:vi.fn(),roleImpact:vi.fn(),updatePerson:vi.fn(),addPerson:vi.fn(),removePerson:vi.fn()}))
vi.mock('./api.js',()=>api)
import PeopleAccess from './PeopleAccess.jsx'
let roster,canManage
const roles=[{id:'platform-admin',name:'Platform Admin',is_system:true},{id:'analyst',name:'Analyst'},{id:'custom-name',name:'Platform Admin',is_system:false}]
beforeEach(()=>{
 roster=[{email:'person@example.com',role:'user',status:'access_ready',workspace_role_id:null}];canManage=true
 api.getPeople.mockImplementation(async()=>({people:roster,can_manage:canManage,domains:[]}))
 api.getWorkspaceRoles.mockResolvedValue({roles,enforced:true})
 api.roleImpact.mockResolvedValue({gains:[],loses:[],enforced:true})
 api.assignWorkspaceRole.mockImplementation(async(email,id,platform)=>{
  roster=roster.map(p=>p.email===email?{...p,workspace_role_id:id||null,...(platform===undefined?{}:{role:platform})}:p)
  return{person:roster.find(p=>p.email===email)}
 })
})
afterEach(async()=>{await unmountAll();vi.resetAllMocks()})
const flush=async()=>act(async()=>{for(let i=0;i<5;i++)await Promise.resolve()})
async function mount(){const{container,root}=createTestRoot();await act(async()=>root.render(createElement(PeopleAccess)));await flush();return container}
const selector=c=>c.querySelector('select[aria-label="Workspace role for person@example.com"]')
async function choose(c,value){await act(async()=>{selector(c).value=value;selector(c).dispatchEvent(new Event('change',{bubbles:true}))});await flush()}
it('mounts one selector and one visible Workspace role column without an Access level field',async()=>{
 const c=await mount();expect(c.querySelectorAll('.people-row select')).toHaveLength(1)
 expect(c.querySelector('.people-head').textContent).toContain('Workspace role')
 expect(c.querySelector('.people-head').textContent).not.toContain('Access level')
 expect([...selector(c).options].map(o=>o.textContent)).toEqual(['No role','Platform Admin','Analyst','Platform Admin (custom role)'])
})
it('optimistically shows explicit platform promotion while its atomic save is in flight',async()=>{
 const c=await mount();let done;api.assignWorkspaceRole.mockImplementationOnce(()=>new Promise(r=>{done=r}))
 await choose(c,'platform-admin');expect(selector(c).value).toBe('platform-admin')
 expect(api.assignWorkspaceRole).toHaveBeenCalledExactlyOnceWith('person@example.com','platform-admin','admin')
 await act(async()=>done({person:{}}))
})
it('reloads server truth after an atomic save fails',async()=>{
 const c=await mount();api.assignWorkspaceRole.mockRejectedValueOnce(new Error('Denied'))
 await choose(c,'platform-admin');expect(selector(c).value).toBe('');expect(c.textContent).toContain('Denied')
})
it('assigns a custom role named Platform Admin without promoting platform access',async()=>{
 const c=await mount();await choose(c,'custom-name')
 expect(api.assignWorkspaceRole).toHaveBeenCalledExactlyOnceWith('person@example.com','custom-name')
 expect(roster[0].role).toBe('user');expect(selector(c).selectedOptions[0].textContent).toContain('(custom role)')
})
it('explicitly demotes platform administration when the owner chooses No role',async()=>{
 roster[0]={...roster[0],role:'admin',workspace_role_id:'platform-admin'}
 const c=await mount();await choose(c,'')
 expect(api.assignWorkspaceRole).toHaveBeenCalledExactlyOnceWith('person@example.com','','user')
 expect(roster[0].role).toBe('user');expect(selector(c).value).toBe('')
})
it('keeps legacy mixed grants visible and restores both fields through Undo',async()=>{
 roster[0]={...roster[0],role:'admin',workspace_role_id:'custom-name'}
 const c=await mount();expect(selector(c).selectedOptions[0].textContent).toContain('Platform Admin + Platform Admin')
 await choose(c,'analyst');expect(api.assignWorkspaceRole).toHaveBeenLastCalledWith('person@example.com','analyst','user')
 await act(async()=>[...document.querySelectorAll('.people-toast button')].find(b=>b.textContent==='Undo').click());await flush()
 expect(api.assignWorkspaceRole).toHaveBeenLastCalledWith('person@example.com','custom-name','admin')
 expect(roster[0].role).toBe('admin');expect(roster[0].workspace_role_id).toBe('custom-name')
})
it('lets a non-owner manager change workspace roles while retaining the platform grant',async()=>{
 canManage=false;roster[0]={...roster[0],role:'admin',workspace_role_id:'custom-name'}
 const c=await mount();expect(selector(c).querySelector('option[value="platform-admin"]').disabled).toBe(true)
 await choose(c,'analyst');expect(api.assignWorkspaceRole).toHaveBeenCalledExactlyOnceWith('person@example.com','analyst')
 expect(roster[0].role).toBe('admin')
})
it('offers no selector or access removal for the protected owner',async()=>{
 roster[0]={...roster[0],protected:true,role:'owner'};const c=await mount()
 expect(c.querySelectorAll('.people-row select')).toHaveLength(0)
 expect(c.textContent).toContain('Owner — full access');expect(c.querySelector('.people-row-actions button')).toBeNull()
})
it('does not promote a custom role that reuses the platform-admin slug',async()=>{
 api.getWorkspaceRoles.mockResolvedValue({roles:[{id:'platform-admin',name:'Platform Admin',is_system:false}],enforced:true})
 const c=await mount();expect([...selector(c).options].map(o=>o.textContent)).toEqual(['No role','Platform Admin (custom role)'])
 await choose(c,'platform-admin');expect(api.assignWorkspaceRole).toHaveBeenCalledExactlyOnceWith('person@example.com','platform-admin')
 expect(roster[0].role).toBe('user')
})
it('keeps deployment-owned admin authority while changing the workspace role',async()=>{
 roster[0]={...roster[0],platform_role_admin:true,platform_role_locked:true}
 const c=await mount();expect(selector(c).selectedOptions[0].textContent).toContain('Platform Admin + No role')
 await choose(c,'analyst');expect(api.assignWorkspaceRole).toHaveBeenCalledExactlyOnceWith('person@example.com','analyst')
 expect(c.textContent).toContain('configured by the deployment and remains enabled')
})
