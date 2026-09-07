import React, { createElement } from 'react'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReleaseFileSelection, { releaseFileSize, releaseFileStatus } from './ReleaseFileSelection.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root
let container

const file = (name, extra = {}) => ({ file: name, source_relative_path: `Finance/${name}`, sourceName: 'Drive', score: 100, ...extra })
const renderSelection = async (props = {}) => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  const selected = props.selectedFiles || new Set(['ready.pdf'])
  await act(async () => root.render(createElement(ReleaseFileSelection, {
    files: [file('ready.pdf', { size_bytes: 2048 }), file('released.docx'), file('changed.pptx')],
    selectedFiles: selected, setSelectedFiles: props.setSelectedFiles || vi.fn(),
    done: { 'released.docx': true }, sourceState: (item) => item.file === 'changed.pptx' ? 'stale' : undefined,
    sourceProduct: 'Google Drive', releaseProvider: 'drive', driveMirrorEnabled: true,
    driveMirrorFolder: 'Remediated', releaseFolder: null, releaseResults: {},
    selectedFile: null, setSelectedFile: vi.fn(), sourcePath: (item) => item.source_relative_path,
    ...props,
  })))
  return container
}

afterEach(() => { if (root) act(() => root.unmount()); container?.remove(); root = null; container = null })

describe('ReleaseFileSelection', () => {
  it('classifies safety states and recognises available byte metadata', () => {
    expect(releaseFileStatus(file('x'), {}, () => 'stale')).toBe('changed')
    expect(releaseFileStatus(file('x'), { x: true }, () => undefined)).toBe('released')
    expect(releaseFileSize({ size_bytes: 4096 })).toBe(4096)
    expect(releaseFileSize({})).toBeNull()
  })

  it('shows compact status totals, exclusions, and an exact package estimate', async () => {
    const view = await renderSelection()
    expect(view.textContent).toContain('1 source changed')
    expect(view.textContent).toContain('1 already released')
    expect(view.textContent).toContain('Estimated package 2 KB')
    expect(view.querySelector('[aria-label="Select changed.pptx"]').disabled).toBe(true)
  })

  it('filters by status and clears all filters from the empty state', async () => {
    const view = await renderSelection()
    const status = [...view.querySelectorAll('select')].find((node) => node.parentElement.textContent.startsWith('Status'))
    await act(async () => { status.value = 'changed'; status.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(view.textContent).toContain('changed.pptx')
    expect(view.textContent).not.toContain('ready.pdf')
    await act(async () => { status.value = 'unreachable'; status.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(view.textContent).toContain('No files match these filters')
    await act(async () => view.querySelector('.release-selection__empty button').click())
    expect(view.textContent).toContain('ready.pdf')
  })
})
