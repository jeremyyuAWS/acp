import { useState, useEffect } from 'react'
import { getSettings, updateSettings } from './api.js'
import { SCOPE_UNIVERSE } from './scopePresets.js'
import { parseStoredScope } from './ScanScope.jsx'

const LS_KEY = 'mova_filetypes'
const LS_CUSTOM = 'mova_filetypes_custom'

const KNOWN = [
  { ext: 'pdf',   label: 'PDF documents',              note: 'Checked for tags, alt text, title, reading order' },
  { ext: 'docx',  label: 'Word documents (.docx)',      note: 'Alt text, table headers, document title, language, link purpose' },
  { ext: 'pptx',  label: 'PowerPoint (.pptx)',          note: 'Slide titles, alt text, reading order, language' },
  { ext: 'xlsx',  label: 'Excel spreadsheets (.xlsx)',  note: 'Table headers, sheet names, language' },
  { ext: 'html',  label: 'HTML / web pages',            note: 'Full axe-core WCAG 2.1 + 2.2 scan' },
  // ACP runs no transcription pipeline; 1.2.x findings are detected and routed to a human.
  { ext: 'video', label: 'Video (.mp4, .mov, .webm)',   note: 'caption + audio-description checks · human review' },
  { ext: 'audio', label: 'Audio (.mp3, .m4a, .wav)',    note: 'transcript check only — no visual output' },
]

const DEFAULTS = Object.fromEntries(KNOWN.map((k) => [k.ext, true]))

// The four formats the ENGINE can be scoped by. Toggling one of these writes the server's
// scan_scope setting, so it genuinely stops being assessed and remediated.
//
// Everything else here (html, video, audio, custom extensions) stays a local Discover view
// filter, because scan_scope has no axis for them — `_DOC_FORMATS` in gen_scope_presets.py
// excludes html deliberately ("this configures a DOCUMENT engagement") and never had
// video/audio at all. Those keep their old behaviour and the panel now says which is which,
// rather than claiming one behaviour for both.
const SCOPED_EXTS = new Set(['pdf', 'docx', 'pptx', 'xlsx'])

// Build the scan_scope map for a set of allowed formats, from the GENERATED universe rather
// than a list typed here — SCOPE_UNIVERSE is emitted from the backend's own tables with a CI
// drift guard, so this cannot offer or withhold a pair the engine does not have.
const scopeForFormats = (allowed) => {
  const out = {}
  for (const row of SCOPE_UNIVERSE) {
    const fmts = row.formats.filter((f) => allowed.has(f))
    if (fmts.length) out[row.sc] = fmts
  }
  return out
}

const loadConfig = () => { try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(LS_KEY) || '{}') } } catch { return { ...DEFAULTS } } }
const loadCustom = () => { try { return JSON.parse(localStorage.getItem(LS_CUSTOM) || '[]') } catch { return [] } }

export const loadFileTypeConfig = loadConfig
export const loadCustomExclusions = loadCustom

/** Write the four ENGINE-scoped formats into the stored view config, leaving everything else be.
 *
 * Exists so ScanSetup can keep the two stores in step. `scan_scope` (server) decides what is
 * ASSESSED; this localStorage config decides what Discover LISTS (Discover.jsx filters on
 * `fileTypeConfig[f.type] !== false`). ScanSetup wrote only the first, so unticking PDF on the
 * first screen scoped the assessment and left every PDF in the inventory — the same "two stores
 * for one fact" this panel's own comment records having already lied about once.
 *
 * MERGES rather than replaces, and that is the whole reason this is a function here instead of a
 * setItem at the call site: the stored config also covers html, video, audio and custom
 * extensions, which have no scan_scope axis and which ScanSetup never offers. Writing the four
 * it knows about as a whole object would silently discard preferences the user set in Settings.
 */
/** The files a given config lets through — the ONE place that decides, for every tab.
 *
 * Was an inline filter inside Discover, so the file-type choice applied to the inventory and to
 * nothing after it: Assess scored the excluded types, Remediate queued them, Overview counted
 * them, Publish certified against them. A filter that stops applying one tab later is worse than
 * none, because every downstream number then describes a different population than the screen
 * the operator set it on.
 *
 * An EMPTY config means no restriction, and a type ABSENT from the config is allowed — only an
 * explicit `false` excludes. That is the original `!== false` test, kept deliberately: custom
 * extensions and formats added later are not silently hidden by a config written before they
 * existed.
 */
export function visibleForFileTypes(files, cfg) {
  if (!cfg || !Object.keys(cfg).length) return files
  return files.filter((f) => cfg[f.type] !== false)
}

export function saveScopedFileTypes(allowed) {
  const next = { ...loadConfig() }
  for (const ext of SCOPED_EXTS) next[ext] = allowed.has(ext)
  try { localStorage.setItem(LS_KEY, JSON.stringify(next)) } catch { /* private mode: view-only */ }
  return next
}

// Settings panel — configure which file types the platform actively remediates.
// Types toggled off still appear in the Discover inventory (they're in the estate)
// but are excluded from automated remediation scoring and queuing.
export default function FileTypeConfig({ onChanged }) {
  const [config, setConfig] = useState(loadConfig)
  const [custom, setCustom] = useState(loadCustom)
  const [adding, setAdding] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  // Whether the platform currently restricts scope at all. Needed because turning a format OFF
  // from "no restriction" has to CREATE one, and that is a bigger change than it looks — see
  // the note rendered below.
  const [restricted, setRestricted] = useState(null)

  // The four scoped formats are read from the SERVER, never from localStorage. Two stores for
  // one fact is what made this panel lie in the first place: it claimed to exclude types from
  // remediation while only hiding rows in Discover, and nothing reconciled the two.
  useEffect(() => {
    let live = true
    getSettings().then((st) => {
      if (!live) return
      const parsed = parseStoredScope(st?.scan_scope || '')
      setRestricted(Boolean(parsed))
      if (!parsed) return                       // no restriction → every format is on
      const on = new Set()
      for (const fmts of Object.values(parsed)) for (const f of fmts) on.add(f)
      setConfig((c) => ({ ...c, ...Object.fromEntries([...SCOPED_EXTS].map((e) => [e, on.has(e)])) }))
    }).catch(() => { /* unreadable settings → leave the local view filter as-is */ })
    return () => { live = false }
  }, [])

  const toggle = async (ext) => {
    const next = { ...config, [ext]: !config[ext] }
    if (!SCOPED_EXTS.has(ext)) {
      // View-only types: unchanged behaviour, local storage, no server write.
      setConfig(next); localStorage.setItem(LS_KEY, JSON.stringify(next)); onChanged?.(next, custom)
      return
    }
    const allowed = new Set([...SCOPED_EXTS].filter((e) => next[e]))
    if (allowed.size === 0) {
      // `{}` means NO RESTRICTION on the backend, so saving an empty selection would assess
      // EVERYTHING while the panel showed every format off — the exact inversion ScanScope.jsx
      // refuses for the same reason. Refuse it here too rather than translate it.
      setMsg('At least one document format has to stay on. Switching them all off would be '
             + 'read as "no restriction" and assess every format.')
      return
    }
    setBusy(true); setMsg('')
    try {
      const res = await updateSettings({ scan_scope: scopeForFormats(allowed) })
      // Trust the SERVER's echo, not the request — SIM builds its response from the request, so
      // a request-shaped answer is the one thing that must never be read as a save (ScanScope).
      if (res?.simulated) {
        setMsg('SIM — nothing was written. This demo build has no backend.')
      } else {
        setConfig(next); setRestricted(true); onChanged?.(next, custom)
        setMsg(`✓ ${ext.toUpperCase()} ${next[ext] ? 'included in' : 'excluded from'} assessment.`)
      }
    } catch (e) {
      setMsg(`Could not save: ${e?.message || 'the platform rejected the change'}`)
    } finally { setBusy(false) }
  }

  const addExclusion = () => {
    const ext = adding.toLowerCase().replace(/^\.|,|\s/g, '').trim()
    if (!ext || custom.includes(ext)) { setAdding(''); return }
    const next = [...custom, ext]
    setCustom(next); localStorage.setItem(LS_CUSTOM, JSON.stringify(next))
    setAdding(''); onChanged?.(config, next)
  }

  const removeExclusion = (ext) => {
    const next = custom.filter((e) => e !== ext)
    setCustom(next); localStorage.setItem(LS_CUSTOM, JSON.stringify(next)); onChanged?.(config, next)
  }

  const disabledCount = KNOWN.filter((k) => !config[k.ext]).length + custom.length

  return (
    <div>
      <p className="muted" style={{ marginBottom: 14 }}>
        <b>PDF, Word, PowerPoint and Excel</b> are gated by the platform: switching one off writes
        the scan scope, so it stops being assessed and remediated everywhere — Discover, Assess,
        Remediate and Publish. That is a platform-wide setting, not a preference for this browser.
        {' '}<b>HTML, video, audio and custom extensions</b> only filter what Discover lists; the
        engine has no scope axis for them.
        {disabledCount > 0 && <b style={{ color: 'var(--warn-fg)', marginLeft: 6 }}>{disabledCount} type{disabledCount !== 1 ? 's' : ''} switched off.</b>}
        {restricted === false && (
          <span className="muted" style={{ display: 'block', marginTop: 6 }}>
            Nothing is restricted today. Switching a document format off creates an explicit
            scope listing every criterion this build knows about — after which a criterion added
            in a later release is not picked up automatically until the scope is revisited.
          </span>
        )}
        {msg && <span role="status" aria-live="polite" style={{ display: 'block', marginTop: 6,
                       color: msg.startsWith('✓') ? 'var(--success-fg)' : msg.startsWith('SIM') ? '#6B4A0B' : 'var(--error-fg-strong)' }}>{msg}</span>}
      </p>

      <table className="ruletable" style={{ width: '100%', marginBottom: 18 }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left', width: 40 }}>On</th>
            <th style={{ textAlign: 'left' }}>File type</th>
            <th style={{ textAlign: 'left' }}>What gets checked</th>
          </tr>
        </thead>
        <tbody>
          {KNOWN.map(({ ext, label, note }) => (
            <tr key={ext} style={!config[ext] ? { opacity: 0.5 } : undefined}>
              <td>
                <input
                  type="checkbox"
                  checked={!!config[ext]}
                  onChange={() => toggle(ext)}
                  /* Disabled while a scoped toggle is in flight: these now write a PLATFORM
                     setting, and two clicks racing would send two full scope maps whose order
                     of arrival decides the result. The view-only types never write, so the
                     guard costs them nothing. */
                  disabled={busy}
                  aria-label={SCOPED_EXTS.has(ext)
                    ? `Assess ${label} — writes the platform scan scope`
                    : `Show ${label} in the Discover inventory`}
                  style={{ cursor: 'pointer' }}
                />
              </td>
              <td style={{ fontWeight: 500, fontSize: 13 }}>{label}</td>
              <td className="muted" style={{ fontSize: 12 }}>{note}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ marginTop: 4 }}>
        <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 6 }}>Custom exclusions</div>
        <p className="muted" style={{ fontSize: 12, marginBottom: 8 }}>Add extensions that should never be queued for remediation (e.g. <code>psd</code>, <code>ai</code>, <code>indd</code>, <code>sketch</code>).</p>
        {custom.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
            {custom.map((ext) => (
              <span key={ext} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: '#f3f0f7', color: '#5b4a72', borderRadius: 4, padding: '2px 8px', fontSize: 12 }}>
                .{ext}
                <button
                  className="ghost small"
                  style={{ fontSize: 10, padding: '0 2px', minWidth: 0 }}
                  onClick={() => removeExclusion(ext)}
                  aria-label={`Remove .${ext} exclusion`}
                >✕</button>
              </span>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            type="text"
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addExclusion()}
            placeholder="psd"
            style={{ fontSize: 12, width: 90, padding: '4px 8px', border: '1px solid var(--line)', borderRadius: 4 }}
            aria-label="Extension to exclude"
          />
          <button className="ghost small" onClick={addExclusion} disabled={!adding.trim()}>+ Add</button>
        </div>
      </div>
    </div>
  )
}
