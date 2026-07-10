// The offending image itself, as captured server-side when the vision model looked at it
// (api/remediate_office.py::_thumb_b64 → "data:image/png;base64,…", max 96px on the long edge).
//
// This is NOT the document's page-1 render. api/render.py can only rasterize PDFs, so for a
// PPTX or DOCX this base64 blob is the only picture a reviewer can ever be shown — and the
// reviewer is being asked to write alt text for exactly this image.
//
// Only a PNG/JPEG/GIF/WEBP data URL is ever put in `src`. The value arrives from the database
// as JSON; anything else (a javascript: URL, a remote http: URL, junk) renders nothing rather
// than being handed to the browser.
const SAFE_DATA_URL = /^data:image\/(png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=]+$/

export const isSafeThumb = (thumb) => typeof thumb === 'string' && SAFE_DATA_URL.test(thumb)

export default function ProposalThumb({ thumb, alt = '', className = '', size = 96 }) {
  if (!isSafeThumb(thumb)) return null
  return (
    <img
      src={thumb}
      alt={alt}
      className={className}
      width={size}
      style={{ width: size, height: 'auto', maxHeight: size, objectFit: 'contain',
               borderRadius: 6, border: '1px solid var(--line)', display: 'block', flexShrink: 0 }}
    />
  )
}
