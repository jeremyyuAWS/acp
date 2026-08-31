import { it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import FolderPicker from './FolderPicker.jsx'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)
it('reuses recent navigation results and lets Refresh bypass them', async () => {
 const lister = vi.fn(async id => ({ folders: id === 'root' ? [{id:'a',name:'Folder A'}] : [] }))
 const {root,container} = createTestRoot()
 await act(async () => root.render(createElement(FolderPicker,{lister,layout:'inline'})))
 const click = async text => act(async () => [...container.querySelectorAll('button')].find(b=>b.textContent.trim().startsWith(text)).click())
 await click('Folder A')
 await click('My Drive')
 expect(lister.mock.calls.map(c=>c[0])).toEqual(['root','a'])
 await click('Refresh folders')
 expect(lister.mock.calls.map(c=>c[0])).toEqual(['root','a','root'])
})
