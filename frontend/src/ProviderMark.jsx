// A provider's logo, when we actually have its official asset, and an honest monogram
// when we do not. Never an approximated brand mark: a hand-drawn lookalike is both poor
// quality and a trademark question, and this panel's whole job is to be accurate about
// where content is sent.
//
// Drop an official SVG at frontend/src/assets/<provider>-logo.svg and it is picked up
// with no code change -- the glob is resolved at build time, so a missing file is simply
// absent from the map rather than a broken import. `sharepoint-logo.svg` already lives
// there and set the convention.
//
// The mark is decorative: aria-hidden, with the provider NAME rendered as real text by
// the caller. A logo is not an accessible name, and this is an accessibility product.
const LOGOS = import.meta.glob('./assets/*-logo.svg', { eager: true, query: '?url', import: 'default' })

export function providerKey(provider) {
  return String(provider || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

export function providerLogo(provider) {
  const key = providerKey(provider)
  return key ? LOGOS[`./assets/${key}-logo.svg`] || null : null
}

export function providerMonogram(provider) {
  const name = String(provider || '').trim()
  if (!name) return '?'
  // Two initials for a multi-word name, otherwise the first character.
  const words = name.split(/[\s._-]+/).filter(Boolean)
  return (words.length > 1 ? words[0][0] + words[1][0] : name[0]).toUpperCase()
}

export default function ProviderMark({ provider }) {
  const src = providerLogo(provider)
  if (src) return <img className="provider-mark" src={src} alt="" aria-hidden="true" />
  return <span className="provider-mark provider-mark--monogram" aria-hidden="true">{providerMonogram(provider)}</span>
}
