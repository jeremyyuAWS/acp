// Native-app remediation instructions — "where to find each broken WCAG item and how to fix
// it by hand" in the document's own editor, on macOS and on Windows. Consumed by the Assess
// PDF report's Manual remediation checklist (scanReport.js > pdfReport.js).
//
// These are MANUAL menu paths a person follows in Word / Excel / PowerPoint / Acrobat — NOT
// the deterministic fixes ACP applies automatically. They exist so a reviewer (or the customer)
// can locate and fix an item ACP routed to a human, on whichever platform they use. The wording
// and shortcuts genuinely differ between Mac and Windows Office (e.g. "Edit Alt Text…" via the
// ribbon vs. right-click), so both are spelled out rather than assumed identical.
//
// Honesty: every entry is a real, current menu path. Where a criterion has no in-app control
// (it needs a content rewrite — images of text, sensory wording), the steps say so plainly
// rather than inventing a button.

const APP = { docx: 'Word', xlsx: 'Excel', pptx: 'PowerPoint', pdf: 'Acrobat Pro', html: 'your HTML editor' }
export const appName = (fmt) => APP[fmt] || 'the native application'

// Office apps share the built-in Accessibility Checker — the reliable generic locator on both OSes.
const OFFICE_CHECK = {
  mac: 'Review tab > Check Accessibility. Double-click a flagged item to jump to it, then use the fix in the Accessibility pane.',
  win: 'Review tab > Check Accessibility. Select a flagged item under “Inspection Results”, then apply the “Recommended Actions” shown.',
}
const ACROBAT_CHECK = {
  mac: 'Acrobat Pro > Tools > Accessibility > Accessibility Check (Full Check) locates issues; use Reading Order / Tags to fix.',
  win: 'Acrobat Pro > Tools > Accessibility > Accessibility Check (Full Check) locates issues; use Reading Order / Tags to fix.',
}
const genericFor = (fmt) => (fmt === 'pdf' ? ACROBAT_CHECK : OFFICE_CHECK)

// both: same text on Mac + Windows. Otherwise { mac, win }.
const both = (s) => ({ mac: s, win: s })

// G[sc] = { where: '<what/where the barrier is>', fmt: { <format>: {mac,win} } }
// A format missing from fmt falls back to genericFor(format).
const G = {
  '1.1.1': {
    where: 'Images, charts, logos and other objects with no text alternative (alt text).',
    fmt: {
      docx: both('Right-click the image or chart > Edit Alt Text… (or select it > Picture/Graphic Format tab > Alt Text). Write one plain sentence describing it; tick “Mark as decorative” only for pure decoration.'),
      xlsx: both('Right-click the chart or image > Edit Alt Text… (or select it > Shape/Graphic Format tab > Alt Text). Describe what the chart shows — its type and the point it makes.'),
      pptx: both('Right-click the picture, chart or shape > Edit Alt Text… (or Picture/Graphic Format > Alt Text). Describe each visual; mark background/decorative shapes as decorative.'),
      pdf: ACROBAT_CHECK,
    },
  },
  '1.3.1': {
    where: 'Structure that is only visual — tables without header rows, text sized to look like a heading instead of using a Heading style.',
    fmt: {
      docx: {
        mac: 'For tables: click in the table > Table Layout tab > tick Header Row, and Repeat Header Rows. For headings: select the text > Home > Styles > Heading 1/2/3 (not just bold/large).',
        win: 'For tables: click in the table > Table Design/Layout > tick Header Row, then Layout > Repeat Header Rows. For headings: Home > Styles gallery > Heading 1/2/3.',
      },
      xlsx: {
        mac: 'Select the data range > Insert > Table (⌘T) and keep “My table has headers”. Give each sheet a real header row; avoid blank rows/columns inside data.',
        win: 'Select the data range > Insert > Table (Ctrl+T) and keep “My table has headers”. Ensure one clear header row per table.',
      },
      pptx: both('Build slides from the built-in layouts (Home > Layout) so titles and content are real placeholders. For a table, click it > Table Design > tick Header Row.'),
      pdf: ACROBAT_CHECK,
    },
  },
  '1.3.2': {
    where: 'Reading order that does not match the visual order — floating objects, hidden rows, or shapes stacked out of sequence.',
    fmt: {
      pptx: {
        mac: 'Home > Arrange > Selection Pane. The reading order is bottom-to-top — reorder items so a screen reader follows the intended flow.',
        win: 'Home > Arrange > Selection Pane (or Review > Check Accessibility > Reading Order). Reorder so the sequence reads top-to-bottom as intended.',
      },
      xlsx: both('Right-click the row or column headers > Unhide to expose hidden content, or delete it if it is truly not needed. Keep content in a single logical order.'),
      pdf: {
        mac: 'Acrobat Pro > Tools > Accessibility > Reading Order > draw/renumber regions in the correct sequence.',
        win: 'Acrobat Pro > Tools > Accessibility > Reading Order (or Tags panel) > set the correct sequence.',
      },
    },
  },
  '1.3.3': {
    where: 'Instructions that rely only on shape, size, position or colour (“click the round button”, “see the box on the right”).',
    fmt: {
      docx: both('This is a wording fix, not a setting. Edit the sentence to add a non-visual cue — name the control or step (“select Submit”), not just its shape or location.'),
      pptx: both('Edit the text so it does not depend on shape/position/colour alone — add the label or order (“in step 3…”) so it makes sense read aloud.'),
      xlsx: both('Reword cell text/notes that point by colour or position (“the red cells”) to name the actual condition (“cells over budget”).'),
    },
  },
  '1.4.2': {
    where: 'Audio or video that plays automatically for more than 3 seconds with no way to pause it.',
    fmt: {
      pptx: {
        mac: 'Click the audio/video > Playback tab > set Start to “When Clicked in Sequence”, and untick “Play Across Slides” / loop.',
        win: 'Click the media > Playback tab > Start: “In Click Sequence” (not Automatically); untick Loop until Stopped.',
      },
    },
  },
  '1.4.3': {
    where: 'Text whose colour is too close to its background (below 4.5:1, or 3:1 for large text).',
    fmt: {
      docx: both('Select the low-contrast text > Home > Font Colour > pick a darker colour. Run Review > Check Accessibility, which flags “Hard-to-read text contrast”.'),
      xlsx: both('Select the cells > Home > Font Colour (and Fill Colour) > increase the difference. Avoid light-grey text on white; Review > Check Accessibility flags weak contrast.'),
      pptx: both('Select the text > Home > Font Colour > darken it against the slide/placeholder fill. Check with Review > Check Accessibility.'),
      pdf: ACROBAT_CHECK,
    },
  },
  '1.4.5': {
    where: 'Text baked into an image (screenshots of text, text inside a picture) instead of real, selectable text.',
    fmt: {
      docx: both('Replace the picture with live text: retype the wording into the document and delete the image. Keep images only for genuine logos/diagrams.'),
      pptx: both('Retype the words as a real text box and remove the image of text. Logos may stay but still need alt text.'),
      xlsx: both('Move the text out of the image into real cells; delete the picture of text.'),
    },
  },
  '1.4.6': {
    where: 'Text contrast below the enhanced AAA ratio (7:1, or 4.5:1 for large text).',
    fmt: {
      docx: both('Same as contrast: Home > Font Colour > choose a darker colour to reach the enhanced 7:1 ratio.'),
      xlsx: both('Home > Font Colour / Fill Colour > increase contrast to the enhanced 7:1 target.'),
      pptx: both('Home > Font Colour > darken text against its background to meet 7:1.'),
    },
  },
  '1.4.8': {
    where: 'Blocks of body text that are fully justified, which opens uneven “rivers” of white space.',
    fmt: {
      docx: {
        mac: 'Select the paragraphs > Home > Align Left (⌘L) instead of Justify.',
        win: 'Select the paragraphs > Home > Align Left (Ctrl+L) instead of Justify.',
      },
    },
  },
  '1.4.9': {
    where: 'Images of text used to convey information (no exception allowed at this AAA criterion).',
    fmt: {
      docx: both('Replace every image of text with real text and delete the image. Only logotypes are exempt.'),
      pptx: both('Retype the text as real text boxes; remove the images of text.'),
    },
  },
  '2.1.1': {
    where: 'Interactive content (embedded controls, macros, action buttons) that a keyboard user cannot reach.',
    fmt: {
      pptx: both('Review any embedded control or action button so it is reachable by Tab and triggered by Enter/Space; avoid interactions that require a mouse only. Complex cases need a design review.'),
    },
  },
  '2.4.1': {
    where: 'No way to skip repeated blocks / no document outline to navigate by.',
    fmt: {
      pdf: {
        mac: 'Acrobat Pro > add Bookmarks for each section (Bookmarks panel > New Bookmark) and ensure headings are tagged so assistive tech can jump between them.',
        win: 'Acrobat Pro > Bookmarks panel > New Bookmark per section; confirm heading tags exist in the Tags panel.',
      },
    },
  },
  '2.4.2': {
    where: 'The document has no descriptive title in its properties (assistive tech announces the filename instead).',
    fmt: {
      docx: {
        mac: 'File > Properties > Summary tab > fill in Title. (Or File > Info on newer builds.)',
        win: 'File > Info > Properties > Title (click “Add a title”). Type a meaningful document title.',
      },
      xlsx: {
        mac: 'File > Properties > Summary tab > Title.',
        win: 'File > Info > Properties > Title.',
      },
      pptx: {
        mac: 'File > Properties > Summary tab > Title. Also give each slide a title (Home > Layout with a Title placeholder, or Outline view).',
        win: 'File > Info > Properties > Title. Ensure each slide has a title in its placeholder / Outline view.',
      },
      pdf: {
        mac: 'Acrobat Pro > File > Properties > Description > Title; then Initial View > Show: “Document Title”.',
        win: 'Acrobat Pro > File > Properties > Description > Title; Initial View tab > Show: Document Title.',
      },
    },
  },
  '2.4.4': {
    where: 'Links whose text does not say where they go (“click here”, “read more”, or a raw URL).',
    fmt: {
      docx: {
        mac: 'Right-click the link > Edit Hyperlink (⌘K) > change “Text to Display” to describe the destination.',
        win: 'Right-click the link > Edit Hyperlink (Ctrl+K) > set “Text to display” to a meaningful phrase.',
      },
      pptx: {
        mac: 'Right-click the link > Edit Hyperlink (⌘K) > set “Text to Display” to describe the target.',
        win: 'Right-click the link > Edit Hyperlink (Ctrl+K) > set “Text to display”.',
      },
    },
  },
  '2.4.6': {
    where: 'Missing or unhelpful headings and labels — content with no heading structure to scan.',
    fmt: {
      docx: both('Apply real heading styles: select each heading > Home > Styles > Heading 1/2/3 in outline order. Use the Navigation Pane to check the structure.'),
      pptx: both('Give every slide a clear, unique title in its Title placeholder (Outline view makes gaps obvious).'),
    },
  },
  '2.4.9': {
    where: 'A link’s text alone does not describe its purpose (fails even without surrounding context).',
    fmt: {
      docx: {
        mac: 'Right-click the link > Edit Hyperlink (⌘K) > make “Text to Display” self-describing on its own.',
        win: 'Right-click the link > Edit Hyperlink (Ctrl+K) > make the link text meaningful by itself.',
      },
      pptx: both('Edit the hyperlink’s display text (right-click > Edit Hyperlink) so it makes sense read out of context.'),
    },
  },
  '2.4.10': {
    where: 'Long content with no section headings to break it up.',
    fmt: {
      docx: both('Add Heading 2/3 styles at each section start (Home > Styles). Confirm the outline in the Navigation Pane (View > Navigation Pane).'),
    },
  },
  '3.1.1': {
    where: 'The document’s default language is not set, so screen readers may use the wrong pronunciation.',
    fmt: {
      docx: {
        mac: 'Tools > Language > pick the document language and Set As Default (or Review > Language).',
        win: 'Review > Language > Set Proofing Language > choose the language > Set As Default.',
      },
      xlsx: {
        mac: 'Excel > Preferences > Edit/Language, or Review > Language, to set the editing language.',
        win: 'Review > Language > Language Preferences > set the editing/display language.',
      },
      pptx: {
        mac: 'Review > Language > set the language (select all slides first to apply throughout).',
        win: 'Review > Language > Set Proofing Language > Set As Default.',
      },
      pdf: {
        mac: 'Acrobat Pro > File > Properties > Advanced > Reading Options > Language.',
        win: 'Acrobat Pro > File > Properties > Advanced > Reading Options > Language.',
      },
    },
  },
  '3.1.2': {
    where: 'Passages in another language are not marked, so they are read with the wrong voice.',
    fmt: {
      docx: {
        mac: 'Select the foreign-language text > Tools > Language (or Review > Language) > set that passage’s language (do not tick “default”).',
        win: 'Select the passage > Review > Language > Set Proofing Language > choose its language for that selection only.',
      },
      pptx: both('Select the foreign-language text > Review > Language > set the language for just that selection.'),
    },
  },
  '3.1.5': {
    where: 'Text that reads well above the expected reading level (long sentences, dense wording).',
    fmt: {
      docx: both('This is an editing task: shorten sentences and simplify wording. Word’s Editor (Review > Editor) reports readability to guide it.'),
    },
  },
  '3.3.2': {
    where: 'Form fields with no visible label or instructions.',
    fmt: {
      docx: both('Add a visible label next to each form field, and set the field’s help/tooltip (Developer tab > field Properties). Keep labels adjacent to their field.'),
    },
  },
  '4.1.2': {
    where: 'Interactive controls with no accessible name/role (form fields, buttons).',
    fmt: {
      docx: both('Give each form control a name and status text via the Developer tab > Properties. Run Review > Check Accessibility to find unnamed controls.'),
    },
  },
}

// Look up the fix steps for a criterion in a specific format. Always returns {where, mac, win}
// — falling back to the app's Accessibility Checker when we have no criterion-specific path.
export function fixSteps(sc, fmt) {
  const e = G[sc]
  const gen = genericFor(fmt)
  if (!e) return { where: '', mac: gen.mac, win: gen.win }
  const f = e.fmt[fmt] || gen
  return { where: e.where || '', mac: f.mac, win: f.win }
}

// True when we have a criterion-specific entry (used only to order the checklist so the
// most actionable rows come first; unknown criteria still render with the generic checker path).
export const hasGuidance = (sc) => !!G[sc]

export default G
