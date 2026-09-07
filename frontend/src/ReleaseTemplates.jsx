import { useState } from 'react'

const methodLabel = (method) => method === 'publish' ? 'Publish to provider'
  : method === 'download' ? 'Download package' : 'Keep in ACP'

export default function ReleaseTemplates({ templates = [], currentPlan, provider,
  onApply, onSave, onDelete, saving = false }) {
  const [name, setName] = useState('')
  const usable = (template) => !template.destination || template.destination.provider === provider
  const save = () => {
    const trimmed = name.trim()
    if (!trimmed || saving) return
    onSave?.({ ...currentPlan, name: trimmed })
    setName('')
  }
  return (
    <details className="release-templates">
      <summary>Saved delivery templates <span>{templates.length}</span></summary>
      <div className="release-templates__body">
        {templates.length === 0 ? <p className="muted">Save this delivery setup to reuse it on a future release.</p>
          : <ul>{templates.map((template) => <li key={template.name}>
            <div><b>{template.name}</b><span>{methodLabel(template.method)}{template.destination ? ` · ${template.destination.folder_name}` : ''}</span></div>
            <button type="button" className="ghost small" disabled={!usable(template) || saving}
                    title={usable(template) ? '' : `This template is for ${template.destination.provider}`}
                    onClick={() => onApply?.(template)}>Apply</button>
            <button type="button" className="linklike" disabled={saving}
                    aria-label={`Delete ${template.name}`} onClick={() => onDelete?.(template)}>Delete</button>
          </li>)}</ul>}
        <div className="release-templates__save">
          <label htmlFor="release-template-name">Template name</label>
          <input id="release-template-name" value={name} maxLength={80}
                 onChange={(event) => setName(event.target.value)} placeholder="For example, Finance ZIP" />
          <button type="button" className="ghost" disabled={!name.trim() || saving} onClick={save}>
            {saving ? 'Saving…' : 'Save current setup'}
          </button>
        </div>
      </div>
    </details>
  )
}
