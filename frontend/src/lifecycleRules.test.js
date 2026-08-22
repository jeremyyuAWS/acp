/**
 * Lifecycle-rule vocabulary and payload shaping (Discover step 2).
 *
 * Two things are asserted here that a DOM test cannot reach:
 *
 *  1. The exact WORDS. On this screen a person writes a rule that sounds destructive and is not —
 *     the rule only writes a recommendation tag. "will be archived" and "will be tagged for
 *     archive review" render identically as far as a DOM query is concerned, so the sentence
 *     generator is asserted string-by-string, and the whole module is swept for the vocabulary
 *     that would be a lie.
 *  2. That every (field, op) this editor can emit is one api/disposition.py accepts. The backend
 *     validates against FIELDS/_OPS and 422s on anything else; that failure would only surface at
 *     create time, in a deployment, as "the rule did not save".
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  ACTIONS, CONDITIONS, LIFECYCLE_ACTIONS, actionSpec, draftProblem, draftToMatch, emptyDraft,
  formatRuleDate, matchCountText, matchToDraftValues, parseMatch, refusalText, ruleSentenceParts,
  ruleSentenceText,
} from './lifecycleRules.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

// Mirrors api/disposition.py — FIELDS and _OPS. Kept literal so a backend narrowing shows up as a
// failing test here rather than as a 422 in a deployment.
const BACKEND_FIELDS = new Set(['department', 'business_criticality', 'regulatory_tags', 'triage_score',
  'source', 'owner', 'age_days', 'path', 'parent_folder', 'modified_age_days', 'modified_at', 'created_at',
  'doc_class', 'size_kb'])
const BACKEND_OPS = new Set(['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'prefix', 'before', 'after'])

const draft = (over = {}) => ({ ...emptyDraft(), ...over, values: { ...emptyDraft().values, ...(over.values || {}) } })

describe('the sentence a rule is restated as', () => {
  it('reads as the design board writes it, for a folder + last-modified archive rule', () => {
    const match = [
      { field: 'parent_folder', op: 'prefix', value: 'Clinical Guidelines/' },
      { field: 'modified_at', op: 'before', value: '2021-01-01' },
    ]
    expect(ruleSentenceText(match, 'archive')).toBe(
      'Files under Clinical Guidelines/ last modified before 1 Jan 2021 will be tagged for archive review.')
  })

  it('says "tagged for deletion review" — never that anything is deleted, trashed or removed', () => {
    const match = [
      { field: 'parent_folder', op: 'prefix', value: 'Accessibility Program/_superseded/' },
      { field: 'modified_at', op: 'before', value: '2023-01-01' },
    ]
    const text = ruleSentenceText(match, 'delete')
    expect(text).toBe('Files under Accessibility Program/_superseded/ last modified before '
      + '1 Jan 2023 will be tagged for deletion review.')
    expect(text).not.toMatch(/\b(deleted|trashed|removed|moved|archived|purged)\b/)
  })

  it('bolds the folder, the date and the outcome — the three things a reader scans for', () => {
    const parts = ruleSentenceParts([
      { field: 'parent_folder', op: 'prefix', value: 'Finance/2019/' },
      { field: 'modified_at', op: 'before', value: '2022-01-01' },
    ], 'archive')
    expect(parts.filter((p) => p.b).map((p) => p.t))
      .toEqual(['Finance/2019/', '1 Jan 2022', 'tagged for archive review'])
  })

  it('joins a non-positional pair with "and" rather than running the clauses together', () => {
    expect(ruleSentenceText([
      { field: 'modified_at', op: 'before', value: '2022-01-01' },
      { field: 'modified_age_days', op: 'gt', value: 1095 },
    ], 'archive')).toBe('Files last modified before 1 Jan 2022 and not modified in the last 1095 days '
      + 'will be tagged for archive review.')
  })

  it('puts the folder first however the conditions were stored', () => {
    expect(ruleSentenceText([
      { field: 'modified_age_days', op: 'gt', value: 730 },
      { field: 'parent_folder', op: 'prefix', value: 'HR/' },
    ], 'archive')).toBe('Files under HR/ not modified in the last 730 days will be tagged for archive review.')
  })

  it('states outright that a rule with no conditions matches everything, rather than leaving a gap', () => {
    // A no-condition rule is refused by the builder, but one can already exist via the API. Read
    // back, it must not render as a harmless-looking "Files will be tagged…".
    expect(ruleSentenceText([], 'delete'))
      .toBe('Files in every folder in scope will be tagged for deletion review.')
  })

  it('phrases a condition the builder cannot create, instead of printing the schema', () => {
    // triage_score is a real backend field (api/disposition.py FIELDS) the builder deliberately
    // does not expose — it's computed, not an attribute an admin would author a rule around — so
    // it is the one field still routed through the last-resort fallback rather than a template.
    expect(ruleSentenceText([{ field: 'triage_score', op: 'gt', value: 70 }], 'archive'))
      .toBe('Files triage score gt 70 will be tagged for archive review.')
  })

  it('phrases every condition the builder CAN create with its own reader-facing wording, not the schema', () => {
    expect(ruleSentenceText([{ field: 'path', op: 'contains', value: '_OLD' }], 'archive'))
      .toBe('Files whose path contains _OLD will be tagged for archive review.')
    expect(ruleSentenceText([{ field: 'age_days', op: 'gt', value: 1825 }], 'archive'))
      .toBe('Files older than 1825 days will be tagged for archive review.')
    expect(ruleSentenceText([{ field: 'created_at', op: 'before', value: '2021-01-01' }], 'archive'))
      .toBe('Files created before 1 Jan 2021 will be tagged for archive review.')
    expect(ruleSentenceText([{ field: 'owner', op: 'eq', value: 'jane@company.com' }], 'archive'))
      .toBe('Files owned by jane@company.com will be tagged for archive review.')
    expect(ruleSentenceText([{ field: 'source', op: 'eq', value: 'sharepoint' }], 'archive'))
      .toBe('Files in sharepoint will be tagged for archive review.')
    expect(ruleSentenceText([{ field: 'doc_class', op: 'eq', value: 'pdf-document' }], 'delete'))
      .toBe('Files of type pdf-document will be tagged for deletion review.')
    expect(ruleSentenceText([{ field: 'size_kb', op: 'gt', value: 10000 }], 'archive'))
      .toBe('Files larger than 10000 KB will be tagged for archive review.')
  })

  it('survives a legacy or corrupt match column without throwing', () => {
    expect(parseMatch('not json')).toEqual([])
    expect(parseMatch(null)).toEqual([])
    expect(parseMatch('{"field":"x"}')).toEqual([])          // an object is not a condition list
    expect(ruleSentenceText('[]', 'archive')).toContain('in every folder in scope')
    expect(ruleSentenceText(JSON.stringify([{ field: 'parent_folder', op: 'prefix', value: 'A/' }]), 'archive'))
      .toBe('Files under A/ will be tagged for archive review.')
  })
})

describe('dates are restated, not echoed', () => {
  it('renders ISO as the board writes it', () => {
    expect(formatRuleDate('2021-01-01')).toBe('1 Jan 2021')
    expect(formatRuleDate('2022-12-31')).toBe('31 Dec 2022')
    expect(formatRuleDate('2023-01-01T00:00:00Z')).toBe('1 Jan 2023')
  })
  it('hands back anything it cannot read unchanged rather than guessing', () => {
    expect(formatRuleDate('last tuesday')).toBe('last tuesday')
    expect(formatRuleDate('2021-13-01')).toBe('2021-13-01')
    expect(formatRuleDate(null)).toBe('')
  })
})

describe('an unasked question is never a measured zero', () => {
  it('null reads as "not asked", not as "nothing matched"', () => {
    expect(matchCountText(null)).toBe('Preview to see how many files match.')
    expect(matchCountText(undefined)).toBe('Preview to see how many files match.')
    expect(matchCountText(null)).not.toMatch(/\b0\b|\bno\b|\bnone\b/)
  })
  it('a real zero is stated as a real zero', () => {
    expect(matchCountText(0)).toBe('Matches none of the files discovered so far.')
  })
  it('counts are singular/plural correct and grouped', () => {
    expect(matchCountText(1)).toBe('Matches about 1 file.')
    expect(matchCountText(310)).toBe('Matches about 310 files.')
    expect(matchCountText(12345)).toMatch(/Matches about 12,345 files\./)
  })
})

describe('draft → the payload the backend validates', () => {
  it('emits only (field, op) pairs api/disposition.py accepts', () => {
    for (const c of CONDITIONS) {
      expect(BACKEND_FIELDS.has(c.field), `${c.field} not in disposition.FIELDS`).toBe(true)
      expect(BACKEND_OPS.has(c.op), `${c.op} not in disposition._OPS`).toBe(true)
    }
    for (const a of ACTIONS) expect(['archive', 'delete']).toContain(a.action)
  })

  it('drops blank fields and coerces days to a number, because gt compares with >', () => {
    const m = draftToMatch(draft({ values: { folder: 'Finance/2019/', modifiedBefore: '', notModifiedDays: '1095' } }))
    expect(m).toEqual([
      { field: 'parent_folder', op: 'prefix', value: 'Finance/2019/' },
      { field: 'modified_age_days', op: 'gt', value: 1095 },
    ])
    expect(typeof m[1].value).toBe('number')     // '1095' > 999 is false as a string compare
  })

  it('builds a condition on file type and size — the two genuinely new fields this adds', () => {
    const m = draftToMatch(draft({ values: { fileType: 'pdf-document', largerThanKb: '10000' } }))
    expect(m).toEqual([
      { field: 'doc_class', op: 'eq', value: 'pdf-document' },
      { field: 'size_kb', op: 'gt', value: 10000 },
    ])
    expect(typeof m[1].value).toBe('number')
  })

  it('refuses a rule with no conditions — it would match every file in scope', () => {
    expect(draftProblem(draft({ name: 'Everything' })))
      .toBe('Add at least one condition — a rule with none would match every file in scope.')
    expect(draftToMatch(draft({ name: 'Everything' }))).toEqual([])
  })

  it('refuses an unnamed rule and a nonsense day count', () => {
    expect(draftProblem(draft({ values: { folder: 'A/' } }))).toBe('Give the rule a name.')
    expect(draftProblem(draft({ name: 'x', values: { notModifiedDays: 'soon' } }))).toMatch(/number of days/)
    expect(draftProblem(draft({ name: 'x', values: { notModifiedDays: '0' } }))).toMatch(/greater than zero/)
    expect(draftProblem(draft({ name: 'x', values: { folder: 'A/', modifiedBefore: '01/01/2021' } })))
      .toMatch(/YYYY-MM-DD/)
  })

  it('accepts the board\'s example rule', () => {
    const d = draft({ name: 'Finance retention', values: { folder: 'Finance/2019/', modifiedBefore: '2022-01-01' } })
    expect(draftProblem(d)).toBe('')
    expect(ruleSentenceText(draftToMatch(d), d.action))
      .toBe('Files under Finance/2019/ last modified before 1 Jan 2022 will be tagged for archive review.')
  })

  it('starts every draft on the reversible action', () => {
    expect(emptyDraft().action).toBe('archive')
  })
})

describe('matchToDraftValues — the inverse of draftToMatch, for editing a saved rule', () => {
  it('round-trips a stored match back into the same per-condition values the builder wrote', () => {
    const stored = draftToMatch(draft({
      values: { folder: 'Finance/2019/', modifiedBefore: '2022-01-01', largerThanKb: '10000' },
    }))
    const values = matchToDraftValues(stored)
    expect(values.folder).toBe('Finance/2019/')
    expect(values.modifiedBefore).toBe('2022-01-01')
    expect(values.largerThanKb).toBe('10000')
    expect(values.notModifiedDays).toBe('')             // every other condition stays blank
  })

  it('parses the stored JSON-string form, the shape the column actually holds', () => {
    const values = matchToDraftValues(JSON.stringify([{ field: 'parent_folder', op: 'prefix', value: 'HR/' }]))
    expect(values.folder).toBe('HR/')
  })

  it('drops a condition the builder cannot create rather than crashing on it', () => {
    const values = matchToDraftValues([{ field: 'triage_score', op: 'gt', value: 70 }])
    expect(Object.values(values).every((v) => v === '')).toBe(true)
  })

  it('returns every key blank for no conditions, [], or a corrupt column', () => {
    for (const m of [[], 'not json', null]) {
      const values = matchToDraftValues(m)
      expect(Object.values(values).every((v) => v === '')).toBe(true)
    }
  })
})

describe('a refused create is explained, not swallowed', () => {
  it('names the permission when the server refuses a non-admin', () => {
    const t = refusalText(new Error('403: admin required'))
    expect(t).toMatch(/Only a platform admin/)
    expect(t).toMatch(/the rule was not saved/)
    expect(t).toContain('403: admin required')          // the server's own words are kept
  })
  it('passes any other failure through rather than mislabelling it a permission problem', () => {
    expect(refusalText(new Error('network down'))).toBe('network down')
    expect(refusalText(undefined)).toBe('The server refused the change.')
  })
})

describe('the two actions carry their real safety semantics', () => {
  it('describes delete as Drive trash, recoverable, never permanent', () => {
    const del = actionSpec('delete')
    expect(del.label).toBe('Recommend deletion')
    expect(del.tag).toBe('recommend deletion')
    expect(del.safety).toMatch(/Drive trash/)
    expect(del.safety).toMatch(/recoverable/)
    expect(del.safety).toMatch(/never a permanent delete/)
    expect(del.safety).toMatch(/Nothing is trashed or deleted here/)
  })
  it('describes archive as a tag that moves nothing', () => {
    const arch = actionSpec('archive')
    expect(arch.tag).toBe('recommend archive')
    expect(arch.safety).toMatch(/Nothing is moved/)
    expect(arch.safety).toMatch(/still needs your decision/)
  })
  it('offers only the two lifecycle actions, so a tag/move/rename policy is never shown here', () => {
    expect([...LIFECYCLE_ACTIONS].sort()).toEqual(['archive', 'delete'])
    expect(LIFECYCLE_ACTIONS.has('tag')).toBe(false)
  })
  it('falls back to the reversible action for an unknown one rather than to delete', () => {
    expect(actionSpec('move').action).toBe('archive')
    expect(actionSpec(undefined).action).toBe('archive')
  })
})

describe('the module never claims a file was acted on', () => {
  // The single most important rule on this screen, asserted over the source itself so a future
  // edit that reintroduces the vocabulary fails here rather than shipping.
  //
  // Scoped to CODE, with comments stripped. Both files carry comments that quote the banned
  // phrasing in order to forbid it ("must never say a file was archived or deleted"), and a guard
  // that cannot tell a prohibition from a violation would force those explanations out of the
  // files — which is where the reason for the rule has to live.
  const stripComments = (src) => src
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
  const BANNED = [
    /\bfiles? (?:was|were|are|is) (?:archived|deleted|trashed|moved|removed)\b/i,
    /\bwill be (?:archived|deleted|trashed|moved|removed)\b/i,
    /\bhas been (?:archived|deleted|trashed|moved)\b/i,
    /\bpermanently delete/i,
  ]
  for (const file of ['lifecycleRules.js', 'DispositionRules.jsx']) {
    it(`${file} contains no "the file was archived/deleted/moved" phrasing`, () => {
      const src = stripComments(read(file))
      for (const re of BANNED) expect(src, `${file} matches ${re}`).not.toMatch(re)
    })
    it(`${file} keeps the prohibition written down in its own comments`, () => {
      // The counterpart to the guard above: strip the comments and you lose the only statement of
      // WHY the words matter. Assert it is still there, so nobody satisfies the guard by deletion.
      expect(read(file)).toMatch(/never (?:say|claims?)|may say a file|must never say/i)
    })
  }
  it('the permitted vocabulary is actually present', () => {
    const src = read('lifecycleRules.js')
    for (const word of ['tagged for review', 'recommendation', 'candidate', 'needs your decision']) {
      expect(src.toLowerCase()).toContain(word)
    }
  })
})
