import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { VALUE_FIX, isValueFix, reviewTelemetry } from './reviewCard.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('VALUE_FIX is shared, not duplicated', () => {
  it('covers the criteria whose fix is a value a screen reader announces', () => {
    expect([...VALUE_FIX].sort()).toEqual(['1.1.1', '2.4.2', '2.4.4', '2.4.9', '3.3.2'])
    expect(isValueFix('1.1.1')).toBe(true)
    expect(isValueFix('1.4.3')).toBe(false)   // contrast is a judgement call, nothing to type
  })

  it('ReviewCenter no longer keeps its own copy', () => {
    // Two screens disagreeing about which items get an editor is how a reviewer approves an
    // empty alt text on one and not the other.
    expect(read('ReviewCenter.jsx')).not.toMatch(/const VALUE_FIX = new Set/)
    expect(read('ReviewCenter.jsx')).toMatch(/from '\.\/reviewCard\.js'/)
  })
})

describe('reviewTelemetry — what the review actually was', () => {
  const base = { editable: true, status: 'approved', aiDraft: 'A cat', elapsedMs: 4200 }

  it('records the elapsed reviewer time', () => {
    expect(reviewTelemetry(base).reviewMs).toBe(4200)
  })

  it('flags an edit when the approved text differs from the AI draft', () => {
    expect(reviewTelemetry({ ...base, value: 'A tabby cat' }).edited).toBe(true)
    expect(reviewTelemetry({ ...base, value: 'A cat' }).edited).toBe(false)
  })

  it('counts authoring a value the AI could not draft as an edit', () => {
    expect(reviewTelemetry({ ...base, aiDraft: null, value: 'A tabby cat' }).edited).toBe(true)
  })

  it('keeps the AI draft alongside the final value, so both are auditable', () => {
    const t = reviewTelemetry({ ...base, value: 'A tabby cat' })
    expect(t.aiValue).toBe('A cat')
    expect(t.finalValue).toBe('A tabby cat')
  })

  it('sends no value on reject or skip — only an approval sets one', () => {
    expect(reviewTelemetry({ ...base, status: 'rejected', value: 'x' }).finalValue).toBeNull()
    expect(reviewTelemetry({ ...base, status: 'skipped', value: 'x' }).finalValue).toBeNull()
    expect(reviewTelemetry({ ...base, status: 'rejected', value: 'x' }).edited).toBe(false)
  })

  it('sends no value for a judgement item, which has nothing to type', () => {
    expect(reviewTelemetry({ ...base, editable: false, value: 'x' }).finalValue).toBeNull()
  })
})

describe('the evidence card is actually mounted, and owns the write', () => {
  const rc = () => read('ReviewCenter.jsx')

  it('ReviewCenter renders EvidenceCard for the open item', () => {
    expect(rc()).toMatch(/<EvidenceCard/)
    expect(rc()).toMatch(/import EvidenceCard from '\.\/EvidenceCard\.jsx'/)
  })

  it('the card decides through the parent, preserving the optimistic update', () => {
    // Calling updateHitlItem directly would bypass HitlBell's optimistic state + drain event.
    expect(read('EvidenceCard.jsx')).not.toMatch(/updateHitlItem/)
    expect(read('EvidenceCard.jsx')).toMatch(/onAct\(card\.id, status, note \|\| null/)
  })

  it('telemetry reaches the API — hitl_events.review_ms was previously always null', () => {
    expect(read('HitlBell.jsx')).toMatch(/updateHitlItem\(itemId, status, note, approvedValue, telemetry\)/)
  })

  it('an editor appears for value fixes even when the AI drafted nothing', () => {
    // The old gate was `aiDraft != null`, which hid the box exactly when a human was needed.
    expect(read('EvidenceCard.jsx')).toMatch(/isValueFix\(card\.sc\)/)
    expect(read('EvidenceCard.jsx')).not.toMatch(/aiDraft\.current != null/)
  })
})
