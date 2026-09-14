import { beforeEach, afterEach, expect, it } from 'vitest'
import { act, createElement, StrictMode } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationWorkspaceTabs from './RemediationWorkspaceTabs.jsx'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
beforeEach(() => {
  history.replaceState({}, '', '/?tab=remediate')
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false }
})
afterEach(unmountAll)
it('introduces each assessment once across remounts and permits explicit reopening', async () => {
  const props = { runId:'once-assessment-fixture', assessmentReady:true, plan:'choices', live:'live', review:'review' }
  const first = createTestRoot()
  await act(async () => first.root.render(createElement(StrictMode, null, createElement(RemediationWorkspaceTabs, props))))
  expect(first.container.querySelector('dialog').open).toBe(true)
  await unmountAll()
  history.replaceState({}, '', '/?tab=remediate&mode=plan')
  const second = createTestRoot()
  await act(async () => second.root.render(createElement(RemediationWorkspaceTabs, props)))
  expect(second.container.querySelector('dialog').open).toBe(false)
  await act(async () => [...second.container.querySelectorAll('button')].find(b => b.textContent === 'Remediation plan').click())
  expect(second.container.querySelector('dialog').open).toBe(true)
  await act(async () => second.root.render(createElement(RemediationWorkspaceTabs, { ...props, assessmentIdentity:'next-assessment-same-scan-fixture' })))
  expect(second.container.querySelector('dialog').open).toBe(true)
})
it('does not introduce an incomplete assessment or accepted plan', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(RemediationWorkspaceTabs, { runId:'incomplete-fixture', assessmentReady:false })))
  expect(container.querySelector('dialog').open).toBe(false)
  await act(async () => root.render(createElement(RemediationWorkspaceTabs, { runId:'accepted-fixture', assessmentReady:true, planAccepted:true })))
  expect(container.querySelector('dialog').open).toBe(false)
})
it('does not reopen an accepted plan while its running snapshot reconnects', async () => {
  history.replaceState({}, '', '/?tab=remediate&mode=plan')
  const {root,container}=createTestRoot()
  const props={runId:'accepted-popup-reconnect',assessmentIdentity:'accepted-popup-reconnect:assessment-1',assessmentReady:true,plan:'choices',live:'progress'}
  await act(async()=>root.render(createElement(RemediationWorkspaceTabs,props)))
  expect(container.querySelector('dialog').open).toBe(true)
  await act(async()=>root.render(createElement(RemediationWorkspaceTabs,{...props,planAccepted:true})))
  expect(container.querySelector('dialog').open).toBe(false)
  // Remediation is running, but the next stream snapshot is unavailable. Its
  // last accepted plan must not become a fresh planning prompt from the old URL.
  await act(async()=>root.render(createElement(RemediationWorkspaceTabs,{...props,assessmentReady:false,planAccepted:false,snapshot:null})))
  expect(container.querySelector('dialog').open).toBe(false)
})

it('keeps an accepted assessment closed across remounts, preserves explicit planning and introduces a new assessment', async () => {
  const props={runId:'accepted-popup-remount',assessmentIdentity:'accepted-popup-remount:assessment-1',assessmentReady:true,plan:'choices',live:'progress'}
  const first=createTestRoot()
  await act(async()=>first.root.render(createElement(RemediationWorkspaceTabs,{...props,planAccepted:true})))
  await unmountAll()
  history.replaceState({}, '', '/?tab=remediate&mode=plan')
  const second=createTestRoot()
  await act(async()=>second.root.render(createElement(RemediationWorkspaceTabs,{...props,assessmentReady:false,planAccepted:false})))
  expect(second.container.querySelector('dialog').open).toBe(false)
  expect(new URLSearchParams(location.search).get('mode')).toBe('live')
  await act(async()=>window.dispatchEvent(new PopStateEvent('popstate')))
  expect(second.container.querySelector('dialog').open).toBe(false)
  await act(async()=>[...second.container.querySelectorAll('button')].find(button=>button.textContent==='Remediation plan').click())
  expect(second.container.querySelector('dialog').open).toBe(true)
  await act(async()=>second.root.render(createElement(RemediationWorkspaceTabs,{...props,assessmentIdentity:'accepted-popup-remount:assessment-2',planAccepted:false})))
  expect(second.container.querySelector('dialog').open).toBe(true)
})
