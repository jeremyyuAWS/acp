import { useCallback, useState } from 'react'
import FolderPicker from './FolderPicker.jsx'
import { listFolders, listSpFolders, putMyReleaseDestination } from './api.js'

const providerCopy = (provider) => provider === 'sharepoint'
  ? { name: 'SharePoint or OneDrive', root: 'Microsoft files' }
  : { name: 'Google Drive', root: 'My Drive' }

export default function ReleaseDestinationPicker({ provider, value, onChange, onError }) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const copy = providerCopy(provider)
  // Keep the lister stable between renders. FolderPicker uses it as the cache
  // key and as a dependency of its initial-load effect; recreating it here
  // causes the picker to reload on every parent update, which looks like a flash.
  const lister = useCallback((parent) => (
    provider === 'sharepoint' ? listSpFolders(parent) : listFolders(parent)
  ), [provider])

  const save = async (picked) => {
    const folder = picked[0]
    if (!folder || saving) return
    const destination = { provider, folder_id: folder.id, folder_name: folder.name }
    setSaving(true)
    try {
      await putMyReleaseDestination(destination)
      onChange?.(destination)
      setOpen(false)
    } catch (error) {
      onError?.(error)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="release-destination-picker">
      <div>
        <b>Parent folder</b>
        <span>{value?.folder_name || `Default “Remediated” folder in ${copy.name}`}</span>
      </div>
      <button type="button" className="ghost" onClick={() => setOpen(true)}>
        {value ? 'Change folder' : 'Choose folder'}
      </button>
      {open && <FolderPicker
        title={`Choose a Release folder in ${copy.name}`}
        sourceName={copy.name}
        rootName={copy.root}
        lister={lister}
        initial={value ? [{ id: value.folder_id, name: value.folder_name }] : []}
        onClose={() => setOpen(false)}
        onConfirm={save}
        requireSelection
        maxSelections={1}
        allowAll={false}
        confirmLabel={saving ? 'Saving…' : 'Use this folder'}
        showRecursionNote={false}
      />}
    </div>
  )
}
