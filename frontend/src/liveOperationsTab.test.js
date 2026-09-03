import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(HERE, 'App.jsx'), 'utf8')
const analytics = readFileSync(join(HERE, 'AdminInsights.jsx'), 'utf8')

describe('admin Live Operations navigation', () => {
  it('offers live Azure traffic as its own top-level tab', () => {
    expect(app).toMatch(/\[\s*'liveops'\s*,\s*'Live Operations'\s*,\s*'Azure traffic'/)
    expect(app).toContain("view === 'liveops' && me.allow?.includes('liveops')")
    expect(app).toContain("lazy(() => import('./AdminLiveTraffic.jsx'))")
  })

  it('grants the tab only after the backend identifies an admin', () => {
    expect(app).toContain("const adminViews = ['analytics', 'liveops']")
    expect(app).toContain("if (m2?.is_admin)")
  })

  it('does not duplicate live traffic inside Scan Analytics', () => {
    expect(analytics).not.toContain('AdminLiveTraffic')
    expect(analytics).not.toContain('Live Azure traffic')
  })
})
