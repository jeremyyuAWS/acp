import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import AutomaticReleasePackage from './AutomaticReleasePackage.jsx'
afterEach(unmountAll)
it('shows preparation, then downloads the exact prepared package without approving findings',async()=>{
 const {root,container}=createTestRoot();const download=vi.fn().mockResolvedValue()
 const render=async status=>act(async()=>root.render(createElement(AutomaticReleasePackage,{scanId:'scan',authorization:{package:{job_id:'frozen-package',status}},download})))
 await render('queued');expect(container.textContent).toContain('Preparing corrected copies');expect(container.querySelector('button')).toBeNull()
 await render('done');expect(container.textContent).toContain('No inspection required')
 await act(async()=>container.querySelector('button').click());expect(download).toHaveBeenCalledWith('scan','frozen-package')
 await render('dead');expect(container.textContent).toContain('Individual corrected copies and reports remain available')
})
