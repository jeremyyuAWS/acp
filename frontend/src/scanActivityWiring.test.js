import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(HERE, 'Monitor.jsx'), 'utf8')

describe('Langfuse activity is a first-class Monitor surface', () => {
  it('mounts the scan activity panel with current and historical scans', () => {
    expect(source).toMatch(/import ScanActivityPanel from '\.\/ScanActivityPanel\.jsx'/)
    expect(source).toMatch(/<ScanActivityPanel run=\{run\} scanList=\{scanList\} \/>/)
  })
})
