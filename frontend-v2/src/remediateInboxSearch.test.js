import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The AI Work Inbox can hold dozens of EvidenceCards; a reviewer needs to collapse them to headers
// and search across them. The behaviour of the search lives in reviewInboxFilter.js and is tested
// directly there. This pins the WIRING in Remediate.jsx — same source-level approach and same
// reason as remediateCollapse.test.js: a mount would need the whole run/files/queue fixture stack,
// and one that silently rendered an empty inbox would pass every "there is a search box" assertion
// by rendering nothing at all.

const HERE = dirname(fileURLToPath(import.meta.url))
const rem = () => readFileSync(join(HERE, 'Remediate.jsx'), 'utf8')

describe('AI Work Inbox: searchable', () => {
  it('renders a search input wired to reviewQuery', () => {
    const s = rem()
    expect(s).toMatch(/const \[reviewQuery, setReviewQuery\] = useState\(''\)/)
    expect(s).toMatch(/<input type="search" className="revsearch"/)
    expect(s).toMatch(/value=\{reviewQuery\}/)
    expect(s).toMatch(/onChange=\{\(e\) => setReviewQuery\(e\.target\.value\)\)?\}/)
    // an accessible name, since the placeholder is not one
    expect(s).toMatch(/aria-label="Search the AI Work Inbox"/)
  })

  it('filters the queue through applyReviewFilters and maps the FILTERED list, not the raw queue', () => {
    const s = rem()
    expect(s).toMatch(/import \{ applyReviewFilters, reviewFacets \} from '\.\/reviewInboxFilter\.js'/)
    expect(s).toMatch(/const filteredQueue = useMemo\(\s*\(\) => applyReviewFilters\(queue, \{ query: reviewQuery/)
    expect(s).toMatch(/\{filteredQueue\.map\(\(q\) =>/)
    // the old unconditional `queue.map` in the review list must be gone
    expect(s).not.toMatch(/<div className="reviewlist">[\s\S]{0,400}\{queue\.map\(/)
  })

  it('tells the reviewer when a search matches nothing, with a way back', () => {
    const s = rem()
    expect(s).toMatch(/filteredQueue\.length === 0 \?/)
    expect(s).toMatch(/No items match/)
    expect(s).toMatch(/onClick=\{clearFilters\}/)
  })
})

describe('AI Work Inbox: collapsible', () => {
  it('wraps each card in a native <details> so collapse is keyboard-operable and self-announcing', () => {
    const s = rem()
    // <details>, not a button+useState with a hand-managed aria-expanded — same accessibility
    // reasoning the RemSection helper follows.
    expect(s).toMatch(/<details key=\{q\.id\} className="revcard" open=\{!collapsedCards\[q\.id\]\}/)
    expect(s).toMatch(/<summary className="revcard-sum">/)
    expect(s).not.toMatch(/aria-expanded=\{[^}]*collapsedCards/)
  })

  it('keeps the identity a reviewer navigates by visible on the collapsed row', () => {
    // filename, WCAG criterion and severity — enough to decide whether to open a card without
    // expanding it.
    const s = rem()
    expect(s).toMatch(/className="revcard-sum-file"[\s\S]{0,80}\{q\.file\}/)
    expect(s).toMatch(/className="revcard-sum-rule[^"]*">\{q\.rule\}/)
    expect(s).toMatch(/revcard-sev sev-\$\{String\(q\.severity\)\.toLowerCase\(\)\}/)
  })

  it('seeds each card collapsed on first appearance, preserving a reviewer’s manual expansion', () => {
    // The map still starts empty, but an effect now seeds every NEW card id as collapsed (true).
    // It merges only ids ABSENT from the map, so a card a reviewer expanded (already present as
    // false) is left alone across the queue's background refetches — the property that makes a
    // default-collapsed inbox usable rather than one that keeps snapping shut under you.
    const s = rem()
    expect(s).toMatch(/const \[collapsedCards, setCollapsedCards\] = useState\(\{\}\)/)
    expect(s).toMatch(/if \(!\(q\.id in next\)\)/)
    expect(s).toMatch(/next\[q\.id\] = true/)
    expect(s).toMatch(/\}, \[queueIds\]\)/)
  })

  it('has a collapse-all / expand-all toggle acting on the visible cards', () => {
    const s = rem()
    expect(s).toMatch(/const allVisibleCollapsed = filteredQueue\.length > 0 && filteredQueue\.every\(\(q\) => collapsedCards\[q\.id\]\)/)
    expect(s).toMatch(/onClick=\{\(\) => setAllVisible\(!allVisibleCollapsed\)\}/)
    expect(s).toMatch(/\{allVisibleCollapsed \? 'Expand all' : 'Collapse all'\}/)
    // the toggle reports its state to assistive tech
    expect(s).toMatch(/aria-pressed=\{allVisibleCollapsed\}/)
  })

  it('leaves the review panel a plain <section>, not a collapsed RemSection', () => {
    // Regression guard shared with remediateCollapse.test.js: the inbox is the work, it must not
    // sit behind its own disclosure.
    const s = rem()
    expect(s).toMatch(/<section className="panel rem-review-panel" id="rem-review">/)
    expect(s).not.toMatch(/<RemSection[^>]*id="rem-review"/)
  })
})

describe('AI Work Inbox: inline triage on the collapsed row', () => {
  it('previews the AI’s proposed fix on the summary so the obvious ones need no expanding', () => {
    const s = rem()
    // The literal proposed value when there is one, the shorter action hint otherwise.
    expect(s).toMatch(/typeof q\.after === 'string' && q\.after\.trim\(\)/)
    expect(s).toMatch(/className="revcard-sum-rec muted"/)
  })

  it('offers Approve / Reject on the row, wired to the same evAct path as the expanded card', () => {
    const s = rem()
    expect(s).toMatch(/evAct\(q\.id, 'approved'\)/)
    expect(s).toMatch(/evAct\(q\.id, 'rejected'\)/)
    // Named for assistive tech, not just a glyph.
    expect(s).toMatch(/aria-label=\{`Approve the proposed fix for \$\{q\.file\}`\}/)
  })

  it('acts on the item instead of toggling the <details> it sits inside', () => {
    // Without preventDefault + stopPropagation a click on Approve would ALSO expand/collapse the
    // card — the button lives inside the <summary> whose default action is the toggle.
    const s = rem()
    expect(s).toMatch(/e\.preventDefault\(\); e\.stopPropagation\(\); evAct\(q\.id, 'approved'\)/)
    expect(s).toMatch(/e\.preventDefault\(\); e\.stopPropagation\(\); evAct\(q\.id, 'rejected'\)/)
  })

  it('hides the inline actions in read-only (time-travel replay)', () => {
    // A historical scan is look-only; the actions must not offer to mutate it.
    const s = rem()
    expect(s).toMatch(/\{!readOnly && \(\s*<span style=\{\{ display: 'inline-flex'/)
  })
})
