/** The published-copy location stays visible outside optional evidence panels. */
export default function ReleaseCopyDestination({ provider, destination, folder, folders = [], folderName = '' }) {
  if (!['sharepoint', 'drive'].includes(provider)) return null
  const product = provider === 'sharepoint' ? 'SharePoint' : 'Google Drive'
  const parent = destination?.folder_name || (provider === 'sharepoint' ? 'Source document library' : 'Drive root')
  const name = folder?.name || folderName.trim()
  const links = folders.length ? folders : folder?.url ? [folder] : []
  return <section aria-label="Published copy destination" style={{ marginTop: 14, padding: 14, border: '1px solid var(--line)', borderRadius: 10 }}>
    <b>Where your published documents will be saved</b>
    <p style={{ margin: '6px 0', overflowWrap: 'anywhere' }}>{product} / {parent} / Remediated / <b>{name || 'Release date and time'}</b></p>
    <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
      {name ? 'This release uses the folder shown above.' : 'ACP creates a timestamped subfolder when you release the documents.'}
      {' '}Corrected copies are saved there; original documents stay unchanged.
    </p>
    {links.filter(item => item.url).map((item, index) => <p key={item.id || item.url} style={{ margin: '8px 0 0' }}>
      <a href={item.url} target="_blank" rel="noopener noreferrer">Open published folder{links.length > 1 ? ` ${index + 1}` : ''} in {product} ↗</a>
    </p>)}
  </section>
}
