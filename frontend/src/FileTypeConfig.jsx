import { useState } from 'react'

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

const loadConfig = () => { try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(LS_KEY) || '{}') } } catch { return { ...DEFAULTS } } }
const loadCustom = () => { try { return JSON.parse(localStorage.getItem(LS_CUSTOM) || '[]') } catch { return [] } }

export const loadFileTypeConfig = loadConfig
export const loadCustomExclusions = loadCustom

// Settings panel — configure which file types the platform actively remediates.
// Types toggled off still appear in the Discover inventory (they're in the estate)
// but are excluded from automated remediation scoring and queuing.
export default function FileTypeConfig({ onChanged }) {
  const [config, setConfig] = useState(loadConfig)
  const [custom, setCustom] = useState(loadCustom)
  const [adding, setAdding] = useState('')

  const toggle = (ext) => {
    const next = { ...config, [ext]: !config[ext] }
    setConfig(next); localStorage.setItem(LS_KEY, JSON.stringify(next)); onChanged?.(next, custom)
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
        Toggle which file types the platform remediates. Types left on still appear in the estate inventory — toggling off only removes them from the remediation queue and scoring.
        {disabledCount > 0 && <b style={{ color: '#854F0B', marginLeft: 6 }}>{disabledCount} type{disabledCount !== 1 ? 's' : ''} excluded from remediation.</b>}
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
                  aria-label={`Include ${label} in remediation`}
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
