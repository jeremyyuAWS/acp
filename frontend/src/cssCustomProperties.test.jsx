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
 * THE ALLOWLIST IS DEBT, NOT PERMISSION. Seven other properties have the same defect today. They
 * are recorded rather than fixed because they belong to screens this change does not touch, and a
 * silent list is how the next one gets added. Several are worse than the one that prompted this:
 * `background: var(--border)` and `background: var(--panel)` render TRANSPARENT rather than merely
 * inheriting a colour.
 *
 * The assertion runs in both directions, like unmountedComponents.test.jsx: adding a new bare
 * undeclared property fails, and FIXING one also fails until it is removed from the list. That is
 * deliberate — a ratchet only tightens if removing an entry is forced rather than optional.
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'fs'
import { resolve, join } from 'path'

const SRC = resolve(import.meta.dirname)

// Known-undeclared, bare, and NOT fixed here. Shrink this list; never grow it.
//   --accent      FolderPicker.jsx
//   --border      AdminInsights.jsx, AdminLiveTraffic.jsx, App.jsx  (renders transparent)
//   --danger-fg   Publish.jsx
//   --error       AdminInsights.jsx
//   --fg          FixOutcomes.jsx, ManualWork.jsx, styles.css
//   --page        AdminLiveTraffic.jsx
//   --panel       AdminLiveTraffic.jsx, styles.css                  (renders transparent)
const KNOWN_UNDECLARED = ['--accent', '--border', '--danger-fg', '--error', '--fg', '--page', '--panel']

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
