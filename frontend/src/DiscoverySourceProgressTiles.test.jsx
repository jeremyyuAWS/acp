import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { createTestRoot, unmountAll } from './testRoots.js'
import DiscoverySourceProgressTiles from './DiscoverySourceProgressTiles.jsx'
import DiscoverRunProgress from './DiscoverRunProgress.jsx'
afterEach(() => { unmountAll(); vi.unstubAllGlobals() })
async function render(progress, freshness = 'live') {
  const view = createTestRoot()
  await act(async () => view.root.render(<DiscoverySourceProgressTiles source="sharepoint" progress={progress} freshness={freshness}/>))
  return view
}
it('shows only recorded numbers, including zero, and never invents site coverage', async () => {
  const { container } = await render({phase: 'discovering', files_found: 0, folders_visited: 12})
  const tiles = container.querySelectorAll('dl > div')
  expect(tiles).toHaveLength(3)
  expect(tiles[0].querySelector('dd').textContent).toBe('0')
  expect(tiles[1].querySelector('dd').textContent).toBe('12')
  expect(tiles[2].querySelector('dd').textContent).toBe('Not Reported Yet')
  expect(container.textContent).not.toContain('sites read')
  expect(container.querySelector('progress')).toBeNull()
})
it('uses measured updates with reduced motion and stops active signals at checkpoint or lifecycle', async () => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({matches:true})))
  const {container, root} = await render({phase:'discovering', files_found:4, folders_found:2, save_new:2, save_updated:1})
  expect(container.querySelectorAll('.is-live')).toHaveLength(3)
  await act(async () => root.render(<DiscoverySourceProgressTiles source="sharepoint" freshness="checkpoint" progress={{phase:'discovering', files_found:8}}/>))
  expect(container.querySelector('dd').textContent).toContain('8')
  expect(container.querySelector('.is-live')).toBeNull()
  await act(async () => root.render(<DiscoverySourceProgressTiles source="sharepoint" freshness="live" progress={{phase:'lifecycle', files_found:8}}/>))
  expect(container.textContent).toContain('Source Inventory Collected')
  expect(container.querySelector('.is-live')).toBeNull()
  expect(readFileSync('src/discovery-source-progress-tiles.css','utf8')).toContain('prefers-reduced-motion: reduce')
})
it('the actual discovery screen replaces the Graph card and duplicate accounting row, preserving its retired code', async () => {
  const {container, root} = createTestRoot()
  await act(async () => root.render(<DiscoverRunProgress busy source="sharepoint" freshness="live" progress={{phase:'discovering', files_found:9, folders_visited:4}}/>))
  expect(container.querySelector('[aria-label="Source discovery progress"]')).not.toBeNull()
  expect(container.querySelector('[aria-label="SharePoint integration status"]')).toBeNull()
  expect(container.querySelector('[aria-label="Live discovery accounting"]')).toBeNull()
  const source = readFileSync('src/DiscoverRunProgress.jsx','utf8')
  expect(source).toContain('function SharePointLiveSummary(')
  expect(source).not.toContain('<SharePointLiveSummary ')
})
it('keeps actual inaccessible-file counts visible without calling them findings', async () => {
  const {container} = await render({phase:'discovering',files_found:9,exc_inaccessible_file:2,exc_deleted_during_scan:1})
  expect(container.querySelector('.needs-attention dd').textContent).toBe('3')
  expect(container.textContent).toContain('Skipped or unreadable items')
})
