import { TAGS } from './sim.js'

export default function Tag({ t }) {
  const [bg, fg] = TAGS[t] || ['#F1EFE8', '#5F5E5A']
  return <span className="tag" style={{ background: bg, color: fg }}>{t}</span>
}
