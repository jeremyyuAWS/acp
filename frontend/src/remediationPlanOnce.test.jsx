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
