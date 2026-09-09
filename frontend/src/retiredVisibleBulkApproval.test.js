import { it, expect } from 'vitest'
import RetiredVisibleBulkApproval from './RetiredVisibleBulkApproval.jsx'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
it('retains the old bulk flow without mounting or importing it in production', () => {
  expect(typeof RetiredVisibleBulkApproval).toBe('function')
  const base = fileURLToPath(new URL('.', import.meta.url))
  const retired = readFileSync(`${base}RetiredVisibleBulkApproval.jsx`, 'utf8')
  expect(retired).toContain('RETIRED:')
  expect(retired).toContain('async function applyVisibleBulk()')
  for (const file of readdirSync(base).filter(name => /\.[jt]sx?$/.test(name) && !name.includes('.test.') && name !== 'RetiredVisibleBulkApproval.jsx')) {
    expect(readFileSync(`${base}${file}`, 'utf8'), file).not.toContain('RetiredVisibleBulkApproval')
  }
})
