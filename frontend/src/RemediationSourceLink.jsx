import { useEffect, useState } from 'react'
import { getSourceLink } from './api.js'

export default function RemediationSourceLink({ finding }) {
  const scanId = finding?.scanId || finding?._raw?.scan_id
  const file = finding?.file
  const [link, setLink] = useState(null)
  useEffect(() => {
    let current = true
    setLink(null)
    if (scanId && file) getSourceLink(scanId, file).then(link => {
      if (current && link?.url && /^https?:\/\//i.test(link.url)) setLink(link)
    }).catch(() => {})
    return () => { current = false }
  }, [scanId, file])
  return link ? <a className="ghost" href={link.url} target="_blank" rel="noopener noreferrer">Open source document</a> : null
}
