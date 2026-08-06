// "How to confirm this fix took" — per WCAG criterion × app (Word/Excel/PowerPoint/Acrobat) ×
// platform (macOS / Windows). The HITL card shows thumbnails + the AI-suggested value + a
// before/after already; this is the missing third piece: exactly where a reviewer clicks in the
// native app to verify the fix landed.
//
// Honesty rule (matches the rest of the product): a wrong instruction is worse than none, so a
// (criterion, app) pair with no crisp, current native step returns null for its steps — the card
// then shows only the always-correct "re-run the Accessibility Checker" line. We never invent a
// menu path we're unsure of.

const APP_BY_EXT = { docx: 'Word', xlsx: 'Excel', pptx: 'PowerPoint', pdf: 'Acrobat' }

export function appFor(file) {
  const ext = String(file || '').split('.').pop().toLowerCase()
  return APP_BY_EXT[ext] || null
}

// The built-in accessibility checker — the universal fallback, shown on every card.
const CHECKER = {
  Word: { win: 'Review ▸ Check Accessibility', mac: 'Review ▸ Check Accessibility' },
  Excel: { win: 'Review ▸ Check Accessibility', mac: 'Review ▸ Check Accessibility' },
  PowerPoint: { win: 'Review ▸ Check Accessibility', mac: 'Review ▸ Check Accessibility' },
  Acrobat: {
    win: 'All tools ▸ Prepare for accessibility ▸ Check for accessibility (Full Check)',
    mac: 'All tools ▸ Prepare for accessibility ▸ Check for accessibility (Full Check)',
  },
}

// Office apps share these paths across Word/Excel/PowerPoint unless noted.
const officeAlt = {
  win: ['Right-click the image ▸ “Edit Alt Text…”', 'Confirm the Alt Text pane shows a real description (not blank, not a file name)'],
  mac: ['Right-click the image ▸ “Edit Alt Text…” (or Picture Format ▸ Alt Text)', 'Confirm the Alt Text pane shows a real description'],
}
const officeTitle = {
  win: ['File ▸ Info ▸ Properties ▸ Show All Properties', 'Confirm the “Title” field is filled in'],
  mac: ['File ▸ Properties ▸ Summary tab', 'Confirm the “Title” field is filled in'],
}

// STEPS[sc][app][platform] = string[]  (absent → only the checker line shows)
const STEPS = {
  '1.1.1': { Word: officeAlt, Excel: officeAlt, PowerPoint: officeAlt,
    Acrobat: { win: ['All tools ▸ Prepare for accessibility ▸ Set alternate text', 'Step through each figure; confirm none is left blank'],
               mac: ['All tools ▸ Prepare for accessibility ▸ Set alternate text', 'Step through each figure; confirm none is left blank'] } },
  '2.4.2': { Word: officeTitle, Excel: officeTitle, PowerPoint: officeTitle,
    Acrobat: { win: ['File ▸ Properties ▸ Description tab — confirm “Title” is set', 'File ▸ Properties ▸ Initial View ▸ Show: “Document Title”'],
               mac: ['File ▸ Properties ▸ Description tab — confirm “Title” is set', 'File ▸ Properties ▸ Initial View ▸ Show: “Document Title”'] } },
  '3.1.1': {
    Word: { win: ['Select all (Ctrl+A) ▸ Review ▸ Language ▸ Set Proofing Language', 'Confirm the language is set (e.g. English) and “Detect language automatically” is off'],
            mac: ['Select all (⌘A) ▸ Tools ▸ Language', 'Confirm the document language is set (e.g. English)'] },
    Acrobat: { win: ['File ▸ Properties ▸ Advanced ▸ Reading Options ▸ Language', 'Confirm a language is selected'],
               mac: ['File ▸ Properties ▸ Advanced ▸ Reading Options ▸ Language', 'Confirm a language is selected'] },
    // Excel/PowerPoint have no per-document language UI — fall through to the checker line.
  },
  '1.3.1': {
    Word: { win: ['Click the table ▸ Table Design ▸ tick “Header Row”', 'Confirm the top row is marked as the header and repeats on each page'],
            mac: ['Click the table ▸ Table Design ▸ tick “Header Row”', 'Confirm the top row is the header'] },
    Excel: { win: ['Click in the data ▸ Table Design ▸ tick “Header Row” (or Insert ▸ Table ▸ “My table has headers”)', 'Confirm the header row is styled and labelled'],
             mac: ['Click in the data ▸ Table Design ▸ tick “Header Row”', 'Confirm the header row is labelled'] },
    PowerPoint: { win: ['Click the table ▸ Table Design ▸ tick “Header Row”', 'Confirm the header row is marked'],
                  mac: ['Click the table ▸ Table Design ▸ tick “Header Row”', 'Confirm the header row is marked'] },
  },
  '2.4.6': {
    Word: { win: ['Home ▸ Styles — confirm section titles use Heading 1/2/3 styles', 'View ▸ Navigation Pane — confirm the outline has no skipped levels'],
            mac: ['Home ▸ Styles — confirm section titles use Heading 1/2/3', 'View ▸ Sidebar ▸ Navigation — confirm the outline has no gaps'] },
    PowerPoint: { win: ['View ▸ Outline View — confirm each slide has a real title', 'Or Home ▸ Arrange ▸ Selection Pane — confirm the Title placeholder is filled'],
                  mac: ['View ▸ Outline — confirm each slide has a title'] },
  },
  '1.3.2': {
    Excel: { win: ['Home ▸ Format ▸ Hide & Unhide ▸ Unhide Rows / Unhide Columns', 'Confirm no data-bearing rows or columns are hidden'],
             mac: ['Format ▸ Row/Column ▸ Unhide', 'Confirm no data-bearing rows or columns are hidden'] },
    PowerPoint: { win: ['Home ▸ Arrange ▸ Selection Pane — confirm no content shape is hidden (eye icon off)'],
                  mac: ['Arrange ▸ Selection Pane — confirm no content shape is hidden'] },
  },
  '3.3.2': {
    Word: { win: ['Developer ▸ (select each content control) ▸ Properties — confirm a Title/label is set', 'Or re-run the Accessibility Checker: it lists any unlabelled form fields'],
            mac: ['Re-run Review ▸ Check Accessibility — it lists any unlabelled form fields'] },
  },
  '2.4.1': {
    Acrobat: { win: ['View ▸ Show/Hide ▸ Side panels ▸ Bookmarks (or the Bookmarks icon)', 'Confirm a section outline is present and jumps to the right pages'],
               mac: ['Open the Bookmarks panel', 'Confirm a section outline is present'] },
  },
}

// Criteria where there is no crisp one-click native check (re-authoring / subjective) — the card
// shows only the checker line. Listed for intent; behaviourally identical to being absent.
// 1.3.3 sensory, 3.1.2 language-of-parts, 1.4.5 images-of-text, 3.1.5 reading level,
// 2.4.4/2.4.9 link purpose, 1.4.3/1.4.6 contrast (checker flags it but there's no toggle).

export function verifySteps(sc, file, platform = 'win') {
  const app = appFor(file)
  if (!app) return null
  const plat = platform === 'mac' ? 'mac' : 'win'
  const checker = (CHECKER[app] && CHECKER[app][plat]) || null
  const perSc = STEPS[sc] && STEPS[sc][app] && STEPS[sc][app][plat]
  if (!perSc && !checker) return null
  return { app, platform: plat, steps: perSc || null, checker }
}

// Best-effort default platform from the browser (the card lets the reviewer flip it).
export function defaultPlatform() {
  const p = (typeof navigator !== 'undefined' && (navigator.platform || navigator.userAgent) || '').toLowerCase()
  return p.includes('mac') ? 'mac' : 'win'
}
