import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(HERE, 'App.jsx'), 'utf8')
const analytics = readFileSync(join(HERE, 'AdminInsights.jsx'), 'utf8')

describe('Live Operations navigation', () => {
  it('offers live Azure traffic as its own top-level tab', () => {
    expect(app).toMatch(/\[\s*'liveops'\s*,\s*'Live Operations'\s*,\s*'Azure traffic'/)
    expect(app).toContain("view === 'liveops' &&")
    expect(app).toContain("lazy(() => import('./AdminLiveTraffic.jsx'))")
  })

  it('shows every top-level tab to every signed-in user for the temporary open-view policy', () => {
    expect(app).toContain('const ALL_TAB_KEYS = TABS.map')
    expect(app).toContain('{TABS.map(([k, label, rg, step]) => {')
    expect(app).toContain('...ALL_TAB_KEYS')
    expect(app).not.toContain("view === 'liveops' && me.allow?.includes('liveops')")
  })

  it('does not duplicate live traffic inside Scan Analytics', () => {
    expect(analytics).not.toContain('AdminLiveTraffic')
    expect(analytics).not.toContain('Live Azure traffic')
  })
})
