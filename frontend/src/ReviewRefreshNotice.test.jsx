import { act } from 'react'
import { expect, it, vi } from 'vitest'
import { createTestRoot } from './testRoots.js'
import ReviewRefreshNotice from './ReviewRefreshNotice.jsx'

it('explains a read failure without falsely claiming fixes failed and retries only the read',async()=>{
 const retry=vi.fn();const {root,container}=createTestRoot()
 await act(async()=>root.render(<ReviewRefreshNotice error={new Error('private backend details')} onRetry={retry}/>))
 expect(container.textContent).toContain('does not mean saved fixes failed')
 expect(container.textContent).not.toContain('private backend details')
 await act(async()=>container.querySelector('button').click())
 expect(retry).toHaveBeenCalledTimes(1)
 await act(async()=>root.render(<ReviewRefreshNotice error={null} onRetry={retry}/>))
 expect(container.querySelector('[role=alert]')).toBeNull()
 await act(async()=>root.unmount())
})
it('does not offer a blind retry for an inaccessible run',async()=>{
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<ReviewRefreshNotice error={{status:403}} onRetry={()=>{}}/>))
 expect(container.textContent).toContain('Sign in again')
 expect(container.querySelector('button')).toBeNull()
 await act(async()=>root.unmount())
})
