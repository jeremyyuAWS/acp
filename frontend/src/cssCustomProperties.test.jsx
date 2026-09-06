/**
 * Every `var(--x)` written WITHOUT a fallback must name a property this codebase actually declares.
 *
 * WHY THIS EXISTS. `--text` was used in three places and declared in none. An undeclared custom
 * property with no fallback makes the whole declaration invalid at computed-value time, so the
 * property falls back to its inherited value — and inheriting a text colour usually looks fine.
 * That is the entire problem: the bug renders correctly, so nothing draws attention to it, and it
 * only becomes visible when the element is moved under an ancestor with a different colour.
 *
 * It also SPREADS, which is what turned this from a curiosity into a guard. `--text` had two uses
 * when it was first written down; a third arrived hours later in an unrelated change to the
 * remediation panel, copied from the neighbouring line. Nothing failed, because nothing could.
 *
 * WHAT IS AND IS NOT A DEFECT. `var(--x, #fff)` with a fallback is deliberate and extremely common
 * here — 66 such uses at the time of writing, and they are correct: the fallback is the value. Only
 * a BARE `var(--x)` naming an undeclared property is a bug. This file draws exactly that line, and
 * drawing it anywhere else would flag most of the codebase.
 *
 * THE ALLOWLIST IS EMPTY, AND THAT IS THE POINT. It shipped with seven entries — the properties
 * that had this defect on screens the --text fix did not touch. All seven are now fixed, so the
 * list is empty and the rule is absolute: no bare undeclared custom property, anywhere.
 *
 * Keep it that way by fixing the property rather than adding a name here. An entry is a statement
 * that a known-broken colour is acceptable for now, and the seven were only ever acceptable
 * because they were about to be fixed.
 *
 * The assertion runs in both directions, like unmountedComponents.test.jsx: adding a new bare
 * undeclared property fails, and FIXING one also fails until it is removed from the list. With an
 * empty list only the first direction can fire, which is the state to preserve.
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'fs'
import { resolve, join } from 'path'

const SRC = resolve(import.meta.dirname)

// Empty, and to be kept empty. The seven this shipped with were fixed in the follow-up that
// emptied it; each was mapped to the declared token its own use already implied:
//   --accent    -> --info-fg            FolderPicker's clickable breadcrumb segments
//   --border    -> --line               15 sites; --line IS the border token
//   --danger-fg -> --error-fg-strong    Publish's failed-release alert
//   --error     -> --error-fg-strong    AdminInsights, which used the right token 4 lines away
//   --fg        -> --ink                3 sites; --ink IS the text token
//   --page      -> --bg                 AdminLiveTraffic's page-coloured wells
//   --panel     -> --surface            5 sites; all 13 fallbacks elsewhere said #fff, and
//                                       --surface is the codebase's opaque #fff card token
const KNOWN_UNDECLARED = []

const sourceFiles = () => {
  const out = []
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      const p = join(dir, entry)
      if (statSync(p).isDirectory()) { if (entry !== 'node_modules') walk(p) }
      // Test files are excluded, and not for convenience: they QUOTE css in assertion strings
      // (`expect(style).toContain('var(--panel)')`), and a quoted property is not a styled
      // element. Including them counted this very file's own failure message as a use of the
      // property it exists to forbid — which is how the exclusion was found.
      else if (/\.(css|jsx?)$/.test(entry) && !/\.test\./.test(entry)) out.push(p)
    }
  }
  walk(SRC)
  return out
}

// Comments MENTION these properties — this very file does, at length — and a mention is not a use.
// Block comments cover CSS, JS and the JSX `{/* … */}` form; the line rule is deliberately anchored
// so that a `//` inside a string (a URL, say) is not mistaken for a comment.
const stripComments = (text) => text
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !/^\s*(\/\/|\*)/.test(l.trim() ? l : 'x')).join('\n')

const scan = () => {
  const declared = new Set()
  const bare = new Map()
  const files = sourceFiles()
  for (const f of files) {
    const text = stripComments(readFileSync(f, 'utf8'))
    for (const m of text.matchAll(/(?:^|[;{\s'"])(--[A-Za-z0-9_-]+)\s*'?"?\s*:/g)) declared.add(m[1])
  }
  for (const f of files) {
    const text = stripComments(readFileSync(f, 'utf8'))
    text.split('\n').forEach((line, i) => {
      for (const m of line.matchAll(/var\(\s*(--[A-Za-z0-9_-]+)\s*(,?)/g)) {
        const [, name, comma] = m
        if (comma === ',' || declared.has(name)) continue
        if (!bare.has(name)) bare.set(name, [])
        bare.get(name).push(`${f.slice(SRC.length + 1)}:${i + 1}`)
      }
    })
  }
  return { declared, bare }
}

describe('custom properties used without a fallback must be declared', () => {
  it('finds no bare undeclared property beyond the recorded debt', () => {
    const { bare } = scan()
    const found = [...bare.keys()].sort()
    const unexpected = found.filter((n) => !KNOWN_UNDECLARED.includes(n))
    // The sites are in the message because "--foo is undeclared" is not actionable on its own.
    const detail = unexpected.map((n) => `${n} at ${bare.get(n).join(', ')}`).join('\n')
    expect(unexpected, `bare undeclared custom properties:\n${detail}`).toEqual([])
  })

  it('has an EMPTY allowlist, so a regression cannot be waved through by listing it', () => {
    // THIS ASSERTION EXISTS BECAUSE A BITE CHECK FAILED TO BITE. With the list merely "asserted
    // in both directions", reintroducing a bare property AND adding its name here passed both of
    // the tests around this one — which is the exact move the list invites, and it is silent.
    //
    // Now that every entry is fixed, the empty list is itself the assertion. Adding a name means
    // deleting this test, and deleting a test that says why it exists is a decision somebody has
    // to make in a diff rather than a string somebody appends to a line.
    expect(KNOWN_UNDECLARED).toEqual([])
  })

  it('does not still carry an entry that has since been fixed', () => {
    // The other direction. Without it the list only ever grows, and a stale entry reads as a
    // defect that is still there.
    const { bare } = scan()
    expect(KNOWN_UNDECLARED.filter((n) => !bare.has(n))).toEqual([])
  })

  it('--text in particular is gone, and --ink is what replaced it', () => {
    // The specific regression this file was written for. `--text` was in LiveOperationsNotifier
    // and twice in remediation-live-detail.css; all three now use `--ink`, which is declared.
    const { declared, bare } = scan()
    expect(declared.has('--line') && declared.has('--bg') && declared.has('--surface')).toBe(true)
    expect(bare.has('--text'), 'the --text property is used bare again, and it is declared nowhere').toBe(false)
    expect(declared.has('--ink')).toBe(true)
  })

  it('does not mistake a mention in a comment for a use', () => {
    // The control. Several files DISCUSS --text, including this one; if comments counted, the
    // test above would fail for the wrong reason and the next reader would "fix" prose.
    const withMention = ['/*', 'the old code said', 'var(--totally-made-up-token)', '*/'].join(' ')
    expect(stripComments(withMention)).not.toContain('--totally-made-up-token')
  })

  it('treats a fallback as deliberate rather than as a defect', () => {
    // The other control, and the reason this file is not a 70-item failure: `var(--x, value)` is
    // the codebase's normal idiom for a JSX-side default.
    const { bare } = scan()
    expect(bare.has('--muted-fg')).toBe(false)   // used widely, always with a fallback
  })
})
