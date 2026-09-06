import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))

describe('runtime-only realtime shadow activation', () => {
  it('uses the server config instead of a build-time Vite flag', () => {
    const app = readFileSync(join(here, 'App.jsx'), 'utf8')
    const client = readFileSync(join(here, 'realtimeShadowClient.js'), 'utf8')
    expect(app).toContain("setRealtimeShadowEnabled(c?.realtime_shadow_enabled === true)")
    expect(app).toContain('<RealtimeShadowPanel enabled={realtimeShadowEnabled}')
    expect(client).not.toContain('VITE_REALTIME_SHADOW_ENABLED')
  })
})
