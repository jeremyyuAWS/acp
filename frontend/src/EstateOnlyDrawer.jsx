import Drawer from './Drawer.jsx'

const fmtSize = (kb) => {
  if (kb == null) return null
  if (kb < 1024) return `${Math.round(kb)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}

// A minimal detail view for a file discovery listed but ACP never opened — an image, a video, or
// an unsupported format. FileDrawer assumes a real assessment record (rules, remediation state,
// evidence, a rescan history) that never existed for these; opening it on an estate-only row would
// either show it empty or, worse, run its document-remediation affordances against a file with no
// backing scan. This shows only what discovery actually read (ADR 0020: metadata, never content)
// and says plainly why there is nothing more to show.
export default function EstateOnlyDrawer({ file, onClose }) {
  return (
    <Drawer title={file.file} subtitle="Listed by discovery — not opened" onClose={onClose}>
      <p className="muted" style={{ fontSize: 13, lineHeight: 1.55, margin: '10px 0 16px' }}>
        This format carries no WCAG test, so ACP never opened it — discovery only read its name,
        size and dates. It is counted in the estate composition so the estate reads honestly, not
        because there is a finding behind it.
      </p>
      {(file._sizeKb != null || file._owner) && (
        <dl style={{ display: 'grid', gridTemplateColumns: '70px 1fr', rowGap: 8, fontSize: 13, margin: 0 }}>
          {file.type && <><dt className="muted">Type</dt><dd style={{ margin: 0 }}>{file.type}</dd></>}
          {file._sizeKb != null && <><dt className="muted">Size</dt><dd style={{ margin: 0 }}>{fmtSize(file._sizeKb)}</dd></>}
          {file._owner && <><dt className="muted">Owner</dt><dd style={{ margin: 0 }}>{file._owner}</dd></>}
        </dl>
      )}
    </Drawer>
  )
}
