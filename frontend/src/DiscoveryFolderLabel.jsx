import { useEffect, useState } from 'react'
import { getDriveFolderName } from './api.js'

export default function DiscoveryFolderLabel({ folder, source }) {
  const opaque = source === 'drive' && /^[A-Za-z0-9_-]{16,}$/.test(folder || '')
  const [resolved, setResolved] = useState(null)
  useEffect(() => {
    let current = true
    setResolved(null)
    if (opaque) getDriveFolderName(folder).then(data => {
      if (current) setResolved(data.name || 'Folder name unavailable')
    }).catch(() => { if (current) setResolved('Folder name unavailable') })
    return () => { current = false }
  }, [folder, opaque])
  return <span title={opaque ? `Drive folder ID: ${folder}` : folder}>{opaque ? resolved || 'Loading folder name…' : folder}</span>
}
