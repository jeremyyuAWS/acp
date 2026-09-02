/**
 * A scan that finds no files has to say so.
 *
 * WHAT IT SAID BEFORE, rendered and read rather than guessed at — a zero-file scan produced a
 * wall of zeros plus:
 *
 *     COULD NOT BE READ
 *     Every one of the 0 files on this screen was read. Nothing was skipped.
 *
 * True, useless, and it reads as a bug. Nowhere did it say the folder was empty, and nowhere did
 * it distinguish that from the two things a user would fear instead: a folder ACP could not open,
 * or a scope that quietly excluded everything.
 *
 * WHAT MAKES THE NEW CLAIM SAFE TO MAKE. #1104. Before it, `_list_folder_files` returned [] when
 * a listing failed, so "empty" and "unreadable" were the same screen and no sentence could
 * honestly tell them apart. It now raises instead — pinned by
 * tests/test_folder_listing_never_fabricates_empty.py — so a rendered zero really does mean the
 * source was read and had nothing in it. That is the only reason this panel can say "this is a
 * result, not a failure to read" without lying.
 */
import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DiscoveryResults from './DiscoveryResults.jsx'

const render = (props) => renderToStaticMarkup(createElement(DiscoveryResults, {
  source: 'drive', inventory: { discovered: 0 }, invRows: [], policies: [], ...props,
})).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

const FILE = { file: 'a.docx', name: 'a.docx', status: 'analysed', issues: [] }

describe('a scan that found nothing', () => {
  it('says so, rather than leaving the reader to infer it from zeros', () => {
    const t = render({ files: [] })
    expect(t).toContain('NOTHING WAS FOUND')
    expect(t).toContain('This scan completed and found no files')
  })

  it('states that this is a result, not a failure to read', () => {
    // The distinction #1104 bought. Without it this sentence would be a guess.
    const t = render({ files: [] })
    expect(t).toContain('not a failure to read')
    expect(t).toContain('a folder ACP cannot open stops the scan and reports the error')
  })

  it('names the scope when one was applied, and the source when none was', () => {
    // "No files" and "no files matching what you asked for" send a user to different places.
    expect(render({ files: [], scopeLine: 'Folder: /Finance' }))
      .toContain('found no files in the scope you selected')
    expect(render({ files: [] })).toMatch(/found no files\./)
    expect(render({ files: [] })).toContain('folder or drive you pointed at')
  })

  it('drops the sentence about reading zero files', () => {
    // "Every one of the 0 files on this screen was read" is true of the empty set and answers a
    // question nobody asked. The panel above now says what actually happened.
    const t = render({ files: [] })
    expect(t, 'the absurd zero sentence is back').not.toContain('Every one of the 0 files')
    expect(t).toContain('No files were listed, so there was nothing to read')
  })

  it('announces itself politely rather than as an alert', () => {
    // An empty folder is a finding, not an error, and it is on screen from first paint — an
    // assertive region would interrupt a screen reader for something nothing went wrong in.
    const html = renderToStaticMarkup(createElement(DiscoveryResults, {
      source: 'drive', files: [], inventory: { discovered: 0 }, invRows: [], policies: [],
    }))
    expect(html).toMatch(/role="status"/)
    expect(html).not.toMatch(/role="alert"[^>]*>\s*<h2>NOTHING WAS FOUND/)
  })
})

describe('a scan that found something is unchanged', () => {
  it('shows no empty-estate panel', () => {
    const t = render({ files: [FILE], inventory: { discovered: 1 } })
    expect(t, 'the empty panel fired on a scan that found a file').not.toContain('NOTHING WAS FOUND')
  })

  it('keeps the original read-confirmation sentence', () => {
    const t = render({ files: [FILE], inventory: { discovered: 1 } })
    expect(t).toContain('was read. Nothing was skipped.')
  })
})

describe('the panel does not claim anything about a scan that never ran', () => {
  it('renders nothing at all when no files array was supplied', () => {
    // estateSummary returns null for a non-array, and DiscoveryResults returns null in turn —
    // "nothing was read, so nothing is claimed", which is a DIFFERENT state from "read, empty"
    // and must not acquire an empty-estate panel by accident.
    const html = renderToStaticMarkup(createElement(DiscoveryResults, {
      source: 'drive', files: null, inventory: null, invRows: [], policies: [],
    }))
    expect(html).toBe('')
  })
})
